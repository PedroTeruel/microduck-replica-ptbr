"""电池电量估算（studio/battery.py、battery-plan.md v2）：查表、去极值、估算中 30 秒、轻松段选取、警告 60 秒 + 回差、
负载线 30 秒、读不到 10 秒重新起步、读数校准、设置文件，以及拿一号鸭 10-12 / 10-13 的上机录像回放。
跑法（studio 目录下）：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_battery'])"
回放数据 tests/fixtures/battery-*.csv：robotd EMA 后的电压反推回每秒的原始读数（15 颗平均）+ 那一秒的状态类别，
做法见文件第一行注释（scratchpad/battery_an/build_fixture.py）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio import battery as B  # noqa: E402

FIX = HERE / "fixtures"
# 二号鸭 10-18 22:03 卸力时 15 颗的电压（ID 20–24 | 30–34 | 10–14），battery-plan.md §2.1
DUCK2 = [7.6, 7.7, 7.6, 7.6, 7.6, 7.7, 7.6, 7.6, 7.5, 7.6, 7.6, 7.7, 7.7, 7.6, 7.7]


class FakeLog:
    def __init__(self):
        self.lines = []

    def write(self, msg, cat="系统", level="info", **kw):
        self.lines.append((level, cat, msg, kw))

    def warn(self, msg, **kw):
        self.lines.append(("warn", kw.get("cat"), msg, kw))


def flat(v):
    """15 颗都一样的读数（回放数据是 15 颗平均，喂成 15 个一样的值，去头去尾平均还是它）。"""
    return [v] * 15


def run(e, seq, t0=0.0, source="robotd"):
    """seq：[(秒数, 电压或 None, cls), …] 每秒一个；电压 None = 这一秒没有新数据。回 (结束时间, 所有事件)。"""
    events = []
    t = t0
    for i, (v, cls) in enumerate(seq):
        t = t0 + i
        if v is None:
            events += [(t, x) for x in e.feed(t, None)]
        else:
            events += [(t, x) for x in e.feed(t, flat(v), None, cls, key=("k", t), source=source)]
    return t, events


def hold(v, cls, n):
    return [(v, cls)] * n


def load_fixture(name):
    rows = []
    for line in open(FIX / name, encoding="utf-8"):
        if line.startswith("#") or line.startswith("t,"):
            continue
        t, v, c = line.strip().split(",")
        rows.append((int(t), float(v), c))
    return rows


def replay(e, rows, t0=0.0):
    """按录像的秒数喂；录像里缺的秒当「这一秒没有新数据」。回 ({秒: 显示的 %}, 事件, 模式记录)。"""
    d = {t: (v, c) for t, v, c in rows}
    shown, events, modes = {}, [], {}
    for t in range(0, rows[-1][0] + 1):
        now = t0 + t
        if t in d:
            v, c = d[t]
            ev = e.feed(now, flat(v), None, c, key=("r", now))
        else:
            ev = e.feed(now, None)
        events += [(t, x) for x in ev]
        shown[t], modes[t] = e.shown, e.mode
    return shown, events, modes


class TableTest(unittest.TestCase):
    def test_points_and_interpolation(self):
        self.assertEqual(B.soc_from_cell(4.20), 100)
        self.assertEqual(B.soc_from_cell(3.80), 46)
        self.assertAlmostEqual(B.soc_from_cell(3.825), 50.5)
        self.assertEqual(B.soc_from_cell(4.35), 100)
        self.assertEqual(B.soc_from_cell(2.8), 0)
        self.assertIsNone(B.soc_from_cell(float("nan")))
        # 方案 §3.1 的换算：30% = 7.42 V、15% = 7.24 V（整包）
        self.assertAlmostEqual(B.soc_from_pack(7.422), 30, delta=0.3)
        self.assertAlmostEqual(B.soc_from_pack(7.242), 15, delta=0.3)
        self.assertAlmostEqual(B.soc_from_pack(7.63), 48.7, delta=0.3)

    def test_monotonic(self):
        prev = -1
        for i in range(600, 860):
            p = B.soc_from_pack(i / 100)
            self.assertGreaterEqual(p, prev)
            prev = p

    def test_robotd_line_for_comparison(self):
        self.assertAlmostEqual(B.linear_pct(7.63), 64.4, delta=0.1)
        self.assertEqual(B.linear_pct(6.0), 0)
        self.assertEqual(B.linear_pct(9.0), 100)
        self.assertIsNone(B.linear_pct(0))


class TrimmedTest(unittest.TestCase):
    def test_duck2_set(self):
        v, n, _ = B.trimmed(DUCK2)
        self.assertEqual(n, 15)
        self.assertAlmostEqual(v, 7.622, places=3)     # 审查核过：平均 7.627、去头去尾 7.622

    def test_invalid_and_outliers(self):
        vs = list(DUCK2)
        vs[0], vs[1], vs[2] = 0.0, 9.9, None            # 0 V、超范围、读不到：都不算
        vs[3], vs[4] = 4.2, 5.0                         # 两颗读坏的：被去掉的最低那 3 颗吃掉
        v, n, valid = B.trimmed(vs)
        self.assertEqual(n, 12)
        self.assertAlmostEqual(v, 7.62, delta=0.04)
        self.assertNotIn(0, [i for i, _ in valid])

    def test_fresh_filter_and_small_counts(self):
        fresh = [True] * 7 + [False] * 8
        v, n, _ = B.trimmed(DUCK2, fresh)
        self.assertEqual(n, 7)
        self.assertEqual(v, 7.6)                        # 5–8 颗取中位
        v, n, _ = B.trimmed(DUCK2[:4])
        self.assertIsNone(v)
        self.assertEqual(n, 4)
        self.assertEqual(B.trimmed(None)[0], None)
        self.assertEqual(B.trimmed([True] * 15)[0], None)   # bool 不是电压


class ClassifyTest(unittest.TestCase):
    def test_from_robotd_shapes(self):
        rows = [json.loads(line) for line in open(FIX / "now-20261018.jsonl", encoding="utf-8")]
        bus = next(r for r in rows if r.get("method") == "robot.busStatus")["reply"]["result"]
        st = {"policy": "walk", "move": {"applied": [0.0, 0.0, 0.0]}, "safety": {"fallen": False}}
        self.assertEqual(B.classify_robotd(bus, st), "light")       # 真机回包：扭矩开着保持
        vs, fr = B.robotd_volts(bus)
        self.assertEqual(len(vs), 15)
        self.assertAlmostEqual(B.trimmed(vs, fr)[0], 7.544, delta=0.01)
        moving = dict(st, move={"applied": [0.1, 0.0, 0.0]})
        self.assertEqual(B.classify_robotd(bus, moving), "heavy")
        self.assertEqual(B.classify_robotd(bus, dict(st, policy="kick_left")), "heavy")
        self.assertEqual(B.classify_robotd(bus, dict(st, safety={"fallen": True})), "heavy")
        self.assertEqual(B.classify_robotd(bus, dict(st, policy="sit")), "light")
        limp = json.loads(json.dumps(bus))
        limp["native"]["torque_state_confirmed"] = False
        self.assertEqual(B.classify_robotd(limp, moving), "rest")    # 卸力了就是卸力，不管指令
        unknown = json.loads(json.dumps(bus))
        unknown["native"]["torque_state_confirmed"] = None
        self.assertIsNone(B.classify_robotd(unknown, st))
        self.assertEqual(B.robotd_volts({"mode": "motion"}), (None, None))

    def test_servo_session(self):
        rows = [{"volt": 7.6, "fresh": True, "torque": False} for _ in range(15)]
        self.assertEqual(B.classify_servo_session(rows), "rest")
        rows[3]["torque"] = True
        self.assertEqual(B.classify_servo_session(rows), "light")
        self.assertIsNone(B.classify_servo_session([{"volt": 7.6}]))
        vs, fr = B.servo_session_volts(rows)
        self.assertEqual(vs[0], 7.6)
        self.assertTrue(all(fr))


class EstimatingTest(unittest.TestCase):
    def test_first_30s_estimating_no_number(self):
        e = B.Estimator()
        t, ev = run(e, hold(7.4, "light", 29))
        self.assertEqual(e.mode, "estimating")
        self.assertIsNone(e.shown)
        v = e.view(t)
        self.assertIsNone(v["pct"])
        self.assertEqual(v["why"], "估算中，刚开始读")
        self.assertGreater(v["estimating_left_s"], 0)
        run(e, hold(7.4, "light", 3), t0=t + 1)
        self.assertEqual(e.mode, "calm")
        self.assertIsNotNone(e.shown)

    def test_restart_in_walking_trough_no_red(self):
        """B-R2：Studio 在走路时重启，第一秒正好是 4.21 V 那种毛刺 → 头 30 秒不出数，之后也不出红条。"""
        e = B.Estimator()
        seq = [(4.21, "heavy")] + [(7.25 if i % 2 else 7.05, "heavy") for i in range(400)]
        t, ev = run(e, seq)
        self.assertEqual(e.mode, "load_rough")
        self.assertFalse(e.red.on)
        self.assertNotIn("error", [x["level"] for _, x in ev])
        self.assertIsNotNone(e.shown)
        self.assertGreater(e.shown, 3)
        v = e.view(t)
        self.assertEqual(v["why"], "走路中，按负载电压粗估，偏低")
        self.assertIn("偏低", " ".join(v["detail"]))

    def test_no_warning_while_estimating(self):
        e = B.Estimator()
        t, ev = run(e, hold(6.5, "heavy", 29))
        self.assertEqual(ev, [])
        self.assertIsNone(e.level())


class CalmTest(unittest.TestCase):
    def test_long_hold_then_stand_comes_back(self):
        """B-R1 / B-R14.2：长时间 HOME 保持（7.52）以后换到站着（7.70），显示要能回来，不能卡在保持的数上。"""
        e = B.Estimator()
        t, _ = run(e, hold(7.52, "light", 338))
        low = e.shown
        self.assertAlmostEqual(low, B.soc_from_pack(7.52), delta=1)
        t, _ = run(e, hold(7.70, "light", 60), t0=t + 1)
        self.assertGreaterEqual(e.shown, 54)
        self.assertGreater(e.shown, low + 10)

    def test_walking_keeps_the_calm_estimate_then_ages_out(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.70, "rest", 60))
        calm = e.shown
        t, _ = run(e, hold(7.40, "heavy", 200), t0=t + 1)
        self.assertEqual(e.shown, calm)                 # 5 分钟以内：还是停下时的估算
        self.assertEqual(e.view(t)["why"], "走路中，按停下时的电压估")
        t, _ = run(e, hold(7.40, "heavy", 200), t0=t + 1)
        self.assertEqual(e.mode, "load_rough")          # 一直走超过 5 分钟：改成负载粗估
        self.assertEqual(e.shown, round(B.soc_from_pack(7.40)))
        t, _ = run(e, hold(7.62, "light", 31), t0=t + 1)
        self.assertEqual(e.mode, "calm")                # 站 30 秒就按站着的电压
        self.assertEqual(e.shown, round(B.soc_from_pack(7.62)))

    def test_most_relaxed_in_5min_wins(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.76, "rest", 40) + hold(7.52, "light", 120))
        self.assertEqual(e.shown, round(B.soc_from_pack(7.76)))   # 卸力那段更轻松
        self.assertEqual(e.view(t)["basis"]["cls"], "rest")

    def test_deadband(self):
        e = B.Estimator()
        seq = [(7.62 if i % 2 else 7.64, "rest") for i in range(200)]
        run(e, seq)
        first = e.shown
        seen = set()
        for i in range(300):
            v = 7.60 + 0.05 * (i % 3) / 2
            e.feed(200.0 + i, flat(v), None, "rest", key=i)
            seen.add(e.shown)
        self.assertLessEqual(len(seen), 2)
        self.assertLessEqual(abs(first - min(seen)), 2)


class WarningTest(unittest.TestCase):
    def test_warn_needs_60s_and_hysteresis(self):
        e = B.Estimator()
        t, ev = run(e, hold(7.40, "rest", 30 + 59))      # 28% < 30%；起步 30 秒 + 59 秒
        self.assertFalse(e.warn.on)
        t, ev = run(e, hold(7.40, "rest", 2), t0=t + 1)
        self.assertTrue(e.warn.on)
        self.assertEqual(e.level(), "warn")
        warns = [x["msg"] for _, x in ev if x["level"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertTrue(warns[0].startswith("电量到提醒线 30%"))
        # 32%：还在回差里（30 + 3）
        t, _ = run(e, hold(7.445, "rest", 120), t0=t + 1)
        self.assertTrue(e.warn.on)
        # 37%：持续 60 秒才收
        t, _ = run(e, hold(7.50, "rest", 40), t0=t + 1)
        self.assertTrue(e.warn.on)
        t, ev = run(e, hold(7.50, "rest", 40), t0=t + 1)
        self.assertFalse(e.warn.on)
        self.assertTrue(any("收起" in x["msg"] for _, x in ev))

    def test_flapping_does_not_flash(self):
        """在线附近来回：60 秒持续条件 + 死区，不会一会儿亮一会儿灭。"""
        e = B.Estimator()
        changes = 0
        last = None
        for i in range(1200):
            v = 7.42 + (0.03 if (i // 20) % 2 else -0.03)
            e.feed(float(i), flat(v), None, "rest", key=i)
            lv = e.level()
            if lv != last:
                changes += 1
                last = lv
        self.assertLessEqual(changes, 2)

    def test_red(self):
        e = B.Estimator()
        t, ev = run(e, hold(7.20, "rest", 100))
        self.assertTrue(e.red.on)
        self.assertTrue(e.warn.on)
        self.assertEqual(e.level(), "error")
        items = B.todo_items(e.view(t))
        self.assertEqual(items[0]["level"], "error")
        self.assertIn("电量只剩约", items[0]["msg"])
        self.assertIn("不会自己停", items[0]["hint"])
        self.assertEqual(len([i for i in items if i["key"] == "battery"]), 1)

    def test_rough_estimate_caps_at_yellow(self):
        """一直在走、没有轻松段：负载电压查表偏低，最多出黄条；红条只认轻松段或负载线。"""
        e = B.Estimator()
        t, ev = run(e, hold(7.20, "heavy", 600))
        self.assertEqual(e.mode, "load_rough")
        self.assertTrue(e.warn.on)
        self.assertFalse(e.red.on)
        self.assertEqual(e.level(), "warn")
        self.assertIn("粗估", B.todo_items(e.view(t))[0]["msg"])

    def test_settings_change_applies_next_tick(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.45, "rest", 100))           # 32%
        self.assertFalse(e.warn.on)
        e.set_settings(dict(e.settings, warn_pct=40))
        t, _ = run(e, hold(7.45, "rest", 61), t0=t + 1)
        self.assertTrue(e.warn.on)
        self.assertEqual(e.view(t)["warn_pct"], 40)


class LoadLineTest(unittest.TestCase):
    def test_30s_then_on_and_clears_after_60s(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.60, "rest", 60))
        t, ev = run(e, hold(6.85, "heavy", 35), t0=t + 1)   # 10 秒中位要先落下去，再持续 30 秒
        self.assertFalse(e.low.on)
        t, ev = run(e, hold(6.85, "heavy", 10), t0=t + 1)
        self.assertTrue(e.low.on)
        self.assertEqual(e.level(), "error")
        msg = [x for _, x in ev if x["level"] == "error"]
        self.assertTrue(msg and msg[0]["msg"].startswith("电压很低"))
        items = B.todo_items(e.view(t))
        self.assertEqual(items[0]["key"], "battery_low_volt")
        t, _ = run(e, hold(7.05, "light", 50), t0=t + 1)
        self.assertTrue(e.low.on)                           # 亮了至少 60 秒才收
        t, _ = run(e, hold(7.05, "light", 30), t0=t + 1)
        self.assertFalse(e.low.on)

    def test_uses_calibrated_voltage(self):
        """B-R10 / B-R14.7：负载线也用校准后的值。读数偏低 0.2 V 时，6.85 的读数其实是 7.05。"""
        e = B.Estimator({"cal_offset_v": 0.2})
        t, _ = run(e, hold(7.60, "rest", 60) + hold(6.85, "heavy", 120))
        self.assertFalse(e.low.on)
        self.assertAlmostEqual(e.view(t)["volts"], 7.05, delta=0.01)

    def test_short_dips_ignored(self):
        e = B.Estimator()
        seq = hold(7.60, "rest", 60)
        for i in range(300):                                 # 走路：每 10 秒里 3 秒掉到 6.7
            seq.append((6.7 if i % 10 < 3 else 7.3, "heavy"))
        t, ev = run(e, seq)
        self.assertFalse(e.low.on)


class GapTest(unittest.TestCase):
    def test_no_voltage_10s_restarts(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.40, "rest", 100))
        self.assertEqual(e.mode, "calm")
        t, ev = run(e, [(None, None)] * 9, t0=t + 1)
        self.assertEqual(e.mode, "calm")                   # 9 秒：还接着用
        t, ev = run(e, [(None, None)] * 3, t0=t + 1)
        self.assertEqual(e.mode, "no_data")
        self.assertIsNone(e.shown)
        self.assertIsNone(e.level())
        self.assertTrue(any("重新估算" in x["msg"] for _, x in ev))
        self.assertEqual(e.view(t)["why"], "读不到电压")
        t, _ = run(e, hold(7.40, "rest", 5), t0=t + 1)
        self.assertEqual(e.mode, "estimating")

    def test_all_servos_invalid_counts_as_no_data(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.40, "rest", 60))
        for i in range(12):
            e.feed(t + 1 + i, [0.0] * 15, None, "rest", key=("z", i))
        self.assertEqual(e.mode, "no_data")

    def test_swap_battery_after_gap_logs(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.40, "rest", 100))
        t, _ = run(e, [(None, None)] * 15, t0=t + 1)
        t, ev = run(e, hold(8.10, "rest", 40), t0=t + 1)
        self.assertEqual(e.shown, round(B.soc_from_pack(8.10)))
        self.assertTrue(any("换了电池或充过电" in x["msg"] for _, x in ev))


class FeedTest(unittest.TestCase):
    def test_three_pages_do_not_duplicate(self):
        """B-R7 / B-R14.3：同一份 busStatus（同一个 key）喂三遍只算一次。"""
        e = B.Estimator()
        for i in range(40):
            for _ in range(3):
                e.feed(i + 0.1, flat(7.5), None, "rest", key=("bus", i))
        self.assertEqual(len(e.samples), 40)
        e2 = B.Estimator()
        for i in range(40):
            for j in range(3):
                e2.feed(i + j * 0.1, flat(7.5), None, "rest")   # 没给 key：同一秒按时间去重
        self.assertEqual(len(e2.samples), 40)

    def test_source_switch_does_not_jump(self):
        """B-R14.5：robotd ↔ 调舵机（Studio 自己读总线）切换，同样的电压显示不变。"""
        e = B.Estimator()
        t, _ = run(e, hold(7.62, "rest", 100))
        before = e.shown
        for i in range(60):
            rows = [{"volt": 7.62, "fresh": True, "torque": False} for _ in range(15)]
            vs, fr = B.servo_session_volts(rows)
            e.feed(t + 1 + i, vs, fr, B.classify_servo_session(rows), key=("servo", i), source="servo")
        self.assertEqual(e.shown, before)
        self.assertEqual(e.source, "servo")
        # 调舵机时照样有电量待办（B-R6：集成时 todo 要在 servo_session 的 return 之前加这几条）
        e3 = B.Estimator()
        rows = [{"volt": 7.20, "fresh": True, "torque": False} for _ in range(15)]
        for i in range(100):
            vs, fr = B.servo_session_volts(rows)
            e3.feed(float(i), vs, fr, "rest", key=i, source="servo")
        self.assertEqual(B.todo_items(e3.view(99.0))[0]["level"], "error")

    def test_view_detail_and_spread(self):
        e = B.Estimator()
        for i in range(40):
            e.feed(float(i), DUCK2, None, "rest", key=i)
        names = ["左髋转向", "左髋横滚", "左髋俯仰", "左膝", "左踝", "脖子", "头俯仰", "头转向", "头横滚", "嘴",
                 "右髋转向", "右髋横滚", "右髋俯仰", "右膝", "右踝"]
        v = e.view(39.0, rd={"volts": 7.63, "percent": 64.4}, names=names)
        self.assertEqual(v["pct"], round(B.soc_from_pack(7.622)))
        self.assertEqual(v["why"], "静置")
        self.assertEqual(v["rd_pct"], 64)
        self.assertEqual(v["spread"]["min_name"], "头横滚")
        text = "\n".join(v["detail"])
        for s in ("15 颗去掉最高最低各 3 颗的平均", "每芯 3.81 V", "主程序自己的算法：64%", "直线，低电量偏高",
                  "放空了尽快充；长期不用存一半电（约 7.4–7.6 V）", "不会自己停", "黄条会比以前早亮", "±15%"):
            self.assertIn(s, text)
        self.assertIn("没电自动坐下关机", "\n".join(e.view(39.0, shutdown=True)["detail"]))

    def test_bench_preset(self):
        e = B.Estimator({"preset": "bench"})
        t, ev = run(e, hold(7.40, "rest", 60) + hold(6.80, "heavy", 60))
        v = e.view(t)
        self.assertIsNone(v["pct"])
        self.assertEqual(v["mode"], "bench")
        self.assertFalse(e.warn.on)
        self.assertTrue(e.low.on)                          # 电压线照样提醒

    def test_glitch_logged_once(self):
        e = B.Estimator()
        seq = hold(7.60, "light", 60) + [(4.21, "light")] + hold(7.60, "light", 5) + [(4.3, "light")] + hold(7.6, "light", 30)
        t, ev = run(e, seq)
        g = [x for _, x in ev if "掉了 1 V" in x["msg"]]
        self.assertEqual(len(g), 1)                        # 一分钟最多一条
        self.assertIn("4.21", g[0]["raw"])
        self.assertEqual(e.shown, round(B.soc_from_pack(7.60)))

    def test_log_events(self):
        log = FakeLog()
        e = B.Estimator()
        _, ev = run(e, hold(7.60, "rest", 40))
        B.log_events(log, [x for _, x in ev])
        self.assertTrue(log.lines)
        self.assertTrue(all(c == "电池" for _, c, _, _ in log.lines))
        self.assertIn("电量估算起步", log.lines[0][2])
        B.log_events(None, [x for _, x in ev])             # 没有 log 不出错


class CalibrateTest(unittest.TestCase):
    def test_offset_from_meter(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.60, "rest", 40))
        r = e.calibrate(t, 7.75)
        self.assertTrue(r["ok"])
        self.assertAlmostEqual(r["offset"], 0.15)
        self.assertFalse(r["confirm"])
        before = e.shown
        e.set_settings(dict(e.settings, cal_offset_v=r["offset"]))
        t, _ = run(e, hold(7.60, "rest", 3), t0=t + 1)
        self.assertEqual(e.shown, round(B.soc_from_pack(7.75)))
        self.assertGreater(e.shown, before)
        # 校准以后再量一次：差值还是按原始读数算（不会越校越多）
        self.assertAlmostEqual(e.calibrate(t, 7.75)["offset"], 0.15)

    def test_needs_rest_and_sane_value(self):
        e = B.Estimator()
        t, _ = run(e, hold(7.60, "light", 40))
        self.assertFalse(e.calibrate(t, 7.7)["ok"])         # 站着不收
        t, _ = run(e, hold(7.60, "rest", 20), t0=t + 1)
        self.assertFalse(e.calibrate(t, 7.7)["ok"])         # 卸力不到 30 秒（站着那段不算）
        t, _ = run(e, hold(7.60, "rest", 15), t0=t + 1)
        self.assertTrue(e.calibrate(t, 7.7)["ok"])
        self.assertTrue(e.calibrate(t, 7.95)["confirm"])    # 差 0.35 V：先问一句
        self.assertFalse(e.calibrate(t, 8.2)["ok"])         # 差 0.6 V：超范围
        self.assertFalse(e.calibrate(t, 12.0)["ok"])
        self.assertFalse(e.calibrate(t, "7.7")["ok"])


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="battery-test-")

    def test_validate(self):
        s, err = B.validate_settings({})
        self.assertEqual((s, err), (B.DEFAULTS, []))
        s, err = B.validate_settings({"red_pct": 20, "cal_offset_v": 0.123})
        self.assertEqual(err, [])
        self.assertEqual((s["red_pct"], s["cal_offset_v"]), (20, 0.12))
        self.assertTrue(B.validate_settings({"capacity_mah": 2600})[1])          # v1 没有容量
        self.assertTrue(B.validate_settings({"warn_pct": 70})[1])
        self.assertTrue(B.validate_settings({"warn_pct": 30.5})[1])
        self.assertTrue(B.validate_settings({"warn_pct": True})[1])
        self.assertTrue(B.validate_settings({"load_floor_v": "6.9"})[1])
        self.assertTrue(B.validate_settings({"cal_offset_v": 0.6})[1])
        self.assertTrue(B.validate_settings({"preset": "lipo"})[1])
        self.assertTrue(B.validate_settings({"warn_pct": 20, "red_pct": 16})[1])  # 红线没比提醒线低 5%
        self.assertEqual(B.validate_settings({"warn_pct": 20, "red_pct": 15})[1], [])
        self.assertTrue(B.validate_settings([1])[1])
        with self.assertRaises(B.SettingsError):
            B.Estimator({"red_pct": 99})

    def test_roundtrip_and_atomic(self):
        self.assertEqual(B.load_settings(self.dir), B.DEFAULTS)           # 没文件 = 默认
        saved = B.save_settings(self.dir, dict(B.DEFAULTS, red_pct=20, cal_offset_v=-0.1))
        self.assertEqual(saved["red_pct"], 20)
        self.assertEqual(os.listdir(self.dir), [B.SETTINGS_FILE])         # 临时文件没留下
        with open(B.settings_path(self.dir), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["v"], 1)
        self.assertEqual(B.load_settings(self.dir)["cal_offset_v"], -0.1)
        with self.assertRaises(B.SettingsError):
            B.save_settings(self.dir, dict(B.DEFAULTS, red_pct=50))
        self.assertEqual(B.load_settings(self.dir)["red_pct"], 20)        # 不合法的没写进去
        with self.assertRaises(B.SettingsError):
            B.save_settings(None, B.DEFAULTS)

    def test_bad_file(self):
        p = B.settings_path(self.dir)
        with open(p, "w", encoding="utf-8") as f:
            f.write("{半截")
        log = FakeLog()
        self.assertEqual(B.load_settings(self.dir, log), B.DEFAULTS)
        self.assertTrue(os.path.exists(p + ".bad"))
        self.assertFalse(os.path.exists(p))
        self.assertEqual(log.lines[0][0], "warn")
        self.assertEqual(log.lines[0][1], "电池")
        with open(p, "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        self.assertEqual(B.load_settings(self.dir, FakeLog()), B.DEFAULTS)

    def test_bad_items_use_defaults(self):
        with open(B.settings_path(self.dir), "w", encoding="utf-8") as f:
            json.dump({"v": 1, "warn_pct": 99, "red_pct": 20, "future_key": 1, "cal_offset_v": 0.1}, f)
        log = FakeLog()
        s = B.load_settings(self.dir, log)
        self.assertEqual((s["warn_pct"], s["red_pct"], s["cal_offset_v"]), (30, 20, 0.1))
        self.assertEqual(len(log.lines), 1)
        self.assertIn("提醒线", log.lines[0][3]["raw"])
        with open(B.settings_path(self.dir), "w", encoding="utf-8") as f:
            json.dump({"warn_pct": 20, "red_pct": 18}, f)                   # 每项都合法、合起来不行
        s = B.load_settings(self.dir, FakeLog())
        self.assertEqual((s["warn_pct"], s["red_pct"]), (30, 15))

    def test_changes_text(self):
        a = dict(B.DEFAULTS)
        b = dict(a, red_pct=20, cal_offset_v=0.12)
        self.assertEqual(B.settings_changes(a, b), "红线 15% → 20%；读数校准 +0.00 V → +0.12 V")
        self.assertEqual(B.settings_changes(a, a), "")


class ReplayTest(unittest.TestCase):
    """一号鸭的真实上机录像（电压是 15 颗平均，每秒一个）。"""

    def test_20261012_1532_hold_then_stand(self):
        """审查 B-R1：原方案在这场会停在 44–46%，实际约 60%（卸力那 14 秒 7.76 V）。"""
        e = B.Estimator()
        shown, ev, modes = replay(e, load_fixture("battery-20261012-1532.csv"))
        self.assertIsNone(shown[20])                               # 头 30 秒估算中
        self.assertGreaterEqual(min(p for t, p in shown.items() if t >= 30), 35)
        end = shown[max(shown)]
        self.assertGreaterEqual(end, 55)
        self.assertLessEqual(end, 62)
        self.assertGreaterEqual(min(p for t, p in shown.items() if t >= 450), 55)   # 站起来以后一直在 55% 以上
        self.assertFalse([x for _, x in ev if x["level"] == "error"])   # 5.02 V、6.32 V 那两秒不出红条
        self.assertFalse(e.low.on)
        self.assertIsNone(e.level())

    def test_20261012_1458_glitch(self):
        """第 924 秒那个 4.21 V（站着），估算不动，日志记一条。"""
        e = B.Estimator()
        shown, ev, _ = replay(e, load_fixture("battery-20261012-1458.csv"))
        self.assertEqual(shown[915], shown[935])
        g = [t for t, x in ev if "掉了 1 V" in x["msg"]]
        self.assertTrue(any(920 <= t <= 930 for t in g))
        self.assertFalse([x for _, x in ev if x["level"] == "error"])
        self.assertTrue(38 <= shown[max(shown)] <= 50)

    def test_20261013_1540_full_pack(self):
        e = B.Estimator()
        shown, ev, _ = replay(e, load_fixture("battery-20261013-1540.csv"))
        vals = [p for t, p in shown.items() if t >= 30]
        self.assertTrue(all(82 <= p <= 86 for p in vals), (min(vals), max(vals)))   # 走路那几段也不往下掉
        self.assertIsNone(e.level())

    def test_switch_to_a_full_pack_follows(self):
        """接着换一段满电的数据（中间不断，比如主控插着 USB、换电池很快）：不靠跳升，靠轻松段跟上来。"""
        e = B.Estimator()
        low = load_fixture("battery-20261012-1458.csv")
        replay(e, low)
        before = e.shown
        t0 = float(low[-1][0] + 1)
        shown, _, _ = replay(e, load_fixture("battery-20261013-1540.csv"), t0=t0)
        self.assertLess(before, 50)
        self.assertGreaterEqual(shown[60], 80)
        self.assertGreaterEqual(min(p for t, p in shown.items() if t >= 60), 80)


if __name__ == "__main__":
    unittest.main()
