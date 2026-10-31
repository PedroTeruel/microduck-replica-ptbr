"""Serviço web do Studio: arquivos estáticos, login, registros, pacote de diagnóstico e hub WebSocket.

WebSocket /ws (valida Host e Origin durante o handshake; rejeita valores inválidos. Sem login, aceita a conexão e depois a fecha com 4401,
para que a página receba 4401 e abra a tela de login. Fechar durante o handshake só produz 1006 no navegador e causa reconexões contínuas):
    Studio → página: {"t":"hello",...}  {"t":"state",...} (10 Hz quando a página está visível)  {"t":"hb"} (1 Hz quando está invisível)
                   {"t":"log","entry":{...}}  {"t":"result","id":...,"ok":...,"reason":...}
    página → Studio: {"t":"hb","seq":N,"visible":true,"route":"/","pad_visible":false} (uma vez por segundo)  {"t":"cmd","id":...,"name":"relax"}
pad_visible indica se a área do controle está visível (revisão O1 da reorganização do resumo: o controle foi integrado ao resumo, então #/pad não garante que esteja na tela). Páginas com a área visível recebem o estado do controle a 10 Hz;
as demais, a 1 Hz (para o cartão de controle no painel). Páginas antigas não enviam esse campo; nesses casos, usa route == "/pad" como alternativa.

Sessão de servos (revisões de código D1, D2, D3 e D9):
- **Sair do Studio não relaxa o torque**: ao sair, fecha apenas a porta serial e mantém os servos habilitados, conforme definido pelo usuário para sair da página de servos.
  Ao abrir o barramento, grava atomicamente servo-session.json no diretório state (porta serial, horário de início e responsável); remove o arquivo apenas após devolver o controle com sucesso. Se o Studio iniciar e encontrar o marcador com o robotd parado,
  retoma automaticamente o barramento em modo somente leitura, sem alterar o torque, e restaura a sessão e o aviso. Se não conseguir retomar, avisa que os servos talvez continuem habilitados e orienta a assumir o controle na página de servos antes de relaxar o torque.
  Se o robotd estiver em execução, ele já terá liberado os servos ao iniciar e o marcador será removido.
- Ao sair ou devolver o barramento, registra primeiro as operações de servo no loop de eventos (op_begin), marca a sessão como closing, aguarda operações em andamento e lê o torque naquele momento (servo.py).
  Não devolve o barramento se outra página ainda estiver na página de servos, se calibração ou movimento estiver em andamento ou se não for possível ler o torque.
- Durante a sessão, verifica a cada 5 segundos o socket do robotd: se conectar, significa que foi iniciado manualmente (ele libera todos os servos e disputa a porta serial com o Studio).
  Registra o erro, fecha o barramento no Studio sem escrever nos servos e exibe o aviso em vermelho.
"""
import asyncio
import contextlib
import gzip
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth import COOKIE, REMEMBER_S, Auth, OriginGuard
from . import helper
from .rpc import open_conn
from .servo import boot_id, view_from_robotd
from .sshkeys import BadKey, SshKeys
from .state import summarize
from .pad import Refused as PadRefused, robot_view  # página do controle
from .ai_connections import AiError
from .ai_service import AiService
from .updates import Updates, UpdateError, handle as handle_updates, safe_during_update

VERSION = "0.1.0-dev"
RUNTIME_ROOT = Path(__file__).resolve().parents[2]
try:
    SUITE_VERSION = json.loads((RUNTIME_ROOT / 'suite-version.json').read_bytes())['version']
except (OSError,ValueError,KeyError):
    SUITE_VERSION = None
MODEL_UPLOAD_LIMIT = 64 * 1024 * 1024
MODEL_OP_LIMIT = 32768
STATE_HZ = 10
COMMANDS = {"relax", "servo.open", "servo.close", "servo.op", "servo.ports", "imu.op", "calib.op", "pad.op", "onboard.op", "battery.op", "tune.op", "net.op"}
HB_QUIET_S = 5.0         # tempo sem heartbeat: considerar invisível (parar de enviar estado; talvez tenha cancelado a inscrição)
HB_DEAD_S = 30.0         # tempo sem mensagens: considerar desconectada (por exemplo, celular fora do Wi-Fi) e fechá-la
MUSIC_PONG_TIMEOUT_S = 5.0
SERVO_IDLE_S = 60.0      # tempo sem ninguém na página de servos e sem servos habilitados: devolver automaticamente ao programa principal
ONBOARD_TICK_S = 0.5     # intervalo de verificação do guia inicial (conta os 3 s para ficar em pé e os 2 s para andar)
SERVO_MARKER = "servo-session.json"   # marcador de sessão de servos aberta (no diretório state; removido após devolução bem-sucedida; revisão D1)
ROBOTD_PROBE_S = 5.0     # intervalo para verificar se robotd iniciou durante a sessão de servos (revisão D9)
# Listas longas de descrições do controle: só envia quando mudam (revisão O12; 4,8 KB por quadro e Wi-Fi e Bluetooth compartilham o chip).
# Envia a lista completa a cada segundo; nos demais quadros, a página reutiliza os valores anteriores.
PAD_HEAVY = ("skills", "actions", "combos", "sounds")


class HostGuard:
    """Middleware ASGI: responde 421 a solicitações com Host desconhecido (proteção contra DNS rebinding) e fecha WebSockets desconhecidos."""

    def __init__(self, app, guard, log):
        self.app, self.guard, self.log = app, guard, log

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and (scope.get('path') == '/api/ai' or scope.get('path','').startswith('/api/updates')):
            original_send = send
            async def private_send(message):
                if message['type'] == 'http.response.start':
                    message = {**message, 'headers':[(k,v) for k,v in message.get('headers',[])
                        if k.lower() != b'cache-control'] + [(b'cache-control',b'no-store')]}
                await original_send(message)
            send = private_send
        if scope["type"] in ("http", "websocket"):
            host = dict(scope.get("headers") or []).get(b"host", b"").decode("latin-1")
            local_ip = (scope.get("server") or (None,))[0]
            if not self.guard.host_ok(host, local_ip):
                # Mantém a mensagem fixa e o valor de Host original: tentativas com Hosts diferentes são agrupadas em uma linha pelo mecanismo de deduplicação.
                self.log.warn("Solicitação rejeitada: Host inválido", cat="Conexão", raw=repr(host[:100]),
                              hint="Isso não deve ocorrer no uso normal. Se estiver usando um endereço novo, adicione-o ao parâmetro --name")
                if scope["type"] == "http":
                    await PlainTextResponse("Host inválido", status_code=421)(scope, receive, send)
                else:
                    await send({"type": "websocket.close", "code": 4403})
                return
        await self.app(scope, receive, send)


