"""Real Studio HTTP + local fake tofd + explicit browser RTC test double, no physical robot."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_vpad_e2e import EDGE, NODE, ROOT, HERE, _kill, _node_ok, _port, _wait_http


BOOT = r'''
import json, os, socketserver, sys, threading
from pathlib import Path
sys.path[:0] = [ROOT, str(Path(ROOT)/"deps"), str(Path(ROOT)/"dev")]
control=Path(os.environ["SENSOR_CONTROL"])
record=Path(os.environ["SENSOR_RECORD"])
class CameraHealth(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(3)
            request=json.loads(self.rfile.readline(4096))
            with Path(os.environ['SENSOR_CAMERA_RECORD']).open('a',encoding='utf-8') as output:
                output.write(json.dumps(request)+'\n')
            if json.loads(control.read_text(encoding='utf-8')).get('camera')=='offline': return
            self.wfile.write((json.dumps({'jsonrpc':'2.0','id':request.get('id'),
                'result':{'api_version':40,'daemon_version':'test-fixture'}})+'\n').encode())
            self.wfile.flush()
        except (OSError,ValueError): pass
class ToF(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(3)
            request=json.loads(self.rfile.readline(4096))
            with record.open('a',encoding='utf-8') as output:
                output.write(json.dumps(request)+'\n')
            mode=json.loads(control.read_text(encoding='utf-8')).get('mode','ready')
            result={'accepted':True,'rows':8,'cols':8,'hz':5}
            if mode=='missing': result['unavailable']='no ToF fitted (test fixture)'
            else: result['sensor']='VL53L8CX' if mode=='ready-real' else 'fake'
            self.wfile.write((json.dumps({'jsonrpc':'2.0','id':request.get('id'),'result':result})+'\n').encode())
            self.wfile.flush()
            if mode=='missing':
                self.rfile.read(1)
                return
            distances=[1000]*64; statuses=[5]*64
            distances[0]=350; distances[1]=1800;statuses[1]=9
            distances[2]=0;statuses[2]=255
            distances[3]=900;statuses[3]=4
            distances[4]=-3;statuses[4]=5
            if mode=='bad': distances=[1]
            frame={'seq':1,'at_us':12000,'t_ns':0,'rows':8,'cols':8,'distance_mm':distances,'status':statuses}
            self.wfile.write((json.dumps({'jsonrpc':'2.0','method':'tof.frame','params':frame})+'\n').encode())
            self.wfile.flush()
            self.rfile.read(1)
        except (OSError,ValueError):
            pass
class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True
tof=Server(('127.0.0.1',int(os.environ['SENSOR_TOF_PORT'])),ToF)
threading.Thread(target=tof.serve_forever,daemon=True).start()
media=Server(('127.0.0.1',int(os.environ['SENSOR_MEDIA_PORT'])),CameraHealth)
threading.Thread(target=media.serve_forever,daemon=True).start()
from studio.__main__ import main
main(sys.argv[1:])
'''


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get('STUDIO_E2E','1')!='0',
                     '需要 Node >=22 和 Edge；STUDIO_E2E=0 时跳过浏览器测试')
class SensorsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keep=os.environ.get('SENSOR_E2E_DIR')
        cls.dir=Path(cls.keep or tempfile.mkdtemp(prefix='sensors-e2e-')).resolve()
        cls.dir.mkdir(parents=True,exist_ok=True)
        root=cls.dir/'duck'; (root/'etc/robot').mkdir(parents=True,exist_ok=True)
        (root/'etc/robot/robotd.toml').write_text('[media]\nsource="test"\n',encoding='utf-8')
        cls.control=cls.dir/'control.json'; cls.control.write_text('{"mode":"ready"}',encoding='utf-8')
        cls.record=cls.dir/'tof.jsonl'; cls.record.write_text('',encoding='utf-8')
        rd,cfg,web,cdp,tof,media=(_port(p) for p in (17061,17062,18121,9361,17063,17064))
        cls.camera_record=cls.dir/'camera.jsonl'; cls.camera_record.write_text('',encoding='utf-8')
        cls.camera_config=root/'etc/robot/robotd.toml'
        cls.web,cls.cdp=web,cdp
        env=dict(os.environ,PYTHONIOENCODING='utf-8',SENSOR_CONTROL=str(cls.control),SENSOR_RECORD=str(cls.record),
            SENSOR_TOF_PORT=str(tof),SENSOR_MEDIA_PORT=str(media),SENSOR_CAMERA_RECORD=str(cls.camera_record))
        boot=cls.dir/'boot.py'; boot.write_text(f'ROOT={str(ROOT)!r}\n'+BOOT,encoding='utf-8')
        cls.procs=[];cls.streams=[]
        def output(name):
            stream=open(cls.dir/name,'w',encoding='utf-8');cls.streams.append(stream);return stream
        try:
            cls.procs.append(subprocess.Popen([sys.executable,'-I',str(ROOT/'dev/fake_robotd.py'),'--fixture',str(HERE/'fixtures/now-20261018.jsonl'),
                '--posture','limp','--robotd-port',str(rd),'--configd-port',str(cfg)],cwd=ROOT,env=env,
                stdout=output('fake.out'),stderr=subprocess.STDOUT))
            cls.procs.append(subprocess.Popen([sys.executable,'-I',str(boot),'--listen',f'127.0.0.1:{web}',
                '--robotd',f'tcp:127.0.0.1:{rd}','--configd',f'tcp:127.0.0.1:{cfg}','--dev-duck-root',str(root),
                '--duck-label','传感器测试鸭','--dev-autologin','--tof',f'tcp:127.0.0.1:{tof}',
                '--camera-socket',f'tcp:127.0.0.1:{media}',
                '--state-dir',str(cls.dir/'state'),'--log-dir',str(cls.dir/'logs')],cwd=ROOT,env=env,
                stdout=output('studio.out'),stderr=subprocess.STDOUT))
            _wait_http(f'http://127.0.0.1:{web}/healthz','传感器测试 Studio')
            cls.procs.append(subprocess.Popen([EDGE,'--headless=new','--disable-gpu','--no-sandbox','--no-first-run',
                '--no-default-browser-check','--autoplay-policy=no-user-gesture-required','--enable-unsafe-swiftshader',
                f'--remote-debugging-port={cdp}',f'--user-data-dir={cls.dir/"edge"}','about:blank'],
                stdout=output('edge.out'),stderr=subprocess.STDOUT))
            _wait_http(f'http://127.0.0.1:{cdp}/json/version','传感器测试 Edge',timeout=60)
        except Exception:
            cls.tearDownClass();raise

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls,'procs',[]): _kill(process)
        for stream in getattr(cls,'streams',[]): stream.close()
        if not cls.keep and cls.dir.name.startswith('sensors-e2e-') and cls.dir.parent==Path(tempfile.gettempdir()).resolve():
            shutil.rmtree(cls.dir,ignore_errors=True)

    def test_pages_lifecycle_and_mobile(self):
        result=subprocess.run([NODE,str(HERE/'sensors_e2e.mjs'),'--url',f'http://127.0.0.1:{self.web}/',
            '--cdp',str(self.cdp),'--control',str(self.control),'--record',str(self.record),'--shots',str(self.dir/'shots'),
            '--camera-config',str(self.camera_config),'--camera-record',str(self.camera_record)],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=160)
        (self.dir/'node.out').write_text(result.stdout or '',encoding='utf-8')
        (self.dir/'node.err').write_text(result.stderr or '',encoding='utf-8')
        self.assertEqual(result.returncode,0,f'{result.stderr[-5000:]}\n测试日志：{self.dir}')
        report=json.loads(result.stdout)
        self.assertEqual(report['errors'],[])
        self.assertTrue(report['mobileFits'])
        requests=[json.loads(line) for line in self.record.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertTrue(requests)
        self.assertTrue(all(request['method']=='tof.stream' for request in requests))
        camera_requests=[json.loads(line) for line in self.camera_record.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertTrue(camera_requests)
        self.assertTrue(all(request['method']=='hello' for request in camera_requests))
