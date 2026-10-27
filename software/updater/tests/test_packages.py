import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package import unpack_outer, PackageError, runtime_path, valid_version


class Packages(unittest.TestCase):
    def outer(self, names=None):
        files = {'2026.10.27.manifest.json': json.dumps({'channel':'software','version':'2026.10.27',
            'url':'2026.10.27.tar.gz','sig_url':'2026.10.27.tar.gz.minisig','size':1,'sha256':'a'*64}).encode(),
            '2026.10.27.manifest.json.minisig':b'signature', '2026.10.27.tar.gz':b'x',
            '2026.10.27.tar.gz.minisig':b'signature'}
        out=io.BytesIO()
        with tarfile.open(fileobj=out, mode='w') as tf:
            for name in names or files:
                info=tarfile.TarInfo(name); data=files.get(name,b'x'); info.size=len(data)
                if name=='link': info.type=tarfile.SYMTYPE; info.linkname='/etc/passwd'; info.size=0
                tf.addfile(info,io.BytesIO(data))
        return out.getvalue()

    def test_strict_outer_and_no_partial_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'cache'
            manifest=unpack_outer(io.BytesIO(self.outer()), dest)
            self.assertEqual(manifest['version'],'2026.10.27')
            self.assertEqual(len(list(dest.iterdir())),4)
        for names in (['../escape'],['/absolute'],['link'],['a','a'],['a']*5):
            with tempfile.TemporaryDirectory() as tmp:
                dest=Path(tmp)/'cache'
                with self.assertRaises(PackageError): unpack_outer(io.BytesIO(self.outer(names)),dest)
                self.assertFalse(dest.exists())

    def test_runtime_whitelist_excludes_state_and_development(self):
        for name in ('software/studio/run.py','software/studio/studio/app.py','software/studio/web/app.js',
                     'software/studio/deps/anyio/__init__.py','software/studio/deploy/microduck-helper',
                     'software/duck-echo/duck_echo.py','software/duck-echo/voice_commands.py'):
            self.assertIsNotNone(runtime_path(name),name)
        for name in ('software/studio/state/password.json','software/studio/tests/test_http.py',
                     'software/studio/dev/fake_robotd.py','software/studio/deps/__pycache__/key.pyc',
                     'software/duck-echo/test_duck_echo.py','software/duck-echo/install_speech.py',
                     'software/studio/web/private.key'):
            self.assertIsNone(runtime_path(name),name)
        for version in ('2026.10.27','2026.10.27-rc.1','2026.10.27+1'): self.assertTrue(valid_version(version))
        for version in ('../1','1.2','01.2.3','1.2.3/../../x','1.2.3-01'): self.assertFalse(valid_version(version))

if __name__=='__main__': unittest.main()
