# -*- coding: utf-8 -*-
"""Converte o modelo MuJoCo do microduck_rl (robot_allcollisions.xml + assets/*.stl) para um formato compacto usado na interface web.

  python build_model.py --src <microduck_rl>/src/mjlab_microduck/robot/microduck

Gera model/model.json (árvore cinemática, geometrias, cores e deslocamentos dos vértices no binário) e model/meshes.bin
(vértices xyz quantizados em int16 e índices de triângulos uint16/uint32 por malha). Depende apenas de numpy.

Origem: https://github.com/apirrone/microduck_rl (Apache-2.0). As malhas foram exportadas do CAD oficial da Pollen.
"""
import argparse
import json
import os
import struct
import xml.etree.ElementTree as ET

import numpy as np

JOINT_IDS = {
    "left_hip_yaw": 20, "left_hip_roll": 21, "left_hip_pitch": 22, "left_knee": 23, "left_ankle": 24,
    "neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33, "mouth": 34,
    "right_hip_yaw": 10, "right_hip_roll": 11, "right_hip_pitch": 12, "right_knee": 13, "right_ankle": 14,
}
# Componentes internos que não são visíveis pela carcaça e não entram na interface web.
SKIP_DEFAULT = "pcb__raspberry_pi_zero_2_w,elec_rpi_robot_hat_pcb,seeed_bearing__configuration__22x16x4,seeed_bearing__configuration_default,speaker,m12_lens_holder,banana_pcb_locker,upper_leg_rigidity_plate,motor_support,power_support"


