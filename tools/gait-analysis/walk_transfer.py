"""Estima, somente para leitura, a resposta em frequência entre o alvo articular e o ângulo real a partir de gravações de marcha.
O alvo enviado pelo modelo a cada quadro serve como sinal de excitação. Usa o espectro cruzado de Welch para calcular H(f)=S_ty/S_tt:
  módulo |H|: amplitude real / amplitude do alvo (>1 indica que o servo ultrapassou o alvo; <1 indica que não acompanhou)
  atraso em ms: fase convertida em tempo
  coerência γ²: confiabilidade da estimativa nessa frequência (considere somente valores >0,6)
Usa segmentos contínuos com policy=walk (parado em posição sustentada ou caminhando), com pelo menos 3 s cada.
Uso: python walk_transfer.py NOME=video.jsonl [NOME=video.jsonl ...]
"""
import json
import math
import sys

import numpy as np
from scipy.signal import csd, welch

LEG = {'hip_roll': (1, 11), 'hip_pitch': (2, 12), 'knee': (3, 13), 'ankle': (4, 14)}
FREQS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)
FS = 50.0
NPER = 64            # Janela de 1,28 s; resolução de frequência de 0,78 Hz.


def segments(path, min_len=150):
    segs, cur = [], []
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if 't' not in r or not r.get('targets') or not r.get('joints'):
            continue
        if r.get('policy') == 'walk' and not (cur and r['t'] < cur[-1]['t']):   # Se t retroceder, robotd reiniciou; inicia outro segmento.
            cur.append(r)
        elif r.get('policy') == 'walk':
            if len(cur) >= min_len: segs.append(cur)
            cur = [r]
        else:
            if len(cur) >= min_len: segs.append(cur)
            cur = []
    if len(cur) >= min_len: segs.append(cur)
    return segs


def transfer(segs, idx):
    sxx = sxy = syy = None; n = 0
    for s in segs:
        x = np.array([r['targets'][idx] for r in s]); y = np.array([r['joints'][idx] for r in s])
        x = x - x.mean(); y = y - y.mean()
        f, pxx = welch(x, FS, nperseg=NPER); _, pyy = welch(y, FS, nperseg=NPER); _, pxy = csd(x, y, FS, nperseg=NPER)
        w = len(s)
        sxx = pxx * w if sxx is None else sxx + pxx * w
        syy = pyy * w if syy is None else syy + pyy * w
        sxy = pxy * w if sxy is None else sxy + pxy * w
        n += w
    H = sxy / sxx
    coh = np.abs(sxy) ** 2 / (sxx * syy)
    return f, H, coh, sxx / n


def main():
    runs = []
    for arg in sys.argv[1:]:
        name, path = arg.split('=', 1)
        segs = segments(path)
        dur = sum(len(s) for s in segs) / FS
        print(f'{name}: {len(segs)} segmentos policy=walk, total de {dur:.0f} s')
        if not segs:
            print(f'  {name}: nenhum segmento contínuo policy=walk com pelo menos {150 / FS:.0f} s; ignorado')
            continue
        runs.append((name, segs, dur))
    if not runs:
        sys.exit('Não há gravações para analisar')
    for joint, (li, ri) in LEG.items():
        print(f'\n## {joint} (média dos lados esquerdo e direito)  Cada célula: módulo / atraso (ms) / coerência')
        print('   Hz   ' + ''.join(f'{n[:16]:>22}' for n, _, _ in runs))
        res = []
        for name, segs, _ in runs:
            out = []
            for idx in (li, ri):
                f, H, coh, pxx = transfer(segs, idx)
                out.append((f, H, coh))
            res.append(out)
        for fq in FREQS:
            cells = []
            for out in res:
                f = out[0][0]; k = int(np.argmin(np.abs(f - fq)))
                g = np.mean([abs(o[1][k]) for o in out])
                ph = np.mean([math.degrees(np.angle(o[1][k])) for o in out])
                c = np.mean([o[2][k] for o in out])
                lag = -ph / (360 * f[k]) * 1000
                cells.append(f'{g:4.2f} / {lag:4.0f} / {c:.2f}')
            print(f'   {fq:3.0f}  ' + ''.join(f'{c:>22}' for c in cells))


if __name__ == '__main__':
    main()
