"""Script de critérios para avaliação no robô (somente leitura e biblioteca padrão): aplica as regras de parada a um trecho de gravação duck_rec (RobotState JSONL, 50 Hz).
Uso: python judge_block.py video.jsonl [segundo_inicial segundo_final] (segundos relativos ao wall do primeiro quadro do arquivo).

Regra de degraus da versão de 10-15, revisada com dados-sombra do robô real e revisão independente; consulte a seção 5.5 do documento de integração da IMU para o histórico.
Degrau = diferença >5° entre a gravidade deste quadro e a gravidade do quadro anterior extrapolada por 20 ms com o giroscópio. Conta somente quadros de marcha em pé (policy == walk, torque ativo, safety.fallen falso).
  Caminho publicado = safety.gravity (no modo gyro, é a postura fundida vista pela política), com o giroscópio deste quadro; ambos passam pela mediana de três pontos e têm o atraso alinhado.
  Caminho-sombra = imu.fusion.fused (valor fundido bruto no modo chip, sem filtro de mediana), com o giroscópio do quadro seguinte (na gravação, o giroscópio filtrado chega um quadro depois).
Cada degrau é classificado pelas decisões de fusão nos ±2 quadros ao redor:
  Rígido: inclui realign_long / realign_gap / fallback / follow (somente esses quatro podem saltar um quadro completo na fusão); um único caso exige voltar ao modo chip, sem exceções.
  Suave: inclui somente accepted / rejected / slew (fazem apenas integração ou correções de até 0,1° por quadro; não podem causar salto de um quadro inteiro):
      dentro de 1,0 s antes do início de uma queda ou com inclinação publicada no quadro anterior ≥30° (o robô já está tombando, mas a detecção ainda não acompanhou): isento, apenas registrado;
      caso contrário, 3 ou mais por segmento exigem voltar ao modo chip; 1–2 são registrados e devem ser analisados individualmente após o segmento.
Também lista quadros em pé e caminhando com decisão rígida (compare as contagens antes/depois do segmento: aumentos de realign/fallback devem corresponder na gravação a uma queda ou ao estado HOME; se não corresponderem, trate como salto real).
Em repouso: divide quadros contínuos com policy == held, torque ativo e |ω| < 20°/s em janelas de 10 s. Em cada janela, mediana θ ≤0,5° e P90 ≤1° (quadros inclinados ou empurrados são removidos naturalmente pelo limite de |ω|).
"""
import json, math, sys

HARD = {'realign_long', 'realign_gap', 'fallback', 'follow'}
PRE_FALL, TILT_EXEMPT, STEP_DEG, SOFT_MAX = 1.0, 30.0, 5.0, 3


def grav(q):
    w, x, y, z = q
    return (-2 * (x * z - w * y), -2 * (y * z + w * x), -(1 - 2 * (x * x + y * y)))


def ang(a, b):
    c = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return math.degrees(math.atan2(math.sqrt(sum(v*v for v in c)), sum(x*y for x, y in zip(a, b))))


def step(g0, g1, w, dt):
    pr = (g0[0] - (w[1]*g0[2] - w[2]*g0[1])*dt, g0[1] - (w[2]*g0[0] - w[0]*g0[2])*dt, g0[2] - (w[0]*g0[1] - w[1]*g0[0])*dt)
    return ang(pr, g1)


def tilt(g):
    n = math.sqrt(sum(v * v for v in g)) or 1.0
    return math.degrees(math.acos(max(-1.0, min(1.0, -g[2] / n))))


def wdeg(r):
    return math.degrees(math.sqrt(sum(v * v for v in r['imu']['gyro'])))


rows = []
for line in open(sys.argv[1], encoding='utf-8'):
    try: r = json.loads(line)
    except ValueError: continue
    if 'imu' in r and 'safety' in r and 'wall' in r: rows.append(r)
rows.sort(key=lambda r: r['wall'])
if not rows:
    sys.exit('Nenhum quadro de estado foi encontrado na gravação')
T0 = rows[0]['wall']
if len(sys.argv) >= 4:
    a, b = float(sys.argv[2]), float(sys.argv[3]); rows = [r for r in rows if a <= r['wall'] - T0 <= b]
fus = lambda r: (r['imu'] or {}).get('fusion') or {}
up = lambda r: r['policy'] == 'walk' and not r['safety']['limp'] and not r['safety'].get('fallen')
modes = {'chip' if fus(r).get('fused') else 'gyro' if fus(r).get('chip') else 'old' for r in rows}
falls = [rows[i]['wall'] for i in range(1, len(rows)) if rows[i]['safety'].get('fallen') and not rows[i-1]['safety'].get('fallen')]


def verdicts_near(i):
    return [fus(rows[j]).get('verdict') for j in range(max(0, i - 2), min(len(rows), i + 3))]


def classify(i):
    """rigidez / isenção / suavidade e justificativa."""
    vs = verdicts_near(i)
    if HARD & set(vs):
        return 'Rígida', vs
    t = rows[i]['wall']
    nf = min((f - t for f in falls if f >= t), default=None)
    if nf is not None and nf <= PRE_FALL:
        return 'Isenta (%.2f s antes da queda)' % nf, vs
    if tilt(rows[i - 1]['safety']['gravity']) >= TILT_EXEMPT:
        return 'Isenta (inclinação do quadro anterior: %.0f°)' % tilt(rows[i - 1]['safety']['gravity']), vs
    return 'Suave', vs


