"""假 robotd 里跟「运行和调参」有关的形状（调参方案 v2 T1–T3）。fake_robotd.py 在三个地方调这里：
- set_posture 之后：after_posture(fake, p) —— 策略开着时补 active_action_scale / active_target_filters / scale_use
  （录的夹具是策略没开时的，没有这几个：等上鸭子录「策略开着站着 / 在走 / 坐着」三段再换真的）；
  新姿势 walk_unloaded：照 fork 的真实行为（审查 T-R1）——第 3 步报 success「策略按配置关闭」、loaded_models 为空、
  槽错误和 change_error 都是空的；
- fake.set：fake_set(fake, params) 认这几个键：
    startup {steps:{...}} / null        盖掉按姿势算的启动四步（null = 回到按姿势算），订阅着的连接马上收到通知
    servo_parameters {kp,kd,torque_limit} / null / "absent"   native.hd1910.servo_parameters（"absent" = 键都没有，像原版板端固件）
    walk_profile {action_scale,head_lowpass,legs_lowpass}    loaded_models.walk.runtime_execution_profile 改成这样
    guard {...}                          home_start_guard 里改几项
    last_enable_refusal "原因" / null
    slot_error {槽: "原因" / null}       robot.policies 的 slots[].error
    change_error "原因" / null           robot.policies 的 change_error
    regs null                            registers_before_arm 变空（没上过力）
- 连接上收到 robot.startupSubscribe：startup_stream(fake, reader, writer, rid) —— 先回现在的四步，有变化推 robot.startup，
  客户端发一行或断开就结束（fork robotd main.rs:4671-4686 一样）。errors 里有这个方法就回错（模拟老 robotd 没有它）。
步骤的原话是我们自己写的近似文字；只有「策略按配置关闭」照抄，startup.py 要认这几个字。
"""
import asyncio
import copy
import json

POLICY_OFF = "策略按配置关闭"


def _ok(detail):
    return {"status": "success", "detail": detail}


def startup_report(fake):
    if getattr(fake, "startup_override", None) is not None:
        return {"steps": copy.deepcopy(fake.startup_override.get("steps") or {}), "build": fake.bus.get("build")}
    p = fake.posture
    s1 = _ok("配置、实例锁、IPC、控制线程都起来了")
    if p == "starting":
        steps = {"1": s1, "2": {"status": "waiting", "detail": fake.bus.get("error") or "等全部关节的新鲜反馈；没发目标"}}
    elif p == "stuck_calib":
        steps = {"1": s1, "2": {"status": "waiting", "detail": fake.bus.get("error")}}
    elif p == "commissioning":
        # 照 fork feetech_commissioning.rs：开总线前第 2 步 starting / 打不开 waiting；第一次读成功以后四步都成功。
        # 旧 fork（comm_stuck）四步照样都成功，只是 busStatus 一直回启动报告
        cp = fake.comm_phase() if hasattr(fake, "comm_phase") and fake.mode == "commissioning" else "up"
        if cp == "waiting":
            steps = {"1": s1, "2": {"status": "waiting", "detail": "torque readback at register 40: Feetech Sync Read timeout"}}
        elif cp == "boot" and not getattr(fake, "comm_stuck", False):
            steps = {"1": s1, "2": {"status": "starting", "detail": "标定模式：读取已有标定，关闭并确认扭矩，初始化 IMU"}}
        else:
            steps = {"1": s1, "2": _ok("标定模式：第一份有效反馈读到了"), "3": _ok("标定模式不加载策略模型"),
                     "4": _ok("标定模式第一个周期完成；运动策略关闭")}
    elif p == "walk_unloaded":
        steps = {"1": s1, "2": _ok("第一份有效关节和 IMU 反馈读到了"), "3": _ok(POLICY_OFF), "4": _ok("第一个控制周期完成")}
    else:
        steps = {"1": s1, "2": _ok("第一份有效关节和 IMU 反馈读到了"), "3": _ok("随包模型可用"), "4": _ok("第一个控制周期完成")}
    return {"steps": steps, "build": fake.bus.get("build")}


