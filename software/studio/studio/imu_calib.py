"""Calibração da orientação de montagem do IMU (feita com o robô em pé): apenas cálculos, sem acesso ao hardware ou à rede; usa somente math da biblioteca padrão.

A página coleta leituras de gravidade nesta ordem: repouso em pé → inclinar para a frente → para trás → para a esquerda → para a direita. solve() retorna a orientação de montagem, a compensação da postura, o resultado de cada etapa e indicadores de qualidade. Gravar os dados no robô e decidir como fazê-lo fica fora deste módulo (veja imu-page-plan.md).

## Convenções (confirmadas com dados do robô; consulte a seção “Fatos” do plano)
- Referencial do corpo B: x aponta para a frente (lado da cabeça), y para a esquerda e z para cima. robot.state.safety.gravity usa esse referencial; em pé, fica aproximadamente em (0, 0, -1) (linha 10 de tests/fixtures/now-20261018.jsonl: [0.044, 0.016, -0.999]).
- Todos os quaternions usam [w, x, y, z] (ordem de robot.state.imu.quat e mount_wxyz do verify-imu).
- Para obter a gravidade do quaternion de orientação q (corpo → mundo): g = R(q)ᵀ·(0, 0, -1). É assim que robotd calcula safety.gravity (depois usa a mediana de 3 pontos).
- A orientação de montagem q_mount transforma o referencial do sensor no referencial do corpo: v_corpo = q_mount ⊗ v_sensor ⊗ q_mount*; robotd calcula a orientação do corpo como q_corpo = q_sensor ⊗ q_mount⁻¹ (firmware do fork duck-control/src/imu.rs:137-151).

## Formato das amostras
Cada amostra é um dict (ou diretamente [gx, gy, gz]); escolha uma das opções:
    {"g": [gx, gy, gz]}       direção da gravidade (o módulo é ignorado) — robot.state.safety.gravity
    {"acc": [ax, ay, az]}     leitura do acelerômetro: em repouso, aponta para cima com 1 g; inverta o sinal para obter gravidade
    {"quat": [w, x, y, z]}    orientação (corpo → mundo)
Pode incluir "t" (segundos) e "step" (para agrupar etapas em uma lista plana). Leituras inf/nan são descartadas.

Referencial (frame):
- "body" (padrão): as leituras já foram convertidas para o referencial do corpo usando a orientação de montagem salva no robô. robot.state no modo de movimento e busStatus.last_sample.imu no modo de depuração (gravity, quaternion_wxyz; firmware do fork robotd/src/feetech_commissioning.rs:1236-1255) já usam esse referencial. O resultado é uma correção; nova orientação = correção ∘ orientação anterior. Por isso, informe old_mount.
- "sensor": leituras nos eixos brutos do sensor (robotd ainda não fornece esse formato; fica reservado para leitura direta futura). O resultado é a própria orientação de montagem.

## Seleção das leituras por etapa (web/imu.js usa a mesma regra para detectar “estabilizou, próxima etapa”; parâmetros em RULES)
- Trecho estável: percorre para trás desde a última leitura e agrupa as leituras consecutivas cuja diferença para a última é ≤ hold_band_deg; ignora saltos isolados (o BNO085 às vezes produz um quadro com salto). Se o movimento passar do ponto e depois estabilizar, considera apenas o trecho estável após retornar.
- Referência nivelada: antes do trecho estável, procura o trecho mais recente de leituras a ≤ level_deg do repouso na mesa, com oscilação ≤ ref_spread_deg e pelo menos ref_min_n amostras consecutivas. Ao levantar o robô, é improvável manter a mão perfeitamente nivelada. Cada etapa usa seu próprio instante nivelado como zero; alguns graus de inclinação da mão não são confundidos com uma inclinação do robô. Se não encontrar esse trecho, usa o instante de repouso na mesa.
- Inclinação e direção: compara a direção média do trecho estável com a referência nivelada. Os limites mínimo/máximo são avaliados no trecho estável.

## Princípio
1. Repouso em pé (na mesa, sem tocar): o sentido oposto à gravidade define “cima”.
2. Para cada uma das quatro inclinações, d = componente horizontal (estável − nivelada). O azimute de d no plano horizontal menos o azimute esperado (frente 0°, esquerda 90°, trás 180°, direita −90°) define para onde a etapa considera que fica a “frente”, c.
3. As etapas para a frente e para trás devem obter o mesmo c (se diferirem, as duas inclinações foram feitas para o mesmo lado); o mesmo vale para esquerda e direita. Os dois pares também devem concordar (diferença próxima a 180° indica que um par foi invertido; diferença de alguns graus indica inclinação diagonal, chamada cross). A média circular dos quatro c define a frente; o desvio de cada etapa indica o quanto ela ficou inclinada para o lado.
4. Ortogonaliza “cima” e “frente” para obter os três eixos.
5. Compensação da postura: “cima” não é forçado a ficar vertical; usa home_gravity, gravidade esperada do corpo na postura HOME oficial (padrão (0,0,-1); o corpo fica nivelado no HOME do treinamento oficial, veja o plano). A diferença observada em pé — seja por montagem inclinada do sensor ou pelas pernas — é incorporada à orientação de montagem. Após calibrar, a leitura em pé coincide com a leitura do HOME oficial. A gravidade sozinha não distingue essas causas; por isso, diferenças acima de 5° exigem confirmação.
6. A autoverificação não detecta se frente/trás e esquerda/direita foram invertidos ao mesmo tempo (como se o robô tivesse girado). Só é possível comparar com a orientação antiga; mudanças de direção acima de 90° exigem confirmação.
"""
import math

