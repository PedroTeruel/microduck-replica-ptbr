"""O estado do botão de alívio de torque é sempre derivado dos dados, não de “ter sido pressionado” (review-impl-plan I5).

No modo de movimento, `robot.relax` apenas coloca a solicitação na fila e retorna `accepted:true` imediatamente — **a resposta não significa que o torque já foi aliviado**.
Por isso, a confirmação depende de `busStatus`:

Modo de movimento (as cinco condições precisam ser atendidas; a regra é igual à do script de instalação imu-module-install.sh:165-170):
    mode == "motion"
    torque_off_pending não é verdadeiro
    native.torque_state_confirmed is False
    native.hd1910.restore_pending is False
    native.hd1910.temporary_gains_applied is False
Modo de depuração:
    torque_state == "off" e torque_off_pending está vazio

Sequência de uma tentativa de pressionamento (avançada por robotd.py; aqui apenas registramos os fatos):
    press()        Pressionar inicia uma tentativa. Em pressionamentos repetidos, vale o mais recente: aguarde novamente a resposta e a leitura de retorno.
    sent()         robotd respondeu à solicitação de alívio de torque (registra o horário sent_at). Só contam envios iniciados depois deste pressionamento
                   (no máximo 0,3 s antes); envios antigos que já estavam em trânsito quando robotd travou não contam (revisão #3).
    on_bus()       A consulta obteve um busStatus. **Só confirma se uma consulta enviada depois de sent_at e do último pressionamento**
                   mostrar torque OFF — uma consulta anterior pode refletir o estado antes do alívio (revisão de código #3, revisão #2).
    finish()       Confirmado / sem confirmação em 8 s / não enviado: a tentativa termina e pressed_at é limpo.
                   Não há reenvio automático após terminar (revisão de código #1: antes, pressed_at não era limpo após confirmar,
                   e o Studio enviava novo alívio automaticamente quando alguém levantava o pato com o controle).
O reenvio (uma vez após 2 s sem confirmação) e o timeout (8 s) são feitos pela tarefa de monitoramento em robotd.py; não dependem de alguém estar olhando a página.

Quatro estados do botão (`status()` apenas lê dados, sem alterar nada):
    ready        Pode pressionar.
    pending      Pressionado, ainda sem confirmação.
    confirmed    OFF confirmado (leitura recente, em até 1,5 s; volta a ready se o torque for ligado novamente; também se aplica se já estava aliviado).
    unavailable  Programa principal ausente ou iniciando, ou a tentativa anterior não foi enviada / não foi confirmada em 8 s (avisa; retorna a ready após 6 s).
Se não for possível ler o estado (busStatus desatualizado), permanece ready: o pressionamento ainda é enviado, mas a confirmação aguarda a recuperação da leitura.
"""
import time

STARTING_PHASES = ("configuring_bus", "waiting_for_bus", "configuration_error")
# Quando o modo de comissionamento está ativo, `robot.busStatus` retorna o snapshot em tempo real de feetech_commissioning.rs (Status, perto da linha 1083 do fork); `phase` assume um destes valores.
# O relatório de inicialização (`{"mode":"commissioning","phase":"configuring_bus",...}`) usa uma fase de STARTING_PHASES;
# o fork antigo nunca a limpava e o Studio mostrava “iniciando” para sempre (teste em hardware de 10-20); o fork novo limpa na primeira leitura bem-sucedida (perto da linha 1497).
# holding: a “postura em pé habilitada” do modo de comissionamento (fork hold-home) está estável; o torque está em torque_state=all_enabled e o alívio continua usando robot.relax.
COMMISSIONING_UP = ("ready", "moving", "holding", "read_error", "stop_unconfirmed", "power_pending")
STARTING_LONG_S = 30.0       # Se o programa principal continuar informando a fase de inicialização por tanto tempo (contado desde a conexão ao Studio): passa a indicar “inicialização travada” (problema do fork antigo ou travamento real).
CONFIRM_TIMEOUT_S = 8.0
RESEND_AT_S = 2.0
CONFIRMED_FRESH_S = 2.5      # Para mostrar “torque aliviado”, a leitura não pode ser mais antiga que isso (consulta a cada 1 s; 1,5 s piscava quando a consulta demorava, revisão #7).
OUTCOME_SHOW_S = 6.0
JOIN_S = 0.3                 # Um envio já em trânsito quando o botão é pressionado conta para esta tentativa se começou há menos de 0,3 s.


def robotd_up(bus):
    """O programa principal está ativo (independentemente de estar em pé)? No modo de movimento, entrou em control; no modo de comissionamento, retorna um snapshot em tempo real (phase em COMMISSIONING_UP;
    read_error também conta como ativo, mas indica falha ao ler os servos). Fase de inicialização ou valor desconhecido retorna False."""
    if not isinstance(bus, dict):
        return False
    mode, phase = bus.get("mode"), bus.get("phase")
    return (mode == "motion" and phase == "control") or (mode == "commissioning" and phase in COMMISSIONING_UP)


def relaxed(bus):
    """O busStatus confirma que o torque está OFF? True / False / None (dados insuficientes para saber)."""
    if not isinstance(bus, dict):
        return None
    mode = bus.get("mode")
    if mode == "motion":
        native = bus.get("native")
        if not isinstance(native, dict) or "torque_state_confirmed" not in native:
            return None
        hd = native.get("hd1910") or {}
        return (bus.get("torque_off_pending") is not True
                and native.get("torque_state_confirmed") is False
                and hd.get("restore_pending") is False
                and hd.get("temporary_gains_applied") is False)
    if mode == "commissioning":
        if "torque_state" not in bus:
            return None
        return bus.get("torque_state") == "off" and not bus.get("torque_off_pending")
    return None


