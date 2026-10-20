"""Studio「连 WiFi」的端到端：假 configd 写 hotspot 的 net.json + 真 Studio + 无头 Edge（390 宽）。

tests/wifi_e2e.mjs 看卡片、选 Home、填错密码、确认、看到「正在切换」，再等 last-try 红字「密码不对」。
任务 17：连接发出去以后页面断线（页面里的 WebSocket 垫片）→「找鸭子」卡片、探 probe.svg（CDP Fetch 拦）、热点回来停下、探到了跳过去。
要电脑上有 Node（>= 22）和 Edge；没有（比如鸭子上）就跳过。设 STUDIO_E2E=0 也跳过。
端口默认 Studio 18091、假 robotd 17031 / configd 17032、Edge 调试口 9344，被占了就换空闲的。
WIFI_E2E_DIR=目录：日志、Edge profile、net.json 放这里（默认临时目录，跑完删）；WIFI_SHOTS=目录：顺手截图。
单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_wifi_e2e'])"
"""
import json
import os
import re
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
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=240, cwd=ROOT)
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

    def test_card_addresses_by_device_and_own_hotspot_filtered(self):
        """任务 16：开着 Clash 的 Windows 打不开 .local——地址按设备写；扫描结果里鸭子自己的热点滤掉；顶栏名字悬停看得到 IP。"""
        c = self.out["card"]
        self.assertIn(f"Windows 电脑：http://duck-fake:{self.port}/（开着代理也能打开）", c["text"])
        self.assertIn(f"苹果手机、Mac：http://duck-fake.local:{self.port}/", c["text"])
        self.assertIn("去路由器的设备列表找 duck-fake", c["text"])
        self.assertIn("Clash 的 TUN 模式", c["text"])
        self.assertIn("Home", c["ssids"])
        self.assertNotIn("Microduck-fake", c["ssids"])
        self.assertIn("IP 10.42.0.1", c["nameTitle"])

    def test_duck_addresses_in_more_page(self):
        a = self.out["addr"]
        self.assertEqual([(r["kind"], r["url"]) for r in a["rows"]],
                         [("ip", f"http://10.42.0.1:{self.port}/"), ("host", f"http://duck-fake:{self.port}/"),
                          ("local", f"http://duck-fake.local:{self.port}/")])
        self.assertTrue(all(r["copy"] == "复制" for r in a["rows"]))
        self.assertIn(a["copied"], ("已复制", "复制不了，长按地址复制"))
        self.assertIn("这只鸭子的地址", a["text"])
        self.assertLessEqual(a["sw"], a["cw"])

    def test_home_expands_for_password_and_saved_network_is_marked(self):
        self.assertEqual(self.out["expanded"]["pskType"], "password")
        self.assertEqual(self.out["expanded"]["saved"], "已保存")
        self.assertIn("鸭子每次连都要密码（官方配网程序的规矩）", self.out["expanded"]["savedNote"])

    def test_confirm_and_switching_text(self):
        c = self.out["confirm"]
        self.assertIn("鸭子会关掉热点，去连「Home」", c)
        self.assertIn("你的手机会断开", c)
        self.assertIn("路由器的设备列表", c)
        self.assertIn("Microduck-fake", c)
        s = self.out["switching"]
        self.assertIn("正在切换……手机马上会断开", s)
        # 切换时那段话：三种地址按设备写（任务 16）
        self.assertIn(f"Windows 电脑：http://duck-fake:{self.port}/（开着代理也能打开）", s)
        self.assertIn(f"苹果手机、Mac：http://duck-fake.local:{self.port}/", s)
        self.assertIn("安卓手机，或者上面都打不开：去路由器的设备列表找 duck-fake，用它的 IP 打开", s)
        self.assertIn("在 Clash 里把局域网（192.168.0.0/16）设成直连", s)

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

    def test_finding_card_probes_and_stops_when_hotspot_returns(self):
        """任务 17：连接发出去、页面跟鸭子断了 →「找鸭子」卡片（地址能点）、每 2 秒探 duck-fake / duck-fake.local 的 probe.svg；
        页面重新连上原来的地址（热点回来了）→ 卡片收起、不再探、照旧显示失败原因。"""
        f = self.out["findA"]
        self.assertEqual(f["phase"], "finding")
        self.assertIn("鸭子正在连「Ghost」……", f["text"])
        self.assertIn("请把这台设备连回「Ghost」（电脑插着网线的不用管），找到鸭子会自动打开", f["text"])
        self.assertIn("找不到时：去路由器设备列表找 duck-fake 的 IP", f["text"])
        self.assertEqual(f["links"], [f"http://duck-fake:{self.port}/", f"http://duck-fake.local:{self.port}/"])
        self.assertLessEqual(f["sw"], f["cw"])
        probed = {re.sub(r"\?t=\d+$", "", u) for u in f["probes"]}
        self.assertEqual(probed, {f"http://duck-fake:{self.port}/probe.svg", f"http://duck-fake.local:{self.port}/probe.svg"})
        self.assertGreaterEqual(len(f["probes"]), 4, f["probes"])               # 4.5 秒里至少两轮、每轮两个地址
        b = self.out["findBack"]
        self.assertFalse(b["finding"])
        self.assertIn("上次连「Ghost」没成功：鸭子找不到这个 WiFi", b["lastTry"])
        self.assertEqual(b["probesLater"], b["probesAtBack"])                   # 热点回来了：不再探

    def test_found_duck_opens_new_address(self):
        """任务 17：探到 duck-fake.local 了：页面自己跳过去。"""
        self.assertEqual(self.out["found"]["href"], f"http://duck-fake.local:{self.port}/")
        self.assertEqual(self.out["found"]["title"], "found")

    def test_hotspot_password_warning_only_while_no_password(self):
        self.assertTrue(self.out["hotspotPasswordHint"])
        self.assertFalse(self.out["hotspotPasswordHintAfterSet"])
        self.assertEqual(self.out["passwordSet"], 200)          # 网页设密码这一下真的成功了


if __name__ == "__main__":
    unittest.main()
