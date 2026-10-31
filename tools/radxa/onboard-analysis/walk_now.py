"""Analisa o trecho mais recente de walk (modelo no controle): imprime periodicamente inclinação, velocidade angular, desvio dos alvos das pernas em relação a HOME, erro de rastreamento e comandos do joystick; ao final, informa a inclinação média e o número de quadros de queda.
Uso: python3 walk_now.py [run-xxxx.jsonl]"""
import json, glob, math, sys
f = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob('/home/duck/r17/rec/run-*.jsonl'))[-1]
R = []
for l in open(f, errors='replace'):
    try: R.append(json.loads(l))
    except ValueError: pass
W = [i for i, r in enumerate(R) if r.get('policy') == 'walk']
if not W: print('O modo walk ainda não foi iniciado'); sys.exit()
# Usa o trecho contínuo mais recente em walk.
i1 = W[-1]; i0 = i1
while i0 - 1 in set(W): i0 -= 1
seg = R[i0:i1 + 1]; HOME = R[i0 - 1]['targets']; LEG = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]
def tilt(g):
    n = math.sqrt(sum(x * x for x in g)); return math.degrees(math.asin(g[0] / n)), math.degrees(math.asin(-g[1] / n))
t0 = seg[0]['t']
print('Duração deste trecho walk', round(seg[-1]['t'] - t0, 1), 's; estado posterior', R[-1]['policy'])
print(' Tempo  Frente  Direita  |gyro|  Desvio do alvo da perna em relação a HOME  Erro de rastreamento  Joystick')
step = max(1, len(seg) // 40)
for k in range(0, len(seg), step):
    r = seg[k]; p, rr = tilt(r['safety']['gravity']); w = math.sqrt(sum(x * x for x in r['imu']['gyro']))
    dev = max(abs(r['targets'][j] - HOME[j]) for j in LEG); err = max(abs(r['targets'][j] - r['joints'][j]) for j in LEG)
    cmd = [round(x, 2) for x in r['move']['requested']]
    print('%5.1fs %+6.1f %+6.1f  %5.2f   %6.1f°       %6.1f°    %s' % (r['t'] - t0, p, rr, w, math.degrees(dev), math.degrees(err), cmd))
ps = [tilt(r['safety']['gravity'])[0] for r in seg]
print('Inclinação frontal média %+.1f°, faixa %+.1f a %+.1f°; quadros de queda: %d' % (sum(ps) / len(ps), min(ps), max(ps), sum(1 for r in seg if r['safety'].get('fallen'))))
