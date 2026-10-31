"""Estimativa de carga da bateria (versão final de battery-plan.md v2): apenas avisa, sem ações automáticas.

O robô não tem medidor de carga nem ADC. A única medição é a tensão de alimentação informada pelas 15 servos (incrementos de 0,1 V; as servos recebem a tensão direta da bateria).
Por isso, a carga é estimada consultando uma tabela de tensão: a leitura em repouso é precisa; sob carga, a tensão cai e a estimativa fica abaixo do real. Regras definidas nas revisões B-R1…B-R15 e na decisão do usuário de 10-18:

    Uma leitura por segundo: entre as leituras novas de 3,0–9,5 V, descarta as 3 maiores e as 3 menores e calcula a média (com menos de 9, usa a mediana; com menos de 5, ignora o segundo)
    Três estados: rest = torque desligado · light = torque ligado sem movimento (mantendo a postura, em pé ou sentado) · heavy = andando, fazendo movimentos ou caído
    Período de baixo esforço: rest ou light por pelo menos 30 s; calcula a mediana dos últimos 30 s e guarda uma “leitura de baixo esforço”
    Estimativa: maior leitura de baixo esforço dos últimos 5 min (o momento de menor esforço), com calibração, dividida por 2 e consultada na tabela;
                 se o robô não parar por 5 min, consulta a mediana dos últimos 30 s e informa que a estimativa aproximada em movimento pode ficar abaixo do real (no máximo, gera aviso amarelo)
    Inicialização: ao ligar, reiniciar o Studio ou ficar mais de 10 s sem tensão, mostra “estimando” por 30 s, sem avisos amarelos ou vermelhos
    Exibição: número inteiro; variações menores que 2% em relação ao último valor não alteram a exibição (zona morta)
    Avisos: a condição precisa persistir por 60 s para o aviso aparecer; para removê-lo, a carga deve ficar 3% acima do limite por 60 s;
             limite sob carga: mediana dos últimos 10 s (após calibração) abaixo de 6,9 V por 30 s gera o aviso mais destacado; só é removido após tensão acima de 7,0 V por 60 s

Somente cálculos: sem rede, barramento ou threads; o horário é recebido de fora (os testes podem avançá-lo). O chamador registra os eventos retornados por feed() usando log_events.
Este módulo também lê e grava o arquivo de configurações de forma atômica; arquivos inválidos são renomeados para .bad, os valores padrão são usados e um aviso é registrado.
"""
import json
import math
import os
import tempfile
from collections import deque

LOG_CAT = "Bateria"

# Tensão em circuito aberto em repouso de uma bateria 18650 de íons de lítio 2S (NP-F550 etc.) → carga. Compromisso entre curvas comuns de 18650, com formato próximo ao de cobalto-lítio:
# Células ternárias têm mais carga para a mesma tensão; por isso, esta tabela é conservadora (indica menos que o real), com erro de cerca de ±15% (battery-plan.md §1.1, revisão B-R5).
OCV_TABLE = ((4.20, 100), (4.15, 95), (4.10, 89), (4.05, 83), (4.00, 77), (3.95, 70), (3.90, 63), (3.85, 55),
             (3.80, 46), (3.75, 37), (3.70, 28), (3.65, 19), (3.60, 12), (3.55, 8), (3.50, 5), (3.40, 2),
             (3.30, 1), (3.00, 0))
CELLS = 2                       # HD-1910 chega a 8,4 V: só pode usar 2S
V_MIN, V_MAX = 3.0, 9.5         # Leituras de uma servo fora desta faixa são consideradas ausentes
RD_EMPTY_V, RD_FULL_V = 6.6, 8.2    # Escala linear do robotd (fork duck-control/src/model.rs:118-137), usada apenas para comparação

ESTIMATING_S = 30       # Nos primeiros 30 s, mostra apenas “estimando” (B-R2)
CALM_S = 30             # Duração mínima do período de baixo esforço (B-R4: de 60 para 30)
CALM_WINDOW_S = 300     # “Momento de menor esforço nos últimos 5 min”
LOAD_ROUGH_S = 30       # Sem período de baixo esforço, usa a mediana dos últimos 30 s para a estimativa aproximada
GAP_S = 10.0            # Sem tensão em nenhuma das 15 servos por mais de 10 s → reinicia a estimativa (B-R4)
RUN_GAP_S = 10.0        # Uma lacuna maior que este valor interrompe o período de baixo esforço
KEEP_S = CALM_WINDOW_S + 60
WARN_HOLD_S = 60        # Avisos amarelo/vermelho: precisam persistir por 60 s para aparecer ou serem removidos
HYST_PCT = 3
LOW_MED_S = 10          # O limite sob carga usa a mediana dos últimos 10 s
LOW_HOLD_S = 30         # Limite sob carga: precisa persistir por 30 s para gerar aviso
LOW_CLEAR_HOLD_S = 60   # Para remover, precisa ficar 0,1 V acima do limite por 60 s
LOW_CLEAR_V = 0.1
DEADBAND_PCT = 2
GLITCH_V = 1.0          # Registra quando a leitura de um segundo fica mais de 1,0 V abaixo da mediana dos últimos 60 s (distingue queda real de falha de leitura, B-R4).
                        # Não usar os 0,5 V sugeridos na revisão: durante a caminhada do robô nº 1, quedas de 0,5–0,8 V em relação à mediana são comuns (12 vezes no registro de 10-12 às 15:32) e representam carga real.
