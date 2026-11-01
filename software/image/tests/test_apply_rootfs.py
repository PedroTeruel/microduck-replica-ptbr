#!/usr/bin/env python3
import os
import re
import shutil
import stat
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    CALIB,
    IS_WINDOWS,
    THIRD_PARTY_NAME,
    THIRD_PARTY_WORD,
    FakeProject,
    grant_777,
    make_tempdir,
    posix_path,
    require_sh,
    rmtree_force,
    ref_text,
    sha,
)


def replace_first_menu_title(data, title=b"menu title Microduck (Radxa U-Boot)"):
    out = []
    replaced = False
    for line in data.splitlines(keepends=True):
        if not replaced and line.startswith(b"menu title"):
            if line.endswith(b"\r\n"):
                ending = b"\r\n"
            elif line.endswith(b"\n"):
                ending = b"\n"
            else:
                ending = b""
            out.append(title + ending)
            replaced = True
        else:
            out.append(line)
    return b"".join(out)


class ApplyTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_sh()

    def setUp(self):
        self.tmp = make_tempdir("microduck-apply-")
        self.fx = FakeProject(self.tmp)

    def tearDown(self):
        rmtree_force(self.tmp)

    def run_ok(self, root, payload, studio, overlay, **kwargs):
        result = self.fx.run_apply(root, payload, studio, overlay, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        return result

    def run_fail(self, root, payload, studio, overlay, **kwargs):
        result = self.fx.run_apply(root, payload, studio, overlay, **kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        return result


class test_apply_full(ApplyTestBase):
    def test_full_apply(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        result = self.run_ok(root, payload, studio, overlay,
                             env_extra={"STUDIO_VERSION": "env-9.9.9"})
        out = result.stdout + "\n" + result.stderr

        # ---- 1. Os arquivos state.py e logs.py do Studio devem ser preservados ----
        self.assertTrue((root / "home/radxa/studio-dev/studio/state.py").exists())
        self.assertTrue((root / "home/radxa/studio-dev/studio/logs.py").exists())
        self.assertTrue((root / "home/radxa/studio-dev/run.py").exists())
        for rel in ["README.md", "LICENSE", "web/index.html", "deps/pkg/__init__.py",
                    "deploy/microduck-helper"]:
            self.assertTrue((root / "home/radxa/studio-dev" / rel).exists(), rel)
        for rel in ["logs", "state-dev", "_testlogs", "docs", "dev",
                    "run_tests.py", "tests", "nested/__pycache__",
                    "studio/__pycache__", "deploy/__pycache__"]:
            self.assertFalse((root / "home/radxa/studio-dev" / rel).exists(), rel)

        # ---- Drop-in do modo de calibração de fábrica ----
        commissioning = (root / "etc/systemd/system/robotd.service.d/"
                         "zzzz-zz-microduck-commissioning.conf")
        self.assertEqual(commissioning.read_bytes(), (
            "# Imagem réplica do Microduck: o programa principal inicia no modo de calibração (--commissioning).\n"
            "# Após concluir a etapa 3 do guia inicial, o assistente root remove este arquivo e o programa volta ao modo de movimento.\n"
            "[Service]\n"
            "ExecStart=\n"
            "ExecStart=/opt/robot/feetech-ft5-r5/robotd --config /etc/robot/feetech-ft5/robotd.toml "
            "--commissioning\n").encode("utf-8"))
        if not IS_WINDOWS:
            commissioning_stat = commissioning.stat()
            self.assertEqual(stat.S_IMODE(commissioning_stat.st_mode), 0o644)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                self.assertEqual((commissioning_stat.st_uid, commissioning_stat.st_gid), (0, 0))

        # ---- 3. padd não passa por startup_gate.py ----
        dropins = sorted(p.name for p in (root / "etc/systemd/system/padd.service.d").iterdir())
        self.assertEqual(dropins, ["zzzz-replica-netpad.conf", "zzzz-replica-padd.conf"])
        gate_hits = [p for p in (root / "etc").rglob("*") if p.is_file() and b"startup_gate" in p.read_bytes()]
        self.assertEqual(gate_hits, [])
        padd_conf = (root / "etc/systemd/system/padd.service.d/zzzz-replica-padd.conf").read_text(encoding="utf-8")
        self.assertIn("--config /etc/robot/feetech-ft5/robotd.toml", padd_conf)
        self.assertIn("RuntimeDirectory=padd", padd_conf)
        self.assertIn("RestartPreventExitStatus=78", padd_conf)

        # ---- 4. Serviços e nomes de outro autor ----
        for rel in [
            "etc/systemd/system/microduck-setup.service",
            "etc/systemd/system/multi-user.target.wants/microduck-setup.service",
            "usr/local/libexec/microduck-setup-portal.py",
            "usr/local/libexec/__pycache__",
            "usr/local/sbin/microduck-public-image",
            "etc/NetworkManager/system-connections/Microduck-Setup.nmconnection",
            "etc/systemd/system/gamesir-xboxd.service",
            "etc/systemd/system/gamesir-xboxd.service.d",
            "usr/local/sbin/gamesir-xboxd",
            "usr/local/sbin/gamesir-xbox-status",
            "etc/udev/rules.d/70-gamesir-xbox-bridge.rules",
            "etc/modules-load.d/gamesir-xbox.conf",
            "etc/systemd/system/alsa-restore.service.d/microduck-audio.conf",
            "etc/systemd/system/alsa-state.service.d/microduck-audio.conf",
            "etc/systemd/system/alsa-restore.service.d",
            "etc/systemd/system/alsa-state.service.d",
            "etc/sudoers.d/microduck-alsa-volume",
            "var/lib/alsa/asound.state",
            "etc/microduck-v112-image.txt",
            "home/radxa/microduck-public-image.sh",
            "home/radxa/microduck-public-image-R5.sh",
            "home/radxa/microduck-official-init",
            "home/radxa/microduck-official-install-20261019",
            "etc/systemd/system/multi-user.target.wants/gamesir-xboxd.service",
        ]:
            self.assertFalse(os.path.lexists(root / rel), rel)

        # A inicialização oficial da placa de som deve ser preservada; não altere o link de habilitação nem o script.
        for rel in [
            "etc/systemd/system/aic3104-init.service",
            "etc/systemd/system/multi-user.target.wants/aic3104-init.service",
            "usr/local/bin/aic3104-init.sh",
        ]:
            self.assertTrue(os.path.lexists(root / rel), rel)
        self.assertEqual((root / "etc/systemd/system/aic3104-init.service").read_bytes(),
                         ref_text("etc/systemd/system/aic3104-init.service"))
        self.assertEqual((root / "usr/local/bin/aic3104-init.sh").read_bytes(), b"#!/bin/sh\nexit 0\n")
        if not IS_WINDOWS:
            self.assertEqual(stat.S_IMODE((root / "usr/local/bin/aic3104-init.sh").stat().st_mode), 0o755)
        self.assertIn("var/lib/alsa/asound.state", out)
        self.assertIn("var/lib/alsa/asound.state", out)
        extlinux = (root / "boot/extlinux/extlinux.conf").read_bytes()
        expected_extlinux = replace_first_menu_title(ref_text("boot/extlinux/extlinux.conf"))
        self.assertEqual(extlinux, expected_extlinux)  # Somente a primeira linha menu title foi alterada.

        # ---- 5. Calibração ----
        cal = root / "etc/robot/feetech-ft5/hd1910-calibration.toml"
        self.assertEqual(cal.read_bytes(), CALIB.read_bytes())
        if not IS_WINDOWS:
            self.assertEqual(stat.S_IMODE(cal.stat().st_mode), 0o644)
        self.assertEqual(sorted(p.name for p in (root / "etc/robot/feetech-ft5").glob("hd1910-calibration*.toml")),
                         ["hd1910-calibration.toml"])
        self.assertTrue((root / "etc/robot/feetech-ft5/robotd.saved.toml").exists())
        self.assertTrue((root / "etc/robot/feetech-ft5/custom-calib.toml").exists())
        with open(cal, "rb") as fh:
            data = tomllib.load(fh)
        self.assertFalse(data["motion_enabled"])
        self.assertFalse(data["imu_mount_verified"])
        self.assertFalse(data["units_verified"])
        self.assertEqual(data["current_ma_per_count"], 0.0)
        self.assertEqual(data["imu_mount_quat"], [0.7071067811865476, 0.0, 0.7071067811865476, 0.0])
        self.assertEqual(len(data["joints"]), 15)
        self.assertEqual([j["id"] for j in data["joints"]],
                         [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14])
        for joint in data["joints"]:
            self.assertEqual(joint["direction"], -1)
            self.assertEqual(joint["zero_raw"], 2048)
            self.assertFalse(joint["calibrated"])
            self.assertEqual(set(joint), {"name", "id", "zero_raw", "direction", "calibrated"})

        # ---- 12. SSH ----
        wants = root / "etc/systemd/system/multi-user.target.wants"
        self.assertTrue(os.path.lexists(wants / "ssh.service"))
        self.assertTrue(os.path.lexists(root / "etc/systemd/system/sshd.service"))
        self.assertTrue(os.path.lexists(wants / "demo.service"))
        self.assertTrue(os.path.lexists(wants / "microduck-studio.service"))
        self.assertFalse(os.path.lexists(root / "root/.ssh/authorized_keys"))
        self.assertFalse(os.path.lexists(root / "root/.ssh/known_hosts"))
        self.assertFalse(os.path.lexists(root / "home/radxa/.ssh/authorized_keys"))
        self.assertFalse(os.path.lexists(root / "home/radxa/.ssh/known_hosts"))
        self.assertIn("não foi encontrada", out)
        self.assertNotIn("sshd_config.d/10-microduck.conf", result.stdout)

        # ---- 13. Rastros pessoais ----
        self.assertEqual((root / "var/log/syslog").read_bytes(), b"")
        self.assertEqual(list((root / "var/log/journal").iterdir()), [])
        self.assertEqual((root / "var/log.hdd/syslog").read_bytes(), b"")
        self.assertEqual(list((root / "var/log.hdd/journal").iterdir()), [])
        self.assertEqual(list((root / "var/lib/bluetooth").iterdir()), [])
        self.assertEqual(list((root / "var/lib/NetworkManager").iterdir()), [])
        self.assertFalse((root / "var/lib/systemd/random-seed").exists())
        for rel in ["root/.python_history", "root/.viminfo", "root/.lesshst",
                    "root/.wget-hsts", "root/.cache", "root/.local/share/recently-used.xbel",
                    "home/radxa/.python_history", "home/radxa/.viminfo",
                    "home/radxa/.lesshst", "home/radxa/.wget-hsts",
                    "home/radxa/.cache", "home/radxa/.local/share/recently-used.xbel"]:
            self.assertFalse(os.path.lexists(root / rel), rel)
        self.assertTrue((root / "var/lib/robot/config").exists())
        self.assertFalse((root / "etc/robot/trusted_keys/local.dev.pub").exists())
        self.assertTrue((root / "etc/robot/trusted_keys/release-2026.pub").exists())
        updater = (root / "etc/robot/updater.toml").read_text(encoding="utf-8")
        self.assertIn("    allow_dev_keys = false  # somente assinatura de desenvolvimento local", updater)
        self.assertIn("verify_signatures = true", updater)
        for rel in ["etc/passwd", "etc/passwd-"]:
            self.assertEqual(
                (root / rel).read_text(encoding="utf-8").splitlines()[23],
                "radxa:x:1000:1000:Microduck:/home/radxa:/bin/bash",
            )
        for rel in ["etc/shadow", "etc/shadow-"]:
            lines = (root / rel).read_text(encoding="utf-8").splitlines()
            radxa = [line for line in lines if line.startswith("radxa:")][0]
            fields = radxa.split(":")
            self.assertTrue(fields[1].startswith("$6$"), rel)
            self.assertRegex(fields[1], r"^\$6\$[^$]+\$")
            salt = fields[1].split("$")[2]
            import subprocess
            expected = subprocess.run(
                ["openssl", "passwd", "-6", "-salt", salt, "microduck"],
                capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(fields[1], expected, rel)
            self.assertTrue(fields[0] == "radxa" and fields[2:] == ["19000", "0", "99999", "7", "", "", ""])
            root_line = [line for line in lines if line.startswith("root:")][0]
            self.assertEqual(root_line.split(":")[1], "!", rel)
        hwclock = (root / "etc/fake-hwclock.data").read_text(encoding="utf-8").strip()
        self.assertRegex(hwclock, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")

        # ---- 15. Drop-in do Studio na imagem ----
        image_conf = (root / "etc/systemd/system/microduck-studio.service.d/10-image.conf").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/bin/python3 -I run.py --listen 0.0.0.0:8000", image_conf)
        self.assertNotIn("Pato 2", image_conf)

        # ---- 16. Documentação dos modelos ----
        doc = (root / "usr/share/doc/microduck/模型说明.txt").read_text(encoding="utf-8")
        self.assertIn("todos os modelos listados em /opt/robot/feetech-ft5-r5/models/ e em roller/", doc)
        self.assertNotIn("cinco políticas treinadas neste diretório", doc)
        self.assertIn("models/aaa", doc)
        self.assertIn(sha(self.fx.model_a), doc)
        self.assertIn("roller/bbb", doc)
        self.assertIn(sha(self.fx.model_b), doc)
        self.assertNotIn("models/legacy", doc)
        self.assertNotIn("@@MODEL_LIST@@", doc)

        # ---- 19. Versão do Studio ----
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        self.assertTrue(manifest.startswith("Manifesto da imagem réplica do Microduck\n"))
        self.assertIn("Versão do Studio: env-9.9.9", manifest)
        self.assertIn(sha(self.fx.robotd), manifest)
        self.assertIn("Aguardando confirmação manual", manifest)
        self.assertIn("var/lib/robot/config", manifest)
        self.assertIn("diretório vazio", manifest)
        self.assertIn("O Studio inclui somente arquivos de execução", manifest)
        self.assertIn("Senha padrão de radxa: microduck", manifest)
        delete_section = manifest.split("Removidos (caminhos relativos à raiz da imagem)", 1)[1].split("Adicionados / instalados", 1)[0]
        self.assertNotIn("aic3104", delete_section)
        self.assertIn("var/lib/alsa/asound.state", delete_section)
        confirm = manifest.split("Aguardando confirmação manual", 1)[1].split("Avisos de configuração SSH", 1)[0]
        self.assertNotIn("local.dev.pub", confirm)

        # enable.list do overlay não deve ser incluído na imagem; permissões dos arquivos do overlay: 0644.
        self.assertFalse((root / "enable.list").exists())
        self.assertFalse((root / "modes.list").exists())
        self.assertTrue((root / "usr/local/bin/demo-tool").exists())
        if not IS_WINDOWS:
            self.assertEqual(stat.S_IMODE((root / "usr/local/bin/demo-tool").stat().st_mode), 0o755)
        if not IS_WINDOWS:
            for rel in ["etc/ssh/sshd_config.d/10-microduck.conf",
                        "etc/systemd/system/padd.service.d/zzzz-replica-padd.conf",
                        "usr/share/doc/microduck/开源许可.txt"]:
                self.assertEqual(stat.S_IMODE((root / rel).stat().st_mode), 0o644, rel)

        # O netpad do payload foi preservado.
        self.assertTrue((root / "etc/systemd/system/padd.service.d/zzzz-replica-netpad.conf").exists())
        # Os arquivos antigos do diretório opt foram removidos.
        for rel in ["opt/robot/feetech-ft5-r5/gamepad-r7", "opt/robot/feetech-ft5-r5/service.sh",
                    "opt/robot/feetech-ft5-r5/_model_yaml", "opt/robot/feetech-ft5-r5/unused.txt"]:
            self.assertFalse((root / rel).exists(), rel)
        # models/, roller/ e onnxruntime/ correspondem ao payload; arquivos extras e diretórios vazios foram removidos.
        opt = root / "opt/robot/feetech-ft5-r5"
        for sub in ["models", "roller", "onnxruntime"]:
            files = sorted(p.relative_to(root).as_posix() for p in (opt / sub).rglob("*") if p.is_file())
            want = sorted(k for k in self.fx.payload_files() if k.startswith(f"opt/robot/feetech-ft5-r5/{sub}/"))
            self.assertEqual(files, want, sub)
        self.assertFalse((opt / "models/legacy").exists())
        self.assertFalse((opt / "models/aaa/upstream-params").exists())
        self.assertIn("opt/robot/feetech-ft5-r5/models/aaa/export-data.zip", manifest)
        self.assertEqual((root / "opt/robot/feetech-ft5-r5/robotd").read_bytes(), self.fx.robotd)

    def test_reshape_failed(self):
        # ---- 11. Verificação da expansão automática na primeira inicialização ----
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        (root / "etc/systemd/system/basic.target.wants/armbian-resize-filesystem.service").unlink()
        result = self.run_fail(root, payload, studio, overlay)
        self.assertIn("armbian-resize-filesystem", result.stdout + result.stderr)

        root2 = self.fx.make_rootfs("rootfs2")
        root2.joinpath("root/.no_rootfs_resize").write_text("x", encoding="utf-8")
        result = self.run_fail(root2, payload, studio, overlay)
        self.assertIn(".no_rootfs_resize", result.stdout + result.stderr)


class test_extlinux_menu_title(ApplyTestBase):
    def test_missing_menu_title_is_left_alone(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        conf = root / "boot/extlinux/extlinux.conf"
        before = b"".join(
            line for line in conf.read_bytes().splitlines(keepends=True)
            if not line.startswith(b"menu title")
        )
        conf.write_bytes(before)

        result = self.run_ok(root, payload, studio, overlay)

        self.assertEqual(conf.read_bytes(), before)
        self.assertIn("não havia linha começando com menu title", result.stdout)


class test_apply_permissions(ApplyTestBase):
    def test_permissions_unchanged_with_umask_000(self):
        payload = self.fx.make_payload(chmod777=True)
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        grant_777(studio)
        grant_777(overlay)

        os.chmod(root, 0o755)
        os.chmod(root / "etc", 0o750)
        os.chmod(root / "usr", 0o751)
        os.chmod(root / "usr/share/doc", 0o700)
        before = {rel: stat.S_IMODE(os.stat(root / rel).st_mode)
                  for rel in [".", "etc", "usr", "usr/share/doc"]}
        self.run_ok(root, payload, studio, overlay, umask="000")
        after = {rel: stat.S_IMODE(os.stat(root / rel).st_mode)
                 for rel in [".", "etc", "usr", "usr/share/doc"]}
        self.assertEqual(before, after)
        # Windows e Git Bash só representam o atributo de leitura; diretórios sempre aparecem como 0777. Verifique bits exatos apenas em POSIX.
        if not IS_WINDOWS:
            self.assertEqual(after["etc"], 0o750)
            self.assertEqual(after["usr"], 0o751)
            self.assertEqual(after["usr/share/doc"], 0o700)
            for p in (root / "home/radxa/studio-dev").rglob("*"):
                mode = stat.S_IMODE(p.stat().st_mode)
                if p.is_dir():
                    self.assertEqual(mode, 0o755, str(p))
                else:
                    self.assertEqual(mode, 0o644, str(p))
            self.assertEqual(stat.S_IMODE((root / "opt/robot/feetech-ft5-r5/models/aaa").stat().st_mode), 0o755)


class test_symlink_escape(ApplyTestBase):
    def _escape(self, rel, outside):
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        payload = self.fx.make_payload()
        outside.mkdir(parents=True, exist_ok=True)
        target = root / rel
        if target.exists():
            rmtree_force(target)
        os.symlink(str(outside), str(target))
        result = self.run_fail(root, payload, studio, overlay)
        self.assertIn("fora de ROOT", result.stdout + result.stderr)
        self.assertEqual(list(outside.iterdir()), [], rel)

    def test_home_radxa(self):
        self._escape("home/radxa", self.tmp / "outside-home")

    def test_usr_local_sbin(self):
        self._escape("usr/local/sbin", self.tmp / "outside-sbin")

    def test_wants_dir(self):
        self._escape("etc/systemd/system/multi-user.target.wants", self.tmp / "outside-wants")

    def test_doc_dir(self):
        self._escape("usr/share/doc/microduck", self.tmp / "outside-doc")


class test_residual_scan(ApplyTestBase):
    def test_third_party_name_leak_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        put_path = root / "etc/leak-notes.txt"
        put_path.write_text("made by " + THIRD_PARTY_NAME + "\n", encoding="utf-8")
        result = self.run_fail(root, payload, studio, overlay)
        text = result.stdout + result.stderr
        self.assertIn("leak-notes.txt", text)
        self.assertIn("nome do autor terceiro", text)

    def test_third_party_word_in_passwd_files_fails(self):
        payload = self.fx.make_payload()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        for index, rel in enumerate(["etc/passwd", "etc/passwd-"]):
            with self.subTest(rel=rel):
                root = self.fx.make_rootfs(f"leak-root-{index}")
                path = root / rel
                path.write_bytes(path.read_bytes().replace(
                    b"root:x:0:0:root",
                    b"root:x:0:0:" + THIRD_PARTY_NAME.encode(), 1))
                result = self.run_fail(root, payload, studio, overlay)
                text = result.stdout + result.stderr
                self.assertIn(rel, text)
                self.assertIn("nome do autor terceiro", text)

    def test_third_party_word_inside_another_word_is_not_a_match(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        (root / "etc/leak-note.txt").write_text(
            THIRD_PARTY_WORD + "ing is not a leak\n", encoding="utf-8")
        self.run_ok(root, payload, studio, overlay)



class test_account_full_name(ApplyTestBase):
    def test_only_radxa_gecos_changes_in_both_passwd_files(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        old_line = b"radxa:x:1000:1000:" + THIRD_PARTY_WORD.encode() + b":/home/radxa:/bin/bash\n"
        new_line = b"radxa:x:1000:1000:Microduck:/home/radxa:/bin/bash\n"
        before = {}
        shadow_before = {}
        shadow_meta = {}
        for rel in ["etc/passwd", "etc/passwd-"]:
            data = (root / rel).read_bytes()
            self.assertEqual(data.splitlines(keepends=True)[23], old_line)
            before[rel] = data
        for rel in ["etc/shadow", "etc/shadow-"]:
            shadow_before[rel] = (root / rel).read_text(encoding="utf-8").splitlines()
            if not IS_WINDOWS:
                shadow_stat = (root / rel).stat()
                shadow_meta[rel] = (shadow_stat.st_uid, shadow_stat.st_gid,
                                    stat.S_IMODE(shadow_stat.st_mode))

        result = self.run_ok(root, payload, studio, overlay)

        for rel, data in before.items():
            after = (root / rel).read_bytes()
            self.assertEqual(after, data.replace(old_line, new_line, 1), rel)
            self.assertEqual(after.splitlines(keepends=True)[23], new_line, rel)
            self.assertIn(rel, result.stdout)
        for rel, old_lines in shadow_before.items():
            if not IS_WINDOWS:
                shadow_stat = (root / rel).stat()
                self.assertEqual(
                    shadow_meta[rel],
                    (shadow_stat.st_uid, shadow_stat.st_gid,
                     stat.S_IMODE(shadow_stat.st_mode)), rel)
            new_lines = (root / rel).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(old_lines), len(new_lines), rel)
            for old, new in zip(old_lines, new_lines):
                if old.startswith("radxa:"):
                    old_fields, new_fields = old.split(":"), new.split(":")
                    self.assertTrue(new_fields[1].startswith("$6$"), rel)
                    salt = new_fields[1].split("$")[2]
                    expected = subprocess.run(
                        ["openssl", "passwd", "-6", "-salt", salt, "microduck"],
                        check=True, capture_output=True, text=True, encoding="utf-8",
                    ).stdout.strip()
                    self.assertEqual(new_fields[1], expected, rel)
                    self.assertEqual(old_fields[2:], new_fields[2:], rel)
                else:
                    self.assertEqual(old, new, rel)
            root_line = next(line for line in new_lines if line.startswith("root:"))
            self.assertEqual(root_line.split(":")[1], "!", "root deve permanecer bloqueado")


class test_updater_trust(ApplyTestBase):
    def test_config_is_locked_and_dev_key_is_removed(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        updater = root / "etc/robot/updater.toml"
        before = updater.read_bytes()

        result = self.run_ok(root, payload, studio, overlay)

        self.assertEqual(
            updater.read_bytes(),
            before.replace(b"allow_dev_keys = true", b"allow_dev_keys = false", 1),
        )
        self.assertIn("    allow_dev_keys = false  # somente assinatura de desenvolvimento local\n",
                      updater.read_text(encoding="utf-8"))
        self.assertIn(b"verify_signatures = true\n", updater.read_bytes())
        self.assertFalse(os.path.lexists(root / "etc/robot/trusted_keys/local.dev.pub"))
        self.assertTrue(os.path.lexists(root / "etc/robot/trusted_keys/release-2026.pub"))
        self.assertIn("local.dev.pub", result.stdout)
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        confirm = manifest.split("Aguardando confirmação manual", 1)[1].split("Avisos de configuração SSH", 1)[0]
        self.assertNotIn("local.dev.pub", confirm)

    def test_only_dev_key_fails_after_printing(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        for key in (root / "etc/robot/trusted_keys").glob("release-*.pub"):
            key.unlink()

        result = self.run_fail(root, payload, studio, overlay)

        text = result.stdout + result.stderr
        self.assertIn("local.dev.pub", text)
        self.assertIn("release-*.pub", text)
        self.assertFalse(os.path.lexists(root / "etc/robot/trusted_keys/local.dev.pub"))


class test_home_install_residue(ApplyTestBase):
    def test_official_installer_leftovers_are_removed(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        leftovers = [
            "home/radxa/microduck-official-init",
            "home/radxa/microduck-official-install-20261019",
        ]

        result = self.run_ok(root, payload, studio, overlay)

        self.assertIn("serão removidos os resíduos de instalação do daemon oficial", result.stdout)
        for rel in leftovers:
            self.assertIn(rel, result.stdout)
            self.assertFalse(os.path.lexists(root / rel), rel)


class test_official_audio_init(ApplyTestBase):
    def test_missing_aic3104_unit_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        (root / "etc/systemd/system/aic3104-init.service").unlink()

        result = self.run_fail(root, payload, studio, overlay)

        self.assertIn("Unidade oficial de inicialização de áudio ausente", result.stdout + result.stderr)


class test_ssh_audit(ApplyTestBase):
    def test_weak_dropin_before_10_warns(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        root.joinpath("etc/ssh/sshd_config.d").mkdir(parents=True, exist_ok=True)
        root.joinpath("etc/ssh/sshd_config.d/05-weak.conf").write_text(
            "PasswordAuthentication yes\n", encoding="utf-8")
        result = self.run_ok(root, payload, studio, overlay)
        self.assertIn("05-weak.conf", result.stdout)
        self.assertIn("Aviso", result.stdout)

    def test_dropin_after_10_is_ignored(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        root.joinpath("etc/ssh/sshd_config.d").mkdir(parents=True, exist_ok=True)
        root.joinpath("etc/ssh/sshd_config.d/20-other.conf").write_text(
            "PasswordAuthentication yes\nPermitRootLogin yes\n", encoding="utf-8")
        result = self.run_ok(root, payload, studio, overlay)
        self.assertIn("não foi encontrada", result.stdout)
        self.assertNotIn("20-other.conf", result.stdout)


class test_payload_guards(ApplyTestBase):
    def test_bad_sha256_stops_before_copy(self):
        payload = self.fx.make_payload(bad_hash=True)
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        result = self.run_fail(root, payload, studio, overlay)
        text = result.stdout + result.stderr
        self.assertIn("sha256", text)
        self.assertIn("robotd", text)
        self.assertFalse((root / "usr/local/sbin/microduck-helper").exists())
        self.assertEqual((root / "opt/robot/feetech-ft5-r5/robotd").read_bytes(), b"old-robotd\n")

    def test_extra_file_rejected(self):
        payload = self.fx.make_payload(extra_file="opt/robot/feetech-ft5-r5/extra.so")
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        result = self.run_fail(root, payload, studio, overlay)
        self.assertIn("não constam no manifesto", result.stdout + result.stderr)

    def test_symlink_rejected(self):
        payload = self.fx.make_payload(extra_symlink=True)
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        result = self.run_fail(root, payload, studio, overlay)
        self.assertIn("links simbólicos", result.stdout + result.stderr)

    def test_empty_root_is_refused(self):
        payload = self.fx.make_payload()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        result = self.fx.run_apply("", payload, studio, overlay)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ROOT não pode estar vazio", result.stdout + result.stderr)


class test_payload_config_attrs(ApplyTestBase):
    def test_original_attrs_preserved_and_missing_file_defaults(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        conf = root / "etc/robot/feetech-ft5/robotd.toml"
        saved = root / "etc/robot/feetech-ft5/robotd.saved.toml"
        self.assertTrue(conf.exists())
        self.assertFalse(saved.exists())

        bindir = self.tmp / "fake-bin"
        bindir.mkdir()
        log = self.tmp / "attr-calls.txt"
        scripts = {
            "stat": '''#!/bin/sh
printf 'STAT %s\\n' "$3" >> "$ATTR_LOG"
case "$3" in
  */etc/robot/feetech-ft5/robotd.toml) printf '0 989 640\\n'; exit 0 ;;
esac
exec "$REAL_STAT" "$@"
''',
            "chown": '''#!/bin/sh
printf 'CHOWN %s %s\\n' "$1" "$2" >> "$ATTR_LOG"
exit 0
''',
            "chmod": '''#!/bin/sh
printf 'CHMOD %s %s\\n' "$1" "$2" >> "$ATTR_LOG"
exec "$REAL_CHMOD" "$@"
''',
        }
        for name, body in scripts.items():
            path = bindir / name
            path.write_text(body, encoding="utf-8")
            os.chmod(path, 0o755)

        env = {
            "PATH": ":".join([posix_path(bindir), "/usr/bin", "/bin"]
                             + [posix_path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]),
            "ATTR_LOG": posix_path(log),
            "REAL_STAT": posix_path(shutil.which("stat")),
            "REAL_CHMOD": posix_path(shutil.which("chmod")),
        }
        self.run_ok(root, payload, studio, overlay, env_extra=env)
        calls = log.read_text(encoding="utf-8").splitlines()

        self.assertIn("STAT %s" % posix_path(conf), calls)
        self.assertIn("CHOWN 0:989 %s" % posix_path(conf), calls)
        self.assertIn("CHMOD 640 %s" % posix_path(conf), calls)
        self.assertIn("CHOWN 0:0 %s" % posix_path(saved), calls)
        self.assertIn("CHMOD 644 %s" % posix_path(saved), calls)


class test_media_source(ApplyTestBase):
    def test_media_source_becomes_test(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay())

        lines = (root / "etc/robot/robotd.toml").read_text(encoding="utf-8").splitlines()
        hits = [i for i, line in enumerate(lines) if line.startswith('source = "test"')]
        self.assertEqual(len(hits), 1, lines)
        self.assertLess(lines.index("[media]"), hits[0])
        self.assertLess(hits[0], lines.index("[audio]"))
        self.assertNotIn('# source = "camera"', lines)
        # Comentários com o mesmo nome em outras seções permanecem inalterados.
        self.assertIn('# source = "mic"', lines)
        self.assertIn('# quality = "720p30"', lines)

    def test_media_without_source_line_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        conf = root / "etc/robot/robotd.toml"
        conf.write_text("[media]\n# quality = \"720p30\"\n\n[audio]\n# source = \"mic\"\n", encoding="utf-8")

        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())

        self.assertIn("Não foi encontrada uma linha source na seção [media]", result.stdout + result.stderr)


class test_commissioning_dropin(ApplyTestBase):
    def test_missing_execstart_fails(self):
        payload = self.fx.make_payload(robotd_dropin=b"[Service]\nRestart=always\n")
        result = self.run_fail(self.fx.make_rootfs(), payload,
                               self.fx.make_studio(), self.fx.make_overlay())
        self.assertIn("ExecStart", result.stdout + result.stderr)

    def test_two_execstart_lines_fail(self):
        payload = self.fx.make_payload(robotd_dropin=(
            b"[Service]\nExecStart=/bin/one\nExecStart=/bin/two\n"))
        result = self.run_fail(self.fx.make_rootfs(), payload,
                               self.fx.make_studio(), self.fx.make_overlay())
        self.assertIn("exatamente uma linha ExecStart= não vazia", result.stdout + result.stderr)

    def test_already_commissioning_fails(self):
        payload = self.fx.make_payload(robotd_dropin=(
            b"[Service]\nExecStart=/opt/robot/feetech-ft5-r5/robotd --commissioning\n"))
        result = self.run_fail(self.fx.make_rootfs(), payload,
                               self.fx.make_studio(), self.fx.make_overlay())
        self.assertIn("--commissioning", result.stdout + result.stderr)


class test_crlf_guard(ApplyTestBase):
    def test_crlf_overlay_file_fails_with_name_and_hint(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        (overlay / "usr/local/bin/crlf-tool").write_bytes(b"#!/bin/sh\r\necho x\r\n")
        (overlay / "usr/local/bin/tiny.png").write_bytes(b"\x89PNG\r\n\x1a\nbinary\r")
        result = self.run_fail(root, payload, studio, overlay)
        text = result.stdout + result.stderr
        self.assertIn("crlf-tool", text)
        self.assertNotIn("tiny.png", text)
        self.assertIn("core.autocrlf false", text)
        self.assertIn("dos2unix", text)


class test_model_cleanup(ApplyTestBase):
    def test_payload_model_note_is_deleted(self):
        payload = self.fx.make_payload(payload_extra={
            "opt/robot/feetech-ft5-r5/models/aaa/使用说明.md": b"export tool note\n",
            "opt/robot/feetech-ft5-r5/roller/bbb/使用说明.md": b"export tool note\n",
        })
        root = self.fx.make_rootfs()
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        self.assertFalse((root / "opt/robot/feetech-ft5-r5/models/aaa/使用说明.md").exists())
        self.assertFalse((root / "opt/robot/feetech-ft5-r5/roller/bbb/使用说明.md").exists())

    def test_training_artifacts_in_payload_fail(self):
        studio = self.fx.make_studio()
        overlay = self.fx.make_overlay()
        for index, name in enumerate(["model.pt", "model.ckpt", "training-request.json",
                                      "upstream-params/x.json", "export-data.zip"]):
            with self.subTest(name=name):
                payload = self.fx.make_payload(payload_extra={
                    "opt/robot/feetech-ft5-r5/models/aaa/" + name: b"x\n"})
                result = self.run_fail(self.fx.make_rootfs("rootfs-%d" % index), payload,
                                       studio, overlay)
                self.assertIn("artefatos de treinamento", result.stdout + result.stderr)


class test_unconfirmed(ApplyTestBase):
    def test_nonempty_config_dir_fails_by_default(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        config = root / "var/lib/robot/config/settings.json"
        config.write_text('{"name": "two"}\n', encoding="utf-8")
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        text = result.stdout + result.stderr
        self.assertIn("var/lib/robot/config/settings.json", text)
        self.assertIn(sha(config.read_bytes()), text)
        self.assertIn("ALLOW_UNCONFIRMED=1", text)

    def test_allow_unconfirmed_is_marked_in_manifest(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        config = root / "var/lib/robot/config/settings.json"
        config.write_text('{"name": "two"}\n', encoding="utf-8")
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay(),
                    env_extra={"ALLOW_UNCONFIRMED": "1"})
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        self.assertIn("liberou os arquivos regulares acima usando ALLOW_UNCONFIRMED=1", manifest)
        self.assertIn(sha(config.read_bytes()), manifest)


class test_manifest_metadata(ApplyTestBase):
    def test_build_metadata_is_at_the_top(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay(), env_extra={
            "BASE_IMG_NAME": "base.img",
            "BASE_IMG_SHA256": "a" * 64,
            "PAYLOAD_SHA256": "b" * 64,
            "IMAGE_VERSION": "test-1",
        })
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        self.assertIn("Nome do arquivo da imagem base: base.img", manifest)
        self.assertIn("SHA-256 da imagem base: " + "a" * 64, manifest)
        self.assertIn("SHA-256 do payload: " + "b" * 64, manifest)
        self.assertIn("Versão do script de imagem: test-1", manifest)


class test_residual_scan_more(ApplyTestBase):
    def test_binary_leak_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        (root / "etc/blob.bin").write_bytes(b"\x00" + THIRD_PARTY_NAME.encode() + b"\x00")
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        self.assertIn("blob.bin", result.stdout + result.stderr)

    def test_name_glued_to_another_word_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        (root / "etc/glued.txt").write_text("prefix-" + THIRD_PARTY_NAME + "-suffix\n",
                                             encoding="utf-8")
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        self.assertIn("glued.txt", result.stdout + result.stderr)

    def test_model_doc_is_the_only_exemption(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        overlay = self.fx.make_overlay()
        doc = overlay / "usr/share/doc/microduck/模型说明.txt"
        doc.write_bytes(doc.read_bytes() + ("\n" + THIRD_PARTY_NAME + "\n").encode("utf-8"))
        self.run_ok(root, payload, self.fx.make_studio(), overlay)

    def test_dangling_link_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        wants = root / "etc/systemd/system/multi-user.target.wants"
        os.symlink("/etc/systemd/system/missing.service", wants / "missing.service")
        os.symlink("/etc/missing-cron", root / "etc/crontab")
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        text = result.stdout + result.stderr
        self.assertIn("missing.service", text)
        self.assertIn("missing-cron", text)
        self.assertIn("Links quebrados", text)

    def test_masked_unit_is_not_dangling(self):
        # O link -> /dev/null criado por systemctl mask não está quebrado, mesmo que /dev/null não exista no rootfs montado.
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        os.symlink("/dev/null", root / "etc/systemd/system/serial-getty@ttyS2.service")
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay())

    def test_deleted_basename_still_referenced_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        (root / "etc/systemd/system/keep.service").write_text(
            "[Unit]\nAfter=microduck-setup.service\n", encoding="utf-8")
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        text = result.stdout + result.stderr
        self.assertIn("keep.service", text)
        self.assertIn("microduck-setup.service", text)
        self.assertIn("referenciam nomes de arquivos removidos", text)


class test_dev_authorized_key(ApplyTestBase):
    KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest microduck-accept@test"

    def test_key_written_only_when_asked(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay(),
                    env_extra={"DEV_AUTHORIZED_KEY": self.KEY})
        keys = root / "home/radxa/.ssh/authorized_keys"
        self.assertEqual(keys.read_text(encoding="utf-8"), self.KEY + "\n")
        if not IS_WINDOWS:
            self.assertEqual(stat.S_IMODE(keys.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(keys.parent.stat().st_mode), 0o700)
            if os.geteuid() == 0:
                self.assertEqual((keys.stat().st_uid, keys.stat().st_gid), (1000, 1000))
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        self.assertIn("Cartão de validação: radxa inclui uma chave pública SSH de desenvolvimento (microduck-accept@test)", manifest)

    def test_no_key_by_default(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        self.run_ok(root, payload, self.fx.make_studio(), self.fx.make_overlay())
        self.assertFalse((root / "home/radxa/.ssh/authorized_keys").exists())
        manifest = (root / "usr/share/doc/microduck/镜像清单.txt").read_text(encoding="utf-8")
        self.assertNotIn("chave pública SSH de desenvolvimento", manifest)

    def test_not_a_key_fails(self):
        payload = self.fx.make_payload()
        root = self.fx.make_rootfs()
        result = self.run_fail(root, payload, self.fx.make_studio(), self.fx.make_overlay(),
                               env_extra={"DEV_AUTHORIZED_KEY": "hello"})
        self.assertIn("não parece conter uma chave pública SSH em uma linha", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
