#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import SCRIPT_BUILD, posix_path, require_sh, run_shell  # noqa: E402


class BuildImageSelftest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_sh()

    def test_partition_selftest(self):
        result = run_shell([posix_path(SCRIPT_BUILD), "--selftest"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("自检通过", result.stdout)
        self.assertIn("GPT", result.stdout)
        self.assertIn("MBR", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
