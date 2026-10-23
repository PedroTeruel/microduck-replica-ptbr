"""Microduck geometry with LuwuDynamics' public 1910 M6 actuator baseline.

Parameters and provenance: robot/hd1910/. This does not replace the robot's
measured mass/inertia, calibration, or runtime gain/IMU integration.
"""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from mjlab.envs import ManagerBasedRlEnvCfg
from mjlab.managers import EventTermCfg

from mjlab_microduck.actuator.feetech_bam import (
    BacklashEncoderFeetechBamActuatorCfg,
    FeetechBamActuatorCfg,
)
from .microduck_velocity_env_cfg import MicroduckRlCfg, make_microduck_velocity_env_cfg
from . import mdp as microduck_mdp


HD1910_M6_JSON = Path(__file__).resolve().parents[1] / "robot" / "hd1910" / "1910_m6.json"


def adapt_microduck_hd1910_env_cfg(
    cfg: ManagerBasedRlEnvCfg,
    *,
    backlash: bool = False,
) -> ManagerBasedRlEnvCfg:
    """Copy an official task and change only its actuator hardware baseline.

    Copy the whole config: factories and backlash robot constants share nested
    home-pose, observation and reward objects. New recipes must not mutate
    another recipe or the original XL330 registrations.
    """
    cfg = deepcopy(cfg)
    robot = cfg.scene.entities["robot"]
    assert robot.articulation is not None
    actuator_cls = BacklashEncoderFeetechBamActuatorCfg if backlash else FeetechBamActuatorCfg
    robot.articulation.actuators = (
        actuator_cls(
            json_path=str(HD1910_M6_JSON),
            target_names_expr=(r"^(?!passive_).*",),
            kp_fw=5.0,
            vin_range=(7.4, 8.0),
            vin_drop_gain_range=(0.0, 0.2),
            vin_min=7.0,
            delay_min_lag=3,
            delay_max_lag=6,
        ),
    )
    # Standalone Crouch/Spin factories omit this declaration. BAM still writes
    # both per-world model fields; ensure they are expanded before simulation.
    cfg.events.setdefault(
        "expand_bam_friction_fields",
        EventTermCfg(func=microduck_mdp.expand_bam_friction_fields, mode="startup"),
    )
    return cfg


def make_microduck_hd1910_velocity_env_cfg(
    play: bool = False,
    rough: bool = False,
) -> ManagerBasedRlEnvCfg:
    cfg = make_microduck_velocity_env_cfg(play=play, rough=rough)
    # The base factory uses a module-level EntityCfg shared by other tasks.
    # Copy before replacing actuators, including nested home-pose dictionaries.
    robot = deepcopy(cfg.scene.entities["robot"])
    assert robot.articulation is not None
    robot.articulation.actuators = (
        FeetechBamActuatorCfg(
            json_path=str(HD1910_M6_JSON),
            target_names_expr=(r"^(?!passive_).*",),
            kp_fw=5.0,
            vin_range=(7.4, 8.0),
            vin_drop_gain_range=(0.0, 0.2),
            vin_min=7.0,
            delay_min_lag=3,
            delay_max_lag=6,
        ),
    )
    cfg.scene.entities["robot"] = robot
    return cfg


MicroduckHD1910RlCfg = replace(
    deepcopy(MicroduckRlCfg),
    experiment_name="microduck_hd1910_velocity",
    run_name="hd1910_m6_luwu",
    logger="tensorboard",
)
