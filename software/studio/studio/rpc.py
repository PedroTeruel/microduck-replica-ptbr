"""Cliente JSON-RPC para robotd / configd.

Formato em produção (início de duck-ipc-proto/src/lib.rs): JSON-RPC 2.0, um objeto por linha (NDJSON).
    → {"jsonrpc":"2.0","id":1,"method":"robot.health","params":{}}
    ← {"jsonrpc":"2.0","id":1,"result":{...}}
Mensagens sem id são notificações (como robot.state em uma assinatura).

robotd processa **uma solicitação por conexão de cada vez**: lê uma linha e responde uma linha. Portanto:
- uma instância de Conn aguarda apenas uma resposta por vez (as solicitações são enfileiradas por um lock);
- ao expirar, a conexão é encerrada e reaberta na próxima chamada. Se permanecer aberta, a solicitação expirada bloqueia as seguintes e uma resposta atrasada pode ser associada incorretamente;
- a desativação do torque usa uma conexão exclusiva (veja robotd.py), sem aguardar solicitações lentas.

O endereço é sempre uma string; o restante do código não precisa saber o tipo de conexão:
    unix:/run/robotd.sock      no robô
    tcp:127.0.0.1:17001        no computador (Python no Windows não oferece AF_UNIX), conectado ao robotd falso

“Programa principal indisponível” e “resposta atrasada” são situações distintas: socket ausente ou conexão recusada resulta em Unreachable;
se conectou, mas não respondeu a tempo, resulta em Timeout. A interface exibe “Programa principal indisponível” ou “Programa principal não respondeu”.
"""
import asyncio
import itertools
import json
import os

LINE_LIMIT = 1 << 20      # busStatus medido em 16,9 KB; o limite padrão de 64 KiB seria insuficiente, então aumenta para 1 MiB.


class RpcError(Exception):
    """O servidor retornou um erro. Os códigos estão em error_code de lib.rs (por exemplo, -32602 para parâmetros inválidos e 1 para ocupado)."""

    def __init__(self, method, code, message, data=None):
        super().__init__(f"{method}：{message}（code {code}）")
        self.method, self.code, self.message, self.data = method, code, message, data


class Unreachable(Exception):
    """Não foi possível conectar: socket ausente, conexão recusada ou encerrada pelo servidor."""


class Timeout(Exception):
    """Conectou, mas não respondeu dentro do prazo."""


def parse_addr(addr):
    if addr.startswith("unix:"):
        return ("unix", addr[5:])
    if addr.startswith("tcp:"):
        host, _, port = addr[4:].rpartition(":")
        return ("tcp", host or "127.0.0.1", int(port))
    raise ValueError(f"Use unix:/caminho ou tcp:host:porta; recebido: {addr!r}")


async def open_conn(addr):
    kind, *rest = parse_addr(addr)
    try:
        if kind == "unix":
            path = rest[0]
            if not hasattr(asyncio, "open_unix_connection"):
                raise Unreachable("O Python deste computador não oferece socket Unix; use um endereço tcp:")
            if not os.path.exists(path):
                raise Unreachable(f"{path} não existe (o programa principal não está em execução)")
            return await asyncio.open_unix_connection(path, limit=LINE_LIMIT)
        host, port = rest
        return await asyncio.open_connection(host, port, limit=LINE_LIMIT)
    except Unreachable:
        raise
    except (ConnectionRefusedError, FileNotFoundError) as e:
        raise Unreachable(f"Não foi possível conectar a {addr}: conexão recusada") from e
    except OSError as e:
        raise Unreachable(f"Não foi possível conectar a {addr}: {type(e).__name__}: {e}") from e


def encode(rid, method, params):
    return (json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}},
                       ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


