"""Localiza a transição de “estável para fora de controle” após o modelo assumir: o instante em que o alvo de uma perna se desvia mais de 15° de HOME pela primeira vez. Imprime quadro a quadro a inclinação, gravidade, velocidade angular e articulação com maior desvio antes e depois.
Uso: python3 failure_onset.py run-xxxx.jsonl (usa o primeiro trecho policy=walk)."""
import json, sys, math
def _load(f):
    out=[]
    for l in open(f, errors='replace'):
        try: out.append(json.loads(l))
        except ValueError: pass
    return out
R=_load(sys.argv[1]); print('Quadros lidos:', len(R), '(linhas inválidas ignoradas)')
i0=next(i for i,r in enumerate(R) if r.get('policy')=='walk'); i1=max(i for i,r in enumerate(R) if r.get('policy')=='walk')
home=R[i0-1]['targets']; LEG=[0,1,2,3,4,10,11,12,13,14]
N=['guinada quadril esq.','rolagem quadril esq.','inclinação quadril esq.','joelho esq.','tornozelo esq.','pescoço','inclinação cabeça','guinada cabeça','rolagem cabeça','boca','guinada quadril dir.','rolagem quadril dir.','inclinação quadril dir.','joelho dir.','tornozelo dir.']
def tilt(g): n=math.sqrt(sum(x*x for x in g)); return math.degrees(math.acos(max(-1,min(1,-g[2]/n))))
dev=lambda r: max(abs(r['targets'][j]-home[j]) for j in LEG)
ib=next((i for i in range(i0,i1) if math.degrees(dev(R[i]))>15), i0)
print('Modelo assumiu em 0 s; duração total', round(R[i1]['t']-R[i0]['t'],1),'s; primeiro desvio do alvo da perna acima de 15° de HOME em', round(R[ib]['t']-R[i0]['t'],2),'s')
print(' Tempo  Desvio  Inclinação  g(x,y,z)                 gyro(x,y,z)            Articulação de maior desvio')
for i in range(max(i0-10,ib-60), min(i1+5,ib+40), 2):
    r=R[i]; d=[abs(r['targets'][j]-home[j]) for j in range(15)]; jm=max(LEG,key=lambda j:d[j])
    g=r['safety']['gravity']; w=r['imu']['gyro']
    print(f"{r['t']-R[i0]['t']:5.2f}s {math.degrees(dev(r)):5.1f}° {tilt(g):5.1f}° ({g[0]:+.2f},{g[1]:+.2f},{g[2]:+.2f})  ({w[0]:+.2f},{w[1]:+.2f},{w[2]:+.2f})  {N[jm]} alvo {math.degrees(r['targets'][jm]-home[jm]):+.0f}° real {math.degrees(r['joints'][jm]-home[jm]):+.0f}°")