GLITCH_EVERY_S = 60     # Registra no máximo uma vez por minuto
JUMP_PCT = 10           # Se a estimativa subir mais de 10% em relação à anterior, registra possível troca ou recarga da bateria

# Rótulos de policy em robot.state que indicam ausência de movimento ativo (fork robotd main.rs:3706-3720, control.rs:592)
CALM_LABELS = {"held", "walk", "stand", "homing", "sit"}
CLS_CN = {"rest": "Sem torque", "light": "Em pé / sentado", "heavy": "Andando / em movimento"}

MAINTENANCE = "Recarregue logo após descarregar; para guardar por muito tempo, deixe com meia carga (cerca de 7,4–7,6 V)"
WARN_ONLY = "Apenas aviso: o robô não para sozinho quando a bateria acaba. Ao terminar, desligue a alimentação e desconecte a bateria (mesmo sem torque, ela continua consumindo energia)"


# ---------------- Consulta à tabela ----------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def soc_from_cell(vc):
    """Converte a tensão por célula em carga (0–100%, ponto flutuante), com interpolação linear entre pontos e limites nas extremidades."""
    if not _num(vc):
        return None
    if vc >= OCV_TABLE[0][0]:
        return 100.0
    for (hi_v, hi_p), (lo_v, lo_p) in zip(OCV_TABLE, OCV_TABLE[1:]):
        if lo_v <= vc <= hi_v:
            return lo_p + (vc - lo_v) / (hi_v - lo_v) * (hi_p - lo_p)
    return 0.0


def soc_from_pack(v, cells=CELLS):
    return soc_from_cell(v / cells) if _num(v) else None


def linear_pct(v):
    """Algoritmo do robotd: 6,6 V = 0%, 8,2 V = 100%, interpolação linear (sob carga; tende a superestimar com pouca carga)."""
    if not _num(v) or v <= 0:
        return None
    return max(0.0, min(1.0, (v - RD_EMPTY_V) / (RD_FULL_V - RD_EMPTY_V))) * 100


# ---------------- Uma leitura por segundo ----------------

def trimmed(volts, fresh=None):
    """Converte as tensões das 15 servos na leitura deste segundo: (valor ou None, quantidade usada, [(índice, tensão)] válidas).
    Uma leitura válida é finita e está entre 3,0 e 9,5 V; se fresh for informado, também precisa ser recente.
    Com 9 ou mais leituras, descarta as 3 maiores e as 3 menores e calcula a média; com 5 a 8, usa a mediana; com menos de 5, retorna None."""
    valid = []
    for i, v in enumerate(volts or ()):
        if fresh is not None and (i >= len(fresh) or fresh[i] is not True):
            continue
        if _num(v) and V_MIN <= v <= V_MAX:
            valid.append((i, float(v)))
    n = len(valid)
    if n < 5:
        return None, n, valid
    xs = sorted(v for _, v in valid)
    if n >= 9:
        mid = xs[3:-3]
        return sum(mid) / len(mid), n, valid
    return _median(xs), n, valid


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def classify(torque_on, moving=False, fallen=False, label=None):
    """Classifica rest / light / heavy. Retorna None se não houver leitura de torque (o segundo não conta como baixo esforço nem como outra condição)."""
    if torque_on is False:
        return "rest"
    if torque_on is not True:
        return None
    if moving or fallen or (isinstance(label, str) and label not in CALM_LABELS):
        return "heavy"
    return "light"


def classify_robotd(bus, state):
    """Classifica o estado a partir de busStatus e robot.state do robotd. Usa native.torque_state_confirmed (confirmação lida de volta, não o comando);
    considera movimento quando move.applied não é zero, quando o rótulo policy indica uma ação (chute, cambalhota, limp_fall etc.) ou safety.fallen é verdadeiro."""
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}
    torque = native.get("torque_state_confirmed")
    st = state if isinstance(state, dict) else {}
    applied = (st.get("move") or {}).get("applied") if isinstance(st.get("move"), dict) else None
    moving = isinstance(applied, list) and any(_num(x) and abs(x) > 1e-3 for x in applied)
    fallen = (st.get("safety") or {}).get("fallen") is True if isinstance(st.get("safety"), dict) else False
    return classify(torque if isinstance(torque, bool) else None, moving, fallen, st.get("policy"))


def robotd_volts(bus):
    """Converte busStatus em (15 tensões, 15 indicadores de leitura recente). Se não houver dados, retorna (None, None)."""
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}
    joints = native.get("joints")
    if not isinstance(joints, list) or not joints:
        return None, None
    js = [j if isinstance(j, dict) else {} for j in joints]
    return [j.get("volts") for j in js], [j.get("feedback_fresh") is True for j in js]


def classify_servo_session(rows):
    """Durante o controle das servos, o Studio ocupa o barramento: se alguma tiver torque ligado, classifica como light; se todas estiverem desligadas, como rest; sem leitura, retorna None."""
    flags = [r.get("torque") for r in rows or () if isinstance(r, dict)]
    known = [bool(f) for f in flags if f is not None and f in (0, 1)]   # servo.py armazena 0 ou 1 (também aceita True/False)
    if not known:
        return None
    return "light" if any(known) else "rest"


