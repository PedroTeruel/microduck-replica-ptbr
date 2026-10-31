"""Análise somente de leitura da qualidade da marcha: identifica as causas de tremores e balanços nas gravações de 50 Hz do duck_rec.
Uso: python gait_quality.py run-xxx.jsonl [relatorio.txt]
Segmentação: policy=walk com velocidade comandada hypot(vx, vy)>0.02 conta como caminhada; policy=walk com comando zero conta como parado.
Se robotd reiniciar durante a gravação (tempo t retrocede ou aparece uma linha rec_error), inicia um novo segmento; não mistura os segmentos.
Métricas:
  1. Oscilação do alvo: RMS da variação do alvo articular por quadro (graus/quadro) e proporção de energia acima de 4 Hz — mostra se a saída do modelo oscila.
  2. Rastreamento: RMS da diferença alvo − valor real e atraso estimado por correlação cruzada (ms) — mostra se os servos acompanham.
  3. Tronco: RMS e frequência dominante do giroscópio; amplitude de balanço para a frente/trás e para os lados segundo a gravidade — mostra quanto e quão rápido o corpo oscila.
  4. Frequência dos passos: frequência dominante da diferença entre os joelhos esquerdo e direito.
  5. Temporização: variação dos intervalos entre quadros e quadros perdidos.
"""
import json, math, sys
import numpy as np

NAMES = ['L_hip_yaw', 'L_hip_roll', 'L_hip_pitch', 'L_knee', 'L_ankle', 'neck_pitch', 'head_pitch',
         'head_yaw', 'head_roll', 'mouth', 'R_hip_yaw', 'R_hip_roll', 'R_hip_pitch', 'R_knee', 'R_ankle']
LEGS = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]
out = open(sys.argv[2], 'w', encoding='utf-8') if len(sys.argv) > 2 else None
def p(*a):
    s = ' '.join(str(x) for x in a); print(s)
    if out: out.write(s + '\n')

R = []
BREAK = {'_break': True}            # Reinício do robotd: o tempo retrocede ou a gravação registra rec_error; o segmento é interrompido aqui.
for l in open(sys.argv[1], encoding='utf-8', errors='replace'):
    try: d = json.loads(l)
    except ValueError: continue
    if 'rec_error' in d or (R and R[-1] is not BREAK and 't' in d and d['t'] < R[-1]['t']):
        if R and R[-1] is not BREAK: R.append(BREAK)
        if 'rec_error' in d: continue
    if 't' in d and d.get('joints') and d.get('targets'): R.append(d)
p(f'Arquivo {sys.argv[1]}: {sum(r is not BREAK for r in R)} quadros; {sum(r is BREAK for r in R)} reinicializações do robotd')

def segments(pred, min_len=50):
    segs, cur = [], []
    for r in R:
        if r is not BREAK and pred(r): cur.append(r)
        else:
            if len(cur) >= min_len: segs.append(cur)
            cur = []
    if len(cur) >= min_len: segs.append(cur)
    return segs
vx = lambda r: (r.get('move') or {}).get('requested', [0, 0, 0])
walking = segments(lambda r: r.get('policy') == 'walk' and math.hypot(vx(r)[0], vx(r)[1]) > 0.02, 50)
standing = segments(lambda r: r.get('policy') == 'walk' and math.hypot(vx(r)[0], vx(r)[1]) <= 0.02, 100)
held = segments(lambda r: r.get('policy') == 'held', 100)

def spectrum(x, fs=50.0):
    x = np.asarray(x) - np.mean(x)
    if len(x) < 32: return None, None
    w = np.hanning(len(x)); F = np.abs(np.fft.rfft(x * w)) ** 2; f = np.fft.rfftfreq(len(x), 1 / fs)
    return f, F

