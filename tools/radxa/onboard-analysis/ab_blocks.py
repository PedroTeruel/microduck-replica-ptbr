"""Análise A/B: conta as quedas de cada gravação, calcula quedas por minuto e compara os totais dos modos chip e gyro (somente leitura).

Uso:
  python ab_blocks.py chip1=video1.jsonl gyro1=video2.jsonl chip2=... gyro2=...
  python ab_blocks.py chip1=video.jsonl@120-300     # analisa somente do segundo 120 ao 300 desta gravação, medido por wall
As etiquetas devem começar com chip ou gyro para entrar na comparação; gravações antigas podem usar old e serão apenas resumidas individualmente. Outros prefixos são inválidos e excluídos.
O modo efetivo é identificado na gravação: imu.fusion com fused indica chip; com chip indica gyro; sem imu.fusion indica versão antiga.
Se a etiqueta não corresponder ao modo gravado, registra [erro] e exclui o trecho.

Critérios:
  Quadro de marcha em pé = policy == walk, torque ativo (safety.limp falso) e sem queda (safety.fallen falso).
  Conta somente quadros de marcha em pé com inclinação ≤30° (exclui robô tombado, inclinado ou sendo segurado); o tempo é calculado pela diferença de wall e lacunas >0,1 s não contam.
  Uma queda = transição de safety.fallen para verdadeiro após quadros de marcha em pé; transições a menos de 3 s do fim da queda anterior pertencem ao mesmo evento (a detecção de queda pode oscilar).
            Transições fora da caminhada (held, homing etc.) ou com torque desativado são listadas separadamente e não entram na contagem. O registro informa o intervalo desde a queda anterior para permitir revisar os casos próximos ao limite de 3 s.
  Queda após comando do joystick = queda precedida pelo acionamento do joystick nos 2 s anteriores à transição.
  Métrica principal = quedas por minuto de joystick acionado = quedas após comando / minutos de acionamento (o operador deve manter igual o tempo de acionamento nos dois modos; o tempo parado sem acionar não depende do modo).
  Referência = quedas por minuto de marcha em pé = todas as quedas / minutos de marcha em pé. Informe se as conclusões divergirem entre os dois denominadores.
  Segmento de caminhada = sequência contínua de quadros de marcha em pé (lacunas <0,2 s são permitidas); uma queda até 1 s após o fim marca o segmento como encerrado por queda.
  Degrau do chip = extrapola a gravidade do quadro anterior usando o giroscópio deste quadro e compara com a gravidade atual; diferença >5° (mesmo critério de judge_block / glitch_rate), contando somente quadros de marcha em pé.
            Caminho do chip: usa safety.gravity nos modos chip e antigo; no modo gyro, usa imu.fusion.chip e aplica o mesmo processamento de safety.gravity:
            normalização e mediana de três pontos por componente. Assim os modos ficam comparáveis. Em verdict == disabled, a postura publicada já vem do chip; classifique como chip.
  Degrau publicado = mesmo critério aplicado a safety.gravity (o valor visto pela política); deve ficar perto de zero no modo gyro.
  Degrau pré-queda = degrau no caminho do chip até 1,5 s antes da queda. Sem referência de base: a proporção em qualquer intervalo aleatório de 1,5 s após acionar o joystick já é 12–47%; use somente como referência.
  Tremor do tronco (limite de proteção) = RMS (°/s) das velocidades angulares de rolagem e inclinação em trechos de marcha em pé com joystick acionado, inclinação ≤30°, duração ≥1,5 s e sem queda nos 2 s após o fim;
            gyro não deve exceder chip em mais de 10%. A métrica original, que inclui tropeços pré-queda, também é listada como referência (ela pode contar novamente o próprio evento de queda).
  Se quadros de marcha em pé no modo minoritário excederem 1 s, exclui o trecho (houve mudança de modo; divida a gravação no instante da mudança).
Comparação: soma separadamente cada modo e calcula a razão gyro/chip. O valor p usa teste binomial condicional exato (com total de quedas fixo, verifica se a proporção de quedas no gyro diverge da proporção de tempo).
      O intervalo de 95% usa Clopper-Pearson. Defina antes da execução o número e a ordem dos trechos (chip, gyro, gyro, chip...); não decida adicionar trechos após observar o valor p.
Registros: classificação e nível em ab_blocks.log, no diretório da primeira gravação; o relatório é anexado a ab_report.txt.
Primeira versão de 10-15 revisada de forma independente e atualizada conforme a revisão: etiquetas old/desconhecidas excluídas; mediana aplicada ao caminho chip do gyro;
  tempo limitado a inclinação ≤30°; denominador pelo tempo de joystick acionado; indicador de proteção exclui trecho pré-queda; disabled conta como chip; trechos com modos misturados excluídos; erros de parâmetros tratados; aviso para reutilização da mesma gravação.
"""
import json
import math
import os
import sys
import time

