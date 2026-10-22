import http.client
import base64
import hashlib
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from training_studio.config import StudioError
from training_studio.server import create_server, safe_file
from training_studio.service import StudioService


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("training studio", encoding="utf-8")
        self.shared = self.root / "shared"
        self.shared.mkdir()
        (self.shared / "duck3d.js").write_text("export{}", encoding="utf-8")
        (self.shared / "app.js").write_text("secret", encoding="utf-8")
        self.service = StudioService(self.root / "state", self.root / "engine", demo=True)
        self.server = create_server(self.service, "127.0.0.1", 0, web_root=self.web, shared_root=self.shared, token="secret-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.service.shutdown()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, payload=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        head = {"X-Studio-Token": "secret-token", **(headers or {})}
        if payload is not None:
            head["Content-Type"] = "application/json"
        conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=head)
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res.status, body, dict(res.headers)

    def test_state_and_static_assets(self):
        status, body, headers = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "demo")
        self.assertIn("nosniff", headers.get("X-Content-Type-Options", ""))
        self.assertEqual(self.request("GET", "/")[1], b"training studio")

    def test_csp_allows_only_exact_repository_importmap_hash(self):
        html = (Path(__file__).resolve().parents[1] / "web/index.html").read_text(encoding="utf-8")
        source = re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(source.encode()).digest()).decode()
        self.assertEqual(digest, "iPcDvAuliaRrhvDxfMXLBSsTjj9Ltu/Gnz87vbMIGjE=")
        csp = self.request("GET", "/")[2]["Content-Security-Policy"]
        scripts = next(part.strip() for part in csp.split(";") if part.strip().startswith("script-src "))
        self.assertIn("'sha256-" + digest + "'", scripts)
        self.assertNotIn("'unsafe-inline'", scripts)

    def test_authentication_and_host_origin_enforcement(self):
        self.assertEqual(self.request("GET", "/api/state", headers={"X-Studio-Token": "wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/runs", {}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": f"http://127.0.0.1:{self.port}"})[0], 200)

    def test_create_and_errors_are_json(self):
        status, body, _ = self.request("POST", "/api/runs", {"recipe_id": "hd1910-flat", "kind": "smoke"})
        self.assertEqual(status, 201)
        run_id = json.loads(body)["run"]["id"]
        self.assertEqual(json.loads(self.request("GET", "/api/runs/" + run_id)[1])["id"], run_id)
        for path, expected in (("/api/runs/missing", 404), ("/api/nope", 404)):
            status, body, _ = self.request("GET", path)
            self.assertEqual(status, expected)
            self.assertIn("error", json.loads(body))
        self.assertEqual(self.request("POST", "/api/runs", {"kind": "shell"})[0], 400)

    def test_shared_and_static_routes_contained(self):
        self.assertEqual(self.request("GET", "/shared/duck3d.js")[0], 200)
        for path in ("/shared/app.js", "/shared/../app.js", "/%2e%2e/run.py", "/shared/vendor/%2e%2e/app.js", "/api/artifacts/missing/../run.json"):
            self.assertIn(self.request("GET", path)[0], (403, 404))

    def test_range_and_missing_auth_on_artifact(self):
        status, body, headers = self.request("GET", "/", headers={"Range": "bytes=0-7"})
        self.assertEqual((status, body), (206, b"training"))
        self.assertEqual(headers["Content-Range"], "bytes 0-7/15")
        self.assertEqual(self.request("GET", "/api/artifacts/missing/foo.zip", headers={"X-Studio-Token": ""})[0], 401)

    def test_invalid_profile_returns_json_instead_of_dropped_connection(self):
        status, body, _ = self.request("POST", "/api/runs", {"profile": {"schema": "microduck-studio-duck-profile/v1", "duck": {"label": 10 ** 1000}}})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_non_loopback_requires_token(self):
        with self.assertRaises(StudioError):
            create_server(self.service, "0.0.0.0", 0, web_root=self.web, shared_root=self.shared)

    def test_safe_file_rejects_symlink_escape(self):
        (self.root / "outside.txt").write_text("private", encoding="utf-8")
        try:
            (self.web / "escape").symlink_to(self.root / "outside.txt")
        except OSError:
            self.skipTest("Symlink creation requires privilege on Windows")
        with self.assertRaises(StudioError):
            safe_file(self.web, "escape")


if __name__ == "__main__":
    unittest.main()
