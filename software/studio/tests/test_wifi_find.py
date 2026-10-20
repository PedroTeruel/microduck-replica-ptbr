"""连 WiFi 以后找鸭子的新地址（任务 17）：web/wifi.js 的探测逻辑，用 Node 跑真代码（不开浏览器）。

tests/wifi_find.mjs 用假时钟、假探测跑几幕（找到了、3 分钟找不到、热点回来了停下、一个地址挂着不回、probeImage 本身），
把每一幕探了哪些地址、什么时候跳、什么时候放弃打成 JSON；这里核对。页面上的那张卡片和真跳转在 tests/wifi_e2e.mjs 里。
电脑上要装 Node（≥ 20）；没有 Node（比如鸭子上）就跳过。单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_wifi_find'])"
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
NODE = shutil.which("node")
HOST = "http://duck-0de6:8000/"
LOCAL = "http://duck-0de6.local:8000/"


@unittest.skipUnless(NODE, "没装 Node，跳过「找鸭子新地址」的前端逻辑测试")
class FindDuckLogic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, str(HERE / "wifi_find.mjs")], capture_output=True, text=True,
                           encoding="utf-8", timeout=60, cwd=str(HERE.parent))
        if r.returncode != 0:
            raise AssertionError(f"Node 脚本出错：{r.stderr[-2000:]}")
        cls.out = json.loads(r.stdout)

    def test_every_two_seconds_for_three_minutes(self):
        self.assertEqual(self.out["consts"], {"every": 2000, "giveUp": 180000, "silent": 5000})

    def test_addresses_from_net_json_hostname(self):
        self.assertEqual(self.out["urls"], [HOST, LOCAL])
        self.assertEqual(self.out["urlsPort"], ["http://duck-c51b:18080/", "http://duck-c51b.local:18080/"])  # 端口跟 --listen
        self.assertEqual(self.out["urlsBare"], ["http://duck-c51b:8000/", "http://duck-c51b.local:8000/"])

    def test_first_success_jumps_and_stops(self):
        s = self.out["found"]
        self.assertEqual(s["found"], [{"t": 6000, "url": LOCAL}])
        self.assertEqual(s["gaveUp"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(sorted({c["t"] for c in s["calls"]}), [0, 2000, 4000, 6000])        # 每 2 秒一轮，找到就不再探
        self.assertTrue(all({c["url"] for c in s["calls"] if c["t"] == t} == {HOST, LOCAL} for t in (0, 2000, 4000, 6000)))

    def test_gives_up_after_three_minutes(self):
        s = self.out["timeout"]
        self.assertEqual(s["gaveUp"], [180000])
        self.assertEqual(s["found"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(len(s["calls"]), 2 * 90)                                       # 0、2、…、178 秒，两个地址
        self.assertEqual(max(c["t"] for c in s["calls"]), 178000)

    def test_stop_when_hotspot_comes_back(self):
        s = self.out["stop"]
        self.assertEqual(s["found"], [])                     # 停之前发出去、停之后才回「通了」的也不跳
        self.assertEqual(s["gaveUp"], [])
        self.assertTrue(s["stopped"])
        self.assertEqual(s["pending"], 0)
        self.assertEqual(max(c["t"] for c in s["calls"]), 4000)

    def test_hanging_address_is_not_piled_up(self):
        s = self.out["hang"]
        local = [c["t"] for c in s["calls"] if c["url"] == LOCAL]
        host = [c["t"] for c in s["calls"] if c["url"] == HOST]
        self.assertEqual(local, [0])
        self.assertEqual(host, [0, 2000, 4000, 6000, 8000, 10000])

    def test_probe_image_loads_probe_svg(self):
        img = self.out["image"]
        self.assertEqual(len(img["srcs"]), 3)
        self.assertRegex(img["srcs"][0], r"^" + re.escape(HOST) + r"probe\.svg\?t=\d+$")
        self.assertRegex(img["srcs"][1], r"^" + re.escape(LOCAL) + r"probe\.svg\?t=\d+$")
        self.assertTrue(img["load"])
        self.assertFalse(img["error"])
        self.assertFalse(img["timeout"])
        self.assertTrue(img["handlersCleared"])


if __name__ == "__main__":
    unittest.main()
