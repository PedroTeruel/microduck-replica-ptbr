import unittest

from training_studio import evaluate
from training_studio.evaluate import bounded_rollout


class RolloutTests(unittest.TestCase):
    def test_exact_step_budget_and_policy_observation_flow(self):
        class Environment:
            def __init__(self):
                self.steps = 0

            def get_observations(self):
                return 0

            def step(self, actions):
                self.steps += 1
                self.assert_action = actions
                return self.steps, float(self.steps), self.steps % 3 == 0, {}

        env = Environment()
        observations = []

        def policy(obs):
            observations.append(obs)
            return obs + 1

        summary = bounded_rollout(env, policy, 7)
        self.assertEqual(env.steps, 7)
        self.assertEqual(observations, list(range(7)))
        self.assertEqual(summary, {"steps": 7, "mean_reward": 4.0, "terminated_episodes": 2})

    def test_rollout_budget_is_bounded_and_validated(self):
        for steps in (0, -1, 10001, True):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                bounded_rollout(None, None, steps)


class BalanceRolloutTests(unittest.TestCase):
    def test_trials_reset_seeds_and_measure_terminal_state_before_reset(self):
        self.assertTrue(hasattr(evaluate, "balance_rollout"), "Balance evaluation is missing")

        class Environment:
            step_dt = 0.02
            reset_terminated = [False]

            def reset(self, *, seed):
                self.seeds.append(seed)
                self.index = 0

            def get_observations(self):
                return self.index

            def step(self, action):
                self.index += 1
                self.reset_terminated = [self.index == 2]
                return self.index, 1.0, self.index == 2, {}

        env = Environment()
        env.seeds = []
        captures = []

        def summarize(samples, skill):
            captures.append(samples)
            return {"success": False, "failure_reasons": ["fell"], "hold_achieved_s": 0}

        result = evaluate.balance_rollout(
            env, env, lambda obs: obs, skill={"support_side": "right"}, trial_steps=6,
            measure=lambda raw: {"elapsed_s": [raw.index * .02], "finite": [True]},
            summarize=summarize, trials=3, seed=42)
        self.assertEqual(env.seeds, [42, 43, 44])
        self.assertEqual([len(samples) for samples in captures], [2, 2, 2])
        self.assertTrue(all(samples[-1]["terminated"] for samples in captures))
        self.assertEqual(result["steps"], 6)
        self.assertEqual(result["trials"], 3)
        self.assertEqual(result["successes"], 0)
        self.assertEqual(result["success_rate"], 0.0)
        self.assertEqual(result["trial_results"][1]["seed"], 43)
        self.assertEqual(result["skill"], {"support_side": "right"})
        captures.clear()
        env.seeds = []
        evaluate.balance_rollout(env, env, lambda obs: obs, skill={}, trial_steps=6,
                                 measure=lambda raw: {"finite": [True]}, summarize=summarize,
                                 trials=3, seed=2147483647)
        self.assertEqual(env.seeds, [2147483647, 0, 1])

    def test_reject_invalid_budgets_before_touching_environment(self):
        self.assertTrue(hasattr(evaluate, "balance_rollout"), "Balance evaluation is missing")
        for options in ({"trial_steps": 0}, {"trial_steps": True}, {"trial_steps": 10001},
                        {"trials": 0}, {"trials": True}, {"trials": 17}, {"seed": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                kwargs = dict(trial_steps=10, trials=8, seed=42)
                kwargs.update(options)
                evaluate.balance_rollout(None, None, None, skill={}, measure=None, summarize=None, **kwargs)