def load_stl(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        tris = []
        for line in data.decode("ascii", "ignore").splitlines():
            line = line.strip()
            if line.startswith("vertex"):
                tris.append([float(x) for x in line.split()[1:4]])
        v = np.array(tris, dtype=np.float32).reshape(-1, 3)
    else:
        n = struct.unpack("<I", data[80:84])[0]
        rec = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        v = rec["v"].reshape(-1, 3).astype(np.float32)
    # Mescla vértices duplicados.
    uniq, inv = np.unique(v, axis=0, return_inverse=True)
    idx = inv.reshape(-1, 3).astype(np.uint32)
    return uniq, idx


def floats(s, default):
    return [float(x) for x in s.split()] if s else list(default)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="Diretório robot/microduck do microduck_rl")
    ap.add_argument("--xml", default="robot_allcollisions.xml")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "model"))
    ap.add_argument("--skip", default=SKIP_DEFAULT)
    ap.add_argument("--mouth-pivot", default="0.003 0 -0.018", help="Posição estimada da dobradiça da boca no referencial da cabeça (metros)")
    ap.add_argument("--official", default="F:/chengshenzhilu/Robot/Microduck/microduck/kinematics/assets/alpha/robot_walk.xml",
                    help="robot_walk.xml oficial, usado para obter massa e centro de massa de cada body; sem ele, não calcula")
    a = ap.parse_args()
    skip = set(x for x in a.skip.split(",") if x)
    root = ET.parse(os.path.join(a.src, a.xml)).getroot()
    meshdir = root.find("compiler").get("meshdir", "assets")
    mesh_files = {}
    for m in root.iter("mesh"):
        name = m.get("name") or os.path.splitext(os.path.basename(m.get("file")))[0]
        mesh_files[name] = (os.path.join(a.src, meshdir, m.get("file")), floats(m.get("scale"), (1, 1, 1)))
    materials = {m.get("name"): floats(m.get("rgba"), (0.8, 0.8, 0.8, 1)) for m in root.iter("material")}

    bodies, used = [], {}

    def walk(el, parent):
        idx = len(bodies)
        b = {"name": el.get("name"), "parent": parent, "pos": floats(el.get("pos"), (0, 0, 0)),
             "quat": floats(el.get("quat"), (1, 0, 0, 0)), "joint": None, "geoms": []}
        j = el.find("joint")
        if j is not None and j.get("type", "hinge") == "hinge":
            b["joint"] = {"name": j.get("name"), "axis": floats(j.get("axis"), (0, 0, 1)),
                          "range": floats(j.get("range"), (-3.14, 3.14)), "id": JOINT_IDS.get(j.get("name"))}
        for g in el.findall("geom"):
            if g.get("type") != "mesh" or g.get("class") == "collision":
                continue
            m = g.get("mesh")
            if m in skip or m not in mesh_files:
                continue
            used[m] = True
            b["geoms"].append({"mesh": m, "pos": floats(g.get("pos"), (0, 0, 0)), "quat": floats(g.get("quat"), (1, 0, 0, 0)),
                               "rgba": materials.get(g.get("material"), [0.8, 0.8, 0.8, 1])})
        bodies.append(b)
        for c in el.findall("body"):
            walk(c, idx)

    for top in root.find("worldbody").findall("body"):
        walk(top, -1)

    # Boca: essa junta não existe no MJCF; a mandíbula está unida à cabeça. Separa as geometrias
    # jaw / jaw_soft e as prende a uma dobradiça sintética. O eixo é y no referencial da cabeça
    # (esquerda/direita); o pivô fica na origem da geometria do servo da boca (xl330), e ângulo positivo abre a boca.
    # A posição é estimada e serve apenas para visualização.
    notes = []
    pivot = [float(x) for x in a.mouth_pivot.split()]
    for b in bodies:
        jaw_geoms = [g for g in b["geoms"] if g["mesh"] in ("jaw", "jaw_soft")]
        if not jaw_geoms:
            continue
        b["geoms"] = [g for g in b["geoms"] if g not in jaw_geoms]
        for g in jaw_geoms:
            g["pos"] = [g["pos"][k] - pivot[k] for k in range(3)]
        bodies.append({"name": "jaw_hinge", "parent": bodies.index(b), "pos": pivot, "quat": [1, 0, 0, 0],
                       "joint": {"name": "mouth", "axis": [0, 1, 0], "range": [-0.0873, 0.5236], "id": JOINT_IDS["mouth"], "synthetic": True},
                       "geoms": jaw_geoms})
        notes.append("A dobradiça da boca 34 é sintética (não existe no modelo original); posição estimada apenas para visualização")
        break

    # Massa e centro de massa: obtidos dos dados inertiais do robot_walk.xml oficial e associados
    # pelo nome da junta (os nomes dos bodies diferem entre os dois modelos).
    if a.official and os.path.exists(a.official):
        off = ET.parse(a.official).getroot()
        by_joint = {}
        def walk_off(el):
            inert = el.find("inertial"); j = el.find("joint")
            m = (float(inert.get("mass")), floats(inert.get("pos"), (0, 0, 0))) if inert is not None else (0.0, [0, 0, 0])
            if j is not None: by_joint[j.get("name")] = m
            elif el.find("freejoint") is not None: by_joint["__trunk__"] = m
            for c in el.findall("body"): walk_off(c)
        for top in off.find("worldbody").findall("body"): walk_off(top)
        for b in bodies:
            key = b["joint"]["name"] if b["joint"] else "__trunk__"
            mass, com = by_joint.get(key, (0.0, [0, 0, 0]))
            if b["joint"] and b["joint"].get("synthetic"): mass, com = 0.0, [0, 0, 0]
            b["mass"], b["com"] = mass, com
        total = sum(b["mass"] for b in bodies)
        notes.append(f"Massa total de {total*1000:.0f} g obtida do robot_walk.xml oficial; centro de massa calculado com base nele")
        print(f"Massa: {total*1000:.0f} g; {sum(1 for b in bodies if b['mass'])} bodies com massa definida")
    # Área de apoio dos pés: caixa delimitadora da malha sole no referencial do tornozelo;
    # a página projeta essa área no chão e desenha um retângulo.
    for b in bodies:
        for g in b["geoms"]:
            if g["mesh"] in ("sole_left", "sole_right"):
                b["sole"] = {"mesh": g["mesh"], "pos": g["pos"], "quat": g["quat"]}

    os.makedirs(a.out, exist_ok=True)
    meshes, blob = {}, bytearray()
    for name in sorted(used):
        path, scale = mesh_files[name]
        v, idx = load_stl(path)
        v = v * np.array(scale, dtype=np.float32)
        lo, hi = v.min(0), v.max(0)
        span = np.where(hi - lo > 0, hi - lo, 1).astype(np.float32)
        q = np.round((v - lo) / span * 65535 - 32768).clip(-32768, 32767).astype("<i2")
        ib = 2 if len(v) < 65536 else 4
        ind = idx.astype("<u2" if ib == 2 else "<u4")
        while len(blob) % 4:
            blob += b"\0"
        off = len(blob)
        blob += q.tobytes()
        while len(blob) % 4:
            blob += b"\0"
        ioff = len(blob)
        blob += ind.tobytes()
        meshes[name] = {"voff": off, "nverts": int(len(v)), "ioff": ioff, "ntris": int(len(idx)), "index_bytes": ib,
                        "bbox_min": lo.tolist(), "bbox_max": hi.tolist()}
        print(f"{name:45s} {len(v):7d} v {len(idx):7d} tri")
    model = {"source": "apirrone/microduck_rl " + a.xml, "license": "Apache-2.0", "up": "z", "notes": notes,
             "bodies": bodies, "meshes": meshes, "joint_ids": JOINT_IDS}
    with open(os.path.join(a.out, "model.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(a.out, "meshes.bin"), "wb") as f:
        f.write(blob)
    joints = [b["joint"]["name"] for b in bodies if b["joint"]]
    print(f"\n{len(bodies)} corpos, {len(joints)} juntas, {len(meshes)} malhas; meshes.bin com {len(blob) / 1e6:.2f} MB")
    print("Juntas:", joints)
    missing = [n for n in JOINT_IDS if n not in joints]
    if missing:
        print("Juntas ausentes no modelo (não se moverão na interface web):", missing)


if __name__ == "__main__":
    main()
