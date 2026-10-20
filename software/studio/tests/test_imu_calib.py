"""IMU 站着校准的纯计算（studio/imu_calib.py）。

合成数据：随机安装方向 + 读数噪声 + 人手倾得不正，看能不能算回来；倾角不够、方向自相矛盾要判失败。
另外用真机录的 now-20261018.jsonl 核对两条约定：四元数 [w,x,y,z]（机身 → 世界）、safety.gravity = R(q)ᵀ·(0,0,-1)。
"""
import json
import math
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent)]

from studio import imu_calib as ic  # noqa: E402

FIXTURE = HERE / "fixtures" / "now-20261018.jsonl"
HZ = 10


def q_axis(axis, deg):
    a = ic.unit(axis)
    h = math.radians(deg) / 2
    return ic.q_normalize((math.cos(h), a[0] * math.sin(h), a[1] * math.sin(h), a[2] * math.sin(h)))


def q_random(rng):
    q = [rng.gauss(0, 1) for _ in range(4)]
    return ic.q_normalize(q)


def q_diff_deg(a, b):
    return ic.q_angle_deg(ic.q_mul(ic.q_conj(a), b))


def jitter(rng, g, sigma_deg):
    """给方向加一点噪声（各轴高斯，σ 按角度给）。"""
    s = math.radians(sigma_deg)
    return ic.unit(ic.add(g, (rng.gauss(0, s), rng.gauss(0, s), rng.gauss(0, s))))


class Duck:
    """合成一只鸭子：世界系 z 朝上；HOME 时机身姿态 stance（机身 → 世界）；芯片装在 mount（芯片 → 机身）。
    人手把整只鸭子绕世界的水平轴倾：前倾 = 绕 +y 转 +θ（头往下），左倾 = 绕 +x 转 −θ（左边往下）。
    skew：人手没对正，倾的轴绕竖直方向偏了几度。
    hand：提起来以后手的「零点」跟桌上站着差的那一点转动（人不可能正好端平）。"""

    def __init__(self, mount, stance=(1.0, 0.0, 0.0, 0.0), old_mount=None, noise_deg=0.15, seed=1, hand=(1.0, 0.0, 0.0, 0.0)):
        self.mount, self.stance, self.hand = mount, stance, hand
        self.old = old_mount
        self.rng = random.Random(seed)
        self.noise = noise_deg

    def reading(self, q_wb):
        g_b = ic.gravity_from_quat(q_wb)                                    # 机身系里的重力
        g_s = ic.mat_vec(ic.mat_t(ic.mat_from_q(self.mount)), g_b)          # 芯片系
        if self.old is None:
            return g_s
        return ic.q_rotate(self.old, g_s)                                    # 按旧方向换到「旧机身系」（robot.state 那样）

    def pose(self, step, deg, skew=0.0):
        if step == "still":
            return self.stance
        axis = {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}[step]
        axis = ic.q_rotate(q_axis((0, 0, 1), skew), axis)
        return ic.q_mul(q_axis(axis, deg), ic.q_mul(self.hand, self.stance))

    def samples(self, step, deg=18.0, skew=0.0, seconds=None, ramp=True, noise=None, pause=0.0, overshoot=0.0):
        """一步的读数：（pause 秒提起来端平）→ 慢慢倾过去（ramp）→（冲过头 overshoot° 再回来）→ 停住 1 秒。"""
        noise = self.noise if noise is None else noise
        out = []
        if step == "still":
            n = int((seconds or 3.0) * HZ)
            for i in range(n):
                out.append({"t": i / HZ, "g": list(jitter(self.rng, self.reading(self.stance), noise))})
            return out
        for i in range(int(pause * HZ)):
            out.append({"g": list(jitter(self.rng, self.reading(self.pose(step, 0.0, skew)), noise))})
        n_ramp = 8 if ramp else 0
        for i in range(n_ramp):
            d = deg * (i + 1) / (n_ramp + 1)
            out.append({"t": i / HZ, "g": list(jitter(self.rng, self.reading(self.pose(step, d, skew)), noise))})
        for d in ((deg + overshoot, deg + overshoot * 0.5) if overshoot else ()):
            out.append({"g": list(jitter(self.rng, self.reading(self.pose(step, d, skew)), noise))})
        for i in range(int((seconds or 1.0) * HZ)):
            out.append({"t": (n_ramp + i) / HZ, "g": list(jitter(self.rng, self.reading(self.pose(step, deg, skew)), noise))})
        return out

    def run(self, tilts=None, skews=None, **kw):
        tilts = tilts or {}
        skews = skews or {}
        return {k: self.samples(k, deg=tilts.get(k, 18.0), skew=skews.get(k, 0.0), **kw) for k in ic.STEPS}