def servo_session_volts(rows):
    """Converte as linhas de servo.snapshot() em (tensões, indicadores de leitura recente)."""
    rs = [r if isinstance(r, dict) else {} for r in rows or ()]
    if not rs:
        return None, None
    return [r.get("volt") for r in rs], [r.get("fresh") is True for r in rs]


# ---------------- Configurações ----------------

SETTINGS_FILE = "battery-settings.json"
SETTINGS_VERSION = 1
PRESETS = {"2s_liion": "Bateria de lítio 2S (NP-F550 etc.)", "bench": "Fonte de bancada (sem estimativa de carga)"}
DEFAULTS = {"preset": "2s_liion", "warn_pct": 30, "red_pct": 15, "load_floor_v": 6.9, "cal_offset_v": 0.0}
RANGES = {"warn_pct": (15, 60), "red_pct": (5, 40), "load_floor_v": (6.6, 7.4), "cal_offset_v": (-0.5, 0.5)}
LABELS = {"preset": "Tipo de bateria", "warn_pct": "Limite de aviso", "red_pct": "Limite crítico", "load_floor_v": "Limite de tensão sob carga", "cal_offset_v": "Calibração da leitura"}
CAL_CONFIRM_V = 0.3     # Se a diferença de calibração exceder ±0,3 V, pede confirmação (a medição pode estar errada; B-R11)


class SettingsError(ValueError):
    pass


def _check_item(k, v):
    """Valida uma configuração e retorna (valor normalizado, None) ou (None, motivo)."""
    if k == "preset":
        return (v, None) if v in PRESETS else (None, f"Deve ser um destes valores: {', '.join(PRESETS)}")
    lo, hi = RANGES[k]
    if not _num(v):
        return None, "deve ser um número"
    if k in ("warn_pct", "red_pct"):
        if float(v) != int(v):
            return None, "deve ser um número inteiro"
        v = int(v)
    else:
        v = round(float(v), 2)
    if not lo <= v <= hi:
        return None, f"deve estar entre {lo} e {hi}"
    return v, None


def validate_settings(values, base=None):
    """Mescla values (que pode conter apenas alguns campos) em base (DEFAULTS por padrão) e retorna (novas configurações, [erros...]).
    Se houver erros, as novas configurações não podem ser usadas. Campos desconhecidos são erros; o limite crítico precisa ficar pelo menos 5% abaixo do limite de aviso."""
    out = dict(DEFAULTS if base is None else base)
    errors = []
    if not isinstance(values, dict):
        return out, ["As configurações devem ser um objeto"]
    for k, v in values.items():
        if k not in DEFAULTS:
            errors.append(f"Campo de configuração desconhecido: “{k}”")
            continue
        good, why = _check_item(k, v)
        if why:
            errors.append(f"{LABELS[k]} {why} (recebido: {v!r})")
        else:
            out[k] = good
    if not errors and out["red_pct"] > out["warn_pct"] - 5:
        errors.append(f"O limite crítico ({out['red_pct']}%) precisa ficar pelo menos 5% abaixo do limite de aviso ({out['warn_pct']}%)")
    return out, errors


def settings_path(state_dir):
    return os.path.join(state_dir or ".", SETTINGS_FILE)


def load_settings(state_dir, log=None):
    """Lê as configurações. Sem arquivo, usa os valores padrão. Se o arquivo for inválido (JSON malformado ou raiz que não seja objeto), renomeia para .bad, usa os padrões e registra um aviso.
    Campos individuais inválidos usam os padrões e geram um aviso; campos desconhecidos são ignorados (podem pertencer a uma versão futura). Nunca propaga exceções."""
    p = settings_path(state_dir)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"O valor raiz não é um objeto ({type(data).__name__})")
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, ValueError) as e:
        bad = p + ".bad"
        try:
            os.replace(p, bad)
        except OSError:
            bad = None
        if log is not None:
            log.warn("Não foi possível ler as configurações da bateria; usando os valores padrão", cat=LOG_CAT, step=p, raw=f"{type(e).__name__}: {e}",
                     hint=(f"O arquivo inválido foi mantido em {bad}; salve novamente pela página de configurações" if bad else "Não foi possível renomear o arquivo inválido; verifique as permissões do diretório de estado"))
        return dict(DEFAULTS)
    out, wrong = dict(DEFAULTS), []
    for k in DEFAULTS:
        if k in data:
            good, why = _check_item(k, data[k])
            if why:
                wrong.append(f"{LABELS[k]}={data[k]!r} ({why})")
            else:
                out[k] = good
    if out["red_pct"] > out["warn_pct"] - 5:
        wrong.append(f"O limite crítico {out['red_pct']}% não está pelo menos 5% abaixo do limite de aviso {out['warn_pct']}%")
        out["warn_pct"], out["red_pct"] = DEFAULTS["warn_pct"], DEFAULTS["red_pct"]
    if wrong and log is not None:
        log.warn("Algumas configurações da bateria são inválidas; usando os valores padrão para elas", cat=LOG_CAT, step=p, raw="; ".join(wrong),
                 hint="Talvez o arquivo tenha sido editado manualmente; salve novamente pela página de configurações")
    return out


