"""Strict, versioned intent recordings. This module never talks to the robot."""
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading

from .pad_combo import Refused, SOUNDS

MAX_SECONDS, MAX_EVENTS, MAX_BYTES, MAX_RECORDINGS = 60., 6000, 1024 * 1024, 20
ID = re.compile(r"[a-f0-9]{32}\Z")
HASH = re.compile(r"[a-f0-9]{64}\Z")
HEAD_ZERO = {"neck_pitch": 0., "head_pitch": 0., "head_yaw": 0., "head_roll": 0.}
CLEANUP = (("robot.move", {"vx": 0., "vy": 0., "vyaw": 0.}), ("robot.head", HEAD_ZERO),
           ("robot.pose", {"active": False}), ("robot.mouth", {"open": 0.}),
           ("robot.sound", {"tag": "wheee", "hold": False}))


def number(value, lo, hi):
    # Compare integer bounds before float conversion: hostile JSON integers can be enormous.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi or not math.isfinite(value):
        raise Refused("O registro de movimento contém um número fora do limite ou não finito.")
    return value


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 32 or any(ord(c) < 32 for c in value):
        raise Refused("O nome deve ter de 1 a 32 caracteres.")
    return value.strip()


def validate_event(raw):
    if not isinstance(raw, dict) or set(raw) != {"t", "method", "params"}:
        raise Refused("Campos do evento de movimento inválidos.")
    number(raw["t"], 0, MAX_SECONDS)
    method, p = raw["method"], raw["params"]
    if not isinstance(p, dict):
        raise Refused("Os parâmetros do movimento devem ser um objeto.")
    if method == "studio.posture":
        if set(p) != {"target"} or p["target"] not in ("sit", "stand"):
            raise Refused("Eventos de sentar/levantar só podem ter o destino sit ou stand.")
        return raw
    if method == "robot.move":
        bounds = {"vx": (-.6, .6), "vy": (-.6, .6), "vyaw": (-3., 3.)}
    elif method == "robot.head":
        bounds = {k: (-2.5, 2.5) for k in HEAD_ZERO}
    elif method == "robot.pose":
        if set(p) == {"active"} and p["active"] is False:
            return raw
        if p.get("active") is not True:
            raise Refused("O modo do corpo deve especificar active explicitamente.")
        bounds = {"z": (-.025, .010), "roll": (-.26, .26), "pitch": (-.26, .26)}
    elif method == "robot.mouth":
        bounds = {"open": (0, 1)}
    elif method == "robot.sound":
        if isinstance(p.get("tag"), str) and p["tag"] in SOUNDS and set(p) == {"tag"}:
            return raw
        if p.get("tag") == "wheee" and set(p) == {"tag", "hold"} and isinstance(p["hold"], bool):
            return raw
        raise Refused("Evento de áudio desconhecido.")
    else:
        # Skills need a verified completion/cancellation API before they can be recorded.
        raise Refused("Evento de movimento desconhecido; habilidades do modelo ainda não têm estado de conclusão.")
    if set(p) != set(bounds) | ({"active"} if method == "robot.pose" else set()):
        raise Refused("Campos dos parâmetros do movimento inválidos.")
    for key, (lo, hi) in bounds.items():
        number(p[key], lo, hi)
    return raw


def validate_clip(raw):
    keys = {"version", "id", "name", "created", "duration_s", "fingerprint", "events"}
    if not isinstance(raw, dict) or set(raw) != keys or type(raw["version"]) is not int or raw["version"] not in (1, 2):
        raise Refused("Versão ou campos do registro de movimento inválidos.")
    if not isinstance(raw["id"], str) or not ID.fullmatch(raw["id"]):
        raise Refused("Identificador do registro de movimento inválido.")
    if not isinstance(raw["fingerprint"], str) or not HASH.fullmatch(raw["fingerprint"]):
        raise Refused("O registro de movimento não contém as impressões digitais do modelo e da configuração.")
    name(raw["name"])
    if not isinstance(raw["created"], str) or not 1 <= len(raw["created"]) <= 40:
        raise Refused("Horário de criação inválido.")
    duration = number(raw["duration_s"], 0, MAX_SECONDS)
    events = raw["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        raise Refused("Número de eventos de movimento inválido (máximo de 6.000).")
    previous = 0.
    for event in events:
        validate_event(event)
        if raw["version"] == 1 and event["method"] == "studio.posture":
            raise Refused("Eventos de sentar/levantar exigem um registro de movimento v2.")
        if event["t"] < previous or event["t"] > duration:
            raise Refused("Os horários dos eventos estão fora de ordem ou excedem a duração.")
        previous = event["t"]
    try:
        payload = json.dumps(raw, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise Refused("Não foi possível codificar o registro de movimento.") from None
    if len(payload) > MAX_BYTES:
        raise Refused("O registro de movimento excede 1 MiB.")
    return copy.deepcopy(raw)


def _unique_pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate JSON key")
        out[k] = v
    return out


class MotionStore:
    def __init__(self, state_dir, log=None):
        self.folder = Path(state_dir) / "motion-recordings" if state_dir else None
        self._lk, self._clips = threading.Lock(), {}
        self.skipped = 0
        if self.folder is None or not self.folder.is_dir():
            return
        for path in sorted(self.folder.glob("*.json")):
            try:
                if not ID.fullmatch(path.stem) or path.stat().st_size > MAX_BYTES:
                    raise Refused("Nome ou tamanho do arquivo inválido.")
                with path.open("r", encoding="utf-8") as f:
                    clip = validate_clip(json.load(f, object_pairs_hook=_unique_pairs))
                if path.stem != clip["id"]:
                    raise Refused("O nome do arquivo não corresponde ao identificador do registro.")
                if len(self._clips) < MAX_RECORDINGS:
                    self._clips[clip["id"]] = clip
            except (OSError, ValueError, Refused, RecursionError) as e:
                self.skipped += 1
                if log:
                log.warn("Registro de movimento web corrompido ignorado", cat="Controle", step=str(path), raw=str(e)[:200])

    def summaries(self):
        with self._lk:
            return [{"id": c["id"], "name": c["name"], "duration_s": c["duration_s"], "events": len(c["events"])}
                    for c in self._clips.values()]

    def get(self, cid):
        with self._lk:
            if not isinstance(cid, str) or cid not in self._clips:
                raise Refused("Registro de movimento não encontrado.")
            return copy.deepcopy(self._clips[cid])

    def _write(self, clip):
        if self.folder is None:
            raise Refused("Este robô não tem um diretório state configurado; não é possível salvar.")
        tmp = None
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".motion-", dir=self.folder)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clip, f, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.folder / (clip["id"] + ".json"))
        except OSError as e:
            raise Refused(f"Não foi possível salvar o registro de movimento: {e}") from None
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def save(self, raw):
        clip = validate_clip(raw)
        with self._lk:
            if clip["id"] not in self._clips and len(self._clips) >= MAX_RECORDINGS:
                raise Refused("É possível salvar no máximo 20 registros de movimento. Exclua um registro primeiro.")
            self._write(clip)
            self._clips[clip["id"]] = clip

    def rename(self, cid, new_name):
        clip = self.get(cid)
        clip["name"] = name(new_name)
        self.save(clip)

    def delete(self, cid):
        with self._lk:
            if not isinstance(cid, str) or cid not in self._clips:
                raise Refused("Registro de movimento não encontrado.")
            try:
                (self.folder / (cid + ".json")).unlink(missing_ok=True)
            except OSError as e:
                raise Refused(f"Não foi possível excluir o registro de movimento: {e}") from None
            del self._clips[cid]
