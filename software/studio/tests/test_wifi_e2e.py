"""Teste ponta a ponta de conexão Wi-Fi do Studio: configd simulado grava net.json; Studio real e Edge sem interface (390 px).

tests/wifi_e2e.mjs confere o cartão, seleciona Home, informa uma senha incorreta, confirma e aguarda a falha.
Tarefa 17: após enviar a conexão, a página perde contato com o robô, exibe o cartão de localização e consulta probe.svg; quando o hotspot volta, as consultas param e a página abre o endereço encontrado.
Requer Node (>= 22) e Edge; sem eles, o teste é ignorado. STUDIO_E2E=0 também o desativa.
Portas padrão: Studio 18091, robotd simulado 17031, configd simulado 17032 e depuração do Edge 9344. Use portas livres se necessário.
WIFI_E2E_DIR= diretório para logs, perfil do Edge e net.json (temporário por padrão, removido ao final); WIFI_SHOTS= diretório para capturas.
Execução isolada:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_wifi_e2e'])"
"""
import json
import os
import re
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
                     "Node >= 22 ou Edge indisponível, ou STUDIO_E2E=0: teste ponta a ponta de Wi-Fi ignorado")
class WifiE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("WIFI_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="wifi-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        net_state = cls.dir / "net.json"
        rec = cls.dir / "robotd-recv.jsonl"
        rec.unlink(missing_ok=True)
        p_rd, p_cfg, p_web, p_cdp = _port(17031), _port(17032), _port(18091), _port(9344)
        cls.port = p_web
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}
        try:
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "holding",
                 "--record", str(rec), "--net-mode", "hotspot", "--net-state-file", str(net_state)],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}",
                 "--robotd", f"tcp:127.0.0.1:{p_rd}", "--configd", f"tcp:127.0.0.1:{p_cfg}",
                 "--net-state", str(net_state), "--dev-autologin", "--servo-sim",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}",
                 f"--user-data-dir={cls.dir / 'edge'}", "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "porta de depuração do Edge sem interface")
            args = [NODE, str(HERE / "wifi_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp)]
            if os.environ.get("WIFI_SHOTS"):
                args += ["--shots", os.environ["WIFI_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=240, cwd=ROOT)
            (cls.dir / "wifi_e2e.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Falha no script Node (logs em {cls.dir}): {(r.stderr or '')[-3000:]}")
            (cls.dir / "wifi_e2e.json").write_text(r.stdout, encoding="utf-8")
            cls.out = json.loads(r.stdout)
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def test_page_has_no_errors(self):
        self.assertEqual(self.out["errors"], [])

    def test_card_is_before_onboard_and_fits_phone(self):
        c = self.out["card"]
        self.assertTrue(c["beforeOnboard"])
        self.assertIn("Este é o hotspot do robô (Microduck-fake)", c["text"])
        self.assertIn(f"duck-fake.local:{self.port}", c["text"])
        self.assertIn("A senha do hotspot é conhecida", c["text"])
        self.assertLessEqual(c["sw"], c["cw"])

    def test_card_addresses_by_device_and_own_hotspot_filtered(self):
        """Tarefa 16: mostra endereços por dispositivo, filtra o hotspot do robô e exibe o IP ao passar o mouse no nome."""
        c = self.out["card"]
        self.assertIn(f"Computador Windows: http://duck-fake:{self.port}/ (funciona mesmo com o proxy ligado)", c["text"])
        self.assertIn(f"iPhone ou Mac: http://duck-fake.local:{self.port}/", c["text"])
        self.assertIn("Procure duck-fake na lista de dispositivos do roteador", c["text"])
        self.assertIn("modo TUN do Clash", c["text"])
        self.assertIn("Home", c["ssids"])
        self.assertNotIn("Microduck-fake", c["ssids"])
        self.assertIn("IP 10.42.0.1", c["nameTitle"])

    def test_duck_addresses_in_more_page(self):
        a = self.out["addr"]
        self.assertEqual([(r["kind"], r["url"]) for r in a["rows"]],
                         [("ip", f"http://10.42.0.1:{self.port}/"), ("host", f"http://duck-fake:{self.port}/"),
                          ("local", f"http://duck-fake.local:{self.port}/")])
        self.assertTrue(all(r["copy"] == "Copiar" for r in a["rows"]))
        self.assertIn(a["copied"], ("Copiado", "Não foi possível copiar; mantenha o endereço pressionado"))
        self.assertIn("Endereço deste robô", a["text"])
        self.assertLessEqual(a["sw"], a["cw"])

    def test_home_expands_for_password_and_saved_network_is_marked(self):
        self.assertEqual(self.out["expanded"]["pskType"], "password")
        self.assertEqual(self.out["expanded"]["saved"], "Salvo")
        self.assertIn("O robô precisa da senha sempre que se conecta, conforme o procedimento oficial de rede", self.out["expanded"]["savedNote"])

    def test_confirm_and_switching_text(self):
        c = self.out["confirm"]
        self.assertIn("O robô desligará o hotspot e se conectará a “Home”", c)
        self.assertIn("Seu celular será desconectado", c)
        self.assertIn("lista de dispositivos do roteador", c)
        self.assertIn("Microduck-fake", c)
        s = self.out["switching"]
        self.assertIn("Conectando… o celular será desconectado em instantes", s)
        # A mensagem durante a troca mostra os três endereços conforme o dispositivo (tarefa 16).
        self.assertIn(f"Computador Windows: http://duck-fake:{self.port}/ (funciona mesmo com o proxy ligado)", s)
        self.assertIn(f"iPhone ou Mac: http://duck-fake.local:{self.port}/", s)
        self.assertIn("Android ou se os endereços acima não funcionarem: procure duck-fake na lista do roteador e use o IP", s)
        self.assertIn("configure a rede local (192.168.0.0/16) como conexão direta no Clash", s)

    def test_wrong_password_is_red_last_try_and_fits_phone(self):
        lt = self.out["lastTry"]
        self.assertIn("Falha na última conexão com “Home”: senha incorreta", lt["text"])
        self.assertNotEqual(lt["color"], "rgb(0, 0, 0)")
        self.assertLessEqual(lt["sw"], lt["cw"])

    def test_phone_can_open_logs_and_diag_from_more(self):
        m = self.out["mobile"]
        self.assertTrue(m["navHidden"])
        self.assertTrue(m["hasLogs"])
        self.assertTrue(m["hasDiag"])
        self.assertIn("Exportar pacote de diagnóstico", m["logs"])
        self.assertEqual(m["diagClicked"], "/api/diag")

    def test_finding_card_probes_and_stops_when_hotspot_returns(self):
        """Tarefa 17: se a página se desconectar após enviar a conexão, mostra o cartão para localizar o robô e consulta os endereços a cada 2 s.
        Quando a conexão é restabelecida, oculta o cartão, interrompe as consultas e mantém o motivo da falha."""
        f = self.out["findA"]
        self.assertEqual(f["phase"], "finding")
        self.assertIn("O robô está se conectando a “Ghost”…", f["text"])
        self.assertIn("Conecte este dispositivo novamente a “Ghost” (não é necessário se o computador estiver conectado por cabo); a página abrirá quando localizar o robô", f["text"])
        self.assertIn("Se não encontrar, procure o IP de duck-fake na lista de dispositivos do roteador", f["text"])
        self.assertEqual(f["links"], [f"http://duck-fake:{self.port}/", f"http://duck-fake.local:{self.port}/"])
        self.assertLessEqual(f["sw"], f["cw"])
        probed = {re.sub(r"\?t=\d+$", "", u) for u in f["probes"]}
        self.assertEqual(probed, {f"http://duck-fake:{self.port}/probe.svg", f"http://duck-fake.local:{self.port}/probe.svg"})
        self.assertGreaterEqual(len(f["probes"]), 4, f["probes"])               # Pelo menos duas rodadas, com dois endereços cada, em 4,5 segundos.
        b = self.out["findBack"]
        self.assertFalse(b["finding"])
        self.assertIn("Falha na última conexão com “Ghost”: o robô não encontrou esta rede Wi-Fi", b["lastTry"])
        self.assertEqual(b["probesLater"], b["probesAtBack"])                   # O hotspot voltou; não há novas consultas.

    def test_found_duck_opens_new_address(self):
        """Tarefa 17: ao encontrar duck-fake.local, a página redireciona automaticamente."""
        self.assertEqual(self.out["found"]["href"], f"http://duck-fake.local:{self.port}/")
        self.assertEqual(self.out["found"]["title"], "found")

    def test_hotspot_password_warning_only_while_no_password(self):
        self.assertTrue(self.out["hotspotPasswordHint"])
        self.assertFalse(self.out["hotspotPasswordHintAfterSet"])
        self.assertEqual(self.out["passwordSet"], 200)          # A senha foi realmente configurada pela página.


if __name__ == "__main__":
    unittest.main()
