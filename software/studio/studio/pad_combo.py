"""“Ações” e “Combinações” da página de controle: dados, validação, leitura e gravação, expansão em uma linha do tempo. São funções puras e não acessam robotd.

Uma combinação tem um nome e várias etapas sequenciais (cada etapa espera a anterior terminar). Cada etapa pertence a um dos tipos abaixo, com parâmetros limitados a faixas seguras:

| Etapa            | Comando enviado ao robotd                         | Referência (repositório oficial microduck/) |
|------------------|---------------------------------------------------|-----------------------------|
| nod   acenar com a cabeça | notificação robot.head, head_pitch oscila a 25 Hz | duck-ipc-proto lib.rs:533, 2058-2065; robotd main.rs:3637-3640 |
| shake negar com a cabeça | notificação robot.head, head_yaw oscila | idem |
| tilt inclinar a cabeça | notificação robot.head, head_roll inclina e volta ao centro | idem |
| mouth abrir a boca | notificação robot.mouth {open}, mantém aberta e fecha | lib.rs:589, 2269-2275; main.rs:3648-3651 |
| chatter falar | notificação robot.mouth abre e fecha repetidamente | idem |
| sound emitir som | solicitação robot.sound {tag} (tem resposta; recusa se não houver som) | lib.rs:590-600, 2094-2140; main.rs:4300-4319 |
| skill habilidade oficial | solicitação robot.do {skill} (tem resposta) | lib.rs:579-581, 2212-2239; main.rs:4219-4255 |
| wait esperar | não envia nada | — |

Não inclui caminhada: combinações não enviam robot.move. Só o joystick move o robô enquanto pressionado; manter uma combinação pressionada executa movimentos no lugar.
Não inclui sit_toggle: altera a postura (sentar/levantar), então há um botão “Sentar” dedicado.

Alguns detalhes sobre cabeça e boca (ao terminar, sempre volta a cabeça ao centro e fecha a boca):
- O destino de robot.head não expira: o último valor enviado permanece (robotd intents.rs:569-588 calcula idade apenas para twist); o padrão é tudo zero (intents.rs:271-274), então voltar ao centro envia zeros uma vez.
- robot.mouth não tem timestamp: se o cliente encerrar, a boca fica aberta (intents.rs:144-146 diz “a mouth left open by a dead client is exactly what the prototype does”); por isso, uma interrupção também envia open=0.
- Os comandos de cabeça viram observações da política, sem gravar diretamente nas servos (lib.rs:2053-2057; padd main.rs:170-174: “the network itself decides how far the head actually goes”); por isso, movimentos da cabeça exigem que a política esteja ativa. Na versão oficial, a boca também só se move com a política ativa (robotd main.rs:3093-3099).
  O fork do robô (R17) move a boca quando já está em postura, inclusive mantendo posição ou sentado (fork robotd main.rs:3897-3909, 4779-4787); o controle físico também envia a boca a cada ciclo, independentemente do modo e da política (fork padd:1351-1363). A terceira revisão (pad-vpad-plan §8 V10) segue o fork: etapas que só movem a boca não exigem política ativa; com torque desligado, o próprio robotd não move a boca, que ainda é fechada ao final.
- Amplitude e velocidade são estimativas ainda não verificadas em hardware: aceno 0,5 rad, negar 0,6 rad, inclinar 0,4 rad. Ajuste observando o robô.
"""
import json
import math
import os
import re
import tempfile

TICK_S = 0.04                 # Notificações da cabeça e da boca a 25 Hz (padd usa 50 Hz: padd main.rs:150-151)
NOD_AMP, SHAKE_AMP, TILT_AMP = 0.5, 0.6, 0.4     # rad; estimativas a verificar em hardware
NOD_PERIOD_S, SHAKE_PERIOD_S = 0.7, 0.8
CHATTER_PERIOD_S = 0.32
MAX_STEPS = 12
MAX_TOTAL_S = 20.0
MAX_USER_COMBOS = 20
NAME_MAX = 16
COMBO_FILE = "pad-combos.json"

