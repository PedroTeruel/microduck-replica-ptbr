"""Argument construction audited against mjlab v1.3.0 scripts/train.py."""
import re
import math
from pathlib import Path

from .config import RECIPE_BY_ID, StudioError, validate_config


EXPERIMENT = "microduck_hd1910_velocity"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def build_train_argv(run, training_root, checkpoint=None):
    if run["task_id"] not in {r["task_id"] for r in RECIPE_BY_ID.values()}:
        raise StudioError("不支持的训练任务")
    cfg = validate_config(run["config"], run.get("kind", "train"))
    argv = ["uv", "run", "--frozen", "--no-sync", "--offline", "train", run["task_id"],
            "--env.scene.num-envs", str(cfg["num_envs"]), "--agent.max-iterations", str(cfg["iterations"]),
            "--agent.save-interval", str(cfg["save_interval"]), "--agent.seed", str(cfg["seed"]),
            "--agent.algorithm.learning-rate", str(cfg["learning_rate"]), "--agent.logger", "tensorboard",
            "--agent.run-name", "studio_" + run["id"]]
    if checkpoint is not None:
        checkpoint = Path(checkpoint).resolve()
        log_root = (Path(training_root) / "logs" / "rsl_rl" / EXPERIMENT).resolve()
        if checkpoint.parent.parent != log_root or not re.fullmatch(r"model_\d+\.pt", checkpoint.name):
            raise StudioError("检查点不属于当前引擎实验目录")
        argv += ["--agent.resume", "True", "--agent.load-run", "^" + re.escape(checkpoint.parent.name) + "$",
                 "--agent.load-checkpoint", "^" + re.escape(checkpoint.name) + "$"]
    return argv


def parse_metric(line):
    line = ANSI.sub("", line)
    result = {}
    patterns = (("iteration", r"Learning iteration\s+(\d+)\s*/"),
                ("reward", r"Mean (?:total )?reward\s*:\s*([-+\d.eE]+|[-+]?inf(?:inity)?|nan)"),
                ("episode_length", r"Mean episode length\s*:\s*([-+\d.eE]+|[-+]?inf(?:inity)?|nan)"),
                ("fps", r"Steps per second:\s*([-+\d.eE]+|[-+]?inf(?:inity)?|nan)"),
                ("fps", r"(?:Computation:\s*|)([\d.]+)\s+steps/s"))
    for key, pattern in patterns:
        match = re.search(pattern, line, re.I)
        if match:
            try:
                value = int(match[1]) if key == "iteration" else float(match[1])
                if not math.isfinite(value):
                    raise StudioError("训练日志出现非有限指标，任务不能被视为成功。", 409)
                result[key] = value
            except ValueError:
                pass
    return result
