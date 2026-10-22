import copy
import http.client
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from training_studio import resources
from training_studio.service import StudioService
from training_studio.server import create_server


class ResourceInterfaceTests(unittest.TestCase):
    def test_service_exposes_separate_resource_snapshot(self):
        self.assertTrue(callable(getattr(StudioService, 'resources', None)))

    def test_resources_api_preserves_auth_and_origin_checks(self):
        service = mock.Mock()
        service.resources.return_value = {'status': 'pending'}
        server = create_server(service, port=0, token='local-test')
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for headers, expected in (({}, 401), ({'X-Studio-Token': 'local-test', 'Origin': 'https://example.com'}, 403),
                                      ({'X-Studio-Token': 'local-test'}, 200)):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                connection.request('GET', '/api/resources', headers=headers)
                response = connection.getresponse(); body = response.read(); connection.close()
                self.assertEqual(response.status, expected)
                if expected == 200:
                    self.assertEqual(json.loads(body), {'status': 'pending'})
            service.resources.assert_called_once_with()
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=1)


class NvidiaTests(unittest.TestCase):
    def test_multiple_devices_and_quoted_names(self):
        devices, errors = resources.parse_nvidia_csv('0, "GPU, One", 34, 55, 1024, 8192\n1, GPU Two, 0, 40, 0, 4096\n')
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]['name'], 'GPU, One')
        self.assertEqual(devices[0]['memory_used_mib'], 1024)
        self.assertEqual(devices[1]['utilization_pct'], 0)
        self.assertEqual(errors, [])

    def test_unavailable_nonfinite_and_invalid_values_are_null(self):
        devices, errors = resources.parse_nvidia_csv('0, GPU, N/A, [Not Supported], nan, 8192\n1, GPU2, 101, inf, 9000, 1000\nmalformed\n')
        self.assertIsNone(devices[0]['utilization_pct'])
        self.assertIsNone(devices[0]['temperature_c'])
        self.assertIsNone(devices[0]['memory_used_mib'])
        self.assertIsNone(devices[1]['utilization_pct'])
        self.assertIsNone(devices[1]['temperature_c'])
        self.assertIsNone(devices[1]['memory_used_mib'])
        self.assertTrue(devices[0]['unavailable_reasons'])
        self.assertTrue(errors)
        json.dumps(devices, allow_nan=False)

    def test_bounded_timeout_or_driver_failure_never_returns_fake_gpu(self):
        for failure in (subprocess.TimeoutExpired('nvidia-smi', 2), OSError('missing')):
            with self.subTest(failure=failure), mock.patch.object(resources.shutil, 'which', return_value='nvidia-smi'):
                runner = mock.Mock(side_effect=failure)
                sampler = resources.ResourceSampler(system='Other', run=runner)
                result = sampler()
                self.assertEqual(result['gpus'], [])
                self.assertTrue(result['gpu_reason'])
                self.assertLessEqual(runner.call_args.kwargs['timeout'], 2)
                self.assertFalse(runner.call_args.kwargs.get('shell', False))

    def test_empty_output_and_nonzero_exit_have_distinct_unavailable_reason(self):
        for code, output in ((0, ''), (1, '0, stale GPU, 99, 90, 8000, 9000')):
            with self.subTest(code=code), mock.patch.object(resources.shutil, 'which', return_value='nvidia-smi'):
                sampler = resources.ResourceSampler(system='Other', run=mock.Mock(
                    return_value=subprocess.CompletedProcess([], code, output, 'driver error')))
                result = sampler()
                self.assertEqual(result['gpus'], [])
                self.assertTrue(result['gpu_reason'])


class LinuxResourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.proc = self.root / 'proc'; self.proc.mkdir()
        self.sys = self.root / 'sys'; self.sys.mkdir()
        (self.proc / 'cpuinfo').write_text('processor : 0\nmodel name : Example CPU\n')
        (self.proc / 'stat').write_text('cpu 100 0 100 800 0 0 0 0 30 0\n')
        (self.proc / 'meminfo').write_text('MemTotal: 8000 kB\nMemAvailable: 3000 kB\n')
        (self.proc / 'sys/kernel').mkdir(parents=True)
        (self.proc / 'sys/kernel/osrelease').write_text('6.1.0-test')
        self.runner = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))

    def sampler(self):
        return resources.ResourceSampler(system='Linux', proc_root=self.proc, sys_root=self.sys, run=self.runner)

    def test_cpu_delta_excludes_guest_double_count_and_ram_uses_available(self):
        sampler = self.sampler()
        with mock.patch.object(resources.shutil, 'which', return_value='nvidia-smi'):
            first = sampler()
            self.assertIsNone(first['cpu']['utilization_pct'])
            self.assertTrue(first['cpu']['utilization_reason'])
            (self.proc / 'stat').write_text('cpu 130 0 120 850 0 0 0 0 50 0\n')
            second = sampler()
        self.assertEqual(second['cpu']['model'], 'Example CPU')
        self.assertEqual(second['cpu']['utilization_pct'], 50)
        self.assertEqual(second['memory']['total_bytes'], 8000 * 1024)
        self.assertEqual(second['memory']['used_bytes'], 5000 * 1024)

    def test_wsl_cpu_temperature_is_null_with_reason(self):
        (self.proc / 'sys/kernel/osrelease').write_text('6.6.87.2-microsoft-standard-WSL2')
        result = self.sampler()()
        self.assertTrue(result['is_wsl'])
        self.assertIsNone(result['cpu']['temperature_c'])
        self.assertIn('WSL', result['cpu']['temperature_reason'])
        self.assertIn('WSL', result['scope_note'])

    def test_temperature_uses_identified_cpu_sensor_not_gpu_or_acpi(self):
        for number, name, value in ((0, 'amdgpu', '85000'), (1, 'coretemp', '58000')):
            sensor = self.sys / f'class/hwmon/hwmon{number}'
            sensor.mkdir(parents=True)
            (sensor / 'name').write_text(name)
            (sensor / 'temp1_input').write_text(value)
        self.assertEqual(self.sampler()()['cpu']['temperature_c'], 58)

    def test_missing_memory_available_never_claims_free_equals_available(self):
        (self.proc / 'meminfo').write_text('MemTotal: 8000 kB\nMemFree: 1000 kB\n')
        result = self.sampler()()
        self.assertIsNone(result['memory']['used_bytes'])
        self.assertTrue(result['memory']['reason'])

    def test_missing_files_and_cpu_counter_reset_do_not_invent_zero_usage(self):
        sampler = self.sampler(); sampler()
        (self.proc / 'stat').write_text('cpu 1 0 1 8 0 0 0 0\n')
        (self.proc / 'meminfo').unlink()
        result = sampler()
        self.assertIsNone(result['cpu']['utilization_pct'])
        self.assertIsNone(result['memory']['total_bytes'])
        self.assertTrue(result['errors'])


