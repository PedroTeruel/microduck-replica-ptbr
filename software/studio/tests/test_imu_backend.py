"""IMU 页后端（studio/imu.py）：推给页面的状态取对了没有，粗校 / verify-imu 该拒的拒。

用 tests/fixtures/now-20261018.jsonl（10-18 二号鸭真机录的）里的 busStatus 和 calibration-status。
粗校 / verify 用假 cmd 连接，照 fork 的 verify-imu 回包文字演成功和三种失败。
"""
import asyncio
import copy
import json
import math
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio.imu import ImuBackend, Refused  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Sample  # noqa: E402
from studio.rpc import RpcError  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


def recorded(method):
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("kind") == "reply" and d.get("method") == method:
            return d["reply"]["result"]
    raise KeyError(method)


class FakeCmd:
    """站在假 rd 的 cmd 连接上：busStatus / calibration-status / verify-imu。"""

    def __init__(self, rd):
        self.rd = rd

    async def call(self, method, params, timeout):
        if method == "robot.busStatus":
            return self.rd.bus.value
        if method == "robot.busCommand":
            action = (params or {}).get("action")
            if action == "calibration-status":
                return self.rd.calib.value
            if action == "verify-imu":
                return self.rd.verify(params)
        raise RpcError(method, -32601, "method not found")


class FakeRd:
    def __init__(self, bus=None, calib=None):
        self.bus, self.calib = Sample(), Sample()
        if bus is not None:
            self.bus.set(bus)
        if calib is not None:
            self.calib.set(calib)
        self.addr, self.verify_plan = None, "ok"
        self.cmd = FakeCmd(self)

    def verify(self, params):
        plan = self.verify_plan
        if plan == "no_sample":
            raise RpcError("robot.busCommand", -32603,
                           "verify-imu needs a live lsm6dsv16x sample; check busStatus last_sample.imu and the reader")
        if plan == "not_upright":
            raise RpcError("robot.busCommand", -32603,
                           "under this mount the trunk reads 31.2° from upright (limit 5°); stand the robot upright, "
                           "or the mount is wrong: check the module axes")
        if plan == "wrong":
            raise RpcError("robot.busCommand", -32603,
                           "tipped 20.0°, but under this mount it reads 90.0° (90.0° from nose-down): the mount is about "
                           "that far off about the vertical axis. If the nose did not go down, tip it nose-down and run "
                           "verify-imu again. Nothing saved: mount unchanged")
        if plan == "timeout":
            raise RpcError("robot.busCommand", -32603,
                           "no nose-down tip of at least 12° held within 20 s of the upright check; nothing saved")
        q = [float(x) for x in params["mount_wxyz"]]
        n = math.sqrt(sum(x * x for x in q))
        q = [x / n for x in q]
        cal = copy.deepcopy(self.calib.value or {})
        cal.setdefault("calibration", {})
        src = cal.get("imu_source") or "bus"
        if src == "bus":
            cal["calibration"]["imu_mount_quat"] = q
            cal["calibration"]["imu_mount_verified"] = True
        else:
            cal["calibration"].setdefault("imu_mounts", {})[src] = {"quat": q, "verified": True}
        top = cal.get("imu_mount")
        if isinstance(top, dict):
            top["quat"], top["verified"] = q, True
        self.calib.set(cal)
        return {"accepted": True, "source": src, "mount_wxyz": q}


def commissioning_bus(source="bus", gravity=None, mode="commissioning"):
    return {"mode": mode, "phase": "ready" if mode == "commissioning" else "control",
            "torque_state": "off", "torque_off_pending": None,
            "native": {"imu_source": source},
            "last_sample": {"servos": [{"id": i} for i in range(15)],
                            "imu": {"source": source, "ready": True, "valid": True,
                                    "gravity": list(gravity or [0.0, 0.0, -1.0]),
                                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                                    "mount_verified": False, "tilt_deg": 0.0}}}


