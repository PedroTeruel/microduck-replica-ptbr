import unittest
import os
import tempfile
from pathlib import Path

import voice_commands as voice


class ParserTests(unittest.TestCase):
    def test_chinese_command_with_optional_address_and_politeness(self):
        self.assertEqual(voice.parse_command('鸭子，请坐下。', 0.95), 'sit')
        self.assertEqual(voice.parse_command('站 起 来', 0.95), 'stand')
        self.assertEqual(voice.parse_command('起立', 0.95), 'stand')

    def test_negation_quotes_and_long_sentences_are_not_commands(self):
        for text in ['不要坐下', '别站起来', '复读坐下', '他说坐下', '坐下再站起来', '坐下吧然后再说', '你现在不要站起来']:
            self.assertIsNone(voice.parse_command(text, 1.0), text)

    def test_low_confidence_and_nonfinite_results_are_rejected(self):
        for score in [0.1, 0.74, float('nan'), float('inf')]:
            self.assertIsNone(voice.parse_command('坐下', score))


class FakeRobot:
    def __init__(self, sitting=False, enabled=True, torque=True, homed=True):
        self.sitting, self.enabled, self.torque, self.homed = sitting, enabled, torque, homed
        self.calls = []
        self.refuse = None

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if method == 'robot.policies':
            return {'sitting': self.sitting, 'homed': self.homed,
                    'slots': [{'slot': 'sitstand', 'path': '/models/sit-network.onnx'}]}
        if method == 'robot.busStatus':
            return {'phase': 'control', 'mode': 'motion', 'homed': self.homed,
                    'policy_enabled': self.enabled, 'native': {'torque_state_confirmed': self.torque}}
        if method == self.refuse:
            return {'accepted': False, 'reason': 'test refusal'}
        if method == 'robot.do':
            self.sitting = not self.sitting
        elif method == 'robot.enable':
            self.enabled = True
        elif method == 'robot.init':
            self.torque, self.homed = True, True
        return {'accepted': True}

    def mutations(self):
        return [(method, params) for method, params in self.calls
                if method not in ('robot.policies', 'robot.busStatus')]


class MotionTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix','Linux updater motion lease')
    def test_motion_lease_refuses_root_exclusive_even_before_marker_observed(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'motion.lock';lock.touch();marker=Path(tmp)/'installing'
            with lock.open('rb') as root:
                fcntl.flock(root,fcntl.LOCK_EX)
                with self.assertRaises(voice.UpdateLocked):
                    with voice.motion_lease(marker):self.fail('exclusive lease was bypassed')
            with voice.motion_lease(marker):pass

    def test_update_appearing_between_state_and_dispatch_prevents_enable_and_toggle(self):
        blocked=[False]
        class Late(FakeRobot):
            def call(self,method,params=None):
                result=super().call(method,params)
                if method=='robot.stop':blocked[0]=True
                return result
        robot=Late(enabled=False)
        result=voice.PostureCommands(robot,guard=lambda:not blocked[0]).execute('sit')
        self.assertFalse(result['accepted'])
        self.assertNotIn('robot.enable',[method for method,_ in robot.calls])
        self.assertNotIn('robot.do',[method for method,_ in robot.calls])

    def test_sit_from_standing_and_repeated_sit_is_idempotent(self):
        robot = FakeRobot()
        motion = voice.PostureCommands(robot)
        self.assertTrue(motion.execute('sit')['accepted'])
        self.assertTrue(motion.execute('sit')['accepted'])
        self.assertEqual(robot.mutations(), [('robot.do', {'skill': 'sit_toggle'})])

    def test_stand_from_sitting_uses_sit_model_once(self):
        robot = FakeRobot(sitting=True)
        motion = voice.PostureCommands(robot)
        self.assertTrue(motion.execute('stand')['accepted'])
        self.assertTrue(motion.execute('stand')['accepted'])
        self.assertEqual(robot.mutations(), [('robot.do', {'skill': 'sit_toggle'})])

    def test_limp_standing_request_uses_init(self):
        robot = FakeRobot(torque=False, homed=False, enabled=False)
        self.assertTrue(voice.PostureCommands(robot).execute('stand')['accepted'])
        self.assertEqual(robot.mutations(), [('robot.init', {})])

    def test_sit_from_homed_hold_enables_policy_before_sit(self):
        robot = FakeRobot(enabled=False)
        self.assertTrue(voice.PostureCommands(robot).execute('sit')['accepted'])
        self.assertEqual(robot.mutations(), [
            ('robot.stop', {}), ('robot.enable', {'on': True, 'toggle': False}),
            ('robot.do', {'skill': 'sit_toggle'}),
        ])

    def test_unknown_sitting_and_limp_sitting_do_not_move(self):
        for robot in [FakeRobot(sitting=None), FakeRobot(sitting=True, torque=False, enabled=False)]:
            self.assertFalse(voice.PostureCommands(robot).execute('stand')['accepted'])
            self.assertEqual(robot.mutations(), [])

    def test_enable_refusal_prevents_toggle(self):
        robot = FakeRobot(enabled=False)
        robot.refuse = 'robot.enable'
        self.assertFalse(voice.PostureCommands(robot).execute('sit')['accepted'])
        self.assertNotIn(('robot.do', {'skill': 'sit_toggle'}), robot.mutations())

    def test_cancelled_command_does_not_issue_motion(self):
        robot = FakeRobot()
        self.assertFalse(voice.PostureCommands(robot).execute('sit', allowed=lambda: False)['accepted'])
        self.assertEqual(robot.mutations(), [])


if __name__ == '__main__':
    unittest.main()
