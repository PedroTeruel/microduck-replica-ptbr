"""Integração da estimativa da bateria ao Studio (battery-plan.md v2 §6 B2/B3): serviço de 1 Hz (studio/battery_svc.py), carga em summarize e nas tarefas
(também durante o controle das servos; revisão B-R6), configurações battery.op, roteiro de bateria do robotd simulado e liberação do comando “ficar em pé” independentemente da carga.
Execução (no diretório studio):
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_battery_svc'])"
"""
import asyncio
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from fake_robotd import BAT_OFFSETS, FakeRobotd  # noqa: E402
from studio import battery as B  # noqa: E402
from studio.battery_svc import BatteryService  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Robotd  # noqa: E402
from studio.state import summarize  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


def fixture_bus():
    for line in open(FIXTURE, encoding="utf-8"):
        d = json.loads(line)
        if d.get("method") == "robot.busStatus":
            return d["reply"]["result"]
    raise AssertionError("A reprodução não contém busStatus")


def set_sample(sample, value, at):
    sample.value, sample.at, sample.error = value, at, None


def bus_with(volts, torque=True, policy=False):
    b = copy.deepcopy(fixture_bus())
    for j, v in zip(b["native"]["joints"], volts):
        j["volts"] = v
        j["feedback_fresh"] = True
    b["native"]["torque_state_confirmed"] = torque
    b["policy_enabled"] = policy
    return b


class FakeServo:
    """Simula o Studio ocupando o barramento durante o controle das servos: state aberto, snapshot() retorna tensão e torque de cada uma."""

    def __init__(self, volt=7.2, torque=0):
        self.state, self.volt, self.torque_v = "open", volt, torque
        self.latched, self.sim, self.port, self.handed_back_at = False, True, None, None

    def snapshot(self):
        rows = [{"id": i, "cn": f"Servo {i + 1}", "volt": self.volt, "fresh": True, "torque": self.torque_v} for i in range(15)]
        return {"t": "servo", "state": self.state, "rows": rows, "online": 15, "total": 15,
                "avg_volts": self.volt, "battery_pct": B.linear_pct(self.volt), "all_off": self.torque_v == 0}

    def estop_status(self):
        return {"state": "confirmed", "why": "Torque aliviado nos 15 servos (leitura do barramento)"}

    def holding(self):
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = Log(self.dir / "logs", echo=False, background=False)
        self.rd = Robotd("none", "none", self.log)
        self.state = str(self.dir / "state")

    def tearDown(self):
        self.tmp.cleanup()

    def svc(self, **kw):
        return BatteryService(self.rd, self.log, self.state, **kw)

    def feed_bus(self, svc, volts, n, t0=None, torque=True, policy=False, per_tick=1):
        """Avança n segundos: um busStatus novo por segundo (horário da amostra igual ao segundo), com per_tick chamadas de tick por segundo (simula várias páginas). Retorna o horário final."""
        t = time.monotonic() if t0 is None else t0
        for i in range(n):
            now = t + i
            set_sample(self.rd.bus, bus_with([volts] * 15 if isinstance(volts, float) else volts, torque, policy), now)
            for k in range(per_tick):
                svc.tick(now + k * 0.1)
        return t + n

    def msgs(self, cat=B.LOG_CAT):
        return [e["msg"] for e in self.log.recent(200, cats=[cat], min_level="debug")]