class AppStatic(StaticFiles):
    """Verifica atualizações dos arquivos da página a cada solicitação (alterações entram em vigor imediatamente); arquivos estáveis, como vendor e model, ficam em cache por um dia."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        path = scope.get("path", "")
        if path.startswith(("/vendor/", "/model/")):
            resp.headers["Cache-Control"] = "public, max-age=86400"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def _client_desc(conn):
    ip = conn.client.host if conn.client else "?"
    ua = conn.headers.get("user-agent", "")
    kind = "celular" if any(k in ua for k in ("iPhone", "Android", "Mobile")) else "computador"
    return f"{kind} {ip}"


def _bus_take(by, servo=None):
    """Para o programa principal e assume o barramento dos servos (chamado em uma thread ao abrir a página de servos). Se o helper estiver disponível, solicita bus-take (sem relaxar o torque, apenas sinaliza a posse).
    Se não estiver (desenvolvimento no computador, bancada ou demonstração), não faz nada; a verificação robotd_active de servo.open continua responsável por informar o erro. Retorna (ok, motivo)."""
    if not helper.available():
        if servo is not None:
            servo.helper_available = False
        return True, None
    if servo is not None:
        servo.helper_available = True
    ok, result, detail = helper.bus_take(by)
    if ok:
        return True, None
    return False, helper.friendly(result, detail, "bus-take")


def _bus_give_back(by, servo=None):
    """Inicia o programa principal depois de devolver o barramento (chamado em uma thread ao clicar em “Devolver ao programa principal” ou sair da página de servos). Se o helper estiver disponível, solicita bus-give-back soft (remove o sinal de posse, inicia robotd e aguarda as quatro etapas de inicialização); caso contrário, não faz nada. Retorna (ok, motivo)."""
    if not helper.available():
        if servo is not None:
            servo.helper_available = False
        return True, None
    if servo is not None:
        servo.helper_available = True
    ok, result, detail = helper.bus_give_back(by, soft=True, timeout=60)
    if servo is not None:
        # O programa principal responde, mas permanece na fase de inicialização (modo de calibração de forks antigos); o aviso após devolver não deve instruir o usuário a iniciar robotd manualmente.
        servo.giveback_stuck = bool(isinstance(detail, dict) and detail.get("still_starting"))
    if ok:
        return True, None
    return False, helper.friendly(result, detail, "bus-give-back")


def build_app(*, auth, robotd, log, web_dir, duck, names=(), state_dir=None, dev_autologin=False, servo=None, imu=None, pad=None,
              onboard=None, battery=None, tune=None, net=None, commit=None, ssh_home=None, models=None, sensors=None, updates=None):
    guard = OriginGuard(names=names)
    ai = AiService(state_dir)
    updates = updates or Updates()
    if pad is not None:
        pad.update_guard=updates.installing
    update_commands = set()

    def update_readiness():
        busy = any(not task.done() for task in update_commands) or model_upload_gate.locked()
        motion = getattr(pad,'motion_studio',None)
        if (updates.installing() or busy or (servo is not None and servo.state != 'closed')
            or (motion is not None and (motion.state != 'idle' or motion.session is not None))
            or (imu is not None and (getattr(imu,'_redo_busy',False)
                or getattr(imu,'blocks_updates',lambda:False)()))):
            return {'ready':False,'error':'Encerre as sessões de servos, calibração, gravação, reprodução e movimento antes de tentar novamente'}
        return {'ready':True}
    if imu is not None and commit is not None:
        imu.commit = commit                          # Modo de calibração “habilitar postura em pé”: usa as mesmas direções gravadas no programa principal.
    if onboard is not None:
        # As duas anotações do guia de configuração vêm daqui: teste de parada de emergência aprovado (thread de teste em pad.py) e validação em pé na página da IMU (imu.py).
        if pad is not None:
            pad.on_estop_passed = onboard.note_estop
        if imu is not None:
            imu.on_check = onboard.note_imu_check
        if commit is not None:
            onboard.commit_service = commit          # Etapa 3, “Gravar no programa principal”: estado de preparação e critério de conclusão.
            commit.onboard = onboard                 # Informa ao estado de preparação quando o usuário marca as etapas 1/2 como “Concluída” ou “Pular”.
    web_dir = Path(web_dir)
    clients = {}           # websocket -> {"visible": bool, "by": str, "hb_at": monotonic}
    login_gate = asyncio.Semaphore(1)
    servo_gate = asyncio.Lock()         # Apenas uma operação de abertura/fechamento do barramento de servos por vez.
    model_upload_gate = asyncio.Lock()
    # Marcador da sessão de servos (revisão D1); não grava se o diretório state não foi informado (testes).
    marker = Path(state_dir) / SERVO_MARKER if state_dir and servo is not None else None   # Serializa tentativas de login para evitar contornar a espera progressiva e alocar várias vezes 16 MB do scrypt simultaneamente.

    dev_sess = {"csrf": "dev", "auth_at": time.time(), "remember": False}
    # Decisão do usuário em 10-18: não exigir senha de administrador; basta iniciar e conectar. Sem senha, o acesso fica aberto a quem estiver na mesma rede (como em servo-web).
    # O login só é exigido quando uma senha foi configurada. As validações de Host/Origin continuam impedindo que outro site use o navegador para controlar o Microduck.
    open_sess = {"csrf": "open", "auth_at": time.time(), "remember": False}
    if dev_autologin:
        log.warn("Modo de desenvolvimento: solicitações locais não exigem login", cat="Sistema", hint="Use somente para capturas de tela no computador; não habilite no Microduck")

    def session_of(conn, touch=True):
        token = conn.cookies.get(COOKIE)
        if dev_autologin and conn.client and conn.client.host == "127.0.0.1":
            return token or "dev", dev_sess
        if not auth.has_password():
            return token or "open", open_sess
        return token, auth.session(token, touch=touch)

    def origin_ok(conn):
        return guard.origin_ok(conn.headers.get("origin"), conn.headers.get("host", ""))

    # ---- HTTP ----

    async def api_updates(request):
        try:
            _,sess=session_of(request)
            result=await handle_updates(request,updates,sess,auth.has_password(),
                dev_autologin and request.client and request.client.host=='127.0.0.1',origin_ok(request))
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except UpdateError as error:
            return JSONResponse({'ok':False,'code':error.code,'error':str(error)},status_code=error.status,headers={'Cache-Control':'no-store'})
        except Exception:
            return JSONResponse({'ok':False,'code':'service','error':'O serviço de atualização não concluiu a solicitação. Tente novamente mais tarde.'},status_code=503,headers={'Cache-Control':'no-store'})

    async def api_ai(request):
        def response(data, status=200):
            return JSONResponse(data, status_code=status, headers={'Cache-Control':'no-store'})
        _, sess = session_of(request)
        local_dev = dev_autologin and request.client and request.client.host == '127.0.0.1'
        # The general Studio open session is unsuitable for billable external requests.
        if not auth.has_password() and not local_dev:
            return response({'ok':False,'code':'password_required','error':'Configure uma senha para a interface web nas configurações antes de conectar a IA.'},403)
        if not sess:
            return response({'ok':False,'code':'unauthorized','error':'Faça login primeiro.'},401)
        if request.method == 'POST' and (not origin_ok(request) or request.headers.get('x-csrf') != sess['csrf']):
            return response({'ok':False,'code':'csrf','error':'A origem da solicitação ou o token de login é inválido.'},403)
        try:
            if request.method == 'GET':
                result = await ai.view()
            else:
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 65536:
                        raise AiError('oversize','A solicitação à IA é grande demais.',413)
                try:
                    body = json.loads(raw)
                except (ValueError,RecursionError):
                    raise AiError('validation','A solicitação não contém JSON válido.') from None
                result = await ai.handle(body)
            return response({'ok':True,**result})
        except AiError as error:
            return response({'ok':False,'code':error.code,'error':str(error)},error.status)
        except Exception:
            # Do not log exception details: network libraries may include request credentials.
            return response({'ok':False,'code':'internal','error':'A solicitação à IA não foi concluída. Tente novamente mais tarde.'},500)

    async def healthz(request):
        return JSONResponse({"ok": True, "version": VERSION,"suite_version":SUITE_VERSION,"runtime_root":str(RUNTIME_ROOT)})

    async def api_session(request):
        token, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False, "has_password": auth.has_password()}, status_code=401)
        return JSONResponse({"ok": True, "csrf": sess["csrf"], "duck": duck, "version": VERSION})

    async def api_login(request):
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "Origem da solicitação inválida."}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        ip = request.client.host if request.client else "?"
        if not isinstance(body, dict):
            body = {}
        pw = str(body.get("password", ""))
        # O corpo da solicitação nunca é registrado; não use log.hide(pw) (revisão de código #12: cada senha testada entraria na tabela de redação,
        # fazendo com que todo "true" nos registros aparecesse como [oculto] após testar essa senha).
        async with login_gate:
            token, why, wait = await asyncio.to_thread(auth.login, pw, ip, bool(body.get("remember")))
        if not token:
            return JSONResponse({"ok": False, "error": why, "wait": wait}, status_code=401)
        resp = JSONResponse({"ok": True})
        # SameSite=Lax permite manter o login ao abrir um link pelo WeChat ou por um aplicativo de mensagens (Strict exigiria login a cada vez);
        # solicitações entre sites são bloqueadas pela validação de Origin e pelo token CSRF.
        resp.set_cookie(COOKIE, token, max_age=REMEMBER_S if body.get("remember") else None,
                        httponly=True, samesite="lax", path="/")
        return resp

    async def api_logout(request):
        token, sess = session_of(request)
        if sess and origin_ok(request) and request.headers.get("x-csrf") == sess["csrf"]:
            auth.logout(token)
            log.info(f"Saiu da sessão ({_client_desc(request)})", cat="Conexão")
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    async def api_password(request):
        """Define, altera ou remove a senha de administrador pela página. Grava em password.json, usado por run.py set-password."""
        token, sess = session_of(request)
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "Origem da solicitação inválida."}, status_code=403)
        if not sess:
            return JSONResponse({"ok": False, "error": "Faça login para alterar a senha."}, status_code=401)
        if request.headers.get("x-csrf") != sess["csrf"]:
            return JSONResponse({"ok": False, "error": "Falha na validação da solicitação. Atualize a página e tente novamente."}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        action = body.get("action", "set")
        ip = request.client.host if request.client else "?"
        if action == "clear":
            if auth.has_password():
                await asyncio.to_thread(auth.clear_password)
                log.info(f"Senha de administrador removida ({_client_desc(request)})", cat="Conexão")
            resp = JSONResponse({"ok": True, "has_password": False})
            resp.delete_cookie(COOKIE, path="/")
            return resp
        if action != "set":
            return JSONResponse({"ok": False, "error": "Operação desconhecida."}, status_code=400)
        pw = body.get("password")
        confirm = body.get("confirm")
        if not isinstance(pw, str) or len(pw) < 6:
            return JSONResponse({"ok": False, "error": "A senha deve ter pelo menos 6 caracteres."}, status_code=400)
        if pw != confirm:
            return JSONResponse({"ok": False, "error": "As senhas digitadas não coincidem."}, status_code=400)
        had_password = auth.has_password()
        keep = token if had_password and token and token != "open" else None
        try:
            await asyncio.to_thread(auth.set_password, pw, keep)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        resp = JSONResponse({"ok": True, "has_password": True})
        if not had_password:
            new_token, _, _ = await asyncio.to_thread(auth.login, pw, ip, False)
            if new_token:
                resp.set_cookie(COOKIE, new_token, httponly=True, samesite="lax", path="/")
        log.info(f"Senha de administrador {'definida' if not had_password else 'alterada'} ({_client_desc(request)})", cat="Conexão")
        return resp

    ssh_gate = asyncio.Lock()
    ssh_keys = SshKeys(ssh_home)        # O Studio é executado como radxa: ~/.ssh/authorized_keys pertence a ele e não depende do helper.

    async def ssh_view(detail=None):
        """Informa se o login por senha está habilitado, o estado do serviço SSH (helper ssh-status; None se não for possível ler) e as chaves registradas (lidas pelo próprio Studio)."""
        if detail is None and await asyncio.to_thread(helper.available):
            ok, _, d = await asyncio.to_thread(helper.ssh_status)
            detail = d if ok else None
        d = detail if isinstance(detail, dict) else {}
        try:
            keys = await asyncio.to_thread(ssh_keys.list)
        except OSError:
            keys = []
        return {"password_login": d.get("password_login") if isinstance(d.get("password_login"), bool) else None,
                "ssh_active": d.get("ssh_active"), "keys": len(keys), "key_list": keys, "user": d.get("user") or "radxa"}

    async def api_ssh(request):
        """SSH da página “Mais”: status / on (senha definida pelo usuário) / off / add_key (colar chave pública) / remove_key.
        A imagem de fábrica aceita apenas chaves, não inclui chaves de terceiros e não tem senha padrão compartilhada. Para habilitar login por senha ou registrar uma chave, primeiro defina a senha de acesso à página:
        caso contrário, qualquer pessoa conectada ao ponto de acesso (cuja senha é pública) poderia abrir a página e habilitar o SSH para obter acesso root. A senha é enviada apenas ao stdin do helper e não entra nos registros."""
        _, sess = session_of(request)
        if not origin_ok(request):
            return JSONResponse({"ok": False, "error": "Origem da solicitação inválida"}, status_code=403)
        if not sess:
            return JSONResponse({"ok": False, "error": "Faça login primeiro"}, status_code=401)
        if request.headers.get("x-csrf") != sess["csrf"]:
            return JSONResponse({"ok": False, "error": "Falha na validação da solicitação; atualize a página e tente novamente"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        action = body.get("action", "status")
        if action not in ("status", "on", "off", "add_key", "remove_key"):
            return JSONResponse({"ok": False, "error": "Operação desconhecida"}, status_code=400)
        if action in ("on", "add_key") and not auth.has_password():
            what = "habilitar o SSH" if action == "on" else "registrar uma chave"
            return JSONResponse({"ok": False, "error": f"Defina primeiro a senha de acesso à página e depois {what}; caso contrário, qualquer pessoa conectada ao ponto de acesso poderá abrir a página e "
                                                     "habilitar o SSH"}, status_code=403)
        if action == "on":
            pw, confirm = body.get("password"), body.get("confirm")
            if not isinstance(pw, str) or not 8 <= len(pw) <= 64:
                return JSONResponse({"ok": False, "error": "A senha SSH deve ter de 8 a 64 caracteres"}, status_code=400)
            if pw != confirm:
                return JSONResponse({"ok": False, "error": "As senhas digitadas não correspondem"}, status_code=400)
        by = _client_desc(request)
        async with ssh_gate:
            if action == "status":
                return JSONResponse({"ok": True, "ssh": await ssh_view()})
            if action in ("add_key", "remove_key"):
                try:
                    if action == "add_key":
                        added, k = await asyncio.to_thread(ssh_keys.add, body.get("key"))
                    else:
                        gone = await asyncio.to_thread(ssh_keys.remove, body.get("fp"))
                except BadKey as e:
                    return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
                except OSError as e:
                    log.error("Falha ao gravar a chave SSH", cat="Sistema", raw=f"{type(e).__name__}: {e}", step=action,
                              hint="Verifique as permissões de /home/radxa/.ssh; se o problema continuar, exporte o pacote de diagnóstico")
                    return JSONResponse({"ok": False, "error": f"Não foi possível gravar em authorized_keys: {e}"}, status_code=500)
                if action == "add_key":
                    what = f"{k['type']} {k['comment'] or '(sem comentário)'} {k['fp']}"
                    log.info(f"Chave SSH {'registrada' if added else 'já estava registrada'}: {what} ({by})", cat="Sistema")
                    return JSONResponse({"ok": True, "added": added, "fp": k["fp"], "ssh": await ssh_view()})
                if gone:
                    log.info(f"Chave SSH removida: {body.get('fp')} ({by})", cat="Sistema")
                return JSONResponse({"ok": True, "removed": gone, "ssh": await ssh_view()})
            if not await asyncio.to_thread(helper.available):
                    return JSONResponse({"ok": False, "error": "O auxiliar root não está instalado neste robô; não é possível ativar o login SSH por senha pela interface web."},
                                    status_code=503)
            if action == "on":
                ok, result, detail = await asyncio.to_thread(helper.ssh_password, by, True, body["password"])
            else:
                ok, result, detail = await asyncio.to_thread(helper.ssh_password, by, False)
            word = "habilitado" if action == "on" else "desabilitado"
            if not ok:
                why = helper.friendly(result, detail, "ssh-password")
                log.warn(f"Login SSH por senha não foi {word}: {why}", cat="Sistema", step=f"ssh-password {action}",
                         hint="Siga as instruções; se o problema continuar, exporte o pacote de diagnóstico")
                return JSONResponse({"ok": False, "error": why},
                                    status_code=400 if result in ("bad_password", "bad_args") else 502)
            log.info(f"Login SSH por senha {word} ({by})", cat="Sistema")
            return JSONResponse({"ok": True, "ssh": await ssh_view()})

    async def api_logs(request):
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 200)), 500))
        except ValueError:
                return JSONResponse({"ok": False, "error": "O limite deve ser um número."}, status_code=400)
        return JSONResponse({"ok": True, "items": log.recent(limit=limit)})

    async def api_diag(request):
        """Pacote de diagnóstico: registros dos últimos dois dias, estado atual, versão e registros do sistema do robotd. Use para pedir ajuda no grupo."""
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        log.info(f"Pacote de diagnóstico exportado ({_client_desc(request)})", cat="Sistema")
        # Obtém o estado no loop de eventos antes de passá-lo para a thread (não lê dados mutáveis de outra thread).
        snap = summarize(robotd, duck, servo, ob=onboard, bat=battery, net=net, commit=commit, auth=auth)
        raw = {"hello": robotd.hello.value, "health": robotd.health.value, "busStatus": robotd.bus.value,
               "policies": robotd.policies.value, "calibration": robotd.calib.value,
               "pad": robotd.pad.value, "system": robotd.sysinfo.value}
        if onboard is not None:
            raw["onboarding_records"] = dict(onboard.rec)        # Dados registrados pelo guia inicial (horário, controle e impressão digital).
        if pad is not None:
            try:
                raw["pad_page"] = pad.diag()
            except Exception as e:  # noqa: BLE001
                raw["pad_page"] = f"Erro: {type(e).__name__}: {e}"
        if tune is not None:
            try:
                raw["tune"] = tune.diag()                          # Instantâneo de calibração (plano de ajuste §5: arquivo e leitura de retorno).
            except Exception as e:  # noqa: BLE001
                raw["tune"] = f"Erro: {type(e).__name__}: {e}"
        data = await asyncio.to_thread(_diag_zip, log, snap, raw)
        name = f"studio-diag-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def api_profile(request):
        """Exporta o perfil do Microduck para treinamento (plano de ajuste T3): resumo somente leitura para baixar em JSON."""
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False}, status_code=401)
        if tune is None:
            return JSONResponse({"ok": False, "error": "O backend do painel de calibração não está habilitado neste Microduck"}, status_code=404)
        log.info(f"Perfil do Microduck exportado ({_client_desc(request)})", cat="Ajuste")
        data = json.dumps(tune.profile(), ensure_ascii=False, indent=1, default=str).encode("utf-8")
        name = f"duck-profile-{time.strftime('%Y%m%d-%H%M%S')}.json"
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    async def sensor_read(request, kind):
        headers = {"Cache-Control": "no-store"}
        _, sess = session_of(request)
        if not sess:
            return JSONResponse({"ok": False, "error": "Faça login para consultar os sensores."}, status_code=401, headers=headers)
        if sensors is None:
            return JSONResponse({"ok": False, "error": "O backend da página de sensores não está ativado"}, status_code=503, headers=headers)
        try:
            data = await getattr(sensors, kind)()
            return JSONResponse({"ok": True, "data": data}, headers=headers)
        except Exception as e:
            label = "câmera" if kind == "camera" else "ToF"
            log.error(f"Falha ao ler o estado de {label}", cat="Sensores", raw=f"{type(e).__name__}: {e}", exc=True)
            return JSONResponse({"ok": False, "error": f"Não foi possível consultar o estado de {label} agora. Tente novamente mais tarde ou consulte os logs."},
                                status_code=503, headers=headers)

    async def api_camera(request):
        return await sensor_read(request, "camera")

    async def api_tof(request):
        return await sensor_read(request, "tof")

    def model_response(payload, status=200):
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    def model_access(request, *, write=False):
        _, sess = session_of(request)
        if not sess:
            return model_response({"ok": False, "error": "Faça login para gerenciar os modelos."}, 401)
        if write and (not origin_ok(request) or request.headers.get("x-csrf") != sess["csrf"]):
            return model_response({"ok": False, "error": "Falha na validação da solicitação. Atualize a página e tente novamente."}, 403)
        if write and updates.installing():
            return model_response({'ok':False,'error':'Uma atualização de software está em andamento. Aguarde a conclusão.'},409)
        if models is None:
            return model_response({"ok": False, "error": "O gerenciamento de modelos não está habilitado neste modo"}, 503)
        return None

    async def model_result(operation):
        try:
            return model_response({"ok": True, "data": await operation()})
        except ValueError as e:
            return model_response({"ok": False, "error": str(e), "code": getattr(e, "code", "invalid")},
                                  getattr(e, "status", 400))
        except Exception as e:  # Não grave o conteúdo enviado nos logs.
            log.error("Falha na operação de gerenciamento de modelos", cat="Modelos", raw=f"{type(e).__name__}: {e}", exc=True)
            return model_response({"ok": False, "error": "O gerenciamento de modelos falhou. Consulte os logs e tente novamente."}, 500)

    async def limited_body(request, limit):
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) < 0:
                    raise ValueError()
                if int(length) > limit:
                    raise OverflowError()
            except ValueError:
                raise ValueError("Tamanho da solicitação inválido.") from None
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise OverflowError()
            data.extend(chunk)
        return data

    async def api_models(request):
        refused = model_access(request)
        if refused is not None:
            return refused
        return await model_result(models.view)

    async def api_model_op(request):
        refused = model_access(request, write=True)
        if refused is not None:
            return refused
        try:
            body = json.loads(await limited_body(request, MODEL_OP_LIMIT))
            if not isinstance(body, dict):
                raise ValueError()
        except OverflowError:
            return model_response({"ok": False, "error": "A solicitação da operação é grande demais."}, 413)
        except (ValueError, UnicodeError, RecursionError):
            return model_response({"ok": False, "error": "Formato da solicitação da operação inválido."}, 400)
        task=asyncio.current_task();update_commands.add(task)
        try:
            if updates.installing():return model_response({'ok':False,'error':'Uma atualização de software está em andamento. Aguarde a conclusão.'},409)
            return await model_result(lambda: models.handle(body, by=_client_desc(request)))
        finally:update_commands.discard(task)

    async def api_model_import(request):
        refused = model_access(request, write=True)
        if refused is not None:
            return refused
        # O nome original serve apenas para identificar o formato. O arquivo temporário usa um nome aleatório do sistema; nunca monta caminhos com dados do usuário.
        filename = request.query_params.get("filename", "")
        if not filename or len(filename) > 200 or any(c in filename for c in ("/", "\\", ":", "\x00")):
            return model_response({"ok": False, "error": "Selecione um pacote de implantação de modelo"}, 400)
        suffix = next((s for s in (".tar.gz", ".tgz", ".zip") if filename.lower().endswith(s)), None)
        if suffix is None:
            return model_response({"ok": False, "error": "Selecione um pacote de modelo nos formatos ZIP, tar.gz ou tgz"}, 400)
        name = request.query_params.get("name", "")
        if len(name) > 80:
            return model_response({"ok": False, "error": "O nome do modelo pode ter no máximo 80 caracteres"}, 400)
        async with model_upload_gate:
            temporary = None
            try:
                if updates.installing():return model_response({'ok':False,'error':'Uma atualização de software está em andamento. Aguarde a conclusão.'},409)
                length = request.headers.get("content-length")
                if length is not None and int(length) > MODEL_UPLOAD_LIMIT:
                    raise OverflowError()
                upload_dir = Path(state_dir or auth.dir) / "model-uploads"
                await asyncio.to_thread(upload_dir.mkdir, parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(suffix=suffix, dir=upload_dir)
                total = 0
                with os.fdopen(fd, "wb") as output:
                    async for chunk in request.stream():
                        total += len(chunk)
                        if total > MODEL_UPLOAD_LIMIT:
                            raise OverflowError()
                        await asyncio.to_thread(output.write, chunk)
                if not total:
                    raise ValueError("O pacote de implantação do modelo está vazio")
                return await model_result(lambda: models.import_package(Path(temporary), name=name))
            except OverflowError:
                return model_response({"ok": False, "error": "O pacote de implantação do modelo não pode exceder 64 MiB"}, 413)
            except ValueError as e:
                return model_response({"ok": False, "error": str(e) or "Formato de solicitação inválido"}, 400)
            finally:
                if temporary is not None:
                    await asyncio.to_thread(Path(temporary).unlink, missing_ok=True)

    async def meshes(request):
        """Modelo 3D de 2,8 MB: entrega diretamente o arquivo .gz pré-comprimido (sem comprimir na placa); o navegador mantém o cache por um dia."""
        raw = web_dir / "model" / "meshes.bin"
        gz = raw.with_suffix(".bin.gz")
        headers = {"Cache-Control": "public, max-age=86400", "Vary": "Accept-Encoding"}
        if gz.is_file() and "gzip" in request.headers.get("accept-encoding", ""):
            headers["Content-Encoding"] = "gzip"
            return FileResponse(gz, media_type="application/octet-stream", headers=headers)
        return FileResponse(raw, media_type="application/octet-stream", headers=headers)

    # ---- WebSocket ----

    def update_viewers():
        robotd.set_viewers(sum(1 for c in clients.values() if c["visible"]))

    tune_err = {"logged": False}

    def tune_view():
        """Gera o instantâneo do painel de calibração; em caso de erro, registra apenas uma ocorrência e retorna None (sem interromper toda a conexão da página)."""
        try:
            v = tune.view()
            tune_err["logged"] = False
            return v
        except Exception as e:  # noqa: BLE001
            if not tune_err["logged"]:
                tune_err["logged"] = True
                log.error("Falha ao montar os dados do painel de calibração", cat="Ajuste", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="É um problema do Studio. Exporte o pacote de diagnóstico e compartilhe; isso não afeta ficar em pé nem andar.")
            return None

    async def ws_endpoint(ws: WebSocket):
        token, sess = session_of(ws)
        if not origin_ok(ws):
            log.warn(f"Conexão da página rejeitada: origem inválida ({_client_desc(ws)})", cat="Conexão",
                     raw=f"Origin={ws.headers.get('origin')!r} Host={ws.headers.get('host')!r}",
                     hint="Isso não ocorre ao abrir a página do Microduck normalmente; rejeitar a conexão é correto se ela vier de outro site.")
            await ws.close(code=4403)
            return
        if not sess:
            log.info(f"A conexão da página não tinha uma sessão válida; solicitando novo login ({_client_desc(ws)})", cat="Conexão")
            await ws.accept()
            await ws.close(code=4401)
            return
        await ws.accept()
        by = _client_desc(ws)
        pad_conn = pad.new_conn() if pad is not None else None
        me = {"visible": True, "by": by, "hb_at": time.monotonic(), "route": None, "pad_visible": None}
        clients[ws] = me
        update_viewers()
        log.info(f"Página conectada ({by}; {len(clients)} no total)", cat="Conexão", dedup=False)
        logq = log.subscribe()
        send_lock = asyncio.Lock()

        async def send(obj):
            async with send_lock:
                await ws.send_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        loop = asyncio.get_running_loop()      # A gravação no programa principal roda em uma thread de segundo plano; o progresso é enviado à página por aqui.

        async def sender():
            await send({"t": "hello", "version": VERSION, "duck": duck})
            last_check = time.monotonic()
            last_imu = 0.0
            last_tune = 0.0
            pad_tick = 0
            pad_lists = None                    # Listas longas do controle enviadas anteriormente (só reenvia quando mudam; revisão O12).
            state_tick = 0
            onb_sent = None                     # Guia inicial enviado anteriormente (só inclui novamente quando muda; revisão de código C5).
            while True:
                quiet = time.monotonic() - me["hb_at"]
                if quiet > HB_DEAD_S:
                    # Background timer throttling must not end server-owned music.
                    # A matched native Pong renews transport liveness only: it never
                    # changes hb_at, visible viewers, drive-area state or ownership.
                    music = pad is not None and pad.motion_studio.background_music(pad_conn)
                    ping = ws.scope.get("extensions", {}).get("studio.websocket.ping")
                    transport_alive = music and time.monotonic() - me.get("pong_at", 0.) <= HB_DEAD_S
                    if music and not transport_alive and callable(ping):
                        transport_alive = await ping(MUSIC_PONG_TIMEOUT_S)
                        if transport_alive:
                            me["pong_at"] = time.monotonic()
                    if not transport_alive:
                        log.info(f"Página sem mensagens por {HB_DEAD_S:.0f} s e conexão não confirmada; considerando-a desconectada ({by})", cat="Conexão")
                        await ws.close(code=4408)
                        return
                if me["visible"] and quiet > HB_QUIET_S:
                    me["visible"] = False          # Sem heartbeat, considera a página invisível para evitar que robotd gere quadros sem necessidade.
                    update_viewers()
                if me["visible"]:
                    st = summarize(robotd, duck, servo, ob=onboard, bat=battery, net=net, commit=commit, auth=auth)
                    # O guia inicial tem cerca de 1 KB: se não mudar, não o envia a cada quadro (a página reutiliza a versão anterior); envia a lista completa uma vez por segundo (revisão de código C5,
                    # pelo mesmo mecanismo das listas longas do controle).
                    state_tick += 1
                    onb = st.get("onboarding")
                    if onb is not None and onb == onb_sent and state_tick % STATE_HZ != 0:
                        del st["onboarding"]
                        st["onboarding_same"] = True
                    else:
                        onb_sent = onb
                    await send(st)
                    # A tabela de servos ocupa 5,6 KB por quadro e só é usada na página de servos: envia apenas nessa página ou enquanto o barramento estiver sob controle (revisão O12 da reorganização do resumo).
                    if servo is not None and (me.get("route") == "/servos" or servo.state in ("open", "opening")):
                        # Com o barramento assumido, envia a tabela completa lida diretamente dele; sem assumir, monta uma tabela somente leitura com os dados do programa principal.
                        await send(servo.snapshot() if servo.state == "open"
                                   else view_from_robotd(robotd.bus.value, servo.directions, servo.state,
                                                         servo.error, servo.sim))
                    if imu is not None and time.monotonic() - last_imu >= 0.5:
                        last_imu = time.monotonic()        # A página da IMU precisa do chip, da orientação de montagem e do estado das leituras; atualizar a cada meio segundo é suficiente.
                        await send(imu.view())
                    if (tune is not None and time.monotonic() - last_tune >= 1.0
                            and me.get("route") in ("/", "/pad", "/settings")):     # Ainda não recebeu heartbeat (não sabe em qual página está); não envia por enquanto.
                        last_tune = time.monotonic()       # “Execução e calibração” no resumo e os modelos na página de configurações: uma vez por segundo (plano de ajuste T1–T3).
                        tv = tune_view()
                        if tv is not None:
                            await send(tv)
                    if pad is not None:
                        # Páginas com a área do controle na tela recebem 10 Hz; as demais, 1 Hz (suficiente para o cartão no painel). Considera apenas pad_visible no heartbeat;
                        # usa a rota como alternativa apenas para páginas antigas (revisão O1: #/pad agora é uma âncora no resumo e não garante que esteja visível).
                        pad_tick += 1
                        hot = me["pad_visible"] if me.get("pad_visible") is not None else me.get("route") == "/pad"
                        full = pad_tick % STATE_HZ == 0
                        if hot or full:
                            try:
                                snap = pad.safe_snapshot(conn=pad_conn)    # Não gera exceções; registra cada tipo de erro uma única vez.
                            except Exception:  # noqa: BLE001
                                snap = None
                            if snap is not None:
                                m = snap.get("motion") if isinstance(snap.get("motion"), dict) else None
                                if m is not None:
                                    lists = {k: m.get(k) for k in PAD_HEAVY}
                                    if not full and lists == pad_lists:
                                        snap = dict(snap, motion={k: v for k, v in m.items() if k not in PAD_HEAVY},
                                                    lists_same=True)
                                    else:
                                        pad_lists = lists
                                await send(snap)
                    await asyncio.sleep(1 / STATE_HZ)
                else:
                    await send({"t": "hb"})
                    await asyncio.sleep(1.0)
                if time.monotonic() - last_check > 5:
                    last_check = time.monotonic()
                    # Apenas verifica, sem renovar: a página estar aberta não significa que alguém esteja usando; a sessão expira após 12 horas sem atividade.
                    if session_of(ws, touch=False)[1] is None:
                        await ws.close(code=4401)
                        return

        async def log_forwarder():
            while True:
                entry = await logq.get()
                await send({"t": "log", "entry": entry})

        cmd_tasks = set()

        async def run_relax(cid):
            if pad is not None:
                pad.note_relax(by)
            try:
                if servo is not None and servo.state == "open":
                    # Com o robotd parado durante o controle dos servos, relaxa diretamente pelo barramento e confirma pela leitura de retorno (servo.relax_all).
                    accepted, reason = await asyncio.to_thread(servo.relax_all, by)
                elif servo is not None and servo.orphan and robotd.present is not True:
                    # A sessão anterior ficou aberta e não foi retomada (revisão D1): o robotd não está rodando, então enviar o comando a ele não funcionaria; é preciso assumir o barramento primeiro.
                    log.warn("Não foi possível relaxar o torque pelo barramento: a sessão de servos anterior não foi retomada", cat="Segurança", raw=f"by={by}",
                             hint="Assuma o barramento na página de servos e tente novamente; em uma emergência, desligue a alimentação.")
                    accepted, reason = False, "Talvez houvesse servos habilitados quando o Studio foi fechado. Assuma o barramento na página de servos antes de relaxar o torque (ou desligue a alimentação em uma emergência)."
                else:
                    accepted, reason = await robotd.relax(by)
            except Exception as e:  # noqa: BLE001 —— 不该发生；发生了也要给页面一个回执
                log.error("Falha do Studio ao processar o comando de relaxamento de torque", cat="Comando", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="É um erro do Studio. Primeiro use o botão − do controle ou desligue a alimentação; depois exporte o pacote de diagnóstico.")
                accepted, reason = False, f"Erro do Studio: {type(e).__name__}"
            try:
                await send({"t": "result", "id": cid, "ok": accepted, "reason": reason})
            except Exception:  # noqa: BLE001 —— 页面已经断了：卸力照样发出去了，回执送不到无所谓
                pass

        async def run_servo(name, cid, args=None):
            if servo is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "Este Microduck não tem um barramento de servos configurado"})
                return
            async with servo_gate:
                if name == "servo.open":
                    # Decisão do usuário em 10-18: assumir automaticamente ao abrir a página de servos. Não assumir enquanto o Microduck anda, executa uma rotina ou está se levantando; as articulações poderiam congelar no meio de um passo.
                    pose = summarize(robotd, duck, net=net, auth=auth)["posture"] if servo.state != "open" else None
                    if pose in ("walking", "policy", "homing"):
                        ok, why = False, "O Microduck está andando ou executando uma rotina. Pare-o ou faça-o sentar antes de abrir a página de servos (modo somente leitura no momento)."
                    else:
                        was_open = servo.state == "open"
                        if was_open:
                            # A sessão já estava aberta e pausada; não altera a consulta ao robotd, independentemente do resultado (revisão #3).
                            ok, why = await asyncio.to_thread(servo.open, by, (args or {}).get("port"))
                        else:
                            # Para assumir em um clique, pausa primeiro o programa principal (helper bus-take: não relaxa o torque, apenas sinaliza a posse). Se o helper não estiver instalado,
                            # deixa a verificação robotd_active de servo.open informar o erro.
                            robotd.set_paused(True, "controle de servos")
                            taken, take_why = await asyncio.to_thread(_bus_take, by, servo)
                            if not taken:
                                ok, why = False, take_why
                                if helper.flag_present():
                                    why = f"{why}. O programa principal está impedido de iniciar pelo sinalizador de posse. Resolva o problema e clique em “Conectar” para assumir; ao terminar, devolva o barramento. Você também pode reiniciar o Microduck."
                                robotd.set_paused(False)
                            else:
                                ok, why = await asyncio.to_thread(servo.open, by, (args or {}).get("port"))
                                if not ok:
                                    robotd.set_paused(False)
                                    # O programa principal foi pausado, mas o barramento não abriu: reinicia-o para não deixar o sinalizador impedir sua inicialização.
                                    asyncio.create_task(asyncio.to_thread(_bus_give_back, by, servo))
                                else:
                                    servo.orphan = servo.conflict_at = None
                                    servo.handed_back_at = None
                                    servo.handback_note = servo.giveback_error = servo.giveback_hint = None
                                    await remember_marker(by)
                elif (args or {}).get("if_idle"):
                    # Ao sair da página de servos, não devolve o barramento se houver servos habilitados (faz leitura imediata), se não conseguir ler o torque, se houver calibração/movimento em andamento ou se outra página ainda estiver na tela de servos.
                    # (Decisão do usuário em 10-18: sair da página deve manter os servos habilitados sem aliviar o torque; revisões D2 e D3.)
                    # O robotd do fork relaxa todos os servos ao iniciar (duck-control feetech.rs:1495 confirm_startup_limp), portanto a devolução é necessariamente suave;
                    # mantém a sessão do barramento aberta. Para devolver, use “Devolver ao programa principal” (sem if_idle).
                    done, kept = await leave_servos(f"Saiu da página de servos ({by})", ws, by)
                    if done:
                        ok, why = True, None
                    else:
                        log.info(f"Saiu da página de servos: {kept}; não devolvendo (sessão do barramento permanece aberta; clique em “Devolver ao programa principal” para devolver)", cat="Barramento",
                                 raw=f"by={by}", dedup=False)
                        ok, why = True, f"{kept}: não devolvido; sessão mantida"
                else:
                    ok, why = await hand_back(f"Clicou em “Devolver ao programa principal” ({by})", by)
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": why})
            except Exception:  # noqa: BLE001
                pass

        async def run_servo_op(cid, args):  # noqa: C901
            """Operações da página de servos (torque, controles deslizantes, movimento, calibração, busca, registradores etc.); servo_ops.handle roda em uma thread."""
            from .servo_ops import Refused
            data, ok, reason = None, True, None
            ops = servo.ops if servo is not None else None
            if ops is None:
                ok, reason = False, "O barramento de servos ainda não foi assumido. Atualize a página de servos e tente novamente."
            else:
                # Registra a operação no loop de eventos antes de iniciá-la na thread (revisão D2): se “manter” e “sair” chegarem juntos, a devolução espera a operação terminar e então lê o torque.
                try:
                    tok = servo.op_begin(args.get("op"))
                except Refused as e:
                    ok, reason, tok = False, str(e), None
                if tok is not None:
                    try:
                        data = await asyncio.to_thread(ops.handle, args, tok)
                    except Refused as e:
                        ok, reason = False, str(e)
                    except Exception as e:  # noqa: BLE001
                        ok, reason = False, f"Erro do Studio: {type(e).__name__}: {e}"
                        log.error(f"Falha na operação de servo: {args.get('op')}", cat="Barramento", raw=f"{type(e).__name__}: {e}", exc=True,
                                  hint="É um problema do Studio. Exporte o pacote de diagnóstico e compartilhe.")
                    finally:
                        servo.op_end(tok)
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_imu_op(cid, args):
            """Operações da página da IMU: por enquanto, apenas solve (calcular a orientação de montagem); gravação, calibração aproximada e troca do chip exigem conexão ao Microduck."""
            from .imu import Refused as ImuRefused
            data, ok, reason = None, True, None
            if imu is None:
                ok, reason = False, "O backend da página da IMU não está habilitado neste Microduck"
            else:
                try:
                    data = await imu.handle(args, by)
                except ImuRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Erro do Studio: {type(e).__name__}: {e}"
                    log.error(f"Falha na operação da IMU: {args.get('op')}", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="É um problema do Studio. Exporte o pacote de diagnóstico e compartilhe.")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_calib_op(cid, args):
            """上手清单第 3 步：「先看看要写什么」= 小助手 dry_run；「写进主程序」= 校验准备情况后交给小助手写、重启主程序。"""
            from .commit import Refused as CommitRefused
            op = args.get("op") if isinstance(args, dict) else None
            if commit is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开「写进主程序」"})
                return
            if op == "preview":
                try:
                    data = await asyncio.to_thread(commit.preview, by)
                except CommitRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("算「要写什么」时出错", cat="Calibração", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False,
                                "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            if op != "commit":
                await send({"t": "result", "id": cid, "ok": False, "reason": f"不认识的写入操作：{op}"})
                return
            try:
                view = commit.view(robotd, servo)
            except Exception as e:  # noqa: BLE001
                log.error("查「写进主程序」的准备情况时出错", cat="Calibração", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                return
            if not view.get("ready"):
                missing = [i for i in view.get("items") or [] if not i.get("ok")]
                reason = "还没准备好：" + "；".join(f"{i.get('label')}：{i.get('text')}" for i in missing[:3])
                if len(missing) > 3:
                    reason += "…"
                await send({"t": "result", "id": cid, "ok": False, "reason": reason, "data": {"readiness": view}})
                return
            # 先回执「开始写」，后面全在后台线程里：页面不能被 90 秒的重启卡住，卸力也照常能点
            await send({"t": "commit", "phase": "started", "msg": "开始写进主程序：会重启主程序（约 20 秒），鸭子会先卸力"})
            await send({"t": "result", "id": cid, "ok": True, "data": {"started": True, "readiness": view}})

            def progress(msg, detail=None):
                item = {"t": "commit", "phase": "running", "msg": msg}
                if isinstance(detail, dict):
                    item["detail"] = detail
                try:
                    asyncio.run_coroutine_threadsafe(send(item), loop)
                except Exception:  # noqa: BLE001 —— 页面断了不影响写
                    pass

            try:
                res = await asyncio.to_thread(commit.commit, by, progress)
            except Exception as e:  # noqa: BLE001
                log.error("写进主程序的后台任务出错", cat="Calibração", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="看看主程序有没有起来；原来的文件有没有换回去，日志里有")
                res = {"ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}", "detail": {}}
            await send({"t": "commit", "phase": "done" if res.get("ok") else "failed", "ok": bool(res.get("ok")),
                        "reason": res.get("reason"), "detail": res.get("detail") or {}})

        async def run_tune_op(cid, args):
            """调参卡 / 设置页模型的操作：这一版只有 save_body（导出档案用的重量，只存在 Studio 里）；改鸭子的一律拒。"""
            from .tune import Refused as TuneRefused
            data, ok, reason = None, True, None
            if tune is None:
                ok, reason = False, "这只鸭子没开调参卡的后端"
            else:
                try:
                    data = await tune.handle(args, by)
                except TuneRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"调参操作出错：{args.get('op')}", cat="Ajuste", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_pad_op(cid, args):
            """手柄页的操作：pad.handle 在线程里跑（搜索、配对、动作自己开后台线程，这里马上回）。"""
            data, ok, reason = None, True, None
            if pad is None:
                ok, reason = False, "这只鸭子没开手柄页的后端（台架模式）"
            else:
                try:
                    data = await asyncio.get_running_loop().run_in_executor(
                        pad.executor_for(args), lambda: pad.handle(args, by, pad_conn))
                except PadRefused as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"手柄操作出错：{args.get('op')}", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def onboard_op(cid, args):
            """上手清单上的按钮（只记一笔，不碰鸭子）：
                confirm_servo              舵机零位「已经校过，核对一下」（审查 O4；页面现在用「已完成」，老接口留着）
                done {step, confirmed}     「已完成」：我以前做过（用户 10-20：「去做、已完成、跳过，有三个也行」）
                skip {step, confirmed}     「跳过」：先不做（用户 10-18：「应该允许跳过、允许重新做」）
                undone / unskip {step, confirmed}   取消
            每一行任何时候都能点；有后果的（主程序明说没做完、读不到、测出了问题、测急停、调舵机时）要点两次，
            页面第二下才带 confirmed: true，后端按现在的情况再判一遍，没带就拒（不能只靠页面）"""
            op = args.get("op")
            if onboard is None:
                return {"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开上手清单"}
            what = {"confirm_servo": "「已经校过，核对一下」", "done": "「已完成」", "skip": "跳过", "unskip": "取消跳过",
                    "undone": "取消「已完成」"}.get(op)
            if what is None:
                return {"t": "result", "id": cid, "ok": False, "reason": f"不认识的指令：{op}"}
            step = str(args.get("step") or "")
            confirmed = args.get("confirmed") is True
            if op == "confirm_servo":
                ok, why = onboard.confirm_servo(robotd, by)
            elif op in ("done", "skip"):
                ok, why = onboard.mark(step, op, robotd, pad, servo, by, confirmed)
            else:
                ok, why = onboard.unmark(step, "skip" if op == "unskip" else "done", by, servo, confirmed)
            if ok:
                onboard.tick(robotd, pad, servo)               # 马上重判一次，页面不用等下一拍
                await asyncio.to_thread(onboard.save)
            else:
                log.info(f"上手清单{what}没记：{why}", cat="Calibração", step=step or "上手清单")
            return {"t": "result", "id": cid, "ok": ok, "reason": why}

        async def run_battery_op(cid, args):
            """设置页「电池」一栏：get / set / calibrate（studio/battery_svc.py）。只改 Studio 自己的设置，不碰鸭子。"""
            data, ok, reason = None, True, None
            if battery is None:
                ok, reason = False, "这只鸭子没开电量估算"
            else:
                try:
                    data = await battery.handle(args, by)
                except ValueError as e:
                    ok, reason = False, str(e)
                except Exception as e:  # noqa: BLE001
                    ok, reason = False, f"Studio 出错：{type(e).__name__}: {e}"
                    log.error(f"电池设置出错：{args.get('op')}", cat="Bateria", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
            try:
                await send({"t": "result", "id": cid, "ok": ok, "reason": reason, "data": data})
            except Exception:  # noqa: BLE001
                pass

        async def run_net_op(cid, args):
            """配网页：scan / connect / forget。connect 先回「开始切换」，真正关热点、连 WiFi 在后台做。"""
            from .net import Refused as NetRefused, validate_connect
            if net is None:
                await send({"t": "result", "id": cid, "ok": False, "reason": "这只鸭子没开配网"})
                return
            op = args.get("op")
            if op == "scan":
                try:
                    data = await net.scan()
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("扫 WiFi 出错", cat="Rede", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            if op == "connect":
                try:
                    ssid, psk = validate_connect(args.get("ssid"), args.get("psk"))
                    started = net.begin_connect()
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                if not started:
                    await send({"t": "result", "id": cid, "ok": False, "reason": "正在连，等一下"})
                    return
                # 先让页面收到回执（显示「正在切换……」），2 秒后 Net.connect 才动热点
                await send({"t": "result", "id": cid, "ok": True, "reason": "开始切换",
                            "data": {"ssid": ssid}})

                async def do_connect():
                    try:
                        await net.connect(ssid, psk, by)
                    except Exception as e:  # noqa: BLE001
                        net.busy = None
                        log.error("连 WiFi 的后台任务出错", cat="Rede", raw=f"{type(e).__name__}: {e}", exc=True,
                                  hint="这是 Studio 的问题，导出诊断包发出来")
                # 引用挂在 net 上，不挂在这个页面的 cmd_tasks：手机断开（热点一关就会断）以后页面的处理函数结束，
                # 后台这一路还要接着连完、写 last-try
                net.connect_task = asyncio.create_task(do_connect())
                return
            if op == "forget":
                try:
                    data = await net.forget(args.get("ssid"))
                except NetRefused as e:
                    await send({"t": "result", "id": cid, "ok": False, "reason": str(e)})
                    return
                except Exception as e:  # noqa: BLE001
                    log.error("忘掉 WiFi 出错", cat="Rede", raw=f"{type(e).__name__}: {e}", exc=True,
                              hint="这是 Studio 的问题，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}: {e}"})
                    return
                await send({"t": "result", "id": cid, "ok": True, "data": data})
                return
            await send({"t": "result", "id": cid, "ok": False, "reason": f"不认识的配网操作：{op}"})

        async def run_onboard_op(cid, args):
            try:
                out = await onboard_op(cid, args)
            except Exception as e:  # noqa: BLE001
                log.error("上手清单的按钮出错", cat="Sistema", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                out = {"t": "result", "id": cid, "ok": False, "reason": f"Studio 出错：{type(e).__name__}"}
            try:
                await send(out)
            except Exception:  # noqa: BLE001
                pass

        async def receiver():
            while True:
                msg = await ws.receive_json()
                me["hb_at"] = time.monotonic()
                if not isinstance(msg, dict):
                    continue
                t = msg.get("t")
                if t == "hb":
                    me["route"] = msg.get("route")
                    if isinstance(msg.get("pad_visible"), bool):
                        me["pad_visible"] = msg["pad_visible"]
                    vis = bool(msg.get("visible", True))
                    if vis != me["visible"]:
                        me["visible"] = vis
                        update_viewers()
                elif t == "cmd":
                    name, cid = msg.get("name"), msg.get("id")
                    args = msg.get('args') or {}
                    if updates.installing() and not safe_during_update(name,args):
                        await send({'t':'result','id':cid,'ok':False,'reason':'Uma atualização de software está em andamento. Aguarde a conclusão; a parada de emergência continua disponível.'})
                        continue
                    if (imu is not None and getattr(imu, 'blocks_updates', lambda: False)()
                            and name in {'pad.op', 'tune.op', 'servo.open', 'servo.op', 'calib.op'}
                            and not safe_during_update(name, args)):
                        await send({'t':'result','id':cid,'ok':False,
                                    'reason':'IMU 标定 / 类型切换会话未结束：先验证完成或取消；卸力仍可使用'})
                        continue
                    if name not in COMMANDS:
                        await send({"t": "result", "id": cid, "ok": False, "reason": f"这一版还不支持「{name}」"})
                        continue
                    if name == "imu.op":
                        task = asyncio.create_task(run_imu_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "calib.op":
                        task = asyncio.create_task(run_calib_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "tune.op":
                        task = asyncio.create_task(run_tune_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "pad.op":
                        task = asyncio.create_task(run_pad_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "onboard.op":
                        # 不在这里 await：写盘慢的时候也不能挡住后面来的卸力（代码审查 #6 同一个道理）
                        task = asyncio.create_task(run_onboard_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "net.op":
                        # 扫 WiFi 最坏约 10 秒、连 WiFi 在后台跑：都不挡住同一页面的卸力
                        task = asyncio.create_task(run_net_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "servo.op":
                        task = asyncio.create_task(run_servo_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "servo.ports":
                        from .servo import list_ports
                        ports = await asyncio.to_thread(list_ports)
                        await send({"t": "result", "id": cid, "ok": True, "data": {
                            "ports": ports, "port": servo.port if servo else None, "sim": bool(servo and servo.sim),
                            "state": servo.state if servo else None}})
                        continue
                    if name in ("servo.open", "servo.close"):
                        task = asyncio.create_task(run_servo(name, cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "battery.op":
                        task = asyncio.create_task(run_battery_op(cid, msg.get("args") or {}))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    if name == "relax":
                        # 卸力不在这里 await（代码审查 #6）：同一页面连按不排队，页面断了也不会把它取消
                        task = asyncio.create_task(run_relax(cid))
                        cmd_tasks.add(task)
                        update_commands.add(task)
                        task.add_done_callback(update_commands.discard)
                        task.add_done_callback(cmd_tasks.discard)
                        continue
                    # 进了 COMMANDS 却忘了写分支：明说，别默认当卸力（手柄页审查：每秒 10 次的 move 会全变成卸力）
                    log.error(f"指令「{name}」在 COMMANDS 里但没有处理分支", cat="Sistema", hint="这是 Studio 的 bug，导出诊断包发出来")
                    await send({"t": "result", "id": cid, "ok": False, "reason": f"Studio 没写「{name}」怎么处理（bug）"})

        tasks = [asyncio.create_task(f()) for f in (sender, log_forwarder, receiver)]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                    log.warn("页面连接出错", cat="Conexão", raw=f"{type(exc).__name__}: {exc}")
        finally:
            for t in tasks:
                t.cancel()
            log.unsubscribe(logq)
            clients.pop(ws, None)
            if pad is not None:
                pad.mark_gone(pad_conn)
                asyncio.get_running_loop().run_in_executor(None, pad.drop_client, pad_conn, by)
            update_viewers()
            log.info(f"页面断开（{by}，还剩 {len(clients)} 个）", cat="Conexão", dedup=False)

    # ---- 舵机会话：标记文件（审查 D1）、交还、离开、看 robotd（审查 D9） ----

    def marker_write(by):
        """开总线时写（线程里调）：先写临时文件再改名。回 True / False；写不进去只记 warn
        （重启以后就不知道上次还开着，但会话不能因此关掉：舵机可能正保持着）。"""
        if marker is None:
            return True
        data = {"v": 1, "port": servo.port, "sim": bool(servo.sim), "at": time.time(), "by": by,
                "boot_id": boot_id()}
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            tmp = marker.with_name(marker.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, marker)
            return True
        except OSError as e:
            log.warn("舵机会话的标记没写进去", cat="Barramento", step=str(marker), raw=f"{type(e).__name__}: {e}",
                     hint="Studio 重启以后就不知道上次还有舵机保持着；看看 state 目录满没满、有没有权限")
            return False

    async def remember_marker(by):
        """写会话标记并把它写没写进去记到 servo.marker_error（页面提示条用）。"""
        ok = await asyncio.to_thread(marker_write, by)
        servo.marker_error = None if ok else (
            "会话标记没写进去：Studio 重启后不知道这里还开着。别重启 Studio，用完点「交还主程序」")
        return ok

    def marker_drop():
        if marker is None:
            return
        try:
            marker.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warn("舵机会话的标记删不掉", cat="Barramento", step=str(marker), raw=f"{type(e).__name__}: {e}",
                     hint="下次 Studio 起来会以为上次还开着、去接管一次总线；看看 state 目录的权限")

    def marker_read():
        """(在不在, 内容)：内容 None = 文件坏了（读不出、不是 JSON 对象）。"""
        if marker is None:
            return False, None
        try:
            raw = marker.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, None
        except OSError:
            return True, None
        try:
            d = json.loads(raw)
        except ValueError:
            return True, None
        return True, d if isinstance(d, dict) else None

    async def robotd_up():
        """robotd 的 socket 连得上吗（连上就关，不说话）。台架模式没有 robotd。"""
        addr = getattr(robotd, "addr", "none")
        if not addr or addr == "none":
            return False
        try:
            _, w = await asyncio.wait_for(open_conn(addr), 1.0)
        except Exception:  # noqa: BLE001 —— 连不上、超时都算不在
            return False
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass
        return True

    async def handed_back(why, by=None):
        """总线已经卸力、关了：恢复跟主程序的轮询、起主程序、按结果删 / 留标记、记一行（每次都记：审查 D13）。"""
        servo.handed_back_at = time.monotonic()
        servo.orphan = None
        servo.marker_error = None
        servo.giveback_error = servo.giveback_hint = None
        robotd.set_paused(False)
        log.info(f"交还主程序：{why}", cat="Barramento", dedup=False)
        # 一键交还：起主程序（小助手 bus-give-back soft：撤旗、起 robotd、等启动四步成功）。
        # 标记等起完再删：没起来、旗还在的话留着，Studio 重启才能接着管（审查 #4）
        ok, gb_why = await asyncio.to_thread(_bus_give_back, by or "Studio", servo)
        if ok:
            await asyncio.to_thread(marker_drop)
            if servo.helper_available is False:
                log.warn("交还了；没装小助手，主程序要手动起：sudo systemctl start robotd", cat="Barramento", dedup=False)
            else:
                log.info("主程序起来了", cat="Barramento", dedup=False)
        else:
            servo.giveback_error = gb_why
            flag = await asyncio.to_thread(helper.flag_present)
            if flag:
                servo.giveback_hint = ("旗还在：手动 start robotd 会被挡住。再进一次舵机页、再点交还；"
                                       "或者重启鸭子（旗在 /run，重启就没了）")
            elif getattr(servo, "giveback_stuck", False):
                servo.giveback_hint = "主程序在回话，只是一直报启动阶段：多半是旧版主程序的毛病，去日志页看它最后说了什么"
                await asyncio.to_thread(marker_drop)
            else:
                servo.giveback_hint = "手动 sudo systemctl start robotd，或者再进一次舵机页再交还"
                await asyncio.to_thread(marker_drop)
            log.error(f"主程序没起来：{gb_why}", cat="Barramento", dedup=False, hint=servo.giveback_hint)

    async def hand_back(why, by=None):
        """点「交还主程序」：先置 closing、等在路上的舵机操作做完（等不到不交还），再在总线上全部卸力并回读确认
        （不指望主程序启动时卸力，审查 S1），再关总线、起主程序（handed_back，审查 D2）。"""
        if servo is None or servo.state != "open":
            return True, None
        ok, reason = await asyncio.to_thread(servo.hand_back_bus, why, before_close=lambda: robotd.set_paused(False))
        if not ok:
            log.error("没交还主程序", cat="Barramento", raw=reason, hint="等校准 / 动作做完再点「交还主程序」", dedup=False)
            return False, reason
        servo.handback_note = reason          # 成功时第二个值是「哪几颗没确认卸力」的提示；全确认是 None
        await handed_back(why, by)
        return True, None

    async def leave_servos(why, ws=None, by=None):
        """离开舵机页 / 没人在看：别的页面还在舵机页、校准 / 运动在跑、当场读到有保持的或读不到的 → 不交还，回 (False, 原因)；
        否则卸力、关总线、起主程序，回 (True, None)（审查 D2、D3）。"""
        others = sum(1 for w, c in clients.items() if w is not ws and c.get("route") == "/servos")
        if others:
            return False, f"还有 {others} 个页面在舵机页"
        verdict, info = await asyncio.to_thread(servo.leave, why, before_close=lambda: robotd.set_paused(False))
        if verdict == "handed_back":
            await handed_back(why, by)
            return True, None
        if verdict == "closed":
            return True, None
        return False, info["why"]

    async def robotd_conflict():
        """会话期间 robotd 被手动起来了（审查 D9）：它起来就把舵机全部松开、还跟 Studio 抢同一个串口。
        Studio 关总线（不写舵机）、删标记、恢复轮询，提示条变红。"""
        async with servo_gate:
            if servo.state != "open" or servo.closing:
                return
            await asyncio.to_thread(servo.close)
            servo.conflict_at = time.monotonic()
            await asyncio.to_thread(marker_drop)
            servo.marker_error = None
            robotd.set_paused(False)
        log.error("主程序被手动起来了：它会把舵机全部松开、跟 Studio 抢串口", cat="Barramento", step="会话期间查 robotd 的 socket",
                  hint="Studio 已经关掉舵机总线（没写舵机）。下次别手动起 robotd：先在页面上点「交还主程序」", dedup=False)

    async def servo_restore():
        """Studio 起来时：上次退出时舵机会话开着（有标记）→ robotd 不在就重新接管总线（只读打开，不改扭矩），恢复会话
        和提示条；接管不上 → 记成 orphan（提示条、卸力按钮引导去舵机页）；robotd 在 → 它起来时已经全部松开，删标记（审查 D1）。"""
        if servo is None:
            return
        if updates.installing():
            log.warn('A proteção de atualização do programa principal continua ativa: a retomada automática da sessão dos servos está pausada. Restaure o programa principal na página de atualização.',cat='Barramento')
            return
        there, data = await asyncio.to_thread(marker_read)
        if not there:
            return
        if data is None:
            log.warn("舵机会话的标记坏了：照上次开着处理（用默认的串口）", cat="Barramento", step=str(marker),
                     hint="多半是写到一半断电了；不影响用")
            data = {}
        here = boot_id()
        if isinstance(data, dict) and data.get("boot_id") and here and data["boot_id"] != here:
            log.info("上次开机留下的舵机会话标记：断过电，舵机早就松了，作废", cat="Barramento", dedup=False)
            await asyncio.to_thread(marker_drop)
            return
        if await robotd_up():
            log.info("上次 Studio 退出时舵机会话开着；主程序现在在跑（它起来时会把舵机全部松开）：不接管", cat="Barramento",
                     dedup=False)
            await asyncio.to_thread(marker_drop)
            return
        port = "sim" if data.get("sim") is True else (data.get("port") if isinstance(data.get("port"), str) else None)
        async with servo_gate:
            if servo.state == "open":
                return
            robotd.set_paused(True, "调舵机（接着上次的会话）")
            # 恢复会话跟网页进舵机页一个样：先 bus_take 立旗（robotd 起不来、管理锁在、确认串口空），再开串口。
            # 不立旗就开串口，robotd 一起来会跟 Studio 抢同一个总线
            taken, take_why = await asyncio.to_thread(_bus_take, "Studio 重启后接着管", servo)
            if not taken:
                ok, why = False, take_why
                servo.orphan = {"why": take_why, "at": time.monotonic()}
                robotd.set_paused(False)
                # bus-take 半路失败可能已经把旗立了：起主程序回滚（撤旗 + 起 robotd），别留个旗让主程序一直起不来
                asyncio.create_task(asyncio.to_thread(_bus_give_back, "Studio 重启后接着管", servo))
            else:
                ok, why = await asyncio.to_thread(servo.open, "Studio 重启后接着管", port, True)
                if ok:
                    servo.orphan = None
                    servo.handed_back_at = None
                    servo.handback_note = servo.giveback_error = servo.giveback_hint = None
                    await remember_marker(data.get("by") if isinstance(data.get("by"), str) else "Studio 重启后接着管")
                else:
                    servo.orphan = {"why": why, "at": time.monotonic()}
                    robotd.set_paused(False)
                    # 主程序停了、总线却没开成：起回来，别留个旗让主程序一直起不来
                    asyncio.create_task(asyncio.to_thread(_bus_give_back, "Studio 重启后接着管", servo))
        if ok:
            log.info(f"会话恢复：上次 Studio 退出时舵机会话开着，重新接管了总线（只读打开，没改扭矩；{servo.holding()} 颗保持着）",
                     cat="Barramento", dedup=False)
        else:
            log.error("上次 Studio 退出时舵机会话开着，这次没接管上：可能还有舵机保持着", cat="Barramento", raw=why, dedup=False,
                      hint="去舵机页接管后才能卸力；急的话关电源")

    async def servo_watch():
        """每秒一拍：
        - 舵机页没人在看超过 SERVO_IDLE_S：没有舵机保持着（当场读，读不到的当在保持）就自动交还（页面关了、断网时主程序
          别一直停着、手柄一直不能用）。有保持着的：不交还、不卸力（用户定过「没人操作不自动卸力」；交还会让 robotd 起来时
          全部松开），只记一行 warn（同一句 1 分钟只记一次）；
        - 会话期间 5 秒看一眼 robotd 起没起来（审查 D9）；
        - 交还以后 / 没接管上的标记：主程序连上（交还之后有新回包）才清掉提示（审查 D12）。"""
        since = None
        last_probe = last_try = 0.0
        while True:
            await asyncio.sleep(1.0)
            if servo is None:
                continue
            now = time.monotonic()
            if servo.state != "open":
                since = None
                fresh = robotd.present is True and robotd.bus.at is not None
                if servo.handed_back_at is not None and fresh and robotd.bus.at > servo.handed_back_at and not robotd.paused:
                    servo.handed_back_at = None                    # 主程序连上了：「已交还……手动起 robotd」那句收起来
                    servo.handback_note = None
                    servo.giveback_error = servo.giveback_hint = None
                if servo.orphan and fresh and robotd.bus.at > servo.orphan["at"] and not robotd.paused:
                    servo.orphan = None                            # 主程序起来了（它会全部松开）：不用再去接管
                    await asyncio.to_thread(marker_drop)
                    log.info("上次退出时开着的舵机会话：主程序起来了（它会把舵机全部松开），不用再接管", cat="Barramento", dedup=False)
                continue
            probe = servo.probe_robotd if servo.probe_robotd is not None else not servo.sim
            if probe and now - last_probe >= ROBOTD_PROBE_S and not servo.closing:
                last_probe = now
                if await robotd_up():
                    await robotd_conflict()
                    continue
            here = sum(1 for c in clients.values() if c.get("route") == "/servos")
            if here:
                since = None
            elif since is None:
                since = now
            elif now - since > SERVO_IDLE_S and now - last_try >= 5.0:
                last_try = now                                     # 有保持着的时候 5 秒再看一次（当场读扭矩）
                async with servo_gate:
                    if servo.state != "open":
                        continue
                    done, kept = await leave_servos(f"舵机页 {SERVO_IDLE_S:.0f} 秒没人在看，也没有舵机保持着", by="Studio 自动交还")
                if done:
                    since = None
                else:
                    log.warn(f"舵机页没人在看，但{kept}：不自动交还、不卸力", cat="Barramento", raw=kept,
                             hint="要交还点页面顶上的「交还主程序」；交还以后舵机会全部松开，先扶住")

    async def pad_feed():
        """robotd 的回读 10 Hz 交给手柄页的后端，不管有没有页面在看（测急停、动作、卸力后 2 秒的保护都靠它）。"""
        while True:
            await asyncio.sleep(1 / STATE_HZ)
            try:
                # A server-owned music lease consumes real robot.state frames
                # even after the last browser viewer leaves the drive area.
                robotd.set_background_music(pad.motion_studio.background_music())
                pad.feed_robot(robot_view(robotd))
            except Exception as e:  # noqa: BLE001
                log.error("把主程序的状态交给手柄页时出错", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来")
                await asyncio.sleep(1.0)

    async def onboard_loop():
        """上手清单、主板温度的回差：0.5 秒判一次（只改内存），记录变了在线程里写盘（审查 O6：只在这一处判、只在这里写）。"""
        while True:
            await asyncio.sleep(ONBOARD_TICK_S)
            try:
                # 读文件（servo-calib 目录、robotd 不报温度时的 /sys/class/thermal）放线程里：SD 卡一卡不能挡住
                # 同一个事件循环里的卸力（代码审查 C9-1）。tick 本身只用内存
                await asyncio.to_thread(onboard.io, onboard.need_board(robotd))
                if pad is not None:
                    pad.battery_shutdown = onboard.battery_shutdown   # 手柄页的低电文案照 robotd 配置说（任务 1 附）
                if onboard.tick(robotd, pad, servo):
                    await asyncio.to_thread(onboard.save)
            except Exception as e:  # noqa: BLE001
                log.error("上手清单判的时候出错", cat="Sistema", raw=f"{type(e).__name__}: {e}", exc=True,
                          hint="这是 Studio 的问题，导出诊断包发出来；不影响站和走")
                await asyncio.sleep(5.0)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        await updates.start_readiness(update_readiness)
        watch = asyncio.create_task(servo_watch())
        feed = asyncio.create_task(pad_feed()) if pad is not None else None
        ob_task = asyncio.create_task(onboard_loop()) if onboard is not None else None
        bat_task = asyncio.create_task(battery.loop()) if battery is not None else None   # 电量估算 1 Hz（审查 B-R7）
        tune_task = asyncio.create_task(tune.loop()) if tune is not None else None     # 调参卡读文件 2 秒一次（线程里）
        robotd.start()
        if net is not None:
            net.start()
        restore = asyncio.create_task(servo_restore())        # 上次退出时舵机会话开着：接着管（审查 D1）
        log.info(f"Studio {VERSION} 启动 · Python {platform.python_version()} · {platform.node()}", cat="Sistema",
                 dedup=False)
        yield
        await updates.stop_readiness()
        restore.cancel()
        watch.cancel()
        if tune_task is not None:
            tune_task.cancel()
        if bat_task is not None:
            bat_task.cancel()
        if ob_task is not None:
            ob_task.cancel()
            await asyncio.to_thread(onboard.save)
        if feed is not None:
            feed.cancel()
            await asyncio.to_thread(pad.close)
        if servo is not None and servo.state != "closed":
            # Studio 退出不卸力（审查 D1）：只关串口，保持着的舵机照样保持；标记留着，下次起来接着管
            n = servo.holding()
            await asyncio.to_thread(servo.close)
            log.info(f"Studio 退出：舵机会话开着（{n} 颗保持着），不卸力；下次起来会接着管", cat="Barramento", dedup=False)
        if net is not None:
            await net.stop()
        await robotd.stop()
        auth.flush()
        log.info("Studio 停止", cat="Sistema", dedup=False)
        log.flush()

    routes = [
        Route("/healthz", healthz),
        Route("/api/session", api_session),
        Route("/api/ai", api_ai, methods=["GET", "POST"]),
        Route('/api/updates',api_updates,methods=['GET','POST']),
        Route('/api/updates/upload',api_updates,methods=['POST']),
        Route("/api/login", api_login, methods=["POST"]),
        Route("/api/logout", api_logout, methods=["POST"]),
        Route("/api/password", api_password, methods=["POST"]),
        Route("/api/ssh", api_ssh, methods=["POST"]),
        Route("/api/logs", api_logs),
        Route("/api/diag", api_diag),
        Route("/api/profile", api_profile),
        Route("/api/camera", api_camera),
        Route("/api/tof", api_tof),
        Route("/api/models", api_models),
        Route("/api/models/op", api_model_op, methods=["POST"]),
        Route("/api/models/import", api_model_import, methods=["POST"]),
        Route("/model/meshes.bin", meshes),
        WebSocketRoute("/ws", ws_endpoint),
        Mount("/", AppStatic(directory=str(web_dir), html=True)),
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    return HostGuard(app, guard, log)


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"（没拿到：{type(e).__name__}: {e}）"


def _diag_zip(log, snap, raw):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("先看我.txt", "Microduck Studio 诊断包\n\n"
                   "里面有：最近两天的 Studio 日志、导出时的状态、robotd 原始回包、版本、robotd/padd 的系统日志。\n"
                   "注意：含鸭子的序列号和局域网 IP。发到公开的群之前，介意的话先删掉 system.txt 和 robotd-raw.json。\n")
        for p in log.files(days=2):
            z.write(p, f"logs/{p.name}")
        z.writestr("state.json", json.dumps(snap, ensure_ascii=False, indent=1, default=str))
        z.writestr("robotd-raw.json", json.dumps(raw, ensure_ascii=False, indent=1, default=str))
        info = {"studio": VERSION, "python": sys.version, "platform": platform.platform(),
                "log": log.snapshot(), "time": time.strftime("%F %T %z")}
        z.writestr("versions.json", json.dumps(info, ensure_ascii=False, indent=1))
        deps = Path(__file__).resolve().parents[1] / "deps" / "VERSIONS.txt"
        if deps.is_file():
            z.write(deps, "deps-VERSIONS.txt")
        if sys.platform.startswith("linux"):
            z.writestr("journal-robotd.txt", _run(["journalctl", "-u", "robotd", "-n", "300", "--no-pager", "-o", "short-iso"]))
            z.writestr("journal-padd.txt", _run(["journalctl", "-u", "padd", "-n", "100", "--no-pager", "-o", "short-iso"]))
            z.writestr("system.txt", "\n".join(_run(c) for c in (["uptime"], ["free", "-m"], ["df", "-h", "/"], ["ip", "-brief", "addr"])))
    return buf.getvalue()


def precompress(web_dir):
    """meshes.bin 先压一份 .gz（只在 .gz 比原文件旧时重压）。"""
    raw = Path(web_dir) / "model" / "meshes.bin"
    gz = raw.with_suffix(".bin.gz")
    try:
        if raw.is_file() and (not gz.is_file() or gz.stat().st_mtime < raw.stat().st_mtime):
            with open(raw, "rb") as f, gzip.open(gz, "wb", compresslevel=9) as g:
                g.write(f.read())
    except OSError:
        # 网页目录只读（装到 /opt、换专用用户以后）：不压了，直接给原文件
        return None
    return gz
