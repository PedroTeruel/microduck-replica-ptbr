"""robotd e configd falsos: reproduz respostas reais gravadas no robô (por dev/record_robotd.py)
para executar o Studio no computador sem conectar o robô.

    (robotd escuta em tcp 127.0.0.1:17001; configd em 17002; somente na interface local)

Comportamentos simulados (review-impl-plan I8):
- Cada conexão é processada em série: lê uma linha e responde uma linha.
- hello deve incluir api_version (como no robô real; sem isso retorna -32602).
- robot.relax retorna accepted:true imediatamente; após relax_delay, busStatus confirma torque OFF;
  depois de hd_delay, restore_pending / temporary_gains_applied de hd1910 são limpos (no robô real, ambos ficam True em pé).
- No modo de depuração, desativar o torque altera apenas torque_state para off, sem trocar o modo.
- restart(segundos) desconecta todas as conexões e recusa novas durante o intervalo, simulando uma reinicialização do robotd.
- inject insere linhas (dados inválidos ou JSON que não seja objeto) antes da próxima resposta; errors faz um método retornar erro.
- robot.subscribe envia robot.state na frequência hz e contabiliza os assinantes.
- No modo de depuração, policies e subscribe retornam erro.
- delays permite atrasar deliberadamente um método (para verificar que pedidos lentos não bloqueiam a desativação do torque).
- down=True recusa novas conexões, simulando a ausência do programa principal.
- Notificações sem id (robot.move / head / pose / mouth / sound / do) seguem JSON-RPC e não recebem resposta, como no robotd.
- Pedidos da página do controle (robot.init / enable / do / sound / stop / pose / head / mouth, pad.bindings) são aceitos.
  enable / init também alteram a postura (ativar → pronto para caminhar; desativar / init → em pé e imóvel); usados no teste e2e do controle web.
- O arquivo --record registra cada entrada (método, parâmetros, se é notificação e horário), uma linha JSON, para conferir o que foi enviado ao robotd.
- fake.set {posture?, pad_connected?} é uma interface de controle para testes: altera a postura e simula um controle físico conectado (configd pad.status retorna conectado).
  A reorganização da página inicial (revisão O18) também adicionou {calib: ok / seed / uncal / unavailable}, {pads: [...]},
  {cpu: {c, level, khz, max_khz}} para alterar temperatura e frequência da placa em health, e {errors: {método: {code, message} ou null}}.
- O modo do programa principal é definido somente por --mode commissioning|motion (fork main.rs:1300-1315), independentemente do conteúdo do arquivo de calibração.
  No modo de calibração, calibration-status pode ser consultado imediatamente. busStatus segue o comportamento do fork (perto de main.rs:4687): antes da primeira leitura bem-sucedida, retorna
  {"build","mode":"commissioning","phase":"configuring_bus","port"} (somente essas quatro chaves; se os servos estiverem sem alimentação, retorna waiting_for_bus + error).
  Após a primeira leitura (comm_read_s segundos depois da inicialização), retorna um instantâneo atual: campos de Status em feetech_commissioning.rs (phase ready; read_error se os servos forem desligados),
  com last_sample (15 servos e campos da IMU com os mesmos nomes do fork). --commissioning-stuck-status (ou fake.set {commissioning_stuck: true})
  simula o fork antigo: o relatório de inicialização nunca é limpo e o Studio continua mostrando “Iniciando” (como na validação em hardware de 20/10).
  No modo de movimento, calibração inválida ou barramento dos servos indisponível retorna phase=waiting_for_bus + error; calibration-status retorna
  o estado solicitado (ok / reject / servo_power). verify-imu simula as regras do fork: postura alinhada a ≤5° e inclinação do pescoço entre 12° e 30° em até 20 segundos;
  uma direção incorreta não salva dados. --mode commissioning --calib factory simula o estado de fábrica.
- calib=seed simula valores zero_raw diferentes de 2048 no arquivo de calibração (fork packaging/hd1910-calibration.robot.toml).
- A configuração de rede (tarefa 10b) simula net.status / net.scan / net.connect / net.forget de configd. --net-mode hotspot|wifi|none
  também grava um net.json falso em --net-state-file (para visualizar o cartão “Conectar ao Wi-Fi” no computador). A senha wrongpass retorna bad_key;
  o SSID Ghost retorna not_found; autenticação corporativa ou senha ausente retorna unsupported; os demais conectam após 3 segundos.
- Roteiro da bateria (battery-plan.md v2 §6): fake.set {battery: {v, drop_per_s, sag, gone, glitch}}; null desativa.
  v é a tensão com torque desativado; os desvios medidos nas 15 peças do robô nº 2 em 18/10 são arredondados a 0,1 V;
  em pé ou com política ativa, subtrai mais 0,08 V; sag é uma queda adicional (simula caminhada).
  drop_per_s define a queda por segundo; gone faz as 15 peças reportarem 0 V (servos desligados); glitch faz a próxima resposta busStatus retornar esse valor para as 15.
  health.battery também é atualizado: volts usa EMA α=0,1 desses valores (como no robô real), e percent usa a escala linear 6,6–8,2 do robotd.
- Execução e ajuste de parâmetros (plano T1–T3): quatro etapas robot.startupSubscribe, postura walk_unloaded, active_* com a política ativa e as chaves fake.set startup / servo_parameters / walk_profile / guard / slot_error ficam em dev/fake_tune.py.

Nos testes, importe FakeRobotd e execute-o no mesmo loop de eventos.
"""
import argparse
import asyncio
import copy
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # Ao executar com -I, o Python não adiciona este diretório automaticamente; fake_tune fica aqui.
import fake_tune  # noqa: E402


def load_fixture(path):
    replies, frames = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") == "reply":
                key = d["method"] if d["method"] != "robot.busCommand" else "busCommand:" + d["params"].get("action", "")
                replies[key] = (d["reply"] or {}).get("result")
            elif d.get("kind") == "notify":
                m = d.get("msg") or {}
                if m.get("method") == "robot.state":
                    frames.append(m.get("params"))
    return replies, frames


