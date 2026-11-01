"""Testes de integração com uvicorn e wsproto reais (mesma implementação da placa, sem TestClient).
Cobrem os itens 4, 5 e 7 do plano review-impl-plan S0: Host 421, matriz de Origin, login, WebSocket sem login e frequência de atualizações.
"""
import asyncio
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

import uvicorn  # noqa: E402
from wsproto import ConnectionType, WSConnection  # noqa: E402
from wsproto.events import (AcceptConnection, CloseConnection, RejectConnection, Request,  # noqa: E402
                            TextMessage, Ping, Pong)

from fake_robotd import FakeRobotd  # noqa: E402
from studio.app import build_app  # noqa: E402
from studio.auth import COOKIE, Auth  # noqa: E402
from studio.imu import ImuBackend  # noqa: E402
from studio.pad import default_pad  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.onboard import Onboarding  # noqa: E402
from studio.robotd import Robotd  # noqa: E402
from studio import helper  # noqa: E402
from studio.ws_protocol import MusicWebSocketProtocol  # noqa: E402
from studio.servo import ServoSession  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
WEB = HERE.parent / "web"
PW = "duck-secret-123"


def http_call(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Host": f"127.0.0.1:{port}"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    c.close()
    return out


class WsClient:
    """Cliente WebSocket mínimo: verifica o handshake e recebe mensagens JSON."""

    def __init__(self, port, origin=None, cookie=None, host=None):
        self.port, self.origin, self.cookie, self.host = port, origin, cookie, host
        self.ws = WSConnection(ConnectionType.CLIENT)
        self.msgs, self.buf = [], ""
        self.accepted = self.rejected = self.close_code = None
        self.pong_mode, self.pings = 'valid', []

    async def open(self):
        self.r, self.w = await asyncio.open_connection("127.0.0.1", self.port)
        hdrs = []
        if self.origin:
            hdrs.append(("Origin", self.origin))
        if self.cookie:
            hdrs.append(("Cookie", f"{COOKIE}={self.cookie}"))
        self.w.write(self.ws.send(Request(host=self.host or f"127.0.0.1:{self.port}", target="/ws", extra_headers=hdrs)))
        await self.w.drain()
        await self.pump(until=lambda: self.accepted or self.rejected or self.close_code is not None, timeout=3)

    async def pump(self, until, timeout=3.0):
        end = time.monotonic() + timeout
        while not until() and time.monotonic() < end:
            try:
                data = await asyncio.wait_for(self.r.read(65536), max(0.01, end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            if not data:
                break
            self.ws.receive_data(data)
            for ev in self.ws.events():
                if isinstance(ev, AcceptConnection):
                    self.accepted = True
                elif isinstance(ev, RejectConnection):
                    self.rejected = ev.status_code
                elif isinstance(ev, CloseConnection):
                    self.close_code = ev.code
                elif isinstance(ev, Ping):
                    self.pings.append(ev.payload)
                    if self.pong_mode is not None:
                        payload = ev.payload if self.pong_mode == 'valid' else b'unmatched'
                        self.w.write(self.ws.send(Pong(payload=payload)))
                        await self.w.drain()
                elif isinstance(ev, TextMessage):
                    self.buf += ev.data
                    if ev.message_finished:
                        self.msgs.append(json.loads(self.buf))
                        self.buf = ""

    async def send(self, obj):
        self.w.write(self.ws.send(TextMessage(json.dumps(obj))))
        await self.w.drain()

    def close(self):
        self.w.close()


class HttpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.log = log
        self.auth = Auth(Path(self.tmp.name) / "state", log)
        self.auth.set_password(PW)
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", log)
        self.servo = ServoSession(log, sim=True)
        self.pad = self.make_pad(log, p1, p2)
        self.onboard = Onboarding(str(Path(self.tmp.name) / "state"), log)
        app = build_app(auth=self.auth, robotd=self.rd, log=log, web_dir=WEB, duck={"label": "Microduck de teste"},
                        names=["microduck-2"], servo=self.servo, imu=ImuBackend(self.rd, log, self.tmp.name),
                        pad=self.pad, onboard=self.onboard, ssh_home=str(Path(self.tmp.name) / "home"))
        cfg = uvicorn.Config(app, host="127.0.0.1", port=0, ws=MusicWebSocketProtocol, http="h11", lifespan="on",
                             log_level="critical")
        self.server = uvicorn.Server(cfg)
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"

    def make_pad(self, log, robotd_port, configd_port):
        return None                     # Modo de bancada sem backend da página de controle; PadHttpTest usa o real.

    async def asyncTearDown(self):
        self.server.should_exit = True
        await self.task
        self.s1.close()
        self.s2.close()
        self.tmp.cleanup()

    async def call(self, *a, **kw):
        return await asyncio.to_thread(http_call, self.port, *a, **kw)

    async def login(self):
        st, h, _ = await self.call("POST", "/api/login", {"password": PW}, {"Origin": self.origin})
        self.assertEqual(st, 200)
        return h["set-cookie"].split(";")[0].split("=", 1)[1], h["set-cookie"]

    async def test_no_password_means_open(self):
        """Sem senha configurada, permite obter uma sessão e abrir o WebSocket sem login."""
        import os
        os.remove(self.auth.pw_path)
        st, _, body = await self.call("GET", "/api/session")
        self.assertEqual(st, 200)
        c = WsClient(self.port, origin=self.origin)
        await c.open()
        self.assertTrue(c.accepted)
        c.close()
        c2 = WsClient(self.port, origin="http://evil.example.com")      # Outros sites continuam bloqueados.
        await c2.open()
        self.assertFalse(c2.accepted)
        c2.close()

    async def test_bad_host_gets_421(self):
        st, _, _ = await self.call("GET", "/", headers={"Host": "evil.example.com"})
        self.assertEqual(st, 421)
        st, _, _ = await self.call("GET", "/healthz", headers={"Host": f"microduck-2:{self.port}"})
        self.assertEqual(st, 200)

    async def test_probe_svg_for_finding_the_duck(self):
        """A página localiza o Microduck pela URL probe.svg, sem login e sem cache, usando os hosts duck-xxxx e duck-xxxx.local."""
        import socket
        hn = socket.gethostname().lower()
        for host in (f"{hn}:{self.port}", f"{hn}.local:{self.port}", f"127.0.0.1:{self.port}"):
            st, h, body = await self.call("GET", "/probe.svg?t=1790000000000", headers={"Host": host})
            self.assertEqual(st, 200, host)
            self.assertTrue(h["content-type"].startswith("image/svg+xml"), h)
            self.assertEqual(h["cache-control"], "no-cache")
            self.assertIn(b"<svg", body)
            self.assertLess(len(body), 1024)                     # Resposta pequena para consultas a cada 2 s.
        st, _, _ = await self.call("GET", "/probe.svg", headers={"Host": "evil.example.com"})
        self.assertEqual(st, 421)                                 # A validação de Host continua ativa.

    async def test_login_origin_matrix_and_cookie(self):
        bad = [None, "http://evil.example.com", f"http://127.0.0.1:{self.port + 1}", "null"]
        for o in bad:
            st, _, _ = await self.call("POST", "/api/login", {"password": PW}, {"Origin": o} if o else {})
            self.assertEqual(st, 403, o)
        st, _, body = await self.call("POST", "/api/login", {"password": "wrong"}, {"Origin": self.origin})
        self.assertEqual(st, 401)
        token, raw = await self.login()
        self.assertIn("HttpOnly", raw)
        self.assertIn("samesite=lax", raw.lower())
        st, _, body = await self.call("GET", "/api/session", headers={"Cookie": f"{COOKIE}={token}"})
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(body)["csrf"])

    async def test_login_backoff_after_five_failures(self):
        for _ in range(5):
            await self.call("POST", "/api/login", {"password": "wrong"}, {"Origin": self.origin})
        st, _, body = await self.call("POST", "/api/login", {"password": PW}, {"Origin": self.origin})
        self.assertEqual(st, 401)
        self.assertGreater(json.loads(body)["wait"], 0)          # A senha correta também é recusada durante a espera.

    async def test_logout_needs_csrf(self):
        token, _ = await self.login()
        ck = {"Cookie": f"{COOKIE}={token}", "Origin": self.origin}
        await self.call("POST", "/api/logout", {}, ck)                       # Sem X-CSRF, a sessão não é encerrada.
        self.assertIsNotNone(self.auth.session(token))
        st, _, body = await self.call("GET", "/api/session", headers=ck)
        csrf = json.loads(body)["csrf"]
        await self.call("POST", "/api/logout", {}, dict(ck, **{"X-CSRF": csrf}))
        self.assertIsNone(self.auth.session(token))

    async def test_password_change_needs_login(self):
        st, _, _ = await self.call("POST", "/api/password",
                                   {"action": "set", "password": "new-secret", "confirm": "new-secret"},
                                   {"Origin": self.origin})
        self.assertEqual(st, 401)
        self.assertTrue(self.auth.check_password(PW))

    async def test_password_change_keeps_this_browser_logged_in(self):
        token, _ = await self.login()
        ck = {"Cookie": f"{COOKIE}={token}", "Origin": self.origin}
        _, _, body = await self.call("GET", "/api/session", headers=ck)
        csrf = json.loads(body)["csrf"]
        st, _, _ = await self.call("POST", "/api/password",
                                   {"action": "set", "password": "new-secret", "confirm": "new-secret"},
                                   dict(ck, **{"X-CSRF": csrf}))
        self.assertEqual(st, 200)
        st, _, _ = await self.call("GET", "/api/session", headers=ck)
        self.assertEqual(st, 200)
        self.assertTrue(self.auth.check_password("new-secret"))

    async def test_password_must_be_six_chars_and_typed_twice(self):
        token, _ = await self.login()
        ck = {"Cookie": f"{COOKIE}={token}", "Origin": self.origin}
        _, _, body = await self.call("GET", "/api/session", headers=ck)
        csrf = json.loads(body)["csrf"]
        for payload in ({"action": "set", "password": "12345", "confirm": "12345"},
                        {"action": "set", "password": "new-secret", "confirm": "new-secret2"}):
            st, _, _ = await self.call("POST", "/api/password", payload,
                                       dict(ck, **{"X-CSRF": csrf}))
            self.assertEqual(st, 400)
        self.assertTrue(self.auth.check_password(PW))

    async def test_first_password_from_the_web_logs_this_browser_in(self):
        os.remove(self.auth.pw_path)
        st, _, body = await self.call("GET", "/api/session")
        self.assertEqual(st, 200)
        csrf = json.loads(body)["csrf"]
        st, h, body = await self.call("POST", "/api/password",
                                      {"action": "set", "password": "new-secret", "confirm": "new-secret"},
                                      {"Origin": self.origin, "X-CSRF": csrf})
        self.assertEqual(st, 200, body)
        token = h["set-cookie"].split(";")[0].split("=", 1)[1]
        st, _, _ = await self.call("GET", "/api/session", headers={"Cookie": f"{COOKIE}={token}"})
        self.assertEqual(st, 200)
        self.assertTrue(self.auth.check_password("new-secret"))

    async def test_password_can_be_cleared_from_the_web(self):
        token, _ = await self.login()
        ck = {"Cookie": f"{COOKIE}={token}", "Origin": self.origin}
        _, _, body = await self.call("GET", "/api/session", headers=ck)
        csrf = json.loads(body)["csrf"]
        st, _, _ = await self.call("POST", "/api/password", {"action": "clear"},
                                   dict(ck, **{"X-CSRF": csrf}))
        self.assertEqual(st, 200)
        self.assertFalse(self.auth.has_password())
        self.assertFalse(self.auth.pw_path.exists())

    # ---- Opções de SSH na página Mais: recuperação pelo usuário, sem regravar o cartão ----

    async def ssh_post(self, payload):
        token, _ = await self.login()
        ck = {"Cookie": f"{COOKIE}={token}", "Origin": self.origin}
        _, _, body = await self.call("GET", "/api/session", headers=ck)
        csrf = json.loads(body)["csrf"]
        st, _, body = await self.call("POST", "/api/ssh", payload, dict(ck, **{"X-CSRF": csrf}))
        return st, json.loads(body or "{}")

    def ssh_patches(self, pw_result=("ssh_password_on", True)):
        result, on = pw_result
        view = {"password_login": on, "ssh_active": True, "keys": 0, "user": "radxa", "exit": 0, "result": "ssh_status"}
        return (unittest.mock.patch("studio.helper.available", return_value=True),
                unittest.mock.patch("studio.helper.ssh_password",
                                    return_value=(True, result, {"exit": 0, "result": result, "password_login": on})),
                unittest.mock.patch("studio.helper.ssh_status", return_value=(True, "ssh_status", view)))

    async def test_ssh_needs_login(self):
        st, _, _ = await self.call("POST", "/api/ssh", {"action": "status"}, {"Origin": self.origin})
        self.assertEqual(st, 401)

    async def test_ssh_on_needs_web_password_first(self):
        os.remove(self.auth.pw_path)
        _, _, body = await self.call("GET", "/api/session")
        csrf = json.loads(body)["csrf"]
        a, b, c = self.ssh_patches()
        with a, b as sp, c:
            st, _, body = await self.call("POST", "/api/ssh",
                                          {"action": "on", "password": "duck-secret-42", "confirm": "duck-secret-42"},
                                          {"Origin": self.origin, "X-CSRF": csrf})
        self.assertEqual(st, 403)
        self.assertIn("Defina primeiro a senha de acesso à página", json.loads(body)["error"])
        sp.assert_not_called()

    async def test_ssh_on_goes_to_helper_and_password_is_never_logged(self):
        pw = "duck-secret-42"
        a, b, c = self.ssh_patches()
        with a, b as sp, c:
            st, data = await self.ssh_post({"action": "on", "password": pw, "confirm": pw})
        self.assertEqual(st, 200, data)
        self.assertTrue(data["ssh"]["password_login"])
        self.assertEqual(sp.call_args.args[1:], (True, pw))
        recent = json.dumps(self.log.recent(limit=500), ensure_ascii=False)
        self.assertIn("Login SSH por senha habilitado", recent)
        self.assertNotIn(pw, recent)
        for f in (Path(self.tmp.name) / "logs").rglob("*"):
            if f.is_file():
                self.assertNotIn(pw, f.read_text(encoding="utf-8", errors="replace"), f)

    async def test_ssh_password_rules_checked_before_the_helper(self):
        a, b, c = self.ssh_patches()
        with a, b as sp, c:
            for payload in ({"action": "on", "password": "short77", "confirm": "short77"},
                            {"action": "on", "password": "duck-secret-42", "confirm": "duck-secret-43"},
                            {"action": "nope"}):
                st, _ = await self.ssh_post(payload)
                self.assertEqual(st, 400, payload)
        sp.assert_not_called()

    async def test_ssh_off_and_status(self):
        a, b, c = self.ssh_patches(("ssh_password_off", False))
        with a, b as sp, c:
            st, data = await self.ssh_post({"action": "off"})
            self.assertEqual(st, 200, data)
            self.assertEqual(sp.call_args.args[1], False)
            st, data = await self.ssh_post({"action": "status"})
        self.assertEqual(st, 200, data)
        self.assertEqual(data["ssh"], {"password_login": False, "ssh_active": True, "keys": 0, "key_list": [],
                                       "user": "radxa"})

    async def test_ssh_keys_add_list_remove(self):
        from tests.test_sshkeys import make_key
        line, fp = make_key(comment="laptop")
        a, b, c = self.ssh_patches(("ssh_password_off", False))
        with a, b, c:
            st, data = await self.ssh_post({"action": "add_key", "key": line})
            self.assertEqual(st, 200, data)
            self.assertTrue(data["added"])
            self.assertEqual([(k["fp"], k["comment"]) for k in data["ssh"]["key_list"]], [(fp, "laptop")])
            self.assertEqual(data["ssh"]["keys"], 1)
            st, data = await self.ssh_post({"action": "add_key", "key": line})
            self.assertEqual((st, data["added"]), (200, False))
            st, data = await self.ssh_post({"action": "add_key", "key": "-----BEGIN OPENSSH PRIVATE KEY-----"})
            self.assertEqual(st, 400)
            self.assertIn("chave privada", data["error"])
            st, data = await self.ssh_post({"action": "remove_key", "fp": fp})
            self.assertEqual((st, data["removed"], data["ssh"]["key_list"]), (200, 1, []))
        text = (Path(self.tmp.name) / "home" / ".ssh" / "authorized_keys").read_text(encoding="utf-8")
        self.assertEqual(text, "")
        self.assertIn("Chave SSH registrada: ssh-ed25519 laptop", json.dumps(self.log.recent(limit=200), ensure_ascii=False))

    async def test_ssh_add_key_needs_web_password_first(self):
        from tests.test_sshkeys import make_key
        line, _ = make_key()
        os.remove(self.auth.pw_path)
        _, _, body = await self.call("GET", "/api/session")
        csrf = json.loads(body)["csrf"]
        st, _, body = await self.call("POST", "/api/ssh", {"action": "add_key", "key": line},
                                      {"Origin": self.origin, "X-CSRF": csrf})
        self.assertEqual(st, 403)
        self.assertIn("registrar uma chave", json.loads(body)["error"])
        self.assertFalse((Path(self.tmp.name) / "home" / ".ssh" / "authorized_keys").exists())

    async def test_ssh_status_lists_keys_even_without_the_helper(self):
        from tests.test_sshkeys import make_key
        line, fp = make_key(comment="pc")
        home = Path(self.tmp.name) / "home" / ".ssh"
        home.mkdir(parents=True)
        (home / "authorized_keys").write_text(line + "\n", encoding="utf-8")
        with unittest.mock.patch("studio.helper.available", return_value=False):
            st, data = await self.ssh_post({"action": "status"})
        self.assertEqual(st, 200, data)
        self.assertIsNone(data["ssh"]["password_login"])            # Sem o helper, não é possível ler se o login por senha está ativo.
        self.assertEqual([k["fp"] for k in data["ssh"]["key_list"]], [fp])

    async def test_ws_without_login_tells_page_to_login(self):
        c = WsClient(self.port, origin=self.origin)
        await c.open()
        # O código 4401 informa à página que deve abrir o login; um 403 no handshake causaria reconexões repetidas.
        self.assertEqual(c.close_code, 4401, f"accepted={c.accepted} rejected={c.rejected}")
        c.close()

    async def test_ws_wrong_origin_is_rejected(self):
        token, _ = await self.login()
        c = WsClient(self.port, origin="http://evil.example.com", cookie=token)
        await c.open()
        self.assertFalse(c.accepted)
        c.close()

    async def test_ws_push_rate_follows_visibility(self):
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        self.assertTrue(c.accepted)
        await c.pump(until=lambda: False, timeout=1.0)
        states = [m for m in c.msgs if m["t"] == "state"]
        self.assertEqual(c.msgs[0]["t"], "hello")
        self.assertGreaterEqual(len(states), 7)                  # Área visível: cerca de 10 Hz.
        self.assertEqual(states[-1]["posture"], "holding")
        await c.send({"t": "hb", "seq": 1, "visible": False})
        await c.pump(until=lambda: False, timeout=0.3)
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=2.2)
        kinds = [m["t"] for m in c.msgs if m["t"] != "log"]
        self.assertNotIn("state", kinds)                         # Em segundo plano, restam apenas heartbeats.
        self.assertTrue(1 <= kinds.count("hb") <= 3, kinds)
        c.close()

    async def test_ws_relax_round_trip(self):
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "cmd", "id": "c1", "name": "relax"})
        await c.pump(until=lambda: any(m.get("t") == "state" and m["estop"]["state"] == "confirmed" for m in c.msgs),
                     timeout=3.0)
        results = [m for m in c.msgs if m["t"] == "result"]
        self.assertEqual(results and results[0]["ok"], True)
        self.assertEqual([m for m in c.msgs if m["t"] == "state"][-1]["estop"]["state"], "confirmed")
        c.close()

    async def test_servo_session_via_ws(self):
        """Abre o barramento simulado, detecta os 15 servos, desliga o torque pelo barramento e retoma a consulta após devolvê-lo."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "cmd", "id": "o1", "name": "servo.open"})
        await c.pump(until=lambda: (
            any(m.get("t") == "result" and m.get("id") == "o1" for m in c.msgs)
            and any(m.get("t") == "servo" and m.get("state") == "open" and m.get("online") == 15
                    for m in c.msgs)), timeout=3.0)
        res = [m for m in c.msgs if m.get("t") == "result" and m.get("id") == "o1"]
        self.assertTrue(res and res[0]["ok"], res)
        self.assertTrue(self.rd.paused)
        states = [m for m in c.msgs if m.get("t") == "state"]
        self.assertEqual(states[-1]["posture"], "servo_session")
        self.assertTrue(states[-1]["robotd_ok"])
        c.msgs.clear()
        await c.send({"t": "cmd", "id": "r1", "name": "relax"})
        await c.pump(until=lambda: any(m.get("t") == "state" and m["estop"]["state"] == "confirmed" for m in c.msgs),
                     timeout=3.0)
        self.assertTrue(any(m.get("t") == "result" and m.get("id") == "r1" and m["ok"] for m in c.msgs))
        self.assertEqual(len([m for _, m in self.fake.calls if m == "robot.relax"]), 0)   # Não aciona o programa principal.
        await c.send({"t": "cmd", "id": "x1", "name": "servo.close"})
        await c.pump(until=lambda: any(m.get("t") == "result" and m.get("id") == "x1" for m in c.msgs), timeout=3.0)
        self.assertEqual(self.servo.state, "closed")
        self.assertFalse(self.rd.paused)
        c.close()

    async def test_servo_session_accepts_open_snapshot_before_command_result(self):
        """The independent snapshot loop may observe open before open's worker returns."""
        release=threading.Event()
        original_open=self.servo.open
        original_client=WsClient
        loop=asyncio.get_running_loop()
        observed=[]
        clients=[]

        def opening(*args,**kwargs):
            result=original_open(*args,**kwargs)
            if result[0] and not release.wait(3):
                raise AssertionError('client did not observe the independent open snapshot')
            return result

        class Messages(list):
            def append(messages,message):
                super().append(message)
                if (not observed and message.get('t')=='servo' and message.get('state')=='open'
                        and message.get('online')==15):
                    observed.append(not any(m.get('t')=='result' and m.get('id')=='o1' for m in messages))
                    # Release on the next loop turn, after pump evaluates its
                    # completion predicate against this snapshot without an ack.
                    loop.call_soon(release.set)

        class Client(original_client):
            def __init__(client,*args,**kwargs):
                super().__init__(*args,**kwargs)
                client.msgs=Messages()
                clients.append(client)

        try:
            with unittest.mock.patch.object(self.servo,'open',side_effect=opening), \
                 unittest.mock.patch(__name__+'.WsClient',Client):
                await self.test_servo_session_via_ws()
            self.assertEqual(observed,[True],'test must exercise snapshot-before-result ordering')
        finally:
            release.set()
            for client in clients:
                if hasattr(client,'w'):client.close()

    async def test_imu_view_and_ops_via_ws(self):
        """A página recebe os dados da IMU do programa principal, calcula o resultado e explica por que a gravação é recusada."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.pump(until=lambda: any(m.get("t") == "imu" and m.get("mount") for m in c.msgs), timeout=4.0)
        v = [m for m in c.msgs if m.get("t") == "imu" and m.get("mount")][-1]
        self.assertEqual(v["source"], "lsm6dsv16x")
        self.assertTrue(v["mount"]["verified"])
        await c.send({"t": "cmd", "id": "s1", "name": "imu.op", "args": {"op": "solve", "samples": [{"g": [0, 0, -1]}]}})
        await c.send({"t": "cmd", "id": "w1", "name": "imu.op", "args": {"op": "save"}})
        await c.pump(until=lambda: {m.get("id") for m in c.msgs if m.get("t") == "result"} >= {"s1", "w1"}, timeout=3.0)
        res = {m["id"]: m for m in c.msgs if m.get("t") == "result"}
        self.assertTrue(res["s1"]["ok"])                       # A operação foi executada, mas os dados são insuficientes.
        self.assertFalse(res["s1"]["data"]["ok"])
        self.assertFalse(res["w1"]["ok"])
        self.assertIn("programa principal", res["w1"]["reason"])
        c.close()

    async def test_servo_refused_while_walking(self):
        """Enquanto o Microduck caminha ou executa uma política, a página dos servos não assume o barramento."""
        self.fake.set_posture("policy")
        await asyncio.sleep(1.2)
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "cmd", "id": "o1", "name": "servo.open"})
        await c.pump(until=lambda: any(m.get("t") == "result" for m in c.msgs), timeout=3.0)
        res = [m for m in c.msgs if m.get("t") == "result"][0]
        self.assertFalse(res["ok"])
        self.assertIn("Pare-o", res["reason"])
        self.assertEqual(self.servo.state, "closed")
        c.close()

    async def test_servo_auto_hand_back_when_nobody_on_page(self):
        """Sem ninguém na página dos servos por SERVO_IDLE_S, o barramento volta automaticamente ao programa principal."""
        from studio import app as app_mod
        token, _ = await self.login()
        with unittest.mock.patch.object(app_mod, "SERVO_IDLE_S", 0.5):
            c = WsClient(self.port, origin=self.origin, cookie=token)
            await c.open()
            await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/servos"})
            await c.send({"t": "cmd", "id": "o1", "name": "servo.open"})
            await c.pump(until=lambda: any(m.get("t") == "result" for m in c.msgs), timeout=3.0)
            self.assertEqual(self.servo.state, "open")
            c.close()                                              # Fecha a página.
            end = time.monotonic() + 15
            while self.servo.state == "open" and time.monotonic() < end:
                await asyncio.sleep(0.2)
        self.assertEqual(self.servo.state, "closed")
        self.assertFalse(self.rd.paused)

    async def test_page_gone_while_relax_in_flight(self):
        """Revisão de código #6: o desligamento do torque termina e é confirmado mesmo se a página desconectar."""
        self.fake.delays["robot.relax"] = 0.5
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "cmd", "id": "c1", "name": "relax"})
        await asyncio.sleep(0.1)
        c.close()
        end = time.monotonic() + 3
        while self.rd.estop.outcome != "confirmed" and time.monotonic() < end:
            await asyncio.sleep(0.05)
        self.assertEqual(self.rd.estop.outcome, "confirmed")
        self.assertEqual(len([m for _, m in self.fake.calls if m == "robot.relax"]), 1)

    async def test_servo_table_only_on_servo_page(self):
        """Revisão O12: a tabela de servos, com 5,6 KB por quadro, só é enviada na página dos servos."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/"})
        await c.pump(until=lambda: False, timeout=1.0)
        self.assertNotIn("servo", [m["t"] for m in c.msgs])
        self.assertIn("state", [m["t"] for m in c.msgs])
        await c.send({"t": "hb", "seq": 2, "visible": True, "route": "/servos"})
        await c.pump(until=lambda: any(m["t"] == "servo" for m in c.msgs), timeout=2.0)
        self.assertIn("servo", [m["t"] for m in c.msgs])
        c.close()

    async def test_state_carries_onboarding_and_board_temperature(self):
        """O estado inclui a lista de configuração e a temperatura da placa; a confirmação da calibração usa onboard.op."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.pump(until=lambda: any(m.get("t") == "state" and m.get("onboarding") for m in c.msgs), timeout=4.0)
        st = [m for m in c.msgs if m.get("t") == "state" and m.get("onboarding")][-1]
        self.assertEqual([r["key"] for r in st["onboarding"]["rows"]], ["servo", "imu", "commit", "pad", "estop", "walk"])
        self.assertEqual(st["cpu"]["c"], 76.9)
        await c.pump(until=lambda: self.rd.calib_fresh() is not None, timeout=3.0)
        await c.send({"t": "cmd", "id": "k1", "name": "onboard.op", "args": {"op": "confirm_servo"}})
        await c.send({"t": "cmd", "id": "k2", "name": "onboard.op", "args": {"op": "rm"}})
        await c.pump(until=lambda: {m.get("id") for m in c.msgs if m.get("t") == "result"} >= {"k1", "k2"}, timeout=4.0)
        res = {m["id"]: m for m in c.msgs if m.get("t") == "result"}
        self.assertTrue(res["k1"]["ok"], res["k1"])
        self.assertFalse(res["k2"]["ok"])
        self.assertTrue((Path(self.tmp.name) / "state" / "onboarding.json").exists())
        c.msgs.clear()
        await c.pump(until=lambda: any(m.get("t") == "state" and m.get("onboarding") for m in c.msgs), timeout=2.5)
        st = [m for m in c.msgs if m.get("t") == "state" and m.get("onboarding")][-1]   # Quadros sem mudanças omitem a lista (C5).
        self.assertEqual(next(r for r in st["onboarding"]["rows"] if r["key"] == "servo")["state"], "ok")
        c.close()

    async def test_onboard_skip_and_unskip_via_ws(self):
        """As ações concluir, pular e desfazer usam onboard.op; pular a confirmação da orientação da IMU exige confirmação dupla no backend."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.pump(until=lambda: self.rd.calib_fresh() is not None, timeout=3.0)

        async def op(cid, args):
            await c.send({"t": "cmd", "id": cid, "name": "onboard.op", "args": args})
            await c.pump(until=lambda: any(m.get("id") == cid for m in c.msgs), timeout=4.0)
            return next(m for m in c.msgs if m.get("id") == cid)

        async def imu_state():
            c.msgs.clear()
            await c.pump(until=lambda: any(m.get("t") == "state" and m.get("onboarding") for m in c.msgs), timeout=2.5)
            st = [m for m in c.msgs if m.get("t") == "state" and m.get("onboarding")][-1]
            return next(r for r in st["onboarding"]["rows"] if r["key"] == "imu")["state"]
        self.assertTrue((await op("s1", {"op": "skip", "step": "imu"}))["ok"])
        self.assertEqual(await imu_state(), "skip")
        self.assertTrue((await op("s2", {"op": "unskip", "step": "imu"}))["ok"])
        self.assertEqual(await imu_state(), "todo")
        self.assertTrue((await op("d1", {"op": "done", "step": "imu"}))["ok"])
        self.assertEqual(await imu_state(), "ok")
        self.assertTrue((await op("d2", {"op": "undone", "step": "imu"}))["ok"])
        self.assertEqual(await imu_state(), "todo")
        self.fake.bus["native"]["imu_mount_verified"] = False
        await asyncio.sleep(1.3)                                   # Aguarda a atualização de busStatus.
        r = await op("s3", {"op": "skip", "step": "imu"})
        self.assertFalse(r["ok"])
        self.assertIn("Confirmação em duas etapas necessária", r["reason"])
        r = await op("s3b", {"op": "skip", "step": "imu", "confirmed": True})
        self.assertTrue(r["ok"], r)
        self.assertEqual(await imu_state(), "skip")
        self.assertFalse((await op("s4", {"op": "skip", "step": "bogus"}))["ok"])
        c.close()

    async def test_onboarding_only_when_changed(self):
        """Revisão C5: quadros sem mudanças omitem onboarding, mas uma versão completa continua sendo enviada por segundo."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/"})
        await c.pump(until=lambda: any(m.get("t") == "state" and m.get("onboarding") for m in c.msgs), timeout=4.0)
        await c.pump(until=lambda: False, timeout=1.0)       # Aguarda a lista estabilizar após a conexão.
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=2.1)
        sts = [m for m in c.msgs if m.get("t") == "state"]
        full = [m for m in sts if "onboarding" in m]
        same = [m for m in sts if m.get("onboarding_same")]
        self.assertGreaterEqual(len(sts), 15)
        self.assertTrue(1 <= len(full) <= 5, (len(full), len(sts)))
        self.assertEqual(len(full) + len(same), len(sts))
        self.assertTrue(all("onboarding" not in m for m in same))
        c.close()

    async def test_ws_without_heartbeat_counts_as_not_looking(self):
        """Revisão #11: uma conexão sem heartbeat não pode contar indefinidamente como página em uso."""
        from studio import app as app_mod
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        with unittest.mock.patch.object(app_mod, "HB_QUIET_S", 0.4):
            await c.open()
            await c.pump(until=lambda: False, timeout=1.2)           # Não envia heartbeats.
            c.msgs.clear()
            await c.pump(until=lambda: False, timeout=1.5)
        self.assertNotIn("state", [m["t"] for m in c.msgs])
        self.assertEqual(self.rd.viewers, 0)
        c.close()

    async def test_ordinary_javascript_silent_connection_still_times_out(self):
        from studio import app as app_mod
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        with unittest.mock.patch.object(app_mod, "HB_DEAD_S", .4):
            await c.open()
            await c.pump(until=lambda: c.close_code is not None, timeout=2.)
        self.assertEqual(c.close_code, 4408)
        self.assertEqual(c.pings, [])
        c.close()


