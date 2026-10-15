"""今晚 A/B 用：每块录像数摔倒、算每分钟摔几次，最后把 chip 和 gyro 各自加总，判断差别算不算数（只读）。

用法：
  python ab_blocks.py chip1=录像1.jsonl gyro1=录像2.jsonl chip2=... gyro2=...
  python ab_blocks.py chip1=录像.jsonl@120-300     # 只看这份录像开头起第 120～300 秒（按 wall 墙钟算）
标签必须以 chip 或 gyro 开头才进对比；旧录像用 old 开头，只出单块数。别的开头报错、不进对比。
每块实际是什么模式从录像里认：imu.fusion 带 fused → chip 模式；带 chip → gyro 模式；没有 imu.fusion → 旧版。
标签和录像里的模式对不上会报 [错误]，这块不进对比。

口径：
  直立走路帧 = policy == walk、未卸力（safety.limp 假）、未倒地（safety.fallen 假）。
  计时只算直立走路帧里倾角 ≤30° 的（摔后躺着、斜靠、被人扶着的不算）；时间按 wall 差算，>0.1 s 的空档不计时。
  一次摔倒 = 直立走路帧之后 safety.fallen 上升沿；离上一次倒地结束不到 3 s 的上升沿算同一次（倒地判定会来回跳）。
            非走路状态（held / homing 等）或卸力时的上升沿单独列出，不计入。日志里写每次距上次倒地多久，卡 3 s 边界的可复核。
  推杆摔 = 上升沿前 2 s 内推过摇杆的摔倒。
  主指标 = 每推杆分钟摔倒 = 推杆摔 / 推摇杆分钟数（推杆时间两种模式由操作者控制得一样；站着不推杆的时间长短跟模式无关）。
  参考   = 每直立走路分钟摔倒 = 全部摔倒 / 直立走路分钟数。两种分母结论不一致要当场说出来。
  走路段 = 连续的直立走路帧（中间空档 <0.2 s 算连续）；段尾 1 s 内接着摔倒的算「以摔倒结束」。
  芯片台阶 = 用本帧陀螺把上一帧重力外推，与本帧差 >5°（judge_block / glitch_rate 同口径），只数直立走路帧。
            芯片那一路：chip 模式和旧版用 safety.gravity；gyro 模式用 imu.fusion.chip，补上和 safety.gravity 一样的
            归一化 + 逐分量三点中值，两种模式才可比。verdict == disabled 的帧发布的已是芯片姿态，按 chip 算。
  发布台阶 = 同样的判据用在 safety.gravity（策略实际看到的），gyro 模式下应接近 0。
  摔前有台阶 = 摔倒前 1.5 s 内芯片那一路有台阶（没有基线：任意推杆时刻往前 1.5 s 有台阶的比例本身就有 12–47%，只作参考）。
  机身颤（护栏）= 推着摇杆、倾角 ≤30° 的直立走路段（每段 ≥1.5 s），且段尾 2 s 内没摔，机身横滚、俯仰角速度 RMS（°/s）；
            gyro 不高于 chip 一成。含摔前踉跄的原口径另列作参考（那个会把摔倒率再数一遍）。
  一块里少数模式的直立走路帧 >1 s → 这块不进对比（中途改过键，要按改键时刻切块）。
对比：两种模式各自加总，率比 = gyro / chip；p 值用精确条件二项检验（总摔倒数固定时，落在 gyro 的份额是否偏离时间占比），
      95% 区间用 Clopper-Pearson。块数和顺序上机前定好（chip、gyro、gyro、chip…），别边看 p 值边决定加不加块。
日志：分类、分级写到第一个录像同目录的 ab_blocks.log；报告同时追加到 ab_report.txt。
10-15 第一版经独立审核，按审核改：old/不认识的标签不进对比、gyro 芯片路补中值、
  倾角 ≤30° 计时、推杆分母、护栏去掉摔前段、disabled 按 chip、混模式整块不进、参数写错不崩、同一文件重复用提示。
"""
import json
import math
import os
import sys
import time

