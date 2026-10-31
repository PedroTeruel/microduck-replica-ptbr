"""Análise somente de leitura da diferença de rolagem (lateral) entre os pés na posição HOME, da articulação responsável e do lado mais baixo.
Normal do pé = direção do menor lado da caixa de colisão; rolagem = inclinação da normal no plano y-z do tronco (+ indica inclinação para a esquerda do robô, deixando baixo o lado esquerdo do pé).
Diferença de rolagem = rolagem do pé esquerdo − rolagem do direito, **em relação à posição HOME simulada**. No modelo, as solas já diferem 5,97° em HOME (lado externo de cada pé cerca de 3° mais baixo, devido à geometria; veja a verificação inicial). Esse valor de referência é subtraído dos resultados. Leituras e alvo HOME usam o mesmo zero, portanto o desvio de zero não aparece aqui.
Contribuição da articulação = variação da diferença quando somente essa articulação passa de HOME ao valor medido (as demais permanecem em HOME).
Bordas interna/externa = altura média, com o tronco nivelado, das bordas longas da parte inferior da caixa de colisão do pé: a mais próxima da linha central do corpo (interna) e a mais distante (externa). A caixa é uma simplificação; confira o robô real.
Uso: python home_roll.py MJCF.xml NOME=video.jsonl ... (usa os últimos 150 quadros de cada trecho com policy=held e torque ativo; apresenta estatísticas por trecho)
     python home_roll.py MJCF.xml NOME=home-capture.json ... (quadro único, campo joints15)
"""
import json
import math
import sys

import mujoco
import numpy as np

J14 = ['left_hip_yaw', 'left_hip_roll', 'left_hip_pitch', 'left_knee', 'left_ankle', 'neck_pitch', 'head_pitch',
       'head_yaw', 'head_roll', 'right_hip_yaw', 'right_hip_roll', 'right_hip_pitch', 'right_knee', 'right_ankle']
HOME = np.array([0.0, -0.0873, -0.4579, -0.0049, 0.453, 0.3491, 0.3491, 0.0, 0.0, 0.0, 0.0873, 0.4579, 0.0049, -0.453])
LEG = {'left': [0, 1, 2, 3, 4], 'right': [9, 10, 11, 12, 13]}
NAME = ['guinada do quadril', 'rolagem do quadril', 'inclinação do quadril', 'joelho', 'tornozelo']
CN = {'left': 'esquerdo', 'right': 'direito'}

m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m)
adr = [m.jnt_qposadr[m.joint(n).id] for n in J14]
gid = {s: m.geom(f'{s}_foot_collision').id for s in ('left', 'right')}
base = m.body('trunk_base').id


def fk(q):
    d.qpos[:] = m.qpos0
    for a, v in zip(adr, q): d.qpos[a] = v
    mujoco.mj_kinematics(m, d)
    return d.xmat[base].reshape(3, 3), d.xpos[base]


def rolls(q):
    Rb, _ = fk(q); out = {}
    for s, g in gid.items():
        R = d.geom_xmat[g].reshape(3, 3); n = Rb.T @ R[:, int(np.argmin(m.geom_size[g]))]
        if n[2] < 0: n = -n
        out[s] = math.degrees(math.atan2(n[1], n[2]))       # + = normal inclinada para a esquerda do robô = lado esquerdo do pé mais baixo
    return out


def diff(q):
    r = rolls(q); return r['left'] - r['right']


def edges(q):
    """Altura média das bordas interna e externa da sola de cada pé nas coordenadas do tronco (mm).
    A sola é o lado voltado para baixo no eixo mais fino da caixa de colisão; interna/externa são as bordas longas mais próxima/distante da linha central do corpo."""
    Rb, pb = fk(q); out = {}
    for s, g in gid.items():
        R = Rb.T @ d.geom_xmat[g].reshape(3, 3); c = Rb.T @ (d.geom_xpos[g] - pb); h = m.geom_size[g]
        n = int(np.argmin(h)); down = -1.0 if R[2, n] > 0 else 1.0
        rest = [k for k in range(3) if k != n]
        lat = max(rest, key=lambda k: abs(R[1, k])); lon = [k for k in rest if k != lat][0]
        bottom = c + down * h[n] * R[:, n]
        side = {}
        for sg in (-1.0, 1.0):
            e = bottom + sg * h[lat] * R[:, lat]
            side[sg] = (abs(e[1]), np.mean([(e + sx * h[lon] * R[:, lon])[2] for sx in (-1.0, 1.0)]))
        inner, outer = sorted(side.values())                  # O menor |y| corresponde ao lado interno.
        out[s] = (inner[1] * 1000, outer[1] * 1000)
    return out


def edge_text(q):
    parts = []
    for s, (zi, zo) in edges(q).items():
        parts.append(f"lado {'externo' if zo < zi else 'interno'} do pé {CN[s]} mais baixo: {abs(zo - zi):.1f} mm")
    return '，'.join(parts)


def report(name, Q):
    Q = np.asarray(Q); qm = np.median(Q, axis=0); base_d = diff(HOME)
    total = diff(qm) - base_d
    parts = []
    for s in ('left', 'right'):
        for k, i in enumerate(LEG[s]):
            q1 = HOME.copy(); q1[i] = qm[i]
            c = diff(q1) - base_d
            if abs(c) >= 0.05: parts.append(f"{CN[s]}{NAME[k]} {c:+.2f}°")
    devs = '  '.join(f"{CN[s]}{NAME[k]} {math.degrees(qm[i] - HOME[i]):+.1f}°"
                     for s in ('left', 'right') for k, i in enumerate(LEG[s]) if k in (0, 1))
    print(f"{name:28s} {len(Q):6d} quadros  diferença de rolagem entre os pés {total:+.2f}° = {'  '.join(parts)}\n"
          f"{'':36s}guinada/rolagem do quadril medido-HOME: {devs}\n{'':36s}com o tronco nivelado: {edge_text(qm)}")


def held_segments(path):
    segs, cur = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        try: r = json.loads(line)
        except ValueError: continue
        if not r.get('joints'):
            continue
        j = r['joints']; q = j[:9] + j[10:15]
        if r.get('policy') == 'held' and not (r.get('safety') or {}).get('limp'):
            cur.append(q)
        elif cur:
            if len(cur) >= 100: segs.append(cur)
            cur = []
    if len(cur) >= 100: segs.append(cur)
    return segs


print(f"Verificação da HOME simulada: diferença de rolagem entre os pés {diff(HOME):+.3f}°, {edge_text(HOME)} (esse valor de referência é subtraído das diferenças abaixo)")
for spec in sys.argv[2:]:
    name, path = spec.split('=', 1)
    if path.endswith('.json'):
        j = json.load(open(path, encoding='utf-8'))['joints15']; report(name, [j[:9] + j[10:15]])
        continue
    for k, seg in enumerate(held_segments(path)):
        report(f'{name}#{k + 1}', seg[-150:])
