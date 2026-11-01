#!/usr/bin/env python3
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import BASE, REAL_OVERLAY, require_sh  # noqa: E402


class OverlayStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_sh()

    def test_padd_dropin(self):
        p = REAL_OVERLAY / "etc/systemd/system/padd.service.d/zzzz-replica-padd.conf"
        text = p.read_text(encoding="utf-8")
        self.assertNotIn("startup_gate", text)
        self.assertIn(
            "ExecStart=/opt/robot/feetech-ft5-r5/padd --socket /run/robotd.sock "
            "--config /etc/robot/feetech-ft5/robotd.toml --max-head 2.5 "
            "--input-settings /etc/robot/feetech-ft5/pad-settings.json",
            text,
        )
        self.assertIn("RuntimeDirectory=padd", text)
        self.assertIn("RestartPreventExitStatus=78", text)
        self.assertTrue(text.startswith("#"))

    def test_studio_dropin(self):
        p = REAL_OVERLAY / "etc/systemd/system/microduck-studio.service.d/10-image.conf"
        text = p.read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -I run.py --listen 0.0.0.0:8000", text)
        self.assertNotIn("Pato 2", text)

    def test_enable_list(self):
        lines = [line.strip() for line in
                 (REAL_OVERLAY / "enable.list").read_text(encoding="utf-8").splitlines()]
        self.assertIn("ssh.service", lines)

    def test_ssh_generates_missing_host_keys(self):
        # Cartão de validação de 21/10: sshd-keygen depende de ConditionFirstBoot; machine-id vazio não conta como primeira inicialização, então as chaves não são geradas e o sshd não inicia.
        conf = REAL_OVERLAY / "etc/systemd/system/ssh.service.d/10-microduck-hostkeys.conf"
        lines = [line.strip() for line in conf.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.startswith("#")]
        self.assertEqual(lines, ["[Service]", "ExecStartPre=",
                                 "ExecStartPre=/usr/bin/ssh-keygen -A",
                                 "ExecStartPre=/usr/sbin/sshd -t"])

    def test_model_doc(self):
        text = (REAL_OVERLAY / "usr/share/doc/microduck/模型说明.txt").read_text(encoding="utf-8")
        self.assertIn("todos os modelos listados em /opt/robot/feetech-ft5-r5/models/ e em roller/", text)
        self.assertNotIn("cinco políticas treinadas neste diretório", text)
        self.assertIn("@@MODEL_LIST@@", text)
        self.assertIn("licença pessoal e não comercial", text)

    def test_signal_traps(self):
        for rel in ["apply-rootfs.sh", "build-image.sh", "capture-payload.sh"]:
            text = (BASE / rel).read_text(encoding="utf-8")
            self.assertIn("trap 'exit 130' INT", text, rel)
            self.assertIn("trap 'exit 143' TERM", text, rel)
            self.assertIn("trap 'exit 129' HUP", text, rel)

    def test_overlay_has_no_symlinks(self):
        for root, dirs, files in os.walk(REAL_OVERLAY):
            for name in dirs + files:
                self.assertFalse(os.path.islink(os.path.join(root, name)), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
