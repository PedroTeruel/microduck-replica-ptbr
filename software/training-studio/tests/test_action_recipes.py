"""Public recipe contract, independently specified from the engine registry."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from training_studio import action_recipes, config, evaluate
from training_studio.commands import build_train_argv, experiment_for
from training_studio.config import StudioError
from training_studio.service import StudioService


SOURCE_REVISION = "525a215a19397767a073b782f57e97cf53683761"
LEGACY = {"hd1910-flat", "hd1910-rough", "hd1910-single-leg"}
# Public task-name metadata from the pinned reference directory; no upstream code.
FAMILIES = (
    ("VelStand", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 6000),
    ("SitStand", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 15000),
    ("GroundPick", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 20000),
    ("BallKickLeft", ("Flat", "Flat-Backlash"), 10000),
    ("BallKick", ("Flat", "Flat-Backlash"), 10000),
    ("Roulade", ("Flat",), 10000),
    ("Velocity", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 50000),
    ("StandUp", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 15000),
    ("Velocity", ("Flat", "Flat-Backlash"), 50000, "-Rollers"),
    ("RollerCrouch", ("Flat", "Flat-Backlash"), 8000),
    ("Velocity", ("Swizzle", "Swizzle-Backlash"), 50000),
    ("RollerSlope", ("Flat", "Flat-Backlash"), 8000),
    ("RollerStandUp", ("Flat",), 15000),
    ("Spin", ("Flat",), 8000),
)
EXPECTED = {
    f"Mjlab-{family[0]}-{variant}-MicroDuck{family[3] if len(family) == 4 else ''}": family[2]
    for family in FAMILIES for variant in family[1]
}


def recipe_id(task):
    return "hd1910-" + task.removeprefix("Mjlab-").lower()


def new_recipes():
    return [recipe for recipe in config.RECIPES if recipe["id"] not in LEGACY]


def wait_complete(service, run_id, *, operation=False):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        run = service.get_run(run_id)
        status = run.get("operation", {}).get("status") if operation else run["status"]
        if status in ("failed", "completed"):
            if status != "completed":
                raise AssertionError(run)
            return run
        time.sleep(.02)
    raise AssertionError(service.get_run(run_id))


class ActionRecipeCatalogTests(unittest.TestCase):
    def test_35_public_variants_and_3_existing_recipes_have_stable_unique_ids(self):
        self.assertEqual(len(config.RECIPES), 38)
        self.assertEqual(len(config.RECIPE_BY_ID), 38)
        self.assertEqual({r["upstream_task_id"] for r in new_recipes()}, set(EXPECTED))
        self.assertEqual(len({r["catalog"]["category"] for r in new_recipes()}), 14)
        for recipe in new_recipes():
            task = recipe["upstream_task_id"]
            with self.subTest(task=task):
                self.assertEqual(recipe["id"], recipe_id(task))
                self.assertEqual(recipe["task_id"], task + "-Studio-HD1910")
                self.assertEqual(recipe["experiment_name"], "microduck_hd1910_" + task.removeprefix("Mjlab-").removesuffix("-MicroDuck").lower().replace("-", "_"))
        self.assertEqual(config.RECIPE_BY_ID["hd1910-flat"]["task_id"], "Mjlab-Velocity-Flat-MicroDuck-HD1910")
        self.assertEqual(config.RECIPE_BY_ID["hd1910-rough"]["experiment_name"], "microduck_hd1910_velocity")
        self.assertEqual(config.RECIPE_BY_ID["hd1910-single-leg"]["defaults"]["num_envs"], 256)

    def test_catalog_explains_source_hardware_budget_and_validation(self):
        self.assertEqual(len(new_recipes()), 35)
        for recipe in new_recipes():
            task, catalog = recipe["upstream_task_id"], recipe["catalog"]
            with self.subTest(task=task):
                self.assertIs(type(recipe["launchable"]), bool)
                self.assertIs(type(recipe["prerequisite_note"]), str)
                self.assertIsInstance(recipe["teacher_recipe_ids"], list)
                self.assertEqual(catalog["source_label"], "官方配方 · 本项目 HD1910 适配")
                self.assertTrue(catalog["source_url"].startswith("https://"))
                self.assertIn(SOURCE_REVISION, catalog["source_url"])
                self.assertEqual(catalog["source_revision"], SOURCE_REVISION)
                self.assertTrue(catalog["official_source_url"].startswith("https://"))
                self.assertIn("d424a0c899f6b33cbd3daeb279913134349c0b63", catalog["official_source_url"])
                self.assertEqual(catalog["engine_baseline_revision"], "d424a0c899f6b33cbd3daeb279913134349c0b63")
                self.assertEqual(catalog["reference_engine_revision"], "8d0db74916a4f833d1d9b95d6a1d7f4d13b9d5ec")
                self.assertIn(catalog["terrain"], ("Flat", "Rough", "Slope"))
                self.assertIs(type(catalog["backlash"]), bool)
                self.assertEqual(catalog["backlash"], "-Backlash-" in task)
                self.assertIs(type(catalog["requires_rollers"]), bool)
                self.assertEqual(catalog["requires_rollers"], any(word in task for word in ("Roller", "Swizzle", "Spin")))
                self.assertEqual(catalog["preview_kind"], "text")
                self.assertTrue(catalog["instructions"])
                self.assertEqual(recipe["defaults"]["num_envs"], 4096)
                self.assertEqual(recipe["defaults"]["iterations"], EXPECTED[task])
                self.assertIn("4096", catalog["budget_note"])
                self.assertIn("24", catalog["budget_note"])
                self.assertIn("HD1910", recipe["hardware"])
                if catalog["requires_rollers"]:
                    self.assertIn("轮滑", recipe["hardware"])
                self.assertIn(catalog["verification_state"], ("unverified", "pipeline"))
                if catalog["verification_state"] == "pipeline":
                    self.assertTrue(catalog["verification_evidence"])

    def test_new_recipes_start_unverified_and_only_successful_evidence_upgrades_label(self):
        rid = recipe_id("Mjlab-SitStand-Flat-MicroDuck")
        for evidence, expected in (({}, "unverified"), ({rid: {"verification_state": "pipeline"}}, "unverified"),
                                   ({rid: {"verification_state": "pipeline", "verification_label": "已完成短试跑",
                                           "verification_evidence": ["docs/evidence/smoke.json"], "validation": "64×5 流程验收"}}, "pipeline")):
            with self.subTest(evidence=evidence), patch.object(action_recipes, "RECIPE_VERIFICATION", evidence):
                recipes = action_recipes.build_action_recipes(config.DEFAULTS)
                target = next(r for r in recipes if r["id"] == rid)
                self.assertEqual(target["catalog"]["verification_state"], expected)
                self.assertTrue(all(r["catalog"]["verification_state"] == "unverified" for r in recipes if r["id"] != rid))
                if expected == "pipeline":
                    self.assertEqual(target["validation"], "64×5 流程验收")
                    target["catalog"]["verification_evidence"].append("changed")
                    self.assertEqual(evidence[rid]["verification_evidence"], ["docs/evidence/smoke.json"])

    def test_joint_variants_link_matching_walk_and_recovery_teachers(self):
        blocked = [r for r in new_recipes() if not r["launchable"]]
        self.assertEqual(len(blocked), 4)
        self.assertEqual(sum(r["launchable"] for r in new_recipes()), 31)
        for recipe in blocked:
            task = recipe["upstream_task_id"]
            self.assertTrue(task.startswith("Mjlab-VelStand-"))
            self.assertEqual(recipe["teacher_recipe_ids"], [recipe_id(task.replace("VelStand", "Velocity")), recipe_id(task.replace("VelStand", "StandUp"))])
            self.assertIn("PT", recipe["prerequisite_note"])
            self.assertIn("联合", recipe["prerequisite_note"])
            self.assertIn("61", recipe["prerequisite_note"])
            self.assertIn("14", recipe["prerequisite_note"])
            for teacher_id in recipe["teacher_recipe_ids"]:
                self.assertTrue(config.RECIPE_BY_ID[teacher_id]["launchable"])

    def test_commands_use_task_specific_experiments_and_reject_blocked_targets(self):
        self.assertEqual(len(new_recipes()), 35)
        for recipe in new_recipes():
            run = dict(id="abc123", recipe_id=recipe["id"], task_id=recipe["task_id"], kind="smoke", config={})
            with self.subTest(recipe=recipe["id"]):
                if not recipe["launchable"]:
                    with self.assertRaises(StudioError):
                        build_train_argv(run, Path("/engine"))
                    continue
                self.assertEqual(experiment_for(run), recipe["experiment_name"])
                argv = build_train_argv(run, Path("/engine"))
                self.assertEqual(argv[6], recipe["task_id"])
                self.assertEqual(argv[argv.index("--env.scene.num-envs") + 1], "64")
                checkpoint = Path("/engine/logs/rsl_rl") / recipe["experiment_name"] / "source/model_4.pt"
                self.assertIn("--agent.resume", build_train_argv(run, Path("/engine"), checkpoint))
                with self.assertRaises(StudioError):
                    build_train_argv({**run, "task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910"}, Path("/engine"))

    def test_catalog_task_and_experiment_contract_matches_engine_descriptors(self):
        path = Path(__file__).resolve().parents[2] / "training/src/mjlab_microduck/tasks/recipe_tasks.py"
        self.assertTrue(path.is_file(), "engine recipe descriptors are missing")
        spec = importlib.util.spec_from_file_location("action_recipe_contract", path)
        engine = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = engine
        spec.loader.exec_module(engine)
        expected = {r["upstream_task_id"]: (r["task_id"], r["experiment_name"]) for r in new_recipes()}
        actual = {r.upstream_task: (r.task_id, r.experiment_name) for r in engine.RECIPE_TASKS}
        self.assertEqual(expected, actual)

    def test_evaluation_parser_allowlist_is_all_launchable_recipes(self):
        self.assertTrue(hasattr(evaluate, "build_parser"), "evaluation parser must expose the shared allowlist")
        parser = evaluate.build_parser()
        choices = next(action.choices for action in parser._actions if action.dest == "task_id")
        allowed = {r["task_id"] for r in config.RECIPES if r.get("launchable", True)}
        self.assertEqual(set(choices), allowed)
        self.assertEqual(len(choices), 34)
        for task in allowed:
            self.assertEqual(parser.parse_args([task, "--checkpoint-file", "test.pt", "--output-dir", "out"]).task_id, task)

    def test_evaluation_script_help_works_by_absolute_path_outside_studio(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, str(Path(evaluate.__file__).resolve()), "--help"], cwd=folder, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mjlab-SitStand-Flat-MicroDuck-Studio-HD1910", result.stdout)
        self.assertNotIn("Mjlab-VelStand-Flat-MicroDuck-Studio-HD1910", result.stdout)


class ActionRecipeServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.service = StudioService(self.root, self.root / "engine", demo=True, demo_interval=.01)

    def tearDown(self):
        self.service.shutdown()
        self.temporary.cleanup()

    def test_joint_prerequisites_reject_before_record_or_child_in_both_modes(self):
        blocked = [recipe_id(t) for t in EXPECTED if t.startswith("Mjlab-VelStand-")]
        for mode in ("demo", "real"):
            self.service.mode = mode
            for recipe in blocked:
                for kind in ("smoke", "train"):
                    with self.subTest(mode=mode, recipe=recipe, kind=kind), patch("training_studio.service.subprocess.Popen") as spawn:
                        with self.assertRaises(StudioError) as error:
                            self.service.create_run({"recipe_id": recipe, "kind": kind})
                        self.assertEqual(error.exception.status, 409)
                        self.assertIn("PT", str(error.exception))
                        spawn.assert_not_called()
        self.assertEqual(self.service.state()["runs"], [])

    def test_nonlegacy_smoke_gate_demo_evaluation_and_export_keep_recipe(self):
        rid = recipe_id("Mjlab-SitStand-Flat-MicroDuck")
        with self.assertRaises(StudioError):
            self.service.create_run({"recipe_id": rid, "kind": "train"})
        smoke = self.service.create_run({"recipe_id": rid, "kind": "smoke"})
        smoke = wait_complete(self.service, smoke["id"])
        for change in ({"config": {"seed": 43}}, {"config": {"learning_rate": .002}}, {"recipe_id": recipe_id("Mjlab-SitStand-Rough-MicroDuck")}):
            with self.subTest(change=change), self.assertRaises(StudioError):
                self.service.create_run({"recipe_id": rid, "kind": "train", **change})
        run = self.service.create_run({"recipe_id": rid, "kind": "train", "config": {"num_envs": 128, "iterations": 2, "save_interval": 1}})
        run = wait_complete(self.service, run["id"])
        self.assertEqual(run["smoke_family"], smoke["smoke_family"])
        self.assertEqual(run["experiment_name"], "microduck_hd1910_sitstand_flat")
        cp_id = run["checkpoints"][-1]["id"]
        for operation in ("evaluate", "export"):
            self.service.operate(run["id"], operation, {"checkpoint_id": cp_id})
            run = wait_complete(self.service, run["id"], operation=True)
        relative = run["checkpoints"][-1]["export_url"].split(f"/{run['id']}/", 1)[1]
        with zipfile.ZipFile(self.service.artifact_path(run["id"], relative)) as archive:
            provenance = json.loads(archive.read("provenance.json"))
            self.assertEqual(provenance["task_id"], "Mjlab-SitStand-Flat-MicroDuck-Studio-HD1910")
            self.assertEqual(provenance["experiment_name"], run["experiment_name"])

    def test_saved_task_tampering_or_blocked_recipe_cannot_evaluate_or_export(self):
        run = self.service.create_run({"recipe_id": "hd1910-flat", "kind": "smoke"})
        run = wait_complete(self.service, run["id"])
        original = copy.deepcopy(self.service._runs[run["id"]])
        for change in ({"task_id": "unregistered"}, {"recipe_id": recipe_id("Mjlab-VelStand-Flat-MicroDuck"), "task_id": "Mjlab-VelStand-Flat-MicroDuck-Studio-HD1910"}):
            stored = self.service._runs[run["id"]]
            stored.update(original)
            stored.update(change)
            for operation in ("evaluate", "export"):
                with self.subTest(change=change, operation=operation), patch.object(self.service, "_operation_child") as spawn:
                    with self.assertRaises(StudioError):
                        self.service.operate(run["id"], operation, {"checkpoint_id": run["checkpoints"][-1]["id"]})
                    spawn.assert_not_called()

    def test_new_real_evaluation_and_export_use_saved_task_checkpoint_and_seed(self):
        rid = recipe_id("Mjlab-Velocity-Flat-MicroDuck-Rollers")
        run = self.service.create_run({"recipe_id": rid, "kind": "smoke", "config": {"seed": 123}})
        run = wait_complete(self.service, run["id"])
        stored = self.service._runs[run["id"]]
        folder = self.root / "engine/logs/rsl_rl" / run["experiment_name"] / ("2026_studio_" + run["id"])
        folder.mkdir(parents=True)
        checkpoint_path = folder / "model_4.pt"
        with zipfile.ZipFile(checkpoint_path, "w") as archive:
            archive.writestr("model/data.pkl", b"structural fixture only")
            archive.writestr("model/version", b"3\n")
        stored.update(mode="real", engine_log_dir=str(folder), checkpoints=[{
            "id": "model-4", "task_id": run["task_id"], "demo": False, "name": checkpoint_path.name,
            "engine_path": str(checkpoint_path), "iteration": 4}])
        calls = []

        def engine_child(actual_run, argv):
            calls.append(argv)
            self.assertIn(run["task_id"], argv)
            self.assertEqual(argv[argv.index("--checkpoint-file") + 1], str(checkpoint_path))
            self.assertNotIn("--balance-config", argv)
            if "--output-dir" in argv:
                self.assertTrue(Path(argv[6]).is_absolute())
                self.assertEqual(argv[argv.index("--seed") + 1], "123")
                self.assertEqual(argv[argv.index("--steps") + 1], "250")
                (Path(argv[argv.index("--output-dir") + 1]) / "rollout.mp4").write_bytes(b"video fixture")
            else:
                self.assertEqual(argv[6], "scripts/export.py")
                self.assertEqual(argv[argv.index("--num-envs") + 1], "1")
                Path(argv[argv.index("--onnx-file") + 1]).write_bytes(b"onnx fixture")

        self.service.mode = "real"
        self.service._environment["ready"] = True
        try:
            with patch.object(self.service, "_operation_child", side_effect=engine_child):
                for operation in ("evaluate", "export"):
                    self.service.operate(run["id"], operation, {"checkpoint_id": "model-4"})
                    run = wait_complete(self.service, run["id"], operation=True)
            self.assertEqual(len(calls), 2)
        finally:
            self.service.mode = "demo"

    def test_state_catalog_is_a_copy(self):
        state = self.service.state()
        state["recipes"][-1]["catalog"]["instructions"].append("changed")
        state["recipes"][-1]["defaults"]["num_envs"] = 16
        self.assertNotEqual(state["recipes"][-1], self.service.state()["recipes"][-1])

    def test_engine_source_hashes_actual_new_registrations_actuator_and_all_task_factories(self):
        engine_root = Path(__file__).resolve().parents[2] / "training"
        expected = {
            "src/mjlab_microduck/tasks/recipe_tasks.py",
            "src/mjlab_microduck/tasks/backlash.py",
            "src/mjlab_microduck/actuator/feetech_bam.py",
        }
        expected.update(path.relative_to(engine_root).as_posix() for path in
                        (engine_root / "src/mjlab_microduck/tasks").glob("microduck_*_env_cfg.py"))
        self.assertIn("src/mjlab_microduck/tasks/microduck_studio_env_cfg.py", expected)
        with patch.object(self.service, "training_root", engine_root):
            source = self.service._engine_source()
        self.assertTrue(expected.issubset(source["files_sha256"]), expected - set(source["files_sha256"]))
        for relative in expected:
            with self.subTest(relative=relative):
                self.assertEqual(source["files_sha256"][relative], self.service._sha256(engine_root / relative))


if __name__ == "__main__":
    unittest.main()
