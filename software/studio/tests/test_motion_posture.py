"""Evidence-driven sit/stand barriers; no hardware or elapsed-time guessing."""
import copy
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import time
from unittest import mock
import unittest

from studio.pad_combo import Refused


def sample(at=10., phase="walk", sitting=False, error=0.):
    return {"present": True, "paused": None, "state_at": at, "policies_at": at, "bus_at": at,
            "bus": {"policy_enabled": True, "homed": True, "native": {"torque_state_confirmed": True}},
            "state": {"policy": phase, "joints": [error] * 15, "targets": [0.] * 15},
            "policies": {"sitting": sitting}}


class PostureTest(unittest.TestCase):
    def tracker(self):
        self.assertIsNotNone(importlib.util.find_spec("studio.motion_posture"), "posture tracker is implemented")
        from studio.motion_posture import PostureTracker
        return PostureTracker()

    def test_onset_flag_homed_and_repeated_samples_do_not_complete_sit(self):
        p = self.tracker()
        token = p.begin("sit", sample(), 10.)
        p.accepted(token)
        for at in (10.1, 10.2, 10.3):
            p.feed(sample(at, "sit", True, .3), at)
        self.assertTrue(p.pending)
        for _ in range(5):
            p.feed(sample(10.4, "sit", True), 10.4)
        self.assertTrue(p.pending, "one cached frame is not consecutive evidence")
        for at in (10.5, 10.6, 10.7):
            p.feed(sample(at, "sit", True), at)
        self.assertFalse(p.pending)

    def test_rise_requires_new_walk_or_stand_phase_and_convergence(self):
        p = self.tracker()
        token = p.begin("stand", sample(10., "sit", True), 10.)
        p.accepted(token)
        for at in (10.1, 10.2, 10.3, 10.4):
            p.feed(sample(at, "rise", False), at)
        self.assertTrue(p.pending)
        p.feed(sample(9.9, "walk", False), 10.4)
        self.assertTrue(p.pending)
        for at in (10.5, 10.6, 10.7):
            p.feed(sample(at, "walk", False), at)
        self.assertFalse(p.pending)

    def test_stale_missing_and_uncertain_source_never_toggle(self):
        for view in (sample(1.), sample(10., "rise"), sample(10., "kick"),
                     dict(sample(), state={"policy": "walk"})):
            with self.subTest(view=view), self.assertRaises(Refused):
                self.tracker().begin("sit", view, 10.)
        p = self.tracker()
        self.assertFalse(p.begin("stand", sample(), 10.)["command"], "already at target is a no-op")

    def test_already_target_does_not_toggle_but_still_needs_three_new_stable_samples(self):
        p = self.tracker()
        token = p.begin("sit", sample(10., "sit", True), 10.)
        self.assertIsNotNone(token, "a single source frame cannot verify settled posture")
        self.assertFalse(token["command"])
        p.accepted(token)
        for at in (10.1, 10.2):
            p.feed(sample(at, "sit", True), at)
        self.assertTrue(p.pending)
        p.feed(sample(10.3, "sit", True), 10.3)
        self.assertFalse(p.pending)

    def test_timeout_and_lost_reply_stay_fenced_until_verified_or_manual_reset(self):
        p = self.tracker()
        token = p.begin("sit", sample(), 10.)
        p.uncertain(token, "回执丢失")
        self.assertTrue(p.pending)
        self.assertIn("回执", p.error)
        self.assertTrue(p.check_timeout(40.))
        self.assertTrue(p.pending)
        with self.assertRaises(Refused):
            p.begin("stand", sample(40., "sit", True), 40.)
        for at in (40.1, 40.2, 40.3):
            p.feed(sample(at, "sit", True), at)
        self.assertFalse(p.pending)
        old = token
        token = p.begin("stand", sample(40.3, "sit", True), 40.3)
        p.rejected(old)
        self.assertTrue(p.pending, "late previous reply cannot clear the new transition")
        p.rejected(token)
        self.assertFalse(p.pending)

    def test_manual_reset_needs_fresh_disabled_then_ready_cycle(self):
        p = self.tracker()
        p.begin("sit", sample(), 10.)
        off = dict(sample(11.), bus={"policy_enabled": False}, bus_at=11.)
        p.feed(off, 11.)
        on = dict(sample(12.), bus={"policy_enabled": True, "homed": True,
                                    "native": {"torque_state_confirmed": True}}, bus_at=12.)
        p.feed(on, 12.)
        self.assertFalse(p.pending)

    def test_delayed_ack_requires_three_new_distinct_samples(self):
        p = self.tracker()
        token = p.begin("sit", sample(), 10.)
        for at in (10.1, 10.2, 10.3):
            p.feed(sample(at, "sit", True), at)
        self.assertTrue(p.pending)
        p.accepted(token)
        p.feed(sample(10.4, "sit", True), 10.4)
        self.assertTrue(p.pending, "pre-reply samples cannot release a newly accepted barrier")
        p.feed(sample(10.5, "sit", True), 10.5)
        self.assertTrue(p.pending)
        p.feed(sample(10.6, "sit", True), 10.6)
        self.assertFalse(p.pending)

    def test_absent_paused_stale_bus_and_torque_off_never_resolve_completion(self):
        for changes in ({"present": False}, {"paused": True}, {"bus_at": 1.},
                        {"bus": {"policy_enabled": True, "native": {"torque_state_confirmed": False}}}):
            p = self.tracker()
            token = p.begin("sit", sample(), 10.)
            p.accepted(token)
            for at in (10.1, 10.2, 10.3, 10.4):
                p.feed(dict(sample(at, "sit", True), **changes), at)
            with self.subTest(changes=changes):
                self.assertTrue(p.pending)


class FakePostureTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_robot_port_stream_and_heartbeat_complete_sit_then_stand(self):
        from dev.fake_robotd import FakeRobotd
        from tests.test_pad import FakeConfigd, FakeHelper
        from studio.log import Log
        from studio.pad import PadOps, RobotPort, robot_view
        from studio.robotd import Robotd
        from studio.motion_studio import fingerprint
        fixture = str(Path(__file__).parent / "fixtures" / "now-20261018.jsonl")
        fake = FakeRobotd(fixture, posture="policy")
        server, port = await fake.serve_tcp()
        addr = f"tcp:127.0.0.1:{port}"
        with tempfile.TemporaryDirectory() as folder:
            log = Log(Path(folder) / "logs", echo=False, background=False)
            rd = Robotd(addr, addr, log)
            robot = RobotPort(addr)
            ops = PadOps(log, configd=FakeConfigd(), robot=robot, helper=FakeHelper(),
                         state_dir=folder, read_text=lambda _: "", exists=lambda _: False)
            rd.start()
            rd.set_viewers(1)
            try:
                for _ in range(150):
                    ops.feed_robot(robot_view(rd))
                    if rd.state.value and rd.policies.value and ops._pose_reset == "done":
                        break
                    await asyncio.sleep(.02)
                self.assertTrue(rd.state.value)
                conn = ops.new_conn()
                await asyncio.to_thread(ops.handle, {"op": "drive", "open": True, "seq": 1}, conn=conn)
                cid = "e" * 32
                ops.motion_studio.store.save({"version": 2, "id": cid, "name": "坐站", "created": "2026-10-25",
                    "duration_s": .2, "fingerprint": fingerprint(ops), "events": [
                        {"t": 0., "method": "studio.posture", "params": {"target": "sit"}},
                        {"t": .1, "method": "studio.posture", "params": {"target": "stand"}}]})
                result = await asyncio.to_thread(ops.handle, {"op": "motion", "action": "play", "id": cid}, conn=conn)
                deadline = time.monotonic() + 9.
                snapshots = 0
                while time.monotonic() < deadline:
                    ops.feed_robot(robot_view(rd))
                    ops.handle({"op": "motion", "action": "heartbeat", "session_id": result["session_id"]}, conn=conn)
                    view = ops.snapshot(conn=conn)["motion_studio"]
                    snapshots += 1
                    if view["state"] == "idle":
                        break
                    await asyncio.sleep(.05)
                self.assertEqual(view["last_result"], "回放完成", view)
                self.assertGreater(snapshots, 10)
                self.assertEqual(sum(m == "robot.do" for _, m in fake.calls), 2)
            finally:
                await asyncio.to_thread(ops.close)
                robot._close()
                await rd.stop()
                server.close()
                await server.wait_closed()

    async def test_fake_models_immediate_flags_phase_and_delayed_convergence(self):
        from dev.fake_robotd import FakeRobotd
        f = FakeRobotd(str(Path(__file__).parent / "fixtures" / "now-20261018.jsonl"), posture="policy")
        await f.dispatch("fake.set", {"posture_delay_s": .8})
        result, _ = await f.dispatch("robot.do", {"skill": "sit_toggle"})
        self.assertTrue(result["accepted"])
        pol, _ = await f.dispatch("robot.policies", {})
        self.assertTrue(pol["sitting"], "flag changes at onset, before actual joints arrive")
        self.assertEqual(f.posture_frame(f.frames[0])["policy"], "sit")
        self.assertNotEqual(f.posture_frame(f.frames[0])["joints"], f.posture_frame(f.frames[0])["targets"])
        with mock.patch("dev.fake_robotd.time.monotonic", return_value=f._posture_transition["start"] + 1.):
            frame = f.posture_frame(f.frames[0])
            self.assertEqual(frame["joints"], frame["targets"])
            result, _ = await f.dispatch("robot.do", {"skill": "sit_toggle"})
            self.assertTrue(result["accepted"])
            self.assertEqual(f.posture_frame(f.frames[0])["policy"], "rise")
            pol, _ = await f.dispatch("robot.policies", {})
            self.assertFalse(pol["sitting"])
            refused, _ = await f.dispatch("robot.do", {"skill": "sit_toggle"})
            self.assertFalse(refused["accepted"])
        with mock.patch("dev.fake_robotd.time.monotonic", return_value=f._posture_transition["start"] + 2.):
            self.assertIn(f.posture_frame(f.frames[0])["policy"], ("walk", "stand"))


if __name__ == "__main__":
    unittest.main()
