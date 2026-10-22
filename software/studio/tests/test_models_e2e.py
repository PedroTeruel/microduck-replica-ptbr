"""真实部署包/HTTP/模型库 + 测试 RPC/预检器 + 无头 Edge；不操作真实鸭子。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.test_vpad_e2e import EDGE, NODE, ROOT, HERE, _kill, _node_ok, _port, _wait_http
from tests.test_model_package import CONTRACT, bundle


BOOT = r'''
import json, os, sys
from pathlib import Path
sys.path[:0] = [ROOT, str(Path(ROOT)/"deps"), str(Path(ROOT)/"dev")]
from tests.test_models import Runtime
from studio import models as M
runtime = Runtime()
original = M.Models.__init__
def init(self, rd, log, state_dir, **kw):
    kw["root"] = os.environ["MODEL_E2E_ROOT"]
    kw["rpc"] = runtime
    kw["validator"] = lambda path: {"valid": True, "test_only": True}
    original(self, rd, log, state_dir, **kw)
M.Models.__init__ = init
from studio.__main__ import main
main(sys.argv[1:])
'''


@unittest.skipUnless(_node_ok() and EDGE and os.environ.get('STUDIO_E2E', '1') != '0',
                     '需要 Node >=22 和 Edge；STUDIO_E2E=0 时不运行浏览器测试')
class ModelsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keep = os.environ.get('MODEL_E2E_DIR')
        cls.dir = Path(cls.keep or tempfile.mkdtemp(prefix='models-e2e-')).resolve()
        cls.dir.mkdir(parents=True, exist_ok=True)
        root = cls.dir / 'duck'
        state = root / 'var/lib/microduck-studio'
        state.mkdir(parents=True, exist_ok=True)
        from tests.test_models import Runtime
        config = root / 'etc/robot/feetech-ft5/robotd.toml'
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[policy]\nwalk = "/opt/robot/feetech-ft5-r5/models/walk/policy.onnx"\n', encoding='utf-8')
        for path in Runtime().paths.values():
            target = root / path.lstrip('/')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'default-test-model')
            target.with_name('deployment-contract.json').write_text(json.dumps(CONTRACT), encoding='utf-8')
        # A real archive, parsed by production package code. The ONNX inference validator is injected above.
        cls.package = cls.dir / 'trained.zip'
        with zipfile.ZipFile(cls.package, 'w') as archive:
            for name, data in bundle().items():
                archive.writestr('export/' + name, data)
        cls.invalid = cls.dir / 'invalid.zip'
        cls.invalid.write_bytes(b'not a valid archive')
        p_rd, p_cfg, p_web, p_cdp = _port(17051), _port(17052), _port(18111), _port(9351)
        cls.p_web, cls.p_cdp = p_web, p_cdp
        env = dict(os.environ, PYTHONIOENCODING='utf-8', MODEL_E2E_ROOT=str(root))
        boot = cls.dir / 'boot.py'
        boot.write_text(f'ROOT = {str(ROOT)!r}\n' + BOOT, encoding='utf-8')
        cls.procs = []
        cls.files = []
        def output(name):
            stream = open(cls.dir / name, 'w', encoding='utf-8')
            cls.files.append(stream)
            return stream
        try:
            cls.procs.append(subprocess.Popen([sys.executable, '-I', str(ROOT / 'dev/fake_robotd.py'),
                '--fixture', str(HERE / 'fixtures/now-20261018.jsonl'), '--posture', 'limp',
                '--robotd-port', str(p_rd), '--configd-port', str(p_cfg)], cwd=ROOT, env=env,
                stdout=output('fake.out'), stderr=subprocess.STDOUT))
            cls.procs.append(subprocess.Popen([sys.executable, '-I', str(boot), '--listen', f'127.0.0.1:{p_web}',
                '--robotd', f'tcp:127.0.0.1:{p_rd}', '--configd', f'tcp:127.0.0.1:{p_cfg}',
                '--duck-label', '模型测试鸭', '--dev-autologin', '--state-dir', str(state),
                '--dev-duck-root', str(root), '--log-dir', str(cls.dir / 'logs')], cwd=ROOT, env=env,
                stdout=output('studio.out'), stderr=subprocess.STDOUT))
            _wait_http(f'http://127.0.0.1:{p_web}/healthz', '模型测试 Studio')
            cls.procs.append(subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-sandbox',
                '--no-first-run', '--no-default-browser-check', '--enable-unsafe-swiftshader',
                f'--remote-debugging-port={p_cdp}', f'--user-data-dir={cls.dir / "edge"}', 'about:blank'],
                stdout=output('edge.out'), stderr=subprocess.STDOUT))
            _wait_http(f'http://127.0.0.1:{p_cdp}/json/version', '模型测试 Edge', timeout=60)
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        for process in getattr(cls, 'procs', []):
            _kill(process)
        for stream in getattr(cls, 'files', []):
            stream.close()
        if not cls.keep:
            # The only deletion target is the resolved, uniquely-created test directory.
            if cls.dir.name.startswith('models-e2e-') and cls.dir.parent == Path(tempfile.gettempdir()).resolve():
                shutil.rmtree(cls.dir, ignore_errors=True)

    def test_library_flow_desktop_and_mobile(self):
        result = subprocess.run([NODE, str(HERE / 'models_e2e.mjs'), '--url', f'http://127.0.0.1:{self.p_web}/',
            '--cdp', str(self.p_cdp), '--package', str(self.package), '--invalid', str(self.invalid),
            '--shots', str(self.dir / 'shots')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=180)
        (self.dir / 'node.out').write_text(result.stdout or '', encoding='utf-8')
        (self.dir / 'node.err').write_text(result.stderr or '', encoding='utf-8')
        self.assertEqual(result.returncode, 0, f'{result.stderr[-5000:]}\n测试日志：{self.dir}')
        report = json.loads(result.stdout)
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['importedAfterDelete'], 0)
        self.assertTrue(report['mobileFits'])
