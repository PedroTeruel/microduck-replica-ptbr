"""Dois comandos SSH do helper root: ssh-status (somente leitura) e ssh-password (ativa ou desativa o login por senha).

Tarefa de 21/10: a imagem pública aceita chaves e não inclui chaves de usuário; o Studio permite definir uma senha própria na página Mais para corrigir problemas via SSH sem regravar o cartão.
Verifique que a senha só passa pelo stdin de chpasswd, nunca por argumentos, logs ou arquivos de resultado; em caso de configuração inválida ou se sshd -T não confirmar a ativação, remova o arquivo de configuração.

    py -3.13 -I -m unittest tests.test_helper_ssh
"""
import json
import shutil
import tempfile
import unittest

from tests.test_helper_bus import H, FakeCtx, World

PW = "duck-secret-42"


class SshWorld(World):
    """Adiciona chpasswd, sshd e o serviço SSH ao ambiente World."""

    def __init__(self, root):
        super().__init__(root)
        self.chpasswd_rc = 0
        self.sshd_t_rc = 0
        self.effective = None          # None consulta o arquivo de configuração; True/False força a resposta de sshd -T.
        self.reload_rc = 0
        self.ssh_unit = "active"
        self.inputs = []

    def run(self, argv):
        name, args = argv[0], argv[1:]
        if name == "chpasswd":
            self.calls.append(list(argv))
            return self.chpasswd_rc, "", "chpasswd: (user radxa) pam_chauthtok() failed" if self.chpasswd_rc else ""
        if name == "sshd":
            self.calls.append(list(argv))
            if args == ["-t"]:
                return self.sshd_t_rc, "", "/etc/ssh/sshd_config.d/05: line 3: Bad configuration option" if self.sshd_t_rc else ""
            if args == ["-T"]:
                on = self.path(H.SSH_PASSWORD_CONF).is_file() if self.effective is None else self.effective
                return 0, f"port 22\npermitrootlogin no\npasswordauthentication {'yes' if on else 'no'}\n", ""
            raise AssertionError(argv)
        if name == "systemctl" and args[:1] == ["reload-or-restart"]:
            self.calls.append(list(argv))
            return self.reload_rc, "", "Job for ssh.service failed" if self.reload_rc else ""
        if name == "systemctl" and args == ["is-active", "ssh"]:
            self.calls.append(list(argv))
            return 0, self.ssh_unit + "\n", ""
        return super().run(argv)


class SshCtx(FakeCtx):
    def run(self, argv, input=None, timeout=15.0):
        self.w.inputs.append((list(argv), input))
        return super().run(argv, input, timeout)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helper-ssh-")
        self.w = SshWorld(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, verb, args):
        ctx = SshCtx(self.w, json.dumps(args).encode())
        code = H.run(["microduck-helper", verb], ctx)
        lines = [json.loads(x) for x in ctx.stdout.buf.getvalue().decode("utf-8").splitlines() if x.strip()]
        return code, lines

    def conf(self):
        return self.w.path(H.SSH_PASSWORD_CONF)

    def everything_written(self, lines):
        """Combina stdout, last-result, oplog, chamadas do logger e argumentos para verificar se a senha vazou."""
        parts = [json.dumps(lines, ensure_ascii=False), json.dumps(self.w.calls, ensure_ascii=False)]
        for rel in (H.LAST, H.OPLOG):
            p = self.w.path(rel)
            if p.exists():
                parts.append(p.read_text(encoding="utf-8"))
        return "\n".join(parts)


class StatusTest(Base):
    def test_reports_off_and_counts_keys(self):
        keys = self.w.path(H.SSH_KEYS)
        keys.parent.mkdir(parents=True)
        keys.write_text("# 注释\nssh-ed25519 AAAA one\n\nssh-ed25519 BBBB two\n", encoding="utf-8")
        code, lines = self.call("ssh-status", {})
        self.assertEqual(code, H.EXIT_OK)
        d = lines[-1]["detail"]
        self.assertEqual((d["password_login"], d["ssh_active"], d["keys"], d["user"]), (False, True, 2, "radxa"))
        self.assertFalse(self.w.path(H.LAST).exists(), "A consulta somente leitura não deve sobrescrever last-result.")

    def test_unknown_key_refused(self):
        code, _ = self.call("ssh-status", {"by": "x", "password": "y"})
        self.assertEqual(code, H.EXIT_ARGS)


