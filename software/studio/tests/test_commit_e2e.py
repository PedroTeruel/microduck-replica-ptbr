"""Teste ponta a ponta do cenário de fábrica “Gravar no programa principal” (tarefa 13): robotd simulado (--mode commissioning --calib factory), Studio real e Edge sem interface.

Fluxo: tests/commit_e2e.mjs confere o botão desativado e a prévia na etapa 3; depois faz a calibração inicial da IMU (o programa simulado ergue e inclina o robô e verify-imu passa), centraliza os servos (--servo-sim) e grava a etapa 3. O helper simulado muda o robotd para motion + control; a etapa 3 fica concluída e a barra superior mostra o modo de movimento. Por fim, repete com a calibração rejeitada: a página deve exibir o motivo e preservar o cartão de progresso durante a desconexão.
Ativação/desativação da postura em pé na página da IMU (tarefa 17): fica indisponível no modo de calibração, que permite ir à etapa 3; no modo de movimento, envia os mesmos comandos que o cartão de controle “Levantar” e o botão superior de liberação de torque.

O computador não tem o helper root: um script temporário substitui studio.helper.calib_commit por uma implementação simulada apenas neste cenário.
Requer Node ≥ 22 e Edge; sem eles (por exemplo, no robô), o teste é ignorado. STUDIO_E2E=0 também o desativa.
Portas padrão: Studio 18091, robotd simulado 17031, configd 17032 e depuração do Edge 9344. Se estiverem ocupadas, escolha portas livres.
COMMIT_E2E_DIR= diretório para logs e perfil do Edge (por padrão usa um diretório temporário removido ao final); COMMIT_SHOTS= diretório para capturas.
Execução isolada:
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_commit_e2e'])"
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
STUCK_CALIB = "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"

BOOT = r'''
import copy, json, os, socket, sys, time
sys.path[:0] = [ROOT, os.path.join(ROOT, "deps"), os.path.join(ROOT, "dev")]
from studio import helper
from studio import commit as C

helper.available = lambda: True
# Sem o helper root no computador: abrir a página dos servos chama bus-take e devolver chama bus-give-back; aqui ambos são simulados como concluídos.
helper.flag_present = lambda: False
helper.bus_take = lambda by, allow_seated=False, timeout=30: (True, "taken", {})
helper.bus_give_back = lambda by, *, soft=True, marker=None, timeout=60: (True, "soft", {})
# Cartão SSH da página Mais: a imagem de fábrica aceita apenas chaves e não contém nenhuma, como na imagem pública.
helper.ssh_status = lambda timeout=10: (True, "ssh_status", {"exit": 0, "result": "ssh_status", "password_login": False,
                                                            "ssh_active": True, "keys": 0, "user": "radxa"})


def fake_rpc(method, obj):
    port = int(os.environ["E2E_FAKE_PORT"])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": obj}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            part = s.recv(4096)
            if not part:
                break
            buf += part
    return json.loads(buf.split(b"\n", 1)[0])


def fake_set(obj):
    return fake_rpc("fake.set", obj)


# Only replaces the systemd/filesystem boundary. Real ImuBackend capture, solver,
# runtime verify and exact calibration readback still run against fake robotd.
redo_state = {"active": False, "phase": "idle", "session_id": None, "source": None}
redo_backup = None


def fake_imu_state(*, root="/"):
    state = copy.deepcopy(redo_state)
    try:
        with open(os.environ["E2E_OUTCOME_FILE"], encoding="utf-8") as f:
            phase = json.load(f).get("redo_phase")
        if state["active"] and phase in ("entering", "finishing", "cancelling"):
            state["phase"] = phase
    except (OSError, ValueError):
        pass
    return state


def fake_imu_recalibrate(by, action, *, confirmed=None, session_id=None, source=None, quat=None, timeout=180):
    global redo_state, redo_backup
    if action == "enter":
        redo_backup = fake_rpc("robot.busCommand", {"action": "calibration-status"})["result"]
        redo_state = {"active": True, "phase": "commissioning", "session_id": "e2e-imu-session",
                      "source": redo_backup.get("imu_source") or "bus"}
        fake_set({"mode": "commissioning", "imu_pose": "upright"})
        fake_rpc("robot.relax", {})
        time.sleep(0.25)
        return True, "entered", dict(redo_state, note="Modo de calibração restaurado; segure o robô com as duas mãos para iniciar a captura")
    if action == "status":
        return True, "status", dict(redo_state)
    if action not in ("finish", "cancel") or not redo_state["active"]:
        return False, "no_session", {"msg": "Não há uma sessão de recalibração"}
    current = fake_rpc("robot.busCommand", {"action": "calibration-status"})["result"]
    restored = copy.deepcopy(current if action == "finish" else redo_backup)
    restored["calibration"]["motion_enabled"] = redo_backup["calibration"]["motion_enabled"]
    fake_set({"calib_commit": {"calibration": restored, "outcome": "ok"}, "posture": "limp", "imu_pose": "upright"})
    redo_state = {"active": False, "phase": "idle", "session_id": None, "source": None}
    return True, "finished" if action == "finish" else "cancelled", dict(redo_state,
        mode="motion", readback_ok=True, note="Nova orientação salva; modo de movimento restaurado com o torque desativado" if action == "finish" else "Orientação e modo de movimento originais restaurados")


helper.imu_redo_state = fake_imu_state
helper.imu_recalibrate = fake_imu_recalibrate


def outcome():
    path = os.environ.get("E2E_OUTCOME_FILE")
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f) or {}).get("outcome") or "ok"
    except (OSError, ValueError):
        return "ok"


def fake_calib_commit(by, joints, imu, dry_run=False, timeout=180, on_line=None):
    cur = {"motion_enabled": False, "imu_mount_verified": False,
           "imu_mount_quat": list(C.DEFAULT_BUS_QUAT), "current_ma_per_count": 0.0, "units_verified": False,
           "imu_mounts": {}, "joints": [{"name": n, "id": C.JOINT_IDS[n], "zero_raw": 2048,
                                         "direction": -1, "calibrated": False} for n in C.JOINT_ORDER]}
    cal = C.build_calibration(cur, joints, imu)
    C.validate_calibration(cal, imu["source"])
    text = C.render_calibration(cal)
    if on_line:
        on_line({"step": "write", "msg": "Helper simulado: gravação concluída"})
    if dry_run:
        return True, "preview", {"exit": 0, "toml": text}

    want = outcome()
    if want == "reject":
        # O programa simulado entra em motion, mas falha na validação e aguarda o barramento; em seguida, simula uma reinicialização e uma breve desconexão da página.
        fake_set({"calib_commit": {"calibration": cal, "outcome": "reject"}})
        fake_set({"restart": 1.5})
        if on_line:
            on_line({"step": "wait", "msg": "Helper simulado: aguardando o programa principal"})
        time.sleep(1.7)
        # Simula a reversão dos arquivos e do modo para os valores de fábrica e reinicia novamente.
        fake_set({"mode": "commissioning", "calib": "factory"})
        fake_set({"restart": 1.0})
        time.sleep(1.2)
        msg = "A calibração não passou na validação do programa principal: " + %r + "; os arquivos e o modo anteriores foram restaurados e o programa principal foi reiniciado"
        return False, "calib_rejected", {"exit": 5, "msg": msg, "rolled_back": True,
                                         "readback_ok": False, "mismatches": [],
                                         "bus_status": {"mode": "motion", "phase": "waiting_for_bus", "error": %r}}
    fake_set({"calib_commit": {"calibration": cal, "outcome": "ok"}})
    if on_line:
        on_line({"step": "done", "msg": "Helper simulado: gravação concluída; programa principal no modo de movimento"})
    return True, "committed", {"exit": 0, "toml": text, "mode": "motion", "phase": "control",
                               "readback_ok": True, "mismatches": [], "fake": True}


helper.calib_commit = fake_calib_commit
from studio.__main__ import main
main(sys.argv[1:])
''' % (STUCK_CALIB, STUCK_CALIB)


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "Node ≥ 22 ou Edge indisponível, ou STUDIO_E2E=0: teste ponta a ponta de gravação no programa principal ignorado")
class CommitE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("COMMIT_E2E_DIR")
        cls.dir = (Path(keep) if keep else Path(tempfile.mkdtemp(prefix="commit-e2e-"))).resolve()
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.state = cls.dir / "state"
        cls.state.mkdir(exist_ok=True)
        cls.outcome_file = cls.dir / "commit-outcome.json"
        p_rd, p_cfg, p_web, p_cdp = _port(17031), _port(17032), _port(18091), _port(9344)
        cls.p_web, cls.p_cfg = p_web, p_cfg
        env = dict(os.environ, PYTHONIOENCODING="utf-8", E2E_FAKE_PORT=str(p_cfg),
                   E2E_OUTCOME_FILE=str(cls.outcome_file))
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        boot = cls.dir / "e2e_boot.py"
        boot.write_text(f"ROOT = {str(ROOT)!r}\n" + BOOT, encoding="utf-8")
        cls.procs = {
            "fake": subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--mode", "commissioning",
                 "--posture", "commissioning", "--calib", "factory", "--record", str(cls.dir / "robotd-recv.jsonl")],
                cwd=ROOT, env=env, stdout=out("fake.out"), stderr=subprocess.STDOUT),
        }
        try:
            cls.procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(boot), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② Réplica 2", "--dev-autologin", "--servo-sim",
                 "--state-dir", str(cls.state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            edge_dir = cls.dir / "edge"
            shutil.rmtree(edge_dir, ignore_errors=True)      # Um perfil antigo pode deixar a inicialização do Edge muito lenta.
            edge_dir.mkdir(parents=True, exist_ok=True)         # Cria o diretório antes de iniciar o Edge.
            cls.procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-setuid-sandbox",
                 "--enable-unsafe-swiftshader", f"--remote-debugging-port={p_cdp}",
                 f"--user-data-dir={edge_dir}", "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "porta de depuração do Edge", timeout=60)
        except Exception:
            for p in cls.procs.values():
                _kill(p)
            raise
        cls.p_cdp = p_cdp

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", {}).values():
            _kill(p)
        if os.environ.get("COMMIT_E2E_DIR"):
            return
        shutil.rmtree(cls.dir, ignore_errors=True)

    def node(self, phase):
        args = [NODE, str(HERE / "commit_e2e.mjs"), "--url", f"http://127.0.0.1:{self.p_web}/",
                "--cdp", str(self.p_cdp), "--fake-port", str(self.p_cfg), "--phase", phase,
                "--control-file", str(self.outcome_file)]
        if os.environ.get("COMMIT_SHOTS"):
            args += ["--shots", os.environ["COMMIT_SHOTS"]]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=220, cwd=ROOT)
        (self.dir / f"commit_e2e-{phase}.err").write_text(r.stderr or "", encoding="utf-8")
        if r.returncode != 0:
            raise AssertionError(f"Falha no script Node ({phase}); logs em {self.dir}: {(r.stderr or '')[-4000:]}")
        (self.dir / f"commit_e2e-{phase}.json").write_text(r.stdout, encoding="utf-8")
        return json.loads(r.stdout)

    def fake_set(self, obj):
        with socket.create_connection(("127.0.0.1", self.p_cfg), timeout=5) as s:
            s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "fake.set", "params": obj}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                part = s.recv(4096)
                if not part:
                    break
                buf += part
        return json.loads(buf.split(b"\n", 1)[0])

    def test_01_factory_preview(self):
        first = self.node("factory")
        self.assertGreaterEqual(first["factory"]["bad"], 1, first)
        self.assertTrue(first["factory"]["writeDisabled"], first["factory"])
        blob = first["factory"]["desc"] + json.dumps(first["factory"]["checks"], ensure_ascii=False)
        self.assertIn("Ponto zero dos servos", blob)
        self.assertEqual(first["preview"]["jointRows"], 15, first["preview"])
        self.assertTrue(first["preview"]["imu"], first["preview"])
        self.assertIn("motion_enabled = true", first["preview"]["toml"])

    def test_01b_mark_servo_step_done(self):
        """Tarefa 16: marcar a primeira etapa de fábrica como concluída confirma o ponto zero dos servos na etapa 3."""
        m = self.node("mark")
        self.assertEqual(m["before"]["check"], "bad", m)
        self.assertEqual(m["ask"], "Marcar como concluído? O programa principal informa que a calibração está incompleta; o robô não ficará em pé", m)
        self.assertNotEqual(m["afterOne"], "Concluído", m)                     # Um clique não confirma a ação.
        self.assertEqual(m["after"]["row"], "Concluído", m)
        self.assertIn("Você marcou como concluído", m["after"]["text"])
        self.assertIn("Você marcou a etapa 1 como concluída: grava offset 2048 para os 15 servos", m["after"]["check"])
        self.assertEqual(m["errors"], [])

    def test_01d_ssh_card_on_the_more_page(self):
        """A página Mais exibe as regras de acesso SSH de fábrica e pede uma senha web antes de habilitar a configuração."""
        r = self.node("ssh")
        s = r["ssh"]
        self.assertIn("Acesso remoto por SSH", s["text"])
        self.assertIn("A imagem de fábrica aceita somente chaves; não aceita senha e não tem senha padrão", s["text"])
        self.assertEqual(s["now"], "Agora: somente chaves (login por senha desativado), nenhuma chave cadastrada")
        self.assertTrue(s["needWebPw"], s)
        self.assertEqual(s["inputs"], 0)
        self.assertTrue(s["onDisabled"])
        self.assertEqual(r["errors"], [])

    def test_01c_stance_buttons_in_commissioning(self):
        """No modo de calibração, habilitar a postura em pé envia imu.op hold; desativá-la envia relax."""
        s = self.node("stance0")
        st = s["stance"]
        self.assertEqual(st["stand"], {"text": "Habilitar postura em pé", "disabled": False}, st)
        self.assertEqual(st["relax"], {"text": "Desativar torque", "disabled": False}, st)
        self.assertIn("Agora: modo de calibração (torque desativado)", st["now"])
        self.assertIsNone(st["why"], st)
        self.assertFalse(st["goCommit"], st)
        self.assertIn("O modo de calibração também permite ficar em pé", st["text"])
        self.assertEqual(s["holdSent"], [{"name": "imu.op", "args": {"op": "hold"}}])
        self.assertEqual(len(s["dialogs"]), 1, s["dialogs"])
        self.assertIn("Os 15 servos entrarão juntos na postura em pé em 3 segundos e permanecerão travados", s["dialogs"][0])
        self.assertIn("Agora: modo de calibração (em pé)", s["holding"]["now"])
        self.assertEqual(s["holding"]["stand"], {"text": "Habilitar postura em pé", "disabled": True}, s["holding"])
        self.assertEqual(s["holding"]["why"], "O robô já está em pé")
        self.assertEqual(s["relaxSent"], [{"name": "relax", "args": {}}])
        self.assertIn("Agora: modo de calibração (torque desativado)", s["after"]["now"])
        recv = [json.loads(x) for x in (self.dir / "robotd-recv.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        holds = [r for r in recv if r.get("method") == "robot.busCommand" and (r.get("params") or {}).get("action") == "hold-home"]
        self.assertEqual(len(holds), 1, holds)
        dirs = holds[0]["params"]["directions"]
        self.assertEqual(len(dirs), 15)
        self.assertEqual(holds[0]["params"]["duration_ms"], 3000)
        self.assertEqual(s["errors"], [])

    def test_02_imu_coarse_verify(self):
        imu = self.node("imu")
        self.assertIn("orientação confirmada", imu["imu"], imu)

    def test_02b_imu_coarse_verify_while_holding(self):
        result = self.node("imu-hold")
        self.assertIn("orientação confirmada", result["imu"], result)
        self.assertIn("Você pode habilitar a postura em pé primeiro", result["start"])
        for label in ("holdBefore", "holdAfter"):
            self.assertEqual(result[label]["torque_state"], "all_enabled", result[label])
            self.assertEqual(result[label]["hold"]["stage"], "holding", result[label])
            self.assertIs(result[label]["policy_motion_enabled"], False)
        self.assertEqual(result["cleaned"]["torque_state"], "off")
        self.assertEqual(result["errors"], [])

    def test_03_servo_center_then_commit(self):
        from studio import commit as C
        servo = self.node("servo")
        self.assertEqual(servo["planRows"], 15, servo)
        # --servo-sim é apenas uma demonstração; só a calibração real grava servo-centered.json.
        # Registra os 15 servos para simular a centralização na página de servos; o fluxo real é coberto por test_servo_*.
        C.record_centered(str(self.state), list(C.JOINT_IDS.values()), "centralização de demonstração e2e")
        time.sleep(1.6)                       # CommitService relê o arquivo de estado no máximo a cada segundo.

        second = self.node("commit")
        self.assertEqual(second["ready"]["bad"], 0, second["ready"])
        self.assertFalse(second["ready"]["writeDisabled"], second["ready"])
        self.assertIn("reiniciará o programa principal", second["confirmText"])
        self.assertEqual(second["done"]["rowState"], "Concluído", second["done"])
        self.assertIn("modo de movimento", second["topbar"], second)
        self.assertEqual(second["errors"], [])

    def test_03b_stance_buttons_in_motion(self):
        """No modo de movimento, os botões de postura em pé e desativação do torque usam os comandos padrão do controle."""
        s = self.node("stance")
        self.assertEqual(s["before"]["stand"], {"text": "Habilitar postura em pé", "disabled": False}, s["before"])
        self.assertFalse(s["before"]["relax"]["disabled"], s["before"])
        self.assertIn("Agora: torque desativado", s["before"]["now"])
        self.assertFalse(s["before"]["goCommit"])
        self.assertEqual(s["standSent"], [{"name": "pad.op", "args": {"op": "stand"}}])
        self.assertEqual(s["remoteSent"], s["standSent"])
        self.assertEqual(s["relaxSent"], [{"name": "relax", "args": {}}])
        recv = [json.loads(x) for x in (self.dir / "robotd-recv.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        methods = [r.get("method") for r in recv]
        self.assertGreaterEqual(methods.count("robot.init"), 2, methods[-40:])      # Uma chamada pela página da IMU e outra pelo controle.
        self.assertIn("robot.relax", methods)
        self.assertEqual(s["errors"], [])

    def test_04_failure_rollback_is_visible(self):
        self.outcome_file.write_text(json.dumps({"outcome": "reject"}), encoding="utf-8")
        self.fake_set({"mode": "commissioning"})          # Retorna ao modo de calibração antes da nova gravação.
        time.sleep(1.6)
        failed = self.node("fail")
        self.assertTrue(failed["offline"], failed.get("offline"))
        self.assertIn("programa principal está reiniciando", failed["offline"]["text"])
        self.assertEqual(failed["failed"]["rowState"], "Pendente", failed["failed"])
        self.assertTrue(any("A calibração não passou na validação do programa principal" in m for m in failed["failed"]["msgs"]), failed["failed"])
        self.assertEqual((failed.get("wsCommit") or {}).get("job", {}).get("phase"), "failed", failed.get("wsCommit"))
        self.outcome_file.write_text(json.dumps({"outcome": "ok"}), encoding="utf-8")

    def test_03c_verified_imu_can_be_recalibrated(self):
        """Uma orientação já salva pode ser recalibrada após uma segunda confirmação; cancelar restaura o modo de movimento."""
        self.fake_set({"mode": "motion", "calib": "seed", "posture": "limp", "imu_pose": "upright"})
        result = self.node("imu-redo")
        self.assertTrue(result["entryVisible"], result)
        self.assertEqual(result["beforeConfirm"], [], result)
        self.assertTrue(result["active"]["stand"]["disabled"], result)
        self.assertFalse(result["active"]["relax"]["disabled"], result)
        self.assertIn("Antes de iniciar a verificação, coloque o robô na posição correta", result["verifyInstruction"])
        self.assertEqual(result["original"]["calibration"]["joints"], result["after"]["calibration"]["joints"])
        self.assertTrue(any(j["zero_raw"] != 2048 for j in result["after"]["calibration"]["joints"]))
        self.assertEqual(result["after"], result["cancelled"])
        self.assertIn("torque desativado", result["afterStance"]["now"])
        self.assertEqual(result["motionCommands"], [])
        self.assertEqual(result["commissioningCommands"], [])
        self.assertEqual(result["recoveredPhases"], ["entering", "finishing", "cancelling"])
        self.assertEqual(result["errors"], [], result)


if __name__ == "__main__":
    unittest.main()
