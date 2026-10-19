"""IMU 页后端（studio/imu.py）：推给页面的状态取对了没有，指令该拒的拒。

用 tests/fixtures/now-20261018.jsonl（10-18 二号鸭真机录的）里的 busStatus 和 calibration-status。
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio.imu import ImuBackend, Refused  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.robotd import Sample  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"


def recorded(method):
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("kind") == "reply" and d.get("method") == method:
            return d["reply"]["result"]
    raise KeyError(method)


class FakeRd:
    def __init__(self, bus=None, calib=None):
        self.bus, self.calib = Sample(), Sample()
        if bus is not None:
            self.bus.set(bus)
        if calib is not None:
            self.calib.set(calib)


class ImuBackendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Log(Path(self.tmp.name) / "logs", echo=False, background=False)

    def tearDown(self):
        self.tmp.cleanup()

    def backend(self, **kw):
        return ImuBackend(FakeRd(**kw), self.log, self.tmp.name)

    def test_view_picks_mount_of_chip_in_use(self):
        # 二号鸭用 LSM6DSV16X：要取 imu_mounts 里它那份，不是顶上那个（那是另一种芯片的）
        v = self.backend(bus=recorded("robot.busStatus"), calib=recorded("robot.busCommand")).view()
        self.assertEqual(v["t"], "imu")
        self.assertEqual(v["source"], "lsm6dsv16x")
        self.assertEqual(v["mount"]["quat"][0], 0.698208849)
        self.assertIs(v["mount"]["verified"], True)
        self.assertTrue(v["ready"])
        self.assertEqual(v["reader"]["state"], "streaming")
        json.dumps(v)                                           # 能直接发给页面

    def test_view_without_robotd(self):
        v = self.backend().view()
        self.assertIsNone(v["source"])
        self.assertIsNone(v["mount"])
        self.assertIsNone(v["stand_calib_at"])

    def test_view_bus_board_falls_back_to_top_level_mount(self):
        # 总线小板：busStatus 没有 imu_source → 当成 bus，方向用顶上的 imu_mount_quat
        bus = {"native": {"imu_age_ms": 5}}
        calib = {"calibration": {"imu_mount_quat": [1, 0, 0, 0], "imu_mount_verified": False}}
        v = self.backend(bus=bus, calib=calib).view()
        self.assertEqual(v["source"], "bus")
        self.assertEqual(v["mount"], {"quat": [1, 0, 0, 0], "verified": False})

    def test_stand_calib_time_read_from_state_dir(self):
        (Path(self.tmp.name) / "imu-stand-calib.json").write_text('{"at": "2026-10-18 02:10"}', encoding="utf-8")
        self.assertEqual(self.backend().view()["stand_calib_at"], "2026-10-18 02:10")

    def test_refuses_bad_or_unfinished_ops(self):
        b = self.backend()
        for args, word in (({"op": "solve"}, "没收到读数"), ({"op": "solve", "samples": [{}] * 6001}, "读数太多"),
                           ({"op": "save"}, "鸭子上"), ({"op": "coarse"}, "鸭子上"), ({"op": "detect"}, "鸭子上"),
                           ({"op": "set_chip", "chip": "bno08x"}, "鸭子上"), ({"op": "rm -rf"}, "不认识")):
            with self.subTest(args=args.get("op")):
                with self.assertRaises(Refused) as cm:
                    asyncio.run(b.handle(args, "测试"))
                self.assertIn(word, str(cm.exception))

    def test_solve_bad_samples_fails_politely(self):
        # 乱七八糟的读数：回 ok=False 和一句原因，不抛异常、不把后端弄挂
        b = self.backend()
        res = asyncio.run(b.handle({"op": "solve", "samples": [{"step": "still", "g": [0, 0, -1]}]}, "测试"))
        self.assertFalse(res["ok"])
        self.assertTrue(res["reason"])
        self.assertIs(b.last_result, res)


if __name__ == "__main__":
    unittest.main()
