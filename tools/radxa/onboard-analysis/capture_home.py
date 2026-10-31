"""Execute na placa: extrai da gravação mais recente os ângulos articulares e a gravidade da IMU (médias) enquanto o Microduck permanece parado em HOME; salva em JSON para sim_home_tilt.py.
Uso: python3 capture_home.py [arquivo_de_saida] (padrão home-capture.json; usa os últimos 100 quadros policy=held).
Pré-requisitos: duck_rec.py está gravando; o Microduck está em HOME sobre uma superfície plana, sem ninguém tocá-lo e imóvel por pelo menos 3 s."""
import json, glob, math, sys
out = sys.argv[1] if len(sys.argv) > 1 else 'home-capture.json'
R = []
for l in open(sorted(glob.glob('/home/duck/r17/rec/run-*.jsonl'))[-1], errors='replace'):
    try: R.append(json.loads(l))
    except ValueError: pass
H = [r for r in R if r.get('policy') == 'held'][-100:]
if len(H) < 50: sys.exit('Há poucos quadros em HOME (são necessários ≥50); toque em Start para o robô ficar em pé e aguarde alguns segundos sem movimento')
gy = max(math.sqrt(sum(x * x for x in r['imu']['gyro'])) for r in H)
if gy > 0.2: print('Aviso: o tronco se moveu durante este trecho (velocidade angular máxima %.2f rad/s); o resultado não é confiável' % gy)
d = {'joints15': [sum(r['joints'][j] for r in H) / len(H) for j in range(15)],
     'gravity': [sum(r['safety']['gravity'][k] for r in H) / len(H) for k in range(3)],
     'frames': len(H), 'span_s': H[-1]['t'] - H[0]['t'], 'gyro_max': gy}
json.dump(d, open(out, 'w'))
print('Salvo', out, ': %d quadros, %.1f s' % (len(H), d['span_s']))
