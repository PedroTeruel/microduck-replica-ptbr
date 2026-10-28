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
                lambda c: c.update(extra=True), lambda c: c.update(version=3),
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

    def test_v2_posture_targets_are_strict_and_v1_remains_readable(self):
        m = self.module()
        c = self.clip()
        m.validate_clip(c)
        c.update(version=2, events=[{"t": 0., "method": "studio.posture", "params": {"target": "sit"}}])
        self.assertEqual(m.validate_clip(c), c)
        for params in ({"target": "init"}, {"target": True}, {"target": "sit", "skill": "kick"}, {}):
            c["events"][0]["params"] = params
            with self.subTest(params=params), self.assertRaises(Refused):
                m.validate_clip(c)
        c["events"][0]["params"] = {"target": "sit"}
        c["version"] = 1
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

    def test_music_generator_uses_existing_lease_and_cleans_on_source_off(self):
        self.music_telemetry(self.ops.clock())
        now = time.monotonic()
        source = {"available": True, "listening": True, "music": True,
                  "rhythm": {"bpm": 120., "confidence": .9, "feel": "lively", "last_beat": now, "age": .01}}
        class Audio:
            def snapshot(self):
                return copy.deepcopy(source)
            def close(self):
                pass
        self.ops.audio = Audio()
        self.motion("idle_start", kind="music")
        self.assertEqual(self.view()["idle_kind"], "music")
        self.ops._tick_once()
        self.assertTrue(any(m == "robot.pose" and p.get("active") is True for m,p in self.sent()))
        source["listening"] = False
        self.ops._tick_once()
        self.assertTrue(any(m == "robot.pose" and p == {"active":False} for m,p in self.sent()))
        self.move(.1)
        self.assertEqual(self.view()["state"], "idle")
        self.assertFalse(any(m in ("robot.init", "robot.enable") for m,p in self.robot.calls))

    def music_source(self):
        self.music_telemetry(self.ops.clock())
        source = {"available": True, "listening": True, "music": True, "error": None,
                  "rhythm": {"bpm": 120., "confidence": .9, "feel": "lively",
                             "last_beat": self.ops.clock(), "age": .01}}
        class Audio:
            def snapshot(self):
                return copy.deepcopy(source)
            def close(self):
                pass
        self.ops.audio = Audio()
        return source

    def test_update_guard_fences_motion_queued_before_journal_and_keeps_neutralization(self):
        self.stop_background_tick()
        blocked=[False];self.ops.update_guard=lambda:blocked[0]
        self.music_source();self.motion('idle_start',kind='music')
        studio=self.ops.motion_studio
        original=self.robot.notify
        def late(method,params):
            original(method,params)
            if method=='robot.pose' and params.get('active') is True:blocked[0]=True
        with mock.patch.object(self.robot,'notify',side_effect=late):self.ops._tick_once()
        self.assertTrue(blocked[0])
        sent=self.sent()
        self.assertEqual(sum(method=='robot.pose' and params.get('active') is True for method,params in sent),1)
        self.assertFalse(any(method=='robot.head' and any(params.values()) for method,params in sent),sent)
        self.ops._tick_once()
        self.assertIsNone(studio.session)
        self.assertTrue(any(method=='robot.pose' and params=={'active':False} for method,params in self.sent()))
        for args in ({'op':'motion','action':'record_start'},{'op':'audio','listening':True},
                     {'op':'skill','name':'roulade'}):
            with self.assertRaises(Refused):self.ops.handle(args,conn=self.conn)
        self.assertFalse(self.ops._notify_output('robot.head',{'head_pitch':.5}))
        self.ops._call_rpc('停止','robot.stop',{},'test')
        with self.assertRaises(Refused):self.ops._call_rpc('旧线程','robot.init',{},'test')
        self.ops._tick_evt.clear();self.ops._tick_once()
        self.assertFalse(self.ops._tick_evt.is_set(),'idle persistent guard must not spin the tick thread')

    def music_telemetry(self, now):
        self.feed(state={"policy": "walk"}, state_at=now, policies_at=now, bus_at=now,
                  pad_status={"driver": "active", "pads": []}, pad_status_at=now)

    def test_background_music_survives_inactive_over_ten_seconds_without_heartbeat(self):
        self.stop_background_tick()
        now = [self.ops.clock()]
        self.ops.clock = lambda: now[0]
        source = self.music_source()
        self.music_telemetry(now[0])
        token = self.motion("idle_start", kind="music")["session_id"]
        self.ops.handle({"op": "drive", "on": False, "seq": next(self.seq)}, conn=self.conn)
        for delay in (.6, 11., 25.):
            now[0] += delay
            self.music_telemetry(now[0])
            source["rhythm"].update(last_beat=now[0], age=.01)
            with self.robot.lk:
                self.robot.sent.clear()
            self.ops._tick_once()
            self.assertEqual(self.view()["session_id"], token)
            self.assertEqual(self.view()["idle_phase"], "moving")
            self.assertTrue(self.sent("robot.pose")[-1][1]["active"])
        # A returning page sees the actual lease, and can stop with its old token.
        self.ops.handle({"op": "drive", "open": True, "seq": next(self.seq)}, conn=self.conn)
        self.assertTrue(self.view()["owner"]["mine"])
        self.motion("stop", session_id=token)
        self.assertEqual(self.view()["state"], "idle")

    def test_background_music_still_rejects_start_outside_foreground_drive_area(self):
        self.stop_background_tick()
        self.music_source()
        self.music_telemetry(self.ops.clock())
        self.ops.handle({"op": "drive", "on": False, "seq": next(self.seq)}, conn=self.conn)
        with self.assertRaises(Refused):
            self.motion("idle_start", kind="music")

    def test_explicit_stop_fences_music_start_still_hashing_without_a_session(self):
        from studio import motion_studio as module
        self.stop_background_tick()
        self.music_source()
        entered, release = threading.Event(), threading.Event()
        original, result = module.fingerprint, []
        def delayed(*args, **kwargs):
            entered.set()
            release.wait(1.)
            return original(*args, **kwargs)
        with mock.patch.object(module, "fingerprint", side_effect=delayed):
            worker = threading.Thread(target=lambda: result.append(self.motion("idle_start", kind="music")))
            worker.start()
            self.assertTrue(entered.wait(.5))
            self.motion("stop")
            release.set()
            worker.join(2.)
        self.assertTrue(result[0].get("dropped"))
        self.assertIsNone(self.ops.motion_studio.session)

    def test_background_music_rechecks_safety_between_queued_outputs(self):
        self.stop_background_tick()
        self.music_source()
        self.motion("idle_start", kind="music")
        with self.robot.lk:
            self.robot.sent.clear()
        original = self.robot.notify
        def stale_after_head(method, params):
            original(method, params)
            if method == "robot.head":
                self.ops._robot["state_at"] -= 2.
        with mock.patch.object(self.robot, "notify", side_effect=stale_after_head):
            self.ops._tick_once()
        self.assertFalse(any(params.get("active") for _, params in self.sent("robot.pose")))
        self.ops._tick_once()
        self.assertIsNone(self.ops.motion_studio.session)
        self.assertEqual(self.sent("robot.pose"), [("robot.pose", {"active": False})])

    def test_background_music_rechecks_source_shutdown_between_queued_outputs(self):
        self.stop_background_tick()
        source = self.music_source()
        self.motion("idle_start", kind="music")
        with self.robot.lk:
            self.robot.sent.clear()
        original = self.robot.notify
        def source_off_after_head(method, params):
            original(method, params)
            if method == "robot.head":
                source["listening"] = False
        with mock.patch.object(self.robot, "notify", side_effect=source_off_after_head):
            self.ops._tick_once()
        self.assertFalse(any(params.get("active") for _, params in self.sent("robot.pose")))
        self.ops._tick_once()
        self.assertIsNone(self.ops.motion_studio.session)
        self.assertEqual(self.sent("robot.pose"), [("robot.pose", {"active": False})])

    def test_only_standalone_music_ignores_action_heartbeat_expiry(self):
        self.stop_background_tick()
        self.music_source()
        for mode in ("lively", "recording", "recording_music", "playback"):
            with self.subTest(mode=mode):
                self.motion("stop")
                if self.view()["state"] == "draft":
                    self.motion("discard")
                self.feed()
                if mode == "lively":
                    self.motion("idle_start")
                elif mode == "playback":
                    clip = self.saved()
                    self.motion("play", id=clip)
                else:
                    self.start()
                    if mode == "recording_music":
                        self.motion("idle_start", kind="music")
                self.ops.motion_studio.session["heartbeat"] -= 11.
                self.ops._tick_once()
                self.assertIsNone(self.ops.motion_studio.session)

    def test_background_music_safety_stops_once_and_never_reclaims_after_takeover(self):
        from studio.motion_store import CLEANUP
        self.stop_background_tick()
        mutations = ("disconnect", "takeover", "manual", "pad", "pad_unreadable", "pad_stale",
                     "state_stale", "state_invalid", "bus_stale", "estop", "policy", "model", "config")
        for reason in mutations:
            with self.subTest(reason=reason):
                self.ops._gone.pop(self.conn, None)
                self.motion("stop")
                self.ops._closed.pop(self.conn, None)
                self.ops._driver = None
                self.ops._web_driving = False
                self.ops._seqs.pop(self.conn, None)
                self.ops._status_error = None
                source = self.music_source()
                self.music_telemetry(self.ops.clock())
                self.ops.handle({"op": "drive", "open": True}, conn=self.conn)
                token = self.motion("idle_start", kind="music")["session_id"]
                self.ops._tick_once()
                self.ops.handle({"op": "drive", "on": False}, conn=self.conn)
                self.assertEqual(self.view()["session_id"], token)
                with self.robot.lk:
                    self.robot.sent.clear()
                if reason == "disconnect":
                    self.ops.mark_gone(self.conn)
                elif reason == "takeover":
                    other = self.ops.new_conn()
                    self.ops.handle({"op": "drive", "on": True, "force": True}, conn=other)
                elif reason == "manual":
                    self.ops.handle({"op": "drive", "open": True}, conn=self.conn)
                    self.move(.1)
                elif reason == "pad":
                    self.ops._status = {"driver": "active", "pads": [{"connected": True}]}
                elif reason == "pad_unreadable":
                    self.ops._status_error = "unreachable"
                elif reason == "pad_stale":
                    self.ops._status_at -= 16.
                elif reason == "state_stale":
                    self.ops._robot["state_at"] -= 2.
                elif reason == "state_invalid":
                    self.ops._robot["state"] = None
                elif reason == "bus_stale":
                    self.ops._robot["bus_at"] -= 4.
                elif reason == "estop":
                    self.ops._robot["estop_active"] = True
                elif reason == "policy":
                    self.ops._robot["policies"]["enabled"] = False
                elif reason == "model":
                    self.ops._robot["policies"] = copy.deepcopy(self.ops._robot["policies"])
                    self.ops._robot["policies"]["slots"][0]["path"] = "/changed.onnx"
                else:
                    self.ops._motion_config_digest = "changed"
                self.ops._tick_once()
                self.assertIsNone(self.ops.motion_studio.session)
                for method, params in CLEANUP:
                    if method in ("robot.head", "robot.pose"):
                        self.assertEqual(self.sent().count((method, params)), 1)
                stopped = self.sent()
                self.music_telemetry(self.ops.clock())
                source["rhythm"].update(last_beat=self.ops.clock(), age=.01)
                if reason != "disconnect":
                    self.motion("heartbeat", session_id=token)
                self.ops._tick_once()
                self.assertEqual(self.sent(), stopped)
                self.assertIsNone(self.ops.motion_studio.session)

    def test_music_phase_tracks_waiting_moving_and_unknown_in_same_session(self):
        self.stop_background_tick()
        source = self.music_source()
        rhythm = copy.deepcopy(source["rhythm"])
        source["rhythm"] = {"bpm": None, "confidence": 0., "feel": "unknown",
                            "last_beat": None, "age": None}
        token = self.motion("idle_start", kind="music")["session_id"]
        self.assertEqual(self.view().get("idle_phase"), "waiting")
        with self.robot.lk:
            self.robot.sent.clear()
        self.ops._tick_once()
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.view().get("idle_phase"), "waiting")
        source["rhythm"] = rhythm
        self.ops._tick_once()
        self.assertEqual(self.view().get("idle_phase"), "moving")
        self.assertTrue(self.sent("robot.pose")[-1][1]["active"])
        with self.robot.lk:
            self.robot.sent.clear()
        source["rhythm"]["confidence"] = 0.
        self.ops._tick_once()
        self.assertEqual(self.view().get("idle_phase"), "waiting")
        self.assertEqual(self.view()["session_id"], token)
        self.assertEqual(self.sent("robot.pose"), [("robot.pose", {"active": False})])
        self.ops._tick_once()
        self.assertEqual(len(self.sent("robot.pose")), 1)
        source["rhythm"]["confidence"] = .9
        self.ops._tick_once()
        self.assertEqual(self.view().get("idle_phase"), "moving")
        self.assertEqual(self.view()["session_id"], token)

    def test_music_source_shutdown_ends_session_once_and_never_revives_it(self):
        from studio.motion_store import HEAD_ZERO
        self.stop_background_tick()
        for change in ({"listening": False}, {"music": False}, {"available": False},
                       {"error": "capture unavailable"}):
            with self.subTest(change=change):
                self.motion("stop")
                source = self.music_source()
                original = copy.deepcopy(source)
                token = self.motion("idle_start", kind="music")["session_id"]
                self.ops._tick_once()
                with self.robot.lk:
                    self.robot.sent.clear()
                # External status changes include the native R3 toggle, bypassing pad.op.
                source.update(change)
                self.ops._tick_once()
                self.assertEqual(self.view()["state"], "idle")
                self.assertIsNone(self.view()["session_id"])
                self.assertFalse(self.view()["idle_running"])
                self.assertEqual(self.sent("robot.head"), [("robot.head", HEAD_ZERO)])
                self.assertEqual(self.sent("robot.pose"), [("robot.pose", {"active": False})])
                stopped = self.sent()
                self.ops._tick_once()
                source.update(original)
                self.ops._tick_once()
                self.assertEqual(self.sent(), stopped)
                self.assertEqual(self.view()["state"], "idle")
                self.assertTrue(self.motion("heartbeat", session_id=token).get("dropped"))

    def test_music_source_shutdown_keeps_combined_recording_semantics(self):
        self.stop_background_tick()
        source = self.music_source()
        token = self.start()
        self.assertEqual(self.motion("idle_start", kind="music")["session_id"], token)
        self.ops._tick_once()
        source["listening"] = False
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "recording")
        self.assertEqual(self.view()["session_id"], token)
        self.assertIsNone(self.view().get("idle_phase"))
        self.assertEqual(self.sent("robot.pose")[-1][1], {"active": False})

    def test_audio_shutdown_does_not_change_lively_or_plain_recording(self):
        self.stop_background_tick()
        source = self.music_source()
        source["available"] = False
        self.motion("idle_start")
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "idle_motion")
        self.assertIsNone(self.view().get("idle_phase"))
        self.motion("stop")
        token = self.start()
        self.ops._tick_once()
        self.assertEqual(self.view()["state"], "recording")
        self.assertEqual(self.view()["session_id"], token)
        self.assertIsNone(self.view().get("idle_phase"))

    def test_music_rejects_missing_service_bad_kind_and_physical_pad(self):
        for kwargs in ({"kind":"music"}, {"kind":"arbitrary"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(Refused):
                self.motion("idle_start", **kwargs)
        class Audio:
            def snapshot(self):
                return {"available":True,"listening":True,"music":True,"rhythm":{}}
            def close(self):
                pass
        self.ops.audio = Audio()
        self.cfg.connect_pad(fixtures.PRO, "Pad")
        self.ops._poll_status()
        with self.assertRaisesRegex(Refused,"实体手柄"):
            self.motion("idle_start",kind="music")

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
        # Keep the second frame inside the rate-limit window even if its worker starts late.
        now = self.ops.clock()
        self.ops.clock = lambda: now
        entered, release = threading.Event(), threading.Event()
        errors = []

        def wait(seconds):
            entered.set()
            release.wait(1.)

        def move():
            try:
                self.move()
            except Exception as exc:
                errors.append(exc)

        self.move(.1)
        with mock.patch.object(self.ops, "_cancel_wait", side_effect=wait):
            worker = threading.Thread(target=move)
            worker.start()
            try:
                self.assertTrue(entered.wait(.5))
                self.ops.handle({"op": "stop", "seq": next(self.seq)}, conn=self.conn)
                self.start()
                boundary = len(self.sent("robot.move"))
            finally:
                release.set()
                worker.join(1.)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
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


    def posture_feed(self, phase="walk", sitting=False, error=0., at=None):
        at = self.ops.clock() if at is None else at
        self.feed(posture="sitting" if sitting else "policy", pol={"sitting": sitting},
                  state={"policy": phase, "joints": [error] * 15, "targets": [0.] * 15},
                  state_at=at, policies_at=at,
                  bus=fixtures.bus(policy_enabled=True, homed=True))

    def settle_posture(self, target):
        for _ in range(3):
            self.posture_feed("sit" if target == "sit" else "walk", target == "sit")
            self.ops.motion_studio.tick()

    def posture_clip(self, targets=("sit", "stand")):
        from studio.motion_studio import fingerprint
        c = StorageTest().clip()
        c.update(version=2, fingerprint=fingerprint(self.ops), duration_s=.3,
                 events=[{"t": i * .1, "method": "studio.posture", "params": {"target": t}}
                         for i, t in enumerate(targets)])
        self.ops.motion_studio.store.save(c)
        return c["id"]

    def test_records_direct_and_dpad_postures_without_ending_recording(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        self.ops.handle({"op": "sit"}, conn=self.conn)
        self.assertEqual(self.view()["state"], "recording")
        self.assertEqual(self.view()["posture_step"]["target"], "sit")
        self.settle_posture("sit")
        self.ops.handle({"op": "key", "key": "dpad_down"}, conn=self.conn)
        self.settle_posture("stand")
        self.assertEqual(self.view()["state"], "recording")
        self.motion("record_finish")
        self.assertEqual(self.view()["state"], "draft")
        self.motion("save", name="坐下再站起")
        c = self.ops.motion_studio.store.get(self.view()["recordings"][0]["id"])
        self.assertEqual(c["version"], 2)
        self.assertEqual([e["params"]["target"] for e in c["events"] if e["method"] == "studio.posture"], ["sit", "stand"])

    def test_refused_posture_is_not_recorded_and_lost_reply_is_not_retried(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        self.robot.replies["robot.do"] = {"accepted": False, "reason": "not ready"}
        with self.assertRaises(Refused):
            self.ops.handle({"op": "sit"}, conn=self.conn)
        self.assertFalse(any(e["method"] == "studio.posture" for e in self.ops.motion_studio.session["events"]))
        self.assertIsNone(self.view()["posture_step"])
        self.robot.replies["robot.do"] = fixtures.Timeout("lost")
        with self.assertRaises(Refused):
            self.ops.handle({"op": "sit"}, conn=self.conn)
        self.ops.motion_studio.tick()
        self.assertIn("未知", self.view()["last_result"])
        self.assertIsNotNone(self.view()["posture_step"])
        with self.assertRaises(Refused):
            self.start()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)

    def test_replay_postures_are_ordered_barriers_even_when_late(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        s = self.ops.motion_studio.session
        s["anchor"] -= .3
        self.ops.motion_studio.tick()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)
        frozen = self.view()["elapsed_s"]
        self.posture_feed("sit", True, error=.3)
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["elapsed_s"], frozen)
        self.assertEqual(self.view()["state"], "playing")
        self.settle_posture("sit")
        s["anchor"] -= .11
        self.ops.motion_studio.tick()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)
        self.posture_feed("rise", False)
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "playing")
        self.settle_posture("stand")
        s["anchor"] -= .3
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")
        self.assertEqual(self.view()["last_result"], "回放完成")

    def test_stop_during_posture_preserves_fence_and_emits_no_more_motion(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.robot.sent.clear()
        self.motion("stop")
        self.assertIn("仍会完成", self.view()["last_result"])
        self.assertFalse(any(m == "robot.move" and any(p.values()) for m, p in self.sent()))
        self.assertFalse(any(m in ("robot.init", "robot.enable", "robot.do") for m, _ in self.sent()))
        with self.assertRaises(Refused):
            self.motion("play", id=cid)
        self.settle_posture("sit")
        self.assertIsNone(self.view()["posture_step"])
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_seated_single_play_is_allowed_but_seated_multi_loop_is_refused(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip(("sit",))
        with self.assertRaisesRegex(Refused, "站"):
            self.motion("play", id=cid, loops=3)
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.settle_posture("sit")
        s = self.ops.motion_studio.session
        s["anchor"] -= .31
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")

    def test_pause_during_sit_waits_for_completion_then_resumes_same_next_step(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.motion("pause")
        self.assertEqual(self.view()["state"], "play_paused")
        self.assertIn("仍会完成", self.view()["last_result"])
        with self.assertRaisesRegex(Refused, "坐站"):
            self.motion("resume")
        self.settle_posture("sit")
        self.motion("resume")
        self.ops.motion_studio.tick()
        self.ops.motion_studio.session["anchor"] -= .11
        self.ops.motion_studio.tick()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)
        self.assertEqual(self.view()["posture_step"]["target"], "stand")

    def test_seated_replay_skips_toggle_but_verifies_target_before_stand(self):
        self.stop_background_tick()
        self.posture_feed("sit", True)
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 0)
        self.assertEqual(self.view()["posture_step"]["target"], "sit")
        self.ops.motion_studio.tick()
        self.assertIsNotNone(self.view()["posture_step"])
        self.settle_posture("sit")
        self.ops.motion_studio.session["anchor"] -= .11
        self.ops.motion_studio.tick()
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)
        self.assertEqual(self.view()["posture_step"]["target"], "stand")

    def test_posture_timeout_fences_future_sessions_and_never_retries(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.ops.motion_studio.posture.pending["start"] -= 16.
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")
        self.assertIn("15 秒", self.view()["last_result"])
        for _ in range(3):
            self.posture_feed()
            self.ops.motion_studio.tick()
        with self.assertRaises(Refused):
            self.motion("play", id=cid)
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_disconnected_late_posture_reply_does_not_enter_recording_or_restart(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        entered, release = threading.Event(), threading.Event()
        def delayed(_):
            entered.set()
            release.wait(1.)
            return {"accepted": True}
        self.robot.replies["robot.do"] = delayed
        worker = threading.Thread(target=lambda: self.ops.handle({"op": "sit"}, conn=self.conn))
        worker.start()
        self.assertTrue(entered.wait(.5))
        self.ops.mark_gone(self.conn)
        release.set()
        worker.join(2.)
        self.assertFalse(worker.is_alive())
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")
        self.assertIsNone(self.view()["draft"])
        self.assertIsNotNone(self.view()["posture_step"])
        self.settle_posture("sit")
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_pending_posture_never_uses_legacy_toggle_when_fresh_state_disappears(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        self.robot.replies["robot.do"] = fixtures.Timeout("lost")
        with self.assertRaises(Refused):
            self.ops.handle({"op": "sit"}, conn=self.conn)
        self.ops.motion_studio.tick()
        self.feed(state=None, state_at=None, policies_at=self.ops.clock())
        self.robot.replies["robot.do"] = {"accepted": True}
        with self.assertRaises(Refused):
            self.ops.handle({"op": "sit"}, conn=self.conn)
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_recording_rebound_dpad_skill_is_refused_before_output(self):
        self.stop_background_tick()
        self.posture_feed()
        self.ops.bindings = [{"button": "dpad_down", "skill": "kick_left"}]
        self.ops._bindings_at = self.ops.clock()
        self.start()
        with self.assertRaisesRegex(Refused, "技能"):
            self.ops.handle({"op": "key", "key": "dpad_down"}, conn=self.conn)
        self.assertFalse(any(m == "robot.do" for m, _ in self.robot.calls))

    def test_posture_final_precheck_requires_live_runtime_enable_and_torque(self):
        self.stop_background_tick()
        for changes in ({"bus": fixtures.bus(policy_enabled=False, homed=True)},
                        {"bus": fixtures.bus(False, policy_enabled=True, homed=True)},
                        {"present": False}, {"paused": True}):
            self.posture_feed()
            self.ops.motion_studio.posture.pending = None
            self.ops._robot.update(changes)
            with self.subTest(changes=changes), self.assertRaises(Refused):
                self.ops.motion_studio.begin_posture("sit")

    def test_missing_posture_evidence_cancels_session_and_recovery_never_resumes(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.feed(state=None, state_at=None, policies_at=self.ops.clock())
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")
        self.assertIn("回读", self.view()["last_result"])
        self.assertIsNotNone(self.view()["posture_step"])
        self.settle_posture("sit")
        self.assertEqual(self.view()["state"], "idle")
        self.assertIsNone(self.view()["posture_step"])
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_stale_or_incomplete_posture_evidence_cancels_future_actions(self):
        self.stop_background_tick()
        cid = self.posture_clip()
        for state, age in (({"policy": "sit", "joints": [0.] * 15, "targets": [0.] * 15}, 2.),
                           ({"policy": "sit", "joints": [0.] * 15}, 0.),
                           ({"policy": "kick_left", "joints": [0.] * 15, "targets": [0.] * 15}, 0.)):
            self.posture_feed()
            self.motion("play", id=cid)
            self.ops.motion_studio.tick()
            before = sum(m == "robot.do" for m, _ in self.robot.calls)
            self.feed(posture="sitting", pol={"sitting": True}, state=state,
                      state_at=self.ops.clock() - age, policies_at=self.ops.clock(),
                      bus=fixtures.bus(policy_enabled=True, homed=True))
            self.ops.motion_studio.tick()
            with self.subTest(state=state, age=age):
                self.assertEqual(self.view()["state"], "idle")
            self.motion("stop")
            self.settle_posture("sit")
            self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), before)

    def test_recording_limit_ends_while_posture_is_still_in_progress(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        self.ops.handle({"op": "sit"}, conn=self.conn)
        self.ops.motion_studio.session["anchor"] -= 61.
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "draft")
        self.assertIn("60 秒", self.view()["last_result"])
        self.assertIsNotNone(self.view()["posture_step"])
        self.settle_posture("sit")
        self.assertEqual(self.view()["state"], "draft")
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_unexpected_sit_after_verified_stand_cancels_later_velocity(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        clip = self.ops.motion_studio.store.get(cid)
        clip["events"].append({"t": .2, "method": "robot.move", "params": {"vx": .12, "vy": 0., "vyaw": 0.}})
        self.ops.motion_studio.store.save(clip)
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.settle_posture("sit")
        self.ops.motion_studio.session["anchor"] -= .11
        self.ops.motion_studio.tick()
        self.settle_posture("stand")
        s = self.ops.motion_studio.session
        self.robot.sent.clear()
        self.posture_feed("sit", True)
        s["anchor"] -= .11
        self.ops.motion_studio.tick()
        self.assertEqual(self.view()["state"], "idle")
        self.assertFalse(any(p.get("vx") for _, p in self.sent("robot.move")))

    def test_seated_start_refuses_continuous_motion_before_first_posture(self):
        self.stop_background_tick()
        self.posture_feed("sit", True)
        cid = self.posture_clip()
        clip = self.ops.motion_studio.store.get(cid)
        clip["events"].insert(0, {"t": 0., "method": "robot.move", "params": {"vx": .12, "vy": 0., "vyaw": 0.}})
        self.ops.motion_studio.store.save(clip)
        with self.assertRaises(Refused):
            self.motion("play", id=cid)
        self.assertFalse(any(m == "robot.do" for m, _ in self.robot.calls))

    def test_frames_captured_before_ack_but_fed_later_do_not_complete_posture(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        stamps = []
        def reply(_):
            stamps.extend(self.ops.clock() for _ in range(3))
            return {"accepted": True}
        self.robot.replies["robot.do"] = reply
        self.ops.handle({"op": "sit"}, conn=self.conn)
        for stamp in stamps:
            self.posture_feed("sit", True, at=stamp)
            self.ops.motion_studio.tick()
        self.assertIsNotNone(self.view()["posture_step"])
        self.settle_posture("sit")
        self.assertIsNone(self.view()["posture_step"])

    def test_manual_stand_accepts_known_unconverged_seat_and_tracks_completion(self):
        self.stop_background_tick()
        self.posture_feed("sit", True, error=.3)
        self.assertTrue(self.ops._motion_view(self.ops.clock())["buttons"]["stand"]["ok"])
        self.assertTrue(self.ops.handle({"op": "stand"}, conn=self.conn)["accepted"])
        self.assertEqual(self.view()["posture_step"]["target"], "stand")
        with self.assertRaises(Refused):
            self.start()
        self.settle_posture("stand")
        self.assertIsNone(self.view()["posture_step"])
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def manual_pending_sit(self):
        self.posture_feed()
        self.ops.handle({"op": "sit"}, conn=self.conn)
        self.posture_feed("sit", True, error=.3)
        return self.ops.motion_studio.posture.pending

    def test_manual_opposite_target_recovers_timed_out_sit_without_home_or_torque_changes(self):
        self.stop_background_tick()
        pending = self.manual_pending_sit()
        pending["start"] -= 16.
        self.ops.motion_studio.tick()
        self.assertIn("15 秒", self.view()["posture_step"]["label"])
        self.assertTrue(self.ops.handle({"op": "stand"}, conn=self.conn)["accepted"])
        self.assertEqual(self.view()["posture_step"]["target"], "stand")
        self.posture_feed("rise", False)
        with self.assertRaises(Refused):
            self.start()
        self.settle_posture("stand")
        self.assertIsNone(self.view()["posture_step"])
        self.assertFalse(any(m in ("robot.init", "robot.enable", "robot.relax") for m, _ in self.robot.calls))
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)

    def test_refused_manual_override_preserves_previous_pending_fence(self):
        self.stop_background_tick()
        previous = self.manual_pending_sit()
        self.robot.replies["robot.do"] = {"accepted": False, "reason": "not ready"}
        with self.assertRaises(Refused):
            self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertIs(self.ops.motion_studio.posture.pending, previous)
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)
        with self.assertRaises(Refused):
            self.start()

    def test_uncertain_manual_override_fences_new_target_and_never_retries(self):
        self.stop_background_tick()
        self.manual_pending_sit()
        self.robot.replies["robot.do"] = fixtures.Timeout("lost")
        with self.assertRaises(Refused):
            self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertEqual(self.view()["posture_step"]["target"], "stand")
        with self.assertRaises(Refused):
            self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)
        with self.assertRaises(Refused):
            self.start()

    def test_manual_recovery_rejects_missing_stale_unknown_or_mismatched_phase(self):
        self.stop_background_tick()
        previous = self.manual_pending_sit()
        for phase, sitting, age in (("sit", True, 2.), ("rise", True, 0.), ("walk", True, 0.), ("kick_left", True, 0.)):
            self.posture_feed(phase, sitting, error=.3, at=self.ops.clock() - age)
            with self.subTest(phase=phase, age=age), self.assertRaises(Refused):
                self.ops.handle({"op": "stand"}, conn=self.conn)
            self.assertIs(self.ops.motion_studio.posture.pending, previous)
        self.feed(posture="sitting", pol={"sitting": True}, state=None, state_at=None, policies_at=self.ops.clock(),
                  bus=fixtures.bus(policy_enabled=True, homed=True))
        with self.assertRaises(Refused):
            self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 1)

    def test_manual_opposite_target_cancels_replay_before_overriding_transition(self):
        self.stop_background_tick()
        self.posture_feed()
        cid = self.posture_clip()
        self.motion("play", id=cid)
        self.ops.motion_studio.tick()
        self.posture_feed("sit", True, error=.3)
        self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertEqual(self.view()["state"], "idle")
        self.assertEqual(self.view()["posture_step"]["target"], "stand")
        self.settle_posture("stand")
        self.assertEqual(sum(m == "robot.do" for m, _ in self.robot.calls), 2)

    def test_manual_opposite_recovery_finishes_recording_before_override(self):
        self.stop_background_tick()
        self.posture_feed()
        self.start()
        self.ops.handle({"op": "sit"}, conn=self.conn)
        self.posture_feed("sit", True, error=.3)
        self.ops.handle({"op": "stand"}, conn=self.conn)
        self.assertEqual(self.view()["state"], "draft")
        targets = [e["params"]["target"] for e in self.ops.motion_studio.draft["events"] if e["method"] == "studio.posture"]
        self.assertEqual(targets, ["sit"])
        self.assertEqual(self.view()["posture_step"]["target"], "stand")


if __name__ == "__main__":
    unittest.main()
