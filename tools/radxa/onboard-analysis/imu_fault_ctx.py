"""Cruza os horários de desconexão da IMU com a atividade do robô: estado, velocidade
angular máxima das juntas, velocidade angular do corpo e tensão dos servos."""
import json, glob, subprocess, datetime, math, bisect
out = subprocess.run(['journalctl','-u','robotd','-b','--no-pager','-o','short-unix'], capture_output=True, text=True).stdout
faults=[]; idents=[]; events=[]
for l in out.splitlines():
    try: ts=float(l.split()[0])
    except ValueError: continue
    if 'trunk IMU reader fault' in l: faults.append(ts)
    elif 'BNO08x identified' in l: idents.append((ts, l.split('reset_cause=')[-1].strip()))
    elif any(k in l for k in ('robot.init: torque on','robot.relax: torque off','fall verdict changed','policy outcome')): events.append((ts, l.split('robotd: ')[-1][:60] if 'robotd: ' in l else l[-60:]))
print('Nesta inicialização: %d desconexões da IMU, %d reconexões; valores de reset_cause: %s' % (len(faults), len(idents), sorted(set(c for _,c in idents))))
# Indexa as gravações (50 Hz) pelo horário de relógio de parede.
R=[]
for f in sorted(glob.glob('/home/duck/r17/rec/run-*.jsonl'))[-4:]:
    for l in open(f, errors='replace'):
        try: r=json.loads(l); R.append((r['wall'], r))
        except (ValueError, KeyError): pass
R.sort(key=lambda x:x[0]); W=[w for w,_ in R]
H=[]
for f in sorted(glob.glob('/home/duck/r17/rec/health-*.csv'))[-4:]:
    for l in open(f).read().splitlines()[1:]:
        p=l.split(',')
        try: H.append((float(p[0]), float(p[1])))
        except (ValueError, IndexError): pass
H.sort(); HW=[w for w,_ in H]
def ctx(ts):
    i=bisect.bisect_left(W, ts-1.0); j=bisect.bisect_left(W, ts+0.05)
    seg=[r for _,r in R[i:j]]
    if not seg: return '(sem gravação)'
    pol=seg[-1].get('policy'); jv=max(max(abs(v) for v in r['velocities']) for r in seg); gy=max(math.sqrt(sum(x*x for x in r['imu']['gyro'])) for r in seg)
    k=bisect.bisect_left(HW, ts-2); hv=[v for w,v in H[k:k+8] if abs(w-ts)<2.5]
    return 'estado=%-7s junta mais rápida no segundo anterior %4.1f rad/s; velocidade angular máxima do corpo %4.2f; tensão %s' % (pol, jv, gy, ('%.2f a %.2f V' % (min(hv), max(hv))) if hv else '—')
print('\nHorário da desconexão  Contexto')
last=0
for ts in faults:
    if ts-last < 0.3: continue
    last=ts
    print(datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S.%f')[:-3], ' ', ctx(ts))
print('\nEventos do robô no mesmo período:')
for ts,e in events:
    if faults and faults[0]-60 < ts < faults[-1]+5: print(' ', datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S'), e)
