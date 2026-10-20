"""Studio「连 WiFi」的端到端：假 configd 写 hotspot 的 net.json + 真 Studio + 无头 Edge（390 宽）。

tests/wifi_e2e.mjs 看卡片、选 Home、填错密码、确认、看到「正在切换」，再等 last-try 红字「密码不对」。
要电脑上有 Node（>= 22）和 Edge；没有（比如鸭子上）就跳过。设 STUDIO_E2E=0 也跳过。
端口默认 Studio 18091、假 robotd 17031 / configd 17032、Edge 调试口 9344，被占了就换空闲的。
WIFI_E2E_DIR=目录：日志、Edge profile、net.json 放这里（默认临时目录，跑完删）；WIFI_SHOTS=目录：顺手截图。
单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_wifi_e2e'])"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "没有 Node >= 22 或者 Edge（或者设了 STUDIO_E2E=0）：跳过 WiFi 的端到端测试")
class WifiE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("WIFI_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="wifi-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        net_state = cls.dir / "net.json"
        rec = cls.dir / "robotd-recv.jsonl"
        rec.unlink(missing_ok=True)
        p_rd, p_cfg, p_web, p_cdp = _port(17031), _port(17032), _port(18091), _port(9344)
        cls.port = p_web
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}
        try:
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "holding",
                 "--record", str(rec), "--net-mode", "hotspot", "--net-state-file", str(net_state)],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}",
                 "--robotd", f"tcp:127.0.0.1:{p_rd}", "--configd", f"tcp:127.0.0.1:{p_cfg}",
                 "--net-state", str(net_state), "--dev-autologin", "--servo-sim",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}",
                 f"--user-data-dir={cls.dir / 'edge'}", "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "无头 Edge 的调试口")
            args = [NODE, str(HERE / "wifi_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp)]
            if os.environ.get("WIFI_SHOTS"):
                args += ["--shots", os.environ["WIFI_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=180, cwd=ROOT)
            (cls.dir / "wifi_e2e.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Node 脚本出错（日志在 {cls.dir}）：{(r.stderr or '')[-3000:]}")
            (cls.dir / "wifi_e2e.json").write_text(r.stdout, encoding="utf-8")
            cls.out = json.loads(r.stdout)
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def test_page_has_no_errors(self):
        self.assertEqual(self.out["errors"], [])

    def test_card_is_before_onboard_and_fits_phone(self):
        c = self.out["card"]
        self.assertTrue(c["beforeOnboard"])
        self.assertIn("现在是鸭子自己的热点（Microduck-fake）", c["text"])
        self.assertIn(f"duck-fake.local:{self.port}", c["text"])
        self.assertIn("热点密码大家都知道", c["text"])
        self.assertLessEqual(c["sw"], c["cw"])

    def test_home_expands_for_password_and_saved_network_is_marked(self):
        self.assertEqual(self.out["expanded"]["pskType"], "password")
        self.assertEqual(self.out["expanded"]["saved"], "已保存")
        self.assertIn("鸭子每次连都要密码（官方配网程序的规矩）", self.out["expanded"]["savedNote"])

    def test_confirm_and_switching_text(self):
        c = self.out["confirm"]
        self.assertIn("鸭子会关掉热点，去连「Home」", c)
        self.assertIn("你的手机会断开", c)
        self.assertIn("路由器后台", c)
        self.assertIn("Microduck-fake", c)
        self.assertIn("正在切换……手机马上会断开", self.out["switching"])

    def test_wrong_password_is_red_last_try_and_fits_phone(self):
        lt = self.out["lastTry"]
        self.assertIn("上次连「Home」没成功：密码不对", lt["text"])
        self.assertNotEqual(lt["color"], "rgb(0, 0, 0)")
        self.assertLessEqual(lt["sw"], lt["cw"])

    def test_phone_can_open_logs_and_diag_from_more(self):
        m = self.out["mobile"]
        self.assertTrue(m["navHidden"])
        self.assertTrue(m["hasLogs"])
        self.assertTrue(m["hasDiag"])
        self.assertIn("导出诊断包", m["logs"])
        self.assertEqual(m["diagClicked"], "/api/diag")

    def test_hotspot_password_warning_only_while_no_password(self):
        self.assertTrue(self.out["hotspotPasswordHint"])
        self.assertFalse(self.out["hotspotPasswordHintAfterSet"])
        self.assertEqual(self.out["passwordSet"], 200)          # 网页设密码这一下真的成功了


if __name__ == "__main__":
    unittest.main()
