"""Run the sensor browser unit tests in the standard unittest suite (Node >=22)."""
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which('node')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, 'Node >=22 is required for sensor UI tests')
class SensorsUiTests(unittest.TestCase):
    def test_sensor_ui_states_and_webrtc(self):
        version = subprocess.run([NODE, '--version'], capture_output=True, text=True, timeout=10)
        if int(version.stdout.strip().lstrip('v').split('.')[0]) < 22:
            self.skipTest('Node >=22 is required for ES module detection')
        result = subprocess.run([NODE, '--test', str(ROOT / 'tests/sensors_ui_unit.mjs')],
                                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
