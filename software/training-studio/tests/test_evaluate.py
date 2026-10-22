import unittest

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