def save_settings(state_dir, settings):
    """Grava o arquivo inteiro (escreve em um temporário e renomeia, para que uma interrupção não danifique o arquivo anterior). Valida antes; configurações inválidas ou falha de gravação geram SettingsError."""
    good, errors = validate_settings(settings, DEFAULTS)
    if errors:
        raise SettingsError("；".join(errors))
    if not state_dir:
        raise SettingsError("O diretório de estado não foi configurado; não é possível salvar")
    os.makedirs(state_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".battery-settings-", dir=state_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dict(good, v=SETTINGS_VERSION), f, ensure_ascii=False, indent=1)
        os.replace(tmp, settings_path(state_dir))
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise SettingsError(f"Não foi possível salvar: {type(e).__name__}: {e}") from None
    return good


def settings_changes(old, new):
    """Gera uma frase para o log, por exemplo: “Limite crítico 15% → 20%; calibração da leitura +0,00 → +0,12 V”. Retorna uma string vazia se nada mudou."""
    unit = {"warn_pct": "%", "red_pct": "%", "load_floor_v": " V", "cal_offset_v": " V"}
    parts = []
    for k in DEFAULTS:
        a, b = old.get(k), new.get(k)
        if a != b:
            fa = PRESETS.get(a, a) if k == "preset" else (f"{a:+.2f}" if k == "cal_offset_v" else a)
            fb = PRESETS.get(b, b) if k == "preset" else (f"{b:+.2f}" if k == "cal_offset_v" else b)
            parts.append(f"{LABELS[k]} {fa}{unit.get(k, '')} → {fb}{unit.get(k, '')}")
    return "；".join(parts)


# ---------------- Estimador ----------------

class _Latch:
    """Chave que só ativa após on_s segundos e só desativa após off_s segundos."""

    def __init__(self, on_s, off_s):
        self.on_s, self.off_s = on_s, off_s
        self.on = False
        self._since = None

    def step(self, now, cond_on, cond_off):
        """Retorna “on” ou “off” se o estado acabou de mudar neste ciclo; caso contrário, None."""
        if not self.on:
            if cond_on:
                self._since = now if self._since is None else self._since
                if now - self._since >= self.on_s:
                    self.on, self._since = True, None
                    return "on"
            else:
                self._since = None
        else:
            if cond_off:
                self._since = now if self._since is None else self._since
                if now - self._since >= self.off_s:
                    self.on, self._since = False, None
                    return "off"
            else:
                self._since = None
        return None

    def reset(self):
        self.on, self._since = False, None


def _ev(level, msg, hint=None, raw=None, ctx=None, step=None):
    return {"level": level, "msg": msg, "hint": hint, "raw": raw, "ctx": ctx, "step": step}