class PasswordOnTest(Base):
    def test_on_sets_password_via_stdin_writes_conf_and_reloads(self):
        code, lines = self.call("ssh-password", {"by": "computador 192.168.0.9", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_OK, lines[-1])
        self.assertEqual(lines[-1]["detail"]["result"], "ssh_password_on")
        chp = [i for a, i in self.w.inputs if a == ["chpasswd"]]
        self.assertEqual(chp, [f"radxa:{PW}\n".encode()])
        text = self.conf().read_text(encoding="utf-8")
        self.assertIn("PasswordAuthentication yes", text)
        self.assertTrue(H.SSH_PASSWORD_CONF.endswith("/05-microduck-ssh-password.conf"))   # Deve vir antes de 10-microduck.conf.
        order = [c[:2] for c in self.w.calls if c[0] in ("chpasswd", "sshd", "systemctl") and c[1:2] != ["is-active"]]
        self.assertEqual(order, [["chpasswd"], ["sshd", "-t"], ["sshd", "-T"], ["systemctl", "reload-or-restart"]])
        self.assertNotIn(PW, self.everything_written(lines))

    def test_password_rules(self):
        for bad in ("short7!", "x" * 65, "microduck", "MicroDuck", "12345678", "duck\npass99", 12345678, None):
            code, lines = self.call("ssh-password", {"by": "t", "on": True, "password": bad})
            self.assertEqual(code, H.EXIT_ARGS, bad)
            self.assertFalse(self.conf().exists())
        self.assertEqual([a for a, _ in self.w.inputs if a == ["chpasswd"]], [])

    def test_sshd_t_failure_rolls_back(self):
        self.w.sshd_t_rc = 1
        code, lines = self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(lines[-1]["detail"]["result"], "sshd_config_bad")
        self.assertFalse(self.conf().exists())
        self.assertEqual([c for c in self.w.calls if c[:2] == ["systemctl", "reload-or-restart"]], [])

    def test_not_effective_rolls_back(self):
        self.w.effective = False          # Por exemplo, PasswordAuthentication no está antes do Include na configuração principal.
        code, lines = self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(lines[-1]["detail"]["result"], "not_effective")
        self.assertFalse(self.conf().exists())

    def test_reload_failure_rolls_back(self):
        self.w.reload_rc = 1
        code, lines = self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertFalse(self.conf().exists())

    def test_chpasswd_failure_writes_nothing(self):
        self.w.chpasswd_rc = 1
        code, lines = self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_FAIL)
        self.assertEqual(lines[-1]["detail"]["result"], "chpasswd_failed")
        self.assertFalse(self.conf().exists())
        self.assertNotIn(PW, self.everything_written(lines))

    def test_busy_when_locked(self):
        self.w.locks.add(H.SSH_LOCK)
        code, _ = self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertEqual(code, H.EXIT_BUSY)


class PasswordOffTest(Base):
    def test_off_removes_conf_and_reloads(self):
        self.call("ssh-password", {"by": "t", "on": True, "password": PW})
        self.assertTrue(self.conf().exists())
        code, lines = self.call("ssh-password", {"by": "t", "on": False})
        self.assertEqual(code, H.EXIT_OK)
        self.assertEqual(lines[-1]["detail"]["result"], "ssh_password_off")
        self.assertFalse(self.conf().exists())
        self.assertEqual(len([c for c in self.w.calls if c[:2] == ["systemctl", "reload-or-restart"]]), 2)

    def test_off_when_already_off(self):
        code, lines = self.call("ssh-password", {"by": "t", "on": False})
        self.assertEqual(code, H.EXIT_OK)
        self.assertIn("本来就是关着的", lines[-1]["msg"])

    def test_off_with_password_refused(self):
        code, _ = self.call("ssh-password", {"by": "t", "on": False, "password": PW})
        self.assertEqual(code, H.EXIT_ARGS)

    def test_on_must_be_bool_and_by_required(self):
        self.assertEqual(self.call("ssh-password", {"by": "t", "on": "yes", "password": PW})[0], H.EXIT_ARGS)
        self.assertEqual(self.call("ssh-password", {"on": True, "password": PW})[0], H.EXIT_ARGS)


if __name__ == "__main__":
    unittest.main()
