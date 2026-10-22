"""HD1910 single-leg balance, with task-space lift/hold/return goals.

No balanced reference joint pose is assumed: CPU geometry checks establish
clearance reachability, but not a robust static equilibrium. The policy must
learn weight transfer and maintain measured named-foot contact through the hold.
"""

import math
from copy import deepcopy
from dataclasses import replace

from mjlab.managers import RewardTermCfg, TerminationTermCfg
from mjlab.sensor import ContactMatch, ContactSensorCfg

from mjlab_microduck.balance_parameters import BALANCE_EXPERIMENT
from mjlab_microduck.robot.microduck_constants import get_standup_spec
from . import mdp
from .microduck_hd1910_env_cfg import (
    MicroduckHD1910RlCfg,
    make_microduck_hd1910_velocity_env_cfg,
)


def make_microduck_balance_env_cfg(play=False, rough=False):
    if rough:
        raise ValueError("Single-leg balance currently supports flat terrain only")
    cfg = deepcopy(make_microduck_hd1910_velocity_env_cfg(play=play, rough=False))
    # Walking has no head/trunk terrain collision. Full collision geometry is
    # needed to measure and reject head/knee/body props, with identical joints,
    # mass and HD1910 actuators. Only this newly registered task uses it.
    cfg.scene.entities["robot"].spec_fn = get_standup_spec
    cfg.scene.sensors += (ContactSensorCfg(
        name="nonfoot_ground_contact",
        primary=ContactMatch(mode="body", pattern=r"^(?!ankle_left$|ankle_right$).*",
                             entity="robot"),
        secondary=ContactMatch(mode="body", pattern="terrain"),
        fields=("found", "force"), reduce="netforce", num_slots=1,
    ),)
    cfg.terminations["nan_state"].params["sensor_names"] = (
        "feet_ground_contact", "nonfoot_ground_contact")
    cfg.sim.mujoco.iterations = 30
    cfg.sim.mujoco.ls_iterations = 50
    cfg.commands["twist"] = mdp.BalanceCommandCfg(resampling_time_range=(1e9, 1e9))
    cfg.episode_length_s = 9.0
    cfg.is_finite_horizon = True

    for name in ("track_linear_velocity", "track_angular_velocity", "air_time",
                 "foot_clearance", "foot_swing_height", "foot_slip", "pose",
                 "body_pose_tracking", "head_pose_bias"):
        cfg.rewards.pop(name, None)
    # Tiny pose-command ranges retain the family observation layout, while
    # explicit zero buckets cover the deployment scheduler's zero padding.
    for name, width in (("head_pose", 4), ("body_pose", 6)):
        cfg.commands[name].ranges = ((-1e-5, 1e-5),) * width
        cfg.commands[name].zero_command_prob = .25
    cfg.rewards["head_pose_tracking"].weight = .1
    cfg.rewards["upright"].weight = 1.0
    cfg.rewards["upright"].params["std"] = .5
    cfg.rewards["body_ang_vel"].weight = -.05
    cfg.rewards["angular_momentum"].weight = -.01
    cfg.rewards["action_rate_l2"].weight = -.05
    for name, func, weight in (
        ("balance_height", mdp.balance_height_reward, 3.),
        ("balance_height_error", mdp.balance_height_cost, -1.),
        ("balance_weight_shift", mdp.balance_com_reward, 1.5),
        ("balance_hold", mdp.balance_hold_reward, 3.),
        ("balance_return", mdp.balance_return_reward, 1.5),
        ("balance_support_slip", mdp.balance_support_slip_cost, -1.),
    ):
        cfg.rewards[name] = RewardTermCfg(func=func, weight=weight)

    # Keep the parent's noise, finite-observation guards, Feetech voltage/delay,
    # friction, mass and small CoM randomization. Velocity-specific command
    # schedules and ±0.3m/s pushes do not describe this controlled first skill.
    cfg.curriculum.clear()
    cfg.events.pop("push_robot", None)
    cfg.terminations["fell_over"].params["limit_angle"] = math.radians(45.)
    cfg.terminations["balance_low_trunk"] = TerminationTermCfg(
        func=mdp.root_height_below, params={"min_height": .065})
    cfg.terminations["balance_cycle_complete"] = TerminationTermCfg(
        func=mdp.balance_cycle_complete, time_out=True)
    cfg.terminations["balance_nonfoot_contact"] = TerminationTermCfg(
        func=mdp.balance_nonfoot_contact)
    return cfg


MicroduckBalanceRlCfg = replace(
    deepcopy(MicroduckHD1910RlCfg),
    experiment_name=BALANCE_EXPERIMENT,
    run_name="hd1910_single_leg",
)
