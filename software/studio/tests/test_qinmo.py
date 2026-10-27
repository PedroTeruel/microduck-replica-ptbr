"""Profile contract and privileged selection, using simulated services only."""
import copy
import json
import os
import unittest
import asyncio
from unittest import mock

from tests.test_imu_backend import ImuBackendTest, commissioning_bus, factory_calib
from tests.test_helper_imu_redo import ImuRedoTest, RedoWorld, OVERRIDE
from tests.test_helper_calib import H, joints_payload, current_calibration
from tests.test_helper_calib import CalibCtx
from studio import commit
from studio.imu import bus_imu_of, mount_of, Refused, bus_protocol_mismatch
from tests.test_http import HttpTest, WsClient
from studio import imu as imu_module

CONFIG = "/etc/robot/feetech-ft5/robotd.toml"
SAVED = "/etc/robot/feetech-ft5/robotd.saved.toml"
INFO = {"protocol": "feetech", "board": "qinmo", "identity": [], "profile": "qinmo",
        "gyro_dps_per_lsb": 1/16.4, "identification": "configured_profile"}

INVALID_METADATA = [
    {"imu_bus":{"protocol":"future","profile":"future"}},
    {"imu_bus":{"protocol":"future","profile":"legacy"}},
    {"imu_bus":{"protocol":"feetech","profile":"future"}},
    {"imu_bus":{"protocol":"feetech","profile":None}},
    {"imu_bus":{"protocol":None,"profile":"legacy"}},
    {"imu_bus":{}}, {"imu_bus":None}, {"imu_bus":[]},
    {"configured_imu_profile":"future", "imu_bus":{"protocol":"feetech","profile":"legacy"}},
    {"configured_imu_profile":None},
    {"configured_imu_profile":[], "imu_bus":{"protocol":"feetech"}},
    {"imu_bus":{"protocol":"dxl2","profile":"qinmo"}},
    {"configured_imu_profile":"qinmo", "imu_bus":{"protocol":"feetech","profile":"legacy"}},
    {"configured_imu_profile":"legacy", "imu_bus":None},
    {"configured_imu_profile":"legacy", "imu_bus":{"protocol":"future","profile":"legacy"}},
]


