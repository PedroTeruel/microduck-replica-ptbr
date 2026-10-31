# -*- coding: utf-8 -*-
"""Ângulos em que as articulações das pernas giram até as peças se tocarem e verificação de contato entre peças nas posturas oficiais.

Ferramenta para encontrar referências mecânicas na calibração do zero: identifica qual articulação encosta em qual peça e em que ângulo quando o Microduck está recolhido.
O MuJoCo calcula somente a cinemática direta (posição de cada peça); o contato é verificado com precisão pelo fcl, usando a interseção das malhas triangulares originais.
O sistema de colisão do próprio MuJoCo trata as malhas como cascos convexos, mais “grossos” que as peças reais, o que subestima o ângulo de contato.

  python fold_contact.py --mjcf <microduck_rl>/src/mjlab_microduck/robot/microduck/robot_walk.xml
  python fold_contact.py --mjcf ... --json out.json

Dependências: mujoco, python-fcl e numpy (pip install mujoco python-fcl numpy).
Pares de geometrias que já se interpenetram na posição zero (pernas estendidas) são tratados como peças montadas, por exemplo servos nos suportes e rolamentos nos alojamentos, e excluídos da varredura.
O modelo oficial usa a geometria original XL330; oito peças de encaixe foram alteradas na versão Feetech, portanto recalcule os valores com o modelo dessa versão.
"""
import argparse
import json
import math
import sys
import time

import fcl
import mujoco
import numpy as np

# Keyframe de microduck_rl scene.xml (d424a0c), 14 articulações na ordem MJCF.
JOINTS = ["left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
          "neck_pitch", "head_pitch", "head_yaw", "head_roll",
          "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle"]
KEYFRAMES = {
    "STAND": [0, -0.08726646259971647, -0.457924, -0.004940, 0.452984,
              0.3490658503988659, 0.3490658503988659, 0, 0,
              0, 0.08726646259971647, 0.457924, 0.004940, -0.452984],
    "SIT": [0, 0, -0.5236, 1.0472, 0, 0.5, 1.6, 0, 0, 0, 0, 0.5236, -1.0472, 0],
    "FOLD": [0, 0, 1.57, 1.57, 0, 1, 1, 0, 0, 0, 0, -1.57, -1.57, 0],
}