def analyse(name, segs):
    if not segs:
        p(f'\n## {name}: nenhum segmento encontrado'); return
    T = np.concatenate([np.array([r['targets'] for r in s]) for s in segs])
    J = np.concatenate([np.array([r['joints'] for r in s]) for s in segs])
    G = np.concatenate([np.array([r['imu']['gyro'] for r in s]) for s in segs])
    g = np.concatenate([np.array([r['safety']['gravity'] for r in s]) for s in segs])
    t = np.concatenate([np.array([r['t'] for r in s]) for s in segs])
    dur = sum(s[-1]['t'] - s[0]['t'] for s in segs)
    cmd = np.concatenate([np.array([vx(r) for r in s]) for s in segs])
    p(f'\n## {name}: {len(segs)} segmentos, total de {dur:.1f} s; comandos médios: vx {cmd[:, 0].mean():.2f} m/s, vy {cmd[:, 1].mean():.2f}, yaw {cmd[:, 2].mean():.2f}')
    # 5. timing
    dts = np.concatenate([np.diff([r['t'] for r in s]) for s in segs]) * 1000
    p(f'  Temporização: intervalo entre quadros {dts.mean():.1f} ms, desvio padrão {dts.std():.2f} ms, máximo {dts.max():.1f} ms, acima de 30 ms: {int((dts > 30).sum())} ocorrências')
    # 1. target jitter
    p('  Articulação   RMS variação-alvo  Energia-alvo >4 Hz (%)  RMS erro-rastreamento  Atraso (ms)  Energia-real >4 Hz (%)')
    for j in LEGS:
        dT = np.concatenate([np.diff(np.array([r['targets'][j] for r in s])) for s in segs])
        rms_step = math.degrees(np.sqrt(np.mean(dT ** 2)))
        hf = []; hfj = []; lags = []
        for s in segs:
            x = np.array([r['targets'][j] for r in s]); y = np.array([r['joints'][j] for r in s])
            f, F = spectrum(x)
            if f is not None and F[f > 0.3].sum() > 0: hf.append(F[f > 4].sum() / F[f > 0.3].sum())
            f2, F2 = spectrum(y)
            if f2 is not None and F2[f2 > 0.3].sum() > 0: hfj.append(F2[f2 > 4].sum() / F2[f2 > 0.3].sum())
            if len(x) > 60:
                xc = x - x.mean(); yc = y - y.mean()
                cc = [np.dot(xc[:len(xc) - k], yc[k:]) for k in range(0, 15)]
                lags.append(int(np.argmax(cc)) * 20)
        err = math.degrees(np.sqrt(np.mean((T[:, j] - J[:, j]) ** 2)))
        p(f'  {NAMES[j]:<13} {rms_step:8.2f}°        {100*np.mean(hf) if hf else float("nan"):6.1f}        {err:6.2f}°     {np.median(lags) if lags else float("nan"):5.0f}    {100*np.mean(hfj) if hfj else float("nan"):6.1f}')
    # 3. trunk
    pitch = np.degrees(np.arcsin(np.clip(g[:, 0] / np.linalg.norm(g, axis=1), -1, 1)))
    roll = np.degrees(np.arcsin(np.clip(-g[:, 1] / np.linalg.norm(g, axis=1), -1, 1)))
    p(f'  Tronco: inclinação frente/trás média {pitch.mean():+.1f}°, amplitude (5–95%) {np.percentile(pitch,95)-np.percentile(pitch,5):.1f}°; inclinação lateral média {roll.mean():+.1f}°, amplitude {np.percentile(roll,95)-np.percentile(roll,5):.1f}°')
    for k, ax in enumerate('xyz'):
        peaks = []
        for s in segs:
            f, F = spectrum([r['imu']['gyro'][k] for r in s])
            if f is not None:
                m = f > 0.3; peaks.append((f[m][np.argmax(F[m])], F[m & (f > 4)].sum() / F[m].sum()))
        if peaks:
            p(f'  Giroscópio {ax}: RMS {np.degrees(np.sqrt(np.mean(G[:, k] ** 2))):6.1f}°/s, frequência dominante {np.median([a for a, _ in peaks]):.2f} Hz, energia >4 Hz {100*np.mean([b for _, b in peaks]):.0f}%')
    # 4. step frequency from knee difference
    fr = []
    for s in segs:
        d = np.array([r['joints'][3] - r['joints'][13] for r in s])
        f, F = spectrum(d)
        if f is not None:
            m = (f > 0.5) & (f < 5); fr.append(f[m][np.argmax(F[m])])
    if fr: p(f'  Frequência dos passos (frequência dominante da diferença entre os joelhos): {np.median(fr):.2f} Hz; amplitude da diferença {math.degrees(np.ptp(np.concatenate([[r["joints"][3]-r["joints"][13] for r in s] for s in segs]))):.0f}°')

analyse('HOME parado (held)', held)
analyse('Modelo no controle, parado (comando 0)', standing)
analyse('Modelo no controle, caminhando (comando > 0)', walking)