def after_posture(fake, p):
    bus = fake.bus
    if not isinstance(bus.get("native"), dict):
        return                                    # 调试模式 / 等总线：busStatus 里没有这些
    b0 = fake._bus0
    if p == "walk_unloaded":
        bus["loaded_models"] = None
        bus["active_model"] = None
    elif bus.get("loaded_models") is None and b0.get("loaded_models") is not None:
        bus["loaded_models"] = copy.deepcopy(b0["loaded_models"])
    wp = getattr(fake, "walk_profile", None)
    walk = (bus.get("loaded_models") or {}).get("walk") if isinstance(bus.get("loaded_models"), dict) else None
    if wp and isinstance(walk, dict) and isinstance(walk.get("runtime_execution_profile"), dict):
        walk["runtime_execution_profile"].update(wp)
    prof = (walk or {}).get("runtime_execution_profile") if isinstance(walk, dict) else None
    if p == "policy" and isinstance(prof, dict):
        mult = bus.get("voltage_scale_mult") or 1.0
        bus["active_action_scale"] = round(prof["action_scale"] * mult, 6)
        bus["active_target_filters"] = {"head_lowpass": prof["head_lowpass"], "legs_lowpass": prof["legs_lowpass"]}
        bus["scale_use"] = "joint_uniform"
        bus["active_model"] = {k: walk.get(k) for k in ("path", "sha256", "task")}
    else:
        bus["active_action_scale"] = None
        bus["active_target_filters"] = None
        bus["scale_use"] = "held"
        if p != "walk_unloaded":
            bus["active_model"] = None


def fake_set(fake, params):
    bus = fake.bus
    native = bus.get("native") if isinstance(bus.get("native"), dict) else None
    hd = native.get("hd1910") if native is not None and isinstance(native.get("hd1910"), dict) else None
    if "startup" in params:
        fake.startup_override = params["startup"] if isinstance(params["startup"], dict) else None
    if "servo_parameters" in params and hd is not None:
        v = params["servo_parameters"]
        if v == "absent":
            hd.pop("servo_parameters", None)
        else:
            hd["servo_parameters"] = v
    if isinstance(params.get("walk_profile"), dict):
        fake.walk_profile = dict(params["walk_profile"])
        after_posture(fake, fake.posture)
    if isinstance(params.get("guard"), dict) and isinstance(bus.get("home_start_guard"), dict):
        bus["home_start_guard"].update(params["guard"])
    if "last_enable_refusal" in params:
        bus["last_enable_refusal"] = params["last_enable_refusal"]
    if isinstance(params.get("slot_error"), dict) or "change_error" in params:
        fake.policies = copy.deepcopy(fake.policies or {})
        for s in fake.policies.get("slots") or []:
            if isinstance(s, dict) and s.get("slot") in (params.get("slot_error") or {}):
                s["error"] = params["slot_error"][s["slot"]]
        if "change_error" in params:
            fake.policies["change_error"] = params["change_error"]
    if "regs" in params and hd is not None and params["regs"] is None:
        hd["registers_before_arm"] = []


async def startup_stream(fake, reader, writer, rid):
    err = (getattr(fake, "errors", None) or {}).get("robot.startupSubscribe")
    if err:
        writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": err}) + "\n").encode())
        await writer.drain()
        return
    last = startup_report(fake)
    writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "result": last}, ensure_ascii=False) + "\n").encode())
    await writer.drain()
    fake.startup_subs = getattr(fake, "startup_subs", 0) + 1
    line = asyncio.ensure_future(reader.readline())
    try:
        while True:
            done, _ = await asyncio.wait({line}, timeout=0.1)
            if done:
                return                            # 客户端发了一行或者断开：跟 robotd 一样结束
            cur = startup_report(fake)
            if cur != last:
                last = cur
                writer.write((json.dumps({"jsonrpc": "2.0", "method": "robot.startup", "params": cur},
                                         ensure_ascii=False) + "\n").encode())
                await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        line.cancel()
        fake.startup_subs -= 1
