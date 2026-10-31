"""Backend das áreas “Execução e ajustes” no painel e “Modelos” nas configurações (plano de ajustes v2 T1–T3; somente leitura).

Plano: scratchpad console/tuning-plan.md (versão final v2). Três cartões:
    Cartão 1, Estado da execução: fase do robotd, quatro etapas de inicialização (startup.py), controle, capacidade de andar e hardware.
    Cartão 2, Ajuste da sensação: escala do modelo de caminhada, suavização da cabeça e das patas (arquivo, configuração ativa e quadro atual), P/D/limite de torque e amplitude da boca/cabeça pelo controle.
    Cartão 3, Modelos: uma linha por slot, somente leitura; cartões de modelos nas configurações, modelos de movimentos especiais e exportação do perfil do robô para treinamento.

**Esta versão não grava dados no robô**: alterações dependem do auxiliar root (plano T4). A única gravação é duck-body.json,
no diretório state do próprio Studio, para guardar o peso preenchido pelo usuário e incluí-lo no perfil exportado.

Fatos importantes (plano §§0 e 2):
- Escala e suavização do modelo combinado Walk ficam em **deployment-execution.json no diretório do próprio modelo** (fork control.rs:622-632).
  action_scale em robotd.toml [policy] não é usado; a suavização global só se aplica a sentar/levantar (control.rs:722-733).
- A configuração “em uso” vem de busStatus.loaded_models.walk.runtime_execution_profile (revisão T-R14).
  active_action_scale / active_target_filters existem apenas com a política ativa e representam os valores usados no quadro atual (incluindo compensação de tensão).
- Sem servo-test-parameters.json, vale o padrão V167 (P = kp_fw do contrato de caminhada, D = 0, limite de torque = 1000).
  O programa principal reporta native.hd1910.servo_parameters; sem essa chave, é o robotd original do firmware da placa, que não permite ajustes (D6c).
  **Não use state.safety.gain**: o backend Feetech não grava esse campo (revisão T-R4, feetech.rs:1825-1834).

A leitura de arquivos ocorre em thread (io(), a cada 2 segundos, com cache por mtime; o contrato de caminhada de 431 KB só é analisado quando muda).
view() apenas combina os dados já carregados em memória. Os caminhos são relativos a root (/, no robô; nos testes e capturas no computador, uma árvore simulada em dev/duckfs.py).
"""
import asyncio
import json
import math
import os
import re
import sys
import tempfile
import time
import tomllib
from collections import deque
from pathlib import Path

from .imu import mount_of
from .robotd import fresh_calib
from .startup import _hello_at, walk_unloaded

ETC = "etc/robot/feetech-ft5"
BASE = "opt/robot/feetech-ft5-r5"
CONFIG, SAVED = f"{ETC}/robotd.toml", f"{ETC}/robotd.saved.toml"
SERVO_FILE = f"{ETC}/servo-test-parameters.json"
PAD_FILE = f"{ETC}/pad-settings.json"
PAD_PREV = f"{ETC}/pad-settings.json.previous"
PAD_LIVE = "run/padd/input-settings.json"      # Configuração realmente usada pelo padd (padd:padd 0644, fork padd/src/input_settings.rs).
PROFILE = f"{BASE}/management-profile.json"     # Nome do modelo incluído no pacote (builtin_models).
ROLLER = f"{BASE}/roller"
ROLLERS = (("swizzle", "Rodas · deslizar simetricamente"), ("crouch", "Rodas · agachar"), ("spin", "Rodas · girar no lugar"), ("standup", "Rodas · levantar após queda"))
BODY_FILE = "duck-body.json"
EXEC = "deployment-execution.json"
SLOTS = ("walk", "sitstand", "ground_pick", "kick_left", "kick_right", "roulade", "stand")
SLOT_CN = {"walk": "Caminhar / manter", "sitstand": "Sentar / levantar", "ground_pick": "Abaixar a cabeça para pegar objetos", "kick_left": "Chute com a perna esquerda",
           "kick_right": "Chute com a perna direita", "roulade": "Cambalhota para a frente", "stand": "Em pé (independente)"}
SLOT_SKILL = {"sitstand": "sit_toggle", "ground_pick": "ground_pick", "kick_left": "kick_left", "kick_right": "kick_right",
              "roulade": "roulade"}
BUTTON_CN = {"a": "A", "b": "B", "x": "X", "y": "Y", "lb": "LB", "rb": "RB", "dpad_down": "Direcional para baixo", "dpad_up": "Direcional para cima",
             "dpad_left": "Direcional para a esquerda", "dpad_right": "Direcional para a direita", "ls": "L3", "rs": "R3"}
