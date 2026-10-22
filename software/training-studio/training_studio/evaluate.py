"""Bounded GPU evaluation, run by uv inside the existing training project.

Unlike scripts/export.py this actually advances the environment for a finite
number of frames, with VideoRecorder enabled. No viewer loop or policy export.
"""
import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path


def _scalar(value, operation="mean"):
    if hasattr(value, operation):
        value = getattr(value, operation)()
    if hasattr(value, "item"):
        value = value.item()
    return float(value)


def bounded_rollout(env, policy, steps):
    if type(steps) is not int or not 1 <= steps <= 10000:
        raise ValueError("Rollout steps must be an integer between 1 and 10000")
    obs = env.get_observations()
    reward_total, terminated = 0.0, 0
    for _ in range(steps):
        actions = policy(obs)
        obs, reward, dones, _extras = env.step(actions)
        measured = _scalar(reward)
        if not math.isfinite(measured):
            raise RuntimeError("Non-finite evaluation reward")
        reward_total += measured
        terminated += int(_scalar(dones, "sum"))
    return {"steps": steps, "mean_reward": reward_total / steps, "terminated_episodes": terminated}


def main():
    parser = argparse.ArgumentParser(description="Bounded Microduck policy evaluation (CUDA)")
    parser.add_argument("task_id", choices=("Mjlab-Velocity-Flat-MicroDuck-HD1910", "Mjlab-Velocity-Rough-MicroDuck-HD1910"))
    parser.add_argument("--checkpoint-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.steps <= 10000 or not args.checkpoint_file.is_file():
        parser.error("A real checkpoint and a step budget of 1–10000 are required")
    import torch
    import mjlab.tasks  # noqa: F401: populate built-in and entry-point registry
    import mjlab_microduck.tasks  # noqa: F401
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends
    from mjlab.utils.wrappers import VideoRecorder

    if not torch.cuda.is_available():
        raise RuntimeError("Real evaluation requires CUDA")
    configure_torch_backends()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_env_cfg(args.task_id, play=True)
    cfg.scene.num_envs = 1
    cfg.viewer.width, cfg.viewer.height = 960, 540
    agent_cfg = load_rl_cfg(args.task_id)
    env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0", render_mode="rgb_array")
    try:
        env = VideoRecorder(env, video_folder=args.output_dir, step_trigger=lambda step: step == 0,
                            video_length=args.steps, disable_logger=True)
        env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
        runner_cls = load_runner_cls(args.task_id) or MjlabOnPolicyRunner
        runner = runner_cls(env, asdict(agent_cfg), device="cuda:0")
        runner.load(str(args.checkpoint_file.resolve()), map_location="cuda:0")
        policy = runner.get_inference_policy(device="cuda:0")
        with torch.inference_mode():
            summary = bounded_rollout(env, policy, args.steps)
        summary.update(task_id=args.task_id, checkpoint=args.checkpoint_file.name, demo=False,
                       note="Single bounded rollout; this is not hardware validation.")
        (args.output_dir / "evaluation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    main()
