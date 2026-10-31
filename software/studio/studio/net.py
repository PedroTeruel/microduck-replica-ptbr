"""Configuração de Wi-Fi: lê o estado do netcheck, chama net.status/scan/connect/forget no configd e pede ao auxiliar para ativar/desativar o hotspot.

Se não conseguir se conectar ao Wi-Fi na inicialização, microduck-netcheck ativa o hotspot (nome de conexão NM Microduck-Hotspot, endereço 10.42.0.1)
e grava o estado atual em /run/microduck/net.json. O Studio apenas lê esse arquivo:

    {"mode": "wifi" | "hotspot" | "none",
     "hotspot_ssid": "Microduck-c51b", "hotspot_ip": "10.42.0.1", "hotspot_psk": "microduck",
     "hostname": "duck-c51b", "since": 1790000000.0,
     "scan": [{"ssid": "Home", "signal": 72, "security": "wpa_psk"}], "scan_at": 1790000000.0}

Se o arquivo não existir (desenvolvimento no computador ou imagem antiga), o estado é “desconhecido”: o painel Wi-Fi fica oculto e o restante funciona normalmente.
No modo hotspot, wlan0 não pode buscar redes (modo AP). Se net.scan do configd retornar vazio ou falhar, usa a busca anterior à ativação do hotspot salva no arquivo e marca o resultado como cached.

Senha: a senha do Wi-Fi doméstico é transmitida uma única vez da página para o configd, somente em memória. Nunca é gravada em logs, state, last-try ou no pacote de diagnóstico.
hotspot.psk em state é a senha pública do próprio hotspot do robô (microduck) e deve ser exibida ao usuário; não é a senha do Wi-Fi doméstico.
"""
import asyncio
import json
import os
import re
import socket
import time
from pathlib import Path

from . import helper
from .log import log_cmd
from .rpc import Conn, RpcError, Timeout, Unreachable, call_once

NET_STATE = "/run/microduck/net.json"
LAST_TRY_NAME = "net-last-try.json"
READ_EVERY_S = 2.0
STATUS_EVERY_S = 5.0
STATUS_TIMEOUT_S = 4.0
CONNECT_DELAY_S = 2.0          # Aguarda a página receber o aviso de início antes de alterar o hotspot.
CONNECT_TIMEOUT_S = 60.0
SCAN_TIMEOUT_S = 15.0
FORGET_TIMEOUT_S = 10.0
STATUS_MAX_AGE_S = 15.0        # Consulta a cada 5 segundos; considera desconhecido após três falhas.
PORT = 8000
HOTSPOT_IP = "10.42.0.1"       # Endereço padrão do hotspot compartilhado do NetworkManager se net.json não informar hotspot_ip.
OWN_PREFIX = "Microduck-"      # O netcheck nomeia os hotspots do robô como Microduck-xxxx.
PSK_HEX = re.compile(r"^[0-9A-Fa-f]{64}$")
PERMISSION = "O Studio não tem permissão para alterar o Wi-Fi (radxa não foi autorizado pelo configd)."

REASON_TEXT = {
    "bad_key": "Senha incorreta.",
    "not_found": "O robô não encontrou esta rede Wi-Fi. Confira o nome e aproxime-se do roteador; redes ocultas não são compatíveis.",
    "timeout": "Conectado, mas não foi possível obter um endereço. Tente novamente.",
    "studio_timeout": "O configurador de rede do robô não respondeu em 60 segundos.",
    "unsupported": "Não é possível conectar o robô a esta rede Wi-Fi (autenticação corporativa ou senha ausente).",
    "other": "Não foi possível conectar.",
}


class Refused(Exception):
    """Operação de rede indisponível ou parâmetro inválido; message é exibido ao usuário na página."""


