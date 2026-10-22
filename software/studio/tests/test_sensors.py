"""Camera configuration and bounded, read-only snapshots from a local fake tofd."""
import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


def frame(**overrides):
    result = {"seq": 41, "at_us": 100000, "t_ns": 0, "rows": 8, "cols": 8,
              "distance_mm": [1200] * 64, "status": [5] * 64}
    result.update(overrides)
    return result


class FakeTofd:
    """Same subscriber protocol as firmware/tof/src/main.rs; no hello method."""

    def __init__(self, frames=None, metadata=None):
        self.frames = [frame()] if frames is None else frames
        self.metadata = {"accepted": True, "sensor": "VL53L8CX", "rows": 8, "cols": 8, "hz": 15}
        if metadata:
            self.metadata.update(metadata)
        self.requests = []
        self.connections = 0
        self.closed = asyncio.Event()
        self.requested = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.tasks = set()
        self.raw = None
        self.disconnect = False
        self.error = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        return f"tcp:127.0.0.1:{port}"

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections += 1
        try:
            request = json.loads(await reader.readline())
            self.requests.append(request)
            self.requested.set()
            await self.release.wait()
            response = {"jsonrpc": "2.0", "id": request["id"], "result": self.metadata}
            if self.error is not None:
                response.pop("result")
                response["error"] = self.error
            writer.write((json.dumps(response) + "\n").encode())
            if self.raw is not None:
                writer.write(self.raw)
            else:
                for data in self.frames:
                    writer.write((json.dumps({"jsonrpc": "2.0", "method": "tof.frame", "params": data}) + "\n").encode())
            await writer.drain()
            if self.disconnect:
                return
            await reader.read()
            self.closed.set()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.2)
            except (TimeoutError, ConnectionError, OSError):
                writer.transport.abort()
            self.tasks.discard(task)

    async def stop(self):
        self.server.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.server.wait_closed()


class FakeMediad:
    """Local hello endpoint; record every request through client EOF."""

    def __init__(self):
        self.response = {"jsonrpc": "2.0", "id": 1,
                         "result": {"api_version": 40, "daemon_version": "0.1.0", "revision": None}}
        self.raw = None
        self.requests = []
        self.connections = 0
        self.requested = asyncio.Event()
        self.closed = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.tasks = set()

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return f"tcp:127.0.0.1:{self.server.sockets[0].getsockname()[1]}"

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.connections += 1
        try:
            self.requests.append(json.loads(await reader.readline()))
            self.requested.set()
            await self.release.wait()
            raw = self.raw if self.raw is not None else (json.dumps(self.response) + "\n").encode()
            writer.write(raw)
            await writer.drain()
            while line := await reader.readline():
                self.requests.append(json.loads(line))
            self.closed.set()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), 0.2)
            except (TimeoutError, ConnectionError, OSError):
                writer.transport.abort()
            self.tasks.discard(task)

    async def stop(self):
        self.server.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.server.wait_closed()


class SensorsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = self.root / "etc" / "robot" / "robotd.toml"
        self.config.parent.mkdir(parents=True)
        self.servers = []

    async def asyncTearDown(self):
        for fake in self.servers:
            await fake.stop()
        self.tmp.cleanup()

    def sensors(self, **kwargs):
        self.assertIsNotNone(importlib.util.find_spec("studio.sensors"), "sensor backend must exist")
        module = importlib.import_module("studio.sensors")
        return module.Sensors(root=self.root, **kwargs)

    async def fake(self, **kwargs):
        fake = FakeTofd(**kwargs)
        addr = await fake.start()
        self.servers.append(fake)
        return fake, self.sensors(tof_addr=addr)

    async def fake_camera(self):
        fake = FakeMediad()
        addr = await fake.start()
        self.servers.append(fake)
        return fake, self.sensors(camera_addr=addr)

    async def test_camera_unavailable_unix_support_is_unknown(self):
        with mock.patch.object(asyncio, "open_unix_connection", None, create=True):
            result = await self.sensors().camera()
        self.assertEqual(result.get("service_state"), "unknown")
        self.assertIn("tcp:", result["service_reason"])

    async def test_camera_hello_reports_service_online_without_verifying_camera(self):
        self.config.write_text('[media]\nsource = "camera"\n', encoding="utf-8")
        before = self.config.read_bytes()
        fake, sensors = await self.fake_camera()
        result = await sensors.camera()
        self.assertEqual(result["service_state"], "online")
        self.assertIsNone(result["service_reason"])
        self.assertEqual(result["source"], "camera")
        self.assertIs(result["source_verified"], False)
        self.assertEqual(self.config.read_bytes(), before)
        await asyncio.wait_for(fake.closed.wait(), 0.5)
        self.assertEqual(fake.requests, [{"jsonrpc": "2.0", "id": 1, "method": "hello", "params": {}}])

    async def test_camera_missing_config_still_checks_service_and_keeps_unknown_source(self):
        fake, sensors = await self.fake_camera()
        result = await sensors.camera()
        self.assertEqual(result["service_state"], "online")
        self.assertEqual(result["source"], "unknown")
        self.assertFalse(result["source_verified"])
        self.assertTrue(result["error"])
        self.assertFalse(self.config.exists())
        self.assertEqual(len(fake.requests), 1)

    async def test_camera_each_status_read_uses_a_fresh_hello(self):
        fake, sensors = await self.fake_camera()
        self.assertEqual((await sensors.camera())["service_state"], "online")
        fake.response = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no hello"}}
        result = await sensors.camera()
        self.assertEqual(result["service_state"], "offline")
        self.assertIn("no hello", result["service_reason"])
        self.assertEqual(fake.connections, 2)

    async def test_camera_requires_a_valid_positive_integer_hello_api_version(self):
        responses = [
            {"jsonrpc": "2.0", "id": 1, "result": result}
            for result in ({}, [], None, {"api_version": 0}, {"api_version": -1},
                           {"api_version": True}, {"api_version": 40.0}, {"api_version": "40"})
        ] + [
            {"jsonrpc": "2.0", "id": True, "result": {"api_version": 40}},
            {"jsonrpc": "2.0", "id": "1", "result": {"api_version": 40}},
            {"jsonrpc": "2.0", "id": 2, "result": {"api_version": 40}},
            {"jsonrpc": "1.0", "id": 1, "result": {"api_version": 40}},
            {"jsonrpc": "2.0", "id": 1, "method": "media.frame", "result": {"api_version": 40}},
            {"jsonrpc": "2.0", "id": 1, "result": {"api_version": 40}, "error": {}},
        ]
        for response in responses:
            with self.subTest(response=response):
                fake, sensors = await self.fake_camera()
                fake.response = response
                result = await sensors.camera()
                self.assertEqual(result["service_state"], "offline")
                self.assertTrue(result["service_reason"])
                self.assertFalse(result["source_verified"])
                await asyncio.wait_for(fake.closed.wait(), 0.5)

    async def test_camera_rejects_bad_json_nonfinite_values_and_oversized_lines(self):
        for raw in (b"garbage\n", b"[1,2,3]\n", b"\xff\n", b"x" * (64 * 1024 + 1),
                    b'{"jsonrpc":"2.0","id":1,"result":{"api_version":NaN}}\n',
                    b'{"jsonrpc":"2.0","id":1,"result":{"api_version":40,"extra":Infinity}}\n'):
            with self.subTest(raw=raw[:60]):
                fake, sensors = await self.fake_camera()
                fake.raw = raw
                result = await sensors.camera()
                self.assertEqual(result["service_state"], "offline")
                self.assertTrue(result["service_reason"])
                await asyncio.wait_for(fake.closed.wait(), 0.5)

    async def test_camera_disabled_is_unknown_and_does_not_open_a_socket(self):
        with mock.patch("studio.sensors.asyncio.open_connection", side_effect=AssertionError("disabled")), \
                mock.patch.object(asyncio, "open_unix_connection", side_effect=AssertionError("disabled"), create=True):
            result = await self.sensors(camera_addr="none").camera()
        self.assertEqual(result["service_state"], "unknown")
        self.assertIn("未配置", result["service_reason"])

    async def test_camera_refused_or_missing_service_is_offline(self):
        fake, sensors = await self.fake_camera()
        await fake.stop()
        self.servers.remove(fake)
        result = await sensors.camera()
        self.assertEqual(result["service_state"], "offline")
        self.assertTrue(result["service_reason"])
        with mock.patch.object(asyncio, "open_unix_connection", mock.AsyncMock(side_effect=FileNotFoundError), create=True):
            result = await self.sensors().camera()
        self.assertEqual(result["service_state"], "offline")

    async def test_camera_total_deadline_and_cancellation_close_the_probe(self):
        fake, sensors = await self.fake_camera()
        fake.release.clear()
        with mock.patch("studio.sensors.CAMERA_TIMEOUT_S", 0.05):
            started = asyncio.get_running_loop().time()
            result = await sensors.camera()
            elapsed = asyncio.get_running_loop().time() - started
        self.assertLess(elapsed, 0.25)
        self.assertEqual(result["service_state"], "offline")
        fake.release.set()
        await asyncio.wait_for(fake.closed.wait(), 0.5)
        fake.closed.clear()
        fake.requested.clear()
        fake.release.clear()
        task = asyncio.create_task(sensors.camera())
        await asyncio.wait_for(fake.requested.wait(), 0.5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        fake.release.set()
        await asyncio.wait_for(fake.closed.wait(), 0.5)
        self.assertEqual([request["method"] for request in fake.requests], ["hello", "hello"])

    async def test_camera_connection_establishment_is_inside_total_deadline(self):
        async def never_connect(*args, **kwargs):
            await asyncio.Event().wait()

        with mock.patch("studio.sensors.asyncio.open_connection", never_connect), \
                mock.patch("studio.sensors.CAMERA_TIMEOUT_S", 0.05):
            result = await asyncio.wait_for(self.sensors(camera_addr="tcp:127.0.0.1:1").camera(), 0.25)
        self.assertEqual(result["service_state"], "offline")

    async def test_camera_healthy_probe_aborts_a_connection_that_cannot_close(self):
        fake, sensors = await self.fake_camera()
        real_open = asyncio.open_connection
        closing_started = asyncio.Event()
        writers = []

        class SlowClose:
            def __init__(self, writer):
                self.writer = writer
                self.transport = mock.Mock(wraps=writer.transport)

            def __getattr__(self, name):
                return getattr(self.writer, name)

            async def wait_closed(self):
                closing_started.set()
                await asyncio.Event().wait()

        async def slow_close(*args, **kwargs):
            reader, writer = await real_open(*args, **kwargs)
            writers.append(SlowClose(writer))
            return reader, writers[-1]

        with mock.patch("studio.sensors.asyncio.open_connection", slow_close):
            result = await asyncio.wait_for(sensors.camera(), 0.5)
        self.assertEqual(result["service_state"], "online")
        self.assertTrue(closing_started.is_set())
        writers[0].transport.abort.assert_called_once_with()
        await asyncio.wait_for(fake.closed.wait(), 0.5)

    async def test_camera_socket_runtime_without_unix_support_is_unknown(self):
        with mock.patch.object(asyncio, "open_unix_connection", mock.AsyncMock(side_effect=NotImplementedError), create=True):
            result = await self.sensors().camera()
        self.assertEqual(result["service_state"], "unknown")
        self.assertIn("tcp:", result["service_reason"])

    async def test_camera_invalid_address_fails_at_construction(self):
        with self.assertRaises(ValueError):
            self.sensors(camera_addr="http://127.0.0.1/")

    async def test_camera_source_is_configuration_and_never_verified_hardware(self):
        self.config.write_text('[media]\nsource = "test"\n', encoding="utf-8")
        before = self.config.read_bytes()
        result = await self.sensors(camera_signaling_port=9443).camera()
        self.assertEqual(result["source"], "test")
        self.assertEqual(result["source_basis"], "config")
        self.assertIs(result["source_verified"], False)
        self.assertEqual(result["signaling_port"], 9443)
        self.assertIn("测试", result["source_label"])
        self.assertIsNone(result["error"])
        self.assertEqual(self.config.read_bytes(), before)

    async def test_camera_unknown_config_preserves_signaling_attempt(self):
        result = await self.sensors().camera()
        self.assertEqual(result["source"], "unknown")
        self.assertEqual(result["signaling_port"], 8443)
        self.assertTrue(result["error"])
        self.assertFalse(self.config.exists())

    async def test_camera_explicit_hardware_source_remains_unverified(self):
        self.config.write_text('[media]\nsource = "camera"\ncamera = false\n', encoding="utf-8")
        result = await self.sensors().camera()
        self.assertEqual(result["source"], "camera")
        self.assertFalse(result["source_verified"])

    async def test_camera_missing_invalid_and_legacy_sources_are_explained(self):
        for content in ('[media]\ncamera = false\n', '[media]\ncamera = true\n',
                        '[media]\nsource = "elsewhere"\n', '[media]\nsource = false\n',
                        'media = 2\n', '[media]\nquality = "720p30"\n', '[media\nsource ='):
            with self.subTest(content=content):
                self.config.write_text(content, encoding="utf-8")
                before = self.config.read_bytes()
                result = await self.sensors().camera()
                self.assertEqual(result["source"], "unknown")
                self.assertTrue(result["error"])
                self.assertEqual(self.config.read_bytes(), before)

    async def test_tof_interprets_sensor_status_and_closes_its_own_connection(self):
        distances = [1200, 600, 0, -5, 900, 0] + [0] * 58
        statuses = [5, 9, 255, 5, 4, 9] + [255] * 58
        fake, sensors = await self.fake(frames=[frame(distance_mm=distances, status=statuses)])
        result = await sensors.tof()
        self.assertEqual(result["state"], "ready")
        self.assertIs(result["connected"], True)
        self.assertEqual(result["sensor"], "VL53L8CX")
        self.assertEqual((result["rows"], result["cols"], result["hz"], result["seq"]), (8, 8, 15, 41))
        self.assertEqual(result["distance_mm"], distances)
        self.assertEqual(result["status"], statuses)
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual((result["nearest_mm"], result["farthest_mm"]), (600, 1200))
        self.assertEqual(result["zones"][:6], [
            {"kind": "range", "mm": 1200, "status": 5},
            {"kind": "range", "mm": 600, "status": 9},
            {"kind": "no_target", "mm": None, "status": 255},
            {"kind": "unusable", "mm": None, "status": 5},
            {"kind": "unusable", "mm": None, "status": 4},
            {"kind": "unusable", "mm": None, "status": 9},
        ])
        self.assertIs(result["simulated"], False)
        self.assertGreaterEqual(result["age_ms"], 0)
        self.assertLess(result["age_ms"], 100)
        await asyncio.wait_for(fake.closed.wait(), 0.5)
        self.assertEqual([r["method"] for r in fake.requests], ["tof.stream"])
        self.assertEqual(fake.requests[0]["params"], {})
        json.dumps(result, allow_nan=False)

    async def test_tof_zero_valid_ranges_has_no_nearest_or_farthest(self):
        _, sensors = await self.fake(frames=[frame(distance_mm=[0] * 64, status=[255] * 64)])
        result = await sensors.tof()
        self.assertEqual(result["valid_count"], 0)
        self.assertIsNone(result["nearest_mm"])
        self.assertIsNone(result["farthest_mm"])

    async def test_tof_rejects_malformed_frame_without_current_values(self):
        bad_fields = [
            {"rows": 4}, {"cols": 8.0}, {"rows": True},
            {"distance_mm": [10] * 63}, {"status": [5] * 65},
            {"distance_mm": [True] + [1] * 63}, {"distance_mm": [1.5] + [1] * 63},
            {"distance_mm": [32768] + [1] * 63}, {"distance_mm": [-32769] + [1] * 63},
            {"distance_mm": "10"}, {"status": [256] + [5] * 63},
            {"status": [-1] + [5] * 63}, {"status": [False] + [5] * 63},
            {"status": [5.0] + [5] * 63}, {"seq": -1}, {"seq": True},
            {"seq": 2**64}, {"at_us": -1}, {"t_ns": "bad"},
        ]
        for fields in bad_fields:
            with self.subTest(fields=fields):
                _, sensors = await self.fake(frames=[frame(**fields)])
                try:
                    result = await sensors.tof()
                except Exception as exc:
                    self.fail(f"bad sensor frame must become a view, not an exception: {exc!r}")
                self.assertEqual(result["state"], "error")
                self.assertTrue(result["reason"])
                self.assertEqual(result["distance_mm"], [])
                self.assertEqual(result["zones"], [])
                self.assertIsNone(result["nearest_mm"])

    async def test_tof_metadata_rejection_and_bad_shape_are_errors(self):
        for metadata in ({"accepted": False}, {"accepted": 1}, {"rows": 4}, {"cols": 8.0},
                         {"hz": 0}, {"hz": True}, {"hz": 256}, {"sensor": {}}, {"unavailable": []}):
            with self.subTest(metadata=metadata):
                _, sensors = await self.fake(metadata=metadata)
                try:
                    result = await sensors.tof()
                except Exception as exc:
                    self.fail(f"bad metadata must become a view, not an exception: {exc!r}")
                self.assertEqual(result["state"], "error")
                self.assertEqual(result["distance_mm"], [])

    async def test_tof_rpc_error_is_reported(self):
        fake, sensors = await self.fake()
        fake.error = {"code": -32601, "message": "no stream"}
        try:
            result = await sensors.tof()
        except Exception as exc:
            self.fail(f"ToF RPC rejection must become a view: {exc!r}")
        self.assertEqual(result["state"], "error")
        self.assertIn("no stream", result["reason"])

    async def test_tof_waits_for_first_frame_and_does_not_return_stale_values(self):
        fake, sensors = await self.fake()
        self.assertEqual((await sensors.tof())["state"], "ready")
        fake.frames = []
        with mock.patch("studio.sensors.TOF_TIMEOUT_S", 0.05):
            try:
                result = await sensors.tof()
            except TimeoutError:
                self.fail("first-frame timeout must return a waiting view")
        self.assertEqual(result["state"], "waiting")
        self.assertTrue(result["connected"])
        self.assertEqual(result["distance_mm"], [])
        self.assertIsNone(result["seq"])
        self.assertEqual(fake.connections, 2)

    async def test_tof_missing_sensor_reports_daemon_reason_and_closes(self):
        fake, sensors = await self.fake(frames=[], metadata={"sensor": None, "unavailable": "not fitted"})
        with mock.patch("studio.sensors.TOF_TIMEOUT_S", 0.05):
            try:
                result = await sensors.tof()
            except TimeoutError:
                self.fail("missing sensor must return an unavailable view")
        self.assertEqual(result["state"], "unavailable")
        self.assertTrue(result["connected"])
        self.assertEqual(result["reason"], "not fitted")
        await asyncio.wait_for(fake.closed.wait(), 0.5)

    async def test_tof_accepts_normal_absent_optional_metadata_and_later_frame(self):
        fake, sensors = await self.fake()
        fake.metadata.pop("sensor")
        result = await sensors.tof()
        self.assertEqual(result["state"], "ready")
        self.assertIsNone(result["sensor"])

    async def test_tof_known_simulator_sources_are_labeled(self):
        for sensor in ("sim", "fake"):
            with self.subTest(sensor=sensor):
                _, sensors = await self.fake(metadata={"sensor": sensor})
                result = await sensors.tof()
                self.assertTrue(result["simulated"])

    async def test_tof_disabled_does_no_io(self):
        sensors = self.sensors(tof_addr="none")
        try:
            result = await sensors.tof()
        except ValueError:
            self.fail("none must disable ToF without parsing a socket address")
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["connected"])
        self.assertIn("未配置", result["reason"])

    async def test_tof_offline_and_disconnected_are_distinct(self):
        fake, sensors = await self.fake(frames=[])
        fake.disconnect = True
        try:
            disconnected = await sensors.tof()
        except Exception as exc:
            self.fail(f"disconnect must return an error view: {exc!r}")
        self.assertEqual(disconnected["state"], "error")
        self.assertFalse(disconnected["connected"])
        self.assertIn("断开", disconnected["reason"])
        await fake.stop()
        self.servers.remove(fake)
        try:
            offline = await sensors.tof()
        except Exception as exc:
            self.fail(f"offline service must return an unavailable view: {exc!r}")
        self.assertEqual(offline["state"], "unavailable")
        self.assertFalse(offline["connected"])

    async def test_tof_rejects_large_or_non_json_notifications(self):
        for raw in (b"x" * (64 * 1024 + 1) + b"\n", b"[1,2,3]\n", b"garbage\n",
                    b'{"jsonrpc":"2.0","method":"tof.frame","params":NaN}\n'):
            with self.subTest(raw=raw[:60]):
                fake, sensors = await self.fake()
                fake.raw = raw
                try:
                    result = await sensors.tof()
                except Exception as exc:
                    self.fail(f"bad wire data must return an error view: {exc!r}")
                self.assertEqual(result["state"], "error")
                self.assertEqual(result["zones"], [])

    async def test_tof_total_deadline_includes_unanswered_subscribe(self):
        fake, sensors = await self.fake()
        fake.release.clear()
        with mock.patch("studio.sensors.TOF_TIMEOUT_S", 0.05):
            started = asyncio.get_running_loop().time()
            try:
                result = await sensors.tof()
            except TimeoutError:
                self.fail("an unanswered subscription must return an error view")
            elapsed = asyncio.get_running_loop().time() - started
        fake.release.set()
        self.assertLess(elapsed, 0.25)
        self.assertEqual(result["state"], "error")
        self.assertTrue(result["reason"])

    async def test_tof_coalesces_only_concurrent_reads(self):
        fake, sensors = await self.fake()
        fake.release.clear()
        tasks = [asyncio.create_task(sensors.tof()) for _ in range(12)]
        await asyncio.sleep(0.03)
        fake.release.set()
        results = await asyncio.gather(*tasks)
        self.assertTrue(all(result["state"] == "ready" for result in results))
        self.assertEqual(fake.connections, 1)
        fake.frames = [frame(seq=42)]
        self.assertEqual((await sensors.tof())["seq"], 42)
        self.assertEqual(fake.connections, 2)

    async def test_tof_canceling_one_reader_keeps_the_other_reader(self):
        fake, sensors = await self.fake()
        fake.release.clear()
        first = asyncio.create_task(sensors.tof())
        second = asyncio.create_task(sensors.tof())
        await asyncio.sleep(0.02)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        fake.release.set()
        self.assertEqual((await second)["state"], "ready")
        self.assertEqual(fake.connections, 1)
        await asyncio.wait_for(fake.closed.wait(), 0.5)

    async def test_tof_canceling_last_reader_closes_without_waiting_deadline(self):
        fake, sensors = await self.fake(frames=[])
        task = asyncio.create_task(sensors.tof())
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(fake.closed.wait(), 0.3)
        fake.frames = [frame(seq=42)]
        self.assertEqual((await sensors.tof())["seq"], 42)
        self.assertEqual(fake.connections, 2)

    async def test_tof_reconnect_during_canceled_connection_cleanup_starts_fresh(self):
        fake, sensors = await self.fake(frames=[])
        cleanup_started, allow_cleanup = asyncio.Event(), asyncio.Event()
        real_open = asyncio.open_connection
        connections = 0

        class SlowClose:
            def __init__(self, writer):
                self.writer = writer

            def __getattr__(self, name):
                return getattr(self.writer, name)

            async def wait_closed(self):
                cleanup_started.set()
                await allow_cleanup.wait()
                await self.writer.wait_closed()

        async def slow_first_close(*args, **kwargs):
            nonlocal connections
            connections += 1
            reader, writer = await real_open(*args, **kwargs)
            return reader, SlowClose(writer) if connections == 1 else writer

        with mock.patch("studio.sensors.asyncio.open_connection", slow_first_close):
            first = asyncio.create_task(sensors.tof())
            await asyncio.wait_for(fake.requested.wait(), 0.5)
            first.cancel()
            await asyncio.wait_for(cleanup_started.wait(), 0.5)
            fake.frames = [frame(seq=42)]
            second = asyncio.create_task(sensors.tof())
            await asyncio.sleep(0)
            allow_cleanup.set()
            results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertIsInstance(results[1], dict, "new reader must not join a canceling connection")
        self.assertEqual(results[1]["seq"], 42)
        self.assertEqual(fake.connections, 2)

    async def test_tof_connection_establishment_is_inside_total_deadline(self):
        sensors = self.sensors(tof_addr="tcp:127.0.0.1:1")

        async def never_connect(*args, **kwargs):
            await asyncio.Event().wait()

        with mock.patch("studio.sensors.asyncio.open_connection", never_connect), \
                mock.patch("studio.sensors.TOF_TIMEOUT_S", 0.05):
            result = await asyncio.wait_for(sensors.tof(), 0.25)
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["connected"])

    async def test_tof_unavailable_unix_support_returns_helpful_state(self):
        sensors = self.sensors()
        with mock.patch.object(asyncio, "open_unix_connection", None, create=True):
            try:
                result = await sensors.tof()
            except Exception as exc:
                self.fail(f"unsupported Unix sockets must return an unavailable view: {exc!r}")
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["connected"])
        self.assertIn("tcp:", result["reason"])

    async def test_tof_unexpected_notification_is_bad_data(self):
        fake, sensors = await self.fake()
        fake.raw = b'{"jsonrpc":"2.0","method":"robot.state","params":{}}\n'
        result = await sensors.tof()
        self.assertEqual(result["state"], "error")
        self.assertTrue(result["reason"])

    async def test_tof_invalid_address_fails_at_construction(self):
        with self.assertRaises(ValueError):
            self.sensors(tof_addr="http://127.0.0.1/")


if __name__ == "__main__":
    unittest.main()
