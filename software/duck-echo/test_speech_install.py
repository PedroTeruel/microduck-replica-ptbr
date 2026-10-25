from pathlib import Path
import tempfile
import unittest
import zipfile

import install_speech


class WheelTests(unittest.TestCase):
    def test_pure_python_wheel_unpacks_into_private_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheel = root / 'example-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('example/__init__.py', 'VALUE = 42\n')
            install_speech.unpack_wheels(root, root / 'target')
            self.assertEqual((root / 'target/example/__init__.py').read_text(), 'VALUE = 42\n')

    def test_archive_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheel = root / 'example-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('../outside.txt', 'unsafe')
            with self.assertRaises(RuntimeError):
                install_speech.unpack_wheels(root, root / 'target')
            self.assertFalse((root / 'outside.txt').exists())


if __name__ == '__main__':
    unittest.main()