DOWN = (0.0, 0.0, -1.0)
STEPS = ("still", "fwd", "back", "left", "right")
STEP_CN = {"still": "Repouso em pé", "fwd": "Inclinação para a frente", "back": "Inclinação para trás", "left": "Inclinação para a esquerda", "right": "Inclinação para a direita"}
TILTS = ("fwd", "back", "left", "right")
EXPECT_DIR = {"fwd": 0.0, "left": 90.0, "back": 180.0, "right": -90.0}   # Direção da gravidade ao inclinar para este lado (graus, anti-horário a partir de +x)

# Critérios compartilhados com RULES em web/imu.js. O frontend é um pouco mais estrito (inclinação ≥12°, ≤30°, estabilizar por 1 s); este módulo aceita o que o frontend aprovar.
RULES = {
    "still_min_n": 15,              # Mínimo de leituras em repouso (1,5 s a 10 Hz; a página coleta por 3 s)
    "still_max_spread_deg": 1.5,    # Oscilação máxima em repouso (percentil 90: ignora saltos isolados, mas detecta oscilação contínua)
    "level_deg": 5.0,               # Diferença máxima do repouso na mesa para considerar nivelado
    "ref_min_n": 5,                 # Mínimo de leituras consecutivas para a referência nivelada (0,5 s)
    "ref_spread_deg": 1.5,          # Oscilação máxima na referência nivelada
    "hold_band_deg": 1.8,           # Diferença máxima para a última leitura do trecho estável
    "hold_min_n": 5,                # Mínimo de leituras estáveis (a página exige 1 s e pelo menos 8 amostras)
    "tilt_min_deg": 10.0,           # Inclinação mínima em relação à referência nivelada; abaixo disso, a mão impede determinar a frente com precisão
    "tilt_max_deg": 35.0,           # Inclinação máxima; acima disso, os pés podem escorregar e as leituras ficam instáveis
    "pair_max_deg": 60.0,           # Diferença máxima entre as direções da frente nas etapas para a frente e para trás; acima disso, inclinaram para o mesmo lado (idem para esquerda/direita)
    "skew_max_deg": 20.0,           # Desvio máximo de cada etapa em relação à direção consensual
    "cross_max_deg": 12.0,          # Diferença máxima entre os pares frente/trás e esquerda/direita (a direção fica errada em cerca de Δ/2)
    "good_skew_deg": 10.0,          # Classifica como boa se cada etapa desviar ≤10° e a diferença entre os pares for ≤6°
    "good_cross_deg": 6.0,
    "big_change_deg": 8.0,          # Mudança em relação à orientação anterior que avisa sobre possível montagem inclinada ou diferente
    "stand_confirm_deg": 5.0,       # Compensação da postura acima desse limite exige confirmação (robotd tolera apenas 5° em pé)
    "flip_deg": 90.0,               # Mudança de direção que exige confirmação; provavelmente frente/trás e esquerda/direita foram invertidos
}


# ---------------- Vetores ----------------

def _v(x):
    return (float(x[0]), float(x[1]), float(x[2]))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a):
    """Normaliza um vetor; retorna None para vetor nulo ou com inf/nan."""
    n = norm(a)
    if not (math.isfinite(n) and n > 1e-9):
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


def angle_deg(a, b):
    """Ângulo entre dois vetores em graus; retorna None se não for possível determinar uma direção."""
    ua, ub = unit(a), unit(b)
    if ua is None or ub is None:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(ua, ub)))))


