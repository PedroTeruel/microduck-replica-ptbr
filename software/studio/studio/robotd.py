"""Comunicação com os serviços do robô: quatro conexões robotd + uma conexão configd (review-impl-plan I4).

| Conexão | Função                                                        |
| stream  | robot.subscribe {"hz":10}. Abre quando alguém está vendo e fecha 10 s após a última pessoa sair |
| poll    | hello (uma vez), health 2 s, busStatus 1 s (10 Hz ao confirmar torque desligado), policies 2 s, calibration-status (ao conectar e quando phase vira control; só vale após este hello) |
| cmd     | Comandos de movimento (usado somente em S1b)                  |
| Torque  | Envia apenas robot.relax; abre uma conexão nova a cada chamada |
| Inicialização | robot.startupSubscribe: abre se alguma das quatro etapas deste hello não tiver sucesso; fecha quando todas passam ou uma falha (startup.py) |
| configd | pad.status a cada 5 s; system.info a cada 60 s                 |

Por que separar: cada conexão robotd processa uma solicitação por vez; o comando para desligar o torque não pode ficar atrás de um busStatus com timeout de 2 segundos.
Por que só abrir a assinatura quando alguém estiver vendo: com qualquer assinante, a thread de controle do robotd precisa montar um quadro a cada ciclo (independentemente de hz);
sem espectadores, evitamos trabalho desnecessário (review-tech-v3 T4).

Todos os intervalos usam time.monotonic(): se o robô iniciar sem rede, o relógio do sistema pode ficar em 1970 (I12).
Este módulo **não importa nenhum recurso serial**: esta versão do Studio não tem nenhum caminho que abra ttyS2 (I1).
"""
import asyncio
import time

from .estop import CONFIRM_TIMEOUT_S, JOIN_S, RESEND_AT_S, STARTING_PHASES, EStop, evidence
from .log import log_cmd
from .rpc import Conn, RpcError, Timeout, Unreachable, call_once, encode, open_conn, read_message
from .startup import StartupTrack, startup_loop

API_VERSION = 40                     # duck-ipc-proto/src/lib.rs:437; divergências são registradas, mas não bloqueiam
KNOWN_BUILDS = ("1fa8438-feetech-ft6-control.43", "4734cbb-feetech-imu-auto-control.44")
BACKOFF = (0.5, 1.0, 2.0, 5.0)
STREAM_HZ = 10
STREAM_LINGER_S = 10.0


class Sample:
    __slots__ = ("value", "at", "error")

    def __init__(self):
        self.value, self.at, self.error = None, None, None

    def set(self, value):
        self.value, self.at, self.error = value, time.monotonic(), None

    def fail(self, error):
        self.error = str(error)

    def age(self, now=None):
        if self.at is None:
            return None
        return (time.monotonic() if now is None else now) - self.at