class Helpers(unittest.TestCase):
    def test_quat_matrix_roundtrip(self):
        rng = random.Random(7)
        for _ in range(200):
            q = q_random(rng)
            self.assertLess(q_diff_deg(q, ic.q_from_mat(ic.mat_from_q(q))), 1e-6)

    def test_q_between(self):
        rng = random.Random(8)
        for _ in range(100):
            a = ic.unit((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
            b = ic.unit((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)))
            self.assertLess(ic.angle_deg(ic.q_rotate(ic.q_between(a, b), a), b), 1e-6)
        self.assertLess(ic.angle_deg(ic.q_rotate(ic.q_between((0, 0, 1), (0, 0, -1)), (0, 0, 1)), (0, 0, -1)), 1e-6)

    def test_describe_standard_mounts(self):
        d = ic.describe_mount((1, 0, 0, 0))
        self.assertEqual(d["text"], "芯片 x 朝前，芯片 y 朝左，芯片 z 朝上")
        self.assertLess(d["off_deg"], 1e-6)
        self.assertEqual(len(ic.STANDARD_MOUNTS), 24)
        # 绕 y 转 90°：芯片 x → 机身下、z → 机身前
        d = ic.describe_mount(q_axis((0, 1, 0), 90))
        self.assertEqual(d["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        d = ic.describe_mount(ic.q_mul(q_axis((0, 1, 0), 90), q_axis((1, 0, 0), 7)))
        self.assertAlmostEqual(d["off_deg"], 7.0, places=3)

    def test_sample_formats(self):
        g = ic.unit((0.1, -0.2, -0.97))
        self.assertLess(ic.angle_deg(ic.sample_gravity({"g": g}), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity(list(g)), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity({"acc": ic.scale(g, -9.81)}), g), 1e-9)
        self.assertLess(ic.angle_deg(ic.sample_gravity({"quat": ic.q_between(g, ic.DOWN)}), g), 1e-6)
        self.assertIsNone(ic.sample_gravity({"g": [0, 0, 0]}))
        self.assertIsNone(ic.sample_gravity({"quat": [1, 2]}))
        self.assertIsNone(ic.sample_gravity("x"))

    def test_tilt_of_directions(self):
        g0 = ic.DOWN
        for step, want in (("fwd", 0), ("left", 90), ("back", 180), ("right", -90)):
            duck = Duck((1, 0, 0, 0), noise_deg=0)
            g = duck.reading(duck.pose(step, 15))
            t, d = ic.tilt_of(g0, g)
            self.assertAlmostEqual(t, 15, places=6)
            self.assertAlmostEqual(abs(((d - want) + 180) % 360 - 180), 0, places=6, msg=step)


class RealData(unittest.TestCase):
    """真机录的数据：约定对不对。"""

    def rows(self):
        out = []
        for line in FIXTURE.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("kind") == "notify" and (r.get("msg") or {}).get("method") == "robot.state":
                out.append(r["msg"]["params"])
        return out

    def test_gravity_is_projected_quat_wxyz(self):
        rows = self.rows()
        self.assertGreater(len(rows), 20)
        # robotd 的重力是最近 3 个读数取中值（官方 duck-control/src/imu.rs:140-155），跟这一刻的四元数差一点点：
        # 录的数据里最多差 0.08°。约定要是错了（xyzw、或者转反了）会差几度到几十度
        exact = 0
        for p in rows:
            g = ic.gravity_from_quat(p["imu"]["quat"])
            d = ic.angle_deg(g, p["safety"]["gravity"])
            self.assertLess(d, 0.25)
            exact += d < 1e-3
        self.assertGreater(exact, 0)
        wrong = ic.gravity_from_quat([rows[0]["imu"]["quat"][i] for i in (1, 2, 3, 0)])       # 当成 xyzw 读
        self.assertGreater(ic.angle_deg(wrong, rows[0]["safety"]["gravity"]), 5)      # 实际差 17°

    def test_still_on_real_standing_data(self):
        rows = self.rows()
        st, g0 = ic.check_still([{"g": p["safety"]["gravity"]} for p in rows])
        self.assertTrue(st["ok"], st)
        self.assertLess(st["spread_deg"], 0.2)
        self.assertAlmostEqual(ic.tilt_of(ic.DOWN, g0)[0], 2.6, delta=0.2)   # 跟 home_start_guard.tilt_deg 2.63° 一致


class Solve(unittest.TestCase):
    def assertMount(self, res, want, tol):
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], want), tol, res)

    def test_sensor_frame_random_mounts_exact(self):
        rng = random.Random(11)
        for i in range(30):
            mount = q_random(rng)
            res = ic.solve(Duck(mount, noise_deg=0.0, seed=i).run(), frame="sensor")
            self.assertMount(res, mount, 0.01)
            self.assertEqual(res["quality"]["grade"], "good")

    def test_sensor_frame_noise_and_human_error(self):
        rng = random.Random(12)
        worst = 0.0
        for i in range(40):
            mount = q_random(rng)
            skews = {k: rng.uniform(-5, 5) for k in ic.TILTS}
            tilts = {k: rng.uniform(12, 28) for k in ic.TILTS}
            res = ic.solve(Duck(mount, noise_deg=0.3, seed=100 + i).run(tilts, skews), frame="sensor")
            self.assertTrue(res["ok"], res.get("reason"))
            worst = max(worst, q_diff_deg(res["mount"], mount))
        self.assertLess(worst, 5.0)        # 四步手歪 ±5° 互相抵掉一部分；只剩朝向有误差，上下由静止定、很准

    def test_body_frame_corrects_old_mount(self):
        """robot.state 的读数已经乘过旧方向：修正 ∘ 旧方向 = 真方向；8.5° 那种装歪能算出来。"""
        rng = random.Random(13)
        for i in range(20):
            mount = q_random(rng)
            err = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)), rng.uniform(0, 12))
            old = ic.q_normalize(ic.q_mul(err, mount))
            res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0, seed=i).run(), frame="body", old_mount=old)
            self.assertMount(res, mount, 0.01)
            self.assertAlmostEqual(res["parts"]["total_deg"], ic.q_angle_deg(err), delta=0.01)
        # 只是往前装歪了 8.5°（10-12 一号鸭猛冲的情形）：拆出来的前倾 ≈ 8.5°，朝向 ≈ 0
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((0, 1, 0), -8.5), mount))
        res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0).run(), frame="body", old_mount=old)
        self.assertMount(res, mount, 0.01)
        self.assertAlmostEqual(res["parts"]["pitch_deg"], 8.5, delta=0.05)
        self.assertAlmostEqual(res["parts"]["yaw_deg"], 0.0, delta=0.05)
        self.assertTrue(res["confirm"])                    # 8.5° > 8°：要人确认
        self.assertEqual(res["standard"]["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")

    def test_small_correction_needs_no_confirm(self):
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((1, 0, 0), 2.0), mount))
        res = ic.solve(Duck(mount, old_mount=old).run(), frame="body", old_mount=old)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["confirm"], [])

    def test_stance_tilt_is_folded_in(self):
        """HOME 时机身其实前倾了 4°（腿的原因）：整体补偿后，站好时读数 = 官方 HOME（水平）。"""
        mount = q_axis((0, 0, 1), 30)
        stance = q_axis((0, 1, 0), 4.0)
        res = ic.solve(Duck(mount, stance=stance, noise_deg=0.0).run(), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        g_still_sensor = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(stance))
        self.assertLess(ic.angle_deg(ic.q_rotate(res["mount"], g_still_sensor), ic.DOWN), 1e-6)
        # 朝向不受影响：新机身系里前倾还是往 +x
        g_fwd = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(ic.q_mul(q_axis((0, 1, 0), 18), stance)))
        g_new = ic.q_rotate(res["mount"], g_fwd)
        self.assertGreater(g_new[0], 0.25)
        self.assertLess(abs(g_new[1]), 1e-6)

    def test_home_gravity_not_level(self):
        """官方 HOME 机身本来就前倾 3°，鸭子站得也正好是这样：真方向原样算回来。"""
        rng = random.Random(14)
        stance = q_axis((0, 1, 0), 3.0)
        hg = ic.gravity_from_quat(stance)
        for i in range(10):
            mount = q_random(rng)
            res = ic.solve(Duck(mount, stance=stance, noise_deg=0.0, seed=i).run(), frame="sensor", home_gravity=hg)
            self.assertMount(res, mount, 0.01)

    def test_flat_list_same_as_dict(self):
        data = Duck(q_axis((1, 1, 0), 40)).run()
        flat = [dict(s, step=k) for k in ic.STEPS for s in data[k]]
        a, b = ic.solve(data, frame="sensor"), ic.solve(flat, frame="sensor")
        self.assertEqual(a["mount"], b["mount"])

    def test_acc_and_quat_inputs_match(self):
        data = Duck(q_axis((0, 1, 1), 70), noise_deg=0.2).run()
        acc = {k: [{"acc": list(ic.scale(s["g"], -9.81))} for s in v] for k, v in data.items()}
        quat = {k: [{"quat": list(ic.q_between(s["g"], ic.DOWN))} for s in v] for k, v in data.items()}
        r0, r1, r2 = (ic.solve(d, frame="sensor") for d in (data, acc, quat))
        self.assertLess(q_diff_deg(r0["mount"], r1["mount"]), 1e-6)
        self.assertLess(q_diff_deg(r0["mount"], r2["mount"]), 1e-4)

    def test_result_is_json(self):
        res = ic.solve(Duck(q_axis((0, 1, 0), 90), old_mount=(1, 0, 0, 0)).run(), frame="body", old_mount=(1, 0, 0, 0))
        json.dumps(res, ensure_ascii=False)


