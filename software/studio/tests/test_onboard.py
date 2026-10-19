"""总览重排（overview-merge-plan.md §5、审查 overview-merge-review.md）的后端：上手清单（studio/onboard.py）、
主板温度格（state.cpu_view）、标定状态只认这次 hello 之后的（robotd.fresh_calib）、IMU 页的「核对过」记录。

清单的判法照审查末尾「清单每一步的最终判法」表（§5 O14 改成 5 行）；每一步测四种状态：✓ ok · ● todo · ○ no · ? unk。
跑法（studio 目录下）：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_onboard'])"
"""
import asyncio
import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from fake_robotd import FakeRobotd  # noqa: E402
from studio import onboard as O  # noqa: E402
from studio.imu import ImuBackend  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Robotd, Sample, fresh_calib  # noqa: E402
from studio.state import cpu_view, summarize, todo  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
XBOX = "78:86:2E:BB:13:28"


def recorded():
    f = FakeRobotd(FIXTURE)
    return copy.deepcopy(f.bus), copy.deepcopy(f.calib), copy.deepcopy(f.health)


BUS, CALIB, HEALTH = recorded()
BUILD = BUS["build"]


def calib_with(dirs=None, **joint_zero):
    c = copy.deepcopy(CALIB)
    for j in c["calibration"]["joints"]:
        if j["name"] in joint_zero:
            j["zero_raw"] = joint_zero[j["name"]]
        if dirs and j["name"] in dirs:
            j["direction"] = dirs[j["name"]]
    return c


def pad_view(known=True, pads=(), attached=False, device=None, estop="ok", checks=None):
    pads = [dict(p) for p in pads]
    active = next((p for p in pads if p.get("connected")), None)
    return {"known": known, "error": None if known else "读不到", "pads": pads, "active": active, "attached": attached,
            "device": device, "estop": {"state": estop, "checks": checks or []}}


XPAD = {"mac": XBOX, "name": "Xbox Wireless Controller", "paired": True, "trusted": True, "connected": True}


def inp(bus=None, calib="rec", pad=None, studio=None, present=True, servo_session=False):
    bus = copy.deepcopy(BUS) if bus is None else bus
    calib = copy.deepcopy(CALIB) if calib == "rec" else calib
    return {"bench": False, "present": present, "bus": bus, "calib": calib, "servo_session": servo_session,
            "pad": pad if pad is not None else pad_view(), "studio_servo": studio or {"ids": set(), "time": None},
            "fp": O.full_fp(bus, calib)}


def row(view, key):
    return next(r for r in view["rows"] if r["key"] == key)


class FakeRd:
    """robotd.Robotd 的样子（onboard / summarize 只读这些）。"""

    def __init__(self, bus=None, calib="rec", health="rec", present=True):
        self.addr = "tcp:x"
        self.present = present
        self.bus, self.calib, self.health = Sample(), Sample(), Sample()
        self.policies, self.state, self.pad, self.sysinfo, self.hello = Sample(), Sample(), Sample(), Sample(), Sample()
        self.calib_valid_after = None
        self.bus.set(copy.deepcopy(BUS) if bus is None else bus)
        if calib is not None:
            self.calib.set(copy.deepcopy(CALIB) if calib == "rec" else calib)
        if health is not None:
            self.health.set(copy.deepcopy(HEALTH) if health == "rec" else health)
        self.policies.set({"sitting": False, "homed": True})
        from studio.estop import EStop
        self.estop = EStop()


# ---------------- 清单每一步 ----------------