class Estimator:
    """Uma instância por robô. Alimentada por um ciclo dedicado de 1 Hz (não por summarize, que roda 10 vezes por segundo em cada página; revisão B-R7).
    summarize apenas chama view(). feed() deduplica pela chave da amostra (horário de amostragem de busStatus), contando dados repetidos uma única vez."""

    def __init__(self, settings=None):
        self.settings = dict(DEFAULTS)
        if settings:
            self.set_settings(settings)
        self._ref_pct = None        # Último nível exibido antes de reiniciar (apenas na memória); usado para detectar troca ou recarga da bateria
        self._reset(None)

    # ---- Estado ----

    def _reset(self, now):
        self.samples = deque()      # (t, leitura bruta V, classe); a calibração é aplicada no uso para surtir efeito imediato após alterar as configurações
        self.calm = deque()         # (t, mediana dos últimos 30 s, classe predominante)
        self.started_at = None
        self.last_valid_t = None
        self.last_feed_t = None
        self.last_key = None
        self.run_start = None
        self.run_last_t = None
        self.shown = None
        self.mode = "no_data"
        self.est = None             # (percentual, tensão usada já calibrada, base: calm / load, classe, horário da base)
        self.spread = None
        self.started_logged = False
        self.warn = _Latch(WARN_HOLD_S, WARN_HOLD_S)
        self.red = _Latch(WARN_HOLD_S, WARN_HOLD_S)
        self.low = _Latch(LOW_HOLD_S, LOW_CLEAR_HOLD_S)
        self.low_min = None
        self.glitch_at = None
        self.n_used = 0
        self.source = None

    def set_settings(self, settings):
        good, errors = validate_settings(settings, DEFAULTS)
        if errors:
            raise SettingsError("；".join(errors))
        self.settings = good

    @property
    def off(self):
        return self.settings["cal_offset_v"]

    # ---- Alimentação de dados ----

    def feed(self, now, volts=None, fresh=None, cls=None, key=None, source="robotd"):
        """Chamada uma vez por segundo. volts=None ou key igual à anterior significa que não há dados novos (o relógio continua; 10 s sem leitura reiniciam a estimativa).
        Retorna os eventos de log deste ciclo, a serem registrados por log_events."""
        events = []
        new = volts is not None and (key is None or key != self.last_key)
        if new and key is None and self.last_feed_t is not None and now - self.last_feed_t < 0.5:
            new = False             # Sem key, deduplica pelo horário: duas chamadas no mesmo segundo contam uma vez
        if new:
            self.last_key, self.last_feed_t = key, now
            v, n, valid = trimmed(volts, fresh)
            self.n_used = n
            if v is not None:
                events += self._add(now, v, cls, valid, volts, source)
        if self.last_valid_t is not None and now - self.last_valid_t > GAP_S:
            if self.started_at is not None:
                events.append(_ev("warn", f"As 15 servos ficaram sem leitura de tensão por mais de {GAP_S:.0f} s; reiniciando a estimativa da bateria",
                                  hint="As servos podem estar sem alimentação (bateria desconectada ou trocada) ou o barramento pode ter caído; quando as leituras voltarem, a estimativa ficará em inicialização por 30 s",
                                  ctx={"last_pct": self.shown}))
                if self.shown is not None:
                    self._ref_pct = self.shown
            self._reset(now)
        events += self._evaluate(now)
        return events

    def _add(self, now, v, cls, valid, volts, source):
        events = []
        if self.started_at is None:
            self.started_at = now
        # Pico: registra se esta leitura ficar mais de 0,5 V abaixo da mediana dos últimos 60 s; a mediana evita que isso afete a estimativa, e os valores brutos das 15 servos vão para o log.
        recent = [x for t, x, _ in self.samples if now - t <= 60]
        if len(recent) >= 10:
            med = _median(recent)
            if v < med - GLITCH_V and (self.glitch_at is None or now - self.glitch_at >= GLITCH_EVERY_S):
                self.glitch_at = now
                raw = [round(x, 2) if _num(x) else x for x in (volts or [])]
                # Texto fixo e valores nos dados brutos: o Studio registra a mesma mensagem no máximo uma vez por minuto.
                events.append(_ev("warn", "A leitura de tensão caiu mais de 1 V de uma vez",
                                  hint="Se durar um ou dois segundos, não afeta a estimativa. Se acontecer com frequência, verifique o conector da bateria e o barramento; os valores brutos das 15 servos ajudam a identificar se houve queda real ou erro de leitura",
                                  raw=f"Nesta leitura: {v:.2f} V; mediana do último minuto: {med:.2f} V; 15 servos: {raw}",
                                  ctx={"cls": cls, "source": source}))
        self.samples.append((now, v, cls))
        self.last_valid_t = now
        self.source = source
        lo = min(valid, key=lambda x: x[1])
        hi = max(valid, key=lambda x: x[1])
        self.spread = {"min": lo[1], "min_i": lo[0], "max": hi[1], "max_i": hi[0], "n": len(valid)}
        # Período de baixo esforço: rest/light contínuos; uma lacuna longa ou outro estado interrompe o período.
        if cls in ("rest", "light"):
            if self.run_start is None or self.run_last_t is None or now - self.run_last_t > RUN_GAP_S:
                self.run_start = now
            self.run_last_t = now
            if now - self.run_start >= CALM_S:
                win = [(x, c) for t, x, c in self.samples if t >= now - CALM_S and t >= self.run_start]
                if len(win) >= CALM_S // 2:
                    nrest = sum(1 for _, c in win if c == "rest")
                    self.calm.append((now, _median([x for x, _ in win]), "rest" if nrest * 2 >= len(win) else "light"))
        else:
            self.run_start = self.run_last_t = None
        while self.samples and now - self.samples[0][0] > KEEP_S:
            self.samples.popleft()
        while self.calm and now - self.calm[0][0] > CALM_WINDOW_S:
            self.calm.popleft()
        return events

    # ---- Cálculo ----

    def _evaluate(self, now):
        events = []
        s = self.settings
        if self.started_at is None:
            self.mode, self.shown, self.est = "no_data", None, None
            return events
        bench = s["preset"] == "bench"
        warming = now - self.started_at < ESTIMATING_S
        while self.calm and now - self.calm[0][0] > CALM_WINDOW_S:
            self.calm.popleft()
        prev_mode = self.mode
        if bench:
            self.mode, self.shown, self.est = "bench", None, None
        elif warming:
            self.mode, self.shown, self.est = "estimating", None, None
        else:
            if self.calm:
                t, v, c = max(self.calm, key=lambda x: x[1])
                vv = v + self.off
                self.mode, self.est = "calm", (soc_from_pack(vv), vv, "calm", c, t)
            else:
                win = [x for t, x, _ in self.samples if now - t <= LOAD_ROUGH_S]
                if win:
                    vv = _median(win) + self.off
                    self.mode, self.est = "load_rough", (soc_from_pack(vv), vv, "load", None, now)
            if self.est is not None:
                pct = self.est[0]
                if self.shown is None or prev_mode != self.mode or abs(pct - self.shown) >= DEADBAND_PCT:
                    self.shown = int(round(pct))
                events += self._log_estimate(now)

        # Avisos: não avalia nos primeiros 30 s (B-R2) nem calcula percentual com fonte de bancada.
        if warming:
            return events
        pct = self.shown
        w, r = s["warn_pct"], s["red_pct"]
        have = pct is not None and self.mode in ("calm", "load_rough")
        ch = self.warn.step(now, have and pct <= w, (not have) or pct >= w + HYST_PCT)
        if ch == "on":
            events.append(_ev("warn", f"Bateria atingiu o limite de aviso de {w}%: cerca de {pct}% restantes",
                              hint="Prepare-se para recarregar; " + self._basis_short(), ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"Bateria voltou para cerca de {pct}%; aviso removido" if pct is not None else "Aviso de bateria removido", ctx=self._ctx()))
        # A estimativa aproximada durante movimento pode gerar aviso amarelo; como a tabela sob carga tende a indicar menos que o real, o vermelho exige estimativa em baixo esforço ou o limite de tensão sob carga.
        ch = self.red.step(now, have and self.mode == "calm" and pct <= r, (not have) or pct >= r + HYST_PCT)
        if ch == "on":
            events.append(_ev("error", f"Bateria atingiu o limite crítico de {r}%: cerca de {pct}% restantes",
                              hint="Recarregue a bateria; " + WARN_ONLY, ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"Bateria voltou para cerca de {pct}%; aviso crítico removido" if pct is not None else "Aviso crítico de bateria removido", ctx=self._ctx()))
        # Limite sob carga: mediana calibrada dos últimos 10 s abaixo do valor configurado por 30 s.
        m10 = self.volts_now(now)
        floor = s["load_floor_v"]
        if m10 is not None and m10 < floor:
            self.low_min = m10 if self.low_min is None else min(self.low_min, m10)
        ch = self.low.step(now, m10 is not None and m10 < floor, m10 is not None and m10 >= floor + LOW_CLEAR_V)
        if ch == "on":
            events.append(_ev("error", f"Tensão muito baixa: abaixo de {floor:.1f} V nos últimos {LOW_HOLD_S} s (mínima de {self.low_min:.2f} V)",
                              hint="Pare, sente o robô e prepare-se para recarregar; " + WARN_ONLY, ctx=self._ctx()))
        elif ch == "off":
            events.append(_ev("info", f"Tensão voltou a {m10:.2f} V; aviso de tensão sob carga removido", ctx=self._ctx()))
            self.low_min = None
        if not self.low.on and not (m10 is not None and m10 < floor):
            self.low_min = None
        return events

    def _log_estimate(self, now):
        """Registra a primeira estimativa após a inicialização. Após reiniciar por falta de tensão por mais de 10 s, registra possível troca ou recarga se a primeira estimativa de baixo esforço subir mais de 10%.
        Não verifica enquanto as leituras são contínuas: passar de postura mantida para torque desligado pode elevar a leitura em 20% com a mesma bateria (registro de 10-12 às 15:32)."""
        events = []
        pct, vv, kind, c, _ = self.est
        if not self.started_logged:
            self.started_logged = True
            events.append(_ev("info", f"Estimativa de bateria iniciada: {self._basis_short()} → cerca de {int(round(pct))}%",
                              hint=f"Estimativa por tabela, com erro de cerca de ±15%; calibração da leitura: {self.off:+.2f} V", ctx=self._ctx()))
        ref = self._ref_pct
        if ref is not None and kind == "calm":
            if pct - ref >= JUMP_PCT:
                events.append(_ev("info", f"A estimativa da bateria subiu {pct - ref:.0f}% desde a interrupção; a bateria pode ter sido trocada ou recarregada",
                                  hint=f"Cerca de {ref:.0f}% → {pct:.0f}% ({self._basis_short()})", ctx=self._ctx()))
            self._ref_pct = None
        return events

    # ---- Leitura dos resultados ----

    def volts_now(self, now):
        """Mediana calibrada dos últimos 10 s, usada nos detalhes e no limite sob carga. Retorna None com menos de 5 amostras."""
        win = [x for t, x, _ in self.samples if now - t <= LOW_MED_S]
        return _median(win) + self.off if len(win) >= 5 else None

    def level(self):
        if self.red.on or self.low.on:
            return "error"
        return "warn" if self.warn.on else None

    def current_cls(self):
        return self.samples[-1][2] if self.samples else None

    def _basis_short(self):
        if self.est is None:
            return "Ainda sem leitura"
        _, vv, kind, c, _ = self.est
        if kind == "calm":
            return f"{('em repouso, sem torque' if c == 'rest' else 'em pé / sentado')} a {vv:.2f} V"
        return f"Em movimento: {vv:.2f} V (tensão sob carga, pode ficar abaixo do real)"

    def _ctx(self):
        return {"mode": self.mode, "pct": self.shown, "cls": self.current_cls(), "source": self.source,
                "basis_v": round(self.est[1], 3) if self.est else None, "cal": self.off,
                "calm_points": len(self.calm), "samples": len(self.samples)}

    def view(self, now, rd=None, names=None, shutdown=None):
        """Fornece dados para o indicador de bateria, a janela de detalhes e a lista de tarefas. rd: battery de robotd health ({volts, percent});
        names: nomes das 15 servos na ordem de volts; shutdown: configuração battery_empty_shutdown do robotd (onboard.read_battery_shutdown)."""
        s = self.settings
        v10 = self.volts_now(now)
        cls = self.current_cls()
        rd = rd if isinstance(rd, dict) else {}
        rd_v = rd.get("volts") if _num(rd.get("volts")) else None
        rd_pct = rd.get("percent") if _num(rd.get("percent")) else (linear_pct(v10 - self.off) if v10 is not None else None)
        basis = None
        if self.est is not None:
            pct, vv, kind, c, t = self.est
            basis = {"kind": kind, "cls": c, "volts": round(vv, 2), "cell": round(vv / CELLS, 3),
                     "age_s": round(max(0.0, now - t)), "pct": round(pct, 1)}
        why = {
            "no_data": "Sem leitura de tensão",
            "estimating": "Estimando; leitura iniciada agora",
            "bench": "Fonte de bancada; sem estimativa de carga",
            "load_rough": "Em movimento; estimativa aproximada pela tensão sob carga, possivelmente abaixo do real",
        }.get(self.mode)
        if self.mode == "calm":
            why = ("Em repouso" if cls == "rest" else "Em pé / sentado" if cls == "light"
                   else "Em movimento; estimativa baseada na tensão em repouso" if cls == "heavy" else "Estimativa baseada na tensão em repouso")
        detail = self._detail(now, v10, cls, rd_v, rd_pct, names, shutdown)
        return {
            "pct": self.shown,
            "mode": self.mode,
            "level": self.level(),
            "warn": self.warn.on,
            "red": self.red.on,
            "low_volt": self.low.on,
            "volts": round(v10, 2) if v10 is not None else None,
            "cls": cls,
            "why": why,
            "basis": basis,
            "rd_volts": round(rd_v, 2) if rd_v is not None else None,
            "rd_pct": round(rd_pct) if rd_pct is not None else None,
            "spread": self._spread(names),
            "warn_pct": s["warn_pct"], "red_pct": s["red_pct"], "load_floor_v": s["load_floor_v"],
            "cal_offset_v": self.off, "preset": s["preset"], "source": self.source, "shutdown": shutdown,
            "estimating_left_s": (max(0, int(math.ceil(ESTIMATING_S - (now - self.started_at))))
                                  if self.mode == "estimating" else None),
            "detail": detail,
        }

    def _spread(self, names):
        sp = self.spread
        if not sp:
            return None
        nm = lambda i: names[i] if names and i < len(names) else f"Servo {i + 1}"
        return {"min": round(sp["min"], 2), "min_name": nm(sp["min_i"]), "max": round(sp["max"], 2),
                "max_name": nm(sp["max_i"]), "n": sp["n"]}

    def _detail(self, now, v10, cls, rd_v, rd_pct, names, shutdown):
        """Linhas da janela de detalhes explicando como o valor foi calculado."""
        s = self.settings
        lines = []
        cal = f"calibração {self.off:+.2f} V"
        if self.mode == "no_data":
            lines.append("Sem leitura de tensão das servos: elas podem estar sem alimentação (bateria desconectada?) ou o programa principal pode não estar em execução")
        elif self.mode == "estimating":
            left = max(0, int(math.ceil(ESTIMATING_S - (now - self.started_at))))
            lines.append(f"Leitura de tensão iniciada; resultado em {left} s (as leituras dos primeiros {ESTIMATING_S} s podem coincidir com uma queda durante o passo e serão ignoradas)")
        elif self.mode == "bench":
            lines.append("A fonte de bancada está selecionada nas configurações: a tensão será exibida, sem estimativa ou avisos de bateria")
        elif self.est is not None:
            pct, vv, kind, c, t = self.est
            if kind == "calm":
                ago = int(now - t)
                when = "agora" if ago < 5 else f"há {ago // 60} min" if ago >= 60 else f"há {ago} s"
                lines.append(f"Momento de menor esforço nos últimos 5 min ({CLS_CN.get(c, c)}, {when}): {vv:.2f} V"
                             f" (média após descartar as 3 leituras mais altas e mais baixas entre 15 servos, {cal}) → {vv / CELLS:.2f} V por célula → cerca de {pct:.0f}%")
                if c == "light":
                    lines.append("Em pé ou sentado, as servos consomem energia e a tensão fica um pouco abaixo da leitura sem torque; o resultado é mais preciso após pelo menos 30 s em repouso")
            else:
                lines.append(f"O robô não parou nos últimos 5 min: estimativa aproximada de {pct:.0f}% com base na tensão em movimento de {vv:.2f} V ({cal})."
                             "O movimento reduz a tensão, então a estimativa pode ficar abaixo do valor real; após parar por 30 s, ela será recalculada com a tensão em repouso")
            lines.append("Tabela genérica para bateria de lítio 2S, com erro de cerca de ±15%; sem calibração, tende a indicar um valor abaixo do real")
        if v10 is not None and self.mode != "no_data":
            lines.append(f"Agora: {v10:.2f} V ({CLS_CN.get(cls, 'estado desconhecido')})")
        if self.mode in ("calm", "load_rough"):
            lines.append(f"Aviso em {s['warn_pct']}% · limite crítico em {s['red_pct']}% · também há aviso se a tensão ficar abaixo de {s['load_floor_v']:.1f} V por {LOW_HOLD_S} s"
                         " (são apenas avisos; na tabela, 30% corresponde a uma tensão maior que os 30% da escala linear antiga do programa, então o aviso amarelo aparece antes)")
        elif self.mode == "bench":
            lines.append(f"Será exibido um aviso se a tensão ficar abaixo de {s['load_floor_v']:.1f} V por {LOW_HOLD_S} s (isso pode ocorrer se a fonte limitar a corrente ou se o cabo for fino demais)")
        if rd_pct is not None and self.mode != "bench":
            src = f"{rd_v:.2f} V, " if rd_v is not None else ""
            lines.append(f"Estimativa do programa principal: {rd_pct:.0f}% ({src}escala linear de 6,6–8,2 V, tende a superestimar com pouca carga)")
        sp = self._spread(names)
        if sp and self.mode != "no_data":
            lines.append(f"Tensão de {sp['n']} servos: mínima {sp['min']:.1f} V ({sp['min_name']}) · máxima {sp['max']:.1f} V ({sp['max_name']})")
        if self.mode == "bench":
            return lines                # Fonte de bancada: sem bateria, não exibe instruções de recarga ou conservação.
        lines.append(stop_words({"source": self.source, "shutdown": shutdown}))
        lines.append(MAINTENANCE)
        return lines

    # ---- Calibração ----

    def calibrate(self, now, measured_v):
        """“Medi a tensão da bateria”: só aceita a medição após pelo menos 30 s em repouso, sem torque (B-R11). Retorna {ok, offset, confirm, reason};
        offset é a nova calibração (tensão nos terminais da bateria − leitura das servos), salva nas configurações após confirmação. Diferenças acima de ±0,3 V pedem nova confirmação."""
        if not _num(measured_v) or not 6.0 <= measured_v <= 9.0:
            return {"ok": False, "offset": None, "confirm": False, "reason": "A tensão medida deve ficar entre 6,0 e 9,0 V; confira se a medição está correta e se as pontas do multímetro não estão invertidas"}
        win = [(x, c) for t, x, c in self.samples if now - t <= CALM_S]
        rest_long = (self.run_start is not None and now - self.run_start >= CALM_S
                     and len(win) >= CALM_S // 2 and all(c == "rest" for _, c in win))
        if not rest_long:
            return {"ok": False, "offset": None, "confirm": False,
                    "reason": f"Desative o torque e deixe o robô em repouso por pelo menos {CALM_S} s antes de medir (a tensão fica mais estável em repouso)"}
        raw = _median([x for x, _ in win])
        off = round(measured_v - raw, 2)
        lo, hi = RANGES["cal_offset_v"]
        if not lo <= off <= hi:
            return {"ok": False, "offset": off, "confirm": False,
                    "reason": f"A medição de {measured_v:.2f} V difere {off:+.2f} V da leitura das servos de {raw:.2f} V, acima de ±{hi} V; confira a medição no terminal de entrada da bateria do HAT"}
        confirm = abs(off) > CAL_CONFIRM_V
        why = (f"Leitura das servos: {raw:.2f} V; medição: {measured_v:.2f} V; diferença: {off:+.2f} V"
               + (". A diferença é alta; confirme se a medição foi feita na entrada da bateria do HAT." if confirm else ""))
        return {"ok": True, "offset": off, "confirm": confirm, "reason": why, "servo_v": round(raw, 3)}


# ---------------- Tarefas e logs ----------------

def stop_words(view):
    """Informa se o robô vai parar quando a bateria acabar. Apenas avisa (decisão do usuário de 10-18). Durante o controle das servos, o programa principal fica parado e não executa o desligamento automático configurado."""
    if view.get("source") == "servo":
        return "Durante o controle das servos, o programa principal fica parado; sem bateria, o robô não se senta sozinho. Ao terminar, desligue a alimentação e desconecte a bateria."
    if view.get("shutdown") is True:
        return "O programa principal está configurado para sentar e desligar quando a bateria acabar: fará isso quando a média de 10 s cair para 6,6 V."
    return WARN_ONLY


def todo_items(view):
    """Converte a estimativa em tarefas, começando pelas mais importantes. Apenas avisos: as mensagens são recomendações."""
    if not isinstance(view, dict):
        return []
    items = []
    pct, floor = view.get("pct"), view.get("load_floor_v")
    if view.get("low_volt"):
        v = view.get("volts")
        vtxt = f"：{v:.2f} V" if _num(v) else ""
        if view.get("preset") == "bench":
            items.append({"key": "battery_low_volt", "level": "error", "msg": f"Tensão da fonte muito baixa{vtxt}",
                          "hint": f"A tensão ficou abaixo de {floor:.1f} V por {LOW_HOLD_S} s; verifique se a fonte está limitando a corrente ou se o cabo é fino ou comprido demais"})
        else:
            items.append({"key": "battery_low_volt", "level": "error", "msg": f"Tensão muito baixa{vtxt}",
                          "hint": f"A tensão ficou abaixo de {floor:.1f} V por {LOW_HOLD_S} s; pare o robô, sente-o e prepare-se para recarregar. {stop_words(view)}"})
    rough = view.get("mode") == "load_rough"
    tail = " (estimativa aproximada pela tensão sob carga durante o movimento; pode ficar abaixo do real)" if rough else ""
    if view.get("red") and _num(pct):
        items.append({"key": "battery", "level": "error", "msg": f"Restam cerca de {pct}% de bateria",
                      "hint": f"Está na hora de recarregar. {stop_words(view)}"})
    elif view.get("warn") and _num(pct):
        items.append({"key": "battery", "level": "warn", "msg": f"Bateria em cerca de {pct}%{tail}",
                      "hint": "Prepare-se para recarregar; estimativa pela tabela de tensão, com erro de cerca de ±15% e tendência a ficar abaixo do real sem calibração"})
    return items


def log_events(log, events):
    """Registra no log do Studio os eventos retornados por feed() (categoria “Bateria”). Não faz nada se log for None."""
    if log is None:
        return
    for e in events or ():
        log.write(e["msg"], cat=LOG_CAT, level=e["level"], step=e.get("step"), raw=e.get("raw"),
                  hint=e.get("hint"), ctx=e.get("ctx"))
