"""Verifica se a rolagem e a inclinação do tronco durante a marcha estão “acopladas”: calcula por faixa de frequência a inclinação da regressão entre x do giroscópio (velocidade angular de rolagem) e y (velocidade angular de inclinação).
Se a IMU estiver girada em torno do eixo vertical por um ângulo θ, a inclinação em todas as faixas será aproximadamente tanθ, com o mesmo sinal; a oscilação real para a frente e para trás aparece somente perto da frequência dos passos."""
import json, math, sys
import numpy as np
from scipy.signal import butter, sosfiltfilt
for spec in sys.argv[1:]:
    name, path = spec.split('=', 1)
    parts = path.split('@'); path = parts[0]; t0 = float(parts[1]) if len(parts) > 1 and parts[1] else -1e18; t1 = float(parts[2]) if len(parts) > 2 and parts[2] else 1e18
    W = []; G = []
    for l in open(path, encoding='utf-8', errors='replace'):
        try: r = json.loads(l)
        except ValueError: continue
        if r.get('policy') != 'walk' or not t0 <= r.get('wall', 0) < t1: continue
        req = (r.get('move') or {}).get('requested', [0, 0, 0])
        if math.hypot(req[0], req[1]) < 0.02: continue
        W.append(r['imu']['gyro']); G.append((r.get('safety') or {}).get('gravity') or [0, 0, -1])
    W = np.degrees(np.array(W)); G = np.array(G)
    roll = np.degrees(np.arcsin(-G[:, 1] / np.linalg.norm(G, axis=1))); pit = np.degrees(np.arcsin(G[:, 0] / np.linalg.norm(G, axis=1)))
    out = [f'{name:10s} {len(W)/50:5.1f}s']
    for lo, hi in ((0.5, 2.0), (2.0, 4.5), (6.0, 20.0)):
        sos = butter(2, [lo, hi], 'bandpass', fs=50, output='sos')
        x = sosfiltfilt(sos, W[:, 0]); y = sosfiltfilt(sos, W[:, 1])
        k = np.dot(x, y) / np.dot(x, x); r = np.corrcoef(x, y)[0, 1]
        out.append(f'{lo:g}-{hi:g} Hz: inclinação {k:+.2f} (correlação {r:+.2f})')
    x = roll - roll.mean(); y = pit - pit.mean()
    out.append(f'Inclinação: regressão da inclinação do tronco sobre a rolagem {np.dot(x, y)/np.dot(x, x):+.2f} (correlação {np.corrcoef(x, y)[0,1]:+.2f})')
    print('  '.join(out))