class RowTest(unittest.TestCase):
    def test_header(self):
        self.assertTrue(O.header_of(inp())["ok"])
        self.assertEqual(O.header_of(inp(present=False))["kind"], "absent")
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus", "error": "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"}
        h = O.header_of(inp(bus=stuck, calib=None))
        self.assertEqual(h["kind"], "stuck_calib")
        self.assertIn("标定或 IMU 方向没过", h["text"])
        self.assertIn("verified IMU mounting", h["raw"])
        h = O.header_of(inp(bus=dict(stuck, error="Feetech Sync Read timeout; missing IDs [21]"), calib=None))
        self.assertEqual(h["kind"], "starting")
        self.assertIn("舵机没上电", h["text"])
        self.assertEqual(O.header_of(inp(bus={"mode": "commissioning", "phase": "ready"}))["kind"], "commissioning")
        self.assertEqual(O.header_of(inp(servo_session=True))["kind"], "servo")

    def test_servo_four_states(self):
        rec = {}
        # ● 主程序文件里 15 颗都是 2048，但 Studio 这边没记录（可能是随包的种子值、手改的）：两个按钮
        r = row(O.evaluate(inp(), rec), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertEqual([a["do"] for a in r["actions"]], ["servos", "confirm_servo"])
        # ● zero_raw 不是 2048：两套零位会打架，列出是哪颗、差多少度
        r = row(O.evaluate(inp(calib=calib_with(left_knee=1990)), rec), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("两套零位会打架", r["text"])
        self.assertIn("左膝 1990（差 -5.1°）", r["text"])
        # ✓ Studio 舵机页标过 15 颗，而且记下的关节指纹没变（代码审查 C9-3：判法表「并且指纹没变」）
        stu = {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        ss = {"servo_studio": {"at": 1.7e9, "fp": O.joints_fp(CALIB), "src": stu["time"]}}
        r = row(O.evaluate(inp(studio=stu), ss), "servo")
        self.assertEqual((r["state"], r["when"]), ("ok", "2026-10-18 03:12:00"))
        r = row(O.evaluate(inp(studio=stu), {"servo_studio": dict(ss["servo_studio"], fp="old")}), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("舵机页标过以后", r["text"])
        # ✓ 点过「已经校过，核对一下」，指纹没变；指纹变了 → ●
        fp = O.joints_fp(CALIB)
        self.assertEqual(row(O.evaluate(inp(), {"confirm_servo": {"at": 1.7e9, "fp": fp}}), "servo")["state"], "ok")
        r = row(O.evaluate(inp(), {"confirm_servo": {"at": 1.7e9, "fp": "old"}}), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])
        # ○ 主程序说有没标的 / 卡在标定报错上
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        self.assertEqual(row(O.evaluate(inp(calib=c), rec), "servo")["state"], "no")
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus", "error": "motion requires all 15 calibrated joints"}
        r = row(O.evaluate(inp(bus=stuck, calib=None), rec), "servo")
        self.assertEqual(r["state"], "no")
        self.assertIn("同一句话", r["text"])
        self.assertEqual(row(O.evaluate(inp(bus={"mode": "commissioning", "phase": "ready", "calibrated": False}, calib=None), rec),
                             "servo")["state"], "no")
        # ? 这次连上以后没读到标定文件
        self.assertEqual(row(O.evaluate(inp(calib=None), rec), "servo")["state"], "unk")

    def test_imu_four_states(self):
        src, mount = "lsm6dsv16x", CALIB["imu_mount"]["quat"]
        mfp = O.mount_fp(src, mount)
        r = row(O.evaluate(inp(), {}), "imu")
        self.assertEqual(r["state"], "todo")                                  # 文件里写着已确认，Studio 没核过
        self.assertIn("8.5°", r["text"])
        ok = {"at": 1.7e9, "source": src, "mount_fp": mfp, "diff_deg": 0.8, "tilt_deg": 1.2, "ok": True}
        self.assertEqual(row(O.evaluate(inp(), {"imu_check": ok}), "imu")["state"], "ok")
        r = row(O.evaluate(inp(), {"imu_check": dict(ok, diff_deg=3.4, ok=False)}), "imu")
        self.assertEqual(r["state"], "todo")
        self.assertIn("差 3.4°", r["text"])
        r = row(O.evaluate(inp(), {"imu_check": dict(ok, mount_fp="other")}), "imu")      # 方向改过以后还没核
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])
        c = copy.deepcopy(CALIB)
        c["imu_mount"]["verified"] = False
        self.assertEqual(row(O.evaluate(inp(calib=c), {"imu_check": ok}), "imu")["state"], "no")
        self.assertEqual(row(O.evaluate(inp(bus={"mode": "commissioning", "phase": "ready", "imu_mount_verified": False},
                                            calib=None), {}), "imu")["state"], "no")
        self.assertEqual(row(O.evaluate(inp(calib=None), {"imu_check": ok}), "imu")["state"], "unk")

    def test_stuck_calib_distinguishes_servo_and_imu(self):
        """F5：主程序那句分不出是哪一项；只有 IMU 明说没确认才拦 IMU，只有关节没标才拦舵机。"""
        stuck = {"build": BUILD, "mode": "motion", "phase": "waiting_for_bus",
                 "error": "motion requires all 15 calibrated joints, measured limits and verified IMU mounting"}

        # 只有舵机没标，IMU 已确认：IMU 行不 hard（能跳过），舵机行照旧 hard
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        bus = copy.deepcopy(stuck)
        bus["native"] = {"imu_mount_verified": True}
        r_servo = row(O.evaluate(inp(bus=bus, calib=c), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=c), {}), "imu")
        self.assertEqual(r_servo["state"], "no")
        self.assertTrue(r_servo["hard"])
        self.assertIsNone(r_imu["hard"])

        # IMU 明说没确认、关节都标了（uncalibrated_joints 是空列表）：IMU 行 hard，舵机行不 hard
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = []
        c["imu_mount"]["verified"] = False
        bus = copy.deepcopy(stuck)
        bus["native"] = {"imu_mount_verified": False}
        r_servo = row(O.evaluate(inp(bus=bus, calib=c), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=c), {}), "imu")
        self.assertIsNone(r_servo["hard"])
        self.assertTrue(r_imu["hard"])
        self.assertEqual(r_imu["state"], "no")

        # 两者都不知道：IMU 行不 hard（unk，能跳过），舵机行照旧 hard
        bus = copy.deepcopy(stuck)
        r_servo = row(O.evaluate(inp(bus=bus, calib=None), {}), "servo")
        r_imu = row(O.evaluate(inp(bus=bus, calib=None), {}), "imu")
        self.assertTrue(r_servo["hard"])
        self.assertIsNone(r_imu["hard"])
        self.assertEqual(r_imu["state"], "unk")

    def test_pad_four_states(self):
        self.assertEqual(row(O.evaluate(inp(pad=pad_view(pads=[XPAD])), {}), "pad")["state"], "ok")
        r = row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, connected=False)])), {}), "pad")
        self.assertEqual(r["state"], "ok")
        self.assertIn("没连", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, trusted=False)])), {}), "pad")
        self.assertEqual(r["state"], "todo")
        self.assertIn("修复", r["text"])
        self.assertEqual(row(O.evaluate(inp(pad=pad_view()), {}), "pad")["state"], "no")
        r = row(O.evaluate(inp(pad=pad_view(known=False)), {"pads_seen": {XBOX: "Xbox Wireless Controller"}}), "pad")
        self.assertEqual(r["state"], "unk")                                    # 读不到 configd：不能写「还没配」
        self.assertIn("以前配过 Xbox", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(known=False, attached=True, device={"name": "Pro Controller"})), {}), "pad")
        self.assertEqual(r["state"], "ok")                                     # 旁路看到 attached 当证据
        self.assertEqual(row(O.evaluate(dict(inp(), pad=None), {}), "pad")["state"], "unk")   # 台架模式没有手柄后端

    def test_estop_four_states(self):
        rec = {"estop": {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": BUILD}}
        p = pad_view(pads=[XPAD])
        self.assertEqual(row(O.evaluate(inp(pad=p), {}), "estop")["state"], "no")
        r = row(O.evaluate(inp(pad=p), rec), "estop")
        self.assertEqual(r["state"], "ok")
        self.assertIn("180 ms", r["text"])
        other = dict(XPAD, mac="98:B6:E9:28:06:09", name="Pro Controller")
        r = row(O.evaluate(inp(pad=pad_view(pads=[other])), rec), "estop")
        self.assertEqual((r["state"], r["text"]), ("todo", "换了手柄：再测一次"))
        r = row(O.evaluate(inp(pad=p, bus=dict(copy.deepcopy(BUS), build="new-build")), rec), "estop")
        self.assertEqual((r["state"], r["text"]), ("todo", "主程序升级过：再测一次"))
        bad = pad_view(pads=[XPAD], estop="bad", checks=[{"key": "netpad", "label": "没开 UDP 手柄（netpad）", "ok": False, "why": "开着 [netpad]"}])
        r = row(O.evaluate(inp(pad=bad), rec), "estop")
        self.assertEqual(r["state"], "todo")
        self.assertIn("netpad", r["text"])
        r = row(O.evaluate(inp(pad=pad_view(known=False)), rec), "estop")      # 测过，现在核对不了
        self.assertEqual(r["state"], "unk")
        # 没连着时：唯一配过的那只也算「现在的手柄」
        self.assertEqual(row(O.evaluate(inp(pad=pad_view(pads=[dict(XPAD, connected=False)])), rec), "estop")["state"], "ok")

    def test_walk_four_states(self):
        fp = O.full_fp(BUS, CALIB)
        self.assertEqual(row(O.evaluate(inp(), {}), "walk")["state"], "no")
        r = row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": fp}}), "walk")
        self.assertEqual(r["state"], "todo")
        self.assertIn("还没走过", r["text"])
        self.assertEqual(row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}),
                             "walk")["state"], "ok")
        r = row(O.evaluate(inp(), {"stood": {"at": 1.7e9, "fp": "old"}, "walked": {"at": 1.7e9, "fp": "old"}}), "walk")
        self.assertEqual(r["state"], "todo")
        self.assertIn("标定改过以后还没站过、走过", r["text"])
        r = row(O.evaluate(inp(calib=None), {"stood": {"at": 1.7e9, "fp": fp}}), "walk")
        self.assertEqual(r["state"], "unk")
        self.assertIn("没法核对", r["text"])

    def test_next_points_at_first_not_done_and_not_unknown(self):
        v = O.evaluate(inp(calib=None, pad=pad_view(pads=[XPAD])), {})
        self.assertEqual([r["state"] for r in v["rows"]][:2], ["unk", "unk"])
        self.assertEqual(v["next"], "estop")                                   # ? 的跳过，指到第一个 ● / ○
        self.assertFalse(v["all_done"])
        fp, mfp = O.full_fp(BUS, CALIB), O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"])
        rec = {"confirm_servo": {"at": 1.7e9, "fp": O.joints_fp(CALIB)},
               "imu_check": {"at": 1.7e9, "source": "lsm6dsv16x", "mount_fp": mfp, "diff_deg": 0.5, "tilt_deg": 1, "ok": True},
               "estop": {"at": 1.7e9, "ms": 1, "mac": XBOX, "name": "x", "build": BUILD},
               "stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}
        v = O.evaluate(inp(pad=pad_view(pads=[XPAD])), rec)
        self.assertTrue(v["all_done"])
        self.assertIsNone(v["next"])
        json.dumps(v)                                                          # 能直接推给页面


# ---------------- 记录、文件 ----------------

class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.dir = Path(self.tmp.name) / "state"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_bad_file_is_moved_aside_and_does_not_crash(self):
        (self.dir / "onboarding.json").write_text("{坏了", encoding="utf-8")
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertEqual(ob.rec, {})
        self.assertTrue((self.dir / "onboarding.json.bad").exists())
        self.assertTrue(any("读不出来" in e["msg"] for e in self.log.recent(20)))
        ob.tick(FakeRd())                                                     # 照样能判
        self.assertEqual(len(ob.view()["rows"]), 5)
        (self.dir / "onboarding.json").write_text("[1, 2]", encoding="utf-8")  # 顶层不是对象也一样
        self.assertEqual(O.Onboarding(str(self.dir), self.log).rec, {})

    def test_save_is_atomic_and_reloads(self):
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertTrue(ob.note_estop({"ms": 120, "mac": XBOX.lower(), "name": "Xbox", "build": BUILD}))
        self.assertTrue(ob.save())
        self.assertFalse(ob.save())                                           # 没变就不写
        data = json.loads((self.dir / "onboarding.json").read_text(encoding="utf-8"))
        self.assertEqual(data["estop"]["mac"], XBOX)                          # MAC 统一大写
        self.assertEqual(data["v"], 1)
        self.assertFalse([f for f in os.listdir(self.dir) if f.startswith(".onboarding-")])   # 临时文件没留下
        self.assertEqual(O.Onboarding(str(self.dir), self.log).rec["estop"]["ms"], 120)

    def test_stood_and_walked_are_recorded_with_fingerprint(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        t = 1000.0
        for _ in range(8):                                                    # 站着保持 3.5 秒
            ob.tick(rd, now=t)
            t += 0.5
        self.assertEqual(ob.rec["stood"]["fp"], O.full_fp(BUS, CALIB))
        self.assertNotIn("walked", ob.rec)
        walking = copy.deepcopy(BUS)
        walking["policy_enabled"] = True
        rd.bus.set(walking)
        rd.state.set({"move": {"applied": [0.2, 0, 0]}})
        for _ in range(6):                                                    # 在走 2.5 秒
            rd.state.set({"move": {"applied": [0.2, 0, 0]}})
            ob.tick(rd, now=t)
            t += 0.5
        self.assertIn("walked", ob.rec)
        self.assertEqual(row(ob.view(), "walk")["state"], "ok")
        # 舵机零位改了（指纹变了）：要重做
        rd.calib.set(calib_with(left_knee=2000))
        ob.tick(rd, now=t)
        self.assertEqual(row(ob.view(), "walk")["state"], "todo")

    def test_servo_session_freezes_rows(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        ob.tick(rd)
        before = [r["state"] for r in ob.view()["rows"]]

        class Servo:
            state = "open"
        rd.calib.set(None)
        ob.tick(rd, servo=Servo())
        v = ob.view()
        self.assertTrue(v["frozen"])
        self.assertEqual(v["header"]["kind"], "servo")
        self.assertEqual([r["state"] for r in v["rows"]], before)

    def test_confirm_servo_checks_the_file(self):
        ob = O.Onboarding(str(self.dir), self.log)
        ok, why = ob.confirm_servo(FakeRd(calib=calib_with(left_knee=1990)), "电脑")
        self.assertFalse(ok)
        self.assertIn("2048", why)
        ok, why = ob.confirm_servo(FakeRd(calib=None), "电脑")
        self.assertFalse(ok)
        ok, why = ob.confirm_servo(FakeRd(), "电脑")
        self.assertTrue(ok, why)
        self.assertEqual(ob.rec["confirm_servo"]["fp"], O.joints_fp(CALIB))
        ob.tick(FakeRd())
        self.assertEqual(row(ob.view(), "servo")["state"], "ok")

    def test_studio_servo_record_reads_eeprom_backups(self):
        d = self.dir / "servo-calib"
        d.mkdir()
        (d / "eeprom-20261018-031200001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:12:00", "targets": {str(i): 2048 for i in O.SERVO_IDS}, "bad": {"23": "读不到"}, "sim": False}),
            encoding="utf-8")
        (d / "eeprom-20261018-031300001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:13:00", "targets": {"23": 2048}, "bad": {}, "sim": False}), encoding="utf-8")
        (d / "eeprom-20261018-031400001.json").write_text(json.dumps(
            {"time": "2026-10-18 03:14:00", "targets": {"99": 2048}, "sim": True}), encoding="utf-8")       # 模拟的不算
        (d / "undone-eeprom-20261018-031500001.json").write_text("{}", encoding="utf-8")                   # 撤销的不算
        (d / "eeprom-broken.json").write_text("{坏", encoding="utf-8")
        r = O.studio_servo_record(str(self.dir))
        self.assertEqual(r["ids"], set(O.SERVO_IDS))
        self.assertEqual(r["time"], "2026-10-18 03:13:00")
        self.assertEqual(O.studio_servo_record(str(self.dir / "nope")), {"ids": set(), "time": None})

    def test_cpu_hysteresis(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        for c, hot in ((79.0, False), (80.0, True), (78.0, True), (77.5, True), (76.9, False), (79.9, False)):
            rd.health.set(dict(HEALTH, cpu_temp_c=c))
            ob.tick(rd)
            self.assertEqual(ob.cpu_hot, hot, c)
            # 待办跟主板格用同一个带回差的 hot：78 °C 时也还在
            v = cpu_view(rd.health.value, 0.1, BUS, True, None, ob)
            items = todo(rd.health.value, BUS, {"stale": []}, "ok", v, {}, {"pct": 60}, "holding")
            self.assertEqual(any(i["key"] == "cpu" for i in items), hot, c)

    def test_read_board_like_robotd(self):
        th, cf = self.dir / "thermal", self.dir / "cpufreq"
        for name, temp in (("thermal_zone0", "76875"), ("thermal_zone1", "81250"), ("thermal_zone2", "-1000")):
            (th / name).mkdir(parents=True)
            (th / name / "temp").write_text(temp)
        for name, kind, cur, mx in (("cooling_device0", "cpufreq-cpu0", "3", "6"), ("cooling_device1", "devfreq-gpu", "6", "6")):
            (th / name).mkdir()
            for k, v in (("type", kind), ("cur_state", cur), ("max_state", mx)):
                (th / name / k).write_text(v)
        (cf / "policy0").mkdir(parents=True)
        (cf / "policy0" / "scaling_max_freq").write_text("1008000")
        (cf / "policy0" / "cpuinfo_max_freq").write_text("1800000")
        b = O.read_board(str(th), str(cf))
        self.assertEqual(b["c"], 81.25)                                        # 最热的那个；≤ 0 的跳过
        self.assertEqual(b["throttle"], {"khz": 1008000, "max_khz": 1800000, "level": 3, "max_level": 6})   # GPU 的不算
        self.assertIsNone(O.read_board(str(self.dir / "nope"), str(self.dir / "nope2")))


# ---------------- 主板温度格 ----------------

class CpuViewTest(unittest.TestCase):
    def test_health_stale_is_not_normal(self):
        """审查 O5：health 过期时不能写「正常」：c、throttled 都给 None，格子写「—」加原因。"""
        v = cpu_view(None, 12.4, BUS, True)
        self.assertIsNone(v["c"])
        self.assertIsNone(v["throttled"])
        self.assertIn("12 秒没更新", v["why"])
        self.assertIn("调试模式", cpu_view(None, None, {"mode": "commissioning"}, True)["why"])
        self.assertIn("等舵机总线", cpu_view(None, None, {"mode": "motion", "phase": "waiting_for_bus"}, True)["why"])
        self.assertIn("没在跑", cpu_view(None, None, None, False)["why"])

        class Servo:
            state = "open"
        self.assertIn("调舵机", cpu_view(None, None, BUS, True, Servo())["why"])
        self.assertIn("没报温度", cpu_view({"battery": {}}, 0.5, BUS, True)["why"])

    def test_throttled_limited_hot(self):
        h = dict(HEALTH, cpu_temp_c=92.4, cpu_throttle={"level": 4, "max_level": 6, "khz": 1008000, "max_khz": 1800000})
        v = cpu_view(h, 0.5, BUS, True)
        self.assertEqual((v["c"], v["throttled"], v["limited"], v["src"]), (92.4, True, False, "robotd"))
        self.assertTrue(v["hot"])
        items = todo(h, BUS, {"stale": []}, "ok", v, {}, {"pct": 60}, "holding")
        self.assertIn("降频了：1008 / 1800 MHz", next(i for i in items if i["key"] == "cpu")["msg"])
        h = dict(HEALTH, cpu_throttle={"level": 0, "max_level": 6, "khz": 1200000, "max_khz": 1800000})
        v = cpu_view(h, 0.5, BUS, True)
        self.assertEqual((v["throttled"], v["limited"]), (False, True))       # 被限频，不是热的
        v = cpu_view(HEALTH, 0.5, BUS, True)
        self.assertEqual((v["c"], v["throttled"], v["limited"], v["hot"]), (76.9, False, False, False))

    def test_studio_reads_board_when_robotd_does_not(self):
        class Ob:
            cpu_hot = True
            board = {"c": 83.0, "throttle": {"level": 0, "max_level": 6, "khz": 1800000, "max_khz": 1800000}}
        v = cpu_view(None, None, {"mode": "commissioning"}, True, None, Ob())
        self.assertEqual((v["c"], v["src"], v["hot"], v["throttled"]), (83.0, "studio", True, False))

    def test_summarize_carries_onboarding_and_todo_keys(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            log = Log(Path(tmp.name) / "logs", echo=False, background=False)
            ob = O.Onboarding(tmp.name, log)
            rd = FakeRd()
            ob.tick(rd)
            s = summarize(rd, {}, ob=ob)
            self.assertEqual(len(s["onboarding"]["rows"]), 5)
            self.assertEqual(s["cpu"]["c"], 76.9)
            self.assertTrue(all("key" in t for t in s["todo"]))
            rd.health = Sample()                                               # health 读不到
            s = summarize(rd, {}, ob=ob)
            self.assertIsNone(s["cpu"]["c"])
            self.assertIsNone(s["cpu"]["throttled"])
            self.assertTrue(s["cpu"]["why"])
        finally:
            tmp.cleanup()


# ---------------- 标定状态只认这次 hello 之后的（审查 O5） ----------------

class CalibFreshTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", Log(Path(self.tmp.name), echo=False, background=False))
        self.rd.start()

    async def asyncTearDown(self):
        await self.rd.stop()
        self.s1.close()
        self.s2.close()
        self.tmp.cleanup()

    async def wait_for(self, cond, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    def calib_asks(self):
        return sum(1 for _, m in self.fake.calls if m == "robot.busCommand")

    async def test_old_calib_does_not_count_after_restart(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))
        # robotd 重启以后卡在等总线（标定 / IMU 没过）：旧的「15 颗都标了」不算数
        self.fake.set_posture("stuck_calib")
        self.fake.restart(0.2)
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_valid_after is not None and self.rd.calib.at < self.rd.calib_valid_after
                                            and (self.rd.bus.value or {}).get("phase") == "waiting_for_bus"))
        self.assertIsNone(self.rd.calib_fresh())
        self.assertIsNotNone(self.rd.calib.value)                              # 旧值还在，只是不认
        # 开了总线（phase 变成 control）：再问一次
        n = self.calib_asks()
        self.fake.set_posture("holding")
        self.assertTrue(await self.wait_for(lambda: self.calib_asks() > n and self.rd.calib_fresh() is not None, 6.0))