def torque_off(bus):
    """O estado do torque foi confirmado como OFF (independentemente das flags hd1910)? Usado para decidir se deve reenviar."""
    if not isinstance(bus, dict):
        return False
    if bus.get("mode") == "commissioning":
        return bus.get("torque_state") == "off"
    native = bus.get("native")
    return isinstance(native, dict) and native.get("torque_state_confirmed") is False


def evidence(bus):
    """Contexto registrado quando não é possível confirmar: campos usados para verificar o alívio de torque."""
    if not isinstance(bus, dict):
        return {"busStatus": None}
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
    return {"mode": bus.get("mode"), "phase": bus.get("phase"), "torque_off_pending": bus.get("torque_off_pending"),
            "torque_state": bus.get("torque_state"), "torque_state_confirmed": native.get("torque_state_confirmed"),
            "restore_pending": hd.get("restore_pending"), "temporary_gains_applied": hd.get("temporary_gains_applied")}


class EStop:
    def __init__(self):
        self.pressed_at = None       # Início da tentativa atual (monotonic); None = nenhuma
        self.sent_at = None          # Horário da primeira confirmação de robotd nesta tentativa
        self.resent = False
        self.saw_off = False         # Uma leitura posterior à resposta mostrou torque OFF (depois só falta a flag hd1910; não precisa reenviar).
        self.send_error = None       # Motivo de falha em um reenvio ou pressionamento posterior, depois que o primeiro envio já foi aceito (registrado no log de timeout).
        self.press_count = 0
        self.last_by = None
        self.confirm_ms = None       # Duração da tentativa mais recente, do pressionamento à confirmação, em ms
        self.outcome = None          # Resultado da última tentativa: confirmed / timeout / send_failed / refused
        self.outcome_at = None
        self.outcome_why = ""

    @property
    def active(self):
        return self.pressed_at is not None

    def press(self, by=None, now=None):
        """Reinicia a contagem a cada pressionamento e aguarda novamente a resposta e a leitura (pressionamentos repetidos com espaço ou toques no celular: vale o último)."""
        now = time.monotonic() if now is None else now
        self.sent_at = None
        self.resent = False
        self.saw_off = False
        self.send_error = None
        self.pressed_at = now
        self.press_count += 1
        self.last_by = by
        self.outcome = None

    def belongs(self, started):
        """Verifica se um envio (started = horário de início) pertence a esta tentativa."""
        return self.active and started >= self.pressed_at - JOIN_S

    def sent(self, started, now=None):
        now = time.monotonic() if now is None else now
        if self.belongs(started) and self.sent_at is None:
            self.sent_at = now

    def send_failed(self, started, why, now=None):
        """Um envio desta tentativa falhou. Se ainda não houve nenhuma resposta, a tentativa falha;
        se já houve uma resposta (o primeiro envio foi aceito e falhou um reenvio ou novo pressionamento), continua aguardando a leitura e guarda o motivo para o log de timeout."""
        if not self.belongs(started):
            return
        if self.sent_at is None:
            self.finish("send_failed", why, now=now)
        else:
            self.send_error = why

    def on_bus(self, bus, asked_at, now=None):
        """A consulta obteve um busStatus (`asked_at` = horário em que esta consulta foi enviada). Retorna True quando confirmado."""
        now = time.monotonic() if now is None else now
        if not self.active or self.sent_at is None or asked_at < max(self.sent_at, self.pressed_at):
            return False
        if torque_off(bus):
            self.saw_off = True
        if relaxed(bus) is True:
            self.confirm_ms = round((now - self.pressed_at) * 1000)
            self.finish("confirmed", now=now)
            return True
        return False

    def finish(self, outcome, why="", now=None):
        now = time.monotonic() if now is None else now
        self.outcome, self.outcome_at, self.outcome_why = outcome, now, why
        self.pressed_at = None

    def elapsed(self, now=None):
        if not self.active:
            return None
        return (time.monotonic() if now is None else now) - self.pressed_at

    def status(self, *, present, bus, bus_age_s, now=None):
        """Retorna `{"state": ..., "why": uma mensagem para exibição}`. Somente leitura."""
        now = time.monotonic() if now is None else now
        mode = bus.get("mode") if isinstance(bus, dict) else None
        phase = bus.get("phase") if isinstance(bus, dict) else None
        no_pad = "só é possível desligar a alimentação" if (not present or phase in STARTING_PHASES or mode == "commissioning") \
            else "use o controle − ou desligue a alimentação"
        if self.active:
            # Avalia antes de “programa principal ausente”: se robotd acabou de voltar e a consulta ainda está no intervalo de espera, a resposta já pode ter chegado; não indicar ausência (revisão #6).
            return {"state": "pending", "why": "Aliviando o torque…"}
        if not present:
            return {"state": "unavailable", "why": f"Programa principal ausente; {no_pad}"}
        fresh = bus is not None and bus_age_s is not None and bus_age_s <= CONFIRMED_FRESH_S
        if fresh and phase in STARTING_PHASES:
            return {"state": "unavailable", "why": f"Programa principal iniciando; {no_pad}"}
        if fresh and relaxed(bus) is True:
            return {"state": "confirmed", "why": "Torque aliviado nos 15 servos"}
        recent = self.outcome_at is not None and now - self.outcome_at < OUTCOME_SHOW_S
        if recent and self.outcome in ("timeout", "send_failed", "refused"):
            return {"state": "unavailable", "why": f"{self.outcome_why}，{no_pad}"}
        if not fresh:
            return {"state": "ready", "why": "Não foi possível ler o estado do pato; o comando ainda será enviado ao pressionar"}
        return {"state": "ready", "why": ""}
