"""Testes de RPC, robotd, parada de emergência e estado. Execute com Python 3.13, como na placa:
    py -3.13 -I run_tests.py ou, no robô, python3 -I run_tests.py
O robotd simulado reproduz tests/fixtures/now-20261018.jsonl, gravado no MicroDuck 2 em 18/10 no modo de movimento, mantendo a postura em pé.
"""
import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from fake_robotd import FakeRobotd  # noqa: E402
from studio import robotd as robotd_mod  # noqa: E402
from studio.estop import EStop, relaxed, robotd_up  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Robotd  # noqa: E402
from studio.rpc import LINE_LIMIT, Conn, RpcError, Timeout, Unreachable  # noqa: E402
from studio.state import posture, summarize, tilt_deg  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


def quiet_log(tmp="."):
    return Log(Path(tmp) / "_testlogs", echo=False, background=False)


async def raw_server(handler):
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, f"tcp:127.0.0.1:{server.sockets[0].getsockname()[1]}"


class RpcTest(unittest.IsolatedAsyncioTestCase):
    async def test_half_lines_notifications_and_garbage(self):
        async def h(r, w):
            req = json.loads(await r.readline())
            w.write(b"not json at all\n")
            w.write(b'{"jsonrpc":"2.0","method":"robot.state","params":{}}\n')
            body = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": {"ok": 1}}).encode() + b"\n"
            w.write(body[:7]); await w.drain(); await asyncio.sleep(0.05)
            w.write(body[7:]); await w.drain()
        server, addr = await raw_server(h)
        async with server:
            c = Conn(addr)
            self.assertEqual(await c.call("x", timeout=1), {"ok": 1})
            self.assertEqual(c.bad_lines, 1)
            c.close()

    async def test_long_line_ok_and_too_long_is_unreachable(self):
        big = "x" * 200_000

        async def h(r, w):
            while True:
                line = await r.readline()
                if not line:
                    return
                req = json.loads(line)
                pad = big if req["method"] == "big" else "y" * (LINE_LIMIT + 10)
                w.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": pad}).encode() + b"\n")
                await w.drain()
        server, addr = await raw_server(h)
        async with server:
            c = Conn(addr)
            self.assertEqual(len(await c.call("big", timeout=2)), 200_000)
            with self.assertRaises(Unreachable):
                await c.call("huge", timeout=2)
            c.close()

    async def test_timeout_closes_and_next_call_reconnects(self):
        n = {"conns": 0}

        async def h(r, w):
            n["conns"] += 1
            req = json.loads(await r.readline())
            if n["conns"] == 1:
                await asyncio.sleep(2)      # A primeira conexão não responde de propósito.
                return
            w.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": "late"}).encode() + b"\n")
            await w.drain()
        server, addr = await raw_server(h)
        async with server:
            c = Conn(addr)
            with self.assertRaises(Timeout):
                await c.call("slow", timeout=0.2)
            self.assertEqual(await c.call("again", timeout=1), "late")
            self.assertEqual(n["conns"], 2)
            c.close()

    async def test_unreachable_vs_rpc_error(self):
        c = Conn("tcp:127.0.0.1:1")
        with self.assertRaises(Unreachable):
            await c.call("x", timeout=3.0)     # No Windows, a conexão recusada leva cerca de 2 s para ser reportada; no socket Unix do robô, é imediato.
        fake = FakeRobotd(FIXTURE)
        server, port = await fake.serve_tcp()
        async with server:
            c = Conn(f"tcp:127.0.0.1:{port}")
            with self.assertRaises(RpcError) as e:
                await c.call("hello", {}, timeout=1)        # No robô real, a chamada é rejeitada sem api_version.
            self.assertEqual(e.exception.code, -32602)
            self.assertEqual((await c.call("hello", {"api_version": 40}))["api_version"], 40)
            c.close()      # No Python 3.12+, server.wait_closed() aguarda todas as conexões encerrarem.