def horiz(v, up):
    """Remove de v a componente ao longo de up (que deve ser unitário)."""
    return sub(v, scale(up, dot(v, up)))


def signed_angle_deg(a, b, axis):
    """Ângulo orientado em graus para girar de a até b ao redor de axis (positivo pela regra da mão direita). Primeiro projeta a e b no plano perpendicular a axis."""
    ha, hb = unit(horiz(a, axis)), unit(horiz(b, axis))
    if ha is None or hb is None:
        return None
    return math.degrees(math.atan2(dot(cross(ha, hb), axis), dot(ha, hb)))


def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def circ_mean_deg(ds):
    s = sum(math.sin(math.radians(d)) for d in ds)
    c = sum(math.cos(math.radians(d)) for d in ds)
    if abs(s) < 1e-9 and abs(c) < 1e-9:
        return None
    return math.degrees(math.atan2(s, c))


# ---------------- Matrizes (tuplas aninhadas 3×3, ordenadas por linha) ----------------

def mat_mul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mat_vec(m, v):
    return tuple(m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] for i in range(3))


def mat_t(m):
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))


# ---------------- Quaternions [w, x, y, z] ----------------

def q_normalize(q):
    if len(q) != 4 or not all(math.isfinite(float(c)) for c in q):
        raise ValueError("O quaternion deve conter 4 números finitos")
    n = math.sqrt(sum(float(c) * float(c) for c in q))
    if not n > 1e-12:
        raise ValueError("O módulo do quaternion é zero")
    q = tuple(float(c) / n for c in q)
    return q if q[0] >= 0 else tuple(-c for c in q)     # Normaliza para w ≥ 0 (q e −q representam a mesma rotação)


def q_mul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def q_conj(q):
    return (q[0], -q[1], -q[2], -q[3])


def q_rotate(q, v):
    return mat_vec(mat_from_q(q), v)


def mat_from_q(q):
    w, x, y, z = q_normalize(q)
    return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
            (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
            (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))


def q_from_mat(m):
    """Converte uma matriz de rotação em quaternion (método de Shepperd, numericamente estável)."""
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = ((m[2][1] - m[1][2]) / s, 0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][2] - m[2][0]) / s, (m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[1][0] - m[0][1]) / s, (m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s)
    return q_normalize(q)


def q_angle_deg(q):
    """Retorna o ângulo desta rotação (0–180°)."""
    w = abs(q_normalize(q)[0])
    return math.degrees(2 * math.acos(min(1.0, w)))


def q_between(a, b):
    """Retorna a rotação mais curta que leva o vetor unitário a até b."""
    a, b = unit(a), unit(b)
    c = dot(a, b)
    if c < -0.999999:
        # Direções exatamente opostas: escolhe qualquer eixo perpendicular a a e gira 180°.
        axis = unit(cross(a, (1.0, 0.0, 0.0))) or unit(cross(a, (0.0, 1.0, 0.0)))
        return (0.0, axis[0], axis[1], axis[2])
    x = cross(a, b)
    return q_normalize((1.0 + c, x[0], x[1], x[2]))


def gravity_from_quat(q):
    """Converte a orientação (corpo → mundo) em direção da gravidade no referencial do corpo, usando o algoritmo de robotd safety.gravity."""
    r = mat_from_q(q)
    return (-r[2][0], -r[2][1], -r[2][2])


def compose_mount(correction, old_mount):
    """Nova orientação de montagem = correção ∘ orientação anterior (ambas sensor → corpo):
    v_corpo_novo = R_correção · v_corpo_anterior = R_correção · R_anterior · v_sensor."""
    return q_normalize(q_mul(correction, old_mount))


# ---------------- Montagens padrão (24 alinhamentos dos eixos do sensor com o corpo) ----------------

_AXIS_CN = {(1, 0): "frente", (1, 1): "esquerda", (1, 2): "cima", (-1, 0): "trás", (-1, 1): "direita", (-1, 2): "baixo"}


def _standard_mounts():
    out = []
    perms = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
    for p in perms:
        for sx in (1, -1):
            for sy in (1, -1):
                for sz in (1, -1):
                    m = [[0.0] * 3 for _ in range(3)]
                    for col, (row, s) in enumerate(zip(p, (sx, sy, sz))):
                        m[row][col] = float(s)      # Eixo col do sensor → eixo row do corpo
                    m = tuple(tuple(r) for r in m)
                    det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                           - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                           + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
                    if det > 0:
                        out.append(m)
    return out


STANDARD_MOUNTS = _standard_mounts()