DEFAULT_BINDINGS = [{"button": b, "skill": s, "overridden": False} for b, s in (
    ("a", "ground_pick"), ("x", "roulade"), ("lb", "kick_left"), ("rb", "kick_right"), ("dpad_down", "sit_toggle"))]
ACCEPT = {"robot.init", "robot.enable", "robot.do", "robot.sound", "robot.stop", "robot.pose", "robot.head",
          "robot.mouth", "robot.move"}
STUCK_CALIB = "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"
NO_POWER = ("torque readback at register 40: Feetech Sync Read timeout; missing IDs [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, "
            "10, 11, 12, 13, 14]")
NO_CALIB = {"code": -32603, "message": "calibration not available yet"}
COMMISSIONING_READ_S = 0.3     # Tempo até a primeira leitura após iniciar/reiniciar o modo de calibração (imediato no hardware; pequeno atraso para exibir o relatório).
COMMISSIONING_BOOT_KEYS = ("build", "mode", "phase", "port")   # O relatório de inicialização contém apenas estas quatro chaves (fork main.rs:1310-1315).
SEED_ZERO = {20: 2035, 21: 2176, 23: 1990, 24: 2101}     # Valores-semente incluídos no pacote: alguns servos diferem de 2048.
POSTURES = ["holding", "limp", "policy", "commissioning", "starting", "stuck_calib", "walk_unloaded"]
IMU_VERIFY_UPRIGHT_MAX_DEG = 5.0
IMU_VERIFY_NOSE_MIN_DEG = 12.0
IMU_VERIFY_NOSE_MAX_DEG = 30.0
VERIFY_NO_SAMPLE = "verify-imu needs a live {source} sample; check busStatus last_sample.imu and the reader"
# Tensão dos 15 servos do robô nº 2 em 18/10, sem torque, menos 7,6 (IDs 20–24 | 30–34 | 10–14, ordem de busStatus).
BAT_OFFSETS = [0.0, 0.1, 0.0, 0.0, 0.0, 0.1, 0.0, 0.0, -0.1, 0.0, 0.0, 0.1, 0.1, 0.0, 0.1]
BAT_SAG = {"holding": 0.08, "policy": 0.08}
# Wi-Fi falso do configd: redes mais fortes primeiro; Home não está salva (exige senha), Home-5G está salva.
# O hotspot do robô também aparece (Microduck-0de6, detectado em 20/10 e marcado como salvo); o Studio deve filtrá-lo.
NETWORKS = [
    {"ssid": "Microduck-fake", "signal": 95, "security": "wpa_psk", "saved": True},
    {"ssid": "Home", "signal": 82, "security": "wpa_psk", "saved": False},
    {"ssid": "Home-5G", "signal": 74, "security": "wpa_psk", "saved": True},
    {"ssid": "Coffee", "signal": 58, "security": "open", "saved": False},
    {"ssid": "Office-5G", "signal": 44, "security": "enterprise", "saved": False},
    {"ssid": "Ghost", "signal": 12, "security": "wpa_psk", "saved": False},
]


def fake_net_json(mode):
    """Estado gravado por netcheck. O hostname duck-fake é fixo e não muda com o nome do computador."""
    nets = [{k: n[k] for k in ("ssid", "signal", "security")} for n in NETWORKS]
    return {"mode": mode, "hotspot_ssid": "Microduck-fake", "hotspot_ip": "10.42.0.1",
            "hotspot_psk": "microduck", "hostname": "duck-fake", "since": time.time(),
            "scan": nets, "scan_at": time.time() - 180.0}


def write_net_state(path, mode):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fake_net_json(mode), f, ensure_ascii=False)
    return path


