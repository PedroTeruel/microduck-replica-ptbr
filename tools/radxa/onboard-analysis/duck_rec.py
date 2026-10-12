"""后台录 robotd 50 Hz 状态（关节、目标、速度指令、IMU、安全、策略状态），只读订阅，不发任何控制。
用法：python3 duck_rec.py 秒数 输出文件"""
import json, socket, sys, time
secs=float(sys.argv[1]); out=sys.argv[2]
keep=('t','policy','move','joints','targets','velocities','imu','safety','loop')
s=socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect('/run/robotd.sock')
s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{}}\n')
r=s.makefile('rb'); t0=time.monotonic(); n=0
with open(out,'w') as f:
    while time.monotonic()-t0<secs:
        line=r.readline()
        if not line: break
        try: m=json.loads(line); p=m.get('params',m.get('result'))
        except ValueError: continue
        if not isinstance(p,dict) or 'joints' not in p: continue
        p={k:p[k] for k in keep if k in p}; p['wall']=time.time()
        f.write(json.dumps(p,separators=(',',':'))+'\n'); n+=1
        if n%500==0: f.flush()