class Model:
    def __init__(self, path):
        self.m = mujoco.MjModel.from_xml_path(path)
        self.d = mujoco.MjData(self.m)
        m = self.m
        # Usa somente as malhas visuais (group 2), que correspondem à forma física; group 3 contém colisores simplificados para treinamento.
        self.geoms = [g for g in range(m.ngeom) if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH
                      and m.geom_group[g] == 2 and m.geom_dataid[g] >= 0]
        self.bvh = {}
        for g in self.geoms:
            mid = m.geom_dataid[g]
            v = m.mesh_vert[m.mesh_vertadr[mid]:m.mesh_vertadr[mid] + m.mesh_vertnum[mid]].astype(np.float64)
            f = m.mesh_face[m.mesh_faceadr[mid]:m.mesh_faceadr[mid] + m.mesh_facenum[mid]].astype(np.int32)
            b = fcl.BVHModel()
            b.beginModel(len(v), len(f))
            b.addSubModel(v, f)
            b.endModel()
            self.bvh[g] = b
        self.q0 = m.qpos0.copy()
        self.baseline = {p for p in self.pairs(self.q0, self.geoms, self.geoms)}

    def name(self, obj, i):
        return mujoco.mj_id2name(self.m, obj, i)

    def label(self, g):
        m = self.m
        return f"{self.name(mujoco.mjtObj.mjOBJ_BODY, m.geom_bodyid[g])}/{self.name(mujoco.mjtObj.mjOBJ_MESH, m.geom_dataid[g])}"

    def qadr(self, joint):
        return self.m.jnt_qposadr[mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_JOINT, joint)]

    def with_joints(self, values, base=None):
        q = (self.q0 if base is None else base).copy()
        for j, v in values.items():
            q[self.qadr(j)] = v
        return q

    def objects(self, q):
        self.d.qpos[:] = q
        mujoco.mj_kinematics(self.m, self.d)
        return {g: fcl.CollisionObject(self.bvh[g], fcl.Transform(self.d.geom_xmat[g].reshape(3, 3).copy(),
                                                                  self.d.geom_xpos[g].copy()))
                for g in self.geoms}

    def pairs(self, q, set_a, set_b, skip=()):
        """Pares de geometrias de peças distintas (bodies diferentes) que se interpenetram entre set_a e set_b na postura q."""
        objs = self.objects(q)
        out = set()
        for a in set_a:
            for b in set_b:
                p = (min(a, b), max(a, b))
                if a == b or p in out or p in skip or self.m.geom_bodyid[a] == self.m.geom_bodyid[b]:
                    continue
                if fcl.collide(objs[a], objs[b], fcl.CollisionRequest(), fcl.CollisionResult()) > 0:
                    out.add(p)
        return out

    def subtree_geoms(self, joint):
        m = self.m
        root = m.jnt_bodyid[mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_JOINT, joint)]
        bodies = {root}
        grew = True
        while grew:
            grew = False
            for b in range(1, m.nbody):
                if m.body_parentid[b] in bodies and b not in bodies:
                    bodies.add(b)
                    grew = True
        return {g for g in self.geoms if m.geom_bodyid[g] in bodies}

    def sweep(self, joint, sign, base, max_deg=180.0, step=0.25, tol=0.05):
        """A partir de base, gira joint na direção sign e retorna (ângulo do primeiro contato em graus, peça atingida); retorna None se não houver contato até max_deg."""
        distal = self.subtree_geoms(joint)
        proximal = set(self.geoms) - distal
        adr = self.qadr(joint)
        start = base[adr]

        def hits(deg):
            q = base.copy()
            q[adr] = start + sign * math.radians(deg)
            return self.pairs(q, distal, proximal, self.baseline)

        prev, a = 0.0, 0.0
        while a <= max_deg:
            if hits(a):
                lo, hi = prev, a
                while hi - lo > tol:
                    mid = (lo + hi) / 2
                    if hits(mid):
                        hi = mid
                    else:
                        lo = mid
                who = sorted({(self.label(x), self.label(y)) for x, y in hits(hi)})
                return math.degrees(start) + sign * hi, who
            prev, a = a, a + step
        return None, []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mjcf", required=True, help="robot_walk.xml ou um modelo com a mesma estrutura")
    ap.add_argument("--json", help="Salva os resultados também em JSON")
    a = ap.parse_args()
    t0 = time.time()
    mdl = Model(a.mjcf)
    out = {"mjcf": a.mjcf, "baseline_pairs": sorted((mdl.label(x), mdl.label(y)) for x, y in mdl.baseline),
           "sweeps": {}, "keyframes": {}}
    print(f"Pares de peças montadas que já se interpenetram na posição zero: {len(mdl.baseline)} (servo no suporte, rolamento no alojamento); excluídos da varredura")

    def record(key, res):
        ang, who = res
        out["sweeps"][key] = {"deg": None if ang is None else round(ang, 2), "contact": who[:3]}
        print(f"  {key}: " + ("sem contato após girar 180°" if ang is None else f"{ang:+.2f}°  contato com {who[:2]}"))

    for side, s in (("left", +1), ("right", -1)):   # s = direção de dobra da postura oficial FOLD.
        print(f"== Perna {side} (direção de dobra {s:+d})")
        knee = mdl.sweep(f"{side}_knee", s, mdl.q0)
        record(f"{side}.dobra do joelho (quadril e tornozelo a 0°)", knee)
        base = mdl.with_joints({f"{side}_hip_pitch": s * 1.57})
        record(f"{side}.dobra do joelho (quadril a {s * 90:+d}°, tornozelo a 0°, como no quadril da FOLD oficial)", mdl.sweep(f"{side}_knee", s, base))
        if knee[0] is not None:
            qk = mdl.with_joints({f"{side}_knee": math.radians(knee[0] - s * 0.1)})
            hip = mdl.sweep(f"{side}_hip_pitch", s, qk)
            record(f"{side}.dobra da inclinação do quadril (joelho totalmente dobrado)", hip)
            if hip[0] is not None:
                qh = qk.copy()
                qh[mdl.qadr(f"{side}_hip_pitch")] = math.radians(hip[0] - s * 0.1)
                record(f"{side}.tornozelo + (joelho e quadril totalmente dobrados)", mdl.sweep(f"{side}_ankle", +1, qh))
                record(f"{side}.tornozelo − (joelho e quadril totalmente dobrados)", mdl.sweep(f"{side}_ankle", -1, qh))

    # Pescoço: a inclinação do pescoço e da cabeça na FOLD oficial é 1 rad (57°). Verifica os contatos girando o pescoço a partir de 0°, com as pernas dobradas, na direção da FOLD (+).
    print("== Pescoço (pernas dobradas conforme a FOLD oficial)")
    fold = mdl.with_joints(dict(zip(JOINTS, KEYFRAMES["FOLD"])))
    for head, rad in (("0°", 0.0), ("57°, cabeça na FOLD oficial", 1.0)):
        q = fold.copy()
        q[mdl.qadr("neck_pitch")] = 0.0
        q[mdl.qadr("head_pitch")] = rad
        record(f"Inclinação do pescoço na direção FOLD (inclinação da cabeça {head})", mdl.sweep("neck_pitch", +1, q))

    print("== Posturas oficiais: há contato entre as peças?")
    for key, vals in KEYFRAMES.items():
        q = mdl.with_joints(dict(zip(JOINTS, vals)))
        bad = mdl.pairs(q, mdl.geoms, mdl.geoms, mdl.baseline)
        who = sorted({(mdl.label(x), mdl.label(y)) for x, y in bad})
        out["keyframes"][key] = who
        print(f"  {key}: " + (f"{len(who)} pares em interseção {who[:3]}" if who else "sem interseção"))
    print(f"Tempo decorrido: {time.time() - t0:.0f} s")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