class FakeRobotd:
    def __init__(self, fixture, posture="holding", record=None, net_mode="none", mode="motion"):
        replies, frames = load_fixture(fixture)
        self.health = copy.deepcopy(replies.get("robot.health"))
        self._bus0 = copy.deepcopy(replies.get("robot.busStatus"))      # Ao mudar para modo de depuração ou estado aguardando o barramento, reinicia a partir desta gravação.
        self.bus = copy.deepcopy(self._bus0)
        self.policies = replies.get("robot.policies")
        self._calib0 = copy.deepcopy(replies.get("busCommand:calibration-status"))
        self.calib = copy.deepcopy(self._calib0)
        self.calib_mode = "ok"
        self.mode = mode if mode in ("commissioning", "motion") else "motion"
        self.servo_power = True
        self.comm_stuck = False                # Fork antigo: o relatório de inicialização do modo de calibração nunca é limpo (--commissioning-stuck-status).
        self.hold = None                       # Modo de calibração hold-home em pé: {stage, max_error_deg, directions} (fork de 21/10).
        self.comm_read_s = COMMISSIONING_READ_S
        self._comm_t0 = time.monotonic()       # Momento em que o modo de calibração iniciou (reinicialização ou entrada no modo recalcula).
        self._comm_read_ok = False             # Se houve uma leitura bem-sucedida desde a inicialização (o fork limpa o relatório após a primeira leitura).
        self.imu_pose = "upright"              # upright / nose_down / wrong / none
        self.imu_verify_plan = "manual"        # manual / ok / not_upright / wrong / timeout
        self.imu_verify_timeout = 20.0
        self.imu_sequence = 0
        self.pad = replies.get("pad.status") or {"driver": "active", "pads": []}
        self.sysinfo = replies.get("system.info") or {"name": "duck-fake"}
        self.net_mode = net_mode if net_mode in ("wifi", "hotspot", "none") else "none"
        self.net_ssid = "Home" if self.net_mode == "wifi" else None
        self.net_signal = 72 if self.net_mode == "wifi" else None
        self.net_ip4 = "192.168.1.50" if self.net_mode == "wifi" else None
        self.frames = frames or [{}]
        self._posture_transition = None
        self.posture_delay_s = .55
        self.sitting = False
        self.relax_delay = 0.3
        self.hd_delay = 0.2
        self.delays = {}
        self.errors = {}                      # Método -> {"code":..,"message":..}
        self.inject = []                      # Linhas brutas (bytes) enviadas antes da próxima resposta.
        self.down = False
        self._writers = set()
        hd = ((self.bus.get("native") or {}).get("hd1910") or {})
        self._hd_hold = {"restore_pending": hd.get("restore_pending", True),
                         "temporary_gains_applied": hd.get("temporary_gains_applied", True)}
        self.subscribers = 0
        self.calls = []                       # (horário, método): permite conferir a ordem nos testes.
        self._relax_at = None
        self.bindings = [dict(b) for b in DEFAULT_BINDINGS]
        self.record = open(record, "a", encoding="utf-8") if record else None   # noqa: SIM115 — mantém aberto enquanto o processo estiver ativo.
        self.battery = None                   # Roteiro da bateria (fake.set battery); None = usa as tensões da gravação.
        self._bat_ema = None
        self.roller_models = False            # Indica se os modelos de rodas estão instalados (necessário para robot.setMode em roller; fake.set roller_models).
        self.set_posture(posture)

    def set_battery(self, cfg):
        """fake.set {battery: {...}} / null. Altera somente os campos fornecidos; se v for informado, recalcula drop_per_s a partir de agora."""
        if cfg is None:
            self.battery, self._bat_ema = None, None
            return
        b = dict(self.battery or {"v": 7.6, "drop_per_s": 0.0, "sag": 0.0, "gone": False, "glitch": None})
        b.update({k: cfg[k] for k in ("v", "drop_per_s", "sag", "gone", "glitch") if k in cfg})
        if "v" in cfg or "t0" not in b:
            b["t0"] = time.monotonic()
        self.battery = b

    def _battery_volts(self):
        b = self.battery
        if b.get("glitch") is not None:
            g = float(b["glitch"])
            b["glitch"] = None
            return [g] * 15
        if b.get("gone"):
            return [0.0] * 15
        base = b["v"] - b["drop_per_s"] * (time.monotonic() - b["t0"]) - BAT_SAG.get(self.posture, 0.0) - b["sag"]
        return [round(base + o, 1) for o in BAT_OFFSETS]

    def _motion_error(self):
        """Executa as verificações essenciais do fork antes de iniciar o modo de movimento. Estado de fábrica ou calibração inválida resulta em waiting_for_bus."""
        if not self.servo_power:
            return NO_POWER
        if self.calib_mode == "unavailable":
            return "calibration file could not be read"
        cal = (self.calib or {}).get("calibration") if isinstance(self.calib, dict) else None
        if not isinstance(cal, dict):
            return "Feetech motion_enabled is false; complete commissioning first"
        if cal.get("motion_enabled") is not True:
            return "Feetech motion_enabled is false; complete commissioning first"
        js = cal.get("joints") if isinstance(cal.get("joints"), list) else []
        if len(js) != 15 or any(not j.get("calibrated") or j.get("min_rad") is None or j.get("max_rad") is None for j in js):
            return STUCK_CALIB
        source = (self.calib or {}).get("imu_source") or "bus"
        if source == "bus":
            verified = cal.get("imu_mount_verified") is True
        else:
            mount = (cal.get("imu_mounts") or {}).get(source) or {}
            verified = mount.get("verified") is True
        if not verified:
            return f"motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the {source} IMU"
        return None

    def _gravity(self):
        a = math.radians(20.0)
        if self.imu_pose == "nose_down":
            return [round(math.sin(a), 6), 0.0, round(-math.cos(a), 6)]
        if self.imu_pose == "wrong":
            return [0.0, round(math.sin(a), 6), round(-math.cos(a), 6)]
        return [0.0, 0.0, -1.0]

    def _imu_status(self):
        cal = (self.calib or {}).get("calibration") if isinstance(self.calib, dict) else {}
        source = (self.calib or {}).get("imu_source") or "bus"
        mount = (cal.get("imu_mounts") or {}).get(source) or {}
        verified = bool(cal.get("imu_mount_verified")) if source == "bus" else bool(mount.get("verified"))
        g = self._gravity()
        tilt = math.degrees(math.acos(max(-1.0, min(1.0, -g[2]))))
        self.imu_sequence += 1
        return {"source": source, "sequence": self.imu_sequence, "ready": self.imu_pose != "none",
                "valid": self.imu_pose != "none", "gravity": g, "gyro_rad_s": [0.0, 0.0, 0.0],
                "quaternion_wxyz": [math.cos(math.radians(20.0) / 2), 0.0,
                                    math.sin(math.radians(20.0) / 2), 0.0],
                "mount_verified": verified, "tilt_deg": round(tilt, 3), "age_ms": 12, "epoch": 1}

    def comm_boot(self, delay=0.0):
        """Inicia ou reinicia o modo de calibração: reinicia o relatório e faz a primeira leitura após comm_read_s. delay pausa antes (simula reinicialização)."""
        self._comm_t0 = time.monotonic() + delay
        self._comm_read_ok = False

    def comm_phase(self):
        """Define qual resposta busStatus retorna no modo de calibração (conforme fork feetech_commissioning.rs 1123-1160, 1497-1556 e main.rs:4687):
        boot = relatório de inicialização (configuring_bus); waiting = barramento indisponível (servos sem alimentação: waiting_for_bus + error); up = instantâneo em tempo real.
        Após uma leitura bem-sucedida, permanece em up (se os servos desligarem depois, read_error aparece no instantâneo); comm_stuck (fork antigo) mantém o relatório inicial."""
        if not self._comm_read_ok:
            if not self.servo_power:
                return "waiting"
            if self.comm_stuck or time.monotonic() - self._comm_t0 < self.comm_read_s:
                return "boot"
            self._comm_read_ok = True
        return "up"

    def _commissioning_bus(self):
        b0 = self._bus0
        st = self.comm_phase()
        if st == "boot":
            return {"build": b0.get("build"), "mode": "commissioning", "phase": "configuring_bus", "port": b0.get("port")}
        if st == "waiting":
            return {"build": b0.get("build"), "mode": "commissioning", "phase": "waiting_for_bus", "error": NO_POWER}
        cal = (self.calib or {}).get("calibration") if isinstance(self.calib, dict) else {}
        js = cal.get("joints") if isinstance(cal.get("joints"), list) else []
        rows = []
        for i, j in enumerate(js[:15]):
            jid = j.get("id")
            rows.append({"id": jid, "joint": j.get("name"), "position_raw": 2048 + i, "position_wire_raw": 2048 + i,
                         "position_signed_raw": i, "speed_raw": 0, "load_raw": 0, "current_raw": 12,
                         "voltage_v": 7.6, "temperature_c": 36, "moving": False,
                         "calibrated": bool(j.get("calibrated"))})
        now = time.monotonic()
        up_us = int(max(0.0, now - self._comm_t0) * 1e6)
        cycles = max(1, up_us // 20000)                 # 50 Hz
        read_error = None if self.servo_power else NO_POWER
        ids = [r["id"] for r in rows]
        imu = self._imu_status()
        # Campos seguem Status do fork (perto da linha 1083 de feetech_commissioning.rs); last_sample contém a leitura mais recente.
        return {"build": b0.get("build"), "port": b0.get("port"), "mode": "commissioning",
                "phase": "read_error" if read_error else ("holding" if self.hold else "ready"),
                "session": os.getpid(), "target_hz": 50.0, "achieved_hz": 49.9 if not read_error else 0.0,
                "total_cycles": cycles, "total_success": cycles if not read_error else max(1, cycles - 50),
                "total_communication_failures": 0 if not read_error else min(50, cycles),
                "errors_by_id": {} if not read_error else {str(i): 1 for i in ids},
                "device_communication": {"classification": "exclusive-v2", "session": f"{os.getpid()}-fake",
                                         "total_reads": cycles, "unsent_reads": 0, "complete_but_late": 0,
                                         "incomplete_timeout_reads": 0, "missing_reads": 0 if not read_error else 1,
                                         "by_id": {}, "last_trace": {}},
                "last_cycle_error": read_error,
                "last_failure": {"cycle": cycles, "error": read_error, "missing_ids": ids} if read_error else None,
                "last_sample": {"cycle": cycles, "at_us": up_us, "servos": rows, "imu": imu},
                "calibrated": self.calib_mode not in ("uncal", "factory"),
                "imu_mount_verified": imu["mount_verified"],          # Da IMU em uso (fork: calibration.imu_mount(source)).
                "torque_state": self.bus.get("torque_state", "all_enabled"), "torque_off_pending": None,
                "power_pending": False, "motion": None, "policy_motion_enabled": False, "updated_at_us": up_us,
                **({"hold": dict(self.hold)} if self.hold else {})}

    def _shaped_bus(self):
        if self.mode == "commissioning":
            return self._commissioning_bus()
        err = self._motion_error()
        if err:
            return {"build": self._bus0.get("build"), "mode": "motion", "phase": "waiting_for_bus",
                    "port": self._bus0.get("port"), "error": err}
        bus = copy.deepcopy(self.bus)
        bus["mode"] = "motion"
        return bus

    def _bus_with_battery(self):
        bus = self._shaped_bus()
        joints = (bus.get("native") or {}).get("joints") if isinstance(bus.get("native"), dict) else None
        if self.battery is None or not isinstance(joints, list):
            return bus
        vs = self._battery_volts()
        for j, v in zip(joints, vs):
            j["volts"] = v
        mean = sum(vs) / len(vs)
        if mean > 0:                    # Com os servos sem alimentação, o hardware não responde; robotd mantém a leitura anterior (não inclui 0 V na média).
            self._bat_ema = mean if self._bat_ema is None else 0.1 * mean + 0.9 * self._bat_ema
        return bus

    def _health_with_battery(self):
        if self.battery is None or self._bat_ema is None:
            return self.health
        h = dict(self.health or {})
        v = self._bat_ema
        h["battery"] = {"volts": v, "percent": max(0.0, min(1.0, (v - 6.6) / 1.6)) * 100 if v > 0 else 0.0}
        return h

    def _log(self, method, params, notify):
        if self.record is not None:
            self.record.write(json.dumps({"t": time.time(), "method": method, "params": params, "notify": notify},
                                         ensure_ascii=False) + "\n")
            self.record.flush()

    def set_calib(self, mode):
        """Estados do arquivo de calibração: ok / committed (15 servos em 2048, todos calibrados), factory (sem calibração de fábrica: motion_enabled false,
        calibrated todos false, sem limites), seed (alguns valores diferentes de 2048), uncal (há servos sem calibrar) e unavailable (não foi possível ler)."""
        self.calib_mode = "ok" if mode == "committed" else mode
        self.calib = copy.deepcopy(self._calib0)
        js = ((self.calib or {}).get("calibration") or {}).get("joints") or []
        if self.calib_mode == "factory":
            cal = self.calib.get("calibration") if isinstance(self.calib, dict) else None
            if isinstance(cal, dict):
                cal["motion_enabled"] = False
                cal["imu_mount_verified"] = False
                for mount in (cal.get("imu_mounts") or {}).values():
                    if isinstance(mount, dict):
                        mount["verified"] = False
                for j in js:
                    j["calibrated"] = False
                    j["zero_raw"] = 2048
                    j.pop("min_rad", None)
                    j.pop("max_rad", None)
            self.calib["uncalibrated_joints"] = [j.get("name") for j in js]
            top = self.calib.get("imu_mount") if isinstance(self.calib, dict) else None
            if isinstance(top, dict):
                top["verified"] = False
        if self.calib_mode == "seed":
            for j in js:
                if j.get("id") in SEED_ZERO:
                    j["zero_raw"] = SEED_ZERO[j["id"]]
        elif self.calib_mode == "uncal":
            for j in js[:2]:
                j["calibrated"] = False
            self.calib["uncalibrated_joints"] = [j.get("name") for j in js[:2]]

    def set_posture(self, p):
        self._posture_transition = None
        self.sitting = p == "sitting"
        if p == "commissioning":
            if self.mode != "commissioning":
                self.comm_boot()                  # O modo vem dos argumentos de inicialização: entrar no modo de calibração reinicia o programa e retorna primeiro o relatório.
            self.mode = "commissioning"
            self._shape(p)
            self.posture = p
            return
        if p in ("starting", "stuck_calib"):
            self._shape(p)
            self.posture = p
            return
        if "native" not in self.bus:
            self.bus = copy.deepcopy(self._bus0)
        n = self.bus.setdefault("native", {})
        hd = n.setdefault("hd1910", {})
        self.bus.update({"mode": "motion", "phase": "control", "policy_enabled": False, "homed": True,
                         "torque_off_pending": False})
        n.update({"torque_enabled": True, "torque_state_confirmed": True})
        hd.update(getattr(self, "_hd_hold", {"restore_pending": True, "temporary_gains_applied": True}))
        self.bus.pop("torque_state", None)
        if p == "limp":
            n.update({"torque_enabled": False, "torque_state_confirmed": False})
            hd.update({"restore_pending": False, "temporary_gains_applied": False})
        elif p in ("policy", "sitting"):
            self.bus["policy_enabled"] = True
        self.posture = p
        fake_tune.after_posture(self, p)          # Estrutura esperada pelo cartão de ajuste (active_* com política ativa e walk_unloaded).

    def posture_frame(self, source):
        """Live sitstand evidence atop the recorded sensors, with physical lag."""
        frame = copy.deepcopy(source)
        now = time.monotonic()
        frame["t"] = now
        frame["t_ns"] = int(now * 1e9)
        transition = self._posture_transition
        if transition:
            done = now - transition["start"] >= self.posture_delay_s
            target = [v + (.35 if transition["target"] == "sit" else 0.) for v in transition["home"]]
            frame["targets"] = target
            frame["joints"] = target[:] if done else [v + .25 for v in target]
            frame["policy"] = "sit" if self.sitting else ("walk" if done else "rise")
        elif self.posture in ("policy", "sitting"):
            frame["policy"] = "sit" if self.sitting else "walk"
            frame["joints"] = list(frame.get("targets") or frame.get("joints") or [0.] * 15)
            frame["targets"] = frame["joints"][:]
        if self.posture in ("policy", "sitting"):
            frame["move"] = {"applied": [0., 0., 0.], "requested": [0., 0., 0.], "limited_by": []}
        return frame

    def _shape(self, p):
        """Formato de busStatus nesses estados no hardware (revisão O18): sem native, apenas alguns campos de nível superior."""
        b0 = self._bus0
        if p == "commissioning":
            self.bus = {"build": b0.get("build"), "mode": "commissioning", "phase": "ready", "port": b0.get("port"),
                        "torque_state": "all_enabled", "torque_off_pending": None, "calibrated": self.calib_mode not in ("uncal", "factory"),
                        "imu_mount_verified": self.calib_mode != "factory", "policy_motion_enabled": self.calib_mode != "factory"}
        else:
            err = STUCK_CALIB if p == "stuck_calib" else "torque readback at register 40: Feetech Sync Read timeout; missing IDs [21]"
            self.bus = {"build": b0.get("build"), "mode": "motion", "phase": "waiting_for_bus", "port": b0.get("port"),
                        "error": err}

    def _tick(self):
        if self._relax_at is None:
            return
        el = time.monotonic() - self._relax_at
        if self.bus.get("mode") == "commissioning":
            if el >= 0:
                self.bus["torque_state"] = "off"
                self.hold = None
                self._relax_at = None
            return
        n = self.bus.get("native")
        if n is None:                    # Aguardando o barramento: não há torque para desativar (no hardware, relax apenas registra o pedido).
            self._relax_at = None
            return
        if el >= 0:
            n.update({"torque_enabled": False, "torque_state_confirmed": False})
        if el >= self.hd_delay:
            n["hd1910"].update({"restore_pending": False, "temporary_gains_applied": False})
            self.posture = "limp"
            self._relax_at = None

    def stand_up(self):
        """Simula outra pessoa usando o controle para colocar o robô em pé (reativar o torque)."""
        self._relax_at = None
        self.set_posture("holding")

    def restart(self, down_s=0.5):
        """Simula a reinicialização do robotd: encerra as conexões atuais e recusa novas por down_s segundos."""
        self.down = True
        self.comm_boot(down_s)                   # Modo de calibração: após iniciar, retorna primeiro o relatório; só retorna o instantâneo após uma leitura bem-sucedida.
        for w in list(self._writers):
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass
        asyncio.get_running_loop().call_later(down_s, setattr, self, "down", False)

    def _commit_calibration(self, cfg):
        """Estado após a ferramenta de calibração falsa concluir: ok = muda para modo de movimento, phase control e retorna a calibração atualizada;
        reject = calibração inválida (waiting_for_bus + erro de calibração); servo_power = servos sem alimentação (waiting_for_bus + erro de barramento)."""
        outcome = cfg.get("outcome") or "ok"
        cal = cfg.get("calibration")
        source = cfg.get("imu_source") or (self.calib or {}).get("imu_source") or "bus"
        if isinstance(cal, dict) and isinstance(cal.get("calibration"), dict):
            self.calib = copy.deepcopy(cal)
        elif isinstance(cal, dict):
            self.calib = {"calibration": copy.deepcopy(cal), "imu_source": source}
        self.calib.setdefault("imu_source", source)
        self.mode = "motion"
        if outcome == "servo_power":
            self.servo_power = False
            self.calib_mode = "ok"
            self.posture = "starting"
            return
        self.servo_power = True
        if outcome == "reject":
            # A calibração pode ter sido gravada corretamente, mas a validação de movimento do programa falha (simula IMU em uso não verificada).
            cal_obj = self.calib.get("calibration") if isinstance(self.calib, dict) else None
            if isinstance(cal_obj, dict):
                cal_obj["imu_mount_verified"] = False
                mount = (cal_obj.get("imu_mounts") or {}).get(source)
                if isinstance(mount, dict):
                    mount["verified"] = False
            self.calib_mode = "uncal"
            self.posture = "stuck_calib"
            return
        self.calib_mode = "ok"
        self.set_posture("holding")

    async def _verify_imu(self, params):
        """Simula as regras verify-imu de feetech_commissioning.rs: alinhar primeiro a ≤5° e inclinar o pescoço entre 12° e 30° em até 20 s;
        orientações incorretas não salvam nada. imu_verify_plan permite simular imediatamente um sucesso ou três tipos de falha."""
        if self.mode != "commissioning":
            return None, {"code": -32603, "message": "verify-imu is only accepted in commissioning mode"}
        if (params or {}).get("confirmed") is not True:
            return None, {"code": -32602, "message": "verify-imu requires --confirmed after checking the official mounting axes"}
        q = (params or {}).get("mount_wxyz")
        if not isinstance(q, list) or len(q) != 4 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in q):
            return None, {"code": -32602, "message": "mount_wxyz must be [w, x, y, z]"}
        src = (self.calib or {}).get("imu_source") or "bus"
        if self.imu_pose == "none":
            return None, {"code": -32603, "message": VERIFY_NO_SAMPLE.format(source=src)}
        plan = self.imu_verify_plan
        if plan == "not_upright":
            return None, {"code": -32603, "message":
                          "under this mount the trunk reads 31.2° from upright (limit 5°); stand the robot upright, "
                          "or the mount is wrong: check the module axes"}
        if plan == "wrong":
            return None, {"code": -32603, "message":
                          "tipped 20.0°, but under this mount it reads 90.0° (90.0° from nose-down): the mount is about "
                          "that far off about the vertical axis. If the nose did not go down, tip it nose-down and run "
                          "verify-imu again. Nothing saved: mount unchanged"}
        if plan == "timeout":
            await asyncio.sleep(min(float(self.imu_verify_timeout), 0.4))
            return None, {"code": -32603, "message":
                          "no nose-down tip of at least 12° held within 20 s of the upright check; nothing saved"}
        if plan == "ok":
            self.imu_pose = "upright"
            await asyncio.sleep(0.15)
            self.imu_pose = "nose_down"
        else:
            # manual: só inicia se estiver upright; depois fake.set altera para nose_down.
            if self.imu_pose != "upright":
                return None, {"code": -32603, "message":
                              "under this mount the trunk reads 20.0° from upright (limit 5°); stand the robot upright, "
                              "or the mount is wrong: check the module axes"}
            end = time.monotonic() + float(self.imu_verify_timeout)
            while self.imu_pose == "upright" and time.monotonic() < end:
                await asyncio.sleep(0.05)
            if self.imu_pose != "nose_down":
                return None, {"code": -32603, "message":
                              "no nose-down tip of at least 12° held within 20 s of the upright check; nothing saved"}
        n = math.sqrt(sum(float(x) * float(x) for x in q))
        if not math.isfinite(n) or n <= 1e-12:
            return None, {"code": -32602, "message": "mount_wxyz must be finite unit length [w,x,y,z]"}
        quat = [float(x) / n for x in q]
        cal = self.calib.setdefault("calibration", {})
        cal["motion_enabled"] = False
        if src == "bus":
            cal["imu_mount_quat"], cal["imu_mount_verified"] = quat, True
        else:
            mounts = cal.setdefault("imu_mounts", {})
            mounts[src] = {"quat": quat, "verified": True}
        top = self.calib.get("imu_mount")
        if isinstance(top, dict) and (self.calib.get("imu_source") in (None, src)):
            top["quat"], top["verified"] = quat, True
        return {"accepted": True, "source": src, "mount_wxyz": quat}, None

    async def dispatch(self, method, params):
        self.calls.append((time.monotonic(), method))
        if method in self.delays:
            await asyncio.sleep(self.delays[method])
        self._tick()
        if method in self.errors:
            return None, self.errors[method]
        if method == "hello":
            if "api_version" not in (params or {}):
                return None, {"code": -32602, "message": "missing field `api_version`"}
            return {"api_version": 40, "daemon_version": "0.17.0", "revision": "fake"}, None
        if method == "robot.health":
            return self._health_with_battery(), None
        if method == "robot.busStatus":
            return self._bus_with_battery(), None
        if method == "robot.policies":
            if self.mode != "motion" or self._motion_error():
                return None, {"code": -32603, "message": "robotd is in commissioning mode"}
            return dict(self.policies or {}, sitting=self.sitting), None
        if method == "robot.busCommand" and (params or {}).get("action") == "calibration-status":
            # Aguardando o barramento: a calibração só é salva depois de abrir o barramento (fork main.rs:1535); retorna erro neste estado.
            if self.mode != "commissioning" and self._shaped_bus().get("phase") == "waiting_for_bus":
                return None, NO_CALIB
            return self.calib, None
        if method == "robot.busCommand" and (params or {}).get("action") == "verify-imu":
            return await self._verify_imu(params)
        if method == "robot.busCommand" and (params or {}).get("action") == "hold-home":
            # Fork de 21/10: no modo de calibração, os 15 servos vão juntos para HOME e travam; responde quando estiver em pé (não aguarda a subida).
            if self.mode != "commissioning":
                return None, {"code": -32603, "message": "raw bus commands require the running robotd commissioning mode"}
            dirs = (params or {}).get("directions") or []
            if dirs and (len(dirs) != 15 or any(d not in (1, -1) for d in dirs)):
                return None, {"code": -32603, "message": "hold-home directions need exactly 15 values of -1/+1, in calibration joint order"}
            if self.hold:
                return {"holding": True, "torque": "on", "already": True, "directions": self.hold["directions"]}, None
            self.hold = {"stage": "holding", "max_error_deg": 0.6, "directions": list(dirs) or [-1] * 15}
            self.bus["torque_state"] = "all_enabled"
            return {"holding": True, "torque": "on", "max_error_deg": 0.6, "directions": self.hold["directions"]}, None
        if method == "robot.relax":
            if self.mode == "commissioning" and self.hold and self._relax_at is None:
                self._relax_at = time.monotonic() + self.relax_delay
                return {"accepted": True}, None
            if self._relax_at is None and not (self.posture == "limp" or self.bus.get("torque_state") == "off"):
                self._relax_at = time.monotonic() + self.relax_delay
            return {"accepted": True}, None
        if method == "pad.status":
            return self.pad, None
        if method == "system.info":
            return self.sysinfo, None
        if method == "net.status":
            if self.net_mode == "wifi" and self.net_ssid:
                return {"state": "connected", "ssid": self.net_ssid, "signal": self.net_signal,
                        "ip4": self.net_ip4, "ip6": None, "mac": "02:00:00:00:00:01", "iface": "wlan0"}, None
            return {"state": "disconnected"}, None
        if method == "net.scan":
            return {"networks": [dict(n) for n in NETWORKS]}, None
        if method == "net.connect":
            return await self._net_connect(params), None
        if method == "net.forget":
            ssid = (params or {}).get("ssid")
            if self.net_ssid == ssid:
                self.net_mode, self.net_ssid, self.net_signal, self.net_ip4 = "none", None, None, None
            return {"removed": bool(ssid)}, None
        if method == "pad.bindings":
            return {"bindings": self.bindings}, None
        if method == "fake.set":                       # Para testes: altera a postura ou simula um controle físico conectado.
            if type(params.get("posture_delay_s")) in (int, float):
                self.posture_delay_s = max(.1, min(30., float(params["posture_delay_s"])))
            if params.get("mode") in ("commissioning", "motion"):
                if params["mode"] == "commissioning" and self.mode != "commissioning":
                    self.comm_boot()
                self.mode = params["mode"]
                if self.mode == "commissioning":
                    self._shape("commissioning")
                    self.posture = "commissioning"
            if "commissioning_stuck" in params:
                self.comm_stuck = bool(params["commissioning_stuck"])
            if "servo_power" in params:
                self.servo_power = bool(params["servo_power"])
            if isinstance(params.get("calib_commit"), dict):
                self._commit_calibration(params["calib_commit"])
            if params.get("imu_pose") in ("upright", "nose_down", "wrong", "none"):
                self.imu_pose = params["imu_pose"]
            if params.get("imu_verify_plan") in ("manual", "ok", "not_upright", "wrong", "timeout"):
                self.imu_verify_plan = params["imu_verify_plan"]
            if isinstance(params.get("imu_verify_timeout"), (int, float)):
                self.imu_verify_timeout = max(0.2, min(30.0, float(params["imu_verify_timeout"])))
            if params.get("posture"):
                self._relax_at = None                  # Cancela também uma desativação de torque ainda pendente e aplica a postura solicitada.
                self.set_posture(params["posture"])
            if "pad_connected" in params:
                self.pad = {"driver": "active", "pads": [{"mac": "78:86:2E:BB:13:28", "name": "Xbox Wireless Controller",
                                                          "paired": True, "trusted": True, "connected": True}]
                            if params["pad_connected"] else []}
            if isinstance(params.get("pads"), list):
                self.pad = {"driver": "active", "pads": params["pads"]}
            if params.get("calib"):
                self.set_calib(params["calib"])
            if "imu_verified" in params and isinstance(self.bus.get("native"), dict):
                # native.imu_mount_verified em busStatus (linha da IMU na lista inicial: não permite ignorar sem confirmação da orientação pelo programa principal).
                self.bus["native"]["imu_mount_verified"] = bool(params["imu_verified"])
            if isinstance(params.get("cpu"), dict):
                c = params["cpu"]
                self.health = dict(self.health or {})
                if "c" in c:
                    self.health["cpu_temp_c"] = c["c"]
                thr = dict(self.health.get("cpu_throttle") or {})
                thr.update({k: c[k] for k in ("level", "max_level", "khz", "max_khz") if k in c})
                self.health["cpu_throttle"] = thr
            if isinstance(params.get("errors"), dict):
                for m, e in params["errors"].items():
                    if e is None:
                        self.errors.pop(m, None)
                    else:
                        self.errors[m] = e
            if "roller_models" in params:
                self.roller_models = bool(params["roller_models"])
            if "battery" in params:
                self.set_battery(params["battery"] if isinstance(params["battery"], dict) else None)
            fake_tune.fake_set(self, params)           # Chaves usadas pelo cartão de ajuste (startup, servo_parameters, walk_profile etc.).
            if params.get("restart"):
                # Simula reinício do robotd (o Studio envia hello novamente e relê a calibração): responde primeiro e depois desconecta, sem encerrar esta conexão de controle.
                asyncio.get_running_loop().call_later(0.05, self.restart, float(params["restart"]))
            return {"posture": self.posture, "pad": self.pad, "calib": self.calib_mode}, None
        if method == "robot.rebootMotors":
            # No fork com handover (main.rs:6050-6056), nunca recusa: o loop principal desativa o torque de todo o corpo antes de reiniciar; depois o robô fica sem torque (main.rs:2731-2758). Aqui, simula a desativação.
            if self._relax_at is None and not (self.posture == "limp" or self.bus.get("torque_state") == "off"):
                self._relax_at = time.monotonic() + self.relax_delay
            return {"accepted": True}, None
        if method == "robot.setMode":
            # Fork com handover (main.rs:5700-5736): recusa modos desconhecidos, sem política ou sem modelos de rodas; aceita se já estiver no modo solicitado (com motivo).
            want = (params or {}).get("mode")
            if want not in ("walk", "roller", "roller_crouch", "roller_spin"):
                return {"accepted": False, "reason": "mode must be walk, roller, roller_crouch or roller_spin"}, None
            if want != "walk" and not self.roller_models:
                return {"accepted": False, "reason": "roller ONNX models are not installed; original walking policy unchanged"}, None
            want = "walk" if want == "walk" else "roller"
            if (self.policies or {}).get("mode", "walk") == want:
                return {"accepted": True, "reason": "mode already selected"}, None
            self.policies = dict(self.policies or {}, mode=want)
            return {"accepted": True}, None
        if method == "robot.do" and params.get("skill") == "sit_toggle":
            previous = self._posture_transition
            if previous and previous["target"] == "stand" and time.monotonic() - previous["start"] < self.posture_delay_s:
                return {"accepted": False, "reason": "already standing up"}, None
            if self.bus.get("policy_enabled") is not True or (self.bus.get("native") or {}).get("torque_state_confirmed") is not True:
                return {"accepted": False, "reason": "policy is not driving"}, None
            target = "stand" if self.sitting else "sit"
            home = list((self.frames[0] or {}).get("targets") or [0.] * 15)
            self.sitting = target == "sit"
            self.posture = "sitting" if self.sitting else "policy"
            self._posture_transition = {"start": time.monotonic(), "target": target, "home": home}
            return {"accepted": True, "reason": target}, None
        if method in ACCEPT:
            if method == "robot.enable" and self.posture in ("holding", "policy"):
                on = (not (self.posture == "policy")) if params.get("toggle") else bool(params.get("on"))
                self.set_posture("policy" if on else "holding")
            elif method == "robot.init" and self.posture == "limp":
                self.set_posture("holding")
            return {"accepted": True}, None
        return None, {"code": -32601, "message": f"method not found: {method}"}

    async def _net_connect(self, params):
        """net.connect falso do configd: wrongpass → bad_key, Ghost → not_found, autenticação corporativa ou senha ausente → unsupported;
        os demais conectam após 3 segundos. Depois do sucesso, net.status também passa a indicar conexão com essa rede Wi-Fi."""
        ssid = (params or {}).get("ssid")
        psk = (params or {}).get("psk") or ""
        net = next((n for n in NETWORKS if n["ssid"] == ssid), None)
        if ssid == "Ghost" or net is None:
            await asyncio.sleep(0.2)
            return {"outcome": "failed", "reason": "not_found", "detail": f"Rede {ssid} não encontrada"}
        if psk == "wrongpass":
            await asyncio.sleep(0.2)
            return {"outcome": "failed", "reason": "bad_key", "detail": "802.1X authentication failed"}
        if net["security"] == "enterprise":
            return {"outcome": "failed", "reason": "unsupported", "detail": "enterprise WiFi is not supported"}
        if net["security"] != "open" and not psk:
            return {"outcome": "failed", "reason": "unsupported", "detail": "this network needs a password"}
        await asyncio.sleep(3.0)
        self.net_mode, self.net_ssid, self.net_signal = "wifi", ssid, net["signal"]
        self.net_ip4 = "192.168.1.66"
        return {"outcome": "connected", "ssid": ssid, "ip4": self.net_ip4}

    async def handle(self, reader, writer):
        self._writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                except ValueError:
                    writer.write(b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}\n')
                    await writer.drain()
                    continue
                rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
                notify = "id" not in req
                self._log(method, params, notify)
                if method == "robot.subscribe":
                    await self._stream(writer, rid, params)
                    break
                if method == "robot.startupSubscribe":
                    await fake_tune.startup_stream(self, reader, writer, rid)
                    break
                result, err = await self.dispatch(method, params)
                if notify:
                    continue                           # Notificações não recebem resposta (JSON-RPC; robotd também não responde).
                while self.inject:
                    writer.write(self.inject.pop(0))
                reply = {"jsonrpc": "2.0", "id": rid}
                reply.update({"error": err} if err else {"result": result})
                writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _stream(self, writer, rid, params):
        hz = params.get("hz")
        if hz is not None and not isinstance(hz, int):
            writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid type: floating point, expected u32"}}) + "\n").encode())
            await writer.drain()
            return
        if self.mode != "motion":
            writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "commissioning mode"}}) + "\n").encode())
            await writer.drain()
            return
        writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"accepted": True}}) + "\n").encode())
        await writer.drain()
        self.subscribers += 1
        i = 0
        try:
            while True:
                frame = self.posture_frame(self.frames[i % len(self.frames)])
                writer.write((json.dumps({"jsonrpc": "2.0", "method": "robot.state", "params": frame}, ensure_ascii=False) + "\n").encode())
                await writer.drain()
                i += 1
                await asyncio.sleep(1.0 / (hz or 50))
        except (ConnectionError, OSError):
            pass
        finally:
            self.subscribers -= 1

    async def _gate(self, reader, writer):
        if self.down:
            writer.close()
            return
        await self.handle(reader, writer)

    async def serve_tcp(self, host="127.0.0.1", port=0):
        server = await asyncio.start_server(self._gate, host, port)
        return server, server.sockets[0].getsockname()[1]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--robotd-port", type=int, default=17001)
    ap.add_argument("--configd-port", type=int, default=17002)
    ap.add_argument("--posture", default="holding", choices=POSTURES)
    ap.add_argument("--mode", default="motion", choices=["commissioning", "motion"],
                    help="busStatus.mode depende apenas desta opção (fork main.rs:1300-1315)")
    ap.add_argument("--calib", default="ok", choices=["ok", "committed", "factory", "seed", "uncal", "unavailable"])
    ap.add_argument("--commissioning-stuck-status", action="store_true",
                    help="Simula um fork antigo: o relatório de inicialização (configuring_bus) do modo de calibração nunca é limpo e o Studio continua exibindo ‘Iniciando’")
    ap.add_argument("--record", help="Grava cada mensagem recebida neste arquivo (um JSON por linha)")
    ap.add_argument("--net-mode", choices=["hotspot", "wifi", "none"],
                    help="Dados falsos de rede: grava um net.json falso (usado com --net-state no Studio)")
    ap.add_argument("--net-state-file", default="state-dev/net.json", help="Caminho para gravar o net.json falso")
    a = ap.parse_args()
    fake = FakeRobotd(a.fixture, a.posture, a.record, net_mode=a.net_mode or "none", mode=a.mode)
    fake.comm_stuck = bool(a.commissioning_stuck_status)
    if a.net_mode:
        write_net_state(a.net_state_file, a.net_mode)
    if a.calib != "ok":
        fake.set_calib(a.calib)
        fake.set_posture(a.posture)
    s1, p1 = await fake.serve_tcp(port=a.robotd_port)
    s2, p2 = await fake.serve_tcp(port=a.configd_port)
    extra = f" | rede {a.net_mode} ({a.net_state_file})" if a.net_mode else ""
    if fake.comm_stuck:
        extra += " | relatório de inicialização do modo de calibração nunca é limpo (fork antigo)"
    print(f"robotd falso em tcp:127.0.0.1:{p1}, configd falso em tcp:127.0.0.1:{p2}, modo {a.mode}, postura {a.posture}{extra}. Ctrl+C para sair.", flush=True)
    async with s1, s2:
        await asyncio.gather(s1.serve_forever(), s2.serve_forever())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
