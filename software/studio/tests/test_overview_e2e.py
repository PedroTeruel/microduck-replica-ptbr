"""总览重排（overview-merge-plan.md §5，审查 overview-merge-review.md）的端到端：假 robotd + 真 Studio + 无头 Edge。

tests/overview_e2e.mjs 在总览上看主板温度格、上手清单、手柄区块，再做几件会出事的操作（按着摇杆时切页 / 滚走、
在舞台上滚滚轮、手机上从手柄图空白处 / 动作按钮 / 图上的 A 起手往下刷），把假 robotd 每一步收到的东西打出来；
这里核对（审查 O1、O2、O5、O8、O13、O14、O17、O18）。分两段跑：main（没有记录的 Studio）；done（Studio 带着
「6 步都做过」的 onboarding.json 重启，清单收成一行）。

要电脑上有 Node（≥ 22）和 Edge；没有（比如鸭子上）就跳过。设 STUDIO_E2E=0 也跳过。
端口默认 Studio 18090、假 robotd 17021 / configd 17022、Edge 调试口 9343，被占了就换空闲的（不碰别人在跑的）。
OVERVIEW_E2E_DIR=目录：日志、Edge 的 profile、假 robotd 的记录放这里（默认临时目录，跑完删）；OVERVIEW_SHOTS=目录：顺手截图。
单独跑：
    py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','-v','tests.test_overview_e2e'])"
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(ROOT / "deps"), str(ROOT / "dev")]

from tests.test_vpad_e2e import EDGE, NODE, _kill, _node_ok, _port, _wait_http, moves, nonzero  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
XBOX = "78:86:2E:BB:13:28"


def all_done_records():
    """「5 步都做过」的记录：指纹按假 robotd 回放的那份标定算（跟 Studio 里 onboard.py 同一套函数）。"""
    from fake_robotd import FakeRobotd
    from studio import onboard as O
    from studio.imu import mount_of
    f = FakeRobotd(str(FIXTURE), posture="policy")
    src, mount = mount_of(f.bus, f.calib)
    now = time.time()
    fp = O.full_fp(f.bus, f.calib)
    return {"v": 1, "confirm_servo": {"at": now - 3600, "fp": O.joints_fp(f.calib), "by": "e2e"},
            # IMU 这一步是跳过的（用户 10-18：「以前标定过，应该跳过就行」）：收起时写「（跳过 1 步）」
            "skipped": {"imu": {"at": now - 3000, "by": "e2e", "fp": O.mount_fp(src, mount["quat"])}},
            "estop": {"at": now - 2400, "ms": 186, "mac": XBOX, "name": "Xbox Wireless Controller", "build": f.bus["build"]},
            "stood": {"at": now - 1800, "fp": fp}, "walked": {"at": now - 1700, "fp": fp}}


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get("STUDIO_E2E", "1") != "0",
                     "没有 Node ≥ 22 或者 Edge（或者设了 STUDIO_E2E=0）：跳过总览的端到端测试")
class OverviewE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        keep = os.environ.get("OVERVIEW_E2E_DIR")
        cls.dir = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="overview-e2e-"))
        cls.dir.mkdir(parents=True, exist_ok=True)
        state = cls.dir / "state"
        if state.exists():
            shutil.rmtree(state)
        rec = cls.dir / "robotd-recv.jsonl"
        rec.unlink(missing_ok=True)
        p_rd, p_cfg, p_web, p_cdp = _port(17021), _port(17022), _port(18090), _port(9343)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        out = lambda name: open(cls.dir / name, "w", encoding="utf-8")   # noqa: E731
        procs = {}

        def studio(tag):
            procs["studio"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "run.py"), "--listen", f"127.0.0.1:{p_web}", "--robotd", f"tcp:127.0.0.1:{p_rd}",
                 "--configd", f"tcp:127.0.0.1:{p_cfg}", "--duck-label", "② 二号鸭", "--dev-autologin", "--servo-sim",
                 "--state-dir", str(state), "--log-dir", str(cls.dir / "logs")],
                cwd=ROOT, env=env, stdout=out(f"studio-{tag}.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_web}/healthz", "Studio")

        def node(phase):
            args = [NODE, str(HERE / "overview_e2e.mjs"), "--url", f"http://127.0.0.1:{p_web}/", "--cdp", str(p_cdp),
                    "--record", str(rec), "--fake", str(p_cfg), "--phase", phase]
            if os.environ.get("OVERVIEW_SHOTS"):
                args += ["--shots", os.environ["OVERVIEW_SHOTS"]]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=400, cwd=ROOT)
            (cls.dir / f"overview_e2e-{phase}.err").write_text(r.stderr or "", encoding="utf-8")
            if r.returncode != 0:
                raise AssertionError(f"Node 脚本（{phase}）出错（日志在 {cls.dir}）：{(r.stderr or '')[-3000:]}")
            (cls.dir / f"overview_e2e-{phase}.json").write_text(r.stdout, encoding="utf-8")
            return json.loads(r.stdout)

        try:
            # 「准备好走」：摇杆、动作、技能都能按（看「不该发」的那几步，要先证明平时是会发的）
            procs["fake"] = subprocess.Popen(
                [sys.executable, "-I", str(ROOT / "dev" / "fake_robotd.py"), "--fixture", str(FIXTURE),
                 "--robotd-port", str(p_rd), "--configd-port", str(p_cfg), "--posture", "policy", "--record", str(rec)],
                cwd=ROOT, env=env, stdout=out("fake_robotd.out"), stderr=subprocess.STDOUT)
            studio("main")
            procs["edge"] = subprocess.Popen(
                [EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={p_cdp}", f"--user-data-dir={cls.dir / 'edge'}",
                 "--no-first-run", "--no-default-browser-check", "about:blank"],
                stdout=out("edge.out"), stderr=subprocess.STDOUT)
            _wait_http(f"http://127.0.0.1:{p_cdp}/json/version", "无头 Edge 的调试口")
            cls.out = node("main")
            # 第二段：Studio 带着「5 步都做过」的记录重启；实体手柄连着（测急停记录里就是这只手柄）
            _kill(procs.pop("studio"))
            (state / "onboarding.json").write_text(json.dumps(all_done_records(), ensure_ascii=False), encoding="utf-8")
            import socket
            for _ in range(20):           # 上一段最后让假 robotd「重启」了一下（0.3 秒拒绝连接）：没回话就再来
                try:
                    with socket.create_connection(("127.0.0.1", p_cfg), 3) as s:
                        s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"fake.set","params":{"pad_connected":true}}\n')
                        if b"connected" in s.recv(4096):
                            break
                except OSError:
                    pass
                time.sleep(0.2)
            else:
                raise AssertionError("假 configd 没接受「手柄连着」")
            studio("done")
            cls.done = node("done")
        finally:
            for p in reversed(list(procs.values())):
                _kill(p)
        if not keep:
            shutil.rmtree(cls.dir, ignore_errors=True)

    def recs(self, step):
        return self.out["steps"][step]["recs"]

    def test_page_has_no_errors(self):
        self.assertEqual(self.out["errors"], [])
        self.assertEqual(self.done["errors"], [])

    def test_overview_layout(self):
        d = self.out["desk"]
        self.assertEqual(d["cells"], 7)                                  # 增加摄像头与ToF，最后主板
        self.assertIn("°C", d["cpu"])
        self.assertEqual(d["rows"], 6)                                   # 清单 6 行（任务 11 加了「写进主程序」）
        self.assertFalse(d["padActive"])                                 # 首页顶上：手柄那一块不在屏幕上
        self.assertEqual(d["nav"], "总览")
        self.assertEqual(d["now"], "1 舵机零位")                         # 现在该做：第一个没完成的
        self.assertEqual(d["marks"][:3], ["●", "●", "✓"])
        tops = self.out["d1100"]["tops"]                                 # 1100 宽：4 + 3
        self.assertEqual(len(set(tops[:4])), 1)
        self.assertGreater(tops[4], tops[0])
        self.assertEqual(len(set(tops[4:])), 1)
        for k in ("d1100", "phone", "phone_pad"):
            self.assertLessEqual(self.out[k]["sw"], self.out[k]["cw"], f"{k}：能左右滑")

    def test_wheel_on_stage_scrolls_page(self):
        self.assertGreater(self.out["wheel"], 100, "在舞台上滚滚轮，页面没动（被 3D 缩放吃掉了）")

    def test_pad_anchor(self):
        n = self.out["padNav"]
        self.assertTrue(n["active"])
        self.assertEqual(n["nav"], "手柄")
        self.assertEqual(n["topbar"], 0)                                 # 顶栏吸顶（卸力一直在屏幕上：O3）
        # 仪表带吸在顶栏下面、侧栏吸住（用户 10-19：往下滑一直看得到）；滚到手柄那一块，停在仪表带下面、不被它盖住
        self.assertEqual(n["band"][0], 56, n)
        self.assertEqual(n["navTop"], 0, n)
        self.assertTrue(n["band"][1] <= n["top"] <= n["band"][1] + 30, n)

    def assert_released(self, st):
        self.assertTrue(any(nonzero(p) for p in moves(st["before"])), "按着摇杆时应该在走（不然这一步没测到东西）")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(st["atLeave" if "atLeave" in st else "atScroll"]))
        self.assertFalse(any(nonzero(p) for p in moves(st["after"])), "离开手柄区以后手还按着也不该再走")
        self.assertFalse(st["active"])
        self.assertTrue(st["offLogged"], "Studio 日志里没看到「离开了手柄区」（drive off）")

    def test_route_change_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["route_leave"])

    def test_scrolling_out_while_holding_stick_stops_and_drives_off(self):
        self.assert_released(self.out["steps"]["scroll_out"])

    def test_checklist_buttons_go_to_the_right_place(self):
        g = self.out["goto"]
        self.assertTrue(g["estop"]["inView"])
        self.assertIn(g["estop"]["focus"], ("pd-estop-btn", "pd-estop"))
        self.assertTrue(g["wizard"]["open"] and g["wizard"]["inView"])
        self.assertEqual(g["imu"], "#/imu")

    def test_swipes_on_phone_send_nothing(self):
        """O2：从手柄图空白处、动作按钮、图上的 A 起手往上刷是在滚页面，robotd 一条都收不到；按住不动 / 点一下才发（对照）。"""
        for step in ("swipe_pad_blank", "swipe_action", "press_right_after_scroll", "swipe_svg_a"):
            with self.subTest(step=step):
                self.assertEqual([r for r in self.recs(step) if r["method"] in ("robot.move", "robot.head", "robot.do", "robot.mouth",
                                                                                  "robot.sound", "robot.pose")], [])
        self.assertTrue(any(r["method"] == "robot.head" for r in self.recs("hold_action")), "按住「点头」不动，头没动")
        self.assertIn({"method": "robot.do", "params": {"skill": "ground_pick"}, "notify": False}, self.recs("tap_svg_a"))

    def test_board_temperature(self):
        c = self.out["cpu"]
        self.assertTrue(c["throttled"]["bad"])
        self.assertIn("降频了：1008 / 1800 MHz", c["throttled"]["text"])
        self.assertIn("主板过热降频了", c["throttled"]["todo"])
        self.assertIn("有点热", c["hot"])
        self.assertIn("—", c["stale"])                                   # health 过期：写「—」，不写「正常」（O5）
        self.assertNotIn("正常", c["stale"])

    def test_unknown_shows_question_marks(self):
        self.assertEqual(self.out["unknown"][:4], ["?", "?", "?", "?"])   # 舵机、IMU、写进主程序、配手柄
        self.assertIn("读不到 configd", self.out["unknownText"])

    def test_c3_keyboard_repeat_after_leaving_does_not_drive(self):
        """代码审查 C3：按住 W 滚出手柄区会停；滚回来（W 还按着、焦点还在）浏览器的自动重复不能让它接着走。"""
        k = self.out["steps"]["kbd_repeat"]
        self.assertTrue(any(nonzero(p) for p in moves(k["held"])), "按住 W 时应该在走（不然这一步没测到东西）")
        self.assertIn({"vx": 0, "vy": 0, "vyaw": 0}, moves(k["out"]))
        self.assertTrue(k["activeBack"] and k["focus"])
        self.assertFalse(any(nonzero(p) for p in moves(k["back"])), "滚回来以后自动重复的按下让鸭子又走了")

    def test_c6_stage_canvas_keeps_pan_y_on_phone(self):
        self.assertEqual(self.out["phoneCanvas"]["computed"], "pan-y", self.out["phoneCanvas"])

    def test_c7_no_hold_after_fast_press_release_press(self):
        """代码审查 C7：回执拖 300 ms，快速按下、松开、再按下：最后松手以后 2 秒里一条 action_hold 都没有。"""
        h = self.out["steps"]["hold_race"]
        self.assertGreater(h["holdsDuring"], 0, h)                     # 按着的时候是在续命的（对照）
        self.assertEqual(h["holdsAfter"], 0, h)

    def test_servo_session_kept_with_bar_on_other_pages(self):
        """用户 10-18：「舵机这个页面出去的时候应该保持住使能」：有舵机保持着，离开不交还、不弹确认框；别的页顶上有提示条，
        刷新以后照样有；「交还主程序」两步确认；交还后提示条换成「已交还……sudo systemctl start robotd」，主程序连上后消失。"""
        b = self.out["servoBar"]
        self.assertIn("调舵机中 · 2 颗保持着 · 主程序停着（手柄、遥控、站走都不能用）", b["text"])
        self.assertIn("回舵机页", b["text"])
        self.assertEqual(b["dialogs"], 0)
        self.assertTrue(b["afterReload"])
        self.assertIn("交还：马上把 15 颗全部松开，鸭子会软下来——先扶住或放平", b["armed"])      # 审查 D7
        self.assertIn("急停用顶上红按钮或空格（手柄 Select 这时不管用）", b["text"])                # 审查 D6
        self.assertIn("别手动起 robotd，先点「交还主程序」", b["text"])                               # 审查 D9
        self.assertTrue(b["sticky"]["visible"], b["sticky"])                                         # 滚到手柄区还在（吸顶）
        self.assertTrue(b["visualFits"], "有舵机提示条时，姿态和视频仍能一起显示或正常滚动")
        p = b["phone"]
        self.assertTrue(p["visible"], p)                                                             # 手机滚到遥控卡也看得到
        self.assertEqual(p["badge"], "调舵机中")
        self.assertTrue(p["remote"])
        self.assertLessEqual(p["sw"], p["cw"])
        self.assertTrue(b["dbl"]["stillOpen"])                                                       # 双击不交还（审查 D4）
        self.assertTrue(b["dbl"]["armed"])
        self.assertTrue(b["dbl"]["disarmed"])                                                        # 3 秒复原
        self.assertTrue(b["earlyIgnored"])                                                           # 700 ms 内点确认不算
        self.assertTrue(b["stillThere"])                                                             # 主程序没连上，「已交还」一直在
        self.assertTrue(b["stillOpen"])                                # 点一下不交还
        self.assertIn("sudo systemctl start robotd", b["after"])
        self.assertTrue(b["gone"])

    def test_pad_3d_left_of_sticks_and_pauses_out_of_view(self):
        """用户 10-24：宽屏左侧3D与摄像头整体吸顶，卡片不相互覆盖；滚出去停画；
        3D 卡不算「在手柄区」（滚回顶上以后 active 是 false）。手机：3D 在遥控上面、矮、不 sticky，不能左右滑。"""
        d = self.out["pad3d"]
        self.assertGreaterEqual(d["visFrac"], 0.6, d)
        self.assertTrue(d["left"], d)
        self.assertEqual(d["sticky"], "static")
        self.assertEqual(d["stackSticky"], "sticky")
        self.assertTrue(d["cameraBelow"])
        self.assertEqual(d["touch"], "pan-y")
        self.assertTrue(d["drawsInView"])
        self.assertFalse(d["drawsOutOfView"])
        self.assertFalse(d["activeAtTop"])
        p = self.out["phone3d"]
        self.assertTrue(p["above"], p)
        self.assertLessEqual(p["h"], 240)
        self.assertEqual(p["sticky"], "static")

    def test_all_done_collapses_to_one_line(self):
        self.assertIn("上手 6 步都完成了（跳过 1 步）", self.done["done"])

    def test_all_done_line_expands_and_remembers(self):
        e = self.done["expanded"]
        self.assertEqual(e["rows"], 6)
        self.assertEqual(e["redo"], 5)                                # 5 行 ✓ 都有「重新做」
        self.assertEqual(e["skip"], 1)
        self.assertIn("收起", e["head"])
        self.assertEqual(self.done["expandedAfterReload"], 6)        # 展开状态存在 localStorage
        self.assertTrue(self.done["collapsedAfterReload"])

    def test_every_row_has_three_buttons(self):
        """用户 10-20：每一行任何时候都有「去做」「已完成」「跳过」（✓ 的行只有「重新做」）。"""
        rows = self.out["threeButtons"]
        self.assertGreaterEqual(len(rows), 3, rows)
        for r in rows:
            with self.subTest(step=r["step"]):
                self.assertEqual(len(r["labels"]), 3, r)
                self.assertEqual(r["labels"][1:], ["已完成", "跳过"], r)

    def test_skip_unskip_and_redo(self):
        """舵机「已完成」→ ✓「你标了已完成（时间）」，有「重新做」「取消」；IMU 跳过 → 「跳过了」（灰 ↷），现在该做到第 4 行；
        取消跳过复原；✓ 行的「重新做」去舵机页；「取消」复原。"""
        m = self.out["marked"]
        self.assertTrue(m["text"].startswith("你标了已完成（"), m)
        self.assertEqual(m["buttons"], ["重新做", "取消"])
        sk = self.out["skip"]
        self.assertEqual(sk["imu"], "onb-skip")
        self.assertEqual(sk["mark"], "↷")
        self.assertIn("跳过了（先不做）", sk["imuText"])
        self.assertEqual(sk["now"], "pad")
        self.assertEqual(self.out["unskip"], {"imu": "onb-todo", "now": "imu"})
        self.assertEqual(self.out["redoHash"], "#/servos")
        self.assertEqual(self.out["undone"], "onb-todo")

    def test_estop_skip_needs_two_clicks_within_3s(self):
        self.assertIn("确定跳过", self.out["estopOnce"]["text"])
        self.assertEqual(self.out["estopOnce"]["skipStill"], ["跳过"])  # 原按钮不在原地变（审查 D4），确认按钮是另一个
        self.assertEqual(self.out["estopOnce"]["state"], "onb-no")    # 点一次不生效
        self.assertEqual(self.out["estopDbl"], {"state": "onb-no", "armed": True},   # 真鼠标双击：不跳过，只是冒出确认
                         {k: self.out.get(k) for k in ("estopDblGap", "estopArmed300", "estopClicks", "estopTargets", "estopArms", "dblAtRects")})
        self.assertEqual(self.out["estopTimeout"], {"text": "跳过", "state": "onb-no"})   # 3 秒没再点：复原
        self.assertEqual(self.out["estopTwice"], "onb-skip")

    def test_imu_unverified_skip_needs_two_clicks(self):
        """主程序明说 IMU 方向没确认：以前跳过灰着；现在能点，第一下冒出写着后果的确认按钮，不点就不跳。"""
        b = self.out["imuBlocked"]
        self.assertFalse(b["disabled"])
        self.assertEqual(b["ask"], "确定跳过？主程序没确认 IMU 方向：跳过了鸭子也站不起来")
        self.assertEqual(b["state"], "onb-no")
        self.assertEqual(b["after"], "onb-no")


if __name__ == "__main__":
    unittest.main()