class EStopTest(unittest.TestCase):
    def bus(self, **kw):
        b = {"mode": "motion", "phase": "control", "torque_off_pending": False,
             "native": {"torque_state_confirmed": True, "hd1910": {"restore_pending": False, "temporary_gains_applied": False}}}
        for k, v in kw.items():
            if k in ("torque_state_confirmed",):
                b["native"][k] = v
            elif k in ("restore_pending", "temporary_gains_applied"):
                b["native"]["hd1910"][k] = v
            else:
                b[k] = v
        return b

    def test_relaxed_rules(self):
        self.assertFalse(relaxed(self.bus()))
        self.assertTrue(relaxed(self.bus(torque_state_confirmed=False)))
        self.assertFalse(relaxed(self.bus(torque_state_confirmed=False, restore_pending=True)))
        self.assertFalse(relaxed(self.bus(torque_state_confirmed=False, torque_off_pending=True)))
        self.assertTrue(relaxed({"mode": "commissioning", "torque_state": "off", "torque_off_pending": None}))
        self.assertFalse(relaxed({"mode": "commissioning", "torque_state": "single_joint_enabled"}))
        self.assertIsNone(relaxed(None))
        self.assertIsNone(relaxed({"mode": "motion"}))

    def test_states(self):
        e = EStop()
        st = lambda b, now, present=True, age=0.1: e.status(present=present, bus=b, bus_age_s=age, now=now)["state"]  # noqa: E731
        self.assertEqual(st(self.bus(), 0), "ready")
        self.assertEqual(st(self.bus(), 0, present=False), "unavailable")
        self.assertEqual(st(self.bus(), 0, age=5), "ready")                     # Ainda é possível acionar mesmo sem ler o estado.
        self.assertIn("Não foi possível ler", e.status(present=True, bus=self.bus(), bus_age_s=5, now=0)["why"])
        self.assertEqual(st(self.bus(phase="waiting_for_bus"), 0), "unavailable")
        limp = self.bus(torque_state_confirmed=False, restore_pending=False, temporary_gains_applied=False)
        self.assertEqual(st(limp, 0), "confirmed")                              # Os servos já estavam sem torque.
        self.assertEqual(st(limp, 0, age=2.0), "confirmed")                     # Uma atualização de 1 Hz não deve fazer o estado piscar.
        self.assertEqual(st(limp, 0, age=3.0), "ready")                         # Uma leitura antiga não deve indicar torque liberado.

    def test_confirm_needs_a_readback_asked_after_the_ack(self):
        """Revisão #3: consultas anteriores ao pressionamento ou à confirmação não validam a ação."""
        e = EStop()
        limp = self.bus(torque_state_confirmed=False, restore_pending=False, temporary_gains_applied=False)
        e.press("computador", now=100)
        self.assertEqual(e.status(present=True, bus=limp, bus_age_s=0.1, now=100.05)["state"], "pending")
        self.assertFalse(e.on_bus(limp, asked_at=99.9, now=100.1))             # A resposta ainda não chegou.
        e.sent(100.0, now=100.2)
        self.assertFalse(e.on_bus(limp, asked_at=100.15, now=100.3))           # Consulta enviada antes da confirmação.
        self.assertTrue(e.on_bus(limp, asked_at=100.25, now=100.4))
        self.assertEqual(e.confirm_ms, 400)
        self.assertFalse(e.active)
        self.assertEqual(e.status(present=True, bus=limp, bus_age_s=0.1, now=100.5)["state"], "confirmed")

    def test_finished_attempt_never_acts_again(self):
        """Revisão #1: se alguém reativar os servos depois da confirmação, o Studio não deve liberá-los novamente."""
        e = EStop()
        limp = self.bus(torque_state_confirmed=False, restore_pending=False, temporary_gains_applied=False)
        e.press("computador", now=100)
        e.sent(100.0, now=100.01)
        self.assertTrue(e.on_bus(limp, asked_at=100.02, now=100.3))
        self.assertFalse(e.active)
        self.assertIsNone(e.elapsed(now=400))                                   # A tarefa de monitoramento encerra ao receber None.
        self.assertEqual(e.status(present=True, bus=self.bus(), bus_age_s=0.1, now=400)["state"], "ready")
        self.assertFalse(e.on_bus(self.bus(), asked_at=400, now=400))

    def test_second_press_waits_for_its_own_ack(self):
        """Revisão #2: ao pressionar duas vezes, a consulta anterior ao segundo toque não conta."""
        e = EStop()
        limp = self.bus(torque_state_confirmed=False, restore_pending=False, temporary_gains_applied=False)
        e.press("computador", now=0)
        e.sent(0.0, now=0.003)
        e.press("computador", now=1.0)
        self.assertIsNone(e.sent_at)
        self.assertFalse(e.on_bus(limp, asked_at=0.95, now=1.02))             # Após a primeira resposta, mas antes do segundo pressionamento.
        e.sent(0.5, now=1.05)                                                   # Um envio iniciado antes, enquanto robotd estava travado, não conta.
        self.assertIsNone(e.sent_at)
        e.sent(1.0, now=1.05)
        self.assertTrue(e.on_bus(limp, asked_at=1.06, now=1.2))
        self.assertEqual(e.confirm_ms, 200)

    def test_failed_resend_after_ack_keeps_waiting(self):
        """Revisão #4: se a primeira tentativa foi enviada e a seguinte falhar, aguarde a leitura e registre o motivo no timeout."""
        e = EStop()
        e.press("computador", now=0)
        e.sent(0.0, now=0.01)
        e.send_failed(2.0, "没发出去：busy", now=2.1)
        self.assertTrue(e.active)
        self.assertEqual(e.send_error, "没发出去：busy")
        e2 = EStop()
        e2.press("电脑", now=0)
        e2.send_failed(0.0, "没发出去：连不上", now=0.2)                       # 一次回执都没有：这次就算失败
        self.assertFalse(e2.active)
        self.assertEqual(e2.outcome, "send_failed")

    def test_saw_torque_off_stops_resend(self):
        e = EStop()
        half = self.bus(torque_state_confirmed=False, restore_pending=True)     # O torque está desligado, mas a flag hd1910 permanece.
        e.press("computador", now=0)
        e.sent(0.0, now=0.01)
        self.assertFalse(e.on_bus(half, asked_at=0.1, now=0.2))
        self.assertTrue(e.saw_off)

    def test_pending_wins_over_absent(self):
        """Revisão #6: se robotd acabou de voltar e a confirmação chegou durante a espera da consulta, mostre a liberação em andamento."""
        e = EStop()
        e.press("computador", now=0)
        self.assertEqual(e.status(present=False, bus=None, bus_age_s=None, now=0.1)["state"], "pending")

    def test_timeout_shows_then_clears(self):
        e = EStop()
        e.press("celular", now=200)
        e.finish("timeout", "Liberação não confirmada após 8 s", now=208)
        self.assertEqual(e.status(present=True, bus=self.bus(), bus_age_s=0.1, now=209)["state"], "unavailable")
        self.assertEqual(e.status(present=True, bus=self.bus(), bus_age_s=0.1, now=215)["state"], "ready")

    def test_unavailable_wording_by_mode(self):
        e = EStop()
        why = e.status(present=False, bus=None, bus_age_s=None)["why"]
        self.assertIn("desligar a alimentação", why)
        e.press("teste", now=1)
        e.finish("send_failed", "Não enviado", now=1)
        why = e.status(present=True, bus=self.bus(), bus_age_s=0.1, now=2)["why"]
        self.assertIn("controle", why)


