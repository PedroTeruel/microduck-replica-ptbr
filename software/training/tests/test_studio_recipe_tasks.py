"""CPU contracts for the public action recipes and their isolated HD1910 cfgs."""

from functools import cache
from pathlib import Path
import runpy

import pytest


# IDs and roles in kissqy's tasks.json at repository revision
# 525a215a19397767a073b782f57e97cf53683761. Keep independent of engine generation.
EXPECTED = {
    "joint": (
        "Mjlab-VelStand-Flat-MicroDuck", "Mjlab-VelStand-Flat-Backlash-MicroDuck",
        "Mjlab-VelStand-Rough-MicroDuck", "Mjlab-VelStand-Rough-Backlash-MicroDuck",
    ),
    "sitstand": (
        "Mjlab-SitStand-Flat-MicroDuck", "Mjlab-SitStand-Flat-Backlash-MicroDuck",
        "Mjlab-SitStand-Rough-MicroDuck", "Mjlab-SitStand-Rough-Backlash-MicroDuck",
    ),
    "ground_pick": (
        "Mjlab-GroundPick-Flat-MicroDuck", "Mjlab-GroundPick-Flat-Backlash-MicroDuck",
        "Mjlab-GroundPick-Rough-MicroDuck", "Mjlab-GroundPick-Rough-Backlash-MicroDuck",
    ),
    "kick_left": ("Mjlab-BallKickLeft-Flat-MicroDuck", "Mjlab-BallKickLeft-Flat-Backlash-MicroDuck"),
    "kick_right": ("Mjlab-BallKick-Flat-MicroDuck", "Mjlab-BallKick-Flat-Backlash-MicroDuck"),
    "roulade": ("Mjlab-Roulade-Flat-MicroDuck",),
    "walk": (
        "Mjlab-Velocity-Flat-MicroDuck", "Mjlab-Velocity-Flat-Backlash-MicroDuck",
        "Mjlab-Velocity-Rough-MicroDuck", "Mjlab-Velocity-Rough-Backlash-MicroDuck",
    ),
    "stand": (
        "Mjlab-StandUp-Flat-MicroDuck", "Mjlab-StandUp-Flat-Backlash-MicroDuck",
        "Mjlab-StandUp-Rough-MicroDuck", "Mjlab-StandUp-Rough-Backlash-MicroDuck",
    ),
    "roller": ("Mjlab-Velocity-Flat-MicroDuck-Rollers", "Mjlab-Velocity-Flat-Backlash-MicroDuck-Rollers"),
    "crouch": ("Mjlab-RollerCrouch-Flat-MicroDuck", "Mjlab-RollerCrouch-Flat-Backlash-MicroDuck"),
    "swizzle": ("Mjlab-Velocity-Swizzle-MicroDuck", "Mjlab-Velocity-Swizzle-Backlash-MicroDuck"),
    "slope": ("Mjlab-RollerSlope-Flat-MicroDuck", "Mjlab-RollerSlope-Flat-Backlash-MicroDuck"),
    "roller_stand": ("Mjlab-RollerStandUp-Flat-MicroDuck",),
    "spin": ("Mjlab-Spin-Flat-MicroDuck",),
}
ALL_UPSTREAM = tuple(task for tasks in EXPECTED.values() for task in tasks)
INDEPENDENT = tuple(task for role, tasks in EXPECTED.items() if role != "joint" for task in tasks)
SUFFIX = "-Studio-HD1910"
SERVO_NAMES = [
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll",
    "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
]


def test_recipe_descriptors_are_pure_and_match_all_35_reference_variants():
    # run_path also exercises the file without mjlab/torch import side effects.
    path = Path(__file__).parents[1] / "src/mjlab_microduck/tasks/recipe_tasks.py"
    assert path.is_file(), "Pure recipe descriptors have not been implemented"
    descriptors = runpy.run_path(str(path))["RECIPE_TASKS"]
    assert len(descriptors) == len(ALL_UPSTREAM) == 35
    assert len({item.task_id for item in descriptors}) == 35
    assert len({item.experiment_name for item in descriptors}) == 35
    assert {item.upstream_task: item.role for item in descriptors} == {
        task: role for role, tasks in EXPECTED.items() for task in tasks
    }
    for item in descriptors:
        assert item.task_id == item.upstream_task + SUFFIX
        slug = item.upstream_task.removeprefix("Mjlab-").removesuffix("-MicroDuck").lower().replace("-", "_")
        assert item.experiment_name == "microduck_hd1910_" + slug
        assert item.rough == ("-Rough-" in item.upstream_task)
        assert item.backlash == ("-Backlash-" in item.upstream_task)
        assert item.requires_teachers == (item.role == "joint")
    assert sum(not item.requires_teachers for item in descriptors) == 31