class FreshCalibTest(unittest.TestCase):
    def test_fresh_calib_without_hello_info(self):
        class R:
            calib = Sample()
        r = R()
        self.assertIsNone(fresh_calib(r))
        r.calib.set({"x": 1})
        self.assertEqual(fresh_calib(r), {"x": 1})                             # 假对象没有 calib_valid_after：不挡
        r.calib_valid_after = time.monotonic() + 1
        self.assertIsNone(fresh_calib(r))


# ---------------- IMU 页的「核对过」（审查 O4：只是记一笔，不往鸭子写） ----------------

class ImuCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.ob = O.Onboarding(self.tmp.name, self.log)
        self.imu = ImuBackend(FakeRd(), self.log, self.tmp.name)
        self.imu.on_check = self.ob.note_imu_check
        self.view = self.imu.view()
        self.old = self.view["mount"]["quat"]

    def tearDown(self):
        self.tmp.cleanup()

    def res(self, diff, tilt):
        return {"ok": True, "parts": {"total_deg": diff, "stand_tilt_deg": tilt}}

    def test_close_enough_is_recorded(self):
        c = self.imu._check(self.res(0.9, 1.5), self.view, self.old, True, "电脑")
        self.assertTrue(c["ok"] and c["recorded"])
        rec = self.ob.rec["imu_check"]
        self.assertEqual(rec["mount_fp"], O.mount_fp("lsm6dsv16x", self.old))
        self.ob.tick(FakeRd())
        self.assertEqual(row(self.ob.view(), "imu")["state"], "ok")

    def test_far_or_tilted_is_recorded_but_not_ok(self):
        c = self.imu._check(self.res(3.2, 1.0), self.view, self.old, True, "电脑")
        self.assertFalse(c["ok"])
        self.assertIn("差 3.2°", c["why"])
        self.assertFalse(self.ob.rec["imu_check"]["ok"])
        c = self.imu._check(self.res(0.5, 7.0), self.view, self.old, True, "电脑")
        self.assertIn("站姿倾斜", c["why"])

    def test_unverified_mount_is_not_recorded(self):
        c = self.imu._check(self.res(0.5, 1.0), self.view, self.old, False, "电脑")
        self.assertFalse(c["ok"] or c["recorded"])
        self.assertNotIn("imu_check", self.ob.rec)


