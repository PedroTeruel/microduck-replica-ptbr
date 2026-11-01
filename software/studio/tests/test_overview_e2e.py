"""Teste de ponta a ponta da visão geral com robotd simulado, Studio e Edge sem interface.

tests/overview_e2e.mjs verifica os indicadores de temperatura, a lista inicial e a área do controle, além de navegação com o analógico pressionado,
rolagem sobre o palco e gestos no celular. Este módulo valida os registros do robotd simulado (revisões O1, O2, O5, O8, O13, O14, O17 e O18).
O cenário roda em duas fases: main, sem registros anteriores; done, com as seis etapas registradas e a lista recolhida.

Requer Node ≥ 22 e Edge; o teste é ignorado quando não estão disponíveis ou quando STUDIO_E2E=0.
Portas padrão: Studio 18090, robotd simulado 17021, configd simulado 17022 e depuração do Edge 9343. Use portas livres.
OVERVIEW_E2E_DIR define o diretório de logs, perfil do Edge e registros (temporário por padrão); OVERVIEW_SHOTS define o diretório de capturas.
Execução manual:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_overview_e2e'])"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http, moves, nonzero  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
XBOX = "78:86:2E:BB:13:28"


def all_done_records():
    """Gera os registros das cinco etapas concluídas usando as impressões digitais de onboard.py."""
    from fake_robotd import FakeRobotd
    from studio import onboard as O
    from studio.imu import mount_of
    f = FakeRobotd(str(FIXTURE), posture="policy")
    src, mount = mount_of(f.bus, f.calib)
    now = time.time()
    fp = O.full_fp(f.bus, f.calib)
    return {"v": 1, "confirm_servo": {"at": now - 3600, "fp": O.joints_fp(f.calib), "by": "e2e"},
            # A IMU foi ignorada; a lista recolhida deve indicar uma etapa ignorada.
            "skipped": {"imu": {"at": now - 3000, "by": "e2e", "fp": O.mount_fp(src, mount["quat"])}},
            "estop": {"at": now - 2400, "ms": 186, "mac": XBOX, "name": "Xbox Wireless Controller", "build": f.bus["build"]},
            "stood": {"at": now - 1800, "fp": fp}, "walked": {"at": now - 1700, "fp": fp}}


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "Node ≥ 22 ou Edge indisponível, ou STUDIO_E2E=0; teste de ponta a ponta ignorado")
class OverviewE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("OVERVIEW_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="overview-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        rec = cls.dir / "robotd-recv.jsonl"
        rec.unlink(missing_ok=True)
        p_rd, p_cfg, p_web, p_cdp = _port(17021), _port(17022), _port(18090), _port(9343)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}

        def studio(tag):
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② Pato 2", "--dev-autologin", "--servo-sim",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out(f"studio-{tag}.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")

        def node(phase):
            args = [NODE, str(HERE / "overview_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp),
                    "--record", str(rec), "--fake", str(p_cfg), "--phase", phase]
            if os.environ.get("OVERVIEW_SHOTS"):
                args += ["--shots", os.environ["OVERVIEW_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=400, cwd=ROOT)
            (cls.dir / f"overview_e2e-{phase}.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Falha no script Node ({phase}); logs em {cls.dir}: {(r.stderr or '')[-3000:]}")
            (cls.dir / f"overview_e2e-{phase}.json").write_text(r.stdout, encoding="utf-8")
            return json.loads(r.stdout)

        try:
            # Postura pronta para caminhar: analógicos, ações e habilidades disponíveis.
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "policy", "--record", str(rec)],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            studio("main")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}", f"--user-data-dir={cls.dir / 'edge'}",
                 "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "porta de depuração do Edge sem interface")
            cls.out = node("main")
            # Segunda fase: reinicia o Studio com cinco etapas registradas e um controle físico conectado.
            _kill(procs.pop("studio"))
            (state / "onboarding.json").write_text(json.dumps(all_done_records(), ensure_ascii=False), encoding="utf-8")
            import socket
            for _ in range(20):           # O robotd simulado recusou conexões por 0,3 s após a reinicialização.
                try:
                    with socket.create_connection(("127.0.0.1", p_cfg), 3) as s:
                        s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"fake.set","params":{"pad_connected":true}}\n')
                        if b"connected" in s.recv(4096):
                            break
                except OSError:
                    pass
                time.sleep(0.2)
            else:
                raise AssertionError("O configd simulado não aceitou o estado de controle conectado")
            studio("done")
            cls.done = node("done")
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def recs(self, step):
        return self.out["steps"][step]["recs"]

    def test_page_has_no_errors(self):
        self.assertEqual(self.out["errors"], [])
        self.assertEqual(self.done["errors"], [])

    def test_overview_layout(self):
        d = self.out["desk"]
        self.assertEqual(d["cells"], 7)                                  # Inclui câmera e ToF, com a placa por último.
        self.assertIn("°C", d["cpu"])
        self.assertEqual(d["rows"], 6)                                   # Seis etapas na lista inicial.
        self.assertFalse(d["padActive"])                                 # A área do controle está fora da tela no topo da página.
        self.assertEqual(d["nav"], "Visão geral")
        self.assertEqual(d["now"], "1 Ponto zero dos servos")                         # A primeira etapa pendente é destacada.
        self.assertEqual(d["marks"][:3], ["●", "●", "●"])
        tops = self.out["d1100"]["tops"]                                 # Quatro cartões na primeira linha e três na segunda.
        self.assertEqual(len(set(tops[:4])), 1)
        self.assertGreater(tops[4], tops[0])
        self.assertEqual(len(set(tops[4:])), 1)
        for k in ("d1100", "phone", "phone_pad"):
            self.assertLessEqual(self.out[k]["sw"], self.out[k]["cw"], f"{k}: não deve haver rolagem horizontal")

    def test_wheel_on_stage_scrolls_page(self):
        self.assertGreater(self.out["wheel"], 100, "A roda sobre o palco deve rolar a página.")

    def test_pad_anchor(self):
        n = self.out["padNav"]
        self.assertTrue(n["active"])
        self.assertEqual(n["nav"], "Controle")
        self.assertEqual(n["topbar"], 0)                                 # A barra superior permanece fixa.
        # A faixa e a navegação permanecem visíveis; a área do controle para abaixo da faixa.
        self.assertEqual(n["band"][0], 56, n)
        self.assertEqual(n["navTop"], 0, n)
        self.assertTrue(n["band"][1] <= n["top"] <= n["band"][1] + 30, n)

    def assert_released(self, st):
        self.assertTrue(any(nonzero(p) for p in moves(st["before"])), "O analógico deve movimentar o robô antes da saída.")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(st["atLeave" if "atLeave" in st else "atScroll"]))
        self.assertFalse(any(nonzero(p) for p in moves(st["after"])), "O robô deve permanecer parado após sair da área do controle.")
        self.assertFalse(st["active"])
        self.assertTrue(st["offLogged"], "O log do Studio deve registrar a saída da área do controle (drive off).")

    def test_route_change_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["route_leave"])

    def test_scrolling_out_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["scroll_out"])

    def test_checklist_buttons_go_to_the_right_place(self):
        g = self.out["goto"]
        self.assertTrue(g["estop"]["inView"])
        self.assertIn(g["estop"]["focus"], ("pd-estop-btn", "pd-estop"))
        self.assertTrue(g["wizard"]["open"] and g["wizard"]["inView"])
        self.assertEqual(g["imu"], "#/imu")

    def test_swipes_on_phone_send_nothing(self):
        """O2: gestos de rolagem não enviam comandos; manter uma ação ou tocar no botão A envia o comando esperado."""
        for step in ("swipe_pad_blank", "swipe_action", "press_right_after_scroll", "swipe_svg_a"):
            with self.subTest(step=step):
                self.assertEqual([r for r in self.recs(step) if r["method"] in ("robot.move", "robot.head", "robot.do", "robot.mouth",
                                                                                  "robot.sound", "robot.pose")], [])
        self.assertTrue(any(r["method"] == "robot.head" for r in self.recs("hold_action")), "Manter uma ação de cabeça pressionada deve enviar comandos de cabeça.")
        self.assertIn({"method": "robot.do", "params": {"skill": "ground_pick"}, "notify": False}, self.recs("tap_svg_a"))

    def test_board_temperature(self):
        c = self.out["cpu"]
        self.assertTrue(c["throttled"]["bad"])
        self.assertIn("Frequência reduzida: 1008 / 1800 MHz", c["throttled"]["text"])
        self.assertIn("A placa reduziu a frequência por superaquecimento", c["throttled"]["todo"])
        self.assertIn("Temperatura alta", c["hot"])
        self.assertIn("—", c["stale"])                                   # Health expirado aparece como indisponível, nunca como normal (O5).
        self.assertNotIn("Normal", c["stale"])

    def test_unknown_shows_question_marks(self):
        self.assertEqual(self.out["unknown"][:4], ["?", "?", "?", "?"])   # Servos, IMU, gravação e pareamento.
        self.assertIn("Não foi possível ler o estado dos controles no configd", self.out["unknownText"])

    def test_c3_keyboard_repeat_after_leaving_does_not_drive(self):
        """C3: sair da área do controle com W pressionado para o movimento; a repetição do teclado não o retoma ao voltar."""
        k = self.out["steps"]["kbd_repeat"]
        self.assertTrue(any(nonzero(p) for p in moves(k["held"])), "Manter W pressionado deve mover o robô antes de sair.")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(k["out"]))
        self.assertTrue(k["activeBack"] and k["focus"])
        self.assertFalse(any(nonzero(p) for p in moves(k["back"])), "Eventos de repetição não devem retomar o movimento ao voltar.")

    def test_c6_stage_canvas_keeps_pan_y_on_phone(self):
        self.assertEqual(self.out["phoneCanvas"]["computed"], "pan-y", self.out["phoneCanvas"])

    def test_c7_no_hold_after_fast_press_release_press(self):
        """C7: respostas atrasadas não podem manter action_hold após soltar a ação."""

        h = self.out["steps"]["hold_race"]
        self.assertGreater(h["holdsDuring"], 0, h)                     # A ação deve continuar ativa enquanto o botão estiver pressionado.
        self.assertEqual(h["holdsAfter"], 0, h)

    def test_servo_session_kept_with_bar_on_other_pages(self):
        """Mantém os servos ativos ao sair da página, mostra o aviso em outras páginas e exige confirmação em duas etapas para devolver o controle."""
        b = self.out["servoBar"]
        self.assertIn("Ajustando servos · 2 mantendo força · programa principal parado", b["text"])
        self.assertIn("Voltar à página Servos", b["text"])
        self.assertEqual(b["dialogs"], 0)
        self.assertTrue(b["afterReload"])
        self.assertIn("os 15 servos serão liberados agora e o MicroDuck ficará sem sustentação. Segure ou apoie o robô antes de continuar.", b["armed"])      # Revisão D7.
        self.assertIn("Use o botão vermelho acima ou a barra de espaço para liberar os servos", b["text"])                # Revisão D6.
        self.assertIn("Não inicie robotd manualmente; primeiro toque em “Devolver ao programa principal”", b["text"])                               # Revisão D9.
        self.assertTrue(b["sticky"]["visible"], b["sticky"])                                         # O aviso fica visível durante a rolagem.
        self.assertTrue(b["visualFits"], "A postura e o vídeo continuam visíveis ou roláveis com o aviso dos servos.")
        p = b["phone"]
        self.assertTrue(p["visible"], p)                                                             # Continua visível ao rolar até o controle remoto no celular.
        self.assertEqual(p["badge"], "Ajustando os servos")
        self.assertTrue(p["remote"])
        self.assertLessEqual(p["sw"], p["cw"])
        self.assertTrue(b["dbl"]["stillOpen"])                                                       # Duplo clique não devolve o controle (revisão D4).
        self.assertTrue(b["dbl"]["armed"])
        self.assertTrue(b["dbl"]["disarmed"])                                                        # A confirmação expira após 3 s.
        self.assertTrue(b["earlyIgnored"])                                                           # Cliques antes de 700 ms são ignorados.
        self.assertTrue(b["stillThere"])                                                             # O aviso permanece enquanto o programa principal está desconectado.
        self.assertTrue(b["stillOpen"])                                # Um clique não devolve o controle.
        self.assertIn("sudo systemctl start robotd", b["after"])
        self.assertTrue(b["gone"])

    def test_pad_3d_left_of_sticks_and_pauses_out_of_view(self):
        """O cartão 3D pausa fora da tela; no celular fica acima do controle remoto, baixo, sem posição fixa nem rolagem horizontal."""
        d = self.out["pad3d"]
        self.assertGreaterEqual(d["visFrac"], 0.6, d)
        self.assertTrue(d["left"], d)
        self.assertEqual(d["sticky"], "static")
        self.assertEqual(d["stackSticky"], "sticky")
        self.assertTrue(d["cameraBelow"])
        self.assertEqual(d["touch"], "pan-y")
        self.assertTrue(d["drawsInView"])
        self.assertFalse(d["drawsOutOfView"])
        self.assertFalse(d["activeAtTop"])
        p = self.out["phone3d"]
        self.assertTrue(p["above"], p)
        self.assertLessEqual(p["h"], 240)
        self.assertEqual(p["sticky"], "static")

    def test_all_done_collapses_to_one_line(self):
        self.assertIn("As 6 etapas iniciais foram concluídas (ignoradas: 1)", self.done["done"])

    def test_all_done_line_expands_and_remembers(self):
        e = self.done["expanded"]
        self.assertEqual(e["rows"], 6)
        self.assertEqual(e["redo"], 5)                                # Cinco etapas concluídas oferecem Refazer.
        self.assertEqual(e["skip"], 1)
        self.assertIn("Recolher", e["head"])
        self.assertEqual(self.done["expandedAfterReload"], 6)        # O estado expandido persiste em localStorage.
        self.assertTrue(self.done["collapsedAfterReload"])

    def test_every_row_has_three_buttons(self):
        """Cada etapa pendente oferece Fazer, Concluído e Pular; uma etapa concluída oferece Refazer."""
        rows = self.out["threeButtons"]
        self.assertGreaterEqual(len(rows), 3, rows)
        for r in rows:
            with self.subTest(step=r["step"]):
                self.assertEqual(len(r["labels"]), 3, r)
                self.assertEqual(r["labels"][1:], ["Concluído", "Pular"], r)

    def test_skip_unskip_and_redo(self):
        """Concluir, pular, desfazer e refazer etapas mantém o estado e a navegação corretos."""
        m = self.out["marked"]
        self.assertTrue(m["text"].startswith("Você marcou como concluído ("), m)
        self.assertEqual(m["buttons"], ["Refazer", "Cancelar"])
        sk = self.out["skip"]
        self.assertEqual(sk["imu"], "onb-skip")
        self.assertEqual(sk["mark"], "↷")
        self.assertIn("Ignorado (não fazer agora)", sk["imuText"])
        self.assertEqual(sk["now"], "pad")
        self.assertEqual(self.out["unskip"], {"imu": "onb-todo", "now": "imu"})
        self.assertEqual(self.out["redoHash"], "#/servos")
        self.assertEqual(self.out["undone"], "onb-todo")

    def test_estop_skip_needs_two_clicks_within_3s(self):
        self.assertIn("Confirma ignorar", self.out["estopOnce"]["text"])
        self.assertEqual(self.out["estopOnce"]["skipStill"], ["Pular"])  # O botão original permanece; a confirmação é outro botão (revisão D4).
        self.assertEqual(self.out["estopOnce"]["state"], "onb-no")    # Um clique não confirma a ação.
        self.assertEqual(self.out["estopDbl"], {"state": "onb-no", "armed": True},   # Duplo clique não ignora a etapa; apenas abre a confirmação.
                         {k: self.out.get(k) for k in ("estopDblGap", "estopArmed300", "estopClicks", "estopTargets", "estopArms", "dblAtRects")})
        self.assertEqual(self.out["estopTimeout"], {"text": "Pular", "state": "onb-no"})   # A pergunta expira após 3 s.
        self.assertEqual(self.out["estopTwice"], "onb-skip")

    def test_imu_unverified_skip_needs_two_clicks(self):
        """Pular uma IMU não confirmada exige confirmação explícita e não altera o estado sem ela."""
        b = self.out["imuBlocked"]
        self.assertFalse(b["disabled"])
        self.assertEqual(b["ask"], "Confirma ignorar? A orientação da IMU não foi confirmada pelo programa principal: o robô não ficará em pé mesmo se for ignorado")
        self.assertEqual(b["state"], "onb-no")
        self.assertEqual(b["after"], "onb-no")


if __name__ == "__main__":
    unittest.main()
