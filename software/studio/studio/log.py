"""Logs do Studio: categorias, níveis e gravação em arquivo; erros incluem a etapa em que ocorreram para facilitar o diagnóstico.

Cada registro vai para três destinos:
- Arquivo `logs/studio-data.log`: uma linha por registro, horário com milissegundos e fuso; erros incluem traceback e contexto.
  Esse arquivo reúne as evidências do problema. Comece por ele ao exportar um pacote de diagnóstico, compartilhar registros ou pedir análise.
- Memória: os 500 registros mais recentes, enviados ao abrir a página e depois em tempo real.
- Saída padrão: o systemd encaminha para o journal (`journalctl -u microduck-studio`).

Exemplo de registro de erro:
    log.error("Falha ao ficar em pé", cat="robotd", step="robot.init",
              raw="bus not ready: waiting_for_bus", hint="O programa principal ainda está iniciando; aguarde 10 s",
              ctx={"mode": "motion", "phase": "waiting_for_bus"})
No arquivo, a linha informa a etapa, o erro original, a sugestão e o contexto. Na página, aparece a mensagem resumida; expandir mostra os detalhes.

O log registra solicitação, resposta e duração de cada comando; em caso de erro, inclui o estado e o log do sistema robotd. Senhas e outros segredos são ocultados; horários têm precisão de milissegundos.
Uma conexão TOF que oscila repetidamente pode gerar mais de 8.700 linhas e ocultar os registros úteis; por isso, ocorrências iguais são registradas uma vez por minuto, com as repetições agrupadas.

Para preservar o cartão SD, mantém somente os últimos 14 dias e no máximo 50 MB. Registros de depuração não são gravados por padrão; a escrita em arquivo ocorre em uma thread em segundo plano e não bloqueia o loop de eventos.
"""
import asyncio
import json
import os
import queue
import re
import threading
import time
import traceback
from collections import deque
from pathlib import Path

CATS = ["Sistema", "Conexão", "Rede", "robotd", "Comando", "Segurança", "Barramento", "Calibração", "IMU", "Controle", "Página", "Bateria", "Ajuste", "Sensores", "Modelos"]
LEVELS = ["debug", "info", "warn", "error"]
_TAG = {"debug": "[Depuração]", "info": "", "warn": "[Aviso]", "error": "[Erro]"}

KEEP_DAYS = 14
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024    # Acima deste limite por dia, grava somente avisos e erros.
MAX_SECRETS = 64
RING = 500
DEDUP_WINDOW_S = 60
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
# Oculta valores associados a estas chaves (inclui a senha de Wi-Fi psk).
SECRET_KEYS = frozenset({"psk", "password", "passwd", "secret", "token", "authorization"})


