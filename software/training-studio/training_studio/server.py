"""Loopback-first HTTP API, with explicit host/origin and file containment."""
import hmac
import ipaddress
import json
import mimetypes
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .config import StudioError


def safe_file(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative or relative.startswith("/") or any(part in ("", ".", "..") for part in relative.split("/")):
        raise StudioError("禁止访问此路径", 403)
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise StudioError("禁止访问此路径", 403)
    if not path.is_file():
        raise StudioError("未找到文件", 404)
    return path


def is_loopback(host):
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class StudioHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(service, host="127.0.0.1", port=8093, *, web_root=None, shared_root=None, token=None):
    if not is_loopback(host) and not token:
        raise StudioError("非回环监听必须配置访问令牌（--token 或 STUDIO_ACCESS_TOKEN）。", 403)
    here = Path(__file__).resolve().parent.parent
    web_root = Path(web_root or here / "web").resolve()
    shared_root = Path(shared_root or here.parent / "studio" / "web").resolve()
    allowed_hosts = {"localhost", "127.0.0.1", "::1"}
    if not is_loopback(host):
        allowed_hosts.update({host.lower(), socket.gethostname().lower(), socket.getfqdn().lower()})
        try:
            allowed_hosts.update(a[4][0].lower() for a in socket.getaddrinfo(socket.gethostname(), None))
        except socket.gaierror:
            pass

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "MicroduckTrainingStudio/1"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, fmt, *args):
            # Avoid exposing access tokens, file paths or user payloads in HTTP logs.
            pass

        def _headers(self, code, content_type, length, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'sha256-iPcDvAuliaRrhvDxfMXLBSsTjj9Ltu/Gnz87vbMIGjE='; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()

        def _json(self, code, data):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._headers(code, "application/json; charset=utf-8", len(body))
            if self.command != "HEAD":
                self.wfile.write(body)

        def _check_request(self, api):
            hosts = self.headers.get_all("Host", [])
            if len(hosts) != 1:
                raise StudioError("Host 请求头无效", 403)
            raw_host = hosts[0]
            try:
                parsed = urlsplit("http://" + raw_host)
                actual_port = parsed.port or 80
                valid = (parsed.hostname or "").lower() in allowed_hosts and actual_port == self.server.server_address[1]
                if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                    valid = False
            except ValueError:
                valid = False
            if not valid:
                raise StudioError("Host 不被允许", 403)
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + raw_host:
                raise StudioError("禁止跨站请求", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise StudioError("禁止跨站请求", 403)
            if api and token:
                supplied = self.headers.get("X-Studio-Token", "")
                if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
                    raise StudioError("访问令牌缺失或不正确", 401)

        def _payload(self):
            if self.headers.get("Transfer-Encoding"):
                raise StudioError("不支持分块请求正文")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise StudioError("Content-Length 无效") from None
            if not 0 <= length <= 100000:
                raise StudioError("请求正文不得超过 100000 字节")
            if length and self.headers.get_content_type() != "application/json":
                raise StudioError("请求正文必须是 application/json")
            try:
                def invalid_constant(value):
                    raise ValueError(value)
                data = json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=invalid_constant) if length else {}
            except (ValueError, UnicodeError, RecursionError):
                raise StudioError("请求正文不是有效 JSON") from None
            if not isinstance(data, dict):
                raise StudioError("请求正文必须是 JSON 对象")
            return data

        def _file(self, path, *, artifact=False):
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if path.suffix.lower() in (".js", ".mjs"):
                mime = "text/javascript"
            size = path.stat().st_size
            start, end, status = 0, max(0, size - 1), 200
            extra = {"Accept-Ranges": "bytes"}
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                if not match or (not match[1] and not match[2]) or size == 0:
                    raise StudioError("Range 请求无效")
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]) if match[2] else size - 1, size - 1)
                else:
                    start = max(0, size - int(match[2]))
                if start > end or start >= size:
                    raise StudioError("Range 超出文件范围")
                status = 206
                extra["Content-Range"] = f"bytes {start}-{end}/{size}"
            if artifact and mime not in ("video/mp4", "image/svg+xml"):
                extra["Content-Disposition"] = f'attachment; filename="{path.name}"'
            length = 0 if size == 0 else end - start + 1
            self._headers(status, mime, length, extra)
            if self.command != "HEAD":
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = length
                    while remaining:
                        data = source.read(min(65536, remaining))
                        if not data:
                            break
                        self.wfile.write(data)
                        remaining -= len(data)

        def _dispatch(self):
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.query:
                raise StudioError("请求路径无效")
            path = unquote(parsed.path)
            if "\x00" in path:
                raise StudioError("请求路径无效")
            api = path.startswith("/api/")
            self._check_request(api)
            method = self.command
            if method in ("GET", "HEAD"):
                if path == "/api/state":
                    return self._json(200, service.state())
                if path == "/api/environment":
                    return self._json(200, service.refresh_environment())
                if path == "/api/resources":
                    return self._json(200, service.resources())
                match = re.fullmatch(r"/api/runs/([a-f0-9]{12})", path)
                if match:
                    return self._json(200, service.get_run(match[1]))
                match = re.fullmatch(r"/api/artifacts/([^/]+)/(.+)", path)
                if match:
                    return self._file(service.artifact_path(match[1], match[2]), artifact=True)
                if api:
                    raise StudioError("未找到 API", 404)
                if path.startswith("/shared/"):
                    relative = path[len("/shared/"):]
                    if relative not in ("duck3d.js", "model-worker.js") and not relative.startswith(("vendor/", "model/")):
                        raise StudioError("未找到共享资源", 404)
                    return self._file(safe_file(shared_root, relative))
                return self._file(safe_file(web_root, "index.html" if path == "/" else path.lstrip("/")))
            if method == "POST":
                payload = self._payload()
                if path == "/api/runs":
                    return self._json(201, {"run": service.create_run(payload)})
                match = re.fullmatch(r"/api/runs/([a-f0-9]{12})/(pause|resume|stop|evaluate|export)", path)
                if match:
                    run_id, action = match.groups()
                    if action in ("pause", "stop"):
                        if payload:
                            raise StudioError("此操作不接受额外参数")
                        run = getattr(service, action)(run_id)
                    elif action == "resume":
                        run = service.resume(run_id, payload)
                    else:
                        run = service.operate(run_id, action, payload)
                    return self._json(200, {"run": run})
            raise StudioError("未找到 API 或操作", 404)

        def _handle(self):
            try:
                self._dispatch()
            except StudioError as exc:
                data = {"error": exc.error}
                if exc.detail is not None:
                    data["detail"] = exc.detail
                self.close_connection = True
                self._json(exc.status, data)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except (OSError, ValueError):
                self.close_connection = True
                self._json(400, {"error": "请求处理失败，请查看任务状态与本地文件。"})

        do_GET = _handle
        do_HEAD = _handle
        do_POST = _handle
        do_OPTIONS = _handle

    return StudioHTTPServer((host, port), Handler)
