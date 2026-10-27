"""Offline ARM64 speech resource preparation and hostile archive protection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / 'voice_resources.py'


class VoiceResources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.wheels = self.root / 'wheels'
        self.wheels.mkdir()
        self.model = self.root / 'model.zip'
        self.model_name = 'vosk-model-small-cn-0.22'
        self.zip(self.model, {self.model_name+'/am/final.mdl': b'fixture-model'})
        self.zip(self.wheels/'vosk-0.3.45-py3-none-manylinux2014_aarch64.whl',
                 {'vosk/__init__.py': b'# model API', 'vosk-0.3.45.dist-info/LICENSE': b'fixture-license'})
        self.zip(self.wheels/'cffi-2.1.1-cp313-cp313-manylinux2014_aarch64.whl',
                 {'cffi/__init__.py': b'# cffi', '_cffi_backend.so': b'fixture-arm64'})

    @staticmethod
    def zip(path, members):
        with zipfile.ZipFile(path, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def module(self):
        self.assertTrue(SOURCE.is_file(), 'offline voice resource preparer is missing')
        spec = importlib.util.spec_from_file_location('voice_resources', SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def prepare(self, **kwargs):
        return self.module().prepare(self.model, self.wheels, self.root/'out',
            expected_model_sha256=hashlib.sha256(self.model.read_bytes()).hexdigest(), **kwargs)

    def test_reproducible_manifest_pins_model_wheels_and_files(self):
        result = self.prepare()
        self.assertEqual(result['target'], 'linux-aarch64-cp313')
        self.assertEqual(len(result['wheels']), 2)
        self.assertEqual((self.root/'out/models'/self.model_name/'am/final.mdl').read_bytes(), b'fixture-model')
        self.assertEqual((self.root/'out/asr-deps/vosk-0.3.45.dist-info/LICENSE').read_bytes(), b'fixture-license')
        for item in result['files']:
            self.assertEqual(hashlib.sha256((self.root/'out'/item['path']).read_bytes()).hexdigest(), item['sha256'])
        self.assertEqual(json.loads((self.root/'out/resources-manifest.json').read_text()), result)

    def test_wrong_model_hash_preserves_existing_inputs_and_writes_nothing(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.module().prepare(self.model,self.wheels,self.root/'out',expected_model_sha256='0'*64)
        self.assertFalse((self.root/'out').exists())

    def test_wrong_python_or_architecture_rejected_before_output(self):
        self.zip(self.wheels/'cffi-2.1.1-cp312-cp312-manylinux2014_x86_64.whl', {'x': b'wrong'})
        with self.assertRaisesRegex(ValueError, 'target'):
            self.prepare()
        self.assertFalse((self.root/'out').exists())

    def test_model_path_escape_and_symlink_are_rejected(self):
        for bad in ('../escape', '/absolute', 'C:/drive', self.model_name+'/../../escape'):
            self.zip(self.model, {bad:b'bad',self.model_name+'/am/final.mdl':b'fixture-model'})
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'unsafe'):
                self.prepare()
        info = zipfile.ZipInfo(self.model_name+'/am/final.mdl')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.model,'w') as archive:
            archive.writestr(info, '/etc/shadow')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.prepare()
        self.assertFalse((self.root/'out').exists())

    def test_duplicate_wheel_files_and_expansion_limits_fail_without_partial_output(self):
        self.zip(self.wheels/'other-1-py3-none-any.whl', {'vosk/__init__.py':b'overwrite'})
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.prepare()
        (self.wheels/'other-1-py3-none-any.whl').unlink()
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.prepare(max_bytes=2)
        self.assertFalse((self.root/'out').exists())

    def test_existing_output_is_never_overwritten(self):
        (self.root/'out').mkdir()
        (self.root/'out/keep').write_text('keep')
        with self.assertRaisesRegex(FileExistsError, 'output'):
            self.prepare()
        self.assertEqual((self.root/'out/keep').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