def describe_mount(q):
    """Descreve a montagem em linguagem simples: para que lado do corpo apontam x/y/z do sensor (montagem padrão mais próxima) e o desvio angular."""
    best, best_deg = None, None
    for m in STANDARD_MOUNTS:
        d = q_angle_deg(q_mul(q_conj(q_from_mat(m)), q))
        if best_deg is None or d < best_deg:
            best, best_deg = m, d
    words = []
    for col, name in enumerate("xyz"):
        row = next(r for r in range(3) if best[r][col] != 0)
        words.append(f"Eixo {name} do sensor aponta para {_AXIS_CN[(int(best[row][col]), row)]}")
    return {"text": "; ".join(words), "off_deg": round(best_deg, 2), "quat": list(q_from_mat(best))}


# ---------------- Amostragem ----------------

def _finite3(x):
    if not isinstance(x, (list, tuple)) or len(x) != 3:
        return None
    try:
        v = _v(x)
    except (TypeError, ValueError):
        return None
    return v if all(math.isfinite(c) for c in v) else None


def sample_gravity(s):
    """Converte uma amostra em vetor unitário da gravidade no referencial do corpo (ou do sensor); retorna None e descarta a leitura se não reconhecida ou com inf/nan."""
    try:
        if isinstance(s, (list, tuple)):
            v = _finite3(s)
            return unit(v) if v else None
        if not isinstance(s, dict):
            return None
        if s.get("g") is not None:
            v = _finite3(s["g"])
            return unit(v) if v else None
        if s.get("acc") is not None:
            v = _finite3(s["acc"])
            a = unit(v) if v else None
            return None if a is None else scale(a, -1.0)
        if s.get("quat") is not None:
            return gravity_from_quat(s["quat"])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return None


def sum_vec(vs):
    s = (0.0, 0.0, 0.0)
    for v in vs:
        s = add(s, v)
    return s


def mean_dir(vs):
    return unit(sum_vec(vs)) if vs else None


def spread_deg(vs, m):
    return max((angle_deg(v, m) or 0.0 for v in vs), default=0.0)


def spread_p90_deg(vs, m):
    """Percentil 90 dos ângulos até m (índice ⌊0,9·(n−1)⌋ após ordenar). Usado no repouso para ignorar saltos isolados. A página usa o mesmo algoritmo spreadP90."""
    ds = sorted(angle_deg(v, m) or 0.0 for v in vs)
    return ds[int(0.9 * (len(ds) - 1))] if ds else 0.0


def trimmed_mean_dir(vs):
    """Calcula a média, remove os 10% mais distantes (acima do percentil 90) e calcula a média novamente. Saltos isolados não desviam “cima”. A página usa trimmedMeanDir."""
    m = mean_dir(vs)
    if m is None:
        return None
    lim = spread_p90_deg(vs, m)
    keep = [v for v in vs if (angle_deg(v, m) or 0.0) <= lim + 1e-9]
    return mean_dir(keep) or m


def group_steps(samples):
    """Usa dict {"still": [...], ...} como está; agrupa uma lista plana pelo campo "step" de cada amostra."""
    if isinstance(samples, dict):
        return {k: list(samples.get(k) or []) for k in STEPS}
    out = {k: [] for k in STEPS}
    for s in samples or []:
        if isinstance(s, dict) and s.get("step") in out:
            out[s["step"]].append(s)
    return out


def tilt_of(g0, g):
    """Calcula o ângulo de inclinação em relação a g0 e a direção (azimute, em graus, no plano horizontal definido por g0, a partir de +x).
    O indicador circular da página usa o mesmo algoritmo (tiltOf em web/imu.js)."""
    t = angle_deg(g0, g)
    up = scale(g0, -1.0)
    d = signed_angle_deg((1.0, 0.0, 0.0), sub(g, g0), up) if unit(horiz(sub(g, g0), up)) else None
    return t, d


# ---------------- Trecho estável e referência nivelada (findHold/findRef em web/imu.js seguem esta implementação) ----------------

def _run_back(gs, end, band):
    """Percorre gs[end] para trás, agrupando leituras consecutivas com diferença ≤ band; ignora saltos isolados no meio. Retorna (índices, quantidade ignorada)."""
    last = gs[end]
    idx, skipped, j = [end], 0, end - 1
    while j >= 0:
        if angle_deg(gs[j], last) <= band:
            idx.append(j)
            j -= 1
        elif j - 1 >= 0 and angle_deg(gs[j - 1], last) <= band:
            skipped += 1                  # Salto isolado: ignora e continua percorrendo para trás.
            j -= 1
        else:
            break
    return sorted(idx), skipped


