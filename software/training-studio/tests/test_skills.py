import importlib.util
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from training_studio import commands, config
from training_studio.config import StudioError
from training_studio.service import StudioService


RECIPE = "hd1910-single-leg"
TASK = "Mjlab-Balance-Flat-MicroDuck-HD1910"
EXPERIMENT = "microduck_hd1910_balance"
SKILL = {"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}


def wait_for(service, run_id, operation=False):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        status = run.get("operation", {}).get("status") if operation else run["status"]
        if status in ("completed", "failed"):
            if status != "completed":
                raise AssertionError(run)
            return run
        time.sleep(0.02)
    raise AssertionError(service.get_run(run_id))


class SkillValidationTests(unittest.TestCase):
    def validate(self, value=None, recipe=RECIPE):
        self.assertTrue(hasattr(config, "validate_skill"), "skill validation is missing")
        return config.validate_skill(recipe, value)

    def test_recipe_exposes_balance_defaults_and_limits(self):
        self.assertIn(RECIPE, config.RECIPE_BY_ID)
        recipe = config.RECIPE_BY_ID[RECIPE]
        self.assertEqual(recipe["task_id"], TASK)
        self.assertEqual(recipe["experiment_name"], EXPERIMENT)
        self.assertEqual(recipe["skill_defaults"], SKILL)
        self.assertEqual(recipe["skill_limits"]["lift_height_m"], {"min": .005, "max": .02, "step": .005})
        self.assertEqual(recipe["skill_limits"]["hold_seconds"], {"min": 1, "max": 5, "step": 1})
        self.assertEqual(recipe["defaults"]["num_envs"], 256)
        self.assertEqual(recipe["defaults"]["save_interval"], 25)

    def test_normalizes_defaults_and_independent_parameter_choices(self):
        self.assertEqual(self.validate(), SKILL)
        self.assertEqual(self.validate({"support_side": "right", "hold_seconds": 5}), {**SKILL, "support_side": "right", "hold_seconds": 5.0})
        for height in (.005, .02):
            self.assertEqual(self.validate({"lift_height_m": height})["lift_height_m"], height)
        self.assertIsNone(self.validate(None, "hd1910-flat"))

    def test_rejects_unknown_nonfinite_boolean_and_out_of_range_fields(self):
        bad = [[], "left", False, {"extra": 1}, {"support_side": "LEFT"}, {"support_side": []}]
        for field, values in (("lift_height_m", (True, "0.01", .004, .021, float("inf"), float("nan"), 10 ** 1000)),
                              ("hold_seconds", (False, 0, 6, float("nan"), "3"))):
            bad.extend({field: value} for value in values)
        for value in bad:
            with self.subTest(value=str(value)[:80]):
                self.assertTrue(hasattr(config, "validate_skill"), "skill validation is missing")
                with self.assertRaises(StudioError):
                    config.validate_skill(RECIPE, value)
        for recipe in ("hd1910-flat", "hd1910-rough", "unknown"):
            with self.subTest(recipe=recipe):
                self.assertTrue(hasattr(config, "validate_skill"), "skill validation is missing")
                with self.assertRaises(StudioError):
                    config.validate_skill(recipe, {})

    def test_builder_uses_whitelisted_task_experiment_and_typed_flags(self):
        run = {"id": "abc123", "recipe_id": RECIPE, "task_id": TASK, "config": {}, "kind": "train", "skill": {**SKILL, "support_side": "right"}}
        self.assertTrue(hasattr(commands, "experiment_for"), "recipe experiment whitelist is missing")
        self.assertEqual(commands.experiment_for(run), EXPERIMENT)
        argv = commands.build_train_argv(run, Path("/engine"))
        for flag, value in (("--env.commands.twist.support-side", "right"), ("--env.commands.twist.lift-height-m", "0.01"), ("--env.commands.twist.hold-seconds", "3.0"), ("--env.scene.num-envs", "256")):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        for changed in ({"task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910"}, {"recipe_id": "unknown"}, {"skill": {"hold_seconds": True}}):
            with self.subTest(changed=changed), self.assertRaises(StudioError):
                commands.build_train_argv({**run, **changed}, Path("/engine"))
        wrong = Path("/engine/logs/rsl_rl/microduck_hd1910_velocity/source/model_4.pt")
        with self.assertRaises(StudioError):
            commands.build_train_argv(run, Path("/engine"), wrong)
        right = Path("/engine/logs/rsl_rl") / EXPERIMENT / "source/model_4.pt"
        self.assertIn("--agent.load-checkpoint", commands.build_train_argv(run, Path("/engine"), right))

    def test_archived_command_contract_matches_engine_helper(self):
        path = Path(__file__).resolve().parents[2] / "training/src/mjlab_microduck/balance_parameters.py"
        spec = importlib.util.spec_from_file_location("studio_engine_balance_contract", path)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        for side in ("left", "right"):
            skill = {**SKILL, "support_side": side, "hold_seconds": 5.0}
            self.assertEqual(config.skill_command_contract(skill), engine.balance_command_contract(skill))


class SkillServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = StudioService(self.root, self.root / "engine", demo=True, demo_interval=.015)

    def tearDown(self):
        self.service.shutdown()
        self.temporary.cleanup()

    def create(self, **extra):
        self.assertIn(RECIPE, config.RECIPE_BY_ID, "balance recipe is missing")
        return self.service.create_run({"recipe_id": RECIPE, "kind": "smoke", **extra})

    def smoke(self, **extra):
        run = self.create(**extra)
        return wait_for(self.service, run["id"])

    def test_real_demo_process_saves_skill_and_gate_rejects_changed_targets(self):
        smoke = self.smoke(skill={"support_side": "right"})
        self.assertEqual(smoke["skill"], {**SKILL, "support_side": "right"})
        self.assertEqual(smoke["config"]["num_envs"], 64)
        self.assertEqual(smoke["config"]["save_interval"], 1)
        self.assertEqual(smoke["config"]["iterations"], 5)
        self.assertEqual(json.loads((self.root / "runs" / smoke["id"] / "skill.json").read_text()), smoke["skill"])
        for skill in ({"support_side": "left"}, {"support_side": "right", "hold_seconds": 4}, {"support_side": "right", "lift_height_m": .015}):
            with self.subTest(skill=skill), self.assertRaises(StudioError):
                self.create(kind="train", skill=skill)
        train = self.create(kind="train", skill=smoke["skill"])
        self.assertEqual(train["config"]["num_envs"], 256)
        self.assertEqual(train["config"]["save_interval"], 25)
        self.assertEqual(train["config"]["iterations"], 1000)
        self.assertEqual(train["smoke_family"], smoke["smoke_family"])

    def test_invalid_input_never_creates_record_or_child(self):
        for payload in ({"recipe_id": RECIPE, "skill": {"lift_height_m": True}}, {"recipe_id": RECIPE, "skill": {"support_side": "$(touch bad)"}}, {"recipe_id": "hd1910-flat", "skill": {}}):
            with self.subTest(payload=payload), patch("training_studio.service.subprocess.Popen") as spawn:
                with self.assertRaises(StudioError):
                    self.service.create_run(payload)
                spawn.assert_not_called()
        self.assertFalse(self.service.state()["runs"])

    def test_resume_and_demo_bundle_keep_skill_and_honest_evidence(self):
        run = self.smoke(skill={"support_side": "right", "hold_seconds": 2})
        cp_id = run["checkpoints"][-1]["id"]
        self.service.operate(run["id"], "evaluate", {"checkpoint_id": cp_id})
        evaluated = wait_for(self.service, run["id"], operation=True)
        summary = evaluated["checkpoints"][-1]["evaluation_summary"]
        self.assertTrue(summary["demo"])
        self.assertEqual(summary["skill"], run["skill"])
        self.assertNotIn("success_rate", summary)
        self.assertNotIn("successes", summary)
        self.service.operate(run["id"], "export", {"checkpoint_id": cp_id})
        exported = wait_for(self.service, run["id"], operation=True)
        relative = exported["checkpoints"][-1]["export_url"].split(f"/{run['id']}/", 1)[1]
        with zipfile.ZipFile(self.service.artifact_path(run["id"], relative)) as archive:
            self.assertEqual(json.loads(archive.read("skill.json")), run["skill"])
            provenance = json.loads(archive.read("provenance.json"))
            self.assertEqual(provenance["skill"], run["skill"])
            self.assertEqual(provenance["experiment_name"], EXPERIMENT)
            self.assertEqual(json.loads(archive.read("command-contract.json")), provenance["command_contract"])
            self.assertEqual(provenance["command_contract"]["version"], "microduck.single_leg_balance.v1")
        resumed = self.service.resume(run["id"], {"checkpoint_id": cp_id})
        self.assertEqual(resumed["skill"], run["skill"])
        self.assertEqual(resumed["parent_id"], run["id"])

    def test_old_walking_record_without_skill_still_allows_training(self):
        old = self.service.create_run({"kind": "smoke"})
        wait_for(self.service, old["id"])
        self.service._runs[old["id"]].pop("skill", None)
        self.service._runs[old["id"]].pop("smoke_family", None)
        self.service._save(self.service._runs[old["id"]])
        self.service.shutdown()
        self.service = StudioService(self.root, self.root / "engine", demo=True, demo_interval=.015)
        train = self.service.create_run({"kind": "train", "config": {"iterations": 10}})
        self.assertEqual(train["recipe_id"], "hd1910-flat")

    def test_checkpoint_scanning_and_selection_deny_wrong_recipe_directory(self):
        run = self.smoke()
        stored = self.service._runs[run["id"]]
        stored["checkpoints"] = []
        self.service.mode = "real"
        try:
            for experiment, expected in (("microduck_hd1910_velocity", 0), (EXPERIMENT, 1)):
                folder = self.root / "engine/logs/rsl_rl" / experiment / ("2026_studio_" + run["id"])
                folder.mkdir(parents=True)
                with zipfile.ZipFile(folder / "model_4.pt", "w") as archive:
                    archive.writestr("model/data.pkl", b"test fixture")
                    archive.writestr("model/version", b"3\n")
                self.service._real_line(stored, f"Logging experiment in directory: {folder}")
                self.service._scan_checkpoints(stored, complete=True)
                self.assertEqual(len(stored["checkpoints"]), expected)
            checkpoint = stored["checkpoints"][-1]
            self.assertEqual(self.service._checkpoint(stored, {"checkpoint_id": checkpoint["id"]}), checkpoint)
            wrong_folder = self.root / "engine/logs/rsl_rl/microduck_hd1910_velocity" / ("2026_studio_" + run["id"])
            stored["engine_log_dir"] = str(wrong_folder)
            checkpoint["engine_path"] = str(wrong_folder / "model_4.pt")
            with self.assertRaises(StudioError):
                self.service._checkpoint(stored, {"checkpoint_id": checkpoint["id"]})
        finally:
            self.service.mode = "demo"

    def test_real_operations_use_same_skill_file_and_record_actual_summary(self):
        run = self.smoke(skill={"hold_seconds": 5})
        stored = self.service._runs[run["id"]]
        folder = self.root / "engine/logs/rsl_rl" / EXPERIMENT / ("2026_studio_" + run["id"])
        folder.mkdir(parents=True)
        path = folder / "model_4.pt"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("model/data.pkl", b"test fixture")
            archive.writestr("model/version", b"3\n")
        stored.update(mode="real", engine_log_dir=str(folder), checkpoints=[{"id": "model-4", "iteration": 4, "task_id": TASK, "demo": False, "name": path.name, "engine_path": str(path)}])
        summary = {"demo": False, "trials": 8, "successes": 0, "success_rate": 0.0, "skill": run["skill"], "trial_results": [{"success": False}] * 8, "note": "Physics measured failure"}
        arguments = []
        def engine_child(actual_run, argv):
            arguments.append(argv)
            skill_file = Path(argv[argv.index("--balance-config") + 1])
            self.assertEqual(json.loads(skill_file.read_text()), run["skill"])
            if "--output-dir" in argv:
                output = Path(argv[argv.index("--output-dir") + 1])
                (output / "rollout.mp4").write_bytes(b"video fixture")
                (output / "evaluation.json").write_text(json.dumps(summary))
                self.assertEqual(argv[argv.index("--seed") + 1], "42")
                self.assertNotIn("--steps", argv)
            else:
                Path(argv[argv.index("--onnx-file") + 1]).write_bytes(b"onnx fixture")
        self.service.mode = "real"
        self.service._environment["ready"] = True
        try:
            with patch.object(self.service, "_operation_child", side_effect=engine_child):
                for kind in ("evaluate", "export"):
                    self.service.operate(run["id"], kind, {"checkpoint_id": "model-4"})
                    result = wait_for(self.service, run["id"], operation=True)
                self.assertEqual(result["checkpoints"][0]["evaluation_summary"], summary)
                self.assertEqual(arguments[0][arguments[0].index("--balance-config") + 1], arguments[1][arguments[1].index("--balance-config") + 1])
        finally:
            self.service.mode = "demo"

    def test_balance_summary_rejects_incomplete_nonfinite_or_mismatched_evidence(self):
        valid = {"demo": False, "trials": 8, "successes": 0, "success_rate": 0.0,
                 "skill": SKILL, "trial_results": [{"success": False}] * 8, "note": "Measured failure"}
        path = self.root / "evaluation.json"
        changes = ({"demo": True}, {"trials": 1}, {"successes": True}, {"success_rate": .5},
                   {"success_rate": float("nan")}, {"trial_results": []},
                   {"trial_results": [{"success": 0}] * 8}, {"skill": {**SKILL, "support_side": "right"}})
        for changed in changes:
            path.write_text(json.dumps({**valid, **changed}), encoding="utf-8")
            with self.subTest(changed=changed), self.assertRaises((RuntimeError, ValueError)):
                self.service._balance_evaluation_summary(path, SKILL)

    def test_source_provenance_separates_lock_candidates_from_runtime_versions(self):
        engine = self.root / "engine"
        engine.mkdir()
        (engine / "uv.lock").write_text('[[package]]\nname = "torch"\nversion = "2.10.0+cu128"\n[[package]]\nname = "torch"\nversion = "2.10.0+cu129"\n', encoding="utf-8")
        source = self.service._engine_source()
        self.assertEqual(source["dependency_versions"], {})
        self.assertEqual(source["lock_dependency_versions"]["torch"], ["2.10.0+cu128", "2.10.0+cu129"])
        self.service._environment["dependency_versions"] = {"torch": "2.10.0+cu128"}
        self.assertEqual(self.service._engine_source()["dependency_versions"], {"torch": "2.10.0+cu128"})


if __name__ == "__main__":
    unittest.main()
