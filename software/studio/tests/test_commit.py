"""写进主程序（studio/commit.py）：Studio 这边的记录、准备情况、预览、调小助手写入。

跑法：
    py -3.13 -I -c "import sys;sys.path[:0]=['.','deps','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_commit'])"
"""
import copy
import importlib.machinery
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps"), str(HERE.parent / "dev")]

from studio import commit as C  # noqa: E402
from studio import helper  # noqa: E402
from studio.robotd import Sample  # noqa: E402
from tests.test_helper_calib import current_calibration, joints_payload  # noqa: E402

HELPER = HERE.parent / "deploy" / "microduck-helper"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("microduck_helper_commit", str(HELPER))
    spec = importlib.util.spec_from_loader("microduck_helper_commit", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


H = load_helper()
BUS_QUAT = [math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0]
MODULE_QUAT = [0.5, 0.5, 0.5, 0.5]


def calibration(committed=False, source="bus", verified=None):
    rows = []
    for name in C.JOINT_ORDER:
        jid = C.JOINT_IDS[name]
        lo, hi = C.LIMITS_DEG[name]
        row = {"name": name, "id": jid, "zero_raw": 2048, "direction": -1, "calibrated": bool(committed)}
        if committed:
            row["min_rad"], row["max_rad"] = math.radians(lo), math.radians(hi)
        rows.append(row)
    cal = {"motion_enabled": bool(committed), "imu_mount_verified": bool(committed if verified is None else verified),
           "imu_mount_quat": list(BUS_QUAT), "current_ma_per_count": 0.0, "units_verified": False,
           "imu_mounts": {}, "joints": rows}
    if source != "bus":
        cal["imu_mounts"][source] = {"quat": list(MODULE_QUAT), "verified": bool(committed if verified is None else verified)}
    return {"calibration": cal, "imu_source": source}


def servo_rows(n=15):
    rows = []
    for i, name in enumerate(C.JOINT_ORDER[:n]):
        rows.append({"id": C.JOINT_IDS[name], "joint": name, "position_raw": 2048 + i,
                     "position_wire_raw": 2048 + i, "position_signed_raw": i, "speed_raw": 0,
                     "load_raw": 0, "current_raw": 12, "voltage_v": 7.6, "temperature_c": 36,
                     "moving": False, "calibrated": False})
    return rows


class Rd:
    """假 Robotd：mode 只由构造参数决定（fork main.rs:1300-1315）。"""

    def __init__(self, calib, source="bus", present=True, mode="commissioning", phase="ready",
                 servos=15, fresh=True, policy=False, torque=False):
        self.calib = Sample()
        if calib is not None:
            self.calib.set(calib)
        native = {"imu_source": source}
        if mode == "commissioning":
            bus = {"mode": "commissioning", "phase": phase, "native": native,
                   "last_sample": {"servos": servo_rows(servos), "imu": {
                       "source": source, "ready": True, "valid": True, "gravity": [0.0, 0.0, -1.0],
                       "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0], "mount_verified": False, "tilt_deg": 0.0}}}
        else:
            bus = {"mode": "motion", "phase": phase, "native": native, "policy_enabled": bool(policy)}
            if phase == "waiting_for_bus":
                bus["error"] = "torque readback at register 40: Feetech Sync Read timeout; missing IDs [21]"
            if phase == "control":
                native["torque_state_confirmed"] = bool(torque)
        self.bus = Sample()
        self.bus.set(bus)
        if not fresh:
            self.bus.at -= 10.0
        self.present, self.addr, self.cmd = present, None, None


class Log:
    def __init__(self):
        self.rows = []

    def info(self, msg, **kw):
        self.rows.append(("info", msg, kw))

    def warn(self, msg, **kw):
        self.rows.append(("warn", msg, kw))

    def error(self, msg, **kw):
        self.rows.append(("error", msg, kw))


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="commit-")
        self.log = Log()
        self.calib = calibration(False)
        self.rd = Rd(self.calib)
        self.svc = C.CommitService(self.rd, self.log, self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def item(self, key, view=None):
        view = view or self.svc.view(self.rd)
        return next(i for i in view["items"] if i["key"] == key)


class RecordsTest(Base):
    def test_centered_record_and_merge(self):
        C.record_centered(self.dir, [20], "舵机页", at=10)
        C.record_centered(self.dir, [21, 22], "一键校准", at=20)
        data = C.load_centered(self.dir)
        self.assertEqual(set(data), {20, 21, 22})
        self.assertEqual(data[20]["by"], "舵机页")
        self.assertEqual(data[22]["at"], 20)

    def test_forget_centered_removes_only_undone(self):
        C.record_centered(self.dir, [20, 21, 30], "测试", at=1)
        self.assertEqual(C.forget_centered(self.dir, [20, 99, 30]), [20, 30])
        self.assertEqual(set(C.load_centered(self.dir)), {21})

    def test_pending_saved_and_cleared(self):
        row = C.save_pending(self.dir, "bus", BUS_QUAT, {"tilt_deg": 1.2}, "测试", at=5)
        self.assertEqual(row["at"], 5)
        back = C.load_pending(self.dir)
        self.assertEqual(back["source"], "bus")
        self.assertAlmostEqual(sum(x * x for x in back["quat"]), 1.0)
        self.assertTrue(C.clear_pending(self.dir))
        self.assertFalse(C.clear_pending(self.dir))
        self.assertIsNone(C.load_pending(self.dir))

    def test_bad_pending_source_is_ignored(self):
        with open(os.path.join(self.dir, C.IMU_PENDING), "w", encoding="utf-8") as f:
            json.dump({"source": "mpu6050", "quat": [1, 0, 0, 0]}, f)
        self.assertIsNone(C.load_pending(self.dir))


class ReadinessTest(Base):
    def test_factory_commissioning_not_ready(self):
        view = self.svc.view(self.rd)
        self.assertFalse(view["ready"])
        self.assertEqual(view["mode"], "commissioning")
        servo = self.item("servo", view)
        self.assertFalse(servo["ok"])
        self.assertEqual(len(servo["missing"]), 15)
        self.assertEqual(self.item("imu", view)["text"], "标定模式：先在 IMU 页粗校一次，交给主程序验证")
        self.assertTrue(self.item("mode", view)["ok"])
        self.assertTrue(self.item("directions", view)["ok"])
        self.assertTrue(self.item("bus", view)["ok"])
        self.assertTrue(self.item("robotd", view)["ok"])

    def test_commissioning_needs_fifteen_fresh_servos(self):
        few = Rd(self.calib, servos=5)
        self.assertFalse(self.item("mode", self.svc.view(few))["ok"])
        self.assertIn("只有 5 颗", self.item("mode", self.svc.view(few))["text"])
        stale = Rd(self.calib, fresh=False)
        mode = self.item("mode", self.svc.view(stale))
        self.assertFalse(mode["ok"])
        self.assertIn("不新", mode["text"])

    def test_all_centered_and_pending_makes_ready(self):
        C.record_centered(self.dir, C.JOINT_IDS.values(), "测试", at=1)
        C.save_pending(self.dir, "bus", BUS_QUAT, {}, "测试", at=2)
        self.svc.reload(force=True)
        view = self.svc.view(self.rd)
        self.assertTrue(view["ready"], view)
        self.assertEqual(self.item("servo", view)["done"], 15)
        self.assertIn("IMU 页校过了", self.item("imu", view)["text"])
        self.assertIn("15 颗舵机都有新读数", self.item("mode", view)["text"])

    def test_motion_control_ready_but_policy_blocks(self):
        C.record_centered(self.dir, C.JOINT_IDS.values(), "测试", at=1)
        C.save_pending(self.dir, "bus", BUS_QUAT, {}, "测试", at=2)
        self.svc.reload(force=True)
        rd = Rd(self.calib, mode="motion", phase="control", torque=False)
        view = self.svc.view(rd)
        self.assertTrue(view["ready"], view)
        self.assertEqual(self.item("mode", view)["text"], "运动模式：总线已经打开")
        self.assertTrue(self.item("safety", view)["ok"])
        busy = Rd(self.calib, mode="motion", phase="control", policy=True)
        view2 = self.svc.view(busy)
        self.assertFalse(view2["ready"])
        self.assertEqual(self.item("safety", view2)["text"], "鸭子在走 / 站着：先坐下或卸力再写")

    def test_motion_waiting_for_bus_not_ready(self):
        rd = Rd(self.calib, mode="motion", phase="waiting_for_bus")
        view = self.svc.view(rd)
        self.assertFalse(view["ready"])
        mode = self.item("mode", view)
        self.assertFalse(mode["ok"])
        self.assertIn("waiting_for_bus", mode["text"])
        self.assertEqual(mode["action"]["do"], "robotd")

    def test_committed_calibration_is_ready(self):
        C.record_centered(self.dir, C.JOINT_IDS.values(), "测试", at=1)
        self.svc.reload(force=True)
        rd = Rd(calibration(True), mode="motion", phase="control", torque=False)
        view = self.svc.view(rd)
        self.assertTrue(view["ready"], view)
        self.assertEqual(self.item("imu", view)["text"], "主程序里的 IMU 方向已经确认过（总线小板（ID 200））")

    def test_servo_session_blocks(self):
        class Servo:
            state = "open"
        view = self.svc.readiness(self.rd, Servo())
        self.assertFalse(next(i for i in view["items"] if i["key"] == "bus")["ok"])
        self.assertFalse(view["ready"])

    def test_robotd_absent_blocks(self):
        rd = Rd(calibration(True), present=False)
        view = self.svc.readiness(rd)
        self.assertFalse(next(i for i in view["items"] if i["key"] == "robotd")["ok"])

    def test_imu_source_changed(self):
        C.save_pending(self.dir, "bno08x", BUS_QUAT, {}, "测试", at=1)
        self.svc.reload(force=True)
        imu = self.item("imu", self.svc.view(Rd(calibration(False, "lsm6dsv16x"), source="lsm6dsv16x")))
        self.assertFalse(imu["ok"])
        self.assertIn("IMU 芯片换过了", imu["text"])
        self.assertIn("重校一次", imu["text"])

    def test_directions_listed(self):
        with open(os.path.join(self.dir, "servo-directions.json"), "w", encoding="utf-8") as f:
            json.dump({"20": 1, "30": 1}, f)
        self.svc.reload(force=True)
        dirs = self.item("directions")
        self.assertTrue(dirs["ok"])
        self.assertEqual([x["id"] for x in dirs["changed"]], [20, 30])

    def test_calib_read_fallback_when_status_unavailable(self):
        rd = Rd(self.calib, mode="motion", phase="waiting_for_bus")
        rd.calib = Sample()                       # 运动模式卡在 waiting_for_bus：calibration-status 读不到
        file_cal = calibration(False)["calibration"]
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_read",
                                  return_value=(True, "read", {"exit": 0, "calibration": file_cal,
                                                               "mode": "motion"})) as call:
            view = self.svc.readiness(rd)
        self.assertTrue(call.called)
        self.assertTrue(view["from_file"])
        self.assertEqual(view["note"], "主程序现在没在用这份标定，下面是文件里的内容")
        self.assertTrue(view["preview_ok"])
        self.assertEqual(self.item("servo", view)["done"], 0)

    def test_pending_and_centered_make_step_three_dirty(self):
        C.save_pending(self.dir, "bus", BUS_QUAT, {}, "测试", at=2)
        self.svc.reload(force=True)
        view = self.svc.view(self.rd)
        self.assertTrue(view["dirty"])
        self.assertIn("IMU 方向有新校准还没写", view["dirty_why"])

        C.record_centered(self.dir, [20], "测试", at=3)
        self.svc.reload(force=True)
        view = self.svc.view(self.rd)
        self.assertIn("舵机零位记录比上次成功写入新", view["dirty_why"])

        with open(os.path.join(self.dir, "servo-directions.json"), "w", encoding="utf-8") as f:
            json.dump({"20": 1}, f)
        self.svc.reload(force=True)
        view = self.svc.view(self.rd)
        self.assertIn("舵机页设的方向和主程序文件不一样", view["dirty_why"])

        # 反过来：舵机页没设过方向、主程序文件是 +1：不算改动，写的时候沿用文件里的 +1，
        # 不能拿默认 −1 把它盖掉（二号鸭的文件里就有 +1）。
        os.unlink(os.path.join(self.dir, "servo-directions.json"))
        flipped = calibration(False)
        flipped["calibration"]["joints"][0]["direction"] = 1
        self.rd.calib.set(flipped)
        self.svc.reload(force=True)
        view = self.svc.view(self.rd)
        self.assertNotIn("舵机页设的方向和主程序文件不一样", view.get("dirty_why") or [])
        payload = self.svc._payload(self.rd)
        first_id = flipped["calibration"]["joints"][0]["id"]
        self.assertEqual([j["direction"] for j in payload["joints"] if j["id"] == first_id], [1])


class PreviewCommitTest(Base):
    def ready(self, source="bus", rd=None):
        C.record_centered(self.dir, C.JOINT_IDS.values(), "测试", at=1)
        C.save_pending(self.dir, source, BUS_QUAT, {"tilt_deg": 0.4}, "测试", at=2)
        self.svc.reload(force=True)
        if rd is not None:
            self.svc.rd = rd
        return rd or self.rd

    def test_preview_without_helper_renders_toml(self):
        self.ready()
        with mock.patch.object(helper, "available", return_value=False):
            data = self.svc.preview("测试")
        self.assertFalse(data["helper"])
        self.assertEqual(len(data["joints"]), 15)
        self.assertTrue(all(j["cn"] for j in data["joints"]))
        self.assertTrue(data["imu"]["text"])
        self.assertIn("off_deg", data["imu"])
        back = H.tomllib.loads(data["toml"])
        H.validate_calibration(back, "bus")
        self.assertTrue(back["motion_enabled"])

    def test_preview_uses_helper_dry_run(self):
        self.ready()
        toml = C.render_calibration(C.build_calibration(self.calib["calibration"], joints_payload(),
                                                       {"source": "bus", "quat": BUS_QUAT}))
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(True, "preview", {"toml": toml})) as call:
            data = self.svc.preview("测试")
        self.assertTrue(data["helper"])
        self.assertEqual(call.call_args.kwargs["dry_run"], True)

    def test_preview_refuses_when_chip_changed(self):
        C.save_pending(self.dir, "bno08x", BUS_QUAT, {}, "测试", at=1)
        rd = Rd(calibration(False, "lsm6dsv16x"), source="lsm6dsv16x")
        self.svc.rd = rd
        self.svc.reload(force=True)
        with mock.patch.object(helper, "available", return_value=False):
            with self.assertRaises(C.Refused) as cm:
                self.svc.preview("测试")
        self.assertIn("IMU 芯片换过了", str(cm.exception))

    def test_commit_success_clears_pending(self):
        self.ready()
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(True, "committed", {"exit": 0})):
            res = self.svc.commit("测试")
        self.assertTrue(res["ok"], res)
        self.assertIsNone(C.load_pending(self.dir))
        self.assertEqual(self.svc.job["phase"], "done")
        self.assertTrue(any(r[0] == "info" and "写进主程序" in r[1] for r in self.log.rows))
        # 成功以后记下这次的 centered mtime：没有新改动时第 3 步不再显示「该做」
        self.svc.reload(force=True)
        self.assertFalse(self.svc.view(self.rd)["dirty"])

    def test_timeout_reads_last_result(self):
        self.ready()
        last = {"verb": "calib-commit", "wall": time.time(), "exit": 0, "result": "committed",
                "reason": "写进主程序了：主程序进了运动模式，15 颗和 IMU 方向读回来都一致",
                "detail": {"readback_ok": True, "bus_status": {"mode": "motion", "phase": "control"}}}
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(False, "TimeoutExpired", None)), \
                mock.patch.object(helper, "last_result", return_value=last):
            res = self.svc.commit("测试")
        self.assertTrue(res["ok"], res)
        self.assertTrue(self.svc.job["from_last_result"])
        self.assertIsNone(C.load_pending(self.dir))

    def test_stale_last_result_after_timeout_is_not_accepted(self):
        self.ready()
        last = {"verb": "calib-commit", "wall": time.time() - 600, "exit": 0, "result": "committed",
                "reason": "旧结果", "detail": {}}
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(False, "TimeoutExpired", None)), \
                mock.patch.object(helper, "last_result", return_value=last):
            res = self.svc.commit("测试")
        self.assertFalse(res["ok"])
        self.assertIn("180 秒", res["reason"])
        self.assertIsNotNone(C.load_pending(self.dir))

    def test_no_helper_refuses(self):
        self.ready()
        with mock.patch.object(helper, "available", return_value=False):
            res = self.svc.commit("测试")
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "电脑上不能写主程序")
        self.assertIsNotNone(C.load_pending(self.dir))

    def test_failure_with_rollback_is_reported(self):
        self.ready()
        msg = "标定没通过主程序的检查：motion requires all 15 calibrated joints；已经换回原来的文件和模式，又起了一次主程序"
        detail = {"rolled_back": True, "files_restored": True, "mode_restored": True,
                  "robotd_up_after_rollback": True, "journal": ["x"], "msg": msg}
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(False, "calib_rejected", detail)):
            res = self.svc.commit("测试")
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], msg)
        self.assertTrue(res["detail"]["rolled_back"])
        self.assertEqual(self.svc.job["phase"], "failed")
        self.assertIsNotNone(C.load_pending(self.dir))

    def test_failure_reports_bus_status(self):
        self.ready()
        msg = "主程序打不开舵机总线：torque readback at register 40: Feetech Sync Read timeout。舵机电源开了吗？"
        detail = {"rolled_back": True, "msg": msg, "readback_ok": False,
                  "bus_status": {"mode": "motion", "phase": "waiting_for_bus", "error": "Feetech Sync Read timeout"}}
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(False, "bus_unavailable", detail)):
            res = self.svc.commit("测试")
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], msg)
        self.assertEqual(res["detail"]["bus_status"]["phase"], "waiting_for_bus")
        self.assertEqual(self.svc.job["phase"], "failed")

    def test_busy_second_commit(self):
        self.assertTrue(self.svc._writing.acquire(blocking=False))
        try:
            res = self.svc.commit("测试")
        finally:
            self.svc._writing.release()
        self.assertTrue(res.get("busy"))
        self.assertIn("已经在写了", res["reason"])

    def test_success_job_collapses_after_two_minutes(self):
        self.ready()
        with mock.patch.object(helper, "available", return_value=True), \
                mock.patch.object(helper, "calib_commit", return_value=(True, "committed", {"exit": 0})):
            self.svc.commit("测试")
        self.assertIsNotNone(self.svc.view(self.rd)["job"])
        self.svc.job["finished"] = time.time() - 121
        self.assertIsNone(self.svc.view(self.rd)["job"])


class SharedCodeTest(unittest.TestCase):
    """小助手和 Studio 里的组 TOML / 校验代码逐字相同：同一份输入必须写出同一份文件。"""

    def test_same_output_for_bus_and_modules(self):
        cur = current_calibration()
        for source, quat in (("bus", [1.0, 0.0, 0.0, 0.0]), ("bno08x", MODULE_QUAT)):
            joints = joints_payload({"left_hip_yaw": 1, "neck_pitch": 1})
            imu = {"source": source, "quat": quat}
            a = H.build_calibration(copy.deepcopy(cur), copy.deepcopy(joints), copy.deepcopy(imu))
            b = C.build_calibration(copy.deepcopy(cur), copy.deepcopy(joints), copy.deepcopy(imu))
            self.assertEqual(a, b)
            self.assertEqual(H.render_calibration(a), C.render_calibration(b))
            H.validate_calibration(a, source)
            C.validate_calibration(b, source)


if __name__ == "__main__":
    unittest.main()
