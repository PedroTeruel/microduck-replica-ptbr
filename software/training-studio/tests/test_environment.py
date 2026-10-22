"""Exercise probe and child environments using CPU-only engine stand-ins."""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from training_studio.environment import inspect_environment
from training_studio.service import StudioService


class RuntimeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = self.root / "engine"
        self.modules = self.root / "modules"
        for name in ("pyproject.toml", "uv.lock", "scripts/export.py",
                     "src/mjlab_microduck/train_cli.py", ".venv/bin/python"):
            self.write(self.engine / name, "")
        fixtures = {
            "torch.py": "class cuda:\n @staticmethod\n def is_available(): return True\n @staticmethod\n def get_device_name(index): return 'CPU test fixture'\n",
            "mujoco.py": "import os\nif os.environ.get('STUDIO_TEST_MISSING_GL') == '1':\n raise ImportError('libEGL.so.1: cannot open shared object file')\nclass GLContext: pass\n",
            "mjlab/__init__.py": "",
            "mjlab/tasks/__init__.py": "",
            "mjlab/tasks/registry.py": "def list_tasks(): return ['Mjlab-Velocity-Flat-MicroDuck-HD1910', 'Mjlab-Velocity-Rough-MicroDuck-HD1910', 'Mjlab-Balance-Flat-MicroDuck-HD1910']\n",
            "mjlab/rl/__init__.py": "",
            "mjlab/rl/config.py": "class RslRlBaseRunnerCfg:\n __dataclass_fields__ = dict.fromkeys(['resume', 'load_run', 'load_checkpoint'])\n",
            "mjlab_microduck/__init__.py": "",
            "mjlab_microduck/tasks.py": "",
            "mjlab-1.3.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: mjlab\nVersion: 1.3.0\n",
            "torch-2.10.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: torch\nVersion: 2.10.0+cu128\n",
            "rsl_rl_lib-5.0.1.dist-info/METADATA": "Metadata-Version: 2.1\nName: rsl-rl-lib\nVersion: 5.0.1\n",
            "mujoco_warp-3.3.7.dist-info/METADATA": "Metadata-Version: 2.1\nName: mujoco-warp\nVersion: 3.3.7\n",
        }
        for name, content in fixtures.items():
            self.write(self.modules / name, content)
        self.real_run = subprocess.run
        self.probe_environments = []

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def probe_transport(self, argv, **kwargs):
        # Execute the actual probe script, replacing only uv and engine modules.
        # No torch/MuJoCo/GPU packages are imported by these test subprocesses.
        if argv[0] == "test-uv":
            self.probe_environments.append(kwargs.get("env", {}).copy())
            argv = [sys.executable, "-c", argv[-1]]
        return self.real_run(argv, **kwargs)

    def test_missing_selected_gl_library_blocks_ready_before_training(self):
        with patch.dict(os.environ, {"PYTHONPATH": str(self.modules), "STUDIO_TEST_MISSING_GL": "1"}):
            os.environ.pop("MUJOCO_GL", None)
            with patch("training_studio.environment.platform.system", return_value="Linux"), \
                 patch("training_studio.environment.shutil.which", return_value="test-uv"), \
                 patch("training_studio.environment.subprocess.run", side_effect=self.probe_transport):
                result = inspect_environment(self.engine)
        self.assertFalse(result["ready"])
        failed_details = " ".join(check["detail"] for check in result["checks"] if not check["ok"])
        self.assertIn("MUJOCO_GL=egl", failed_details)
        self.assertIn("libEGL.so.1", failed_details)

    def test_missing_balance_task_blocks_ready(self):
        self.write(self.modules / "mjlab/tasks/registry.py", "def list_tasks(): return ['Mjlab-Velocity-Flat-MicroDuck-HD1910', 'Mjlab-Velocity-Rough-MicroDuck-HD1910']\n")
        with patch.dict(os.environ, {"PYTHONPATH": str(self.modules)}), \
             patch("training_studio.environment.platform.system", return_value="Linux"), \
             patch("training_studio.environment.shutil.which", return_value="test-uv"), \
             patch("training_studio.environment.subprocess.run", side_effect=self.probe_transport):
            os.environ.pop("STUDIO_TEST_MISSING_GL", None)
            result = inspect_environment(self.engine)
        self.assertFalse(result["ready"])

    def test_demo_does_not_stat_wsl_virtual_environment(self):
        original = Path.is_file
        def is_file(path):
            if ".venv" in path.parts:
                raise OSError(1920, "Windows cannot access WSL virtual environment link")
            return original(path)
        with patch.object(Path, "is_file", is_file):
            self.assertTrue(inspect_environment(self.engine, demo=True)["ready"])

    def test_probe_training_and_evaluation_share_default_and_explicit_backend(self):
        for explicit, expected in ((None, "egl"), ("osmesa", "osmesa")):
            with self.subTest(explicit=explicit), patch.dict(os.environ, {"PYTHONPATH": str(self.modules)}):
                os.environ.pop("STUDIO_TEST_MISSING_GL", None)
                if explicit is None:
                    os.environ.pop("MUJOCO_GL", None)
                else:
                    os.environ["MUJOCO_GL"] = explicit
                with patch("training_studio.environment.platform.system", return_value="Linux"), \
                     patch("training_studio.environment.shutil.which", return_value="test-uv"), \
                     patch("training_studio.environment.subprocess.run", side_effect=self.probe_transport):
                    service = StudioService(self.root / expected, self.engine)
                try:
                    self.assertTrue(service.environment()["ready"])
                    expected_versions = {"mjlab": "1.3.0", "torch": "2.10.0+cu128", "rsl-rl-lib": "5.0.1", "mujoco-warp": "3.3.7"}
                    self.assertEqual(service.environment().get("dependency_versions"), expected_versions)
                    self.assertEqual(service._engine_source()["dependency_versions"], expected_versions)
                    capture = "import os; print('selected_gl=' + os.environ.get('MUJOCO_GL', 'unset'), flush=True)"
                    argv = [sys.executable, "-u", "-c", capture]
                    with patch("training_studio.service.build_train_argv", return_value=argv), \
                         patch.object(service, "_engine_source", return_value={}):
                        run = service.create_run({"kind": "smoke"})
                    deadline = time.monotonic() + 5
                    while service.get_run(run["id"])["status"] not in ("completed", "failed") and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertEqual(service.get_run(run["id"])["status"], "completed")
                    stored = service._runs[run["id"]]
                    stored["operation"] = {"kind": "evaluate"}
                    service._operation_child(stored, argv)
                    backend_lines = [line.split("  ", 1)[-1] for line in service.get_run(run["id"])["logs"] if "selected_gl=" in line]
                    self.assertEqual(backend_lines, [f"selected_gl={expected}"] * 2)
                    self.assertEqual(self.probe_environments[-1].get("MUJOCO_GL"), expected)
                    self.assertEqual(self.probe_environments[-1].get("PYTHONUNBUFFERED"), "1")
                    self.assertEqual(os.environ.get("MUJOCO_GL"), explicit)
                finally:
                    service.shutdown()


if __name__ == "__main__":
    unittest.main()