def redact(value):
    """Substitui por [oculto] os valores de chaves sensíveis, inclusive em dicionários e listas aninhados."""
    if isinstance(value, dict):
        return {k: ("[oculto]" if isinstance(k, str) and k.lower() in SECRET_KEYS else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def _stamp(ts):
    """2026-10-18T09:41:07.123+08:00"""
    lt = time.localtime(ts)
    off = time.strftime("%z", lt)
    return time.strftime("%Y-%m-%dT%H:%M:%S", lt) + f".{int(ts * 1000) % 1000:03d}" + (off[:3] + ":" + off[3:] if off else "")


class Log:
    def __init__(self, directory, prefix="studio", echo=True, background=True):
        self.dir = Path(directory)
        self.prefix = prefix
        self.echo = echo
        self.debug_to_file = False
        self._lock = threading.Lock()
        self._ring = deque(maxlen=RING)
        self._n = 0
        self._day = None
        self._day_bytes = 0
        self._capped = False
        self._listeners = set()      # (loop, queue): assinaturas WebSocket da página.
        self._secrets = set()
        self._seen = {}              # (cat, level, msg) -> [horário da primeira ocorrência, número de repetições].
        self.counts = {lv: 0 for lv in LEVELS}
        self.write_errors = 0        # Quantidade de falhas ao gravar logs (visível no pacote de diagnóstico).
        self._q = queue.SimpleQueue() if background else None
        if background:
            threading.Thread(target=self._writer, name="studio-log", daemon=True).start()

    # ---- Gravação ----

    def hide(self, value):
        """Oculta este valor em todos os registros futuros (por exemplo, senha ou token)."""
        if value and len(value) >= 4:
            with self._lock:
                if len(self._secrets) < MAX_SECRETS:
                    self._secrets.add(str(value))

    def write(self, msg, cat="Sistema", level="info", step=None, raw=None, hint=None, ctx=None,
              exc=False, dedup=True):
        """cat está em CATS; level está em LEVELS.
        step: etapa em que parou (nome da interface ou número da etapa); raw: erro original ou resposta; hint: sugestão;
        ctx: contexto (modo, postura, bateria etc., em um dicionário); exc=True inclui o traceback atual no arquivo;
        dedup=False: registra cada ocorrência (por exemplo, solicitação e resposta de um comando).

        **Nunca propaga exceções**: registra antes de enviar o comando de desativação do torque; falha no log não pode bloqueá-lo (revisão #1)."""
        try:
            return self._write(msg, cat, level, step, raw, hint, ctx, exc, dedup)
        except Exception:  # noqa: BLE001
            self.write_errors += 1
            return None

    def _write(self, msg, cat, level, step, raw, hint, ctx, exc, dedup):
        if level not in LEVELS:
            level = "info"
        now = time.time()
        msg, raw, hint, step = (self._clean(x) for x in (msg, raw, hint, step))
        tb = self._clean(traceback.format_exc()) if exc else ""
        ctx_text = self._clean(json.dumps(redact(ctx), ensure_ascii=False, default=str)) if ctx else None
        with self._lock:
            if dedup:
                key = (cat, level, msg)
                seen = self._seen.get(key)
                if seen and now - seen[0] < DEDUP_WINDOW_S:
                    seen[1] += 1
                    return None
                if seen and seen[1]:
                    self._emit_locked(now, cat, level, f"A mensagem anterior “{msg}” se repetiu {seen[1]} vezes em 1 minuto; ocorrências agrupadas.")
                self._seen[key] = [now, 0]
                if len(self._seen) > 2000:
                    self._seen = {k: v for k, v in self._seen.items() if now - v[0] < DEDUP_WINDOW_S}
            return self._emit_locked(now, cat, level, msg, step, raw, hint, ctx_text, tb)

    def _emit_locked(self, now, cat, level, msg, step=None, raw=None, hint=None, ctx=None, tb=""):
        parts = [f"{_stamp(now)} [{cat}]{_TAG[level]} {msg}"]
        if step:
            parts.append(f"Interrompido em: {step}" if level in ("warn", "error") else f"Etapa: {step}")
        if raw:
            parts.append(f"Texto original: {raw}")
        if hint:
            parts.append(f"Sugestão: {hint}")
        if ctx:
            parts.append(f"Contexto: {ctx}")
        line = " · ".join(parts)
        self.counts[level] += 1
        if level != "debug" or self.debug_to_file:
            self._to_file(now, line + "\n" + tb, level in ("warn", "error"))
        entry = None
        if level != "debug":
            self._n += 1
            entry = {"n": self._n, "ts": now, "t": time.strftime("%H:%M:%S", time.localtime(now)),
                     "cat": cat, "level": level, "msg": msg, "step": step, "raw": raw, "hint": hint, "ctx": ctx}
            self._ring.append(entry)
            for loop, q in list(self._listeners):
                try:
                    loop.call_soon_threadsafe(_offer, q, entry)
                except RuntimeError:      # O loop de eventos já foi encerrado.
                    pass
        if self.echo:
            try:
                # Se não for possível escrever na saída padrão (terminal SSH fechado ou journald travado), descarta esta cópia; o arquivo e a página continuam disponíveis.
                print(line + ("\n" + tb.rstrip() if tb else ""), flush=True)
            except Exception:  # noqa: BLE001
                self.write_errors += 1
        return entry

    def debug(self, msg, **kw):
        return self.write(msg, level="debug", **kw)

    def info(self, msg, **kw):
        return self.write(msg, level="info", **kw)

    def warn(self, msg, **kw):
        return self.write(msg, level="warn", **kw)

    def error(self, msg, **kw):
        return self.write(msg, level="error", **kw)

    # ---- Leitura ----

    def recent(self, limit=200, cats=None, min_level="info"):
        floor = LEVELS.index(min_level) if min_level in LEVELS else 1
        with self._lock:
            items = [e for e in self._ring
                     if LEVELS.index(e["level"]) >= floor and (not cats or e["cat"] in cats)]
        return items[-limit:]

    def subscribe(self, loop=None, maxsize=200):
        """Logs em tempo real da página: retorna um asyncio.Queue; quando estiver cheio, descarta o item mais antigo para não atrasar quem grava."""
        loop = loop or asyncio.get_running_loop()
        q = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._listeners.add((loop, q))
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._listeners = {(lp, qq) for lp, qq in self._listeners if qq is not q}

    def files(self, days=2):
        """Para o pacote de diagnóstico: arquivos dos últimos days dias, do mais antigo ao mais recente."""
        self.flush()
        if not self.dir.is_dir():
            return []
        return sorted(self.dir.glob(f"{self.prefix}-*.log"))[-days:]

    def snapshot(self):
        with self._lock:
            return {"counts": dict(self.counts), "last_n": self._n, "dir": str(self.dir),
                    "write_errors": self.write_errors}

    def flush(self, timeout=2.0):
        """Aguarda a thread em segundo plano gravar as linhas pendentes (antes de exportar um pacote de diagnóstico ou sair)."""
        if self._q is None:
            return
        done = threading.Event()
        self._q.put(done)
        done.wait(timeout)

    # ---- Arquivos ----

    def _clean(self, text):
        if text is None:
            return None
        text = _ANSI.sub("", str(text))
        for s in self._secrets:
            text = text.replace(s, "[oculto]")
        return text

    def _to_file(self, now, text, important=False):
        if self._q is not None:
            self._q.put((now, text, important))
        else:
            self._append(now, text, important)

    def _writer(self):
        while True:
            item = self._q.get()
            if isinstance(item, threading.Event):
                item.set()
                continue
            self._append(*item)

    def _append(self, now, text, important=False):
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{self.prefix}-{day}.log"
            if day != self._day:
                self._day = day
                self._prune()
                self._day_bytes = _size(path)
                self._capped = False
            if self._day_bytes > MAX_FILE_BYTES:
                # Proteção contra excesso de registros: após 20 MB no dia, não grava linhas comuns no arquivo (continuam na página); avisos e erros ainda são gravados.
                if not important:
                    if not self._capped:
                        self._capped = True
                        text = f"Os logs de hoje ultrapassaram {MAX_FILE_BYTES >> 20} MB; somente avisos e erros serão gravados a partir de agora.\n"
                    else:
                        return
                elif self._day_bytes > MAX_FILE_BYTES * 2:
                    return
            data = text.encode("utf-8")
            with open(path, "ab") as f:
                f.write(data)
            self._day_bytes += len(data)
        except OSError:
            # Falha ao gravar o arquivo (cartão cheio ou somente leitura) não deve afetar o chamador; a saída padrão continua disponível.
            pass

    def _prune(self):
        """Mantém os últimos KEEP_DAYS dias; se o total ultrapassar MAX_TOTAL_BYTES, exclui os arquivos mais antigos (preserva o arquivo de hoje)."""
        logs = sorted(self.dir.glob(f"{self.prefix}-*.log"))
        today = self.dir / f"{self.prefix}-{self._day}.log"
        old = [p for p in logs if p != today]
        excess = len(old) - (KEEP_DAYS - 1)
        for p in old[:max(excess, 0)]:
            _unlink(p)
        logs = sorted(self.dir.glob(f"{self.prefix}-*.log"))
        total = sum(_size(p) for p in logs)
        for p in logs:
            if total <= MAX_TOTAL_BYTES:
                break
            if p == today:      # Se o relógio estiver em 1970, o arquivo de hoje pode vir primeiro; ignore-o e continue excluindo os seguintes.
                continue
            total -= _size(p)
            _unlink(p)


def _offer(q, entry):
    if q.full():
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(entry)


def _size(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _unlink(p):
    try:
        p.unlink()
    except OSError:
        pass


class Timer:
    """Registra o ciclo de um comando:
        with log_cmd(log, "Ficar em pé", "robot.init", ctx=...) as t:
            reply = await ...
            t.ok(reply)        # ou t.fail("motivo", raw=..., hint=...)
    Solicitação, resposta e duração são registradas em linhas separadas, sem agrupamento; falhas incluem o contexto."""

    def __init__(self, log, what, step, who=None, args=None, ctx=None):
        self.log, self.what, self.step, self.ctx = log, what, step, ctx
        self.t0 = time.monotonic()
        self.done = False
        detail = f"({who})" if who else ""
        self.log.write(f"→ {what}{detail}", cat="Comando", step=step,
                       raw=json.dumps(redact(args), ensure_ascii=False) if args else None, dedup=False)

    def ms(self):
        return int((time.monotonic() - self.t0) * 1000)

    def ok(self, reply=None, note=""):
        self.done = True
        self.log.write(f"← {self.what} concluído · {self.ms()} ms{(' · ' + note) if note else ''}", cat="Comando",
                       step=self.step, raw=_brief(reply), dedup=False)

    def fail(self, why, raw=None, hint=None, ctx=None):
        self.done = True
        self.log.write(f"← {self.what} falhou: {why} · {self.ms()} ms", cat="Comando", level="error",
                       step=self.step, raw=_brief(raw), hint=hint, ctx=ctx or self.ctx, dedup=False)

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is not None and not self.done:
            self.fail(f"{et.__name__}: {ev}")
        elif not self.done:
            self.ok()
        return False


def _brief(x, limit=600):
    if x is None:
        return None
    s = x if isinstance(x, str) else json.dumps(redact(x), ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + f"… ({len(s)} caracteres no total)"


def log_cmd(log, what, step, **kw):
    return Timer(log, what, step, **kw)


def to_json(entry):
    return json.dumps(entry, ensure_ascii=False)


_default = None


def setup(directory, **kw):
    """Cria apenas uma instância por processo; os módulos usam `from studio.log import get; log = get()`."""
    global _default
    _default = Log(directory, **kw)
    return _default


def get():
    if _default is None:
        return setup(os.path.join(os.getcwd(), "logs"))
    return _default
