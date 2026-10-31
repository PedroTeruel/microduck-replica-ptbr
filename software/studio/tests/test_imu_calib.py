"""Cálculos puros da calibração do IMU em pé (studio/imu_calib.py).

Os dados sintéticos combinam orientações de montagem aleatórias, ruído de leitura e inclinações imprecisas feitas à mão.
Os casos verificam a recuperação da orientação e a rejeição de inclinações insuficientes ou contraditórias.
O arquivo real now-20261018.jsonl também confirma duas convenções: quaternion [w,x,y,z] (corpo → mundo) e
safety.gravity = R(q)ᵀ·(0,0,-1).
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
    """Adiciona ruído à direção usando distribuições gaussianas por eixo e sigma em graus."""
    s = math.radians(sigma_deg)
    return ic.unit(ic.add(g, (rng.gauss(0, s), rng.gauss(0, s), rng.gauss(0, s))))


class Duck:
    """Robô sintético: z aponta para cima no referencial mundial; stance é a postura do corpo no HOME (corpo → mundo)
    e mount é a orientação do sensor (sensor → corpo). O operador inclina o robô em torno de um eixo horizontal:
    inclinar para a frente gira +θ em torno de +y (abaixa a cabeça); para a esquerda gira −θ em torno de +x.
    skew representa o desvio do eixo de inclinação em torno da vertical. hand representa o pequeno desvio de
    nivelamento da mão em relação à postura na mesa; não é possível nivelar perfeitamente ao erguer o robô."""

    def __init__(self, mount, stance=(1.0, 0.0, 0.0, 0.0), old_mount=None, noise_deg=0.15, seed=1, hand=(1.0, 0.0, 0.0, 0.0)):
        self.mount, self.stance, self.hand = mount, stance, hand
        self.old = old_mount
        self.rng = random.Random(seed)
        self.noise = noise_deg

    def reading(self, q_wb):
        g_b = ic.gravity_from_quat(q_wb)                                    # Gravidade no referencial do corpo.
        g_s = ic.mat_vec(ic.mat_t(ic.mat_from_q(self.mount)), g_b)          # Referencial do sensor.
        if self.old is None:
            return g_s
        return ic.q_rotate(self.old, g_s)                                    # Converte para o referencial do corpo antigo, como em robot.state.

    def pose(self, step, deg, skew=0.0):
        if step == "still":
            return self.stance
        axis = {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}[step]
        axis = ic.q_rotate(q_axis((0, 0, 1), skew), axis)
        return ic.q_mul(q_axis(axis, deg), ic.q_mul(self.hand, self.stance))

    def samples(self, step, deg=18.0, skew=0.0, seconds=None, ramp=True, noise=None, pause=0.0, overshoot=0.0):
        """Leituras de uma etapa: ergue e nivela por pause segundos, inclina gradualmente (ramp),
        talvez ultrapasse overshoot graus e volte, depois mantém a posição por 1 segundo."""
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
        self.assertEqual(d["text"], "Eixo x do sensor aponta para frente; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para cima")
        self.assertLess(d["off_deg"], 1e-6)
        self.assertEqual(len(ic.STANDARD_MOUNTS), 24)
        # Rotação de 90° em torno de y: x do sensor aponta para baixo no corpo; z aponta para a frente.
        d = ic.describe_mount(q_axis((0, 1, 0), 90))
        self.assertEqual(d["text"], "Eixo x do sensor aponta para baixo; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para frente")
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
    """Confere as convenções com dados gravados no robô real."""

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
        # robotd usa a mediana das três leituras mais recentes de gravidade (duck-control/src/imu.rs:140-155),
        # portanto há uma pequena diferença em relação ao quaternion do instante. Nos dados gravados, o máximo é 0,08°.
        # Uma convenção incorreta (xyzw ou rotação invertida) produziria diferenças de vários graus.
        exact = 0
        for p in rows:
            g = ic.gravity_from_quat(p["imu"]["quat"])
            d = ic.angle_deg(g, p["safety"]["gravity"])
            self.assertLess(d, 0.25)
            exact += d < 1e-3
        self.assertGreater(exact, 0)
        wrong = ic.gravity_from_quat([rows[0]["imu"]["quat"][i] for i in (1, 2, 3, 0)])       # Interpreta incorretamente como xyzw.
        self.assertGreater(ic.angle_deg(wrong, rows[0]["safety"]["gravity"]), 5)      # Diferença observada: 17°.

    def test_still_on_real_standing_data(self):
        rows = self.rows()
        st, g0 = ic.check_still([{"g": p["safety"]["gravity"]} for p in rows])
        self.assertTrue(st["ok"], st)
        self.assertLess(st["spread_deg"], 0.2)
        self.assertAlmostEqual(ic.tilt_of(ic.DOWN, g0)[0], 2.6, delta=0.2)   # Compatível com home_start_guard.tilt_deg = 2,63°.


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
        self.assertLess(worst, 5.0)        # Os desvios manuais de ±5° se compensam parcialmente; o repouso define cima com precisão.

    def test_body_frame_corrects_old_mount(self):
        """robot.state já aplica a orientação antiga: correção ∘ orientação antiga = orientação real, inclusive com montagem inclinada em 8,5°."""
        rng = random.Random(13)
        for i in range(20):
            mount = q_random(rng)
            err = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1)), rng.uniform(0, 12))
            old = ic.q_normalize(ic.q_mul(err, mount))
            res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0, seed=i).run(), frame="body", old_mount=old)
            self.assertMount(res, mount, 0.01)
            self.assertAlmostEqual(res["parts"]["total_deg"], ic.q_angle_deg(err), delta=0.01)
        # Apenas 8,5° de inclinação frontal na montagem; a decomposição deve apontar pitch ≈ 8,5° e yaw ≈ 0.
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((0, 1, 0), -8.5), mount))
        res = ic.solve(Duck(mount, old_mount=old, noise_deg=0.0).run(), frame="body", old_mount=old)
        self.assertMount(res, mount, 0.01)
        self.assertAlmostEqual(res["parts"]["pitch_deg"], 8.5, delta=0.05)
        self.assertAlmostEqual(res["parts"]["yaw_deg"], 0.0, delta=0.05)
        self.assertTrue(res["confirm"])                    # 8,5° > 8°: exige confirmação.
        self.assertEqual(res["standard"]["text"], "Eixo x do sensor aponta para baixo; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para frente")

    def test_small_correction_needs_no_confirm(self):
        mount = q_axis((0, 1, 0), 90)
        old = ic.q_normalize(ic.q_mul(q_axis((1, 0, 0), 2.0), mount))
        res = ic.solve(Duck(mount, old_mount=old).run(), frame="body", old_mount=old)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertEqual(res["confirm"], [])

    def test_stance_tilt_is_folded_in(self):
        """O corpo está inclinado 4° para a frente no HOME por causa das patas; após compensar, a leitura em pé coincide com o HOME oficial."""
        mount = q_axis((0, 0, 1), 30)
        stance = q_axis((0, 1, 0), 4.0)
        res = ic.solve(Duck(mount, stance=stance, noise_deg=0.0).run(), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        g_still_sensor = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(stance))
        self.assertLess(ic.angle_deg(ic.q_rotate(res["mount"], g_still_sensor), ic.DOWN), 1e-6)
        # A direção permanece correta: a inclinação frontal aponta para +x no novo referencial do corpo.
        g_fwd = ic.mat_vec(ic.mat_t(ic.mat_from_q(mount)), ic.gravity_from_quat(ic.q_mul(q_axis((0, 1, 0), 18), stance)))
        g_new = ic.q_rotate(res["mount"], g_fwd)
        self.assertGreater(g_new[0], 0.25)
        self.assertLess(abs(g_new[1]), 1e-6)

    def test_home_gravity_not_level(self):
        """O HOME oficial já inclina o corpo 3° para a frente; como o robô está nessa mesma postura, a orientação real deve ser recuperada."""
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
        self.assertIn("inclinação para a frente", res["reason"])
        self.assertIn("mínimo", res["reason"])

    def test_tilt_too_big(self):
        res = self.solve(Duck(self.mount).run(tilts={"left": 45}))
        self.assertFalse(res["ok"])
        self.assertIn("acima do máximo", res["steps"]["left"]["msg"])

    def test_still_not_still(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["still"] = duck.samples("still", noise=2.0)
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("oscilaram", res["reason"])

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
        self.assertIn("direita", res["reason"])

    def test_not_held_still(self):
        """Inclina até 18° e volta sem parar: há apenas uma ou duas leituras perto da inclinação máxima."""
        duck = Duck(self.mount)
        data = duck.run()
        swing = [2, 4, 6, 8, 10, 12, 14, 16, 18, 16, 14, 12, 10, 8, 6, 4, 2]
        data["back"] = [{"g": list(duck.reading(duck.pose("back", d)))} for d in swing]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("não ficou parado", res["steps"]["back"]["msg"])

    def test_circling_not_held(self):
        """A inclinação permanece em 15°, mas a direção gira: o ângulo e as leituras estáveis são suficientes, porém a direção oscila demais."""
        duck = Duck(self.mount)
        data = duck.run()
        data["fwd"] = [{"g": list(duck.reading(duck.pose("fwd", 15, skew=s)))} for s in range(-30, 31, 5)]
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("não ficou parado", res["steps"]["fwd"]["msg"])

    def test_same_side_twice(self):
        """A etapa para trás foi feita inclinando o robô para a frente."""
        duck = Duck(self.mount)
        data = duck.run()
        data["back"] = duck.samples("fwd")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("inclinação para a frente e inclinação para trás", res["reason"])

    def test_left_right_swapped(self):
        duck = Duck(self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = self.solve(data)
        self.assertFalse(res["ok"])
        self.assertIn("invertido", res["reason"])
        # Com uma orientação anterior confiável (frame=body), identifica qual par foi invertido.
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertFalse(res["ok"])
        self.assertIn("As inclinações para a esquerda e para a direita foram invertidas", res["reason"])

    def test_tilted_diagonally(self):
        """As inclinações para ambos os lados desviam 30° (15° cada), deixando os pares frente/trás e esquerda/direita fora de perpendicularidade."""
        res = self.solve(Duck(self.mount).run(skews={"left": 30, "right": 30}))
        self.assertFalse(res["ok"])
        self.assertIn("não estão perpendiculares", res["reason"])

    def test_turned_around_needs_confirm(self):
        """Os dois pares foram invertidos, como se o robô tivesse girado: a autoverificação não percebe, mas a comparação com a orientação antiga exige confirmação para uma mudança de 180°."""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertGreater(abs(res["parts"]["yaw_deg"]), 170)
        self.assertTrue(any("tivesse girado" in c for c in res["confirm"]))

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
    """A1: sintetiza leituras seguindo TrunkFrame::push do robotd no firmware do fork (duck-control/src/imu.rs:137-170):
    q_corpo = q_sensor ⊗ mount⁻¹ e gravity = rotate_inverse(q_corpo, [0,0,-1]) = q⁻¹·v·q.
    A multiplicação de quaternions e a rotação são implementadas separadamente, sem reutilizar q_mul, q_rotate ou gravity_from_quat testados."""

    @staticmethod
    def hmul(a, b):                       # Produto de Hamilton implementado termo a termo.
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
            true_mount = self.norm4([rng.gauss(0, 1) for _ in range(4)])     # Orientação real do sensor para o corpo.
            stored = self.norm4([rng.gauss(0, 1) for _ in range(4)])         # Orientação armazenada no robô, com erro arbitrário.
            stance = self.axis_angle((0, 0, 1), rng.uniform(-180, 180))       # Robô em pé e nivelado; yaw arbitrário.

            def reading(q_trunk_world):
                q_sensor_world = self.hmul(q_trunk_world, true_mount)         # Postura do sensor = postura do corpo ⊗ sensor→corpo.
                q_trunk_robotd = self.hmul(q_sensor_world, self.conj(stored))  # robotd: q_sensor ⊗ mount⁻¹.
                g = self.rotate_inverse(q_trunk_robotd, (0.0, 0.0, -1.0))
                # Confere também se gravity_from_quat segue a mesma convenção de rotate_inverse.
                self.assertLess(ic.angle_deg(g, ic.gravity_from_quat(q_trunk_robotd)), 1e-4)   # acos perto de zero tem precisão de ~1e-6°.
                return {"g": list(g)}

            data = {"still": [reading(stance)] * 20}
            for k, ax in {"fwd": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}.items():
                ax_w = self.rotate_inverse(self.conj(stance), ax)              # Eixo do corpo expresso no referencial mundial (q·v·q⁻¹).
                data[k] = [reading(self.hmul(self.axis_angle(ax_w, 18), stance))] * 10
            res = ic.solve(data, frame="body", old_mount=stored, old_verified=False)
            self.assertTrue(res["ok"], res.get("reason"))
            d = abs(sum(a * b for a, b in zip(res["mount"], true_mount)))
            worst = max(worst, math.degrees(2 * math.acos(min(1.0, d))))
        self.assertLess(worst, 0.01)          # Erro de arredondamento acumulado; acos amplifica a diferença perto de 1.

    def test_default_mounts_in_words(self):
        # Montagem padrão do BNO08x: trunk_imu.rs:63, sensor X à esquerda, Y para cima e Z para a frente.
        self.assertEqual(ic.describe_mount([0.5, 0.5, 0.5, 0.5])["text"], "Eixo x do sensor aponta para esquerda; Eixo y do sensor aponta para cima; Eixo z do sensor aponta para frente")
        # Padrão da placa de barramento: imu.rs:76, trunk = [+raw_z, +raw_y, −raw_x].
        r = math.sqrt(0.5)
        self.assertEqual(ic.describe_mount([r, 0, r, 0])["text"], "Eixo x do sensor aponta para baixo; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para frente")
        # Orientação armazenada no robô 2 (linha 6 do fixture): montagem padrão com desvio adicional de 6°.
        d = ic.describe_mount([0.698208849, 0.036261753, 0.714055021, 0.036261753])
        self.assertEqual(d["text"], "Eixo x do sensor aponta para baixo; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para frente")
        self.assertAlmostEqual(d["off_deg"], 6.0, delta=0.1)


class HumanHandling(unittest.TestCase):
    """A2: situações que podem ocorrer ao manusear o robô."""
    mount = q_axis((0, 1, 0), 90)

    def test_overshoot_then_settle(self):
        """Ultrapassa a posição em 4° e volta a parar: considere somente o trecho estável após o retorno."""
        res = ic.solve(Duck(self.mount, noise_deg=0.2).run(overshoot=4.0), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], self.mount), 1.0)
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 18, delta=0.6)

    def test_overshoot_reviewer_case(self):
        """Caso de revisão: inclina até 21°, volta a 17° e mantém por 1,5 s (antes era classificado como apenas uma leitura)."""
        g = lambda d: {"g": list(ic.gravity_from_quat(q_axis((0, 1, 0), d)))}
        still = [g(0)] * 30
        step = lambda ax, d, n=15: [{"g": list(ic.gravity_from_quat(q_axis(ax, d)))}] * n
        data = {"still": still, "fwd": [g(x) for x in (4, 8, 12, 16, 19, 21, 19)] + [g(17)] * 15,
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["steps"]["fwd"]["tilt_deg"], 17, delta=0.01)

    def test_single_spike(self):
        """Um quadro instável (como pode ocorrer no BNO085) durante a pausa, no meio ou no final, não deve causar falha."""
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
        """A mão fica 4,9° fora de nível ao erguer o robô (o limite é 5°): cada etapa usa seu próprio nivelamento como zero, sem confundir isso com uma inclinação diagonal."""
        rng = random.Random(41)
        for i in range(20):
            hand = q_axis((rng.gauss(0, 1), rng.gauss(0, 1), 0), 4.9)
            mount = q_random(rng)
            duck = Duck(mount, noise_deg=0.0, seed=i, hand=hand)
            res = ic.solve(duck.run(tilts={"fwd": 13, "back": 13, "left": 13, "right": 13}, pause=0.8), frame="sensor")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertEqual(res["steps"]["fwd"]["ref"], "Posição nivelada")
            self.assertAlmostEqual(res["steps"]["fwd"]["ref_offset_deg"], 4.9, delta=0.3)   # A janela de nivelamento pode incluir a primeira leitura da inclinação, sem afetar a direção.
            self.assertLess(q_diff_deg(res["mount"], mount), 0.3)
            self.assertLess(res["quality"]["max_skew_deg"], 1.0)      # O desvio de 4,9° deixa apenas um pequeno erro de segunda ordem.

    def test_consistent_twist_fails(self):
        """Inclinações para a frente e para trás torcidas em 15° (probe3): apesar de serem opostas, os pares diferem 15° e a calibração deve falhar."""
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 15, "back": 15}), frame="sensor")
        self.assertFalse(res["ok"])
        self.assertIn("não estão perpendiculares", res["reason"])
        res = ic.solve(Duck(self.mount, noise_deg=0.0).run(skews={"fwd": 5, "back": 5}), frame="sensor")
        self.assertTrue(res["ok"], res.get("reason"))           # Com torção de 5°, ainda é utilizável; direção com precisão aproximada de ±2,5°.
        self.assertAlmostEqual(res["quality"]["yaw_uncert_deg"], 2.5, delta=0.1)

    def test_tilt_max_by_any_held_reading(self):
        """G6: uma leitura de 36° no trecho estável excede o limite (a média anterior de 34,6° deixava o caso passar)."""
        g = lambda ax, d: {"g": list(ic.gravity_from_quat(q_axis(ax, d)))}
        still = [g((0, 1, 0), 0)] * 30
        step = lambda ax, d: [g(ax, d)] * 12
        data = {"still": still, "fwd": step((0, 1, 0), 34.5) + [g((0, 1, 0), 36)],
                "back": step((0, -1, 0), 17), "left": step((-1, 0, 0), 17), "right": step((1, 0, 0), 17)}
        res = ic.solve(data, frame="body", old_mount=(1, 0, 0, 0))
        self.assertFalse(res["ok"])
        self.assertIn("acima do máximo", res["reason"])
        self.assertAlmostEqual(res["steps"]["fwd"]["max_tilt_deg"], 36, delta=0.01)

    def test_bad_numbers_dropped(self):
        """G5: descarta leituras inf/nan sem falhar."""
        self.assertIsNone(ic.sample_gravity({"g": [float("inf"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"g": [float("nan"), 0, -1]}))
        self.assertIsNone(ic.sample_gravity({"acc": [0, float("inf"), 9.8]}))
        self.assertIsNone(ic.sample_gravity({"quat": [float("nan"), 0, 0, 0]}))
        self.assertIsNone(ic.sample_gravity({"g": [1e308, 1e308, 1e308]}))     # O quadrado transborda para inf.
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
        self.assertIn("Há apenas 0 leituras em repouso", res["reason"])

    def test_still_spikes_tolerated(self):
        """Dois quadros instáveis em 3 segundos de repouso (menos de 10% dos 30 quadros) não contam como oscilação; uma oscilação contínua de 2° conta."""
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
        """G4: uma leitura em pé a mais de 5° do HOME (mão apoiada, mesa desnivelada ou patas sem calibração) exige confirmação."""
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 6.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertAlmostEqual(res["parts"]["stand_tilt_deg"], 6.0, delta=0.01)
        self.assertTrue(any("difere 6.0° do HOME oficial" in c for c in res["confirm"]))
        duck = Duck(self.mount, stance=q_axis((0, 1, 0), 4.0), old_mount=self.mount, noise_deg=0.0)
        res = ic.solve(duck.run(), frame="body", old_mount=self.mount)
        self.assertFalse(any("difere" in c for c in res["confirm"]))

    def test_flip_after_coarse(self):
        """Quando a orientação antiga vem de uma calibração aproximada, o aviso de inversão deve mencionar a calibração anterior."""
        duck = Duck(self.mount, old_mount=self.mount)
        data = duck.run()
        data["fwd"], data["back"] = duck.samples("back"), duck.samples("fwd")
        data["left"], data["right"] = duck.samples("right"), duck.samples("left")
        res = ic.solve(data, frame="body", old_mount=self.mount, old_source="coarse")
        self.assertTrue(any("calibração aproximada anterior pode ter sido invertida" in c for c in res["confirm"]))


class Redo(unittest.TestCase):
    """Em caso de falha, redo identifica as etapas a refazer; a página solicita apenas essas etapas."""
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
        self.assertIn("não estão perpendiculares", res["reason"])
        self.assertEqual(res["redo"], ["fwd", "back"])
        self.assertEqual(ic.solve(twisted, frame="body", old_mount=self.mount, old_verified=False)["redo"], list(ic.TILTS))


class Coarse(unittest.TestCase):
    """Calibração aproximada para orientação ainda não confirmada e robô incapaz de ficar em pé: apoie-o e colete repouso e inclinação para a frente (mais a etapa para trás, se possível)."""

    def test_still_and_fwd_only(self):
        rng = random.Random(21)
        for i in range(20):
            mount = q_random(rng)
            data = Duck(mount, noise_deg=0.0, seed=i).run()
            res = ic.solve({"still": data["still"], "fwd": data["fwd"]}, frame="sensor", mode="coarse")
            self.assertTrue(res["ok"], res.get("reason"))
            self.assertLess(q_diff_deg(res["mount"], mount), 0.01)
            self.assertEqual(res["quality"]["grade"], "coarse")
            self.assertTrue(any("Calibração aproximada" in n for n in res["notes"]))

    def test_with_back_and_default_old_mount(self):
        """O padrão do LSM6DSV16X é o quaternion identidade (trunk_imu.rs:56-58), que pode diferir muito da orientação real; não exija confirmação por grande mudança se o padrão não foi verificado."""
        mount = q_axis((0, 1, 0), 90)
        old = (1.0, 0.0, 0.0, 0.0)
        data = Duck(mount, old_mount=old, noise_deg=0.2).run()
        part = {k: data[k] for k in ("still", "fwd", "back")}
        res = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=False)
        self.assertTrue(res["ok"], res.get("reason"))
        self.assertLess(q_diff_deg(res["mount"], mount), 1.0)
        # Não compare com um padrão não verificado para detectar uma grande mudança, mas exija confirmação da montagem física (o robotd não detecta inversão dos lados; plano S1).
        self.assertEqual(len(res["confirm"]), 1)
        self.assertIn("Eixo x do sensor aponta para baixo; Eixo y do sensor aponta para esquerda; Eixo z do sensor aponta para frente", res["confirm"][0])
        res2 = ic.solve(part, frame="body", old_mount=old, mode="coarse", old_verified=True)
        self.assertEqual(len(res2["confirm"]), 2)

    def test_needs_fwd(self):
        data = Duck(q_axis((0, 1, 0), 90)).run()
        res = ic.solve({"still": data["still"]}, frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("inclinação para a frente", res["reason"])

    def test_back_same_side_fails(self):
        duck = Duck(q_axis((0, 1, 0), 90))
        res = ic.solve({"still": duck.samples("still"), "fwd": duck.samples("fwd"), "back": duck.samples("fwd")},
                       frame="sensor", mode="coarse")
        self.assertFalse(res["ok"])
        self.assertIn("inclinação para a frente e inclinação para trás", res["reason"])


if __name__ == "__main__":
    unittest.main()