# Tags de robot.sound (lib.rs:2094-2113). wheee precisa ser enviado continuamente enquanto pressionado (hold), não como botão de acionamento único.
SOUNDS = {
    "chirp": "Piu (emitir som)",
    "greet": "Cumprimentar",
    "inquire": "Perguntar",
    "coo": "Arrulhar (carinho)",
    "alarm": "Gritar",
    "peck": "Despedir-se",
}

# Nomes das habilidades robot.do → rótulos em português. Consulte as habilidades de robot.policies para ver o que robotd oferece (lib.rs:2338-2346);
# ground_pick e sit_toggle não aparecem nessa lista; verifique se os slots sitstand/ground_pick estão instalados (robotd main.rs:4136-4156).
SKILL_CN = {
    "ground_pick": "Pegar objeto no chão",
    "roulade": "Cambalhota para a frente",
    "kick_left": "Chute com a perna esquerda",
    "kick_right": "Chute com a perna direita",
    "roller_stand": "Levantar no modo de rodas",
    "sit_toggle": "Sentar ↔ levantar",
}
# Duração estimada das habilidades (a próxima etapa da combinação espera): valor padrão em robotd-params lib.rs:1311-1341 (chute 0,5 s, cambalhota 1 s);
# pegar objeto no chão é um movimento por fases, com janela de 2,8 s (receita de treinamento original); espera 2 s para habilidades desconhecidas.
SKILL_HOLD_S = {"kick_left": 0.8, "kick_right": 0.8, "roulade": 1.3, "ground_pick": 3.0}
SKILL_HOLD_DEFAULT_S = 2.0
NO_COMBO_SKILLS = {"sit_toggle"}
SKILL_RE = re.compile(r"^[a-z0-9_]{1,32}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,23}$")

STEP_CN = {"nod": "Acenar", "shake": "Negar", "tilt": "Inclinar a cabeça", "mouth": "Abrir a boca", "chatter": "Falar (abrir e fechar a boca)",
           "sound": "Emitir som", "skill": "Habilidade", "wait": "Esperar"}
# Etapas que exigem política ativa (veja o início do arquivo). Abrir a boca e falar movem apenas a boca e não exigem isso, conforme o fork (revisão V10).
NEEDS_POLICY = {"nod", "shake", "tilt", "skill"}


class Refused(Exception):
    """Esta operação não pode ser executada agora. O motivo é exibido diretamente na página (compartilhado por pad.py e pad_drive.py)."""


# ---------------- Predefinições ----------------

# Ações individuais (pressione e segure na página para executar uma vez; solte para parar).
ACTIONS = [
    {"id": "nod", "name": "Acenar", "steps": [{"do": "nod", "times": 2}]},
    {"id": "shake", "name": "Negar", "steps": [{"do": "shake", "times": 2}]},
    {"id": "tilt", "name": "Inclinar a cabeça", "steps": [{"do": "tilt", "side": "right", "ms": 1200}]},
    {"id": "mouth", "name": "Abrir a boca", "steps": [{"do": "mouth", "open": 0.9, "ms": 900}]},
]
# Combinações predefinidas (combinações personalizadas ficam em pad-combos.json no diretório state; a interface de edição será feita em outra etapa).
BUILTIN_COMBOS = [
    {"id": "hello", "name": "Cumprimentar", "steps": [{"do": "sound", "tag": "greet"}, {"do": "nod", "times": 2},
                                              {"do": "mouth", "open": 0.8, "ms": 500}]},
    {"id": "happy", "name": "Feliz", "steps": [{"do": "sound", "tag": "chirp"}, {"do": "chatter", "times": 3},
                                            {"do": "nod", "times": 1}]},
    {"id": "ask", "name": "Perguntar", "steps": [{"do": "sound", "tag": "inquire"}, {"do": "tilt", "side": "right", "ms": 1000}]},
    {"id": "no", "name": "Não", "steps": [{"do": "shake", "times": 3}, {"do": "sound", "tag": "coo"}]},
    {"id": "kicks", "name": "Chutar para os dois lados", "steps": [{"do": "skill", "name": "kick_left"}, {"do": "wait", "ms": 600},
                                                 {"do": "skill", "name": "kick_right"}]},
]


