"""上机用的判据脚本（只读、只用标准库）：一段 duck_rec 录像（50 Hz RobotState jsonl）按停止规则出数。
用法：python judge_block.py 录像.jsonl [起始秒 结束秒]（秒 = 相对文件第一帧的 wall 秒）

10-15 第二版：按真机影子数据和独立审核改的台阶规则，来龙去脉见 docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md §5.5。
台阶 = 用陀螺把上一帧重力外推 20 ms，与本帧差 >5°，只数直立走路帧（policy == walk、未卸力、safety.fallen 假）。
  发布那一路 = safety.gravity（gyro 模式下就是策略看到的融合姿态），配本帧陀螺（两者都过了三点中值，延迟对齐）。
  影子那一路 = imu.fusion.fused（chip 模式下的融合原值，没过中值），配下一帧陀螺（录像的陀螺过了中值、晚一帧）。
每次台阶按它前后 ±2 帧的融合判定分类：
  硬：判定里有 realign_long / realign_gap / fallback / follow（融合能整步跳的只有这四种）→ 1 次就回 chip，不受任何豁免；
  软：判定只有 accepted / rejected / slew（这几种融合只做积分或每帧 ≤0.1° 的修正，不可能整步跳）：
      摔倒上升沿前 1.0 s 内、或上一帧发布倾角 ≥30°（已经在倒、倒地判断还没跟上）→ 豁免，只记下；
      其余每块 ≥3 次 → 回 chip；1–2 次 → 记下、块后逐个看。
另列：直立走路帧里出现硬判定的帧（配合块前后计数：realign/fallback 涨了要能在录像里对上倒地后 / HOME 时，对不上按真跳处理）。
静站：policy == held、未卸力、|ω| < 20°/s 的连续帧按 10 s 分窗，每窗 θ 中位 ≤0.5°、P90 ≤1°（倾斜、推动的帧自然被 |ω| 去掉）。
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
    sys.exit('录像里没有状态帧')
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
    """硬 / 豁免 / 软，和说明。"""
    vs = verdicts_near(i)
    if HARD & set(vs):
        return '硬', vs
    t = rows[i]['wall']
    nf = min((f - t for f in falls if f >= t), default=None)
    if nf is not None and nf <= PRE_FALL:
        return '豁免(摔前%.2fs)' % nf, vs
    if tilt(rows[i - 1]['safety']['gravity']) >= TILT_EXEMPT:
        return '豁免(上一帧倾角%.0f°)' % tilt(rows[i - 1]['safety']['gravity']), vs
    return '软', vs


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

print(f'帧 {len(rows)}；模式 {sorted(modes)}；直立走路 {up_frames} 帧 / {up_time:.0f} s；摔倒上升沿 {len(falls)} 次：{[round(f - T0, 1) for f in falls]}')


def report(name, steps, judge):
    counts = {'硬': 0, '软': 0, '豁免': 0}
    lines = []
    for i, e in steps:
        cls, vs = classify(i)
        counts['豁免' if cls.startswith('豁免') else cls] += 1
        nxt = wdeg(rows[i + 1]) if i + 1 < len(rows) else float('nan')
        lines.append('   t=%.2f  %.1f°  %s  |ω| %.0f→%.0f°/s  判定±2帧 %s' % (rows[i]['wall'] - T0, e, cls, wdeg(rows[i]), nxt, vs))
    print(f'{name}：>5° 台阶 {len(steps)} 次 → 硬 {counts["硬"]}、软 {counts["软"]}、豁免 {counts["豁免"]}')
    for l in lines[:30]: print(l)
    if len(lines) > 30: print('   …（共 %d 条）' % len(lines))
    if judge:
        if counts['硬']:
            print('   → 回 chip：有硬台阶（融合整步对齐附近的跳）')
        elif counts['软'] >= SOFT_MAX:
            print(f'   → 回 chip：软台阶 {counts["软"]} 次 ≥{SOFT_MAX}（判据或轴向有系统性问题）')
        elif counts['软']:
            print(f'   → 继续，但块后逐个看这 {counts["软"]} 次')
        else:
            print('   → 没触发')


report('发布那一路（safety.gravity，策略看到的）', pub, judge='gyro' in modes)
if 'chip' in modes:
    print('   （chip 模式下发布的是芯片姿态，上面只作基线，不触发停止规则）')
    report('影子那一路（imu.fusion.fused，配下一帧陀螺）', shadow, judge=False)

hard_frames = [(r['wall'] - T0, fus(r).get('verdict'), up(r)) for r in rows if fus(r).get('verdict') in HARD]
if hard_frames:
    up_hard = [h for h in hard_frames if h[2]]
    print(f'硬判定帧（录像每帧只带最后一条报告的判定）：共 {len(hard_frames)} 帧，其中直立走路帧 {len(up_hard)}')
    for t, v, u in hard_frames[:15]:
        after = [round(t - (f - T0), 2) for f in falls if 0 <= t - (f - T0) <= 10]
        print('   t=%.2f  %s  %s%s' % (t, v, '直立走路' if u else '非直立走路', ('  倒地后 %ss' % after[-1]) if after else ''))
    if up_hard:
        print('   → 直立走路帧里有硬判定：对照计数和录像，不是倒地后/HOME 时的 → 回 chip')

vs_all, vs_up = {}, {}
for r in rows:
    v = fus(r).get('verdict')
    if v:
        vs_all[v] = vs_all.get(v, 0) + 1
        if up(r): vs_up[v] = vs_up.get(v, 0) + 1
if vs_all:
    print('判定（全部帧）:', vs_all); print('判定（直立走路帧）:', vs_up)

# 静站：held、未卸力、|ω|<20°/s 的连续帧按 10 s 分窗
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
    print(f'HOME 静站：{len(wins)} 个窗（共 {tot:.0f} s），最差窗 θ 中位 {worst[0]:.3f}°、P90 {worst[1]:.3f}°'
          + (f'；超标窗 {bad} → 回 chip' if bad else '；都在中位 ≤0.5°、P90 ≤1° 以内'))
else:
    print('没有 HOME 静站窗（held、未卸力、|ω|<20°/s、≥5 s）')
