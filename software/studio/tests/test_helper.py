"""studio/helper.py（root 小助手的 Python 薄封装）：_call 解析、friendly 映射、available 缓存。

不碰真系统：mock subprocess.run 和 sys.platform。真正的小助手总线逻辑在 tests/test_helper_bus.py。
"""
import json
import unittest
from unittest import mock
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from studio import helper  # noqa: E402


def _proc(stdout, stderr="", rc=0):
    m = mock.MagicMock()
    m.stdout, m.stderr, m.returncode = stdout, stderr, rc
    return m


def _patch_run(stdout, stderr="", rc=0):
    return mock.patch.object(helper.subprocess, "run", return_value=_proc(stdout, stderr, rc))


class FriendlyTest(unittest.TestCase):
    def test_take(self):
        self.assertIn("主程序停了", helper.friendly("taken", None, "bus-take"))

    def test_take_port_busy(self):
        self.assertIn("串口还被占着", helper.friendly("port_busy", None, "bus-take"))

    def test_give_soft(self):
        self.assertIn("主程序起来了", helper.friendly("soft", None, "bus-give-back"))

    def test_give_limp(self):
        self.assertIn("全卸", helper.friendly("limp", None, "bus-give-back"))

    def test_give_still_starting_is_not_called_cannot_start(self):
        # 任务 16：主程序在回话、只是一直报启动阶段（旧 fork）：不说「起不来」，用小助手的整句原话
        msg = "主程序 30 秒一直报「启动中」（phase=configuring_bus）：可能其实起来了、只是状态没更新（旧版主程序的毛病）"
        self.assertEqual(msg, helper.friendly("soft_failed", {"msg": msg, "still_starting": True}, "bus-give-back"))
        self.assertIn("主程序起不来", helper.friendly("soft_failed", {"msg": "x"}, "bus-give-back"))

    def test_unknown_result(self):
        # 不认识的结果回退成原样，不带 msg 就不拼原话
        self.assertEqual("weird", helper.friendly("weird", None, "bus-take"))

    def test_msg_appended_when_not_duplicate(self):
        d = {"msg": "具体原因"}
        self.assertEqual("串口还被占着：具体原因", helper.friendly("port_busy", d, "bus-take"))

    def test_pad_pair_failure_has_official_reason(self):
        text = helper.friendly("pair_failed", {"reason": "not_found"}, "pad-pair")
        self.assertIn("没配上", text)
        self.assertIn("not_found", text)

    def test_pad_missing_robotctl(self):
        self.assertIn("robotctl", helper.friendly("no_robotctl", None, "pad-pair"))

    def test_pad_forget(self):
        self.assertIn("忘掉了", helper.friendly("forgotten", None, "pad-forget"))

    def test_not_motion_keeps_helper_reason(self):
        msg = "写进去了，但主程序停在调试模式：commissioning；已经换回原来的文件，再起了一次"
        self.assertEqual(msg, helper.friendly("not_motion", {"msg": msg}, "calib-commit"))

    def test_wifi_old_helper_says_reinstall(self):
        text = helper.friendly("bad_verb", None, "wifi-hotspot-down")
        self.assertIn("小助手太旧", text)
        self.assertIn("deploy/install.sh", text)

    def test_wifi_results(self):
        self.assertIn("热点关了", helper.friendly("hotspot_down", None, "wifi-hotspot-down"))
        self.assertIn("本来就没开", helper.friendly("already_down", None, "wifi-hotspot-down"))
        self.assertIn("热点开回来了", helper.friendly("hotspot_up", None, "wifi-hotspot-up"))


class PadCallTest(unittest.TestCase):
    def test_pair_payload_and_wrapper_timeout(self):
        out = '{"step":"done","detail":{"exit":0,"result":"paired","pair":{"outcome":"paired"}}}\n'
        with mock.patch.object(helper.subprocess, "run", return_value=_proc(out)) as run:
            ok, result, detail = helper.pad_pair("电脑", mac="aa:bb:cc:dd:ee:ff", timeout=20)
        self.assertTrue(ok)
        self.assertEqual(result, "paired")
        self.assertEqual(detail["pair"]["outcome"], "paired")
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", helper.HELPER, "pad-pair"])
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload, {"by": "电脑", "timeout": 20, "mac": "aa:bb:cc:dd:ee:ff"})
        self.assertEqual(run.call_args.kwargs["timeout"], 65)

    def test_forget_payload(self):
        out = '{"step":"done","detail":{"exit":0,"result":"forgotten","removed":true}}\n'
        with mock.patch.object(helper.subprocess, "run", return_value=_proc(out)) as run:
            ok, result, detail = helper.pad_forget("电脑", "AA:BB:CC:DD:EE:FF")
        self.assertTrue(ok)
        self.assertEqual(result, "forgotten")
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", helper.HELPER, "pad-forget"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]),
                         {"by": "电脑", "mac": "AA:BB:CC:DD:EE:FF"})


