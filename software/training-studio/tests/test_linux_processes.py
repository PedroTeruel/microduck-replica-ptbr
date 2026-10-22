"""Actual Linux process controls on CPU; engine diagnostics/argv alone are stubbed."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from training_studio.service import StudioService


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.025)
    raise AssertionError("Timed out waiting for actual Linux process state")


def alive(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state not in ("Z", "X")
    except FileNotFoundError:
        return False


@unittest.skipUnless(sys.platform == "linux", "Actual SIGSTOP/process-group checks require Linux")
class LinuxProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = self.root / "engine"
        self.engine.mkdir()
        with patch("training_studio.service.inspect_environment", return_value={"ready": True, "checks": [], "pause_supported": True}):
            self.service = StudioService(self.root / "state", self.engine, demo=False)

    def tearDown(self):
        self.service.shutdown()
        self.tmp.cleanup()

    def launch(self, script):
        def argv(run, _root, _checkpoint):
            return [sys.executable, "-u", "-c", script(run) if callable(script) else script]
        with patch("training_studio.service.build_train_argv", side_effect=argv):
            return self.service.create_run({"recipe_id": "hd1910-flat", "kind": "smoke"})

    def orphan_script(self, pid_file):
        return ("import subprocess,sys,pathlib\n"
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
                "print('leader exiting',flush=True)\n")

    def test_training_leader_exit_cleans_descendant_that_keeps_stdout_open(self):
        pid_file = self.root / "descendant.pid"
        run = self.launch(self.orphan_script(pid_file))
        until(pid_file.exists)
        descendant = int(pid_file.read_text())
        until(lambda: self.service.get_run(run["id"])["status"] == "completed", timeout=3)
        self.assertFalse(alive(descendant))
        self.assertIsNone(self.service.state()["active_run_id"])
        until(lambda: not self.service._readers[run["id"]].is_alive())
        self.assertFalse(self.service._readers[run["id"]].is_alive())

    def completed_fixture(self):
        def script(run):
            folder = self.engine / "logs/rsl_rl/microduck_hd1910_velocity" / ("cpu_studio_" + run["id"])
            return ("import pathlib,zipfile\n"
                    f"folder=pathlib.Path({str(folder)!r});folder.mkdir(parents=True)\n"
                    "with zipfile.ZipFile(folder/'model_4.pt','w') as z:\n"
                    " z.writestr('model/data.pkl','structural CPU fixture, not trained weights')\n"
                    " z.writestr('model/version','3')\n"
                    "print('[INFO] Logging experiment in directory: '+str(folder),flush=True)\n")
        run = self.launch(script)
        until(lambda: self.service.get_run(run["id"])["status"] == "completed")
        return self.service.get_run(run["id"])

    def test_operation_leader_exit_releases_job_when_descendant_holds_stdout(self):
        run = self.completed_fixture()
        pid_file = self.root / "operation-descendant.pid"
        original = self.service._operation_child
        def cpu_argv(stored, _argv):
            return original(stored, [sys.executable, "-u", "-c", self.orphan_script(pid_file)])
        with patch.object(self.service, "_operation_child", side_effect=cpu_argv):
            self.service.operate(run["id"], "export", {"checkpoint_id": run["checkpoints"][0]["id"]})
            until(pid_file.exists)
            descendant = int(pid_file.read_text())
            until(lambda: self.service.get_run(run["id"])["operation"]["status"] != "running", timeout=3)
        # The CPU argv cannot emit ONNX, so failure is expected after prompt cleanup.
        self.assertEqual(self.service.get_run(run["id"])["operation"]["status"], "failed")
        self.assertFalse(alive(descendant))
        self.assertIsNone(self.service.state()["active_run_id"])

    def test_kernel_pause_freezes_entire_group_resume_advances_shutdown_cleans(self):
        parent_counter = self.root / "parent.count"
        child_counter = self.root / "child.count"
        pid_file = self.root / "counter-descendant.pid"
        def counter_code(path):
            return ("import os,pathlib,time\n"
                    f"p=pathlib.Path({str(path)!r});t=p.with_suffix('.tmp');i=0\n"
                    "while True:\n"
                    " i+=1;t.write_text(str(i));os.replace(t,p);time.sleep(.04)\n")
        script = ("import pathlib,subprocess,sys\n"
                  f"p=subprocess.Popen([sys.executable,'-u','-c',{counter_code(child_counter)!r}])\n"
                  f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid))\n"
                  "print('CPU process-control fixture ready',flush=True)\n" + counter_code(parent_counter))
        run = self.launch(script)
        until(lambda: parent_counter.exists() and child_counter.exists())
        leader = self.service.child_pid(run["id"])
        descendant = int(pid_file.read_text())
        self.assertEqual(self.service.pause(run["id"])["status"], "paused")
        paused = (parent_counter.read_text(), child_counter.read_text())
        time.sleep(0.25)
        self.assertEqual((parent_counter.read_text(), child_counter.read_text()), paused)
        self.service.resume(run["id"], {})
        until(lambda: int(parent_counter.read_text()) > int(paused[0]) and int(child_counter.read_text()) > int(paused[1]))
        self.service.pause(run["id"])
        self.service.shutdown()
        self.assertEqual(self.service.get_run(run["id"])["status"], "stopped")
        self.assertFalse(alive(leader))
        self.assertFalse(alive(descendant))
        self.assertIsNone(self.service.child_pid(run["id"]))


if __name__ == "__main__":
    unittest.main()
