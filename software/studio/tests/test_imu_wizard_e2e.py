"""Teste ponta a ponta da coleta do IMU no frontend (código real de web/imu.js, executado com Node)
e do cálculo no backend (imu_calib.solve).

tests/imu_wizard_e2e.mjs fornece leituras simuladas à lógica de coleta da página e imprime em JSON
as etapas registradas e os dados coletados em cada cenário. Este arquivo passa esses dados ao Python
para verificar se tudo que o frontend aceita também é processado corretamente pelo backend.
É necessário ter Node (>= 20.6); sem ele, o teste é ignorado. Para executar separadamente:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_imu_wizard_e2e'])"
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from studio import imu_calib as ic  # noqa: E402

NODE = shutil.which("node")
ALL = {"still": True, "fwd": True, "back": True, "left": True, "right": True}


@unittest.skipUnless(NODE, "Node não está instalado; teste ponta a ponta da coleta do frontend ignorado")
class CollectToSolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(HERE / "imu_wizard_e2e.mjs")], capture_output=True, text=True,
                           encoding="utf-8", timeout=60, cwd=str(HERE.parent))
        if r.returncode != 0:
            raise AssertionError(f"Erro no script Node: {r.stderr[-2000:]}")
        cls.out = json.loads(r.stdout)
        # A orientação antiga simulada contém o erro ERR (leitura = ERR · gravidade real); a correção correta é ERR⁻¹.
        err = tuple(tuple(row) for row in cls.out["err"])
        cls.want = ic.q_from_mat(ic.mat_t(err))

    def solve(self, sc, name):
        self.assertEqual(sc["phase"], "solving", f"{name}: parou em {sc['phase']}, etapas registradas: {sc['done']}")
        res = ic.solve(sc["samples"], frame="body", old_mount=(1.0, 0.0, 0.0, 0.0))
        self.assertTrue(res["ok"], f"{name}: frontend aceitou, mas o backend rejeitou: {res['reason']}")
        err = ic.q_angle_deg(ic.q_mul(ic.q_conj(res["mount"]), self.want))
        return res, err

    def test_normal_with_duplicates(self):
        sc = self.out["normal"]
        res, err = self.solve(sc, "normal")
        self.assertLess(err, 0.5)
        self.assertAlmostEqual(res["parts"]["pitch_deg"], 3.0, delta=0.3)
        self.assertAlmostEqual(res["parts"]["yaw_deg"], 4.0, delta=0.5)
        # Cada quadro foi enviado duas vezes com o mesmo state_t_ns: conte apenas uma vez; ao concluir cada etapa,
        # registre um evento (usado pela página para tocar um som); o último evento é all.
        self.assertEqual(sum(sc["counts"].values()) + sc["seg"], sc["pushed"])
        self.assertEqual(sc["events"], ["still", "fwd", "back", "left", "all"])

    def test_dedupe_without_timestamp(self):
        sc = self.out["normal_nokey"]
        _, err = self.solve(sc, "normal_nokey")
        self.assertLess(err, 0.5)
        self.assertEqual(sum(sc["counts"].values()) + sc["seg"], sc["pushed"])

    def test_any_order(self):
        """A ordem é livre: direita, trás, esquerda e frente."""
        sc = self.out["any_order"]
        _, err = self.solve(sc, "any_order")
        self.assertLess(err, 0.5)
        self.assertEqual(sc["events"], ["still", "right", "back", "left", "all"])

    def test_overshoot(self):
        _, err = self.solve(self.out["overshoot"], "overshoot")
        self.assertLess(err, 0.5)

    def test_spike(self):
        _, err = self.solve(self.out["spike"], "spike")
        self.assertLess(err, 0.5)

    def test_still_spike_not_reset(self):
        """Dois quadros instáveis durante o repouso não reiniciam a contagem do frontend; a etapa ainda termina em cerca de 3 segundos e o backend aceita os dados."""
        _, err = self.solve(self.out["still_spike"], "still_spike")
        self.assertLess(err, 0.5)
        self.assertLessEqual(self.out["still_spike"]["counts"]["still"], 32)

    def test_hand_offset(self):
        res, err = self.solve(self.out["hand_offset"], "hand_offset")
        self.assertLess(err, 1.0)
        self.assertTrue(all(res["steps"][k]["ref"] == "Posição nivelada" for k in ic.TILTS))

    def test_too_small_not_taken(self):
        sc = self.out["too_small"]
        self.assertEqual(sc["phase"], "collect")
        self.assertEqual(sc["done"], {"still": True, "fwd": False, "back": False, "left": False, "right": False})

    def test_offline_pauses(self):
        sc = self.out["offline"]
        self.assertEqual(sc["phase"], "collect")
        self.assertEqual(sc["counts"]["still"], 0)
        self.assertIn("interrompidas", sc["paused"])

    def test_wrong_direction_then_fix(self):
        """A etapa para trás foi inclinada para a frente e não conta. Ao encerrar, falta a etapa para trás; colete-a e os dados ficam completos."""
        sc = self.out["back_wrong"]
        self.assertEqual(sc["before"]["phase"], "collect")
        self.assertFalse(sc["before"]["done"]["back"])
        self.assertTrue(sc["before"]["done"]["left"] and sc["before"]["done"]["right"])
        self.assertEqual(sc["short"], {"phase": "short", "missing": ["back"]})
        _, err = self.solve(sc["after"], "back_wrong corrigido")
        self.assertLess(err, 0.5)

    def test_end_early(self):
        sc = self.out["short"]
        self.assertEqual(sc["phase"], "short")
        self.assertEqual(sc["missing"], ["back", "left", "right"])

    def test_redo_one_step(self):
        """Refazer apenas a inclinação para a esquerda preserva as demais etapas e completa a coleta automaticamente."""
        sc = self.out["redo"]
        self.assertEqual(sc["mid"]["phase"], "collect")
        self.assertEqual(sc["mid"]["done"], dict(ALL, left=False))
        self.assertEqual(sc["mid"]["left"], 0)
        self.assertTrue(sc["fwd_kept"])
        res, err = self.solve(sc["after"], "redo")
        self.assertLess(err, 0.5)
        self.assertAlmostEqual(res["steps"]["left"]["tilt_deg"], 18, delta=0.6)


if __name__ == "__main__":
    unittest.main()
