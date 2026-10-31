"""Grava no programa principal os offsets dos servos e as orientações dos servos e da IMU em um único arquivo de calibração do robotd.

Por que este serviço existe: a calibração central na página dos servos altera apenas a EEPROM do servo; as orientações ficam somente em
servo-directions.json; a orientação da IMU é calculada apenas na interface. O robotd lê outro arquivo,
/etc/robot/feetech-ft5/hd1910-calibration.toml. No modo de movimento, se ele não estiver correto, o robotd fica em waiting_for_bus e o robô não consegue ficar em pé.

Este módulo faz três coisas:
- registra o que foi feito no Studio (servo-centered.json e imu-pending.json no diretório state);
- calcula a “prontidão” e monta o conteúdo a gravar (compartilha o mesmo código de montagem/validação TOML com o assistente root, que mantém uma cópia);
- trata calib.op: preview mostra à interface o que seria gravado; commit chama o assistente (dry_run=False) para gravar de verdade e reiniciar o programa principal.

O assistente é um script root independente e não pode importar o Studio. Por isso, build_calibration / render_calibration /
validate_calibration têm uma cópia idêntica em deploy/microduck-helper;
tests/test_commit.py compara as saídas dos dois lados usando a mesma entrada.
"""
import json
import math
import os
import tempfile
import threading
import time

JOINT_ORDER = (
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
)
JOINT_ID = {
    "left_hip_yaw": 20, "left_hip_roll": 21, "left_hip_pitch": 22, "left_knee": 23, "left_ankle": 24,
    "neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33, "mouth": 34,
    "right_hip_yaw": 10, "right_hip_roll": 11, "right_hip_pitch": 12, "right_knee": 13, "right_ankle": 14,
}
JOINT_IDS = JOINT_ID       # nome antigo (usado por outros módulos/testes do Studio)
# HOME oficial do robotd do fork (DEFAULT_POSITION em deployment.rs), na ordem JOINT_ORDER
HOME_RAD = {
    "left_hip_yaw": 0.0, "left_hip_roll": -0.0873, "left_hip_pitch": -0.4579, "left_knee": -0.0049,
    "left_ankle": 0.453, "neck_pitch": 0.3491, "head_pitch": 0.3491, "head_yaw": 0.0, "head_roll": 0.0,
    "mouth": 0.0, "right_hip_yaw": 0.0, "right_hip_roll": 0.0873, "right_hip_pitch": 0.4579,
    "right_knee": 0.0049, "right_ankle": -0.453,
}
# Limites padrão usados no robô real (graus): a guinada dos quadris esquerdo e direito é espelhada
LIMITS_DEG = {
    "left_hip_yaw": (-25.0, 30.0), "left_hip_roll": (-22.0, 22.0), "left_hip_pitch": (-90.0, 90.0),
    "left_knee": (-90.0, 90.0), "left_ankle": (-70.0, 70.0),
    "neck_pitch": (-90.0, 70.0), "head_pitch": (-90.0, 90.0), "head_yaw": (-170.0, 170.0),
    "head_roll": (-20.0, 20.0), "mouth": (-5.0, 30.0),
    "right_hip_yaw": (-30.0, 25.0), "right_hip_roll": (-22.0, 22.0), "right_hip_pitch": (-90.0, 90.0),
    "right_knee": (-90.0, 90.0), "right_ankle": (-70.0, 70.0),
}
IMU_SOURCES = ("bus", "bno08x", "lsm6dsv16x")
CHIP_CN = {"bus": "Placa do barramento (ID 200)", "bno08x": "BNO085(I²C)", "lsm6dsv16x": "LSM6DSV16X(I²C)"}
DEFAULT_BUS_QUAT = [math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0]     # fork imu.rs: SflpDecoder::DEFAULT_MOUNT
# Se a etapa 2 estiver marcada como concluída/pulada, a orientação no programa principal não estiver confirmada e a IMU ainda não tiver sido calibrada na interface, a etapa 3 grava usando estas “montagens padrão” (tarefa 17, pedido do usuário em 21/10:
# “Eu sempre pulo, mas no final ainda não entra no modo de movimento.”).Para a placa do barramento, usa imu_mount_quat já presente no arquivo (de fábrica, corresponde à montagem oficial acima).
DEFAULT_MOUNTS = {
    "bno08x": [0.5, 0.5, 0.5, 0.5],                                  # fork duck-control/src/trunk_imu.rs: BNO08X_DEFAULT_MOUNT
    # Montagem recomendada para a réplica: eixo x do módulo voltado para baixo e z para a frente (medida no segundo robô em 17/10). O fork fornece um quaternion unitário (“a placa não tem uma orientação superior universalmente reconhecida”), então não o usamos.
    "lsm6dsv16x": [0.7071067811865476, 0.0, 0.7071067811865476, 0.0],
}
DEFAULT_HOW = {"bus": "montagem oficial", "bno08x": "montagem padrão do fork", "lsm6dsv16x": "montagem recomendada para a réplica, módulo com x para baixo e z para a frente"}
TOP_KEYS = ("motion_enabled", "imu_mount_verified", "imu_mount_quat", "imu_bus_protocol", "imu_bus_profile", "current_ma_per_count", "units_verified")
TAU = 2.0 * math.pi

SERVO_CENTERED = "servo-centered.json"
IMU_PENDING = "imu-pending.json"
COMMIT_LAST = "commit-last.json"
COMMIT_WAIT_S = 180.0


class CalibError(Exception):
    """Esta calibração não passou na validação do robotd. A mensagem é exibida diretamente à interface/usuário."""


class Refused(Exception):
    """A operação não pode ser feita agora (preparação incompleta, calibração indisponível ou assistente ausente). O motivo é exibido diretamente à interface."""


# ---------------- Montagem/validação TOML (há uma cópia idêntica no assistente) ----------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _quat(q, what):
    if not isinstance(q, (list, tuple)) or len(q) != 4 or not all(_is_num(x) for x in q):
        raise CalibError(f"{what} deve conter quatro números finitos [w, x, y, z]")
    return [float(x) for x in q]


def normalize_quat(q):
    """Normaliza; rejeita vetor nulo, nan e inf. Aceita erro de até 1e-6, como o robotd."""
    v = _quat(q, "quaternion")
    n = math.sqrt(sum(x * x for x in v))
    if not math.isfinite(n) or n <= 1e-12:
        raise CalibError("O quaternion é um vetor nulo e não pode ser normalizado")
    return [x / n for x in v]


def _num_text(v):
    return repr(float(v))


def _bool_text(v):
    return "true" if v else "false"