class QinmoBackendTest(ImuBackendTest):
    def test_conflicting_shadow_metadata_invalidates_result_without_resurrection(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus['native'].update(imu_bus={'protocol':'feetech','profile':'legacy','board':'ft6','identity':[1]},
                             configured_imu_profile='legacy')
        backend = self.backend(bus=bus,calib=cal)
        projected = backend.view()['imu_bus']
        backend.last_result = {'ok':True,'mount':[1,0,0,0]}
        backend.job = {'done':True}
        bus['imu_bus'] = copy.deepcopy(INFO)
        view = backend.view()
        self.assertEqual(view['imu_bus'],projected)
        self.assertTrue(view['metadata_error'])
        self.assertIsNone(backend.last_result)
        self.assertIsNone(backend.job)
        del bus['imu_bus']
        self.assertIsNone(backend.view()['metadata_error'])
        self.assertIsNone(backend.last_result)

    def test_conflicting_shadow_metadata_discards_inflight_solve(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus['native'].update(imu_bus={'protocol':'feetech','profile':'legacy','board':'ft6','identity':[1]},
                             configured_imu_profile='legacy')
        backend = self.backend(bus=bus,calib=cal)
        def solve(*args,**kwargs):
            bus['imu_bus'] = copy.deepcopy(INFO)
            return {'ok':True,'mount':[1,0,0,0],'mode':'full','quality':{}}
        with mock.patch('studio.imu.imu_calib.solve',side_effect=solve):
            with self.assertRaises(Refused):
                asyncio.run(backend.handle({'op':'solve','mode':'full','samples':[{'g':[0,0,-1]}]}))
        self.assertIsNone(commit.load_pending(self.tmp.name))
        del bus['imu_bus']
        backend.view()
        self.assertIsNone(backend.last_result)

    def test_conflict_then_recovery_discards_inflight_solve(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus['native'].update(imu_bus={'protocol':'feetech','profile':'legacy','board':'ft6','identity':[1]})
        backend = self.backend(bus=bus,calib=cal)
        def solve(*args,**kwargs):
            bus['imu_bus'] = copy.deepcopy(INFO)
            backend.view()
            del bus['imu_bus']
            backend.view()
            return {'ok':True,'mount':[1,0,0,0],'mode':'full','quality':{}}
        with mock.patch('studio.imu.imu_calib.solve',side_effect=solve):
            with self.assertRaises(Refused):
                asyncio.run(backend.handle({'op':'solve','mode':'full','samples':[{'g':[0,0,-1]}]}))
        self.assertIsNone(commit.load_pending(self.tmp.name))
        self.assertIsNone(backend.last_result)

    def test_conflict_then_recovery_discards_awaited_verifier_reply(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus['native'].update(imu_bus={'protocol':'feetech','profile':'legacy','board':'ft6','identity':[1]})
        backend = self.backend(bus=bus,calib=cal)
        backend.view()
        backend.last_result = {'ok':True,'mode':'coarse','mount':[.5]*4}
        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()
            original = backend._rpc_once
            async def delayed(method,params,timeout,name):
                if params.get('action') == 'verify-imu':
                    started.set()
                    await release.wait()
                return await original(method,params,timeout,name)
            with mock.patch.object(backend,'_rpc_once',side_effect=delayed):
                task = asyncio.create_task(backend.handle({'op':'verify','confirmed':True,'mount_wxyz':[.5]*4}))
                await started.wait()
                bus['imu_bus'] = copy.deepcopy(INFO)
                backend.view()
                del bus['imu_bus']
                backend.view()
                release.set()
                with self.assertRaises(Refused):
                    await task
        asyncio.run(scenario())
        self.assertIsNone(backend.last_result)
        self.assertFalse((backend.job or {}).get('done'))

    def test_conflict_then_recovery_discards_awaited_capture_reply(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus['native'].update(imu_bus={'protocol':'feetech','profile':'legacy','board':'ft6','identity':[1]})
        backend = self.backend(bus=bus,calib=cal)
        backend.view()
        async def scenario():
            started, release = asyncio.Event(), asyncio.Event()
            async def delayed():
                started.set()
                await release.wait()
                return bus
            with mock.patch.object(backend,'_bus_once',side_effect=delayed):
                task = asyncio.create_task(backend.handle({'op':'coarse-capture','phase':'still','seconds':.5}))
                await started.wait()
                bus['imu_bus'] = copy.deepcopy(INFO)
                backend.view()
                del bus['imu_bus']
                backend.view()
                release.set()
                with self.assertRaisesRegex(Refused,'改变'):
                    await task
        asyncio.run(scenario())
        self.assertFalse((backend.job or {}).get('done'))

    def test_raw_metadata_presence_is_validated_before_projection_and_actions(self):
        for raw in INVALID_METADATA:
            for native in (False, True):
                with self.subTest(raw=raw,native=native):
                    bus, cal = commissioning_bus(), factory_calib()
                    cal['calibration']['imu_mount_verified'] = True
                    backend = self.backend(bus=bus,calib=cal)
                    backend.view()
                    backend.last_result = {'ok':True,'mount':[1,0,0,0]}
                    (bus['native'] if native else bus).update(copy.deepcopy(raw))
                    view = backend.view()
                    self.assertIsNone(backend.last_result)
                    self.assertFalse(view['mount']['verified'])
                    self.assertTrue(view['profile_error'])
                    self.assertFalse(commit.pending_matches({'source':'bus'},'bus',bus))
                    with self.assertRaises(Refused):
                        backend._coarse_guard(bus)
                    for args in ({'op':'solve','mode':'full','samples':[{'g':[0,0,-1]}]},
                                 {'op':'coarse-capture','phase':'still','seconds':.5},
                                 {'op':'verify','mount_wxyz':[1,0,0,0],'confirmed':True},
                                 {'op':'profile-select','profile':'qinmo','confirmed':True}):
                        with self.assertRaises(Refused):
                            asyncio.run(backend.handle(args))

    def test_metadata_validator_contract_matches_standalone_helper(self):
        valid = [{}, {'imu_bus':{'protocol':'feetech'}}, {'imu_bus':{'protocol':'dxl2','profile':'legacy'}},
                 {'configured_imu_profile':'qinmo'}, {'configured_imu_profile':'legacy'},
                 {'configured_imu_profile':'qinmo','imu_bus':INFO}]
        for raw in valid + INVALID_METADATA:
            result = imu_module.imu_bus_metadata(raw)
            self.assertEqual(result,H.imu_bus_metadata(raw))
            self.assertEqual(bool(result[2]),raw in INVALID_METADATA)

    def test_pending_present_malformed_metadata_does_not_use_old_absence_fallback(self):
        bus = {'imu_bus':{'protocol':'feetech','board':'ft6','identity':[1]}}
        self.assertTrue(commit.pending_matches({'source':'bus'},'bus',bus))
        for info in (None, {}, [], {'protocol':'future','profile':'legacy'}, {'protocol':'feetech','profile':None}):
            with self.subTest(info=info):
                self.assertFalse(commit.pending_matches({'source':'bus','imu_bus':info},'bus',bus))

    def test_i2c_redo_ignores_unused_bus_metadata(self):
        from studio import helper
        bus, cal = commissioning_bus(source='bno08x',mode='motion'), factory_calib('bno08x')
        bus['native']['imu_bus'] = None
        backend = self.backend(bus=bus,calib=cal)
        with mock.patch.object(helper,'available',return_value=True), mock.patch.object(helper,'imu_recalibrate',return_value=(True,'imu_entered',{})):
            self.assertTrue(asyncio.run(backend.handle({'op':'redo-start','confirmed':True}))['ok'])

    def test_explicit_unknown_profile_is_not_absent_legacy_metadata(self):
        for location in ("native", "top"):
            bus, cal = commissioning_bus(), factory_calib()
            info = {"protocol":"feetech", "board":"ft6", "identity":[1], "profile":"future"}
            if location == "native":
                bus["native"]["imu_bus"] = info
            else:
                bus["imu_bus"] = info
            cal["calibration"]["imu_mount_verified"] = True
            cal["imu_mount"] = {"quat":[1,0,0,0], "verified":True}
            backend = self.backend(bus=bus,calib=cal)
            info["profile"] = "legacy"
            backend.view()
            backend.last_result = {"ok":True,"mount":[1,0,0,0]}
            info["profile"] = "future"
            self.assertEqual(backend.view()["imu_bus"]["profile"], "future")
            self.assertIsNone(backend.last_result)
            self.assertFalse(backend.view()["mount"]["verified"])
            self.assertTrue(backend.view()["mount_protocol_mismatch"])
            self.assertIn("不支持", backend.view()["profile_error"])
            self.assertFalse(commit.pending_matches({"source":"bus"}, "bus",bus))
            self.assertFalse(commit.pending_matches({"source":"bus","imu_bus":info}, "bus",bus))
            with self.assertRaises(Refused):
                backend._coarse_guard(bus)
            with mock.patch("studio.imu.imu_calib.solve",return_value={"ok":True,"mount":[1,0,0,0]}) as solve:
                with self.assertRaises(Refused):
                    asyncio.run(backend.handle({"op":"solve","mode":"full","samples":[{"g":[0,0,-1]}]}))
                solve.assert_not_called()
            cal["calibration"]["imu_bus_profile"] = "future"
            self.assertTrue(bus_protocol_mismatch(bus,cal), "matching unknown strings cannot authenticate a binding")

    def test_raw_qinmo_binding_never_promotes_without_discovery_or_effective_mount(self):
        for include_source in (False, True):
            for include_top in (False, True):
                bus, cal = commissioning_bus(), factory_calib()
                if not include_source:
                    bus = {}
                    cal.pop("imu_source")
                cal["calibration"].update(imu_mount_verified=True,imu_bus_profile="qinmo")
                if include_top:
                    cal["imu_mount"] = {"quat":[1,0,0,0],"verified":True}
                backend = self.backend(bus=bus,calib=cal)
                self.assertFalse(backend.view()["mount"]["verified"])
                self.assertTrue(backend.view()["mount_protocol_mismatch"])
                self.assertIn("尚未连接", backend.view()["profile_error"])
                with self.assertRaises(Refused):
                    backend._coarse_guard(bus)
                # Truly absent old-server profile fields retain legacy behavior.
                del cal["calibration"]["imu_bus_profile"]
                self.assertTrue(mount_of(bus,cal)[1]["verified"])

    def test_profile_metadata_binding_context_and_pending(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus.update(imu_bus=copy.deepcopy(INFO), configured_imu_profile="qinmo")
        cal["calibration"]["imu_mount_verified"] = True
        backend = self.backend(bus=bus, calib=cal)
        self.assertEqual(bus_imu_of(bus), INFO)
        self.assertFalse(mount_of(bus, cal)[1]["verified"])
        cal["calibration"]["imu_bus_profile"] = "qinmo"
        self.assertTrue(mount_of(bus, cal)[1]["verified"])
        backend.view()
        backend.last_result = {"ok": True}
        backend.rd.bus.value["imu_bus"]["profile"] = "legacy"
        backend.view()
        self.assertIsNone(backend.last_result)
        commit.save_pending(self.tmp.name, "bus", [1,0,0,0], imu_bus=INFO)
        pending = commit.load_pending(self.tmp.name)
        self.assertEqual(pending["imu_bus"]["profile"], "qinmo")
        self.assertFalse(commit.pending_matches(pending, "bus", backend.rd.bus.value))

    def test_configured_without_discovery_invalidates_mount_and_supports_recovery(self):
        bus, cal = commissioning_bus(), factory_calib()
        bus.update(mode="motion", phase="waiting_for_bus", configured_imu_profile="qinmo")
        cal["calibration"].update(imu_mount_verified=True, imu_bus_profile="qinmo")
        backend = self.backend(bus=bus, calib=cal)
        self.assertFalse(backend.view()["mount"]["verified"])
        self.assertEqual(backend.view()["configured_imu_profile"], "qinmo")
        bus.pop("configured_imu_profile")
        cal["calibration"].pop("imu_bus_profile")
        self.assertTrue(mount_of(bus, cal)[1]["verified"], "old-server legacy fallback")

    def test_builders_preserve_profile_and_refuse_unknown(self):
        cal = current_calibration()
        cal.update(imu_bus_profile="qinmo", imu_bus_protocol="feetech")
        for module in (commit, H):
            built = module.build_calibration(cal, joints_payload(), {"source":"bus", "quat":[1,0,0,0]})
            self.assertEqual(built["imu_bus_profile"], "qinmo")
            module.validate_calibration(built, "bus")
            self.assertIn('imu_bus_profile = "qinmo"', module.render_calibration(built))
            bad = dict(built, imu_bus_profile="unknown")
            with self.assertRaises(module.CalibError):
                module.validate_calibration(bad, "bus")

    def test_page_selection_uses_fixed_helper_request_and_clears_pending(self):
        from studio import helper
        bus = commissioning_bus()
        bus["configured_imu_profile"] = "legacy"
        backend = self.backend(bus=bus, calib=factory_calib())
        commit.save_pending(self.tmp.name, "bus", [1,0,0,0])
        with mock.patch.object(helper, "available", return_value=True), mock.patch.object(helper, "imu_recalibrate", return_value=(True,"imu_entered",{})) as call:
            result = asyncio.run(backend.handle({"op":"profile-select", "profile":"qinmo", "confirmed":True}, "test"))
        self.assertTrue(result["ok"])
        self.assertEqual(call.call_args.kwargs["profile"], "qinmo")
        self.assertIsNone(commit.load_pending(self.tmp.name))

    def test_old_pending_does_not_apply_to_qinmo_or_missing_discovery(self):
        old = {"source":"bus", "quat":[1,0,0,0]}
        self.assertFalse(commit.pending_matches(old, "bus", {"imu_bus":INFO}))
        self.assertFalse(commit.pending_matches(old, "bus", {"configured_imu_profile":"qinmo"}))

    def test_pending_missing_profile_keeps_legacy_semantics_and_updates_block_sessions(self):
        from studio import helper
        info = {"protocol":"feetech", "board":"ft6", "identity":[1]}
        old = {"source":"bus", "imu_bus":info}
        self.assertTrue(commit.pending_matches(old,"bus",{"imu_bus":dict(info,profile="legacy",gyro_dps_per_lsb=.0175)}))
        backend = self.backend()
        with mock.patch.object(helper,"imu_redo_state",return_value={"active":True}):
            self.assertTrue(backend.blocks_updates())


class ProfileWorld(RedoWorld):
    def __init__(self, root):
        super().__init__(root)
        self.exec_override = "/opt/robot/robotd --params " + CONFIG + " --socket /run/robotd.sock"
        self.capability = True
        self.discovered = True
        self.config_readback = None

    def _rpc(self, method, params=None):
        bus = super()._rpc(method, params)
        if method == "robot.busStatus" and self.capability:
            import tomllib
            profile = tomllib.loads(self.path(CONFIG).read_text())["bus"].get("imu_profile", "legacy")
            bus["configured_imu_profile"] = self.config_readback or profile
            if self.discovered:
                bus["imu_bus"] = dict(INFO, profile=profile, board="qinmo" if profile == "qinmo" else "ft6")
            elif self.live_mode == "commissioning":
                bus["phase"] = "waiting_for_bus"
            if self.live_mode == "startup":
                bus.update(mode="motion", phase="waiting_for_bus")
                bus.pop("native")
        return bus

    def run(self, argv):
        result = super().run(argv)
        if argv[:2] == ["systemctl", "daemon-reload"]:
            self.effective_commissioning = self.path(OVERRIDE).exists() or self.path(H.COMMISSIONING_DROPIN).exists()
        return result


class QinmoProfileTest(ImuRedoTest):
    def setUp(self):
        super().setUp()
        # Reuse the base fixture's already-populated fake root; constructing a
        # second World would recreate its non-idempotent systemd directory.
        self.w.__class__ = ProfileWorld
        self.w.robot.rpc = self.w._rpc
        self.w.exec_override = "/opt/robot/robotd --params " + CONFIG + " --socket /run/robotd.sock"
        self.w.capability, self.w.discovered, self.w.config_readback = True, True, None
        self.config_old = ('feetech_calibration="' + H.CALIB + '"\n').encode() + b'[bus]\nprotocol="feetech"\nimu_protocol="auto"\nport="/dev/ttyS2"\n[future]\nkeep=[1,2,3]\n'
        self.w.path(CONFIG).write_bytes(self.config_old)
        self.w.path(SAVED).write_bytes(self.config_old + b'# saved\n')

    def select(self, profile="qinmo"):
        return self.call_redo(profile=profile)

    def test_select_persists_only_profile_and_protocol_in_both_configs(self):
        import tomllib
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        for path in (CONFIG, SAVED):
            expected = tomllib.loads(self.config_old.decode())
            expected["bus"].update(imu_profile="qinmo", imu_protocol="feetech")
            self.assertEqual(tomllib.loads(self.w.path(path).read_text()), expected)
        self.assertEqual(self.w.live_mode, "commissioning")
        self.assertEqual(self.manifest()["profile"], "qinmo")
        self.assertEqual(self.w.units["padd"], "inactive")

    def test_cancel_after_reboot_restores_exact_configs_and_calibration(self):
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.w.units["padd"] = "active"
        code, detail = self.call_redo("cancel", session_id=detail["session_id"])
        self.assertEqual(code, H.EXIT_OK, detail)
        if detail.get("original_mode") == "startup":
            self.assertIn("标定模式", detail["reason"])
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)
        self.assertEqual(self.w.path(SAVED).read_bytes(), self.config_old + b'# saved\n')
        self.assertEqual(self.path.read_bytes(), self.old)

    def test_unknown_old_daemon_wrong_path_and_conflict_refuse_before_writes(self):
        for profile in ("arbitrary", "qinmo;reboot", ""):
            code, _ = self.select(profile)
            self.assertEqual(code, H.EXIT_ARGS)
        self.w.capability = False
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.w.capability = True
        self.w.exec_override = "/opt/robot/robotd --params /tmp/caller.toml"
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)
        self.assertFalse(self.w.path(OVERRIDE).exists())

    def test_supported_precontrol_recovery_reconnects_commissioning(self):
        self.w.live_mode = "startup"
        self.w.discovered = False
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.w.live_mode, "commissioning")

    def test_precontrol_cancel_lands_in_factory_and_allows_new_selection_finish(self):
        self.w.live_mode = "startup"
        self.w.discovered = False
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        code, detail = self.call_redo("cancel", session_id=detail["session_id"])
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)
        self.assertFalse(self.manifest()["active"])
        self.assertFalse(self.w.path(OVERRIDE).exists())
        self.assertTrue(self.w.path(H.COMMISSIONING_DROPIN).exists())
        self.assertIn("标定模式", detail["reason"])
        self.assertEqual(self.w.live_mode, "commissioning")
        self.w.discovered = True
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.verify_qinmo()
        code, detail = self.call_redo("finish", session_id=detail["session_id"], source="bus", quat=[.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.w.live_mode, "commissioning")

    def test_commit_refuses_profile_mismatch_or_unverified_qinmo(self):
        self.w.path(CONFIG).write_bytes(self.config_old.replace(b'imu_protocol="auto"', b'imu_protocol="feetech"\nimu_profile="qinmo"'))
        for binding, verified in ((None, True), ("qinmo", False)):
            cal = dict(self.baseline, imu_mount_verified=verified)
            if binding:
                cal["imu_bus_profile"] = binding
            self.path.write_text(H.render_calibration(cal), encoding="utf-8")
            code, _ = self.call(self.payload(dry=True), verb="calib-commit")
            self.assertEqual(code, H.EXIT_STATE, self.last())

    def test_helper_commit_rejects_explicit_unknown_profile_without_configured_field(self):
        self.w.capability = False
        self.w.bus_mutate = lambda bus: bus.update(imu_bus={"protocol":"feetech","profile":"future","board":"ft6","identity":[1]})
        code, _ = self.call(self.payload(dry=True),verb="calib-commit")
        self.assertEqual(code,H.EXIT_STATE,self.last())

    def test_helper_redo_rejects_explicit_unknown_profile_without_configured_field(self):
        self.w.capability = False
        self.w.bus_mutate = lambda bus: bus.update(imu_bus={"protocol":"feetech","profile":"future","board":"ft6","identity":[1]})
        code, detail = self.call_redo()
        self.assertEqual(code,H.EXIT_STATE,detail)
        self.assertFalse(self.w.path(OVERRIDE).exists())

    def test_helper_commit_and_readback_reject_all_malformed_present_metadata(self):
        self.w.capability = False
        for raw in INVALID_METADATA:
            with self.subTest(raw=raw):
                self.w.bus_mutate = lambda bus, raw=raw: bus.update(copy.deepcopy(raw))
                code, _ = self.call(self.payload(dry=True),verb='calib-commit')
                self.assertEqual(code,H.EXIT_STATE)
                op = H.Op(CalibCtx(self.w,b'{}'),'imu-recalibrate')
                with self.assertRaises(H.Stop):
                    H.imu_redo_readback(op,self.baseline,'bus')
                with self.assertRaises(H.Stop):
                    H.imu_redo_readback(op,self.baseline,'bus',[1,0,0,0])

    def test_ordinary_redo_entry_refuses_unknown_protocol_and_configured_profile(self):
        self.w.capability = False
        for raw in (INVALID_METADATA[1], INVALID_METADATA[8]):
            with self.subTest(raw=raw):
                self.w.bus_mutate = lambda bus, raw=raw: bus.update(copy.deepcopy(raw))
                code, detail = self.call_redo()
                if code == H.EXIT_OK:
                    self.w.bus_mutate = None
                    self.call_redo('cancel',session_id=detail['session_id'])
                self.assertEqual(code,H.EXIT_STATE)
                self.assertFalse(self.w.path(OVERRIDE).exists())

    def test_ordinary_commit_readback_rejects_metadata_becoming_invalid_after_restart(self):
        self.w.capability = False
        def mutate(bus):
            if any(call[:3] == ['systemctl','restart','robotd'] for call in self.w.calls):
                bus.update(imu_bus={'protocol':'future','profile':'legacy'})
        self.w.bus_mutate = mutate
        code, _ = self.call(self.payload(dry=False),verb='calib-commit')
        self.assertNotEqual(code,H.EXIT_OK,self.last())

    def test_ordinary_redo_finish_refuses_invalid_raw_metadata_before_writes(self):
        self.w.capability = False
        session = self.enter()
        self.verified()
        before = self.path.read_bytes()
        self.w.bus_mutate = lambda bus: bus.update(configured_imu_profile='future')
        code, detail = self.call_redo('finish',session_id=session,source='bus',quat=[.5]*4)
        self.assertEqual(code,H.EXIT_STATE,detail)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertTrue(self.w.path(OVERRIDE).exists())

    def test_restart_failure_rolls_back_config(self):
        self.w.restart_failures = 1
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_FAIL, detail)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)

    def verify_qinmo(self):
        self.verified()
        for path in (self.path, self.saved):
            text = path.read_text(encoding="utf-8").replace("imu_mount_verified = false", "imu_mount_verified = true")
            path.write_text('imu_bus_profile="qinmo"\nimu_bus_protocol="feetech"\n' + text, encoding="utf-8")

    def test_finish_requires_binding_then_persists_selected_profile(self):
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        session = detail["session_id"]
        self.verified()
        self.assertEqual(self.call_redo("finish", session_id=session, source="bus", quat=[.5]*4)[0], H.EXIT_STATE)
        self.verify_qinmo()
        code, detail = self.call_redo("finish", session_id=session, source="bus", quat=[.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertIn('imu_profile = "qinmo"', self.w.path(CONFIG).read_text())
        self.assertFalse(self.manifest()["active"])

    def test_selection_invalidates_even_a_previous_matching_saved_mount(self):
        self.old = ('imu_bus_profile="qinmo"\n' + self.old.decode()).encode()
        self.path.write_bytes(self.old)
        self.saved.write_bytes(self.old)
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        import tomllib
        self.assertFalse(tomllib.loads(self.path.read_text())["imu_mount_verified"])
        code, _ = self.call_redo("finish", session_id=detail["session_id"], source="bus", quat=[1,0,0,0])
        self.assertEqual(code, H.EXIT_STATE)

    def test_changed_selected_config_prevents_finish(self):
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.verify_qinmo()
        self.w.path(SAVED).write_bytes(self.w.path(SAVED).read_bytes() + b'\n[unexpected]\nvalue=true\n')
        code, _ = self.call_redo("finish", session_id=detail["session_id"], source="bus", quat=[.5]*4)
        self.assertEqual(code, H.EXIT_STATE)

    def test_precontrol_factory_landing_is_persisted_before_owned_override_removal(self):
        self.w.live_mode = "startup"
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        real = H.remove
        def check(ctx, path):
            if path == OVERRIDE:
                self.assertTrue(self.w.path(H.COMMISSIONING_DROPIN).exists())
            return real(ctx,path)
        with mock.patch.object(H,"remove",side_effect=check):
            code, detail = self.call_redo("cancel",session_id=detail["session_id"])
        self.assertEqual(code,H.EXIT_OK,detail)

    def test_factory_finish_remains_commissioning_for_existing_firstboot_commit(self):
        self.w.path(H.COMMISSIONING_DROPIN).write_text("[Service]\nExecStart=\n", encoding="utf-8")
        self.w.effective_commissioning = True
        self.w.live_mode = "commissioning"
        self.w.commissioning_dropin = True
        # Factory calibration is not motion-enabled yet.
        self.old = self.old.replace(b'motion_enabled = true', b'motion_enabled = false')
        self.path.write_bytes(self.old)
        self.saved.write_bytes(self.old)
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        self.verify_qinmo()
        code, detail = self.call_redo("finish", session_id=detail["session_id"], source="bus", quat=[.5]*4)
        self.assertEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.w.live_mode, "commissioning")
        self.assertTrue(self.w.path(H.COMMISSIONING_DROPIN).exists())
        self.assertFalse(self.manifest()["active"])

    def test_factory_cancel_without_discovery_leaves_fresh_selection_available(self):
        self.w.path(H.COMMISSIONING_DROPIN).write_text("[Service]\nExecStart=\n",encoding="utf-8")
        self.w.effective_commissioning = self.w.commissioning_dropin = True
        self.w.live_mode = "commissioning"
        self.w.discovered = False
        code, detail = self.select()
        self.assertEqual(code,H.EXIT_OK,detail)
        code, detail = self.call_redo('cancel',session_id=detail['session_id'])
        self.assertEqual(code,H.EXIT_OK,detail)
        self.assertFalse(self.manifest()['active'])
        self.assertEqual(self.select()[0],H.EXIT_OK)

    def test_quoted_image_toml_preserves_inline_policy_values(self):
        raw = ('"feetech_calibration"="' + H.CALIB + '"\n').encode() + b'["bus"]\n"protocol"="feetech"\n"imu_protocol"="auto"\n["policy"]\n"skill"=[{name="a",values=[1,2]}, {name="b"}]\n'
        self.w.path(CONFIG).write_bytes(raw)
        self.w.path(SAVED).write_bytes(raw)
        code, detail = self.select()
        self.assertEqual(code, H.EXIT_OK, detail)
        import tomllib
        self.assertEqual(tomllib.loads(self.w.path(CONFIG).read_text())["policy"], tomllib.loads(raw.decode())["policy"])

    def test_lock_active_control_and_readonly_refused_before_mutation(self):
        self.w.locks.add(H.SERVICE_LOCK)
        self.assertEqual(self.select()[0], H.EXIT_BUSY)
        self.w.locks.clear()
        self.w.bus_mutate = lambda bus: bus["native"].update(torque_state_confirmed=True)
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.w.bus_mutate = None
        self.w.exec_override += " --read-only"
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)

    def test_latched_voice_is_excluded_and_prior_service_state_restored(self):
        self.w.units['duck-echo'] = 'active'
        def voice_can_enable(bus):
            if self.w.units['padd'] == 'inactive' and self.w.units['duck-echo'] == 'active':
                bus['native']['torque_state_confirmed'] = True
        self.w.bus_mutate = voice_can_enable
        code, detail = self.select()
        self.assertEqual(code,H.EXIT_OK,detail)
        self.assertEqual(self.w.units['duck-echo'],'inactive')
        self.assertTrue(self.manifest()['controllers']['duck_echo'])
        self.w.units['duck-echo'] = 'active'  # reboot may have restarted the service
        code, detail = self.call_redo('cancel',session_id=detail['session_id'])
        self.assertEqual(code,H.EXIT_OK,detail)
        self.assertEqual(self.w.units['duck-echo'],'active')

    def test_failed_saved_write_and_runtime_readback_restore_original(self):
        real = H._write_preserving
        def fail_once(op, path, data, *args):
            if path == SAVED and b'imu_profile' in data:
                raise OSError("injected saved write failure")
            return real(op, path, data, *args)
        with mock.patch.object(H, "_write_preserving", side_effect=fail_once):
            code, detail = self.select()
        self.assertEqual(code, H.EXIT_FAIL, detail)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)

    def test_calibration_path_socket_substitution_and_i2c_runtime_refused(self):
        self.w.path(CONFIG).write_bytes(self.config_old.replace(H.CALIB.encode(), b'/tmp/foreign-calibration.toml'))
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.w.path(CONFIG).write_bytes(self.config_old)
        argv = self.w.exec_override
        self.w.exec_override = argv.replace('/run/robotd.sock','/tmp/foreign.sock')
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.w.exec_override = argv
        self.w.bus_mutate = lambda bus: bus['native'].update(imu_source='bno08x')
        self.assertEqual(self.select()[0], H.EXIT_STATE)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)

    def test_stale_loaded_calibration_refused_before_profile_writes(self):
        self.w.runtime_mutate = lambda status: status['calibration']['joints'][0].update(zero_raw=1234)
        code, detail = self.select()
        self.assertEqual(code,H.EXIT_STATE,detail)
        self.assertEqual(self.w.path(CONFIG).read_bytes(),self.config_old)

    def test_runtime_readback_failure_restores_original_config(self):
        def changed(bus):
            if self.w.live_mode == "commissioning":
                self.w.config_readback = "legacy"
        self.w.bus_mutate = changed
        code, detail = self.select()
        self.assertNotEqual(code, H.EXIT_OK, detail)
        self.assertEqual(self.w.path(CONFIG).read_bytes(), self.config_old)

    @unittest.skipUnless(os.name == "posix", "real POSIX file permissions required")
    def test_real_symlink_parent_and_unsafe_write_permissions_are_refused(self):
        op = H.Op(CalibCtx(self.w, b"{}"), "imu-recalibrate")
        target = self.w.path(CONFIG)
        moved = target.with_suffix(".real")
        target.rename(moved)
        target.symlink_to(moved)
        with self.assertRaises(H.Stop):
            H.imu_profile_safe_file(op, CONFIG)
        target.unlink()
        moved.rename(target)
        parent = target.parent
        outside = parent.with_name("actual-config")
        parent.rename(outside)
        parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(H.Stop):
            H.imu_profile_safe_file(op, CONFIG)
        parent.unlink()
        outside.rename(parent)
        if os.geteuid() == 0:
            op.ctx.check_owner = True
            os.chmod(target, 0o666)
            with self.assertRaises(H.Stop):
                H.imu_profile_safe_file(op, CONFIG)
            os.chmod(target, 0o640)
            os.chown(target, 65534, 65534)
            with self.assertRaises(H.Stop):
                H.imu_profile_safe_file(op, CONFIG)
            os.chown(target, 0, 0)
            self.assertEqual(H.imu_profile_safe_file(op, CONFIG), self.config_old)


