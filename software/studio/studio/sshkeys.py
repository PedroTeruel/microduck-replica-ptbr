"""Chaves do cartão SSH na página “Mais”: cadastra, lista e remove chaves públicas SSH do usuário radxa.

Pedido do usuário em 10-21: quem usa chaves pode colar a chave pública do próprio computador e acessar por SSH sem habilitar login por senha.
O Studio já roda como radxa e ~/.ssh/authorized_keys pertence a esse usuário, portanto não precisa do assistente root.

Aceita uma linha completa (tipo + base64 + comentário opcional), sem opções como command= ou from= no início. O conteúdo colado na página
é salvo no formato comum. A impressão digital segue o SHA256 de `ssh-keygen -l` e permite identificar e remover a chave correta.
"""
import base64
import binascii
import hashlib
import os
import struct

KEY_TYPES = ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
             "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com")
MAX_LINE = 16384
MAX_COMMENT = 200


class BadKey(ValueError):
    """A chave pública colada é inválida. A mensagem é exibida diretamente na página."""


def fingerprint(blob):
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode("ascii").rstrip("=")


def parse(line):
    """Converte uma linha de chave pública em {"type", "b64", "comment", "fp"}. Se for inválida, gera BadKey com uma mensagem legível."""
    if not isinstance(line, str):
        raise BadKey("Cole uma linha de texto com a chave pública")
    text = line.strip()
    if not text:
        raise BadKey("Nenhum conteúdo foi colado")
    if "\n" in text or "\r" in text:
        raise BadKey("Cole apenas uma linha: cada chave pública ocupa uma linha inteira (ssh-ed25519 AAAA… comentário)")
    if len(text) > MAX_LINE:
        raise BadKey("O conteúdo é longo demais para uma chave pública")
    parts = text.split(None, 2)
    kind = parts[0]
    if kind not in KEY_TYPES:
        if "PRIVATE KEY" in text:
            raise BadKey("Isto é uma chave privada! Nunca a compartilhe; cole o conteúdo do arquivo terminado em .pub")
        raise BadKey("A linha deve começar com um tipo de chave pública, como ssh-ed25519, ssh-rsa ou ecdsa-sha2-… (cole o conteúdo do arquivo .pub, sem opções no início)")
    if len(parts) < 2:
        raise BadKey("A linha contém apenas o tipo, sem a chave; cole a linha inteira")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        raise BadKey("O trecho da chave não é um base64 válido; talvez não tenha sido copiado por completo") from None
    if len(blob) < 4:
        raise BadKey("O trecho da chave é curto demais; talvez não tenha sido copiado por completo")
    (n,) = struct.unpack(">I", blob[:4])
    if blob[4:4 + n] != kind.encode("ascii"):
        raise BadKey("O conteúdo da chave não corresponde ao tipo indicado no início; talvez não tenha sido copiado por completo")
    comment = parts[2].strip() if len(parts) > 2 else ""
    comment = "".join(c for c in comment if ord(c) >= 32 and ord(c) != 127)[:MAX_COMMENT]
    return {"type": kind, "b64": parts[1], "comment": comment, "fp": fingerprint(blob)}


def _key_in_line(line):
    """Converte uma linha de authorized_keys (que pode conter opções) na chave correspondente; retorna None para comentários ou linhas inválidas."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    tokens = text.split()
    for i, t in enumerate(tokens):
        if t in KEY_TYPES and i + 1 < len(tokens):
            try:
                k = parse(" ".join(tokens[i:]))
            except BadKey:
                return None
            k["options"] = i > 0
            return k
    return None


class SshKeys:
    def __init__(self, home=None):
        self.home = home or os.path.expanduser("~")

    @property
    def dir(self):
        return os.path.join(self.home, ".ssh")

    @property
    def path(self):
        return os.path.join(self.dir, "authorized_keys")

    def _read(self):
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def list(self):
        out = []
        for line in self._read().splitlines():
            k = _key_in_line(line)
            if k is not None:
                out.append({"type": k["type"], "comment": k["comment"], "fp": k["fp"], "options": k["options"]})
        return out

    def _write(self, text):
        if os.path.islink(self.dir):
            raise BadKey("~/.ssh é um link simbólico; gravação recusada")
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)
        if os.path.islink(self.path):
            raise BadKey("authorized_keys é um link simbólico; alteração recusada")
        tmp = os.path.join(self.dir, f".authorized_keys.studio.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def add(self, line):
        """Retorna (se foi adicionada, chave). Não grava duplicatas; retorna False se a chave já existir."""
        k = parse(line)
        if any(x["fp"] == k["fp"] for x in self.list()):
            return False, k
        text = self._read()
        if text and not text.endswith("\n"):
            text += "\n"
        text += " ".join(p for p in (k["type"], k["b64"], k["comment"]) if p) + "\n"
        self._write(text)
        return True, k

    def remove(self, fp):
        """Remove pela impressão digital (apaga todas as linhas que contenham a mesma chave). Retorna a quantidade de linhas removidas."""
        if not isinstance(fp, str) or not fp.startswith("SHA256:"):
            raise BadKey("Impressão digital inválida")
        kept, gone = [], 0
        for line in self._read().splitlines(keepends=True):
            k = _key_in_line(line)
            if k is not None and k["fp"] == fp:
                gone += 1
                continue
            kept.append(line)
        if gone:
            self._write("".join(kept))
        return gone