def factory_calib(source="bus"):
    cal = {"motion_enabled": False, "imu_mount_verified": False,
           "imu_mount_quat": [math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0],
           "current_ma_per_count": 0.0, "units_verified": False, "imu_mounts": {},
           "joints": [{"name": n, "id": 10 + i, "zero_raw": 2048, "direction": -1, "calibrated": False}
                      for i, n in enumerate(("left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee",
                                             "left_ankle", "neck_pitch", "head_pitch", "head_yaw", "head_roll",
                                             "mouth", "right_hip_yaw", "right_hip_roll", "right_hip_pitch",
                                             "right_knee", "right_ankle"))]}
    if source != "bus":
        cal["imu_mounts"][source] = {"quat": [0.5, 0.5, 0.5, 0.5], "verified": False}
    return {"calibration": cal, "imu_source": source}


class ImuBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)

    def tearDown(self):
        self.tmp.cleanup()

    def backend(self, **kw):
        return ImuBackend(FakeRd(**kw), self.log, self.tmp.name)

    def test_view_picks_mount_of_chip_in_use(self):
        # 二号鸭用 LSM6DSV16X：要取 imu_mounts 里它那份，不是顶上那个（那是另一种芯片的）
        v = self.backend(bus=recorded("robot.busStatus"), calib=recorded("robot.busCommand")).view()
        self.assertEqual(v["t"], "imu")
        self.assertEqual(v["source"], "lsm6dsv16x")
        self.assertEqual(v["mount"]["quat"][0], 0.698208849)
        self.assertIs(v["mount"]["verified"], True)
        self.assertTrue(v["ready"])
        self.assertEqual(v["reader"]["state"], "streaming")
        json.dumps(v)                                           # 能直接发给页面

    def test_view_without_robotd(self):
        v = self.backend().view()
        self.assertIsNone(v["source"])
        self.assertIsNone(v["mount"])
        self.assertIsNone(v["stand_calib_at"])

    def test_view_bus_board_falls_back_to_top_level_mount(self):
        # 总线小板：busStatus 没有 imu_source → 当成 bus，方向用顶上的 imu_mount_quat
        bus = {"native": {"imu_age_ms": 5}}
        calib = {"calibration": {"imu_mount_quat": [1, 0, 0, 0], "imu_mount_verified": False}}
        v = self.backend(bus=bus, calib=calib).view()
        self.assertEqual(v["source"], "bus")
        self.assertEqual(v["mount"], {"quat": [1, 0, 0, 0], "verified": False})

    def test_view_commissioning_reads_last_sample(self):
        v = self.backend(bus=commissioning_bus(), calib=factory_calib()).view()
        self.assertEqual(v["mode"], "commissioning")
        self.assertTrue(v["ready"])
        self.assertEqual(v["reader"]["state"], "streaming")
        self.assertEqual(v["gravity"], [0.0, 0.0, -1.0])

    def test_stand_calib_time_read_from_state_dir(self):
        (Path(self.tmp.name) / "imu-stand-calib.json").write_text('{"at": "2026-10-18 02:10"}', encoding="utf-8")
        self.assertEqual(self.backend().view()["stand_calib_at"], "2026-10-18 02:10")

    def test_refuses_bad_or_unfinished_ops(self):
        b = self.backend()
        for args, word in (({"op": "solve"}, "没收到读数"),
                           ({"op": "solve", "samples": [{}] * 6001}, "读数太多"),
                           ({"op": "save"}, "写进主程序"),
                           ({"op": "coarse"}, "粗校"),
                           ({"op": "detect"}, "第一次开机前接好"),
                           ({"op": "set_chip", "chip": "bno08x"}, "microduck-firstboot"),
                           ({"op": "rm -rf"}, "不认识")):
            with self.subTest(args=args.get("op")):
                with self.assertRaises(Refused) as cm:
                    asyncio.run(b.handle(args, "测试"))
                self.assertIn(word, str(cm.exception))

    def test_full_solve_saves_pending_for_commit(self):
        """站着完整校完、结果 ok：新的方向、来源、质量写进 state/imu-pending.json（Studio 重启也不丢）。"""
        from tests.test_imu_calib import Duck
        b = self.backend(bus=recorded("robot.busStatus"), calib=recorded("robot.busCommand"))
        old = b.view()["mount"]["quat"]
        data = Duck(old, old_mount=old, noise_deg=0.1).run()
        samples = [{"step": step, "g": s["g"]} for step, rows in data.items() for s in rows]
        res = asyncio.run(b.handle({"op": "solve", "samples": samples}, "测试"))
        self.assertTrue(res["ok"], res)
        row = json.loads((Path(self.tmp.name) / "imu-pending.json").read_text(encoding="utf-8"))
        self.assertEqual(row["source"], "lsm6dsv16x")
        self.assertEqual(row["by"], "测试")
        self.assertIn("quality", row)
        self.assertAlmostEqual(sum(x * x for x in row["quat"]), 1.0, places=9)

    def test_solve_bad_samples_fails_politely(self):
        # 乱七八糟的读数：回 ok=False 和一句原因，不抛异常、不把后端弄挂
        b = self.backend()
        res = asyncio.run(b.handle({"op": "solve", "samples": [{"step": "still", "g": [0, 0, -1]}]}, "测试"))
        self.assertFalse(res["ok"])
        self.assertTrue(res["reason"])
        self.assertIs(b.last_result, res)

    def test_coarse_capture_then_solve_uses_commissioning_last_sample(self):
        rd = FakeRd(bus=commissioning_bus(), calib=factory_calib())
        b = ImuBackend(rd, self.log, self.tmp.name)
        still = asyncio.run(b.handle({"op": "coarse-capture", "phase": "still", "seconds": 1.7}, "测试"))
        self.assertEqual(still["phase"], "still")
        self.assertGreaterEqual(still["n"], 15)
        self.assertEqual(still["samples"][0]["g"], [0.0, 0.0, -1.0])

        a = math.radians(20.0)
        rd.bus.value["last_sample"]["imu"]["gravity"] = [math.sin(a), 0.0, -math.cos(a)]
        fwd = asyncio.run(b.handle({"op": "coarse-capture", "phase": "fwd", "seconds": 1.7}, "测试"))
        self.assertGreaterEqual(fwd["n"], 15)

        samples = still["samples"] + fwd["samples"]
        res = asyncio.run(b.handle({"op": "solve", "mode": "coarse", "frame": "body", "samples": samples}, "测试"))
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["mode"], "coarse")
        self.assertEqual(res["quality"]["grade"], "coarse")
        self.assertEqual(len(res["mount"]), 4)
        self.assertTrue(res["confirm"])

    def test_verify_success_writes_and_rereads_calibration(self):
        rd = FakeRd(bus=commissioning_bus("lsm6dsv16x"), calib=factory_calib("lsm6dsv16x"))
        b = ImuBackend(rd, self.log, self.tmp.name)
        mount = [0.5, 0.5, 0.5, 0.5]
        b.last_result = {"ok": True, "mode": "coarse", "mount": mount}
        rd.verify_plan = "ok"
        res = asyncio.run(b.handle({"op": "verify", "confirmed": True, "mount_wxyz": mount}, "测试"))
        self.assertTrue(res["ok"], res)
        v = b.view()
        self.assertEqual(v["source"], "lsm6dsv16x")
        self.assertIs(v["mount"]["verified"], True)
        self.assertAlmostEqual(v["mount"]["quat"][0], 0.5)

    def _verify_failure(self, plan):
        rd = FakeRd(bus=commissioning_bus("lsm6dsv16x"), calib=factory_calib("lsm6dsv16x"))
        b = ImuBackend(rd, self.log, self.tmp.name)
        mount = [0.5, 0.5, 0.5, 0.5]
        b.last_result = {"ok": True, "mode": "coarse", "mount": mount}
        rd.verify_plan = plan
        with self.assertRaises(Refused) as cm:
            asyncio.run(b.handle({"op": "verify", "confirmed": True, "mount_wxyz": mount}, "测试"))
        return str(cm.exception)

    def test_verify_failure_no_sample_is_translated(self):
        msg = self._verify_failure("no_sample")
        self.assertIn("没有 IMU 读数", msg)
        self.assertIn("Nothing saved", msg)

    def test_verify_failure_not_upright_is_translated(self):
        msg = self._verify_failure("not_upright")
        self.assertIn("没有摆正", msg)
        self.assertIn("Nothing saved", msg)

    def test_verify_failure_wrong_heading_is_translated(self):
        msg = self._verify_failure("wrong")
        self.assertIn("低头方向不对", msg)
        self.assertIn("90°", msg)
        self.assertIn("Nothing saved", msg)

    def test_verify_failure_timeout_is_translated(self):
        msg = self._verify_failure("timeout")
        self.assertIn("超时没看到往前低头", msg)
        self.assertIn("Nothing saved", msg)

    def test_motion_mode_refuses_coarse(self):
        b = self.backend(bus=commissioning_bus(mode="motion"), calib=factory_calib())
        for args in ({"op": "solve", "mode": "coarse", "samples": [{"step": "still", "g": [0, 0, -1]}]},
                     {"op": "coarse-capture", "phase": "still", "seconds": 0.5},
                     {"op": "verify", "confirmed": True, "mount_wxyz": [1, 0, 0, 0]}):
            with self.subTest(op=args["op"]):
                with self.assertRaises(Refused) as cm:
                    asyncio.run(b.handle(args, "测试"))
                self.assertIn("主程序已经在运动模式", str(cm.exception))

    def test_verify_readback_failure_or_mismatch_is_not_success(self):
        for corrupt in ("unreachable", "wrong-source", "wrong-quat", "unverified", "not-normalized", "contradictory-top"):
            b = self.backend(bus=commissioning_bus(), calib=factory_calib())
            q = [0.5]*4
            b.last_result = {"ok": True, "mode": "coarse", "mount": q}
            original = b.rd.cmd.call
            async def broken(method, params, timeout):
                if (params or {}).get("action") == "calibration-status":
                    if corrupt == "unreachable":
                        raise RpcError(method, -1, "readback missing")
                    status = copy.deepcopy(b.rd.calib.value)
                    if corrupt == "wrong-source":
                        status["imu_source"] = "lsm6dsv16x"
                    elif corrupt == "wrong-quat":
                        status["calibration"]["imu_mount_quat"] = [1.,0.,0.,0.]
                    elif corrupt == "not-normalized":
                        status["calibration"]["imu_mount_quat"] = [1.]*4
                    elif corrupt == "contradictory-top":
                        status["imu_mount"] = {"quat": q, "verified": True}
                        status["calibration"]["imu_mount_verified"] = False
                    else:
                        status["calibration"]["imu_mount_verified"] = False
                    return status
                return await original(method, params, timeout)
            b.rd.cmd.call = broken
            with self.subTest(corrupt=corrupt), self.assertRaises(Refused):
                asyncio.run(b.handle({"op": "verify", "confirmed": True, "mount_wxyz": q}))
            self.assertFalse((b.job or {}).get("done"))

    def test_redo_view_resumes_persistent_session_and_blocks_hold(self):
        from studio import helper
        root = Path(self.tmp.name) / "duck"
        directory = root / "var/lib/microduck-helper/imu-recalibrate"
        directory.mkdir(parents=True)
        manifest = {"schema": "microduck-imu-recalibrate/1", "active": True, "phase": "commissioning",
                    "session_id": "a"*32, "source": "bus"}
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        b = ImuBackend(FakeRd(bus=commissioning_bus(), calib=factory_calib()), self.log, self.tmp.name, root=str(root))
        with mock.patch.object(helper, "_call", side_effect=AssertionError("view must not sudo")):
            redo = b.view()["redo"]
        self.assertTrue(redo["active"])
        self.assertEqual(redo["session_id"], "a"*32)
        self.assertEqual(redo["phase"], "commissioning")
        with self.assertRaisesRegex(Refused, "重做"):
            asyncio.run(b.handle({"op": "hold"}))

    def test_factory_coarse_refuses_enabled_hold_and_pending_torque(self):
        for key, value in (("torque_state", "all_enabled"), ("torque_state", None),
                           ("torque_off_pending", True), ("hold", {"active": True})):
            bus = commissioning_bus()
            bus[key] = value
            b = self.backend(bus=bus, calib=factory_calib())
            with self.subTest(key=key), self.assertRaisesRegex(Refused, "卸力"):
                asyncio.run(b.handle({"op": "coarse-capture", "phase": "still", "seconds": 0.5}))

    def test_coarse_capture_rejects_source_change_mid_collection(self):
        b = self.backend(bus=commissioning_bus(), calib=factory_calib())
        calls = {"n": 0}
        async def bus_once():
            calls["n"] += 1
            return commissioning_bus("bus" if calls["n"] == 1 else "lsm6dsv16x")
        b._bus_once = bus_once
        with self.assertRaisesRegex(Refused, "来源"):
            asyncio.run(b.handle({"op": "coarse-capture", "phase": "still", "seconds": 0.5}))
        self.assertIs((b.job or {}).get("failed"), True)

    def test_coarse_capture_rpc_failure_ends_job_and_keeps_retry_available(self):
        b = self.backend(bus=commissioning_bus(), calib=factory_calib())
        async def fail():
            raise RpcError("robot.busStatus", -1, "fresh status unavailable")
        b._bus_once = fail
        with self.assertRaises((RpcError, Refused)):
            asyncio.run(b.handle({"op": "coarse-capture", "phase": "still", "seconds": 0.5}))
        self.assertIs((b.job or {}).get("failed"), True)

    def test_redo_start_requires_confirmation_and_runs_helper_off_event_loop(self):
        from studio import helper
        import threading
        bus = commissioning_bus(mode="motion")
        b = self.backend(bus=bus, calib=factory_calib())
        with mock.patch.object(helper, "available", return_value=True), mock.patch.object(helper, "imu_recalibrate") as redo:
            with self.assertRaises(Refused):
                asyncio.run(b.handle({"op": "redo-start", "confirmed": False}))
            redo.assert_not_called()
            seen = []
            def enter(*a, **kw):
                seen.append(threading.current_thread())
                b.rd.bus.set(commissioning_bus())
                return True, "imu_entered", {"active": True, "phase": "commissioning", "session_id": "a"*32, "source": "bus"}
            redo.side_effect = enter
            res = asyncio.run(b.handle({"op": "redo-start", "confirmed": True}, "test"))
        self.assertTrue(res["ok"])
        self.assertIsNot(seen[0], threading.current_thread())
        self.assertEqual(redo.call_args.args[:2], ("test", "enter"))

    def test_redo_old_helper_and_denied_sudo_explain_required_install_update(self):
        from studio import helper
        for result in ("bad_verb", "denied", "sudo: a password is required"):
            b = self.backend(bus=commissioning_bus(mode="motion"), calib=factory_calib())
            with mock.patch.object(helper, "available", return_value=True), \
                 mock.patch.object(helper, "imu_recalibrate", return_value=(False, result, None)):
                with self.assertRaisesRegex(Refused, "新版.*小助手.*sudoers"):
                    asyncio.run(b.handle({"op": "redo-start", "confirmed": True}))

    def test_source_mode_or_session_change_clears_stale_solve(self):
        b = self.backend(bus=commissioning_bus(), calib=factory_calib())
        b.view()
        b.last_result = {"ok": True, "mode": "coarse", "mount": [1.,0.,0.,0.]}
        b.rd.bus.value["native"]["imu_source"] = "lsm6dsv16x"
        b.view()
        self.assertIsNone(b.last_result)

    def test_redo_verification_finishes_with_expected_session_source_and_quaternion(self):
        from studio import helper
        b = self.backend(bus=commissioning_bus(), calib=factory_calib())
        session = {"active": True, "phase": "commissioning", "session_id": "b"*32, "source": "bus"}
        q = [0.5]*4
        b.last_result = {"ok": True, "mode": "coarse", "mount": q}
        def finish(by, action, **kw):
            self.assertEqual(action, "finish")
            self.assertEqual(kw["source"], "bus")
            self.assertEqual(kw["quat"], q)
            self.assertEqual(kw["session_id"], "b"*32)
            session["active"] = False
            b.rd.bus.set(commissioning_bus(mode="motion"))
            return True, "imu_finished", {}
        with mock.patch.object(helper, "imu_redo_state", side_effect=lambda **_: dict(session)), \
             mock.patch.object(helper, "imu_recalibrate", side_effect=finish) as call:
            res = asyncio.run(b.handle({"op": "verify", "confirmed": True, "mount_wxyz": q}, "test"))
        self.assertTrue(res["ok"])
        self.assertEqual(call.call_count, 1)


if __name__ == "__main__":
    unittest.main()
