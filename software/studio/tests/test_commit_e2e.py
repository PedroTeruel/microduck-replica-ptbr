"""出厂场景「写进主程序」（任务 13）的端到端：假 robotd（--mode commissioning --calib factory）+ 真 Studio + 无头 Edge。

流程：tests/commit_e2e.mjs 先在出厂状态看第 3 步的灰按钮和预览；然后 IMU 页粗校（假主程序模拟托起、低头、
verify-imu 成功）、舵机页一键中位（--servo-sim）、第 3 步写入。假小助手让假主程序切到 motion + control，
清单第 3 步变成完成、顶栏显示运动模式。最后再跑一次「标定被拒」：页面要看到原因，断线期间进度卡也不能丢。

电脑上没有 root 小助手：用临时启动脚本把 studio.helper.calib_commit 换成假实现（只在这一段里）。
要电脑上有 Node（≥ 22）和 Edge；没有（比如鸭子上）就跳过。设 STUDIO_E2E=0 也跳过。
端口默认 Studio 18091、假 robotd 17031 / configd 17032、Edge 调试口 9344，被占了就换空闲的。
COMMIT_E2E_DIR=目录：日志、Edge 的 profile 放这里（默认临时目录，跑完删）；COMMIT_SHOTS=目录：顺手截图。
单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_commit_e2e'])"
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
STUCK_CALIB = "motion requires all 15 calibrated joints, measured limits and verified IMU mounting for the lsm6dsv16x IMU"

BOOT = r'''
import json, os, socket, sys, time
sys.path[:0] = [ROOT, os.path.join(ROOT, "deps"), os.path.join(ROOT, "dev")]
from studio import helper
from studio import commit as C

helper.available = lambda: True
# 电脑上没有 root 小助手：进舵机页要调 bus-take，交还要调 bus-give-back；这里都当“已经做了”。
helper.flag_present = lambda: False
helper.bus_take = lambda by, allow_seated=False, timeout=30: (True, "taken", {})
helper.bus_give_back = lambda by, *, soft=True, marker=None, timeout=60: (True, "soft", {})


def fake_set(obj):
    port = int(os.environ["E2E_FAKE_PORT"])
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "fake.set", "params": obj}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            part = s.recv(4096)
            if not part:
                break
            buf += part
    return json.loads(buf.split(b"\n", 1)[0])


def outcome():
    path = os.environ.get("E2E_OUTCOME_FILE")
    try:
        with open(path, encoding="utf-8") as f:
            return (json.load(f) or {}).get("outcome") or "ok"
    except (OSError, ValueError):
        return "ok"


def fake_calib_commit(by, joints, imu, dry_run=False, timeout=180, on_line=None):
    cur = {"motion_enabled": False, "imu_mount_verified": False,
           "imu_mount_quat": list(C.DEFAULT_BUS_QUAT), "current_ma_per_count": 0.0, "units_verified": False,
           "imu_mounts": {}, "joints": [{"name": n, "id": C.JOINT_IDS[n], "zero_raw": 2048,
                                         "direction": -1, "calibrated": False} for n in C.JOINT_ORDER]}
    cal = C.build_calibration(cur, joints, imu)
    C.validate_calibration(cal, imu["source"])
    text = C.render_calibration(cal)
    if on_line:
        on_line({"step": "write", "msg": "假小助手：写好了"})
    if dry_run:
        return True, "preview", {"exit": 0, "toml": text}

    want = outcome()
    if want == "reject":
        # 先让假主程序切到 motion，但标定校验不过 -> waiting_for_bus；再模拟 robotd 重启，页面会短暂断线
        fake_set({"calib_commit": {"calibration": cal, "outcome": "reject"}})
        fake_set({"restart": 1.5})
        if on_line:
            on_line({"step": "wait", "msg": "假小助手：等主程序回来"})
        time.sleep(1.7)
        # 模拟回滚：文件、模式都换回出厂那份，再重启一次（真小助手也是这样把 robotd 拉回标定模式的）。
        fake_set({"mode": "commissioning", "calib": "factory"})
        fake_set({"restart": 1.0})
        time.sleep(1.2)
        msg = "标定没通过主程序的检查：" + %r + "；已经换回原来的文件和模式，又起了一次主程序"
        return False, "calib_rejected", {"exit": 5, "msg": msg, "rolled_back": True,
                                         "readback_ok": False, "mismatches": [],
                                         "bus_status": {"mode": "motion", "phase": "waiting_for_bus", "error": %r}}
    fake_set({"calib_commit": {"calibration": cal, "outcome": "ok"}})
    if on_line:
        on_line({"step": "done", "msg": "假小助手：写进去了，主程序切到运动模式"})
    return True, "committed", {"exit": 0, "toml": text, "mode": "motion", "phase": "control",
                               "readback_ok": True, "mismatches": [], "fake": True}


helper.calib_commit = fake_calib_commit
from studio.__main__ import main
main(sys.argv[1:])
''' % (STUCK_CALIB, STUCK_CALIB)


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "没有 Node ≥ 22 或者 Edge（或者设了 STUDIO_E2E=0）：跳过「写进主程序」的端到端测试")
class CommitE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("COMMIT_E2E_DIR")
        cls.dir = (Path(keep) if keep else Path(tempfile.mkdtemp(prefix="commit-e2e-"))).resolve()
        cls.dir.mkdir(parents=True, exist_ok=True)
        cls.state = cls.dir / "state"
        cls.state.mkdir(exist_ok=True)
        cls.outcome_file = cls.dir / "commit-outcome.json"
        p_rd, p_cfg, p_web, p_cdp = _port(17031), _port(17032), _port(18091), _port(9344)
        cls.p_web, cls.p_cfg = p_web, p_cfg
        env = dict(os.environ, PYTHONIOENCODING="utf-8", E2E_FAKE_PORT=str(p_cfg),
                   E2E_OUTCOME_FILE=str(cls.outcome_file))
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        boot = cls.dir / "e2e_boot.py"
        boot.write_text(f"ROOT = {str(ROOT)!r}\n" + BOOT, encoding="utf-8")
        cls.procs = {
            "fake": subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--mode", "commissioning",
                 "--posture", "commissioning", "--calib", "factory", "--record", str(cls.dir / "robotd-recv.jsonl")],
                cwd=ROOT, env=env, stdout=out("fake.out"), stderr=subprocess.STDOUT),
        }
        try:
            cls.procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(boot), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② 二号鸭", "--dev-autologin", "--servo-sim",
                 "--state-dir", str(cls.state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            edge_dir = cls.dir / "edge"
            shutil.rmtree(edge_dir, ignore_errors=True)      # 上一次没清理的 profile 会让 Edge 起得极慢
            edge_dir.mkdir(parents=True, exist_ok=True)         # Edge 自己建不出来（沙箱里会报 Lock file 不能创建）
            cls.procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-setuid-sandbox",
                 "--enable-unsafe-swiftshader", f"--remote-debugging-port={p_cdp}",
                 f"--user-data-dir={edge_dir}", "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "Edge 调试口", timeout=60)
        except Exception:
            for p in cls.procs.values():
                _kill(p)
            raise
        cls.p_cdp = p_cdp

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "procs", {}).values():
            _kill(p)
        if os.environ.get("COMMIT_E2E_DIR"):
            return
        shutil.rmtree(cls.dir, ignore_errors=True)

    def node(self, phase):
        args = [NODE, str(HERE / "commit_e2e.mjs"), "--url", f"http://127.0.0.1:{self.p_web}/",
                "--cdp", str(self.p_cdp), "--fake-port", str(self.p_cfg), "--phase", phase]
        if os.environ.get("COMMIT_SHOTS"):
            args += ["--shots", os.environ["COMMIT_SHOTS"]]
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=220, cwd=ROOT)
        (self.dir / f"commit_e2e-{phase}.err").write_text(r.stderr or "", encoding="utf-8")
        if r.returncode != 0:
            raise AssertionError(f"Node 脚本（{phase}）出错（日志在 {self.dir}）：{(r.stderr or '')[-4000:]}")
        (self.dir / f"commit_e2e-{phase}.json").write_text(r.stdout, encoding="utf-8")
        return json.loads(r.stdout)

    def fake_set(self, obj):
        with socket.create_connection(("127.0.0.1", self.p_cfg), timeout=5) as s:
            s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "fake.set", "params": obj}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                part = s.recv(4096)
                if not part:
                    break
                buf += part
        return json.loads(buf.split(b"\n", 1)[0])

    def test_01_factory_preview(self):
        first = self.node("factory")
        self.assertGreaterEqual(first["factory"]["bad"], 1, first)
        self.assertTrue(first["factory"]["writeDisabled"], first["factory"])
        blob = first["factory"]["desc"] + json.dumps(first["factory"]["checks"], ensure_ascii=False)
        self.assertIn("舵机零位", blob)
        self.assertEqual(first["preview"]["jointRows"], 15, first["preview"])
        self.assertTrue(first["preview"]["imu"], first["preview"])
        self.assertIn("motion_enabled = true", first["preview"]["toml"])

    def test_02_imu_coarse_verify(self):
        imu = self.node("imu")
        self.assertIn("方向已确认", imu["imu"], imu)

    def test_03_servo_center_then_commit(self):
        from studio import commit as C
        servo = self.node("servo")
        self.assertEqual(servo["planRows"], 15, servo)
        # --servo-sim 是演示舵机，后端不会把它记进 servo-centered.json（真机上真校才记）。
        # 这里补记 15 颗，模拟「在这只鸭子上用舵机页一键中位过」；真正的记录路径在 test_servo_* 里测。
        C.record_centered(str(self.state), list(C.JOINT_IDS.values()), "e2e 演示中位")
        time.sleep(1.6)                       # CommitService 最多 1 秒重读一次 state 文件

        second = self.node("commit")
        self.assertEqual(second["ready"]["bad"], 0, second["ready"])
        self.assertFalse(second["ready"]["writeDisabled"], second["ready"])
        self.assertIn("会重启主程序，鸭子会先卸力，扶好鸭子", second["confirmText"])
        self.assertEqual(second["done"]["rowState"], "完成", second["done"])
        self.assertIn("运动模式", second["topbar"], second)
        self.assertEqual(second["errors"], [])

    def test_04_failure_rollback_is_visible(self):
        self.outcome_file.write_text(json.dumps({"outcome": "reject"}), encoding="utf-8")
        self.fake_set({"mode": "commissioning"})          # 回到标定模式再写一次
        time.sleep(1.6)
        failed = self.node("fail")
        self.assertTrue(failed["offline"], failed.get("offline"))
        self.assertIn("主程序在重启", failed["offline"]["text"])
        self.assertEqual(failed["failed"]["rowState"], "该做", failed["failed"])
        self.assertTrue(any("标定没通过主程序的检查" in m for m in failed["failed"]["msgs"]), failed["failed"])
        self.assertEqual((failed.get("wsCommit") or {}).get("job", {}).get("phase"), "failed", failed.get("wsCommit"))
        self.outcome_file.write_text(json.dumps({"outcome": "ok"}), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