def build_calibration(current, joints, imu):
    """Monta uma calibração completa com name/id do arquivo atual e as orientações dos servos e da IMU desta operação.

    current: dicionário do arquivo atual (calibration em calibration-status ou lido por tomllib);
    joints: [{"id": int, "direction": 1|-1}, ...], 15 itens;
    imu: {"source": "bus"|"bno08x"|"lsm6dsv16x", "quat": [w,x,y,z]}.
    """
    if not isinstance(current, dict):
        raise CalibError("O arquivo de calibração atual do programa principal não é um objeto")
    rows = current.get("joints")
    if not isinstance(rows, list):
        raise CalibError("O arquivo de calibração atual do programa principal não contém joints")
    by_name = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise CalibError("Uma articulação no arquivo de calibração atual do programa principal não tem name")
        name = row["name"]
        if name not in JOINT_ID:
            raise CalibError(f"O arquivo de calibração atual do programa principal contém uma articulação desconhecida: {name}")
        if name in by_name:
            raise CalibError(f"{name} aparece duas vezes no arquivo de calibração atual do programa principal")
        by_name[name] = row
    if set(by_name) != set(JOINT_ORDER):
        missing = [n for n in JOINT_ORDER if n not in by_name]
        raise CalibError("O arquivo de calibração atual do programa principal não contém as 15 articulações oficiais" + (f"(faltam {', '.join(missing)})" if missing else ""))

    if not isinstance(joints, list) or len(joints) != 15:
        raise CalibError("joints deve conter exatamente 15 itens {id, direction}")
    dirs = {}
    for row in joints:
        if not isinstance(row, dict) or not _is_int(row.get("id")) or row.get("direction") not in (-1, 1):
            raise CalibError("Cada item de joints deve ser {id: inteiro, direction: 1 ou -1}")
        if row["id"] in dirs:
            raise CalibError(f"O id {row['id']} aparece duas vezes em joints")
        dirs[row["id"]] = row["direction"]
    file_ids = {row.get("id") for row in by_name.values()}
    if set(dirs) != file_ids:
        raise CalibError(f"Os 15 servos desta operação ({sorted(dirs)}) não correspondem aos do arquivo do programa principal ({sorted(file_ids, key=str)})")

    out_joints = []
    for name in JOINT_ORDER:
        src = by_name[name]
        jid = src.get("id")
        if not _is_int(jid):
            raise CalibError(f"O id de {name} não é um inteiro")
        lo, hi = LIMITS_DEG[name]
        out_joints.append({
            "name": name, "id": jid, "zero_raw": 2048, "direction": dirs[jid], "calibrated": True,
            "min_rad": math.radians(lo), "max_rad": math.radians(hi),
        })

    out = {
        "motion_enabled": True,
        "imu_mount_verified": bool(current.get("imu_mount_verified", False)),
        "imu_mount_quat": DEFAULT_BUS_QUAT,
        "current_ma_per_count": float(current.get("current_ma_per_count") or 0.0),
        "units_verified": bool(current.get("units_verified", False)),
        "imu_mounts": {},
        "joints": out_joints,
    }
    raw_bus = current.get("imu_mount_quat")
    if raw_bus is not None:
        out["imu_mount_quat"] = _quat(raw_bus, "imu_mount_quat")
    if "imu_bus_protocol" in current:
        protocol = current["imu_bus_protocol"]
        if protocol not in ("feetech", "dxl2"):
            raise CalibError("imu_bus_protocol deve ser feetech ou dxl2 (gravado após validação pelo programa principal)")
        out["imu_bus_protocol"] = protocol
    if "imu_bus_profile" in current:
        if current["imu_bus_profile"] not in ("legacy", "qinmo"):
            raise CalibError("imu_bus_profile deve ser legacy ou qinmo")
        out["imu_bus_profile"] = current["imu_bus_profile"]

    raw_mounts = current.get("imu_mounts")
    if isinstance(raw_mounts, dict):
        for kind in ("bno08x", "lsm6dsv16x"):
            mount = raw_mounts.get(kind)
            if mount is None:
                continue
            if not isinstance(mount, dict):
                raise CalibError(f"imu_mounts.{kind} não é um objeto")
            out["imu_mounts"][kind] = {"quat": _quat(mount.get("quat"), f"imu_mounts.{kind}.quat"),
                                       "verified": bool(mount.get("verified", False))}

    if not isinstance(imu, dict):
        raise CalibError("imu deve ser um objeto")
    source = imu.get("source")
    if source not in IMU_SOURCES:
        raise CalibError(f"imu.source deve ser bus / bno08x / lsm6dsv16x; valor atual: {source!r}")
    quat = normalize_quat(imu.get("quat"))
    if source == "bus":
        out["imu_mount_quat"], out["imu_mount_verified"] = quat, True
    else:
        out["imu_mounts"][source] = {"quat": quat, "verified": True}
    return out


def _raw_position(zero_raw, radians, direction):
    return float(zero_raw) + float(radians) * float(direction) * 4096.0 / TAU


