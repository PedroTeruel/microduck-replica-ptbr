"""Read-only camera service health/configuration and short-lived ToF subscriptions.

Neither configuration nor mediad's hello proves that a camera is present. The
browser verifies video separately. Neither read uses a robotd control connection.
"""
import asyncio
import json
from pathlib import Path
import time
import tomllib

from .rpc import encode, parse_addr

TOF_TIMEOUT_S = 1.0
TOF_LINE_LIMIT = 64 * 1024
CAMERA_TIMEOUT_S = 0.8
CAMERA_LINE_LIMIT = 64 * 1024


def _view(state, connected=False, sensor=None, reason=None, hz=None):
    return {"state": state, "connected": connected, "sensor": sensor, "reason": reason,
            "rows": 8, "cols": 8, "hz": hz, "seq": None, "age_ms": None,
            "distance_mm": [], "status": [], "valid_count": 0,
            "nearest_mm": None, "farthest_mm": None, "zones": [], "simulated": sensor in ("sim", "fake")}


def _integer(value, low, high):
    return type(value) is int and low <= value <= high


def _geometry(data):
    return all(type(data.get(key)) is int and data[key] == 8 for key in ("rows", "cols"))


def _metadata(data):
    if not isinstance(data, dict) or data.get("accepted") is not True:
        raise ValueError("A assinatura ToF não foi aceita")
    if not _geometry(data) or not _integer(data.get("hz"), 1, 255):
        raise ValueError("O serviço ToF retornou dimensões ou frequência inválidas")
    for key, limit in (("sensor", 100), ("unavailable", 2048)):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not value or len(value) > limit):
            raise ValueError(f"O serviço ToF retornou um valor inválido para {key}")
    return data


def _frame_view(data, metadata):
    if not isinstance(data, dict) or not _geometry(data):
        raise ValueError("O quadro ToF deve ter tamanho 8×8")
    if not _integer(data.get("seq"), 0, 2**64 - 1):
        raise ValueError("O número de sequência do quadro ToF é inválido")
    for key in ("at_us", "t_ns"):
        if key in data and not _integer(data[key], 0, 2**64 - 1):
            raise ValueError("O horário do quadro ToF é inválido")
    distances, statuses = data.get("distance_mm"), data.get("status")
    for values, low, high in ((distances, -32768, 32767), (statuses, 0, 255)):
        if not isinstance(values, list) or len(values) != 64 or not all(_integer(v, low, high) for v in values):
            raise ValueError("O quadro ToF precisa conter 64 distâncias e estados inteiros dentro dos limites")
    received = time.monotonic()
    zones, valid = [], []
    for mm, status in zip(distances, statuses):
        kind = "no_target" if status == 255 else "unusable"
        if status in (5, 9) and mm > 0:
            kind = "range"
            valid.append(mm)
        zones.append({"kind": kind, "mm": mm if kind == "range" else None, "status": status})
    result = _view("ready", True, metadata.get("sensor"), hz=metadata["hz"])
    # at_us belongs to the daemon's lifetime; t_ns may come from a different
    # computer in development. A new subscription only receives future frames.
    result.update(seq=data["seq"], age_ms=max(0, int((time.monotonic() - received) * 1000)),
                  distance_mm=distances, status=statuses, zones=zones, valid_count=len(valid),
                  nearest_mm=min(valid) if valid else None, farthest_mm=max(valid) if valid else None)
    return result


def _reject_constant(value):
    raise ValueError(f"O JSON ToF contém um valor não finito: {value}")


async def _message(reader, service="ToF", line_limit=TOF_LINE_LIMIT):
    try:
        raw = await reader.readline()
    except (ValueError, asyncio.LimitOverrunError):
        raise ValueError(f"A mensagem do serviço {service} excede 64 KiB") from None
    if not raw:
        raise ConnectionError(f"A conexão com o serviço {service} foi encerrada")
    if len(raw) > line_limit:
        raise ValueError(f"A mensagem do serviço {service} excede 64 KiB")
    if not raw.endswith(b"\n"):
        raise ValueError(f"A mensagem do serviço {service} terminou incompleta")
    try:
        message = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError(f"O serviço {service} retornou um JSON inválido") from None
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ValueError(f"O serviço {service} retornou uma mensagem em formato inválido")
    return message