class ServiceTest(Base):
    def test_robotd_source_and_dedup(self):
        """Um busStatus por segundo; alimentar a mesma amostra várias vezes (por três páginas a 10 Hz, por exemplo) só deve contá-la uma vez (revisão B-R7)."""
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40, per_tick=3)
        self.assertEqual(len(s.est.samples), 40)
        v = s.view(t)
        self.assertEqual(v["mode"], "calm")
        self.assertEqual(v["source"], "robotd")
        self.assertEqual(v["cls"], "light")             # Sem robot.state: torque ligado e estratégia desligada → postura mantida (sem caminhar)
        self.assertEqual(v["pct"], round(B.soc_from_pack(7.62)))
        self.assertTrue(any("Estimativa de bateria iniciada" in m for m in self.msgs()))

    def test_limp_without_state_stream_is_rest(self):
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40, torque=False)
        self.assertEqual(s.view(t)["cls"], "rest")
        self.assertEqual(s.view(t)["why"], "Em repouso")

    def test_stale_bus_restarts(self):
        s = self.svc()
        t = self.feed_bus(s, 7.62, 40)
        for i in range(15):                              # busStatus deixa de atualizar (robotd parado ou desconectado)
            s.tick(t + i)
        self.assertEqual(s.view(t + 15)["mode"], "no_data")
        self.assertTrue(any("ficaram sem leitura de tensão por mais de" in m for m in self.msgs()))

    def test_state_stream_classifies_walking(self):
        s = self.svc()
        t = time.monotonic()
        for i in range(60):
            now = t + i
            set_sample(self.rd.bus, bus_with([7.4] * 15, policy=True), now)
            set_sample(self.rd.state, {"policy": "walk", "move": {"applied": [0.2, 0, 0]}, "safety": {"fallen": False}}, now)
            s.tick(now)
        v = s.view(t + 59)
        self.assertEqual(v["cls"], "heavy")
        self.assertEqual(v["mode"], "load_rough")
        self.assertEqual(v["why"], "Em movimento; estimativa aproximada pela tensão sob carga, possivelmente abaixo do real")

    def test_servo_session_source_and_todo(self):
        """Durante o controle das servos, a tensão vem do barramento do próprio Studio; a tarefa ainda mostra a carga da bateria (revisão B-R6) e informa que o programa principal está parado."""
        servo = FakeServo(volt=7.2)
        s = self.svc(servo=servo)
        t = time.monotonic()
        for i in range(100):
            s.tick(t + i)
        v = s.view(t + 99)
        self.assertEqual(v["source"], "servo")
        self.assertEqual(v["cls"], "rest")
        self.assertTrue(v["red"])
        st = summarize(self.rd, {"label": "Robô"}, servo, now=t + 99, bat=s)
        self.assertEqual(st["posture"], "servo_session")
        self.assertEqual(st["battery"]["pct"], v["pct"])
        keys = [i["key"] for i in st["todo"]]
        self.assertIn("battery", keys)
        self.assertIn("servo_session", keys)
        bat = next(i for i in st["todo"] if i["key"] == "battery")
        self.assertEqual(bat["level"], "error")
        self.assertIn("Durante o controle das servos, o programa principal fica parado", bat["hint"])
        self.assertLess(keys.index("battery"), keys.index("servo_session"))   # Alertas críticos aparecem primeiro

    def test_switch_robotd_to_servo_keeps_estimate(self):
        servo = FakeServo(volt=7.62)
        servo.state = "closed"
        s = self.svc(servo=servo)
        t = self.feed_bus(s, 7.62, 60, torque=False)
        before = s.view(t)["pct"]
        servo.state = "open"
        for i in range(30):
            s.tick(t + i)
        self.assertEqual(s.view(t + 29)["pct"], before)
        self.assertEqual(s.view(t + 29)["mode"], "calm")

    def test_summarize_without_estimator_is_unchanged(self):
        set_sample(self.rd.bus, bus_with([7.5] * 15), time.monotonic())
        set_sample(self.rd.health, {"battery": {"percent": 55.0, "volts": 7.48}}, time.monotonic())
        st = summarize(self.rd, {"label": "Robô"})
        self.assertEqual(st["battery"], {"pct": 55.0, "volts": 7.48})

    def test_summarize_with_estimator(self):
        s = self.svc()
        t = self.feed_bus(s, 7.30, 120, torque=False)        # 19%: aviso amarelo
        set_sample(self.rd.health, {"battery": {"percent": 43.0, "volts": 7.29}}, t)
        st = summarize(self.rd, {"label": "Robô"}, now=t, bat=s)
        b = st["battery"]
        self.assertEqual(b["mode"], "calm")
        self.assertEqual(b["rd_pct"], 43)
        self.assertTrue(b["warn"])
        item = next(i for i in st["todo"] if i["key"] == "battery")
        self.assertEqual(item["level"], "warn")
        self.assertEqual(item["msg"], f"Bateria em cerca de {b['pct']}%")

    def test_shutdown_wording(self):
        class Ob:
            battery_shutdown = True
        s = self.svc(onboard=Ob())
        t = self.feed_bus(s, 7.15, 120, torque=False)
        hint = next(i for i in B.todo_items(s.view(t)) if i["key"] == "battery")["hint"]
        self.assertIn("6.6 V", hint)
        Ob.battery_shutdown = False
        hint = next(i for i in B.todo_items(s.view(t)) if i["key"] == "battery")["hint"]
        self.assertIn("não para sozinho", hint)

    def test_speed(self):
        s = self.svc(speed=20)
        self.assertTrue(any("estimativa da bateria acelerada" in m for m in self.msgs()))
        t0 = time.monotonic()
        set_sample(self.rd.bus, bus_with([7.62] * 15, torque=False), t0)
        for i in range(40):                                   # Durante a aceleração, cada busStatus também conta como nova amostra: 2 s reais = 40 s
            s.tick(t0 + i * 0.05)
        self.assertEqual(s.view(t0 + 2.0)["mode"], "calm")