GAP = 0.1            # Intervalos entre quadros acima deste valor não contam no tempo.
SEG_GAP = 0.2        # Lacuna permitida dentro de um segmento de caminhada.
MERGE = 3.0          # Janela para agrupar oscilações na detecção de queda.
PRE_FALL = 1.5       # Intervalo observado antes da queda.
STEP_DEG = 5.0
SHAKE_MIN = 1.5
TILT_MAX = 30.0      # Tempo e tremor consideram somente marcha em pé com inclinação ≤30° (exclui robô tombado ou sendo segurado).
STICK_RECENT = 2.0   # Acionamento do joystick neste intervalo antes da transição classifica a queda como precedida por comando.
SHAKE_SKIP = 2.0     # Tremor considera somente segmentos sem queda durante este intervalo após o fim.
MIX_MAX = 50         # Mais quadros que este limite no modo minoritário (1 s) causam erro no trecho.

LOG = None


def log(cat, level, msg):
    line = '%s [%s][%s] %s' % (time.strftime('%H:%M:%S'), level, cat, msg)
    if LOG:
        LOG.write(line + '\n')
        LOG.flush()
    if level != 'INFO':
        print(line, file=sys.stderr)


def grav(q):
    w, x, y, z = q
    return (-2 * (x * z - w * y), -2 * (y * z + w * x), -(1 - 2 * (x * x + y * y)))


def ang(a, b):
    c = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return math.degrees(math.atan2(math.sqrt(sum(v * v for v in c)), sum(x * y for x, y in zip(a, b))))


def step(g0, g1, w, dt):
    pr = (g0[0] - (w[1] * g0[2] - w[2] * g0[1]) * dt, g0[1] - (w[2] * g0[0] - w[0] * g0[2]) * dt,
          g0[2] - (w[0] * g0[1] - w[1] * g0[0]) * dt)
    return ang(pr, g1)


def fusion(r):
    return (r.get('imu') or {}).get('fusion')


def frame_mode(r):
    f = fusion(r)
    if not f:
        return 'old'
    if f.get('fused') is not None:
        return 'chip'
    if f.get('chip') is not None:
        # Em disabled, o valor publicado já vem do chip (bno08x.rs sample()/HostImuSample.quat); classifique como chip.
        return 'chip' if f.get('verdict') == 'disabled' else 'gyro'
    return '?'


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v) if n > 0 else None


def chip_gravs(rows, mode):
    """Gravidade por quadro no caminho do chip. No modo gyro, imu.fusion.chip não passa pela mediana; aplique aqui o mesmo processamento que
    safety.gravity (normalização e mediana de três pontos por componente, reiniciada após lacunas) para permitir comparar os dois modos."""
    if mode != 'gyro':
        return [r['safety']['gravity'] for r in rows]
    raw = []
    for r in rows:
        f = fusion(r)
        raw.append(_norm(grav(f['chip'])) if f and f.get('chip') else None)
    out, hist = [], []
    for i, g in enumerate(raw):
        if g is None or (i and rows[i]['wall'] - rows[i - 1]['wall'] > GAP):
            hist = []
        if g is None:
            out.append(None)
            continue
        hist = (hist + [g])[-3:]
        h = hist if len(hist) == 3 else [hist[0]] * (3 - len(hist)) + hist
        out.append(tuple(sorted(c)[1] for c in zip(*h)))
    return out


def tilt(r):
    g = r['safety']['gravity']
    n = math.sqrt(sum(v * v for v in g))
    return math.degrees(math.acos(max(-1.0, min(1.0, -g[2] / n)))) if n > 0 else 0.0


