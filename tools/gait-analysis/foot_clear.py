"""Análise somente de leitura da folga do pé em balanço: usa a gravidade da IMU para nivelar o tronco e calcula “ponto mais baixo do pé em balanço − ponto mais baixo do pé de apoio”.
A cada quadro: calcula a cinemática direta dos 8 vértices das caixas de colisão dos dois pés (coordenadas do tronco), transforma-os para o plano horizontal com safety.gravity e considera apoio o pé mais baixo; o outro está em balanço.
Também substitui as articulações por targets (alvos do modelo para os servos) para identificar de onde vem a perda de folga:
  real/real: folga real; alvo/real: folga se a perna em balanço acompanhar perfeitamente o alvo; real/alvo: folga se a perna de apoio não ceder; alvo/alvo: resultado pretendido pelo modelo.
Uso: python foot_clear.py MJCF.xml NOME=video.jsonl[@wall_inicial[@wall_final]] ...
"""
import json
import math
import sys

import mujoco
import numpy as np

J14 = ['left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle', 'neck_pitch', 'head_pitch',
       'head_yaw', 'head_roll', 'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle']
LEGIDX = {'left': [0, 1, 2, 3, 4], 'right': [9, 10, 11, 12, 13]}
LEGNAME = ['guinada do quadril', 'rolagem do quadril', 'inclinação do quadril', 'joelho', 'tornozelo']
SIDES = ('left', 'right')
CN = {'left': 'pé esquerdo', 'right': 'pé direito'}


def load(spec):
    parts = spec.split('@'); path = parts[0]
    t0 = float(parts[1]) if len(parts) > 1 and parts[1] else -1e18
    t1 = float(parts[2]) if len(parts) > 2 and parts[2] else 1e18
    held, walk = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not r.get('joints') or not r.get('targets'):
            continue
        if not t0 <= r.get('wall', 0) < t1:
            continue
        g = (r.get('safety') or {}).get('gravity') or (r.get('imu') or {}).get('gravity')
        if not g:
            continue
        j = r['joints']; tg = r['targets']
        row = (np.array(j[:9] + j[10:15]), np.array(tg[:9] + tg[10:15]), np.array(g, float))
        req = (r.get('move') or {}).get('requested', [0, 0, 0])
        if r.get('policy') == 'held' and not (r.get('safety') or {}).get('limp'):
            held.append(row)
        elif r.get('policy') == 'walk' and math.hypot(req[0], req[1]) > 0.02:
            walk.append(row)
    return held, walk


def level(g):
    """Rotação das coordenadas do tronco para o plano horizontal (aplica somente rolagem e inclinação, alinhando a gravidade com -z)."""
    v = g / np.linalg.norm(g); t = np.array([0.0, 0.0, -1.0])
    ax = np.cross(v, t); s = np.linalg.norm(ax); c = float(np.dot(v, t))
    if s < 1e-9:
        return np.eye(3)
    k = ax / s; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + s * K + (1 - c) * K @ K


