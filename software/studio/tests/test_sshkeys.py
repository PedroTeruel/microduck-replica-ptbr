"""Chaves SSH do cartão “Mais” (studio/sshkeys.py): análise, impressão digital, cadastro, deduplicação e remoção.

    py -3.13 -I -m unittest tests.test_sshkeys (ou use run_tests.py do repositório)
"""
import base64
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from studio import sshkeys as K  # noqa: E402


def make_key(kind="ssh-ed25519", body=b"\x01" * 32, comment="me@pc"):
    blob = struct.pack(">I", len(kind)) + kind.encode() + struct.pack(">I", len(body)) + body
    b64 = base64.b64encode(blob).decode()
    return f"{kind} {b64} {comment}".strip(), K.fingerprint(blob)


class ParseTest(unittest.TestCase):
    def test_good_key(self):
        line, fp = make_key()
        k = K.parse("  " + line + "\n")
        self.assertEqual((k["type"], k["comment"], k["fp"]), ("ssh-ed25519", "me@pc", fp))
        self.assertTrue(fp.startswith("SHA256:") and not fp.endswith("="))

    def test_comment_optional_and_control_chars_dropped(self):
        line, _ = make_key(comment="")
        self.assertEqual(K.parse(line)["comment"], "")
        line, _ = make_key(comment="a\tb")
        self.assertEqual(K.parse(line)["comment"], "ab")

    def test_rejects(self):
        good, _ = make_key()
        kind, b64, _c = good.split(" ", 2)
        cases = {
            "": "Nenhum conteúdo",
            good + "\n" + good: "apenas uma linha",
            "-----BEGIN OPENSSH PRIVATE KEY-----": "chave privada",
            'command="x" ' + good: "opções no início",
            kind: "apenas o tipo",
            f"{kind} not-base64!!": "base64",
            f"ssh-rsa {b64}": "não corresponde",
        }
        for text, why in cases.items():
            with self.assertRaises(K.BadKey, msg=text) as cm:
                K.parse(text)
            self.assertIn(why, str(cm.exception), text)


class FileTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="sshkeys-")
        self.keys = K.SshKeys(self.home)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def test_add_list_dedupe_remove(self):
        a, fa = make_key(comment="laptop")
        b, fb = make_key(body=b"\x02" * 32, comment="desk")
        self.assertEqual(self.keys.list(), [])
        self.assertEqual(self.keys.add(a)[0], True)
        self.assertEqual(self.keys.add(a)[0], False)             # Não grava a mesma chave duas vezes
        self.assertEqual(self.keys.add(b)[0], True)
        self.assertEqual([k["fp"] for k in self.keys.list()], [fa, fb])
        self.assertEqual(self.keys.remove(fa), 1)
        self.assertEqual([k["fp"] for k in self.keys.list()], [fb])
        self.assertEqual(self.keys.remove(fa), 0)
        with self.assertRaises(K.BadKey):
            self.keys.remove("nope")

    def test_keeps_existing_lines_and_reads_option_lines(self):
        a, fa = make_key(comment="old")
        os.makedirs(os.path.join(self.home, ".ssh"))
        with open(self.keys.path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# comentário manual\nfrom=\"10.0.0.1\" " + a)  # A última linha não termina com quebra de linha
        b, fb = make_key(body=b"\x03" * 32, comment="new")
        self.keys.add(b)
        text = open(self.keys.path, encoding="utf-8").read()
        self.assertTrue(text.startswith("# comentário manual\nfrom=\"10.0.0.1\" "))
        self.assertTrue(text.endswith(b + "\n"))
        listed = self.keys.list()
        self.assertEqual([(k["fp"], k["options"]) for k in listed], [(fa, True), (fb, False)])
        self.keys.remove(fa)
        self.assertEqual(open(self.keys.path, encoding="utf-8").read(), "# comentário manual\n" + b + "\n")

    @unittest.skipUnless(os.name == "posix", "Permissões são verificadas apenas no Linux")
    def test_permissions(self):
        a, _ = make_key()
        self.keys.add(a)
        self.assertEqual(os.stat(self.keys.dir).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(self.keys.path).st_mode & 0o777, 0o600)

    @unittest.skipUnless(os.name == "posix", "Links simbólicos são verificados apenas no Linux")
    def test_refuses_symlinked_ssh_dir(self):
        target = tempfile.mkdtemp(prefix="sshkeys-target-")
        self.addCleanup(shutil.rmtree, target, True)
        os.symlink(target, os.path.join(self.home, ".ssh"))
        a, _ = make_key()
        with self.assertRaises(K.BadKey):
            self.keys.add(a)


if __name__ == "__main__":
    unittest.main()