up_frames, up_time = 0, 0.0
pub, shadow = [], []
for i in range(1, len(rows)):
    p, c = rows[i - 1], rows[i]
    dt = c['wall'] - p['wall']
    if not 0.015 < dt < 0.03 or not (up(c) and up(p)):
        continue
    up_frames += 1; up_time += dt
    e = step(p['safety']['gravity'], c['safety']['gravity'], c['imu']['gyro'], dt)
    if e > STEP_DEG:
        pub.append((i, e))
    fp, fc = fus(p), fus(c)
    if fp.get('fused') and fc.get('fused') and i + 1 < len(rows):
        e2 = step(grav(fp['fused']), grav(fc['fused']), rows[i + 1]['imu']['gyro'], dt)
        if e2 > STEP_DEG:
            shadow.append((i, e2))

print(f'Quadros: {len(rows)}; modos: {sorted(modes)}; marcha em pé: {up_frames} quadros / {up_time:.0f} s; início de quedas: {len(falls)} — {[round(f - T0, 1) for f in falls]}')


def report(name, steps, judge):
    counts = {'Rígida': 0, 'Suave': 0, 'Isenta': 0}
    lines = []
    for i, e in steps:
        cls, vs = classify(i)
        counts['Isenta' if cls.startswith('Isenta') else cls] += 1
        nxt = wdeg(rows[i + 1]) if i + 1 < len(rows) else float('nan')
        lines.append('   t=%.2f  %.1f°  %s  |ω| %.0f→%.0f°/s  decisões em ±2 quadros %s' % (rows[i]['wall'] - T0, e, cls, wdeg(rows[i]), nxt, vs))
    print(f'{name}: {len(steps)} degraus >5° → rígidos {counts["Rígida"]}, suaves {counts["Suave"]}, isentos {counts["Isenta"]}')
    for l in lines[:30]: print(l)
    if len(lines) > 30: print('   … (%d itens no total)' % len(lines))
    if judge:
        if counts['Rígida']:
            print('   → Volte ao modo chip: houve degrau rígido (salto de um quadro perto do realinhamento da fusão)')
        elif counts['Suave'] >= SOFT_MAX:
            print(f'   → Volte ao modo chip: {counts["Suave"]} degraus suaves ≥{SOFT_MAX} (possível problema sistemático nos critérios ou no eixo)')
        elif counts['Suave']:
            print(f'   → Continue, mas analise individualmente estes {counts["Suave"]} casos após o segmento')
        else:
            print('   → Nenhum critério acionado')


report('Caminho publicado (safety.gravity, visto pela política)', pub, judge='gyro' in modes)
if 'chip' in modes:
    print('   (no modo chip, a postura publicada vem do chip; acima serve apenas de referência e não aciona a regra de parada)')
    report('Caminho-sombra (imu.fusion.fused, pareado com o giroscópio do próximo quadro)', shadow, judge=False)

hard_frames = [(r['wall'] - T0, fus(r).get('verdict'), up(r)) for r in rows if fus(r).get('verdict') in HARD]
if hard_frames:
    up_hard = [h for h in hard_frames if h[2]]
    print(f'Quadros com decisão rígida (a gravação mantém somente a última decisão reportada por quadro): {len(hard_frames)} no total, {len(up_hard)} durante marcha em pé')
    for t, v, u in hard_frames[:15]:
        after = [round(t - (f - T0), 2) for f in falls if 0 <= t - (f - T0) <= 10]
        print('   t=%.2f  %s  %s%s' % (t, v, 'marcha em pé' if u else 'fora da marcha em pé', ('  %s s após a queda' % after[-1]) if after else ''))
    if up_hard:
        print('   → Há uma decisão rígida durante marcha em pé: confira as contagens e a gravação. Se não ocorreu após uma queda ou em HOME, volte ao modo chip')

vs_all, vs_up = {}, {}
for r in rows:
    v = fus(r).get('verdict')
    if v:
        vs_all[v] = vs_all.get(v, 0) + 1
        if up(r): vs_up[v] = vs_up.get(v, 0) + 1
if vs_all:
    print('Decisões (todos os quadros):', vs_all); print('Decisões (quadros de marcha em pé):', vs_up)

# Repouso em pé: divide em janelas de 10 s os quadros contínuos held, com torque ativo e |ω|<20°/s.
wins, cur = [], []
for r in rows:
    ok = r['policy'] == 'held' and not r['safety']['limp'] and wdeg(r) < 20 and 'theta_deg' in fus(r)
    if ok and cur and r['wall'] - cur[0]['wall'] >= 10:
        wins.append(cur); cur = []
    if ok:
        if cur and r['wall'] - cur[-1]['wall'] > 0.1:
            if cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
            cur = []
        cur.append(r)
    elif cur:
        if cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
        cur = []
if cur and cur[-1]['wall'] - cur[0]['wall'] >= 5: wins.append(cur)
if wins:
    bad = []
    worst = (0, 0)
    for wv in wins:
        th = sorted(fus(r)['theta_deg'] for r in wv); n = len(th)
        med, p90 = th[n // 2], th[min(n - 1, int(n * .9))]
        worst = (max(worst[0], med), max(worst[1], p90))
        if med > 0.5 or p90 > 1.0: bad.append((round(wv[0]['wall'] - T0, 1), round(med, 3), round(p90, 3)))
    tot = sum(wv[-1]['wall'] - wv[0]['wall'] for wv in wins)
    print(f'Repouso em HOME: {len(wins)} janelas (total de {tot:.0f} s); pior janela: mediana θ {worst[0]:.3f}°, P90 {worst[1]:.3f}°'
          + (f'; janelas fora do limite {bad} → voltar ao modo chip' if bad else '; todas dentro dos limites de mediana ≤0,5° e P90 ≤1°'))
else:
    print('Não há janelas de repouso HOME (held, torque ativo, |ω|<20°/s e duração ≥5 s)')
