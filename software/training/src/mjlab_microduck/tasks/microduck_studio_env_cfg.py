"""Isolated HD1910 adaptations of the existing official action factories."""

from copy import deepcopy
from dataclasses import replace

from mjlab.envs import ManagerBasedRlEnvCfg
from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, register_mjlab_task

from .backlash import make_backlash_variant
from .microduck_ball_kick_env_cfg import make_microduck_ball_kick_env_cfg
from .microduck_hd1910_env_cfg import adapt_microduck_hd1910_env_cfg
from .recipe_tasks import RECIPE_TASKS, RecipeTask


def make_studio_hd1910_env_cfg(
    recipe: RecipeTask,
    play: bool = False,
) -> ManagerBasedRlEnvCfg:
    """Retain the task's model, commands, rewards and DR; replace its servos."""
    if recipe.role == "kick_left":
        # The official factory supports both feet, although the legacy registry
        # only exposes right kick. Do not mirror rewards or change module flags.
        cfg = deepcopy(make_microduck_ball_kick_env_cfg(play=play, kick_foot="left"))
        if recipe.backlash:
            cfg = make_backlash_variant(cfg)
    else:
        # These registrations were built by the official factories above us in
        # tasks/__init__.py. Registry loading returns an isolated config copy.
        cfg = load_env_cfg(recipe.upstream_task, play=play)
    cfg = adapt_microduck_hd1910_env_cfg(cfg, backlash=recipe.backlash)

    if recipe.role == "roller_stand":
        # Upstream uses raw 18-joint roller indices, but these shared MDP funcs
        # now select the canonical 14-servo view before indexing. Restrict the
        # correction to this new adaptation; retain all original reward funcs,
        # weights and targets and leave legacy registrations untouched.
        for name in ("pose_stand_legs", "pose_stand_l1", "standing_composite"):
            cfg.rewards[name].params["joint_indices"] = [0, 1, 2, 3, 4, 9, 10, 11, 12, 13]
    return cfg


def register_studio_hd1910_tasks(runner_cls: type) -> None:
    for recipe in RECIPE_TASKS:
        # Left and right kick use the same official PPO settings. Every new ID
        # gets its own experiment directory, including terrain/backlash twins.
        rl_source = recipe.upstream_task.replace("BallKickLeft", "BallKick")
        rl_cfg = replace(
            load_rl_cfg(rl_source),
            experiment_name=recipe.experiment_name,
            run_name="studio_hd1910_m6",
            logger="tensorboard",
        )
        register_mjlab_task(
            task_id=recipe.task_id,
            env_cfg=make_studio_hd1910_env_cfg(recipe),
            play_env_cfg=make_studio_hd1910_env_cfg(recipe, play=True),
            rl_cfg=rl_cfg,
            runner_cls=runner_cls,
        )
