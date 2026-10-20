"""root 小助手 deploy/microduck-helper 的七个动词：总线三个（bus-take / bus-give-back / bus-abort）、手柄两个（pad-pair / pad-forget）、
热点两个（wifi-hotspot-down / wifi-hotspot-up）。

在电脑上跑，不碰真系统：假 systemctl（robotd 的状态机：stop 卡住、KILL、Restart=always、Condition 旗、
start-limit 计数、reset-failed）、假 robotd（busStatus / safeToRestart / policies / startupSubscribe 按剧本变，
启动时读走交接标记）、假 robotctl（脚本结果按顺序给）、临时根目录、假时钟（sleep 只是把时间往前拨）。

    py -3.12 -m pytest tests/test_helper_bus.py -q      （或 py -3.12 -m unittest tests.test_helper_bus）

方案：scratchpad console/handover-plan.md v2 §2.2、§4.2、§5；规矩：studio-ops-plan.md §7。
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = HERE.parent / "deploy" / "microduck-helper"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("microduck_helper", str(HELPER))
    spec = importlib.util.spec_from_loader("microduck_helper", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


H = load_helper()
IDS = sorted(H.JOINT_IDS)


class Clock:
    def __init__(self):
        self.t = 1000.0


class Out:
    """假 stdout：break_after 次写以后像管道被关了一样抛 BrokenPipeError（SIGPIPE 已被忽略时拿到的就是它）。"""

    def __init__(self, break_after=None):
        self.buf, self.writes, self.break_after = io.BytesIO(), 0, break_after

    def write(self, b):
        if self.break_after is not None and self.writes >= self.break_after:
            raise BrokenPipeError(32, "Broken pipe")
        self.writes += 1
        self.buf.write(b)

    def flush(self):
        pass

    def lines(self):
        return [json.loads(x) for x in self.buf.getvalue().decode().splitlines() if x.strip()]


class Robot:
    """假 robotd：开机以后按 behaviour 走启动；运行中按字段回 busStatus。"""

    def __init__(self, world):
        self.w = world
        self.reachable = True
        self.mode, self.phase = "motion", "control"
        self.error = None
        self.policy_enabled, self.homed, self.torque = False, True, True
        self.homed_at = None
        self.handover_hold, self.home_recovery = False, False
        self.safe, self.sitting, self.moving = True, False, False
        self.joints = {i: 0.1 for i in IDS}
        self.handover = None
        self.step4 = "success"
        # 开机剧本
        self.boot_at = None
        # adopt / decline / ignore / never_read / stuck_imu / never_ready；
        # 标定模式（mode="commissioning"）：commissioning = 修好的 fork（第一次读成功以后换成实时快照）、
        # commissioning_stuck = 旧 fork（启动报告永远不清，一直 configuring_bus）
        self.behaviour = "adopt"
        self.consume_delay, self.control_delay = 1.0, 5.0
        self.consumed = False
        self.read_marker = None

    def boot(self, t):
        self.boot_at = t
        self.phase, self.step4, self.handover, self.consumed = "configuring_bus", "starting", None, False
        self.handover_hold, self.torque, self.homed, self.policy_enabled = False, None, False, False

    def tick(self, t):
        if self.homed_at is not None and t >= self.homed_at:
            self.homed, self.homed_at = True, None
        if self.boot_at is None or self.w.robotd != "active":
            return
        dt = t - self.boot_at
        if self.mode == "commissioning":
            # 照 fork feetech_commissioning.rs：不认交接标记，开总线时先全部卸力，第一个周期第 4 步就成功；
            # 修好的 fork 第一次读成功以后 busStatus 换成实时快照（舵机读不到是 read_error），旧 fork 永远停在启动报告
            if dt >= self.consume_delay and not self.consumed:
                self.consumed, self.torque, self.step4 = True, False, "success"
            if dt >= self.control_delay and self.consumed and self.behaviour != "commissioning_stuck":
                self.phase = "read_error" if self.error else "ready"
            return
        if dt >= self.consume_delay and not self.consumed:
            self.consumed = True
            marker = Path(self.w.root, "run/microduck-handover/handover.json")
            if self.behaviour == "never_read":
                self.phase = "waiting_for_bus"
            elif marker.exists() and self.behaviour != "ignore":
                self.read_marker = json.loads(marker.read_text(encoding="utf-8"))
                marker.unlink()
                if self.behaviour == "decline":
                    self.phase = "handover_declined"
                    self.handover = {"supported": True, "enabled": True, "result": "declined",
                                     "reason": "目标跟标记不一致", "joint": 23, "item": "goal"}
                else:
                    self.handover = {"supported": True, "enabled": True, "result": "adopted"}
                    self.handover_hold, self.torque = True, True
            else:
                self.torque = False
        if dt >= self.control_delay and self.phase == "configuring_bus" and self.consumed:
            if self.behaviour in ("stuck_imu", "never_ready"):
                return
            self.phase, self.step4 = "control", "success"
            if self.torque is None:
                self.torque = False

    def rpc(self, method, params=None):
        if self.w.robotd != "active" or not self.reachable:
            raise H.RpcError(f"{method}：连不上")
        self.w.rpc_calls.append(method)
        if method == "robot.busStatus" and self.mode == "commissioning":
            return self.commissioning_status()
        if method == "robot.busStatus":
            if self.phase != "control":
                d = {"build": "fake", "mode": self.mode, "phase": self.phase}
                if self.error is not None:
                    d["error"] = self.error
                if self.handover is not None:
                    d["handover"] = self.handover
                return d
            if self.moving:
                self.joints = {i: v + 0.05 for i, v in self.joints.items()}
            d = {"build": "fake", "mode": self.mode, "phase": "control", "homed": self.homed,
                 "policy_enabled": self.policy_enabled, "home_recovery": self.home_recovery,
                 "handover": self.handover,
                 "native": {"torque_state_confirmed": self.torque, "handover_hold": self.handover_hold,
                            "joints": [{"id": i, "position_rad": v} for i, v in self.joints.items()]}}
            if self.error is not None:
                d["error"] = self.error
            return d
        if method == "robot.safeToRestart":
            return {"safe": self.safe, "reason": None if self.safe else "the robot is walking"}
        if method == "robot.policies":
            return {"sitting": self.sitting, "enabled": self.policy_enabled}
        if method == "robot.busCommand":
            if (params or {}).get("action") == "calibration-status":
                return self.w.calibration_status(method)
            raise H.RpcError(f"{method}：不认识的动作 {(params or {}).get('action')}")
        if method == "robot.startupSubscribe":
            return {"steps": {"1": {"status": "success"}, "4": {"status": self.step4}}}
        raise H.RpcError(f"{method}：不认识")

    def commissioning_status(self):
        """标定模式的 busStatus：启动报告（只有四个键，fork main.rs:1310-1315），或者实时快照（feetech_commissioning.rs 的 Status）。"""
        if self.phase in H.STARTING_PHASES:
            return {"build": "fake", "mode": "commissioning", "phase": self.phase, "port": "/dev/ttyS2"}
        servos = [{"id": i, "joint": f"j{i}", "position_raw": 2048, "position_wire_raw": 2048, "position_signed_raw": 0,
                   "speed_raw": 0, "load_raw": 0, "current_raw": 0, "voltage_v": 7.6, "temperature_c": 36,
                   "moving": False, "calibrated": True} for i in IDS]
        return {"build": "fake", "port": "/dev/ttyS2", "mode": "commissioning", "phase": self.phase, "session": 4242,
                "target_hz": 50.0, "achieved_hz": 49.9, "total_cycles": 100, "total_success": 100,
                "total_communication_failures": 0, "errors_by_id": {}, "device_communication": {},
                "last_cycle_error": self.error, "last_failure": None,
                "last_sample": {"cycle": 100, "at_us": 2000000, "servos": servos, "imu": {"source": "bus", "ready": True}},
                "calibrated": True, "imu_mount_verified": True, "torque_state": "off", "torque_off_pending": None,
                "power_pending": False, "motion": None, "policy_motion_enabled": False, "updated_at_us": 2000000}


class World:
    """假 systemd + fuser + 文件系统根 + 锁。"""

    def __init__(self, root):
        self.root, self.clock = root, Clock()
        self.robotd = "active"            # active / deactivating / inactive / failed
        self.result, self.condition = "success", "yes"
        self.stop_hang, self.stop_delay, self.stop_at = False, 0.3, None
        self.restart_at = None
        self.force_condition_no = False
        self.starts = []
        self.units = {"padd": "active", H.GAMESIR: "inactive", H.HOLD_UNIT: "inactive"}
        self.enabled = {H.GAMESIR: False}
        self.dropin, self.hold_fails = True, False
        self.exec_commissioning = False
        self.commissioning_dropin = False
        self.calib_available = True
        self.ctx_factory = FakeCtx
        self.port_users = []
        self.calls, self.rpc_calls, self.events = [], [], []
        self.locks = set()
        self.robot = Robot(self)
        self.on_tick = None
        self.relays = []
        self.robotctl_replies = []      # [(rc, stdout, stderr)]；按调用顺序弹
        self.robotctl_timeouts = []
        self.robotctl_timeout = False
        self.nmcli_active = None        # "wlan0" = 热点开着
        self.nmcli_down_rc, self.nmcli_up_rc = 0, 0
        self.nmcli_down_hang = self.nmcli_up_hang = False
        self.nmcli_calls = []
        self.run_timeouts = []
        Path(root, "etc/systemd/system/robotd.service.d").mkdir(parents=True)
        Path(root, H.DROPIN.lstrip("/")).write_text("[Unit]\n", encoding="utf-8")

    # 文件
    def path(self, p):
        return Path(self.root, p.lstrip("/"))

    def flag(self):
        return self.path(H.FLAG).exists()

    def open_session(self):
        """会话已经开着：旗在、管理锁在、robotd 停着（Studio 拿着总线）。"""
        self.path(H.HELPER_DIR).mkdir(parents=True, exist_ok=True)
        self.path(H.FLAG).write_text("{}", encoding="utf-8")
        self.units[H.HOLD_UNIT] = "active"
        self.robotd = "inactive"

    def calibration_status(self, method="robot.busCommand"):
        if not self.calib_available:
            raise H.RpcError(f"{method}：calibration not available yet")
        import tomllib
        try:
            with open(self.path(H.CALIB), "rb") as f:
                cal = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise H.RpcError(f"{method}：{e}") from e
        return {"calibration": cal, "imu_source": "bus", "uncalibrated_joints": [],
                "imu_mount": {"quat": cal.get("imu_mount_quat"), "verified": cal.get("imu_mount_verified")}}

    # 时间
    def tick(self):
        t = self.clock.t
        if self.robotd == "deactivating" and self.stop_at is not None and t >= self.stop_at:
            self.robotd, self.stop_at = "inactive", None
        if self.restart_at is not None and t >= self.restart_at:
            self.restart_at = None
            self._start(auto=True)
        self.robot.tick(t)
        if self.on_tick:
            self.on_tick(self)

    # systemctl
    def _start(self, auto=False):
        t = self.clock.t
        self.starts = [s for s in self.starts if t - s < 10.0] + [t]
        if len(self.starts) > 5:
            self.result, self.robotd = "start-limit-hit", "failed"
            return 1
        if self.flag() or self.force_condition_no:
            self.condition = "no"
            if self.robotd != "active":
                self.robotd = "inactive"
            return 0
        self.condition = "yes"
        if self.robotd != "active":
            self.robotd = "active"
            self.events.append(("robotd_started", t, self.units[H.HOLD_UNIT], self.flag()))
            self.robot.boot(t)
        return 0

    def show(self, unit, props):
        if unit == "robotd":
            sub = {"active": "running", "deactivating": "stop-sigterm", "inactive": "dead", "failed": "failed"}[self.robotd]
            vals = {"ActiveState": self.robotd, "SubState": sub, "Result": self.result,
                    "ConditionResult": self.condition,
                    "DropInPaths": "/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf"
                    + (" /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf" if self.dropin else "")
                    + (" " + H.COMMISSIONING_DROPIN if self.commissioning_dropin else ""),
                    "ExecStart": "{ path=/opt/robot/robotd ; argv[]=/opt/robot/robotd --socket /run/robotd.sock"
                                 + (" --commissioning" if self.exec_commissioning else "") + " ; }"}
        else:
            vals = {"ActiveState": self.units.get(unit, "inactive")}
        return "".join(f"{p}={vals.get(p, '')}\n" for p in props)

    def run(self, argv):
        self.calls.append(list(argv))
        name, args = argv[0], argv[1:]
        t = self.clock.t
        if name == "logger":
            return 0, "", ""
        if name == "fuser":
            return (0, " ".join(map(str, self.port_users)), "") if self.port_users else (1, "", "")
        if name == "nmcli":
            return self.run_nmcli(args)
        if name == "systemd-run":
            if any(a == f"--unit={H.HOLD_UNIT}" for a in args):
                if self.units[H.HOLD_UNIT] == "active":
                    return 1, "", "Unit microduck-bus-hold.service already exists."
                self.units[H.HOLD_UNIT] = "inactive" if self.hold_fails else "active"
                return 0, "", ""
            return 1, "", "unexpected systemd-run"
        assert name == "systemctl", argv
        if args[0] == "show":
            unit = args[1]
            props = [args[i + 1] for i, a in enumerate(args) if a == "-p"]
            return 0, self.show(unit, props), ""
        if args[0] == "is-active":
            return 0, (self.robotd if args[1] == "robotd" else self.units.get(args[1], "inactive")) + "\n", ""
        if args[0] == "is-enabled":
            return 0, ("enabled" if self.enabled.get(args[1]) else "disabled") + "\n", ""
        if args[0] == "daemon-reload":
            return 0, "", ""
        if args[0] == "restart":
            if args[1] == "robotd":
                self.events.append(("restart_robotd", t))
                if getattr(self, "restart_ok", True):
                    self.robotd, self.result, self.condition = "active", "success", "yes"
                    self.robot.boot(t)
                    return 0, "", ""
                self.robotd, self.result = "failed", "exit-code"
                return 1, "", "Job for robotd.service failed"
            return 0, "", ""
        if args[0] == "reset-failed":
            if args[1] == "robotd":
                self.starts, self.result = [], "success"
                self.events.append(("reset_failed", t))
            return 0, "", ""
        rest = [a for a in args[1:] if a != "--no-block"]
        if args[0] == "start":
            for u in rest:
                if u == "robotd":
                    self.events.append(("start_robotd", t))
                    return self._start(), "", ""
                self.units[u] = "active"
            return 0, "", ""
        if args[0] == "stop":
            for u in rest:
                if u == "robotd":
                    self.events.append(("stop_robotd", t, self.flag()))
                    if self.robotd == "active":
                        self.robotd = "deactivating"
                        self.stop_at = float("inf") if self.stop_hang else t + self.stop_delay
                else:
                    self.units[u] = "inactive"
            return 0, "", ""
        if args[0] == "kill":
            self.events.append(("kill_robotd", t, self.flag()))
            if self.robotd in ("active", "deactivating"):
                self.robotd, self.result, self.stop_at = "inactive", "signal", None
                self.restart_at = t + 2.0          # Restart=always，RestartSec=2s
                return 0, "", ""
            return 1, "", "robotd.service is not loaded/running"
        raise AssertionError(argv)

    def run_nmcli(self, args):
        self.nmcli_calls.append(list(args))
        if args[:4] == ["-t", "-f", "NAME,DEVICE", "connection"] and args[4:] == ["show", "--active"]:
            return 0, (f"{H.HOTSPOT}:{self.nmcli_active}\n" if self.nmcli_active else ""), ""
        if args == ["connection", "down", H.HOTSPOT]:
            if self.nmcli_down_rc:
                return self.nmcli_down_rc, "", "Error: failed to bring down the connection"
            if not self.nmcli_down_hang:
                self.nmcli_active = None
            return 0, "", ""
        if args == ["connection", "up", H.HOTSPOT]:
            if self.nmcli_up_rc:
                return self.nmcli_up_rc, "", "Error: failed to activate connection"
            if not self.nmcli_up_hang:
                self.nmcli_active = "wlan0"
            return 0, "", ""
        return 1, "", f"unexpected nmcli: {args}"

    def run_robotctl(self, argv, timeout):
        self.calls.append(list(argv))
        self.robotctl_timeouts.append(timeout)
        if self.robotctl_timeout:
            self.clock.t += timeout
            return None, "", "", True
        if not self.robotctl_replies:
            return 127, "", "no scripted robotctl", False
        rc, out, err = self.robotctl_replies.pop(0)
        return rc, out, err, False

    def relay(self, ctx, argv, data, on_line):
        self.relays.append((list(argv), data))
        env = {a.split("=", 1)[1].split("=", 1)[0]: a.split("=", 1)[1].split("=", 1)[1]
               for a in argv if a.startswith("--setenv=")}
        verb = argv[-1]
        child = self.ctx_factory(self, data, env=env)
        code = H.run(["microduck-helper", verb], child)
        for line in child.stdout.buf.getvalue().splitlines(keepends=True):
            on_line(line)
        return code


class FakeCtx(H.Ctx):
    def __init__(self, world, stdin, env=None, out=None):
        super().__init__(root=world.root, stdin=io.BytesIO(stdin), stdout=out or Out(), env=env or {},
                         self_path="/usr/local/sbin/microduck-helper")
        self.w = world
        self.check_owner = False

    def now(self):
        return self.w.clock.t

    def sleep(self, s):
        self.w.clock.t += s
        self.w.tick()

    def pid(self):
        return 4242

    def run(self, argv, input=None, timeout=15.0):
        self.w.run_timeouts.append((list(argv), timeout))
        return self.w.run(argv)

    def relay(self, argv, data, on_line):
        return self.w.relay(self, argv, data, on_line)

    def run_robotctl(self, argv, timeout):
        return self.w.run_robotctl(argv, timeout)

    def rpc(self, method, params=None, timeout=1.0):
        return self.w.robot.rpc(method, params)

    def startup_report(self, timeout=1.0):
        return self.w.robot.rpc("robot.startupSubscribe")

    def boot_id(self):
        return "boot-1"

    def lock(self, path):
        if path in self.w.locks:
            return None
        self.w.locks.add(path)
        return path

    def unlock(self, handle):
        self.w.locks.discard(handle)

    def fsync_dir(self, path):
        pass

    def is_root(self):
        return True


def joints(**over):
    rows = [{"id": i, "torque": 1, "goal": 2048 + i, "present": 2045 + i, "offset": 0, "load": 100, "temp": 36,
             "status": 0} for i in IDS]
    for r in rows:
        r.update(over.get(str(r["id"]), {}))
    return rows


def marker(**kw):
    m = {"requested_by": "Studio 测试 · 192.168.0.100", "ttl_ms": 20000, "port": "/dev/ttyS2",
         "arm_registers": {"limit": 1000, "p": 5, "d": 0}, "joints": joints()}
    m.update(kw)
    return m


DETACHED = {H.DETACH_ENV: "1", H.REQUEST_ENV: "tok"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helper-bus-")
        self.w = World(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, verb, args, env=None, out=None, raw=None):
        ctx = FakeCtx(self.w, raw if raw is not None else json.dumps(args).encode(), env=env, out=out)
        code = H.run(["microduck-helper", verb], ctx)
        return code, ctx

    def give(self, args, **kw):
        env = dict(DETACHED, **{H.REQUESTED_ENV: str(int(self.w.clock.t * 1000))})
        return self.call("bus-give-back", args, env=env, **kw)

    def last(self):
        return json.loads(self.w.path(H.LAST).read_text(encoding="utf-8"))

    def ev(self, name):
        return [e for e in self.w.events if e[0] == name]

    def calls(self, *prefix):
        return [c for c in self.w.calls if c[:len(prefix)] == list(prefix)]


# ---------------------------------------------------------------------------

class TakeTest(Base):
    def test_from_holding_stops_pads_then_flags_then_stops_robotd(self):
        code, ctx = self.call("bus-take", {"by": "电脑 192.168.0.100"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertTrue(self.w.flag())
        self.assertEqual(self.w.robotd, "inactive")
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active")
        self.assertEqual(self.w.units["padd"], "inactive")
        stops = self.ev("stop_robotd")
        self.assertEqual(len(stops), 1)
        self.assertTrue(stops[0][2], "停 robotd 的时候旗必须已经立好")
        order = [c for c in self.w.calls if c[0] == "systemctl" and c[1] == "stop"]
        self.assertEqual(order[0], ["systemctl", "stop", "padd"], "手柄先停，再判状态、停主程序")
        self.assertEqual(self.last()["result"], "taken")
        self.assertEqual(ctx.stdout.lines()[-1]["step"], "done")
        oplog = self.w.path(H.OPLOG).read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(oplog[-1])["verb"], "bus-take")

    def test_policy_enabled_is_refused_and_pads_come_back(self):
        self.w.robot.policy_enabled = True
        code, ctx = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertIn("先按手柄 Start", self.last()["reason"])
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.robotd, "active")
        self.assertFalse(self.ev("stop_robotd"))
        self.assertEqual(self.w.units["padd"], "active", "门槛没过要把 padd 拉回来")
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive", "这次起的管理锁要放掉")
        self.assertNotIn("robot.enable", self.w.rpc_calls, "不自动停策略")

    def test_seated(self):
        self.w.robot.policy_enabled = self.w.robot.sitting = True
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_STATE, "没允许坐姿接管")
        self.assertIn("坐", self.last()["reason"])
        self.w.robot.moving = True
        code, _ = self.call("bus-take", {"by": "x", "allow_seated": True})
        self.assertEqual(code, H.EXIT_STATE, "坐着但在动")
        self.assertIn("moved_deg", self.last()["detail"])
        self.w.robot.moving = False
        self.w.robot.safe = False
        code, _ = self.call("bus-take", {"by": "x", "allow_seated": True})
        self.assertEqual(code, H.EXIT_STATE, "坐下动作还没做完")
        self.w.robot.safe = True
        code, _ = self.call("bus-take", {"by": "x", "allow_seated": True})
        self.assertEqual(code, H.EXIT_OK)
        self.assertIn("坐", self.last()["reason"])

    def test_waits_for_homing_up_to_3s(self):
        self.w.robot.homed = False
        self.w.robot.homed_at = self.w.clock.t + 1.0
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)
        self.w.robot.homed = False
        self.w.robotd = "active"
        self.w.path(H.FLAG).unlink()
        self.w.units[H.HOLD_UNIT] = "inactive"
        t0 = self.w.clock.t
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertIn("3 秒", self.last()["reason"])
        self.assertLess(self.w.clock.t - t0, 5.0)

    def test_stop_hang_kills_after_10s_with_flag_and_restart_is_blocked(self):
        self.w.stop_hang = True
        t0 = self.w.clock.t
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)
        kills = self.ev("kill_robotd")
        self.assertEqual(len(kills), 1)
        self.assertGreaterEqual(kills[0][1] - t0, 10.0)
        self.assertTrue(kills[0][2], "KILL 之前旗必须已经立好")
        Clock_before = self.w.clock.t
        FakeCtx(self.w, b"").sleep(3.0)           # Restart=always 2 秒后去拉 robotd：被旗挡住
        self.assertGreater(self.w.clock.t, Clock_before)
        self.assertEqual(self.w.robotd, "inactive")
        self.assertEqual(self.w.condition, "no")

    def test_port_busy_keeps_flag_and_lock(self):
        self.w.port_users = [777]
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(self.last()["result"], "port_busy")
        self.assertTrue(self.w.flag(), "端口被占时旗不撤")
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active")

    def test_without_guard_refused_before_touching_anything(self):
        self.w.dropin = False
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertEqual(self.last()["result"], "no_guard")
        self.assertEqual(self.w.robotd, "active")
        self.assertEqual(self.w.units["padd"], "active")

    def test_service_lock_busy_is_exit_4(self):
        self.w.hold_fails = True
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_BUSY)
        self.assertEqual(self.w.robotd, "active")
        self.assertEqual(self.w.units["padd"], "active", "锁都没拿到，不碰手柄")
        self.assertFalse(self.w.flag())

    def test_helper_lock_busy_is_exit_4(self):
        self.w.locks.add(H.LOCK)
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_BUSY)
        self.assertEqual(self.w.robotd, "active")

    def test_robotd_absent(self):
        self.w.robotd = "inactive"
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)
        self.assertTrue(self.w.flag())
        self.assertIn("没在跑", self.last()["reason"])

    def test_session_already_open(self):
        self.w.open_session()
        n_runs = len(self.calls("systemd-run"))
        code, _ = self.call("bus-take", {"by": "Studio 重启后重新接管"})
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(len(self.calls("systemd-run")), n_runs, "管理锁已经在，不再起一个")
        self.assertTrue(self.last()["detail"]["session_was_open"])

    def test_unreachable_robotd_refused(self):
        self.w.robot.reachable = False
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertIn("不回话", self.last()["reason"])
        self.assertFalse(self.w.flag())

    def test_starting_phase_and_declined_phase_are_takeable(self):
        for phase in ("waiting_for_bus", "handover_declined"):
            self.w.robotd = "active"
            self.w.robot.phase = phase
            if self.w.flag():
                self.w.path(H.FLAG).unlink()
            code, _ = self.call("bus-take", {"by": "x"})
            self.assertEqual(code, H.EXIT_OK, phase)


class PadTest(Base):
    """pad-pair / pad-forget：只跑官方 robotctl，不碰总线、hold 单元、robotd 或服务管理锁。"""

    PRO = "AA:BB:CC:DD:EE:11"

    def setUp(self):
        super().setUp()
        p = self.w.path(H.ROBOTCTL)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#!/bin/sh\n", encoding="utf-8")

    def robotctl_calls(self):
        return [c for c in self.w.calls if c and c[0] == H.ROBOTCTL]

    def test_pair_args_are_validated_without_running_robotctl(self):
        cases = [
            {"by": "x", "mac": "nope"},
            {"by": "x", "mac": "AA:BB:CC:DD:EE"},
            {"by": "x", "extra": 1},
            {"by": "x", "timeout": 9},
            {"by": "x", "timeout": 121},
            {"by": "x", "timeout": True},
            {"by": "", "mac": self.PRO},
        ]
        for args in cases:
            with self.subTest(args=args):
                code, ctx = self.call("pad-pair", args)
                self.assertEqual(code, H.EXIT_ARGS, ctx.stdout.lines())
                self.assertEqual(self.last()["result"], "bad_args")
        self.assertEqual(self.robotctl_calls(), [])

    def test_forget_args_are_validated_without_running_robotctl(self):
        cases = [{"by": "x"}, {"by": "x", "mac": "nope"}, {"by": "x", "mac": self.PRO, "timeout": 10}]
        for args in cases:
            with self.subTest(args=args):
                code, ctx = self.call("pad-forget", args)
                self.assertEqual(code, H.EXIT_ARGS, ctx.stdout.lines())
                self.assertEqual(self.last()["result"], "bad_args")
        self.assertEqual(self.robotctl_calls(), [])

    def test_missing_robotctl(self):
        self.w.path(H.ROBOTCTL).unlink()
        code, ctx = self.call("pad-pair", {"by": "x"})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "no_robotctl")
        self.assertEqual(self.robotctl_calls(), [])

    def test_paired_json_is_parsed_and_stderr_is_kept(self):
        self.w.robotctl_replies.append((
            0,
            '{"outcome":"paired","pad":{"mac":"AA:BB:CC:DD:EE:11","name":"Pro Controller",'
            '"paired":true,"trusted":true,"connected":true}}\n',
            "paused btd while the pad bonds; it comes back on its own\n"
            "warning: could not power-cycle the Bluetooth adapter, so this pairing may fail.\n",
        ))
        code, ctx = self.call("pad-pair", {"by": "电脑", "mac": "aa:bb:cc:dd:ee:11", "timeout": 20})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        last = self.last()
        self.assertEqual(last["result"], "paired")
        self.assertEqual(last["detail"]["pair"]["pad"]["name"], "Pro Controller")
        self.assertEqual(len(last["detail"]["stderr"]), 2)
        self.assertIn("paused btd", last["detail"]["stderr"][0])
        self.assertEqual(self.robotctl_calls(),
                         [[H.ROBOTCTL, "pad", "pair", "--json", "--timeout", "20", self.PRO]])
        self.assertEqual(self.w.robotctl_timeouts, [50])

    def test_official_failure_keeps_reason_and_detail(self):
        self.w.robotctl_replies.append((
            0,
            '{"outcome":"failed","reason":"not_found","detail":"nothing that looks like a gamepad turned up"}\n',
            "",
        ))
        code, ctx = self.call("pad-pair", {"by": "电脑", "mac": self.PRO})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        last = self.last()
        self.assertEqual(last["result"], "pair_failed")
        self.assertEqual(last["detail"]["reason"], "not_found")
        self.assertIn("not_found", last["reason"])
        self.assertEqual(last["detail"]["pair"]["detail"], "nothing that looks like a gamepad turned up")

    def test_timeout_kills_and_reports_timeout(self):
        self.w.robotctl_timeout = True
        code, ctx = self.call("pad-pair", {"by": "电脑", "timeout": 10})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "timeout")
        self.assertEqual(self.w.robotctl_timeouts, [40])
        self.assertIn("40", self.last()["reason"])

    def test_forget_success_and_not_paired(self):
        self.w.robotctl_replies.append((
            0, f"forgot {self.PRO}\nThe pad still has its half of the bond. Press Sync before pairing it again.\n", ""))
        code, ctx = self.call("pad-forget", {"by": "电脑", "mac": self.PRO.lower()})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "forgotten")
        self.assertIs(self.last()["detail"]["removed"], True)
        self.assertEqual(self.robotctl_calls(), [[H.ROBOTCTL, "pad", "forget", self.PRO]])

        self.w.robotctl_replies.append((0, f"{self.PRO} was not paired\n", ""))
        code, ctx = self.call("pad-forget", {"by": "电脑", "mac": self.PRO})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertIs(self.last()["detail"]["removed"], False)

    def test_pair_is_busy_while_lock_is_held(self):
        self.w.locks.add(H.LOCK)
        code, ctx = self.call("pad-pair", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_BUSY, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "busy")
        self.assertEqual(self.robotctl_calls(), [])

    def test_pair_does_not_touch_the_bus_or_robotd(self):
        self.w.robotctl_replies.append((0, '{"outcome":"paired","pad":{}}\n', ""))
        code, ctx = self.call("pad-pair", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertEqual(self.w.robotd, "active")
        self.assertEqual([c for c in self.w.calls if c and c[0] == "systemctl"], [])
        self.assertEqual([c for c in self.w.calls if c and c[0] == "systemd-run"], [])


class WifiTest(Base):
    """wifi-hotspot-down / wifi-hotspot-up：只碰 nmcli，不碰总线旗子、hold 单元、robotd 或 helper.lock。"""

    def nmcli(self, verb="show"):
        return [c for c in self.w.nmcli_calls if c[:1] == [verb] or (verb == "show" and c[:1] == ["-t"])]

    def test_args_are_validated_without_running_nmcli(self):
        for verb in ("wifi-hotspot-down", "wifi-hotspot-up"):
            for args in ({"by": ""}, {"by": "x", "extra": 1}, {"by": 3}, {}):
                with self.subTest(verb=verb, args=args):
                    code, ctx = self.call(verb, args)
                    self.assertEqual(code, H.EXIT_ARGS, ctx.stdout.lines())
                    self.assertEqual(self.last()["result"], "bad_args")
        code, ctx = self.call("wifi-hotspot-down", {"by": "x", "ssid": 3})
        self.assertEqual(code, H.EXIT_ARGS, ctx.stdout.lines())
        self.assertEqual(self.w.nmcli_calls, [])

    def test_down_when_already_off_is_ok(self):
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "already_down")
        self.assertEqual(self.w.nmcli_calls[0][:1], ["-t"])
        self.assertNotIn(["connection", "down", H.HOTSPOT], self.w.nmcli_calls)
        self.assertFalse(self.w.path(H.STUDIO_CONNECTING).exists())

    def test_down_turns_the_hotspot_off_and_waits(self):
        self.w.nmcli_active = "wlan0"
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑", "ssid": "Home"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "hotspot_down")
        self.assertIn(["connection", "down", H.HOTSPOT], self.w.nmcli_calls)
        self.assertIsNone(self.w.nmcli_active)
        self.assertEqual(self.last()["by"], "电脑")
        window = json.loads(self.w.path(H.STUDIO_CONNECTING).read_text(encoding="utf-8"))
        self.assertEqual(window["ssid"], "Home")
        self.assertTrue(time.time() + 80 < window["until"] <= time.time() + 95)
        self.assertIn((H.STUDIO_CONNECTING, 0o644), ctx.fs_log)
        self.assertIn((H.STUDIO_CONNECTING_DIR, 0o755), ctx.fs_log)
        self.assertIn((["nmcli", "connection", "down", H.HOTSPOT], H.NMCLI_DOWN_TIMEOUT),
                      self.w.run_timeouts)

    def test_down_failure_is_exit_5(self):
        self.w.nmcli_active = "wlan0"
        self.w.nmcli_down_rc = 4
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "down_failed")
        self.assertEqual(self.last()["exit"], H.EXIT_FAIL)

    def test_down_times_out_after_10s(self):
        self.w.nmcli_active = "wlan0"
        self.w.nmcli_down_hang = True
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "timeout")
        self.assertGreaterEqual(self.w.clock.t, 1000.0 + H.WIFI_DOWN_WAIT)

    def test_up_when_already_on_is_ok(self):
        self.w.nmcli_active = "wlan0"
        self.w.path(H.STUDIO_CONNECTING_DIR).mkdir(parents=True, exist_ok=True)
        self.w.path(H.STUDIO_CONNECTING).write_text("{}", encoding="utf-8")
        code, ctx = self.call("wifi-hotspot-up", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "already_up")
        self.assertNotIn(["connection", "up", H.HOTSPOT], self.w.nmcli_calls)
        self.assertFalse(self.w.path(H.STUDIO_CONNECTING).exists())

    def test_up_turns_the_hotspot_on_and_waits(self):
        self.w.path(H.STUDIO_CONNECTING_DIR).mkdir(parents=True, exist_ok=True)
        self.w.path(H.STUDIO_CONNECTING).write_text("{}", encoding="utf-8")
        code, ctx = self.call("wifi-hotspot-up", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "hotspot_up")
        self.assertEqual(self.w.nmcli_active, "wlan0")
        self.assertIn(["connection", "up", H.HOTSPOT], self.w.nmcli_calls)
        self.assertFalse(self.w.path(H.STUDIO_CONNECTING).exists())

    def test_up_failure_is_exit_5(self):
        self.w.nmcli_up_rc = 3
        code, ctx = self.call("wifi-hotspot-up", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "up_failed")

    def test_up_times_out_after_30s(self):
        self.w.nmcli_up_hang = True
        code, ctx = self.call("wifi-hotspot-up", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_FAIL, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "timeout")
        self.assertGreaterEqual(self.w.clock.t, 1000.0 + H.WIFI_UP_WAIT)

    def test_wifi_lock_is_separate_from_the_bus_lock(self):
        self.w.locks.add(H.WIFI_LOCK)
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_BUSY, ctx.stdout.lines())
        self.assertEqual(self.last()["result"], "busy")
        self.assertEqual(self.w.nmcli_calls, [])
        self.w.locks.discard(H.WIFI_LOCK)
        self.w.locks.add(H.LOCK)                     # 总线锁不算：热点操作照常
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())

    def test_does_not_touch_the_bus_or_robotd(self):
        self.w.nmcli_active = "wlan0"
        code, ctx = self.call("wifi-hotspot-down", {"by": "电脑"})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertEqual(self.w.robotd, "active")
        self.assertEqual([c for c in self.w.calls if c and c[0] == "systemctl"], [])


class MarkerTest(Base):
    def setUp(self):
        super().setUp()
        self.w.open_session()

    def test_written_atomically_with_helper_fields(self):
        code, ctx = self.give({"by": "x", "marker": marker(boot_id="studio-made-up", mono_ms=1)})
        self.assertEqual(code, H.EXIT_OK, ctx.stdout.lines())
        m = self.w.robot.read_marker
        self.assertEqual(m["schema"], H.SCHEMA)
        self.assertEqual(m["boot_id"], "boot-1", "boot_id 由小助手填，覆盖 Studio 给的")
        self.assertNotEqual(m["mono_ms"], 1)
        self.assertEqual(m["ttl_ms"], 20000)
        self.assertEqual(len(m["joints"]), 15)
        self.assertIn((H.MARKER_DIR, 0o700), ctx.fs_log)
        self.assertIn((H.MARKER, 0o600), ctx.fs_log)
        leftovers = [p.name for p in self.w.path(H.MARKER_DIR).iterdir()]
        self.assertEqual(leftovers, [], "没有临时文件留下、标记已被 robotd 读走")

    @unittest.skipUnless(os.name == "posix", "权限位只在 POSIX 上能核")
    def test_marker_modes_on_posix(self):
        self.w.robot.behaviour = "never_read"
        seen = {}

        def peek(w):
            p = w.path(H.MARKER)
            if p.exists() and not seen:
                seen["file"] = stat.S_IMODE(p.stat().st_mode)
                seen["dir"] = stat.S_IMODE(w.path(H.MARKER_DIR).stat().st_mode)
        self.w.on_tick = peek
        self.give({"by": "x", "marker": marker()})
        self.assertEqual(seen, {"file": 0o600, "dir": 0o700})

    def test_validation(self):
        bad = [
            marker(joints=joints()[:14]),
            marker(joints=joints()[:14] + [joints()[0]]),
            marker(joints=joints(**{"23": {"torque": 0}})),
            marker(joints=joints(**{"23": {"goal": 40000}})),
            marker(joints=joints(**{"23": {"goal": True}})),
            marker(joints=joints(**{"23": {"extra": 1}})),
            marker(ttl_ms=30001),
            marker(ttl_ms=10),
            marker(port="/dev/ttyS0"),
            marker(schema="microduck-handover/2"),
            marker(arm_registers={"limit": 1000, "p": 5}),
            dict(marker(), surprise=1),
        ]
        for m in bad:
            code, _ = self.give({"by": "x", "marker": m})
            self.assertEqual(code, H.EXIT_ARGS, json.dumps(m, ensure_ascii=False)[:120])
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertFalse(self.ev("start_robotd"), "参数错就不起 robotd")
        self.assertTrue(self.w.flag())
        for args in ({"by": "x"}, {"by": "x", "soft": True, "marker": marker()}, {"by": "x", "soft": False},
                     {"marker": marker()}, {"by": "x", "marker": marker(), "z": 1}):
            code, _ = self.give(args)
            self.assertEqual(code, H.EXIT_ARGS, args.keys())

    def test_adopted_releases_lock_and_starts_pads(self):
        self.w.units["padd"] = "inactive"
        self.w.enabled[H.GAMESIR] = True
        flag_lock_during = []
        self.w.on_tick = lambda w: flag_lock_during.append((w.flag(), w.units[H.HOLD_UNIT]))
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(self.last()["result"], "adopted")
        self.assertFalse(self.w.flag())
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive", "有结果才放锁")
        self.assertEqual(self.w.units["padd"], "active")
        self.assertEqual(self.w.units[H.GAMESIR], "active", "gamesir 只在 enabled 时拉")
        started = self.ev("robotd_started")[0]
        self.assertEqual(started[2], "active", "撤旗、起 robotd 时管理锁还拿着")
        self.assertFalse(started[3])
        self.assertTrue(all(lock == "active" for _, lock in flag_lock_during[:-1]))
        rf, st = self.ev("reset_failed"), self.ev("start_robotd")
        self.assertTrue(rf and rf[0][1] <= st[0][1], "start 之前先 reset-failed")

    def test_declined_retakes_at_once_with_joint_and_item(self):
        self.w.robot.behaviour = "decline"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_RETAKE)
        last = self.last()
        self.assertEqual(last["result"], "retake")
        self.assertIn("#23", last["reason"])
        self.assertIn("goal", last["reason"])
        self.assertEqual(last["detail"]["joint"], 23)
        self.assertTrue(self.w.flag(), "回退重新立旗")
        self.assertEqual(self.w.robotd, "inactive")
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active", "回退不放锁")
        self.assertLess(self.w.clock.t - t0, 5.0)
        stop = self.ev("stop_robotd")[-1]
        self.assertTrue(stop[2], "停 robotd 的时候旗已经立好")

    def test_marker_not_read_in_15s_retakes(self):
        self.w.robot.behaviour = "never_read"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_RETAKE)
        self.assertIn("15 秒没读", self.last()["reason"])
        self.assertAlmostEqual(self.w.clock.t - t0, 15.0, delta=1.5)
        self.assertFalse(self.w.path(H.MARKER).exists(), "没读走的标记要删掉")
        self.assertTrue(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active")

    def test_adopted_but_stuck_retakes_at_20s(self):
        self.w.robot.behaviour = "stuck_imu"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_RETAKE)
        self.assertIn("20 秒", self.last()["reason"])
        self.assertGreaterEqual(self.w.clock.t - t0, 20.0)
        self.assertEqual(self.w.robotd, "inactive")

    def test_start_returning_0_with_condition_no_is_not_success(self):
        self.w.force_condition_no = True
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_RETAKE)
        self.assertIn("Condition", self.last()["reason"])
        start = self.calls("systemctl", "start", "--no-block", "robotd")
        self.assertTrue(start)

    def test_start_limit_hit_retakes_and_reset_failed_every_time(self):
        self.w.starts = [self.w.clock.t - 1] * 5
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_OK, "reset-failed 清了计数，起得来")
        self.w.open_session()
        orig = self.w.run

        def no_reset(argv):
            if argv[:2] == ["systemctl", "reset-failed"]:
                self.w.calls.append(list(argv))
                return 0, "", ""
            return orig(argv)
        self.w.run = no_reset
        self.w.starts = [self.w.clock.t] * 5
        self.w.robot.boot_at = None
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_RETAKE)
        self.assertIn("start-limit-hit", self.last()["reason"])

    def test_robotd_that_ignores_the_marker_is_limp_not_retake(self):
        self.w.robot.behaviour = "ignore"
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(self.last()["result"], "limp")
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")

    def test_commissioning_snapshot_is_limp_not_retake(self):
        """任务 16：标定模式不认交接标记（开总线先全部卸力）。快照来了就算起来了：照「没接手、全卸了」结束，
        不等 15 秒再把总线拿回来、停主程序。"""
        self.w.robot.mode, self.w.robot.behaviour = "commissioning", "commissioning"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_FAIL)
        last = self.last()
        self.assertEqual(last["result"], "limp")
        self.assertIn("标定模式", last["reason"])
        self.assertLess(self.w.clock.t - t0, 10.0)
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.robotd, "active")
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")

    def test_port_busy_refuses_and_keeps_session(self):
        self.w.port_users = [1234]
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(self.last()["result"], "refused")
        self.assertTrue(self.w.flag())
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertFalse(self.ev("start_robotd"))

    def test_no_session_refused(self):
        self.w.path(H.FLAG).unlink()
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertEqual(self.last()["result"], "no_session")
        self.assertFalse(self.ev("start_robotd"))


class AbortTest(Base):
    def setUp(self):
        super().setUp()
        self.w.open_session()

    def test_abort_during_give_back(self):
        self.w.robot.behaviour = "stuck_imu"
        results = {}

        def press_relax(w):
            if "abort" not in results and w.robotd == "active" and w.clock.t - w.robot.boot_at >= 1.5:
                results["abort"] = self.call("bus-abort", {"by": "页面卸力"})[0]
                results["abort_ms"] = self.last()["ms"]
        self.w.on_tick = press_relax
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(results["abort"], H.EXIT_OK)
        self.assertLessEqual(results["abort_ms"], 1000)
        self.assertEqual(code, H.EXIT_BUSY)
        self.assertEqual(self.last()["result"], "aborted")
        self.assertEqual(self.w.robotd, "inactive")
        self.assertTrue(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active", "中止不放锁")
        kill = self.ev("kill_robotd")[0]
        self.assertTrue(kill[2], "KILL 之前旗已经立好")
        self.assertFalse(self.w.path(H.ABORT).exists(), "give-back 看到以后把中止请求清掉")

    def test_abort_alone_is_fast_and_idempotent(self):
        self.w.robotd = "active"
        self.w.robot.boot(self.w.clock.t)
        self.w.path(H.MARKER_DIR).mkdir(parents=True)
        self.w.path(H.MARKER).write_text("{}", encoding="utf-8")
        self.w.path(H.FLAG).unlink()
        t0 = self.w.clock.t
        code, _ = self.call("bus-abort", {"by": "页面卸力"})
        self.assertEqual(code, H.EXIT_OK)
        self.assertLessEqual(self.w.clock.t - t0, 0.6)
        self.assertTrue(self.w.flag())
        self.assertFalse(self.w.path(H.MARKER).exists())
        self.assertEqual(self.w.robotd, "inactive")
        code, _ = self.call("bus-abort", {"by": "又按了一次"})
        self.assertEqual(code, H.EXIT_OK)

    def test_abort_without_any_session_refuses_and_touches_nothing(self):
        """F4：旗、管理锁、交接标记都不在：没有会话，不许立旗 / 写 abort / KILL 主程序。"""
        self.w.path(H.FLAG).unlink()
        self.w.units[H.HOLD_UNIT] = "inactive"
        self.w.robotd = "active"
        self.w.robot.boot(self.w.clock.t)
        code, ctx = self.call("bus-abort", {"by": "页面卸力"})
        self.assertEqual(code, H.EXIT_STATE)
        self.assertEqual(self.last()["result"], "no_session")
        self.assertFalse(self.w.flag())
        self.assertFalse(self.w.path(H.ABORT).exists())
        self.assertEqual(self.w.robotd, "active")
        self.assertFalse(self.ev("kill_robotd"))
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertEqual(ctx.stdout.lines()[-1]["step"], "done")

    def test_abort_is_not_blocked_by_helper_lock(self):
        self.w.locks.add(H.LOCK)
        code, _ = self.call("bus-abort", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)

    def test_abort_restarts_missing_hold(self):
        self.w.units[H.HOLD_UNIT] = "inactive"
        code, _ = self.call("bus-abort", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(self.w.units[H.HOLD_UNIT], "active")

    def test_old_abort_file_is_ignored_and_cleared(self):
        self.w.path(H.ABORT).write_text(json.dumps({"mono_ms": int((self.w.clock.t - 60) * 1000)}), encoding="utf-8")
        code, _ = self.give({"by": "x", "marker": marker()})
        self.assertEqual(code, H.EXIT_OK)
        self.assertFalse(self.w.path(H.ABORT).exists())

    def test_abort_before_give_back_started_wins(self):
        requested = int(self.w.clock.t * 1000)
        self.w.clock.t += 0.1
        self.call("bus-abort", {"by": "x"})
        env = dict(DETACHED, **{H.REQUESTED_ENV: str(requested)})
        code, _ = self.call("bus-give-back", {"by": "x", "marker": marker()}, env=env)
        self.assertEqual(code, H.EXIT_BUSY)
        self.assertFalse(self.ev("start_robotd"), "已经中止了，不起 robotd")


class SoftTest(Base):
    def setUp(self):
        super().setUp()
        self.w.open_session()

    def test_soft_success(self):
        self.w.units["padd"] = "inactive"
        self.w.path(H.MARKER_DIR).mkdir(parents=True)
        self.w.path(H.MARKER).write_text("{}", encoding="utf-8")
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(self.last()["result"], "soft")
        self.assertIsNone(self.w.robot.read_marker, "软交还先删掉旧标记")
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertEqual(self.w.units["padd"], "active")

    def test_soft_never_ready_fails_after_30s_and_releases_lock(self):
        self.w.robot.behaviour = "never_ready"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(self.last()["result"], "soft_failed")
        self.assertGreaterEqual(self.w.clock.t - t0, 30.0)
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertFalse(self.w.flag())

    def test_soft_port_busy(self):
        self.w.port_users = [99]
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertTrue(self.w.flag())

    def test_soft_commissioning_snapshot_counts_as_up(self):
        """任务 16：标定模式的实时快照（ready）算主程序起来了：不能等满 30 秒判「起不来」（10-20 真机每次交还都这样）。"""
        self.w.robot.mode, self.w.robot.behaviour = "commissioning", "commissioning"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_OK)
        last = self.last()
        self.assertEqual(last["result"], "soft")
        self.assertIn("标定模式", last["reason"])
        self.assertEqual(last["detail"]["phase"], "ready")
        self.assertLess(self.w.clock.t - t0, 10.0)
        self.assertFalse(self.w.flag())
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")

    def test_soft_commissioning_read_error_is_up_with_the_error(self):
        """read_error：主程序起来了，只是读舵机出错——交还算成，把主程序的原话带上。"""
        self.w.robot.mode, self.w.robot.behaviour = "commissioning", "commissioning"
        self.w.robot.error = "Feetech Sync Read timeout; missing IDs [21]"
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_OK)
        self.assertIn("读舵机出错：Feetech Sync Read timeout; missing IDs [21]", self.last()["reason"])

    def test_soft_old_fork_stuck_status_still_fails_but_says_why(self):
        """旧 fork：启动报告永远不清（一直 configuring_bus）。照旧判没起来，话照实说（跟总览「一直报启动中」一个口气）。"""
        self.w.robot.mode, self.w.robot.behaviour = "commissioning", "commissioning_stuck"
        t0 = self.w.clock.t
        code, _ = self.give({"by": "x", "soft": True})
        self.assertEqual(code, H.EXIT_FAIL)
        last = self.last()
        self.assertEqual(last["result"], "soft_failed")
        self.assertIn("30 秒一直报「启动中」（phase=configuring_bus）", last["reason"])
        self.assertIn("旧版主程序的毛病", last["reason"])
        self.assertIn("去日志页", last["reason"])
        self.assertTrue(last["detail"]["still_starting"])
        self.assertEqual(last["detail"]["msg"], last["reason"])          # Studio 只读 done 那一行的 detail
        self.assertGreaterEqual(self.w.clock.t - t0, 30.0)
        self.assertEqual(self.w.units[H.HOLD_UNIT], "inactive")
        self.assertFalse(self.w.flag())                                  # 软交还没拿回总线：主程序照样在跑


class PlumbingTest(Base):
    def test_sigpipe_stdout_closed_midway_still_finishes(self):
        out = Out(break_after=2)
        code, ctx = self.call("bus-take", {"by": "x"}, out=out)
        self.assertEqual(code, H.EXIT_OK)
        self.assertTrue(self.w.flag())
        self.assertEqual(self.w.robotd, "inactive")
        last = self.last()
        self.assertEqual(last["result"], "taken")
        self.assertTrue(last["stdout_dead"])

    def test_detach_reexec_forwards_stdin_and_does_not_recurse(self):
        self.w.open_session()
        raw = json.dumps({"by": "x", "marker": marker()}, ensure_ascii=False).encode()
        code, ctx = self.call("bus-give-back", None, raw=raw)
        self.assertEqual(len(self.w.relays), 1, "只转一次")
        argv, data = self.w.relays[0]
        self.assertEqual(data, raw, "stdin 原样转过去")
        self.assertEqual(argv[0], "systemd-run")
        for flag in ("--wait", "--pipe", "--collect", "--quiet", f"--setenv={H.DETACH_ENV}=1"):
            self.assertIn(flag, argv)
        self.assertTrue(any(a.startswith("--unit=microduck-handover-") for a in argv))
        self.assertEqual(argv[-2:], ["/usr/local/sbin/microduck-helper", "bus-give-back"])
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(self.last()["result"], "adopted")
        self.assertEqual(self.last()["request_id"], next(a for a in argv if a.startswith(f"--setenv={H.REQUEST_ENV}="))
                         .split("=", 2)[2])
        self.assertTrue(any(l.get("result") == "adopted" for l in [x.get("detail") or {} for x in ctx.stdout.lines()]),
                        "子进程的输出原样转回来")

    def test_detach_bad_args_rejected_before_detaching(self):
        self.w.open_session()
        code, _ = self.call("bus-give-back", {"by": "x", "marker": marker(ttl_ms=99999)})
        self.assertEqual(code, H.EXIT_ARGS)
        self.assertFalse(self.w.relays)

    def test_bad_verb_bad_json_unknown_keys(self):
        self.assertEqual(self.call("bus-nope", {"by": "x"})[0], H.EXIT_ARGS)
        self.assertEqual(self.call("bus-take", None, raw=b"not json")[0], H.EXIT_ARGS)
        self.assertEqual(self.call("bus-take", None, raw=b"[1,2]")[0], H.EXIT_ARGS)
        self.assertEqual(self.call("bus-take", {"by": "x", "root": "/tmp"})[0], H.EXIT_ARGS)
        self.assertEqual(self.call("bus-take", {"by": ""})[0], H.EXIT_ARGS)
        self.assertEqual(self.call("bus-abort", {"by": "x", "kill": "all"})[0], H.EXIT_ARGS)
        self.assertEqual(self.w.robotd, "active", "参数错什么都不动")

    def test_bad_verb_does_not_overwrite_last_result_or_oplog(self):
        """F11：Studio 探测小助手用的坏动词照样回 done，但不覆盖上次结果、不追加 oplog。"""
        code, _ = self.call("bus-take", {"by": "x"})
        self.assertEqual(code, H.EXIT_OK)
        last_before = self.w.path(H.LAST).read_text(encoding="utf-8")
        oplog_before = self.w.path(H.OPLOG).read_text(encoding="utf-8").splitlines()
        code, ctx = self.call("bus-nope", {"by": "x"})
        self.assertEqual(code, H.EXIT_ARGS)
        self.assertEqual(ctx.stdout.lines()[-1]["step"], "done")
        self.assertEqual(ctx.stdout.lines()[-1]["detail"]["result"], "bad_verb")
        self.assertEqual(self.w.path(H.LAST).read_text(encoding="utf-8"), last_before)
        self.assertEqual(self.w.path(H.OPLOG).read_text(encoding="utf-8").splitlines(), oplog_before)

    def test_flag_content_and_mode(self):
        code, ctx = self.call("bus-take", {"by": "电脑 A"})
        self.assertEqual(code, H.EXIT_OK)
        body = json.loads(self.w.path(H.FLAG).read_text(encoding="utf-8"))
        self.assertEqual(body["by"], "电脑 A")
        self.assertEqual(body["boot_id"], "boot-1")
        self.assertIn((H.FLAG, 0o644), ctx.fs_log)
        self.assertIn((H.HELPER_DIR, 0o755), ctx.fs_log)

    def test_no_env_can_move_the_root(self):
        src = HELPER.read_text(encoding="utf-8")
        self.assertNotIn("environ.get(\"MICRODUCK_HELPER_ROOT", src)
        self.assertTrue(src.startswith("#!/usr/bin/python3 -IS\n"))
        self.assertEqual(H.Ctx().root, "/")


if __name__ == "__main__":
    unittest.main()
