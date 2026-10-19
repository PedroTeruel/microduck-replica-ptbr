"""电池（battery-plan.md v2）的端到端：假 robotd（电池剧本）+ 真 Studio（估算器 20 倍速快进）+ 无头 Edge。
tests/battery_e2e.mjs 看总览电池格的各种状态（静置、点开详情、读不到、估算中、黄、红、电压很低、手机宽度），
再到设置页改红线（先试一个不合法的）、「我量了电池电压」、切到台架电源；这里核对。

要电脑上有 Node（≥ 22）和 Edge；没有就跳过。设 STUDIO_E2E=0 也跳过。
端口默认 Studio 18103、假 robotd 17055 / configd 17056、Edge 调试口 9353（协调员分给电池的），被占了就换空闲的。
BATTERY_E2E_DIR=目录：日志、Edge 的 profile 放这里（默认临时目录，跑完删）；BATTERY_SHOTS=目录：顺手截图。
单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_battery_e2e'])"
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
                     "没有 Node ≥ 22 或者 Edge（或者设了 STUDIO_E2E=0）：跳过电池的端到端测试")
class BatteryE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("BATTERY_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="battery-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        p_rd, p_cfg, p_web, p_cdp = _port(17055), _port(17056), _port(18103), _port(9353)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}
        try:
            # 一开始软着（卸力）：静置读数最准，「我量了电池电压」也要卸力
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "limp"],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② 二号鸭", "--dev-autologin",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=dict(env, STUDIO_BATTERY_SPEED="20"), stdout=out("studio.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}", f"--user-data-dir={cls.dir / 'edge'}",
                 "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "无头 Edge 的调试口")
            args = [NODE, str(HERE / "battery_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp),
                    "--fake", str(p_cfg)]
            if os.environ.get("BATTERY_SHOTS"):
                args += ["--shots", os.environ["BATTERY_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=ROOT)
            (cls.dir / "battery_e2e.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Node 脚本出错（日志在 {cls.dir}）：{(r.stderr or '')[-3000:]}")
            (cls.dir / "battery_e2e.json").write_text(r.stdout, encoding="utf-8")
            cls.out = json.loads(r.stdout)
            cls.settings_file = json.loads((state / "battery-settings.json").read_text(encoding="utf-8"))
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def step(self, name):
        return self.out["steps"][name]

    def test_no_page_errors(self):
        self.assertEqual(self.out["errors"], [])

    def test_overview_states(self):
        calm = self.step("calm")
        self.assertRegex(calm["text"], r"电池 (4[5-9]|50) % 7\.6\d V · 静置")       # 二号鸭那组：7.62 V → 约 48%
        self.assertNotIn("warn", calm["cls"])
        self.assertIn("读不到电压", self.step("nodata")["text"])
        self.assertIn("估算中", self.step("estimating")["text"])
        self.assertNotIn("电量", self.step("estimating")["todo"])                    # 估算中不出黄红（审查 B-R2）
        warn = self.step("warn")
        self.assertRegex(warn["text"], r"电池 (2\d|30) %")                          # 7.40 V 加二号鸭那组偏差：7.42 V → 30%
        self.assertRegex(warn["todo"], r"电量约 (2\d|30)%")
        red = self.step("red")
        self.assertRegex(red["todo"], r"电量只剩约 \d+%")
        self.assertIn("不会自己停", red["todo"])                                       # 只警告的文案
        low = self.step("lowvolt")
        self.assertIn("电压很低", low["todo"])
        self.assertTrue(low["badge"])
        self.assertLess(low["todo"].index("电压很低"), len(low["todo"]))

    def test_detail_explains(self):
        d = self.step("detail")
        self.assertEqual(d["expanded"], "true")
        text = "\n".join(d["lines"])
        for s in ("最近 5 分钟最轻松的那会儿（卸力", "15 颗去掉最高最低各 3 颗的平均", "每芯 3.81 V", "±15%",
                  "主程序自己的算法", "直线，低电量偏高", "不会自己停", "放空了尽快充；长期不用存一半电（约 7.4–7.6 V）"):
            self.assertIn(s, text)

    def test_mobile_no_horizontal_scroll(self):
        m = self.step("mobile")
        self.assertLessEqual(m["sw"], m["cw"])
        self.assertLessEqual(m["popRight"], m["cw"])

    def test_settings(self):
        s = self.step("settings")["text"]
        for x in ("2S 锂电（NP-F550 等）", "台架电源（不算电量）", "提醒线", "红线", "负载电压线", "读数校准", "我量了电池电压",
                  "接可调电源时，看电源屏上的电压跟这里对一下也行（鸭子不动时）", "黄条会比以前早亮",
                  "放空了尽快充；长期不用存一半电（约 7.4–7.6 V）", "不会自己停"):
            self.assertIn(x, s)
        self.assertIn("没存", self.step("bad")["msg"])
        self.assertIn("至少低 5%", self.step("bad")["msg"])
        self.assertIn("已保存", self.step("saved")["msg"])
        self.assertTrue(any("红线 15% → 20%" in m for m in self.step("saved")["logs"]))
        self.assertIn("差 +0.18 V", self.step("calc")["msg"])
        self.assertIn("校准 +0.18 V", self.step("calibrated")["now"])
        # 最后改回 2S 锂电；红线、校准留着
        self.assertEqual((self.settings_file["preset"], self.settings_file["red_pct"], self.settings_file["cal_offset_v"]),
                         ("2s_liion", 20, 0.18))

    def test_bench(self):
        self.assertIn("只显示电压，不算百分比、不报电量", self.step("benchForm")["text"])
        self.assertNotIn("提醒线（黄）", self.step("benchForm")["text"])
        b = self.step("bench")
        self.assertRegex(b["text"], r"电池 7\.\d\d V 台架电源，不算电量")
        self.assertNotIn("%", b["text"])
        self.assertNotIn("电量", b["todo"])
        text = "\n".join(b["lines"])
        self.assertIn("台架电源", text)
        self.assertNotIn("主程序自己的算法", text)
        self.assertNotIn("放空了尽快充", text)


if __name__ == "__main__":
    unittest.main()