class StateTest(unittest.TestCase):
    def test_posture_from_real_fixture(self):
        fake = FakeRobotd(FIXTURE)
        self.assertEqual(posture(True, fake.bus, fake.policies, fake.frames[0]), "holding")
        # homed fica true antes de a articulação retornar à posição HOME (busStatus inclui a diferença home_start_guard do robotd simulado).
        self.assertTrue(fake.bus["home_start_guard"]["ready"])
        lagging = dict(fake.bus, home_start_guard=dict(fake.bus["home_start_guard"], ready=False, max_joint_error_deg=12.3))
        self.assertEqual(posture(True, lagging, fake.policies, fake.frames[0]), "homing")
        legacy = dict(fake.bus)
        legacy.pop("home_start_guard", None)          # Versões antigas do robotd não têm esse campo; então use apenas homed.
        self.assertEqual(posture(True, legacy, fake.policies, fake.frames[0]), "holding")
        for p, want in (("limp", "limp"), ("policy", "policy"), ("commissioning", "commissioning"), ("starting", "starting")):
            fake.set_posture(p)
            self.assertEqual(posture(True, fake.bus, fake.policies, fake.frames[0]), want, p)
        self.assertEqual(posture(False, None, None, None), "absent")
        fake.set_posture("policy")
        walking = dict(fake.frames[0], move={"applied": [0.2, 0, 0]})
        self.assertEqual(posture(True, fake.bus, fake.policies, walking), "walking")
        self.assertEqual(posture(True, fake.bus, dict(fake.policies, sitting=True), walking), "sitting")

    def test_tilt(self):
        self.assertAlmostEqual(tilt_deg([0, 0, -1]), 0.0)
        g = [0.17364817766693033, 0, -0.984807753012208]          # Inclinação para a frente de 10°.
        self.assertAlmostEqual(tilt_deg(g), 10.0, places=4)
        self.assertIsNone(tilt_deg(None))


class RobotdTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", quiet_log())
        self.rd.start()
        for _ in range(100):
            if self.rd.bus.value and self.rd.health.value and self.rd.pad.value:
                break
            await asyncio.sleep(0.02)

    async def asyncTearDown(self):
        await self.rd.stop()
        self.s1.close()
        self.s2.close()

    async def test_snapshot_from_real_data(self):
        s = summarize(self.rd, {"label": "MicroDuck 2"})
        self.assertEqual(s["posture"], "holding")
        self.assertTrue(s["robotd_ok"])
        self.assertEqual(s["mode"], "motion")
        self.assertAlmostEqual(s["battery"]["pct"], 58.77, places=1)
        self.assertEqual(s["servos"]["online"], 15)
        self.assertEqual(s["imu"]["status"], "ok")
        self.assertFalse(s["pad"]["connected"])
        self.assertEqual(s["estop"]["state"], "ready")
        self.assertFalse(any("placa" in t["msg"] for t in s["todo"]))  # A gravação estava a 78 °C; abaixo de 80 °C não gera alerta.

    async def wait_for(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    def relax_calls(self):
        return len([m for _, m in self.fake.calls if m == "robot.relax"])

    async def test_no_resend_after_confirm_and_restand(self):
        """Revisão #1: depois de confirmar a liberação, levantar o robô pelo controle não deve provocar uma nova liberação automática."""
        await asyncio.sleep(0.2)
        self.rd.set_viewers(0)                                         # O comportamento deve valer mesmo sem páginas abertas.
        self.assertTrue((await self.rd.relax("teste"))[0])
        self.assertTrue(await self.wait_for(lambda: self.rd.estop.outcome == "confirmed"))
        self.fake.stand_up()
        for _ in range(30):                                            # 3 秒，超过 2 秒补发点；期间一直有人在读状态
            summarize(self.rd, {})
            await asyncio.sleep(0.1)
        self.assertEqual(self.relax_calls(), 1)
        self.assertEqual(summarize(self.rd, {})["posture"], "holding")

    async def test_first_relax_after_restart_succeeds(self):
        """Revisão #2: a primeira liberação após reiniciar robotd não deve falhar."""
        await asyncio.sleep(0.3)
        self.fake.restart(0.05)                                        # Encerra as conexões atuais e retorna após 0,05 s.
        accepted, why = await self.rd.relax("teste")
        self.assertTrue(accepted, why)
        self.assertTrue(await self.wait_for(lambda: self.rd.estop.outcome == "confirmed", 4))

    async def test_second_press_while_robotd_stuck_sends_again(self):
        """复核 #3：robotd 卡住时按一次，1 秒后再按：第二次要自己发，不能合并进卡住的那次。"""
        self.fake.delays["robot.relax"] = 2.0
        await asyncio.sleep(0.2)
        first = asyncio.create_task(self.rd.relax("teste"))
        await asyncio.sleep(1.0)
        second = asyncio.create_task(self.rd.relax("teste"))
        await asyncio.sleep(0.2)
        self.assertEqual(self.relax_calls(), 2)
        await asyncio.gather(first, second)

    async def test_log_failure_does_not_block_relax(self):
        """Revisão #1: a liberação deve ser enviada mesmo se não for possível escrever em stdout, como em uma sessão SSH fechada."""
        class Broken:
            def write(self, *_):
                raise OSError(5, "Input/output error")

            def flush(self):
                raise OSError(5, "Input/output error")
        noisy = Log(Path(".") / "_testlogs", echo=True, background=False)
        self.rd.log = noisy
        with mock.patch("sys.stdout", Broken()):
            accepted, why = await self.rd.relax("teste")
        self.assertTrue(accepted, why)
        self.assertEqual(self.relax_calls(), 1)
        self.assertGreater(noisy.write_errors, 0)

    async def test_slow_calibration_status_does_not_block_bus(self):
        """Revisão #8: uma consulta lenta de calibração usa conexão separada; busStatus continua a cada segundo."""
        await self.rd.stop()
        self.fake.delays["robot.busCommand"] = 4.0
        self.rd = Robotd(self.rd.addr, self.rd.cfg.addr, quiet_log())
        self.rd.start()
        await asyncio.sleep(2.0)
        self.assertIsNotNone(self.rd.bus.age())
        self.assertLess(self.rd.bus.age(), 1.5)

    async def test_relax_right_after_robotd_comes_back(self):
        """复核 #6：robotd 刚回来、轮询还在退避里睡：按下后马上显示卸力中，并很快确认。"""
        self.fake.restart(2.0)
        await asyncio.sleep(2.1)
        accepted, why = await self.rd.relax("teste")
        self.assertTrue(accepted, why)
        self.assertIn(summarize(self.rd, {})["estop"]["state"], ("pending", "confirmed"))
        self.assertTrue(await self.wait_for(lambda: self.rd.estop.outcome == "confirmed", 3))

    async def test_relax_waits_for_hd1910_flags(self):
        self.fake.hd_delay = 0.6                                       # 扭矩先确认 OFF，hd1910 两个标志晚 0.6 秒清
        await asyncio.sleep(0.2)
        await self.rd.relax("teste")
        await asyncio.sleep(0.6)                                       # 0.3 秒时扭矩已确认 OFF，标志还在
        self.assertTrue(self.rd.estop.active)
        self.assertTrue(await self.wait_for(lambda: self.rd.estop.outcome == "confirmed"))
        self.assertGreaterEqual(self.rd.estop.confirm_ms, 850)

    async def test_relax_in_commissioning_mode(self):
        self.fake.set_posture("commissioning")
        await asyncio.sleep(1.2)
        self.assertTrue((await self.rd.relax("teste"))[0])
        self.assertTrue(await self.wait_for(lambda: self.rd.estop.outcome == "confirmed"))
        self.assertEqual(self.fake.bus["mode"], "commissioning")

    async def test_garbage_lines_do_not_kill_polling(self):
        """Revisão #4: uma resposta inválida de robotd não deve interromper as consultas periódicas."""
        self.fake.inject = [b"[1,2,3]\n", b'"x"\n', b"null\n"]
        await asyncio.sleep(1.5)
        self.assertLess(self.rd.bus.age(), 1.5)
        self.assertFalse(any(t.done() for t in self.rd._tasks))

    async def test_health_error_does_not_block_bus_status(self):
        """Revisão #5: uma falha de consulta só deve afetar aquela consulta."""
        self.fake.errors["robot.health"] = {"code": -32603, "message": "boom"}
        await asyncio.sleep(2.5)
        self.assertLess(self.rd.bus.age(), 1.5)
        n_bus = len([m for _, m in self.fake.calls if m == "robot.busStatus"])
        self.assertLess(n_bus, 6, "出错的那项不能让循环 20 Hz 空转")

    async def test_relax_is_not_blocked_by_a_slow_poll(self):
        self.fake.delays["robot.busStatus"] = 10.0                   # poll 连接上挂一个 10 秒不回的请求
        await asyncio.sleep(1.2)
        t0 = time.monotonic()
        accepted, _ = await self.rd.relax("teste")
        took = time.monotonic() - t0
        self.assertTrue(accepted)
        self.assertLess(took, 0.3, f"卸力等了 {took:.2f} 秒")
        relax_at = [t for t, m in self.fake.calls if m == "robot.relax"][0]
        self.assertLess(relax_at - t0, 0.1)

    async def test_relax_confirms_from_bus_status(self):
        await asyncio.sleep(0.2)                                      # 让一次 1 秒的常规轮询先排上
        accepted, _ = await self.rd.relax("teste")
        self.assertTrue(accepted)
        for _ in range(50):
            if summarize(self.rd, {})["estop"]["state"] == "confirmed":
                break
            await asyncio.sleep(0.05)
        s = summarize(self.rd, {})
        self.assertEqual(s["estop"]["state"], "confirmed")
        self.assertEqual(s["posture"], "limp")
        # 假 robotd 0.3 秒扭矩 OFF、再 0.2 秒清 hd1910 标志；按下后每 0.1 秒回读，
        # 确认应在 0.8 秒内（不能等到下一个 1 秒轮询）
        self.assertLess(self.rd.estop.confirm_ms, 800)

    async def test_subscribe_only_while_someone_looks(self):
        await asyncio.sleep(0.3)
        self.assertEqual(self.fake.subscribers, 0)
        self.rd.set_viewers(1)
        for _ in range(60):
            if self.fake.subscribers and self.rd.state.value:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(self.fake.subscribers, 1)
        self.assertEqual(len(self.rd.state.value["joints"]), 15)
        with mock.patch.object(robotd_mod, "STREAM_LINGER_S", 0.2):
            self.rd.set_viewers(0)
            for _ in range(60):
                if self.fake.subscribers == 0:
                    break
                await asyncio.sleep(0.05)
        self.assertEqual(self.fake.subscribers, 0)

    async def test_background_music_keeps_real_telemetry_after_last_viewer_leaves(self):
        setter = getattr(self.rd, "set_background_music", None)
        self.assertTrue(callable(setter), "background music needs its own telemetry subscriber")
        setter(True)
        for _ in range(60):
            if self.fake.subscribers and self.rd.state.at:
                break
            await asyncio.sleep(.05)
        self.assertEqual(self.rd.viewers, 0)
        self.assertEqual(self.fake.subscribers, 1)
        before = self.rd.state.at
        self.rd._last_viewer_at = time.monotonic() - 11.
        await asyncio.sleep(.25)
        self.assertEqual(self.fake.subscribers, 1)
        self.assertGreater(self.rd.state.at, before)
        setter(False)
        for _ in range(60):
            if not self.fake.subscribers:
                break
            await asyncio.sleep(.05)
        self.assertEqual(self.fake.subscribers, 0)
        before = self.rd.state.at
        await asyncio.sleep(.15)
        self.assertEqual(self.rd.state.at, before, "no synthetic freshness after unsubscribing")

    async def test_robotd_gone_and_back(self):
        self.fake.restart(1.5)                                         # 真重启：现有连接也断
        for _ in range(60):
            if self.rd.present is False:
                break
            await asyncio.sleep(0.05)
        self.assertIs(self.rd.present, False)
        self.assertEqual(summarize(self.rd, {})["posture"], "absent")
        self.assertEqual(summarize(self.rd, {})["estop"]["state"], "unavailable")
        for _ in range(80):
            if self.rd.present is True:
                break
            await asyncio.sleep(0.05)
        self.assertIs(self.rd.present, True)


# ---------------- 标定模式的 busStatus（任务 16：10-20 真机验收，旧 fork 永远报 configuring_bus） ----------------

STATUS_KEYS = ("build", "port", "mode", "phase", "session", "target_hz", "achieved_hz", "total_cycles", "total_success",
               "total_communication_failures", "errors_by_id", "device_communication", "last_cycle_error", "last_failure",
               "last_sample", "calibrated", "imu_mount_verified", "torque_state", "torque_off_pending", "power_pending",
               "motion", "policy_motion_enabled", "updated_at_us")     # fork feetech_commissioning.rs 的 Status


class FakeCommissioningTest(unittest.IsolatedAsyncioTestCase):
    """假 robotd 照 fork 真实行为（上一轮的毛病：假的直接给快照，测试全过、真机露馅）：
    标定模式没读成功之前回启动报告（只有四个键），读成功以后回实时快照；--commissioning-stuck-status 永远回启动报告。"""

    async def bus(self, fake):
        return (await fake.dispatch("robot.busStatus", {}))[0]

    async def test_boot_report_then_snapshot(self):
        fake = FakeRobotd(FIXTURE, posture="commissioning", mode="commissioning")
        fake.comm_read_s = 0.2
        b = await self.bus(fake)
        self.assertEqual(sorted(b), sorted(("build", "mode", "phase", "port")))
        self.assertEqual((b["mode"], b["phase"], b["port"]), ("commissioning", "configuring_bus", "/dev/ttyS2"))
        self.assertEqual(posture(True, b, None, None), "starting")
        self.assertFalse(robotd_up(b))
        self.assertIsNotNone((await fake.dispatch("robot.busCommand", {"action": "calibration-status"}))[0])   # 标定照样能读
        await asyncio.sleep(0.25)
        b = await self.bus(fake)
        self.assertEqual(b["phase"], "ready")
        for k in STATUS_KEYS:
            self.assertIn(k, b)
        self.assertEqual(len(b["last_sample"]["servos"]), 15)
        self.assertIsNone(b["last_cycle_error"])
        self.assertTrue(robotd_up(b))
        self.assertEqual(posture(True, b, None, None), "commissioning")
        # 读成功过以后舵机断电：还是快照，phase read_error（起来了，只是读舵机出错）
        fake.servo_power = False
        b = await self.bus(fake)
        self.assertEqual(b["phase"], "read_error")
        self.assertIn("Sync Read timeout", b["last_cycle_error"])
        self.assertTrue(robotd_up(b))
        fake.servo_power = True
        # 重启：又从启动报告开始，读成功才回快照
        fake.restart(0.05)
        self.assertEqual((await self.bus(fake))["phase"], "configuring_bus")
        await asyncio.sleep(0.35)
        self.assertEqual((await self.bus(fake))["phase"], "ready")

    async def test_stuck_status_never_clears(self):
        import fake_tune
        fake = FakeRobotd(FIXTURE, posture="commissioning", mode="commissioning")
        fake.comm_read_s = 0.05
        fake.comm_stuck = True
        await asyncio.sleep(0.15)
        for _ in range(3):
            b = await self.bus(fake)
            self.assertEqual(sorted(b), sorted(("build", "mode", "phase", "port")))
            self.assertEqual(b["phase"], "configuring_bus")
        steps = fake_tune.startup_report(fake)["steps"]
        self.assertEqual(steps["4"]["status"], "success")                    # 旧 fork：四步都成功了，只是状态不更新
        await fake.dispatch("fake.set", {"commissioning_stuck": False})
        self.assertEqual((await self.bus(fake))["phase"], "ready")           # 新 fork：读成功一次就清掉

    async def test_no_servo_power_before_first_read_is_waiting_for_bus(self):
        fake = FakeRobotd(FIXTURE, posture="commissioning", mode="commissioning")
        fake.servo_power = False
        await asyncio.sleep(0.4)
        b = await self.bus(fake)
        self.assertEqual((b["mode"], b["phase"]), ("commissioning", "waiting_for_bus"))
        self.assertIn("Sync Read timeout", b["error"])
        self.assertEqual(posture(True, b, None, None), "starting")

    def test_cli_flag_exists(self):
        src = (HERE.parent / "dev" / "fake_robotd.py").read_text(encoding="utf-8")
        self.assertIn('"--commissioning-stuck-status"', src)


class StartingTimerTest(unittest.IsolatedAsyncioTestCase):
    """Studio 自己计时「一直报启动中」：从这次连上算（hello 以后），连续报启动阶段超过 30 秒才改口；起来了清零。"""

    async def asyncSetUp(self):
        self.fake = FakeRobotd(FIXTURE, posture="commissioning", mode="commissioning")
        self.fake.comm_stuck = True                                       # Fork antigo.
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", quiet_log())
        self.rd.start()

    async def asyncTearDown(self):
        await self.rd.stop()
        self.s1.close()
        self.s2.close()

    async def wait_for(self, cond, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    async def test_stuck_commissioning_then_cleared(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.starting_since is not None))
        self.assertEqual(self.rd.bus.value["phase"], "configuring_bus")
        since = self.rd.starting_since
        s = summarize(self.rd, {})
        self.assertEqual(s["posture"], "starting")
        self.assertFalse(s["starting_long"])
        await asyncio.sleep(1.2)
        self.assertEqual(self.rd.starting_since, since)                      # 连续报着：不重新计
        s = summarize(self.rd, {}, now=since + 31)                          # 假时钟：过了 31 秒
        self.assertTrue(s["starting_long"])
        self.assertIn("O programa principal continua inicializando", [t["msg"] for t in s["todo"]])
        self.fake.comm_stuck = False                                        # O fork corrigido envia o snapshot e zera a contagem.
        self.assertTrue(await self.wait_for(lambda: self.rd.starting_since is None
                                            and (self.rd.bus.value or {}).get("phase") == "ready"))
        self.assertEqual(summarize(self.rd, {})["posture"], "commissioning")
        self.fake.comm_stuck = True                                         # Reinicie novamente com o fork antigo e conte desde o novo hello.
        self.fake.restart(0.2)
        self.assertTrue(await self.wait_for(lambda: self.rd.starting_since is not None and self.rd.starting_since > since, 6.0))


if __name__ == "__main__":
    unittest.main()
