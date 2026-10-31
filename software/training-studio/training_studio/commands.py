"""Argument construction audited against mjlab v1.3.0 scripts/train.py."""
import re
import math
from pathlib import Path

from .config import RECIPE_BY_ID, StudioError, recipe_config, validate_skill


EXPERIMENT = "microduck_hd1910_velocity"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def experiment_for(run):
    recipe_id = run.get("recipe_id")
    recipe = RECIPE_BY_ID.get(recipe_id) if isinstance(recipe_id, str) else None
    if recipe is None or run.get("task_id") != recipe["task_id"]:
        raise StudioError("Tarefa de treinamento não compatível")
    return recipe["experiment_name"]


def build_train_argv(run, training_root, checkpoint=None):
    experiment = experiment_for(run)
    cfg = recipe_config(run["recipe_id"], run["config"], run.get("kind", "train"))
    skill = validate_skill(run["recipe_id"], run.get("skill"))
    argv = ["uv", "run", "--frozen", "--no-sync", "--offline", "train", run["task_id"],
            "--env.scene.num-envs", str(cfg["num_envs"]), "--agent.max-iterations", str(cfg["iterations"]),
            "--agent.save-interval", str(cfg["save_interval"]), "--agent.seed", str(cfg["seed"]),
            "--agent.algorithm.learning-rate", str(cfg["learning_rate"]), "--agent.logger", "tensorboard",
            "--agent.run-name", "studio_" + run["id"]]
    if skill is not None:
        argv += ["--env.commands.twist.support-side", skill["support_side"],
                 "--env.commands.twist.lift-height-m", str(skill["lift_height_m"]),
                 "--env.commands.twist.hold-seconds", str(skill["hold_seconds"])]
    if checkpoint is not None:
        checkpoint = Path(checkpoint).resolve()
        log_root = (Path(training_root) / "logs" / "rsl_rl" / experiment).resolve()
        if checkpoint.parent.parent != log_root or not re.fullmatch(r"model_\d+\.pt", checkpoint.name):
            raise StudioError("O checkpoint não pertence ao diretório de experimentos deste mecanismo")
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
                    raise StudioError("O log de treinamento contém uma métrica não finita; a tarefa não pode ser considerada bem-sucedida.", 409)
                result[key] = value
            except ValueError:
                pass
    return result
