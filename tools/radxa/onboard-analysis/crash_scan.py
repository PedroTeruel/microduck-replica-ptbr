"""Para cada gravação, mostra a linha do tempo de estados, comandos do joystick e o estado de segurança dos últimos quadros; use o CSV health do mesmo trecho para consultar tensão e temperatura. Somente leitura.
Usa wall (relógio de parede) da gravação: duck_rec reconecta após a reinicialização do robotd, cujo próprio t volta a zero.
Uso: python3 crash_scan.py run-xxx.jsonl [health-xxx.csv]"""
import csv, json, math, sys

R = []
for l in open(sys.argv[1], errors="replace"):
    try:
        d = json.loads(l)
    except ValueError:
        continue
    if 'rec_error' in d:
        print('  rec_error', d)
        continue
    if 'wall' in d and 't' in d:
        R.append(d)
if not R:
    sys.exit('empty')
w0 = R[0]['wall']
print(f"{sys.argv[1]}: {len(R)} quadros, {R[-1]['wall'] - w0:.1f} s, wall {w0:.0f}->{R[-1]['wall']:.0f}")


def req(r):
    return (r.get('move') or {}).get('requested', [0, 0, 0])


prev = None
for r in R:
    s = r.get('safety', {})
    key = (r.get('policy'), s.get('limp'), s.get('fallen'))
    if key != prev:
        print(f"  {r['wall'] - w0:7.2f}s policy={r.get('policy')} limp={s.get('limp')} fallen={s.get('fallen')} joystick={req(r)}")
        prev = key
moving = [r for r in R if any(abs(v) > 0.01 for v in req(r))]
if moving:
    print(f"  Quadros com comando de joystick: {len(moving)}, primeiro em {moving[0]['wall'] - w0:.2f}s, último em {moving[-1]['wall'] - w0:.2f}s, exemplo {req(moving[-1])}")
print('Últimos 3 quadros:')
for r in R[-3:]:
    s = dict(r.get('safety', {}))
    g = s.pop('gravity', None) or [0, 0, -1]
    n = math.sqrt(sum(x * x for x in g)) or 1
    tilt = math.degrees(math.acos(max(-1, min(1, -g[2] / n))))     # Em pé, a gravidade aponta para baixo (g_z<0), inclinação de 0°.
    print(f"  {r['wall'] - w0:7.2f}s policy={r.get('policy')} loop={r.get('loop')} inclinação={tilt:.1f}° joystick={req(r)} safety={s}")
if len(sys.argv) > 2:
    rows = list(csv.reader(open(sys.argv[2])))
    print('health:', rows[0])
    print(f"  {len(rows) - 1} linhas; últimas 6:")
    for row in rows[-6:]:
        print('  ', row)
    try:
        vi = rows[0].index(next(h for h in rows[0] if 'volt' in h.lower()))
        vs = [float(x[vi]) for x in rows[1:] if x[vi] not in ('', 'None')]
        print(f"  Tensão mínima {min(vs):.2f}, máxima {max(vs):.2f}")
    except Exception as e:
        print('  Falha ao interpretar a coluna de tensão', e)