def find_hold(gs, rules=RULES):
    """Trecho estável: percorre a partir da última leitura (ou da penúltima, se a última tiver um salto) e seleciona a sequência mais longa."""
    if not gs:
        return [], 0
    best = _run_back(gs, len(gs) - 1, rules["hold_band_deg"])
    if len(gs) >= 2:
        alt = _run_back(gs, len(gs) - 2, rules["hold_band_deg"])
        if len(alt[0]) > len(best[0]) + 1:
            best = alt
    return best


def find_ref(gs, g0, before, rules=RULES):
    """Referência nivelada: encontra em gs[:before] o trecho mais recente com leituras a ≤ level_deg de g0, oscilação ≤ ref_spread_deg e pelo menos ref_min_n amostras consecutivas.
    Retorna a direção média ou None se não encontrar."""
    n = rules["ref_min_n"]
    for end in range(before, n - 1, -1):
        win = gs[end - n:end]
        if all((angle_deg(g0, v) or 0.0) <= rules["level_deg"] for v in win):
            m = mean_dir(win)
            if m is not None and spread_deg(win, m) <= rules["ref_spread_deg"]:
                return m
    return None


# ---------------- Etapas ----------------

def _r(x, nd=2):
    return None if x is None else round(x, nd)


def _gs(samples):
    return [g for g in (sample_gravity(s) for s in samples) if g is not None]


def check_still(samples, rules=RULES):
    gs = _gs(samples)
    out = {"step": "still", "name": STEP_CN["still"], "n": len(gs), "dropped": len(samples) - len(gs), "ok": False}
    if len(gs) < rules["still_min_n"]:
        out["msg"] = f"Há apenas {len(gs)} leituras em repouso (mínimo de {rules['still_min_n']}): os dados foram interrompidos ou a coleta foi curta demais"
        return out, None
    g0 = trimmed_mean_dir(gs)
    if g0 is None:
        out["msg"] = "A soma das leituras em repouso é zero; não foi possível calcular a direção"
        return out, None
    spread = spread_p90_deg(gs, g0)
    out["spread_deg"] = _r(spread)
    out["max_dev_deg"] = _r(spread_deg(gs, g0))
    if spread > rules["still_max_spread_deg"]:
        out["msg"] = f"As leituras oscilaram {spread:.1f}° em repouso (máximo de {rules['still_max_spread_deg']}°): segure firme, não toque na mesa e tente novamente"
        return out, None
    out.update(ok=True, msg="Estável")
    return out, g0


def check_tilt(step, samples, g0, rules=RULES):
    """Retorna (descrição da etapa, gravidade média do trecho estável, referência nivelada)."""
    gs = _gs(samples)
    name = STEP_CN[step]
    out = {"step": step, "name": name, "n": len(gs), "dropped": len(samples) - len(gs), "ok": False}
    if not gs:
        out["msg"] = f"Não há leituras para “{name}”"
        return out, None, None
    idx, skipped = find_hold(gs, rules)
    hold = [gs[i] for i in idx]
    ref = find_ref(gs, g0, idx[0], rules)
    out["ref"] = "Posição nivelada" if ref is not None else "Repouso na mesa"
    ref = ref or g0
    out["ref_offset_deg"] = _r(angle_deg(g0, ref))
    g = mean_dir(hold)
    tilt = angle_deg(ref, g) if g is not None else None
    tmax = max(angle_deg(ref, v) for v in hold)       # O máximo considera a maior inclinação no trecho estável, não a média.
    out.update(n_used=len(hold), skipped=skipped, tilt_deg=_r(tilt), max_tilt_deg=_r(tmax),
               spread_deg=_r(spread_deg(hold, g) if g else None))
    if len(hold) < rules["hold_min_n"] or g is None:
        out["msg"] = f"“{name}” não ficou parado depois de inclinar (apenas {len(hold)} leituras estáveis): mantenha a inclinação por 1 segundo"
        return out, None, None
    if tilt < rules["tilt_min_deg"]:
        out["msg"] = f"“{name}” inclinou apenas {tilt:.1f}°; o mínimo é {rules['tilt_min_deg']:.0f}°"
        return out, None, None
    if tmax > rules["tilt_max_deg"]:
        out["msg"] = f"“{name}” inclinou {tmax:.0f}°, acima do máximo de {rules['tilt_max_deg']:.0f}°: as patas podem escorregar e as leituras ficar instáveis"
        return out, None, None
    out.update(ok=True, msg=f"Inclinação de {tilt:.0f}°")
    return out, g, ref


