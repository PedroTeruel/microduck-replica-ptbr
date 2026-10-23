"""Repeat initial IMU calibration without changing any joint calibration; no real services."""
import copy
import json
import os
import unittest
from unittest import mock

from tests.test_helper_calib import Base, CalibWorld, CalibCtx, build_valid, H


REDO = "/var/lib/microduck-helper/imu-recalibrate"
OVERRIDE = "/etc/systemd/system/robotd.service.d/zzzzzz-studio-imu-recalibrate.conf"


class RedoWorld(CalibWorld):
    def __init__(self, root):
        super().__init__(root)
        self.bus_mutate = None
        self.runtime_mutate = None
        self.exec_override = None
        self.restart_failures = 0
        # Installed files, systemd's loaded ExecStart, and live robotd can differ
        # when a helper is killed between unlink, daemon-reload and restart.
        self.effective_commissioning = False
        self.live_mode = "motion"
        self.units["padd"] = "active"
        self.units[H.GAMESIR] = "inactive"
        self.robot.torque = False
        self.rpc = self.robot.rpc
        self.robot.rpc = self._rpc

    def _rpc(self, method, params=None):
        if method == "robot.relax":
            self.robot.torque = False
            return {"accepted": True}
        if method == "robot.busStatus":
            commissioning = self.live_mode == "commissioning"
            bus = {"mode": "commissioning" if commissioning else "motion",
                   "phase": "ready" if commissioning else "control",
                   "policy_enabled": False, "home_recovery": False,
                   "torque_state": "off", "torque_off_pending": False,
                   "native": {"imu_source": "bus", "torque_state_confirmed": self.robot.torque,
                              "hd1910": {"restore_pending": False, "temporary_gains_applied": False}},
                   "last_sample": {"imu": {"source": "bus", "ready": True}}}
            if self.bus_mutate:
                self.bus_mutate(bus)
            return bus
        return self.rpc(method, params)

    def calibration_status(self, method="robot.busCommand"):
        status = super().calibration_status(method)
        if self.runtime_mutate:
            self.runtime_mutate(status)
        return status

    def show(self, unit, props):
        out = super().show(unit, props)
        if unit == "robotd" and "ExecStart" in props:
            import re
            command = self.exec_override or "/opt/robot/robotd --socket /run/robotd.sock"
            if self.effective_commissioning:
                command += " --commissioning"
            line = "ExecStart={ path=/opt/robot/robotd ; argv[]=" + command + " ; ignore_errors=no ; }"
            out = re.sub(r"ExecStart=.*", lambda _: line, out)
        return out

    def run(self, argv):
        if argv[:2] == ["systemctl", "daemon-reload"]:
            self.effective_commissioning = self.path(OVERRIDE).exists()
        if argv[:3] == ["systemctl", "restart", "robotd"]:
            self.calls.append(list(argv))
            if self.restart_failures:
                self.restart_failures -= 1
                return 1, "", "injected restart failure"
            self.robotd = "active"
            self.live_mode = "commissioning" if self.effective_commissioning else "motion"
            return 0, "", ""
        return super().run(argv)


