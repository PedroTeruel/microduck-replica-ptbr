"""Lista de integração da página inicial e leitura da temperatura da placa.

A lista tem seis etapas: calibrar servos, verificar a orientação da IMU, gravar no programa principal, parear o controle,
testar a parada de emergência e confirmar que o robô fica em pé e caminha. Cada etapa pode ser concluída, ignorada ou refeita.
As marcações ficam ligadas às condições verificadas (calibração, sensor, controle e versão do programa) e perdem validade
quando essas condições mudam. A confirmação de ações com consequências exige uma segunda etapa no servidor.

Os registros ficam em state_dir/onboarding.json e são validados item por item. Leituras de arquivos ocorrem em uma thread
separada para evitar que o cartão SD bloqueie o loop de controle. A histerese da temperatura da placa é calculada à parte.
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import time

from .estop import STARTING_LONG_S, STARTING_PHASES
from .imu import mount_of
from .robotd import fresh_calib
from .state import JOINT_CN, MAX_AGE, STILL_STARTING, posture, starting_secs

ONBOARD_FILE = "onboarding.json"
SERVO_IDS = (20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14)   # Mesmo conjunto de servo.IDS; não importe servo porque ele acessa a porta serial.
STOOD_S = 3.0             # Tempo contínuo em postura ereta com torque confirmado para registrar que o robô ficou em pé.
WALKED_S = 2.0            # Tempo acumulado caminhando para registrar que o robô caminhou.
CPU_WARN_C = 80.0         # Mesmo limite de state.CPU_WARN_C; a placa fica a 77–78 °C em repouso.
CPU_CLEAR_C = 77.0        # Histerese: só apaga o aviso abaixo desta temperatura.
STUDIO_SCAN_S = 10.0      # Intervalo para reler a pasta servo-calib.
THERMAL_ROOT = "/sys/class/thermal"
# Configurações do robotd: o fork usa --params /etc/robot/feetech-ft5/robotd.toml; o caminho padrão é /etc/robot/robotd.toml.
ROBOTD_CONFIGS = ("/etc/robot/feetech-ft5/robotd.toml", "/etc/robot/robotd.toml")
ROBOTD_CFG_S = 30.0       # Intervalo para reler a configuração.
CPUFREQ_ROOT = "/sys/devices/system/cpu/cpufreq"
STAND = ("holding", "policy", "walking")
# Mensagem emitida quando o modo de movimento aguarda o barramento; calibração e IMU podem gerar a mesma mensagem.
CALIB_ERR = re.compile(r"calibrat|motion_enabled|calibration file|IMU mounting", re.I)

TIPS = {
    "servo": "Os pontos zero podem entrar em conflito: calibre na página de servos do Studio (os 15 valores zero_raw no arquivo principal devem ser 2048)",
    "imu": "Com o sensor instalado em ângulo, o robô pode avançar ao caminhar",
    "commit": "Ao gravar, o programa principal libera o torque: segure o robô para ele não cair",
    "pad": "Coloque o G50 Pro na posição S",
    "estop": "Teste sempre que trocar de controle",
    "walk": None,
}
TITLES = {"servo": "Ponto zero dos servos", "imu": "Orientação da IMU", "commit": "Gravar no programa", "pad": "Parear controle", "estop": "Testar parada de emergência", "walk": "Ficar em pé e caminhar"}
ORDER = ("servo", "imu", "commit", "pad", "estop", "walk")
GO = {"servo": "servos", "imu": "imu", "commit": "commit", "pad": "pad_wizard", "estop": "estop", "walk": "remote"}   # Ação de abrir ou refazer cada etapa.
SKIP_CHANGED = {"servo": "o ponto zero dos servos", "imu": "a orientação da IMU (ou o sensor)", "commit": "a calibração", "estop": "o controle (ou a versão do programa principal)", "walk": "a calibração"}
COMMIT_TEXT = "Grava no programa principal os pontos zero, as orientações dos servos e a orientação da IMU. A imagem de fábrica inicia no modo de calibração; ao concluir, muda para o modo de movimento e reinicia (cerca de 20 segundos). Depois disso, o robô poderá ficar em pé e caminhar ao iniciar, sem abrir a página web."

# Ações de concluir e ignorar: convertem as ações da página nas chaves dos registros; são mutuamente exclusivas.
KINDS = {"done": "done", "skip": "skipped"}
OTHER = {"done": "skip", "skip": "done"}
MARKED_TEXT = {"done": "Você marcou como concluído", "skip": "Ignorado (não fazer agora)"}
MARKED_WORD = {"done": "marcado como concluído", "skip": "ignorado"}
CHANGED_WORD = {"done": "A conclusão foi marcada, mas", "skip": "O item foi ignorado, mas"}
# Texto da confirmação em duas etapas: {q} é a pergunta e {v} descreve a consequência.
ASK_Q = {"done": "marcar como concluído", "skip": "ignorar"}
ASK_V = {"done": "marcado como concluído", "skip": "ignorado"}
# Ações que exigem confirmação adicional por causa das consequências.
HARD_SERVO = "O programa principal informa que a calibração está incompleta: o robô não ficará em pé mesmo se for {v}"
HARD_IMU = "A orientação da IMU não foi confirmada pelo programa principal: o robô não ficará em pé mesmo se for {v}"
HARD_STUCK = "O programa principal não permite ativar o torque (calibração ou orientação da IMU incompleta): o robô não ficará em pé mesmo se for {v}"
UNK_WHY = "Não foi possível ler este item ({text}): o Studio não pode verificá-lo e seguirá sua indicação"
FP_WHY = "{what}: o Studio registrará agora e verificará quando os dados estiverem disponíveis"
FROZEN_ASK = "Confirma {q}? Os servos estão sendo ajustados: a lista permanece como estava antes do ajuste e só exibirá que foi {v} quando o controle voltar ao programa principal"
FROZEN_UNDO = "Confirma o cancelamento? Os servos estão sendo ajustados: a lista permanece como estava antes do ajuste e só exibirá o cancelamento quando o controle voltar ao programa principal"


def fill(text, kind):
    """Substitui {q} e {v} na pergunta e na consequência pelo texto da ação (use replace porque o motivo pode conter chaves)."""
    return text.replace("{q}", ASK_Q[kind]).replace("{v}", ASK_V[kind]) if text else text


# ---------------- Impressões digitais ----------------

def _joints(calib):
    cal = (calib or {}).get("calibration") if isinstance((calib or {}).get("calibration"), dict) else None
    js = (cal or {}).get("joints")
    return [j for j in js if isinstance(j, dict)] if isinstance(js, list) else None


def _hash(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def joints_fp(calib):
    """Retorna a impressão digital de zero_raw/direction dos 15 servos ou None se a calibração não estiver disponível."""
    js = _joints(calib)
    if not js:
        return None
    return _hash(sorted([j.get("id"), j.get("zero_raw"), j.get("direction")] for j in js))


def mount_fp(source, quat):
    """Retorna a impressão digital do sensor e da orientação de montagem, arredondada para quatro casas decimais."""
    if not isinstance(quat, (list, tuple)) or len(quat) != 4:
        return None
    try:
        return _hash([source, [round(float(x), 4) for x in quat]])
    except (TypeError, ValueError):
        return None


def full_fp(bus, calib):
    """Impressão digital da calibração dos servos e da orientação atual da IMU."""
    j = joints_fp(calib)
    source, mount = mount_of(bus, calib)
    m = mount_fp(source, (mount or {}).get("quat"))
    if j is None or m is None:
        return None
    return _hash([j, m])


# ---------------- Registros de calibração dos servos do Studio ----------------

def studio_servo_record(state_dir):
    """Lê as calibrações EEPROM não simuladas e não desfeitas; retorna os IDs válidos e o horário do registro mais recente.
    Registros desfeitos são renomeados para undone-* e ignorados; cópias de simulação ficam em uma pasta temporária."""
    d = os.path.join(state_dir or ".", "servo-calib")
    ids, latest = set(), None
    try:
        names = sorted(f for f in os.listdir(d) if f.startswith("eeprom-") and f.endswith(".json"))
    except OSError:
        return {"ids": ids, "time": None}
    for fn in names:
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("sim"):
            continue
        targets = rec.get("targets") if isinstance(rec.get("targets"), dict) else {}
        bad = rec.get("bad") if isinstance(rec.get("bad"), dict) else {}
        got = {int(k) for k in targets if str(k).isdigit()} - {int(k) for k in bad if str(k).isdigit()}
        if got:
            ids |= got
            latest = rec.get("time") or latest
    return {"ids": ids, "time": latest}


# ---------------- Temperatura da placa: leitura própria do Studio ----------------

def _read_int(path):
    try:
        with open(path, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_board(thermal_root=THERMAL_ROOT, cpufreq_root=CPUFREQ_ROOT):
    """Lê temperatura e limitação de frequência da placa usando o mesmo cálculo do robotd.
    Usa a maior temperatura válida e o maior nível de limitação de frequência. Retorna None fora do Linux ou sem dados."""
    try:
        zones = [e for e in os.listdir(thermal_root)]
    except OSError:
        return None
    hot = None
    for name in zones:
        if not name.startswith("thermal_zone"):
            continue
        milli = _read_int(os.path.join(thermal_root, name, "temp"))
        if milli is None or milli <= 0:
            continue
        c = milli / 1000.0
        hot = c if hot is None or c > hot else hot
    thr = None
    try:
        pols = os.listdir(cpufreq_root)
    except OSError:
        pols = []
    for name in pols:
        if not name.startswith("policy"):
            continue
        khz = _read_int(os.path.join(cpufreq_root, name, "scaling_max_freq"))
        mx = _read_int(os.path.join(cpufreq_root, name, "cpuinfo_max_freq"))
        if khz is None or not mx:
            continue
        if thr is None or khz * thr["max_khz"] < thr["khz"] * mx:
            thr = {"khz": khz, "max_khz": mx, "level": 0, "max_level": 0}
    if thr is not None:
        for name in zones:
            if not name.startswith("cooling_device"):
                continue
            try:
                with open(os.path.join(thermal_root, name, "type"), encoding="ascii") as f:
                    kind = f.read().strip()
            except OSError:
                continue
            if "cpufreq" not in kind:
                continue
            lv, mx = _read_int(os.path.join(thermal_root, name, "cur_state")), _read_int(os.path.join(thermal_root, name, "max_state"))
            if lv is None or not mx:
                continue
            if thr["max_level"] == 0 or lv * thr["max_level"] > thr["level"] * mx:
                thr.update(level=lv, max_level=mx)
    if hot is None and thr is None:
        return None
    return {"c": hot, "throttle": thr}


def read_battery_shutdown(paths=ROBOTD_CONFIGS):
    """Lê battery_empty_shutdown da seção [safety] da configuração do robotd; retorna None se indisponível."""
    import tomllib
    for path in paths:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return None
        v = (data.get("safety") or {}).get("battery_empty_shutdown") if isinstance(data.get("safety"), dict) else None
        return v if isinstance(v, bool) else None
    return None


# ---------------- Avaliação das etapas ----------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _f1(x):
    """Formata uma casa decimal; valores não numéricos são exibidos como “?”."""
    return f"{x:.1f}" if _num(x) else "?"


def _row(key, state, text, when=None, actions=(), note=None, hard=None, found=None, ask=None):
    """Monta uma etapa. hard/found descrevem consequências que exigem confirmação; ask é a confirmação da parada de emergência.
    mark contém as ações para conclusão ou para ignorar; marked indica uma marcação feita pelo usuário."""
    return {"key": key, "n": ORDER.index(key) + 1, "title": TITLES[key], "tip": TIPS[key], "state": state,
            "text": text, "when": when, "note": note, "actions": [{"do": d, "label": lab} for d, lab in actions],
            "hard": hard, "found": found, "ask": ask, "go": GO[key], "mark": None, "marked": None}


def header_of(inp):
    """Monta o cabeçalho de conexão e o estado do robô."""
    bus = inp.get("bus") if isinstance(inp.get("bus"), dict) else None
    if inp.get("bench"):
        return {"ok": False, "kind": "bench", "text": "Modo de bancada: sem conexão ao programa principal; lista desativada"}
    if inp.get("servo_session"):
        return {"ok": False, "kind": "servo", "text": "Ajustando servos: a lista permanece no estado anterior ao ajuste"}
    if inp.get("present") is False:
        return {"ok": False, "kind": "absent", "text": "O programa principal não está em execução: sem conexão ao robotd"}
    if bus is None:
        return {"ok": False, "kind": "connecting", "text": "Conectando ao programa principal…"}
    mode, phase, err = bus.get("mode"), bus.get("phase"), bus.get("error")
    if phase in STARTING_PHASES:
        if err and CALIB_ERR.search(str(err)):
            return {"ok": False, "kind": "stuck_calib", "text": "O programa principal não ativa o torque: calibração ou orientação da IMU incompleta", "raw": str(err)}
        if phase == "waiting_for_bus":
            text = "Aguardando o barramento dos servos (eles podem estar sem energia)"
        elif (inp.get("starting_s") or 0) >= STARTING_LONG_S:
            # Se ainda estiver na etapa de inicialização após 30 segundos, informe que o processo está parado.
            text = f"O programa principal continua informando “iniciando” após {STARTING_LONG_S:.0f} segundos: {STILL_STARTING}"
        else:
            text = "O programa principal ainda está iniciando"
        return {"ok": False, "kind": "starting", "text": text, "raw": str(err) if err else None}
    if mode == "commissioning":
        # Instantâneo do modo de calibração. read_error indica que o programa iniciou, mas falhou ao ler os servos.
        if phase == "read_error":
            return {"ok": False, "kind": "commissioning", "text": "Modo de calibração: programa iniciado, mas houve erro ao ler os servos (verifique a alimentação e os cabos)",
                    "raw": str(bus.get("last_cycle_error") or err or "") or None}
        return {"ok": False, "kind": "commissioning", "text": "Modo de calibração: conclua a calibração inicial da IMU; a etapa 3 ativa o modo de movimento"}
    if mode == "motion" and phase == "control":
        return {"ok": True, "kind": "ok", "text": "Conectado"}
    return {"ok": False, "kind": "other", "text": f"Programa principal no modo {mode or '?'}, etapa {phase or '?'}"}


def _imu_mount_unverified(bus, calib):
    """Retorna True se o programa principal indicar explicitamente que a orientação da IMU não foi confirmada."""
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    _source, mount = mount_of(bus, calib)
    return native.get("imu_mount_verified") is False or (isinstance(mount, dict) and mount.get("verified") is False)


def servo_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("servo", "unk", "Conecte ao programa principal para verificar", actions=[("servos", "Abrir servos")])
    uncal = (calib or {}).get("uncalibrated_joints")
    if head["kind"] == "stuck_calib":
        # Se somente a IMU não estiver confirmada e todos os servos estiverem calibrados, avalie a etapa normalmente.
        if not (_imu_mount_unverified(bus, calib) and isinstance(uncal, list) and not uncal):
            return _row("servo", "no", "O programa principal não ativa o torque: calibração ou orientação da IMU incompleta",
                        actions=[("servos", "Abrir servos")], hard=HARD_STUCK)
    js = _joints(calib)
    if isinstance(uncal, list) and uncal:
        names = ", ".join(JOINT_CN.get(str(x), str(x)) for x in uncal[:4]) + ("…" if len(uncal) > 4 else "")
        return _row("servo", "no", f"O programa principal informa que {len(uncal)} servos não foram calibrados: {names}", actions=[("servos", "Abrir servos")], hard=HARD_SERVO)
    if js and any(j.get("calibrated") is False for j in js):
        bad = [JOINT_CN.get(j.get("name"), j.get("name")) for j in js if j.get("calibrated") is False]
        return _row("servo", "no", f"{len(bad)} servos não estão calibrados no arquivo do programa principal: {', '.join(bad[:4])}", actions=[("servos", "Abrir servos")],
                    hard=HARD_SERVO)
    if head["kind"] == "commissioning" and bus.get("calibrated") is False:
        return _row("servo", "no", "O programa principal informa que a calibração está incompleta", actions=[("servos", "Abrir servos")], hard=HARD_SERVO)
    if not js:
        return _row("servo", "unk", "O arquivo de calibração do programa principal ainda não foi lido (calibration-status)", actions=[("servos", "Abrir servos")])
    off = [j for j in js if j.get("zero_raw") != 2048]
    if off:
        def one(j):
            z = j.get("zero_raw")
            d = f" (diferença de {(z - 2048) * 360 / 4096:+.1f}°)" if isinstance(z, (int, float)) else ""
            return f"{JOINT_CN.get(j.get('name'), j.get('name'))} {z}{d}"
        text = f"Os pontos zero divergem: {len(off)} valores zero_raw no arquivo principal diferem de 2048 — " + ", ".join(one(j) for j in off[:3]) \
            + ("…" if len(off) > 3 else "") + ". Provavelmente são valores de fábrica; calibre os servos no Studio."
        return _row("servo", "todo", text, actions=[("servos", "Abrir servos")],
                    found="Os pontos zero divergem: o robô pode ficar torto ou desviar mesmo se for {v} (a etapa 3 grava o ponto zero 2048).")
    st = inp.get("studio_servo") or {}
    fp = joints_fp(calib)
    if set(SERVO_IDS) <= set(st.get("ids") or ()):
        # Salva a impressão digital dos servos após a calibração; uma alteração exige nova verificação.
        ss = rec.get("servo_studio") if isinstance(rec.get("servo_studio"), dict) else None
        if ss and ss.get("src") == st.get("time") and ss.get("fp") == fp:
            return _row("servo", "ok", "Servos calibrados no Studio; os 15 valores no arquivo principal são 2048", when=st.get("time"))
        if ss and ss.get("src") == st.get("time"):
            return _row("servo", "todo", "O arquivo de calibração mudou depois do ajuste dos servos: marque como concluído se já verificou ou calibre novamente",
                        when=st.get("time"), actions=[("servos", "Abrir servos")])
    c = rec.get("confirm_servo") if isinstance(rec.get("confirm_servo"), dict) else None
    if c and c.get("fp") == fp:
        return _row("servo", "ok", "Verificado: os 15 valores no arquivo principal são 2048", when=c.get("at"))
    if c:
        return _row("servo", "todo", "O arquivo de calibração principal mudou depois da verificação: marque como concluído se já verificou ou calibre novamente",
                    actions=[("servos", "Abrir servos")])
    return _row("servo", "todo", "O arquivo principal indica que os servos foram calibrados, mas o Studio não tem esse registro. "
                "Marque como concluído se já fez a calibração na página de servos do Studio.", actions=[("servos", "Abrir servos")])


def imu_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("imu", "unk", "Conecte ao programa principal para verificar", actions=[("imu", "Abrir IMU")])
    source, mount = mount_of(bus, calib)
    # A verificação explícita da IMU é feita nos ramos HARD_IMU abaixo.
    if head["kind"] == "commissioning" and bus.get("imu_mount_verified") is False:
        return _row("imu", "no", "O programa principal informa que a orientação da IMU não foi confirmada", actions=[("imu", "Abrir IMU")], hard=HARD_IMU)
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    if native.get("imu_mount_verified") is False:
        # Se busStatus indicar explicitamente que a orientação não foi confirmada, exiba como pendente.
        return _row("imu", "no", "A orientação de montagem da IMU ainda não foi confirmada; uma montagem incorreta pode fazer o robô avançar ao caminhar", actions=[("imu", "Abrir IMU")],
                    hard=HARD_IMU)
    if mount and mount.get("verified") is False:
        return _row("imu", "no", "A orientação da IMU salva pelo programa principal não foi confirmada (verified não é true)",
                    actions=[("imu", "Abrir IMU")], hard=HARD_IMU)
    mfp = mount_fp(source, (mount or {}).get("quat"))
    if mfp is None:
        return _row("imu", "unk", "A orientação da IMU salva pelo programa principal ainda não foi lida (calibration-status)", actions=[("imu", "Abrir IMU")])
    chk = rec.get("imu_check") if isinstance(rec.get("imu_check"), dict) else None
    if chk and chk.get("source") == source and chk.get("mount_fp") == mfp:
        d, t = chk.get("diff_deg"), chk.get("tilt_deg")
        if chk.get("ok") is True and _num(d):
            return _row("imu", "ok", f"Verificado em pé na página da IMU: diferença de {_f1(d)}° em relação à orientação usada pelo programa principal", when=chk.get("at"))
        return _row("imu", "todo", f"Última verificação em pé: diferença de {_f1(d)}° na orientação usada pelo programa principal e inclinação de {_f1(t)}°"
                    " (meta: diferença < 2° e inclinação ≤ 5°)", when=chk.get("at"), actions=[("imu", "Abrir IMU")],
                    found=f"Verificação em pé encontrou diferença de {_f1(d)}° na orientação: o robô pode avançar ao caminhar mesmo se for {{v}}")
    if chk:
        return _row("imu", "todo", "A orientação da IMU ou o sensor mudou desde a verificação: verifique novamente em pé na página da IMU", actions=[("imu", "Abrir IMU")])
    return _row("imu", "todo", "O arquivo informa que a orientação foi confirmada; verifique-a em pé na página da IMU", actions=[("imu", "Abrir IMU")])


def _commit_complete(bus, calib):
    """Verifica se o programa principal ativou o movimento e confirmou os 15 servos e a IMU em uso."""
    cal = (calib or {}).get("calibration") if isinstance(calib, dict) else None
    cal = cal if isinstance(cal, dict) else (calib if isinstance(calib, dict) else {})
    js = _joints(calib)
    _source, mount = mount_of(bus, calib)
    return (cal.get("motion_enabled") is True and isinstance(js, list) and len(js) == len(SERVO_IDS)
            and all(j.get("calibrated") is True for j in js)
            and isinstance(mount, dict) and mount.get("verified") is True)


def commit_row(inp, rec, head):
    """Avalia a gravação no programa principal e inclui os itens de preparação do CommitService."""
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    cv = inp.get("commit") if isinstance(inp.get("commit"), dict) else None

    def out(state, text, actions=()):
        row = _row("commit", state, text, actions=actions)
        row["desc"] = COMMIT_TEXT
        if cv is not None and cv.get("note"):
            row["desc"] += "\n" + cv["note"]
        if cv is not None:
            row["commit"] = cv
        return row

    if head["kind"] in ("absent", "connecting", "bench"):
        return out("unk", "Conecte ao programa principal para verificar", [("commit", "Ver detalhes")])
    if cv is not None and cv.get("dirty") is True:
        why = ", ".join(cv.get("dirty_why") or []) or "há alterações"
        return out("todo", f"Há alterações que ainda não foram gravadas no programa principal: {why}", [("commit", "Gravar no programa")])
    if _commit_complete(bus, calib):
        return out("ok", "Gravado no programa principal: os 15 servos e a orientação da IMU estão confirmados; o robô poderá ficar em pé e caminhar ao iniciar",
                   [("commit", "Gravar novamente")])
    js = _joints(calib)
    if (not isinstance(js, list) or not js) and not (cv is not None and cv.get("preview_ok") is True):
        return out("unk", "O arquivo de calibração do programa principal ainda não foi lido; aguarde alguns segundos", [("commit", "Ver detalhes")])
    if cv is None:
        return out("todo", "Ainda não foi gravado no programa principal; aguarde o Studio ler os itens de preparação", [("commit", "Ver detalhes")])
    items = cv.get("items") if isinstance(cv.get("items"), list) else []
    bad = [i for i in items if isinstance(i, dict) and not i.get("ok")]
    if bad:
        labels = ", ".join(str(i.get("label") or "?") for i in bad[:3]) + ("…" if len(bad) > 3 else "")
        return out("todo", f"Faltam {labels}: {bad[0].get('text') or 'complete os itens abaixo'}", [("commit", "Gravar no programa")])
    if cv.get("ready") is True:
        return out("todo", "Tudo pronto: grave no programa principal; ele será reiniciado ao concluir", [("commit", "Gravar no programa")])
    return out("todo", "Ainda não foi gravado no programa principal; complete os itens abaixo", [("commit", "Gravar no programa")])

def _pad_names(pads):
    return ", ".join(p.get("name") or p.get("mac") or "controle" for p in pads[:2])


def pad_row(inp, rec, head):
    pad = inp.get("pad")
    if pad is None:
        return _row("pad", "unk", "O suporte a controles está desativado neste robô (modo de bancada)")
    pads = [p for p in pad.get("pads") or [] if isinstance(p, dict)]
    good = [p for p in pads if p.get("paired") and p.get("trusted")]
    if good:
        on = next((p for p in good if p.get("connected")), None)
        return _row("pad", "ok", f"{on.get('name') or 'Controle'} · conectado" if on else
                    f"{_pad_names(good)} pareado; desconectado (ligue o controle para reconectar)")
    if any(p.get("paired") for p in pads):
        return _row("pad", "todo", "Pareado, mas não autorizado: não reconectará após reiniciar; selecione Reparar", actions=[("pad_known", "Reparar")])
    dev = pad.get("device") or {}
    if pad.get("attached"):
        return _row("pad", "ok", f"padd detectou {dev.get('name') or 'um controle'} conectado" + ("" if pad.get("known") else " (configd indisponível)"))
    if pad.get("known"):
        return _row("pad", "no", "Nenhum controle pareado (você também pode usar o controle web abaixo)", actions=[("pad_wizard", "Parear controle")])
    seen = rec.get("pads_seen") if isinstance(rec.get("pads_seen"), dict) else {}
    tail = f"; controles pareados antes: {', '.join(list(seen.values())[:2])}" if seen else ""
    return _row("pad", "unk", f"Não foi possível ler o estado dos controles no configd{tail}", actions=[("pad_wizard", "Parear controle")])


def _current_pad(pad):
    """Retorna MAC e nome do controle ativo, detectado ou único pareado; retorna (None, None) quando indisponível."""
    if pad is None:
        return None, None
    a = pad.get("active") or {}
    if a.get("mac"):
        return str(a["mac"]).upper(), a.get("name")
    dev = pad.get("device") or {}
    if pad.get("attached") and dev.get("unique"):
        return str(dev["unique"]).upper(), dev.get("name")
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired") and p.get("mac")]
    if pad.get("known") and len(paired) == 1:
        return str(paired[0]["mac"]).upper(), paired[0].get("name")
    return None, None


def _no_physical_pad(pad):
    """Indica que não há controle físico pareado ou conectado e o configd confirmou esse estado."""
    return bool(pad and pad.get("known") and not pad.get("attached")
                and not [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")])


def _many_unconnected(pad):
    """Retorna quantos controles estão pareados quando há vários, mas nenhum está conectado."""
    if not pad or pad.get("attached") or (pad.get("active") or {}).get("mac"):
        return 0
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")]
    return len(paired) if len(paired) >= 2 and not any(p.get("connected") for p in paired) else 0


# Concluir ou ignorar o teste de parada de emergência exige confirmação em duas etapas.
ESTOP_ASK = {"never": "Confirma {q}? Ainda não foi testado se o botão Select do controle consegue parar o robô",
             "web": "Confirma {q}? No controle web, use Espaço ou o botão vermelho superior; teste novamente ao parear um controle físico",
             "pad": "Confirma {q}? O controle mudou e o botão Select deste controle ainda não foi testado",
             "build": "Confirma {q}? O programa principal foi atualizado e o botão Select precisa ser testado novamente",
             "bad": "Confirma {q}? A parada de emergência não está funcionando ({why}); isso não mudará se for {v}"}


def estop_row(inp, rec, head):
    pad = inp.get("pad")
    r = rec.get("estop") if isinstance(rec.get("estop"), dict) else None
    es = (pad or {}).get("estop") or {}
    first_bad = next((c for c in es.get("checks") or [] if c.get("ok") is False), None)
    bad_why = f"{first_bad.get('label')}：{first_bad.get('why') or '×'}" if first_bad else None
    many = _many_unconnected(pad)
    if r is None:
        # Sem controle físico, a parada do controle web usa Espaço ou o botão vermelho superior.
        web = _no_physical_pad(pad)
        web_only = ". No controle web, Espaço e o botão vermelho superior acionam a parada; esta etapa pode ser ignorada" if web else ""
        now = f" ({many} controles pareados, nenhum conectado: conecte um antes do teste)" if many else (f" (não é possível testar agora: {bad_why})" if bad_why else "")
        ask = ESTOP_ASK["web"] if web else (ESTOP_ASK["bad"].replace("{why}", bad_why) if es.get("state") == "bad" and bad_why
                                            else ESTOP_ASK["never"])
        return _row("estop", "no", "O botão Select ainda não foi testado" + now + web_only, actions=[("estop", "Testar parada de emergência")], ask=ask)
    mac, _ = _current_pad(pad)
    build = (inp.get("bus") or {}).get("build")
    if mac is None or not build:
        miss = (f"{many} controles pareados, nenhum conectado: conecte um antes do teste" if many else "não foi possível identificar o controle conectado") if mac is None \
            else "não foi possível ler a versão do programa principal"
        return _row("estop", "unk", f"Teste registrado para {r.get('name') or 'o controle'}, mas não pode ser verificado: {miss}", when=r.get("at"),
                    actions=[("estop", "Testar parada de emergência")])
    if str(r.get("mac") or "").upper() != mac:
        return _row("estop", "todo", "O controle mudou: teste novamente", when=r.get("at"), actions=[("estop", "Testar parada de emergência")], ask=ESTOP_ASK["pad"])
    if r.get("build") != build:
        return _row("estop", "todo", "O programa principal foi atualizado: teste novamente", when=r.get("at"), actions=[("estop", "Testar parada de emergência")],
                    ask=ESTOP_ASK["build"])
    if es.get("state") == "bad":
        return _row("estop", "todo", f"Teste concluído, mas a parada de emergência não funciona: {bad_why}", when=r.get("at"), actions=[("estop", "Ver detalhes")],
                    found=f"A parada de emergência não funciona ({bad_why}); isso não mudará se for {{v}}. Corrija antes de continuar.")
    ms = r.get("ms")
    return _row("estop", "ok", f"{r.get('name') or 'Controle'} testado: {ms} ms entre soltar Select e liberar o torque" if _num(ms)
                else f"{r.get('name') or 'Controle'} testado", when=r.get("at"))


def walk_row(inp, rec, head):
    s = rec.get("stood") if isinstance(rec.get("stood"), dict) else None
    w = rec.get("walked") if isinstance(rec.get("walked"), dict) else None
    go = [("remote", "Abrir controle remoto")]
    if s is None and w is None:
        return _row("walk", "no", "O robô ainda não ficou em pé: segure-o, selecione Ficar em pé, depois Iniciar caminhada e mova o controle esquerdo", actions=go)
    fp = inp.get("fp")
    last = (w if w is not None else s).get("at")
    if fp is None:
        return _row("walk", "unk", ("Ficou em pé e caminhou" if w else "Ficou em pé") + "; calibração indisponível, não é possível verificar se mudou", when=last, actions=go)
    s_ok = s is not None and s.get("fp") == fp
    w_ok = w is not None and w.get("fp") == fp
    if w_ok:                                   # Se caminhou com a calibração atual, também ficou em pé.
        return _row("walk", "ok", "Ficou em pé e caminhou", when=w.get("at"))
    if (s is not None and not s_ok) or w is not None:
        return _row("walk", "todo", "A calibração mudou; ainda não " + ("ficou em pé nem caminhou" if not s_ok else "caminhou"), when=last, actions=go)
    return _row("walk", "todo", "Já ficou em pé, mas ainda não caminhou: selecione Iniciar caminhada e mova o controle esquerdo", when=s.get("at"), actions=go)


def step_fp(key, inp):
    """Retorna se a marcação depende de uma impressão digital e o valor atual; dados indisponíveis retornam None."""
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if key == "servo":
        return True, joints_fp(calib)
    if key == "imu":
        source, mount = mount_of(bus, calib)
        return True, mount_fp(source, (mount or {}).get("quat"))
    if key == "commit":
        return True, inp.get("fp")             # Alterações na calibração invalidam esta marcação.
    if key == "estop":
        mac, _ = _current_pad(inp.get("pad"))
        if mac is None and _no_physical_pad(inp.get("pad")):
            mac = "no-physical-controller"  # O pareamento futuro de um controle físico invalida a marcação.
        build = bus.get("build")
        return True, (_hash([mac, build]) if mac and build else None)
    if key == "walk":
        return True, inp.get("fp")
    return False, None                          # Parear controle não depende de impressão digital.


FP_WHAT = {"servo": "não foi possível ler o arquivo de calibração principal", "imu": "não foi possível ler a orientação da IMU salva pelo programa", "commit": "não foi possível ler a calibração",
           "estop": "não foi possível identificar o controle atual ou a versão do programa", "walk": "não foi possível ler a calibração"}
BOUND = ("servo", "imu", "commit", "estop", "walk")      # Etapas ligadas a uma impressão digital; parear controle não é vinculado.


def _marks(rec, key):
    """Retorna os registros de conclusão e de etapa ignorada; conclusão tem prioridade se ambos existirem."""
    out = {}
    for kind, rk in KINDS.items():
        d = rec.get(rk) if isinstance(rec.get(rk), dict) else {}
        if isinstance(d.get(key), dict):
            out[kind] = d[key]
    return out


def mark_offer(row, bound, fp):
    """Monta as opções de concluir ou ignorar e indica quando é necessária uma segunda confirmação."""
    key = row["key"]
    acks = [k for k in ("found", "hard") if row.get(k)]
    if row["state"] == "unk":
        acks.append("unk")
    if bound and fp is None:
        acks.append("fp")
    if row.get("found"):
        ask = "Confirma {q}? " + row["found"]
    elif row.get("hard"):
        ask = "Confirma {q}? " + row["hard"]
    elif key == "estop" and row.get("ask"):
        ask = row["ask"]
    elif row["state"] == "unk":
        ask = "Confirma {q}? " + UNK_WHY.replace("{text}", row["text"])
    elif key == "estop":
        ask = ESTOP_ASK["never"]
    elif bound and fp is None:
        ask = "Confirma {q}? " + FP_WHY.replace("{what}", FP_WHAT[key])
    else:
        ask = None
    out = {"ack": acks}
    for kind in KINDS:
        out[kind] = {"confirm": ask is not None, "ask": fill(ask, kind)}
    return out


def with_mark(row, inp, rec):
    """Aplica as marcações do usuário, invalida as que ficaram desatualizadas e inclui as opções para etapas sem marcação."""
    key = row["key"]
    if row["state"] == "ok":
        return row
    bound, fp = step_fp(key, inp)
    for kind, m in _marks(rec, key).items():
        ack = m.get("ack") if isinstance(m.get("ack"), list) else []
        if row.get("found") and "found" not in ack:
            row["note"] = f"Anteriormente {MARKED_WORD[kind]}; a marcação não vale após este problema"
            row["void"] = row.get("void", []) + [kind]
            continue
        if row.get("hard") and "hard" not in ack:
            row["note"] = f"Anteriormente {MARKED_WORD[kind]}, mas agora o programa principal informa que esta etapa não foi concluída; a marcação não vale"
            continue
        old = m.get("fp")
        if bound and fp is not None and old is not None and old != fp:
            row = dict(row, state="todo", text=f"{CHANGED_WORD[kind]} {SKIP_CHANGED[key]} mudou: {row['text']}")
            continue
        out = _row(key, "ok" if kind == "done" else "skip", MARKED_TEXT[kind], when=m.get("at"))
        out["note"] = row["text"] if row["state"] != "unk" else None
        out["marked"] = kind
        for k in ("desc", "commit"):                                  # Mantém os detalhes de preparação ao abrir a etapa 3.
            if k in row:
                out[k] = row[k]
        return out
    row["mark"] = mark_offer(row, bound, fp)
    return row


def evaluate(inp, rec):
    """Avalia os dados atuais e os registros e retorna o cartão completo para a página."""
    head = header_of(inp)
    rows = [servo_row(inp, rec, head), imu_row(inp, rec, head), commit_row(inp, rec, head),
            pad_row(inp, rec, head), estop_row(inp, rec, head), walk_row(inp, rec, head)]
    rows = [with_mark(r, inp, rec) for r in rows]
    nxt = next((r["key"] for r in rows if r["state"] in ("todo", "no")), None)
    return {"header": head, "rows": rows, "next": nxt, "all_done": all(r["state"] in ("ok", "skip") for r in rows),
            "skipped_n": sum(1 for r in rows if r["state"] == "skip"),
            "marked_n": sum(1 for r in rows if r.get("marked") == "done"), "frozen": False}


# ---------------- Validação item por item dos registros ----------------

def _opt(x, *types):
    return x is None or (isinstance(x, types) and not isinstance(x, bool))


def _at(d):
    return _opt(d.get("at"), int, float)


CHECKS = {
    "confirm_servo": lambda d: _at(d) and isinstance(d.get("fp"), str),
    "servo_studio": lambda d: _at(d) and isinstance(d.get("fp"), str) and _opt(d.get("src"), str),
    "imu_check": lambda d: (_at(d) and _opt(d.get("source"), str) and isinstance(d.get("mount_fp"), str)
                            and _num(d.get("diff_deg")) and _opt(d.get("tilt_deg"), int, float) and isinstance(d.get("ok"), bool)),
    "estop": lambda d: (_at(d) and _opt(d.get("ms"), int, float) and _opt(d.get("mac"), str) and _opt(d.get("name"), str)
                        and _opt(d.get("build"), str)),
    "stood": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
    "walked": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
}


def clean_records(data):
    """Retorna os registros válidos e os itens descartados; preserva chaves desconhecidas de versões futuras."""
    out, bad = {}, []
    for k, v in data.items():
        if k == "v":
            continue
        if k == "pads_seen":
            if isinstance(v, dict):
                out[k] = {str(m): n for m, n in v.items() if isinstance(n, str)}
            else:
                bad.append((k, f"não é um objeto ({type(v).__name__})"))
            continue
        if k in KINDS.values():
            # done.<etapa> e skipped.<etapa>: at deve ser numérico; fp pode ser string ou null; ack é uma lista opcional de strings.
            if not isinstance(v, dict):
                bad.append((k, f"não é um objeto ({type(v).__name__})"))
                continue
            good = {}
            for step, e in v.items():
                if (step in ORDER and isinstance(e, dict) and _num(e.get("at")) and _opt(e.get("by"), str)
                        and _opt(e.get("fp"), str)
                        and (e.get("ack") is None or (isinstance(e.get("ack"), list)
                                                      and all(isinstance(a, str) for a in e["ack"])))):
                    good[step] = e
                else:
                    bad.append((f"{k}.{step}", json.dumps(e, ensure_ascii=False, default=str)[:120]))
            out[k] = good
            continue
        chk = CHECKS.get(k)
        if chk is None:
            out[k] = v
            continue
        try:
            ok = isinstance(v, dict) and bool(chk(v))
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            out[k] = v
        else:
            bad.append((k, json.dumps(v, ensure_ascii=False, default=str)[:120]))
    return out, bad


def error_view(why):
    """Monta o cartão de erro para todas as etapas."""
    rows = [_row(k, "unk", f"Erro ao avaliar esta etapa no Studio: {why}") for k in ORDER]
    return {"header": {"ok": False, "kind": "error", "text": "Erro ao avaliar a lista (consulte as linhas Sistema do log)", "raw": why},
            "rows": rows, "next": None, "all_done": False, "skipped_n": 0, "marked_n": 0, "frozen": False}


# ---------------- Gerenciador da lista ----------------

class Onboarding:
    def __init__(self, state_dir, log, clock=time.monotonic, wall=time.time):
        self.state_dir, self.log = state_dir, log
        self.clock, self.wall = clock, wall
        self._lk = threading.Lock()
        self._save_lk = threading.Lock()      # Serializa gravações para evitar que um registro antigo substitua um novo.
        self.rec = {}
        self._dirty = False
        self._view = None
        self._stand_since = None
        self._walk_acc = 0.0
        self._walk_last = None
        self._studio = {"ids": set(), "time": None}
        self._studio_at = -1e9
        self._studio_mtime = None             # mtime da pasta servo-calib; relê os arquivos quando houver alteração.
        self._eval_err = None                 # Motivo do último erro de avaliação; registra cada erro uma vez.
        self._servo = None                    # Sessão de servos mais recente.
        self.commit_service = None            # CommitService conectado pelo app; fornece a preparação da etapa 3.
        self.battery_shutdown = None          # Valor de battery_empty_shutdown na configuração do robotd, se disponível.
        self._cfg_at = -1e9
        self.robotd_configs = ROBOTD_CONFIGS
        self.cpu_hot = False                  # Estado do aviso de temperatura com histerese.
        self.board = None                     # Temperatura lida pelo Studio quando o robotd não informa.
        self._board_ok = os.path.isdir(THERMAL_ROOT)
        self.load()

    # ---- Arquivo de estado ----

    def path(self):
        return os.path.join(self.state_dir or ".", ONBOARD_FILE)

    def load(self):
        """Carrega os registros; renomeia arquivos inválidos para .bad e continua com uma lista vazia."""
        p = self.path()
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"o valor raiz não é um objeto ({type(data).__name__})")
        except FileNotFoundError:
            self.rec = {}
            return
        except (OSError, ValueError) as e:
            bad = p + ".bad"
            try:
                os.replace(p, bad)
            except OSError:
                bad = None
            self.log.warn("Não foi possível ler o arquivo de registros da lista; iniciando uma lista vazia", cat="Sistema", step=p, raw=f"{type(e).__name__}: {e}",
                          hint=(f"O arquivo inválido foi preservado em {bad}" if bad else "Não foi possível renomear o arquivo; verifique as permissões da pasta state"))
            self.rec = {}
            return
        self.rec, bad = clean_records(data)
        for k, raw in bad:
            self.log.warn(f"Registro inválido da lista em {k}; o item será descartado", cat="Sistema", step=p, raw=raw,
                          hint="O registro pode ter sido editado ou criado por uma versão antiga; faça a etapa novamente para registrá-la")

    def save(self):
        """Grava o arquivo inteiro por meio de um arquivo temporário; erros são registrados no log."""
        with self._save_lk:
            return self._save_locked()

    def _save_locked(self):
        with self._lk:
            if not self._dirty:
                return False
            data = dict(self.rec, v=1)
            self._dirty = False
        d = self.state_dir or "."
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".onboarding-", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path())
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            with self._lk:
                self._dirty = True              # Tenta novamente no próximo ciclo.
            self.log.warn("Não foi possível salvar os registros da lista", cat="Sistema", step=self.path(), raw=f"{type(e).__name__}: {e}",
                          hint="A pasta state pode estar cheia ou sem permissão; uma nova tentativa será feita")
            return False
        return True

    def _put(self, key, value, say=None, cat="Sistema"):
        with self._lk:
            if self.rec.get(key) == value:
                return False
            self.rec[key] = value
            self._dirty = True
        if say:
            self.log.info(say, cat=cat, dedup=False)
        return True

    # ---- Registros recebidos de outros módulos ----

    def note_estop(self, r):
        """Registra um teste da parada de emergência em memória. r contém ms, mac, name e build."""
        try:
            rec = {"at": self.wall(), "ms": r.get("ms"), "mac": (str(r["mac"]).upper() if r.get("mac") else None),
                   "name": r.get("name"), "build": r.get("build")}
            self._put("estop", rec, say=f"Lista de integração: parada de emergência testada ({rec['name'] or rec['mac'] or 'controle'}, programa {rec['build']})",
                      cat="Segurança")
            return True
        except Exception:  # noqa: BLE001 - Uma falha ao registrar o teste não deve interromper a thread.
            return False

    def note_imu_check(self, c):
        """Registra a última verificação completa da IMU com o robô em pé, mesmo quando a diferença excede o limite."""
        rec = {"at": self.wall(), "source": c.get("source"), "mount_fp": mount_fp(c.get("source"), c.get("quat")),
               "diff_deg": c.get("diff_deg"), "tilt_deg": c.get("tilt_deg"), "ok": bool(c.get("ok")), "by": c.get("by")}
        if rec["mount_fp"] is None:
            return False
        return self._put("imu_check", rec, say=f"Lista de integração: verificação da IMU registrada (diferença de {rec['diff_deg']}°, {'dentro' if rec['ok'] else 'fora'} do limite)",
                         cat="IMU") or True

    def confirm_servo(self, rd, by=None):
        """Confirma a calibração dos servos quando os 15 valores zero_raw são 2048; retorna um motivo se não puder confirmar."""
        calib = fresh_calib(rd)
        js = _joints(calib)
        if not js:
            return False, "O arquivo de calibração ainda não foi lido após conectar; aguarde alguns segundos e tente novamente"
        if (calib or {}).get("uncalibrated_joints"):
            return False, "O programa principal informa que há juntas não calibradas; calibre-as na página de servos"
        off = [j for j in js if j.get("zero_raw") != 2048 or j.get("calibrated") is False]
        if off:
            return False, f"{len(off)} valores zero_raw diferem de 2048 ou não foram calibrados; calibre-os na página de servos"
        if len(js) < len(SERVO_IDS):
            return False, f"O arquivo do programa principal contém apenas {len(js)} servos"
        fp = joints_fp(calib)
        self._put("confirm_servo", {"at": self.wall(), "fp": fp, "by": by},
                  say=f"Lista de integração: pontos zero verificados ({by or 'página'}; 15 valores são 2048)", cat="Calibração")
        return True, None

    def mark(self, step, kind, rd, pad=None, servo=None, by=None, confirmed=False):
        """Marca uma etapa como concluída ou ignorada e exige confirmação do servidor quando necessário."""
        if step not in ORDER:
            return False, f"Etapa desconhecida: {step}"
        if kind not in KINDS:
            return False, f"Tipo de marcação desconhecido: {kind}"
        if servo is not None:
            self._servo = servo
        inp = self._inputs(rd, pad, servo, self.clock())
        if inp["bench"]:
            return False, "Modo de bancada: a lista não é avaliada nem marcada"
        with self._lk:
            rec = dict(self.rec)
        row = next(r for r in evaluate(inp, rec)["rows"] if r["key"] == step)
        if row.get("marked") == kind:
            return True, "A etapa já foi ignorada" if kind == "skip" else "A etapa já foi marcada como concluída"
        if row.get("marked"):
            return False, "Esta etapa foi ignorada; cancele essa marcação primeiro" if row["marked"] == "skip" else "Esta etapa foi marcada como concluída; cancele essa marcação primeiro"
        if row["state"] == "ok":
            return False, "O Studio já tem um registro de conclusão desta etapa"
        offer = row.get("mark") or {}
        ask = (offer.get(kind) or {}).get("ask")
        if inp["servo_session"] and not ask:
            ask = fill(FROZEN_ASK, kind)
        if ask and confirmed is not True:
            return False, f"Confirmação em duas etapas necessária: {ask}"
        bound, fp = step_fp(step, inp)
        entry = {"at": self.wall(), "by": by, "fp": fp if bound else None}
        if offer.get("ack"):
            entry["ack"] = list(offer["ack"])
        with self._lk:
            mine = dict(self.rec.get(KINDS[kind]) or {})
            theirs = dict(self.rec.get(KINDS[OTHER[kind]]) or {})
        mine[step] = entry
        word = "ignorada" if kind == "skip" else "marcada como concluída"
        self._put(KINDS[kind], mine, cat="Calibração",
                  say=f"Lista de integração: etapa {TITLES[step]} {word} ({by or 'página'})" + (f"; confirmação: {ask}" if ask else ""))
        if theirs.pop(step, None) is not None:
            self._put(KINDS[OTHER[kind]], theirs)
        return True, None

    def skip(self, step, rd, pad=None, servo=None, by=None, confirmed=False):
        return self.mark(step, "skip", rd, pad, servo, by, confirmed)

    def mark_done(self, step, rd, pad=None, servo=None, by=None, confirmed=False):
        return self.mark(step, "done", rd, pad, servo, by, confirmed)

    def unmark(self, step, kind, by=None, servo=None, confirmed=False):
        """Remove uma marcação e reavalia a etapa; durante o ajuste dos servos, requer confirmação adicional."""
        if step not in ORDER:
            return False, f"Etapa desconhecida: {step}"
        if kind not in KINDS:
            return False, f"Tipo de marcação desconhecido: {kind}"
        sv = servo if servo is not None else self._servo
        if sv is not None and getattr(sv, "state", None) in ("open", "opening") and confirmed is not True:
            return False, f"Confirmação em duas etapas necessária: {FROZEN_UNDO}"
        with self._lk:
            mine = dict(self.rec.get(KINDS[kind]) or {})
        if step not in mine:
            return True, "A etapa não estava ignorada" if kind == "skip" else "A etapa não estava marcada como concluída"
        mine.pop(step)
        word = "marcação de ignorada removida" if kind == "skip" else "marcação de conclusão removida"
        self._put(KINDS[kind], mine, say=f"Lista de integração: {word} para {TITLES[step]} ({by or 'página'})", cat="Calibração")
        return True, None

    def unskip(self, step, by=None, servo=None, confirmed=False):
        return self.unmark(step, "skip", by, servo, confirmed)

    def user_mark(self, step):
        """Retorna se o usuário marcou a etapa como concluída ou ignorada, usando o resultado em cache."""
        rows = (self._view or {}).get("rows") or []
        r = next((x for x in rows if isinstance(x, dict) and x.get("key") == step), None)
        return r.get("marked") if r else None

    # ---- Leitura de arquivos em uma thread; tick usa apenas o cache. ----

    def need_board(self, rd):
        """Indica se o Studio deve ler /sys/class/thermal porque o robotd não informou a temperatura."""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        return self._board_ok and not (isinstance(h, dict) and _num(h.get("cpu_temp_c")))

    def io(self, board=False, now=None):
        """Atualiza os dados de calibração e, quando solicitado, a temperatura da placa. Chamado em uma thread."""
        now = self.clock() if now is None else now
        try:
            d = os.path.join(self.state_dir or ".", "servo-calib")
            try:
                mt = os.stat(d).st_mtime
            except OSError:
                mt = None
            if mt != self._studio_mtime or now - self._studio_at >= STUDIO_SCAN_S:
                self._studio = studio_servo_record(self.state_dir)
                self._studio_mtime, self._studio_at = mt, now
        except Exception:  # noqa: BLE001 - Dados indisponíveis são tratados como ausentes.
            pass
        if board:
            try:
                self.board = read_board()
            except Exception:  # noqa: BLE001
                self.board = None
        else:
            self.board = None
        if now - self._cfg_at >= ROBOTD_CFG_S:
            self._cfg_at = now
            self.battery_shutdown = read_battery_shutdown(self.robotd_configs)

    # ---- Executado a cada 0,5 segundo ----

    def _inputs(self, rd, pad, servo, now):
        bus = rd.bus.value if isinstance(rd.bus.value, dict) else None
        calib = fresh_calib(rd)
        pv = None
        if pad is not None:
            try:
                pv = pad.onboard_view()
            except Exception as e:  # noqa: BLE001 - Uma falha do controle não deve ocultar o cartão inteiro.
                pv = {"known": False, "error": f"{type(e).__name__}: {e}", "pads": []}
        return {"bench": getattr(rd, "addr", None) == "none", "present": rd.present, "bus": bus, "calib": calib,
                "servo_session": servo is not None and getattr(servo, "state", None) in ("open", "opening"),
                "pad": pv, "studio_servo": self._studio, "fp": full_fp(bus, calib),
                # starting_since usa o relógio real; o parâmetro now pode ser simulado.
                "commit": self._commit_view(rd, servo), "starting_s": starting_secs(rd, bus)}

    def _commit_view(self, rd, servo):
        """Retorna a preparação da etapa 3; uma falha afeta apenas esta etapa."""
        svc = self.commit_service
        if svc is None:
            return None
        try:
            return svc.view(rd, servo)
        except Exception as e:  # noqa: BLE001
            return {"ready": False, "items": [], "job": None, "error": f"{type(e).__name__}: {e}"}

    def tick(self, rd, pad=None, servo=None, now=None):
        """Reavalia a lista e atualiza registros em memória; retorna True quando há dados para salvar."""
        now = self.clock() if now is None else now
        if servo is not None:
            self._servo = servo
        try:
            self._board_tick(rd)
        except Exception as e:  # noqa: BLE001
            self.log.error("Erro ao atualizar a histerese da temperatura da placa", cat="Sistema", raw=f"{type(e).__name__}: {e}", exc=True)
        try:
            inp = self._inputs(rd, pad, servo, now)
            if not inp["servo_session"]:
                self._track(rd, inp, now)
                self._bind_marks(inp)
            with self._lk:
                rec = dict(self.rec)
            v = evaluate(inp, rec)
            if not inp["servo_session"]:
                self._void_marks(v)
            if inp["servo_session"] and self._view is not None and self._view["header"].get("kind") != "error":
                # Durante o ajuste dos servos, mantenha a lista anterior esmaecida; as ações exigem confirmação adicional.
                v = dict(self._view, header=v["header"], frozen=True,
                         frozen_ask={"done": fill(FROZEN_ASK, "done"), "skip": fill(FROZEN_ASK, "skip"), "undo": FROZEN_UNDO})
            self._eval_err = None
        except Exception as e:  # noqa: BLE001 - Exibe erro em todas as etapas e registra cada erro uma vez.
            why = f"{type(e).__name__}: {e}"[:200]
            if why != self._eval_err:
                self._eval_err = why
                self.log.error("Erro ao avaliar a lista de integração; exibindo estado desconhecido", cat="Sistema", raw=why, exc=True,
                               hint="Exporte o pacote de diagnóstico; o controle de movimento não é afetado")
            v = error_view(why)
        self._view = v
        with self._lk:
            return self._dirty

    def _void_marks(self, v):
        """Remove marcações sem confirmação quando a avaliação atual encontrou um problema."""
        for kind, rk in KINDS.items():
            gone = [r for r in v["rows"] if kind in (r.get("void") or ())]
            if not gone:
                continue
            with self._lk:
                d = dict(self.rec.get(rk) or {})
            for r in gone:
                d.pop(r["key"], None)
            word = "ignorada" if kind == "skip" else "marcada como concluída"
            self._put(rk, d, cat="Calibração",
                      say="Lista de integração: " + "; ".join(f"marcação {word} para {r['title']} invalidada ({fill(r['found'], kind)})" for r in gone))

    def _bind_marks(self, inp):
        """Vincula a impressão digital atual às marcações criadas enquanto os dados estavam indisponíveis."""
        for kind, rk in KINDS.items():
            with self._lk:
                d = dict(self.rec.get(rk) or {}) if isinstance(self.rec.get(rk), dict) else {}
            named = []
            for step, e in list(d.items()):
                if step not in BOUND or not isinstance(e, dict) or e.get("fp") is not None:
                    continue
                _bound, fp = step_fp(step, inp)
                if fp is not None:
                    d[step] = dict(e, fp=fp)
                    named.append(TITLES[step])
            if named:
                word = "ignorada" if kind == "skip" else "marcada como concluída"
                self._put(rk, d, cat="Calibração", say=f"Lista de integração: impressão digital vinculada à etapa {'; '.join(named)} ({word})")

    def _track(self, rd, inp, now):
        """Registra quando o robô ficou em pé, caminhou ou pareou um controle."""
        bus = inp["bus"] or {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # A idade dos dados usa o relógio monotônico; as durações de postura e caminhada usam now.
        pa, sa = rd.policies.age(), rd.state.age()
        pol = rd.policies.value if pa is not None and pa <= MAX_AGE["policies"] else None
        st = rd.state.value if sa is not None and sa <= MAX_AGE["state"] else None
        pose = posture(rd.present, inp["bus"], pol, st)
        # Não grave nem substitua registros se a impressão digital estiver indisponível; os temporizadores continuam ativos.
        fp = inp["fp"]
        if pose in STAND and native.get("torque_state_confirmed") is True:
            if self._stand_since is None:
                self._stand_since = now
            elif now - self._stand_since >= STOOD_S and fp is not None:
                old = self.rec.get("stood") if isinstance(self.rec.get("stood"), dict) else None
                if old is None or old.get("fp") != fp:
                    self._put("stood", {"at": self.wall(), "fp": fp}, say="Lista de integração: robô ficou em pé", cat="Controle")
        else:
            self._stand_since = None
        if pose == "walking":
            if self._walk_last is not None:
                self._walk_acc += min(now - self._walk_last, 1.0)
            self._walk_last = now
            old = self.rec.get("walked") if isinstance(self.rec.get("walked"), dict) else None
            if self._walk_acc >= WALKED_S and fp is not None and (old is None or old.get("fp") != fp):
                self._walk_acc = 0.0
                self._put("walked", {"at": self.wall(), "fp": fp}, say="Lista de integração: robô caminhou", cat="Controle")
        else:
            self._walk_last = None
        # Registre a impressão digital dos servos quando os 15 pontos zero no arquivo principal forem 2048.
        stu = inp["studio_servo"] or {}
        js = _joints(inp["calib"])
        jfp = joints_fp(inp["calib"])
        if set(SERVO_IDS) <= set(stu.get("ids") or ()) and js and jfp and all(j.get("zero_raw") == 2048 for j in js):
            ss = self.rec.get("servo_studio") if isinstance(self.rec.get("servo_studio"), dict) else None
            if ss is None or ss.get("src") != stu.get("time"):
                self._put("servo_studio", {"at": self.wall(), "fp": jfp, "src": stu.get("time")},
                          say="Lista de integração: calibração dos servos corresponde ao arquivo principal (15 valores em 2048)", cat="Calibração")
        pv = inp["pad"] or {}
        seen = dict(self.rec.get("pads_seen") or {}) if isinstance(self.rec.get("pads_seen"), dict) else {}
        changed = False
        for p in pv.get("pads") or []:
            if isinstance(p, dict) and p.get("paired") and p.get("mac") and seen.get(str(p["mac"]).upper()) != p.get("name"):
                seen[str(p["mac"]).upper()] = p.get("name") or p.get("mac")
                changed = True
        if changed:
            self._put("pads_seen", seen)

    def _board_tick(self, rd):
        """Atualiza o aviso de temperatura com histerese; usa a leitura local se o robotd não informar."""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        c = (h or {}).get("cpu_temp_c") if isinstance(h, dict) else None
        if not _num(c):
            c = (self.board or {}).get("c") if isinstance(self.board, dict) else None
        if not _num(c):
            self.cpu_hot = False
        elif c >= CPU_WARN_C:
            self.cpu_hot = True
        elif c < CPU_CLEAR_C:
            self.cpu_hot = False

    def view(self):
        return self._view