@cache
def _model(spec_fn):
    return spec_fn().compile()


@pytest.mark.parametrize("upstream", ALL_UPSTREAM)
@pytest.mark.parametrize("play", [False, True])
def test_new_configs_keep_the_official_model_dr_and_policy_contract(upstream, play):
    import mujoco
    from mjlab.tasks.registry import list_tasks, load_env_cfg, load_rl_cfg
    from mjlab_microduck.actuator.feetech_bam import (
        BacklashEncoderFeetechBamActuatorCfg, FeetechBamActuatorCfg,
    )
    from mjlab_microduck.tasks.microduck_ball_kick_env_cfg import make_microduck_ball_kick_env_cfg

    task = upstream + SUFFIX
    assert task in list_tasks(), f"Missing Studio registration: {task}"
    cfg = load_env_cfg(task, play=play)
    robot = cfg.scene.entities["robot"]
    actuator = robot.articulation.actuators[0]
    assert isinstance(actuator, FeetechBamActuatorCfg)
    assert type(actuator) is (BacklashEncoderFeetechBamActuatorCfg if "-Backlash-" in upstream else FeetechBamActuatorCfg)
    assert actuator.target_names_expr == (r"^(?!passive_).*",)
    assert actuator.kp_fw == 5.0
    assert actuator.vin_range == (7.4, 8.0)
    assert actuator.delay_min_lag == 3 and actuator.delay_max_lag == 6
    assert cfg.decimation * cfg.sim.mujoco.timestep == pytest.approx(0.02)
    assert "expand_bam_friction_fields" in cfg.events
    model = _model(robot.spec_fn)
    assert model.nu == 14
    assert [model.joint(i).name for i in range(model.njnt)
            if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_HINGE
            and not model.joint(i).name.startswith("passive_")] == SERVO_NAMES
    agent = load_rl_cfg(task)
    assert agent.actor.obs_normalization
    assert agent.critic.obs_normalization
    assert agent.logger == "tensorboard"
    assert agent.experiment_name == "microduck_hd1910_" + upstream.removeprefix("Mjlab-").removesuffix("-MicroDuck").lower().replace("-", "_")

    # Left kick is an official factory option, absent from the legacy registry.
    if "BallKickLeft" in upstream:
        if "-Backlash-" in upstream:
            from mjlab_microduck.tasks.backlash import make_backlash_variant
            base = make_backlash_variant(make_microduck_ball_kick_env_cfg(play=play, kick_foot="left"))
        else:
            base = make_microduck_ball_kick_env_cfg(play=play, kick_foot="left")
    else:
        base = load_env_cfg(upstream, play=play)
    original = base.scene.entities["robot"]
    assert robot.spec_fn is original.spec_fn
    assert robot.init_state == original.init_state
    assert robot.collisions == original.collisions
    assert cfg.actions == base.actions
    assert list(cfg.observations["actor"].terms) == list(base.observations["actor"].terms)
    # Standalone Crouch/Spin need the BAM field-expansion declaration. Preserve
    # every original DR/reset event while adding the missing no-op startup hook.
    assert {key: value for key, value in cfg.events.items() if key in base.events} == base.events
    assert set(cfg.events) - set(base.events) <= {"expand_bam_friction_fields"}
    assert cfg.commands == base.commands
    assert cfg.curriculum == base.curriculum
    assert cfg.rewards.keys() == base.rewards.keys()
    for name, term in cfg.rewards.items():
        assert term.func is base.rewards[name].func
        assert term.weight == base.rewards[name].weight
        if upstream != "Mjlab-RollerStandUp-Flat-MicroDuck":
            assert term.params == base.rewards[name].params


def test_new_factory_copies_nested_cfgs_without_mutating_any_legacy_task():
    from mjlab.tasks.registry import load_env_cfg
    from mjlab_microduck.tasks.microduck_studio_env_cfg import make_studio_hd1910_env_cfg
    from mjlab_microduck.tasks.recipe_tasks import RECIPE_TASKS

    for recipe in RECIPE_TASKS:
        cfg = make_studio_hd1910_env_cfg(recipe)
        robot = cfg.scene.entities["robot"]
        robot.init_state.joint_pos[".*hip_yaw.*"] = 99
        robot.articulation.actuators[0].kp_fw = 99
        next(iter(cfg.rewards.values())).weight = 99
        again = make_studio_hd1910_env_cfg(recipe)
        assert again.scene.entities["robot"].articulation.actuators[0].kp_fw == 5
        assert again.scene.entities["robot"].init_state.joint_pos[".*hip_yaw.*"] == 0
        assert next(iter(again.rewards.values())).weight != 99
        if recipe.role != "kick_left":
            original = load_env_cfg(recipe.upstream_task)
            assert original.scene.entities["robot"].articulation.actuators[0].motor_name == "xl330"
            assert original.scene.entities["robot"].articulation.actuators[0].kp_fw == 200
    for task in ("Mjlab-Balance-Flat-MicroDuck-HD1910", "Mjlab-Velocity-Flat-MicroDuck-HD1910", "Mjlab-Velocity-Rough-MicroDuck-HD1910"):
        assert load_env_cfg(task).scene.entities["robot"].articulation.actuators[0].kp_fw == 5


