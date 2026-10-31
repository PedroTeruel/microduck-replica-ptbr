"""Para cada articulação, compara a derivada do ângulo (velocidade real) com a velocidade informada pelo robotd. Razão ≈+1 é normal, ≈−1 indica sinal invertido e grande desvio de 1 indica escala incorreta."""
import json, sys, math
R=[]
for _l in open(sys.argv[1], errors='replace'):
    try: R.append(json.loads(_l))
    except ValueError: pass
NAMES=['guinada do quadril esquerdo','rolagem do quadril esquerdo','inclinação do quadril esquerdo','joelho esquerdo','tornozelo esquerdo','inclinação do pescoço','inclinação da cabeça','guinada da cabeça','rolagem da cabeça','boca','guinada do quadril direito','rolagem do quadril direito','inclinação do quadril direito','joelho direito','tornozelo direito']
print(f"{'Articulação':32s} Amostras  Correlação  Razão (informada/real)")
for j,n in enumerate(NAMES):
    xs=[];ys=[]
    for i in range(1,len(R)-1):
        dt=R[i+1]['t']-R[i-1]['t']
        if not 0.03<dt<0.06: continue
        d=(R[i+1]['joints'][j]-R[i-1]['joints'][j])/dt; v=R[i]['velocities'][j]
        if abs(d)>0.3: xs.append(d); ys.append(v)
    if len(xs)<20: print(f"{n:32s} {len(xs):4d}  (movimento insuficiente)"); continue
    mx=sum(xs)/len(xs); my=sum(ys)/len(ys)
    cov=sum((a-mx)*(b-my) for a,b in zip(xs,ys)); sx=math.sqrt(sum((a-mx)**2 for a in xs)); sy=math.sqrt(sum((b-my)**2 for b in ys))
    ratio=sum(a*b for a,b in zip(xs,ys))/sum(a*a for a in xs)
    print(f"{n:6s} {len(xs):4d}  {cov/(sx*sy):+.3f}    {ratio:+.2f}")