class Sensors:
    def __init__(self, log=None, root="/", tof_addr="unix:/run/tofd/tof.sock", camera_signaling_port=8443,
                 camera_addr="unix:/run/mediad/media.sock"):
        self.log = log
        self.root = Path(root)
        if tof_addr != "none":
            parse_addr(tof_addr)
        self.tof_addr = tof_addr
        self.camera_signaling_port = camera_signaling_port
        if camera_addr != "none":
            parse_addr(camera_addr)
        self.camera_addr = camera_addr
        self._tof_task = None
        self._tof_waiters = {}

    async def camera(self):
        result = await asyncio.to_thread(self._camera_config)
        state, reason = await self._camera_service()
        result.update(service_state=state, service_reason=reason)
        return result

    async def _camera_service(self):
        if self.camera_addr == "none":
            return "unknown", "A verificação do serviço de câmera não está configurada"
        writer = None
        try:
            # One fresh read-only hello; do not request a capture or start video.
            async with asyncio.timeout(CAMERA_TIMEOUT_S):
                kind, *address = parse_addr(self.camera_addr)
                if kind == "unix":
                    open_unix = getattr(asyncio, "open_unix_connection", None)
                    if not callable(open_unix):
                        return "unknown", "Este sistema não oferece suporte a socket Unix; em desenvolvimento, configure um endereço tcp:"
                    reader, writer = await open_unix(address[0], limit=CAMERA_LINE_LIMIT)
                else:
                    reader, writer = await asyncio.open_connection(*address, limit=CAMERA_LINE_LIMIT)
                writer.write(encode(1, "hello", {}))
                await writer.drain()
                response = await _message(reader, "câmera", CAMERA_LINE_LIMIT)
                if type(response.get("id")) is not int or response["id"] != 1 or "method" in response:
                    raise ValueError("O serviço de câmera respondeu ao hello em formato inválido")
                if "error" in response:
                    error = response["error"]
                    message = error.get("message") if isinstance(error, dict) else "falha no hello"
                    raise ValueError(f"O serviço de câmera recusou o hello: {str(message)[:2048]}")
                result = response.get("result")
                api_version = result.get("api_version") if isinstance(result, dict) else None
                if type(api_version) is not int or api_version <= 0:
                    raise ValueError("O hello do serviço de câmera não informou uma versão válida da API")
                return "online", None
        except NotImplementedError:
            return "unknown", "Este sistema não oferece suporte a socket Unix; em desenvolvimento, configure um endereço tcp:"
        except TimeoutError:
            return "offline", "O serviço de câmera não respondeu a tempo"
        except (ConnectionError, OSError):
            return "offline", "O serviço de câmera está offline ou a conexão foi encerrada"
        except ValueError as exc:
            return "offline", f"O serviço de câmera respondeu com dados inválidos: {exc}"
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.1)
                except (TimeoutError, ConnectionError, OSError):
                    writer.transport.abort()

    def _camera_config(self):
        result = {"source": "unknown", "source_label": "Origem desconhecida (aguardando confirmação do vídeo)",
                  "source_basis": "config", "source_verified": False,
                  "signaling_port": self.camera_signaling_port, "error": None}
        try:
            config = tomllib.loads((self.root / "etc/robot/robotd.toml").read_text(encoding="utf-8"))
        except FileNotFoundError:
            result["error"] = "A configuração da origem da câmera não foi encontrada; ainda é possível tentar conectar o vídeo"
            return result
        except (OSError, UnicodeError, ValueError):
            result["error"] = "Não foi possível ler a configuração da origem da câmera; ainda é possível tentar conectar o vídeo"
            return result
        media = config.get("media")
        if not isinstance(media, dict):
            result["error"] = "A origem da câmera não está configurada; aguardando confirmação dos metadados do vídeo"
            return result
        source = media.get("source")
        if source in ("camera", "test"):
            result["source"] = source
            result["source_label"] = ("Câmera (configurada, ainda não verificada)" if source == "camera"
                                      else "Vídeo de teste (configurado)")
        elif "camera" in media:
            result["error"] = "A configuração contém apenas o campo antigo media.camera, ignorado pela versão atual; aguardando confirmação dos metadados do vídeo"
        else:
            result["error"] = "A origem da câmera configurada é desconhecida; aguardando confirmação dos metadados do vídeo"
        return result

    async def tof(self):
        if self.tof_addr == "none":
            return _view("unavailable", reason="O serviço ToF não está configurado")
        task = self._tof_task
        if task is None or task.done():
            task = self._tof_task = asyncio.create_task(self._read_tof())
        self._tof_waiters[task] = self._tof_waiters.get(task, 0) + 1
        try:
            return await asyncio.shield(task)
        finally:
            self._tof_waiters[task] -= 1
            if not self._tof_waiters[task]:
                del self._tof_waiters[task]
                if not task.done():
                    # A new viewer must start its own read while this canceled
                    # connection is still finishing wait_closed().
                    if self._tof_task is task:
                        self._tof_task = None
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def _read_tof(self):
        writer = None
        connected = False
        metadata = None
        try:
            async with asyncio.timeout(TOF_TIMEOUT_S):
                kind, *address = parse_addr(self.tof_addr)
                if kind == "unix":
                    open_unix = getattr(asyncio, "open_unix_connection", None)
                    if not callable(open_unix):
                        return _view("unavailable", reason="Este sistema não oferece suporte a socket Unix; em desenvolvimento, configure um endereço tcp:")
                    reader, writer = await open_unix(address[0], limit=TOF_LINE_LIMIT)
                else:
                    reader, writer = await asyncio.open_connection(*address, limit=TOF_LINE_LIMIT)
                connected = True
                # tofd has no hello handler: its only depth request is tof.stream.
                writer.write(encode(1, "tof.stream", {}))
                await writer.drain()
                response = await _message(reader)
                if type(response.get("id")) is not int or response["id"] != 1:
                    raise ValueError("O serviço ToF respondeu com um número de sequência de assinatura inválido")
                if "error" in response:
                    error = response["error"]
                    message = error.get("message") if isinstance(error, dict) else "falha na assinatura"
                    raise ValueError(f"O serviço ToF recusou a assinatura: {str(message)[:2048]}")
                metadata = _metadata(response.get("result"))
                notification = await _message(reader)
                if notification.get("method") != "tof.frame" or "id" in notification:
                    raise ValueError("A assinatura ToF deve retornar uma notificação tof.frame")
                return _frame_view(notification.get("params"), metadata)
        except TimeoutError:
            if metadata is not None:
                reason = metadata.get("unavailable")
                return _view("unavailable" if reason else "waiting", True, metadata.get("sensor"),
                             reason or "Aguardando o primeiro quadro ToF", metadata["hz"])
            return _view("error" if connected else "unavailable", connected,
                         reason="O serviço ToF não respondeu a tempo" if connected else "Tempo esgotado ao conectar ao serviço ToF")
        except (ConnectionError, OSError) as exc:
            return _view("error" if connected else "unavailable", False,
                         sensor=metadata.get("sensor") if metadata else None,
                         reason="A conexão com o serviço ToF foi encerrada" if connected else f"O serviço ToF está offline: {exc}",
                         hz=metadata.get("hz") if metadata else None)
        except ValueError as exc:
            return _view("error", connected, sensor=metadata.get("sensor") if metadata else None,
                         reason=f"Dados ToF inválidos: {exc}", hz=metadata.get("hz") if metadata else None)
        finally:
            if writer is not None:
                writer.close()
                try:
                    await asyncio.wait_for(writer.wait_closed(), 0.1)
                except (TimeoutError, ConnectionError, OSError):
                    writer.transport.abort()
