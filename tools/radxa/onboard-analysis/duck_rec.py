"""Grava em segundo plano o estado do robotd a 50 Hz (juntas, alvos, comandos de
velocidade, IMU, segurança e estado da política). Apenas assina os dados; não envia
comandos de controle. Sincroniza em disco a cada segundo: um corte de energia pode
perder no máximo o último segundo. Se o robotd desconectar, registra uma linha
rec_error e tenta reconectar. Acrescenta dados sem sobrescrever o arquivo existente.
Uso: python3 duck_rec.py duração_em_segundos arquivo_de_saida"""
import json, os, socket, sys, time
secs = float(sys.argv[1]); out = sys.argv[2]
keep = ('t', 'policy', 'move', 'joints', 'targets', 'velocities', 'imu', 'safety', 'loop')
t0 = time.monotonic()
with open(out, 'a') as f:
    def sync():
        f.flush(); os.fsync(f.fileno())
    while time.monotonic() - t0 < secs:
        try:
            s = socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect('/run/robotd.sock')
            s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"robot.subscribe","params":{}}\n')
            r = s.makefile('rb'); last = time.monotonic()
            while time.monotonic() - t0 < secs:
                line = r.readline()
                if not line:
                    raise OSError('robotd closed the subscription')
                try:
                    m = json.loads(line); p = m.get('params', m.get('result'))
                except ValueError:
                    continue
                if not isinstance(p, dict) or 'joints' not in p:
                    continue
                p = {k: p[k] for k in keep if k in p}; p['wall'] = time.time()
                f.write(json.dumps(p, separators=(',', ':')) + '\n')
                if time.monotonic() - last >= 1:
                    sync(); last = time.monotonic()
        except (OSError, socket.timeout) as e:
            f.write(json.dumps({'wall': time.time(), 'rec_error': f'{type(e).__name__}: {e}'}) + '\n'); sync()
            time.sleep(1)