# ---------------- 代码审查 C1–C9（scratchpad console/overviewreview/repro_onboard.py 的几种情况） ----------------

class ReviewFixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.dir = Path(self.tmp.name) / "state"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        (self.dir / "onboarding.json").write_text(json.dumps(data), encoding="utf-8")

    def test_c1_bad_single_records_are_dropped_and_hot_still_works(self):
        """C1：合法 JSON、但单条类型不对（diff_deg 是 null、walked 是空对象）：那一条丢掉、记一行 warn，清单照判；
        85 °C 时主板「有点热」照样亮。"""
        src, m = "lsm6dsv16x", CALIB["imu_mount"]["quat"]
        self.write({"v": 1, "imu_check": {"source": src, "mount_fp": O.mount_fp(src, m), "ok": True, "diff_deg": None},
                    "walked": {}, "stood": {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}, "future_key": {"x": 1}})
        ob = O.Onboarding(str(self.dir), self.log)
        self.assertNotIn("imu_check", ob.rec)
        self.assertNotIn("walked", ob.rec)
        self.assertIn("stood", ob.rec)                                     # 好的那几条照用
        self.assertIn("future_key", ob.rec)                                # 不认识的键原样留着
        warns = [e["msg"] for e in self.log.recent(30) if "格式不对" in e["msg"]]
        self.assertEqual(len(warns), 2)
        rd = FakeRd()
        rd.health.set(dict(HEALTH, cpu_temp_c=85.0))
        ob.tick(rd)
        self.assertTrue(ob.cpu_hot)
        self.assertEqual(row(ob.view(), "imu")["state"], "todo")
        self.assertEqual(row(ob.view(), "walk")["state"], "todo")
        # 记录里的数字是 null 也不抛（直接给 evaluate，不经过校验）
        v = O.evaluate(inp(), {"imu_check": {"source": src, "mount_fp": O.mount_fp(src, m), "ok": False, "diff_deg": None},
                               "estop": {"at": 1.7e9, "ms": None, "mac": XBOX, "build": BUILD}})
        self.assertIn("差 ?°", row(v, "imu")["text"])

    def test_c1_evaluate_error_shows_question_marks_and_hysteresis_keeps_going(self):
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd()
        rd.health.set(dict(HEALTH, cpu_temp_c=85.0))
        real = O.evaluate
        O.evaluate = lambda inp, rec: 1 / 0
        try:
            ob.tick(rd)
            ob.tick(rd)
        finally:
            O.evaluate = real
        v = ob.view()
        self.assertEqual(v["header"]["kind"], "error")
        self.assertEqual([r["state"] for r in v["rows"]], ["unk"] * 5)
        self.assertIn("ZeroDivisionError", v["rows"][0]["text"])
        self.assertTrue(ob.cpu_hot)                                        # 回差不受清单出错影响
        self.assertEqual(sum(1 for e in self.log.recent(30) if "上手清单判的时候出错" in e["msg"]), 1)   # 同一种错只记一次
        ob.tick(rd)
        self.assertEqual(ob.view()["header"]["kind"], "ok")                # 好了就恢复

    def test_c2_no_fingerprint_does_not_overwrite_records(self):
        """C2：robotd 刚重启、标定还没读回来（指纹 None）时站满 3 秒：不写、不覆盖带指纹的旧记录。"""
        ob = O.Onboarding(str(self.dir), self.log)
        fp = O.full_fp(BUS, CALIB)
        ob.rec = {"stood": {"at": 1.7e9, "fp": fp}, "walked": {"at": 1.7e9, "fp": fp}}
        rd = FakeRd()
        rd.calib_valid_after = rd.calib.at + 1.0                           # 这次 hello 之后还没读到标定
        walking = copy.deepcopy(BUS)
        walking["policy_enabled"] = True
        rd.bus.set(walking)
        t = 1000.0
        for _ in range(10):
            rd.state.set({"move": {"applied": [0.2, 0, 0]}})
            ob.tick(rd, now=t)
            t += 0.5
        self.assertEqual(ob.rec["stood"]["fp"], fp)
        self.assertEqual(ob.rec["walked"]["fp"], fp)
        rd.calib.set(copy.deepcopy(CALIB))                                 # 读回来了，内容没变
        rd.calib_valid_after = rd.calib.at - 0.001
        ob.tick(rd, now=t)
        self.assertEqual(row(ob.view(), "walk")["state"], "ok")

    def test_c4_native_says_unverified_is_not_unknown(self):
        """C4：busStatus 明说 IMU 方向没确认，标定状态读不到：第 2 步是 ○，不是 ?。"""
        bus = copy.deepcopy(BUS)
        bus["native"]["imu_mount_verified"] = False
        r = row(O.evaluate(inp(bus=bus, calib=None), {}), "imu")
        self.assertEqual(r["state"], "no")
        self.assertIn("还没确认", r["text"])
        ob = O.Onboarding(str(self.dir), self.log)
        rd = FakeRd(bus=bus, calib=None)
        ob.tick(rd)
        s = summarize(rd, {}, ob=ob)
        self.assertIn("imu_unverified", [t["key"] for t in s["todo"]])    # 待办照样有（前端按清单这一行是 ○ 才去重）
        self.assertEqual(row(s["onboarding"], "imu")["state"], "no")

    def test_c9_tick_does_not_touch_files(self):
        """C9-1：读 servo-calib 目录、/sys/class/thermal 在 io()（线程里）做；tick 只用缓存。"""
        ob = O.Onboarding(str(self.dir), self.log)
        calls = []
        real_scan, real_board = O.studio_servo_record, O.read_board
        O.studio_servo_record = lambda d: calls.append("scan") or {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        O.read_board = lambda *a: calls.append("board") or {"c": 83.0, "throttle": None}
        try:
            rd = FakeRd(health=None)                                       # robotd 不报温度
            ob._board_ok = True
            for _ in range(3):
                ob.tick(rd)
            self.assertEqual(calls, [])
            self.assertTrue(ob.need_board(rd))
            ob.io(board=True, now=0.0)
            self.assertEqual(calls, ["scan", "board"])
            ob.io(board=False, now=1.0)                                    # 目录没变、没到 10 秒：不重读
            self.assertEqual(calls, ["scan", "board"])
            ob.io(board=False, now=20.0)
            self.assertEqual(calls.count("scan"), 2)
            ob.tick(rd)
            self.assertEqual(row(ob.view(), "servo")["state"], "ok")       # 缓存里的 Studio 记录照样用上
            self.assertIn("servo_studio", ob.rec)                          # 第一次对上：记下指纹（C9-3）
            self.assertFalse(rd.health.value)
            self.assertFalse(ob.need_board(FakeRd()))                      # robotd 报温度：不用自己读
        finally:
            O.studio_servo_record, O.read_board = real_scan, real_board

    def test_c9_studio_record_fingerprint_change_needs_recheck(self):
        ob = O.Onboarding(str(self.dir), self.log)
        ob._studio = {"ids": set(O.SERVO_IDS), "time": "2026-10-18 03:12:00"}
        rd = FakeRd()
        ob.tick(rd)
        self.assertEqual(row(ob.view(), "servo")["state"], "ok")
        rd.calib.set(calib_with(left_knee=2048, mouth=2048))
        js = rd.calib.value["calibration"]["joints"]
        js[0]["direction"] = 1                                             # 方向改了：关节指纹变了，零位还是 2048
        ob.tick(rd)
        r = row(ob.view(), "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("改过了", r["text"])

    def test_c9_concurrent_saves_keep_the_newest(self):
        """C9-2：两处同时存（0.5 秒的小任务、「核对一下」按钮），旧的不能后落盘把新的盖掉。"""
        import threading
        ob = O.Onboarding(str(self.dir), self.log)
        real = O.os.replace
        first = {"slow": True}

        def slow_replace(a, b):
            if first["slow"]:
                first["slow"] = False
                time.sleep(0.3)
            return real(a, b)
        O.os.replace = slow_replace
        try:
            ob._put("stood", {"at": 1.0, "fp": "old"})
            ta = threading.Thread(target=ob.save)
            ta.start()
            time.sleep(0.05)
            ob._put("stood", {"at": 2.0, "fp": "new"})
            tb = threading.Thread(target=ob.save)
            tb.start()
            ta.join()
            tb.join()
        finally:
            O.os.replace = real
        data = json.loads((self.dir / "onboarding.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stood"]["fp"], "new")


class PollReconnectTest(unittest.IsolatedAsyncioTestCase):
    """C8：轮询连接超时重连过、或者 robotd 离开了 control：已经读到的标定不作数，重新 hello、重读。"""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = FakeRobotd(FIXTURE)
        self.s1, p1 = await self.fake.serve_tcp()
        self.s2, p2 = await self.fake.serve_tcp()
        self.rd = Robotd(f"tcp:127.0.0.1:{p1}", f"tcp:127.0.0.1:{p2}", Log(Path(self.tmp.name), echo=False, background=False))
        self.rd.start()

    async def asyncTearDown(self):
        await self.rd.stop()
        await asyncio.sleep(0.05)
        self.s1.close()
        self.s2.close()
        self.tmp.cleanup()

    async def wait_for(self, cond, timeout=6.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            await asyncio.sleep(0.02)
        return cond()

    def hellos(self):
        return sum(1 for _, m in self.fake.calls if m == "hello")

    async def test_timeout_reconnect_is_a_new_hello(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))
        n, after0 = self.hellos(), self.rd.calib_valid_after
        self.fake.delays["robot.busStatus"] = 2.6                          # robotd 卡住 > 2 秒：轮询超时、关连接
        self.assertTrue(await self.wait_for(lambda: self.rd.poll.reconnects > 0, 8.0))
        self.fake.delays.pop("robot.busStatus", None)
        self.assertTrue(await self.wait_for(lambda: self.hellos() > n, 8.0))
        # 假 robotd 记下 hello 的时候，Studio 还没收到回包：等它收到、把以前读到的作废
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_valid_after > after0, 4.0))
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None and self.rd.calib.at > self.rd.calib_valid_after))

    async def test_leaving_control_invalidates_calib(self):
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None
                                            and (self.rd.bus.value or {}).get("phase") == "control"))
        self.fake.set_posture("starting")                                  # 没重启、卡回了等总线
        self.assertTrue(await self.wait_for(lambda: (self.rd.bus.value or {}).get("phase") == "waiting_for_bus"))
        self.assertIsNone(self.rd.calib_fresh())
        self.fake.set_posture("holding")
        self.assertTrue(await self.wait_for(lambda: self.rd.calib_fresh() is not None))


