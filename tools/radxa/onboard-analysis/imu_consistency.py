"""Verifica a consistência da IMU na gravação: a taxa de variação da gravidade g no sistema do tronco deve satisfazer dg/dt = -ω × g (ω é a velocidade angular no tronco).
Compara possíveis erros (inversão de ω, inversão dos eixos ou troca de eixos); a opção que melhor corresponde às medições indica a configuração efetiva da IMU."""
import json, sys, math, itertools
R=[]
for _l in open(sys.argv[1], errors='replace'):
    try: R.append(json.loads(_l))
    except ValueError: pass
R=[r for r in R if r.get('policy') in ('walk','homing') or True]
g=[r['safety']['gravity'] for r in R]; w=[r['imu']['gyro'] for r in R]; t=[r['t'] for r in R]
def cross(a,b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
pairs=[]
for i in range(1,len(R)-1):
    dt=t[i+1]-t[i-1]
    if not 0.03<dt<0.06: continue
    dg=[(g[i+1][k]-g[i-1][k])/dt for k in range(3)]
    if math.sqrt(sum(x*x for x in dg))<0.3: continue          # Considera somente momentos de rotação evidente.
    pairs.append((dg,w[i],g[i]))
print('Amostras válidas', len(pairs), '(|dg/dt|>0,3/s)')
def score(T):
    num=0; den1=0; den2=0
    for dg,wi,gi in pairs:
        pred=[-x for x in cross(T(wi),gi)]
        num+=sum(a*b for a,b in zip(dg,pred)); den1+=sum(a*a for a in dg); den2+=sum(b*b for b in pred)
    return num/math.sqrt(den1*den2) if den1 and den2 else float('nan')
cands={'ω original':lambda v:v,'ω invertido':lambda v:[-v[0],-v[1],-v[2]]}
for perm in itertools.permutations(range(3)):
    for signs in itertools.product((1,-1),repeat=3):
        name=f"ω'=({','.join(('-' if s<0 else '+')+'xyz'[p] for p,s in zip(perm,signs))})"
        cands[name]=(lambda perm,signs:lambda v:[signs[k]*v[perm[k]] for k in range(3)])(perm,signs)
res=sorted(((score(T),n) for n,T in cands.items()),reverse=True)
print('Correlação de ω original (1=coincidência total, -1=oposição total):', round(score(cands['ω original']),3))
print('Cinco opções com maior correspondência:'); [print('  ',round(s,3),n) for s,n in res[:5]]
# Gravidade na postura em pé.
held=[r['safety']['gravity'] for r in R if r.get('policy')=='held'][-200:]
if held: print('Gravidade média em pé', [round(sum(x[k] for x in held)/len(held),3) for k in range(3)])