# O modelo combinado Walk incluído no pacote é o único com valores padrão definidos diretamente; outros usam .orig (revisão T-R17).
BUNDLED_WALK = "1cbf8730eadd75a5704332c9f3c10f60"
BUNDLED_WALK_DEFAULT = {"action_scale": 1.0, "head_lowpass": 0.5, "legs_lowpass": 0.7}
V167_SERVO = {"kd": 0, "torque_limit": 1000}    # Sem arquivo de parâmetros: D = 0, limite de torque = 1000 e P vem do contrato de caminhada (hd1910.rs:121-155, 257-267).
PAD_DEFAULT = {"mouth_percent": 100.0, "head_rad": 2.5}
MOUTH_WARN = 10                                  # Abertura máxima da boca ≤10%: quase não abre; exibe aviso (D6e: ainda sem botão para restaurar).
SCALE_USE_CN = {"joint_uniform": "Caminhada (parâmetros do próprio modelo combinado)", "walking": "Caminhada", "hold": "Manter posição", "held": "Inferência inativa",
                "homing": "Retornando à postura", "sit": "Sentado", "rise": "Levantando", "ground_pick": "Abaixando a cabeça para pegar objetos", "roulade": "Cambalhota para a frente",
                "kick_left": "Chute com a perna esquerda", "kick_right": "Chute com a perna direita", "stand": "Modelo de postura em pé", "walk": "Caminhada"}
PHASE_CN = {"control": ("Em controle", "ok"), "configuring_bus": ("Configurando o barramento dos servos", "warn"), "waiting_for_bus": ("Aguardando o barramento dos servos", "warn"),
            "configuration_error": ("Erro de configuração", "bad"), "configuring_uart": ("Configurando a porta serial", "warn"), "ready": ("Modo de depuração", "warn"),
            "read_error": ("Modo de depuração · erro ao ler os servos", "bad")}
MAX_JSON = 2 << 20            # Tamanho máximo de JSON/TOML comum: 2 MB.
MAX_CONTRACT = 8 << 20        # Limite para contratos de aproximadamente 431 KB.
IO_EVERY_S = 2.0
MISSED_WINDOW_S = 60.0
AGE = {"health": 8.0, "policies": 6.0, "state": 1.5}
BODY_KEYS = ("total_g", "trunk_g", "head_g", "leg_left_g", "leg_right_g")
BODY_MAX_G = 5000


class Refused(Exception):
    """Operação indisponível; o motivo é exibido diretamente na página."""


def num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x) if math.isfinite(x) else None
    except (OverflowError, ValueError):
        return None


def _fresh(sample, key, now):
    age = sample.age(now) if sample is not None else None
    return sample.value if age is not None and age <= AGE[key] and isinstance(sample.value, dict) else None


def rounds_of(checkpoint):
    """Normaliza o número de iterações de treinamento: por exemplo, checkpoints 9599 → 9600, 9999 → 10000 e 11000 → 11000.
    Para strings, como caminhos de checkpoints em manifests antigos (por exemplo, …/model_9999.pt), usa o último número."""
    n = None
    if isinstance(checkpoint, bool):
        return None
    if isinstance(checkpoint, int):
        n = checkpoint
    elif isinstance(checkpoint, float) and checkpoint.is_integer():
        n = int(checkpoint)
    elif isinstance(checkpoint, str):
        m = re.findall(r"(\d+)", os.path.basename(checkpoint))
        n = int(m[-1]) if m else None
    if n is None or n < 0:
        return None
    return n + 1 if (n + 1) % 100 == 0 else n


