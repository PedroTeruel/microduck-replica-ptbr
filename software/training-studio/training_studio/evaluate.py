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


def balance_rollout(env, raw_env, policy, *, skill, trial_steps, measure, summarize, trials=8, seed=42):
    """Measure complete attempts before resets; reward never determines success.

    The raw environment must have auto_reset=False. One continuous recording
    includes every attempt, including failures, in the same order as the report.
    """
    if type(trial_steps) is not int or not 1 <= trial_steps <= 10000:
        raise ValueError("Invalid per-trial step budget")
    if type(trials) is not int or not 1 <= trials <= 16:
        raise ValueError("Invalid trial count")
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Invalid evaluation seed")
    results, total_steps, reward_total = [], 0, 0.0
    for index in range(trials):
        trial_seed = (seed + index) % 2147483648
        raw_env.reset(seed=trial_seed)
        obs = env.get_observations()
        samples = []
        for _ in range(trial_steps):
            obs, reward, dones, _extras = env.step(policy(obs))
            measured = _scalar(reward)
            if not math.isfinite(measured):
                raise RuntimeError("Non-finite evaluation reward")
            values = measure(raw_env)
            sample = {key: value[0].item() if hasattr(value[0], "item") else value[0]
                      for key, value in values.items()}
            sample.update(dt_s=raw_env.step_dt, terminated=bool(raw_env.reset_terminated[0]))
            samples.append(sample)
            reward_total += measured
            total_steps += 1
            if _scalar(dones, "sum"):
                break
        result = summarize(samples, skill)
        result.update(trial=index + 1, seed=trial_seed, steps=len(samples))
        results.append(result)
    successes = sum(bool(item["success"]) for item in results)
    return {"steps": total_steps, "mean_reward": reward_total / total_steps, "trials": trials,
            "successes": successes, "success_rate": successes / trials, "skill": dict(skill),
            "trial_results": results, "seed": seed}


def main():
    parser = argparse.ArgumentParser(description="Bounded Microduck policy evaluation (CUDA)")
    balance_task = "Mjlab-Balance-Flat-MicroDuck-HD1910"
    parser.add_argument("task_id", choices=("Mjlab-Velocity-Flat-MicroDuck-HD1910", "Mjlab-Velocity-Rough-MicroDuck-HD1910", balance_task))
    parser.add_argument("--checkpoint-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=250)
    parser.add_argument("--balance-config", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if not 1 <= args.steps <= 10000 or not args.checkpoint_file.is_file():
        parser.error("A real checkpoint and a step budget of 1–10000 are required")
    if (args.task_id == balance_task) != (args.balance_config is not None):
        parser.error("Balance evaluation requires its saved skill configuration")
    if not 0 <= args.seed <= 2147483647:
        parser.error("Seed is outside the supported range")
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
    # Actuators sample voltage/resistance when the environment is constructed.
    # Seeding only the later trial resets cannot reproduce that initial physics.
    cfg.seed = args.seed
    cfg.scene.num_envs = 1
    cfg.viewer.width, cfg.viewer.height = 960, 540
    skill = None
    if args.balance_config is not None:
        from mjlab_microduck.balance_parameters import (
            apply_balance_parameters, balance_cycle_seconds, aggregate_balance_trial,
            balance_command_contract, validate_balance_parameters,
        )
        from mjlab_microduck.tasks.mdp import balance_measurements
        skill = validate_balance_parameters(json.loads(args.balance_config.read_text(encoding="utf-8")))
        apply_balance_parameters(cfg, skill)
        cfg.auto_reset = False
        # The inherited 3 m walking camera makes this 30 cm robot too small to
        # inspect foot clearance. Follow its trunk from a close three-quarter view.
        cfg.viewer.distance = .7
        cfg.viewer.lookat = (0., 0., .05)
        cfg.viewer.elevation = -15.
        cfg.viewer.azimuth = 135.
    agent_cfg = load_rl_cfg(args.task_id)
    env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0", render_mode="rgb_array")
    try:
        raw_env = env
        trial_steps = math.ceil(balance_cycle_seconds(skill) / raw_env.step_dt) + 2 if skill else 0
        video_steps = trial_steps * 8 if skill else args.steps
        env = VideoRecorder(env, video_folder=args.output_dir, step_trigger=lambda step: step == 0,
                            video_length=video_steps, disable_logger=True)
        env = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
        runner_cls = load_runner_cls(args.task_id) or MjlabOnPolicyRunner
        runner = runner_cls(env, asdict(agent_cfg), device="cuda:0")
        runner.load(str(args.checkpoint_file.resolve()), map_location="cuda:0")
        policy = runner.get_inference_policy(device="cuda:0")
        with torch.inference_mode():
            if skill:
                summary = balance_rollout(env, raw_env, policy, skill=skill, trial_steps=trial_steps,
                                          measure=balance_measurements, summarize=aggregate_balance_trial,
                                          seed=args.seed)
                summary.update(command_contract=balance_command_contract(skill),
                               evaluation_camera={"distance_m": cfg.viewer.distance,
                                                  "lookat_offset_m": list(cfg.viewer.lookat),
                                                  "elevation_deg": cfg.viewer.elevation,
                                                  "azimuth_deg": cfg.viewer.azimuth},
                               note="Eight seeded complete-cycle attempts; success requires hold and return. Simulation only, not hardware validation.")
            else:
                summary = bounded_rollout(env, policy, args.steps)
                summary["note"] = "Single bounded rollout; this is not hardware validation."
        summary.update(task_id=args.task_id, checkpoint=args.checkpoint_file.name, demo=False,
                       evaluation_seed=summary.get("seed", args.seed), startup_seed=args.seed)
        (args.output_dir / "evaluation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary), flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    main()