async def read_message(reader, timeout):
    """Lê uma linha e decodifica o JSON. Linha longa demais ou conexão encerrada resulta em Unreachable; dados inválidos retornam None para o chamador ignorar."""
    try:
        raw = await asyncio.wait_for(reader.readline(), timeout)
    except asyncio.TimeoutError:
        raise
    except (ValueError, asyncio.LimitOverrunError) as e:      # A linha ultrapassou LINE_LIMIT.
        raise Unreachable(f"O servidor enviou uma linha grande demais (mais de {LINE_LIMIT} bytes)") from e
    except (ConnectionError, OSError, asyncio.IncompleteReadError) as e:
        raise Unreachable(f"Conexão encerrada: {type(e).__name__}: {e}") from e
    if not raw:
        raise Unreachable("O servidor encerrou a conexão")
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None      # Valores como [1,2,3] ou "x" também são ignorados como dados inválidos.


class Conn:
    """Conexão serial. call() enfileira as solicitações; timeout ou desconexão encerra a conexão, que será reaberta na chamada seguinte."""

    def __init__(self, addr, name="rpc", log=None):
        self.addr, self.name, self.log = addr, name, log
        self._r = self._w = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self.connected = False
        self.reconnects = 0
        self.bad_lines = 0

    @property
    def busy(self):
        return self._lock.locked()

    async def call(self, method, params=None, timeout=2.0):
        """O timeout inclui o estabelecimento da conexão (robotd pode ficar travado durante a conexão)."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            if self._w is None:
                try:
                    await asyncio.wait_for(self._connect(), timeout)
                except asyncio.TimeoutError:
                    self._close()
                    raise Timeout(f"{method}: não conectou em {timeout:g} s") from None
            rid = next(self._ids)
            try:
                self._w.write(encode(rid, method, params))
                await self._w.drain()
                while True:
                    left = deadline - loop.time()
                    if left <= 0:
                        raise asyncio.TimeoutError
                    msg = await read_message(self._r, left)
                    if msg is None:
                        self.bad_lines += 1
                        continue
                    if msg.get("id") == rid:
                        break
                    # Notificação ou resposta atrasada de uma chamada anterior expirada: descarta.
            except asyncio.TimeoutError:
                self._close()
                raise Timeout(f"{method} não respondeu em {timeout:g} s") from None
            except Unreachable:
                self._close()
                raise
            except (ConnectionError, OSError) as e:
                self._close()
                raise Unreachable(f"Conexão encerrada: {type(e).__name__}: {e}") from e
            except asyncio.CancelledError:
                # Se o chamador for cancelado, a solicitação pode já ter sido enviada; robotd ainda a processará em ordem e retornará uma resposta atrasada.
                # Encerra a conexão para que outras solicitações não fiquem atrás dela nem recebam sua resposta atrasada.
                self._close()
                raise
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            raise RpcError(method, err.get("code"), err.get("message", ""), err.get("data"))
        return msg.get("result")

    async def _connect(self):
        self._r, self._w = await open_conn(self.addr)
        if self.connected is False and self.reconnects:
            # Mantém a mensagem estável e inclui o contador em raw: reconexões repetidas em um minuto são agrupadas para evitar excesso de logs.
            self._note("info", f"Conexão {self.name} com o programa principal restabelecida", raw=f"Reconexão nº {self.reconnects}")
        self.connected = True

    def _close(self):
        if self._w is not None:
            try:
                self._w.close()
            except Exception:  # noqa: BLE001 — erros ao encerrar a conexão não são relevantes.
                pass
        self._r = self._w = None
        if self.connected:
            self.reconnects += 1
        self.connected = False

    def close(self):
        self._close()

    def _note(self, level, msg, raw=None):
        if self.log:
            self.log.write(msg, cat="robotd", level=level, raw=raw)


async def call_once(addr, method, params=None, timeout=2.0, name="once", log=None):
    """Abre uma conexão, envia uma solicitação e fecha. A desativação do torque usa esta função para evitar uma conexão antiga que morreu após reiniciar robotd.
    No mesmo computador, um socket local conecta em menos de 1 ms."""
    c = Conn(addr, name, log)
    try:
        return await c.call(method, params, timeout)
    finally:
        c.close()