# ---------------- 跳过 / 重新做（用户 10-18 在二号鸭上：「应该允许跳过、允许重新做」） ----------------

class FakePad:
    def __init__(self, view):
        self.view = view

    def onboard_view(self):
        return copy.deepcopy(self.view)


class SkipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)
        self.ob = O.Onboarding(self.tmp.name, self.log)
        self.rd = FakeRd()
        self.pad = FakePad(pad_view(pads=[XPAD]))

    def tearDown(self):
        self.tmp.cleanup()

    def tick(self):
        self.ob.tick(self.rd, self.pad)
        return self.ob.view()

    def test_each_step_skip_and_unskip(self):
        rec_fp = {"servo": O.joints_fp(CALIB), "imu": O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"]),
                  "estop": O._hash([XBOX, BUILD]), "walk": O.full_fp(BUS, CALIB)}
        self.pad.view = pad_view(pads=[XPAD])
        v = self.tick()
        for key in ("servo", "imu", "estop", "walk"):
            with self.subTest(step=key):
                r = row(v, key)
                if r["state"] in ("todo", "no"):
                    self.assertTrue(r["skip"]["ok"], r)
                    self.assertEqual(r["skip"]["confirm"], key == "estop")    # 测急停的跳过要点两次（前端做）
                    ok, why = self.ob.skip(key, self.rd, self.pad, by="电脑 1.2.3.4")
                    self.assertTrue(ok, why)
                    self.assertEqual(self.ob.rec["skipped"][key]["fp"], rec_fp[key])
                    self.assertEqual(self.ob.rec["skipped"][key]["by"], "电脑 1.2.3.4")
                    r = row(self.tick(), key)
                    self.assertEqual(r["state"], "skip")
                    self.assertIn("跳过了", r["text"])
                    self.assertEqual(r["go"], O.GO[key])                       # 「去做」/「重新做」去哪
                    ok, _ = self.ob.unskip(key, by="电脑 1.2.3.4")
                    self.assertTrue(ok)
                    self.assertNotIn(key, self.ob.rec["skipped"])
                    self.assertIn(row(self.tick(), key)["state"], ("todo", "no"))
        # 配手柄：没配时能跳，不绑指纹
        self.pad.view = pad_view()
        self.assertEqual(row(self.tick(), "pad")["state"], "no")
        self.assertTrue(self.ob.skip("pad", self.rd, self.pad, by="手机")[0])
        self.assertIsNone(self.ob.rec["skipped"]["pad"]["fp"])
        self.assertEqual(row(self.tick(), "pad")["state"], "skip")
        msgs = [e["msg"] for e in self.log.recent(50)]
        self.assertIn("上手清单：IMU 方向 跳过（电脑 1.2.3.4）", msgs)
        self.assertIn("上手清单：IMU 方向 取消跳过（电脑 1.2.3.4）", msgs)
        self.assertTrue(any(e["cat"] == "校准" for e in self.log.recent(50) if "跳过" in e["msg"]))
        self.assertTrue(self.ob.save())                                       # 原子写，读回来一样
        self.assertEqual(O.Onboarding(self.tmp.name, self.log).rec["skipped"], self.ob.rec["skipped"])

    def test_ok_or_unknown_rows_cannot_be_skipped(self):
        self.ob.rec["walked"] = {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}
        ok, why = self.ob.skip("walk", self.rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("已经完成", why)
        rd = FakeRd(calib=None)                                                # IMU 读不到（?）
        self.assertEqual(row(O.evaluate(inp(calib=None), {}), "imu")["state"], "unk")
        ok, why = self.ob.skip("imu", rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("读不到", why)
        self.assertFalse(self.ob.skip("nope", self.rd)[0])

    def test_imu_native_unverified_refused_by_backend(self):
        """IMU 例外：busStatus 的 native.imu_mount_verified 明确 false：按钮灰着、后端也拒。"""
        bus = copy.deepcopy(BUS)
        bus["native"]["imu_mount_verified"] = False
        self.rd.bus.set(bus)
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "no")
        self.assertFalse(r["skip"]["ok"])
        self.assertIn("跳过了鸭子也站不起来", r["skip"]["why"])
        ok, why = self.ob.skip("imu", self.rd, self.pad, by="电脑")
        self.assertFalse(ok)
        self.assertIn("先去 IMU 页", why)
        self.assertNotIn("imu", self.ob.rec.get("skipped") or {})
        # 以前跳过的，主程序明说没确认时也不算数
        self.ob.rec["skipped"] = {"imu": {"at": 1.7e9, "by": "x", "fp": O.mount_fp("lsm6dsv16x", CALIB["imu_mount"]["quat"])}}
        r = row(self.tick(), "imu")
        self.assertEqual(r["state"], "no")
        self.assertIn("跳过不管用", r["note"])
        bus["native"]["imu_mount_verified"] = True                             # true 时正常能跳
        self.rd.bus.set(bus)
        self.assertEqual(row(self.tick(), "imu")["state"], "skip")

    def test_fingerprint_change_voids_skip_but_none_does_not(self):
        self.assertTrue(self.ob.skip("servo", self.rd, self.pad)[0])
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad)[0])
        # 读不到（指纹 None）：不作废
        self.rd.calib_valid_after = self.rd.calib.at + 1
        self.pad.view = pad_view(known=False)
        v = self.tick()
        self.assertEqual(row(v, "servo")["state"], "skip")
        self.assertEqual(row(v, "estop")["state"], "skip")
        # 读回来、标定改过了（方向改了，零位还是 2048）/ 换了手柄：作废、回 ●，写清是什么改过了
        self.rd.calib.set(calib_with(dirs={"left_knee": 1}))
        self.rd.calib_valid_after = self.rd.calib.at - 0.001
        other = dict(XPAD, mac="98:B6:E9:28:06:09", name="Pro Controller")
        self.pad.view = pad_view(pads=[other])
        v = self.tick()
        r = row(v, "servo")
        self.assertEqual(r["state"], "todo")
        self.assertIn("跳过以后舵机零位改过了", r["text"])
        r = row(v, "estop")
        self.assertEqual(r["state"], "todo")
        self.assertIn("跳过以后手柄（或主程序版本）改过了", r["text"])
        self.assertTrue(r["skip"]["ok"])                                       # 能再跳一次（绑新的）

    def test_fingerprint_unknown_means_no_new_skip(self):
        """指纹读不到时不记新的跳过（照 C2）：测急停配过两只手柄、一只都没连，读不出是哪只。"""
        two = [dict(XPAD, connected=False), dict(XPAD, mac="98:B6:E9:28:06:09", connected=False)]
        self.pad.view = pad_view(pads=two)
        r = row(self.tick(), "estop")
        self.assertFalse(r["skip"]["ok"])
        ok, why = self.ob.skip("estop", self.rd, self.pad)
        self.assertFalse(ok)
        self.assertIn("先连上一只手柄", why)                                # 审查 D11：写清楚要做什么
        self.assertIn("先连上一只手柄再测", r["text"])

    def test_web_only_estop_can_be_skipped(self):
        """只用网页（确定没有实体手柄）：测急停那行写「空格就是急停……可以跳过这步」，能跳；之后配上手柄，跳过作废。"""
        self.pad.view = pad_view()
        r = row(self.tick(), "estop")
        self.assertIn("空格就是急停", r["text"])
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad)[0])
        self.assertEqual(row(self.tick(), "estop")["state"], "skip")
        self.pad.view = pad_view(pads=[XPAD])
        self.assertEqual(row(self.tick(), "estop")["state"], "todo")

    def test_skip_counts_as_done_and_next_moves(self):
        self.ob.rec["confirm_servo"] = {"at": 1.7e9, "fp": O.joints_fp(CALIB)}
        v = self.tick()
        self.assertEqual(v["next"], "imu")
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad)[0])
        v = self.tick()
        self.assertEqual(v["next"], "estop")                                   # 配手柄这一行是 ✓（XPAD 连着）：往下走到测急停
        self.assertEqual(v["skipped_n"], 1)
        self.assertTrue(self.ob.skip("estop", self.rd, self.pad)[0])
        self.ob.rec["walked"] = {"at": 1.7e9, "fp": O.full_fp(BUS, CALIB)}
        v = self.tick()
        self.assertTrue(v["all_done"])
        self.assertIsNone(v["next"])
        self.assertEqual(v["skipped_n"], 2)
        json.dumps(v)

    def test_bad_skipped_records_are_dropped(self):
        Path(self.tmp.name, "onboarding.json").write_text(json.dumps({"v": 1, "skipped": {
            "imu": {"at": 1.7e9, "by": "x", "fp": "abc"}, "servo": {"at": "昨天"}, "nope": {"at": 1}, "pad": [1]}}), encoding="utf-8")
        ob = O.Onboarding(self.tmp.name, self.log)
        self.assertEqual(list(ob.rec["skipped"]), ["imu"])
        self.assertEqual(sum(1 for e in self.log.recent(30) if "skipped." in e["msg"]), 3)
        Path(self.tmp.name, "onboarding.json").write_text(json.dumps({"v": 1, "skipped": "全跳"}), encoding="utf-8")
        self.assertNotIn("skipped", O.Onboarding(self.tmp.name, self.log).rec)
        ob.tick(self.rd, self.pad)                                             # 照样能判
        self.assertEqual(len(ob.view()["rows"]), 5)

    def test_hard_block_servo_not_skippable(self):
        c = copy.deepcopy(CALIB)
        c["uncalibrated_joints"] = ["left_knee"]
        self.rd.calib.set(c)
        r = row(self.tick(), "servo")
        self.assertFalse(r["skip"]["ok"])
        self.assertFalse(self.ob.skip("servo", self.rd, self.pad)[0])