class WifiCallTest(unittest.TestCase):
    def test_down_payload_and_wrapper_timeout(self):
        out = '{"step":"done","detail":{"exit":0,"result":"hotspot_down"}}\n'
        with mock.patch.object(helper.subprocess, "run", return_value=_proc(out)) as run:
            ok, result, detail = helper.wifi_hotspot_down("电脑", "Home")
        self.assertTrue(ok)
        self.assertEqual(result, "hotspot_down")
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", helper.HELPER, "wifi-hotspot-down"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"by": "电脑", "ssid": "Home"})
        self.assertEqual(run.call_args.kwargs["timeout"], 30)

    def test_up_payload_and_wrapper_timeout(self):
        out = '{"step":"done","detail":{"exit":0,"result":"hotspot_up"}}\n'
        with mock.patch.object(helper.subprocess, "run", return_value=_proc(out)) as run:
            ok, result, detail = helper.wifi_hotspot_up("电脑")
        self.assertTrue(ok)
        self.assertEqual(result, "hotspot_up")
        self.assertEqual(run.call_args.args[0], ["sudo", "-n", helper.HELPER, "wifi-hotspot-up"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"by": "电脑"})
        self.assertEqual(run.call_args.kwargs["timeout"], 40)


class CallParseTest(unittest.TestCase):
    def test_done_taken(self):
        out = ('{"step":"lock","level":"info"}\n'
               '{"step":"done","level":"info","detail":{"exit":0,"result":"taken"}}\n')
        with _patch_run(out):
            ok, result, detail = helper._call("bus-take", {"by": "x"}, 30)
        self.assertTrue(ok)
        self.assertEqual(result, "taken")
        self.assertEqual(detail["result"], "taken")

    def test_done_failure_exit_5(self):
        out = '{"step":"done","level":"error","detail":{"exit":5,"result":"port_busy"}}\n'
        with _patch_run(out):
            ok, result, detail = helper._call("bus-take", {"by": "x"}, 30)
        self.assertFalse(ok)
        self.assertEqual(result, "port_busy")

    def test_no_done_falls_back_to_stderr(self):
        with _patch_run("不是 JSON\n", "小助手没装"):
            ok, result, detail = helper._call("bus-take", {"by": "x"}, 30)
        self.assertFalse(ok)
        self.assertEqual(result, "小助手没装")

    def test_no_done_no_stderr_falls_back_to_exit_code(self):
        with _patch_run("", rc=1):
            ok, result, detail = helper._call("bus-take", {"by": "x"}, 30)
        self.assertFalse(ok)
        self.assertEqual(result, "exit 1")

    def test_timeout(self):
        with mock.patch.object(helper.subprocess, "run", side_effect=helper.subprocess.TimeoutExpired("sudo", 1)):
            ok, result, detail = helper._call("bus-take", {"by": "x"}, 30)
        self.assertFalse(ok)
        self.assertEqual(result, "TimeoutExpired")


class AvailableTest(unittest.TestCase):
    def setUp(self):
        helper._avail = None

    def test_not_linux(self):
        with mock.patch.object(helper.sys, "platform", "win32"):
            self.assertFalse(helper.available())

    def test_file_missing(self):
        with mock.patch.object(helper.sys, "platform", "linux"), \
             mock.patch.object(helper.os.path, "exists", return_value=False):
            self.assertFalse(helper.available())

    def test_sudo_allows(self):
        with mock.patch.object(helper.sys, "platform", "linux"), \
             mock.patch.object(helper.os.path, "exists", return_value=True), \
             mock.patch.object(helper.subprocess, "run", return_value=_proc("", rc=2)):
            self.assertTrue(helper.available())

    def test_sudo_rejected(self):
        with mock.patch.object(helper.sys, "platform", "linux"), \
             mock.patch.object(helper.os.path, "exists", return_value=True), \
             mock.patch.object(helper.subprocess, "run", return_value=_proc("", rc=1)):
            self.assertFalse(helper.available())

    def test_cached(self):
        helper._avail = True
        self.assertTrue(helper.available())


class FlagPresentTest(unittest.TestCase):
    def test_non_linux_is_false(self):
        with mock.patch.object(helper.sys, "platform", "win32"), \
             mock.patch.object(helper.os.path, "exists") as exists:
            self.assertFalse(helper.flag_present())
            exists.assert_not_called()

    def test_linux_checks_the_run_flag(self):
        with mock.patch.object(helper.sys, "platform", "linux"), \
             mock.patch.object(helper.os.path, "exists", return_value=True) as exists:
            self.assertTrue(helper.flag_present())
            exists.assert_called_once_with(helper.FLAG)


if __name__ == "__main__":
    unittest.main()
