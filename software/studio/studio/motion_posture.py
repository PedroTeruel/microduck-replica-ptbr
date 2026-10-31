"""Target-aware posture evidence. No RPCs, threads, guessed completion or toggles.

All calls are made under PadOps' state lock. A pending transition outlives its
web session: stopping a webpage cannot cancel robotd's sitstand controller.
"""
import math

from .pad_combo import Refused

STATE_MAX_AGE_S = 1.5
POLICIES_MAX_AGE_S = 6.
WAIT_S = 15.
SAMPLES = 3
# The real HD1910 stationary walk sample has a stable .132 rad knee offset.
# .18 rad allows that measured tracking offset; completion additionally requires
# three distinct phase-correct samples with stable actual and target positions.
ERROR_RAD = .18
STABLE_RAD = .05


def _fresh(at, now, age):
    return isinstance(at, (int, float)) and not isinstance(at, bool) and 0 <= now - at <= age


def phase_evidence(view, now):
    if not _fresh(view.get("state_at"), now, STATE_MAX_AGE_S):
        raise Refused("Sentar e levantar exigem dados atualizados da fase da política e das articulações.")
    if not _fresh(view.get("policies_at"), now, POLICIES_MAX_AGE_S):
        raise Refused("Sentar e levantar exigem uma leitura atualizada da postura.")
    state, pol = view.get("state") or {}, view.get("policies") or {}
    if not isinstance(state, dict) or not isinstance(pol, dict):
        raise Refused("A fase de sentar ou levantar não está clara; não é seguro adivinhar nem repetir a alternância.")
    phase, sitting = state.get("policy"), pol.get("sitting")
    if phase not in ("sit", "rise", "walk", "stand") or type(sitting) is not bool:
        raise Refused("A fase de sentar ou levantar não está clara; não é seguro adivinhar nem repetir a alternância.")
    return view["state_at"], phase, sitting


def evidence(view, now):
    at, phase, sitting = phase_evidence(view, now)
    state = view["state"]
    actual, targets = state.get("joints"), state.get("targets")
    if not (isinstance(actual, list) and isinstance(targets, list) and len(actual) == len(targets) == 15
            and all(type(v) in (int, float) and math.isfinite(v) for v in actual + targets)):
        raise Refused("Faltam leituras completas das posições atuais e desejadas das articulações para sentar ou levantar.")
    return at, phase, sitting, actual, targets


def converged(actual, targets):
    return max(abs(a - b) for a, b in zip(actual, targets)) <= ERROR_RAD


class PostureTracker:
    def __init__(self):
        self.pending = None
        self.error = None

    def begin(self, target, view, now, manual=False):
        previous = self.pending
        if previous and (not manual or previous["target"] == target):
            raise Refused(self.error or "A transição atual ainda pode terminar. Aguarde uma leitura atualizada antes de tentar novamente.")
        if target not in ("sit", "stand"):
            raise Refused("Postura de destino desconhecida.")
        if manual:
            at, phase, sitting = phase_evidence(view, now)
        else:
            at, phase, sitting, actual, targets = evidence(view, now)
        if (phase == "rise" or (phase == "sit") != sitting
                or (not manual and not converged(actual, targets))):
            raise Refused("A postura ainda não está estável ou não está clara; não é possível alternar agora.")
        if previous and (at <= previous["start"] or (target == "sit") == sitting):
            raise Refused("Ainda não há uma leitura atualizada confirmando a postura após a transição anterior; não é possível repetir nem alternar na direção oposta.")
        prior = (previous, self.error) if previous else None
        self.error = None
        token = {"target": target, "start": now, "after": at, "last": at, "count": 0,
                 "previous": None, "accepted": False, "reset": False,
                 "command": (target == "sit") != sitting, "prior": prior}
        self.pending = token
        return token

    def accepted(self, token, now=None):
        if token is not None and self.pending is token:
            token["accepted"] = True
            token.pop("prior", None)
            token["count"], token["previous"] = 0, None
            if now is not None:
                token["last"] = max(token["last"], now)

    def rejected(self, token):
        if token is not None and self.pending is token:
            self.pending, self.error = token.get("prior") or (None, None)

    def uncertain(self, token, reason, now=None):
        if token is not None and self.pending is token:
            self.accepted(token, now)  # only new telemetry can resolve an uncertain reply
            self.error = f"Resultado da transição desconhecido ({reason}); as ações seguintes foram canceladas e a alternância não será repetida."

    def check_timeout(self, now):
        p = self.pending
        if p and now - p["start"] > WAIT_S:
            self.error = self.error or "A transição excedeu 15 segundos; as ações seguintes foram canceladas. Aguarde uma leitura atualizada de conclusão ou pare manualmente antes de voltar a caminhar."
            return self.error
        return None

    def feed(self, view, now):
        p = self.pending
        if p is None:
            return
        bus = view.get("bus") or {}
        live = (view.get("present") is True and not view.get("paused")
                and _fresh(view.get("bus_at"), now, 3.))
        if live and view["bus_at"] > p["start"] and bus.get("policy_enabled") is False:
            p["reset"] = True
        try:
            at, phase, sitting, actual, targets = evidence(view, now)
        except Refused:
            p["count"], p["previous"] = 0, None
            return
        if (live and p["reset"] and bus.get("policy_enabled") is True and bus.get("homed") is True
                and (bus.get("native") or {}).get("torque_state_confirmed") is True
                and phase in ("walk", "stand") and sitting is False and at > p["start"]
                and converged(actual, targets)):
            self.pending, self.error = None, None
            return
        if not (live and bus.get("policy_enabled") is True
                and (bus.get("native") or {}).get("torque_state_confirmed") is True):
            p["count"], p["previous"] = 0, None
            return
        if at <= p["last"] or at <= p["start"]:
            return
        p["last"] = at
        want = phase == "sit" and sitting if p["target"] == "sit" else phase in ("walk", "stand") and not sitting
        previous = p["previous"]
        stable = previous is None or all(abs(a - b) <= STABLE_RAD for a, b in zip(actual + targets, previous))
        p["count"] = (p["count"] + 1 if stable else 1) if want and converged(actual, targets) else 0
        p["previous"] = actual + targets
        if p["accepted"] and p["count"] >= SAMPLES:
            self.pending, self.error = None, None

    def snapshot(self):
        if self.pending is None:
            return None
        target = self.pending["target"]
        label = ("Sentando, aguardando a estabilização das articulações." if target == "sit" else "Levantando, aguardando a retomada da política e a estabilização.")
        if not self.pending["command"]:
            label = "Já está na postura desejada; confirmando leituras estáveis consecutivas."
        return {"target": target, "label": self.error or label}