class QinmoHttpTest(HttpTest):
    async def test_profile_session_excludes_web_control_but_relax_remains_available(self):
        token, _ = await self.login()
        client = WsClient(self.port, origin=self.origin, cookie=token)
        await client.open()
        try:
            with mock.patch("studio.imu.ImuBackend.blocks_updates", return_value=True):
                for index, name in enumerate(("pad.op", "tune.op", "servo.open", "calib.op")):
                    await client.send({"t":"cmd", "id":str(index), "name":name, "args":{"op":"stand"}})
                    await client.pump(until=lambda:any(row.get("id")==str(index) and row.get("t")=="result" for row in client.msgs))
                    result = next(row for row in client.msgs if row.get("id")==str(index) and row.get("t")=="result")
                    self.assertFalse(result["ok"])
                    self.assertIn("IMU", result["reason"])
                await client.send({"t":"cmd", "id":"relax", "name":"relax"})
                await client.pump(until=lambda:any(row.get("id")=="relax" and row.get("t")=="result" for row in client.msgs))
                self.assertTrue(next(row for row in client.msgs if row.get("id")=="relax" and row.get("t")=="result")["ok"])
        finally:
            client.close()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(cls(name) for cls in (QinmoBackendTest, QinmoProfileTest, QinmoHttpTest)
        for name in cls.__dict__ if name.startswith("test_"))