# ---------------- Função principal ----------------

def solve(samples, frame="body", old_mount=None, home_gravity=DOWN, rules=None, mode="full", old_verified=True,
          old_source=None):
    """Calcula a orientação de montagem. Veja o formato de samples na documentação do módulo.
    Retorna um dict com valores que podem ser enviados diretamente em JSON.

    mode="full": cinco etapas para calibração precisa com o robô em pé.
    mode="coarse": exige repouso e inclinação para a frente; usa a inclinação para trás se disponível.
    Serve para robôs cuja orientação ainda não foi confirmada e que não conseguem ficar em pé: apoie-os com as mãos.
    O resultado deve ser verificado por verify-imu do robotd. Como a calibração aproximada não verifica os lados e
    a compensação da postura é menos precisa, faça depois a calibração completa com o robô em pé. Confira a montagem
    física do módulo antes de confirmar o resultado (plano S1).
    old_verified=False: a orientação anterior é apenas um valor padrão não verificado; não a use para detectar
    mudanças grandes ou uma rotação de 180 graus.
    old_source="coarse": a orientação anterior veio de uma calibração aproximada; ajuste o aviso de inversão
    para informar que a calibração anterior pode ter sido feita ao contrário.

    Campos retornados:
        ok         True / False
        reason     explicação do primeiro problema, quando ok=False
        redo       etapas que precisam ser refeitas
        steps      dados de cada etapa: {step, name, ok, msg, n, n_used, tilt_deg, spread_deg, skew_deg, ref, ...}
        correction [w,x,y,z]: transforma as leituras atuais no referencial do corpo
                   (quando frame="sensor", corresponde à orientação de montagem)
        mount      [w,x,y,z]: nova orientação de montagem (em frame="body", requer old_mount)
        parts      decomposição da correção: pitch_deg, roll_deg, yaw_deg, stand_tilt_deg e total_deg
        quality    métricas de qualidade, grade (good / ok / coarse) e incerteza do yaw
        standard   montagem padrão mais próxima da nova orientação e seu desvio angular
        notes      observações; confirm lista os itens que precisam ser confirmados antes de gravar
    """
    rules = dict(RULES, **(rules or {}))
    if frame not in ("body", "sensor"):
        raise ValueError("frame deve ser body ou sensor")
    if mode not in ("full", "coarse"):
        raise ValueError("mode deve ser full ou coarse")
    hg = unit(_v(home_gravity))
    if hg is None:
        raise ValueError("home_gravity é um vetor nulo")
    steps = group_steps(samples)
    res = {"ok": False, "reason": None, "redo": [], "steps": {}, "frame": frame, "mode": mode, "rules": rules,
           "notes": [], "confirm": []}
    need = TILTS if mode == "full" else ("fwd",)
    optional = () if mode == "full" else ("back",)

    st, g0 = check_still(steps["still"], rules)
    res["steps"]["still"] = st
    gs, refs = {}, {}
    for k in need + optional:
        if g0 is None:
            res["steps"][k] = {"step": k, "name": STEP_CN[k], "ok": False, "msg": "Primeiro, conclua corretamente a etapa de repouso"}
            continue
        if k in optional and not steps[k]:
            continue
        res["steps"][k], g, ref = check_tilt(k, steps[k], g0, rules)
        if g is not None:
            gs[k], refs[k] = g, ref
    bad = [res["steps"][k] for k in ("still",) + need if not res["steps"][k]["ok"]]
    bad += [res["steps"][k] for k in optional if k in res["steps"] and not res["steps"][k]["ok"]]
    if bad:
        res["reason"] = bad[0]["msg"]
        # Se o repouso falhar, basta refazer essa etapa; as inclinações podem ser recalculadas com as leituras existentes.
        res["redo"] = ["still"] if g0 is None else [b["step"] for b in bad]
        return res

    up = scale(g0, -1.0)
    # Origem do azimute: eixo +x projetado no plano horizontal; se estiver vertical, use +y.
    axis0 = unit(horiz((1.0, 0.0, 0.0), up)) or unit(horiz((0.0, 1.0, 0.0), up))
    c = {}
    for k in gs:
        d = horiz(sub(gs[k], refs[k]), up)
        az = signed_angle_deg(axis0, d, up)
        if az is None:
            res["reason"] = f"Não foi possível calcular a direção de {STEP_CN[k].lower()}; refaça esta etapa"
            res["redo"] = [k]
            return res
        c[k] = wrap180(az - EXPECT_DIR[k])      # Direção para a qual esta etapa considera que fica a frente.
    q = {}
    res["quality"] = q

    def pair(a, b):
        if a in c and b in c:
            d = abs(wrap180(c[a] - c[b]))
            q[f"{'fb' if a == 'fwd' else 'lr'}_pair_deg"] = _r(d)
            if d > rules["pair_max_deg"]:
                res["reason"] = (f"As direções de {STEP_CN[a].lower()} e {STEP_CN[b].lower()} não coincidem "
                                 f"(diferença de {d:.0f}°; deveriam ser opostas): as inclinações foram feitas "
                                 "para o mesmo lado?")
                res["redo"] = [a, b]
                return False
        return True

    if not pair("fwd", "back") or not pair("left", "right"):
        return res
    if mode == "full":
        psi_fb = circ_mean_deg([c["fwd"], c["back"]])
        psi_lr = circ_mean_deg([c["left"], c["right"]])
        crs = abs(wrap180(psi_fb - psi_lr))
        q["cross_deg"] = _r(crs)
        if crs > 90.0:
            res["reason"], res["redo"] = _swapped_reason(psi_fb, psi_lr, frame == "body" and old_verified)
            return res
    psi = circ_mean_deg(list(c.values()))
    skews = {k: wrap180(c[k] - psi) for k in c}
    for k, s in skews.items():
        res["steps"][k]["skew_deg"] = _r(abs(s))
    worst = max(skews, key=lambda k: abs(skews[k]))
    q["max_skew_deg"] = _r(abs(skews[worst]))
    if abs(skews[worst]) > rules["skew_max_deg"]:
        res["reason"] = (f"“{STEP_CN[worst]}” desviou {abs(skews[worst]):.0f}° (a inclinação deve seguir "
                         f"exatamente para {STEP_CN[worst].lower()}): siga a seta 3D e não gire a mão")
        res["redo"] = [worst]
        return res
    if mode == "full":
        if crs > rules["cross_max_deg"]:
            res["reason"] = (f"As inclinações para a frente/trás e para os lados não estão perpendiculares "
                             f"(diferença de {crs:.0f}°; a direção terá metade desse erro): talvez sua mão tenha girado "
                             "durante a inclinação. Siga as setas 3D para frente, trás, esquerda e direita.")
            # Com orientação anterior confiável, refaça o par mais distante da frente atual; caso contrário, refaça as quatro etapas.
            if frame == "body" and old_verified:
                res["redo"] = ["left", "right"] if abs(wrap180(psi_lr)) > abs(wrap180(psi_fb)) else ["fwd", "back"]
            else:
                res["redo"] = list(TILTS)
            return res
        q["grade"] = "good" if crs <= rules["good_cross_deg"] and abs(skews[worst]) <= rules["good_skew_deg"] else "ok"
        q["yaw_uncert_deg"] = _r(max(crs / 2, 0.5))
    else:
        q["grade"] = "coarse"
        res["notes"].append("Calibração aproximada: foram usadas apenas as etapas de repouso e inclinação para a frente; "
                            "os lados não foram verificados e a compensação da postura é imprecisa porque o robô foi "
                            "apoiado. Faça a calibração completa quando ele conseguir ficar em pé.")
    p = math.radians(psi)
    x_dir = add(scale(axis0, math.cos(p)), scale(cross(up, axis0), math.sin(p)))
    return _finish(res, g0, up, x_dir, hg, frame, old_mount, old_verified, old_source, rules)