class MonitorTests(unittest.TestCase):
    def test_lazy_first_snapshot_is_pending_nonblocking_and_cached(self):
        entered, release = threading.Event(), threading.Event()
        sample = resources.empty_snapshot('demo', system='Other')
        sample['cpu']['model'] = 'Observed CPU'
        def probe():
            entered.set(); release.wait(2); return copy.deepcopy(sample)
        sampler = mock.Mock(side_effect=probe)
        monitor = resources.ResourceMonitor(mode='demo', sampler=sampler)
        self.addCleanup(monitor.close); self.addCleanup(release.set)
        self.assertIsNone(monitor._thread)
        before = time.monotonic(); initial = monitor.snapshot()
        self.assertLess(time.monotonic() - before, .2)
        self.assertEqual(initial['status'], 'pending')
        self.assertTrue(entered.wait(.5))
        again = monitor.snapshot()
        self.assertEqual(again['sampled_at'], None)
        self.assertEqual(sampler.call_count, 1)
        release.set()
        deadline = time.monotonic() + 1
        while monitor.snapshot()['sampled_at'] is None and time.monotonic() < deadline:
            time.sleep(.005)
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot['cpu']['model'], 'Observed CPU')
        self.assertEqual(snapshot['mode'], 'demo')
        snapshot['cpu']['model'] = 'Mutated'
        self.assertEqual(monitor.snapshot()['cpu']['model'], 'Observed CPU')
        self.assertEqual(sampler.call_count, 1)

    def test_old_cached_sample_marked_stale_and_close_prevents_restart(self):
        clock = mock.Mock(return_value=100)
        monitor = resources.ResourceMonitor(sampler=lambda: resources.empty_snapshot('real'), clock=clock)
        self.addCleanup(monitor.close)
        monitor.snapshot()
        deadline = time.monotonic() + 1
        while monitor.snapshot()['sampled_at'] is None and time.monotonic() < deadline:
            time.sleep(.005)
        clock.return_value = 120
        self.assertTrue(monitor.snapshot()['stale'])
        monitor.close()
        self.assertFalse(monitor._thread.is_alive())
        self.assertTrue(monitor.snapshot()['stale'])
        self.assertFalse(monitor._thread.is_alive())

    def test_unexpected_probe_error_is_visible_and_keeps_worker_controlled(self):
        monitor = resources.ResourceMonitor(sampler=mock.Mock(side_effect=RuntimeError('bad probe')))
        self.addCleanup(monitor.close); monitor.snapshot()
        deadline = time.monotonic() + 1
        while not monitor.snapshot()['errors'] and time.monotonic() < deadline:
            time.sleep(.005)
        result = monitor.snapshot()
        self.assertEqual(result['status'], 'unavailable')
        self.assertTrue(result['stale'])
        self.assertTrue(result['errors'])

    def test_service_state_does_not_start_sampler_resources_and_shutdown_do(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch('training_studio.service.ResourceMonitor') as cls:
            service = StudioService(Path(folder) / 'state', Path(folder) / 'engine', demo=True)
            service.state()
            cls.return_value.snapshot.assert_not_called()
            service.resources()
            cls.return_value.snapshot.assert_called_once_with()
            service.shutdown()
            cls.return_value.close.assert_called_once_with()

    def test_resource_read_does_not_wait_for_training_lock(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch('training_studio.service.ResourceMonitor') as cls:
            service = StudioService(Path(folder) / 'state', Path(folder) / 'engine', demo=True)
            done = threading.Event()
            try:
                with service._condition:
                    reader = threading.Thread(target=lambda: (service.resources(), done.set()))
                    reader.start()
                    self.assertTrue(done.wait(.5), 'resource HTTP reads must not acquire training lock')
                reader.join(timeout=1)
                cls.return_value.snapshot.assert_called_once_with()
            finally:
                service.shutdown()


if __name__ == '__main__':
    unittest.main()