class Fails(unittest.TestCase):
    mount = q_axis((0, 1, 0), 90)

    def solve(self, data):
        return ic.solve(data, frame="sensor")

    def test_tilt_too_small(self):
        res = self.solve(Duck(self.mount).run(tilts={"fwd": 6}))
        self.assertFalse(res["ok"])
        self.assertFalse(res["steps"]["fwd"]["ok"])
        self.assertIn("前倾", res["reason"])
        self.assertIn("至少", res["reason"])

    def test_tilt_too_big(self):
        res = self.solve(Duck(self.mount).run(tilts={"left": 45}))
        self.assertFalse(res["ok"])
        self.assertIn("太多", res["steps"]["left"]["msg"])

    def test_still_not_still(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["still"] = duck.samples("still", noise=2.0)
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("晃", res["reason"])

    def test_still_too_short(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["still"] = duck.samples("still", seconds=0.8)
        self.assertFalse(self.solve(data)["ok"])

    def test_missing_step(self):
        data = Duck(self.mount).run()
        data["right"] = []
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("右倾", res["reason"])

    def test_not_held_still(self):
        """倾到 18° 马上回来、没停住：最大倾角附近只有一两个读数。"""
        duck = Duck(self.mount)
        data = duck.run()
        swing = [2, 4, 6, 8, 10, 12, 14, 16, 18, 16, 14, 12, 10, 8, 6, 4, 2]
        data["back"] = [{"g": list(duck.reading(duck.pose("back", d)))} for d in swing]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("没停住", res["steps"]["back"]["msg"])

    def test_circling_not_held(self):
        """倾角一直 15°，但方向在转圈：倾角够、停住的读数也够，方向晃得太厉害。"""
        duck = Duck(self.mount)
        data = duck.run()
        data["fwd"] = [{"g": list(duck.reading(duck.pose("fwd", 15, skew=s)))} for s in range(-30, 31, 5)]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("没停住", res["steps"]["fwd"]["msg"])

    def test_same_side_twice(self):
        """「后倾」那步其实又往前倾了。"""
        duck = Duck(self.mount)
        data = duck.run()
        data["back"] = duck.samples("fwd")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("前倾和后倾", res["reason"])

    def test_left_right_swapped(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("做反了", res["reason"])
        # 旧方向可信（frame=body）时能说出是哪一对做反了
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertFalse(res["ok"])
        self.assertIn("左倾、右倾做反了", res["reason"])

    def test_tilted_diagonally(self):
        """左倾、右倾都斜了 30°（每步只斜 15°，但两对差 30°）：前后和左右不垂直。"""
        res = self.solve(Duck(self.mount).run(skews={"left": 30, "right": 30}))
        self.assertFalse(res["ok"])
        self.assertIn("不垂直", res["reason"])

    def test_turned_around_needs_confirm(self):
        """前后、左右都做反了（鸭子转了个身）：自检查不出来，但跟旧方向比朝向改了 180°，要人确认。"""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(abs(res["parts"]["yaw_deg"]), 170)
        self.assertTrue(any("转了个身" in c for c in res["confirm"]))

    def test_body_frame_without_old_mount(self):
        res = ic.solve(Duck(self.mount, old_mount=self.mount).run(), frame="body")
        self.assertTrue(res["ok"])
        self.assertNotIn("mount", res)
        self.assertTrue(res["notes"])

    def test_bad_frame(self):
        with self.assertRaises(ValueError):
            ic.solve({}, frame="world")
        with self.assertRaises(ValueError):
            ic.solve({}, mode="quick")


class RobotdFormula(unittest.TestCase):
    """A1：照 fork 固件 robotd 的 TrunkFrame::push 逐字合成读数（duck-control/src/imu.rs:137-170）：
        q_机身 = q_芯片 ⊗ mount⁻¹，gravity = rotate_inverse(q_机身, [0,0,-1]) = q⁻¹·v·q。
    四元数乘法、转动都在这里另写一份，不用被测代码的 q_mul / q_rotate / gravity_from_quat。"""

    @staticmethod
    def hmul(a, b):                       # Hamilton 乘积，照教科书逐项写
        w1, x1, y1, z1 = a
        w2, x2, y2, z2 = b
        return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)

    @staticmethod
    def conj(q):
        return (q[0], -q[1], -q[2], -q[3])

    @classmethod
    def rotate_inverse(cls, q, v):        # q⁻¹ · (0, v) · q
        r = cls.hmul(cls.hmul(cls.conj(q), (0.0, v[0], v[1], v[2])), q)
        return r[1:]

    @staticmethod
    def axis_angle(axis, deg):
        n = math.sqrt(sum(a * a for a in axis))
        h = math.radians(deg) / 2
        return (math.cos(h),) + tuple(a / n * math.sin(h) for a in axis)

    @staticmethod
    def norm4(q):
        n = math.sqrt(sum(c * c for c in q))
        return tuple(c / n for c in q)

    def test_robotd_pipeline_any_old_mount(self):
        rng = random.Random(31)
        worst = 0.0
        for _ in range(60):
            true_mount = self.norm4([rng.gauss(0, 1) for _ in range(4)])     # 芯片 → 机身（真的）
            stored = self.norm4([rng.gauss(0, 1) for _ in range(4)])         # 鸭子上存的（错多少都行）
            stance = self.axis_angle((0, 0, 1), rng.uniform(-180, 180))       # 站好：水平，偏航随便

            def reading(q_trunk_world):
                q_sensor_world = self.hmul(q_trunk_world, true_mount)         # 芯片姿态 = 机身姿态 ⊗ 芯片→机身
                q_trunk_robotd = self.hmul(q_sensor_world, self.conj(stored))  # robotd：q_芯片 ⊗ mount⁻¹
                g = self.rotate_inverse(q_trunk_robotd, (0.0, 0.0, -1.0))
                # 被测代码的约定也顺手核一下：gravity_from_quat 跟 rotate_inverse 一致
                self.assertLess(ic.angle_deg(g, ic.gravity_from_quat(q_trunk_robotd)), 1e-4)   # acos 在 0 附近只准到 ~1e-6°
                return {"g": list(g)}

            data = {"still": [reading(stance)] * 20}
            for k, ax in {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}.items():
                ax_w = self.rotate_inverse(self.conj(stance), ax)              # 机身的这根轴在世界里（q·v·q⁻¹）
                data[k] = [reading(self.hmul(self.axis_angle(ax_w, 18), stance))] * 10
            res = ic.solve(data, frame="body", old_mount=stored, old_verified=False)
            self.assertTrue(res["ok"], res.get("reason"))
            d = abs(sum(a * b for a, b in zip(res["mount"], true_mount)))
            worst = max(worst, math.degrees(2 * math.acos(min(1.0, d))))
        self.assertLess(worst, 0.01)          # 十来次连乘的舍入误差，acos 在 1 附近会放大

    def test_default_mounts_in_words(self):
        # BNO08x 默认：trunk_imu.rs:63「mounted sensor X left, Y up, Z forward」
        self.assertEqual(ic.describe_mount([0.5, 0.5, 0.5, 0.5])["text"], "芯片 x 朝左，芯片 y 朝上，芯片 z 朝前")
        # 总线小板默认：官方 imu.rs:76「trunk = [+raw_z, +raw_y, −raw_x]」
        r = math.sqrt(0.5)
        self.assertEqual(ic.describe_mount([r, 0, r, 0])["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        # 二号鸭现在存的（fixture 第 6 行）：标准装法再偏 6°
        d = ic.describe_mount([0.698208849, 0.036261753, 0.714055021, 0.036261753])
        self.assertEqual(d["text"], "芯片 x 朝下，芯片 y 朝左，芯片 z 朝前")
        self.assertAlmostEqual(d["off_deg"], 6.0, delta=0.1)


class HumanHandling(unittest.TestCase):
    """A2：真人手上会出的状况。"""
    mount = q_axis((0, 1, 0), 90)

    def test_overshoot_then_settle(self):
        """冲过头 4° 再回来停住：只算回来以后停住的那段。"""
        res = ic.solve(Duck(self.mount, noise_deg=0.2).run(overshoot=4.0), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], self.mount), 1.0)
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 18, delta=0.6)

    def test_overshoot_reviewer_case(self):
        """审查员的例子：倾到 21° 回到 17° 停 1.5 秒（以前判「只有 1 个读数」）。"""
        g = lambda d: {"g": list(ic.gravity_from_quat(q_axis((0, 1, 0), d)))}
        still = [g(0)] * 30
        step = lambda ax, d, n=15: [{"g": list(ic.gravity_from_quat(q_axis(ax, d)))}] * n
        data = {"still": still, "fwd": [g(x) for x in (4, 8, 12, 16, 19, 21, 19)] + [g(17)] * 15,
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 17, delta=0.01)

    def test_single_spike(self):
        """停住时混进一帧乱跳（BNO085 那种），在中间、在最后都不该判失败。"""
        duck = Duck(self.mount, noise_deg=0.1)
        data = duck.run()
        spike = {"g": list(duck.reading(duck.pose("fwd", 33)))}
        data["fwd"] = data["fwd"][:13] + [spike] + data["fwd"][13:]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["steps"]["fwd"]["skipped"], 1)
        data["back"] = data["back"] + [{"g": list(duck.reading(duck.pose("back", 33)))}]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], self.mount), 0.5)

    def test_hand_reference_offset(self):
        """提起来时手的零点偏 4.9°（端平只要求 5° 以内）：每步以自己端平的那一下为零点，不再判成「斜着倾」。"""
        rng = random.Random(41)
        for i in range(20):
            hand = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), 0), 4.9)
            mount = q_random(rng)
            duck = Duck(mount, noise_deg=0.0, seed=i, hand=hand)
            res = ic.solve(duck.run(tilts={"fwd": 13, "back": 13, "left": 13, "right": 13}, pause=0.8), frame="sensor")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertEqual(res["steps"]["fwd"]["ref"], "端平那一下")
            self.assertAlmostEqual(res["steps"]["fwd"]["ref_offset_deg"], 4.9, delta=0.3)   # 端平窗口可能带上爬坡第一个读数（沿倾的方向，不影响朝向）
            self.assertLess(q_diff_deg(res["mount"], mount), 0.3)
            self.assertLess(res["quality"]["max_skew_deg"], 1.0)      # 零点偏 4.9° 只剩二阶的一点点

    def test_consistent_twist_fails(self):
        """前倾、后倾都拧着 15°（审查员 probe3：以前「相反差 0」能过、朝向错 7.5°）：前后和左右差 15° → 判失败。"""
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 15, "back": 15}), frame="sensor")
        self.assertFalse(res["ok"])
        self.assertIn("不垂直", res["reason"])
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 5, "back": 5}), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))           # 拧 5° 还能用，朝向大约准到 ±2.5°
        self.assertAlmostEqual(res["quality"]["yaw_uncert_deg"], 2.5, delta=0.1)

    def test_tilt_max_by_any_held_reading(self):
        """G6：停住段里有一个 36° 就算太多（以前按平均 34.6° 放过去了）。"""
        g = lambda ax, d: {"g": list(ic.gravity_from_quat(q_axis(ax, d)))}
        still = [g((0, 1, 0), 0)] * 30
        step = lambda ax, d: [g(ax, d)] * 12
        data = {"still": still, "fwd": step((0, 1, 0), 34.5) + [g((0, 1, 0), 36)],
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertFalse(res["ok"])
        self.assertIn("太多", res["reason"])
        self.assertAlmostEqual(res["steps"]["fwd"]["max_tilt_deg"], 36, delta=0.01)

    def test_bad_numbers_dropped(self):
        """G5：inf / nan 的读数丢掉，不崩。"""
        self.assertIsNone(ic.sample_gravity({"g": [float("inf"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"g": [float("nan"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"acc": [0, float("inf"), 9.8]}))
        self.assertIsNone(ic.sample_gravity({"quat": [float("nan"), 0, 0, 0]}))
        self.assertIsNone(ic.sample_gravity({"g": [1e308, 1e308, 1e308]}))     # 平方溢出成 inf
        data = Duck(self.mount).run()
        data["still"] = data["still"][:25] + [{"g": [float("inf"), 0, 0]}] * 10
        data["left"] = data["left"] + [{"g": [float("nan")] * 3}]
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["steps"]["still"]["dropped"], 10)
        self.assertEqual(res["steps"]["left"]["dropped"], 1)
        data["still"] = [{"g": [float("inf"), 0, 0]}] * 30
        res = ic.solve(data, frame="sensor")
        self.assertFalse(res["ok"])
        self.assertIn("静止的读数只有 0 个", res["reason"])

    def test_still_spikes_tolerated(self):
        """静止那 3 秒里乱跳两帧（30 帧里不到 10%）：不算晃；一直晃 2° 才算。"""
        duck = Duck(self.mount, noise_deg=0.1)
        data = duck.run()
        spike = {"g": list(duck.reading(duck.pose("left", 12)))}
        data["still"][5] = spike
        data["still"][20] = spike
        res = ic.solve(data, frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(res["steps"]["still"]["max_dev_deg"], 10)
        self.assertLess(q_diff_deg(res["mount"], self.mount), 0.5)

    def test_big_stand_offset_needs_confirm(self):
        """G4：站着时读数离 HOME 超过 5°（静止时手按着、桌子斜、腿没校好）要人确认。"""
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 6.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["parts"]["stand_tilt_deg"], 6.0, delta=0.01)
        self.assertTrue(any("离官方 HOME 差 6.0°" in c for c in res["confirm"]))
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 4.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertFalse(any("离官方 HOME" in c for c in res["confirm"]))

    def test_flip_after_coarse(self):
        """旧方向是上次粗校写的：转了个身的提示改成「上次粗校可能做反了」。"""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount, old_source="coarse")
        self.assertTrue(any("上次粗校可能做反了" in c for c in res["confirm"]))


class Redo(unittest.TestCase):
    """没过时 redo 说清楚要补做哪几步（页面只让人补那几步）。"""
    mount = q_axis((0, 1, 0), 90)

    def test_each_failure_names_steps(self):
        duck = Duck(self.mount)
        self.assertEqual(ic.solve(duck.run(tilts={"fwd": 6}), frame="sensor")["redo"], ["fwd"])
        data = duck.run()
        data["right"] = []
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["right"])
        data = duck.run()
        data["still"] = duck.samples("still", noise=3.0)
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["still"])
        data = duck.run()
        data["back"] = duck.samples("fwd")
        self.assertEqual(ic.solve(data, frame="sensor")["redo"], ["fwd", "back"])
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"left": 30}), frame="sensor")
        self.assertFalse(res["ok"])
        self.assertEqual(res["redo"], ["left"])
        self.assertTrue(ic.solve(duck.run(), frame="sensor")["ok"])

    def test_swapped_and_cross_with_and_without_trust(self):
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        self.assertEqual(ic.solve(data, frame="body", old_mount=self.mount)["redo"], ["left", "right"])
        self.assertEqual(ic.solve(data, frame="body", old_mount=self.mount, old_verified=False)["redo"], list(ic.TILTS))
        twisted = Duck(self.mount, old_mount=self.mount, noise_deg=0.0).run(skews={"fwd": 15, "back": 15})
        res = ic.solve(twisted, frame="body", old_mount=self.mount)
        self.assertIn("不垂直", res["reason"])
        self.assertEqual(res["redo"], ["fwd", "back"])
        self.assertEqual(ic.solve(twisted, frame="body", old_mount=self.mount, old_verified=False)["redo"], list(ic.TILTS))