class PadHttpTest(HttpTest):
    """Repete os testes HTTP com o backend do controle ativo e cobre também as operações próprias da página do controle."""

    def make_pad(self, log, robotd_port, configd_port):
        return default_pad(log, configd_addr=f"tcp:127.0.0.1:{configd_port}", robotd_addr=f"tcp:127.0.0.1:{robotd_port}",
                           tap_addr="tcp:127.0.0.1:9", state_dir=self.tmp.name)

    async def music_client(self):
        self.fake.set_posture("policy")
        class Audio:
            def snapshot(self):
                return {"available": True, "listening": True, "music": True,
                        "rhythm": {"bpm": 120., "confidence": .9, "feel": "lively",
                                   "last_beat": time.monotonic(), "age": .01}}
            def close(self):
                pass
        self.pad.audio.close()
        self.pad.audio = Audio()
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "hb", "visible": True, "route": "/pad", "pad_visible": True})
        await c.send({"t": "cmd", "id": "open", "name": "pad.op", "args": {"op": "drive", "open": True}})
        await c.pump(until=lambda: any(m.get("motion_studio", {}).get("idle_available", {}).get("ok")
                                     for m in c.msgs) and self.rd.state.at is not None, timeout=4.)
        await c.send({"t": "cmd", "id": "music", "name": "pad.op", "args": {"op": "motion", "action": "idle_start", "kind": "music"}})
        await c.pump(until=lambda: any(m.get("id") == "music" for m in c.msgs), timeout=3.)
        result = next(m for m in c.msgs if m.get("id") == "music")
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(self.pad.motion_studio.background_music())
        await c.send({"t": "hb", "visible": False, "route": "/logs", "pad_visible": False})
        await c.send({"t": "cmd", "id": "leave", "name": "pad.op", "args": {"op": "drive", "on": False}})
        await c.pump(until=lambda: any(m.get("id") == "leave" for m in c.msgs))
        return c, result["data"]["session_id"]

    async def test_javascript_silent_music_uses_native_pongs_without_fake_viewers(self):
        from studio import app as app_mod
        c, token = await self.music_client()
        before = self.rd.state.at
        self.rd._last_viewer_at = time.monotonic() - 11.
        with unittest.mock.patch.object(app_mod, "HB_DEAD_S", .4):
            await c.pump(until=lambda: False, timeout=2.4)
        self.assertIsNone(c.close_code)
        self.assertGreaterEqual(len(c.pings), 2)
        self.assertEqual(self.rd.viewers, 0)
        self.assertGreater(self.rd.state.at, before)
        self.assertEqual(self.pad.motion_studio.session["id"], token)
        c.close()
        end = time.monotonic() + 1.
        while self.pad.motion_studio.session is not None and time.monotonic() < end:
            await asyncio.sleep(.02)
        self.assertIsNone(self.pad.motion_studio.session)

    async def test_missing_or_unmatched_native_pong_closes_and_stops_music(self):
        from studio import app as app_mod
        for mode in (None, "invalid"):
            with self.subTest(mode=mode):
                c, _ = await self.music_client()
                c.pong_mode = mode
                with unittest.mock.patch.object(app_mod, "HB_DEAD_S", .4), \
                        unittest.mock.patch.object(app_mod, "MUSIC_PONG_TIMEOUT_S", .15):
                    await c.pump(until=lambda: c.close_code is not None, timeout=2.5)
                self.assertTrue(c.pings)
                self.assertEqual(c.close_code, 4408)
                await asyncio.sleep(.1)
                self.assertIsNone(self.pad.motion_studio.session)
                c.close()

    async def test_pad_page_via_ws(self):
        """Com a página do controle aberta, recebe mensagens pad e envia o desligamento do torque ao programa principal uma vez."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/pad"})
        await c.send({"t": "cmd", "id": "w1", "name": "pad.op", "args": {"op": "watch"}})
        await c.pump(until=lambda: sum(1 for m in c.msgs if m.get("t") == "pad") >= 3, timeout=4.0)
        self.assertTrue(any(m.get("t") == "result" and m.get("id") == "w1" and m["ok"] for m in c.msgs))
        snap = [m for m in c.msgs if m.get("t") == "pad"][-1]
        self.assertIn("virtual", snap)
        c.msgs.clear()
        await c.send({"t": "cmd", "id": "r1", "name": "relax"})
        await c.pump(until=lambda: any(m.get("t") == "result" and m.get("id") == "r1" for m in c.msgs), timeout=4.0)
        self.assertTrue([m for m in c.msgs if m.get("id") == "r1"][0]["ok"])
        self.assertEqual(len([m for _, m in self.fake.calls if m == "robot.relax"]), 1)
        c.close()
        t0 = time.monotonic()
        while self.pad.snapshot()["virtual"].get("driver") is not None and time.monotonic() - t0 < 3:
            await asyncio.sleep(0.05)
        self.assertIsNone(self.pad.snapshot()["virtual"].get("driver"))

    def pads(self, c):
        return [m for m in c.msgs if m.get("t") == "pad"]

    # ---- Requisito: ao sair da página dos servos, manter os servos retidos sem desligar o torque. ----

    async def servo_open_holding(self, c):
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/servos"})
        await c.send({"t": "cmd", "id": "o1", "name": "servo.open"})
        await c.pump(until=lambda: self.servo.state == "open", timeout=5.0)
        await c.send({"t": "cmd", "id": "t1", "name": "servo.op", "args": {"op": "torque", "ids": [20, 21], "on": 1}})
        end = time.monotonic() + 5
        while self.servo.holding() < 2 and time.monotonic() < end:
            await c.pump(until=lambda: False, timeout=0.2)
        self.assertGreaterEqual(self.servo.holding(), 2)

    async def test_leaving_servo_page_keeps_session_while_holding(self):
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await self.servo_open_holding(c)
        relax0 = len([m for _, m in self.fake.calls if m == "robot.relax"])
        # Ao sair da página, servo.close {if_idle} mantém a sessão enquanto houver servos retidos.
        await c.send({"t": "hb", "seq": 2, "visible": True, "route": "/"})
        await c.send({"t": "cmd", "id": "x1", "name": "servo.close", "args": {"if_idle": True}})
        await c.pump(until=lambda: any(m.get("id") == "x1" for m in c.msgs), timeout=5.0)
        self.assertTrue(next(m for m in c.msgs if m.get("id") == "x1")["ok"])
        self.assertEqual(self.servo.state, "open")
        self.assertGreaterEqual(self.servo.holding(), 2)
        self.assertTrue(self.rd.paused)
        c.msgs.clear()
        await c.pump(until=lambda: any(m.get("t") == "state" for m in c.msgs), timeout=2.0)
        st = [m for m in c.msgs if m.get("t") == "state"][-1]
        self.assertGreaterEqual(st["servo_session"]["holding"], 2)            # Usado no aviso exibido nas outras páginas.
        self.assertEqual(len([m for _, m in self.fake.calls if m == "robot.relax"]), relax0)
        # Depois de soltar todos os servos, sair devolve o barramento normalmente.
        await c.send({"t": "cmd", "id": "t2", "name": "servo.op", "args": {"op": "torque", "on": 0}})
        end = time.monotonic() + 5
        while self.servo.holding() > 0 and time.monotonic() < end:
            await c.pump(until=lambda: False, timeout=0.2)
        await c.send({"t": "cmd", "id": "x2", "name": "servo.close", "args": {"if_idle": True}})
        await c.pump(until=lambda: any(m.get("id") == "x2" for m in c.msgs), timeout=8.0)   # Aguarda fechar o barramento e retomar a consulta.
        self.assertEqual(self.servo.state, "closed")
        self.assertFalse(self.rd.paused)
        c.msgs.clear()
        await c.pump(until=lambda: any(m.get("t") == "state" for m in c.msgs), timeout=2.0)
        st = [m for m in c.msgs if m.get("t") == "state"][-1]
        self.assertIsNone(st["servo_session"])
        self.assertIsNotNone(st["servo_handback_s"])                          # Indica que o usuário pode precisar iniciar o robotd.
        c.close()

    async def test_nobody_watching_but_holding_does_not_hand_back(self):
        """Sem visualizações e com servos retidos, não devolve nem desliga o torque; após soltá-los, devolve automaticamente."""
        from studio import app as app_mod
        token, _ = await self.login()
        with unittest.mock.patch.object(app_mod, "SERVO_IDLE_S", 0.5):
            c = WsClient(self.port, origin=self.origin, cookie=token)
            await c.open()
            await self.servo_open_holding(c)
            c.close()                                                          # Fecha a página.
            await asyncio.sleep(12.0)                                         # servo_watch verifica a cada 5 segundos.
            self.assertEqual(self.servo.state, "open")
            self.assertGreaterEqual(self.servo.holding(), 2)
            warns = [e for e in self.rd.log.recent(200) if "não devolvendo nem relaxando o torque automaticamente" in e["msg"]]
            self.assertEqual(len(warns), 1)                                    # Registra o aviso uma única vez.
            await asyncio.to_thread(self.servo.ops.handle, {"op": "torque", "on": 0})
            end = time.monotonic() + 15
            while self.servo.state == "open" and time.monotonic() < end:
                await asyncio.sleep(0.2)
        self.assertEqual(self.servo.state, "closed")
        self.assertFalse(self.rd.paused)

    async def test_pad_push_rate_follows_pad_visible_not_route(self):
        """Revisão O1: envia o controle a 10 Hz quando visível e a 1 Hz quando oculto; heartbeats antigos usam route como fallback."""
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": "/pad", "pad_visible": False})
        await c.pump(until=lambda: False, timeout=0.3)
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=2.05)
        self.assertLessEqual(len(self.pads(c)), 3)
        await c.send({"t": "hb", "seq": 2, "visible": True, "route": "/", "pad_visible": True})
        await c.pump(until=lambda: False, timeout=0.3)
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=1.0)
        snaps = self.pads(c)
        self.assertGreaterEqual(len(snaps), 7)
        # Não reenvia listas longas a cada quadro (revisão O12); envia uma versão completa ao menos uma vez por segundo.
        slim = [m for m in snaps if m.get("lists_same")]
        self.assertGreaterEqual(len(slim), len(snaps) - 2)
        self.assertTrue(all("actions" not in m["motion"] for m in slim))
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=1.2)
        self.assertTrue(any("actions" in m["motion"] for m in self.pads(c)))
        c.close()
        c2 = WsClient(self.port, origin=self.origin, cookie=token)               # Página antiga sem pad_visible no heartbeat.
        await c2.open()
        await c2.send({"t": "hb", "seq": 1, "visible": True, "route": "/pad"})
        await c2.pump(until=lambda: False, timeout=0.3)
        c2.msgs.clear()
        await c2.pump(until=lambda: False, timeout=1.0)
        self.assertGreaterEqual(len(self.pads(c2)), 7)
        c2.close()

    async def test_new_page_sticks_dropped_until_open(self):
        """Revisão O1: uma conexão nova descarta comandos do joystick até abrir a área do controle."""
        self.fake.set_posture("policy")
        await asyncio.sleep(1.2)
        token, _ = await self.login()
        c = WsClient(self.port, origin=self.origin, cookie=token)
        await c.open()
        stick = {"op": "sticks", "mode": "drive", "lx": 0, "ly": -1, "rx": 0, "ry": 0}
        await c.send({"t": "cmd", "id": "s1", "name": "pad.op", "args": dict(stick, seq=1)})
        await c.pump(until=lambda: any(m.get("id") == "s1" for m in c.msgs), timeout=3.0)
        r = next(m for m in c.msgs if m.get("id") == "s1")
        self.assertIn("dropped", r["data"])
        self.assertNotIn("robot.move", [m for _, m in self.fake.calls])
        await c.send({"t": "cmd", "id": "o1", "name": "pad.op", "args": {"op": "drive", "open": True, "seq": 2}})
        await c.pump(until=lambda: any(m.get("id") == "o1" for m in c.msgs), timeout=3.0)
        await c.send({"t": "cmd", "id": "s2", "name": "pad.op", "args": dict(stick, seq=3)})
        await c.pump(until=lambda: any(m.get("id") == "s2" for m in c.msgs), timeout=3.0)
        r = next(m for m in c.msgs if m.get("id") == "s2")
        self.assertIn("sent", r["data"], r)
        c.close()


def free_port():
    import socket
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


class ServoSessionBatch3Test(unittest.IsolatedAsyncioTestCase):
    """Testa marcador da sessão dos servos, retomada após reinício, condições de corrida e mensagens de devolução."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.tmp.name) / "state"
        self.state_dir.mkdir()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.fake = FakeRobotd(FIXTURE)
        self.s2, self.p2 = await self.fake.serve_tcp()
        self.s1 = None
        self.server = None

    async def start(self, robotd_up=True, servo=None):
        if robotd_up:
            self.s1, p1 = await self.fake.serve_tcp()
        else:
            p1 = free_port()                                # Porta sem listener: robotd está parado.
        self.p1 = p1
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{self.p2}", self.log)
        self.servo = servo or ServoSession(self.log, sim=True)
        auth = Auth(self.state_dir, self.log)
        app = build_app(auth=auth, robotd=self.rd, log=self.log, web_dir=WEB, duck={"label": "Microduck de teste"}, state_dir=str(self.state_dir),
                        servo=self.servo, dev_autologin=True)
        cfg = uvicorn.Config(app, host="127.0.0.1", port=0, ws="wsproto", http="h11", lifespan="on", log_level="critical")
        self.server = uvicorn.Server(cfg)
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.02)
        self.port = self.server.servers[0].sockets[0].getsockname()[1]
        self.origin = f"http://127.0.0.1:{self.port}"

    async def stop(self):
        if self.server is not None:
            self.server.should_exit = True
            await self.task
            self.server = None

    async def asyncTearDown(self):
        await self.stop()
        if self.servo.state == "open":
            self.servo.close()
        for sv in (self.s1, self.s2):
            if sv is not None:
                sv.close()
        self.tmp.cleanup()

    @property
    def marker(self):
        return self.state_dir / "servo-session.json"

    def logs(self, word):
        return [e for e in self.log.recent(300) if word in e["msg"]]

    async def until(self, cond, timeout=8.0):
        end = time.monotonic() + timeout
        while not cond() and time.monotonic() < end:
            await asyncio.sleep(0.05)
        return cond()

    async def client(self, route="/servos"):
        c = WsClient(self.port, origin=self.origin)
        await c.open()
        self.assertTrue(c.accepted)
        await c.send({"t": "hb", "seq": 1, "visible": True, "route": route})
        return c

    async def cmd(self, c, cid, name, args=None, timeout=10.0):
        await c.send({"t": "cmd", "id": cid, "name": name, "args": args or {}})
        await c.pump(until=lambda: any(m.get("id") == cid for m in c.msgs), timeout=timeout)
        return next((m for m in c.msgs if m.get("id") == cid), None)

    async def state(self, c):
        """Retorna o estado mais recente após receber os quadros pendentes no socket."""
        c.msgs.clear()
        await c.pump(until=lambda: False, timeout=0.4)
        await c.pump(until=lambda: any(m.get("t") == "state" for m in c.msgs), timeout=3.0)
        return [m for m in c.msgs if m.get("t") == "state"][-1]

    async def open_holding(self, c):
        r = await self.cmd(c, "o1", "servo.open")
        self.assertTrue(r["ok"], r)
        r = await self.cmd(c, "t1", "servo.op", {"op": "torque", "ids": [20, 21], "on": 1})
        self.assertTrue(r["ok"], r)

    # ---- D1: marcador da sessão, encerramento sem soltar os servos e retomada após reinício ----

    async def test_native_persistent_guard_prevents_boot_servo_autorestore(self):
        self.marker.write_text(json.dumps({'v':1,'sim':True,'at':1.7e9,'by':'x'}),encoding='utf-8')
        with unittest.mock.patch('studio.helper.native_update_state',return_value={'active':True,'phase':'recovery_required'}), \
             unittest.mock.patch('studio.app._bus_take',return_value=(True,None)) as take:
            await self.start(robotd_up=False)
            self.assertTrue(await self.until(lambda:self.logs('Proteção de atualização do programa principal'),timeout=2))
            self.assertEqual(self.servo.state,'closed')
            take.assert_not_called()
            self.assertTrue(self.marker.exists())

    async def test_marker_kept_on_exit_and_session_restored_after_restart(self):
        await self.start(robotd_up=True)
        c = await self.client()
        await self.open_holding(c)
        self.assertTrue(self.marker.exists())                                   # O marcador é gravado ao abrir o barramento.
        m = json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertTrue(m["sim"])
        self.assertIn("by", m)
        c.close()
        sim = self.servo.sim_serial
        await self.stop()                                                       # Encerra o Studio normalmente.
        self.assertEqual([sim._by_id(i).r[40] for i in (20, 21)], [1, 1])      # Mantém o torque ao encerrar.
        self.assertTrue(self.marker.exists())
        self.assertTrue(self.logs("Studio encerrado: sessão de servos aberta"))
        # Após reiniciar, retoma a sessão mesmo com robotd parado.
        self.s1.close()
        self.s1 = None
        self.servo = ServoSession(self.log, sim=True)
        await self.start(robotd_up=False, servo=self.servo)
        self.assertTrue(await self.until(lambda: self.servo.state == "open"))
        self.assertTrue(self.servo.restored)
        self.assertTrue(self.rd.paused)
        self.assertTrue(await self.until(lambda: self.logs("Sessão restaurada")))
        c = await self.client("/")
        st = await self.state(c)
        self.assertTrue(st["servo_session"]["restored"])
        self.assertEqual(st["posture"], "servo_session")
        r = await self.cmd(c, "r1", "relax")                                     # O botão superior desliga o torque pelo barramento.
        self.assertTrue(r["ok"], r)
        c.close()

    async def test_bad_marker_does_not_crash(self):
        self.marker.write_text("{inválido", encoding="utf-8")
        await self.start(robotd_up=False)
        self.assertTrue(await self.until(lambda: self.servo.state == "open"))
        self.assertTrue(self.logs("Marcador da sessão de servos inválido"))
        self.assertTrue(await self.until(lambda: self.logs("Sessão restaurada")))
        self.assertTrue(json.loads(self.marker.read_text(encoding="utf-8"))["sim"])   # Regrava o marcador ao retomar a sessão.

    async def test_marker_with_robotd_running_is_dropped(self):
        self.marker.write_text(json.dumps({"v": 1, "sim": True, "port": None, "at": 1.7e9, "by": "x"}), encoding="utf-8")
        await self.start(robotd_up=True)
        self.assertTrue(await self.until(lambda: not self.marker.exists()))
        self.assertEqual(self.servo.state, "closed")
        self.assertTrue(self.logs("o programa principal está em execução"))

    async def test_restore_failure_shows_orphan_and_relax_points_to_servo_page(self):
        self.marker.write_text(json.dumps({"v": 1, "sim": False, "port": None, "at": 1.7e9, "by": "x"}), encoding="utf-8")
        await self.start(robotd_up=False, servo=ServoSession(self.log, sim=False, port=None))
        self.assertTrue(await self.until(lambda: self.servo.orphan is not None))
        self.assertTrue(self.marker.exists())                                   # Sem retomada, mantém o marcador.
        c = await self.client("/")
        st = await self.state(c)
        self.assertIsNotNone(st["servo_orphan"])
        self.assertEqual(st["estop"]["state"], "unavailable")
        self.assertIn("sessão de servos anterior não foi retomada", st["estop"]["why"])
        r = await self.cmd(c, "r1", "relax")
        self.assertFalse(r["ok"])
        self.assertIn("sessão de servos anterior não foi retomada", r["reason"])
        c.close()

    async def test_handback_removes_marker_and_note_stays_until_robotd_connects(self):
        """D12: mantém o aviso de devolução até o programa principal se conectar, sem expirar após dez minutos."""
        await self.start(robotd_up=False)
        c = await self.client()
        await self.open_holding(c)
        r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.marker.exists())
        self.servo.handed_back_at -= 700                                        # Simula mais de dez minutos decorridos.
        await asyncio.sleep(2.5)
        st = await self.state(c)
        self.assertIsNotNone(st["servo_handback_s"])
        self.s1, _ = await self.fake.serve_tcp(port=self.p1)                     # Inicia o programa principal.
        ok = False
        end = time.monotonic() + 15
        while time.monotonic() < end and not ok:
            st = await self.state(c)
            ok = st["servo_handback_s"] is None
        self.assertTrue(ok)
        c.close()

    async def test_helper_available_is_exposed_for_handback_note(self):
        """D12: informa à página quando o helper está disponível para iniciar o programa principal."""
        await self.start(robotd_up=False)
        self.servo.helper_available = True
        self.servo.handed_back_at = time.monotonic()
        c = await self.client("/")
        st = await self.state(c)
        self.assertTrue(st["servo_helper"])
        self.assertIsNotNone(st["servo_handback_s"])
        c.close()

    async def test_open_port_switch_while_open_is_refused_and_keeps_paused(self):
        """F1: recusa trocar a porta durante o ajuste e mantém sessão, porta, torque e robotd inalterados."""
        await self.start()
        c = await self.client()
        await self.open_holding(c)
        before = (self.servo.port, self.servo.sim)
        r = await self.cmd(c, "p1", "servo.open", {"port": "/dev/ttyS99"})
        self.assertFalse(r["ok"])
        self.assertIn("Não troque a porta serial", r["reason"])
        self.assertEqual(self.servo.state, "open")
        self.assertEqual((self.servo.port, self.servo.sim), before)
        self.assertTrue(self.rd.paused)
        self.assertEqual([self.servo.sim_serial._by_id(i).r[40] for i in (20, 21)], [1, 1])
        c.close()

    async def test_marker_from_other_boot_is_dropped_without_take(self):
        """F2: descarta marcadores de outra inicialização sem assumir o barramento nem pausar o robotd."""
        self.marker.write_text(json.dumps({"v": 1, "sim": True, "port": None, "at": 1.7e9, "by": "x",
                                           "boot_id": "old-boot"}), encoding="utf-8")
        with unittest.mock.patch("studio.app.boot_id", return_value="new-boot"), \
             unittest.mock.patch("studio.app._bus_take") as take:
            await self.start(robotd_up=False)
            self.assertTrue(await self.until(lambda: not self.marker.exists()))
            await asyncio.sleep(0.1)
            self.assertEqual(self.servo.state, "closed")
            self.assertFalse(self.rd.paused)
            self.assertTrue(self.logs("houve perda de energia"))
            self.assertFalse(self.logs("Sessão restaurada"))
            self.assertFalse(take.called)

    async def test_marker_with_same_boot_id_is_restored(self):
        """F2: retoma normalmente os marcadores criados na inicialização atual."""
        self.marker.write_text(json.dumps({"v": 1, "sim": True, "port": None, "at": 1.7e9, "by": "x",
                                           "boot_id": "same-boot"}), encoding="utf-8")
        with unittest.mock.patch("studio.app.boot_id", return_value="same-boot"):
            await self.start(robotd_up=False)
            self.assertTrue(await self.until(lambda: self.servo.state == "open"))
            self.assertTrue(self.servo.restored)
            self.assertTrue(self.rd.paused)
            self.assertTrue(await self.until(lambda: self.logs("Sessão restaurada")))
            m = json.loads(self.marker.read_text(encoding="utf-8"))
            self.assertEqual(m["boot_id"], "same-boot")

    async def test_handback_note_reports_unconfirmed_relax(self):
        """F6: informa à página quais servos não confirmaram o desligamento do torque."""
        await self.start(robotd_up=False)
        c = await self.client()
        await self.open_holding(c)
        self.servo.sim_serial._by_id(14).muted = {40}
        r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertIn("#14", self.servo.handback_note)
        self.assertIn("sem confirmação", self.servo.handback_note)
        st = await self.state(c)
        self.assertEqual(st["servo_handback_note"], self.servo.handback_note)
        c.close()

    async def test_handback_keeps_marker_when_helper_fails_and_flag_remains(self):
        """F7: se o helper falhar e a trava persistir, mantém o marcador para retomar após reiniciar o Studio."""
        await self.start(robotd_up=False)
        c = await self.client()
        await self.open_holding(c)
        with unittest.mock.patch.object(helper, "available", return_value=True), \
             unittest.mock.patch.object(helper, "bus_give_back",
                                        return_value=(False, "soft_failed", {"result": "soft_failed"})), \
             unittest.mock.patch.object(helper, "flag_present", return_value=True):
            r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.marker.exists())
        self.assertIn("Não foi possível iniciar o programa principal", self.servo.giveback_error)
        self.assertIn("sinalizador", self.servo.giveback_hint)
        st = await self.state(c)
        self.assertEqual(st["servo_giveback_error"], self.servo.giveback_error)
        self.assertEqual(st["servo_giveback_hint"], self.servo.giveback_hint)
        c.close()

    async def test_handback_drops_marker_when_helper_fails_without_flag(self):
        """F7: se o helper falhar sem deixar a trava, remove o marcador e pede para iniciar o programa principal manualmente."""
        await self.start(robotd_up=False)
        c = await self.client()
        await self.open_holding(c)
        with unittest.mock.patch.object(helper, "available", return_value=True), \
             unittest.mock.patch.object(helper, "bus_give_back",
                                        return_value=(False, "soft_failed", {"result": "soft_failed"})), \
             unittest.mock.patch.object(helper, "flag_present", return_value=False):
            r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertFalse(self.marker.exists())
        self.assertIn("sudo systemctl start robotd", self.servo.giveback_hint)
        c.close()

    async def test_take_failure_with_flag_adds_recovery_hint(self):
        """F8: inclui instruções de recuperação quando a trava impede o programa principal de iniciar."""
        await self.start(robotd_up=False)
        c = await self.client()
        with unittest.mock.patch.object(helper, "available", return_value=True), \
             unittest.mock.patch.object(helper, "bus_take",
                                        return_value=(False, "port_busy", {"result": "port_busy"})), \
             unittest.mock.patch.object(helper, "flag_present", return_value=True):
            r = await self.cmd(c, "o1", "servo.open")
        self.assertFalse(r["ok"])
        self.assertIn("sinalizador", r["reason"])
        self.assertFalse(self.rd.paused)
        self.assertEqual(self.servo.state, "closed")
        c.close()

    async def test_marker_write_failure_is_visible_and_keeps_session(self):
        """F10: mantém a sessão se não conseguir gravar o marcador e exibe o erro na página."""
        await self.start()
        c = await self.client()
        real_replace = os.replace

        def fail_marker(src, dst):
            if str(dst).endswith("servo-session.json"):
                raise OSError("disk full")
            return real_replace(src, dst)

        with unittest.mock.patch("studio.app.os.replace", side_effect=fail_marker):
            r = await self.cmd(c, "o1", "servo.open")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.servo.state, "open")
        self.assertIn("Não foi possível gravar o marcador da sessão", self.servo.marker_error)
        st = await self.state(c)
        self.assertEqual(st["servo_marker_error"], self.servo.marker_error)
        r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertIsNone(self.servo.marker_error)
        c.close()

    async def test_handback_without_helper_does_not_claim_robotd_started(self):
        """F12: sem o helper instalado, pede para iniciar o programa principal manualmente."""
        await self.start(robotd_up=False)
        c = await self.client()
        await self.open_holding(c)
        with unittest.mock.patch.object(helper, "available", return_value=False):
            r = await self.cmd(c, "x1", "servo.close", {}, timeout=15)
        self.assertTrue(r["ok"], r)
        self.assertTrue(self.logs("helper não instalado"))
        self.assertFalse(self.logs("Programa principal iniciado"))
        c.close()

    # ---- D2 e D3: condições de corrida e verificações ao sair da página ----

    async def test_torque_then_leave_in_one_packet_keeps_holding(self):
        """D2: se retenção e saída chegam no mesmo pacote TCP, aguarda a retenção e verifica o torque antes de devolver."""
        await self.start()
        c = await self.client()
        r = await self.cmd(c, "o1", "servo.open")
        self.assertTrue(r["ok"])
        data = b"".join(c.ws.send(TextMessage(json.dumps(m))) for m in (
            {"t": "cmd", "id": "tq", "name": "servo.op", "args": {"op": "torque", "ids": [20, 21], "on": 1}},
            {"t": "hb", "seq": 9, "visible": True, "route": "/"},
            {"t": "cmd", "id": "x", "name": "servo.close", "args": {"if_idle": True}}))
        c.w.write(data)
        await c.w.drain()
        await c.pump(until=lambda: sum(1 for m in c.msgs if m.get("id") in ("tq", "x")) >= 2, timeout=10)
        res = {m["id"]: m for m in c.msgs if m.get("id") in ("tq", "x")}
        self.assertTrue(res["tq"]["ok"], res)
        self.assertIn("2  servos retidos", res["x"]["reason"])
        self.assertEqual(self.servo.state, "open")
        self.assertEqual([self.servo.sim_serial._by_id(i).r[40] for i in (20, 21)], [1, 1])
        c.close()

    async def test_torque_then_leave_same_packet_40_times(self):
        """D2: repete 40 vezes retenção e saída no mesmo pacote para evitar torque ativo após devolver o barramento."""
        await self.start()
        c = await self.client()
        self.assertTrue((await self.cmd(c, "o1", "servo.open"))["ok"])
        try:
            for n in range(40):
                c.msgs.clear()
                tq_id, x_id = f"tq{n}", f"x{n}"
                payload = b"".join(c.ws.send(TextMessage(json.dumps(m))) for m in (
                    {"t": "cmd", "id": tq_id, "name": "servo.op", "args": {"op": "torque", "ids": [20, 21], "on": 1}},
                    {"t": "hb", "seq": 20 + n, "visible": True, "route": "/"},
                    {"t": "cmd", "id": x_id, "name": "servo.close", "args": {"if_idle": True}}))
                c.w.write(payload)
                await c.w.drain()
                await c.pump(until=lambda: sum(1 for m in c.msgs if m.get("id") in (tq_id, x_id)) >= 2, timeout=10)
                res = {m["id"]: m for m in c.msgs if m.get("id") in (tq_id, x_id)}
                self.assertTrue(res[tq_id]["ok"], f"Retenção {n + 1}: {res[tq_id]}")
                self.assertIn("2  servos retidos", res[x_id]["reason"], f"Saída {n + 1}: {res[x_id]}")
                self.assertEqual(self.servo.state, "open", f"A sessão foi devolvida após a saída {n + 1}.")
                self.assertEqual([self.servo.sim_serial._by_id(i).r[40] for i in (20, 21)], [1, 1],
                                 f"Servos ainda retidos após a saída {n + 1}.")
                off = await self.cmd(c, f"off{n}", "servo.op", {"op": "torque", "ids": [20, 21], "on": 0})
                self.assertTrue(off["ok"], f"Liberação {n + 1}: {off}")
        finally:
            c.close()

    async def test_leave_while_calibrating_keeps_session_and_calibration_finishes(self):
        """D3a: sair durante a calibração não devolve o barramento e permite calibrar os 15 servos."""
        await self.start()
        c = await self.client()
        self.assertTrue((await self.cmd(c, "o1", "servo.open"))["ok"])
        # Sai da página no mesmo pacote em que inicia a calibração, antes que a simulação termine.
        c.w.write(b"".join(c.ws.send(TextMessage(json.dumps(m))) for m in (
            {"t": "cmd", "id": "cal", "name": "servo.op", "args": {"op": "calibrate", "ids": "20-24,30-34,10-14"}},
            {"t": "hb", "seq": 2, "visible": True, "route": "/"},
            {"t": "cmd", "id": "x", "name": "servo.close", "args": {"if_idle": True}})))
        await c.w.drain()
        await c.pump(until=lambda: any(m.get("id") == "x" for m in c.msgs), timeout=10)
        r = next(m for m in c.msgs if m.get("id") == "x")
        self.assertIn("calibração", r["reason"])
        await c.pump(until=lambda: any(m.get("id") == "cal" for m in c.msgs), timeout=30)
        cal = next(m for m in c.msgs if m.get("id") == "cal")
        self.assertTrue(cal["ok"], cal)
        self.assertEqual(cal["data"]["bad"], {})
        self.assertEqual(len(cal["data"]["ok"]), 15)
        self.assertEqual(self.servo.state, "open")
        c.close()

    async def test_other_page_on_servos_keeps_session(self):
        """D3b: uma página não devolve a sessão enquanto outra página dos servos continua aberta."""
        await self.start()
        a = await self.client()
        self.assertTrue((await self.cmd(a, "o1", "servo.open"))["ok"])
        b = await self.client()
        await b.send({"t": "hb", "seq": 2, "visible": True, "route": "/"})
        r = await self.cmd(b, "x", "servo.close", {"if_idle": True})
        self.assertIn("Ainda há 1 páginas abertas", r["reason"])
        self.assertEqual(self.servo.state, "open")
        a.close()
        b.close()

    async def test_unreadable_torque_counts_as_maybe_holding(self):
        """D3c: trata torque ilegível como possivelmente ativo e não devolve o barramento ao sair."""
        await self.start()
        c = await self.client()
        self.assertTrue((await self.cmd(c, "o1", "servo.open"))["ok"])
        self.servo.sim_serial._by_id(14).muted = {40}
        await c.send({"t": "hb", "seq": 2, "visible": True, "route": "/"})
        r = await self.cmd(c, "x", "servo.close", {"if_idle": True})
        self.assertIn("1  servo sem leitura de torque", r["reason"])
        self.assertEqual(self.servo.state, "open")
        st = await self.state(c)
        self.assertEqual(st["servo_session"]["unknown"], 1)
        c.close()

    # ---- D9: robotd iniciado manualmente durante a sessão ----

    async def test_robotd_started_by_hand_closes_bus_without_writing(self):
        await self.start(robotd_up=True)
        self.servo.probe_robotd = True                     # Ativa a verificação do robotd nesta simulação.
        c = await self.client()
        await self.open_holding(c)
        sim = self.servo.sim_serial
        # close() publica o estado da porta antes de o observador remover o marcador e informar o conflito.
        self.assertTrue(await self.until(lambda: self.servo.state == "closed" and not self.rd.paused
                                        and not self.marker.exists() and bool(self.logs("O programa principal foi iniciado manualmente")), timeout=12))
        self.assertEqual([sim._by_id(i).r[40] for i in (20, 21)], [1, 1])      # Não grava nos servos.
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.rd.paused)
        self.assertTrue(self.logs("O programa principal foi iniciado manualmente"))
        st = await self.state(c)
        self.assertIsNotNone(st["servo_conflict_s"])
        c.close()


if __name__ == "__main__":
    unittest.main()
