"""Execute no computador: calcula o novo quaternion de montagem a partir do "desvio
de montagem da IMU" calculado por sim_home_tilt.py.
Convenção do robotd (duck-control/src/imu.rs): M = [w,x,y,z] representa a rotação do
sensor para o corpo; a gravidade no corpo é M·g_sensor·M⁻¹.
A compensação multiplica uma pequena rotação à esquerda: M' = C ⊗ M. C gira as
leituras no referencial do corpo em torno de +Y pelo desvio de inclinação para frente
e em torno de +X pelo desvio de inclinação para a direita.
Uso: python imu_mount_fix.py <desvio_frontal°> <desvio_direita°> [w x y z do M atual]
Exemplo (primeira unidade, 2026-10-12): python imu_mount_fix.py 8.54 1.78 0.5 0.5 0.5 0.5
  → [0.454164155, 0.544101455, 0.527409117, 0.468538313]"""
import math, sys
def qmul(a, b):
    aw, ax, ay, az = a; bw, bx, by, bz = b
    return (aw*bw - ax*bx - ay*by - az*bz, aw*bx + ax*bw + ay*bz - az*by, aw*by - ax*bz + ay*bw + az*bx, aw*bz + ax*by - ay*bx + az*bw)
def rot(q, v):
    w, x, y, z = q; r = qmul(qmul(q, (0.0,) + tuple(v)), (w, -x, -y, -z)); return r[1:]
def ang(g):
    n = math.sqrt(sum(c * c for c in g)); return math.degrees(math.asin(g[0] / n)), math.degrees(math.asin(-g[1] / n))
dp, dr = float(sys.argv[1]), float(sys.argv[2])
M = tuple(float(x) for x in sys.argv[3:7]) if len(sys.argv) >= 7 else (0.5, 0.5, 0.5, 0.5)
C = qmul((math.cos(math.radians(dp) / 2), 0, math.sin(math.radians(dp) / 2), 0), (math.cos(math.radians(dr) / 2), math.sin(math.radians(dr) / 2), 0, 0))
N = qmul(C, M); n = math.sqrt(sum(c * c for c in N)); N = tuple(c / n for c in N)
print('Novo quaternion de montagem [w,x,y,z] = [%.9f, %.9f, %.9f, %.9f]' % N)
# Autoverificação: uma gravidade lida com inclinações dp/dr na calibração antiga deve
# ser lida como 0/0 depois de aplicar a nova calibração.
gx = math.sin(math.radians(dp)); gyv = -math.sin(math.radians(dr)); g_old = (gx, gyv, -math.sqrt(1 - gx * gx - gyv * gyv))
g_sensor = rot((M[0], -M[1], -M[2], -M[3]), g_old)
print('Autoverificação: calibração antiga lê inclinação frontal %+.2f° e à direita %+.2f° → nova calibração lê %+.2f° e %+.2f° (deve ficar perto de zero)' % ((dp, dr) + ang(rot(N, g_sensor))))
print('Grave em ["imu_mounts"."bno08x"] → "quat" no arquivo /etc/robot/feetech-ft5/hd1910-calibration.toml; faça backup antes. Reinicie o robotd com os torques desativados para aplicar.')