class Robotd:
    def __init__(self, robotd_addr, configd_addr, log):
        self.log = log
        self.addr = robotd_addr
        self.poll = Conn(robotd_addr, "poll", log)
        self.cmd = Conn(robotd_addr, "cmd", log)
        self.cfg = Conn(configd_addr, "configd", log)
        self.hello, self.health, self.bus = Sample(), Sample(), Sample()
        self.policies, self.calib, self.state = Sample(), Sample(), Sample()
        self.pad, self.sysinfo = Sample(), Sample()
        self.present = None          # indica se o socket robotd existe; None = ainda não verificado
        self.absent_since = None
        self.estop = EStop()
        self.viewers = 0             # número de páginas visíveis
        self.force_subscribe = False
        self.background_music = False  # consumidor interno de ações; não conta como página visível
        self.stream_open = False
        self._last_viewer_at = 0.0
        self._tasks = []
        self._wake_stream = asyncio.Event()
        self._due = {"health": 0.0, "bus": 0.0, "policies": 0.0}   # horário da próxima consulta de cada item (monotonic)
        self._fails = {}             # falhas consecutivas por item
        self._relax_send = None      # envio de desligamento de torque em andamento (asyncio.Task)
        self._relax_send_started = 0.0
        self._relax_watch = None     # reenvio e monitoramento de timeout do comando de desligamento do torque
        self._calib_task = None
        # O estado de calibração (calibration-status) só vale se lido após este hello (revisão O5 da reorganização do painel): depois que o robotd reinicia,
        # não confie no antigo “15 servos calibrados” durante os 20 segundos iniciais, antes de abrir o barramento. None = ainda não houve hello (também vale para objetos simulados nos testes)
        self.calib_valid_after = None
        self._last_phase = None
        # instante (monotonic) em que busStatus começou a informar a fase de inicialização após esta conexão; None fora dessa fase. Após 30 segundos, a interface passa a informar
        # “continua inicializando” (teste em hardware real em 20/10: o modo de calibração do fork antigo informa configuring_bus indefinidamente)
        self.starting_since = None
        self._wake_poll = asyncio.Event()   # desperta a consulta durante o sono de espera quando o torque é desligado
        self._loop = None                   # event loop usado para despertar a consulta com segurança entre threads quando set_paused é chamado
        self.paused = None                  # o robotd é pausado intencionalmente ao ajustar os servos: suspende as consultas sem informar que o programa principal está ausente
        self.startup = StartupTrack()       # quatro etapas de inicialização (gravadas por startup_loop em startup.py; lidas pelo cartão de ajustes e pela lista de tarefas)

    # ---- Ciclo de vida ----

    def start(self):
        loop = asyncio.get_running_loop()
        self._loop = loop
        if self.addr == "none":
            # Modo de bancada: sem firmware no controlador principal; ajusta os servos no computador com a placa de depuração, sem conexão ao programa principal
            self.log.info("Modo de bancada: sem conexão ao robotd principal", cat="robotd")
            self._tasks = []
            return
        self._tasks = [loop.create_task(self._supervise("consulta", self._poll_loop), name="robotd-poll"),
                       loop.create_task(self._supervise("assinatura de estado em tempo real", self._stream_loop), name="robotd-stream"),
                       loop.create_task(self._supervise("consulta configd", self._configd_loop), name="configd-poll"),
                       loop.create_task(self._supervise("assinatura das etapas de inicialização", lambda: startup_loop(self)), name="robotd-startup")]

    async def stop(self):
        # Aguarda o envio do desligamento de torque em andamento (no máximo 1 s), sem interrompê-lo ao fechar o Studio
        if self._relax_send is not None and not self._relax_send.done():
            await asyncio.wait({self._relax_send}, timeout=1.0)
        tasks = [t for t in self._tasks + [self._relax_send, self._relax_watch, self._calib_task]
                 if t is not None]
        for t in tasks:
            t.cancel()
        for c in (self.poll, self.cmd, self.cfg):
            c.close()
        # Após cancelar, aguarda as tarefas realmente terminarem. Se não aguardar, uma tarefa pode ficar parada depois que o future retorna e antes da próxima etapa,
        # deixando uma tarefa cancelada que nunca desperta e travando _cancel_all_tasks nos testes ou no encerramento.
        # Como limite de segurança, espera no máximo 2 s para que o Studio ainda consiga encerrar.
        pending = [t for t in tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=2.0)

    async def _supervise(self, name, fn):
        """Nenhuma falha inesperada pode encerrar silenciosamente um loop em segundo plano (revisão de código #4): registra o erro completo e reinicia após 1 s."""
        while True:
            try:
                await fn()
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.log.error(f"A tarefa em segundo plano “{name}” falhou; reiniciando em 1 s", cat="Sistema", raw=f"{type(e).__name__}: {e}",
                               hint="Este é um erro do Studio; envie o pacote de diagnóstico", exc=True)
                await asyncio.sleep(1.0)

    def set_paused(self, on, why=None):
        if on and not self.paused:
            self.paused = why or "pausado"
            self.log.info(f"Consultas ao programa principal pausadas ({self.paused})", cat="robotd", hint="O programa principal está pausado intencionalmente; não é um erro")
        elif not on and self.paused:
            self.log.info(f"Consultas ao programa principal retomadas (fim de {self.paused})", cat="robotd")
            self.paused = None
            # Quando chamado pela thread dos servos (para retomar as consultas antes de fechar o barramento), não chame Event.set diretamente: no modo de depuração, Future.set_result
            # marca o evento como concluído antes de lançar um erro ao agendar entre threads, e a tarefa em espera nunca desperta.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                if self._loop is not None and not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._wake_poll.set)
            else:
                self._wake_poll.set()

    def set_viewers(self, n):
        n = max(0, n)
        if n and not self.viewers:
            self._wake_stream.set()
        if self.viewers and not n:
            self._last_viewer_at = time.monotonic()
        self.viewers = n

    def set_background_music(self, on):
        on = bool(on)
        if on != self.background_music:
            self.background_music = on
            self._wake_stream.set()

    # ---- Desligamento do torque ----

    async def relax(self, by):
        """Pressiona para desligar o torque e retorna (se foi enviado, motivo). A confirmação é feita pela leitura de busStatus (estop.on_bus).

        - O envio roda em uma tarefa independente e não é cancelado se o chamador (conexão da interface) cair (revisão de código #6)；
        - No máximo um envio fica em andamento por vez; pressionar repetidamente é equivalente a uma única solicitação；
        - A tarefa de monitoramento reenvia após 2 s e encerra após confirmação ou timeout de 8 s (revisão de código #1)。"""
        now = time.monotonic()
        self.estop.press(by, now)
        self._due["bus"] = 0.0          # antecipa a próxima consulta busStatus: começa a ler novamente a cada 0,1 s
        self._wake_poll.set()           # desperta as consultas se estiverem no intervalo de espera (robotd acabou de voltar)
        loop = asyncio.get_running_loop()
        # Se o envio em andamento começou há pouco (<0,3 s), aguarda-o; se já está em andamento há mais tempo (robotd travado), envia outro para não perder esta pressão (revisão #3)
        if (self._relax_send is None or self._relax_send.done()
                or now - self._relax_send_started > JOIN_S):
            self._start_send(by, "Desligar torque")
        if self._relax_watch is None or self._relax_watch.done():
            self._relax_watch = loop.create_task(self._watch_relax())
        return await asyncio.shield(self._relax_send)

    def _start_send(self, by, what):
        started = time.monotonic()
        self._relax_send_started = started
        self._relax_send = asyncio.get_running_loop().create_task(self._send_relax(by, what, started))

    async def _send_relax(self, by, what, started):
        """Abre uma nova conexão para cada envio (revisão de código #2: conexões ociosas por muito tempo deixam de funcionar após reiniciar o robotd).
        Se não conectar, tenta novamente após 0,1 s (o socket pode ficar indisponível por um instante durante a reinicialização do robotd).
        Nenhuma etapa anterior ao envio pode falhar: erros de log não devem ser propagados e a leitura dos campos do estado atual não conta como falha (revisão #1)."""
        with log_cmd(self.log, what, "robot.relax", who=by,
                     ctx={"mode": self._mode(), "phase": self._phase()}) as t:
            r = None
            for attempt in (1, 2):
                try:
                    r = await call_once(self.addr, "robot.relax", {}, timeout=3.0, name="Desligar torque", log=self.log)
                    break
                except Unreachable as e:
                    if attempt == 1:
                        await asyncio.sleep(0.1)
                        continue
                    return self._relax_failed(t, started, f"Não foi possível enviar: {e}")
                except (Timeout, RpcError) as e:
                    return self._relax_failed(t, started, f"Não foi possível enviar: {e}")
            if isinstance(r, dict) and r.get("accepted") is False:
                return self._relax_failed(t, started, f"O programa principal não aceitou desligar o torque: {r.get('reason') or 'motivo não informado'}", reply=r)
            self.estop.sent(started)
            self._mark_present(True)        # robotd respondeu e está ativo (as consultas talvez ainda estejam aguardando o intervalo e não tenham detectado seu retorno)
            note = "Enviado; aguardando confirmação pela leitura de retorno"
            if not (isinstance(r, dict) and "accepted" in r):
                note += "（A resposta não contém o campo accepted; a leitura de retorno será considerada definitiva）"
            t.ok(r, note=note)
            return True, None

    def _relax_failed(self, t, started, why, reply=None):
        t.fail(why, hint="Para pará-lo, use o botão − do controle ou desligue a alimentação", raw=reply)
        self.estop.send_failed(started, why)
        return False, why

    async def _watch_relax(self):
        while self.estop.active:
            el = self.estop.elapsed()
            if el >= CONFIRM_TIMEOUT_S:
                bus = self.bus.value
                why = "O desligamento do torque não foi confirmado após 8 s"
                if self.estop.send_error:
                    why += f"（erro no reenvio: {self.estop.send_error}）"
                self.estop.finish("timeout", why)
                self.log.error("O desligamento do torque não foi confirmado após 8 s", cat="Segurança", step="leitura de retorno de busStatus",
                               ctx=dict(evidence(bus), bus_age_s=_round(self.bus.age()),
                                        saw_torque_off=self.estop.saw_off, send_error=self.estop.send_error),
                               hint="Os servos ainda podem estar energizados: use o botão − do controle ou desligue a alimentação; envie o pacote de diagnóstico")
                return
            # Se não houver confirmação após 2 s, reenvia uma vez. Não reenvia se a leitura já indicar torque desligado (restando apenas o sinalizador hd1910):
            # alguém pode já ter usado o controle para colocar o robô em pé, e o reenvio o deixaria frouxo novamente (revisão #5)
            if el >= RESEND_AT_S and not self.estop.resent and not self.estop.saw_off:
                self.estop.resent = True
                if self._relax_send is None or self._relax_send.done():
                    self._start_send(self.estop.last_by, "Desligamento do torque (sem confirmação após 2 s; reenvio)")
            await asyncio.sleep(0.1)

    # ---- Consultas periódicas ----

    async def _ask(self, key, method, params=None, timeout=2.0, every=1.0):
        """Consulta um item. Em caso de sucesso, agenda a próxima consulta após every; erro ou timeout afeta somente esse item (revisão de código #5),
        e aplica espera progressiva sem bloquear os demais. Unreachable é propagado (a conexão inteira caiu)."""
        asked = time.monotonic()
        try:
            r = await self.poll.call(method, params or {}, timeout=timeout)
            if not isinstance(r, dict):
                raise RpcError(method, None, f"a resposta não é um objeto ({type(r).__name__})")
        except (RpcError, Timeout) as e:
            n = self._fails[key] = self._fails.get(key, 0) + 1
            self._due[key] = time.monotonic() + BACKOFF[min(n - 1, len(BACKOFF) - 1)] * 2
            if n in (1, 10) or n % 60 == 0:      # registra na 1ª, 10ª e a cada 60ª falha
                self.log.warn("O programa principal respondeu incorretamente a esta consulta", cat="robotd", step=method, raw=f"{e}（falha consecutiva nº {n}）",
                              hint="Uma falha ocasional não é problema; se continuar, verifique a temperatura da placa principal e os logs do robotd")
            return None, asked
        if self._fails.pop(key, 0) >= 10:
            self.log.info("Esta consulta voltou a funcionar", cat="robotd", step=method)
        self._due[key] = time.monotonic() + every
        return r, asked

    async def _poll_loop(self):
        due = self._due
        fails = 0
        hello_done = False
        hello_link = None             # contador de reconexões da conexão de consulta no momento do hello
        while True:
            if self.paused:
                hello_done = False
                await self._nap(1.0)
                continue
            if hello_done and self.poll.reconnects != hello_link:
                # A conexão de consulta caiu e foi restabelecida (um timeout RPC fecha a conexão, que é reaberta automaticamente na próxima tentativa); o robotd pode estar em um processo novo,
                # então trata como uma nova conexão, envia hello novamente e invalida a calibração já lida (revisão de código C8)
                hello_done = False
                self.log.info("A conexão de consulta ao programa principal foi restabelecida; iniciando nova conexão, hello e releitura do estado de calibração", cat="robotd")
            try:
                if not hello_done:
                    r = await self.poll.call("hello", {"api_version": API_VERSION}, timeout=2.0)
                    self.hello.set(r)
                    self.calib_valid_after = self.hello.at    # o estado de calibração lido antes disso é invalidado (revisão O5)
                    self._last_phase = None
                    self.starting_since = None                # reinicia a contagem de “continua inicializando” a partir desta conexão
                    self._mark_present(True)
                    hello_done = True
                    hello_link = self.poll.reconnects
                    self._ask_calib(again=True)
                    v = r.get("api_version") if isinstance(r, dict) else None
                    if v != API_VERSION:
                        self.log.warn(f"A versão da interface do programa principal é {v}; o Studio foi desenvolvido para {API_VERSION}", cat="robotd",
                                      hint="Em geral funciona; erros serão informados no recurso correspondente")
                    ver = r.get("daemon_version") if isinstance(r, dict) else None
                    self.log.info(f"Conectado ao programa principal (interface v{v}, versão {ver})", cat="robotd")
                now = time.monotonic()
                if now >= due["bus"]:
                    # No modo de calibração, consulta a 10 Hz: as leituras em tempo real da página da IMU e a calibração em pé vêm de last_sample (esse modo não tem robot.state)
                    every = 0.1 if (self.bus.value or {}).get("mode") == "commissioning" else 1.0
                    bus, asked = await self._ask("bus", "robot.busStatus", every=every)
                    if bus is not None:
                        self.bus.set(bus)
                        self._check_build(bus)
                        # Ao sair de control (robotd volta a aguardar o barramento ou muda de modo), invalida a calibração lida (revisão de código C8);
                        # Ao passar de “aguardando barramento/inicializando” para control (ou ready no modo de depuração), o arquivo de calibração só então é carregado no robotd
                        # （fork main.rs:1535），consulta novamente (revisão O5)
                        phase = bus.get("phase") if isinstance(bus, dict) else None
                        if self._last_phase == "control" and phase != "control":
                            self.calib_valid_after = time.monotonic()
                        if (phase != self._last_phase and self._last_phase is not None and phase is not None
                                and phase not in STARTING_PHASES):
                            self._ask_calib(again=True)
                        self._last_phase = phase
                        if phase in STARTING_PHASES:
                            if self.starting_since is None:
                                self.starting_since = time.monotonic()
                        else:
                            self.starting_since = None
                        if self.estop.on_bus(bus, asked):
                            self.log.info(f"Desligamento do torque confirmado ({self.estop.confirm_ms} ms entre pressionar e confirmar)", cat="Segurança",
                                          step="leitura de retorno de busStatus")
                    if self.estop.active:
                        due["bus"] = min(due["bus"], time.monotonic() + 0.1)
                if now >= due["health"]:
                    r, _ = await self._ask("health", "robot.health", every=2.0)
                    if r is not None:
                        self.health.set(r)
                if now >= due["policies"]:
                    if self._mode() == "motion" and self._phase() == "control":
                        r, _ = await self._ask("policies", "robot.policies", every=2.0)
                        if r is not None:
                            self.policies.set(r)
                    else:
                        due["policies"] = now + 2.0
                fails = 0
            except Unreachable as e:
                hello_done = False
                self._mark_present(False, e)
                fails += 1
                await self._nap(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
                continue
            except (Timeout, RpcError) as e:
                # Somente hello chega aqui
                fails += 1
                self.log.warn("O programa principal respondeu incorretamente ao hello", cat="robotd", raw=str(e),
                              hint="O programa principal talvez esteja iniciando; se continuar, verifique os logs do robotd")
                await self._nap(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
                continue
            await asyncio.sleep(0.05)

    async def _nap(self, seconds):
        """Espera progressiva, interrompida quando o torque é desligado."""
        try:
            await asyncio.wait_for(self._wake_poll.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake_poll.clear()

    def _ask_calib(self, again=False):
        """Inicia _calib_once uma vez (não inicia de novo se já estiver em andamento). again: quando phase acaba de virar control, a tentativa anterior pode estar dormindo após “não foi possível ler; tentar novamente em 10 s”,
        então cancela a espera e consulta novamente (o arquivo de calibração já estará disponível)."""
        if again and self._calib_task is not None and not self._calib_task.done():
            self._calib_task.cancel()
            self._calib_task = None
        if self._calib_task is None or self._calib_task.done():
            self._calib_task = asyncio.get_running_loop().create_task(self._calib_once())

    def calib_fresh(self):
        """Retorna a resposta de calibration-status somente se tiver sido lida após este hello; se não houver resposta ou ela for antiga, retorna None (revisão O5)."""
        return fresh_calib(self)

    async def _calib_once(self):
        """Consulta o estado de calibração uma vez ao conectar e outra quando phase vira control, usando uma conexão separada: a chamada pode demorar no robotd e não deve bloquear
        busStatus (revisão #8). Em caso de falha, tenta no máximo mais duas vezes, com intervalo de 10 s; se continuar falhando, desiste (a interface mostra “desconhecido”)."""
        for attempt in range(3):
            try:
                r = await call_once(self.addr, "robot.busCommand", {"action": "calibration-status"},
                                    timeout=5.0, name="Estado da calibração", log=self.log)
                if isinstance(r, dict):
                    self.calib.set(r)
                    return
                self.calib.fail(f"a resposta não é um objeto ({type(r).__name__})")
            except (Unreachable, Timeout, RpcError) as e:
                self.calib.fail(e)
                if attempt == 2:
                    self.log.warn("Não foi possível ler o estado da calibração", cat="Calibração", raw=str(e), hint="Isso não impede ficar em pé nem andar; a calibração aparecerá como “desconhecida” na interface")
            await asyncio.sleep(10.0)

    def _mark_present(self, ok, why=None):
        if ok and self.present is not True:
            if self.present is False:
                gone = time.monotonic() - (self.absent_since or time.monotonic())
                self.log.info(f"O programa principal voltou após {gone:.0f} s desconectado", cat="robotd")
            self.present, self.absent_since = True, None
        elif not ok and self.present is not False:
            self.present, self.absent_since = False, time.monotonic()
            self.log.warn("Não foi possível conectar ao robotd principal", cat="robotd", raw=str(why),
                          hint="O programa principal do robô não está em execução ou está reiniciando (cerca de 2 s). Atenção: parar o robotd não desliga o torque; os servos podem continuar energizados")

    def _check_build(self, bus):
        build = (bus or {}).get("build")
        if build and build not in KNOWN_BUILDS and not getattr(self, "_warned_build", False):
            self._warned_build = True
            self.log.warn(f"A versão {build} do programa principal ainda não foi verificada com o Studio", cat="robotd",
                          hint="A exibição somente leitura e o desligamento do torque continuam funcionando; os futuros botões de movimento ficarão desativados")

    def _mode(self):
        b = self.bus.value
        return b.get("mode") if isinstance(b, dict) else None

    def _phase(self):
        b = self.bus.value
        return b.get("phase") if isinstance(b, dict) else None

    # ---- Assinaturas ----

    def _want_stream(self):
        if self.paused:
            return False
        if self.force_subscribe or self.background_music or self.viewers > 0:
            return True
        return time.monotonic() - self._last_viewer_at < STREAM_LINGER_S

    async def _stream_loop(self):
        fails = 0
        while True:
            if not self._want_stream() or self._mode() != "motion" or self._phase() != "control":
                self._wake_stream.clear()
                try:
                    await asyncio.wait_for(self._wake_stream.wait(), 1.0)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await self._stream_once()
                fails = 0
            except (Unreachable, RpcError) as e:
                fails += 1
                self.log.warn("A assinatura do estado em tempo real foi interrompida", cat="robotd", raw=str(e))
                await asyncio.sleep(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
            except asyncio.TimeoutError:
                fails += 1
                self.log.warn("Nenhum quadro novo de estado em tempo real recebido em 3 s; assinando novamente", cat="robotd")

    async def _stream_once(self):
        r, w = await asyncio.wait_for(open_conn(self.addr), 3.0)
        self.stream_open = True
        self.log.info(f"Iniciando assinatura do estado em tempo real ({STREAM_HZ} Hz; {self.viewers} páginas visualizando)", cat="robotd")
        try:
            try:
                w.write(encode(1, "robot.subscribe", {"hz": int(STREAM_HZ)}))   # hz deve ser um inteiro (u32)
                await w.drain()
            except (ConnectionError, OSError) as e:
                raise Unreachable(f"Não foi possível enviar a solicitação de assinatura: {type(e).__name__}: {e}") from e
            while True:
                msg = await read_message(r, 3.0)
                if msg is None:
                    continue
                if msg.get("id") == 1:
                    if "error" in msg:
                        err = msg["error"] or {}
                        raise RpcError("robot.subscribe", err.get("code"), err.get("message", ""))
                    continue
                if msg.get("method") == "robot.state":
                    self.state.set(msg.get("params"))
                if not self._want_stream():
                    self.log.info("Ninguém está visualizando; encerrando a assinatura", cat="robotd")
                    return
        finally:
            self.stream_open = False
            try:
                w.close()
            except Exception:  # noqa: BLE001
                pass

    # ---- configd ----

    async def _configd_loop(self):
        """system.info a cada 60 s e pad.status a cada 5 s; cada item aplica sua própria espera em caso de falha (revisão de código #19: antes, se system.info
        falhasse continuamente, pad.status nunca seria consultado)."""
        due = {"info": 0.0, "pad": 0.0}
        down = {"info": False, "pad": False}
        while True:
            now = time.monotonic()
            for key, method, sample, every in (("info", "system.info", self.sysinfo, 60.0),
                                               ("pad", "pad.status", self.pad, 5.0)):
                if now < due[key]:
                    continue
                try:
                    sample.set(await self.cfg.call(method, {}, timeout=2.0))
                    due[key] = now + every
                    if down[key]:
                        down[key] = False
                        self.log.info(f"{method} do configd voltou a funcionar", cat="Controle")
                except (Unreachable, Timeout, RpcError) as e:
                    sample.fail(e)
                    due[key] = now + 5.0
                    if not down[key]:
                        down[key] = True
                        self.log.warn(f"Não foi possível ler {method} do configd", cat="Controle", raw=str(e),
                                      hint="Alguns robôs desativam o configd; isso não impede ficar em pé nem andar, mas a seção do controle mostrará “desconhecido”")
            await asyncio.sleep(0.5)

    # ---- Autodiagnóstico somente leitura (--selfcheck) ----

    async def selfcheck(self):
        """Somente leitura. Além de consultar cada serviço uma vez, verifica as permissões dos três sockets (um problema comum ao configurar o grupo robot),
        e se é possível consultar diretamente em uma nova conexão sem enviar hello primeiro (o comando para desligar o torque sempre é enviado por uma conexão nova)."""
        import grp
        import os
        import pwd
        out = {}
        try:
            me = pwd.getpwuid(os.getuid()).pw_name
            groups = sorted(grp.getgrgid(g).gr_name for g in os.getgroups())
            out["Usuário"] = f"{me} · grupos {','.join(groups)}"
        except (ImportError, KeyError, OSError) as e:
            out["Usuário"] = f"(não foi possível consultar: {e})"
        for path in ("/run/robotd.sock", "/run/configd.sock", "/run/padd/pad.sock"):
            if not os.path.exists(path):
                out[path] = "ausente"
            else:
                out[path] = "leitura e gravação permitidas" if os.access(path, os.R_OK | os.W_OK) else "sem permissão (adicione o usuário ao grupo robot)"
        for name, method, params, addr in (
            ("Consulta direta em nova conexão", "robot.health", {}, self.addr),
            ("hello", "hello", {"api_version": API_VERSION}, self.addr),
            ("busStatus", "robot.busStatus", {}, self.addr),
            ("pad.status", "pad.status", {}, self.cfg.addr),
            ("system.info", "system.info", {}, self.cfg.addr),
        ):
            try:
                r = await call_once(addr, method, params, timeout=3.0)
                if name == "busStatus":
                    out[name] = f"ok · mode={r.get('mode')} phase={r.get('phase')} build={r.get('build')}"
                elif name == "hello":
                    out[name] = f"ok · interface v{r.get('api_version')} versão {r.get('daemon_version')}"
                else:
                    out[name] = "ok"
            except Exception as e:  # noqa: BLE001
                out[name] = f"Falhou: {e}"
        return out


def _round(x, nd=2):
    return None if x is None else round(x, nd)


def fresh_calib(rd):
    """Valor de rd.calib, válido somente se lido após este hello (revisão O5 da reorganização do painel). Se rd não tiver calib_valid_after (objeto simulado dos testes),
    não bloqueia a leitura. Qualquer valor que não seja dict retorna None."""
    s = getattr(rd, "calib", None)
    if s is None or not isinstance(s.value, dict) or s.at is None:
        return None
    after = getattr(rd, "calib_valid_after", None)
    if after is not None and s.at < after:
        return None
    return s.value
