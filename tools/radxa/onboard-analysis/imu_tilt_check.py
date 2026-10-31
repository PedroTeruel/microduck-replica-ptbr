"""Localiza trechos de inclinação manual nos últimos N segundos da gravação: imprime a cada 0,5 s os ângulos frontal/lateral do tronco e seleciona automaticamente os trechos mais distantes da postura em pé.
Convenção (coordenadas do tronco: x para a frente, y para a esquerda, z para cima; gravidade g no tronco): inclinar para a frente torna g_x positivo; inclinar para a direita torna g_y negativo."""
import json, sys, math, glob
secs=float(sys.argv[1]) if len(sys.argv)>1 else 120
f=sorted(glob.glob('/home/duck/r17/rec/run-*.jsonl'))[-1]
R=[]
for l in open(f, errors='replace'):
    try: R.append(json.loads(l))
    except ValueError: pass
R=[r for r in R if r['t']>=R[-1]['t']-secs]
def ang(g):
    n=math.sqrt(sum(x*x for x in g)) or 1
    return math.degrees(math.asin(max(-1,min(1,g[0]/n)))), math.degrees(math.asin(max(-1,min(1,-g[1]/n))))  # Inclinação frontal positiva; para a direita positiva.
base=[sum(r['safety']['gravity'][k] for r in R[:100])/100 for k in range(3)]
b=ang(base); print(f"Referência inicial: inclinação frontal {b[0]:+.1f}°  inclinação à direita {b[1]:+.1f}°")
print(" Tempo   Frente(+)/trás(-)   Direita(+)/esquerda(-)   gyro(x,y,z)")
for i in range(0,len(R),25):
    r=R[i]; a=ang(r['safety']['gravity']); w=r['imu']['gyro']
    mark='  ←' if abs(a[0]-b[0])>8 or abs(a[1]-b[1])>8 else ''
    print(f"{r['t']-R[0]['t']:6.1f}s   {a[0]-b[0]:+6.1f}°          {a[1]-b[1]:+6.1f}°        ({w[0]:+.2f},{w[1]:+.2f},{w[2]:+.2f}){mark}")
