"""Operações da página dos servos: testes com o simulador de protocolo do servo-web."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio.log import Log  # noqa: E402
from studio.servo import ServoSession  # noqa: E402
from studio.servo_ops import Refused  # noqa: E402


class ServoOpsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.s = ServoSession(Log(Path(self.tmp.name) / "logs", echo=False, background=False), sim=True,
                              state_dir=self.tmp.name)
        ok, why = self.s.open("teste")
        self.assertTrue(ok, why)
        end = time.monotonic() + 2
        while len(self.s.rows) < 15 and time.monotonic() < end:
            time.sleep(0.02)
        self.o = self.s.ops

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def sim(self, i):
        return self.s.sim_serial.servos[i]

    def test_torque_on_aligns_goal_first(self):
        r = self.o.handle({"op": "torque", "on": 1, "ids": [22]})
        self.assertEqual(r["on"], [22])
        self.assertEqual(self.sim(22).r[40], 1)
        self.assertEqual(round(self.sim(22).pos()), 2347)          # Sem ultrapassar a posição, alinha o alvo antes.

    def test_slider_goal_moves_when_holding(self):
        self.o.handle({"op": "torque", "on": 1, "ids": [20]})
        self.o.handle({"op": "goal", "id": 20, "pos": 2300})
        self.assertEqual(round(self.sim(20).pos()), 2300)

    def test_calibrate_sets_2048_and_holds(self):
        plan = self.o.handle({"op": "calib_plan", "ids": "22"})
        self.assertAlmostEqual(plan["rows"][0]["diff_deg"], -26.3, delta=0.1)
        r = self.o.handle({"op": "calibrate", "ids": "22"})
        self.assertEqual(r["ok"], [22])
        self.assertEqual(round(self.sim(22).pos()), 2048)
        self.assertEqual(self.sim(22).r[40], 1)                     # Mantém o torque após calibrar, conforme solicitado.
        self.assertEqual(r["hold"]["on"], [22])
        u = self.o.handle({"op": "undo"})
        self.assertEqual(u["ok"], [22])
        self.assertEqual(round(self.sim(22).pos()), 2347)          # Desfaz a calibração e restaura o offset original.

    def test_calibrate_with_torque_on_and_minus_offset_does_not_double_the_error(self):
        """Em 19/10, o Microduck 2 mostrou que calibrar com torque ligado podia dobrar o erro de offset; agora infere o sinal pela leitura 0x0B."""
        for droop in (0.0, 0.5):
            with self.subTest(droop=droop):
                self.o.offset_sign = None
                sv = self.sim(22)
                sv.offset_adds = False
                sv.droop = droop
                self.o.handle({"op": "torque", "on": 1, "ids": [22]})
                self.o.handle({"op": "goal", "id": 22, "pos": 2120})      # Move 72 passos a partir do ponto zero.
                phys = sv.phys                                   # Posição física definida com o torque ligado.
                r = self.o.handle({"op": "calibrate", "ids": "22"})
                self.assertEqual(r["ok"], [22])
                self.assertEqual(self.o.offset_sign, -1)         # O sinal foi inferido.
                at_phys = phys - sv.off                          # Leitura atual da posição física definida.
                self.assertLessEqual(abs(at_phys - 2048), 3, f"A leitura da posição definida foi {at_phys}, não 2048.")
                sv.droop = 0.0

    def test_infer_offset_sign(self):
        from studio.servo_ops import infer_offset_sign
        self.assertEqual(infer_offset_sign(2064, 2048, 16), -1)      # #24: a leitura diminui 16 e o offset aumenta 16.
        self.assertEqual(infer_offset_sign(2064, 2048, -16), 1)
        self.assertEqual(infer_offset_sign(2064, 2046, 16), -1)      # Também identifica o sinal após uma queda adicional de 2 passos.
        self.assertIsNone(infer_offset_sign(2050, 2048, 2))          # A mudança é pequena demais para determinar o sinal.
        self.assertIsNone(infer_offset_sign(2100, 2048, 16))         # Nenhum dos sinais corresponde.

    def test_latched_refuses_motion_until_manual_torque_on(self):
        """Após desligar o torque, rejeita movimentos e calibração até que o usuário habilite o torque manualmente."""
        self.assertTrue(self.s.relax_all("teste")[0])
        for args in ({"op": "goal", "id": 20, "pos": 2100}, {"op": "calibrate", "ids": "20"},
                     {"op": "official", "key": "stand"}, {"op": "idle", "on": True}):
            with self.assertRaises(Refused):
                self.o.handle(args)
        self.assertEqual(self.o.handle({"op": "torque", "on": 1, "ids": [20]})["on"], [20])
        self.assertFalse(self.s.latched)
        self.o.handle({"op": "goal", "id": 20, "pos": 2100})

    def test_official_pose_and_saved_poses(self):
        self.o.handle({"op": "torque", "on": 1})
        self.o.handle({"op": "official", "key": "zero", "seconds": 0.2, "mode": "stream"})
        time.sleep(0.8)
        self.assertEqual(round(self.sim(22).pos()), 2048)
        poses = self.o.handle({"op": "save_pose", "name": "Postura do ponto zero"})["poses"]
        self.assertEqual(poses[0]["name"], "Postura do ponto zero")
        self.assertEqual(self.o.handle({"op": "delete_pose", "file": poses[0]["file"]})["poses"], [])

    def test_tools(self):
        self.assertEqual(self.o.handle({"op": "scan", "ids": "20-24"})["found"], [20, 21, 22, 23, 24])
        self.assertEqual(len(self.o.handle({"op": "dump", "id": 20})["rows"]), 62)    # Inclui P/D/I em operação no HD-1910 (50–52).
        self.assertEqual(self.o.handle({"op": "timing", "n": 10})["fails"], 0)
        with self.assertRaises(Refused):
            self.o.handle({"op": "write_reg", "id": 20, "addr": 40, "value": 1})   # Não permite alterar o torque por esta operação.
        with self.assertRaises(Refused):
            self.o.handle({"op": "nope"})


if __name__ == "__main__":
    unittest.main()
