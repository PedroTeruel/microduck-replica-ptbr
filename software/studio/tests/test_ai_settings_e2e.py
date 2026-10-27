"""Real Studio/Edge + loopback fake provider; never contacts a public AI service."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests import test_vpad_e2e as harness

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(harness._node_ok() and harness.EDGE and os.environ.get('STUDIO_E2E', '1') != '0',
                     'requires Node >=22 and Edge')
class AiSettingsBrowser(unittest.TestCase):
    def test_saved_connections_and_real_mock_model_roundtrip(self):
        output = Path(os.environ.get('AI_E2E_DIR') or tempfile.mkdtemp(prefix='ai-settings-e2e-'))
        output.mkdir(parents=True, exist_ok=True)
        requests = []
        request_lock = threading.Lock()

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                with request_lock:
                    data = json.dumps({'requests': requests}, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                payload = json.loads(raw)
                entry = {'path': self.path, 'authorization': self.headers.get('Authorization'), 'body': payload}
                with request_lock:
                    requests.append(entry)
                model = payload.get('model')
                messages = payload.get('messages') or []
                if self.path != '/v1/chat/completions':
                    status, response = 404, {'error': {'message': 'wrong endpoint'}}
                elif model == 'reject-auth':
                    status, response = 401, {'error': {'message': 'fixture-ai-key-A must never be echoed'}}
                else:
                    text = next((m['content'] for m in reversed(messages) if m.get('role') == 'user'), '')
                    answer = ('fixture-ai-key-A' if model == 'echo-key' else
                              '长' * 2501 if model == 'long-answer' and text == '长回答' else
                              f'模拟回复[{model}]：{text}')
                    status, response = 200, {'choices': [{'message': {'role': 'assistant', 'content': answer}}]}
                data = json.dumps(response, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        p_robot, p_config, p_web, p_cdp = [harness._port(0) for _ in range(4)]
        processes, streams = [], []
        record = output / 'robotd.jsonl'
        record.write_text('', encoding='utf-8')

        def launch(name, arguments):
            stream = (output / name).open('w', encoding='utf-8')
            streams.append(stream)
            processes.append(subprocess.Popen(arguments, cwd=ROOT,
                env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, stdout=stream, stderr=subprocess.STDOUT))

        try:
            launch('fake.log', [sys.executable, '-I', str(ROOT/'dev/fake_robotd.py'), '--fixture',
                str(ROOT/'tests/fixtures/now-20261018.jsonl'), '--robotd-port', str(p_robot),
                '--configd-port', str(p_config), '--posture', 'holding', '--record', str(record)])
            launch('studio.log', [sys.executable, '-I', str(ROOT/'tests/audio_fixture_launcher.py'), '--listen',
                f'127.0.0.1:{p_web}', '--robotd', f'tcp:127.0.0.1:{p_robot}', '--configd',
                f'tcp:127.0.0.1:{p_config}', '--dev-autologin', '--servo-sim',
                '--state-dir', str(output/'state'), '--log-dir', str(output/'logs')])
            harness._wait_http(f'http://127.0.0.1:{p_web}/healthz', 'AI test Studio')
            launch('edge.log', [harness.EDGE, '--headless=new', '--disable-gpu', '--no-first-run',
                '--no-default-browser-check', f'--remote-debugging-port={p_cdp}',
                f'--user-data-dir={output/"edge"}', 'about:blank'])
            harness._wait_http(f'http://127.0.0.1:{p_cdp}/json/version', 'AI test Edge')
            result = subprocess.run([harness.NODE, str(ROOT/'tests/ai_settings_e2e.mjs'), '--url',
                f'http://127.0.0.1:{p_web}/#/settings', '--cdp', str(p_cdp), '--provider',
                f'http://127.0.0.1:{provider.server_port}/v1', '--shots', str(output/'shots')],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=160)
            (output/'browser.json').write_text(result.stdout, encoding='utf-8')
            (output/'browser.stderr').write_text(result.stderr, encoding='utf-8')
            self.assertEqual(result.returncode, 0, f'{result.stderr[-4500:]}\nArtifacts: {output}')
            report = json.loads(result.stdout)
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['layouts'], [1440, 390, 320])
            self.assertTrue(report['draft_ready_false'])
            self.assertTrue(report['key_hidden_after_reload'])
            self.assertTrue(report['current_persisted'])
            self.assertTrue(report['test_roundtrip'])
            self.assertTrue(report['chat_roundtrip'])
            self.assertTrue(report['multiturn'])
            self.assertTrue(report['long_reply_multiturn'])
            self.assertTrue(report['no_secret_in_responses_or_browser_storage'])
            self.assertTrue(report['error_rendered'])
            self.assertTrue(report['delete_succeeded'])
            with request_lock:
                captured = list(requests)
            self.assertGreaterEqual(len(captured), 4)
            self.assertTrue(all(r['path'] == '/v1/chat/completions' for r in captured))
            self.assertTrue(any(r['authorization'] == 'Bearer fixture-ai-key-A' for r in captured))
            self.assertTrue(any(len(r['body'].get('messages', [])) >= 3 for r in captured))
            self.assertTrue(any(any(m['role'] == 'assistant' and len(m['content']) > 2000
                for m in r['body'].get('messages', [])) for r in captured))
            movement = [json.loads(line) for line in record.read_text(encoding='utf-8').splitlines() if line]
            disallowed = {'robot.init','robot.enable','robot.do','robot.head','robot.mouth','robot.move'}
            self.assertFalse(any(r['method'] in disallowed for r in movement), 'AI settings/chat must never actuate robot')
        finally:
            provider.shutdown(); provider.server_close(); thread.join(timeout=3)
            with request_lock:
                (output/'provider-requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
            for process in reversed(processes):
                harness._kill(process)
            for stream in streams:
                stream.close()
