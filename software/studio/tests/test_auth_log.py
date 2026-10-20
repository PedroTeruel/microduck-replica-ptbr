"""auth / log 的测试。只用标准库：python -m unittest discover -s tests（在 software/studio 下跑）。"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import auth as auth_mod  # noqa: E402
from studio.auth import Auth, OriginGuard  # noqa: E402
from studio.log import Log, log_cmd  # noqa: E402


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.auth = Auth(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_password_refuses_login(self):
        token, why, _ = self.auth.login("whatever", "1.2.3.4")
        self.assertIsNone(token)
        self.assertIn("还没设", why)

    def test_set_and_login(self):
        self.auth.set_password("duck-123456")
        self.assertTrue(self.auth.check_password("duck-123456"))
        self.assertFalse(self.auth.check_password("duck-12345"))
        token, why, _ = self.auth.login("duck-123456", "1.2.3.4", remember=True)
        self.assertIsNotNone(token, why)
        sess = self.auth.session(token)
        self.assertTrue(sess["remember"])
        self.assertTrue(Auth.recent_auth(sess))

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            self.auth.set_password("123")

    def test_password_file_is_private(self):
        self.auth.set_password("duck-123456")
        if os.name == "posix":
            self.assertEqual(os.stat(self.auth.pw_path).st_mode & 0o777, 0o600)
        data = json.loads(self.auth.pw_path.read_text(encoding="utf-8"))
        self.assertNotIn("duck-123456", json.dumps(data))

    def test_backoff_after_five_failures_and_only_for_that_ip(self):
        self.auth.set_password("duck-123456")
        waits = [self.auth.login("bad", "9.9.9.9")[2] for _ in range(5)]
        self.assertEqual(waits[:4], [0, 0, 0, 0])
        self.assertEqual(waits[4], 30)
        token, why, wait = self.auth.login("duck-123456", "9.9.9.9")
        self.assertIsNone(token)
        self.assertGreater(wait, 0)
        self.assertIn("秒后再试", why)
        token, _, _ = self.auth.login("duck-123456", "8.8.8.8")
        self.assertIsNotNone(token)

    def test_sessions_survive_restart_and_expire(self):
        self.auth.set_password("duck-123456")
        keep, _, _ = self.auth.login("duck-123456", "1.1.1.1", remember=True)
        short, _, _ = self.auth.login("duck-123456", "1.1.1.1", remember=False)
        again = Auth(self.tmp.name)
        self.assertIsNotNone(again.session(keep))
        self.assertIsNotNone(again.session(short))
        later = time.time() + auth_mod.IDLE_S + 10
        with mock.patch("studio.auth.time.time", return_value=later):
            self.assertIsNone(again.session(short))
            self.assertIsNotNone(again.session(keep))

    def test_changing_password_revokes_sessions(self):
        self.auth.set_password("duck-123456")
        token, _, _ = self.auth.login("duck-123456", "1.1.1.1")
        self.auth.set_password("duck-654321")
        self.assertIsNone(self.auth.session(token))

    def test_changing_password_can_keep_the_current_browser(self):
        self.auth.set_password("duck-123456")
        token, _, _ = self.auth.login("duck-123456", "1.1.1.1")
        other, _, _ = self.auth.login("duck-123456", "2.2.2.2")
        self.auth.set_password("duck-654321", keep_token=token)
        self.assertIsNotNone(self.auth.session(token))
        self.assertIsNone(self.auth.session(other))
        self.assertTrue(self.auth.check_password("duck-654321"))

    def test_clear_password_removes_file_and_sessions(self):
        self.auth.set_password("duck-123456")
        token, _, _ = self.auth.login("duck-123456", "1.1.1.1")
        self.auth.clear_password()
        self.assertFalse(self.auth.has_password())
        self.assertFalse(self.auth.pw_path.exists())
        self.assertIsNone(self.auth.session(token))

    def test_reauth(self):
        self.auth.set_password("duck-123456")
        token, _, _ = self.auth.login("duck-123456", "1.1.1.1")
        with mock.patch("studio.auth.time.time", return_value=time.time() + 700):
            self.assertFalse(Auth.recent_auth(self.auth.session(token)))
            self.assertFalse(self.auth.reauth(token, "wrong"))
            self.assertTrue(self.auth.reauth(token, "duck-123456"))
            self.assertTrue(Auth.recent_auth(self.auth.session(token)))


class OriginGuardTest(unittest.TestCase):
    def setUp(self):
        self.g = OriginGuard(names=["microduck-2", "microduck-2.local"])

    def test_host(self):
        self.assertTrue(self.g.host_ok("microduck-2.local"))
        self.assertTrue(self.g.host_ok("microduck-2:80"))
        self.assertTrue(self.g.host_ok("localhost:8000"))
        self.assertTrue(self.g.host_ok("127.0.0.1:8000"))
        self.assertTrue(self.g.host_ok("192.168.0.103", local_ip="192.168.0.103"))
        self.assertFalse(self.g.host_ok("192.168.0.103", local_ip="192.168.0.105"))
        self.assertFalse(self.g.host_ok("evil.example.com"))
        self.assertFalse(self.g.host_ok(""))

    def test_origin(self):
        self.assertTrue(self.g.origin_ok("http://microduck-2.local", "microduck-2.local"))
        self.assertTrue(self.g.origin_ok("http://192.168.0.103:8000", "192.168.0.103:8000"))
        self.assertFalse(self.g.origin_ok("http://192.168.0.103:8080", "192.168.0.103:8000"))
        self.assertFalse(self.g.origin_ok("http://evil.example.com", "microduck-2.local"))
        self.assertFalse(self.g.origin_ok(None, "microduck-2.local"))
        self.assertFalse(self.g.origin_ok("file://", "microduck-2.local"))


class SetPasswordCommandTest(unittest.TestCase):
    def test_refuses_root_before_prompting(self):
        from studio import __main__ as main_mod
        with mock.patch.object(main_mod.os, "geteuid", return_value=0, create=True), \
             mock.patch.object(main_mod.getpass, "getpass") as ask:
            with self.assertRaises(SystemExit) as e:
                main_mod.main(["set-password"])
        self.assertIn("别用 sudo", str(e.exception))
        self.assertIn("radxa", str(e.exception))
        ask.assert_not_called()


class LogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(self.tmp.name, echo=False, background=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_error_line_names_step_raw_and_hint(self):
        self.log.error("站起来没成功", cat="robotd", step="robot.init", raw="waiting_for_bus", hint="等 10 秒")
        text = self.log.files()[-1].read_text(encoding="utf-8")
        self.assertIn("[robotd][错误] 站起来没成功", text)
        self.assertIn("卡在：robot.init", text)
        self.assertIn("原文：waiting_for_bus", text)
        self.assertIn("建议：等 10 秒", text)
        e = self.log.recent()[-1]
        self.assertEqual((e["level"], e["step"]), ("error", "robot.init"))

    def test_success_line_does_not_say_stuck(self):
        self.log.info("← 卸力 成功", cat="命令", step="robot.relax")
        text = self.log.files()[-1].read_text(encoding="utf-8")
        self.assertIn("步骤：robot.relax", text)
        self.assertNotIn("卡在", text)

    def test_debug_not_on_page_or_disk_by_default(self):
        self.log.debug("帧 123")
        self.assertEqual(self.log.recent(min_level="debug"), [])
        self.assertEqual(self.log.files(), [])

    def test_filter(self):
        self.log.info("连上了", cat="连接")
        self.log.warn("温度高", cat="系统")
        self.assertEqual([e["msg"] for e in self.log.recent(cats=["连接"])], ["连上了"])
        self.assertEqual([e["msg"] for e in self.log.recent(min_level="warn")], ["温度高"])

    def test_prune_keeps_recent_days(self):
        d = Path(self.tmp.name)
        for i in range(20):
            (d / f"studio-2026-09-{i + 1:02d}.log").write_text("x", encoding="utf-8")
        self.log.info("今天")
        left = sorted(p.name for p in d.glob("studio-*.log"))
        self.assertEqual(len(left), 14)
        self.assertIn("studio-" + time.strftime("%Y-%m-%d") + ".log", left)   # 不看排第几：钟可能停在 1970

    def test_prune_by_size_when_today_sorts_first(self):
        # 钟停在 1970 时，今天的文件名排在最前；以前总量检查碰到它就停了，一个都不删
        from studio import log as log_mod
        d = Path(self.tmp.name)
        for i in range(3):
            (d / f"studio-2099-01-0{i + 1}.log").write_text("x" * 50, encoding="utf-8")
        with mock.patch.object(log_mod, "MAX_TOTAL_BYTES", 120):
            self.log.info("今天")
        left = sorted(p.name for p in d.glob("studio-*.log"))
        self.assertIn("studio-" + time.strftime("%Y-%m-%d") + ".log", left)
        self.assertLess(len([n for n in left if "2099" in n]), 3)

    def test_subscribe_receives_and_drops_oldest(self):
        import asyncio

        async def run():
            q = self.log.subscribe(maxsize=2)
            for i in range(3):
                self.log.info(f"第{i}条")
            await asyncio.sleep(0)
            got = [q.get_nowait()["msg"] for _ in range(q.qsize())]
            self.log.unsubscribe(q)
            return got

        self.assertEqual(asyncio.run(run()), ["第1条", "第2条"])


    def test_secrets_are_hidden(self):
        self.log.hide("duck-123456")
        self.log.warn("登录失败", raw="password=duck-123456")
        text = self.log.files()[-1].read_text(encoding="utf-8")
        self.assertNotIn("duck-123456", text)
        self.assertIn("[已隐藏]", text)

    def test_secret_keys_are_redacted_even_without_hide(self):
        """按键名打码：psk、password 这些键的值不进日志（家里的 WiFi 密码走这条）。"""
        with log_cmd(self.log, "连 WiFi", "configd net.connect",
                     args={"ssid": "Home", "psk": "Unique-PSK-2026-xyz"}) as t:
            t.ok({"outcome": "connected", "ssid": "Home"})
        self.log.warn("现场", ctx={"ssid": "Home", "psk": "Unique-PSK-2026-xyz", "nested": [{"password": "p2-unique"}]})
        text = self.log.files()[-1].read_text(encoding="utf-8")
        self.assertNotIn("Unique-PSK-2026-xyz", text)
        self.assertNotIn("p2-unique", text)
        self.assertIn("[已隐藏]", text)

    def test_repeats_within_a_minute_are_merged(self):
        for _ in range(5):
            self.log.warn("TOF 连接断了", cat="连接")
        self.assertEqual(len(self.log.recent()), 1)
        with mock.patch("studio.log.time.time", return_value=time.time() + 61):
            self.log.warn("TOF 连接断了", cat="连接")
        msgs = [e["msg"] for e in self.log.recent()]
        self.assertIn("在 1 分钟内又出现了 4 次", msgs[1])
        self.assertEqual(msgs[2], "TOF 连接断了")

    def test_command_timer_logs_request_reply_and_failure(self):
        with log_cmd(self.log, "站起来", "robot.init", args={"x": 1}) as t:
            t.fail("总线没准备好", raw={"error": "waiting_for_bus"}, hint="等 10 秒")
        with log_cmd(self.log, "卸力", "robot.relax"):
            pass
        msgs = [e["msg"] for e in self.log.recent()]
        self.assertTrue(msgs[0].startswith("→ 站起来"))
        self.assertIn("没成功：总线没准备好", msgs[1])
        self.assertTrue(msgs[3].startswith("← 卸力 成功"))
        self.assertEqual(self.log.recent()[1]["level"], "error")

    def test_timestamp_has_milliseconds(self):
        self.log.info("x")
        line = self.log.files()[-1].read_text(encoding="utf-8").splitlines()[0]
        self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}")


if __name__ == "__main__":
    unittest.main()