class Coarse(unittest.TestCase):
    """粗校：方向一次都没确认过、站不起来时，软着托起来做「静止 + 前倾（+ 后倾）」。"""

    def test_still_and_fwd_only(self):
        rng = random.Random(21)
        for i in range(20):
            mount = q_random(rng)
            data = Duck(mount, noise_deg=0.0, seed=i).run()
            res = ic.solve({"still": data["still"], "fwd": data["fwd"]}, frame="sensor", mode="coarse")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertLess(q_diff_deg(res["mount"], mount), 0.01)
            self.assertEqual(res["quality"]["grade"], "coarse")
            self.assertTrue(any("粗校" in n for n in res["notes"]))

    def test_with_back_and_default_old_mount(self):
        """LSM6DSV16X 的默认方向是单位四元数（trunk_imu.rs:56-58），跟真方向差很多：没验过就不要人确认「改太多」。"""
        mount = q_axis((0, 1, 0), 90)
        old = (1.0, 0.0, 0.0, 0.0)
        data = Duck(mount, old_mount=old, noise_deg=0.2).run()
        part = {k: data[k] for k in ("still", "fwd", "back")}
        res = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=False)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], mount), 1.0)
        # 不拿没验过的默认值比「改太多」，但一定要人对照模块实际装法勾一下（做反了 robotd 验不出左右，方案 S1）
        self.assertEqual(len(res["confirm"]), 1)
        self.assertIn("芯片 x 朝下，芯片 y 朝左，芯片 z 朝前", res["confirm"][0])
        res2 = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=True)
        self.assertEqual(len(res2["confirm"]), 2)

    def test_needs_fwd(self):
        data = Duck(q_axis((0, 1, 0), 90)).run()
        res = ic.solve({"still": data["still"]}, frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("前倾", res["reason"])

    def test_back_same_side_fails(self):
        duck = Duck(q_axis((0, 1, 0), 90))
        res = ic.solve({"still": duck.samples("still"), "fwd": duck.samples("fwd"), "back": duck.samples("fwd")},
                       frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("前倾和后倾", res["reason"])


if __name__ == "__main__":
    unittest.main()