class Batch3SkipTest(unittest.TestCase):
    """第三批代码审查 D5、D10、D11（复现脚本 repro_onboard.py 的 R1–R7）。"""
    setUp, tearDown, tick = SkipTest.setUp, SkipTest.tearDown, SkipTest.tick

    def test_found_problems_cannot_be_skipped_and_old_skips_are_voided(self):
        """D5：IMU 核过差 8.5°、急停测过但现在不管用、两套零位打架——不让跳（只给重新做）；已有的跳过作废、从记录里删掉。"""
        src, mount = "lsm6dsv16x", CALIB["imu_mount"]
        mfp = O.mount_fp(src, mount["quat"])
        efp = O._hash([XBOX, BUILD])
        self.ob.rec.update({
            "imu_check": {"at": 1.7e9, "source": src, "mount_fp": mfp, "diff_deg": 8.5, "tilt_deg": 1.0, "ok": False},
            "estop": {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": BUILD},
            "skipped": {"imu": {"at": 1.7e9, "by": "x", "fp": mfp}, "estop": {"at": 1.7e9, "by": "x", "fp": efp},
                        "servo": {"at": 1.7e9, "by": "x", "fp": O.joints_fp(calib_with(left_knee=1990))}}})
        self.rd.calib.set(calib_with(left_knee=1990))
        self.rd.calib_valid_after = self.rd.calib.at - 0.001
        self.pad.view = pad_view(pads=[XPAD], estop="bad", checks=[{"label": "padd 在跑", "ok": False, "why": "padd 没在跑"}])
        v = self.tick()
        for key, word in (("imu", "差 8.5°"), ("estop", "急停不管用"), ("servo", "两套零位")):
            with self.subTest(step=key):
                r = row(v, key)
                self.assertEqual(r["state"], "todo", r)                         # 以测出的问题为准，不再是「跳过了」
                self.assertFalse(r["skip"]["ok"])
                self.assertIn(word, r["skip"]["why"])
                self.assertIn("跳过不算了", r["note"])
                self.assertTrue(r["found"])
                ok, why = self.ob.skip(key, self.rd, self.pad)
                self.assertFalse(ok)
                self.assertIn(word, why)
        self.assertEqual(self.ob.rec["skipped"], {})                           # 作废的从记录里删了
        self.assertTrue(any("跳过作废" in e["msg"] for e in self.log.recent(50)))

    def test_skip_records_need_number_at_and_string_fp(self):
        """D10：at 不是数字、绑指纹的步 fp 不是字符串 → 丢掉并记 warn；配手柄不绑指纹，fp 可以是 null。"""
        good, bad = O.clean_records({"skipped": {
            "imu": {}, "servo": {"x": 1}, "walk": {"at": None, "fp": "abc"}, "estop": {"at": 1.7e9, "fp": None},
            "pad": {"at": 1.7e9, "by": "x", "fp": None}, "servo2": {"at": 1.7e9, "fp": "a"}}})
        self.assertEqual(good["skipped"], {"pad": {"at": 1.7e9, "by": "x", "fp": None}})
        self.assertEqual(sorted(k for k, _ in bad), ["skipped.estop", "skipped.imu", "skipped.servo", "skipped.servo2", "skipped.walk"])
        p = Path(self.tmp.name) / O.ONBOARD_FILE
        p.write_text(json.dumps({"skipped": {"servo": {"at": 1.7e9, "by": "x", "fp": None}}}), encoding="utf-8")
        ob = O.Onboarding(self.tmp.name, self.log)
        self.assertEqual(ob.rec["skipped"], {})
        self.assertTrue(any("skipped.servo" in e["msg"] for e in self.log.recent(20)))

    def test_frozen_during_servo_session_refuses_skip_and_unskip(self):
        """D11：调舵机时清单冻结，跳过、取消跳过后端都拒（原因写清楚）。"""
        self.assertTrue(self.ob.skip("imu", self.rd, self.pad)[0])

        class Sess:
            state = "open"
        ok, why = self.ob.skip("walk", self.rd, self.pad, Sess())
        self.assertFalse(ok)
        self.assertIn("在调舵机", why)
        ok, why = self.ob.unskip("imu", servo=Sess())
        self.assertFalse(ok)
        self.assertIn("交还主程序以后", why)
        self.assertIn("imu", self.ob.rec["skipped"])
        self.assertFalse(self.ob.unskip("imu")[0])        # 没传会话：看最近见到的那个（还开着）——照样拒（审查 R6）
        Sess.state = "closed"                             # 交还了
        self.assertTrue(self.ob.unskip("imu")[0])

    def test_estop_skip_ask_text_by_situation(self):
        """D11：测急停跳过的确认那句按情况写：没测过 / 换了手柄 / 主程序升级过 / 急停现在不管用 / 只用网页。"""
        self.pad.view = pad_view(pads=[XPAD])
        self.assertIn("没测过", row(self.tick(), "estop")["skip"]["ask"])
        self.pad.view = pad_view(pads=[XPAD], estop="bad", checks=[{"label": "padd 在跑", "ok": False, "why": "padd 没在跑"}])
        r = row(self.tick(), "estop")
        self.assertIn("急停现在不管用（padd 在跑：padd 没在跑）", r["skip"]["ask"])
        self.assertTrue(r["skip"]["ok"])                                        # 没测过的：能跳（不是测出来的问题）
        self.pad.view = pad_view()
        self.assertIn("只用网页", row(self.tick(), "estop")["skip"]["ask"])
        self.ob.rec["estop"] = {"at": 1.7e9, "ms": 180, "mac": "98:B6:E9:28:06:09", "name": "Pro", "build": BUILD}
        self.pad.view = pad_view(pads=[XPAD])
        r = row(self.tick(), "estop")
        self.assertIn("换了手柄", r["skip"]["ask"])
        self.ob.rec["estop"] = {"at": 1.7e9, "ms": 180, "mac": XBOX, "name": "Xbox", "build": "old-build"}
        self.assertIn("主程序升级过", row(self.tick(), "estop")["skip"]["ask"])


class BatteryWordingTest(unittest.TestCase):
    """电量低的待办：没电了会不会自己坐下关机，照 robotd 配置的 [safety] battery_empty_shutdown 说（二号鸭真机是 false）。"""

    def test_read_setting_and_wording(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            d = Path(tmp.name)
            fork, official = d / "fork.toml", d / "official.toml"
            self.assertIsNone(O.read_battery_shutdown([str(fork), str(official)]))          # 都没有：读不到
            official.write_text("[safety]\nbattery_empty_shutdown = true\n", encoding="utf-8")
            self.assertIs(O.read_battery_shutdown([str(fork), str(official)]), True)
            fork.write_text("[safety]\nlimp_fall = false\nbattery_empty_shutdown = false\n", encoding="utf-8")
            self.assertIs(O.read_battery_shutdown([str(fork), str(official)]), False)        # fork 的在前
            fork.write_text("[safety]\nlimp_fall = false\n", encoding="utf-8")
            self.assertIsNone(O.read_battery_shutdown([str(fork)]))                         # 没写这一项：按读不到
            fork.write_text("坏[", encoding="utf-8")
            self.assertIsNone(O.read_battery_shutdown([str(fork)]))
        finally:
            tmp.cleanup()
        low = {"pct": 9}

        def hint(v):
            return next(i for i in todo(HEALTH, BUS, {"stale": []}, "ok", {}, {}, low, "holding", battery_shutdown=v)
                        if i["key"] == "battery")["hint"]
        self.assertEqual(hint(True), "该充电了；到 6.6 V 它会自己坐下关机")
        self.assertEqual(hint(False), "该充电了；没电时它不会自己坐下，先停下、坐下再充")
        self.assertEqual(hint(None), "该充电了；没电时它不会自己坐下，先停下、坐下再充")


if __name__ == "__main__":
    unittest.main()
