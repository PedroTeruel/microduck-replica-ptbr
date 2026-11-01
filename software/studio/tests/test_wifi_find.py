"""Localização do novo endereço do robô após conectar ao Wi-Fi (tarefa 17): executa a lógica real de web/wifi.js no Node, sem navegador.

tests/wifi_find.mjs executa cenários com relógio e sondagens simulados (robô encontrado, timeout de 3 min, retorno do hotspot, endereço sem resposta e probeImage),
e registra em JSON os endereços consultados, redirecionamentos e desistências. O cartão da página e a navegação real ficam em tests/wifi_e2e.mjs.
Requer Node (>= 20); sem Node, o teste é ignorado. Execução isolada:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_wifi_find'])"
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")
HOST = "http://duck-0de6:8000/"
LOCAL = "http://duck-0de6.local:8000/"


@unittest.skipUnless(NODE, "Node não está instalado; teste da lógica de busca do robô ignorado.")
class FindDuckLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(HERE / "wifi_find.mjs")], capture_output=True, text=True,
                           encoding="utf-8", timeout=60, cwd=str(HERE.parent))
        if r.returncode != 0:
            raise AssertionError(f"Erro no script Node: {r.stderr[-2000:]}")
        cls.out = json.loads(r.stdout)

    def test_every_two_seconds_for_three_minutes(self):
        self.assertEqual(self.out["consts"], {"every": 2000, "giveUp": 180000, "silent": 5000})

    def test_addresses_from_net_json_hostname(self):
        self.assertEqual(self.out["urls"], [HOST, LOCAL])
        self.assertEqual(self.out["urlsPort"], ["http://duck-c51b:18080/", "http://duck-c51b.local:18080/"])  # Usa a porta de --listen.
        self.assertEqual(self.out["urlsBare"], ["http://duck-c51b:8000/", "http://duck-c51b.local:8000/"])

    def test_first_success_jumps_and_stops(self):
        s = self.out["found"]
        self.assertEqual(s["found"], [{"t": 6000, "url": LOCAL}])
        self.assertEqual(s["gaveUp"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(sorted({c["t"] for c in s["calls"]}), [0, 2000, 4000, 6000])        # Consulta a cada 2 s e para ao encontrar.
        self.assertTrue(all({c["url"] for c in s["calls"] if c["t"] == t} == {HOST, LOCAL} for t in (0, 2000, 4000, 6000)))

    def test_gives_up_after_three_minutes(self):
        s = self.out["timeout"]
        self.assertEqual(s["gaveUp"], [180000])
        self.assertEqual(s["found"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(len(s["calls"]), 2 * 90)                                       # Dois endereços de 0 a 178 s, em intervalos de 2 s.
        self.assertEqual(max(c["t"] for c in s["calls"]), 178000)

    def test_stop_when_hotspot_comes_back(self):
        s = self.out["stop"]
        self.assertEqual(s["found"], [])                     # Uma resposta após stop não provoca navegação.
        self.assertEqual(s["gaveUp"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(max(c["t"] for c in s["calls"]), 4000)

    def test_hanging_address_is_not_piled_up(self):
        s = self.out["hang"]
        local = [c["t"] for c in s["calls"] if c["url"] == LOCAL]
        host = [c["t"] for c in s["calls"] if c["url"] == HOST]
        self.assertEqual(local, [0])
        self.assertEqual(host, [0, 2000, 4000, 6000, 8000, 10000])

    def test_probe_image_loads_probe_svg(self):
        img = self.out["image"]
        self.assertEqual(len(img["srcs"]), 3)
        self.assertRegex(img["srcs"][0], r"^" + re.escape(HOST) + r"probe\.svg\?t=\d+$")
        self.assertRegex(img["srcs"][1], r"^" + re.escape(LOCAL) + r"probe\.svg\?t=\d+$")
        self.assertTrue(img["load"])
        self.assertFalse(img["error"])
        self.assertFalse(img["timeout"])
        self.assertTrue(img["handlersCleared"])


if __name__ == "__main__":
    unittest.main()
