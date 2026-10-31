#!/usr/bin/env python3
"""Exporta um STL montado a partir do MJCF do Microduck.

Os 47 STL do repositório upstream usam coordenadas locais das peças; importá-los diretamente no CAD sobreporia tudo na origem.
Este script serve apenas para analisar o modelo de simulação upstream; não gera peças para impressão do CAD físico atual.
Por padrão, grava em analysis-output/cad-upstream/ e não no diretório de download de modelos do repositório principal.
O script lê a árvore cinemática do MJCF, aplica a transformação mundial correta a cada malha
 e exporta os grupos de corpos rígidos como uma montagem que pode ser aberta no CAD ou em um fatiador.

Uso:
    python scripts/export_assembly_stl.py <caminho microduck_rl upstream> [diretório de saída]
"""
import sys, os, struct, json
import numpy as np
import mujoco

MJCF = "src/mjlab_microduck/robot/microduck/robot_allcollisions.xml"

CN = {
    'trunk_base':'01_tronco','yaw2roll':'02_quadril_esquerdo_yaw-roll','hip_l':'03_quadril_esquerdo_roll',
    'upper_leg_left':'04_coxa_esquerda','leg':'05_perna_esquerda','ankle_left':'06_tornozelo_pe_esquerdo',
    'neck':'07_base_do_pescoco','neck_pitch':'08_inclinacao_do_pescoco','yaw_roll_motion':'09_cabeca_yaw-roll',
    'jaw_soft':'10_conjunto_da_cabeca','bearing_roll':'11_quadril_direito_yaw-roll','hip_l_2':'12_quadril_direito_roll',
    'upper_leg_right':'13_coxa_direita','leg_2':'14_perna_direita','ankle_right':'15_tornozelo_pe_direito',
}


def write_stl(path, tris):
    """Grava um STL binário. tris: matriz de vértices (N,3,3), em mm."""
    with open(path, 'wb') as f:
        f.write(b'\0' * 80)
        f.write(struct.pack('<I', len(tris)))
        for t in tris:
            n = np.cross(t[1] - t[0], t[2] - t[0])
            L = np.linalg.norm(n)
            n = n / L if L > 1e-12 else np.zeros(3)
            f.write(struct.pack('<3f', *n))
            for v in t:
                f.write(struct.pack('<3f', *v))
            f.write(b'\0\0')


def geom_tris(m, d, g):
    """Obtém os triângulos de um geom, transforma para coordenadas mundiais e converte para mm."""
    mid = m.geom_dataid[g]
    if mid < 0:
        return None
    va, vn = m.mesh_vertadr[mid], m.mesh_vertnum[mid]
    fa, fn = m.mesh_faceadr[mid], m.mesh_facenum[mid]
    V = m.mesh_vert[va:va + vn].reshape(-1, 3)
    F = m.mesh_face[fa:fa + fn].reshape(-1, 3)
    R = d.geom_xmat[g].reshape(3, 3)
    W = (V @ R.T) + d.geom_xpos[g]
    return W[F] * 1000.0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    root = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "analysis-output/cad-upstream"
    os.makedirs(out, exist_ok=True)

    path = os.path.join(root, MJCF)
    if not os.path.exists(path):
        sys.exit(f"MJCF não encontrado: {path}\nExecute scripts/fetch_upstream.sh primeiro.")

    m = mujoco.MjModel.from_xml_path(path)
    d = mujoco.MjData(m)
    d.qpos[:] = 0
    d.qpos[3] = 1.0          # Quaternion unitário da junta livre: postura de referência em zero
    mujoco.mj_forward(m, d)

    names = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, i) for i in range(m.nbody)]
    allt, manifest = [], {}

    for b in range(1, m.nbody):
        tris, srcs = [], []
        for g in range(m.ngeom):
            if m.geom_bodyid[g] != b or m.geom_group[g] != 2:   # grupo 2 = malha visual
                continue
            t = geom_tris(m, d, g)
            if t is None:
                continue
            tris.append(t)
            srcs.append(mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_MESH, m.geom_dataid[g]))
        if not tris:
            continue
        T = np.concatenate(tris, 0)
        allt.append(T)
        name = CN.get(names[b], names[b])
        write_stl(os.path.join(out, f"{name}.stl"), T)
        manifest[name] = {'body': names[b], 'stl_origem': srcs, 'faces_triangulares': len(T)}
        print(f"  {name:22s} {len(T):7d} tris  <- {len(srcs)} malhas de origem")

    A = np.concatenate(allt, 0)
    write_stl(os.path.join(out, "00_Microduck_montagem_completa.stl"), A)
    bb = A.reshape(-1, 3)
    print(f"\nMontagem completa: {len(A)} faces triangulares")
    print(f"Dimensões (mm): {bb[:,0].ptp():.1f} x {bb[:,1].ptp():.1f} x {bb[:,2].ptp():.1f}")

    with open(os.path.join(out, "tabela_de_pecas.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
