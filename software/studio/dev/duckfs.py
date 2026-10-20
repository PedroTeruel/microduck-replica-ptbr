"""造一棵假的鸭子文件树（调参方案 v2 T2、T3：调参卡读的那些文件），给测试和电脑上截图用。

    py -3.13 -I dev/duckfs.py <目录>            # 造一棵跟二号鸭 10-18 一样的（没有舵机参数文件、嘴巴 0%）
    run.py ... --robotd tcp:... --dev-duck-root <目录>

**内容是我们自己写的最小 JSON / TOML**，只放调参卡要读的字段，不拷原版板端文件（它们不是开源许可）。
形状照二号鸭上读到的（scratchpad duck4.log、tuning-plan.md §2.1）：
- etc/robot/feetech-ft5/robotd.toml 和 robotd.saved.toml：键带引号（原版板端工具的写法），[policy] 里
  action_scale = 0.7、没有 head_lowpass / legs_lowpass、各槽是 /opt/robot/feetech-ft5-r5/models/<id>/policy.onnx；
- 走路模型 1cbf8730… 的 deployment-execution.json：1.0 / 0.5 / 0.7；合同里 model.actuators[0].kp_fw = 5；
- pad-settings.json：嘴巴 0%、头 2.5（.previous 是 6%）；padd 的回执 run/padd/input-settings.json；
- 4 个滑轮模型目录；management-profile.json 的 builtin_models（名字是我们自己起的）。
模型的 sha256 跟假 robotd 回放的夹具（tests/fixtures/now-20261018.jsonl 的 loaded_models）对得上。
"""
import json
import sys
from pathlib import Path

BASE = "opt/robot/feetech-ft5-r5"
ETC = "etc/robot/feetech-ft5"
WALK = "1cbf8730eadd75a5704332c9f3c10f60"
MODELS = {
    WALK: {"slot": "walk", "task": "Mjlab-VelStand-Rough-Backlash-MicroDuck", "ckpt": 9599, "name": "走路＋倒地（联合）9600 轮",
           "sha": "1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f", "filter": False,
           "exec": {"action_scale": 1.0, "head_lowpass": 0.5, "legs_lowpass": 0.7}},
    "1c94934c6421ec72ed48079cea749668": {"slot": "sitstand", "task": "Mjlab-SitStand-Flat-MicroDuck",
                                         "ckpt": "logs/rsl_rl/sitstand/model_9999.pt", "name": None,
                                         "sha": "1c94934c6421ec72ed48079cea74966868a7a59f7d732e0207d0f7bdaeed3c50", "filter": None},
    "b14e3a8b56ddbb8d2d831e727774a168": {"slot": "ground_pick", "task": "Mjlab-GroundPick-Flat-Backlash-MicroDuck", "ckpt": 9999,
                                         "name": "低头捡东西 10000 轮", "filter": True,
                                         "sha": "b14e3a8b56ddbb8d2d831e727774a168c8f5b00194e3e431ae7593a840498c69"},
    "59e15d7b04d0c40e9b11b8a70bdecae6": {"slot": "roulade", "task": "Mjlab-Roulade-Flat-MicroDuck", "ckpt": 9999,
                                         "name": "前滚翻 10000 轮", "filter": True,
                                         "sha": "59e15d7b04d0c40e9b11b8a70bdecae6da87a5e096efc204fb58eea304fcbbac"},
    "67ad09d82f4865d222a7ae06f250cf9f": {"slot": "kick_right", "task": "Mjlab-BallKick-Flat-MicroDuck", "ckpt": 9999,
                                         "name": "右脚踢 10000 轮", "filter": True,
                                         "sha": "67ad09d82f4865d222a7ae06f250cf9f77f08c27e4f019ee3f7e431a764419fd"},
    "ee0376c927044cdece056ba1d3e6eac7": {"slot": "kick_left", "task": "Mjlab-BallKickLeft-Flat-Backlash-MicroDuck", "ckpt": 9999,
                                         "name": "左脚踢 10000 轮", "filter": True,
                                         "sha": "ee0376c927044cdece056ba1d3e6eac77b3e02ee3f701f1feb437c183ed39a6d"},
}
ROLLERS = {"swizzle": (9999, {"action_scale": 1.0, "head_lowpass": 1.0, "legs_lowpass": 1.0}, None),
           "crouch": (7999, {"ground_pick_action_scale": 1.0, "head_lowpass": 1.0, "legs_lowpass": 1.0}, None),
           "spin": (7999, {"ground_pick_action_scale": 1.0, "head_lowpass": 1.0, "legs_lowpass": 1.0}, None),
           "standup": (11000, {"head_lowpass": 1.0, "legs_lowpass": 1.0}, 1.0)}
SKILLS = ("kick_right", "kick_left")


def _w(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, indent=1)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def model_path(ident):
    return f"/{BASE}/models/{ident}/policy.onnx"


