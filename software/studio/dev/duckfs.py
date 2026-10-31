"""Cria uma árvore de arquivos falsa do robô (plano de ajuste v2 T2 e T3), usada pelos testes e capturas de tela.

    py -3.13 -I dev/duckfs.py <diretório>       # Replica o robô nº 2 de 18/10 (sem arquivo de parâmetros dos servos; bico em 0%)
    run.py ... --robotd tcp:... --dev-duck-root <diretório>

**Os arquivos JSON / TOML são mínimos e criados para este projeto**: contêm apenas os campos lidos pelo cartão de ajuste e não copiam arquivos do firmware original (que não têm licença de código aberto).
A estrutura segue os dados lidos no robô nº 2 (scratchpad duck4.log, tuning-plan.md §2.1):
- etc/robot/feetech-ft5/robotd.toml e robotd.saved.toml: chaves entre aspas, como na ferramenta original; em [policy], action_scale = 0.7, sem head_lowpass / legs_lowpass e caminhos dos slots em /opt/robot/feetech-ft5-r5/models/<id>/policy.onnx;
- deployment-execution.json do modelo de caminhada 1cbf8730…: 1.0 / 0.5 / 0.7; no contrato, model.actuators[0].kp_fw = 5;
- pad-settings.json: bico em 0% e cabeça em 2.5 (.previous contém 6%); resposta de padd em run/padd/input-settings.json;
- quatro diretórios de modelos de rodas; builtin_models em management-profile.json (nomes definidos neste projeto).
Os SHA256 dos modelos correspondem a loaded_models no registro de reprodução do robotd falso (tests/fixtures/now-20261018.jsonl).
"""
import json
import sys
from pathlib import Path

BASE = "opt/robot/feetech-ft5-r5"
ETC = "etc/robot/feetech-ft5"
WALK = "1cbf8730eadd75a5704332c9f3c10f60"
MODELS = {
    WALK: {"slot": "walk", "task": "Mjlab-VelStand-Rough-Backlash-MicroDuck", "ckpt": 9599, "name": "Caminhada e recuperação de queda (conjunto), 9.600 iterações",
           "sha": "1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f", "filter": False,
           "exec": {"action_scale": 1.0, "head_lowpass": 0.5, "legs_lowpass": 0.7}},
    "1c94934c6421ec72ed48079cea749668": {"slot": "sitstand", "task": "Mjlab-SitStand-Flat-MicroDuck",
                                         "ckpt": "logs/rsl_rl/sitstand/model_9999.pt", "name": None,
                                         "sha": "1c94934c6421ec72ed48079cea74966868a7a59f7d732e0207d0f7bdaeed3c50", "filter": None},
    "b14e3a8b56ddbb8d2d831e727774a168": {"slot": "ground_pick", "task": "Mjlab-GroundPick-Flat-Backlash-MicroDuck", "ckpt": 9999,
                                         "name": "Abaixar a cabeça para pegar objetos, 10.000 iterações", "filter": True,
                                         "sha": "b14e3a8b56ddbb8d2d831e727774a168c8f5b00194e3e431ae7593a840498c69"},
    "59e15d7b04d0c40e9b11b8a70bdecae6": {"slot": "roulade", "task": "Mjlab-Roulade-Flat-MicroDuck", "ckpt": 9999,
                                         "name": "Cambalhota para a frente, 10.000 iterações", "filter": True,
                                         "sha": "59e15d7b04d0c40e9b11b8a70bdecae6da87a5e096efc204fb58eea304fcbbac"},
    "67ad09d82f4865d222a7ae06f250cf9f": {"slot": "kick_right", "task": "Mjlab-BallKick-Flat-MicroDuck", "ckpt": 9999,
                                         "name": "Chute com o pé direito, 10.000 iterações", "filter": True,
                                         "sha": "67ad09d82f4865d222a7ae06f250cf9f77f08c27e4f019ee3f7e431a764419fd"},
    "ee0376c927044cdece056ba1d3e6eac7": {"slot": "kick_left", "task": "Mjlab-BallKickLeft-Flat-Backlash-MicroDuck", "ckpt": 9999,
                                         "name": "Chute com o pé esquerdo, 10.000 iterações", "filter": True,
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
    """Cria a árvore. servo: conteúdo do arquivo de parâmetros dos servos (dict); None = arquivo ausente (firmware original V167). bad_servo / bad_exec: grava texto inválido.
    orig: coloca uma cópia .orig no diretório do modelo de caminhada. saved_differs: robotd.saved.toml difere do arquivo principal."""
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
        builtin.append({"id": ident, "slot": m["slot"], "name": m["name"] or "Sentar / levantar, 10.000 iterações"})
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
        raise SystemExit("Uso: py -3.13 -I dev/duckfs.py <diretório>")
    print(build(sys.argv[1]))