def validate_calibration(cal, source=None):
    """Replica item a item Calibration::validate do robotd do fork; em caso de erro, lança CalibError indicando a articulação e o campo."""
    if not isinstance(cal, dict):
        raise CalibError("A calibração não é um objeto")
    allowed = set(TOP_KEYS) | {"imu_mounts", "joints"}
    extra = sorted(set(cal) - allowed)
    if extra:
        raise CalibError(f"Há chaves desconhecidas no nível superior: {extra} (o robotd rejeitará o arquivo inteiro)")

    if not isinstance(cal.get("motion_enabled"), bool):
        raise CalibError("motion_enabled deve ser true/false")
    if not isinstance(cal.get("imu_mount_verified"), bool):
        raise CalibError("imu_mount_verified deve ser true/false")
    if "imu_bus_protocol" in cal and cal["imu_bus_protocol"] not in ("feetech", "dxl2"):
        raise CalibError("imu_bus_protocol deve ser feetech ou dxl2")
    if "imu_bus_profile" in cal and cal["imu_bus_profile"] not in ("legacy", "qinmo"):
        raise CalibError("imu_bus_profile deve ser legacy ou qinmo")
    if cal.get("imu_bus_profile") == "qinmo" and cal.get("imu_bus_protocol", "feetech") != "feetech":
        raise CalibError("Qinmo só oferece suporte a Feetech")
    if not _is_num(cal.get("current_ma_per_count")):
        raise CalibError("current_ma_per_count deve ser um número finito")
    if not isinstance(cal.get("units_verified"), bool):
        raise CalibError("units_verified deve ser true/false")

    bus_q = _quat(cal.get("imu_mount_quat"), "imu_mount_quat")
    mounts = cal.get("imu_mounts")
    mounts = mounts if isinstance(mounts, dict) else {}
    if set(mounts) - {"bno08x", "lsm6dsv16x"}:
        raise CalibError(f"imu_mounts contém uma origem desconhecida: {sorted(set(mounts) - {'bno08x', 'lsm6dsv16x'})}")
    checked = [("Placa do barramento", bus_q)]
    for kind in ("bno08x", "lsm6dsv16x"):
        mount = mounts.get(kind)
        if mount is None:
            continue
        if not isinstance(mount, dict):
            raise CalibError(f"imu_mounts.{kind} não é um objeto")
        if not isinstance(mount.get("verified"), bool):
            raise CalibError(f"imu_mounts.{kind}.verified deve ser true/false")
        checked.append((CHIP_CN[kind], _quat(mount.get("quat"), f"imu_mounts.{kind}.quat")))
    for label, q in checked:
        norm = sum(x * x for x in q)
        if not math.isfinite(norm) or abs(norm - 1.0) > 1e-6:
            raise CalibError(f"O quaternion da orientação de montagem de {label} não tem norma unitária (o erro deve ser ≤ 1e-6; atual: {norm - 1.0:+.2e})")

    if cal.get("units_verified") and float(cal["current_ma_per_count"]) <= 0.0:
        raise CalibError("Quando units_verified = true, current_ma_per_count deve ser positivo")

    joints = cal.get("joints")
    if not isinstance(joints, list) or len(joints) != 15:
        raise CalibError("Deve haver exatamente 15 articulações, na ordem oficial")
    seen = set()
    for i, name in enumerate(JOINT_ORDER):
        j = joints[i]
        if not isinstance(j, dict):
            raise CalibError(f"{name} (articulação nº {i + 1}) não é um objeto")
        if j.get("name") != name:
            raise CalibError(f"A articulação nº {i + 1} deve ser {name}; valor atual: {j.get('name')!r} (as 15 articulações devem seguir a ordem oficial)")
        jid = j.get("id")
        if not _is_int(jid) or jid >= 254 or jid == 200:
            raise CalibError(f"{name}: id deve ser um inteiro menor que 254 e não pode ser 200 (placa IMU); valor atual: {jid!r}")
        if jid in seen:
            raise CalibError(f"{name}: id {jid} está duplicado")
        seen.add(jid)
        zero = j.get("zero_raw")
        if not _is_int(zero) or not 0 <= zero <= 4095:
            raise CalibError(f"{name}: zero_raw deve estar entre 0 e 4095; valor atual: {zero!r}")
        direction = j.get("direction")
        if direction not in (-1, 1):
            raise CalibError(f"{name}: direction deve ser 1 ou -1; valor atual: {direction!r}")
        if not isinstance(j.get("calibrated"), bool):
            raise CalibError(f"{name}: calibrated deve ser true/false")
        lo, hi = j.get("min_rad"), j.get("max_rad")
        if lo is None and hi is None:
            if j.get("calibrated"):
                raise CalibError(f"{name}: se calibrated estiver definido, os limites são obrigatórios")
            continue
        if not (_is_num(lo) and _is_num(hi)):
            raise CalibError(f"{name}: os dois limites são obrigatórios e devem ser finitos")
        lo, hi = float(lo), float(hi)
        if not lo < hi:
            raise CalibError(f"{name}: min_rad deve ser menor que max_rad ({lo:g} / {hi:g})")
        for edge, value in (("min", lo), ("max", hi)):
            raw = _raw_position(zero, value, direction)
            if not math.isfinite(raw) or not 0.0 <= round(raw) <= 4095.0:
                raise CalibError(f"{name}: a leitura {raw:.1f} correspondente a {edge}_rad está fora de 0–4095 (cruzaria o limite de uma volta)")
        home = HOME_RAD[name]
        if not lo <= home <= hi:
            raise CalibError(f"{name}: os limites {lo:.4f}–{hi:.4f} não incluem o HOME oficial {home:.4f}")

    if cal.get("motion_enabled"):
        if any(not j.get("calibrated") or j.get("min_rad") is None or j.get("max_rad") is None for j in joints):
            raise CalibError("Quando motion_enabled = true, os 15 servos devem estar calibrados e ter limites definidos")
        if source in ("bno08x", "lsm6dsv16x"):
            mount = mounts.get(source) or {}
            verified = bool(mount.get("verified")) if isinstance(mount, dict) else False
            label = CHIP_CN[source]
        elif source == "bus":
            verified, label = bool(cal.get("imu_mount_verified")), CHIP_CN["bus"]
        else:
            verified = bool(cal.get("imu_mount_verified")) or any(
                isinstance(m, dict) and m.get("verified") for m in mounts.values())
            label = "em uso"
        if not verified:
            raise CalibError(f"Quando motion_enabled = true, a orientação da IMU {label} em uso deve estar verificada")
    return cal


def render_calibration(cal):
    """Gera o TOML: chaves de nível superior → [imu_mounts.*] → [[joints]]. Depois, relê com tomllib para conferir."""
    lines = [
        f"motion_enabled = {_bool_text(cal.get('motion_enabled'))}",
        f"imu_mount_verified = {_bool_text(cal.get('imu_mount_verified'))}",
        "imu_mount_quat = [" + ", ".join(_num_text(x) for x in cal.get("imu_mount_quat") or []) + "]",
        f"current_ma_per_count = {_num_text(cal.get('current_ma_per_count') or 0.0)}",
        f"units_verified = {_bool_text(cal.get('units_verified'))}",
    ]
    if "imu_bus_protocol" in cal:
        if cal["imu_bus_protocol"] not in ("feetech", "dxl2"):
            raise CalibError("imu_bus_protocol deve ser feetech ou dxl2")
        lines.append(f'imu_bus_protocol = "{cal["imu_bus_protocol"]}"')
    if "imu_bus_profile" in cal:
        if cal["imu_bus_profile"] not in ("legacy", "qinmo"):
            raise CalibError("imu_bus_profile deve ser legacy ou qinmo")
        lines.append(f'imu_bus_profile = "{cal["imu_bus_profile"]}"')
    mounts = cal.get("imu_mounts") or {}
    for kind in ("bno08x", "lsm6dsv16x"):
        mount = mounts.get(kind)
        if mount is None:
            continue
        lines += ["", f"[imu_mounts.{kind}]",
                  "quat = [" + ", ".join(_num_text(x) for x in mount.get("quat") or []) + "]",
                  f"verified = {_bool_text(mount.get('verified'))}"]
    for j in cal.get("joints") or []:
        lines += ["", "[[joints]]",
                  f'name = "{j.get("name")}"',
                  f'id = {int(j.get("id"))}',
                  f'zero_raw = {int(j.get("zero_raw"))}',
                  f'direction = {int(j.get("direction"))}',
                  f'calibrated = {_bool_text(j.get("calibrated"))}']
        if j.get("min_rad") is not None:
            lines.append(f'min_rad = {_num_text(j.get("min_rad"))}')
        if j.get("max_rad") is not None:
            lines.append(f'max_rad = {_num_text(j.get("max_rad"))}')
    return "\n".join(lines) + "\n"


def normalized_calibration(cal):
    """Usado para comparar após reler: [imu_mounts] vazio não é gravado e, portanto, a chave não aparece na leitura."""
    out = dict(cal)
    out["imu_mounts"] = dict(cal.get("imu_mounts") or {})
    return out


