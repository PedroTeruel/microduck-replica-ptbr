"""Altura sustentada pela perna de apoio: distância vertical entre a origem do tronco e o ponto mais baixo do pé apoiado, com o tronco nivelado pela IMU. Compara valores reais e alvo, separando os lados.
Quanto mais baixa a sustentação (maior a queda em relação ao alvo), mais cedo o pé oposto em balanço toca o chão e mais difícil fica levantá-lo."""
import os
import sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import foot_clear as fc
import mujoco
m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m)
adr = [m.jnt_qposadr[m.joint(n).id] for n in fc.J14]
gid = {s: m.geom(f'{s}_foot_collision').id for s in fc.SIDES}; base = m.body('trunk_base').id
def zmin(q, L):
    d.qpos[:] = m.qpos0
    for a, v in zip(adr, q): d.qpos[a] = v
    mujoco.mj_kinematics(m, d)
    Rb = d.xmat[base].reshape(3, 3); pb = d.xpos[base]; out = {}
    for s in fc.SIDES:
        g = gid[s]; c = d.geom_xpos[g]; R = d.geom_xmat[g].reshape(3, 3); sz = m.geom_size[g]
        pts = np.array([c + R @ (np.array([a, b, e]) * sz) for a in (-1, 1) for b in (-1, 1) for e in (-1, 1)])
        out[s] = float((((pts - pb) @ Rb) @ L.T)[:, 2].min()) * 1000
    return out
for spec in sys.argv[2:]:
    name, src = spec.split('=', 1)
    held, walk = fc.load(src)
    if held:
        h = [zmin(q, fc.level(g)) for q, _, g in held[-150:]]
        print(f'\n## {name}  HOME: altura sustentada pela perna esquerda {-np.mean([x["left"] for x in h]):.1f} mm; perna direita {-np.mean([x["right"] for x in h]):.1f} mm')
    else:
        print(f'\n## {name}')
    A = []; T = []
    for q, t, g in walk:
        L = fc.level(g); A.append(zmin(q, L)); T.append(zmin(t, L))
    st = np.array(['left' if a['left'] <= a['right'] else 'right' for a in A])
    for s in fc.SIDES:
        i = np.flatnonzero(st == s)
        a = -np.array([A[k][s] for k in i]); t = -np.array([T[k][s] for k in i])
        print(f'  Perna {fc.CN[s]} em apoio durante {len(i)/len(A)*100:3.0f}% da caminhada; altura real mediana {np.median(a):5.1f} mm (5º percentil {np.percentile(a,5):5.1f}); alvo {np.median(t):5.1f} mm; queda em relação ao alvo {np.median(t-a):4.1f} mm')
