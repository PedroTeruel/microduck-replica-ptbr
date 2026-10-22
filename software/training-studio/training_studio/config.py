"""Validated public configuration. No user input becomes a shell fragment."""
import copy
import json
import math


class StudioError(Exception):
    def __init__(self, error, status=400, detail=None):
        super().__init__(error)
        self.error, self.status, self.detail = error, status, detail


DEFAULTS = {"num_envs": 2048, "iterations": 1000, "save_interval": 50,
            "seed": 42, "learning_rate": 0.001}
BALANCE_RECIPE = "hd1910-single-leg"
SKILL_DEFAULTS = {"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}
SKILL_LIMITS = {"support_side": ["left", "right"],
                "lift_height_m": {"min": 0.005, "max": 0.02, "step": 0.005},
                "hold_seconds": {"min": 1, "max": 5, "step": 1}}
RECIPES = [
    {"id": "hd1910-flat", "title": "HD1910 平地行走", "description": "练习在平地站稳、向前行走和转向。先短试跑，确认环境能正常运行。",
     "catalog": {"category": "行走", "tags": ["平地", "基础步态", "转向"],
                 "preview_kind": "robot_model", "source_label": "项目内置",
                 "verification_state": "pipeline", "verification_label": "已完成短试跑",
                 "instructions": ["从双脚站立开始。", "根据速度目标练习行走和转向。", "训练后通过检查点评估观察实际步态。"]},
     "task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_velocity", "defaults": dict(DEFAULTS),
     "hardware": "Linux + NVIDIA CUDA 显卡；HD1910 舵机模型", "validation": "已通过 WSL / RTX 5060 Ti 的 64 环境、5 轮短试跑；只验证流程，不代表已经学会走路。"},
    {"id": "hd1910-rough", "title": "HD1910 起伏地形", "description": "练习在有起伏的地面保持平衡和行走。先完成同一配置的短试跑。",
     "catalog": {"category": "行走", "tags": ["起伏地形", "步态", "平衡"],
                 "preview_kind": "text", "source_label": "项目内置",
                 "verification_state": "unverified", "verification_label": "待 GPU 验证",
                 "instructions": ["在有起伏的地面练习行走。", "在速度目标与地形变化中保持身体稳定。", "目前提供任务说明，尚无经过本项目验证的实际回放。"]},
     "task_id": "Mjlab-Velocity-Rough-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_velocity", "defaults": dict(DEFAULTS),
     "hardware": "Linux + NVIDIA CUDA 显卡；HD1910 舵机模型", "validation": "尚未在 GPU 上验证；训练后请先看回放，再决定是否用于机器人。"},
    {"id": BALANCE_RECIPE, "title": "HD1910 单脚平衡", "description": "选择支撑脚、另一只脚抬高多少和保持多久，训练完整的抬脚、保持和落脚动作。",
     "catalog": {"category": "平衡", "tags": ["单脚站立", "抬脚", "自选目标"],
                 "preview_kind": "balance_target", "source_label": "项目内置",
                 "verification_state": "pipeline", "verification_label": "已完成短试跑",
                 "instructions": ["先双脚站立，向支撑脚转移重心。", "抬起另一只脚，保持设定的高度和时间。", "落脚，恢复双脚支撑后才算完成一次动作。"]},
     "task_id": "Mjlab-Balance-Flat-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_balance",
     "defaults": dict(DEFAULTS, num_envs=256, save_interval=25),
     "skill_defaults": dict(SKILL_DEFAULTS), "skill_limits": copy.deepcopy(SKILL_LIMITS),
     "hardware": "Linux + NVIDIA CUDA 显卡；HD1910 舵机模型",
     "validation": "已完成左右两组真实 GPU 短试跑、评估和导出；当前 5 轮策略为 0/8 成功，尚未学会动作，也未经过真机验证。"},
]
RECIPE_BY_ID = {r["id"]: r for r in RECIPES}


def validate_skill(recipe_id, value):
    if not isinstance(recipe_id, str) or recipe_id not in RECIPE_BY_ID:
        raise StudioError("未知训练配方")
    if recipe_id != BALANCE_RECIPE:
        if value is not None:
            raise StudioError("行走配方不接受单脚平衡参数")
        return None
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(SKILL_DEFAULTS):
        raise StudioError("动作参数包含未知字段，或不是 JSON 对象")
    result = dict(SKILL_DEFAULTS, **value)
    if result["support_side"] not in ("left", "right"):
        raise StudioError("support_side 必须是 left 或 right")
    for name in ("lift_height_m", "hold_seconds"):
        number, limits = result[name], SKILL_LIMITS[name]
        if type(number) not in (int, float) or not limits["min"] <= number <= limits["max"] or not math.isfinite(number):
            raise StudioError(f"{name} 必须是 {limits['min']}–{limits['max']} 的有限数字")
        result[name] = float(number)
    return result


def skill_command_contract(skill):
    """Portable copy of engine balance_parameters contract; parity is tested.

    The Studio runtime need not have the engine's Python package installed.
    Update the version together with the engine when command semantics change.
    """
    skill = validate_skill(BALANCE_RECIPE, skill)
    return {
        "version": "microduck.single_leg_balance.v1",
        "actor_observation_size": 61, "action_size": 14, "control_hz": 50,
        "twist_slots": ["support_sign (+1 left, -1 right)",
                        "scheduled swing sole clearance (metres)",
                        "phase / 3 (0 init, 1 lift, 2 hold, 3 return)"],
        "phase_seconds": {"init": 1.0, "lift": 1.0,
                          "hold": skill["hold_seconds"], "return": 1.5},
        "return_includes_settle_seconds": .5,
        "cycle_seconds": skill["hold_seconds"] + 3.5,
        "head_body_commands": "Near-zero pose command padding; deployment uses zeros.",
        "runtime_adapter_required": True,
        "runtime_note": "A matching phase scheduler is required; this is not a velocity policy.",
        "hardware_validated": False, "skill": skill,
    }


def recipe_config(recipe_id, value, kind):
    if not isinstance(value, dict):
        raise StudioError("配置必须是 JSON 对象")
    return validate_config(dict(RECIPE_BY_ID[recipe_id]["defaults"], **value), kind)


def validate_config(config, kind):
    if kind not in ("smoke", "train"):
        raise StudioError("任务类型必须是 smoke 或 train")
    if not isinstance(config, dict) or set(config) - set(DEFAULTS):
        raise StudioError("配置包含未知字段，或不是 JSON 对象")
    result = dict(DEFAULTS, **config)
    for name, lower, upper in (("num_envs", 16, 16384), ("iterations", 1, 100000),
                               ("save_interval", 1, 10000), ("seed", 0, 2147483647)):
        value = result[name]
        if type(value) is not int or not lower <= value <= upper:
            raise StudioError(f"{name} 必须是 {lower}–{upper} 的整数")
    if result["num_envs"] % 4:
        raise StudioError("num_envs 必须是 4 的倍数（PPO 小批次约束）")
    lr = result["learning_rate"]
    if type(lr) not in (int, float) or not 0.000001 <= lr <= 0.01 or not math.isfinite(lr):
        raise StudioError("learning_rate 必须在 0.000001–0.01 之间")
    result["learning_rate"] = float(lr)
    if kind == "smoke":
        result.update(num_envs=64, iterations=5, save_interval=1)
    return result


def validate_profile(profile):
    if profile is None:
        return None
    if not isinstance(profile, dict) or profile.get("schema") != "microduck-studio-duck-profile/v1":
        raise StudioError("档案 schema 必须是 microduck-studio-duck-profile/v1")
    allowed = {"schema", "exported_at", "note", "duck", "body", "imu", "joints", "servo", "walk_model", "policy_global", "voltage"}
    if set(profile) - allowed:
        raise StudioError("档案包含未知的顶层字段")
    try:
        encoded = json.dumps(profile, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise StudioError("档案包含非有限数字或无效 JSON 值") from None
    if len(encoded) > 65536:
        raise StudioError("档案不得超过 64 KiB")

    def walk(value, depth=0):
        if depth > 10:
            raise StudioError("档案嵌套过深")
        if isinstance(value, dict):
            if len(value) > 128:
                raise StudioError("档案对象字段过多")
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > 100:
                    raise StudioError("档案字段名无效")
                walk(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 256:
                raise StudioError("档案数组过长")
            for child in value:
                walk(child, depth + 1)
        elif isinstance(value, str):
            if len(value) > 4096 or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
                raise StudioError("档案文本无效或过长")
        elif type(value) in (int, float):
            if abs(value) > 1e12 or not math.isfinite(value):
                raise StudioError("档案数字超出范围")
        elif value is not None and type(value) is not bool:
            raise StudioError("档案值类型无效")

    walk(profile)
    for key in ("duck", "body", "imu", "servo", "walk_model", "policy_global", "voltage"):
        if profile.get(key) is not None and not isinstance(profile[key], dict):
            raise StudioError(f"档案 {key} 必须是对象或 null")
    for key, value in (profile.get("body") or {}).items():
        if key.endswith("_g") and value is not None and (type(value) not in (int, float) or not 0 < value <= 10000):
            raise StudioError("档案重量必须在 0–10000 克之间")
    quat = (profile.get("imu") or {}).get("mount_quat_wxyz")
    if (profile.get("imu") or {}).get("verified") is not None and type(profile["imu"]["verified"]) is not bool:
        raise StudioError("IMU verified 必须是布尔值或 null")
    if quat is not None and (not isinstance(quat, list) or len(quat) != 4 or
                             any(type(v) not in (int, float) for v in quat) or
                             not 0.8 <= sum(v * v for v in quat) <= 1.2):
        raise StudioError("IMU 四元数必须包含 4 个归一化有限数字")
    joints = profile.get("joints")
    if joints is not None:
        if not isinstance(joints, list) or len(joints) > 32:
            raise StudioError("关节档案必须是最多 32 项的数组")
        ids = set()
        for joint in joints:
            if not isinstance(joint, dict):
                raise StudioError("关节档案必须是对象")
            jid = joint.get("id")
            if jid is not None:
                if type(jid) is not int or not 1 <= jid <= 253 or jid in ids:
                    raise StudioError("关节 ID 必须唯一且在 1–253 之间")
                ids.add(jid)
            if joint.get("direction") is not None and (type(joint["direction"]) not in (int, float) or joint["direction"] not in (-1, 1)):
                raise StudioError("关节方向必须为 -1 或 1")
            for key in ("min_rad", "max_rad"):
                if joint.get(key) is not None and (type(joint[key]) not in (int, float) or abs(joint[key]) > 4 * math.pi):
                    raise StudioError("关节角度超出范围")
            if joint.get("min_rad") is not None and joint.get("max_rad") is not None and joint["min_rad"] >= joint["max_rad"]:
                raise StudioError("关节最小角必须小于最大角")
    voltage = profile.get("voltage") or {}
    if set(voltage) - {"adapt", "nominal_v", "mult"}:
        raise StudioError("电压档案包含未知字段")
    if voltage.get("adapt") is not None and type(voltage["adapt"]) is not bool:
        raise StudioError("电压 adapt 必须是布尔值或 null")
    for key, upper in (("nominal_v", 30), ("mult", 10)):
        value = voltage.get(key)
        if value is not None and (type(value) not in (int, float) or not 0 < value <= upper):
            raise StudioError("电压档案数值超出范围")
    return copy.deepcopy(profile)