def same_calibration(a, b):
    """Compara cada item rigorosamente: o TOML grava floats usando repr, então a releitura deve ser idêntica."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same_calibration(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_calibration(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b)
    return a == b


# ---------------- Arquivos de estado do Studio ----------------

def _path(state_dir, name):
    return os.path.join(state_dir or ".", name)


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _write_json(path, obj):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_centered(state_dir, ids, by, at=None):
    """Registra cada servo calibrado com sucesso: {id: {"at": horário local, "by": autor}}."""
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    p = _path(state_dir, SERVO_CENTERED)
    data = _read_json(p) or {}
    now = time.time() if at is None else at
    for jid in ids:
        data[str(jid)] = {"at": now, "by": by or "página dos servos"}
    _write_json(p, data)
    return data


def load_centered(state_dir):
    data = _read_json(_path(state_dir, SERVO_CENTERED)) or {}
    out = {}
    for key, row in data.items():
        try:
            jid = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict) and isinstance(row.get("at"), (int, float)):
            out[jid] = row
    return out


def save_pending(state_dir, source, quat, quality=None, by=None, at=None, *, imu_bus=None):
    """Resultado aprovado da calibração completa em pé da página da IMU; persiste após reiniciar o Studio."""
    if source not in IMU_SOURCES:
        raise Refused(f"Origem de IMU desconhecida: {source!r}")
    row = {"at": time.time() if at is None else at, "by": by, "source": source,
           "quat": normalize_quat(quat), "quality": quality if isinstance(quality, dict) else {}}
    if source == "bus" and imu_bus is not None:
        row["imu_bus"] = imu_bus
    _write_json(_path(state_dir, IMU_PENDING), row)
    return row


def load_pending(state_dir):
    row = _read_json(_path(state_dir, IMU_PENDING))
    if not isinstance(row, dict) or row.get("source") not in IMU_SOURCES:
        return None
    try:
        q = normalize_quat(row.get("quat"))
    except CalibError:
        return None
    out = dict(row)
    out["quat"] = q
    return out


def clear_pending(state_dir):
    try:
        os.unlink(_path(state_dir, IMU_PENDING))
        return True
    except FileNotFoundError:
        return False


def pending_matches(pending, source, bus):
    """Resultados antigos da calibração em pé só são compatíveis com Feetech; novos resultados devem corresponder exatamente à placa do barramento usada na coleta."""
    from .imu import bus_imu_of, configured_profile, imu_bus_metadata
    if not pending or pending.get("source") != source:
        return False
    if source != "bus":
        return True
    if imu_bus_metadata(bus)[2]:
        return False
    if "imu_bus" in pending and imu_bus_metadata({"imu_bus": pending["imu_bus"]})[2]:
        return False
    actual, saved = bus_imu_of(bus), pending.get("imu_bus")
    if saved is None:
        return ((actual is None and not configured_profile(bus)) or
                (actual is not None and actual["protocol"] == "feetech" and actual.get("profile", "legacy") == "legacy"))
    if not isinstance(actual, dict) or not isinstance(saved, dict):
        return False
    return (all(actual.get(key) == saved.get(key) for key in ("protocol", "board", "identity"))
            and actual.get("profile", "legacy") == saved.get("profile", "legacy")
            and saved.get("profile", "legacy") in ("legacy", "qinmo"))


def forget_centered(state_dir, ids):
    """Ao desfazer a calibração central, remove os servos correspondentes de servo-centered.json. Retorna os IDs removidos."""
    p = _path(state_dir, SERVO_CENTERED)
    data = _read_json(p) or {}
    gone = []
    for jid in ids:
        if data.pop(str(int(jid)), None) is not None:
            gone.append(int(jid))
    if gone:
        _write_json(p, data)
    return gone


def _load_directions(state_dir):
    """Servos com orientação explicitamente definida em servo-directions.json (somente estes contam como “orientação do Studio”); vazio se não houver nenhum."""
    try:
        with open(_path(state_dir, "servo-directions.json"), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if str(k).isdigit() and v in (1, -1) and not isinstance(v, bool):
                out[int(k)] = int(v)
    return out


def _file_directions(cal):
    """Orientações atuais {id: ±1} das 15 articulações no arquivo do programa principal; omite as que não puder ler."""
    out = {}
    for j in (cal or {}).get("joints") or []:
        if isinstance(j, dict) and isinstance(j.get("id"), int) and j.get("direction") in (1, -1):
            out[j["id"]] = j["direction"]
    return out


# ---------------- Prontidão / pré-visualização / gravação ----------------

class CommitService:
    def __init__(self, robotd, log, state_dir, simulate=False):
        self.rd, self.log, self.state_dir = robotd, log, state_dir
        self.simulate = simulate
        self.centered, self.pending, self.directions = {}, None, {}
        self._mt = {}
        self.file_calib = None
        self._file_calib_at = -1e9
        self.cal_from_file = False
        self.job = None
        self.onboard = None                    # Lista inicial (conectada pelo app): a prontidão precisa saber se o usuário marcou as etapas 1/2 como “concluída” ou “pular”
        self._writing = threading.Lock()
        self._reload_at = -1e9
        self.reload(force=True)
        self.job = self._job_from_last_result()

    # ---- Arquivos de estado: cacheados por data de modificação (state.summarize chama view a cada quadro; não leia do disco em todo quadro) ----

    def _sig(self, path):
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size, getattr(st, "st_ino", 0))
        except OSError:
            return None

    def reload(self, force=False):
        now = time.monotonic()
        if not force and now - self._reload_at < 1.0:
            return
        self._reload_at = now
        specs = (
            ("centered", SERVO_CENTERED, lambda: load_centered(self.state_dir)),
            ("pending", IMU_PENDING, lambda: load_pending(self.state_dir)),
            ("directions", "servo-directions.json", lambda: _load_directions(self.state_dir)),
        )
        for key, name, fn in specs:
            path = _path(self.state_dir, name)
            sig = self._sig(path)
            if force or self._mt.get(key) != sig:
                self._mt[key] = sig
                if key == "centered":
                    self.centered = fn()
                elif key == "pending":
                    self.pending = fn()
                else:
                    self.directions = fn()

    def _calibration(self, rd=None):
        """Prefere calibration-status lido após este hello; se indisponível (modo de movimento preso em waiting_for_bus),
        chama o assistente calib-read para ler o arquivo. Como alternativa, consulta o arquivo no máximo a cada 5 s; a interface não executa sudo a cada quadro."""
        from .robotd import fresh_calib
        from . import helper
        rd = rd or self.rd
        calib = fresh_calib(rd)
        if isinstance(calib, dict) and isinstance(calib.get("calibration"), dict):
            self.cal_from_file = False
            return calib.get("calibration"), calib
        if isinstance(calib, dict) and isinstance(calib.get("joints"), list):
            self.cal_from_file = False
            return calib, calib
        now = time.monotonic()
        if self.file_calib is None or now - self._file_calib_at >= 5.0:
            self._file_calib_at = now
            self.file_calib = None
            if helper.available():
                ok, _result, detail = helper.calib_read(by="Prontidão do Studio", timeout=10)
                if ok and isinstance(detail, dict) and isinstance(detail.get("calibration"), dict):
                    self.file_calib = {"calibration": detail["calibration"],
                                       "imu_source": detail.get("imu_source"),
                                       "mode": detail.get("mode"), "path": detail.get("path")}
        if self.file_calib is not None:
            self.cal_from_file = True
            return self.file_calib["calibration"], self.file_calib
        self.cal_from_file = False
        return None, (calib if isinstance(calib, dict) else None)

    def _current_bus(self, rd=None):
        rd = rd or self.rd
        return rd.bus.value if isinstance(rd.bus.value, dict) else {}

    def _mtime(self, name):
        try:
            return os.stat(_path(self.state_dir, name)).st_mtime_ns
        except OSError:
            return None

    def _last_commit(self):
        row = _read_json(_path(self.state_dir, COMMIT_LAST))
        return row if isinstance(row, dict) else None

    def _dirty(self, cal):
        why = []
        if self.pending:
            why.append("Há uma nova calibração de orientação da IMU que ainda não foi gravada")
        last = self._last_commit() or {}
        cm = self._mtime(SERVO_CENTERED)
        if cm is not None and cm > int(last.get("centered_mtime_ns") or -1):
            why.append("O registro de offsets dos servos é mais recente que a última gravação bem-sucedida")
        # Compara somente as orientações definidas explicitamente na página dos servos; as demais são mantidas conforme o arquivo e não contam como alterações
        rows = {j.get("id"): j for j in (cal or {}).get("joints") or [] if isinstance(j, dict)}
        if rows and any(jid in rows and rows[jid].get("direction") != d for jid, d in self.directions.items()):
            why.append("A orientação definida na página dos servos difere do arquivo do programa principal")
        return why

    def _user_mark(self, step):
        """Verifica se o usuário marcou a etapa step da lista inicial (done / skip / None); se a lista não estiver conectada ou falhar, considera sem marcação."""
        ob = self.onboard
        if ob is None:
            return None
        try:
            return ob.user_mark(step)
        except Exception:  # noqa: BLE001 —— A prontidão é calculada a cada quadro; falhas na lista não podem interromper o cálculo.
            return None

    def _default_imu(self, source, mount, cal, mark=None):
        """Se a etapa 2 estiver marcada como “concluída”/“pular”, a orientação da IMU em uso ainda não estiver confirmada no programa principal e não existir imu-pending.json:
        grava a montagem padrão para esse chip e marca como confirmada (tarefa 17). Retorna {source, quat, label, how, mark}; retorna None quando não deve usar o padrão.
        Se houver pending (calibração em pé), usa-o; se a orientação já estiver confirmada, mantém a do programa principal; não tenta adivinhar o chip desconhecido."""
        if self.pending or source not in IMU_SOURCES or (mount or {}).get("verified") is True:
            return None
        if source == "bus" and (cal or {}).get("imu_bus_profile") == "qinmo":
            return None
        mark = self._user_mark("imu") if mark is None else mark
        if mark not in ("done", "skip"):
            return None
        if source == "bus":
            quat = list(DEFAULT_BUS_QUAT)
            raw = (cal or {}).get("imu_mount_quat") if isinstance(cal, dict) else None
            if raw is not None:
                try:
                    quat = normalize_quat(raw)
                except CalibError:
                    pass
        else:
            quat = list(DEFAULT_MOUNTS[source])
        return {"source": source, "quat": quat, "label": CHIP_CN[source], "how": DEFAULT_HOW[source], "mark": mark}

    def readiness(self, rd=None, servo=None):
        from .estop import STARTING_LONG_S, STARTING_PHASES
        from .imu import bus_protocol_mismatch, mount_of
        from .state import JOINT_CN, STILL_STARTING, starting_secs
        self.reload()
        rd = rd or self.rd
        cal, calib = self._calibration(rd)
        cal = cal if isinstance(cal, dict) else {}
        bus = self._current_bus(rd)
        mode = bus.get("mode") if isinstance(bus, dict) else None
        phase = bus.get("phase") if isinstance(bus, dict) else None
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        items = []

        online = rd.present is True and isinstance(bus, dict)
        items.append({"key": "robotd", "label": "Programa principal", "ok": online,
                      "text": "Programa principal online" if online else "O programa principal não está em execução ou ainda não conectou. Aguarde alguns segundos; se o problema persistir, consulte a página de logs para saber por que não iniciou", "action": None})

        sample = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
        servos = sample.get("servos") if isinstance(sample.get("servos"), list) else []
        try:
            age = rd.bus.age()
        except Exception:  # noqa: BLE001
            age = None
        fresh = age is not None and age <= 3.0
        starting_s = starting_secs(rd, bus)
        err = bus.get("error") if isinstance(bus, dict) else None
        if not online:
            mode_ok, mode_text = False, "O modo atual só pode ser determinado após conectar ao programa principal"
        elif mode == "commissioning" and phase in STARTING_PHASES:
            # Relatório de inicialização no modo de calibração (ainda sem primeira leitura bem-sucedida): não significa que last_sample tenha zero servos. O fork antigo pode ficar preso aqui (verificação em hardware real em 20/10)
            mode_ok = False
            if phase == "waiting_for_bus":
                mode_text = "Modo de calibração: o programa principal está aguardando o barramento dos servos (provavelmente os servos estão sem alimentação)" + (f": {err}" if err else "")
            elif starting_s is not None and starting_s >= STARTING_LONG_S:
                mode_text = f"Modo de calibração: o programa principal continua informando “inicializando” (phase={phase}; {starting_s} s decorridos):{STILL_STARTING}"
            else:
                mode_text = f"Modo de calibração: o programa principal ainda está iniciando(phase={phase}): As leituras dos servos estarão disponíveis após a inicialização; aguarde alguns segundos"
        elif mode == "commissioning" and phase == "read_error":
            # O programa iniciou (snapshot em tempo real), mas a leitura dos servos falhou neste ciclo: mostra a mensagem original do programa principal
            mode_ok = False
            cycle_err = bus.get("last_cycle_error")
            mode_text = "Modo de calibração: o programa principal iniciou, mas houve um erro ao ler os servos" + (f": {cycle_err}" if cycle_err else "") + ".Verifique primeiro a alimentação e os cabos dos servos"
        elif mode == "commissioning":
            mode_ok = len(servos) == 15 and fresh
            mode_text = ("Modo de calibração: os 15 servos têm leituras recentes" if mode_ok
                         else f"Modo de calibração, mas last_sample contém somente {len(servos)} servos" +
                              ("" if fresh else ", as leituras estão desatualizadas") + ": Ligue a alimentação dos servos e aguarde alguns segundos")
        elif mode == "motion":
            mode_ok = phase == "control"
            if mode_ok:
                mode_text = "Modo de movimento: barramento aberto"
            else:
                err = bus.get("error") if isinstance(bus, dict) else None
                mode_text = (f"Modo de movimento, mas o programa principal ainda não entrou na etapa de controle (phase={phase or '?'})"
                             + (f": {err}" if err else "")
                             + ".Provavelmente a calibração não passou na validação ou o barramento dos servos não abriu. Verifique a alimentação e siga as instruções da página de logs")
        else:
            mode_ok, mode_text = False, f"Programa principal no modo {mode or '?'}, etapa {phase or '?'}"
        items.append({"key": "mode", "label": "Modo do programa principal", "ok": mode_ok, "text": mode_text,
                      "action": {"do": "robotd", "label": "Abrir a página de logs"} if online and not mode_ok else None,
                      "mode": mode, "phase": phase})

        safe_ok = True
        safe_text = "O robô está andando/em pé; sente-o ou desligue o torque antes de gravar"
        if mode == "motion" and phase == "control":
            if bus.get("policy_enabled") is True or native.get("torque_state_confirmed") is True:
                safe_ok = False
        elif mode == "commissioning" and isinstance(bus.get("hold"), dict):
            # Se o robô estiver em pé com “postura em pé habilitada” no modo de calibração, gravar no programa principal o reiniciará e desativará o torque dos 15 servos de uma vez, fazendo-o cair
            safe_ok = False
            safe_text = "O robô está em pé no modo de calibração (postura habilitada). Primeiro selecione “Desativar torque” na página da IMU ou no topo; segure-o antes de gravar"
        items.append({"key": "safety", "label": "Postura do robô", "ok": safe_ok,
                      "text": "O robô não está andando nem em pé; pode gravar" if safe_ok else safe_text,
                      "action": None})

        missing = [name for name in JOINT_ORDER if JOINT_ID[name] not in self.centered]
        servo_mark = self._user_mark("servo")
        servo_ok = not missing or servo_mark in ("done", "skip")
        if not missing:
            servo_text = "Os offsets dos 15 servos estão registrados em servo-centered.json"
        elif servo_mark:
            # Pedido do usuário em 20/10: os offsets do segundo robô já foram calibrados; não exigir nova calibração. Ao gravar, manter 2048 para os 15 servos mesmo se a etapa 1 foi concluída antes ou pulada.
            servo_text = (("Você marcou a etapa 1 como concluída" if servo_mark == "done" else "Você pulou a etapa 1")
                          + ": grava offset 2048 para os 15 servos (correto somente se os offsets tiverem sido calibrados na página dos servos do Studio)")
        else:
            names = ", ".join(JOINT_CN.get(n, n) for n in missing[:6]) + ("…" if len(missing) > 6 else "")
            servo_text = f"Ainda faltam {len(missing)} servos na calibração central em lote: {names}"
        items.append({"key": "servo", "label": "Offset dos servos", "ok": servo_ok, "text": servo_text,
                      "action": {"do": "servos", "label": "Abrir a página dos servos"} if not servo_ok else None,
                      "missing": missing, "done": 15 - len(missing), "by_mark": servo_mark if missing else None})

        # Orientações a gravar: usa as definidas explicitamente na página dos servos e mantém as demais do arquivo do programa principal (não sobrescreve com o padrão −1)
        file_dirs = _file_directions(cal)
        final = {jid: self.directions.get(jid, file_dirs.get(jid, -1)) for jid in JOINT_ID.values()}
        changed = [{"id": jid, "name": name, "cn": JOINT_CN.get(name, name), "direction": final[jid]}
                   for name, jid in JOINT_ID.items() if final[jid] != -1]
        changed.sort(key=lambda r: JOINT_ORDER.index(r["name"]))
        dir_text = ("Devem ser definidas como +1:  " + ", ".join(f"{r['cn']}" for r in changed) + ": confirme se a orientação está correta"
                    if changed else "Os 15 servos estão em −1")
        if self.directions:
            dir_text += "(usa as orientações da página dos servos quando definidas; mantém as demais do arquivo principal)"
        else:
            dir_text += "(a página dos servos não alterou as orientações; mantém as do arquivo principal)"
        items.append({"key": "directions", "label": "Orientações", "ok": True, "text": dir_text,
                      "action": {"do": "servos", "label": "Conferir orientações"} if changed else None, "changed": changed})

        source, mount = mount_of(bus, calib if isinstance(calib, dict) else {})
        mount = mount if isinstance(mount, dict) else {}
        verified = mount.get("verified") is True
        protocol_changed = bus_protocol_mismatch(bus, calib, source)
        if not source:
            imu_ok, imu_text = False, "O programa principal ainda não informou qual IMU está em uso"
        elif protocol_changed:
            imu_ok, imu_text = False, "O protocolo da IMU do barramento não corresponde à calibração da orientação de montagem. Recalibre na página da IMU e envie para verificação do programa principal"
        elif self.pending and self.pending.get("source") != source:
            imu_ok = False
            imu_text = (f"O chip da IMU foi trocado (em uso: {CHIP_CN.get(source, source)}; "
                        f"calibrado anteriormente: {self.pending.get('source')}). Calibre novamente")
        elif self.pending and not pending_matches(self.pending, source, bus):
            imu_ok, imu_text = False, "A placa do barramento da IMU mudou. Recalibre na página da IMU"
        elif self.pending:
            imu_ok = True
            imu_text = f"Calibração feita na página da IMU ({CHIP_CN.get(source, source)}); a nova orientação será gravada"
        elif verified:
            imu_ok, imu_text = True, f"A orientação da IMU no programa principal já foi confirmada ({CHIP_CN.get(source, source)})"
        elif mode == "commissioning":
            imu_ok, imu_text = False, "Modo de calibração: faça a calibração inicial na página da IMU e envie para verificação do programa principal"
        else:
            imu_ok, imu_text = False, "A orientação de montagem ainda não foi calibrada na página da IMU"
        imu_mark = self._user_mark("imu")
        imu_default = None
        if not imu_ok and imu_mark and not protocol_changed:
            said = "Você marcou a etapa 2 como concluída" if imu_mark == "done" else "Você pulou a etapa 2"
            imu_default = self._default_imu(source, mount, cal, imu_mark)
            if imu_default:
                # Pedido do usuário em 21/10: se a etapa for sempre pulada e o robô não entrar no modo de movimento, usar a montagem padrão e marcá-la como confirmada quando a IMU já tiver sido calibrada.
                imu_ok = True
                imu_text = (f"{said}: grava a montagem padrão da IMU ({imu_default['label']}: {imu_default['how']})."
                            "Se a montagem física for diferente, o robô pode tombar ao ficar em pé. Após gravar, calibre em pé na página da IMU e grave novamente no programa principal")
            else:
                # Se o chip for desconhecido ou a página da IMU tiver registrado outro chip, não é possível gravar usando a montagem padrão
                imu_text = f"{said}, mas não é possível gravar usando a montagem padrão: {imu_text}"
        items.append({"key": "imu", "label": "Orientação da IMU", "ok": imu_ok, "text": imu_text,
                      "action": {"do": "imu", "label": "Abrir a página da IMU"} if not imu_ok else None, "source": source,
                      "default": bool(imu_default)})

        servo_open = servo is not None and getattr(servo, "state", None) in ("open", "opening")
        items.append({"key": "bus", "label": "Barramento dos servos", "ok": not servo_open,
                      "text": "A página dos servos está usando o barramento. Selecione “Devolver ao programa principal” nela." if servo_open else "A página dos servos não está usando o barramento",
                      "action": {"do": "servos", "label": "Abrir a página dos servos"} if servo_open else None})

        why = self._dirty(cal)
        note = ("O programa principal não está usando esta calibração; abaixo estão os dados do arquivo" if self.cal_from_file else None)
        return {"ready": all(i["ok"] for i in items), "items": items, "source": source,
                "imu_default": ({k: imu_default[k] for k in ("source", "label", "how", "quat")} if imu_default else None),
                "pending": bool(self.pending), "centered": len(self.centered),
                "preview_ok": bool(cal.get("joints")), "mode": mode, "phase": phase,
                "from_file": bool(self.cal_from_file), "note": note,
                "dirty": bool(why), "dirty_why": why}

    def view(self, rd=None, servo=None):
        out = self.readiness(rd, servo)
        job = dict(self.job) if isinstance(self.job, dict) else None
        # Após 2 minutos, oculta o progresso de uma gravação bem-sucedida (para não manter expandido o cartão da etapa 3); mantém falhas visíveis até que alguém as examine
        if job and job.get("ok") and job.get("phase") == "done":
            finished = job.get("finished")
            if isinstance(finished, (int, float)) and time.time() - finished > 120:
                job = None
                self.job = None
        out["job"] = job
        out["simulate"] = self.simulate
        return out

    def hold_directions(self, rd=None):
        """Orientações das 15 articulações usadas para “habilitar postura em pé” no modo de calibração (fork hold-home), na ordem JOINT_ORDER; iguais às gravadas no programa principal por _payload
        (usa as orientações definidas na página dos servos e mantém as demais do arquivo principal). A postura em pé corresponde ao HOME do modo de movimento após a gravação."""
        self.reload()
        cal, _calib = self._calibration(rd or self.rd)
        if not isinstance(cal, dict) or not isinstance(cal.get("joints"), list) or len(cal["joints"]) != 15:
            raise Refused("As 15 calibrações do programa principal ainda não foram lidas. Aguarde alguns segundos e tente novamente")
        by_name = {j.get("name"): j for j in cal["joints"] if isinstance(j, dict)}
        out = []
        for name in JOINT_ORDER:
            row = by_name.get(name)
            if not isinstance(row, dict) or not _is_int(row.get("id")):
                raise Refused(f"{name} está inválido no arquivo de calibração do programa principal: não foi possível ler id")
            file_dir = row.get("direction") if row.get("direction") in (1, -1) else -1
            out.append(self.directions.get(row["id"], file_dir))
        return out

    def _payload(self, rd=None):
        from .imu import bus_protocol_mismatch, mount_of
        rd = rd or self.rd
        cal, calib = self._calibration(rd)
        if not isinstance(cal, dict) or not isinstance(cal.get("joints"), list) or len(cal["joints"]) != 15:
            raise Refused("As 15 calibrações do programa principal ainda não foram lidas. Aguarde alguns segundos e tente novamente")
        by_name = {j.get("name"): j for j in cal["joints"] if isinstance(j, dict)}
        joints = []
        for name in JOINT_ORDER:
            row = by_name.get(name)
            if not isinstance(row, dict) or not _is_int(row.get("id")):
                raise Refused(f"{name} está inválido no arquivo de calibração do programa principal: não foi possível ler id")
            file_dir = row.get("direction") if row.get("direction") in (1, -1) else -1
            joints.append({"id": row["id"], "direction": self.directions.get(row["id"], file_dir)})
        bus = self._current_bus(rd)
        source, mount = mount_of(bus, calib if isinstance(calib, dict) else {})
        if bus_protocol_mismatch(bus, calib, source):
            raise Refused("O protocolo da IMU do barramento não corresponde à calibração da orientação de montagem. Recalibre e verifique na página da IMU")
        mount = mount if isinstance(mount, dict) else {}
        if source not in IMU_SOURCES:
            if self.pending and self.pending.get("source") in IMU_SOURCES:
                source = self.pending["source"]
            else:
                raise Refused("O programa principal ainda não informou qual IMU está em uso; aguarde alguns segundos e tente novamente")
        # Seleção da orientação da IMU: calibração em pé da interface (pending) > orientação confirmada no programa principal > montagem padrão quando a etapa 2 foi marcada (tarefa 17) > orientação não confirmada no programa principal
        # (A última opção só aparece na prévia; não é possível gravar enquanto a prontidão não for atendida.)
        dflt = None
        if self.pending:
            if self.pending.get("source") != source:
                raise Refused("O chip da IMU foi trocado; calibre novamente")
            if not pending_matches(self.pending, source, bus):
                raise Refused("A placa do barramento da IMU mudou; calibre novamente")
            quat = self.pending["quat"]
        elif mount.get("verified") is True and mount.get("quat"):
            quat = mount["quat"]
        elif (dflt := self._default_imu(source, mount, cal)) is not None:
            quat = dflt["quat"]
        elif mount.get("quat"):
            quat = mount["quat"]
        else:
            raise Refused("A orientação da IMU ainda não foi lida. Aguarde o programa principal informá-la ou calibre na página da IMU")
        out = {"joints": joints, "imu": {"source": source, "quat": list(quat)}}
        if dflt:
            out["imu_default"] = dflt["how"]          # usado apenas na prévia/log; o campo imu enviado ao assistente continua contendo somente {source, quat}
        return out

    def _summary(self, payload, toml, used_helper):
        from .imu_calib import describe_mount
        from .state import JOINT_CN
        q = payload["imu"]["quat"]
        desc = describe_mount(q)
        rows = []
        for name in JOINT_ORDER:
            jid = JOINT_ID[name]
            row = next((j for j in payload["joints"] if j["id"] == jid), None)
            if row is None:
                continue
            lo, hi = LIMITS_DEG[name]
            rows.append({"name": name, "cn": JOINT_CN.get(name, name), "id": jid, "direction": row["direction"],
                         "min_deg": lo, "max_deg": hi})
        return {"imu": {"source": payload["imu"]["source"], "label": CHIP_CN.get(payload["imu"]["source"]),
                        "text": desc["text"], "off_deg": desc["off_deg"], "quat": list(q),
                        "default": payload.get("imu_default")},
                "joints": rows, "toml": toml, "helper": used_helper,
                "from_file": bool(self.cal_from_file), "note": "O programa principal não está usando esta calibração; abaixo estão os dados do arquivo" if self.cal_from_file else None}

    def preview(self, by=None, rd=None):
        from . import helper
        self.reload(force=True)
        payload = self._payload(rd)
        cal, _ = self._calibration(rd)
        if helper.available():
            ok, result, detail = helper.calib_commit(by or "Studio", payload["joints"], payload["imu"],
                                                     dry_run=True, timeout=90)
            if not ok:
                raise Refused(helper.friendly(result, detail, "calib-commit"))
            toml = (detail or {}).get("toml")
            if not isinstance(toml, str) or not toml.strip():
                raise Refused("O assistente não retornou o conteúdo a gravar")
            return self._summary(payload, toml, True)
        built = build_calibration(cal, payload["joints"], payload["imu"])
        validate_calibration(built, payload["imu"]["source"])
        return self._summary(payload, render_calibration(built), False)

    def _record_success(self, payload):
        row = {"at": time.time(), "directions": {str(j["id"]): j["direction"] for j in payload["joints"]},
               "centered_mtime_ns": self._mtime(SERVO_CENTERED), "imu_source": payload["imu"]["source"],
               "imu_quat": list(payload["imu"]["quat"])}
        try:
            _write_json(_path(self.state_dir, COMMIT_LAST), row)
            self._mt["commit-last"] = self._sig(_path(self.state_dir, COMMIT_LAST))
        except OSError as e:
            self.log.warn("Não foi possível salvar o registro de sucesso (isso não afeta a calibração no programa principal)", cat="Calibração", raw=f"{type(e).__name__}: {e}")

    @staticmethod
    def _job_from_result(row):
        if not isinstance(row, dict) or row.get("verb") != "calib-commit":
            return None
        detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
        ok = row.get("exit") == 0
        return {"phase": "done" if ok else "failed", "ok": ok, "reason": row.get("reason") or detail.get("msg"),
                "started": row.get("wall"), "finished": row.get("wall"), "detail": detail,
                "from_last_result": True, "msg": "Resultado da última gravação" if ok else "A última gravação falhou"}

    def _job_from_last_result(self):
        from . import helper
        return self._job_from_result(helper.last_result())

    def commit(self, by=None, progress=None, rd=None):
        from . import helper
        if not self._writing.acquire(blocking=False):
            return {"ok": False, "reason": "Uma gravação já está em andamento; aguarde sua conclusão", "busy": True}
        started_wall = time.time()
        try:
            by = by or "Studio"
            self.reload(force=True)
            payload = self._payload(rd)
            self.job = {"phase": "running", "msg": "Preparando para gravar", "started": started_wall, "steps": []}

            def say(msg, detail=None):
                self.job["msg"] = msg
                self.job["steps"] = (self.job.get("steps") or [])[-30:] + [{"msg": msg, "at": time.time()}]
                if progress is not None:
                    try:
                        progress(msg, detail)
                    except Exception:  # noqa: BLE001
                        pass

            say("Preparando para gravar")
            if payload.get("imu_default"):
                src = payload["imu"]["source"]
                self.log.info(f"Gravando a IMU com a montagem padrão ({CHIP_CN.get(src, src)}: {payload['imu_default']}): a etapa 2 está marcada como concluída/pulada,"
                              "a orientação não foi confirmada no programa principal e não foi calibrada na página da IMU", cat="Calibração", raw=json.dumps(payload["imu"]),
                              hint="Se a montagem for diferente, o robô pode tombar ao ficar em pé. Após gravar, faça a calibração em pé na página da IMU e grave novamente no programa principal")
            if self.simulate:
                cal, _ = self._calibration(rd)
                built = build_calibration(cal, payload["joints"], payload["imu"])
                validate_calibration(built, payload["imu"]["source"])
                toml = render_calibration(built)
                say("Demonstração no computador: o programa principal não foi gravado de verdade")
                clear_pending(self.state_dir)
                self._record_success(payload)
                self.reload(force=True)
                done = time.time()
                self.job.update({"phase": "done", "ok": True, "reason": "Demonstração no computador: concluída (nenhum arquivo foi realmente alterado)",
                                 "toml": toml, "finished": done})
                self.log.info("Gravação no programa principal (demonstração no computador; sem gravação real)", cat="Calibração", raw=toml[:2000])
                return {"ok": True, "reason": self.job["reason"], "detail": {"simulate": True}}
            if not helper.available():
                reason = "Não é possível gravar no programa principal pelo computador"
                self.job.update({"phase": "failed", "ok": False, "reason": reason, "finished": time.time()})
                self.log.warn(reason, cat="Calibração", hint="A gravação no programa principal deve ser feita no robô (instale o assistente em deploy)")
                return {"ok": False, "reason": reason, "detail": {"rolled_back": False}}

            def on_line(obj):
                step, msg = obj.get("step"), obj.get("msg")
                if step in ("mode", "gate", "backup", "write", "check", "restart", "wait", "rollback", "done") and isinstance(msg, str):
                    if step == "done":
                        return
                    say(msg, {"step": step, "level": obj.get("level")})

            say("Gravando arquivo, alterando modo e reiniciando o programa principal (máximo: 180 s)")
            ok, result, detail = helper.calib_commit(by, payload["joints"], payload["imu"], dry_run=False,
                                                     timeout=COMMIT_WAIT_S, on_line=on_line)
            from_last = False
            if result == "TimeoutExpired":
                last = helper.last_result()
                if isinstance(last, dict) and last.get("verb") == "calib-commit" and (last.get("wall") or 0) >= started_wall - 2.0:
                    d = dict(last.get("detail") or {})
                    d["msg"] = last.get("reason") or d.get("msg")
                    ok, result, detail, from_last = last.get("exit") == 0, last.get("result"), d, True
                else:
                    reason = "O assistente não retornou o resultado final após 180 s; talvez ainda esteja em execução em uma unidade separada. Consulte a página de logs mais tarde ou reabra o Studio"
                    self.job.update({"phase": "failed", "ok": False, "reason": reason, "finished": time.time()})
                    self.log.warn(reason, cat="Calibração", hint="O resultado do assistente é gravado em /run/microduck-helper/last-result.json")
                    return {"ok": False, "reason": reason, "detail": {"rolled_back": False}}
            if ok:
                clear_pending(self.state_dir)
                self._record_success(payload)
                self.reload(force=True)
                reason = "Gravado no programa principal, que entrou no modo de movimento"
                self.job.update({"phase": "done", "ok": True, "reason": reason, "finished": time.time(),
                                 "from_last_result": from_last, "detail": detail or {}})
                self.log.info(reason, cat="Calibração", raw=json.dumps(detail or {}, ensure_ascii=False)[:2000])
                return {"ok": True, "reason": reason, "detail": detail or {}}
            reason = helper.friendly(result, detail, "calib-commit")
            rolled = bool((detail or {}).get("rolled_back"))
            self.job.update({"phase": "failed", "ok": False, "reason": reason, "rolled_back": rolled,
                             "finished": time.time(), "from_last_result": from_last, "detail": detail or {}})
            self.log.error(f"Falha ao gravar no programa principal: {reason}", cat="Calibração", raw=json.dumps(detail or {}, ensure_ascii=False)[:4000],
                           hint="Consulte as últimas linhas do programa principal anexadas pelo assistente no log; o arquivo original foi restaurado" if rolled else "Consulte a mensagem do assistente no log")
            return {"ok": False, "reason": reason, "detail": detail or {}}
        except (Refused, CalibError) as e:
            reason = str(e)
            self.job = {"phase": "failed", "msg": reason, "ok": False, "reason": reason,
                        "started": started_wall, "finished": time.time()}
            self.log.warn(f"A gravação no programa principal não foi iniciada: {reason}", cat="Calibração")
            return {"ok": False, "reason": reason, "detail": {"rolled_back": False}}
        except Exception as e:  # noqa: BLE001
            reason = f"Erro do Studio: {type(e).__name__}: {e}"
            self.job = {"phase": "failed", "msg": reason, "ok": False, "reason": reason,
                        "started": started_wall, "finished": time.time()}
            self.log.error("O Studio encontrou um erro ao gravar no programa principal", cat="Calibração", raw=reason, exc=True,
                           hint="O arquivo original não foi alterado; exporte e envie o pacote de diagnóstico")
            return {"ok": False, "reason": reason, "detail": {"rolled_back": False}}
        finally:
            self._writing.release()
