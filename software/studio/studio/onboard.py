"""总览上的「上手清单」，顺带主板温度格的回差、Studio 自己读的主板温度（总览重排 §5、审查 O4–O8、O14、O15）。

清单照 overview-merge-review.md 末尾「清单每一步的最终判法」表，按 §5 O14 改成 5 行：
    卡片头（不编号）连上鸭子
    1 舵机零位   2 IMU 方向   3 配手柄   4 测急停   5 站起来、走几步（记录还是两条：stood、walked）
每一步五种状态：ok ✓ 完成 · skip ↷ 跳过了 · todo ● 该做 / 要重做 · no ○ 没做 · unk ? 读不到。
「现在该做」= 第一个 ● / ○ 的步（跳过的算完成）。后面的不锁，照样能做。

**跳过**（用户 10-18 在二号鸭上：「以前标定过，应该跳过就行……应该允许跳过、允许重新做」）：● / ○ 的行能跳过，记一笔
skipped.<步> = {at, by, fp}，fp 跟这一步的正式记录绑同样的东西（舵机：关节指纹；IMU：芯片 + 方向；配手柄：不绑；
测急停：手柄 MAC + 主程序 build；站走：标定指纹）。指纹变了跳过作废、那行回 ●；指纹读不到不作废、也不记新的跳过（照 C2）。
主程序明说不行的（标定没做完、IMU 方向没确认、不让上力）跳过也站不起来：跳过按钮灰着，后端也拒。读不到（?）的不让跳。
**测出了问题的不让跳**（第三批代码审查 D5）：IMU 站着核过但差 8.5°、急停测过但现在不管用、两套零位打架——这些是
「做过、结果不行」，跳过只会把问题藏起来（以前跳过以后一直显示「你说以前做过」）。只有「没有记录」（或者记录对不上
现在的手柄 / 标定）的行能跳；测出问题的行按钮灰着写原因，只给「重新做」；已经存在的这类跳过记录作废、从记录里删掉。
测急停的跳过要点两次，确认那句按情况写（没测过 / 换了手柄 / 主程序升级过 / 急停现在不管用：审查 D11）。
调舵机时清单冻结：跳过、取消跳过都不收（后端拒、页面灰，审查 D11）。
✓ 和跳过了的行都能「重新做」：就是那一步的「去做」，旧记录留着，新结果出来才替换。

**主程序的字段只当「没完成」的证据**（审查 O4）：fork 的运动模式要 15 颗都标了、IMU 也 verified 才肯开总线
（fork robotd main.rs:1510-1519），所以 control 阶段这两个字段恒为 true；而这个 true 可能是安装脚本拿一号鸭的种子值
补上的（fork packaging/rebuild-config.py:75-99），也可能是手写的（二号鸭 10-17 手写了 verified = true）。
「完成」要靠 Studio 自己的记录：舵机页标定留下的 servo-calib/eeprom-*.json、用户点过的「已经校过，核对一下」、
IMU 页站着完整校过一次且跟主程序用的方向差 < 2°。

记录存 state_dir/onboarding.json（审查 O6）：先写临时文件再改名；文件坏了改名成 .bad 留着、当空的，记一行 warn。
每条记录带「它成立的条件」，条件变了显示「要重做」，记录本身不删：
    急停     {at, ms, mac, name, build}      换了手柄（MAC 不同）、主程序升级（build 不同）→ 再测一次
    站 / 走  {at, fp}                        fp = 标定指纹（15 颗 zero_raw / direction + 现在用的 IMU 方向）
    舵机核对 {at, fp}                        fp = 关节指纹（只看 15 颗 zero_raw / direction）
    IMU 核对 {at, source, mount_fp, ...}     芯片或方向改过 → 再核一次
时间存 time.time()（墙钟，给人看的）；鸭子开机没联网时墙钟停在 1970，页面上年份 < 2024 写「时间不准」。
换卡：state 目录跟着卡走，新卡上自然是空的（舵机 EEPROM 里的零位还在，第 1 步走「已经校过，核对一下」）；
重装 Studio 不动 /var/lib 就留着；换主板不清（零位在舵机和卡上，不跟主板走）。

只在后端一处判：app 的小任务每 0.5 秒调一次 tick()，summarize 只读 view()（每个页面每秒 10 次，不能在那里写盘）。
读文件（servo-calib 目录、/sys/class/thermal）在线程里做（io()，代码审查 C9），tick 只用缓存：SD 卡一卡不能挡住同一个
事件循环里的卸力。记录文件读进来逐条校验，坏的那一条丢掉、记一行 warn，别的照用；判清单整体出错时清单写「?」和原因，
主板温度的回差单独算、不受它影响（代码审查 C1）。
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import time

from .estop import STARTING_PHASES
from .imu import mount_of
from .robotd import fresh_calib
from .state import JOINT_CN, MAX_AGE, posture

ONBOARD_FILE = "onboarding.json"
SERVO_IDS = (20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14)   # 跟 servo.IDS 一样（这里不 import servo：它带串口）
STOOD_S = 3.0             # 站着（holding / policy / walking 且扭矩确认开着）连续这么久算「站起来过」（审查 O6）
WALKED_S = 2.0            # walking 累计这么久算「走过」
CPU_WARN_C = 80.0         # 跟 state.CPU_WARN_C 一样：这块板待机就 77–78 °C
CPU_CLEAR_C = 77.0        # 回差：降到这以下才收（审查 O8：没有回差，仪表带和待办会来回跳、把下面的控件推上推下）
STUDIO_SCAN_S = 10.0      # servo-calib 目录多久重新扫一次
THERMAL_ROOT = "/sys/class/thermal"
# robotd 读的配置：fork 是 --params /etc/robot/feetech-ft5/robotd.toml（fork packaging/runtime.py:28、123），官方默认 /etc/robot/robotd.toml
ROBOTD_CONFIGS = ("/etc/robot/feetech-ft5/robotd.toml", "/etc/robot/robotd.toml")
ROBOTD_CFG_S = 30.0       # 多久重读一次
CPUFREQ_ROOT = "/sys/devices/system/cpu/cpufreq"
STAND = ("holding", "policy", "walking")
# 运动模式卡在「等总线」时报的是这一句（fork main.rs:1546-1552；feetech.rs:1011-1049）：标定没过、IMU 没过都报它
CALIB_ERR = re.compile(r"calibrat|motion_enabled|calibration file|IMU mounting", re.I)

TIPS = {
    "servo": "两套零位会打架：用 Studio 的舵机页标（标完，主程序文件里 15 颗的 zero_raw 都要是 2048）",
    "imu": "装歪 8.5° 一走就往前冲（一号鸭 10-12）",
    "pad": "G50 Pro 先拨到 S 档",
    "estop": "每次换手柄都测一次",
    "walk": None,
}
TITLES = {"servo": "舵机零位", "imu": "IMU 方向", "pad": "配手柄", "estop": "测急停", "walk": "站起来、走几步"}
ORDER = ("servo", "imu", "pad", "estop", "walk")
GO = {"servo": "servos", "imu": "imu", "pad": "pad_wizard", "estop": "estop", "walk": "remote"}   # 每一步的「去做」/「重新做」
SKIP_CHANGED = {"servo": "舵机零位", "imu": "IMU 方向（或芯片）", "estop": "手柄（或主程序版本）", "walk": "标定"}
HARD_SERVO = "主程序说标定没做完，跳过了鸭子也站不起来：先去舵机页"
HARD_IMU = "主程序没确认方向，跳过了鸭子也站不起来，先去 IMU 页"
HARD_STUCK = "主程序不让上力（标定或 IMU 方向没过），跳过了鸭子也站不起来：先去舵机页 / IMU 页"
FROZEN_WHY = "在调舵机：清单先停在调之前的样子，跳过 / 取消跳过等交还主程序以后再点"


# ---------------- 指纹 ----------------

def _joints(calib):
    cal = (calib or {}).get("calibration") if isinstance((calib or {}).get("calibration"), dict) else None
    js = (cal or {}).get("joints")
    return [j for j in js if isinstance(j, dict)] if isinstance(js, list) else None


def _hash(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def joints_fp(calib):
    """15 颗的 zero_raw / direction 的指纹；读不到标定文件回 None。"""
    js = _joints(calib)
    if not js:
        return None
    return _hash(sorted([j.get("id"), j.get("zero_raw"), j.get("direction")] for j in js))


def mount_fp(source, quat):
    """芯片 + 安装方向的指纹（四元数取 4 位小数：同一份文件读两次一定一样）。"""
    if not isinstance(quat, (list, tuple)) or len(quat) != 4:
        return None
    try:
        return _hash([source, [round(float(x), 4) for x in quat]])
    except (TypeError, ValueError):
        return None


def full_fp(bus, calib):
    """标定指纹：关节 + 现在用的 IMU 方向（站起来 / 走过的记录绑它：标定改过以后要重新站、重新走）。"""
    j = joints_fp(calib)
    source, mount = mount_of(bus, calib)
    m = mount_fp(source, (mount or {}).get("quat"))
    if j is None or m is None:
        return None
    return _hash([j, m])


# ---------------- Studio 自己的舵机标定记录（servo_ops.py:426-441、612-656、735） ----------------

def studio_servo_record(state_dir):
    """非模拟、没撤销的 eeprom-*.json 里，targets 减 bad 的并集；回 {"ids": set, "time": 最近一份的时间字符串}。
    撤销会把文件改名成 undone-…（不以 eeprom- 开头，自然跳过）；模拟模式的备份在临时目录，这里看不到。"""
    d = os.path.join(state_dir or ".", "servo-calib")
    ids, latest = set(), None
    try:
        names = sorted(f for f in os.listdir(d) if f.startswith("eeprom-") and f.endswith(".json"))
    except OSError:
        return {"ids": ids, "time": None}
    for fn in names:
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("sim"):
            continue
        targets = rec.get("targets") if isinstance(rec.get("targets"), dict) else {}
        bad = rec.get("bad") if isinstance(rec.get("bad"), dict) else {}
        got = {int(k) for k in targets if str(k).isdigit()} - {int(k) for k in bad if str(k).isdigit()}
        if got:
            ids |= got
            latest = rec.get("time") or latest
    return {"ids": ids, "time": latest}


# ---------------- 主板温度：Studio 自己读（照 fork robotd/src/soc.rs 的算法） ----------------

def _read_int(path):
    try:
        with open(path, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def read_board(thermal_root=THERMAL_ROOT, cpufreq_root=CPUFREQ_ROOT):
    """主板温度和降频，跟 robotd health 的 cpu_temp_c / cpu_throttle 同一个算法（fork soc.rs:25-170）：
    温度取所有 thermal_zone 里最热的（≤ 0 °C 的当坏传感器跳过）；频率取被压得最狠的 policy 的
    scaling_max_freq / cpuinfo_max_freq；level 取类型名含 cpufreq 的 cooling device 里压得最深的。
    读不到（不是 Linux、电脑上开发）回 None。"""
    try:
        zones = [e for e in os.listdir(thermal_root)]
    except OSError:
        return None
    hot = None
    for name in zones:
        if not name.startswith("thermal_zone"):
            continue
        milli = _read_int(os.path.join(thermal_root, name, "temp"))
        if milli is None or milli <= 0:
            continue
        c = milli / 1000.0
        hot = c if hot is None or c > hot else hot
    thr = None
    try:
        pols = os.listdir(cpufreq_root)
    except OSError:
        pols = []
    for name in pols:
        if not name.startswith("policy"):
            continue
        khz = _read_int(os.path.join(cpufreq_root, name, "scaling_max_freq"))
        mx = _read_int(os.path.join(cpufreq_root, name, "cpuinfo_max_freq"))
        if khz is None or not mx:
            continue
        if thr is None or khz * thr["max_khz"] < thr["khz"] * mx:
            thr = {"khz": khz, "max_khz": mx, "level": 0, "max_level": 0}
    if thr is not None:
        for name in zones:
            if not name.startswith("cooling_device"):
                continue
            try:
                with open(os.path.join(thermal_root, name, "type"), encoding="ascii") as f:
                    kind = f.read().strip()
            except OSError:
                continue
            if "cpufreq" not in kind:
                continue
            lv, mx = _read_int(os.path.join(thermal_root, name, "cur_state")), _read_int(os.path.join(thermal_root, name, "max_state"))
            if lv is None or not mx:
                continue
            if thr["max_level"] == 0 or lv * thr["max_level"] > thr["level"] * mx:
                thr.update(level=lv, max_level=mx)
    if hot is None and thr is None:
        return None
    return {"c": hot, "throttle": thr}


def read_battery_shutdown(paths=ROBOTD_CONFIGS):
    """robotd 配置里 [safety] battery_empty_shutdown 写的是什么：True / False；文件读不到、没写这一项回 None
    （没写时 robotd 默认是开着的：fork robotd-params lib.rs:1804；但我们按「读不到」处理，页面上说「不会自己坐下」，宁可保守）。
    按顺序找第一个在的文件（fork 的、官方默认的）。"""
    import tomllib
    for path in paths:
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            return None
        v = (data.get("safety") or {}).get("battery_empty_shutdown") if isinstance(data.get("safety"), dict) else None
        return v if isinstance(v, bool) else None
    return None


# ---------------- 判一步 ----------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _f1(x):
    """一位小数；不是数字写「?」（记录文件里可能是 null：代码审查 C1）。"""
    return f"{x:.1f}" if _num(x) else "?"


def _row(key, state, text, when=None, actions=(), note=None, hard=None, found=None, ask=None):
    """hard：主程序明说这一步不行（标定没做完、IMU 方向没确认、不让上力）——跳过了鸭子也站不起来，不让跳（写原因）。
    found：做过 / 查过、结果不行（测出了问题，审查 D5）——不让跳，只给「重新做」（写原因）。
    ask：要点两次的跳过（测急停）第二下按钮上的那句（按情况写：审查 D11）。"""
    return {"key": key, "n": ORDER.index(key) + 1, "title": TITLES[key], "tip": TIPS[key], "state": state,
            "text": text, "when": when, "note": note, "actions": [{"do": d, "label": lab} for d, lab in actions],
            "hard": hard, "found": found, "ask": ask, "go": GO[key], "skip": None}


def header_of(inp):
    """卡片头上的「连上鸭子」（不编号）。kind：ok / absent / connecting / bench / servo / commissioning / stuck_calib / starting / other。"""
    bus = inp.get("bus") if isinstance(inp.get("bus"), dict) else None
    if inp.get("bench"):
        return {"ok": False, "kind": "bench", "text": "台架模式：不连主程序，清单不检查"}
    if inp.get("servo_session"):
        return {"ok": False, "kind": "servo", "text": "在舵机页调舵机（主程序按计划停着）：清单先停在调之前的样子"}
    if inp.get("present") is False:
        return {"ok": False, "kind": "absent", "text": "主程序没在跑：连不上 robotd"}
    if bus is None:
        return {"ok": False, "kind": "connecting", "text": "正在连主程序…"}
    mode, phase, err = bus.get("mode"), bus.get("phase"), bus.get("error")
    if phase in STARTING_PHASES:
        if err and CALIB_ERR.search(str(err)):
            return {"ok": False, "kind": "stuck_calib", "text": "主程序不让上力：标定或 IMU 方向没过", "raw": str(err)}
        return {"ok": False, "kind": "starting", "text": "在等舵机总线（多半是舵机没上电）" if phase == "waiting_for_bus"
                else "主程序还在启动", "raw": str(err) if err else None}
    if mode == "commissioning":
        return {"ok": False, "kind": "commissioning", "text": "调试模式：要站要走先回运动模式"}
    if mode == "motion" and phase == "control":
        return {"ok": True, "kind": "ok", "text": "连上了"}
    return {"ok": False, "kind": "other", "text": f"主程序在 {mode or '?'} 模式、{phase or '?'} 阶段"}


def _imu_mount_unverified(bus, calib):
    """主程序明说 IMU 方向没确认吗：busStatus 的 native.imu_mount_verified 或标定文件 mount.verified 是 False。
    不知道也当 False（只有主程序明说没确认才拦）。"""
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    _source, mount = mount_of(bus, calib)
    return native.get("imu_mount_verified") is False or (isinstance(mount, dict) and mount.get("verified") is False)


def servo_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("servo", "unk", "连上主程序才判得出", actions=[("servos", "去舵机页")])
    uncal = (calib or {}).get("uncalibrated_joints")
    if head["kind"] == "stuck_calib":
        # 只有 IMU 明说没确认、而且关节都标了（uncalibrated_joints 是空列表）时，原因在 IMU：
        # 舵机行不 hard，照正常逻辑往下判；其余情况照旧 hard。
        if not (_imu_mount_unverified(bus, calib) and isinstance(uncal, list) and not uncal):
            return _row("servo", "no", "主程序不让上力：标定或 IMU 方向没过（它报的是同一句话，分不出是哪个）",
                        actions=[("servos", "去舵机页")], hard=HARD_STUCK)
    js = _joints(calib)
    if isinstance(uncal, list) and uncal:
        names = "、".join(JOINT_CN.get(str(x), str(x)) for x in uncal[:4]) + ("…" if len(uncal) > 4 else "")
        return _row("servo", "no", f"主程序说 {len(uncal)} 颗还没标：{names}", actions=[("servos", "去舵机页")], hard=HARD_SERVO)
    if js and any(j.get("calibrated") is False for j in js):
        bad = [JOINT_CN.get(j.get("name"), j.get("name")) for j in js if j.get("calibrated") is False]
        return _row("servo", "no", f"主程序文件里 {len(bad)} 颗没标：{'、'.join(bad[:4])}", actions=[("servos", "去舵机页")],
                    hard=HARD_SERVO)
    if head["kind"] == "commissioning" and bus.get("calibrated") is False:
        return _row("servo", "no", "调试模式下主程序说标定没做完", actions=[("servos", "去舵机页")], hard=HARD_SERVO)
    if not js:
        return _row("servo", "unk", "这次连上以后还没读到主程序的标定文件（calibration-status）", actions=[("servos", "去舵机页")])
    off = [j for j in js if j.get("zero_raw") != 2048]
    if off:
        def one(j):
            z = j.get("zero_raw")
            d = f"（差 {(z - 2048) * 360 / 4096:+.1f}°）" if isinstance(z, (int, float)) else ""
            return f"{JOINT_CN.get(j.get('name'), j.get('name'))} {z}{d}"
        text = f"两套零位会打架：主程序文件里 {len(off)} 颗的 zero_raw 不是 2048——" + "、".join(one(j) for j in off[:3]) \
            + ("…" if len(off) > 3 else "") + "。多半是随包的一号鸭数值，在舵机页标一遍"
        return _row("servo", "todo", text, actions=[("servos", "去舵机页")],
                    found="两套零位会打架：跳过了也会站歪、走偏，要在舵机页标一遍")
    st = inp.get("studio_servo") or {}
    fp = joints_fp(calib)
    if set(SERVO_IDS) <= set(st.get("ids") or ()):
        # 舵机页标过 15 颗：第一次看到时记下当时的关节指纹（servo_studio，_track 里记），之后指纹变了就要重新核对
        # （判法表：「并且指纹没变」，代码审查 C9-3）
        ss = rec.get("servo_studio") if isinstance(rec.get("servo_studio"), dict) else None
        if ss and ss.get("src") == st.get("time") and ss.get("fp") == fp:
            return _row("servo", "ok", "舵机页标过；主程序文件里 15 颗都是 2048", when=st.get("time"))
        if ss and ss.get("src") == st.get("time"):
            return _row("servo", "todo", "舵机页标过以后，主程序的标定文件改过了：再核对一次，或者在舵机页再标一遍",
                        when=st.get("time"), actions=[("servos", "去舵机页"), ("confirm_servo", "已经校过，核对一下")])
    c = rec.get("confirm_servo") if isinstance(rec.get("confirm_servo"), dict) else None
    if c and c.get("fp") == fp:
        return _row("servo", "ok", "核对过：主程序文件里 15 颗都是 2048", when=c.get("at"))
    if c:
        return _row("servo", "todo", "核对以后主程序的标定文件改过了：再核对一次，或者在舵机页标一遍",
                    actions=[("servos", "去舵机页"), ("confirm_servo", "已经校过，核对一下")])
    return _row("servo", "todo", "主程序文件里写着标过（可能是随包的一号鸭数值或手改的），Studio 这边没有记录",
                actions=[("servos", "去舵机页"), ("confirm_servo", "已经校过，核对一下")])


def imu_row(inp, rec, head):
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if head["kind"] in ("absent", "connecting", "bench"):
        return _row("imu", "unk", "连上主程序才判得出", actions=[("imu", "去 IMU 页")])
    source, mount = mount_of(bus, calib)
    # stuck_calib 不在这里拦：主程序明说 IMU 没确认由下面两个 HARD_IMU 分支拦，否则照正常逻辑判（能跳过）
    if head["kind"] == "commissioning" and bus.get("imu_mount_verified") is False:
        return _row("imu", "no", "调试模式下主程序说 IMU 方向没确认", actions=[("imu", "去 IMU 页")], hard=HARD_IMU)
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    if native.get("imu_mount_verified") is False:
        # busStatus 明说没确认：标定状态读不到也是「没做」，不是「?」（代码审查 C4；待办那条也就不该被藏）
        return _row("imu", "no", "主程序说 IMU 的安装方向还没确认：装歪了走路会往前冲", actions=[("imu", "去 IMU 页")],
                    hard=HARD_IMU)
    if mount and mount.get("verified") is False:
        return _row("imu", "no", "主程序存的 IMU 方向还没确认（verified 不是 true）：fork 上没确认连站都不让",
                    actions=[("imu", "去 IMU 页")], hard=HARD_IMU)
    mfp = mount_fp(source, (mount or {}).get("quat"))
    if mfp is None:
        return _row("imu", "unk", "这次连上以后还没读到主程序存的 IMU 方向（calibration-status）", actions=[("imu", "去 IMU 页")])
    chk = rec.get("imu_check") if isinstance(rec.get("imu_check"), dict) else None
    if chk and chk.get("source") == source and chk.get("mount_fp") == mfp:
        d, t = chk.get("diff_deg"), chk.get("tilt_deg")
        if chk.get("ok") is True and _num(d):
            return _row("imu", "ok", f"IMU 页站着核过：跟主程序用的方向差 {_f1(d)}°", when=chk.get("at"))
        return _row("imu", "todo", f"上次站着核对：主程序用的方向跟算出来的差 {_f1(d)}°、站姿倾斜 {_f1(t)}°"
                    "（要差 < 2°、倾斜 ≤ 5°）", when=chk.get("at"), actions=[("imu", "去 IMU 页")],
                    found=f"站着核过，方向差 {_f1(d)}°：跳过了走路也会往前冲（一号鸭 10-12 就是装歪 8.5°），去 IMU 页重新核")
    if chk:
        return _row("imu", "todo", "核对以后 IMU 方向（或芯片）改过了：去 IMU 页站着再核一次", actions=[("imu", "去 IMU 页")])
    return _row("imu", "todo", "文件里写着已确认；装歪 8.5° 也会显示已确认：去 IMU 页站着核一次", actions=[("imu", "去 IMU 页")])


def _pad_names(pads):
    return "、".join(p.get("name") or p.get("mac") or "手柄" for p in pads[:2])


def pad_row(inp, rec, head):
    pad = inp.get("pad")
    if pad is None:
        return _row("pad", "unk", "这只鸭子没开手柄的后端（台架模式）")
    pads = [p for p in pad.get("pads") or [] if isinstance(p, dict)]
    good = [p for p in pads if p.get("paired") and p.get("trusted")]
    if good:
        on = next((p for p in good if p.get("connected")), None)
        return _row("pad", "ok", f"{on.get('name') or '手柄'} · 连着" if on else
                    f"配过 {_pad_names(good)} · 没连（打开手柄就会自己连上）")
    if any(p.get("paired") for p in pads):
        return _row("pad", "todo", "配上了但没「信任」：重启鸭子以后不会自己回连，点「修复」", actions=[("pad_known", "去修复")])
    dev = pad.get("device") or {}
    if pad.get("attached"):
        return _row("pad", "ok", f"padd 看到 {dev.get('name') or '手柄'} 连着" + ("" if pad.get("known") else "（configd 读不到）"))
    if pad.get("known"):
        return _row("pad", "no", "还没配手柄（也可以先用下面的网页手柄）", actions=[("pad_wizard", "配对手柄")])
    seen = rec.get("pads_seen") if isinstance(rec.get("pads_seen"), dict) else {}
    tail = f"；以前配过 {'、'.join(list(seen.values())[:2])}" if seen else ""
    return _row("pad", "unk", f"读不到 configd 的手柄状态（有的鸭子关着它）{tail}", actions=[("pad_wizard", "配对手柄")])


def _current_pad(pad):
    """现在的手柄 (mac, name)：连着的那只；旁路看到的；都没有时，唯一配过的那只。读不到回 (None, None)。"""
    if pad is None:
        return None, None
    a = pad.get("active") or {}
    if a.get("mac"):
        return str(a["mac"]).upper(), a.get("name")
    dev = pad.get("device") or {}
    if pad.get("attached") and dev.get("unique"):
        return str(dev["unique"]).upper(), dev.get("name")
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired") and p.get("mac")]
    if pad.get("known") and len(paired) == 1:
        return str(paired[0]["mac"]).upper(), paired[0].get("name")
    return None, None


def _no_physical_pad(pad):
    """确定没有实体手柄（configd 读得到、一个都没配、旁路也没看到）：只用网页手柄。读不到 configd 不算。"""
    return bool(pad and pad.get("known") and not pad.get("attached")
                and not [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")])


def _many_unconnected(pad):
    """配过不止一只手柄、一只都没连：认不出「现在的手柄」是哪只（审查 D11：这时写「先连上一只手柄再测」）。"""
    if not pad or pad.get("attached") or (pad.get("active") or {}).get("mac"):
        return 0
    paired = [p for p in pad.get("pads") or [] if isinstance(p, dict) and p.get("paired")]
    return len(paired) if len(paired) >= 2 and not any(p.get("connected") for p in paired) else 0


ESTOP_ASK = {"never": "确定跳过？没测过：手柄 Select 能不能停住它没验过",
             "web": "确定跳过？只用网页的话急停是空格 / 顶上红按钮，以后配了手柄要再测",
             "pad": "确定跳过？换了手柄：这只手柄的 Select 没测过",
             "build": "确定跳过？主程序升级过：升级以后 Select 没测过",
             "bad": "确定跳过？急停现在不管用（{why}）：跳过也不会变好用"}


def estop_row(inp, rec, head):
    pad = inp.get("pad")
    r = rec.get("estop") if isinstance(rec.get("estop"), dict) else None
    es = (pad or {}).get("estop") or {}
    first_bad = next((c for c in es.get("checks") or [] if c.get("ok") is False), None)
    bad_why = f"{first_bad.get('label')}：{first_bad.get('why') or '×'}" if first_bad else None
    many = _many_unconnected(pad)
    if r is None:
        # 没配实体手柄、只用网页：网页上的急停是空格 / 顶上红按钮（跟遥控卡的卸力同一条路），不经过手柄，用不着测（用户 10-18）
        web = _no_physical_pad(pad)
        web_only = "。只用网页的话：空格就是急停，跟顶上红按钮同一条路，不用测；可以跳过这步" if web else ""
        now = f"（配过 {many} 只手柄、现在都没连：先连上一只手柄再测）" if many else (f"（现在测不了：{bad_why}）" if bad_why else "")
        ask = ESTOP_ASK["web"] if web else (ESTOP_ASK["bad"].format(why=bad_why) if es.get("state") == "bad" and bad_why
                                            else ESTOP_ASK["never"])
        return _row("estop", "no", "还没真按一次 Select 测过" + now + web_only, actions=[("estop", "去测急停")], ask=ask)
    mac, _ = _current_pad(pad)
    build = (inp.get("bus") or {}).get("build")
    if mac is None or not build:
        miss = (f"配过 {many} 只手柄、现在都没连：先连上一只手柄再测" if many else "读不到现在连的是哪只手柄") if mac is None \
            else "读不到主程序版本"
        return _row("estop", "unk", f"{r.get('name') or '手柄'} 测过，现在核对不了：{miss}", when=r.get("at"),
                    actions=[("estop", "去测急停")])
    if str(r.get("mac") or "").upper() != mac:
        return _row("estop", "todo", "换了手柄：再测一次", when=r.get("at"), actions=[("estop", "去测急停")], ask=ESTOP_ASK["pad"])
    if r.get("build") != build:
        return _row("estop", "todo", "主程序升级过：再测一次", when=r.get("at"), actions=[("estop", "去测急停")],
                    ask=ESTOP_ASK["build"])
    if es.get("state") == "bad":
        return _row("estop", "todo", f"测过，但现在急停不管用：{bad_why}", when=r.get("at"), actions=[("estop", "去看看")],
                    found=f"测过，但现在急停不管用（{bad_why}）：跳过也不会变好用，先把它弄好")
    ms = r.get("ms")
    return _row("estop", "ok", f"{r.get('name') or '手柄'} 测过：松开 Select 到卸力 {ms} ms" if _num(ms)
                else f"{r.get('name') or '手柄'} 测过", when=r.get("at"))


def walk_row(inp, rec, head):
    s = rec.get("stood") if isinstance(rec.get("stood"), dict) else None
    w = rec.get("walked") if isinstance(rec.get("walked"), dict) else None
    go = [("remote", "去遥控")]
    if s is None and w is None:
        return _row("walk", "no", "还没站起来过：托着它，点「站起来」，再点「开始走」、推左摇杆", actions=go)
    fp = inp.get("fp")
    last = (w if w is not None else s).get("at")
    if fp is None:
        return _row("walk", "unk", ("站起来过、走过" if w else "站起来过") + "；标定读不到，没法核对改没改过", when=last, actions=go)
    s_ok = s is not None and s.get("fp") == fp
    w_ok = w is not None and w.get("fp") == fp
    if w_ok:                                   # 用现在的标定走过，当然也站起来过
        return _row("walk", "ok", "站起来过、走过", when=w.get("at"))
    if (s is not None and not s_ok) or w is not None:
        return _row("walk", "todo", "标定改过以后还没" + ("站过、走过" if not s_ok else "走过"), when=last, actions=go)
    return _row("walk", "todo", "站起来过，还没走过：点「开始走」，推左摇杆", when=s.get("at"), actions=go)


def step_fp(key, inp):
    """(这一步的跳过绑不绑指纹, 现在的指纹)。跟正式记录绑同样的东西；读不到是 None。"""
    bus = inp.get("bus") or {}
    calib = inp.get("calib")
    if key == "servo":
        return True, joints_fp(calib)
    if key == "imu":
        source, mount = mount_of(bus, calib)
        return True, mount_fp(source, (mount or {}).get("quat"))
    if key == "estop":
        mac, _ = _current_pad(inp.get("pad"))
        if mac is None and _no_physical_pad(inp.get("pad")):
            mac = "无实体手柄"            # 只用网页：之后配上手柄，指纹就变了，跳过作废、要测一次
        build = bus.get("build")
        return True, (_hash([mac, build]) if mac and build else None)
    if key == "walk":
        return True, inp.get("fp")
    return False, None                          # 配手柄：不绑


FP_WHAT = {"servo": "读不到主程序的标定文件", "imu": "读不到主程序存的 IMU 方向", "estop": "读不到现在连的是哪只手柄（或主程序版本）",
           "walk": "读不到标定"}
BOUND = ("servo", "imu", "estop", "walk")      # 跳过要绑指纹的步（配手柄不绑）


def with_skip(row, inp, rec):
    """把「跳过」套到一行上：✓ 的不变；有跳过记录、指纹没变 → 「跳过了」；指纹变了 → ●「跳过以后 xx 改过了」；
    主程序明说不行（hard）→ 跳过不管用、按钮灰着。测出了问题（found）→ 不让跳，已有的跳过作废（void_skip：tick 删掉它）。
    ● / ○ 的行带上 skip（能不能跳、为什么不能、要不要二次确认、确认那句）。"""
    key = row["key"]
    if row["state"] == "ok":
        return row
    sk = (rec.get("skipped") or {}).get(key) if isinstance(rec.get("skipped"), dict) else None
    bound, fp = step_fp(key, inp)
    if row.get("hard"):
        row["skip"] = {"ok": False, "why": row["hard"], "confirm": False}
        if sk:
            row["note"] = "之前点过跳过，但现在主程序明说这一步不行：跳过不管用"
        return row
    if row.get("found"):
        row["skip"] = {"ok": False, "why": row["found"], "confirm": False}
        if sk:
            row["note"] = "之前点过跳过；测出了问题以后跳过不算了"
            row["void_skip"] = True
        return row
    if sk:
        old = sk.get("fp")
        if bound and fp is not None and old is not None and old != fp:
            row = dict(row, state="todo", text=f"跳过以后{SKIP_CHANGED[key]}改过了：{row['text']}")
        else:
            out = _row(key, "skip", "跳过了（你说以前做过）", when=sk.get("at"))
            out["note"] = row["text"] if row["state"] != "unk" else None   # 底下真实的情况，页面小字写
            return out
    if row["state"] in ("todo", "no"):
        why = None
        if bound and fp is None:
            many = _many_unconnected(inp.get("pad")) if key == "estop" else 0
            why = (f"配过 {many} 只手柄、现在都没连：先连上一只手柄" if many else f"{FP_WHAT[key]}，现在记不了跳过：等几秒再点")
        row["skip"] = {"ok": why is None, "why": why, "confirm": key == "estop",
                       "ask": (row.get("ask") or ESTOP_ASK["never"]) if key == "estop" else None}
    return row


def evaluate(inp, rec):
    """纯函数：inp 是 Onboarding._inputs() 收好的现场，rec 是记录。回给页面的整张卡。"""
    head = header_of(inp)
    rows = [servo_row(inp, rec, head), imu_row(inp, rec, head), pad_row(inp, rec, head),
            estop_row(inp, rec, head), walk_row(inp, rec, head)]
    rows = [with_skip(r, inp, rec) for r in rows]
    nxt = next((r["key"] for r in rows if r["state"] in ("todo", "no")), None)
    return {"header": head, "rows": rows, "next": nxt, "all_done": all(r["state"] in ("ok", "skip") for r in rows),
            "skipped_n": sum(1 for r in rows if r["state"] == "skip"), "frozen": False}


# ---------------- 记录文件逐条校验（代码审查 C1：合法 JSON、但某一条类型不对，不能让整张清单每 0.5 秒出错一次） ----------------

def _opt(x, *types):
    return x is None or (isinstance(x, types) and not isinstance(x, bool))


def _at(d):
    return _opt(d.get("at"), int, float)


CHECKS = {
    "confirm_servo": lambda d: _at(d) and isinstance(d.get("fp"), str),
    "servo_studio": lambda d: _at(d) and isinstance(d.get("fp"), str) and _opt(d.get("src"), str),
    "imu_check": lambda d: (_at(d) and _opt(d.get("source"), str) and isinstance(d.get("mount_fp"), str)
                            and _num(d.get("diff_deg")) and _opt(d.get("tilt_deg"), int, float) and isinstance(d.get("ok"), bool)),
    "estop": lambda d: (_at(d) and _opt(d.get("ms"), int, float) and _opt(d.get("mac"), str) and _opt(d.get("name"), str)
                        and _opt(d.get("build"), str)),
    "stood": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
    "walked": lambda d: _num(d.get("at")) and isinstance(d.get("fp"), str),
}


def clean_records(data):
    """(能用的记录, 丢掉的 [(键, 原因)])。认识的键逐条按 CHECKS 查；pads_seen 只留 字符串 → 字符串；不认识的键原样留着（以后的版本加的）。"""
    out, bad = {}, []
    for k, v in data.items():
        if k == "v":
            continue
        if k == "pads_seen":
            if isinstance(v, dict):
                out[k] = {str(m): n for m, n in v.items() if isinstance(n, str)}
            else:
                bad.append((k, f"不是对象（{type(v).__name__}）"))
            continue
        if k == "skipped":
            if not isinstance(v, dict):
                bad.append((k, f"不是对象（{type(v).__name__}）"))
                continue
            good = {}
            for step, e in v.items():
                # at 必须是数字；绑指纹的步 fp 必须是字符串（null 的话指纹变了也作废不了，会一直「跳过了」：审查 D10）
                if (step in ORDER and isinstance(e, dict) and _num(e.get("at")) and _opt(e.get("by"), str)
                        and (isinstance(e.get("fp"), str) if step in BOUND else _opt(e.get("fp"), str))):
                    good[step] = e
                else:
                    bad.append((f"skipped.{step}", json.dumps(e, ensure_ascii=False, default=str)[:120]))
            out[k] = good
            continue
        chk = CHECKS.get(k)
        if chk is None:
            out[k] = v
            continue
        try:
            ok = isinstance(v, dict) and bool(chk(v))
        except Exception:  # noqa: BLE001
            ok = False
        if ok:
            out[k] = v
        else:
            bad.append((k, json.dumps(v, ensure_ascii=False, default=str)[:120]))
    return out, bad


def error_view(why):
    """判清单整体出错：五行都写「?」和原因（不要永远「还在判…」，代码审查 C1）。"""
    rows = [_row(k, "unk", f"Studio 判这一步时出错：{why}") for k in ORDER]
    return {"header": {"ok": False, "kind": "error", "text": "清单判的时候出错（看日志里「系统」那几行）", "raw": why},
            "rows": rows, "next": None, "all_done": False, "skipped_n": 0, "frozen": False}


# ---------------- 主体 ----------------

class Onboarding:
    def __init__(self, state_dir, log, clock=time.monotonic, wall=time.time):
        self.state_dir, self.log = state_dir, log
        self.clock, self.wall = clock, wall
        self._lk = threading.Lock()
        self._save_lk = threading.Lock()      # 整个写盘过程拿着它：两处同时存时旧的不会后落盘把新的盖掉（代码审查 C9-2）
        self.rec = {}
        self._dirty = False
        self._view = None
        self._stand_since = None
        self._walk_acc = 0.0
        self._walk_last = None
        self._studio = {"ids": set(), "time": None}
        self._studio_at = -1e9
        self._studio_mtime = None             # servo-calib 目录的 mtime：没变就不重新读文件
        self._eval_err = None                 # 上一次判清单出错的原因（同一种错只记一次）
        self._servo = None                    # 最近见到的舵机会话（取消跳过没传时用它判「清单冻着」）
        self.battery_shutdown = None          # robotd 配置的 [safety] battery_empty_shutdown：True / False / None（读不到）
        self._cfg_at = -1e9
        self.robotd_configs = ROBOTD_CONFIGS
        self.cpu_hot = False                  # 主板「有点热」带回差（审查 O8）
        self.board = None                     # Studio 自己读的主板温度（robotd 不报时兜底）
        self._board_ok = os.path.isdir(THERMAL_ROOT)
        self.load()

    # ---- 文件 ----

    def path(self):
        return os.path.join(self.state_dir or ".", ONBOARD_FILE)

    def load(self):
        """读记录。文件坏了：改名成 .bad 留着（以后查得到），当空的，记一行 warn——不能让总览因为它崩（审查 O6）。"""
        p = self.path()
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"顶层不是对象（{type(data).__name__}）")
        except FileNotFoundError:
            self.rec = {}
            return
        except (OSError, ValueError) as e:
            bad = p + ".bad"
            try:
                os.replace(p, bad)
            except OSError:
                bad = None
            self.log.warn("上手清单的记录文件读不出来，当成空的重新记", cat="系统", step=p, raw=f"{type(e).__name__}: {e}",
                          hint=(f"坏文件留在 {bad}" if bad else "坏文件改名也没成功，看看 state 目录的权限"))
            self.rec = {}
            return
        self.rec, bad = clean_records(data)
        for k, raw in bad:
            self.log.warn(f"上手清单的记录「{k}」格式不对，这一条不用了", cat="系统", step=p, raw=raw,
                          hint="多半是手改过或者旧版本写的；那一步会按「没做」重新判，做一次就会重新记")

    def save(self):
        """整份写回（先写临时文件再改名，写一半断电不会把旧的弄坏）。在线程里调；出错只记日志，不抛。"""
        with self._save_lk:
            return self._save_locked()

    def _save_locked(self):
        with self._lk:
            if not self._dirty:
                return False
            data = dict(self.rec, v=1)
            self._dirty = False
        d = self.state_dir or "."
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".onboarding-", dir=d)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path())
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError as e:
            with self._lk:
                self._dirty = True              # 下一拍再试
            self.log.warn("上手清单的记录没存进去", cat="系统", step=self.path(), raw=f"{type(e).__name__}: {e}",
                          hint="state 目录满了或者没权限；不影响站和走，下次再试")
            return False
        return True

    def _put(self, key, value, say=None, cat="系统"):
        with self._lk:
            if self.rec.get(key) == value:
                return False
            self.rec[key] = value
            self._dirty = True
        if say:
            self.log.info(say, cat=cat, dedup=False)
        return True

    # ---- 外面来的记录 ----

    def note_estop(self, r):
        """测急停过了（pad.py 测急停线程里调：只改内存）。r = {ms, mac, name, build}。"""
        try:
            rec = {"at": self.wall(), "ms": r.get("ms"), "mac": (str(r["mac"]).upper() if r.get("mac") else None),
                   "name": r.get("name"), "build": r.get("build")}
            self._put("estop", rec, say=f"上手清单：记下「测急停过了」（{rec['name'] or rec['mac'] or '手柄'}，主程序 {rec['build']}）",
                      cat="安全")
            return True
        except Exception:  # noqa: BLE001 —— 测急停线程里，记不上也不能出事
            return False

    def note_imu_check(self, c):
        """IMU 页完整站着校完（imu.py _check 调）：记最近一次核对，不管够不够近（不够近清单写「差 x°」）。"""
        rec = {"at": self.wall(), "source": c.get("source"), "mount_fp": mount_fp(c.get("source"), c.get("quat")),
               "diff_deg": c.get("diff_deg"), "tilt_deg": c.get("tilt_deg"), "ok": bool(c.get("ok")), "by": c.get("by")}
        if rec["mount_fp"] is None:
            return False
        return self._put("imu_check", rec, say=f"上手清单：记下 IMU 核对（差 {rec['diff_deg']}°，{'够' if rec['ok'] else '不够'}近）",
                         cat="IMU") or True

    def confirm_servo(self, rd, by=None):
        """「已经校过，核对一下」：主程序文件里 15 颗都标了、zero_raw 全是 2048，才记一笔（指纹绑关节）。不能记就回原因。"""
        calib = fresh_calib(rd)
        js = _joints(calib)
        if not js:
            return False, "这次连上以后还没读到主程序的标定文件：等几秒再点"
        if (calib or {}).get("uncalibrated_joints"):
            return False, "主程序说还有没标的关节：去舵机页标"
        off = [j for j in js if j.get("zero_raw") != 2048 or j.get("calibrated") is False]
        if off:
            return False, f"有 {len(off)} 颗的 zero_raw 不是 2048（或者没标）：两套零位会打架，去舵机页标"
        if len(js) < len(SERVO_IDS):
            return False, f"主程序文件里只有 {len(js)} 颗"
        fp = joints_fp(calib)
        self._put("confirm_servo", {"at": self.wall(), "fp": fp, "by": by},
                  say=f"上手清单：舵机零位「已经校过，核对一下」（{by or '页面'}；主程序文件里 15 颗都是 2048）", cat="校准")
        return True, None

    def skip(self, step, rd, pad=None, servo=None, by=None):
        """「跳过」：按现在的情况重判一遍，这一行是 ● / ○、又没被主程序明说不行、指纹读得到，才记 skipped.<步>。
        不能跳回 (False, 原因)：页面按钮灰着也不能只靠它（IMU 方向主程序明说没确认时，前端灰、后端也拒）。"""
        if step not in ORDER:
            return False, f"不认识的步骤：{step}"
        if servo is not None:
            self._servo = servo
        inp = self._inputs(rd, pad, servo, self.clock())
        if inp["servo_session"]:
            return False, FROZEN_WHY
        if inp["bench"]:
            return False, "台架模式：清单现在不判，也不能跳过"
        with self._lk:
            rec = dict(self.rec)
        row = next(r for r in evaluate(inp, rec)["rows"] if r["key"] == step)
        if row["state"] == "skip":
            return True, "已经跳过了"
        if row["state"] == "ok":
            return False, "这一步已经完成了，不用跳过"
        sk = row.get("skip")
        if sk is None:
            return False, "这一步现在读不到（?），不让跳过：等它读出来再说"
        if not sk["ok"]:
            return False, sk["why"]
        bound, fp = step_fp(step, inp)
        with self._lk:
            skipped = dict(self.rec.get("skipped") or {})
        skipped[step] = {"at": self.wall(), "by": by, "fp": fp if bound else None}
        self._put("skipped", skipped, say=f"上手清单：{TITLES[step]} 跳过（{by or '页面'}）", cat="校准")
        return True, None

    def unskip(self, step, by=None, servo=None):
        """「取消跳过」：删掉 skipped.<步>，那一行回到按真实情况判。调舵机时清单冻结着，也不收（审查 D11）。"""
        if step not in ORDER:
            return False, f"不认识的步骤：{step}"
        sv = servo if servo is not None else self._servo      # 没传就看 tick / skip 最近见到的那个舵机会话
        if sv is not None and getattr(sv, "state", None) in ("open", "opening"):
            return False, FROZEN_WHY
        with self._lk:
            skipped = dict(self.rec.get("skipped") or {})
        if step not in skipped:
            return True, "本来就没跳过"
        skipped.pop(step)
        self._put("skipped", skipped, say=f"上手清单：{TITLES[step]} 取消跳过（{by or '页面'}）", cat="校准")
        return True, None

    # ---- 读文件：在线程里（app 用 asyncio.to_thread 调），tick 只用缓存（代码审查 C9-1） ----

    def need_board(self, rd):
        """robotd 没报温度（调试模式、等总线、过期）时才要 Studio 自己读 /sys/class/thermal。在事件循环里调（只看内存）。"""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        return self._board_ok and not (isinstance(h, dict) and _num(h.get("cpu_temp_c")))

    def io(self, board=False, now=None):
        """在线程里调：servo-calib 目录（mtime 变了、或者 10 秒到了才重读）、主板温度（board=True 才读）。不抛。"""
        now = self.clock() if now is None else now
        try:
            d = os.path.join(self.state_dir or ".", "servo-calib")
            try:
                mt = os.stat(d).st_mtime
            except OSError:
                mt = None
            if mt != self._studio_mtime or now - self._studio_at >= STUDIO_SCAN_S:
                self._studio = studio_servo_record(self.state_dir)
                self._studio_mtime, self._studio_at = mt, now
        except Exception:  # noqa: BLE001 —— 读不到就当没有记录
            pass
        if board:
            try:
                self.board = read_board()
            except Exception:  # noqa: BLE001
                self.board = None
        else:
            self.board = None
        if now - self._cfg_at >= ROBOTD_CFG_S:
            self._cfg_at = now
            self.battery_shutdown = read_battery_shutdown(self.robotd_configs)

    # ---- 每 0.5 秒一次 ----

    def _inputs(self, rd, pad, servo, now):
        bus = rd.bus.value if isinstance(rd.bus.value, dict) else None
        calib = fresh_calib(rd)
        pv = None
        if pad is not None:
            try:
                pv = pad.onboard_view()
            except Exception as e:  # noqa: BLE001 —— 手柄后端出错：这一行写「读不到」，别把整张卡弄没
                pv = {"known": False, "error": f"{type(e).__name__}: {e}", "pads": []}
        return {"bench": getattr(rd, "addr", None) == "none", "present": rd.present, "bus": bus, "calib": calib,
                "servo_session": servo is not None and getattr(servo, "state", None) in ("open", "opening"),
                "pad": pv, "studio_servo": self._studio, "fp": full_fp(bus, calib)}

    def tick(self, rd, pad=None, servo=None, now=None):
        """判一遍、记该记的（只改内存，不读文件）。回 True = 记录变了，调用方在线程里 save()。
        主板温度的回差先算、单独 try：判清单出错不能让它停在旧值（代码审查 C1）。"""
        now = self.clock() if now is None else now
        if servo is not None:
            self._servo = servo
        try:
            self._board_tick(rd)
        except Exception as e:  # noqa: BLE001
            self.log.error("算主板温度的回差时出错", cat="系统", raw=f"{type(e).__name__}: {e}", exc=True)
        try:
            inp = self._inputs(rd, pad, servo, now)
            if not inp["servo_session"]:
                self._track(rd, inp, now)
            with self._lk:
                rec = dict(self.rec)
            v = evaluate(inp, rec)
            if not inp["servo_session"]:
                self._void_skips(v)
            if inp["servo_session"] and self._view is not None and self._view["header"].get("kind") != "error":
                # 在舵机页调舵机：主程序按计划停着，各步保留上一次的显示、变灰（审查判法表「在调舵机」一行）
                v = dict(self._view, header=v["header"], frozen=True)
            self._eval_err = None
        except Exception as e:  # noqa: BLE001 —— 清单出错：五行写「?」和原因，记一行（同一种错只记一次）
            why = f"{type(e).__name__}: {e}"[:200]
            if why != self._eval_err:
                self._eval_err = why
                self.log.error("上手清单判的时候出错，清单先写「?」", cat="系统", raw=why, exc=True,
                               hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
            v = error_view(why)
        self._view = v
        with self._lk:
            return self._dirty

    def _void_skips(self, v):
        """测出了问题的行（found），之前的跳过作废：从记录里删掉、记一行（审查 D5）。页面这一拍已经按问题显示了。"""
        gone = [r for r in v["rows"] if r.get("void_skip")]
        if not gone:
            return
        with self._lk:
            skipped = dict(self.rec.get("skipped") or {})
        for r in gone:
            skipped.pop(r["key"], None)
        self._put("skipped", skipped, cat="校准",
                  say="上手清单：" + "、".join(f"{r['title']}的跳过作废（{r['found']}）" for r in gone))

    def _track(self, rd, inp, now):
        """站起来过、走过、配过哪些手柄（只看 Studio 自己收到的状态：robot.state 要有页面看着才推）。"""
        bus = inp["bus"] or {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # 数据新不新看真的钟（Sample 记的是 monotonic）；站了多久、走了多久看 now（测试里能拨）。新鲜度跟 state.MAX_AGE 一样
        pa, sa = rd.policies.age(), rd.state.age()
        pol = rd.policies.value if pa is not None and pa <= MAX_AGE["policies"] else None
        st = rd.state.value if sa is not None and sa <= MAX_AGE["state"] else None
        pose = posture(rd.present, inp["bus"], pol, st)
        # 指纹读不到（robotd 刚重启、刚起来、标定读失败在重试）：不记、不覆盖带指纹的旧记录——不然标定读回来以后
        # 第 5 步会变成「标定改过以后还没站过」（代码审查 C2）。站的计时、走的累计照样算，读到了马上记
        fp = inp["fp"]
        if pose in STAND and native.get("torque_state_confirmed") is True:
            if self._stand_since is None:
                self._stand_since = now
            elif now - self._stand_since >= STOOD_S and fp is not None:
                old = self.rec.get("stood") if isinstance(self.rec.get("stood"), dict) else None
                if old is None or old.get("fp") != fp:
                    self._put("stood", {"at": self.wall(), "fp": fp}, say="上手清单：记下「站起来过」", cat="手柄")
        else:
            self._stand_since = None
        if pose == "walking":
            if self._walk_last is not None:
                self._walk_acc += min(now - self._walk_last, 1.0)
            self._walk_last = now
            old = self.rec.get("walked") if isinstance(self.rec.get("walked"), dict) else None
            if self._walk_acc >= WALKED_S and fp is not None and (old is None or old.get("fp") != fp):
                self._walk_acc = 0.0
                self._put("walked", {"at": self.wall(), "fp": fp}, say="上手清单：记下「走过」", cat="手柄")
        else:
            self._walk_last = None
        # 舵机页标过 15 颗、主程序文件里也都是 2048：记下这时的关节指纹，之后变了要重新核对（代码审查 C9-3）
        stu = inp["studio_servo"] or {}
        js = _joints(inp["calib"])
        jfp = joints_fp(inp["calib"])
        if set(SERVO_IDS) <= set(stu.get("ids") or ()) and js and jfp and all(j.get("zero_raw") == 2048 for j in js):
            ss = self.rec.get("servo_studio") if isinstance(self.rec.get("servo_studio"), dict) else None
            if ss is None or ss.get("src") != stu.get("time"):
                self._put("servo_studio", {"at": self.wall(), "fp": jfp, "src": stu.get("time")},
                          say="上手清单：舵机页的标定记录跟主程序文件对上了（15 颗都是 2048）", cat="校准")
        pv = inp["pad"] or {}
        seen = dict(self.rec.get("pads_seen") or {}) if isinstance(self.rec.get("pads_seen"), dict) else {}
        changed = False
        for p in pv.get("pads") or []:
            if isinstance(p, dict) and p.get("paired") and p.get("mac") and seen.get(str(p["mac"]).upper()) != p.get("name"):
                seen[str(p["mac"]).upper()] = p.get("name") or p.get("mac")
                changed = True
        if changed:
            self._put("pads_seen", seen)

    def _board_tick(self, rd):
        """主板温度：回差（≥ 80 °C 亮、降到 77 °C 以下才收）；robotd 不报时用 Studio 自己读的（io() 在线程里读好的
        /sys/class/thermal，鸭子上才有）。"""
        ha = rd.health.age()
        h = rd.health.value if ha is not None and ha <= MAX_AGE["health"] else None
        c = (h or {}).get("cpu_temp_c") if isinstance(h, dict) else None
        if not _num(c):
            c = (self.board or {}).get("c") if isinstance(self.board, dict) else None
        if not _num(c):
            self.cpu_hot = False
        elif c >= CPU_WARN_C:
            self.cpu_hot = True
        elif c < CPU_CLEAR_C:
            self.cpu_hot = False

    def view(self):
        return self._view
