import pytest
import torch
import tyro
import mjlab
from mjlab.scripts.train import TrainConfig
from mjlab.tasks.registry import load_env_cfg, load_rl_cfg
from mjlab_microduck.tasks import mdp


TASK = "Mjlab-Balance-Flat-MicroDuck-HD1910"


def test_balance_retains_hd1910_contract_without_velocity_curricula():
    cfg = load_env_cfg(TASK)
    base = load_env_cfg("Mjlab-Velocity-Flat-MicroDuck-HD1910")
    assert list(cfg.observations["actor"].terms) == list(base.observations["actor"].terms)
    assert cfg.actions == base.actions
    assert cfg.decimation * cfg.sim.mujoco.timestep == pytest.approx(.02)
    assert cfg.scene.entities["robot"].articulation.actuators == base.scene.entities["robot"].articulation.actuators
    assert cfg.episode_length_s >= 8.5
    assert cfg.auto_reset
    assert "expand_bam_friction_fields" in cfg.events
    assert "nan_state" in cfg.terminations
    assert "balance_cycle_complete" in cfg.terminations
    assert "balance_nonfoot_contact" in cfg.terminations
    assert "nonfoot_ground_contact" in {sensor.name for sensor in cfg.scene.sensors}
    assert "standing_envs" not in cfg.curriculum
    assert "head_pose_range" not in cfg.curriculum
    assert "push_robot" not in cfg.events
    assert "track_linear_velocity" not in cfg.rewards
    assert "air_time" not in cfg.rewards
    assert load_rl_cfg(TASK).experiment_name == "microduck_hd1910_balance"
    cfg.commands["twist"].support_side = "right"
    assert load_env_cfg(TASK).commands["twist"].support_side == "left"
    assert base.commands["twist"].ranges.lin_vel_x == (-.4, .4)


def test_three_cli_parameters_are_actual_typed_training_inputs():
    parsed = tyro.cli(TrainConfig, default=TrainConfig.from_task(TASK),
                      args=["--env.commands.twist.support-side", "right",
                            "--env.commands.twist.lift-height-m", ".015",
                            "--env.commands.twist.hold-seconds", "5"],
                      config=mjlab.TYRO_FLAGS)
    cmd = parsed.env.commands["twist"]
    assert (cmd.support_side, cmd.lift_height_m, cmd.hold_seconds) == ("right", .015, 5.)


def test_saved_skill_reapplies_to_play_and_rejects_velocity_task():
    from mjlab_microduck.balance_parameters import apply_balance_parameters, balance_command_contract
    skill = {"support_side": "right", "lift_height_m": .02, "hold_seconds": 5.}
    cfg = load_env_cfg(TASK, play=True)
    applied = apply_balance_parameters(cfg, skill)
    assert applied == skill
    command = cfg.commands["twist"]
    assert {name: getattr(command, name) for name in skill} == skill
    assert balance_command_contract(applied)["cycle_seconds"] == 8.5
    assert cfg.episode_length_s >= 8.5
    with pytest.raises(ValueError, match="registered balance task"):
        apply_balance_parameters(load_env_cfg("Mjlab-Velocity-Flat-MicroDuck-HD1910"), skill)


def test_phase_command_full_cycle_and_partial_reset():
    from types import SimpleNamespace
    env = SimpleNamespace(num_envs=2, device="cpu", episode_length_buf=torch.zeros(2))
    cmd = mdp.BalanceCommandCfg(resampling_time_range=(1e9, 1e9), hold_seconds=1.).build(env)
    cmd.reset(torch.tensor([0, 1]))
    cmd.compute(0.)
    assert torch.equal(cmd.command[:, 0], torch.ones(2))
    env.episode_length_buf[:] = 1
    cmd.compute(1.5)
    assert torch.allclose(cmd.command[:, 1], torch.full((2,), .005))
    assert torch.equal(cmd.phase, torch.ones(2, dtype=torch.long))
    cmd.compute(.5)
    assert torch.equal(cmd.phase, torch.full((2,), 2, dtype=torch.long))
    cmd.reset(torch.tensor([0]))
    assert cmd.elapsed_s[0] == 0 and cmd.elapsed_s[1] == 2
    cmd.compute(2.5)
    assert cmd.phase[1] == 3
    assert cmd.command[1, 1] == 0


def test_reward_rejects_wrong_foot_and_nan(monkeypatch):
    rows = dict(target_clearance_m=torch.tensor([.01]*4), swing_clearance_m=torch.tensor([.01]*4),
                support_contact=torch.tensor([True, False, True, True]),
                swing_contact=torch.tensor([False, False, True, False]),
                support_force_n=torch.tensor([7.]*4), finite=torch.tensor([True, True, True, False]),
                nonfoot_contact=torch.zeros(4, dtype=torch.bool),
                tilt_rad=torch.zeros(4), com_margin_m=torch.tensor([.01]*4),
                root_speed_mps=torch.zeros(4), support_speed_mps=torch.zeros(4),
                phase=torch.tensor([2]*4))
    monkeypatch.setattr(mdp, "balance_measurements", lambda env: rows)
    result = mdp.balance_hold_reward(None)
    assert result[0] > 0
    assert torch.equal(result[1:], torch.zeros(3))
    assert torch.isfinite(result).all()