# ---------------- Validação ----------------

def _num(v, lo, hi, default, what):
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise Refused(f"{what} deve ser um número")
    return max(lo, min(hi, v))


def clean_step(raw):
    """Normaliza uma etapa (descarta campos desconhecidos e limita os valores). Etapas inválidas geram Refused."""
    if not isinstance(raw, dict):
        raise Refused("Cada etapa deve ser um objeto como {\"do\": …}")
    do = raw.get("do")
    if do == "nod" or do == "shake":
        return {"do": do, "times": int(_num(raw.get("times"), 1, 4, 2, "Quantidade de repetições"))}
    if do == "tilt":
        side = raw.get("side", "right")
        if side not in ("left", "right"):
            raise Refused("O lado da inclinação só pode ser left/right")
        return {"do": "tilt", "side": side, "ms": int(_num(raw.get("ms"), 300, 2000, 1000, "Duração da inclinação"))}
    if do == "mouth":
        return {"do": "mouth", "open": round(_num(raw.get("open"), 0.1, 1.0, 0.8, "Abertura da boca"), 2),
                "ms": int(_num(raw.get("ms"), 100, 2000, 600, "Duração com a boca aberta"))}
    if do == "chatter":
        return {"do": "chatter", "times": int(_num(raw.get("times"), 1, 6, 3, "Quantidade de repetições"))}
    if do == "sound":
        tag = raw.get("tag")
        if tag not in SOUNDS:
            raise Refused(f"Som desconhecido: {tag} (opções: {', '.join(SOUNDS)})")
        return {"do": "sound", "tag": tag}
    if do == "skill":
        name = raw.get("name")
        if not isinstance(name, str) or not SKILL_RE.match(name):
            raise Refused("O nome da habilidade só pode conter letras minúsculas, números e sublinhados")
        if name in NO_COMBO_SKILLS:
            raise Refused("Sentar/levantar altera a postura e não pode fazer parte de uma combinação; use o botão “Sentar”")
        return {"do": "skill", "name": name}
    if do == "wait":
        return {"do": "wait", "ms": int(_num(raw.get("ms"), 0, 3000, 300, "Duração da espera"))}
    raise Refused(f"Etapa desconhecida: {do} (opções: {', '.join(STEP_CN)})")


def clean_combo(raw, builtin_ids=()):
    """Normaliza uma combinação enviada pela página. Nome, quantidade de etapas e duração total têm limites; o id não pode coincidir com um predefinido."""
    if not isinstance(raw, dict):
        raise Refused("A combinação deve ser um objeto")
    cid = raw.get("id")
    if not isinstance(cid, str) or not ID_RE.match(cid):
        raise Refused("O identificador pode conter apenas letras minúsculas, números, - e _ (até 24 caracteres)")
    if cid in builtin_ids:
        raise Refused(f"“{cid}” é predefinido; escolha outro identificador")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise Refused("Informe um nome")
    name = name.strip()[:NAME_MAX]
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        raise Refused("Adicione pelo menos uma etapa")
    if len(steps) > MAX_STEPS:
        raise Refused(f"No máximo {MAX_STEPS} etapas")
    clean = [clean_step(s) for s in steps]
    total = duration(clean)
    if total > MAX_TOTAL_S:
        raise Refused(f"A combinação é longa demais: cerca de {total:.0f} s; o máximo é {MAX_TOTAL_S:.0f} s")
    return {"id": cid, "name": name, "steps": clean}


# ---------------- Expansão em linha do tempo ----------------

def step_seconds(step):
    do = step["do"]
    if do == "nod":
        return step["times"] * NOD_PERIOD_S
    if do == "shake":
        return step["times"] * SHAKE_PERIOD_S
    if do in ("tilt", "mouth", "wait"):
        return step["ms"] / 1000
    if do == "chatter":
        return step["times"] * CHATTER_PERIOD_S
    if do == "sound":
        return 0.25            # O som toca por conta própria; espera um instante antes da próxima etapa para parecer que o robô primeiro emitiu o som e depois se moveu.
    if do == "skill":
        return SKILL_HOLD_S.get(step["name"], SKILL_HOLD_DEFAULT_S)
    return 0.0