def toml_text(action_scale=0.7, extra_policy=""):
    slots = {m["slot"]: model_path(i) for i, m in MODELS.items()}
    skill = ", ".join('{ "name" = "%s", "path" = "%s", "duration" = 0.5, "params" = { "action_scale" = 1.0 } }'
                      % (s, slots[s]) for s in SKILLS)
    return "\n".join([
        '["bus"]', '"port" = "/dev/ttyS2"', f'"feetech_calibration" = "/{ETC}/hd1910-calibration.toml"', "",
        '["policy"]', '"custom_only" = true', '"enabled" = true', '"mode" = "walk"',
        *[f'"{s}" = "{slots[s]}"' for s in ("walk", "sitstand")], '"stand" = "none"',
        *[f'"{s}" = "{slots[s]}"' for s in ("ground_pick", "kick_left", "kick_right", "roulade")],
        '"gain" = 5', f'"action_scale" = {action_scale}', '"standing_action_scale" = 1.0', extra_policy,
        f'"skill" = [{skill}]', "",
        '["pad"]', '"a" = "ground_pick"', '"x" = "roulade"', '"lb" = "kick_left"', '"rb" = "kick_right"',
        '"dpad_down" = "sit_toggle"', "",
        '["trunk_imu"]', '"chip" = "lsm6dsv16x"', ""])


def build(root, servo=None, exec_walk=None, orig=False, saved_differs=False, mouth=0.0, pad_live=True,
          bad_servo=None, bad_exec=None, no_pad_file=False):
    """造树。servo：舵机参数文件的内容（dict），None = 没有这个文件（V167 原版）。bad_servo / bad_exec：写一段坏文本。
    orig：走路模型目录里放一份 .orig。saved_differs：robotd.saved.toml 跟主文件不一样。"""
    root = Path(root)
    _w(root / ETC / "robotd.toml", toml_text())
    _w(root / ETC / "robotd.saved.toml", toml_text(0.8) if saved_differs else toml_text())
    sp = root / ETC / "servo-test-parameters.json"
    if bad_servo is not None:
        _w(sp, bad_servo)
    elif servo is not None:
        _w(sp, json.dumps(servo))
    elif sp.exists():
        sp.unlink()
    pf = root / ETC / "pad-settings.json"
    if no_pad_file:
        if pf.exists():
            pf.unlink()
    else:
        _w(pf, {"mouth_percent": mouth, "head_rad": 2.5})
    _w(root / ETC / "pad-settings.json.previous", {"mouth_percent": 6.0, "head_rad": 2.5})
    live = root / "run" / "padd" / "input-settings.json"
    if pad_live:
        _w(live, {"pid": 1234, "path": f"/{ETC}/pad-settings.json", "settings": {"mouth_percent": mouth, "head_rad": 2.5}})
    elif live.exists():
        live.unlink()
    builtin = []
    for ident, m in MODELS.items():
        d = root / BASE / "models" / ident
        _w(d / "policy.onnx", b"onnx-placeholder")
        man = {"onnx_sha256": m["sha"], "task": m["task"]}
        if isinstance(m["ckpt"], int):
            man["training"] = {"task_id": m["task"], "repo": "pollen-robotics/microduck_rl", "commit": "8d0db74916a4", "checkpoint": m["ckpt"]}
        else:
            man["checkpoint"] = m["ckpt"]
        _w(d / "manifest.json", man)
        if m["name"]:
            _w(d / "model-info.json", {"name": m["name"]})
        con = {"task": m["task"], "model": {"actuators": [{"kp_fw": 5.0}]}}
        if m["filter"] is not None:
            con["action_filter"] = {"enabled": False, "head_alpha": 1.0, "legs_alpha": 1.0}
        _w(d / "deployment-contract.json", con)
        if "exec" in m:
            e = d / "deployment-execution.json"
            if bad_exec is not None:
                _w(e, bad_exec)
            else:
                prof = dict(m["exec"], **(exec_walk or {}))
                _w(e, {"schema": "microduck-runtime-execution/v1", "model_sha256": m["sha"], "mode": "uniform", **prof})
            o = d / "deployment-execution.json.orig"
            if orig:
                _w(o, {"schema": "microduck-runtime-execution/v1", "model_sha256": m["sha"], "mode": "uniform", **m["exec"]})
            elif o.exists():
                o.unlink()
        builtin.append({"id": ident, "slot": m["slot"], "name": m["name"] or "坐下 / 站起 10000 轮"})
    _w(root / BASE / "management-profile.json", {"builtin_models": builtin})
    for name, (ckpt, req, rt) in ROLLERS.items():
        d = root / BASE / "roller" / name
        _w(d / "policy.onnx", b"onnx-placeholder")
        _w(d / "manifest.json", {"onnx_sha256": f"{name:0<16}"[:16] + "0" * 48, "task": f"Mjlab-Roller-{name}",
                                 "training": {"checkpoint": ckpt}})
        con = {"robot_mode": "roller", "required_policy_settings": req}
        if rt is not None:
            con["runtime_action_scale"] = rt
        _w(d / "deployment-contract.json", con)
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：py -3.13 -I dev/duckfs.py <目录>")
    print(build(sys.argv[1]))
