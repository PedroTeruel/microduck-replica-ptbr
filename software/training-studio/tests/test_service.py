import copy
import json
import tempfile
import time
import unittest
import zipfile
import signal
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from training_studio.config import StudioError, validate_config, validate_profile
from training_studio.commands import build_train_argv, parse_metric
from training_studio.service import StudioService


def wait_for(service, run_id, predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        if predicate(run):
            return run
        time.sleep(0.025)
    raise AssertionError(f"Timed out: {service.get_run(run_id)}")


class ValidationTests(unittest.TestCase):
    def test_smoke_forces_small_honest_test(self):
        cfg = validate_config({"num_envs": 4096, "iterations": 6000}, "smoke")
        self.assertEqual((cfg["num_envs"], cfg["iterations"]), (64, 5))

    def test_config_rejects_bad_types_and_ranges(self):
        for cfg in ({"iterations": True}, {"iterations": 0}, {"num_envs": 999999},
                    {"learning_rate": float("nan")}, {"seed": -1}, {"shell": "x"},
                    {"save_interval": 0}, {"learning_rate": "0.001"}, {"learning_rate": 10 ** 1000}):
            with self.subTest(cfg=cfg), self.assertRaises(StudioError):
                validate_config(cfg, "train")

    def test_profile_accepts_real_schema_and_archives_without_physics_mutation(self):
        profile = {"schema": "microduck-studio-duck-profile/v1", "body": {"total_g": 880},
                   "imu": {"mount_quat_wxyz": [1, 0, 0, 0]}, "joints": None}
        self.assertEqual(validate_profile(profile), profile)

    def test_profile_rejects_unbounded_or_invalid_values(self):
        for p in ({"schema": "other"}, {"schema": "microduck-studio-duck-profile/v1", "body": {"total_g": -3}},
                  {"schema": "microduck-studio-duck-profile/v1", "imu": {"mount_quat_wxyz": [1, 0]}},
                  {"schema": "microduck-studio-duck-profile/v1", "note": "x" * 70000},
                  {"schema": "microduck-studio-duck-profile/v1", "duck": {"label": float("inf")}}):
            with self.subTest(profile=str(p)[:100]), self.assertRaises(StudioError):
                validate_profile(p)

    def test_profile_rejects_boolean_direction_and_bad_voltage(self):
        for p in ({"joints": [{"id": 1, "direction": True}]}, {"voltage": {"volts": -12}},
                  {"imu": {"verified": "yes"}}, {"duck": {"label": 10 ** 1000}}):
            with self.subTest(profile=str(p)[:60]), self.assertRaises(StudioError):
                validate_profile({"schema": "microduck-studio-duck-profile/v1", **p})

    def test_real_command_uses_frozen_numeric_flags_and_exact_checkpoint(self):
        run = {"id": "abc123", "recipe_id": "hd1910-flat", "task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910",
               "config": validate_config({}, "smoke")}
        argv = build_train_argv(run, Path("/engine"), Path("/engine/logs/rsl_rl/microduck_hd1910_velocity/2026_studio_source/model_4.pt"))
        self.assertEqual(argv[:4], ["uv", "run", "--frozen", "--no-sync"])
        self.assertIn("--agent.load-run", argv)
        self.assertEqual(argv[argv.index("--agent.load-run") + 1], "^2026_studio_source$")
        self.assertEqual(argv[argv.index("--agent.load-checkpoint") + 1], r"^model_4\.pt$")
        self.assertEqual(argv[argv.index("--agent.resume") + 1], "True")
        self.assertNotIn("--hf-jobs", argv)

    def test_command_builder_itself_rejects_injected_numeric_values(self):
        run = {"id": "abc123", "recipe_id": "hd1910-flat", "task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910",
               "kind": "train", "config": {**validate_config({}, "train"), "iterations": "5 --hf-jobs"}}
        with self.assertRaises(StudioError):
            build_train_argv(run, Path("/engine"))

    def test_metrics_come_from_actual_engine_lines(self):
        metric = {}
        for line in ("Learning iteration 4/500", "Mean reward: 18.25", "Mean episode length: 70.2", "Computation: 3480 steps/s (collection: 1s)"):
            metric.update(parse_metric(line))
        self.assertEqual(metric, {"iteration": 4, "reward": 18.25, "episode_length": 70.2, "fps": 3480.0})
        self.assertEqual(parse_metric("A normal log line"), {})

    def test_actual_pinned_rsl_rl_fps_label_and_nonfinite_rejection(self):
        self.assertEqual(parse_metric("Steps per second: 3480"), {"fps": 3480.0})
        for line in ("Mean reward: 1e999", "Mean reward: nan", "Mean episode length: inf"):
            with self.subTest(line=line), self.assertRaises(StudioError):
                parse_metric(line)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = StudioService(self.root, self.root / "engine", demo=True, demo_interval=0.07)

    def tearDown(self):
        self.service.shutdown()
        self.tmp.cleanup()

    def create(self, **kwargs):
        return self.service.create_run({"name": "测试", "recipe_id": "hd1910-flat", "kind": "smoke", **kwargs})

    def complete_smoke(self):
        run = self.create()
        return wait_for(self.service, run["id"], lambda r: r["status"] == "completed")

    def test_smoke_subprocess_completes_with_demo_checkpoints(self):
        run = self.complete_smoke()
        self.assertEqual(run["progress"]["iteration"], 5)
        self.assertTrue(run["checkpoints"])
        self.assertTrue(all(c["demo"] and c["name"].endswith(".json") for c in run["checkpoints"]))
        self.assertEqual(len(run["metrics"]), 5)
        self.assertTrue(any("DEMO" in line for line in run["logs"]))

    def test_pause_acknowledges_and_iterations_freeze_then_resume_same_child(self):
        self.complete_smoke()
        run = self.create(kind="train", config={"iterations": 30, "save_interval": 2})
        wait_for(self.service, run["id"], lambda r: r["progress"]["iteration"] >= 2)
        child = self.service.child_pid(run["id"])
        paused = self.service.pause(run["id"])
        self.assertEqual(paused["status"], "paused")
        iteration = paused["progress"]["iteration"]
        time.sleep(0.25)
        self.assertEqual(self.service.get_run(run["id"])["progress"]["iteration"], iteration)
        with self.assertRaises(StudioError):
            self.create()
        resumed = self.service.resume(run["id"], {})
        self.assertEqual(resumed["id"], run["id"])
        self.assertEqual(self.service.child_pid(run["id"]), child)
        wait_for(self.service, run["id"], lambda r: r["progress"]["iteration"] > iteration)

    def test_training_requires_same_recipe_smoke(self):
        with self.assertRaises(StudioError):
            self.create(kind="train")
        self.complete_smoke()
        with self.assertRaises(StudioError):
            self.create(kind="train", recipe_id="hd1910-rough")
        run = self.create(kind="train", config={"iterations": 10})
        self.assertEqual(run["kind"], "train")

    def test_smoke_gate_compares_seed_lr_and_full_canonical_profile(self):
        profile = {"schema": "microduck-studio-duck-profile/v1", "body": {"total_g": 880, "head_g": 100}}
        smoke = self.create(profile=profile)
        wait_for(self.service, smoke["id"], lambda r: r["status"] == "completed")
        for change in ({"config": {"seed": 43}}, {"config": {"learning_rate": 0.002}},
                       {"profile": None}, {"profile": {**profile, "body": {"total_g": 890, "head_g": 100}}}):
            with self.subTest(change=change), self.assertRaises(StudioError):
                self.create(kind="train", **{"profile": profile, **change})
        equivalent = {"body": {"head_g": 100, "total_g": 880}, "schema": profile["schema"]}
        run = self.create(kind="train", profile=equivalent, config={"num_envs": 128, "iterations": 20, "save_interval": 2})
        self.assertIn("smoke_family", run)
        self.assertEqual(run["smoke_family"], self.service.get_run(smoke["id"])["smoke_family"])

    def test_whitespace_name_rejected(self):
        with self.assertRaises(StudioError):
            self.create(name="  \u3000 ")

    def test_smoke_profile_json_distinguishes_boolean_from_number(self):
        profile = {"schema": "microduck-studio-duck-profile/v1", "duck": {"build": {"flag": True}}}
        smoke = self.create(profile=profile)
        wait_for(self.service, smoke["id"], lambda r: r["status"] == "completed")
        changed = {"schema": profile["schema"], "duck": {"build": {"flag": 1}}}
        with self.assertRaises(StudioError):
            self.create(kind="train", profile=changed)

    def test_paused_job_blocks_checkpoint_operations(self):
        smoke = self.complete_smoke()
        run = self.create(kind="train", config={"iterations": 30})
        wait_for(self.service, run["id"], lambda r: r["status"] == "running")
        self.service.pause(run["id"])
        with self.assertRaises(StudioError):
            self.service.operate(smoke["id"], "export", {"checkpoint_id": smoke["checkpoints"][0]["id"]})

    def test_logs_and_metrics_remain_capped(self):
        run = self.complete_smoke()
        with self.service._condition:
            stored = self.service._runs[run["id"]]
            stored["logs"] = [str(i) for i in range(700)]
            stored["metrics"] = [{"iteration": i} for i in range(2500)]
            self.service._save(stored)
        result = self.service.get_run(run["id"])
        self.assertEqual(len(result["logs"]), 400)
        self.assertEqual(len(result["metrics"]), 2000)
        self.assertEqual(result["metrics"][-1]["iteration"], 2499)

    def test_real_log_checkpoints_only_come_from_this_run_directory(self):
        run = self.complete_smoke()
        owned = self.root / "engine/logs/rsl_rl/microduck_hd1910_velocity" / ("2026_studio_" + run["id"])
        foreign = owned.parent / "2026_studio_foreign"
        for folder in (owned, foreign):
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "model_3.pt", "w") as archive:
                archive.writestr("model/data.pkl", b"structural torch-save fixture only")
                archive.writestr("model/version", b"3\n")
        self.service.mode = "real"
        try:
            with self.service._condition:
                stored = self.service._runs[run["id"]]
                stored["checkpoints"] = []
                stored["metrics"] = []
                self.service._real_line(stored, f"[INFO] Logging experiment in directory: {foreign}")
                self.assertFalse(stored["checkpoints"])
                self.service._real_line(stored, f"[INFO] Logging experiment in directory: {owned}")
                self.assertFalse(stored["checkpoints"])
                self.service._scan_checkpoints(stored, complete=True)
                self.assertEqual(len(stored["checkpoints"]), 1)
                self.assertEqual(stored["metrics"], [])
                self.service._real_line(stored, "Learning iteration 3/10")
                self.assertNotIn("reward", stored["metrics"][-1])
        finally:
            self.service.mode = "demo"

    def test_partial_checkpoint_never_advertised_and_complete_file_waits_for_stability(self):
        run = self.complete_smoke()
        folder = self.root / "engine/logs/rsl_rl/microduck_hd1910_velocity" / ("2026_studio_" + run["id"])
        folder.mkdir(parents=True)
        (folder / "model_2.pt").write_bytes(b"PK\x03\x04incomplete")
        with zipfile.ZipFile(folder / "model_3.pt", "w") as archive:
            archive.writestr("model/data.pkl", b"structural torch-save fixture only")
            archive.writestr("model/version", b"3\n")
        self.service.mode = "real"
        try:
            stored = self.service._runs[run["id"]]
            stored["engine_log_dir"] = str(folder)
            stored["checkpoints"] = []
            with patch("training_studio.service.time.monotonic", return_value=10):
                self.service._scan_checkpoints(stored)
            self.assertEqual(stored["checkpoints"], [])
            with patch("training_studio.service.time.monotonic", return_value=12):
                self.service._scan_checkpoints(stored)
            self.assertEqual([c["id"] for c in stored["checkpoints"]], ["model-3"])
            self.service._scan_checkpoints(stored, complete=True)
            self.assertEqual([c["id"] for c in stored["checkpoints"]], ["model-3"])
        finally:
            self.service.mode = "demo"

    def test_operation_read_failure_terminates_before_releasing_child_ownership(self):
        run = self.complete_smoke()
        stored = self.service._runs[run["id"]]
        stored["operation"] = {"kind": "export", "status": "running"}
        class BrokenStream:
            def __iter__(self):
                raise OSError("injected pipe failure")
            def close(self):
                pass
        child = SimpleNamespace(stdout=BrokenStream())
        with patch("training_studio.service.subprocess.Popen", return_value=child), \
             patch.object(self.service, "_start_leader_watcher"), patch.object(self.service, "_terminate") as terminate:
            with self.assertRaises(OSError):
                self.service._operation_child(stored, ["ignored"])
            terminate.assert_called_once_with(child)
        self.assertNotIn(run["id"], self.service._children)

    def test_unreaped_exited_owned_leader_keeps_group_reserved_until_cleanup(self):
        child = SimpleNamespace(pid=12345, returncode=None, poll=lambda: self.fail("Linux must not poll/reap before group cleanup"))
        sent = []
        def wait(**kwargs):
            sent.append("reap")
            child.returncode = 0
            return 0
        child.wait = wait
        def killpg(pid, sig):
            if sig == 0:
                raise ProcessLookupError()
            sent.append((pid, sig))
        with patch("training_studio.service.os.name", "posix"), patch("training_studio.service.os.killpg", side_effect=killpg, create=True), \
             patch("training_studio.service.signal.SIGCONT", 18, create=True):
            self.service._terminate(child)
        self.assertIn((12345, signal.SIGTERM), sent)
        self.assertEqual(sent[-1], "reap")

    def test_reaped_child_never_signals_a_potentially_reused_group(self):
        child = SimpleNamespace(pid=12345, returncode=0)
        with patch("training_studio.service.os.killpg", create=True) as kill:
            self.service._terminate(child)
            kill.assert_not_called()

    def test_linux_exit_observation_never_reaps_leader(self):
        child = SimpleNamespace(pid=12345, returncode=None, poll=lambda: self.fail("must retain leader"))
        with patch("training_studio.service.sys.platform", "linux"), \
             patch("training_studio.service.os.waitid", return_value=SimpleNamespace(si_code=1, si_status=0), create=True) as waitid, \
             patch("training_studio.service.os.P_PID", 1, create=True), \
             patch("training_studio.service.os.WEXITED", 4, create=True), \
             patch("training_studio.service.os.WNOWAIT", 8, create=True), \
             patch("training_studio.service.os.WNOHANG", 1, create=True), \
             patch("training_studio.service.os.CLD_EXITED", 1, create=True):
            self.assertEqual(self.service._peek(child), 0)
            self.assertIsNone(child.returncode)
            self.assertEqual(waitid.call_args.args, (1, 12345, 13))

    def test_real_pause_does_not_signal_an_already_exited_child(self):
        run = self.complete_smoke()
        child = SimpleNamespace(pid=12345, returncode=0, poll=lambda: 0)
        stored = self.service._runs[run["id"]]
        stored["status"] = "running"
        self.service._children[run["id"]] = child
        self.service.mode = "real"
        try:
            with patch("training_studio.service.sys.platform", "linux"), \
                 patch("training_studio.service.os.killpg", create=True) as kill, \
                 patch("training_studio.service.os.waitid", return_value=None, create=True), \
                 patch("training_studio.service.signal.SIGSTOP", 19, create=True), \
                 patch("training_studio.service.os.P_PID", 1, create=True), \
                 patch("training_studio.service.os.WSTOPPED", 2, create=True):
                with self.assertRaises(StudioError):
                    self.service.pause(run["id"])
                kill.assert_not_called()
        finally:
            self.service.mode = "demo"
            self.service._children.pop(run["id"], None)
            stored["status"] = "completed"

    def test_real_pause_waits_for_matching_kernel_ack_and_uses_nonblocking_flag(self):
        run = self.complete_smoke()
        child = SimpleNamespace(pid=12345, returncode=None, poll=lambda: None)
        stored = self.service._runs[run["id"]]
        stored["status"] = "running"
        self.service._children[run["id"]] = child
        self.service.mode = "real"
        try:
            with patch("training_studio.service.sys.platform", "linux"), \
                 patch.object(self.service, "_peek", return_value=None), \
                 patch("training_studio.service.os.killpg", create=True), \
                 patch("training_studio.service.os.waitid", side_effect=[SimpleNamespace(si_pid=99), SimpleNamespace(si_pid=12345)], create=True) as waitid, \
                 patch("training_studio.service.signal.SIGSTOP", 19, create=True), \
                 patch("training_studio.service.os.P_PID", 1, create=True), \
                 patch("training_studio.service.os.WSTOPPED", 2, create=True), \
                 patch("training_studio.service.os.WNOHANG", 1, create=True):
                self.assertEqual(self.service.pause(run["id"])["status"], "paused")
                self.assertEqual(waitid.call_count, 2)
                self.assertEqual(waitid.call_args.args, (1, 12345, 3))
        finally:
            self.service.mode = "demo"
            self.service._children.pop(run["id"], None)
            stored["status"] = "completed"

    def test_real_pause_timeout_is_bounded_and_attempts_resume(self):
        run = self.complete_smoke()
        child = SimpleNamespace(pid=12345, returncode=None, poll=lambda: None)
        stored = self.service._runs[run["id"]]
        stored["status"] = "running"
        self.service._children[run["id"]] = child
        self.service.mode = "real"
        try:
            with patch("training_studio.service.sys.platform", "linux"), \
                 patch.object(self.service, "_peek", return_value=None), \
                 patch("training_studio.service.os.killpg", create=True) as kill, \
                 patch("training_studio.service.os.waitid", return_value=None, create=True), \
                 patch("training_studio.service.time.monotonic", side_effect=[0, 4]), \
                 patch("training_studio.service.signal.SIGSTOP", 19, create=True), \
                 patch("training_studio.service.signal.SIGCONT", 18, create=True), \
                 patch("training_studio.service.os.P_PID", 1, create=True), \
                 patch("training_studio.service.os.WSTOPPED", 2, create=True), \
                 patch("training_studio.service.os.WNOHANG", 1, create=True):
                with self.assertRaises(StudioError):
                    self.service.pause(run["id"])
                self.assertEqual([call.args for call in kill.call_args_list], [(12345, 19), (12345, 18)])
                self.assertEqual(stored["status"], "running")
        finally:
            self.service.mode = "demo"
            self.service._children.pop(run["id"], None)
            stored["status"] = "completed"

    def test_real_control_signals_hold_child_cleanup_lock(self):
        run = self.complete_smoke()
        child = SimpleNamespace(pid=12345, returncode=None)
        stored = self.service._runs[run["id"]]
        stored["status"] = "running"
        self.service._children[run["id"]] = child
        self.service.mode = "real"
        def signal_group(pid, sig):
            self.assertTrue(self.service._process_lock(child)._is_owned(), "signal and liveness must share cleanup lock")
        try:
            with patch("training_studio.service.sys.platform", "linux"), \
                 patch.object(self.service, "_peek", return_value=None), \
                 patch("training_studio.service.os.killpg", side_effect=signal_group, create=True), \
                 patch("training_studio.service.os.waitid", return_value=SimpleNamespace(si_pid=12345), create=True), \
                 patch("training_studio.service.signal.SIGSTOP", 19, create=True), \
                 patch("training_studio.service.signal.SIGCONT", 18, create=True), \
                 patch("training_studio.service.os.P_PID", 1, create=True), \
                 patch("training_studio.service.os.WSTOPPED", 2, create=True), \
                 patch("training_studio.service.os.WNOHANG", 1, create=True):
                self.service.pause(run["id"])
                self.service.resume(run["id"], {})
        finally:
            self.service.mode = "demo"
            self.service._children.pop(run["id"], None)
            stored["status"] = "completed"

    def test_environment_refresh_is_explicit_while_state_uses_cache(self):
        with patch("training_studio.service.inspect_environment", return_value={"ready": False, "checks": [], "pause_supported": False}) as inspect:
            self.service.state()
            inspect.assert_not_called()
            result = self.service.refresh_environment()
            inspect.assert_called_once()
            self.assertFalse(result["ready"])

    def test_export_embeds_checkpoint_evaluation_and_source_provenance(self):
        (self.root / "engine").mkdir()
        source = self.root / "engine/pyproject.toml"
        source.write_text("original training source", encoding="utf-8")
        expected_source_hash = self.service._sha256(source)
        run = self.complete_smoke()
        source.write_text("modified after training", encoding="utf-8")
        checkpoint_id = run["checkpoints"][-1]["id"]
        self.service.operate(run["id"], "evaluate", {"checkpoint_id": checkpoint_id})
        wait_for(self.service, run["id"], lambda r: r.get("operation", {}).get("status") == "completed")
        self.service.operate(run["id"], "export", {"checkpoint_id": checkpoint_id})
        result = wait_for(self.service, run["id"], lambda r: r.get("operation", {}).get("status") == "completed")
        relative = result["checkpoints"][-1]["export_url"].split(f"/{run['id']}/", 1)[1]
        with zipfile.ZipFile(self.service.artifact_path(run["id"], relative)) as archive:
            self.assertIn("evaluation/demo-replay.svg", archive.namelist())
            provenance = json.loads(archive.read("provenance.json"))
            self.assertIn("engine_source", provenance)
            self.assertEqual(provenance["engine_source"]["files_sha256"]["pyproject.toml"], expected_source_hash)

    def test_stop_keeps_checkpoints_and_resume_creates_child(self):
        self.complete_smoke()
        run = self.create(kind="train", config={"iterations": 30, "save_interval": 2})
        run = wait_for(self.service, run["id"], lambda r: len(r["checkpoints"]) >= 1)
        checkpoint = run["checkpoints"][0]
        stopped = self.service.stop(run["id"])
        self.assertEqual(stopped["status"], "stopped")
        self.assertTrue(stopped["checkpoints"])
        with self.assertRaises(StudioError):
            self.service.resume(run["id"], {"checkpoint_id": "foreign"})
        resumed = self.service.resume(run["id"], {"checkpoint_id": checkpoint["id"]})
        self.assertNotEqual(resumed["id"], run["id"])
        self.assertEqual(resumed["parent_id"], run["id"])

    def test_completed_smoke_is_never_resumed_as_formal_training(self):
        run = self.complete_smoke()
        resumed = self.service.resume(run["id"], {"checkpoint_id": run["checkpoints"][-1]["id"]})
        self.assertEqual(resumed["kind"], "smoke")

    def test_long_valid_name_can_resume_without_auto_suffix_overflow(self):
        run = self.create(name="鸭" * 100)
        run = wait_for(self.service, run["id"], lambda r: r["status"] == "completed")
        resumed = self.service.resume(run["id"], {"checkpoint_id": run["checkpoints"][-1]["id"]})
        self.assertLessEqual(len(resumed["name"]), 100)
        self.assertEqual(resumed["parent_id"], run["id"])

    def test_invalid_transitions_and_foreign_checkpoint_rejected(self):
        run = self.complete_smoke()
        for action in (self.service.pause, self.service.stop):
            with self.assertRaises(StudioError):
                action(run["id"])
        with self.assertRaises(StudioError):
            self.service.operate(run["id"], "export", {"checkpoint_id": "foreign"})

    def test_demo_export_zip_contains_provenance_only(self):
        run = self.complete_smoke()
        self.service.operate(run["id"], "export", {"checkpoint_id": run["checkpoints"][-1]["id"]})
        run = wait_for(self.service, run["id"], lambda r: r.get("operation", {}).get("status") == "completed")
        url = run["checkpoints"][-1]["export_url"]
        artifact = self.service.artifact_path(run["id"], url.split(f"/{run['id']}/", 1)[1])
        with zipfile.ZipFile(artifact) as package:
            self.assertIn("provenance.json", package.namelist())
            self.assertFalse(any(n.endswith((".pt", ".onnx")) for n in package.namelist()))

    def test_demo_evaluation_is_explicitly_marked_preview(self):
        run = self.complete_smoke()
        self.service.operate(run["id"], "evaluate", {"checkpoint_id": run["checkpoints"][-1]["id"]})
        run = wait_for(self.service, run["id"], lambda r: r.get("operation", {}).get("status") == "completed")
        self.assertTrue(run["checkpoints"][-1]["video_url"].endswith(".svg"))

    def test_profile_saved_and_not_applied_to_config(self):
        profile = {"schema": "microduck-studio-duck-profile/v1", "body": {"total_g": 910}}
        run = self.create(profile=profile)
        self.assertEqual(run["profile"], profile)
        self.assertNotIn("body", run["config"])
        self.assertFalse(run["profile_summary"]["applied_to_physics"])

    def test_atomic_persistence_and_restart_marks_active_interrupted(self):
        run = self.complete_smoke()
        stored = json.loads((self.root / "runs" / run["id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["status"], "completed")
        stale = copy.deepcopy(stored)
        stale["status"] = "paused"
        (self.root / "runs" / run["id"] / "run.json").write_text(json.dumps(stale), encoding="utf-8")
        second = StudioService(self.root, self.root / "engine", demo=True)
        try:
            self.assertEqual(second.get_run(run["id"])["status"], "interrupted")
            self.assertIsNone(second.child_pid(run["id"]))
        finally:
            second.shutdown()

    def test_artifacts_reject_traversal_absolute_and_unregistered_files(self):
        run = self.complete_smoke()
        for bad in ("../run.json", "/etc/passwd", "run.json", "..\\run.json", "C:/secret"):
            with self.subTest(path=bad), self.assertRaises(StudioError):
                self.service.artifact_path(run["id"], bad)

    def test_shutdown_stops_paused_owned_child(self):
        run = self.create()
        wait_for(self.service, run["id"], lambda r: r["status"] == "running")
        self.service.pause(run["id"])
        self.service.shutdown()
        self.assertEqual(self.service.get_run(run["id"])["status"], "stopped")
        self.assertIsNone(self.service.child_pid(run["id"]))

    def test_real_mode_fails_closed_without_prerequisites(self):
        real = StudioService(self.root / "real", self.root / "missing", demo=False)
        try:
            self.assertFalse(real.environment()["ready"])
            with self.assertRaises(StudioError):
                real.create_run({"kind": "smoke", "recipe_id": "hd1910-flat"})
        finally:
            real.shutdown()


if __name__ == "__main__":
    unittest.main()