GAP = 0.1            # 帧间隔超过这个不计时
SEG_GAP = 0.2        # 走路段内允许的空档
MERGE = 3.0          # 倒地判定来回跳的合并窗口
PRE_FALL = 1.5       # 摔前看多久
STEP_DEG = 5.0
SHAKE_MIN = 1.5
TILT_MAX = 30.0      # 计时/机身颤只算倾角 ≤30° 的直立走路帧（摔后躺着、被扶着的不算）
STICK_RECENT = 2.0   # 上升沿前这么久内推过摇杆 → 算「推杆摔」
SHAKE_SKIP = 2.0     # 机身颤只用段尾之后这么久内没摔的段
MIX_MAX = 50         # 非多数模式的直立走路帧超过这么多（1 s）→ 这块报错

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
        # disabled 时发布的已经是芯片（bno08x.rs sample()/HostImuSample.quat），按 chip 算
        return 'chip' if f.get('verdict') == 'disabled' else 'gyro'
    return '?'


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return tuple(x / n for x in v) if n > 0 else None


def chip_gravs(rows, mode):
    """芯片那一路每帧的重力。gyro 模式下 imu.fusion.chip 没过中值，这里补上和
    safety.gravity 一样的处理（先归一化、再逐分量三点中值，断档后重新起头），两种模式才可比。"""
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
    """计时用：直立走路且倾角 ≤ TILT_MAX。台阶仍按 upright() 数，免得把芯片跳到 30° 以外的帧漏掉。"""
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
        log('读取', 'WARN', '%s：%d 行不是 JSON，已跳过' % (path, bad))
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
        log('读取', 'ERROR', '%s：帧太少（%d）' % (label, len(rows)))
        out['error'] = '帧太少'
        return out
    modes = {}
    for r in rows:
        m = frame_mode(r)
        modes[m] = modes.get(m, 0) + 1
    mode = max(modes, key=modes.get)
    out['modes'] = modes
    out['mode'] = mode
    # 标签只认 chip/gyro/old 开头；只有 chip/gyro 开头的才进对比（见 main）
    want = next((m for m in ('chip', 'gyro', 'old') if label.startswith(m)), None)
    out['want'] = want
    if want is None:
        log('参数', 'ERROR', '%s：标签要以 chip / gyro / old 开头，这块不进对比' % label)
        out['error'] = '标签不认识'
    if len(modes) > 1:
        log('分段', 'WARN', '%s：一块里有多种模式 %s（中途改过键？），按多数 %s 算' % (label, modes, mode))
        # 少数模式在直立走路里超过 1 s → 不进对比，免得混块
        minority_up = sum(1 for r in rows if upright(r) and frame_mode(r) != mode)
        if minority_up > MIX_MAX:
            log('分段', 'ERROR', '%s：非 %s 模式的直立走路帧 %d 帧（>%d），这块不进对比；请按改键时刻切块' % (
                label, mode, minority_up, MIX_MAX))
            out['error'] = '混了别的模式（%d 帧直立走路）' % minority_up
    if want in ('chip', 'gyro') and mode != want:
        log('分段', 'ERROR', '%s：标签是 %s，录像里是 %s，这块不进对比' % (label, want, mode))
        out['error'] = '模式对不上（录像里是 %s）' % mode
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
        log('读取', 'WARN', '%s：%d 处帧间隔 >%.1f s（录像断过），这些空档不计时' % (label, gaps, GAP))
    if t_tilted:
        log('统计', 'INFO', '%s：直立走路状态但倾角 >%.0f° 的 %.1f s 不计时（摔后躺着/被扶着）' % (label, TILT_MAX, t_tilted))
    out.update(t_up=t_up, t_stick=t_stick, t_tilted=t_tilted, chip_steps=len(chip_steps), pub_steps=len(pub_steps))

    # 倒地事件：先找 fallen 的连续段，再合并来回跳的
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
            # 上升沿前 STICK_RECENT 秒内推过摇杆 → 推杆摔（分母用推摇杆时间）
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
        log('摔倒', 'INFO', '%s：%.1f s 处倒地判定，状态 %s 卸力 %s，不计入' % (label, wt - w0, pol, limp))
    out['falls'] = len(falls)
    out['falls_stick'] = len(falls_stick)
    out['other_falls'] = len(other)

    # 走路段
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
    # 块里第一次摔倒前累计直立走路了多久
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
        log('摔倒', 'INFO', '%s：%.1f s 摔倒（%s；距上次倒地结束 %s），摔前 %.1f s 内芯片台阶 %d 次' % (
            label, ft - w0, '推杆' if ft in falls_stick else '没推杆',
            '—' if since[ft] is None else '%.1f s' % since[ft], PRE_FALL, len(pre)))

    # 机身颤
    # 护栏只用「段尾之后 SHAKE_SKIP 秒内没摔」的推杆段（倾角 ≤ TILT_MAX）：原版把摔前踉跄算进去，
    # 护栏量的其实是摔倒本身。原版口径另存 *_all 供参考。
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
    log('统计', 'INFO', '%s：%s' % (label, {k: v for k, v in out.items() if k not in ('path',)}))
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
            print('参数要写成 标签=文件[@起-止]：%s' % a, file=sys.stderr)
            sys.exit(2)
        label, rest = a.split('=', 1)
        window = None
        if '@' in rest:
            rest, w = rest.rsplit('@', 1)
            try:
                lo, hi = (float(v) for v in w.split('-'))
            except ValueError:
                print('%s：时间窗要写成 @起-止（秒，例如 @120-300）：@%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            if hi <= lo:
                print('%s：时间窗结束要大于开始：@%s' % (label, w), file=sys.stderr)
                sys.exit(2)
            window = (lo, hi)
        specs.append((label, rest, window))
    missing = [(label, rest) for label, rest, _ in specs if not os.path.isfile(rest)]
    if missing:
        for label, rest in missing:
            print('%s：文件不存在 %s' % (label, rest), file=sys.stderr)
        sys.exit(1)
    outdir = os.path.dirname(os.path.abspath(specs[0][1]))
    LOG = open(os.path.join(outdir, 'ab_blocks.log'), 'a', encoding='utf-8')
    log('开始', 'INFO', ' '.join(args))
    blocks = [analyze(label, rest, window) for label, rest, window in specs]
    # 同一份录像的重叠时间段进了对比两次 → 摔倒会被数两次；只在两块都进对比时报，写进报告
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
                msg = '%s 和 %s 用了同一份录像的重叠时间段，摔倒会被数两次' % (specs[j][0], specs[i][0])
                log('参数', 'WARN', msg)
                overlap.append(msg)

    lines = []
    lines.append('== A/B 报告 %s ==' % time.strftime('%Y-%m-%d %H:%M:%S'))
    for msg in overlap:
        lines.append('[警告] ' + msg)
    hdr = ('%-8s %-5s %7s %7s %4s %7s %5s %9s %9s %8s %8s %11s %11s' %
           ('块', '模式', '直立走', '推摇杆', '摔', '每直立分', '段', '以摔结束', '摔前中位', '首摔前', '芯片台阶', '摔前有台阶', '颤 横滚/俯仰'))
    lines.append(hdr)
    for b in blocks:
        if 'error' in b and b.get('frames', 0) < 2:
            lines.append('%-8s 出错：%s' % (b['label'], b['error']))
            continue
        rate = b['falls'] / (b['t_up'] / 60) if b['t_up'] > 0 else None
        lines.append('%-8s %-5s %6.0fs %6.0fs %4d %7s %5d %9s %8ss %7ss %8d %11s %11s%s' % (
            b['label'], b['mode'], b['t_up'], b['t_stick'], b['falls'], fmt(rate, '%.2f'), b['segs'],
            '%d/%d' % (b['segs_fall'], b['segs']), fmt(b['median_to_fall']), fmt(b['first_fall']),
            b['chip_steps'], '%d/%d' % (b['pre_step'], b['falls']),
            ('%.0f/%.0f' % (b['roll_rms'], b['pitch_rms'])) if 'roll_rms' in b else '—',
            ('  ← ' + b['error']) if 'error' in b else ''))
        rate_s = b['falls_stick'] / (b['t_stick'] / 60) if b['t_stick'] > 0 else None
        lines.append('%-8s       推杆摔 %d 次 / 推摇杆 %.0f s → 每推杆分钟 %s；倾角>%.0f° 不计时 %.0f s' % (
            '', b['falls_stick'], b['t_stick'], fmt(rate_s, '%.2f'), TILT_MAX, b['t_tilted']))
        if b['mode'] == 'gyro':
            lines.append('%-8s       发布台阶（策略看到的）%d 次；直立走路判定 %s' % ('', b['pub_steps'], b['verdicts_up']))
        if b['other_falls']:
            lines.append('%-8s       另有 %d 次倒地判定不在走路状态，不计入（明细见 ab_blocks.log）' % ('', b['other_falls']))

    tot = {}
    for b in blocks:
        # old 开头（或不认识的标签）不进对比，哪怕录像里是 chip/gyro
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
        # 两种分母各出一遍：直立走路（含站着不推杆）和推摇杆；两者结论不一致要当场说出来
        for name, kf, kt in (('主指标·推摇杆', 'falls_s', 't_s'), ('参考·直立走路', 'falls', 't')):
            if c[kt] <= 0 or g[kt] <= 0:
                lines.append('[%s] 有一边时间为 0，不出对比。' % name)
                continue
            rc, rg = c[kf] / (c[kt] / 60), g[kf] / (g[kt] / 60)
            lines.append('[%s] chip %d 块 %.0f s 摔 %d 次 每分钟 %.2f；gyro %d 块 %.0f s 摔 %d 次 每分钟 %.2f' % (
                name, c['n'], c[kt], c[kf], rc, g['n'], g[kt], g[kf], rg))
            n = c[kf] + g[kf]
            share = g[kt] / (g[kt] + c[kt])
            if n == 0:
                lines.append('[%s] 两边都没摔，比不出摔倒率。' % name)
                continue
            p = binom_p_two_sided(g[kf], n, share)
            lo, hi = clopper_pearson(g[kf], n)
            odds = (1 - share) / share
            rr_lo = lo / (1 - lo) * odds if lo < 1 else float('inf')
            rr_hi = hi / (1 - hi) * odds if hi < 1 else float('inf')
            rr = (rg / rc) if rc > 0 else float('inf')
            verdict = ('gyro 摔得明显少' if rr < 1 else 'gyro 摔得明显多：停 gyro，查原因') if p < 0.05 else '差别还不够大，不能下结论'
            lines.append('[%s] 率比 gyro/chip = %s，95%% 区间 %.2f～%s，p = %.3f → %s' % (
                name, fmt(rr, '%.2f', '∞'), rr_lo, '∞' if math.isinf(rr_hi) else '%.2f' % rr_hi, p, verdict))
        if c['shake_s'] > 0 and g['shake_s'] > 0:
            cr, cp = math.sqrt(c['roll2'] / c['shake_s']), math.sqrt(c['pitch2'] / c['shake_s'])
            gr, gp = math.sqrt(g['roll2'] / g['shake_s']), math.sqrt(g['pitch2'] / g['shake_s'])
            ok = gr <= cr * 1.1 and gp <= cp * 1.1
            lines.append('机身颤（°/s RMS，没摔的推杆段）chip %.0f/%.0f（%.0f s），gyro %.0f/%.0f（%.0f s）→ 护栏%s%s' % (
                cr, cp, c['shake_s'], gr, gp, g['shake_s'], '没超' if ok else '超了（gyro 比 chip 高一成以上）',
                '；有一边不到 20 s，只作参考' if min(c['shake_s'], g['shake_s']) < 20 else ''))
        else:
            lines.append('机身颤：有一边没有「没摔的推杆段」（≥%.1f s），护栏判不了。' % SHAKE_MIN)
        if c['shake_s_all'] > 0 and g['shake_s_all'] > 0:
            lines.append('    参考（原口径，含摔前踉跄）chip %.0f/%.0f，gyro %.0f/%.0f' % (
                math.sqrt(c['roll2_all'] / c['shake_s_all']), math.sqrt(c['pitch2_all'] / c['shake_s_all']),
                math.sqrt(g['roll2_all'] / g['shake_s_all']), math.sqrt(g['pitch2_all'] / g['shake_s_all'])))
    else:
        lines.append('还没有 chip 和 gyro 两种块，不出对比。')
    report = '\n'.join(lines)
    print(report)
    with open(os.path.join(outdir, 'ab_report.txt'), 'a', encoding='utf-8') as fh:
        fh.write(report + '\n\n')
    log('结束', 'INFO', '报告已追加到 %s' % os.path.join(outdir, 'ab_report.txt'))


if __name__ == '__main__':
    main()
