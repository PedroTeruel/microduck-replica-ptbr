"""假 robotd + 假 configd：回放鸭子上录下来的真实回包（dev/record_robotd.py 录的），
让 Studio 在电脑上不接鸭子也能跑通。

    py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl
    （robotd 听 tcp 127.0.0.1:17001，configd 听 17002；只绑本机）

模拟的行为（review-impl-plan I8）：
- 每条连接串行处理：读一行、答一行；
- hello 必须带 api_version（真机就是这样，不带回 -32602）；
- robot.relax 立刻回 accepted:true；过 relax_delay 秒 busStatus 显示扭矩确认 OFF，
  再过 hd_delay 秒 hd1910 的 restore_pending / temporary_gains_applied 才清掉（真机站着时这两个是 True）；
- 调试模式下卸力只把 torque_state 改成 off，不切模式；
- restart(秒)：断开所有现有连接，这段时间拒绝新连接（模拟 robotd 重启）；
- inject：下一次回包前先塞几行（乱码、非对象的 JSON）；errors：指定方法回错误；
- robot.subscribe 按 hz 降频推 robot.state，统计订阅者个数；
- 调试模式下 policies、subscribe 返回错误；
- delays 可以让某个方法故意慢（测「卸力不被慢请求挡住」）；
- down=True 时拒绝新连接（模拟主程序不在）；
- 通知（不带 id：robot.move / head / pose / mouth / sound / do 这些）照 JSON-RPC 不回话（robotd 也不回）；
- 手柄页的请求（robot.init / enable / do / sound / stop / pose / head / mouth、pad.bindings）回 accepted，
  enable / init 顺手改姿势（开 → 准备好走，关 / init → 站着保持），网页手柄的 e2e（tests/test_vpad_e2e.py）靠它；
- --record 文件：收到的每一条（方法、参数、是不是通知、时间）一行 JSON，e2e 拿它核对「发给 robotd 的是什么」；
- fake.set {posture?, pad_connected?}：测试用的控制口，换姿势、假装实体手柄连着（configd 的 pad.status 回连着）。
  总览重排（审查 O18）又加了：{calib: ok / seed / uncal / unavailable}、{pads: [...]}（configd 原样回）、
  {cpu: {c, level, khz, max_khz}}（改 health 里的主板温度、降频）、{errors: {方法: {code, message} 或 null}}。
- 姿势的「形状」照真机（审查 O18）：commissioning 是调试模式的 busStatus（顶层 calibrated / imu_mount_verified /
  policy_motion_enabled，没有 native：fork feetech_commissioning.rs:1522-1524）；starting、stuck_calib 是运动模式卡在
  等总线（只有 build / mode / phase / port / error，没有 native：fork main.rs:1546-1552），这时 calibration-status
  回「calibration not available yet」（feetech_commissioning.rs:160-164）。stuck_calib 报的是标定 / IMU 没过的那一句。
- calib=seed：标定文件里的 zero_raw 不是 2048（随包种子值的样子，fork packaging/hd1910-calibration.robot.toml）。
- 电池剧本（battery-plan.md v2 §6）：fake.set {battery: {v, drop_per_s, sag, gone, glitch}}，null 关掉。
  v 卸力时的电压；每颗按二号鸭 10-18 实测那组偏差量化到 0.1 V；保持 / 策略站着再低 0.08 V，sag 是额外压降（假装在走）；
  drop_per_s 每秒掉多少；gone 15 颗都报 0 V（舵机断电）；glitch 下一次 busStatus 15 颗一起报这个值。
  health.battery 跟着报：volts 是这串数的 α=0.1 EMA（跟真机一样），percent 用 robotd 的 6.6–8.2 直线。
- 运行和调参（调参方案 T1–T3）：启动四步 robot.startupSubscribe、姿势 walk_unloaded、策略开着时的 active_*、
  fake.set 的 startup / servo_parameters / walk_profile / guard / slot_error 这些，都在 dev/fake_tune.py。
测试里直接 import FakeRobotd，在同一个事件循环里起。
"""
import argparse
import asyncio
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I 跑脚本时不会自己加：fake_tune 跟它放在一起
import fake_tune  # noqa: E402


def load_fixture(path):
    replies, frames = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") == "reply":
                key = d["method"] if d["method"] != "robot.busCommand" else "busCommand:" + d["params"].get("action", "")
                replies[key] = (d["reply"] or {}).get("result")
            elif d.get("kind") == "notify":
                m = d.get("msg") or {}
                if m.get("method") == "robot.state":
                    frames.append(m.get("params"))
    return replies, frames