def test_roller_standup_pose_rewards_index_the_servo_view_and_ignore_wheels():
    import torch
    from types import SimpleNamespace
    from mjlab.tasks.registry import load_env_cfg
    from mjlab_microduck.tasks import mdp

    cfg = load_env_cfg("Mjlab-RollerStandUp-Flat-MicroDuck" + SUFFIX)
    expected = [0, 1, 2, 3, 4, 9, 10, 11, 12, 13]
    for name in ("pose_stand_legs", "pose_stand_l1", "standing_composite"):
        assert cfg.rewards[name].params["joint_indices"] == expected
    original = load_env_cfg("Mjlab-RollerStandUp-Flat-MicroDuck")
    assert original.rewards["pose_stand_legs"].params["joint_indices"] == [0, 1, 2, 3, 4, 11, 12, 13, 14, 15]

    # Exercise the real reward using the actual model's interleaved wheel names.
    model = _model(cfg.scene.entities["robot"].spec_fn)
    names = [model.joint(i).name for i in range(1, model.njnt)]
    ids = [i for i, name in enumerate(names) if not name.startswith("passive_")]
    pos = torch.zeros((1, len(names)))
    pos[:, [i for i, name in enumerate(names) if name.startswith("passive_")]] = 12.0
    asset = SimpleNamespace(data=SimpleNamespace(joint_pos=pos, default_joint_pos=torch.zeros_like(pos)), find_joints=lambda pattern: (ids, SERVO_NAMES))
    env = SimpleNamespace(scene={"robot": asset})
    assert mdp.pose_target_match(env, joint_indices=expected).item() == 1.0
    assert mdp.pose_l1_penalty(env, joint_indices=expected).item() == 0.0
    pos[:, ids[13]] = 1.0
    assert mdp.pose_l1_penalty(env, joint_indices=expected).item() == pytest.approx(-0.1)


def test_backlash_feetech_keeps_encoder_feedback_and_goal_reset_behavior(monkeypatch):
    import torch
    from types import SimpleNamespace
    from mjlab.actuator.actuator import ActuatorCmd
    from mjlab_microduck.actuator.feetech_bam import BacklashEncoderFeetechBamActuator
    from mjlab_microduck.actuator.friction_dr_bam import FrictionDRBamActuator

    actuator = object.__new__(BacklashEncoderFeetechBamActuator)
    actuator._backlash_joint_ids = torch.tensor([1, 3])
    actuator._backlash_mask = torch.ones(2)
    cmd = ActuatorCmd(
        pos=torch.tensor([[0.2, 0.3], [0.4, 0.5]]), vel=torch.zeros((2, 2)),
        position_target=torch.zeros((2, 2)), velocity_target=torch.zeros((2, 2)),
        effort_target=torch.zeros((2, 2)),
    )
    monkeypatch.setattr(FrictionDRBamActuator, "get_command", lambda self, data: cmd)
    data = SimpleNamespace(joint_pos=torch.tensor([[0.2, 0.01, 0.3, -0.02], [0.4, 0.03, 0.5, -0.04]]))
    sensed = actuator.get_command(data)
    torch.testing.assert_close(sensed.pos, torch.tensor([[0.21, 0.28], [0.43, 0.46]]))
    actuator._bam_model = SimpleNamespace(actuator=SimpleNamespace(q_target_smooth=torch.ones((2, 2))))
    actuator._goal_reset_pending = torch.tensor([[True], [False]])
    monkeypatch.setattr(FrictionDRBamActuator, "compute", lambda self, command: command.pos)
    actuator.compute(sensed)
    torch.testing.assert_close(actuator._bam_model.actuator.q_target_smooth[0], sensed.pos[0])
    torch.testing.assert_close(actuator._bam_model.actuator.q_target_smooth[1], torch.ones(2))
    assert not actuator._goal_reset_pending.any()