def upright(r):
    return r['policy'] == 'walk' and not r['safety']['limp'] and not r['safety'].get('fallen')


def upright_t(r):
    """Usado na contagem de tempo: marcha em pé e inclinação ≤ TILT_MAX. Os degraus ainda usam upright() para não excluir quadros em que o salto do chip excedeu 30°."""
    return upright(r) and tilt(r) <= TILT_MAX


def stick(r):
    req = (r.get('move') or {}).get('requested') or [0, 0, 0]
    return max(abs(v) for v in req) > 1e-6


def load(path, window):
    rows, bad = [], 0
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if 'imu' in r and 'safety' in r and 'wall' in r:
                rows.append(r)
    rows.sort(key=lambda r: r['wall'])
    if bad:
        log('Leitura', 'WARN', '%s: %d linhas não são JSON e foram ignoradas' % (path, bad))
    if not rows:
        return rows
    if window:
        w0 = rows[0]['wall']
        rows = [r for r in rows if window[0] <= r['wall'] - w0 <= window[1]]
    return rows


def analyze(label, path, window):
    rows = load(path, window)
    out = {'label': label, 'path': path, 'frames': len(rows)}
    if len(rows) < 2:
        log('Leitura', 'ERROR', '%s: poucos quadros (%d)' % (label, len(rows)))
        out['error'] = 'Poucos quadros'
        return out
    modes = {}
    for r in rows:
        m = frame_mode(r)
        modes[m] = modes.get(m, 0) + 1
    mode = max(modes, key=modes.get)
    out['modes'] = modes
    out['mode'] = mode
    # Aceita etiquetas iniciadas por chip/gyro/old; somente chip/gyro entram na comparação (consulte main).
    want = next((m for m in ('chip', 'gyro', 'old') if label.startswith(m)), None)
    out['want'] = want
    if want is None:
        log('Parâmetros', 'ERROR', '%s: a etiqueta deve começar com chip / gyro / old; trecho excluído' % label)
        out['error'] = 'Etiqueta desconhecida'
    if len(modes) > 1:
        log('Segmentação', 'WARN', '%s: o trecho contém vários modos %s (o modo pode ter mudado durante a gravação); usando o modo predominante %s' % (label, modes, mode))
        # Se o modo minoritário aparecer por mais de 1 s durante marcha em pé, exclui o trecho para evitar misturar modos.
        minority_up = sum(1 for r in rows if upright(r) and frame_mode(r) != mode)
        if minority_up > MIX_MAX:
            log('Segmentação', 'ERROR', '%s: %d quadros de marcha em pé no modo diferente de %s (>%d); trecho excluído. Separe no instante da mudança' % (
                label, mode, minority_up, MIX_MAX))
            out['error'] = 'Trecho mistura outro modo (%d quadros de marcha em pé)' % minority_up
    if want in ('chip', 'gyro') and mode != want:
        log('Segmentação', 'ERROR', '%s: etiqueta indica %s, mas a gravação está no modo %s; trecho excluído' % (label, want, mode))
        out['error'] = 'Modo divergente (gravação em %s)' % mode
    verdicts = {}
    for r in rows:
        f = fusion(r)
        if f and upright(r):
            verdicts[f.get('verdict')] = verdicts.get(f.get('verdict'), 0) + 1
    out['verdicts_up'] = verdicts

    t_up = t_stick = t_tilted = 0.0
    gaps = 0
    chip_steps, pub_steps = [], []
    cg = chip_gravs(rows, mode)
    for i in range(1, len(rows)):
        p, c = rows[i - 1], rows[i]
        dt = c['wall'] - p['wall']
        if dt > GAP:
            gaps += 1
            continue
        if not (upright(c) and upright(p)):
            continue
        if upright_t(c) and upright_t(p):
            t_up += dt
            if stick(c):
                t_stick += dt
        else:
            t_tilted += dt
        if not 0.005 < dt < 0.05:
            continue
        w = c['imu']['gyro']
        if step(p['safety']['gravity'], c['safety']['gravity'], w, dt) > STEP_DEG:
            pub_steps.append(c['wall'])
        g0, g1 = cg[i - 1], cg[i]
        if g0 and g1 and step(g0, g1, w, dt) > STEP_DEG:
            chip_steps.append(c['wall'])
    if gaps:
        log('Leitura', 'WARN', '%s: %d intervalos entre quadros >%.1f s (gravação interrompida); não contabilizados' % (label, gaps, GAP))
    if t_tilted:
        log('Estatísticas', 'INFO', '%s: %.1f s em marcha em pé com inclinação >%.0f°; tempo excluído (robô tombado ou sendo segurado)' % (label, t_tilted, TILT_MAX))
    out.update(t_up=t_up, t_stick=t_stick, t_tilted=t_tilted, chip_steps=len(chip_steps), pub_steps=len(pub_steps))

    # Eventos de queda: identifica segmentos contínuos de fallen e agrupa as oscilações na detecção.
    runs, cur = [], None
    for i, r in enumerate(rows):
        f = bool(r['safety'].get('fallen'))
        if f and cur is None:
            cur = i
        elif not f and cur is not None:
            runs.append((cur, i))
            cur = None
    if cur is not None:
        runs.append((cur, len(rows) - 1))
    falls, other = [], []
    since = {}
    falls_stick = []
    last_end = None
    for a, b in runs:
        merged = last_end is not None and rows[a]['wall'] - last_end < MERGE
        gap_prev = None if last_end is None else rows[a]['wall'] - last_end
        last_end = rows[b]['wall']
        if merged:
            continue
        prev = rows[a - 1] if a > 0 else None
        if prev is not None and prev['policy'] == 'walk' and not prev['safety']['limp']:
            ft = rows[a]['wall']
            falls.append(ft)
            since[ft] = gap_prev
            # Joystick acionado nos STICK_RECENT segundos antes da transição: queda após comando (denominador = tempo de acionamento).
            j = a - 1
            while j >= 0 and ft - rows[j]['wall'] <= STICK_RECENT:
                if stick(rows[j]):
                    falls_stick.append(ft)
                    break
                j -= 1
        else:
            other.append((rows[a]['wall'], rows[a]['policy'], rows[a]['safety']['limp']))
    w0 = rows[0]['wall']
    for wt, pol, limp in other:
        log('Queda', 'INFO', '%s: detecção de queda em %.1f s, estado %s, torque desativado %s; não contabilizada' % (label, wt - w0, pol, limp))
    out['falls'] = len(falls)
    out['falls_stick'] = len(falls_stick)
    out['other_falls'] = len(other)

    # Segmentos de caminhada.
    segs, cur = [], None
    for p, c in zip(rows, rows[1:]):
        if upright(c) and c['wall'] - p['wall'] <= SEG_GAP and (upright(p) or cur is None):
            if cur is None:
                cur = [c['wall'], c['wall']]
            cur[1] = c['wall']
        elif cur is not None:
            segs.append(cur)
            cur = None
    if cur is not None:
        segs.append(cur)
    segs = [s for s in segs if s[1] - s[0] >= 0.5]
    ended = []
    for s in segs:
        hit = any(0 <= ft - s[1] <= 1.0 for ft in falls)
        ended.append((s[1] - s[0], hit))
    out['segs'] = len(segs)
    out['segs_fall'] = sum(1 for _, h in ended if h)
    fall_durs = sorted(d for d, h in ended if h)
    out['median_to_fall'] = fall_durs[len(fall_durs) // 2] if fall_durs else None
    # Tempo acumulado de marcha em pé antes da primeira queda do trecho.
    acc, first = 0.0, None
    if falls:
        for p, c in zip(rows, rows[1:]):
            if c['wall'] >= falls[0]:
                break
            dt = c['wall'] - p['wall']
            if dt <= GAP and upright_t(c) and upright_t(p):
                acc += dt
        first = acc
    out['first_fall'] = first
    out['pre_step'] = sum(1 for ft in falls if any(ft - PRE_FALL <= st < ft for st in chip_steps))
    for ft in falls:
        pre = [st for st in chip_steps if ft - PRE_FALL <= st < ft]
        log('Queda', 'INFO', '%s: queda em %.1f s (%s; intervalo desde o fim da queda anterior: %s); %d degraus do chip nos %.1f s anteriores' % (
            label, ft - w0, 'com comando do joystick' if ft in falls_stick else 'sem comando do joystick',
            '—' if since[ft] is None else '%.1f s' % since[ft], PRE_FALL, len(pre)))

    # Tremor do tronco.
    # O limite de proteção considera somente segmentos com joystick acionado, inclinação ≤ TILT_MAX e sem queda durante SHAKE_SKIP após o fim. A métrica original incluía tropeços pré-queda,
    # medindo na prática a própria queda; o valor original também é salvo em *_all para referência.
    def shake_segs(ok):
        ss, cur = [], []
        for r in rows:
            if ok(r):
                if cur and r['wall'] - cur[-1]['wall'] > SEG_GAP:
                    ss.append(cur)
                    cur = []
                cur.append(r)
            elif cur:
                ss.append(cur)
                cur = []
        if cur:
            ss.append(cur)
        return [s for s in ss if s[-1]['wall'] - s[0]['wall'] >= SHAKE_MIN]
    for key, fr in (
            ('', [r for s in shake_segs(lambda r: upright_t(r) and stick(r))
                  if not any(0 <= ft - s[-1]['wall'] <= SHAKE_SKIP for ft in falls) for r in s]),
            ('_all', [r for s in shake_segs(lambda r: upright(r) and stick(r)) for r in s])):
        if fr:
            out['roll_rms' + key] = math.degrees(math.sqrt(sum(r['imu']['gyro'][0] ** 2 for r in fr) / len(fr)))
            out['pitch_rms' + key] = math.degrees(math.sqrt(sum(r['imu']['gyro'][1] ** 2 for r in fr) / len(fr)))
            out['shake_s' + key] = len(fr) / 50
    log('Estatísticas', 'INFO', '%s: %s' % (label, {k: v for k, v in out.items() if k not in ('path',)}))
    return out


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def binom_p_two_sided(k, n, p):
    pk = math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    return min(1.0, sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i)
                        for i in range(n + 1)
                        if math.comb(n, i) * p ** i * (1 - p) ** (n - i) <= pk * (1 + 1e-9)))