DEFAULT_BINDINGS = [{"button": b, "skill": s, "overridden": False} for b, s in (
    ("a", "ground_pick"), ("x", "roulade"), ("lb", "kick_left"), ("rb", "kick_right"), ("dpad_down", "sit_toggle"))]
ACCEPT = {"robot.init", "robot.enable", "robot.do", "robot.sound", "robot.stop", "robot.pose", "robot.head",
          "robot.mouth", "robot.move"}
STUCK_CALIB = "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"
NO_CALIB = {"code": -32603, "message": "calibration not available yet"}
SEED_ZERO = {20: 2035, 21: 2176, 23: 1990, 24: 2101}     # 随包种子值那种：几颗不是 2048
POSTURES = ["holding", "limp", "policy", "commissioning", "starting", "stuck_calib", "walk_unloaded"]
# 二号鸭 10-18 卸力时 15 颗的电压减去 7.6（ID 20–24 | 30–34 | 10–14，busStatus 的顺序）
BAT_OFFSETS = [0.0, 0.1, 0.0, 0.0, 0.0, 0.1, 0.0, 0.0, -0.1, 0.0, 0.0, 0.1, 0.1, 0.0, 0.1]
BAT_SAG = {"holding": 0.08, "policy": 0.08}


class FakeRobotd:
    def __init__(self, fixture, posture="holding", record=None):
        replies, frames = load_fixture(fixture)
        self.health = copy.deepcopy(replies.get("robot.health"))
        self._bus0 = copy.deepcopy(replies.get("robot.busStatus"))      # 换成调试 / 等总线的样子以后从录的这份重新开始
        self.bus = copy.deepcopy(self._bus0)
        self.policies = replies.get("robot.policies")
        self._calib0 = copy.deepcopy(replies.get("busCommand:calibration-status"))
        self.calib = copy.deepcopy(self._calib0)
        self.calib_mode = "ok"
        self.pad = replies.get("pad.status") or {"driver": "active", "pads": []}
        self.sysinfo = replies.get("system.info") or {"name": "duck-fake"}
        self.frames = frames or [{}]
        self.relax_delay = 0.3
        self.hd_delay = 0.2
        self.delays = {}
        self.errors = {}                      # 方法 -> {"code":..,"message":..}
        self.inject = []                      # 下一次回包前先发出的原始行（bytes）
        self.down = False
        self._writers = set()
        hd = ((self.bus.get("native") or {}).get("hd1910") or {})
        self._hd_hold = {"restore_pending": hd.get("restore_pending", True),
                         "temporary_gains_applied": hd.get("temporary_gains_applied", True)}
        self.subscribers = 0
        self.calls = []                       # (时间, 方法)：测试看先后
        self._relax_at = None
        self.bindings = [dict(b) for b in DEFAULT_BINDINGS]
        self.record = open(record, "a", encoding="utf-8") if record else None   # noqa: SIM115 —— 进程活多久开多久
        self.battery = None                   # 电池剧本（fake.set battery）；None = 回放录的那份电压
        self._bat_ema = None
        self.roller_models = False            # 装没装轮滑模型（robot.setMode 切 roller 要它；fake.set roller_models）
        self.set_posture(posture)

    def set_battery(self, cfg):
        """fake.set {battery: {...}} / null。只给了几项就只改那几项；给了 v 就从现在重新开始算 drop_per_s。"""
        if cfg is None:
            self.battery, self._bat_ema = None, None
            return
        b = dict(self.battery or {"v": 7.6, "drop_per_s": 0.0, "sag": 0.0, "gone": False, "glitch": None})
        b.update({k: cfg[k] for k in ("v", "drop_per_s", "sag", "gone", "glitch") if k in cfg})
        if "v" in cfg or "t0" not in b:
            b["t0"] = time.monotonic()
        self.battery = b

    def _battery_volts(self):
        b = self.battery
        if b.get("glitch") is not None:
            g = float(b["glitch"])
            b["glitch"] = None
            return [g] * 15
        if b.get("gone"):
            return [0.0] * 15
        base = b["v"] - b["drop_per_s"] * (time.monotonic() - b["t0"]) - BAT_SAG.get(self.posture, 0.0) - b["sag"]
        return [round(base + o, 1) for o in BAT_OFFSETS]

    def _bus_with_battery(self):
        bus = copy.deepcopy(self.bus)
        joints = (bus.get("native") or {}).get("joints") if isinstance(bus.get("native"), dict) else None
        if self.battery is None or not isinstance(joints, list):
            return bus
        vs = self._battery_volts()
        for j, v in zip(joints, vs):
            j["volts"] = v
        mean = sum(vs) / len(vs)
        if mean > 0:                    # 舵机断电时真机读不到回包，robotd 沿用上一个读数（不会把 0 V 平均进去）
            self._bat_ema = mean if self._bat_ema is None else 0.1 * mean + 0.9 * self._bat_ema
        return bus

    def _health_with_battery(self):
        if self.battery is None or self._bat_ema is None:
            return self.health
        h = dict(self.health or {})
        v = self._bat_ema
        h["battery"] = {"volts": v, "percent": max(0.0, min(1.0, (v - 6.6) / 1.6)) * 100 if v > 0 else 0.0}
        return h

    def _log(self, method, params, notify):
        if self.record is not None:
            self.record.write(json.dumps({"t": time.time(), "method": method, "params": params, "notify": notify},
                                         ensure_ascii=False) + "\n")
            self.record.flush()

    def set_calib(self, mode):
        """标定文件的样子：ok 录的（15 颗 2048）、seed 种子值（几颗不是 2048）、uncal 有没标的、unavailable 读不到。"""
        self.calib_mode = mode
        self.calib = copy.deepcopy(self._calib0)
        js = ((self.calib or {}).get("calibration") or {}).get("joints") or []
        if mode == "seed":
            for j in js:
                if j.get("id") in SEED_ZERO:
                    j["zero_raw"] = SEED_ZERO[j["id"]]
        elif mode == "uncal":
            for j in js[:2]:
                j["calibrated"] = False
            self.calib["uncalibrated_joints"] = [j.get("name") for j in js[:2]]

    def set_posture(self, p):
        if p in ("commissioning", "starting", "stuck_calib"):
            self._shape(p)
            self.posture = p
            return
        if "native" not in self.bus:
            self.bus = copy.deepcopy(self._bus0)
        n = self.bus.setdefault("native", {})
        hd = n.setdefault("hd1910", {})
        self.bus.update({"mode": "motion", "phase": "control", "policy_enabled": False, "homed": True,
                         "torque_off_pending": False})
        n.update({"torque_enabled": True, "torque_state_confirmed": True})
        hd.update(getattr(self, "_hd_hold", {"restore_pending": True, "temporary_gains_applied": True}))
        self.bus.pop("torque_state", None)
        if p == "limp":
            n.update({"torque_enabled": False, "torque_state_confirmed": False})
            hd.update({"restore_pending": False, "temporary_gains_applied": False})
        elif p == "policy":
            self.bus["policy_enabled"] = True
        self.posture = p
        fake_tune.after_posture(self, p)          # 调参卡要的形状（策略开着的 active_*、walk_unloaded）

    def _shape(self, p):
        """真机上这几种时候 busStatus 的样子（审查 O18）：没有 native，只有几个顶层字段。"""
        b0 = self._bus0
        if p == "commissioning":
            self.bus = {"build": b0.get("build"), "mode": "commissioning", "phase": "ready", "port": b0.get("port"),
                        "torque_state": "all_enabled", "torque_off_pending": None, "calibrated": self.calib_mode != "uncal",
                        "imu_mount_verified": True, "policy_motion_enabled": True}
        else:
            err = STUCK_CALIB if p == "stuck_calib" else "torque readback at register 40: Feetech Sync Read timeout; missing IDs [21]"
            self.bus = {"build": b0.get("build"), "mode": "motion", "phase": "waiting_for_bus", "port": b0.get("port"),
                        "error": err}

    def _tick(self):
        if self._relax_at is None:
            return
        el = time.monotonic() - self._relax_at
        if self.bus.get("mode") == "commissioning":
            if el >= 0:
                self.bus["torque_state"] = "off"
                self._relax_at = None
            return
        n = self.bus.get("native")
        if n is None:                    # 卡在等总线：没有扭矩可卸（真机这时 relax 也只是记一下）
            self._relax_at = None
            return
        if el >= 0:
            n.update({"torque_enabled": False, "torque_state_confirmed": False})
        if el >= self.hd_delay:
            n["hd1910"].update({"restore_pending": False, "temporary_gains_applied": False})
            self.posture = "limp"
            self._relax_at = None

    def stand_up(self):
        """模拟别人用手柄让它站起来（重新上力）。"""
        self._relax_at = None
        self.set_posture("holding")

    def restart(self, down_s=0.5):
        """模拟 robotd 重启：现有连接全部断开，down_s 秒内拒绝新连接。"""
        self.down = True
        for w in list(self._writers):
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass
        asyncio.get_running_loop().call_later(down_s, setattr, self, "down", False)

    async def dispatch(self, method, params):
        self.calls.append((time.monotonic(), method))
        if method in self.delays:
            await asyncio.sleep(self.delays[method])
        self._tick()
        if method in self.errors:
            return None, self.errors[method]
        if method == "hello":
            if "api_version" not in (params or {}):
                return None, {"code": -32602, "message": "missing field `api_version`"}
            return {"api_version": 40, "daemon_version": "0.17.0", "revision": "fake"}, None
        if method == "robot.health":
            return self._health_with_battery(), None
        if method == "robot.busStatus":
            return self._bus_with_battery(), None
        if method == "robot.policies":
            if self.bus.get("mode") != "motion":
                return None, {"code": -32603, "message": "robotd is in commissioning mode"}
            return dict(self.policies or {}, sitting=False), None
        if method == "robot.busCommand" and (params or {}).get("action") == "calibration-status":
            # 卡在等总线：标定只在开总线成功后才存（fork main.rs:1535），这时回错
            if self.calib_mode == "unavailable" or self.posture in ("starting", "stuck_calib"):
                return None, NO_CALIB
            return self.calib, None
        if method == "robot.relax":
            if self._relax_at is None and not (self.posture == "limp" or self.bus.get("torque_state") == "off"):
                self._relax_at = time.monotonic() + self.relax_delay
            return {"accepted": True}, None
        if method == "pad.status":
            return self.pad, None
        if method == "system.info":
            return self.sysinfo, None
        if method == "pad.bindings":
            return {"bindings": self.bindings}, None
        if method == "fake.set":                       # 测试用：换姿势、假装实体手柄连着
            if params.get("posture"):
                self._relax_at = None                  # 卸力还没「落地」的也算了：直接换成要的姿势
                self.set_posture(params["posture"])
            if "pad_connected" in params:
                self.pad = {"driver": "active", "pads": [{"mac": "78:86:2E:BB:13:28", "name": "Xbox Wireless Controller",
                                                          "paired": True, "trusted": True, "connected": True}]
                            if params["pad_connected"] else []}
            if isinstance(params.get("pads"), list):
                self.pad = {"driver": "active", "pads": params["pads"]}
            if params.get("calib"):
                self.set_calib(params["calib"])
            if "imu_verified" in params and isinstance(self.bus.get("native"), dict):
                # busStatus 的 native.imu_mount_verified（上手清单 IMU 那行「主程序没确认方向，不让跳过」）
                self.bus["native"]["imu_mount_verified"] = bool(params["imu_verified"])
            if isinstance(params.get("cpu"), dict):
                c = params["cpu"]
                self.health = dict(self.health or {})
                if "c" in c:
                    self.health["cpu_temp_c"] = c["c"]
                thr = dict(self.health.get("cpu_throttle") or {})
                thr.update({k: c[k] for k in ("level", "max_level", "khz", "max_khz") if k in c})
                self.health["cpu_throttle"] = thr
            if isinstance(params.get("errors"), dict):
                for m, e in params["errors"].items():
                    if e is None:
                        self.errors.pop(m, None)
                    else:
                        self.errors[m] = e
            if "roller_models" in params:
                self.roller_models = bool(params["roller_models"])
            if "battery" in params:
                self.set_battery(params["battery"] if isinstance(params["battery"], dict) else None)
            fake_tune.fake_set(self, params)           # 调参卡用的键（startup、servo_parameters、walk_profile……）
            if params.get("restart"):
                # 模拟 robotd 重启（Studio 会重新 hello、重读标定）：先回话再断，别把这条控制连接也掐了
                asyncio.get_running_loop().call_later(0.05, self.restart, float(params["restart"]))
            return {"posture": self.posture, "pad": self.pad, "calib": self.calib_mode}, None
        if method == "robot.rebootMotors":
            # fork（handover 版）main.rs:6050-6056 从不拒；主循环先全身卸力再重启，之后软着（main.rs:2731-2758）。这里当卸力演
            if self._relax_at is None and not (self.posture == "limp" or self.bus.get("torque_state") == "off"):
                self._relax_at = time.monotonic() + self.relax_delay
            return {"accepted": True}, None
        if method == "robot.setMode":
            # fork（handover 版）main.rs:5700-5736：不认识的、没策略的、没装轮滑模型的拒；已经是那个模式算接受（带原因）
            want = (params or {}).get("mode")
            if want not in ("walk", "roller", "roller_crouch", "roller_spin"):
                return {"accepted": False, "reason": "mode must be walk, roller, roller_crouch or roller_spin"}, None
            if want != "walk" and not self.roller_models:
                return {"accepted": False, "reason": "roller ONNX models are not installed; original walking policy unchanged"}, None
            want = "walk" if want == "walk" else "roller"
            if (self.policies or {}).get("mode", "walk") == want:
                return {"accepted": True, "reason": "mode already selected"}, None
            self.policies = dict(self.policies or {}, mode=want)
            return {"accepted": True}, None
        if method in ACCEPT:
            if method == "robot.enable" and self.posture in ("holding", "policy"):
                on = (not (self.posture == "policy")) if params.get("toggle") else bool(params.get("on"))
                self.set_posture("policy" if on else "holding")
            elif method == "robot.init" and self.posture == "limp":
                self.set_posture("holding")
            return {"accepted": True}, None
        return None, {"code": -32601, "message": f"method not found: {method}"}

    async def handle(self, reader, writer):
        self._writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                except ValueError:
                    writer.write(b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}\n')
                    await writer.drain()
                    continue
                rid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
                notify = "id" not in req
                self._log(method, params, notify)
                if method == "robot.subscribe":
                    await self._stream(writer, rid, params)
                    break
                if method == "robot.startupSubscribe":
                    await fake_tune.startup_stream(self, reader, writer, rid)
                    break
                result, err = await self.dispatch(method, params)
                if notify:
                    continue                           # 通知不回话（JSON-RPC；robotd 也不回）
                while self.inject:
                    writer.write(self.inject.pop(0))
                reply = {"jsonrpc": "2.0", "id": rid}
                reply.update({"error": err} if err else {"result": result})
                writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self._writers.discard(writer)
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    async def _stream(self, writer, rid, params):
        hz = params.get("hz")
        if hz is not None and not isinstance(hz, int):
            writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "invalid type: floating point, expected u32"}}) + "\n").encode())
            await writer.drain()
            return
        if self.bus.get("mode") != "motion":
            writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": -32603, "message": "commissioning mode"}}) + "\n").encode())
            await writer.drain()
            return
        writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"accepted": True}}) + "\n").encode())
        await writer.drain()
        self.subscribers += 1
        i = 0
        try:
            while True:
                frame = self.frames[i % len(self.frames)]
                writer.write((json.dumps({"jsonrpc": "2.0", "method": "robot.state", "params": frame}, ensure_ascii=False) + "\n").encode())
                await writer.drain()
                i += 1
                await asyncio.sleep(1.0 / (hz or 50))
        except (ConnectionError, OSError):
            pass
        finally:
            self.subscribers -= 1

    async def _gate(self, reader, writer):
        if self.down:
            writer.close()
            return
        await self.handle(reader, writer)

    async def serve_tcp(self, host="127.0.0.1", port=0):
        server = await asyncio.start_server(self._gate, host, port)
        return server, server.sockets[0].getsockname()[1]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--robotd-port", type=int, default=17001)
    ap.add_argument("--configd-port", type=int, default=17002)
    ap.add_argument("--posture", default="holding", choices=POSTURES)
    ap.add_argument("--calib", default="ok", choices=["ok", "seed", "uncal", "unavailable"])
    ap.add_argument("--record", help="把收到的每一条记进这个文件（一行一个 JSON）")
    a = ap.parse_args()
    fake = FakeRobotd(a.fixture, a.posture, a.record)
    if a.calib != "ok":
        fake.set_calib(a.calib)
        fake.set_posture(a.posture)
    s1, p1 = await fake.serve_tcp(port=a.robotd_port)
    s2, p2 = await fake.serve_tcp(port=a.configd_port)
    print(f"假 robotd 在 tcp:127.0.0.1:{p1}，假 configd 在 tcp:127.0.0.1:{p2}，姿势 {a.posture}。Ctrl+C 退出。", flush=True)
    async with s1, s2:
        await asyncio.gather(s1.serve_forever(), s2.serve_forever())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
