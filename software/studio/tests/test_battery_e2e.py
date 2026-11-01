"""Teste ponta a ponta da bateria (battery-plan.md v2): robotd simulado (roteiro de bateria), Studio real (estimador acelerado em 20x) e Edge sem interface.
tests/battery_e2e.mjs verifica os estados do indicador da bateria na Visão geral (repouso, detalhes, sem leitura, estimativa em andamento, alertas amarelo e vermelho, tensão muito baixa e largura de celular),
depois altera o limite crítico na página de configurações (incluindo um valor inválido), calibra a leitura da bateria e seleciona a fonte de bancada; este arquivo confere os resultados.

Requer Node (≥ 22) e Edge; sem eles, o teste é ignorado. Também pode ser ignorado definindo STUDIO_E2E=0.
As portas padrão são Studio 18103, robotd simulado 17055 / configd 17056 e depuração do Edge 9353; se alguma estiver ocupada, será escolhida outra disponível.
BATTERY_E2E_DIR=diretório: local para os logs e o perfil do Edge (por padrão, usa um diretório temporário removido ao final); BATTERY_SHOTS=diretório: local opcional para capturas de tela.
Execução isolada:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_battery_e2e'])"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "Node ≥ 22 ou Edge não está disponível, ou STUDIO_E2E=0; teste ponta a ponta da bateria ignorado")
class BatteryE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("BATTERY_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="battery-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        p_rd, p_cfg, p_web, p_cdp = _port(17055), _port(17056), _port(18103), _port(9353)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}
        try:
            # O robô inicia sem torque: a leitura em repouso é mais precisa, e a calibração da tensão também exige torque desativado.
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "limp"],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② Microduck 2", "--dev-autologin",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=dict(env, STUDIO_BATTERY_SPEED="20"), stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}", f"--user-data-dir={cls.dir / 'edge'}",
                 "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "porta de depuração do Edge sem interface")
            args = [NODE, str(HERE / "battery_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp),
                    "--fake", str(p_cfg)]
            if os.environ.get("BATTERY_SHOTS"):
                args += ["--shots", os.environ["BATTERY_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=ROOT)
            (cls.dir / "battery_e2e.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Falha no script Node (logs em {cls.dir}): {(r.stderr or '')[-3000:]}")
            (cls.dir / "battery_e2e.json").write_text(r.stdout, encoding="utf-8")
            cls.out = json.loads(r.stdout)
            cls.settings_file = json.loads((state / "battery-settings.json").read_text(encoding="utf-8"))
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def step(self, name):
        return self.out["steps"][name]

    def test_no_page_errors(self):
        self.assertEqual(self.out["errors"], [])

    def test_overview_states(self):
        calm = self.step("calm")
        self.assertRegex(calm["text"], r"Bateria (4[5-9]|50) % 7\.6\d V · Em repouso")  # Conjunto do robô 2: 7,62 V → cerca de 48%
        self.assertNotIn("warn", calm["cls"])
        self.assertIn("Não foi possível ler a tensão", self.step("nodata")["text"])
        self.assertIn("Estimando", self.step("estimating")["text"])
        self.assertNotIn("Bateria", self.step("estimating")["todo"])  # Durante a inicialização, não deve haver alertas amarelos ou vermelhos (revisão B-R2).
        warn = self.step("warn")
        self.assertRegex(warn["text"], r"Bateria (2\d|30) %")  # 7,40 V, com o desvio do segundo Microduck: 7,42 V → 30%.
        self.assertRegex(warn["todo"], r"Bateria em cerca de (2\d|30)%")
        red = self.step("red")
        self.assertRegex(red["todo"], r"Restam cerca de \d+% de bateria")
        self.assertIn("não para automaticamente", red["todo"])  # O alerta é apenas informativo.
        low = self.step("lowvolt")
        self.assertIn("Tensão muito baixa", low["todo"])
        self.assertTrue(low["badge"])
        self.assertLess(low["todo"].index("Tensão muito baixa"), len(low["todo"]))

    def test_detail_explains(self):
        d = self.step("detail")
        self.assertEqual(d["expanded"], "true")
        text = "\n".join(d["lines"])
        for s in ("Momento de menor esforço nos últimos 5 min", "média após descartar as 3 leituras mais altas e mais baixas entre 15 servos", "3.81 V por célula", "±15%",
                  "Estimativa do programa principal", "escala linear de 6,6–8,2 V", "não para automaticamente", "Recarregue a bateria pouco depois de descarregá-la. Para armazenamento prolongado, deixe-a com meia carga (cerca de 7,4–7,6 V)"):
            self.assertIn(s, text)

    def test_mobile_no_horizontal_scroll(self):
        m = self.step("mobile")
        self.assertLessEqual(m["sw"], m["cw"])
        self.assertLessEqual(m["popRight"], m["cw"])

    def test_settings(self):
        s = self.step("settings")["text"]
        for x in ("Bateria de lítio 2S (NP-F550 etc.)", "Fonte de bancada (sem estimativa de carga)", "Limite de aviso (amarelo)", "Limite crítico (vermelho)", "Limite de tensão sob carga", "Calibração da leitura", "Medi a tensão da bateria",
                  "também é possível comparar com a tensão exibida nela enquanto o Microduck estiver parado", "faixa amarela aparece antes",
                  "Recarregue a bateria pouco depois de descarregá-la", "não para automaticamente"):
            self.assertIn(x, s)
        self.assertIn("não está pelo menos 5% abaixo", self.step("bad")["msg"])
        self.assertIn("Salvo e aplicado imediatamente", self.step("saved")["msg"])
        self.assertTrue(any("Limite crítico 15% → 20%" in m for m in self.step("saved")["logs"]))
        self.assertIn("diferença: +0.18 V", self.step("calc")["msg"])
        self.assertIn("calibração +0.18 V", self.step("calibrated")["now"])
        # Restaura a bateria 2S; o limite crítico e a calibração permanecem salvos.
        self.assertEqual((self.settings_file["preset"], self.settings_file["red_pct"], self.settings_file["cal_offset_v"]),
                         ("2s_liion", 20, 0.18))

    def test_bench(self):
        self.assertIn("mostra somente a tensão, sem calcular nem avisar a porcentagem de carga", self.step("benchForm")["text"])
        self.assertNotIn("Limite de aviso (amarelo)", self.step("benchForm")["text"])
        b = self.step("bench")
        self.assertRegex(b["text"], r"Bateria 7\.\d\d V · Fonte de bancada")
        self.assertNotIn("%", b["text"])
        self.assertNotIn("Bateria", b["todo"])
        text = "\n".join(b["lines"])
        self.assertIn("Fonte de bancada", text)
        self.assertNotIn("Estimativa do programa principal", text)
        self.assertNotIn("Recarregue a bateria pouco depois de descarregá-la", text)


if __name__ == "__main__":
    unittest.main()