def clopper_pearson(k, n, alpha=0.05):
    def solve(f, target):
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if f(mid) > target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    lower = 0.0 if k == 0 else solve(lambda p: binom_cdf(k - 1, n, p), 1 - alpha / 2)
    upper = 1.0 if k == n else solve(lambda p: binom_cdf(k, n, p), alpha / 2)
    return lower, upper


def fmt(v, f='%.1f', none='—'):
    return none if v is None else f % v


def main():
    global LOG
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    specs = []
    for a in args:
        if '=' not in a:
            print('Use ETIQUETA=ARQUIVO[@INÍCIO-FIM]: %s' % a, file=sys.stderr)
            sys.exit(2)
        label, rest = a.split('=', 1)
        window = None
        if '@' in rest:
            rest, w = rest.rsplit('@', 1)
            try:
                lo, hi = (float(v) for v in w.split('-'))
            except ValueError:
                print('%s: a janela deve estar no formato @INÍCIO-FIM em segundos (exemplo: @120-300): @%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            if hi <= lo:
                print('%s: o fim da janela deve ser posterior ao início: @%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            window = (lo, hi)
        specs.append((label, rest, window))
    missing = [(label, rest) for label, rest, _ in specs if not os.path.isfile(rest)]
    if missing:
        for label, rest in missing:
            print('%s: arquivo inexistente %s' % (label, rest), file=sys.stderr)
        sys.exit(1)
    outdir = os.path.dirname(os.path.abspath(specs[0][1]))
    LOG = open(os.path.join(outdir, 'ab_blocks.log'), 'a', encoding='utf-8')
    log('Início', 'INFO', ' '.join(args))
    blocks = [analyze(label, rest, window) for label, rest, window in specs]
    # Intervalos sobrepostos da mesma gravação seriam contados duas vezes; registra o aviso somente se ambos os trechos entram na comparação.
    overlap = []
    compared = lambda b: 'error' not in b and b.get('want') in ('chip', 'gyro') and b['mode'] in ('chip', 'gyro')
    for i in range(len(specs)):
        for j in range(i):
            if not (compared(blocks[i]) and compared(blocks[j])):
                continue
            if os.path.normcase(os.path.abspath(specs[i][1])) != os.path.normcase(os.path.abspath(specs[j][1])):
                continue
            a0, a1 = specs[i][2] or (0, float('inf'))
            b0, b1 = specs[j][2] or (0, float('inf'))
            if a0 < b1 and b0 < a1:
                msg = '%s e %s usam intervalos sobrepostos da mesma gravação; as quedas seriam contadas duas vezes' % (specs[j][0], specs[i][0])
                log('Parâmetros', 'WARN', msg)
                overlap.append(msg)

    lines = []
    lines.append('== Relatório A/B %s ==' % time.strftime('%Y-%m-%d %H:%M:%S'))
    for msg in overlap:
        lines.append('[Aviso] ' + msg)
    hdr = ('%-8s %-5s %7s %7s %4s %7s %5s %9s %9s %8s %8s %11s %11s' %
           ('Trecho', 'Modo', 'Marcha em pé', 'Joystick', 'Quedas', 'Quedas/min em pé', 'Segmentos', 'Termina em queda', 'Mediana pré-queda', 'Antes da 1ª queda', 'Degraus chip', 'Degraus pré-queda', 'Tremor rolagem/inclinação'))
    lines.append(hdr)
    for b in blocks:
        if 'error' in b and b.get('frames', 0) < 2:
            lines.append('%-8s Erro: %s' % (b['label'], b['error']))
            continue
        rate = b['falls'] / (b['t_up'] / 60) if b['t_up'] > 0 else None
        lines.append('%-8s %-5s %6.0fs %6.0fs %4d %7s %5d %9s %8ss %7ss %8d %11s %11s%s' % (
            b['label'], b['mode'], b['t_up'], b['t_stick'], b['falls'], fmt(rate, '%.2f'), b['segs'],
            '%d/%d' % (b['segs_fall'], b['segs']), fmt(b['median_to_fall']), fmt(b['first_fall']),
            b['chip_steps'], '%d/%d' % (b['pre_step'], b['falls']),
            ('%.0f/%.0f' % (b['roll_rms'], b['pitch_rms'])) if 'roll_rms' in b else '—',
            ('  ← ' + b['error']) if 'error' in b else ''))
        rate_s = b['falls_stick'] / (b['t_stick'] / 60) if b['t_stick'] > 0 else None
        lines.append('%-8s       %d quedas após comando do joystick / %.0f s acionando → por minuto de acionamento: %s; %.0f s com inclinação >%.0f° excluídos' % (
            '', b['falls_stick'], b['t_stick'], fmt(rate_s, '%.2f'), TILT_MAX, b['t_tilted']))
        if b['mode'] == 'gyro':
            lines.append('%-8s       Degraus publicados (vistos pela política): %d; decisões durante marcha em pé: %s' % ('', b['pub_steps'], b['verdicts_up']))
        if b['other_falls']:
            lines.append('%-8s       Mais %d detecções de queda fora do estado de caminhada, não contabilizadas (detalhes em ab_blocks.log)' % ('', b['other_falls']))

    tot = {}
    for b in blocks:
        # Etiquetas iniciadas por old (ou desconhecidas) não entram na comparação, mesmo se a gravação estiver em chip/gyro.
        if 'error' in b or b.get('want') not in ('chip', 'gyro') or b['mode'] not in ('chip', 'gyro'):
            continue
        t = tot.setdefault(b['mode'], {'falls': 0, 't': 0.0, 'falls_s': 0, 't_s': 0.0, 'n': 0,
                                       'roll2': 0.0, 'pitch2': 0.0, 'shake_s': 0.0,
                                       'roll2_all': 0.0, 'pitch2_all': 0.0, 'shake_s_all': 0.0})
        t['falls'] += b['falls']
        t['t'] += b['t_up']
        t['falls_s'] += b['falls_stick']
        t['t_s'] += b['t_stick']
        t['n'] += 1
        for key in ('', '_all'):
            if 'roll_rms' + key in b:
                t['roll2' + key] += b['roll_rms' + key] ** 2 * b['shake_s' + key]
                t['pitch2' + key] += b['pitch_rms' + key] ** 2 * b['shake_s' + key]
                t['shake_s' + key] += b['shake_s' + key]
    lines.append('')
    if 'chip' in tot and 'gyro' in tot and tot['chip']['t'] > 0 and tot['gyro']['t'] > 0:
        c, g = tot['chip'], tot['gyro']
        # Exibe os dois denominadores: marcha em pé (inclui ficar parado) e tempo acionando o joystick. Informe divergências.
        for name, kf, kt in (('Métrica principal · joystick acionado', 'falls_s', 't_s'), ('Referência · marcha em pé', 'falls', 't')):
            if c[kt] <= 0 or g[kt] <= 0:
                lines.append('[%s] um dos modos tem tempo zero; comparação não calculada.' % name)
                continue
            rc, rg = c[kf] / (c[kt] / 60), g[kf] / (g[kt] / 60)
            lines.append('[%s] chip: %d trechos, %.0f s, %d quedas, %.2f por minuto; gyro: %d trechos, %.0f s, %d quedas, %.2f por minuto' % (
                name, c['n'], c[kt], c[kf], rc, g['n'], g[kt], g[kf], rg))
            n = c[kf] + g[kf]
            share = g[kt] / (g[kt] + c[kt])
            if n == 0:
                lines.append('[%s] nenhum dos modos teve quedas; não é possível comparar as taxas.' % name)
                continue
            p = binom_p_two_sided(g[kf], n, share)
            lo, hi = clopper_pearson(g[kf], n)
            odds = (1 - share) / share
            rr_lo = lo / (1 - lo) * odds if lo < 1 else float('inf')
            rr_hi = hi / (1 - hi) * odds if hi < 1 else float('inf')
            rr = (rg / rc) if rc > 0 else float('inf')
            verdict = ('gyro teve claramente menos quedas' if rr < 1 else 'gyro teve claramente mais quedas: interrompa gyro e investigue a causa') if p < 0.05 else 'a diferença ainda não permite uma conclusão'
            lines.append('[%s] razão gyro/chip = %s, intervalo de 95%% %.2f–%s, p = %.3f → %s' % (
                name, fmt(rr, '%.2f', '∞'), rr_lo, '∞' if math.isinf(rr_hi) else '%.2f' % rr_hi, p, verdict))
        if c['shake_s'] > 0 and g['shake_s'] > 0:
            cr, cp = math.sqrt(c['roll2'] / c['shake_s']), math.sqrt(c['pitch2'] / c['shake_s'])
            gr, gp = math.sqrt(g['roll2'] / g['shake_s']), math.sqrt(g['pitch2'] / g['shake_s'])
            ok = gr <= cr * 1.1 and gp <= cp * 1.1
            lines.append('Tremor do tronco (RMS °/s, segmentos com joystick sem queda) chip %.0f/%.0f (%.0f s), gyro %.0f/%.0f (%.0f s) → limite de proteção %s%s' % (
                cr, cp, c['shake_s'], gr, gp, g['shake_s'], 'dentro do limite' if ok else 'excedido (gyro está mais de 10% acima de chip)',
                '; um modo tem menos de 20 s; resultado apenas indicativo' if min(c['shake_s'], g['shake_s']) < 20 else ''))
        else:
            lines.append('Tremor do tronco: um modo não tem segmento com joystick sem queda (≥%.1f s); não é possível avaliar o limite de proteção.' % SHAKE_MIN)
        if c['shake_s_all'] > 0 and g['shake_s_all'] > 0:
            lines.append('    Referência (métrica original, inclui tropeços pré-queda): chip %.0f/%.0f, gyro %.0f/%.0f' % (
                math.sqrt(c['roll2_all'] / c['shake_s_all']), math.sqrt(c['pitch2_all'] / c['shake_s_all']),
                math.sqrt(g['roll2_all'] / g['shake_s_all']), math.sqrt(g['pitch2_all'] / g['shake_s_all'])))
    else:
        lines.append('Ainda não há trechos nos modos chip e gyro; comparação não calculada.')
    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(outdir, 'ab_report.txt'), 'a', encoding='utf-8') as fh:
        fh.write(report + '\n\n')
    log('Fim', 'INFO', 'Relatório anexado a %s' % os.path.join(outdir, 'ab_report.txt'))


if __name__ == '__main__':
    main()