class FileCache:
    """Armazena em cache o resultado do parsing por (mtime_ns, size). Ausente = {"missing": True}; inválido = {"error": "motivo"}."""

    def __init__(self):
        self._c = {}

    def get(self, path, parse, limit=MAX_JSON):
        try:
            stt = os.stat(path)
        except FileNotFoundError:
            self._c.pop(path, None)
            return {"missing": True}
        except OSError as e:
            return {"error": f"Não foi possível ler: {type(e).__name__}: {e}"}
        key = (stt.st_mtime_ns, stt.st_size)
        hit = self._c.get(path)
        if hit and hit[0] == key:
            return hit[1]
        if stt.st_size > limit:
            out = {"error": f"Arquivo grande demais ({stt.st_size} bytes)."}
        else:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                out = {"value": parse(data), "mtime": stt.st_mtime}
            except (OSError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
                out = {"error": f"{type(e).__name__}: {e}"[:300]}
        self._c[path] = (key, out)
        return out


def _json(data):
    return json.loads(data.decode("utf-8"))


def _toml(data):
    return tomllib.loads(data.decode("utf-8"))


def _contract_summary(data):
    """Mantém somente alguns campos dos contratos de caminhada/movimento, sem guardar os 431 KB completos na memória."""
    c = json.loads(data.decode("utf-8"))
    acts = ((c.get("model") or {}).get("actuators") or []) if isinstance(c.get("model"), dict) else []
    kp = acts[0].get("kp_fw") if acts and isinstance(acts[0], dict) else None
    rp = c.get("required_policy_settings") if isinstance(c.get("required_policy_settings"), dict) else {}
    return {"task": c.get("task"), "kp_fw": kp, "task_adapter": c.get("task_adapter"),
            "action_filter": c.get("action_filter") if isinstance(c.get("action_filter"), dict) else None,
            "required": {k: rp.get(k) for k in ("action_scale", "head_lowpass", "legs_lowpass", "ground_pick_action_scale")},
            "runtime_action_scale": c.get("runtime_action_scale"), "robot_mode": c.get("robot_mode")}


def _val(entry):
    return entry.get("value") if isinstance(entry, dict) else None


def _err(entry):
    if not isinstance(entry, dict):
        return None
    return entry.get("error")


class Tune:
    def __init__(self, rd, log, state_dir=".", root="/", duck=None):
        self.rd, self.log, self.state_dir, self.duck = rd, log, state_dir, duck or {}
        self.root = Path(root)
        self.cache = FileCache()
        self.disk = {}                 # Conteúdo lido por io(); substituído por inteiro. view() lê no loop de eventos sem lock.
        self._missed = deque(maxlen=64)   # (monotonic, missed, ticks): calcula quadros perdidos no último minuto.
        self._io_err_logged = set()

    # ---- Caminhos ----

    def p(self, rel):
        return self.root / rel

    def abs_path(self, path):
        """Converte um caminho absoluto informado pelo robotd (/opt/robot/...) para um caminho sob root."""
        if not isinstance(path, str) or not path.startswith("/"):
            return None
        return self.root / path.lstrip("/")

    # ---- Leitura de arquivos (em thread) ----

    def io(self):
        c = self.cache
        disk = {}
        cfg = c.get(self.p(CONFIG), _toml)
        saved = c.get(self.p(SAVED), _toml)
        disk["config"], disk["saved"] = cfg, saved
        disk["servo_file"] = c.get(self.p(SERVO_FILE), _json)
        disk["pad_file"] = c.get(self.p(PAD_FILE), _json)
        disk["pad_prev"] = c.get(self.p(PAD_PREV), _json)
        disk["pad_live"] = c.get(self.p(PAD_LIVE), _json)
        prof = _val(c.get(self.p(PROFILE), _json)) or {}
        disk["builtin_names"] = {m.get("id"): m.get("name") for m in (prof.get("builtin_models") or [])
                                 if isinstance(m, dict) and isinstance(m.get("id"), str)}
        disk["body"] = c.get(Path(self.state_dir) / BODY_FILE, _json)
        # Diretórios a ler: caminhos dos slots e habilidades no TOML, além dos loaded_models informados pelo programa principal.
        paths = set()
        pol = (_val(cfg) or {}).get("policy") if isinstance(_val(cfg), dict) else None
        if isinstance(pol, dict):
            for s in SLOTS:
                if isinstance(pol.get(s), str):
                    paths.add(pol[s])
            for sk in pol.get("skill") or []:
                if isinstance(sk, dict) and isinstance(sk.get("path"), str):
                    paths.add(sk["path"])
        bus = self.rd.bus.value if isinstance(self.rd.bus.value, dict) else {}
        lm = bus.get("loaded_models") if isinstance(bus.get("loaded_models"), dict) else {}
        for v in lm.values():
            if isinstance(v, dict) and isinstance(v.get("path"), str):
                paths.add(v["path"])
        models = {}
        for path in sorted(paths):
            full = self.abs_path(path)
            if full is None or path == "none":
                continue
            d = full.parent
            models[path] = self._model_dir(d)
        disk["models"] = models
        rollers = []
        for name, label in ROLLERS:
            d = self.p(ROLLER) / name
            m = self._model_dir(d)
            rollers.append({"id": name, "label": label, **m})
        disk["rollers"] = rollers
        disk["at"] = time.monotonic()
        # Verifica se os dois arquivos TOML correspondem (o script da placa grava ambos; robot.loadPolicy grava somente o primeiro).
        a, b = _val(cfg), _val(saved)
        if a is None or b is None:
            disk["tomls_same"] = None
        else:
            disk["tomls_same"] = a == b
        self.disk = disk
        # Registra o histórico de quadros perdidos do monitor de integridade e calcula o total do último minuto.
        h = self.rd.health.value if isinstance(self.rd.health.value, dict) else None
        loop = (h or {}).get("control_loop") if isinstance((h or {}).get("control_loop"), dict) else None
        if loop and isinstance(loop.get("missed"), int) and isinstance(loop.get("ticks"), int):
            if self._missed and (loop["ticks"] < self._missed[-1][2] or loop["missed"] < self._missed[-1][1]):
                self._missed.clear()          # O robotd reiniciou; reinicia a contagem.
            self._missed.append((time.monotonic(), loop["missed"], loop["ticks"]))
        for key, entry in (("config", cfg), ("servo_file", disk["servo_file"]), ("pad_file", disk["pad_file"])):
            e = _err(entry)
            if e and key not in self._io_err_logged:
                self._io_err_logged.add(key)
                self.log.warn(f"Não foi possível interpretar o arquivo de configuração do robô ({key})", cat="Ajuste", raw=e,
                              hint="O item correspondente no cartão de ajustes será marcado como ilegível; se o arquivo tiver sido alterado incorretamente, o programa principal também pode não iniciar.")
            elif not e:
                self._io_err_logged.discard(key)

    def _model_dir(self, d):
        c = self.cache
        man = c.get(d / "manifest.json", _json)
        info = c.get(d / "model-info.json", _json)
        exe = c.get(d / EXEC, _json)
        con = c.get(d / "deployment-contract.json", _contract_summary, limit=MAX_CONTRACT)
        out = {"dir": d.name, "onnx": (d / "policy.onnx").is_file(), "orig": (d / (EXEC + ".orig")).is_file(),
               "manifest": _val(man), "manifest_error": _err(man), "info": _val(info), "exec": _val(exe),
               "exec_error": _err(exe), "exec_missing": bool(exe.get("missing")) if isinstance(exe, dict) else None,
               "contract": _val(con), "contract_error": _err(con)}
        if out["orig"]:
            out["orig_exec"] = _val(c.get(d / (EXEC + ".orig"), _json))
        return out

    async def loop(self):
        """Inicia no lifespan de app.py; lê os arquivos a cada 2 segundos em uma thread, sem bloquear a desativação do torque se o SD travar."""
        while True:
            try:
                await asyncio.to_thread(self.io)
            except Exception as e:  # noqa: BLE001
                self.log.error("Falha ao ler arquivos do cartão de ajustes", cat="Ajuste", raw=f"{type(e).__name__}: {e}", exc=True,
                               hint="Este é um problema do Studio. Exporte e envie o pacote de diagnóstico; ficar em pé e caminhar não são afetados.")
                await asyncio.sleep(5.0)
            await asyncio.sleep(IO_EVERY_S)

    # ---- Dados enviados à página ----

    def view(self, now=None):
        now = time.monotonic() if now is None else now
        rd = self.rd
        bus = rd.bus.value if isinstance(rd.bus.value, dict) else {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
        health = _fresh(rd.health, "health", now)
        pol = _fresh(rd.policies, "policies", now)
        st = _fresh(rd.state, "state", now)
        disk = self.disk
        cfg = _val(disk.get("config")) if disk else None
        policy_cfg = cfg.get("policy") if isinstance(cfg, dict) and isinstance(cfg.get("policy"), dict) else {}
        fork = ("servo_parameters" in hd) if hd else None
        walk = self._walk(bus, policy_cfg, disk)
        out = {
            "t": "tune",
            "ready": bool(disk),
            "cap": self._cap(fork, bus),
            "run": self._run(now, bus, native, health, pol, st, walk, cfg),
            "feel": self._feel(bus, native, hd, fork, walk, policy_cfg, disk),
            "models": self._models(bus, pol, policy_cfg, cfg, disk),
        }
        return out

    def _cap(self, fork, bus):
        if fork is False:
            why = "O programa principal deste robô não permite alterações (não é o nosso fork e não oferece interfaces para parâmetros de servo ou configuração de execução)."
        else:
            why = "Por enquanto, somente leitura. Instale o auxiliar root no robô para habilitar alterações aqui."
        return {"can_edit": False, "fork": fork, "why": why, "build": bus.get("build")}

    def _phase(self, bus):
        rd = self.rd
        if getattr(rd, "paused", None):
            return {"word": "Ajuste dos servos", "kind": "warn", "why": "O programa principal está parado conforme esperado; a página dos servos assumiu o barramento.", "error": None}
        if rd.present is False:
            return {"word": "Programa principal parado", "kind": "bad", "why": "Parar o robotd não desativa o torque; os servos ainda podem estar fazendo força.", "error": None}
        if not bus:
            return {"word": "Ainda sem leitura", "kind": None, "why": None, "error": None}
        word, kind = PHASE_CN.get(bus.get("phase"), (bus.get("phase") or "Desconhecido", None))
        if bus.get("mode") == "commissioning" and bus.get("phase") == "ready":
            word, kind = "Modo de depuração", "warn"
        return {"word": word, "kind": kind, "mode": bus.get("mode"), "phase": bus.get("phase"),
                "why": None, "error": bus.get("error")}

    def _missed_per_min(self, now):
        if len(self._missed) < 2:
            return None
        last = self._missed[-1]
        first = next((x for x in self._missed if last[0] - x[0] <= MISSED_WINDOW_S), None)
        if first is None or first is last or last[0] - first[0] < 5:
            return None
        return round((last[1] - first[1]) * 60.0 / (last[0] - first[0]), 1)

    def _run(self, now, bus, native, health, pol, st, walk, cfg):
        rd = self.rd
        loop = (health or {}).get("control_loop") if isinstance((health or {}).get("control_loop"), dict) else {}
        guard = bus.get("home_start_guard") if isinstance(bus.get("home_start_guard"), dict) else None
        track = getattr(rd, "startup", None)
        startup = track.view(now) if track is not None and track.epoch is not None and track.epoch == _hello_at(rd) else None
        unloaded = walk_unloaded(rd, pol, bus)
        lm = bus.get("loaded_models") if isinstance(bus.get("loaded_models"), dict) else {}
        am = bus.get("active_model") if isinstance(bus.get("active_model"), dict) else None
        models = self.disk.get("models") or {}
        active_name = self._name_of(am.get("path"), models) if am else None
        reader = native.get("imu_reader") if isinstance(native.get("imu_reader"), dict) else {}
        fusion = ((st or {}).get("imu") or {}).get("fusion") if isinstance((st or {}).get("imu"), dict) else None
        trunk = (cfg or {}).get("trunk_imu") if isinstance((cfg or {}).get("trunk_imu"), dict) else {}
        hbus = (health or {}).get("bus") if isinstance((health or {}).get("bus"), dict) else {}
        mv = (st or {}).get("move") if isinstance((st or {}).get("move"), dict) else None
        worst = self._worst_servos(bus)
        hz = num(loop.get("achieved_hz"))
        can_walk = None
        if guard is not None:
            can_walk = bool(guard.get("ready")) and not unloaded
        scale_base = (walk.get("loaded") or {}).get("action_scale") if walk.get("joint") else num(bus.get("action_scale"))
        return {
            "phase": self._phase(bus),
            "startup": startup,
            "walk_unloaded": unloaded,
            "loop": {"target": num(loop.get("target_hz")), "hz": hz, "missed": loop.get("missed"),
                     "missed_per_min": self._missed_per_min(now), "last_tick_age_ms": loop.get("last_tick_age_ms")},
            "health": {"healthy": (health or {}).get("healthy"), "degraded": (health or {}).get("degraded"),
                       "reason": (health or {}).get("reason")} if health else None,
            "guard": {k: guard.get(k) for k in ("ready", "reason", "max_joint_error_deg", "joint_tolerance_deg",
                                                 "tilt_deg", "tilt_tolerance_deg")} if guard else None,
            "can_walk": can_walk,
            "refusal": bus.get("last_enable_refusal"),
            "net": {"policy": (st or {}).get("policy"), "scale_use": bus.get("scale_use"),
                    "scale_use_cn": SCALE_USE_CN.get(bus.get("scale_use"), bus.get("scale_use")),
                    "policy_enabled": bus.get("policy_enabled"), "homed": bus.get("homed"),
                    "active_model": active_name, "walk_model": walk.get("name"), "walk_loaded": isinstance(lm.get("walk"), dict)},
            "scale": {"base": scale_base, "volt_mult": num(bus.get("voltage_scale_mult")),
                      "actual": num(bus.get("active_action_scale")), "voltage_adapt": bus.get("voltage_adapt"),
                      "nominal_v": num(bus.get("nominal_voltage"))},
            "move": {"requested": mv.get("requested"), "applied": mv.get("applied"),
                     "limited_by": mv.get("limited_by") or []} if mv else None,
            "imu": {"source": native.get("imu_source"), "ready": native.get("imu_ready"),
                    "reader": {k: reader.get(k) for k in ("state", "samples", "errors", "dropped", "last_error")} if reader else None,
                    "age_ms": native.get("imu_age_ms"),
                    "fusion_mode": trunk.get("bno08x_fusion") if native.get("imu_source") == "bno08x" else None,
                    "fusion": {"verdict": fusion.get("verdict"), "theta_deg": num(fusion.get("theta_deg"))}
                    if isinstance(fusion, dict) else None},
            "bus": {"consecutive_errors": hbus.get("consecutive_errors"), "startup_failures": hbus.get("startup_failures"),
                    "worst": worst, "last_cycle_error": bus.get("last_cycle_error"), "read_recovery": bus.get("read_recovery"),
                    "clamps": native.get("command_clamps_total"), "stale_ids": native.get("stale_joint_ids") or []},
            "cpu_c": num((health or {}).get("cpu_temp_c")),
            "infer_note": "Duração da inferência: o programa principal não informa; consulte a contagem de quadros perdidos.",
        }

    def _worst_servos(self, bus):
        from .servo import NAMES
        dc = bus.get("device_communication") if isinstance(bus.get("device_communication"), dict) else {}
        by = dc.get("by_id") if isinstance(dc.get("by_id"), dict) else {}
        rows = []
        for k, v in by.items():
            if not isinstance(v, dict):
                continue
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            t, m = v.get("timeout") or 0, v.get("missing") or 0
            if not isinstance(t, int) or not isinstance(m, int) or t + m == 0:
                continue
            rows.append({"id": i, "name": (NAMES.get(i) or (str(i),))[0], "timeout": t, "missing": m})
        rows.sort(key=lambda r: (-(r["timeout"] + r["missing"]), r["id"]))
        return rows[:3]

    # ---- Cartão 2 ----

    def _walk(self, bus, policy_cfg, disk):
        """Modelo de caminhada: diretório configurado no TOML, configuração de execução (arquivo) e modelo em uso pelo programa principal (loaded_models.walk)."""
        models = disk.get("models") or {}
        lm = bus.get("loaded_models") if isinstance(bus.get("loaded_models"), dict) else {}
        loaded = lm.get("walk") if isinstance(lm.get("walk"), dict) else None
        path = policy_cfg.get("walk") if isinstance(policy_cfg.get("walk"), str) else (loaded or {}).get("path")
        m = models.get(path) or {}
        file = m.get("exec") if isinstance(m.get("exec"), dict) else None
        running = loaded.get("runtime_execution_profile") if loaded and isinstance(loaded.get("runtime_execution_profile"), dict) else None
        joint = bool(file or running)
        keys = ("action_scale", "head_lowpass", "legs_lowpass")
        if joint:
            loaded_vals = {k: num(running.get(k)) for k in keys} if running else None
        else:
            # Para modelos não combinados, a caminhada usa [policy] global (valor resolved informado pelo programa principal).
            loaded_vals = {k: num(bus.get(k)) for k in keys} if any(num(bus.get(k)) is not None for k in keys) else None
        vals = {k: {"file": num((file or {}).get(k)), "loaded": (loaded_vals or {}).get(k)} for k in keys}
        mid = m.get("dir") or (os.path.basename(os.path.dirname(path)) if isinstance(path, str) else None)
        default = None
        if mid == BUNDLED_WALK:
            default, dsrc = dict(BUNDLED_WALK_DEFAULT), "Padrão incluído no pacote"
        elif isinstance(m.get("orig_exec"), dict):
            default, dsrc = {k: num(m["orig_exec"].get(k)) for k in keys}, "Valores anteriores à primeira alteração (.orig)"
        else:
            dsrc = None
        loaded_path = (loaded or {}).get("path")
        return {
            "path": path, "id": mid, "name": self._name_of(path, models), "joint": joint,
            "values": vals, "file": file is not None, "file_error": m.get("exec_error"),
            "loaded": loaded_vals,
            "same": (all(vals[k]["file"] == vals[k]["loaded"] for k in keys) if file and running else None),
            "orig": bool(m.get("orig")), "default": default, "default_src": dsrc,
            "path_differs": bool(loaded_path and path and loaded_path != path),
            "loaded_path": loaded_path,
        }

    def _feel(self, bus, native, hd, fork, walk, policy_cfg, disk):
        active = None
        if bus.get("policy_enabled") is True and num(bus.get("active_action_scale")) is not None:
            tf = bus.get("active_target_filters") if isinstance(bus.get("active_target_filters"), dict) else {}
            active = {"action_scale": num(bus.get("active_action_scale")), "head_lowpass": num(tf.get("head_lowpass")),
                      "legs_lowpass": num(tf.get("legs_lowpass")), "use": SCALE_USE_CN.get(bus.get("scale_use"), bus.get("scale_use"))}
        glob = {"action_scale": num(bus.get("action_scale")), "head_lowpass": num(bus.get("head_lowpass")),
                "legs_lowpass": num(bus.get("legs_lowpass")),
                "in_file": {k: policy_cfg.get(k) for k in ("action_scale", "head_lowpass", "legs_lowpass") if k in policy_cfg},
                "note": "A escala não é usada; a suavização só se aplica ao sentar e levantar (essas ações não são exibidas, plano D6d)."}
        return {
            "walk": walk, "active": active, "global": glob,
            "voltage": {"adapt": bus.get("voltage_adapt"), "nominal_v": num(bus.get("nominal_voltage")),
                        "mult": num(bus.get("voltage_scale_mult"))},
            "servo": self._servo(hd, fork, walk, disk, native.get("gain_mode")),
            "pad": self._pad(disk),
            "tomls_same": disk.get("tomls_same") if disk else None,
        }

    def _servo(self, hd, fork, walk, disk, gain_mode=None):
        models = disk.get("models") or {}
        con = (models.get(walk.get("path")) or {}).get("contract") or {}
        kp_fw = num(con.get("kp_fw"))
        default = {"kp": int(kp_fw) if kp_fw is not None else 5, "kd": V167_SERVO["kd"], "torque_limit": V167_SERVO["torque_limit"]}
        fe = disk.get("servo_file") or {}
        file, ferr = None, None
        if fe.get("missing"):
            file = None
        elif fe.get("error"):
            ferr = fe["error"]
        else:
            v = fe.get("value")
            if (isinstance(v, dict) and set(v) == {"kp", "kd", "torque_limit"}
                    and all(type(x) is int for x in v.values())):
                file = dict(v)
            else:
                ferr = "Formato inválido: são necessários exatamente três inteiros, kp / kd / torque_limit (o programa principal permanece aguardando o barramento se ler um arquivo assim)."
        loaded = hd.get("servo_parameters") if fork else None
        loaded = dict(loaded) if isinstance(loaded, dict) else None
        if fork:
            eff, src = (loaded, "Arquivo de parâmetros") if loaded else (default, "Sem arquivo de parâmetros: padrão V167 (P vem do contrato de caminhada)")
        else:
            eff, src = default, "Padrão V167 (P vem do contrato de caminhada)"
        same = None
        if fork is not None:
            same = (file == loaded) if fork else None
        regs = hd.get("registers_before_arm") if isinstance(hd.get("registers_before_arm"), list) else []
        reg = None
        if regs:
            ram = _group([r.get("temporary_pdi") for r in regs if isinstance(r, dict)])
            eep = _group([r.get("eeprom_pdi") for r in regs if isinstance(r, dict)])
            reg = {"ram_before_arm": ram, "eeprom": eep, "n": len(regs)}
        warn = []
        if eff:
            if (eff.get("kp") or 0) > 10:
                warn.append("P acima de 10: mais rígido que o usual e pode causar vibração.")
            if (eff.get("torque_limit") or 1000) < 500:
                warn.append("Limite de torque abaixo de 500: talvez não consiga ficar em pé.")
            if (eff.get("kd") or 0) > 0:
                warn.append("D acima de 0: ainda não testado no robô.")
        return {"fork": fork, "file": file, "file_exists": not fe.get("missing", False), "file_error": ferr,
                "loaded": loaded, "effective": eff, "src": src, "default": default,
                "file_vs_loaded": same, "written_p": {"p": (eff or {}).get("kp"),
                                                      "src": "Arquivo de parâmetros" if loaded else "Contrato de caminhada (kp_fw)",
                                                      "applied": hd.get("temporary_gains_applied") if hd else None},
                "regs": reg, "regs_why": None if reg else "Disponível somente depois que o robô ficar em pé e os servos aplicarem torque.", "gain_mode": gain_mode,
                "warn": warn}

    def _pad(self, disk):
        def settings(entry):
            v = _val(entry)
            if isinstance(v, dict) and "settings" in v and isinstance(v["settings"], dict):
                v = v["settings"]                # Resposta do padd: {"pid", "path", "settings": {...}}.
            if not isinstance(v, dict):
                return None
            return {"mouth_percent": num(v.get("mouth_percent")), "head_rad": num(v.get("head_rad"))}
        fe = disk.get("pad_file") or {}
        file = settings(fe)
        live = settings(disk.get("pad_live") or {})
        prev = settings(disk.get("pad_prev") or {})
        cur = file if file else (dict(PAD_DEFAULT) if fe.get("missing") else None)
        mouth = (cur or {}).get("mouth_percent")
        return {"file": file, "file_missing": bool(fe.get("missing")), "file_error": _err(fe), "live": live,
                "previous": prev, "current": cur, "default": dict(PAD_DEFAULT),
                "mouth_warn": mouth is not None and mouth <= MOUTH_WARN,
                "same": (file == live) if file and live else None}

    # ---- Cartão 3 / página de modelos ----

    def _name_of(self, path, models):
        if not isinstance(path, str):
            return None
        m = models.get(path) or {}
        info = m.get("info") if isinstance(m.get("info"), dict) else {}
        names = self.disk.get("builtin_names") or {}
        return info.get("name") or names.get(m.get("dir")) or None

    def _models(self, bus, pol, policy_cfg, cfg, disk):
        models = disk.get("models") or {}
        lm = bus.get("loaded_models") if isinstance(bus.get("loaded_models"), dict) else {}
        am = bus.get("active_model") if isinstance(bus.get("active_model"), dict) else {}
        pad = (cfg or {}).get("pad") if isinstance((cfg or {}).get("pad"), dict) else {}
        slots_pol = {s.get("slot"): s for s in (pol or {}).get("slots") or [] if isinstance(s, dict)}
        rows = []
        for slot in SLOTS:
            ps = slots_pol.get(slot) or {}
            path = ps.get("path") if ps else None
            if not path:
                path = policy_cfg.get(slot) if isinstance(policy_cfg.get(slot), str) else None
            if path == "none":
                path = None
            m = models.get(path) or {}
            man = m.get("manifest") if isinstance(m.get("manifest"), dict) else {}
            tr = man.get("training") if isinstance(man.get("training"), dict) else {}
            ld = lm.get(slot) if isinstance(lm.get(slot), dict) else None
            sha = (ld or {}).get("sha256") or man.get("onnx_sha256")
            ckpt = tr.get("checkpoint", man.get("checkpoint"))
            skill = SLOT_SKILL.get(slot)
            buttons = [BUTTON_CN.get(b, b) for b, v in pad.items() if skill and v == skill]
            exe = m.get("exec") if isinstance(m.get("exec"), dict) else None
            con = m.get("contract") if isinstance(m.get("contract"), dict) else {}
            filt = con.get("action_filter") or {}
            plain = filt.get("enabled") is False and (filt.get("head_alpha") == 1.0 and filt.get("legs_alpha") == 1.0)
            rows.append({
                "slot": slot, "label": SLOT_CN[slot], "path": path, "id": m.get("dir"),
                "name": self._name_of(path, models), "task": (ld or {}).get("task") or man.get("task") or con.get("task"),
                "rounds": rounds_of(ckpt), "checkpoint": ckpt if isinstance(ckpt, (int, float)) else None,
                "commit": tr.get("commit"), "repo": tr.get("repo"), "sha": sha, "sha12": sha[:12] if isinstance(sha, str) else None,
                "loaded": ld is not None, "active": bool(am and path and am.get("path") == path),
                "error": ps.get("error"), "buttons": buttons,
                "exec": {k: num(exe.get(k)) for k in ("action_scale", "head_lowpass", "legs_lowpass")} if exe else None,
                "orig": bool(m.get("orig")), "unfiltered": bool(plain) and not exe,
                "files_ok": bool(m.get("onnx")) if path else None, "manifest_error": m.get("manifest_error"),
                "kp_fw": num(con.get("kp_fw")),
            })
        rollers = []
        for r in disk.get("rollers") or []:
            man = r.get("manifest") if isinstance(r.get("manifest"), dict) else {}
            tr = man.get("training") if isinstance(man.get("training"), dict) else {}
            con = r.get("contract") if isinstance(r.get("contract"), dict) else {}
            req = con.get("required") or {}
            scale = con.get("runtime_action_scale") if r["id"] == "standup" else (
                req.get("ground_pick_action_scale") if r["id"] in ("crouch", "spin") else req.get("action_scale"))
            rollers.append({"id": r["id"], "label": r["label"], "installed": bool(r.get("onnx") and man),
                            "rounds": rounds_of(tr.get("checkpoint", man.get("checkpoint"))), "task": man.get("task"),
                            "sha12": (man.get("onnx_sha256") or "")[:12] or None,
                            "action_scale": num(scale), "head_lowpass": num(req.get("head_lowpass")),
                            "legs_lowpass": num(req.get("legs_lowpass"))})
        return {"slots": rows, "rollers": rollers, "skills": (pol or {}).get("skills") or [],
                "change_error": (pol or {}).get("change_error"), "policies_known": pol is not None}

    # ---- Exportação do perfil do robô ----

    def body(self):
        v = _val((self.disk or {}).get("body") or {})
        if v is None:
            v = _val(self.cache.get(Path(self.state_dir) / BODY_FILE, _json))
        return v if isinstance(v, dict) else None

    def profile(self):
        """Perfil do robô para treinamento (resumo somente leitura, plano §2.4). Valores indisponíveis são null; nenhum dado é inventado."""
        rd = self.rd
        bus = rd.bus.value if isinstance(rd.bus.value, dict) else {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
        calib = fresh_calib(rd)
        source, mount = mount_of(bus, calib)
        cal = (calib or {}).get("calibration") if isinstance((calib or {}).get("calibration"), dict) else (calib or {})
        joints = []
        for j in cal.get("joints") or []:
            if isinstance(j, dict):
                joints.append({k: j.get(k) for k in ("name", "id", "zero_raw", "direction", "min_rad", "max_rad", "calibrated")})
        v = self.view()
        servo = v["feel"]["servo"]
        walk = v["feel"]["walk"]
        wrow = next((r for r in v["models"]["slots"] if r["slot"] == "walk"), {})
        regs = hd.get("registers_before_arm") if isinstance(hd.get("registers_before_arm"), list) else []
        return {
            "schema": "microduck-studio-duck-profile/v1",
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "note": "Perfil do robô exportado pelo Microduck Studio para treinamento. Valores indisponíveis são null; o peso é informado pelo usuário.",
            "duck": {"label": self.duck.get("label"), "name_on_duck": (rd.sysinfo.value or {}).get("name") if isinstance(rd.sysinfo.value, dict) else None,
                     "build": bus.get("build")},
            "body": self.body(),
            "imu": {"chip": source, "mount_quat_wxyz": (mount or {}).get("quat"), "verified": (mount or {}).get("verified")},
            "joints": joints or None,
            "servo": {"effective": servo["effective"], "source": servo["src"], "file": servo["file"],
                      "registers_before_arm": [{k: r.get(k) for k in ("id", "name", "temporary_pdi", "eeprom_pdi", "mode")}
                                               for r in regs if isinstance(r, dict)] or None},
            "walk_model": {"id": walk.get("id"), "name": walk.get("name"), "task": wrow.get("task"), "checkpoint": wrow.get("checkpoint"),
                           "rounds": wrow.get("rounds"), "commit": wrow.get("commit"), "sha256": wrow.get("sha"),
                           "execution_loaded": walk.get("loaded"), "execution_file": {k: walk["values"][k]["file"] for k in walk["values"]}
                           if walk.get("file") else None},
            "policy_global": {k: v["feel"]["global"][k] for k in ("action_scale", "head_lowpass", "legs_lowpass")},
            "voltage": v["feel"]["voltage"],
        }

    def save_body(self, body, by=None):
        """Peso (g) e material das patas informados nas configurações. Grava somente no diretório state do Studio, sem alterar a configuração do robô."""
        if not isinstance(body, dict):
            raise Refused("Nenhum dado foi recebido.")
        out = {}
        for k in BODY_KEYS:
            x = body.get(k)
            if x in (None, ""):
                out[k] = None
                continue
            if isinstance(x, str):
                try:
                    x = float(x)
                except ValueError:
                    raise Refused(f"{k}: informe um número em gramas.") from None
            x = num(x)
            if x is None or not 0 < x <= BODY_MAX_G:
                raise Refused(f"{k}: o valor deve estar entre 0 e {BODY_MAX_G} g.")
            out[k] = round(x, 1)
        for k, n in (("foot", 40), ("note", 200)):
            s = body.get(k)
            if s in (None, ""):
                out[k] = None
                continue
            if not isinstance(s, str) or len(s) > n or any(ord(ch) < 32 for ch in s):
                raise Refused(f"{'Material das patas' if k == 'foot' else 'Observação'}: máximo de {n} caracteres, sem quebras de linha.")
            out[k] = s.strip() or None
        out["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        out["by"] = by
        path = Path(self.state_dir) / BODY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".duck-body-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.log.info("Peso do perfil do robô salvo somente no Studio", cat="Ajuste",
                      raw=json.dumps({k: out[k] for k in BODY_KEYS + ("foot",)}, ensure_ascii=False), ctx={"by": by})
        self.disk = dict(self.disk, body={"value": out})
        return out

    async def handle(self, args, by=None):
        op = args.get("op")
        if op == "save_body":
            return await asyncio.to_thread(self.save_body, args.get("body"), by)
        if op == "body":
            return self.body()
        if op in ("tune_walk", "tune_servo", "tune_pad", "undo", "default"):
            raise Refused("Por enquanto, somente leitura. Instale o auxiliar root no robô para habilitar alterações aqui.")
        raise Refused(f"Operação desconhecida: {op}")

    def diag(self):
        """Snapshot de ajustes no pacote de diagnóstico: dados lidos dos três tipos de arquivo e confirmação do programa principal."""
        v = self.view()
        d = self.disk or {}
        return {"view": v, "files": {k: (d.get(k) or {}).get("error") or ("ausente" if (d.get(k) or {}).get("missing") else "presente")
                                     for k in ("config", "saved", "servo_file", "pad_file", "pad_live")},
                "tomls_same": d.get("tomls_same"), "root": str(self.root), "platform": sys.platform}


def _group(rows):
    """Converte [[P, D, I], ...] em [{"pdi": [P, D, I], "n": quantidade}]; agrupa em uma linha quando os 15 servos são iguais."""
    out = {}
    for r in rows:
        if isinstance(r, list) and len(r) == 3:
            key = tuple(r)
            out[key] = out.get(key, 0) + 1
    return [{"pdi": list(k), "n": n} for k, n in sorted(out.items(), key=lambda kv: -kv[1])]
