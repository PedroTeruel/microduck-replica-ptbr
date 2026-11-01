"""Página dos servos 4a: sessão de barramento (somente leitura e liberação de torque), usando o simulador de protocolo sim_bus do servo-web."""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from studio.log import Log  # noqa: E402
from studio import servo as servo_mod  # noqa: E402
from studio.bus import sim_bus  # noqa: E402
from studio.servo import IDS, ServoSession, angle_deg  # noqa: E402


def quiet_log():
    return Log(Path(".") / "_testlogs", echo=False, background=False)


def wait(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def patch_real_sim_bus(case, regs=None):
    """Substitui a porta serial real pelo barramento simulado SimSerial para o teste de referência F3."""
    real = servo_mod.feetech.FeetechBus

    def make(port, baud=1_000_000):
        ser = sim_bus.SimSerial(IDS)
        for sid, values in (regs or {}).items():
            sv = ser._by_id(sid)
            sv.r[41] = values[0]
            sv.r[46], sv.r[47] = values[1] & 0xFF, values[1] >> 8
        return real(None, ser=ser)

    p = unittest.mock.patch("studio.servo.feetech.FeetechBus", side_effect=make)
    p.start()
    case.addCleanup(p.stop)


class ServoSessionTest(unittest.TestCase):
    def setUp(self):
        self.s = ServoSession(quiet_log(), sim=True)
        ok, why = self.s.open("teste")
        self.assertTrue(ok, why)
        self.assertTrue(wait(lambda: len(self.s.rows) == 15))

    def tearDown(self):
        self.s.close()

    def test_reads_15_and_angles_match_home_pose(self):
        snap = self.s.snapshot()
        self.assertEqual(snap["state"], "open")
        self.assertEqual(snap["online"], 15)
        row = {r["id"]: r for r in snap["rows"]}
        self.assertAlmostEqual(row[22]["deg"], -26.2, delta=0.2)     # Inclinação do quadril esquerdo: −0,4579 rad.
        self.assertAlmostEqual(row[12]["deg"], 26.2, delta=0.2)      # Espelhamento do quadril direito.
        self.assertEqual(row[23]["temp_limit"], 70)                  # Registrador 13.
        self.assertEqual(row[20]["torque"], 0)                       # O torque está desligado ao ligar o servo simulado.
        self.assertTrue(wait(lambda: self.s.hz > 5, 2.5))

    def test_missing_servo_counts_as_dropped(self):
        self.s.sim_serial.servos[23].muted = {56}                     # O servo do joelho esquerdo não responde ao status.
        time.sleep(0.5)
        snap = self.s.snapshot()
        row = {r["id"]: r for r in snap["rows"]}
        self.assertFalse(row[23]["fresh"])
        self.assertEqual(snap["online"], 14)
        self.assertGreater(row[23]["comm"]["missed"], 5)
        self.assertGreater(row[23]["comm"]["streak"], 5)
        self.assertEqual(row[20]["comm"]["missed"], 0)

    def test_relax_all_confirms_by_readback_and_latches(self):
        self.s.bus.sync_write(40, 1, [(i, b"\x01") for i in IDS])      # Simula todos os servos mantendo torque.
        self.s._read_torque()
        self.assertEqual(self.s.snapshot()["holding"], 15)
        self.assertEqual(self.s.estop_status()["state"], "ready")
        ok, why = self.s.relax_all("测试")
        self.assertTrue(ok, why)
        snap = self.s.snapshot()
        self.assertTrue(snap["all_off"])
        self.assertTrue(snap["latched"])
        self.assertEqual(self.s.estop_status()["state"], "confirmed")
        self.assertTrue(all(sv.r[40] == 0 for sv in self.s.sim_serial.servos.values()))

    def test_angle_formula(self):
        self.assertAlmostEqual(angle_deg(2048 + 1024, -1), -90.0)
        self.assertIsNone(angle_deg(None, 1))

    def test_open_refuses_port_switch_while_open(self):
        """Não permita trocar a porta serial durante o ajuste: fechar o barramento atual impediria a liberação de torque real."""
        self.s.bus.sync_write(40, 1, [(i, b"\x01") for i in (20, 21)])
        before = (self.s.state, self.s.port, self.s.sim)
        ok, why = self.s.open("测试", "COM9")
        self.assertFalse(ok)
        self.assertIn("不能换串口", why)
        self.assertEqual((self.s.state, self.s.port, self.s.sim), before)
        self.assertEqual(self.s.state, "open")
        self.assertEqual([self.s.sim_serial._by_id(i).r[40] for i in (20, 21)], [1, 1])   # Os registros de torque não foram alterados.

    def test_open_refuses_switch_from_real_to_sim(self):
        s = ServoSession(quiet_log(), sim=False, port="/dev/ttyS2")
        s.state = "open"
        ok, why = s.open("测试", "sim")
        self.assertFalse(ok)
        self.assertIn("不能换串口", why)
        self.assertEqual((s.state, s.sim, s.port), ("open", False, "/dev/ttyS2"))


class LeaveAndHandBackTest(unittest.TestCase):
    """Revisões D2 e D3: registre as operações em andamento; aguarde-as antes de devolver/sair e leia o torque; rejeite novas operações durante o fechamento."""

    def setUp(self):
        self.s = ServoSession(quiet_log(), sim=True)
        self.assertTrue(self.s.open("测试")[0])

    def tearDown(self):
        if self.s.state == "open":
            self.s.close()

    def regs(self):
        return [self.s.sim_serial._by_id(i).r[40] for i in (20, 21)]

    def test_leave_waits_for_reserved_torque_and_keeps_holding(self):
        """Se a operação “manter” já foi registrada pelo app, mas a thread ainda não iniciou, aguarde-a e leia os dois servos mantendo torque antes de decidir não devolver."""
        from studio.servo_ops import Refused  # noqa: F401
        tok = self.s.op_begin("torque")
        out = {}

        def leave():
            out["v"] = self.s.leave("离开舵机页", wait_s=3.0)
        import threading
        t = threading.Thread(target=leave)
        t.start()
        time.sleep(0.1)
        self.assertTrue(self.s.closing)                                   # Enquanto aguarda, novas operações são rejeitadas.
        with self.assertRaises(Exception):
            self.s.op_begin("goal")
        self.s.ops.handle({"op": "torque", "ids": [20, 21], "on": 1}, tok)   # Uma operação já registrada termina normalmente.
        self.s.op_end(tok)
        t.join(5)
        verdict, info = out["v"]
        self.assertEqual(verdict, "kept")
        self.assertEqual(info["holding"], 2)
        self.assertEqual(self.regs(), [1, 1])
        self.assertFalse(self.s.closing)

    def test_leave_hands_back_only_when_all_15_read_zero(self):
        self.s.sim_serial._by_id(14).muted = {40}                         # Sem leitura do torque do servo 14, considere que ele pode continuar ativo (D3c).
        verdict, info = self.s.leave("离开")
        self.assertEqual((verdict, info["unknown"], info["holding"]), ("kept", 1, 0))
        self.s.sim_serial._by_id(14).muted = set()
        verdict, _ = self.s.leave("离开")
        self.assertEqual(verdict, "handed_back")
        self.assertEqual(self.s.state, "closed")

    def test_leave_while_motion_runs_keeps_session(self):
        """D3a: sair durante a transição de uma postura oficial não devolve o controle."""
        self.s.ops.handle({"op": "torque", "on": 1})
        self.s.ops.handle({"op": "official", "key": "sit", "seconds": 2})
        verdict, info = self.s.leave("离开")
        self.assertEqual(verdict, "kept")
        self.assertIn("动作在跑", info["why"])

    def test_hand_back_refuses_new_ops_and_manual_torque_cannot_clear_latch(self):
        """D2: rejeite operações novas durante a devolução; uma ação “manter” atrasada não pode desfazer a liberação."""
        tok = self.s.op_begin("torque")
        out = {}
        import threading
        t = threading.Thread(target=lambda: out.setdefault("v", self.s.hand_back_bus("交还", wait_s=3.0)))
        t.start()
        time.sleep(0.1)
        with self.assertRaises(Exception) as cm:
            self.s.op_begin("torque")
        self.assertIn("正在交还", str(cm.exception))
        self.s.ops.handle({"op": "torque", "ids": [20, 21], "on": 1}, tok)
        self.s.op_end(tok)
        t.join(5)
        self.assertEqual(out["v"], (True, None))
        self.assertEqual(self.regs(), [0, 0])                             # A operação “manter” concluída também foi liberada na devolução.
        self.assertEqual(self.s.state, "closed")

    def test_hand_back_gives_up_when_op_never_finishes(self):
        tok = self.s.op_begin("calibrate")
        ok, why = self.s.hand_back_bus("交还", wait_s=0.3)
        self.assertFalse(ok)
        self.assertIn("没交还", why)
        self.assertEqual(self.s.state, "open")
        self.assertFalse(self.s.closing)
        self.s.op_end(tok)


class ServoClosedTest(unittest.TestCase):
    def test_relax_without_bus_is_refused(self):
        s = ServoSession(quiet_log(), sim=True)
        ok, why = s.relax_all("测试")
        self.assertFalse(ok)
        self.assertEqual(s.estop_status()["state"], "unavailable")


class BaselineTest(unittest.TestCase):
    """F3: registre 41/46 na primeira tomada do barramento, restaure e confira na devolução; não sobrescreva no mesmo boot_id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.patch_boot = unittest.mock.patch("studio.servo.boot_id", return_value="boot-a")
        self.patch_boot.start()
        self.addCleanup(self.patch_boot.stop)
        self.addCleanup(self.tmp.cleanup)
        patch_real_sim_bus(self)
        self.patch_robotd = unittest.mock.patch("studio.servo.robotd_active", return_value=False)
        self.patch_robotd.start()
        self.addCleanup(self.patch_robotd.stop)
        self.s = ServoSession(quiet_log(), sim=False, port="/dev/ttyS99", state_dir=self.dir)
        ok, why = self.s.open("测试")
        self.assertTrue(ok, why)

    def tearDown(self):
        if self.s.state == "open":
            self.s.close()

    def path(self):
        return Path(self.dir) / "servo-baseline-boot-a.json"

    def test_baseline_written_once_and_not_overwritten_on_second_takeover(self):
        data = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual(data["boot_id"], "boot-a")
        self.assertEqual(len(data["regs"]), 15)
        first = dict(data["regs"]["20"])
        self.s.bus.write_u8(20, 41, 33)                 # O Studio alterou o registrador; esse valor não é a referência original.
        self.s.bus.write_u16(20, 46, 1234)
        self.s.close()
        self.s = ServoSession(quiet_log(), sim=False, port="/dev/ttyS99", state_dir=self.dir)
        self.assertTrue(self.s.open("第二次接管")[0])
        data2 = json.loads(self.path().read_text(encoding="utf-8"))
        self.assertEqual(data2["regs"]["20"], first)    # Uma segunda tomada não substitui o valor registrado inicialmente.

    def test_hand_back_writes_baseline_back(self):
        want = dict(self.s.baseline[20])
        sv = self.s.bus.ser._by_id(20)
        self.s.bus.write_u8(20, 41, 9)
        self.s.bus.write_u16(20, 46, 2222)
        ok, note = self.s.hand_back_bus("交还", wait_s=1.0)
        self.assertTrue(ok, note)
        self.assertIsNone(note)
        self.assertEqual(self.s.state, "closed")
        self.assertEqual(sv.r[41], want["41"])
        self.assertEqual(sv.r[46] | (sv.r[47] << 8), want["46"])

    def test_baseline_readback_mismatch_keeps_session_open(self):
        sv = self.s.bus.ser._by_id(20)
        sv.r[41], sv.r[46], sv.r[47] = 17, 5, 0
        sv.readonly = {41, 46}                           # Simula uma gravação que retorna sucesso, mas não altera os registradores.
        ok, why = self.s.hand_back_bus("交还", wait_s=1.0)
        self.assertFalse(ok)
        self.assertIn("没交还", why)
        self.assertIn("加速度/速度没写回", why)
        self.assertEqual(self.s.state, "open")

    def test_baseline_unanswered_still_hands_back_with_note(self):
        self.s.bus.ser._by_id(14).muted = {41, 46}
        ok, note = self.s.hand_back_bus("交还", wait_s=1.0)
        self.assertTrue(ok, note)
        self.assertIn("#14", note)
        self.assertIn("没确认卸力", note)
        self.assertEqual(self.s.state, "closed")

    def test_changed_boot_id_records_new_and_removes_old_file(self):
        old = self.path()
        self.assertTrue(old.exists())
        self.s.close()
        with unittest.mock.patch("studio.servo.boot_id", return_value="boot-b"):
            self.s = ServoSession(quiet_log(), sim=False, port="/dev/ttyS99", state_dir=self.dir)
            self.assertTrue(self.s.open("新开机")[0])
        new = Path(self.dir) / "servo-baseline-boot-b.json"
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertEqual(json.loads(new.read_text(encoding="utf-8"))["boot_id"], "boot-b")


class SimBaselineIsolationTest(unittest.TestCase):
    """R1: a sessão de demonstração mantém 41/46 apenas em memória, sem ler, gravar ou excluir o arquivo real de referência dos servos."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.addCleanup(self.tmp.cleanup)
        self.patch_boot = unittest.mock.patch("studio.servo.boot_id", return_value="boot-fixed")
        self.patch_boot.start()
        self.addCleanup(self.patch_boot.stop)
        self.sessions = []

    def tearDown(self):
        for s in self.sessions:
            if s.state == "open":
                s.close()

    def open_sim(self):
        s = ServoSession(quiet_log(), sim=True, state_dir=self.dir)
        self.sessions.append(s)
        ok, why = s.open("演示")
        self.assertTrue(ok, why)
        return s

    def files(self):
        return sorted(p.name for p in Path(self.dir).glob("servo-baseline-*.json"))

    def test_sim_baseline_writes_no_file(self):
        self.open_sim()
        self.assertEqual(self.files(), [])

    def test_sim_baseline_does_not_leak_into_real_port_file(self):
        self.open_sim()                                   # Abra primeiro a demonstração; os valores simulados zerados ficam em memória.
        patch_real_sim_bus(self, {20: (7, 2222)})
        p = unittest.mock.patch("studio.servo.robotd_active", return_value=False)
        p.start()
        self.addCleanup(p.stop)
        real = ServoSession(quiet_log(), sim=False, port="/dev/ttyS99", state_dir=self.dir)
        self.sessions.append(real)
        ok, why = real.open("真口")
        self.assertTrue(ok, why)
        data = json.loads((Path(self.dir) / "servo-baseline-boot-fixed.json").read_text(encoding="utf-8"))
        self.assertEqual(data["regs"]["20"], {"41": 7, "46": 2222})   # Valor lido da porta real, não os zeros simulados.

    def test_sim_baseline_does_not_delete_other_boot_file(self):
        other = Path(self.dir) / "servo-baseline-boot-old.json"
        other.write_text('{"v":1,"boot_id":"boot-old","at":0,"regs":{}}', encoding="utf-8")
        self.open_sim()
        self.assertTrue(other.exists())                   # A demonstração não remove referências de outras inicializações.


class RobotdProbeTest(unittest.TestCase):
    """F9: se systemctl falhar ou expirar, não sabemos se o programa principal está ativo; não abra para evitar disputa pela serial."""

    def test_open_refuses_when_robotd_state_is_unknown(self):
        s = ServoSession(quiet_log(), sim=False, port="/dev/ttyS99")
        with unittest.mock.patch("studio.servo.robotd_active", return_value=None):
            ok, why = s.open("测试")
        self.assertFalse(ok)
        self.assertIn("查不了主程序在不在", why)
        self.assertEqual(s.state, "error")

    def test_robotd_active_returns_none_on_systemctl_error(self):
        from studio import servo as servo_mod
        with unittest.mock.patch("studio.servo.sys.platform", "linux"), \
             unittest.mock.patch("studio.servo.subprocess.run", side_effect=subprocess.TimeoutExpired("systemctl", 3)):
            self.assertIsNone(servo_mod.robotd_active())



if __name__ == "__main__":
    unittest.main()

class DirectionsLoadTest(unittest.TestCase):
    def test_saved_directions_with_int_keys_do_not_crash_startup(self):
        """MicroDuck 2 em 19/10: depois de salvar direções em servo-directions.json, o Studio falhava ao reiniciar com dict(DEFAULT, **{30: 1})."""
        import json as _json
        import os
        from studio.servo import load_directions, ServoSession, DEFAULT_DIRECTIONS
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "servo-directions.json"), "w", encoding="utf-8") as f:
                _json.dump({"30": 1, "31": -1}, f)
            dirs = load_directions(d)
            self.assertEqual(dirs, {30: 1, 31: -1})
            s = ServoSession(Log(Path(d) / "logs", echo=False, background=False), sim=True, directions=dirs, state_dir=d)
            self.assertEqual(s.directions[30], 1)
            self.assertEqual(s.directions[20], DEFAULT_DIRECTIONS[20])