class OpTest(Base):
    def run_op(self, s, args):
        return asyncio.run(s.handle(args, by="teste"))

    def test_get_set(self):
        s = self.svc()
        d = self.run_op(s, {"op": "get"})
        self.assertEqual(d["settings"], B.DEFAULTS)
        self.assertEqual(set(d["presets"]), {"2s_liion", "bench"})
        d = self.run_op(s, {"op": "set", "values": {"red_pct": 20, "load_floor_v": 7.0}})
        self.assertEqual((d["settings"]["red_pct"], s.est.settings["red_pct"]), (20, 20))   # Aplicação imediata
        with open(B.settings_path(self.state), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["load_floor_v"], 7.0)
        self.assertTrue(any("Configurações da bateria alteradas: Limite crítico 15% → 20%" in m for m in self.msgs()))
        # Reinicia o Studio e lê as configurações salvas
        self.assertEqual(self.svc().settings["red_pct"], 20)
        with self.assertRaises(ValueError) as cm:
            self.run_op(s, {"op": "set", "values": {"red_pct": 29}})          # Não fica 5% abaixo do limite de aviso
        self.assertIn("pelo menos 5% abaixo", str(cm.exception))
        with self.assertRaises(ValueError):
            self.run_op(s, {"op": "set", "values": {"capacity_mah": 2600}})
        with self.assertRaises(ValueError):
            self.run_op(s, {"op": "nope"})
        self.assertEqual(s.settings["red_pct"], 20)                           # A alteração rejeitada não foi aplicada

    def test_bench_preset(self):
        s = self.svc()
        self.run_op(s, {"op": "set", "values": {"preset": "bench"}})
        t = self.feed_bus(s, 7.40, 40, torque=False)
        v = s.view(t)
        self.assertEqual(v["mode"], "bench")
        self.assertIsNone(v["pct"])
        self.assertEqual(v["volts"], 7.4)
        self.assertEqual(B.todo_items(v), [])
        self.assertNotIn("Recarregue logo após descarregar", "\n".join(v["detail"]))  # Sem bateria, não exibe instruções de conservação
        t = self.feed_bus(s, 6.70, 60, t0=t)
        items = B.todo_items(s.view(t))
        self.assertEqual(items[0]["msg"], "Tensão da fonte muito baixa: 6.70 V")
        self.assertIn("limitando a corrente", items[0]["hint"])

    def test_calibrate(self):
        s = self.svc()
        r = self.run_op(s, {"op": "calibrate", "measured_v": 7.8})
        self.assertFalse(r["ok"])                                             # Ainda não ficou em repouso
        t0 = time.monotonic() - 45
        self.feed_bus(s, 7.62, 40, t0=t0, torque=False)
        r = self.run_op(s, {"op": "calibrate", "measured_v": 7.80})
        self.assertTrue(r["ok"], r)
        self.assertAlmostEqual(r["offset"], 0.18, places=2)
        self.assertEqual(r["current"], 0.0)
        self.assertEqual(s.settings["cal_offset_v"], 0.0)                     # Calcula, mas não salva
        self.run_op(s, {"op": "set", "values": {"cal_offset_v": r["offset"]}})
        self.assertEqual(s.est.off, 0.18)

    def test_bad_file_at_start(self):
        os.makedirs(self.state, exist_ok=True)
        with open(B.settings_path(self.state), "w", encoding="utf-8") as f:
            f.write("{invalid")
        s = self.svc()
        self.assertEqual(s.settings, B.DEFAULTS)
        self.assertTrue(os.path.exists(B.settings_path(self.state) + ".bad"))
        self.assertTrue(any("Não foi possível ler as configurações da bateria" in m for m in self.msgs()))