def main():
    m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m)
    adr = [m.jnt_qposadr[m.joint(n).id] for n in J14]
    gid = {s: m.geom(f'{s}_foot_collision').id for s in SIDES}
    base = m.body('trunk_base').id

    def corners(q):
        d.qpos[:] = m.qpos0
        for a, v in zip(adr, q): d.qpos[a] = v
        mujoco.mj_kinematics(m, d)
        Rb = d.xmat[base].reshape(3, 3); pb = d.xpos[base]
        out = {}
        for s in SIDES:
            g = gid[s]; c = d.geom_xpos[g]; R = d.geom_xmat[g].reshape(3, 3); sz = m.geom_size[g]
            pts = np.array([c + R @ (np.array([a, b, e]) * sz) for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)])
            out[s] = (pts - pb) @ Rb                                     # Coordenadas do tronco: x para a frente, y para a esquerda, z para cima.
        return out

    def label(p, side):
        """Indica onde está o vértice mais baixo do pé: dianteira/traseira e interna/externa."""
        fb = 'ponta do pé' if p[0] > 0 else 'calcanhar'
        inner = (p[1] < 0) if side == 'left' else (p[1] > 0)
        return fb + ('interna' if inner else 'externa')

    for spec in sys.argv[2:]:
        name, src = spec.split('=', 1)
        held, walk = load(src)
        print(f'\n## {name}: {len(held)} quadros em HOME, {len(walk) / 50:.1f} s caminhando')
        if len(held) >= 25:
            gap = []
            for q, _, g in held[-150:]:
                C = corners(q); L = level(g)
                zl = (C['left'] @ L.T)[:, 2]; zr = (C['right'] @ L.T)[:, 2]
                gap.append((zl.min() - zr.min()) * 1000)
            print(f'  Verificação: ponto mais baixo do pé esquerdo − direito em HOME = {np.mean(gap):+.1f} mm (deve ficar perto de 0, com os dois pés apoiados)')
        if len(walk) < 100:
            continue
        A = [corners(q) for q, _, _ in walk]; T = [corners(t) for _, t, _ in walk]
        Ls = [level(g) for _, _, g in walk]
        def zmin(C, L, s): return float((C[s] @ L.T)[:, 2].min())
        za = {s: np.array([zmin(C, L, s) for C, L in zip(A, Ls)]) for s in SIDES}
        zt = {s: np.array([zmin(C, L, s) for C, L in zip(T, Ls)]) for s in SIDES}
        stance = np.where(za['left'] <= za['right'], 'left', 'right')
        roll = np.degrees([math.asin(-g[1] / np.linalg.norm(g)) for _, _, g in walk])
        for s in SIDES:
            o = 'right' if s == 'left' else 'left'
            sw = stance == o                                              # Quadros em que este pé está em balanço.
            idx = np.flatnonzero(sw)
            if len(idx) < 10:
                continue
            segs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
            segs = [g for g in segs if len(g) >= 3]
            def peak(zs, zo):
                v = (zs - zo) * 1000
                return np.array([v[g].max() for g in segs]), v
            aa, va = peak(za[s], za[o]); ta, _ = peak(zt[s], za[o]); at, _ = peak(za[s], zt[o]); tt, _ = peak(zt[s], zt[o])
            drag = np.mean(va[idx] < 2.0) * 100
            low = [label((A[g[np.argmax(va[g])]][s] @ Ls[g[np.argmax(va[g])]].T)[np.argmin((A[g[np.argmax(va[g])]][s] @ Ls[g[np.argmax(va[g])]].T)[:, 2])], s) for g in segs]
            top = max(set(low), key=low.count)
            print(f'  {CN[s]}: {len(segs):3d} passos; folga máxima por passo, mediana {np.median(aa):4.1f} mm (quadros em balanço com <2 mm: {drag:3.0f}%)  '
                  f'ponto mais baixo no pico: {top} ({low.count(top)}/{len(low)})')
            print(f'        Decomposição: intenção do modelo {np.median(tt):4.1f} | perna em balanço acompanhando o alvo {np.median(ta):4.1f} | perna de apoio sem ceder {np.median(at):4.1f} | real {np.median(aa):4.1f} mm'
                  f'   rolagem média do tronco durante o balanço {roll[sw].mean():+.1f}°')
        # Rastreamento: amplitude real/alvo e desvio médio de cada articulação em cada perna, separados entre apoio e balanço.
        Q = np.array([q for q, _, _ in walk]); Tg = np.array([t for _, t, _ in walk])
        for s in SIDES:
            o = 'right' if s == 'left' else 'left'
            row = []
            for k, i in enumerate(LEGIDX[s]):
                amp_q = np.percentile(Q[:, i], 95) - np.percentile(Q[:, i], 5)
                amp_t = np.percentile(Tg[:, i], 95) - np.percentile(Tg[:, i], 5)
                bias_st = np.degrees(np.mean((Q[:, i] - Tg[:, i])[stance == s]))
                row.append(f'{LEGNAME[k]}: amplitude-alvo {math.degrees(amp_t):4.1f}°; real/alvo {amp_q / amp_t if amp_t > 1e-6 else 0:4.2f}; desvio no apoio {bias_st:+4.1f}°')
            print(f'Acompanhamento da perna {CN[s]}: ' + '; '.join(row[1:]))


if __name__ == '__main__':
    main()
