"""每 0.5 s 记一次舵机供电电压、最热舵机、CPU 温度和频率（robotctl health --json），CSV。只读。"""
import json, subprocess, sys, time
secs=float(sys.argv[1]); out=sys.argv[2]; t0=time.time()
with open(out,'w') as f:
    f.write('wall,volts,motor_max_c,motor_hottest,motor_mean_c,cpu_c,cpu_mhz\n')
    while time.time()-t0<secs:
        a=time.time()
        try:
            h=json.loads(subprocess.run(['robotctl','health','--json'],capture_output=True,text=True,timeout=3).stdout)['robot']
            m=h.get('motors',{}); thr=h.get('cpu_throttle',{})
            f.write(f"{a:.2f},{h['battery']['volts']:.3f},{m.get('max_c')},{m.get('hottest')},{m.get('mean_c',0):.1f},{h.get('cpu_temp_c')},{thr.get('khz',0)//1000}\n"); f.flush()
        except Exception as e:
            f.write(f"{a:.2f},,,,,,err:{type(e).__name__}\n"); f.flush()
        time.sleep(max(0, 0.5-(time.time()-a)))
