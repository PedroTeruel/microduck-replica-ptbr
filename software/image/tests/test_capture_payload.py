#!/usr/bin/env python3
import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import REF, SCRIPT_CAPTURE, make_tempdir, posix_path, require_sh, rmtree_force, run_shell  # noqa: E402

FIXTURE = REF / "etc" / "robot" / "feetech-ft5" / "robotd.toml"


class CaptureCleanToml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_sh()

    def setUp(self):
        self.tmp = make_tempdir("microduck-clean-")

    def tearDown(self):
        rmtree_force(self.tmp)

    def clean(self, text):
        src = self.tmp / "in.toml"
        dst = self.tmp / "out.toml"
        src.write_text(text, encoding="utf-8")
        result = run_shell([posix_path(SCRIPT_CAPTURE), "--clean-toml",
                            posix_path(src), posix_path(dst)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return dst.read_text(encoding="utf-8")

    def test_fixture_with_trunk_imu_and_audio(self):
        base = FIXTURE.read_text(encoding="utf-8")
        cut = base.index('["audio"]')
        base = base[:cut]
        extra = '''["audio"]
"enabled" = true
"device" = "plughw:aic3104"
"bank" = "/opt/robot/feetech-ft5-r5/voice-bank"

["trunk_imu"]
"model" = "LSM6DSV16X"
"i2c_device" = "/dev/i2c-3"
"i2c_address" = "0x6B"
'''
        text = base + extra
        out = self.clean(text)
        before = tomllib.loads(text)
        after = tomllib.loads(out)

        self.assertNotIn("trunk_imu", after)
        self.assertEqual(after["audio"]["bank"], "/var/lib/robot/sounds")
        self.assertTrue(after["audio"]["enabled"])
        self.assertEqual(after["audio"]["device"], "plughw:aic3104")

        expected = dict(before)
        del expected["trunk_imu"]
        expected["audio"] = dict(before["audio"])
        expected["audio"]["bank"] = "/var/lib/robot/sounds"
        self.assertEqual(after, expected)

        # 其余段原样：行级比较
        for section in ['["bus"]', '["control"]', '["policy"]', '["safety"]', '["pad"]']:
            start_in = text.index(section)
            end_in = text.index("\n[", start_in + 1) if "\n[" in text[start_in + 1:] else len(text)
            start_out = out.index(section)
            end_out = out.index("\n[", start_out + 1) if "\n[" in out[start_out + 1:] else len(out)
            self.assertEqual(text[start_in:end_in].strip(), out[start_out:end_out].strip(), section)

    def test_multiline_deleted_key(self):
        text = '''["bus"]
"port" = "/dev/ttyS2"

["imu"]
"imu_mount_quat" = [
  0.7,
  0.0,
  0.7,
  0.0
]
"other" = 2

["policy"]
"skill" = [
  { "name" = "a" },
  { "name" = "b" }
]
'''
        out = self.clean(text)
        data = tomllib.loads(out)
        self.assertNotIn("imu_mount_quat", data["imu"])
        self.assertEqual(data["imu"]["other"], 2)
        self.assertEqual(len(data["policy"]["skill"]), 2)
        self.assertNotIn("0.7", out)


class CaptureModelSkip(unittest.TestCase):
    """copy_models 的实际跳过规则：训练产物和作者使用说明都不进 payload。"""

    @classmethod
    def setUpClass(cls):
        require_sh()

    def setUp(self):
        self.tmp = make_tempdir("microduck-model-skip-")

    def tearDown(self):
        rmtree_force(self.tmp)

    def test_copy_models_skips_training_artifacts_and_note(self):
        text = SCRIPT_CAPTURE.read_text(encoding="utf-8")
        match = re.search(r"copy_models\(\) \{.*?\n\}", text, re.S)
        self.assertIsNotNone(match)
        src = self.tmp / "src"
        files = {
            "policy.onnx": b"model\n",
            "使用说明.md": b"export tool note\n",
            "model.pt": b"pt\n",
            "model.ckpt": b"ckpt\n",
            "export-data.zip": b"zip\n",
            "training-request.json": b"{}\n",
            "upstream-params/x.json": b"{}\n",
        }
        for rel, data in files.items():
            p = src / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        script = (
            'TMP="%s"\n'
            'mkdir -p "$TMP/stage"\n'
            '%s\n'
            'copy_models "%s" models\n'
        ) % (posix_path(self.tmp), match.group(0), posix_path(src))
        result = run_shell(["-c", script])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = sorted(p.name for p in (self.tmp / "stage/models").rglob("*") if p.is_file())
        self.assertEqual(installed, ["policy.onnx"])
        self.assertIn("使用说明.md", result.stdout)
        self.assertIn("model.pt", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