def _swapped_reason(psi_fb, psi_lr, trust_old):
    """Os pares frente/trás e esquerda/direita diferem cerca de 180°: um foi invertido.
    Se a orientação anterior for confiável, o par mais distante da frente atual é o invertido.
    Retorna (motivo, etapas a refazer)."""
    if trust_old:
        if abs(wrap180(psi_lr)) > abs(wrap180(psi_fb)):
            return "As inclinações para a esquerda e para a direita foram invertidas: use os lados do robô como referência (de frente para ele, a esquerda dele fica à sua direita).", ["left", "right"]
        return "As inclinações para a frente e para trás foram invertidas: para inclinar para a frente, abaixe o lado da cabeça.", ["fwd", "back"]
    return ("Um dos pares frente/trás ou esquerda/direita foi invertido. Para inclinar para a frente, abaixe o lado da cabeça; use os lados do robô como referência (de frente para ele, a esquerda dele fica à sua direita).",
            list(TILTS))


def _finish(res, g0, up, x_dir, hg, frame, old_mount, old_verified, old_source, rules):
    """Usa “cima” e “frente” para obter os três eixos, calcular correção e nova orientação, e verificar confirmações."""
    y = unit(cross(up, x_dir))
    x = cross(y, up)
    r_lm = (x, y, up)                        # Linhas: eixos do referencial horizontal L; v_L = R_LM · v_M
    r_bl = mat_from_q(q_between(DOWN, hg))   # Postura do corpo no HOME em relação ao referencial horizontal (yaw = 0)
    r_bm = mat_mul(r_bl, r_lm)
    corr = q_from_mat(r_bm)
    res["correction"] = [round(c, 9) for c in corr]

    # Decompõe a postura (pitch e roll) e a direção (yaw).
    hp = math.degrees(math.atan2(hg[0], -hg[2]))
    hroll = math.degrees(math.atan2(hg[1], -hg[2]))
    parts = {"total_deg": _r(q_angle_deg(corr))}
    if frame == "body":
        parts["pitch_deg"] = _r(math.degrees(math.atan2(g0[0], -g0[2])) - hp)
        parts["roll_deg"] = _r(math.degrees(math.atan2(g0[1], -g0[2])) - hroll)
        parts["yaw_deg"] = _r(signed_angle_deg((1.0, 0.0, 0.0), x, up))
        parts["stand_tilt_deg"] = _r(angle_deg(g0, hg))
    res["parts"] = parts

    # Nova orientação.
    if frame == "sensor":
        mount = corr
    elif old_mount is not None:
        mount = compose_mount(corr, q_normalize(old_mount))
    else:
        mount = None
        res["notes"].append("A orientação de montagem anterior não foi informada; só é possível calcular a correção, não a nova orientação.")
    if mount is not None:
        res["mount"] = [round(c, 9) for c in mount]
        res["standard"] = describe_mount(mount)

    # Observações e confirmações necessárias.
    full = res["mode"] == "full"
    if frame == "body" and old_verified and parts.get("yaw_deg") is not None:
        tot = q_angle_deg(corr)
        if abs(parts["yaw_deg"]) > rules["flip_deg"]:
            if old_source == "coarse":
                res["confirm"].append(
                    f"A direção precisa mudar {parts['yaw_deg']:+.0f}°: a calibração aproximada anterior pode ter sido invertida "
                    "(ela verificou apenas a frente, não os lados). Confira a montagem física do módulo e confirme o resultado antes de gravar.")
            else:
                res["confirm"].append(
                    f"A direção precisa mudar {parts['yaw_deg']:+.0f}°. Provavelmente os pares frente/trás e esquerda/direita foram invertidos "
                    "(como se o robô tivesse girado). Grave assim somente se o módulo IMU realmente foi instalado girado.")
        elif tot > rules["big_change_deg"]:
            res["confirm"].append(f"A orientação difere {tot:.1f}° da atual, uma mudança considerável. O módulo foi inclinado ou montado de outro jeito? Confirme antes de gravar.")
    if frame == "body" and full:
        st = parts["stand_tilt_deg"]
        if st is not None and st > rules["stand_confirm_deg"]:
            res["confirm"].append(
                f"Em pé, a leitura difere {st:.1f}° do HOME oficial (o programa principal tolera apenas "
                f"{rules['stand_confirm_deg']:.0f}° ao verificar a orientação): talvez o zero das patas não esteja calibrado, "
                "a mesa esteja desnivelada ou alguém tenha tocado no robô durante os 3 segundos de repouso. Grave somente se confirmar que o módulo está inclinado.")
        res["notes"].append(
            f"Em pé, a leitura tem inclinação de {parts['pitch_deg']:+.1f}° para a frente e {parts['roll_deg']:+.1f}° para a esquerda "
            "em relação ao HOME oficial; essa diferença será incorporada à orientação de montagem "
            "(o IMU sozinho não distingue um módulo inclinado de uma postura causada pelas patas; calibre primeiro o zero delas).")
    if not full and res.get("standard"):
        s = res["standard"]
        res["confirm"].append(
            f"Resultado da calibração aproximada: {s['text']}" + (f" (desvio de {s['off_deg']:.0f}°)" if s["off_deg"] >= 1 else "")
            + ". Compare com a montagem física do módulo e grave somente se corresponder (se estiver invertida, o programa principal não consegue verificar os lados).")
    if res.get("standard") and res["standard"]["off_deg"] > 20:
        res["notes"].append(f"A nova orientação difere {res['standard']['off_deg']:.0f}° da montagem padrão mais próxima "
                            f"({res['standard']['text']}); o módulo foi instalado inclinado?")
    res["ok"] = True
    return res