class FakeRobotdBatteryTest(unittest.TestCase):
    def call(self, f, method, params=None):
        return asyncio.run(f.dispatch(method, params or {}))[0]

    def test_script(self):
        f = FakeRobotd(str(FIXTURE), posture="limp")
        recorded = [j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]]
        self.call(f, "fake.set", {"battery": {"v": 7.6}})
        vs = [j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]]
        self.assertEqual(vs, [round(7.6 + o, 1) for o in BAT_OFFSETS])
        self.assertAlmostEqual(B.trimmed(vs)[0], 7.62, delta=0.01)            # Conjunto do robô 2: 7,62 após descartar extremos
        h = self.call(f, "robot.health")["battery"]
        self.assertAlmostEqual(h["volts"], sum(vs) / 15, places=3)
        self.assertAlmostEqual(h["percent"], B.linear_pct(h["volts"]), places=3)
        f.set_posture("holding")                                              # Torque ligado: cai mais 0,08
        self.assertLess(B.trimmed([j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]])[0], 7.6)
        self.call(f, "fake.set", {"battery": {"glitch": 4.2}})
        self.assertEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {4.2})
        self.assertNotEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {4.2})   # Apenas uma vez
        self.call(f, "fake.set", {"battery": {"gone": True}})
        self.assertEqual({j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]}, {0.0})
        self.call(f, "fake.set", {"battery": None})
        self.assertEqual([j["volts"] for j in self.call(f, "robot.busStatus")["native"]["joints"]], recorded)


try:
    from tests.test_pad import POLICIES, PadTestBase, bus as pad_bus   # noqa: E402
except Exception:  # noqa: BLE001 — problemas na ferramenta de teste do controle não impedem os demais testes da bateria
    PadTestBase = None

if PadTestBase is not None:
    class StandNotBlockedTest(PadTestBase):
        """Decisão do usuário de 10-18: a bateria apenas avisa; mesmo no limite crítico, não bloqueia “ficar em pé” (antes bloqueava em 10% na escala linear do robotd, com mensagem de desligamento automático)."""

        def test_low_battery_does_not_block_stand(self):
            self.robot_ok(torque_on=False, posture="limp", battery_pct=3.0, bus=pad_bus(False), policies=POLICIES)
            self.ops._relax_at = -1e9                        # Não acabou de desligar o torque (há outra proteção temporária, independente da bateria)
            stand = self.ops.snapshot()["motion"]["buttons"]["stand"]
            self.assertTrue(stand["ok"], stand)
            self.assertEqual(stand["call"], "robot.init")
            self.assertIsNone(stand["why"])

        def test_low_battery_note_follows_robotd_shutdown_setting(self):
            """Complemento da tarefa 1: carga baixa gera aviso, mas não bloqueia; a mensagem reflete a configuração real de onboard.read_battery_shutdown()."""
            self.robot_ok(torque_on=False, posture="limp", battery_pct=3.0, bus=pad_bus(False), policies=POLICIES)
            self.ops._relax_at = -1e9
            self.ops.battery_shutdown = False
            stand = self.ops.snapshot()["motion"]["buttons"]["stand"]
            self.assertTrue(stand["ok"], stand)
            self.assertIn("Restam apenas 3% de bateria", stand["note"])
            self.assertIn("Recarregue antes de continuar", stand["note"])
            self.assertIn("não se sentará sozinho", stand["note"])
            self.ops.battery_shutdown = True
            note = self.ops.snapshot()["motion"]["buttons"]["stand"]["note"]
            self.assertIn("se sentará e desligará automaticamente", note)


if __name__ == "__main__":
    unittest.main()