class ImuRedoTest(Base):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp(prefix="helper-imu-redo-")
        self.w = RedoWorld(self.tmp)
        self.path = self.w.path(H.CALIB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.saved = self.w.path(H.CALIB_SAVED)
        self.dropin = self.w.path(H.COMMISSIONING_DROPIN)
        self.baseline = build_valid()
        self.baseline["joints"][0]["zero_raw"] = 2117
        self.baseline["imu_mounts"] = {"bno08x": {"quat": [1., 0., 0., 0.], "verified": True}}
        self.old = H.render_calibration(self.baseline).encode() + b'\n[future_setting]\nanswer = "preserve me"\n'
        self.path.write_bytes(self.old)
        self.saved.write_bytes(self.old + b"# separate saved bytes\n")
        self.saved_old = self.saved.read_bytes()

    def call_redo(self, action="enter", **extra):
        payload = {"by": "test", "action": action}
        if action in ("enter", "cancel"):
            payload["confirmed"] = True
        payload.update(extra)
        code, ctx = self.call(payload, verb="imu-recalibrate")
        return code, next(row["detail"] for row in reversed(ctx.stdout.lines()) if row["step"] == "done")

    def manifest(self):
        return json.loads(self.w.path(REDO + "/manifest.json").read_text(encoding="utf-8"))

    def enter(self):
        code, detail = self.call_redo()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertTrue(self.w.path(OVERRIDE).exists())
        self.assertEqual(self.path.read_bytes(), self.old)
        return detail["session_id"]

    def verified(self, quat=None):
        # Original robotd verifier writes both files and forces motion_enabled=false.
        text = self.path.read_text(encoding="utf-8")
        import re
        text = re.sub(r"(?m)^motion_enabled\s*=.*$", "motion_enabled = false", text)
        text = re.sub(r"(?m)^imu_mount_quat\s*=.*$", "imu_mount_quat = " + json.dumps(quat or [0.5]*4), text)
        self.path.write_text(text, encoding="utf-8")
        self.saved.write_text(text, encoding="utf-8")

    def test_strict_arguments_and_no_external_commands(self):
        for payload in ({"action": "shell", "command": "rm"}, {"action": "enter", "confirmed": False},
                        {"action": "enter", "confirmed": True, "service": "evil"},
                        {"action": "finish", "session_id": "bad", "source": "bus", "quat": [1,0,0,0]}):
            code, _ = self.call({"by": "test", **payload}, verb="imu-recalibrate")
            self.assertEqual(code, H.EXIT_ARGS)
        self.assertFalse(self.w.path(OVERRIDE).exists())

    def test_execstart_quoting_preserves_installed_arguments_and_refuses_ambiguity(self):
        description = '{ path=/opt/robot/robotd ; argv[]=/opt/robot/robotd --model "a path/model.onnx" ; ignore_errors=no ; start_time=[n/a] ; }'
        self.assertEqual(H.imu_redo_arguments(description), ["/opt/robot/robotd", "--model", "a path/model.onnx"])
        for bad in (description + " " + description,
                    '{ path=/bin/sh ; argv[]=/bin/sh -c robotd ; ignore_errors=no ; }',
                    description.replace('"a path/model.onnx"', 'a\\x20path/model.onnx'),
                    description.replace('"a path/model.onnx"', '$MODEL')):
            with self.subTest(bad=bad), self.assertRaises(H.Stop):
                H.imu_redo_arguments(bad)

    def test_enter_verified_motion_persists_separate_backups_and_stops_controllers(self):
        session = self.enter()
        manifest = self.manifest()
        self.assertEqual(manifest["session_id"], session)
        self.assertEqual(manifest["phase"], "commissioning")
        self.assertEqual(self.w.units["padd"], "inactive")
        self.assertEqual(self.saved.read_bytes(), self.saved_old)
        self.assertFalse(self.dropin.exists())
        code, status = self.call_redo("status")
        self.assertEqual(code, H.EXIT_OK)
        self.assertTrue(status["active"])
        self.assertEqual(status["session_id"], session)

    def test_real_commissioning_status_without_native_can_finish(self):
        session = self.enter()
        self.verified()
        def actual(bus):
            if bus["mode"] == "commissioning":
                bus.pop("native")
                bus.pop("policy_enabled")
                bus["torque_off_pending"] = None
                bus["policy_motion_enabled"] = False
        self.w.bus_mutate = actual
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)

    def test_power_loss_before_override_or_during_finish_can_cancel(self):
        for phase in ("finishing", "cancelling"):
            for loaded in (False, True):
                with self.subTest(phase=phase, daemon_reloaded=loaded):
                    session = self.enter()
                    manifest = self.manifest()
                    self.verified()
                    self.w.path(OVERRIDE).unlink()
                    if loaded:
                        self.w.run(["systemctl", "daemon-reload"])
                    self.assertEqual(self.w.live_mode, "commissioning", "unlink/reload does not restart live robotd")
                    manifest["phase"] = phase
                    self.w.path(REDO + "/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                    code, detail = self.call_redo("cancel", session_id=session)
                    self.assertEqual(code, H.EXIT_OK, detail)
                    self.assertEqual(self.path.read_bytes(), self.old)
                    self.assertEqual(self.saved.read_bytes(), self.saved_old)
                    self.assertEqual(self.w.live_mode, "motion")
                    self.assertFalse(self.manifest()["active"])

    def test_interrupted_finish_refuses_foreign_effective_exec_before_restoring_files(self):
        session = self.enter()
        self.verified()
        before = self.path.read_bytes(), self.saved.read_bytes()
        self.w.path(OVERRIDE).unlink()
        self.w.run(["systemctl", "daemon-reload"])
        manifest = self.manifest()
        manifest["phase"] = "finishing"
        self.w.path(REDO + "/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.w.exec_override = "/opt/robot/robotd --socket /tmp/foreign.sock"
        code, detail = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_STATE, detail)
        self.assertEqual(detail["result"], "imu_session_tampered")
        self.assertEqual((self.path.read_bytes(), self.saved.read_bytes()), before)

    def test_interrupted_enter_before_daemon_reload_can_cancel_exact_owned_override(self):
        for phase in ("entering", "recovery_required"):
            with self.subTest(phase=phase):
                session = self.enter()
                manifest = self.manifest()
                manifest["phase"] = phase
                self.w.path(REDO + "/manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                # Equivalent to a kill immediately after override write, before
                # reload/restart: exact owned bytes exist, loaded/live stay original.
                self.w.effective_commissioning = False
                self.w.live_mode = "motion"
                code, detail = self.call_redo("cancel", session_id=session)
                self.assertEqual(code, H.EXIT_OK, detail)
                self.assertFalse(self.w.path(OVERRIDE).exists())
                self.assertEqual(self.path.read_bytes(), self.old)
                self.assertEqual(self.saved.read_bytes(), self.saved_old)

    def test_normal_commissioning_phase_requires_loaded_commissioning_exec(self):
        session = self.enter()
        self.w.effective_commissioning = False
        code, detail = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_STATE, detail)
        self.assertEqual(detail["result"], "imu_session_tampered")
        self.assertTrue(self.w.path(OVERRIDE).exists())

    def test_controllers_started_after_reboot_are_stopped_before_finish_transition(self):
        session = self.enter()
        self.verified()
        self.w.units["padd"] = "active"
        real = H.remove
        def check(ctx, path):
            if path == OVERRIDE:
                self.assertEqual(self.w.units["padd"], "inactive")
            return real(ctx, path)
        with mock.patch.object(H, "remove", side_effect=check):
            code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)

    def test_motion_entry_requires_two_confirmed_off_safe_snapshots(self):
        cases = [lambda b: b.pop("policy_enabled"), lambda b: b.update(policy_enabled=True),
                 lambda b: b.update(home_recovery=True), lambda b: b.update(torque_off_pending=True),
                 lambda b: b["native"].update(torque_state_confirmed=None),
                 lambda b: b["native"]["hd1910"].update(restore_pending=True),
                 lambda b: b["native"]["hd1910"].update(temporary_gains_applied=True)]
        for mutate in cases:
            self.w.bus_mutate = mutate
            code, detail = self.call_redo()
            self.assertEqual(code, H.EXIT_STATE, detail)
            self.assertIn("卸力", detail.get("reason", ""))
            self.assertFalse(self.w.path(OVERRIDE).exists())
        self.w.bus_mutate = None
        reads = {"n": 0}
        def change(bus):
            reads["n"] += 1
            if reads["n"] >= 2:
                bus["native"]["torque_state_confirmed"] = True
        self.w.bus_mutate = change
        code, detail = self.call_redo()
        self.assertEqual(code, H.EXIT_STATE, detail)
        self.assertEqual(self.w.units["padd"], "active")
        self.assertFalse(any(c[:3] == ["systemctl", "restart", "robotd"] for c in self.w.calls))

    def test_enter_restart_failure_restores_original_mode_calibration_and_controllers(self):
        self.w.restart_failures = 1
        code, detail = self.call_redo()
        self.assertEqual(code, H.EXIT_FAIL, detail)
        self.assertEqual(self.path.read_bytes(), self.old)
        self.assertEqual(self.saved.read_bytes(), self.saved_old)
        self.assertFalse(self.w.path(OVERRIDE).exists())
        self.assertEqual(self.w.units["padd"], "active")
        self.assertFalse(self.manifest()["active"])

    def test_gate_change_after_controller_stop_refuses_without_restart(self):
        calls = {"n": 0}
        def enable_late(bus):
            calls["n"] += 1
            if calls["n"] >= 4:
                bus["native"]["torque_state_confirmed"] = True
        self.w.bus_mutate = enable_late
        code, detail = self.call_redo()
        self.assertEqual(code, H.EXIT_STATE, detail)
        self.assertFalse(any(c[:3] == ["systemctl", "restart", "robotd"] for c in self.w.calls))
        self.assertFalse(self.w.path(OVERRIDE).exists())
        self.assertEqual(self.w.units["padd"], "active")

    def test_persistent_backups_tamper_and_changed_session_are_refused(self):
        session = self.enter()
        code, _ = self.call_redo("cancel", session_id="f"*32)
        self.assertEqual(code, H.EXIT_STATE)
        backup = self.w.path(REDO + "/" + session + "/saved.toml")
        backup.write_bytes(b"tampered")
        code, _ = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_STATE)
        self.assertTrue(self.w.path(OVERRIDE).exists())

    def test_bus_lock_wins_and_manifest_precedes_override_write(self):
        self.w.locks.add(H.LOCK)
        code, _ = self.call_redo()
        self.assertEqual(code, H.EXIT_BUSY)
        self.w.locks.clear()
        real = H.write_atomic
        def checking(ctx, path, data, *args, **kw):
            if path == OVERRIDE:
                manifest = self.manifest()
                self.assertTrue(manifest["active"])
                self.assertTrue(self.w.path(REDO + "/" + manifest["session_id"] + "/main.toml").exists())
            return real(ctx, path, data, *args, **kw)
        with mock.patch.object(H, "write_atomic", side_effect=checking):
            self.enter()

    def test_active_session_blocks_commit_and_take_but_cancel_restores_exact_files(self):
        session = self.enter()
        for verb, payload in (("bus-take", {"by": "test"}), ("calib-commit", self.payload(dry=True))):
            code, _ = self.call(payload, verb=verb)
            self.assertEqual(code, H.EXIT_STATE, self.last())
            self.assertEqual(self.last()["result"], "imu_recalibrate_active")
        self.verified()
        code, detail = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.path.read_bytes(), self.old)
        self.assertEqual(self.saved.read_bytes(), self.saved_old)
        self.assertFalse(self.w.path(OVERRIDE).exists())
        self.assertEqual(self.w.units["padd"], "active")
        self.assertEqual(self.w.units[H.GAMESIR], "inactive")

    def test_finish_preserves_every_other_field_and_restores_motion_enabled_only(self):
        session = self.enter()
        self.verified()
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)
        import tomllib
        got = tomllib.loads(self.path.read_text(encoding="utf-8"))
        before = tomllib.loads(self.old.decode())
        self.assertTrue(got["motion_enabled"])
        self.assertEqual(got["imu_mount_quat"], [0.5]*4)
        before["imu_mount_quat"] = [0.5]*4
        self.assertEqual(got, before)
        self.assertFalse(self.w.path(OVERRIDE).exists())
        self.assertFalse(self.manifest()["active"])
        self.assertFalse(self.w.robot.torque)

    def test_dxl2_finish_accepts_verified_protocol_binding_and_cancel_preserves_original(self):
        self.w.bus_mutate = lambda bus: bus.update(imu_bus={"protocol": "dxl2", "board": "sflp_124_12", "identity": [1]})
        session = self.enter()
        self.verified()
        for path in (self.path, self.saved):
            path.write_text('imu_bus_protocol = "dxl2"\n' + path.read_text(encoding="utf-8"), encoding="utf-8")
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)
        import tomllib
        self.assertEqual(tomllib.loads(self.path.read_text(encoding="utf-8"))["imu_bus_protocol"], "dxl2")
        original = self.path.read_bytes()
        self.old = original
        session = self.enter()
        self.verified([1., 0., 0., 0.])
        code, detail = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.path.read_bytes(), original)

    def test_dxl2_finish_rejects_missing_protocol_binding(self):
        self.w.bus_mutate = lambda bus: bus.update(imu_bus={"protocol": "dxl2", "board": "sflp_124_12", "identity": [1]})
        session = self.enter()
        self.verified()
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_STATE, detail)
        self.assertTrue(self.manifest()["active"])

    def test_finish_refuses_unverified_mismatch_other_calibration_or_source(self):
        session = self.enter()
        self.verified()
        code, _ = self.call_redo("finish", session_id=session, source="bus", quat=[1.,0.,0.,0.])
        self.assertEqual(code, H.EXIT_STATE)
        self.path.write_text(self.path.read_text().replace("zero_raw = 2117", "zero_raw = 2048"), encoding="utf-8")
        code, _ = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_STATE)
        self.assertTrue(self.w.path(OVERRIDE).exists())

    def test_runtime_readback_failure_is_not_success(self):
        session = self.enter()
        self.verified()
        self.w.runtime_mutate = lambda s: s.update(imu_source="lsm6dsv16x")
        code, _ = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_STATE)
        self.assertTrue(self.w.path(OVERRIDE).exists())

    def test_restart_failure_keeps_verified_commissioning_session_retryable(self):
        session = self.enter()
        self.verified()
        verified = self.path.read_bytes()
        self.w.restart_failures = 1
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_FAIL, detail)
        self.assertTrue(self.w.path(OVERRIDE).exists())
        self.assertEqual(self.path.read_bytes(), verified)
        self.assertEqual(self.manifest()["phase"], "finish_failed")
        self.assertEqual(self.w.units["padd"], "inactive")
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[0.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)

    def test_tampered_owned_override_is_never_removed(self):
        session = self.enter()
        self.w.path(OVERRIDE).write_text("foreign content", encoding="utf-8")
        code, _ = self.call_redo("cancel", session_id=session)
        self.assertEqual(code, H.EXIT_STATE)
        self.assertEqual(self.w.path(OVERRIDE).read_text(), "foreign content")

    def test_foreign_wrapper_and_bus_held_refused_before_mutation(self):
        self.w.exec_override = "/bin/sh -c robotd"
        code, _ = self.call_redo()
        self.assertEqual(code, H.EXIT_STATE)
        self.w.exec_override = None
        self.w.path(H.FLAG).write_text("{}", encoding="utf-8")
        code, _ = self.call_redo()
        self.assertEqual(code, H.EXIT_STATE)


if __name__ == "__main__":
    unittest.main()
