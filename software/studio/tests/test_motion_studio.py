"""Web motion recorder: disk validation and actual robotd output, without hardware."""
import copy
import importlib.util
import itertools
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests import test_pad as fixtures
from tests.test_pad import PadTestBase, POLICIES
from studio.pad_combo import Refused


class StorageTest(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("studio.motion_store"), "motion storage is implemented")
        from studio import motion_store
        return motion_store

    def clip(self):
        return {"version": 1, "id": "a" * 32, "name": "小步", "created": "2026-10-25T00:00:00Z",
                "duration_s": 0.5, "fingerprint": "b" * 64,
                "events": [{"t": 0.0, "method": "robot.move", "params": {"vx": .2, "vy": 0., "vyaw": 0.}},
                           {"t": .5, "method": "robot.move", "params": {"vx": 0., "vy": 0., "vyaw": 0.}}]}

    def test_atomic_persistence_and_rejects_untrusted_events(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as td:
            store = m.MotionStore(td)
            clip = self.clip()
            store.save(clip)
            self.assertEqual(m.MotionStore(td).get(clip["id"]), clip)
            store.rename(clip["id"], "转一圈")
            self.assertEqual(m.MotionStore(td).get(clip["id"])["name"], "转一圈")
            store.delete(clip["id"])
            self.assertEqual(m.MotionStore(td).summaries(), [])
            for mutate in (
                lambda c: c.update(extra=True), lambda c: c.update(version=2),
                lambda c: c.update(duration_s=61), lambda c: c.update(duration_s=float("nan")),
                lambda c: c.update(name="x" * 33),
                lambda c: c["events"][0].update(method="robot.init"),
                lambda c: c["events"][0]["params"].update(vx=float("inf")),
                lambda c: c["events"][0]["params"].update(vx=.7),
                lambda c: c["events"][0].update(t=.6),
                lambda c: c["events"][0]["params"].update(arbitrary="path"),
                lambda c: c["events"][0].update(method="robot.sound", params={"tag": []}),
                lambda c: c["events"][0].update(method="robot.pose", params={"active": 0}),
                lambda c: c.update(duration_s=10 ** 400),
                lambda c: c["events"][0].update(t=10 ** 400),
                lambda c: c["events"][0]["params"].update(vx=10 ** 400),
            ):
                bad = self.clip()
                mutate(bad)
                with self.subTest(bad=repr(bad)[:160]), self.assertRaises(Refused):
                    store.save(bad)

    def test_corruption_limits_and_failed_replace_preserve_original(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as td:
            store = m.MotionStore(td)
            clip = self.clip()
            store.save(clip)
            with mock.patch.object(m.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(Refused):
                    store.rename(clip["id"], "new")
            self.assertEqual(store.get(clip["id"])["name"], clip["name"])
            for i in range(1, 20):
                c = self.clip()
                c["id"] = f"{i:032x}"
                store.save(c)
            c = self.clip()
            c["id"] = "f" * 32
            with self.assertRaises(Refused):
                store.save(c)
            folder = Path(td) / "motion-recordings"
            (folder / ("e" * 32 + ".json")).write_text("{" * (1024 * 1024 + 1), encoding="utf8")
            (folder / ("d" * 32 + ".json")).write_text('{"version":NaN}', encoding="utf8")
            reloaded = m.MotionStore(td)
            self.assertEqual(len(reloaded.summaries()), 20)
            self.assertEqual(reloaded.skipped, 2)
            c = self.clip()
            c["events"] *= 3001
            with self.assertRaises(Refused):
                m.validate_clip(c)

    def test_huge_json_integers_are_skipped_on_restart(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as td:
            store = m.MotionStore(td)
            good = self.clip()
            store.save(good)
            folder = Path(td) / "motion-recordings"
            for i, field in enumerate(("duration", "time", "param")):
                bad = self.clip()
                bad["id"] = f"{i:032x}"
                if field == "duration":
                    bad["duration_s"] = 10 ** 400
                elif field == "time":
                    bad["events"][0]["t"] = 10 ** 400
                else:
                    bad["events"][0]["params"]["vx"] = 10 ** 400
                (folder / (bad["id"] + ".json")).write_text(json.dumps(bad), encoding="utf8")
            self.assertEqual(m.MotionStore(td).summaries(), store.summaries())


class MotionStudioTest(PadTestBase):
    feed, sent = fixtures.VpadTest.feed, fixtures.VpadTest.sent

    def setUp(self):
        super().setUp()
        self.feed()
        self.conn = self.ops.new_conn()
        self.seq = itertools.count(100)
        self.ops.handle({"op": "drive", "open": True, "seq": next(self.seq)}, conn=self.conn)

    def motion(self, action, conn=None, **args):
        self.assertIn("motion_studio", self.ops.snapshot(conn=self.conn))
        return self.ops.handle(dict(op="motion", action=action, **args), conn=conn or self.conn, by="电脑 A")

    def view(self):
        snap = self.ops.snapshot(conn=self.conn)
        self.assertIn("motion_studio", snap, "motion studio snapshot is published")
        return snap["motion_studio"]

    def start(self):
        r = self.motion("record_start")
        self.assertIsInstance(r.get("session_id"), str)
        return r["session_id"]

    def move(self, vx=.12):
        return self.ops.handle({"op": "move", "vx": vx, "seq": next(self.seq)}, conn=self.conn)

    def saved(self):
        self.start()
        self.move()
        time.sleep(.05)
        self.motion("record_finish")
        self.motion("save", name="一步")
        return self.view()["recordings"][0]["id"]

    def test_records_clamped_accepted_output_and_cleanup(self):
        token = self.start()
        self.assertEqual(self.view()["state"], "recording")
        self.move(99)
        with self.assertRaises(Refused):
            self.ops.handle({"op": "sound", "tag": "unknown"}, conn=self.conn)
        self.motion("record_finish")
        self.assertEqual(self.view()["state"], "draft")
        self.motion("save", name="直走")
        studio = self.ops.motion_studio
        c = studio.store.get(self.view()["recordings"][0]["id"])
        self.assertEqual(c["events"][0]["params"]["vx"], .3)
        self.assertEqual(c["events"][-1]["method"], "robot.sound")
        self.assertTrue(any(e["method"] == "robot.move" and e["params"] == {"vx": 0., "vy": 0., "vyaw": 0.}
                            for e in c["events"]))
        self.assertFalse(any(e["params"].get("tag") == "unknown" for e in c["events"]))
        self.assertNotEqual(token, self.motion("play", id=c["id"], loops=1)["session_id"])

    def test_unsupported_skill_rejected_before_send_and_recording_keeps_running(self):
        self.start()
        for args in ({"op": "skill", "name": "kick_left"}, {"op": "key", "key": "x"},
                     {"op": "keys", "held": ["x"], "down": ["x"], "seq": next(self.seq)},
                     {"op": "action_start", "id": "kicks"}):
            with self.subTest(args=args), self.assertRaisesRegex(Refused, "技能.*完成"):
                self.ops.handle(args, conn=self.conn)
        self.assertFalse(any(m == "robot.do" for m, _ in self.robot.calls + self.sent()))
        self.assertEqual(self.view()["state"], "recording")

    def test_snapshot_readiness_and_closed_owner(self):
        self.assertTrue(self.view()["record_available"]["ok"])
        c = self.ops.new_conn()
        with self.assertRaises(Refused):
            self.motion("record_start", conn=c)
        self.start()
        c = self.ops.new_conn()
        self.ops.handle({"op": "drive", "open": True}, conn=c)
        for action in ("record_start", "record_pause", "record_finish", "stop", "idle_start"):
            with self.subTest(action=action), self.assertRaises(Refused):
                self.motion(action, conn=c)
        self.assertFalse(self.ops.snapshot(conn=c)["motion_studio"]["owner"]["mine"])

    def test_pause_excludes_wait_and_fences_late_inputs(self):
        self.start()
        self.move()
        self.motion("record_pause")
        elapsed = self.view()["elapsed_s"]
        time.sleep(.10)
        self.assertAlmostEqual(self.view()["elapsed_s"], elapsed, delta=.02)
        with self.assertRaises(Refused):
            self.move()
        self.motion("record_resume")
        self.move(.1)
        self.motion("record_finish")
        self.assertLess(self.view()["draft"]["duration_s"], .16)

    def test_heartbeat_timeout_and_old_token_never_revives(self):
        token = self.start()
        self.move()
        with self.ops._lk:
            self.ops.motion_studio.session["heartbeat"] -= .6
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "draft")
        self.assertTrue(self.motion("heartbeat", session_id=token).get("dropped"))
        self.motion("discard")
        newer = self.start()
        self.assertNotEqual(token, newer)
        with self.ops._lk:
            before = self.ops.motion_studio.session["heartbeat"]
        self.motion("heartbeat", session_id=token)
        self.assertEqual(self.ops.motion_studio.session["heartbeat"], before)
        self.assertIs(self.ops.executor_for({"op": "motion", "action": "heartbeat"}), self.ops._fast_pool)

    def test_pause_stop_manual_takeover_and_disconnect_cleanup(self):
        cid = self.saved()
        token = self.motion("play", id=cid, loops=3)["session_id"]
        self.motion("pause")
        paused_count = len(self.sent())
        self.ops._tick_once()
        self.assertEqual(len(self.sent()), paused_count)
        self.motion("resume")
        self.move(.08)
        self.assertEqual(self.view()["state"], "idle")
        self.assertEqual(self.sent("robot.move")[-1][1]["vx"], .08)
        self.ops.handle({"op": "stop", "seq": next(self.seq)}, conn=self.conn)
        token = self.motion("idle_start")["session_id"]
        self.ops.mark_gone(self.conn)
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "idle")
        self.assertIn(("robot.mouth", {"open": 0.}), self.sent())
        with self.assertRaises(Refused):
            self.motion("heartbeat", session_id=token)

    def test_fingerprint_changes_reject_same_path_new_bytes_and_ignore_telemetry(self):
        path = Path(self.tmp.name) / "walk.onnx"
        path.write_bytes(b"old model")
        pol = copy.deepcopy(POLICIES)
        pol["slots"][0]["path"] = str(path)
        self.feed(pol=pol)
        cid = self.saved()
        self.feed(pol=dict(pol, enabled=True, homed=True, sitting=False, progress=.5))
        self.motion("play", id=cid, loops=1)
        self.motion("stop")
        path.write_bytes(b"new model")
        with self.assertRaisesRegex(Refused, "模型|配置"):
            self.motion("play", id=cid, loops=1)

    def test_lively_expanded_samples_are_recorded_and_stop_on_policy_invalid(self):
        self.motion("idle_start")
        self.start()
        with self.ops._lk:
            lively = self.ops.motion_studio.session["lively"]
            lively.start, lively.previous = None, None
            lively.rng.seed(1)
        for _ in range(4):
            self.ops._tick_once()
            time.sleep(.045)
        self.assertTrue(self.view()["idle_running"])
        self.motion("record_finish")
        self.motion("save", name="灵动")
        c = self.ops.motion_studio.store.get(self.view()["recordings"][0]["id"])
        self.assertTrue(any(e["method"] == "robot.head" and any(e["params"].values()) for e in c["events"]))
        self.assertFalse(any("seed" in e for e in c["events"]))
        self.robot.sent.clear()
        token = self.motion("play", id=c["id"], loops=1)["session_id"]
        fixtures.wait_until(lambda: self.view()["state"] == "idle", timeout=.5)
        replayed = [p for _, p in self.sent("robot.head") if any(p.values())]
        recorded = [e["params"] for e in c["events"] if e["method"] == "robot.head"]
        self.assertTrue(replayed)
        self.assertTrue(all(p in recorded for p in replayed), "playback reuses expanded recorded values")
        self.motion("idle_start")
        self.feed(posture="holding")
        self.ops._tick_once()
        self.assertFalse(self.view()["idle_running"])
        self.assertEqual(self.sent("robot.mouth")[-1][1], {"open": 0.})

    def test_heartbeat_does_not_wait_for_slow_robot_output(self):
        token = self.motion("idle_start")["session_id"]
        entered, release, beat_done = threading.Event(), threading.Event(), threading.Event()
        original = self.robot.notify

        def slow(method, params):
            if method == "robot.head":
                entered.set()
                release.wait(1.)
            return original(method, params)

        with mock.patch.object(self.robot, "notify", side_effect=slow):
            tick = threading.Thread(target=self.ops._tick_once)
            tick.start()
            self.assertTrue(entered.wait(.5))
            beat = threading.Thread(target=lambda: (self.motion("heartbeat", session_id=token), beat_done.set()))
            beat.start()
            try:
                self.assertTrue(beat_done.wait(.15), "heartbeat must not wait behind network output")
            finally:
                release.set()
                tick.join(2.)
                beat.join(2.)

    def test_late_action_sample_cannot_override_pause_cleanup(self):
        self.start()
        entered, release = threading.Event(), threading.Event()
        original = self.ops._notify_quiet

        def delayed(method, params, *args, **kwargs):
            if method == "robot.head" and any(params.values()):
                entered.set()
                release.wait(1.)
            return original(method, params, *args, **kwargs)

        with mock.patch.object(self.ops, "_notify_quiet", side_effect=delayed):
            self.ops.handle({"op": "action_start", "id": "nod"}, conn=self.conn)
            self.assertTrue(entered.wait(.5))
            self.motion("record_pause")
            boundary = len(self.sent("robot.head"))
            release.set()
            fixtures.wait_until(lambda: self.ops._action is None)
        heads = self.sent("robot.head")
        self.assertFalse(any(heads[-1][1].values()), "late worker must not overwrite the neutral head")
        self.assertFalse(any(any(params.values()) for _, params in heads[boundary:]), "no late nonzero frame after pause")

    def test_token_bound_stop_cannot_stop_newer_session(self):
        old = self.motion("idle_start")["session_id"]
        self.motion("stop", session_id=old)
        new = self.motion("idle_start")["session_id"]
        r = self.motion("stop", session_id=old)
        self.assertTrue(r.get("dropped"))
        self.assertEqual(self.view()["session_id"], new)

    def test_lively_can_start_during_recording_without_changing_its_token(self):
        token = self.start()
        self.assertTrue(self.view()["idle_available"]["ok"])
        self.assertEqual(self.motion("idle_start")["session_id"], token)
        self.assertEqual(self.view()["state"], "recording")
        self.assertTrue(self.view()["idle_running"])

    def test_output_failure_is_not_recorded(self):
        self.start()
        self.robot.fail = fixtures.Unreachable("gone")
        with self.assertRaises(Refused):
            self.move()
        self.robot.fail = None
        self.motion("record_finish")
        self.assertEqual(self.view()["state"], "idle")
        self.assertIsNone(self.view()["draft"])

    def test_pause_and_finish_record_actual_head_mouth_and_held_sound_cleanup(self):
        self.start()
        self.ops.handle({"op": "keys", "held": ["lt"], "down": ["lt"], "seq": next(self.seq)}, conn=self.conn)
        self.ops._tick_once()
        self.motion("record_pause")
        s = self.ops.motion_studio.session
        self.assertTrue(any(e["params"] == {"tag": "wheee", "hold": True} for e in s["events"]))
        self.assertTrue(any(e["params"] == {"tag": "wheee", "hold": False} for e in s["events"]))
        self.assertEqual(self.sent("robot.mouth")[-1][1], {"open": 0.})
        self.motion("record_finish")
        self.motion("save", name="张嘴叫")

    def test_recording_limit_and_physical_pad_attach_end_automation(self):
        self.start()
        self.move()
        with self.ops._lk:
            self.ops.motion_studio.session["base"] = 60.
        self.ops._tick_once()
        self.assertEqual(self.view()["draft"]["duration_s"], 60.)
        self.motion("discard")
        self.motion("idle_start")
        self.ops._tap_on = True
        self.tap.running = True
        self.ops.tap_state = "attached"
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "idle")

    def test_replay_coalesces_due_channels_and_runs_only_finite_loops(self):
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)
        clock = [time.monotonic()]
        self.ops.clock = lambda: clock[0]
        token = self.start()
        self.move(.10)
        clock[0] += .04
        self.move(.15)
        clock[0] += .04
        self.move(.20)
        clock[0] += .12
        self.motion("record_finish")
        self.motion("save", name="三步")
        cid = self.view()["recordings"][0]["id"]
        token = self.motion("play", id=cid, loops=3)["session_id"]
        self.robot.sent.clear()
        clock[0] += .09
        self.motion("heartbeat", session_id=token)
        self.ops._tick_once()
        self.assertEqual(self.sent("robot.move"), [("robot.move", {"vx": .2, "vy": 0., "vyaw": 0.})])
        for _ in range(3):
            clock[0] += .21
            self.motion("heartbeat", session_id=token)
            self.ops._tick_once()
        self.assertEqual(self.view()["state"], "idle")
        self.assertEqual(self.view()["last_result"], "回放完成")
        self.assertEqual(self.sent("robot.move")[-1][1]["vx"], 0.)

    def test_disconnected_draft_can_be_discarded_by_reconnected_page(self):
        self.start()
        self.move()
        self.ops.mark_gone(self.conn)
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "draft")
        new = self.ops.new_conn()
        self.ops.handle({"op": "drive", "open": True}, conn=new)
        self.assertTrue(self.ops.snapshot(conn=new)["motion_studio"]["owner"]["mine"])
        self.motion("discard", conn=new)
        self.assertEqual(self.motion("record_start", conn=new).get("session_id"),
                         self.ops.snapshot(conn=new)["motion_studio"]["session_id"])

    def test_save_is_serialized_without_blocking_snapshot(self):
        self.start()
        self.move()
        self.motion("record_finish")
        entered, release, snap_done = threading.Event(), threading.Event(), threading.Event()
        original = self.ops.motion_studio.store._write

        def slow(clip):
            entered.set()
            release.wait(1.)
            original(clip)

        with mock.patch.object(self.ops.motion_studio.store, "_write", side_effect=slow):
            saver = threading.Thread(target=lambda: self.motion("save", name="one"))
            saver.start()
            self.assertTrue(entered.wait(.5))
            reader = threading.Thread(target=lambda: (self.view(), snap_done.set()))
            reader.start()
            try:
                self.assertTrue(snap_done.wait(.15))
                with self.assertRaisesRegex(Refused, "保存|文件|整理"):
                    self.motion("save", name="duplicate")
                with self.assertRaises(Refused):
                    self.motion("discard")
            finally:
                release.set()
                saver.join(2.)
                reader.join(2.)
        self.assertEqual(len(self.view()["recordings"]), 1)

    def test_skill_accepted_before_recording_needs_verified_policy_cycle(self):
        self.ops.handle({"op": "skill", "name": "kick_left"}, conn=self.conn)
        with self.assertRaisesRegex(Refused, "技能.*完成|策略.*重新"):
            self.start()
        # A stop RPC acknowledgement alone is not evidence of physical completion.
        self.ops.handle({"op": "walk_stop"}, conn=self.conn)
        with self.assertRaises(Refused):
            self.start()
        self.feed(posture="holding", pol={"enabled": False})
        self.feed()
        self.start()

    def test_skill_reset_uses_bus_runtime_flag_when_policy_config_stays_enabled(self):
        self.ops.handle({"op": "skill", "name": "kick_left"}, conn=self.conn)
        # The real daemon's robot.policies.enabled is a startup configuration flag.
        # Stopping the runtime does not turn that flag off.
        self.ops.handle({"op": "walk_stop"}, conn=self.conn)
        self.feed(posture="holding")
        stopped = self.view()
        self.assertFalse(stopped["record_available"]["ok"])
        self.assertIn("开始走", stopped["record_available"]["why"])
        self.assertNotIn("先手动停下策略", stopped["record_available"]["why"])
        with self.assertRaises(Refused):
            self.start()
        self.ops.handle({"op": "walk"}, conn=self.conn)
        with self.assertRaises(Refused):
            self.start()  # A successful enable response still needs fresh ready telemetry.
        self.feed()
        self.assertTrue(self.view()["record_available"]["ok"])
        self.assertTrue(self.view()["idle_available"]["ok"])
        self.start()

    def test_policy_config_disabled_does_not_replace_runtime_stop_evidence(self):
        self.ops.handle({"op": "skill", "name": "kick_left"}, conn=self.conn)
        self.feed(pol={"enabled": False})  # bus.policy_enabled is still True
        self.feed()
        with self.assertRaises(Refused):
            self.motion("idle_start")

    def test_body_modes_replay_without_changing_browser_mode(self):
        self.start()
        self.ops.handle({"op": "mode", "mode": "body", "seq": next(self.seq)}, conn=self.conn)
        self.ops.handle({"op": "sticks", "mode": "body", "ly": 1., "rx": 1., "seq": next(self.seq)}, conn=self.conn)
        time.sleep(.05)
        self.motion("record_finish")
        self.motion("save", name="身体")
        clip = self.ops.motion_studio.store.get(self.view()["recordings"][0]["id"])
        poses = [e["params"] for e in clip["events"] if e["method"] == "robot.pose"]
        self.assertIn({"active": False}, poses)
        self.assertTrue(any(p.get("active") is True for p in poses))
        token = self.motion("play", id=clip["id"], loops=1)["session_id"]
        self.assertEqual(self.ops._mode_of(self.conn), "drive")

    def test_old_manual_frame_waiting_before_new_session_is_dropped(self):
        entered, release = threading.Event(), threading.Event()
        original = self.ops._cancel_wait

        def wait(seconds):
            entered.set()
            release.wait(1.)

        self.move(.1)
        with mock.patch.object(self.ops, "_cancel_wait", side_effect=wait):
            worker = threading.Thread(target=self.move)
            worker.start()
            self.assertTrue(entered.wait(.5))
            self.ops.handle({"op": "stop", "seq": next(self.seq)}, conn=self.conn)
            self.start()
            boundary = len(self.sent("robot.move"))
            release.set()
            worker.join(1.)
        self.assertEqual(len(self.sent("robot.move")), boundary)

    def test_expired_lively_session_cannot_be_revived_by_record_start(self):
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)
        self.motion("idle_start")
        with self.ops._lk:
            self.ops.motion_studio.session["heartbeat"] -= .6
        with self.assertRaisesRegex(Refused, "心跳|结束"):
            self.motion("record_start")
        self.assertEqual(self.view()["state"], "idle")

    def test_pause_boundary_uses_one_timestamp_and_resumed_events_stay_ordered(self):
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)
        now = time.monotonic()
        self.ops.clock = lambda: now
        self.start()
        self.move()
        studio = self.ops.motion_studio
        # Emulate a clock ticking forward by microseconds while the boundary is planned.
        samples = iter(.1 + i / 1000000 for i in range(100))
        with mock.patch.object(studio, "elapsed", side_effect=lambda *a: next(samples)):
            self.ops.handle({"op": "motion", "action": "record_pause"}, conn=self.conn)
        times = [e["t"] for e in studio.session["events"][-5:]]
        self.assertEqual(len(set(times)), 1)
        self.assertEqual(studio.session["base"], times[0])
        self.motion("record_resume")
        self.move(.11)
        self.motion("record_finish")
        self.motion("save", name="瞬间继续")
        c = studio.store.get(self.view()["recordings"][0]["id"])
        self.assertEqual([e["t"] for e in c["events"]], sorted(e["t"] for e in c["events"]))

    def test_old_tokenless_resume_cannot_resume_replacement_session(self):
        from studio import motion_studio as module
        cid = self.saved()
        self.motion("play", id=cid, loops=1)
        self.motion("pause")
        entered, release = threading.Event(), threading.Event()
        original = module.fingerprint
        result = []
        worker = None

        def delayed(pad, *args, **kwargs):
            if threading.current_thread() is worker:
                entered.set()
                release.wait(1.)
            return original(pad, *args, **kwargs)

        with mock.patch.object(module, "fingerprint", side_effect=delayed):
            worker = threading.Thread(target=lambda: result.append(self.ops.handle({"op": "motion", "action": "resume"}, conn=self.conn)))
            worker.start()
            self.assertTrue(entered.wait(.5))
            self.motion("stop")
            new = self.motion("play", id=cid, loops=1)["session_id"]
            self.motion("pause")
            release.set()
            worker.join(2.)
        self.assertEqual(self.view()["session_id"], new)
        self.assertEqual(self.view()["state"], "play_paused")
        self.assertTrue(result[0].get("dropped"))

    def test_replay_resume_restores_latches_and_keeps_velocity_neutral(self):
        from studio.motion_studio import fingerprint
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)
        clock = [time.monotonic()]
        self.ops.clock = lambda: clock[0]
        head = {"neck_pitch": 0., "head_pitch": .2, "head_yaw": 0., "head_roll": 0.}
        pose = {"active": True, "z": .005, "roll": .1, "pitch": .1}
        events = [{"t": 0., "method": m, "params": p} for m, p in (
            ("robot.head", head), ("robot.pose", pose), ("robot.mouth", {"open": .6}),
            ("robot.move", {"vx": .2, "vy": 0., "vyaw": 0.}), ("robot.sound", {"tag": "chirp"}))]
        events += [{"t": .4, "method": "robot.head", "params": dict.fromkeys(head, 0.)},
                   {"t": .4, "method": "robot.pose", "params": {"active": False}}]
        clip = {"version": 1, "id": "d" * 32, "name": "latches", "created": "2026-10-25T00:00:00Z",
                "duration_s": .5, "fingerprint": fingerprint(self.ops), "events": events}
        self.ops.motion_studio.store.save(clip)
        self.motion("play", id=clip["id"], loops=1)
        self.ops._tick_once()
        clock[0] += .1
        self.motion("pause")
        self.robot.sent.clear()
        clock[0] += .1
        self.motion("resume")
        self.assertEqual(self.sent("robot.head"), [("robot.head", head)])
        self.assertEqual(self.sent("robot.pose"), [("robot.pose", pose)])
        self.assertEqual(self.sent("robot.mouth"), [("robot.mouth", {"open": .6})])
        self.assertFalse(any(m == "robot.move" and p.get("vx") for m, p in self.sent()))
        self.assertFalse(any(m == "robot.sound" and p.get("tag") == "chirp" for m, p in self.sent()))
        self.motion("heartbeat", session_id=self.view()["session_id"])
        clock[0] += .35
        self.ops._tick_once()
        self.motion("pause")
        self.robot.sent.clear()
        clock[0] += .01
        self.motion("resume")
        self.assertEqual(self.sent("robot.pose"), [("robot.pose", {"active": False})])

    def test_delayed_sound_reply_does_not_enter_new_recording(self):
        self.start()
        self.move()
        entered, release = threading.Event(), threading.Event()

        def slow_sound(params):
            entered.set()
            release.wait(1.)
            return {"accepted": True}

        self.robot.replies["robot.sound"] = slow_sound
        worker = threading.Thread(target=lambda: self.ops.handle({"op": "sound", "tag": "chirp"}, conn=self.conn))
        worker.start()
        self.assertTrue(entered.wait(.5))
        self.motion("record_finish")
        self.motion("save", name="old")
        self.start()
        release.set()
        worker.join(2.)
        self.assertEqual(self.ops.motion_studio.session["events"], [])

    def test_final_loop_dispatches_recent_tail_sound_before_cleanup(self):
        from studio.motion_studio import fingerprint
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)
        clock = [time.monotonic()]
        self.ops.clock = lambda: clock[0]
        c = {"version": 1, "id": "e" * 32, "name": "tail", "created": "2026-10-25T00:00:00Z",
             "duration_s": .2, "fingerprint": fingerprint(self.ops),
             "events": [{"t": .19, "method": "robot.sound", "params": {"tag": "chirp"}},
                        {"t": .2, "method": "robot.move", "params": {"vx": 0., "vy": 0., "vyaw": 0.}}]}
        self.ops.motion_studio.store.save(c)
        self.motion("play", id=c["id"], loops=1)
        self.robot.sent.clear()
        clock[0] += .21
        self.ops._tick_once()
        self.assertEqual(self.sent()[0], ("robot.sound", {"tag": "chirp"}))
        self.assertEqual(self.view()["state"], "idle")
        self.assertEqual(self.sent("robot.mouth")[-1][1], {"open": 0.})

    def test_lost_skill_reply_fences_automation_and_explicit_refusal_does_not(self):
        self.robot.replies["robot.do"] = fixtures.Timeout("reply lost after execution")
        with self.assertRaises(Refused):
            self.ops.handle({"op": "skill", "name": "kick_left"}, conn=self.conn)
        with self.assertRaisesRegex(Refused, "技能.*完成"):
            self.start()
        self.feed(posture="holding", pol={"enabled": False})
        self.feed()
        self.robot.replies["robot.do"] = {"accepted": False, "reason": "policy is not driving"}
        with self.assertRaises(Refused):
            self.ops.handle({"op": "skill", "name": "kick_left"}, conn=self.conn)
        self.start()

    def test_skill_combo_timeout_also_fences_recording(self):
        self.robot.replies["robot.do"] = fixtures.Timeout("reply lost")
        self.ops.handle({"op": "action_start", "id": "kicks"}, conn=self.conn)
        fixtures.wait_until(lambda: self.ops._action is None)
        with self.assertRaisesRegex(Refused, "技能.*完成"):
            self.start()

    def test_corrupt_library_exposes_warning_without_blocking_existing_controls(self):
        from studio.motion_store import MotionStore
        folder = Path(self.ops.state_dir) / "motion-recordings"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ("f" * 32 + ".json")).write_text("{broken", encoding="utf8")
        self.ops.motion_studio.store = MotionStore(self.ops.state_dir)
        self.assertIn("1", self.view()["library_warning"])
        self.assertIn("损坏", self.view()["library_warning"])
        self.move(.1)
        self.assertEqual(self.sent("robot.move")[-1][1]["vx"], .1)

    def stop_background_tick(self):
        self.ops._tick_stop.set()
        self.ops._tick_evt.set()
        self.ops._tick_thread.join(1.)

    def hash_then_change_policy(self, action, **args):
        from studio import motion_studio as module
        original = module.fingerprint

        def changed(pad, *a, **kw):
            result = original(pad, *a, **kw)
            self.feed(pol={"mode": "roller"})
            return result

        with mock.patch.object(module, "fingerprint", side_effect=changed):
            with self.assertRaisesRegex(Refused, "模型|配置"):
                self.motion(action, **args)

    def test_record_start_rejects_policy_changed_during_fingerprint(self):
        self.stop_background_tick()
        self.hash_then_change_policy("record_start")
        self.assertEqual(self.view()["state"], "idle")
        self.assertIsNone(self.ops.motion_studio.session)

    def test_play_rejects_policy_changed_during_fingerprint(self):
        self.stop_background_tick()
        cid = self.saved()
        self.robot.sent.clear()
        self.hash_then_change_policy("play", id=cid, loops=1)
        self.assertEqual(self.view()["state"], "idle")
        self.assertFalse(any(any(p.values()) for _, p in self.sent("robot.head")))

    def test_resume_rejects_policy_changed_during_fingerprint(self):
        self.stop_background_tick()
        cid = self.saved()
        self.motion("play", id=cid, loops=1)
        self.motion("pause")
        self.robot.sent.clear()
        self.hash_then_change_policy("resume")
        self.assertEqual(self.view()["state"], "idle")
        self.assertFalse(any(p.get("vx") for _, p in self.sent("robot.move")))

    def test_record_resume_rejects_policy_changed_during_fingerprint(self):
        self.stop_background_tick()
        self.start()
        self.move()
        self.motion("record_pause")
        self.hash_then_change_policy("record_resume")
        self.assertEqual(self.view()["state"], "draft")

    def test_resumed_output_rechecks_identity_after_state_mutation(self):
        self.stop_background_tick()
        self.start()
        self.ops.handle({"op": "mode", "mode": "head", "seq": next(self.seq)}, conn=self.conn)
        self.ops.handle({"op": "sticks", "mode": "head", "ry": .5, "seq": next(self.seq)}, conn=self.conn)
        time.sleep(.05)
        self.motion("record_finish")
        self.motion("save", name="head")
        cid = self.view()["recordings"][0]["id"]
        self.motion("play", id=cid, loops=1)
        with self.ops._lk:
            self.ops.motion_studio.session["base"] = .01
        self.ops._tick_once()
        self.motion("pause")
        self.robot.sent.clear()
        studio = self.ops.motion_studio
        original = studio._flush_outputs

        def changed():
            self.feed(pol={"mode": "roller"})
            original()

        with mock.patch.object(studio, "_flush_outputs", side_effect=changed):
            self.motion("resume")
        self.assertFalse(any(any(p.values()) for _, p in self.sent("robot.head")))
        self.assertTrue(studio.session is None or studio.session.get("invalid"))

    def test_failed_cleanup_cannot_override_newer_manual_body_output(self):
        self.stop_background_tick()
        self.motion("idle_start")
        self.robot.fail = fixtures.Unreachable("offline")
        self.motion("stop")
        self.assertEqual(len(self.ops.motion_studio._pending_cleanup), 5)
        self.robot.fail = None
        self.ops.handle({"op": "mode", "mode": "body", "seq": next(self.seq)}, conn=self.conn)
        self.ops.handle({"op": "sticks", "mode": "body", "ly": 1., "seq": next(self.seq)}, conn=self.conn)
        self.assertIs(self.sent("robot.pose")[-1][1]["active"], True)
        self.ops._tick_once()
        self.assertIs(self.sent("robot.pose")[-1][1]["active"], True)

    def test_cleanup_retries_are_deduplicated_backed_off_and_survive_recovery(self):
        self.stop_background_tick()
        clock = [time.monotonic()]
        self.ops.clock = lambda: clock[0]
        self.motion("idle_start")
        self.robot.fail = fixtures.Unreachable("offline")
        with mock.patch.object(self.robot, "notify", wraps=self.robot.notify) as output:
            self.motion("stop")
            for _ in range(50):
                clock[0] += .04
                self.ops._tick_once()
            self.assertLessEqual(output.call_count, 15, "offline retry rate must be bounded")
            self.assertEqual(len(self.ops.motion_studio._pending_cleanup), 5)
            self.robot.fail = None
            clock[0] += 8.
            self.ops._tick_once()
        self.assertFalse(self.ops.motion_studio._pending_cleanup)
        self.assertEqual(self.sent("robot.mouth")[-1][1], {"open": 0.})

    def test_passive_mode_reports_keep_lively_replay_and_recording_alive(self):
        self.stop_background_tick()
        cid = self.saved()
        for action in ("idle_start", "play", "record_lively"):
            with self.subTest(action=action):
                self.ops.handle({"op": "mode", "mode": "head", "seq": next(self.seq)}, conn=self.conn)
                if action == "record_lively":
                    self.start()
                    self.motion("idle_start")
                else:
                    self.motion(action, **({"id": cid, "loops": 1} if action == "play" else {}))
                before = self.view()
                self.ops.handle({"op": "mode", "mode": "head", "hb": True}, conn=self.conn)
                self.assertEqual(self.view()["state"], before["state"])
                self.assertEqual(self.view()["session_id"], before["session_id"])
                self.assertEqual(self.ops._mode_of(self.conn), "drive")
                self.ops.handle({"op": "mode", "mode": "drive", "seq": next(self.seq)}, conn=self.conn)
                self.assertEqual(self.view()["state"], before["state"])
                self.motion("stop")
                if self.view()["state"] == "draft":
                    self.motion("discard")

    def test_old_legacy_dispatch_after_preflight_cannot_mutate_new_playback(self):
        self.stop_background_tick()
        cid = self.saved()
        cases = (("_move", {"op": "move", "vx": .2}),
                 ("_sticks", {"op": "sticks", "mode": "drive", "ly": -1.}),
                 ("_stop_move", {"op": "stop"}),
                 ("_keys_op", {"op": "keys", "held": ["lt"], "down": ["lt"]}),
                 ("_mode_op", {"op": "mode", "mode": "head"}),
                 ("_action_start", {"op": "action_start", "id": "nod"}),
                 ("_motion_cmd", {"op": "sound", "tag": "chirp"}))
        for method, args in cases:
            with self.subTest(method=method):
                entered, release = threading.Event(), threading.Event()
                original = getattr(self.ops, method)
                result = []

                def delayed(*a, **kw):
                    entered.set()
                    release.wait(1.)
                    return original(*a, **kw)

                def old_request():
                    try:
                        result.append(self.ops.handle(dict(args, seq=next(self.seq)), conn=self.conn))
                    except Refused as error:
                        result.append({"dropped": str(error)})

                with mock.patch.object(self.ops, method, side_effect=delayed):
                    worker = threading.Thread(target=old_request)
                    worker.start()
                    self.assertTrue(entered.wait(.5))
                    token = self.motion("play", id=cid, loops=1)["session_id"]
                    self.robot.sent.clear()
                    release.set()
                    worker.join(2.)
                try:
                    self.assertEqual(self.view()["state"], "playing")
                    self.assertEqual(self.view()["session_id"], token)
                    self.assertTrue(result[0].get("dropped"))
                    self.assertFalse(self.ops._keys)
                    self.assertIsNone(self.ops._action)
                    self.assertEqual(self.ops._mode_of(self.conn), "drive")
                    self.assertFalse(any(p.get("vx") for _, p in self.sent("robot.move")))
                finally:
                    self.motion("stop")
                    fixtures.wait_until(lambda: self.ops._action is None)

    def test_legacy_request_context_is_cleared_after_errors(self):
        with self.assertRaises(Refused):
            self.ops.handle({"op": "unknown"}, conn=self.conn)
        self.assertIsNone(self.ops.motion_studio._request_local.origin)
        self.move(.1)
        self.assertEqual(self.sent("robot.move")[-1][1]["vx"], .1)

    def test_lively_start_inside_recording_fences_preflighted_manual_control(self):
        self.stop_background_tick()
        token = self.start()
        entered, release = threading.Event(), threading.Event()
        original = self.ops._move
        result = []

        def delayed(*args, **kwargs):
            entered.set()
            release.wait(1.)
            return original(*args, **kwargs)

        with mock.patch.object(self.ops, "_move", side_effect=delayed):
            worker = threading.Thread(target=lambda: result.append(self.move(.2)))
            worker.start()
            self.assertTrue(entered.wait(.5))
            self.assertEqual(self.motion("idle_start")["session_id"], token)
            self.robot.sent.clear()
            release.set()
            worker.join(2.)
        self.assertTrue(result[0].get("dropped"))
        self.assertEqual(self.view()["state"], "recording")
        self.assertTrue(self.view()["idle_running"])
        self.assertFalse(any(p.get("vx") for _, p in self.sent("robot.move")))


if __name__ == "__main__":
    unittest.main()