def duration(steps):
    return sum(step_seconds(s) for s in steps)


def head_at(step, t):
    """Retorna a posição da cabeça no instante t (neck_pitch, head_pitch, head_yaw, head_roll), ou None se a etapa não mover a cabeça."""
    do = step["do"]
    if do == "nod":
        return (0.0, NOD_AMP * math.sin(2 * math.pi * t / NOD_PERIOD_S), 0.0, 0.0)
    if do == "shake":
        return (0.0, 0.0, SHAKE_AMP * math.sin(2 * math.pi * t / SHAKE_PERIOD_S), 0.0)
    if do == "tilt":
        total = step["ms"] / 1000
        ramp = min(0.25, total / 3)
        k = min(1.0, t / ramp) if t < total - ramp else max(0.0, (total - t) / ramp)
        return (0.0, 0.0, 0.0, (TILT_AMP if step["side"] == "right" else -TILT_AMP) * k)
    return None


def mouth_at(step, t):
    """Retorna a abertura da boca (0..1) no instante t, ou None se a etapa não mover a boca."""
    do = step["do"]
    if do == "mouth":
        return step["open"] if t < step["ms"] / 1000 - TICK_S else 0.0
    if do == "chatter":
        return 0.85 if (t % CHATTER_PERIOD_S) < CHATTER_PERIOD_S / 2 else 0.05
    return None


def needs_policy(steps):
    return any(s["do"] in NEEDS_POLICY for s in steps)


def describe(steps):
    """Gera uma frase para a página, por exemplo: acenar 2 vezes → abrir a boca → emitir um som (cumprimentar)."""
    out = []
    for s in steps:
        do = s["do"]
        if do in ("nod", "shake", "chatter"):
            out.append(f"{STEP_CN[do]} {s['times']} vez(es)")
        elif do == "tilt":
            out.append("Inclinar a cabeça" + (" (direita)" if s["side"] == "right" else " (esquerda)"))
        elif do == "mouth":
            out.append("Abrir a boca")
        elif do == "sound":
            out.append(f"Emitir um som ({SOUNDS.get(s['tag'], s['tag'])})")
        elif do == "skill":
            out.append(SKILL_CN.get(s["name"], s["name"]))
        elif do == "wait":
            out.append(f"Esperar {s['ms'] / 1000:g} s")
    return " → ".join(out)


# ---------------- Leitura/gravação (pad-combos.json no diretório state) ----------------

def load_user_combos(state_dir, log=None):
    """Lê as combinações personalizadas do usuário. Se o arquivo estiver inválido ou uma combinação tiver erro, ignora apenas o item e registra no log."""
    if not state_dir:
        return []
    path = os.path.join(state_dir, COMBO_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        if log:
            log.warn("Não foi possível ler as combinações personalizadas; elas serão ignoradas", cat="Controle", step=path, raw=f"{type(e).__name__}: {e}",
                     hint="Se o arquivo estiver inválido, remova-o e crie as combinações novamente")
        return []
    builtin = {c["id"] for c in BUILTIN_COMBOS + ACTIONS}
    out = []
    for raw in (data.get("combos") if isinstance(data, dict) else None) or []:
        try:
            out.append(clean_combo(raw, builtin))
        except Refused as e:
            if log:
                log.warn("Uma combinação inválida foi ignorada", cat="Controle", step=path, raw=f"{raw!r:.200}: {e}")
    return out[:MAX_USER_COMBOS]


def save_user_combos(state_dir, combos):
    """Grava o arquivo inteiro de forma atômica (escreve em um temporário e renomeia para que uma interrupção não danifique o arquivo anterior)."""
    if not state_dir:
        raise Refused("O diretório state não foi configurado para este robô; não é possível salvar")
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, COMBO_FILE)
    fd, tmp = tempfile.mkstemp(prefix=".pad-combos-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "combos": combos}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise Refused(f"Não foi possível salvar: {type(e).__name__}: {e}") from None
    return path
