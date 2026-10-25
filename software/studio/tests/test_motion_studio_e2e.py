"""Real Studio + fake robotd + Edge: complete web recording and lively flow."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tests import test_vpad_e2e as harness

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(harness._node_ok() and harness.EDGE and os.environ.get('STUDIO_E2E', '1') != '0',
                     'requires Node >=22 and Edge')
class MotionStudioBrowser(unittest.TestCase):
    def test_record_lively_save_replay_and_lifecycle(self):
        output = Path(os.environ.get('MOTION_E2E_DIR') or tempfile.mkdtemp(prefix='motion-studio-e2e-'))
        output.mkdir(parents=True, exist_ok=True)
        p_robot, p_config, p_web, p_cdp = [harness._port(0) for _ in range(4)]
        processes, streams = [], []
        record = output / 'robotd.jsonl'
        record.write_text('', encoding='utf-8')

        def launch(name, args):
            stream = (output / name).open('w', encoding='utf-8')
            streams.append(stream)
            processes.append(subprocess.Popen(args, cwd=ROOT, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                                              stdout=stream, stderr=subprocess.STDOUT))

        try:
            launch('fake.log', [sys.executable, '-I', str(ROOT / 'dev/fake_robotd.py'), '--fixture',
                               str(ROOT / 'tests/fixtures/now-20261018.jsonl'), '--robotd-port', str(p_robot),
                               '--configd-port', str(p_config), '--posture', 'policy', '--record', str(record)])
            launch('studio.log', [sys.executable, '-I', str(ROOT / 'run.py'), '--listen', f'127.0.0.1:{p_web}',
                                 '--robotd', f'tcp:127.0.0.1:{p_robot}', '--configd', f'tcp:127.0.0.1:{p_config}',
                                 '--dev-autologin', '--servo-sim', '--state-dir', str(output / 'state'),
                                 '--log-dir', str(output / 'logs')])
            harness._wait_http(f'http://127.0.0.1:{p_web}/healthz', 'motion test Studio')
            launch('edge.log', [harness.EDGE, '--headless=new', '--disable-gpu', '--no-first-run',
                               '--no-default-browser-check', f'--remote-debugging-port={p_cdp}',
                               f'--user-data-dir={output / "edge"}', 'about:blank'])
            harness._wait_http(f'http://127.0.0.1:{p_cdp}/json/version', 'motion test Edge')
            result = subprocess.run([harness.NODE, str(ROOT / 'tests/motion_studio_e2e.mjs'),
                                     '--url', f'http://127.0.0.1:{p_web}/#/pad', '--cdp', str(p_cdp),
                                     '--record', str(record), '--fake', str(p_config), '--shots', str(output / 'shots')],
                                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=200)
            (output / 'browser.stderr').write_text(result.stderr, encoding='utf-8')
            (output / 'browser.json').write_text(result.stdout, encoding='utf-8')
            self.assertEqual(result.returncode, 0, f'{result.stderr[-5000:]}\nArtifacts: {output}')
            report = json.loads(result.stdout)
            self.assertEqual(report['errors'], [])
            self.assertGreater(report['recorded_action_frames'], 3)
            self.assertGreater(report['replayed_action_frames'], 3)
            self.assertGreaterEqual(report['three_loop_action_frames'], report['recorded_action_frames'] * 2.5)
            self.assertEqual(report['loops_seen'], [1, 2, 3])
            self.assertEqual(report['layouts'], [1440, 390, 320])
        finally:
            for process in reversed(processes):
                harness._kill(process)
            for stream in streams:
                stream.close()
