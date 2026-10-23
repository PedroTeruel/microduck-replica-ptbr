"""Real browser IMU page, with explicit transport snapshots and delayed command replies."""
import functools
import http.server
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from tests.test_vpad_e2e import EDGE, NODE, ROOT, HERE, _kill, _node_ok, _port, _wait_http


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "需要 Node >=22 和 Edge；STUDIO_E2E=0 时跳过浏览器测试")
class ImuBusUiTest(unittest.TestCase):
    def test_bus_labels_binding_and_calibration_context(self):
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path == "/fixture":
                    content = (b'<!doctype html><meta charset="utf-8"><script type="importmap">'
                               b'{"imports":{"three":"/vendor/three/three.module.js"}}</script><body></body>')
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    try:
                        super().do_GET()
                    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                        pass

        handler = functools.partial(QuietHandler, directory=str(ROOT / "web"))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        edge = None
        try:
            with tempfile.TemporaryDirectory(prefix="imu-bus-ui-") as directory:
                cdp = _port(9368)
                with open(Path(directory) / "edge.log", "w", encoding="utf-8") as log:
                    edge = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
                        "--no-default-browser-check", "--enable-unsafe-swiftshader",
                        f"--remote-debugging-port={cdp}", f"--user-data-dir={directory}/edge", "about:blank"],
                        stdout=log, stderr=subprocess.STDOUT)
                    try:
                        _wait_http(f"http://127.0.0.1:{cdp}/json/version", "IMU 测试 Edge", timeout=30)
                        result = subprocess.run([NODE, str(HERE / "imu_bus_ui.mjs"),
                            f"http://127.0.0.1:{server.server_port}/fixture", str(cdp)], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                    finally:
                        _kill(edge)
                        edge = None
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        finally:
            _kill(edge)
            server.shutdown()
            server.server_close()
            thread.join(5)
