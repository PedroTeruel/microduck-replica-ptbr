"""Opt-in real CUDA check; CPU test runs never allocate a GPU environment."""
import os

import pytest
import torch

from mjlab.envs import ManagerBasedRlEnv
from mjlab.tasks.registry import load_env_cfg
from mjlab_microduck.balance_parameters import apply_balance_parameters
from mjlab_microduck.tasks.mdp import balance_measurements


@pytest.mark.skipif(os.environ.get("MICRODUCK_BALANCE_GPU_TEST") != "1",
                    reason="Explicit MICRODUCK_BALANCE_GPU_TEST=1 required")
def test_balance_real_observations_actions_contacts_and_partial_reset():
    cfg = load_env_cfg("Mjlab-Balance-Flat-MicroDuck-HD1910")
    apply_balance_parameters(cfg, {"support_side": "right", "lift_height_m": .01, "hold_seconds": 1.})
    cfg.scene.num_envs = 4
    env = ManagerBasedRlEnv(cfg, device="cuda:0")
    try:
        obs, _ = env.reset(seed=7)
        assert obs["actor"].shape == (4, 61)
        assert env.action_manager.total_action_dim == 14
        assert env.step_dt == pytest.approx(.02)
        for step in range(30):
            obs, reward, _, _, _ = env.step(torch.zeros(4, 14, device=env.device))
            assert torch.isfinite(obs["actor"]).all()
            assert torch.isfinite(obs["critic"]).all()
            assert torch.isfinite(reward).all()
            measured = balance_measurements(env)
            assert measured["finite"].all()
            assert (env.command_manager.get_term("twist").command[:, 0] == -1.).all()
            if step == 15:
                env.reset(env_ids=torch.tensor([0], device=env.device))
                assert env.command_manager.get_term("twist").elapsed_s[0] == 0.
    finally:
        env.close()
