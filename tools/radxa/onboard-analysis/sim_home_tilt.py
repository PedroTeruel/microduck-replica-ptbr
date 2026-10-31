"""Execute no computador (requer mujoco e o MJCF oficial de microduck_rl). Usa cinemática: toma o keyframe STAND do MJCF (robô em pé, solas apoiadas no chão) como referência para os pés nivelados.
Substitui os ângulos das articulações pelos valores reais, mantém a orientação de ambos os pés igual à referência (solas ainda niveladas), calcula a postura do tronco e lê a gravidade no sistema de coordenadas da IMU.
Uso: python sim_home_tilt.py <microduck_rl>/src/mjlab_microduck/robot/microduck/scene_backlash.xml home-capture.json
Produz o “desvio de instalação da IMU (medido − esperado)” para imu_mount_fix.py."""
import json, sys, math
import numpy as np, mujoco
m = mujoco.MjModel.from_xml_path(sys.argv[1]); d = mujoco.MjData(m); real = json.load(open(sys.argv[2]))
ORDER15 = ['left_hip_yaw','left_hip_roll','left_hip_pitch','left_knee','left_ankle','neck_pitch','head_pitch','head_yaw','head_roll','mouth',
           'right_hip_yaw','right_hip_roll','right_hip_pitch','right_knee','right_ankle']
HOME14 = dict(zip([n for n in ORDER15 if n!='mouth'], [0.0,-0.0873,-0.4579,-0.0049,0.453,0.3491,0.3491,0.0,0.0,0.0,0.0873,0.4579,0.0049,-0.453]))
bodies = [m.body(i).name for i in range(m.nbody)]
feet = [b for b in bodies if 'foot' in b.lower()] or [b for b in bodies if 'ankle' in b.lower()]
print('Bodies dos pés:', feet)
def fk(qpos):
    d.qpos[:] = qpos; mujoco.mj_kinematics(m, d)
    return {b: d.body(b).xmat.reshape(3,3).copy() for b in feet + ['trunk_base' if 'trunk_base' in bodies else bodies[1]]}, d.site('imu').xmat.reshape(3,3).copy()
k = m.key('STAND'); q0 = k.qpos.copy()
print('Quaternion do tronco no keyframe STAND', np.round(q0[3:7],4), ' articulações (°):', {m.joint(i).name: round(math.degrees(q0[m.jnt_qposadr[i]]),1) for i in range(m.njnt) if m.jnt_type[i]!=0 and 'passive' not in m.joint(i).name})
# Referência: orientação dos pés no sistema global durante STAND (presumindo as solas niveladas).
ref, imu_ref = fk(q0)
g = lambda Rimu: Rimu.T @ np.array([0,0,-1.0])
def ang(v): n=np.linalg.norm(v); return math.degrees(math.asin(v[0]/n)), math.degrees(math.asin(-v[1]/n))
print('Inclinação frontal/lateral da IMU no próprio keyframe STAND: %+.2f° / %+.2f°' % ang(g(imu_ref)))
def tilt_for(qmap):
    q = q0.copy(); q[3:7] = [1,0,0,0]
    for i in range(m.njnt):
        if m.jnt_type[i]==0: continue
        n = m.joint(i).name
        q[m.jnt_qposadr[i]] = qmap.get(n, 0.0) if not n.startswith('passive') else 0.0
    Rs, Rimu = fk(q)   # Orientação de cada peça com o tronco nivelado.
    out = []
    for f in feet:
        # Exige R_world_base * R_base_foot = R_ref_foot, portanto R_world_base = R_ref_foot * R_base_foot^T (aqui, com a base nivelada, xmat equivale a R_base_x).
        Rwb = ref[f] @ Rs[f].T
        out.append(ang(g(Rwb @ Rimu)))
    return out
for label, qmap in (('HOME ideal', HOME14), ('Ângulos atuais das articulações reais', {n: real['joints15'][i] for i,n in enumerate(ORDER15)})):
    res = tilt_for(qmap)
    print(f"{label}: nivelando o pé esquerdo — inclinação frontal {res[0][0]:+.2f}°, lateral {res[0][1]:+.2f}° | nivelando o pé direito — inclinação frontal {res[1][0]:+.2f}°, lateral {res[1][1]:+.2f}°")
pr, rr = ang(np.array(real['gravity']))
res = tilt_for({n: real['joints15'][i] for i,n in enumerate(ORDER15)})
ps = sum(r[0] for r in res)/len(res); rs = sum(r[1] for r in res)/len(res)
print(f"Medição real da IMU: inclinação frontal {pr:+.2f}°, lateral {rr:+.2f}°")
print(f"⇒ Desvio de instalação da IMU (medido − esperado): frontal {pr-ps:+.2f}°, lateral {rr-rs:+.2f}°")