def validate_ssid(value):
    """SSID de 1 a 32 bytes (UTF-8; alguns caracteres ocupam vários bytes). Não aplique strip: espaços podem fazer parte do nome da rede."""
    if not isinstance(value, str) or value == "":
        raise Refused("O nome do Wi-Fi deve ter de 1 a 32 bytes.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as e:
        raise Refused(f"O nome do Wi-Fi contém um caractere inválido: {e}") from None
    if size > 32:
        raise Refused("O nome do Wi-Fi não pode ultrapassar 32 bytes.")
    if "\x00" in value:
        raise Refused("O nome do Wi-Fi não pode conter NUL.")
    return value


def validate_psk(value):
    """Vazio indica rede aberta; caso contrário, aceita 8 a 63 caracteres ou 64 dígitos hexadecimais (formatos WPA)."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise Refused("A senha do Wi-Fi deve ser texto.")
    if PSK_HEX.fullmatch(value):
        return value
    if 8 <= len(value) <= 63:
        return value
    raise Refused("A senha do Wi-Fi deve ter de 8 a 63 caracteres ou 64 dígitos hexadecimais.")


def validate_connect(ssid, psk):
    return validate_ssid(ssid), validate_psk(psk)


def addresses(host, ip, port=PORT):
    """Endereços disponíveis para este robô, com indicação de qual usar em cada dispositivo.
    Em um teste real, o Windows com proxy Clash não abriu .local (erro 502); o nome sem ponto resolveu via LLMNR e ignorou o proxy por <local>. O endereço IP funciona em qualquer dispositivo."""
    out = []
    if ip:
        out.append({"kind": "ip", "url": f"http://{ip}:{port}/", "note": "IP: funciona em qualquer dispositivo (pode mudar ao trocar de roteador ou endereço)"})
    out.append({"kind": "host", "url": f"http://{host}:{port}/", "note": "Para computadores Windows; funciona mesmo com proxy ativo"})
    out.append({"kind": "local", "url": f"http://{host}.local:{port}/", "note": "Para iPhone, iPad e Mac"})
    return out


def own_hotspot(n, hotspot_ssid):
    """Verifica se a rede encontrada é o próprio hotspot do robô. Em um dispositivo real, Microduck-0de6 aparecia como salva; selecioná-la poderia levar o usuário a informar a senha doméstica.
    Se net.json fornecer hotspot_ssid, compare com ele; caso contrário, reconheça redes salvas cujo nome começa com Microduck-."""
    ssid = n.get("ssid") if isinstance(n, dict) else None
    if not isinstance(ssid, str):
        return False
    if hotspot_ssid:
        return ssid == hotspot_ssid
    return ssid.startswith(OWN_PREFIX) and bool(n.get("saved"))


def explain(reason, detail=None):
    """Converte o motivo de falha do configd em uma mensagem curta para a página. Inclui detail para other e mantém explícitos os erros de permissão."""
    if detail and str(detail).strip() == PERMISSION:
        return PERMISSION
    base = REASON_TEXT.get(reason, REASON_TEXT["other"])
    if reason == "other" and detail:
        return f"{base}（{detail}）"
    return base


def _scrub(text, psk=None):
    """Antes de gravar logs ou last-try, oculta a senha doméstica e sua forma codificada em URL como [oculto]."""
    if text is None:
        return None
    out = str(text)
    if psk:
        out = out.replace(psk, "[oculto]")
    return out[:600]


def _rpc_error(e, what):
    if isinstance(e, RpcError):
        if e.code == 14 or re.search(r"permission|not authori[sz]ed|not allowed|access denied", e.message or "", re.I):
            return PERMISSION
        return f"{what}: {e.message}"
    if isinstance(e, Timeout):
        return f"Tempo limite excedido em {what} ({e})."
    return f"Não foi possível conectar ao configd: {e}"


class Net:
    """Estado e operações de rede. start() inicia dois ciclos: lê net.json a cada 2 segundos e consulta net.status do configd a cada 5 segundos, somente se o arquivo existir."""

    def __init__(self, configd_addr, state_file=NET_STATE, state_dir=None, log=None, *, dev_mode=False,
                 hostname=None, port=PORT):
        self.configd_addr = configd_addr
        self.state_file = Path(state_file)
        self.hostname = hostname
        self.port = int(port)
        self.log = log
        self.dev_mode = bool(dev_mode)
        self.last_try_path = Path(state_dir) / LAST_TRY_NAME if state_dir else None
        self.cfg = Conn(configd_addr, "configd-net", log) if configd_addr and configd_addr != "none" else None
        self.info = None
        self.info_at = None
        self.status = None
        self.status_at = None
        self.busy = None
        self.last_try = self._load_last_try()
        self._bad_state_logged = False
        self._status_error_logged = False
        self._tasks = []
        self.connect_task = None       # Tarefa de conexão Wi-Fi em segundo plano iniciada por app.py; não deve ser cancelada se a página desconectar.

    # ---- Ciclo de vida ----

    def start(self):
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(self._read_loop(), name="net-state"),
                       loop.create_task(self._status_loop(), name="net-status")]

    async def stop(self):
        for t in self._tasks:
            t.cancel()
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=1.0)
        self._tasks = []
        if self.cfg is not None:
            self.cfg.close()

    async def _read_loop(self):
        while True:
            try:
                await asyncio.to_thread(self._read_once)
            except Exception as e:  # noqa: BLE001 — um erro ao ler o arquivo de estado não deve encerrar todo o Studio.
                if self.log:
                    self.log.warn("Falha ao ler o arquivo de estado da rede", cat="Rede", step=str(self.state_file),
                                  raw=f"{type(e).__name__}: {e}", dedup=True)
            await asyncio.sleep(READ_EVERY_S)

    def _read_once(self):
        try:
            raw = self.state_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            had = self.info is not None
            self.info, self.info_at = None, None
            self.status, self.status_at = None, None
            self._bad_state_logged = False
            if had and self.log:
                self.log.info("Arquivo de estado de rede ausente; painel Wi-Fi oculto, demais funções normais", cat="Rede")
            return
        except OSError as e:
            self._state_bad(f"Não foi possível ler {self.state_file}: {type(e).__name__}: {e}")
            return
        try:
            data = json.loads(raw)
        except ValueError as e:
            self._state_bad(f"JSON inválido: {e}")
            return
        if not isinstance(data, dict) or data.get("mode") not in ("wifi", "hotspot", "none"):
            self._state_bad("O conteúdo não é um objeto ou mode não é wifi/hotspot/none.")
            return
        was_bad = self._bad_state_logged
        self.info, self.info_at = data, time.monotonic()
        self._bad_state_logged = False
        if was_bad and self.log:
            self.log.info("Arquivo de estado de rede voltou a ser lido", cat="Rede")

    def _state_bad(self, why):
        self.info, self.info_at = None, None
        self.status, self.status_at = None, None
        if self._bad_state_logged or self.log is None:
            return
        self._bad_state_logged = True
        self.log.warn("Não foi possível interpretar o arquivo de estado de rede; painel Wi-Fi oculto", cat="Rede", step=str(self.state_file),
                      raw=why, hint="O arquivo é gravado pelo netcheck e será atualizado na próxima execução. As demais funções continuam normais.")

    async def _status_loop(self):
        while True:
            if self.cfg is not None and self.info is not None:
                try:
                    r = await self.cfg.call("net.status", {}, timeout=STATUS_TIMEOUT_S)
                    if not isinstance(r, dict):
                        raise RpcError("net.status", None, f"A resposta não é um objeto ({type(r).__name__}).")
                    self.status, self.status_at = r, time.monotonic()
                    if self._status_error_logged and self.log:
                        self.log.info("Estado do Wi-Fi restabelecido", cat="Rede")
                    self._status_error_logged = False
                except (Unreachable, Timeout, RpcError) as e:
                    self.status, self.status_at = None, None
                    if not self._status_error_logged and self.log:
                        self._status_error_logged = True
                        self.log.warn("Não foi possível ler o estado do Wi-Fi", cat="Rede", step="configd net.status", raw=str(e),
                                      hint="O configd pode não estar em execução. Isso não afeta ficar em pé ou caminhar; somente o painel Wi-Fi ficará como desconhecido.")
            else:
                self.status, self.status_at = None, None
                self._status_error_logged = False
            await asyncio.sleep(STATUS_EVERY_S)

    # ---- Dados para a página ----

    def mode(self):
        return self.info.get("mode") if isinstance(self.info, dict) else None

    def view(self, now=None):
        """Campo net enviado à página. Arquivo ausente ou inválido resulta em {"known": false}."""
        if not isinstance(self.info, dict):
            return {"known": False}
        now = time.monotonic() if now is None else now
        st = self.status if (isinstance(self.status, dict) and self.status_at is not None
                             and now - self.status_at <= STATUS_MAX_AGE_S) else None
        connected = bool(st and st.get("state") == "connected")
        host = self.info.get("hostname") or self.hostname or socket.gethostname()
        last = None
        if isinstance(self.last_try, dict):
            last = {k: self.last_try.get(k) for k in ("ssid", "at", "ok", "reason", "detail", "ip4")}
            last["reason_text"] = explain(last.get("reason"), last.get("detail"))
        mode = self.info.get("mode")
        ip4 = st.get("ip4") if connected else None
        # Endereço IP disponível: endereço do hotspot do robô (10.42.0.1) no modo hotspot; caso contrário, ip4 de configd net.status (nulo se desconectado).
        ip_now = (self.info.get("hotspot_ip") or HOTSPOT_IP) if mode == "hotspot" else ip4
        return {
            "known": True,
            "mode": mode,
            "ssid": st.get("ssid") if connected else None,
            "signal": st.get("signal") if connected else None,
            "ip4": ip4,
            "ip_now": ip_now,
            "hostname": host,
            "url_local": f"http://{host}.local:{self.port}/",
            "url_host": f"http://{host}:{self.port}/",
            "urls": addresses(host, ip_now, self.port),
            "hotspot": {"ssid": self.info.get("hotspot_ssid"), "ip": self.info.get("hotspot_ip"),
                        "psk": self.info.get("hotspot_psk")},
            "last_try": last,
            "busy": self.busy,
        }

    def begin_connect(self):
        """Marca a conexão como em andamento; um segundo connect retorna False. Lança Refused se o estado da rede for desconhecido."""
        if not isinstance(self.info, dict):
            raise Refused("O estado da rede do robô é desconhecido; o Wi-Fi está indisponível.")
        if self.busy is not None:
            return False
        self.busy = "connecting"
        return True

    # ---- Busca de redes ----

    async def scan(self):
        """Busca redes com configd net.scan. No modo hotspot, o adaptador pode não conseguir buscar; se o resultado vier vazio ou ocorrer um erro, usa a busca anterior à ativação do hotspot salva em net.json.
        Filtra o próprio hotspot do robô para não exibi-lo como rede salva e induzir o usuário a informar a senha doméstica."""
        if not isinstance(self.info, dict):
            raise Refused("O estado da rede do robô é desconhecido; o Wi-Fi está indisponível.")
        own = self.info.get("hotspot_ssid")
        result, error = None, None
        with log_cmd(self.log, "Buscar redes Wi-Fi", "configd net.scan") as t:
            try:
                r = await call_once(self.configd_addr, "net.scan", {}, timeout=SCAN_TIMEOUT_S)
                nets = r.get("networks") if isinstance(r, dict) else None
                if not isinstance(nets, list):
                    raise Refused("Não foi possível interpretar a lista de redes Wi-Fi retornada pelo configd.")
                result = [n for n in nets if isinstance(n, dict) and n.get("ssid") and not own_hotspot(n, own)]
                t.ok({"networks": len(result)})
            except (Unreachable, Timeout, RpcError, Refused) as e:
                error = _rpc_error(e, "buscar redes Wi-Fi") if not isinstance(e, Refused) else str(e)
                result = None
                t.fail(error, hint="No modo hotspot, use a busca feita antes da ativação do hotspot.")
        if self.mode() == "hotspot" and not result:
            cached = self.info.get("scan")
            if isinstance(cached, list):
                if self.log:
                    self.log.info("Usando a busca anterior à ativação do hotspot", cat="Rede", raw=error or "A lista retornada pelo configd está vazia.",
                                  dedup=True)
                return {"networks": [n for n in cached if isinstance(n, dict) and not own_hotspot(n, own)], "cached": True,
                        "scan_at": self.info.get("scan_at")}
        if result is None:
            raise Refused(error or "Não foi possível ler a lista de redes Wi-Fi.")
        return {"networks": result, "cached": False, "scan_at": None}

    # ---- Conexão ----

    async def connect(self, ssid, psk, by):
        """Desativa o hotspot, chama configd net.connect e grava last-try. Chame begin_connect() antes.
        Retorna o registro last-try sem a senha. Em caso de falha, reativa o hotspot imediatamente; para bad_key, remove primeiro a configuração inválida criada nesta tentativa."""
        ssid, psk = validate_connect(ssid, psk)
        if self.busy is None:
            self.busy = "connecting"
        if psk and self.log:
            self.log.hide(psk)                    # Proteção adicional caso outro código envie a senha aos logs.
        outcome = {"ok": False, "reason": "other", "detail": None, "ip4": None}
        hotspot_stopped = False
        hotspot_down_tried = False
        try:
            await asyncio.sleep(CONNECT_DELAY_S)
            if self.mode() == "hotspot":
                if self.dev_mode:
                    if self.log:
                        self.log.info("Desenvolvimento no computador (--dev-autologin): mantendo o hotspot ativo e conectando ao Wi-Fi", cat="Rede",
                                      raw=f"by={by}", dedup=False)
                else:
                    if not helper.available(refresh=True):
                        if self.log:
                            self.log.warn("Auxiliar ausente antes da conexão Wi-Fi", cat="Rede", step="wifi-hotspot-down",
                                          hint="Execute deploy/install.sh no robô primeiro.")
                        raise Refused("O auxiliar não está instalado. Execute deploy/install.sh no robô para permitir que o Studio desative o hotspot e conecte ao Wi-Fi.")
                    hotspot_down_tried = True
                    with log_cmd(self.log, "Desativar hotspot", "Auxiliar wifi-hotspot-down", who=by) as th:
                        try:
                            ok_h, result_h, detail_h = await asyncio.to_thread(helper.wifi_hotspot_down, by, ssid)
                        except Exception as e:  # noqa: BLE001
                            th.fail(f"{type(e).__name__}: {e}", hint="Confira se o auxiliar está instalado e atualizado.")
                            raise Refused(f"Falha ao executar o auxiliar: {type(e).__name__}: {e}") from None
                        if result_h == "bad_verb":
                            th.fail("Auxiliar antigo não reconhece wifi-hotspot-down", hint="Reinstale com deploy/install.sh.")
                            raise Refused("O auxiliar está desatualizado. Reinstale com deploy/install.sh.")
                        if not ok_h:
                            why = helper.friendly(result_h, detail_h, "wifi-hotspot-down")
                            th.fail(why, raw=str(detail_h), hint="Confira se nmcli detecta Microduck-Hotspot.")
                            raise Refused(f"Não foi possível desativar o hotspot: {why}")
                        th.ok({"result": result_h})
                    hotspot_stopped = True
            params = {"ssid": ssid}
            if psk:
                params["psk"] = psk
            with log_cmd(self.log, f"Conectar ao Wi-Fi “{ssid}”", "configd net.connect", who=by,
                         args={"ssid": ssid, "senha": "com senha" if psk else "sem senha"}) as t:
                try:
                    r = await call_once(self.configd_addr, "net.connect", params, timeout=CONNECT_TIMEOUT_S)
                except (Unreachable, Timeout, RpcError) as e:
                    if isinstance(e, Timeout):
                        outcome = {"ok": False, "reason": "studio_timeout",
                                   "detail": f"O configurador de rede do robô não respondeu em {CONNECT_TIMEOUT_S:.0f} segundos.", "ip4": None}
                    else:
                        outcome = {"ok": False, "reason": "other", "detail": _scrub(_rpc_error(e, "conectar ao Wi-Fi"), psk),
                                   "ip4": None}
                    t.fail(explain(outcome["reason"], outcome["detail"]), raw=_scrub(str(e), psk))
                else:
                    outcome = self._read_connect(r, psk)
                    if outcome["ok"]:
                        note = f"IP {outcome['ip4']}" if outcome.get("ip4") else ""
                        t.ok({"outcome": "connected", "ssid": r.get("ssid"), "ip4": r.get("ip4")}, note=note)
                    else:
                        t.fail(explain(outcome["reason"], outcome["detail"]),
                               raw={"outcome": r.get("outcome"), "reason": r.get("reason")} if isinstance(r, dict) else None,
                               hint="O hotspot será reativado em breve; reconecte o celular ao hotspot do robô para ver o motivo.")
        except Refused as e:
            outcome = {"ok": False, "reason": "other", "detail": _scrub(str(e), psk), "ip4": None}
            if self.log:
                self.log.warn("Não foi possível iniciar a conexão Wi-Fi", cat="Rede", step="Desativar hotspot", raw=_scrub(str(e), psk),
                              hint="Confira se o auxiliar está instalado e atualizado.")
        except Exception as e:  # noqa: BLE001 — erros internos do Studio também precisam ser registrados em last-try.
            outcome = {"ok": False, "reason": "other", "detail": _scrub(f"{type(e).__name__}: {e}", psk), "ip4": None}
            if self.log:
                self.log.error("Erro do Studio durante a conexão Wi-Fi", cat="Rede", raw=_scrub(f"{type(e).__name__}: {e}", psk),
                               exc=True, hint="Este é um problema do Studio. Exporte e envie o pacote de diagnóstico.")
        finally:
            rec = {"ssid": ssid, "at": time.time(), "ok": bool(outcome["ok"]),
                   "reason": outcome["reason"], "detail": _scrub(outcome["detail"], psk),
                   "ip4": outcome.get("ip4")}
            self.last_try = rec
            self._save_last_try(rec)
            if outcome["ok"]:
                self._set_connected(ssid, outcome.get("ip4"))
            elif hotspot_down_tried and not outcome["ok"]:
                if hotspot_stopped and outcome["reason"] == "bad_key":
                    await self._forget_bad_key(ssid, by)
                await self._hotspot_up(by)
            self.busy = None
        return rec

    def _read_connect(self, r, psk):
        if not isinstance(r, dict):
            return {"ok": False, "reason": "other", "detail": "A resposta do configd não é um objeto.", "ip4": None}
        if r.get("outcome") == "connected":
            return {"ok": True, "reason": None, "detail": None, "ip4": r.get("ip4")}
        if r.get("outcome") == "failed":
            reason = r.get("reason") if r.get("reason") in REASON_TEXT else "other"
            detail = _scrub(r.get("detail"), psk) if r.get("detail") else None
            return {"ok": False, "reason": reason, "detail": detail, "ip4": None}
        return {"ok": False, "reason": "other", "detail": _scrub(f"Resposta não reconhecida: {r}", psk), "ip4": None}

    async def _hotspot_up(self, by):
        with log_cmd(self.log, "Ativar hotspot", "Auxiliar wifi-hotspot-up", who=by) as t:
            try:
                ok, result, detail = await asyncio.to_thread(helper.wifi_hotspot_up, by)
            except Exception as e:  # noqa: BLE001
                t.fail(f"{type(e).__name__}: {e}", hint="O netcheck também ativa o hotspot quando a janela de conexão termina.")
                return
            if result == "bad_verb":
                t.fail("Auxiliar antigo não reconhece wifi-hotspot-up", hint="Reinstale com deploy/install.sh; o netcheck ativa o hotspot ao fim da janela de conexão.")
            elif ok:
                t.ok({"result": result})
            else:
                t.fail(helper.friendly(result, detail, "wifi-hotspot-up"), raw=str(detail),
                       hint="O netcheck também ativa o hotspot quando a janela de conexão termina.")

    async def _forget_bad_key(self, ssid, by):
        """Senha incorreta: o connect do sistema já substituiu a configuração de mesmo nome pela senha inválida; remova-a para evitar novas tentativas do netcheck."""
        with log_cmd(self.log, f"Remover Wi-Fi com senha incorreta “{ssid}”", "configd net.forget", who=by) as t:
            try:
                r = await call_once(self.configd_addr, "net.forget", {"ssid": ssid}, timeout=FORGET_TIMEOUT_S)
            except (Unreachable, Timeout, RpcError) as e:
                t.fail(_rpc_error(e, "remover Wi-Fi"), raw=str(e), hint="O hotspot será reativado imediatamente; a configuração pode continuar salva.")
                return
            if not isinstance(r, dict):
                t.fail("A resposta do configd não é um objeto.", raw=repr(r)[:200])
                return
            t.ok({"removed": bool(r.get("removed"))})

    def _set_connected(self, ssid, ip4):
        self.status = {"state": "connected", "ssid": ssid, "ip4": ip4}
        self.status_at = time.monotonic()

    # ---- Remover rede salva ----

    async def forget(self, ssid):
        ssid = validate_ssid(ssid)
        if not isinstance(self.info, dict):
            raise Refused("O estado da rede do robô é desconhecido; o Wi-Fi está indisponível.")
        with log_cmd(self.log, f"Remover Wi-Fi “{ssid}”", "configd net.forget") as t:
            try:
                r = await call_once(self.configd_addr, "net.forget", {"ssid": ssid}, timeout=FORGET_TIMEOUT_S)
            except (Unreachable, Timeout, RpcError) as e:
                text = _rpc_error(e, "remover Wi-Fi")
                t.fail(text, raw=str(e))
                raise Refused(text) from None
            if not isinstance(r, dict):
                t.fail("A resposta do configd não é um objeto.", raw=repr(r)[:200])
                raise Refused("A resposta do configd não é um objeto.")
            removed = bool(r.get("removed"))
            t.ok({"removed": removed})
        if isinstance(self.status, dict) and self.status.get("ssid") == ssid:
            self.status, self.status_at = None, None
        return {"removed": removed}

    # ---- Arquivo last-try ----

    def _load_last_try(self):
        if self.last_try_path is None:
            return None
        try:
            data = json.loads(self.last_try_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return {k: data.get(k) for k in ("ssid", "at", "ok", "reason", "detail", "ip4")}

    def _save_last_try(self, rec):
        if self.last_try_path is None:
            return
        try:
            self.last_try_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.last_try_path.with_name(self.last_try_path.name + ".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
            try:
                os.chmod(tmp, 0o644)
            except OSError:
                pass
            os.replace(tmp, self.last_try_path)
        except OSError as e:
            if self.log:
                self.log.warn("Não foi possível gravar o resultado da última conexão Wi-Fi", cat="Rede", step=str(self.last_try_path),
                              raw=f"{type(e).__name__}: {e}",
                              hint="A página não mostrará o motivo da falha anterior quando se reconectar. Confira se o diretório state está cheio ou sem permissão.")
