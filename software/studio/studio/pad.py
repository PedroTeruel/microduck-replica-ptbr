"""Backend da página do controle: estado, pareamento visual, botões em tempo real e teste da parada de emergência. A movimentação do Microduck fica em pad_drive.py (herdada por PadOps).

As quatro interfaces com o sistema são recebidas no construtor e podem ser simuladas (tests/test_pad.py usa apenas simulações e roda mesmo em computador sem Bluetooth):

| Porta     | Real                                   | Função |
|-----------|----------------------------------------|--------|
| configd   | ConfigdPort (unix:/run/configd.sock)   | pad.status consulta o estado; pad.pair / pad.forget pareiam e removem controles (operações de alteração; configd aceita apenas root e --allow-user, main.rs:112-131) |
| bluetooth | BluetoothCtl (sessão bluetoothctl)     | Lista de busca (a interface oficial não oferece isso); pareamento alternativo quando configd não permite |
| tap       | PaddTap (unix:/run/padd/pad.sock)      | Acesso paralelo do padd a pad.input: eventos brutos de teclas evdev; assina somente enquanto alguém vê a página do controle (o padd abre o dispositivo apenas durante a assinatura) |
| robot     | RobotPort (unix:/run/robotd.sock)      | robot.move / head / mouth (notificações); init / enable / do / sound / stop / busStatus (solicitações); pad.bindings |

As leituras de retorno do robotd (torque, postura e número de acionamentos do relaxamento) são obtidas por app.py no loop de eventos com robot_view(robotd) e entregues por feed_robot(). Uma tarefa a 10 Hz no lifespan faz isso mesmo sem ninguém vendo a página (revisão 13); este módulo não acessa objetos do robotd entre threads.
O teste de emergência consulta robot.busStatus por conta própria, abre uma conexão nova e registra o horário da consulta (revisão 1).

Como em servo_ops, handle() roda em asyncio.to_thread. Busca e pareamento são lentos, então ficam em uma thread de tarefa em segundo plano e handle retorna imediatamente. O progresso fica em snapshot() (a página consulta a 10 Hz). A thread de monitoramento só fica ativa enquanto alguém vê a página, há uma tarefa ou o teste de emergência está em andamento. Ela consulta pad.status e ativa ou desativa a leitura paralela; quando não há mais trabalho, encerra. O teste de emergência e as ações usam threads próprias, que terminam ao concluir.

Os fatos confirmados na implementação oficial (arquivo e linha) estão em scratchpad console/pad-page-plan.md; são referenciados aqui apenas nos pontos importantes.
"""
import codecs
import concurrent.futures
import json
import math
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import tomllib
from collections import deque

from . import helper as helper_api
from .estop import STARTING_PHASES, relaxed, torque_off
from .pad_combo import Refused
from .motion_studio import MotionStudio, _digest
from .pad_drive import (DRIVING, FAST_WORKERS, MAX_V, MAX_W, RELAX_CLEAR_DELAY_S, RELAX_GUARD_S,  # noqa: F401 — MAX_V / MAX_W são importados por outros módulos
                        DriveMixin, parse_speed_limits)
from .rpc import LINE_LIMIT, RpcError, Timeout, Unreachable, parse_addr
from .state import MAX_AGE
from .state import posture as _posture

SCAN_S, SCAN_MAX_S = 12, 30
PAIR_WINDOW_S = 20        # timeout_seconds enviado ao configd: com MAC informado, para assim que encontrar o dispositivo (bluez.rs:593-628)
PAIR_CALL_MARGIN_S = 110  # pior caso do configd: janela + 30 + 5 + 30 + 30 segundos (bluez.rs:212-223)
CONNECT_WAIT_S = 10
PADD_WAIT_S = 30          # no dispositivo real, o kernel cria a entrada cerca de 15 segundos após o pareamento; margem dobrada
PAD_PAIR_TIMEOUT_S = 60   # tempo limite para o Assistente executar robotctl pad pair oficial (10–120)
WATCH_LEASE_S = 6.0       # a página envia um sinal a cada 2 segundos; sem sinal por 6 segundos, considera que ninguém está vendo
KEYS_NEED = 4             # teste dos botões: pressionar 4 botões diferentes e mover os dois analógicos para concluir
TEST_TORQUE_WAIT_S = 60
TEST_PRESS_WAIT_S = 90
TEST_READBACK_S = 6.0
SELECT_LONG_S = 1.5       # avisa após manter pressionado por 1,5 segundo
SHUTDOWN_HOLD_S = 2.0     # padd: manter Select pressionado por 2 segundos faz sentar, relaxar e desligar (robot.shutdown); não é parada de emergência (padd main.rs:192-193, 725-739)
TEST_PROBE_S = 0.25       # intervalo das consultas próprias a busStatus durante o teste de emergência
BUS_FRESH_S = 3.0
STICK_ACTIVE = 0.15
MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
WEIRD_BLE = "/var/lib/robot/weird-ble"     # nas placas com esse marcador, o robotctl oficial pausa o btd e reinicia o adaptador antes do pareamento (robotctl main.rs:2799-2945)
ROBOTD_TOML = "/etc/robot/robotd.toml"      # arquivo em que padd lê [netpad] (robotd-params DEFAULT_PATH)
FINAL = ("idle", "passed", "failed")
_HELPER_OLD = object()      # o Assistente antigo retorna bad_verb: usar o método alternativo


class BtError(Exception):
    """Erro de Bluetooth: code é uma chave de FAILS e raw contém a mensagem original."""

    def __init__(self, code, raw=""):
        super().__init__(raw or code)
        self.code, self.raw = code, raw


class NoPermission(Unreachable):
    """O socket existe, mas o usuário do Studio não tem permissão para conectar (não significa que o serviço esteja indisponível: revisão 17)."""


# ---------------- Mensagens claras: causa da falha → explicação e solução ----------------

NO_RESTART_BT = "Não reinicie o bluetooth: nesta placa o Bluetooth pode parar de funcionar e só voltar após reiniciar (pair-a-gamepad.md oficial:142)"
ROBOT_GROUP = "Adicione o usuário do Studio ao grupo robot com sudo usermod -aG robot <usuário> e reinicie o Studio"
FAILS = {
    "no_adapter": ("O Bluetooth do Microduck ainda não está pronto (hci0 não encontrado)",
                   f"Isso é normal nos primeiros 70 segundos após ligar (nesta placa, hci0 aparece por volta de 73 segundos). Aguarde um minuto e tente novamente. Se continuar, reinicie o Microduck. {NO_RESTART_BT}"),
    "rfkill": ("O Bluetooth foi desativado pelo sistema (rfkill)", "Execute sudo rfkill unblock bluetooth no Microduck e tente novamente"),
    "powered_off": ("O Bluetooth do Microduck está desligado", "Tente novamente para ligá-lo; se não funcionar, reinicie o Microduck"),
    "bluez_down": ("O serviço bluetoothd não está em execução no Microduck", f"Reinicie o Microduck. {NO_RESTART_BT}"),
    "configd_down": ("O serviço configd não está em execução no Microduck", "No primeiro Microduck, esse serviço costuma ficar parado: execute sudo systemctl start configd no dispositivo e tente novamente"),
    "socket_perm": ("O Studio não tem permissão para se conectar ao configd (/run/configd.sock)", ROBOT_GROUP),
    "configd_busy": ("O pareamento anterior do configd ainda não terminou", "Não é possível interrompê-lo; ele deve terminar em um ou dois minutos. Aguarde esta mensagem desaparecer antes de tentar novamente."),
    "driving": ("O Microduck está se movendo ou uma rotina está em execução", "A busca e o pareamento ocupam o Bluetooth. O controle em uso pode travar enquanto o Microduck continua andando. Pare primeiro (clique em ‘Parar (ficar em pé)’ ou pressione Start no controle) e então busque."),
    "no_btctl": ("O Microduck não tem bluetoothctl e não consegue listar dispositivos próximos", "Clique em ‘Parear diretamente (seleção automática)’ para deixar o configd procurar"),
    "permission": ("O Studio não tem permissão para parear", "O configd permite pareamento apenas como root. Por enquanto, execute sudo robotctl pad pair no Microduck via SSH; depois de instalar o Assistente, será possível fazer isso pela página."),
    "bt_permission": ("O Studio não tem permissão para usar o Bluetooth", "Adicione o usuário do Studio ao grupo bluetooth ou execute sudo robotctl pad pair no Microduck via SSH"),
    "scan_failed": ("Não foi possível iniciar a busca Bluetooth", "Outro programa pode estar buscando ou pareando; aguarde alguns segundos e tente novamente"),
    "not_found": ("Nenhum controle em modo de pareamento foi encontrado", "A luz do controle precisa piscar rapidamente (piscar devagar ou ficar acesa não indica modo de pareamento). Coloque-o nesse modo seguindo as instruções acima e clique em iniciar assim que a luz começar a piscar."),
    "not_found_pad": ("Há dispositivos Bluetooth próximos, mas nenhum parece ser um controle", "A luz do controle está piscando rapidamente? Se ele aparecer na lista, clique em ‘Parear este’ ao lado dele."),
    "ambiguous": ("Há vários controles em modo de pareamento ao mesmo tempo", "Deixe apenas um com a luz piscando ou clique em ‘Iniciar busca’ e escolha o controle na lista."),
    "timeout": ("O controle foi encontrado, mas o pareamento não terminou", "O controle pode ter saído do modo de pareamento. Pressione novamente o botão de pareamento e clique em ‘Tentar novamente’ assim que a luz piscar rapidamente."),
    "rejected": ("O Bluetooth recusou o pareamento",
                 "Provavelmente o controle saiu do modo de pareamento. Pressione o botão de pareamento e tente novamente quando a luz piscar rapidamente. Se isso acontecer sempre, confira Privacy em /etc/bluetooth/main.conf; "
                 "a recomendação oficial é Privacy = device (reinicie o Microduck após alterar)"),
    "auth_failed": ("O controle recusou o pareamento (falha de autenticação)",
                    "Isso costuma ocorrer quando o controle já foi pareado com outro dispositivo: controles Xbox guardam um único host; pareie com um computador ou celular e remova o pareamento. Modelos como o G50 guardam apenas o dispositivo pareado por último. "
                    "Depois, coloque o controle novamente em modo de pareamento."),
    "pin": ("Este controle exige um PIN, que o Microduck não consegue digitar", "Mude o controle para o modo Switch ou X-input e tente novamente, ou use outro controle"),
    "key_missing": ("As chaves salvas nos dois dispositivos não correspondem (PIN ou chave ausente)",
                    "Clique em ‘Esquecer’ em ‘Controles lembrados pelo Microduck’, coloque o controle novamente em modo de pareamento e tente parear. Se ainda falhar: segundo a documentação oficial, Privacy = device causa isso em algumas placas; reverta a configuração e tente apenas pausar o btd."),
    "le_abort": ("O próprio Microduck encerrou a conexão (le-connection-abort-by-local)", "Segundo a documentação oficial, isso geralmente indica um valor incorreto em Privacy no arquivo /etc/bluetooth/main.conf. Use Privacy = device e reinicie o Microduck após alterar."),
    "dhkey": ("Falha na verificação do pareamento (DHKey check failed)", "Segundo a documentação oficial, este é outro caso relacionado a Privacy: tente Privacy = off e reinicie o Microduck após alterar."),
    "not_bondable": ("O Bluetooth do Microduck está ‘não vinculável’ e não pode salvar as chaves", "É preciso ser root: execute sudo btmgmt bondable on no Microduck e tente novamente"),
    "agent": ("Não foi possível registrar o agente de pareamento Bluetooth", "Provavelmente outro programa (o serviço de configuração ou outro bluetoothctl) está usando o agente. Aguarde e tente novamente; se persistir, reinicie o Microduck."),
    "busy": ("Outro pareamento está em andamento", "Aguarde a conclusão (pode levar até um ou dois minutos) e tente novamente"),
    "not_trusted": ("Pareado, mas não marcado como confiável", "Ele pode ser usado agora, mas não se reconectará após reiniciar o Microduck. Clique em ‘Reparar’ em ‘Controles lembrados pelo Microduck’."),
    "not_connected": ("Pareado, mas não conectado", "Pressione o botão Home/Xbox para ligar o controle; ele deverá se conectar automaticamente."),
    "padd_down": ("O controle se conectou, mas o padd não está em execução", "O padd só inicia quando o programa principal robotd está em execução. Inicie o programa principal; se não resolver, confira as linhas do padd nos logs."),
    "no_input": ("Conectado, mas o padd não reconheceu este controle (não consegue ler os botões)",
                 "Pressione Home/Xbox para despertar o controle; a página tentará restabelecer a conexão. Se ainda não for possível ler os botões, confira o modo do controle e os logs. Se houver aviso de chaves incompatíveis, esqueça o dispositivo e pareie novamente."),
    "wrong_input": ("O padd abriu outro controle", "Desconecte o outro controle e desperte o controle selecionado. O sistema não desconectará por você outro controle que esteja em uso."),
    "no_robotctl": ("O robotctl oficial não está instalado no Microduck (/usr/local/bin/robotctl)",
                    "Reinstale o firmware oficial/robotctl e confirme a instalação, ou execute sudo robotctl pad pair no Microduck. O Assistente novo usa esse comando para pausar o btd e reiniciar o Bluetooth."),
    "weird_ble": ("Nesta placa, é preciso pausar o btd e reiniciar o Bluetooth antes de parear um controle novo", "O Assistente novo executa robotctl pad pair oficial para fazer isso. Se não tiver a versão nova, reinstale o Assistente ou execute sudo robotctl pad pair no Microduck."),
    "cancelled": ("Interrompido", "Para parear, clique em ‘Começar de novo’."),
    "other": ("O pareamento falhou", "Confira a mensagem original abaixo; você pode exportar um pacote de diagnóstico e compartilhá-lo com a equipe."),
}

_CLASSIFY = [
    (r"org\.freedesktop\.DBus\.Error\.AccessDenied|Access denied", "bt_permission"),
    (r"Device [0-9A-Fa-f:]{17} not available", "not_found"),
    (r"ServiceUnknown|cannot reach bluetoothd|Waiting to connect to bluetoothd|org\.bluez was not provided", "bluez_down"),
    (r"No default controller|no Bluetooth adapter|Controller .* not available", "no_adapter"),
    (r"NotReady|not powered|Resource Not Ready", "powered_off"),
    (r"InProgress|In Progress|Operation already in progress|org\.bluez\.Error\.Busy", "busy"),
    (r"PIN or Key Missing|Key Missing", "key_missing"),
    (r"DHKey", "dhkey"),
    (r"le-connection-abort-by-local", "le_abort"),
    (r"cannot enter a PIN|cannot enter a passkey|Enter PIN code|Enter passkey|Confirm passkey|RequestPinCode", "pin"),
    (r"Authentication ?Failed|Authentication ?Rejected|Authentication ?Canceled", "auth_failed"),
    (r"AuthenticationTimeout|Page Timeout|page-timeout|ConnectionAttemptFailed|Host is down|did not finish pairing|timed out|Timeout", "timeout"),
    (r"No Bonding|not bondable", "not_bondable"),
    (r"Permission denied", "not_bondable"),     # Em 10-15, conectar HID sem vínculo faz o BlueZ retornar Permission denied (13) (arquivo de registro de problemas, linha 272)
    (r"Failed to register agent|Agent is already registered|already registered", "agent"),
    (r"Failed to start discovery", "scan_failed"),
]


def classify(raw):
    """Converte mensagens originais de BlueZ, bluetoothctl e configd em chaves de FAILS; mensagens desconhecidas viram other."""
    text = str(raw or "")
    for pat, code in _CLASSIFY:
        if re.search(pat, text, re.I):
            return code
    return "other"


def explain(code, raw=None):
    msg, fix = FAILS.get(code, FAILS["other"])
    return {"code": code, "msg": msg, "fix": fix, "raw": (str(raw)[-600:] if raw else None)}


# ---------------- Identificação de controles: mesmas regras do configd (configd/src/pad.rs:121-163) ----------------

def gamepad_evidence(name, icon=None, cls=None, appearance=None):
    """Retorna classified se ícone, classe ou aparência indicar um controle; name se apenas o nome parecer de controle; caso contrário, None."""
    if icon == "input-gaming":
        return "classified"
    if isinstance(cls, int):
        if (cls >> 8) & 0x1F == 0x05 and ((cls >> 2) & 0x3F) & 0x0F in (0x01, 0x02):
            return "classified"
    if appearance == 0x03C4:
        return "classified"
    lower = (name or "").lower()
    if any(k in lower for k in ("controller", "gamepad", "joystick", "dualsense", "dualshock")):
        return "name"
    return None


def same_pad(a, b):
    """Endereços com os mesmos três últimos bytes representam o mesmo controle (clones de Switch aparecem em LE e Bluetooth clássico; pad.rs:165-194)."""
    ta, tb = (a or "").upper().split(":")[-3:], (b or "").upper().split(":")[-3:]
    return len(ta) == 3 and ta == tb


def pad_kind(name, vendor=None):
    """Retorna xbox, ps, switch ou generic para escolher o desenho e os nomes dos botões na página."""
    n = (name or "").lower()
    if vendor == 0x045E or "xbox" in n:
        return "xbox"
    if vendor == 0x054C or any(k in n for k in ("dualsense", "dualshock", "playstation")) or n.strip() == "wireless controller":
        return "ps"
    if vendor == 0x057E or any(k in n for k in ("pro controller", "joy-con", "nintendo", "switch")):
        return "switch"
    return "generic"


KIND_LABEL = {"xbox": "Xbox", "ps": "PlayStation", "switch": "Switch Pro", "generic": ""}
ICON_CN = {"audio-headset": "Fone com microfone", "audio-headphones": "Fone de ouvido", "audio-card": "Caixa de som", "phone": "Celular", "computer": "Computador",
           "input-keyboard": "Teclado", "input-mouse": "Mouse", "input-tablet": "Mesa digitalizadora", "video-display": "Monitor"}


# ---------------- Botões em tempo real (o acesso paralelo do padd fornece eventos evdev brutos; lib.rs:4205-4451) ----------------

BTN_ROLE = {0x130: "south", 0x131: "east", 0x133: "north", 0x134: "west", 0x136: "lb", 0x137: "rb",
            0x138: "lt", 0x139: "rt", 0x13A: "select", 0x13B: "start", 0x13C: "home", 0x13D: "l3", 0x13E: "r3",
            0x220: "du", 0x221: "dd", 0x222: "dl", 0x223: "dr", 158: "select", 172: "home"}
# Xbox (hid-generic por BLE, xpad por USB e 360 virtualizado pela ponte GameSir): o botão marcado X emite BTN_X(0x133), e o marcado Y emite BTN_Y(0x134),
# ao contrário do mapeamento por posição norte/oeste; PS (hid-playstation) e Switch (hid-nintendo) usam a posição.
# **Hipótese, ainda não verificada no Microduck (E9)**: a página informa que as posições X/Y do Xbox precisam ser confirmadas.
XBOX_SWAP = {0x133: "west", 0x134: "north"}
XBOX_SWAP_VERIFIED = False
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_GAS, ABS_BRAKE, ABS_HAT0X, ABS_HAT0Y = 0, 1, 2, 3, 4, 5, 9, 10, 16, 17
EV_KEY, EV_ABS = 1, 3


class LiveInput:
    """Acumula eventos usando a descrição do dispositivo attached para determinar quais botões estão pressionados e a posição dos analógicos. Quando o controle fica parado, o padd não envia eventos,
    por isso os valores iniciais vêm de attached."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.device = None
        self.kind = None
        self.buttons = {}            # role -> bool
        self.other = {}              # teclas fora do mapeamento: nome -> bool
        self.axes = {}               # função -> valor (analógicos de -1 a 1, baixo/direita positivos; gatilhos de 0 a 1)
        self.amap = {}               # código de eixo evdev -> (função, mínimo, máximo)
        self.last_at = None
        self.activity_at = None      # último movimento real (mudança de botão ou analógico fora do centro)
        self.seen = set()

    def _role(self, code):
        if self.kind == "xbox" and code in XBOX_SWAP:
            return XBOX_SWAP[code]
        return BTN_ROLE.get(code)

    def attach(self, device, now):
        self.reset()
        self.device = device if isinstance(device, dict) else {}
        self.kind = pad_kind(self.device.get("name"), self.device.get("vendor"))
        axes = {a.get("code"): a for a in self.device.get("axes") or [] if isinstance(a, dict)}
        amap = {ABS_X: "lx", ABS_Y: "ly", ABS_HAT0X: "hatx", ABS_HAT0Y: "haty"}
        if ABS_RX in axes:                     # xpad / hid-playstation / hid-nintendo: analógico direito usa RX/RY
            amap.update({ABS_RX: "rx", ABS_RY: "ry"})
            if ABS_BRAKE in axes or ABS_GAS in axes:
                amap.update({ABS_BRAKE: "lt", ABS_GAS: "rt"})
            else:
                amap.update({ABS_Z: "lt", ABS_RZ: "rt"})
        else:                                  # Xbox por BLE com hid-generic: analógico direito usa Z/RZ e gatilhos usam BRAKE/GAS
            amap.update({ABS_Z: "rx", ABS_RZ: "ry", ABS_BRAKE: "lt", ABS_GAS: "rt"})
        for code, role in amap.items():
            a = axes.get(code)
            if a is not None:
                self.amap[code] = (role, a.get("min", -32768), a.get("max", 32767))
                self._set_axis(code, a.get("value", 0))
        for b in self.device.get("buttons") or []:
            if isinstance(b, dict):
                self._set_key(b.get("code"), b.get("name"), bool(b.get("pressed")), track=False)
        self.last_at = now

    def _set_axis(self, code, raw):
        role, lo, hi = self.amap[code]
        if not isinstance(raw, (int, float)):
            return
        if role in ("hatx", "haty"):
            v = 0 if raw == 0 else (1 if raw > 0 else -1)
            neg, pos = ("dl", "dr") if role == "hatx" else ("du", "dd")
            self.buttons[neg], self.buttons[pos] = v < 0, v > 0
            return
        if hi == lo:
            return
        if role in ("lt", "rt"):
            v = (raw - lo) / (hi - lo)
            v = max(0.0, min(1.0, v))
        else:
            mid, half = (hi + lo) / 2, (hi - lo) / 2
            v = max(-1.0, min(1.0, (raw - mid) / half))
        self.axes[role] = v

    def _set_key(self, code, name, down, track=True):
        role = self._role(code)
        if role:
            self.buttons[role] = down
            if down and track:
                self.seen.add(role)
        else:
            self.other[name or f"tecla 0x{code or 0:03x}"] = down

    def frame(self, frame, now):
        """Retorna a mudança do botão Select neste quadro: True ao pressionar, False ao soltar e None sem mudança."""
        select = None
        for ev in (frame or {}).get("events") or []:
            if not isinstance(ev, dict):
                continue
            kind, code, value = ev.get("kind"), ev.get("code"), ev.get("value", 0)
            if kind == EV_KEY:
                if value == 2:               # repetição automática: não é uma soltura
                    continue
                was = self.buttons.get(self._role(code)) if self._role(code) else None
                self._set_key(code, ev.get("name"), value != 0)
                if self._role(code) == "select" and was != (value != 0):
                    select = value != 0
                self.activity_at = now
            elif kind == EV_ABS and code in self.amap:
                self._set_axis(code, value)
                role = self.amap[code][0]
                if role in ("hatx", "haty"):
                    if value:
                        self.seen.add({("hatx", True): "dr", ("hatx", False): "dl", ("haty", True): "dd",
                                       ("haty", False): "du"}[(role, value > 0)])
                    self.activity_at = now
        for stick, (x, y) in (("ls", ("lx", "ly")), ("rs", ("rx", "ry"))):
            mag = math.hypot(self.axes.get(x, 0.0), self.axes.get(y, 0.0))
            if mag > STICK_ACTIVE:
                self.activity_at = now
            if mag > 0.5:
                self.seen.add(stick)
        for t in ("lt", "rt"):
            if self.axes.get(t, 0.0) > 0.5:
                self.seen.add(t)
        self.last_at = now
        return select

    def view(self, now):
        d = self.device or {}
        return {"device": {"name": d.get("name"), "node": d.get("node"), "unique": d.get("unique"), "kind": self.kind,
                           "bus": "Bluetooth" if d.get("bus") == 5 else "USB" if d.get("bus") == 3 else None,
                           "keys_unverified": self.kind == "xbox" and not XBOX_SWAP_VERIFIED} if self.device else None,
                "buttons": {k: True for k, v in self.buttons.items() if v},
                "axes": {k: round(v, 2) for k, v in self.axes.items()},
                "other": sorted(k for k, v in self.other.items() if v),
                "last_ms": None if self.last_at is None else int((now - self.last_at) * 1000)}


# ---------------- Operações principais ----------------

PAIR_STEPS = [("pair", "Parear"), ("trust", "Marcar como confiável: reconectar após ligar"), ("connect", "Conectar"),
              ("padd", "padd reconhece o controle"), ("keys", "Testar botões: pressione cada botão e mova os analógicos")]
SCAN_STEPS = [("ready", "Bluetooth do Microduck pronto"), ("scan", "Buscando controles próximos (luz piscando rapidamente)"), ("pick", "Selecione um controle")]


def _idle_wizard():
    return {"state": "idle", "phase": None, "steps": [], "devices": [], "picked": None, "error": None, "via": None,
            "started": None, "elapsed_s": None, "result_name": None, "seen": [], "retry": None, "mac": None,
            "helper_available": None}


def _torque_on(bus):
    """Verifica se busStatus confirma o torque ligado (no modo de movimento usa native.torque_state_confirmed; no modo de comissionamento, torque_state)."""
    if not isinstance(bus, dict):
        return False
    if bus.get("mode") == "commissioning":
        return bus.get("torque_state") == "on"
    native = bus.get("native")
    return isinstance(native, dict) and native.get("torque_state_confirmed") is True


class PadOps(DriveMixin):
    def __init__(self, log, configd=None, bt=None, tap=None, robot=None, *, helper=None, clock=time.monotonic,
                 exists=os.path.exists, read_text=None, robotd_toml=ROBOTD_TOML, weird_ble=WEIRD_BLE, waits=None,
                 state_dir=None, audio=None):
        self.log = log
        self.configd, self.bt, self.tap, self.robot = configd, bt, tap, robot
        self.audio = audio
        self.helper = helper_api if helper is None else helper
        self._helper_pad_ok = None       # None: ainda não verificado; True: Assistente novo aceita pad-pair; False: versão antiga ou ausente
        self.clock = clock
        self.exists = exists
        self.read_text = read_text or _read_text
        self.robotd_toml, self.weird_ble_path = robotd_toml, weird_ble
        w = {"poll": 0.1, "status_watch": 2.0, "status_job": 0.5, "padd": PADD_WAIT_S, "connect": CONNECT_WAIT_S,
             "readback": TEST_READBACK_S, "torque": TEST_TORQUE_WAIT_S, "press": TEST_PRESS_WAIT_S,
             "lease": WATCH_LEASE_S, "scan_tick": 0.5, "pair_window": PAIR_WINDOW_S, "scan_min": 3,
             "pad_timeout": PAD_PAIR_TIMEOUT_S,
             "reconnect_after": 2.0, "reconnect_interval": 4.0, "reconnect_timeout": 5.0,
             "probe": TEST_PROBE_S, "shutdown_hold": SHUTDOWN_HOLD_S, "select_long": SELECT_LONG_S,
             "relax_guard": RELAX_GUARD_S, "files": 10.0, "bindings": 10.0}
        w.update(waits or {})
        self.w = w
        self._lk = threading.RLock()
        self._wake = threading.Event()
        self._closing = False
        self._worker = None
        self._watch_until = 0.0
        self._status = None              # resultado mais recente de configd pad.status
        self._status_at = None
        self._status_error = None
        self._status_due = 0.0
        self._robot = {}                 # leituras do robotd recebidas pelo app
        self._robot_at = None
        self._netpad = None
        self._netpad_why = None
        self._worker_error = None        # erro na thread de monitoramento: não foi possível detectar um controle físico (revisão 2, severidade média 3)
        self._snap_errors = set()
        self.live = LiveInput()
        self.tap_state, self.tap_why = "off", None
        self._tap_on = False
        self._attach_wait_since = None
        self._tap_err_said = False
        self.bindings = None
        self._bindings_at = -1e9
        self._bindings_err = None
        self.wiz = _idle_wizard()
        self._job = None                 # (id, thread)
        self._job_id = 0
        self._cancel = threading.Event()
        self._configd_thread = None      # configd pad.pair não pode ser interrompido: não permite novo pareamento enquanto a thread estiver ativa (revisão 10)
        self._configd_until = 0.0
        self.test = {"state": "idle"}
        self._test_evt = threading.Event()
        self.on_estop_passed = None          # registra teste de emergência aprovado (app conecta a onboard.Onboarding.note_estop)
        self.battery_shutdown = None         # [safety] battery_empty_shutdown do robotd define o aviso de bateria baixa na página (tarefa 1)
        self._attach_said = None             # registra o dispositivo attached apenas quando ele muda (revisão O16: desconectar por 6 s e voltar gera uma linha)
        self._pad_config = robotd_toml       # arquivo em que padd lê [netpad] e [pad_imu_head_control]: opção --config de padd.service (_refresh_files)
        self._drive_init(state_dir)
        self.motion_studio = MotionStudio(self)
        # move / sticks / keys / stop usam seu próprio pool de threads para não disputar com chamadas lentas de configd, Bluetooth e solicitações pontuais (revisão 2, severidade média 4);
        # a terceira rodada acrescentou sinais periódicos dos analógicos, botões e modos; quatro threads mantêm parada e recentralização sem fila (3 V13)
        self._fast_pool = concurrent.futures.ThreadPoolExecutor(max_workers=FAST_WORKERS, thread_name_prefix="pad-fast")
        # robotd.toml e padd.service são lidos em segundo plano; snapshot usa apenas o cache (é chamado no loop de eventos: revisão 2, severidade média 9)
        self._files_stop = threading.Event()
        self._refresh_files()
        threading.Thread(target=self._files_loop, name="pad-files", daemon=True).start()
        self._drive_start()

    # ================= Interface pública =================

    def handle(self, args, by=None, conn=None):
        from .updates import safe_during_update
        if self._update_blocked() and not safe_during_update('pad.op',args):
            raise Refused('A proteção de atualização do software/programa principal está ativa; a parada de emergência e o encerramento da voz continuam disponíveis')
        with self.motion_studio.request():
            return self._handle_request(args, by=by, conn=conn)

    def _handle_request(self, args, by=None, conn=None):
        """Instrução da página (executada em uma thread). Retorna um dict para a página; se não puder ser executada, lança Refused com o motivo exibido ao usuário.
        by: identificação legível, como “computador 192.168.1.5”; conn: conexão da página (distingue até duas abas no mesmo computador)."""
        op = args.get("op")
        if conn is not None and conn in self._gone and op not in ("watch", "stop", "action_stop", "drive"):
            raise Refused("Esta página já foi desconectada")      # instrução que chegou tarde ao pool de threads (revisão 2 S1)
        if op == "motion":
            return self.motion_studio.handle(args, conn, by)
        if op == "audio":
            values = {key:value for key,value in args.items() if key != "op"}
            if not values or set(values)-{"listening","music"} or any(type(value) is not bool for value in values.values()):
                raise Refused("A voz aceita apenas os controles de escuta e música")
            if conn is None or conn in self._gone or conn in self._closed:
                raise Refused("Volte à área de controle remoto para usar a voz")
            if self.audio is None:
                raise Refused("O serviço de voz não está configurado; verifique duck-echo")
            if values.get("listening") is False or values.get("music") is False:
                with self._lk:
                    if (self.motion_studio.session or {}).get("idle_kind") == "music":
                        self.motion_studio.invalidate("O modo de escuta ou música foi desativado")
            try:
                return {"audio":self.audio.set(**values)}
            except (OSError,ValueError,TypeError):
                raise Refused("Não foi possível conectar ao serviço de voz; verifique duck-echo") from None
        if self.motion_studio.before(args, conn, by) is False:
            return {"dropped": "A sessão de movimento mudou; a solicitação antiga foi descartada"}
        if op == "watch":
            self._watch()
            return {}
        if op == "refresh":
            self._poll_status()
            with self._lk:
                return {"status": self._status_view(self.clock())}
        if op == "scan":
            secs = args.get("seconds", SCAN_S)
            try:
                secs = max(self.w["scan_min"], min(SCAN_MAX_S, float(secs)))
            except (TypeError, ValueError):
                raise Refused("O tempo de busca deve ser um número de segundos") from None
            if not math.isfinite(secs):
                raise Refused("O tempo de busca deve ser um número de segundos")
            return self._start_job("scan", self._job_scan, secs)
        if op == "pair":
            mac = args.get("mac")
            if mac is not None and not MAC_RE.match(str(mac)):
                raise Refused("Formato de endereço MAC inválido; use algo como AA:BB:CC:DD:EE:FF")
            return self._start_job("pair", self._job_pair, (mac.upper() if mac else None, by))
        if op == "cancel":
            return self._cancel_job()
        if op == "forget":
            mac = str(args.get("mac") or "")
            if not MAC_RE.match(mac):
                raise Refused("Formato de endereço MAC inválido; use algo como AA:BB:CC:DD:EE:FF")
            return self._forget(mac.upper(), by)
        if op == "keys_done":
            return self._keys_done(manual=True)
        if op == "wizard_reset":
            with self._lk:
                if self._job_alive():
                    raise Refused("Busca ou pareamento em andamento: clique em ‘Parar’ primeiro")
                self.wiz = _idle_wizard()
            return {}
        if op == "estop_test":
            return self._estop_test(args.get("action"))
        # ---- Movimentação do Microduck (pad_drive.py) ----
        if op == "drive":
            return self._drive(args, conn, by)
        if op == "move":
            return self._move(args, conn, by)
        if op == "sticks":
            return self._sticks(args, conn, by)
        if op == "stop":
            return self._stop_move(args, conn, by)
        if op == "mode":
            return self._mode_op(args, conn, by)
        if op == "keys":
            return self._keys_op(args, conn, by)
        if op == "start":
            return self._start(args, conn, by)
        if op == "key":
            return self._key_press(args, conn, by)
        if op == "reboot":
            return self._reboot(args, conn, by)
        if op == "drive_mode":
            return self._drive_mode(args, conn, by)
        if op in ("stand", "walk", "walk_stop", "sit", "skill", "sound"):
            return self._motion_cmd(op, args, conn, by)
        if op == "action_start":
            return self._action_start(args, conn, by)
        if op == "action_hold":
            return self._action_hold(conn, args.get("press"))
        if op == "action_stop":
            return self._action_stop(conn, "O usuário clicou em parar ou soltou o botão")
        if op == "combo_save":
            return self._combo_save(args)
        if op == "combo_delete":
            return self._combo_delete(args)
        raise Refused(f"Instrução desconhecida: {op}")

    def watched(self):
        """Quando alguém vê a página, está pareando ou testando a parada de emergência, o app envia snapshots a 10 Hz; nos demais casos, 1 Hz é suficiente."""
        with self._lk:
            return self._busy_reason(self.clock())

    def feed_robot(self, view):
        """Leituras de retorno do robotd, obtidas pelo app com robot_view() no loop de eventos. O contador de relaxamento também é lido aqui (revisão 1)."""
        if not isinstance(view, dict):
            return
        relax_new = False
        with self._lk:
            self._robot = view
            self._robot_at = self.clock()
            st = view.get("pad_status")
            at = view.get("pad_status_at")
            # robotd.py já consulta pad.status a cada 5 segundos; use esse dado quando ninguém estiver na página, sem fazer outra consulta
            if isinstance(st, dict) and at is not None and (self._status_at is None or at > self._status_at):
                self._status, self._status_at, self._status_error = st, at, None
            elif view.get("pad_status_error") and self._status_at is None:
                self._status_error = view.get("pad_status_error")
            relax_new = self._relax_seen(view, self.clock())
            self._drive_feed(view)          # primeira leitura do programa principal ou mudança de postura em relação a “pronto para andar” (altera apenas a memória)
        if relax_new:
            self._action_stop(None, "O torque foi relaxado")
            self._request_clear(None, "Torque relaxado (detectado na leitura de retorno)", RELAX_CLEAR_DELAY_S)   # 3 V1, item 5: apenas define a sinalização
            self._test_evt.set()

    def snapshot(self, robot=None, conn=None):
        if robot is not None:
            self.feed_robot(robot)
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            live = self.live.view(now)
            live.update(state=self.tap_state if self._tap_on else "off", why=self.tap_why)
            wiz = dict(self.wiz)
            if wiz.get("started") is not None and wiz["state"] == "running":
                wiz["elapsed_s"] = now - wiz["started"]
            wiz.pop("started", None)
            wiz["seen"] = sorted(self.live.seen) if wiz.get("phase") == "keys" else []
            wiz["configd_busy_s"] = self._configd_busy_left(now)
            wiz["helper_available"] = self._helper_pad_ok
            test = {k: v for k, v in self.test.items() if not k.startswith("_")}
            if test.get("state") == "pressed" and self.test.get("_pressed_at") is not None:
                test["held_s"] = round(now - self.test["_pressed_at"], 1)
            attached, pad_why = self._pad_attached(now)
            d = self._lease_holder(now)
            ex = self._mode_exit.get(conn)
            ks = self._keys.get(conn)
            virtual = {"owner": self._owner(now), "last": self.virtual["last"],
                       "age_ms": None if self.virtual["at"] is None else int((now - self.virtual["at"]) * 1000),
                       "mirror": attached is True, "mirror_why": pad_why if attached else None,
                       "pad_unknown": pad_why if attached is None else None, "limits": self._speed_limits(),
                       "driver": None if d is None else {"by": d["by"], "mine": d["conn"] == conn,
                                                         "for_s": int(now - d["since"])},
                       # rodada 3: modo da página registrado no backend (a página usa este valor), motivo de saída forçada do modo e teclas pressionadas
                       "mode": self._mode_of(conn), "mode_exit": None if ex is None or now - ex["at"] > 10 else
                       {"why": ex["why"], "age_s": round(now - ex["at"], 1)},
                       "keys": [] if ks is None or ks.get("end") else sorted(ks["held"]),
                       "inputs": self._inputs, "pad_imu_head": self._imu_head, "pad_imu_head_why": self._imu_head_why,
                       "latch": {k: v is not None for k, v in self._latch.items()}}
            return {"t": "pad", "status": status, "estop": self._estop_checks(now, status), "live": live,
                    "wizard": wiz, "estop_test": test, "virtual": virtual, "motion": self._motion_view(now),
                    "motion_studio": self.motion_studio.snapshot(conn, now),
                    "audio": self.audio.snapshot() if self.audio is not None else {"available":False,"why":"O serviço de voz não está configurado"},
                    "bindings": self.bindings}

    def safe_snapshot(self, conn=None):
        """Usado pelo loop de envio do app: registra cada erro apenas uma vez e retorna None para ignorar este quadro,
        sem encerrar o loop de envio (o botão superior de relaxamento também ficaria desativado: revisão 2 I3)."""
        try:
            return self.snapshot(conn=conn)
        except Exception as e:  # noqa: BLE001
            key = f"{type(e).__name__}: {e}"[:200]
            if key not in self._snap_errors:
                self._snap_errors.add(key)
                self.log.error("Falha ao calcular o estado da página do controle; quadro ignorado", cat="Controle", raw=key, exc=True,
                               hint="Problema no Studio; exporte e compartilhe o pacote de diagnóstico. Este erro será registrado apenas uma vez")
            return None

    def diag(self):
        """Usado no pacote de diagnóstico: inclui o snapshot, mas mostra apenas a quantidade de dispositivos Bluetooth próximos e nomes/MACs parciais (revisão 2, severidade média 8: o pacote será compartilhado)."""
        snap = self.safe_snapshot()
        if snap is None:
            return {"error": "Falha no snapshot; consulte o log"}
        wiz = snap.get("wizard") or {}
        devs = wiz.get("devices") or []
        wiz["devices"] = {"count": len(devs), "pads": sum(1 for d in devs if d.get("pad")),
                          "items": [{"name": _mask_name(d.get("name")), "mac": _mask_mac(d.get("mac")), "pad": d.get("pad"),
                                     "rssi": d.get("rssi")} for d in devs[:20]]}
        for k in ("mac", "picked"):
            if wiz.get(k):
                wiz[k] = _mask_mac(wiz[k])
        dev = (snap.get("live") or {}).get("device") or {}
        if dev.get("unique"):
            dev["unique"] = _mask_mac(dev["unique"])
        return snap

    def estop_ok(self):
        """Retorna apenas se a parada de emergência está válida (o resumo em state.py chamará este método para evitar calcular um snapshot completo a cada quadro: revisão 23)."""
        now = self.clock()
        with self._lk:
            return self._estop_checks(now, self._status_view(now))["ok"]

    def onboard_view(self):
        """Dados usados nas etapas 3 e 4 do roteiro inicial (onboard.py chama a cada 0,5 s): mesmo status/estop do snapshot do controle (revisão O7 da reorganização do resumo),
        além do dispositivo detectado pelo acesso paralelo (evidência de que há um controle conectado quando configd não consegue ler: revisão O5). Não acessa a rede; apenas lê a memória sob bloqueio."""
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            attached = self._tap_on and self.tap_state == "attached"
            dev = dict(self.live.device or {}) if attached else None
            es = self._estop_checks(now, status)
        return {"known": status["known"], "error": status["error"], "pads": status["pads"], "active": status["active"],
                "attached": attached, "device": {"name": (dev or {}).get("name"), "unique": (dev or {}).get("unique")} if dev else None,
                "estop": {"state": es["state"], "checks": es["checks"]}}

    def _estop_passed_record(self):
        """Ao aprovar o teste de emergência, informa ao roteiro inicial qual controle e versão do programa principal foram usados (revisão O6: é preciso testar de novo após trocar o controle ou atualizar o programa).
        Chamado pela thread de teste sem manter o bloqueio; erros no callback são apenas registrados no log."""
        hook = getattr(self, "on_estop_passed", None)
        if hook is None:
            return
        now = self.clock()
        with self._lk:
            status = self._status_view(now)
            a = status["active"] or {}
            dev = self.live.device or {}
            mac = a.get("mac") or (dev.get("unique") if self.tap_state == "attached" else None)
            name = a.get("name") or dev.get("name")
            bus = (self._robot or {}).get("bus") if isinstance((self._robot or {}).get("bus"), dict) else {}
            rec = {"ms": self.test.get("ms"), "mac": mac, "name": name, "build": bus.get("build")}
        try:
            hook(rec)
        except Exception as e:  # noqa: BLE001
            self.log.error("Falha ao registrar a aprovação do teste de emergência", cat="Segurança", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="Problema no Studio; o teste de emergência foi aprovado, mas não foi registrado no roteiro do resumo")

    def close(self):
        self._closing = True
        self._cancel.set()
        self._wake.set()
        self._test_evt.set()
        self._action_stop(None, "O Studio foi encerrado")
        self._drive_close()                 # recentraliza a cabeça e o corpo e solta as teclas pressionadas (3 V1, item 9; tenta enviar os comandos)
        if self.audio is not None:
            self.audio.close()
        self._files_stop.set()
        try:
            self._fast_pool.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: BLE001
            pass
        if self.tap is not None and self._tap_on:
            try:
                self.tap.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.bt is not None:
            try:
                self.bt.close()
            except Exception:  # noqa: BLE001
                pass

    # ================= Estado =================

    def _status_view(self, now):
        st = self._status if isinstance(self._status, dict) else None
        pads = []
        for p in (st or {}).get("pads") or []:
            if isinstance(p, dict):
                pads.append({"mac": p.get("mac"), "name": p.get("name"), "paired": p.get("paired"),
                             "trusted": p.get("trusted"), "connected": p.get("connected"),
                             "kind": pad_kind(p.get("name"))})
        active = next((p for p in pads if p["connected"]), None)
        age = None if self._status_at is None else now - self._status_at
        known = st is not None and age is not None and age < 20
        return {"known": known, "error": None if known else self._status_error,
                "driver": (st or {}).get("driver") if known else None, "pads": pads if known else [],
                "active": active if known else None, "age_ms": None if age is None else int(age * 1000),
                "netpad": self._netpad_value(now), "netpad_why": self._netpad_why}

    def _netpad_value(self, now=None):
        """Valor de [netpad] enabled em /etc/robot/robotd.toml (em cache; o arquivo é lido em _refresh_files). Se a leitura falhar, retorna None: o Studio não conseguir ler não significa que o padd também não consiga (revisão 7); por isso, a verificação de emergência trata como “não confirmado”, não como “desativado”.
        Atenção: o padd lê a configuração apenas ao iniciar; se o arquivo mudar sem reiniciar o padd, este valor não refletirá a configuração ativa."""
        return self._netpad

    def _refresh_files(self):
        """Lê o arquivo de unidade do padd (velocidade com o analógico no máximo, amplitude da cabeça/boca e caminho da configuração) e, em seguida, as seções [netpad] e [pad_imu_head_control] desse arquivo. Armazena os dados em cache. Roda em uma thread em segundo plano (com uma leitura síncrona inicial durante a construção).
        O padd lê a configuração indicada por --config (o padrão é /etc/robot/robotd.toml; o drop-in deste fork aponta para /etc/robot/feetech-ft5/robotd.toml: fork packaging/gamepad.py:94). As duas seções são lidas desse caminho (fork padd main.rs:692, 776)."""
        try:
            texts = self._read_padd_texts()
            limits = parse_speed_limits(texts)
            inputs, cfg = self._read_inputs(texts)
        except Exception as e:  # noqa: BLE001 — o parser não lança exceções; se algo inesperado ocorrer, usa os padrões oficiais
            limits = dict(self._limits, src=f"Padrões oficiais (falha ao ler a configuração do padd: {type(e).__name__})")
            inputs, cfg = self._inputs, None
        path = cfg or self.robotd_toml
        imu_head, imu_why = None, None
        config_text = None
        try:
            config_text = self.read_text(path)
            data = tomllib.loads(config_text)
            netpad, why = bool((data.get("netpad") or {}).get("enabled", False)), None
            ih = data.get("pad_imu_head_control") or {}
            imu_head = bool(ih.get("enabled", False)) if isinstance(ih, dict) else None
        except FileNotFoundError:
            # Arquivo ausente: robotd usa os padrões; [netpad] fica desativado por padrão (robotd-params lib.rs:107-121);
            # [pad_imu_head_control] também fica desativado por padrão (fork robotd-params lib.rs:140-155)
            netpad, why = False, f"Arquivo {path} ausente; usando o padrão (desativado)"
            imu_head, imu_why = False, why
        except PermissionError as e:
            netpad, why = None, f"O Studio não tem permissão para ler {path} ({e.strerror or e})"
            imu_why = why
        except Exception as e:  # noqa: BLE001 — formato inválido ou outro erro de leitura
            netpad, why = None, f"Não foi possível ler {path} ({type(e).__name__}: {e})"
            imu_why = why
        with self._lk:
            self._netpad, self._netpad_why, self._limits = netpad, why, limits
            self._inputs, self._pad_config = inputs, path
            self._imu_head, self._imu_head_why = imu_head, imu_why
            self._motion_config_digest = _digest({"padd": texts, "path": path, "config": config_text})

    def _files_loop(self):
        while not self._files_stop.wait(self.w["files"]):
            try:
                self._refresh_files()
            except Exception as e:  # noqa: BLE001
                self.log.error("Falha ao ler arquivo de configuração em segundo plano", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True)

    def _robot_ok(self, now):
        r = self._robot or {}
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else None
        if r.get("paused"):
            return False, "Ajuste dos servos em andamento: o programa principal está pausado conforme planejado"
        if r.get("present") is False:
            return False, "O programa principal robotd não está em execução"
        if self._robot_at is None or now - self._robot_at > BUS_FRESH_S:
            return None, "O Studio não recebeu os dados de retorno do programa principal"
        if bus is None or r.get("bus_at") is None or now - r["bus_at"] > BUS_FRESH_S:
            return None, "Não foi possível ler o estado do programa principal"
        if bus.get("phase") in STARTING_PHASES:
            return False, "O programa principal ainda está iniciando"
        if bus.get("mode") == "commissioning":
            return False, "Modo de comissionamento: Select não passa pelo programa principal"
        if bus.get("mode") != "motion":
            return None, f"O programa principal está no modo {bus.get('mode')}"
        return True, None

    def _estop_checks(self, now, status):
        """Quatro condições para considerar a parada de emergência válida (plano v3.1 §3): controle conectado, padd em execução, programa principal em execução e netpad desativado.
        Com o acesso paralelo ativo, verifica também se o padd abriu este controle (caso em que está conectado, mas sem dispositivo de entrada; pair-a-gamepad.md:184-189).
        Se configd não responder, mas o acesso paralelo detectar attached, usa essa observação como evidência (é mais direta que configd: revisão 16).
        Estado: ok significa que todos passaram; unknown indica que nenhum falhou, mas há itens sem confirmação; bad indica ao menos uma falha."""
        checks = []
        tap_ok = self._tap_on and self.tap_state == "attached"
        dev = (self.live.device or {}).get("name") if tap_ok else None
        if not status["known"]:
            if tap_ok:
                checks.append({"key": "pad", "label": "Controle conectado", "ok": True,
                               "why": f"{dev or 'controle'} (detectado pelo acesso paralelo do padd; configd indisponível)"})
            else:
                checks.append({"key": "pad", "label": "Controle conectado", "ok": None, "why": status["error"] or "Não foi possível ler o estado do controle no configd"})
        else:
            a = status["active"]
            checks.append({"key": "pad", "label": "Controle conectado", "ok": bool(a),
                           "why": a["name"] if a else ("Nenhum controle pareado está ligado" if status["pads"] else "Nenhum controle foi pareado")})
        drv = status["driver"]
        if drv is None and tap_ok:
            checks.append({"key": "padd", "label": "padd em execução (encaminha os botões do controle ao programa principal)", "ok": True,
                           "why": "O acesso paralelo do padd está ativo e enviando botões (configd indisponível)"})
        else:
            checks.append({"key": "padd", "label": "padd em execução (encaminha os botões do controle ao programa principal)",
                           "ok": None if drv is None else drv == "active", "why": None if drv in (None, "active") else f"Estado atual do padd: {drv}"})
        ok, why = self._robot_ok(now)
        checks.append({"key": "robotd", "label": "Programa principal em execução (modo de movimento)", "ok": ok, "why": why})
        np = status["netpad"]
        checks.append({"key": "netpad", "label": "Controle UDP (netpad) desativado", "ok": None if np is None else not np,
                       "why": "[netpad] está ativo: o padd lê apenas UDP, não controles Bluetooth" if np else
                       (status.get("netpad_why") if np is False else
                        f"{status.get('netpad_why') or 'Não foi possível ler robotd.toml'} : netpad não foi verificado. Se estiver ativo, o controle Bluetooth e sua parada de emergência não funcionarão")})
        if self._tap_on and (status["active"] or tap_ok):
            if self.tap_state == "attached":
                checks.append({"key": "input", "label": "O padd abriu este controle (botões legíveis)", "ok": True, "why": None})
            elif self.tap_state == "waiting" and self._attach_wait_since is not None and now - self._attach_wait_since > 3:
                checks.append({"key": "input", "label": "O padd abriu este controle (botões legíveis)", "ok": False,
                               "why": "Conectado, mas o padd não o abriu: provavelmente não há dispositivo de entrada. Remova o pareamento, coloque-o novamente em modo de pareamento e tente de novo."})
        vals = [c["ok"] for c in checks]
        good = all(v is True for v in vals)
        state = "ok" if good else ("bad" if any(v is False for v in vals) else "unknown")
        return {"ok": good, "state": state, "checks": checks}

    def _poll_status(self):
        if self.configd is None:
            with self._lk:
                self._status_error = "O configd não está configurado neste Microduck"
            return None
        try:
            r = self.configd.call("pad.status", {}, 2.0)
            if not isinstance(r, dict):
                raise RpcError("pad.status", None, f"A resposta não é um objeto ({type(r).__name__})")
        except NoPermission as e:
            with self._lk:
                if self._status_error is None:
                    self.log.warn("O Studio não tem permissão para ler o estado do controle no configd", cat="Controle", step="pad.status", raw=str(e), hint=ROBOT_GROUP)
                self._status_error = str(e)
            return None
        except (Unreachable, Timeout, RpcError) as e:
            with self._lk:
                if self._status_error is None:
                    self.log.warn("Não foi possível ler o estado do controle no configd", cat="Controle", step="pad.status", raw=str(e),
                                  hint="Alguns Microducks mantêm o configd desativado (sudo systemctl start configd); isso não impede o robô de ficar em pé ou andar")
                self._status_error = str(e)
            return None
        with self._lk:
            if self._status_error is not None:
                self.log.info("A leitura do estado do controle no configd foi restabelecida", cat="Controle")
            self._status, self._status_at, self._status_error = r, self.clock(), None
        return r

    def _pad_in_status(self, mac):
        st = self._status if isinstance(self._status, dict) else {}
        for p in st.get("pads") or []:
            if isinstance(p, dict) and (p.get("mac") or "").upper() == (mac or "").upper():
                return p
        return None

    # ================= Monitoramento: ativo durante visualização, tarefas ou teste de emergência =================

    def _watch(self):
        """Alguém está vendo a página do controle. Renova apenas a concessão de visualização, não a do controle virtual (manter a página aberta não conta como controle ativo: revisão 2 I1)."""
        now = self.clock()
        with self._lk:
            first = self._watch_until < now
            self._watch_until = now + self.w["lease"]
            if first:
                self._status_due = 0.0
                self._bindings_due = 0.0          # A thread de monitoramento busca pad.bindings (3 V13: watch roda no pool rápido e não pode esperar 2 segundos)
        self._ensure_worker()

    def _fetch_bindings(self):
        """Consulta quais ações estão associadas aos cinco botões no robotd (pad.bindings: fork lib.rs:4478-4497; o robotd lê a configuração a cada consulta,
        o padd relê a cada segundo: padd:806-817). A thread de monitoramento consulta a cada 10 segundos e também atualiza antes de executar uma ação se os dados estiverem antigos (3 V14). Não lança exceções."""
        if self.robot is None:
            return None
        try:
            r = self.robot.call("pad.bindings", {}, 2.0)
        except (Unreachable, Timeout, RpcError) as e:
            with self._lk:
                self._bindings_at = self.clock()       # Considera a tentativa como consulta mesmo sem resposta: tenta de novo após 10 segundos, sem atrasar cada botão em 2 segundos
                said = self._bindings_err is not None
                self._bindings_err = str(e)
            if not said:
                self.log.info("Não foi possível ler as associações dos botões do controle (usando os padrões oficiais)", cat="Controle", step="pad.bindings", raw=str(e))
            return None
        rows = r.get("bindings") if isinstance(r, dict) else None
        rows = [b for b in rows if isinstance(b, dict)] if isinstance(rows, list) else None
        with self._lk:
            changed = rows != self.bindings
            self.bindings, self._bindings_at, self._bindings_err = rows, self.clock(), None
        if changed and rows is not None:
            text = ", ".join(f"{b.get('button')}={b.get('skill') or '(desativado)'}" + (f"({b['error']})" if b.get("error") else "")
                            for b in rows)
            self.log.info(f"Associações dos botões do controle: {text}", cat="Controle", step="pad.bindings")
        return rows

    def _ensure_worker(self):
        with self._lk:
            if self._worker is not None and self._worker.is_alive():
                self._wake.set()
                return
            self._worker = threading.Thread(target=self._worker_loop, name="pad-watch", daemon=True)
            self._worker_error = None
            self._worker.start()

    def _busy_reason(self, now):
        return (self._watch_until > now or self._job_alive()
                or self.test.get("state") not in FINAL)

    def _worker_loop(self):
        try:
            while not self._closing:
                now = self.clock()
                with self._lk:
                    alive = self._busy_reason(now)
                    watching = self._watch_until > now or self.test.get("state") not in FINAL \
                        or self.wiz.get("phase") in ("padd", "keys")
                    if not alive:
                        self._worker = None
                if not alive:
                    break
                if now >= self._status_due:
                    self._status_due = now + (self.w["status_job"] if self._job_alive() else self.w["status_watch"])
                    self._poll_status()
                if now >= self._bindings_due and self._watch_until > now:
                    self._bindings_due = now + self.w["bindings"]
                    self._fetch_bindings()
                self._tap_lease(watching)
                self._keys_tick()
                self._wake.wait(self.w["poll"])
                self._wake.clear()
        except Exception as e:  # noqa: BLE001 — a thread de monitoramento não pode encerrar silenciosamente
            self.log.error("Erro na thread de monitoramento da página do controle", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="Problema no Studio; exporte o pacote de diagnóstico. Atualize a página do controle para iniciar outra thread")
            with self._lk:
                self._worker = None
                self._worker_error = f"{type(e).__name__}: {e}"
        finally:
            self._tap_lease(False)

    # ---- Acesso paralelo ----

    def _tap_lease(self, want):
        if self.tap is None:
            return
        with self._lk:
            if want == self._tap_on:
                return
            self._tap_on = want
            if want:
                self.tap_state, self.tap_why = "connecting", None
                self._attach_wait_since = None
        if want:
            self.tap.start(self._on_tap_report, self._on_tap_state)
        else:
            self.tap.stop()
            with self._lk:
                self.live.reset()
                self.tap_state, self.tap_why = "off", None

    def _on_tap_state(self, state, why=None):
        with self._lk:
            if state == "waiting" and self.tap_state != "waiting":
                self._attach_wait_since = self.clock()
            if (state, why) != (self.tap_state, self.tap_why) and state in ("absent", "denied", "error"):
                self.log.warn(f"Não foi possível ler os botões do controle (acesso paralelo do padd): {why}", cat="Controle", step="pad.input",
                              hint=ROBOT_GROUP if state == "denied" else "O padd só fica ativo enquanto o programa principal está em execução")
            self.tap_state, self.tap_why = state, why

    def _on_tap_report(self, rep):
        """Chamado pela thread de acesso paralelo para attached / frame / detached (os eventos de IMU são ignorados). Erros são registrados, sem serem propagados (revisão 15)."""
        if not isinstance(rep, dict):
            return
        try:
            self._tap_report(rep)
        except Exception as e:  # noqa: BLE001
            if not self._tap_err_said:
                self._tap_err_said = True
                self.log.error("Erro no Studio ao processar os botões do controle", cat="Controle", raw=f"{type(e).__name__}: {e}  ·  {json.dumps(rep)[:300]}",
                               exc=True, hint="Problema no Studio; exporte o pacote de diagnóstico")

    def _tap_report(self, rep):
        now = self.clock()
        kind = rep.get("report")
        with self._lk:
            if kind == "attached":
                self.live.attach(rep.get("device"), now)
                self.tap_state, self.tap_why = "attached", None
                d = self.live.device or {}
                key = (d.get("name"), d.get("unique"), d.get("node"))
                if key != self._attach_said:
                    self._attach_said = key
                    self.log.info(f"O padd abriu o controle: {d.get('name')} ({d.get('node')})", cat="Controle", dedup=False)
            elif kind == "frame":
                sel = self.live.frame(rep, now)
                if sel is not None:
                    self._on_select(sel, now)
            elif kind == "detached":
                self.live.reset()
                self.tap_state, self.tap_why = "waiting", rep.get("why")
                self._attach_wait_since = now
                self.log.info(f"O controle foi desconectado do padd: {rep.get('why')}", cat="Controle")
        if kind == "attached":
            self._action_stop(None, "Um controle físico foi conectado")
            self._request_clear(None, "Um controle físico foi conectado")     # 3 V1, item 6: também limpa os espelhamentos de cabeça/corpo definidos pela página
            with self._lk:
                error = self.wiz.get("error") or {}
                if (self.wiz.get("state") == "failed" and error.get("code") in ("no_input", "not_connected")
                        and self._pair_input_matches(self.wiz.get("mac")) and self._mine(self._job_id)):
                    self._pair_keys_ready(self._job_id, self.wiz.get("mac"))

    # ================= Assistente de pareamento =================

    def _job_alive(self):
        # Considera apenas trabalhos ainda em execução: após falhar ou aguardar uma seleção, a thread pode continuar viva; nesse momento, “Tentar novamente” não deve ser tratado como ocupado
        return self._job is not None and self._job[1].is_alive() and self.wiz.get("state") == "running"

    def _configd_busy_left(self, now):
        t = self._configd_thread
        if t is None or not t.is_alive():
            return None
        return max(1, int(self._configd_until - now))

    def _start_job(self, kind, fn, arg):
        now = self.clock()
        with self._lk:
            if self._job_alive():
                raise Refused("Busca ou pareamento em andamento: aguarde a conclusão ou clique em ‘Parar’")
            if self.test.get("state") not in FINAL:
                raise Refused("Teste de emergência em andamento: aguarde a conclusão ou clique em ‘Cancelar teste’")
            left = self._configd_busy_left(now)
            if left is not None:
                raise Refused(f"O pareamento anterior do configd ainda não terminou e não pode ser interrompido. Deve levar mais {left} segundos; aguarde antes de tentar novamente")
            # Revisão 8: busca e pareamento ocupam o rádio; o controle em uso pode travar sem desconectar, e o padd continua enviando o último valor do analógico sem acionar o deadman
            bus = (self._robot or {}).get("bus")
            if self._posture() in DRIVING or (isinstance(bus, dict) and bus.get("policy_enabled") is True):
                msg, fix = FAILS["driving"]
                raise Refused(f"{msg}：{fix}")
            self._job_id += 1
            jid = self._job_id
            self._cancel = threading.Event()
            keep = kind == "pair" and self.wiz.get("phase") == "pick"
            if not keep:
                self.wiz = _idle_wizard()
            self.wiz.update(state="running", started=self.clock(), error=None, retry=None,
                            elapsed_s=None, result_name=None)
            t = threading.Thread(target=self._run_job, args=(jid, fn, arg), name=f"pad-{kind}", daemon=True)
            self._job = (jid, t)
            t.start()
        self._ensure_worker()
        return {"job": jid}

    def _run_job(self, jid, fn, arg):
        try:
            fn(jid, arg)
        except Exception as e:  # noqa: BLE001 — não deveria ocorrer; se ocorrer, a página precisa exibir o motivo
            self.log.error("Erro no assistente de pareamento", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="Falha no Studio; exporte o pacote de diagnóstico")
            self._fail(jid, None, "other", f"Erro no Studio: {type(e).__name__}: {e}")
        finally:
            with self._lk:
                if self.wiz.get("state") == "running" and jid == self._job_id:
                    self.wiz["elapsed_s"] = self.clock() - (self.wiz.get("started") or self.clock())
            self._wake.set()

    def _mine(self, jid):
        return jid == self._job_id and not self._cancel.is_set()

    def _step(self, jid, key, state, note=None):
        with self._lk:
            if jid != self._job_id:
                return
            for s in self.wiz["steps"]:
                if s["key"] == key:
                    if s["state"] == "ok" and state == "doing":
                        return               # não desfaz uma etapa já concluída
                    s["state"] = state
                    if note is not None:
                        s["note"] = note
            self.wiz["phase"] = key if state in ("doing", "fail") else self.wiz["phase"]

    def _note(self, jid, key, extra):
        with self._lk:
            for s in self.wiz["steps"]:
                if jid == self._job_id and s["key"] == key:
                    s["note"] = "；".join(x for x in (s.get("note"), extra) if x)

    def _fail(self, jid, key, code, raw=None, retry=None):
        with self._lk:
            if jid != self._job_id:
                return
            if key:
                self._step(jid, key, "fail")
            err = explain(code, raw)
            self.wiz.update(state="failed", error=err, retry=retry)
            if self.wiz.get("started") is not None:
                self.wiz["elapsed_s"] = self.clock() - self.wiz["started"]
        lvl = "info" if code == "cancelled" else "warn"
        self.log.write(f"Falha ao parear o controle: {err['msg']}", cat="Controle", level=lvl, step=key, raw=raw, hint=err["fix"])

    def _set_steps(self, jid, defs, keep=False):
        with self._lk:
            if jid != self._job_id:
                return
            have = {s["key"] for s in self.wiz["steps"]} if keep else set()
            if not keep:
                self.wiz["steps"] = []
            for k, label in defs:
                if k not in have:
                    self.wiz["steps"].append({"key": k, "label": label, "state": "todo", "note": None})

    def _sleep(self, s):
        """Espera interrompível pelo comando “Parar”. Retorna True se interrompida."""
        return self._cancel.wait(s)

    # ---- Busca ----

    def _job_scan(self, jid, seconds):
        self._set_steps(jid, SCAN_STEPS)
        if not self._prepare_adapter(jid, via_helper=self._helper_pad_ok):
            return
        bt = self.bt
        self._step(jid, "scan", "doing", f"No máximo {seconds:g} s")
        self.log.info(f"Iniciando busca por controles ({seconds:g} s)", cat="Controle")
        devices = []
        try:
            try:
                bt.scan_start()
            except BtError as e:
                self._fail(jid, "scan", e.code if e.code != "other" else "scan_failed", e.raw, retry={"op": "scan", "seconds": seconds})
                return
            started = self.clock()
            try:
                while self.clock() - started < seconds:
                    devices = self._device_list(bt.devices(), started)
                    with self._lk:
                        if jid == self._job_id:
                            self.wiz["devices"] = devices
                            n = sum(1 for d in devices if d["pad"])
                            self._step(jid, "scan", "doing", f"Restam {max(0, seconds - (self.clock() - started)):.0f} s · {len(devices)} dispositivos encontrados, {n} parecem controles")
                    if self._sleep(self.w["scan_tick"]):
                        break
                devices = self._device_list(bt.devices(), started)
            finally:
                try:
                    bt.scan_stop()
                except BtError as e:
                    self.log.info("Erro ao encerrar a busca Bluetooth (sem impacto)", cat="Controle", raw=e.raw)
        finally:
            # Revisão 5: encerra a sessão bluetoothctl ao fim da busca para não deixá-la aberta (o pareamento usa outra sessão e registra o agente apenas durante a janela de pareamento)
            try:
                bt.close()
            except Exception:  # noqa: BLE001
                pass
        if self._cancel.is_set():
            self._fail(jid, "scan", "cancelled")
            return
        pads = [d for d in devices if d["pad"]]
        self.log.info(f"Busca concluída: {len(devices)} dispositivos Bluetooth encontrados, {len(pads)} parecem controles", cat="Controle",
                      raw=", ".join(f"{d['name'] or '?'} {d['mac']}" for d in pads[:6]) or None)
        with self._lk:
            if jid != self._job_id:
                return
            self.wiz["devices"] = devices
            self._step(jid, "scan", "ok", f"{len(devices)} dispositivos Bluetooth encontrados, {len(pads)} parecem controles")
            fresh = [d for d in pads if not d["paired"]]
            self.wiz["picked"] = fresh[0]["mac"] if len(fresh) == 1 else None
            self.wiz["phase"] = "pick"
            self.wiz["state"] = "waiting"
            for s in self.wiz["steps"]:
                if s["key"] == "pick":
                    s["state"] = "doing"
                    s["note"] = ("É este? Clique em ‘Parear este’" if len(fresh) == 1 else
                                 "Há vários em modo de pareamento: selecione o desejado" if len(fresh) > 1 else None)
            if not pads:
                self.wiz["error"] = explain("not_found_pad" if devices else "not_found")
                self.wiz["retry"] = {"op": "scan", "seconds": seconds}

    def _device_list(self, raw_devices, since):
        """Converte os dispositivos do bluetoothctl na lista da página: inclui apenas os vistos nesta busca (com sinal), prioriza controles e combina as duas identidades do mesmo controle."""
        out = []
        for d in raw_devices or []:
            seen = d.get("seen_at")
            if not d.get("connected") and (seen is None or seen < since - 0.5):
                continue
            name = d.get("name") or d.get("alias")
            ev = gamepad_evidence(name, d.get("icon"), d.get("cls"), d.get("appearance"))
            kind = pad_kind(name)
            out.append({"mac": d.get("mac"), "name": name, "rssi": d.get("rssi"), "pad": ev is not None, "evidence": ev,
                        "classic": isinstance(d.get("cls"), int), "kind": kind if ev else None,
                        "kind_label": KIND_LABEL.get(kind) if ev else None,
                        "why_not": None if ev else (f"Parece ser {ICON_CN[d.get('icon')]}" if d.get("icon") in ICON_CN else "Não parece ser um controle"),
                        "paired": bool(d.get("paired")), "connected": bool(d.get("connected"))})
        pads = [x for x in out if x["pad"]]
        drop = set()
        for a in pads:
            for b in pads:
                if a is not b and same_pad(a["mac"], b["mac"]) and a["classic"] and not b["classic"]:
                    drop.add(b["mac"])          # Mantém a identidade Bluetooth clássica: o HID usa essa conexão (pad.rs:173-177)
        out = [x for x in out if x["mac"] not in drop]
        out.sort(key=lambda x: (not x["pad"], x["evidence"] != "classified", -(x["rssi"] if isinstance(x["rssi"], int) else -999)))
        return out

    def _prepare_adapter(self, jid, via_helper=None):
        """Etapa ready: o adaptador existe, não está bloqueado por rfkill e está ligado. A busca não exige o modo “vinculável”, apenas avisa; ele é ativado temporariamente durante o pareamento (_ensure_pairable).
        via_helper=None indica que o método ainda não foi definido; True usa o Assistente novo; False indica que ele não está disponível (método alternativo)."""
        self._step(jid, "ready", "doing")
        bt = self.bt
        if bt is None:
            self._fail(jid, "ready", "no_btctl", retry={"op": "pair"})
            return False
        a = bt.adapter()
        if a.get("missing"):
            self._fail(jid, "ready", "no_btctl", a.get("raw"), retry={"op": "pair"})
            return False
        if a.get("blocked"):
            self._fail(jid, "ready", "rfkill", a.get("raw"), retry={"op": "scan"})
            return False
        if a.get("error"):
            self._fail(jid, "ready", a.get("code") or classify(a["error"]), a["error"], retry={"op": "scan"})
            return False
        if not a.get("present"):
            self._fail(jid, "ready", "no_adapter", a.get("raw"), retry={"op": "scan"})
            return False
        notes = []
        if not a.get("powered"):
            try:
                bt.power_on()
                notes.append("Bluetooth acabou de ser ligado")
            except BtError as e:
                self._fail(jid, "ready", e.code if e.code != "other" else "powered_off", e.raw, retry={"op": "scan"})
                return False
        if a.get("pairable") is False:
            notes.append("O modo vinculável está desativado: será ativado temporariamente durante o pareamento e restaurado depois")
        if self.exists(self.weird_ble_path):
            if via_helper is True:
                notes.append("Esta placa exige pausar o btd antes de parear um controle novo: o Assistente novo pausa o btd e reinicia o Bluetooth, depois o inicia novamente")
            elif via_helper is False:
                notes.append("Esta placa exige pausar o btd antes de parear um controle novo. Sem o Assistente novo, o Studio não consegue fazer isso e o pareamento pode falhar. "
                             "Reinstale o Assistente ou execute sudo robotctl pad pair no Microduck")
            else:
                notes.append("Esta placa exige pausar o btd antes de parear um controle novo. O Assistente novo faz isso; sem ele, o pareamento pode falhar. "
                             "Reinstale o Assistente ou execute sudo robotctl pad pair no Microduck")
        self._step(jid, "ready", "ok", "；".join(notes) or None)
        return True

    def _ensure_pairable(self, jid):
        """Antes do pareamento, ativa temporariamente o modo vinculável se ele estiver desligado (caso contrário, as chaves não serão salvas: No Bonding). Retorna True se foi ativado por este código, para restaurar depois (revisão 5)."""
        bt = self.bt
        if bt is None:
            return False
        try:
            a = bt.adapter()
        except Exception:  # noqa: BLE001
            return False
        if a.get("pairable") is not False:
            return False
        try:
            bt.pairable_on()
        except BtError as e:
            self._note(jid, "ready", "Não foi possível ativar o modo vinculável (requer root); as chaves podem não ser salvas mesmo que o pareamento funcione")
            self.log.warn("Não foi possível ativar o modo vinculável do Bluetooth", cat="Controle", step="pairable on", raw=e.raw, hint="sudo btmgmt bondable on")
            return False
        self._note(jid, "ready", "Modo vinculável ativado temporariamente")
        self.log.info("Modo vinculável do Bluetooth ativado temporariamente (será restaurado após o pareamento)", cat="Controle")
        return True

    # ---- Pareamento ----

    def _job_pair(self, jid, arg):
        mac, by = arg if isinstance(arg, tuple) else (arg, None)
        from_pick = self.wiz.get("phase") == "pick"
        try:
            available = bool(self.helper.available())
        except Exception:  # noqa: BLE001 — se não for possível verificar o Assistente, considera-o indisponível
            available = False
        use_helper = self._helper_pad_ok is not False and available
        if not available:
            self._helper_pad_ok = False       # sem Assistente: mostra diretamente o aviso sobre o método alternativo
        if from_pick:
            self._set_steps(jid, SCAN_STEPS + PAIR_STEPS, keep=True)
            self._step(jid, "pick", "ok", mac)
        else:
            self._set_steps(jid, SCAN_STEPS + PAIR_STEPS)
            if use_helper:
                self._step(jid, "ready", "skip", "O Assistente cuidará disso: o robotctl oficial pausa o btd e reinicia o Bluetooth")
            elif self.bt is not None:
                if not self._prepare_adapter(jid, via_helper=False):
                    return
            else:
                self._step(jid, "ready", "skip", "bluetoothctl indisponível; verificação ignorada")
            note = ("O Assistente (robotctl oficial) buscará controles em modo de pareamento" if use_helper
                    else "O configd buscará controles em modo de pareamento") if mac is None else mac
            self._step(jid, "scan", "skip", note)
            self._step(jid, "pick", "skip" if mac is None else "ok", None if mac is None else mac)
        if self.bt is not None:
            try:
                self.bt.close()       # O Assistente fará o robotctl reiniciar o Bluetooth; encerra esta sessão antes (o método alternativo via configd também faz isso)
            except Exception:  # noqa: BLE001
                pass
        restore = False
        try:
            with self._lk:
                self.wiz.update(mac=mac, phase="pair", retry={"op": "pair", "mac": mac} if mac else {"op": "pair"})
            self._step(jid, "pair", "doing", "A luz do controle deve continuar piscando rapidamente; a busca pode levar alguns segundos")
            self.log.info(f"Iniciando pareamento do controle {mac or '(seleção automática)'}", cat="Controle", dedup=False)
            pad = None
            if use_helper:
                got = self._pair_via_helper(jid, mac, by)
                if got is _HELPER_OLD:
                    use_helper = False
                    if self.bt is not None:
                        if not self._prepare_adapter(jid, via_helper=False):
                            return
                    else:
                        self._step(jid, "ready", "skip", "bluetoothctl indisponível; verificação ignorada")
                else:
                    pad = got
            if not use_helper:
                restore = self._ensure_pairable(jid)      # apenas o método alternativo ativa temporariamente o modo vinculável
                pad = self._pair_via_configd(jid, mac)
            if pad is None:
                return
            if not self._mine(jid):
                self._fail(jid, None, "cancelled")
                return
        finally:
            if restore:
                try:
                    self.bt.pairable_off()
                    self.log.info("Restaurando o modo vinculável do Bluetooth ao estado original (desativado)", cat="Controle")
                except Exception as e:  # noqa: BLE001
                    self.log.warn("Não foi possível restaurar o modo vinculável", cat="Controle", step="pairable off", raw=str(e),
                                  hint="Isso apenas permite que outros dispositivos tentem parear. Reiniciar o Microduck restaurará o estado original")
        self._after_pair(jid, pad)

    def _pair_via_helper(self, jid, mac, by):
        """Método principal: o Assistente executa robotctl pad pair oficial como root. Conforme o marcador da placa, ele pausa o btd e reinicia o Bluetooth.
        O robotctl não pode ser interrompido, então uma thread separada aguarda sua conclusão e _tick_from_device atualiza as etapas (como no fluxo do configd)."""
        with self._lk:
            self.wiz["via"] = "Assistente (robotctl pad pair oficial: pausa o btd e reinicia o Bluetooth)"
        box = {}

        def call():
            try:
                box["r"] = self.helper.pad_pair(by or "Studio", mac=mac, timeout=self.w["pad_timeout"])
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=call, name="pad-helper-pair", daemon=True)
        t.start()
        while t.is_alive():
            t.join(self.w["status_job"])
            if self._cancel.is_set():
                self.log.info("O usuário clicou em parar; o pareamento do robotctl no Assistente continuará até terminar (pode levar um ou dois minutos). Não será possível iniciar outro antes disso",
                              cat="Controle")
                self._fail(jid, "pair", "cancelled")
                return None
            if mac:
                self._tick_from_device(jid, mac)
        if "e" in box:
            e = box["e"]
            self._fail(jid, "pair", "other", f"{type(e).__name__}: {e}", retry=self.wiz.get("retry"))
            return None
        r = box.get("r")
        if not isinstance(r, tuple) or len(r) != 3:
            self._fail(jid, "pair", "other", f"O Assistente retornou um formato inesperado (esperado: ok, result, detail): {r!r}",
                       retry=self.wiz.get("retry"))
            return None
        ok, result, detail = r
        detail = detail if isinstance(detail, dict) else {}
        if result == "bad_verb":
            self.log.info("O Assistente é antigo e não reconhece pad-pair; usando o método alternativo", cat="Controle", raw=detail.get("msg"),
                          hint="Instale a versão nova do Assistente para usar robotctl pad pair oficial")
            self._helper_pad_ok = False
            with self._lk:
                self.wiz["via"] = None
            return _HELPER_OLD
        self._helper_pad_ok = True
        pair = detail.get("pair") if isinstance(detail.get("pair"), dict) else {}
        if ok and result == "paired" and pair.get("outcome") == "paired":
            pad = pair.get("pad") if isinstance(pair.get("pad"), dict) else {}
            self.log.info(f"Pareamento concluído pelo Assistente: {pad.get('name')} {pad.get('mac')}", cat="Controle", dedup=False)
            return pad
        reason = detail.get("reason") or pair.get("reason") or "other"
        code = {"not_found": "not_found", "ambiguous": "ambiguous", "timeout": "timeout",
                "no_adapter": "no_adapter", "rejected": "rejected"}.get(reason, "other")
        if result == "timeout":
            code = "timeout"
        elif result == "no_robotctl":
            code = "no_robotctl"
        raw = "\n".join(str(x) for x in [detail.get("msg"), pair.get("detail")] +
                         list(detail.get("stderr") or []) if x)
        if reason == "rejected":
            sub = classify(raw)
            if sub in ("auth_failed", "key_missing", "le_abort", "dhkey", "pin", "not_bondable"):
                code = sub
        self._fail(jid, "pair", code, raw or result, retry=self.wiz.get("retry"))
        return None

    def _pair_via_configd(self, jid, mac):
        """O comando oficial pad.pair executa busca, agente, pareamento e confiança em uma chamada (bluez.rs:853-1052). É bloqueante e não informa progresso,
        por isso uma thread separada aguarda enquanto consulta pad.status do configd e info do bluetoothctl, marcando as etapas concluídas."""
        if self.configd is None:
            return self._pair_via_bt(jid, mac, "configd_down", "O configd não está configurado neste Microduck")
        with self._lk:
            self.wiz["via"] = "configd (pad.pair oficial)"
        params = {"timeout_seconds": int(self.w["pair_window"])}
        if mac:
            params["mac"] = mac
        box = {}
        limit = self.w["pair_window"] + PAIR_CALL_MARGIN_S

        def call():
            try:
                box["r"] = self.configd.call("pad.pair", params, limit)
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        t = threading.Thread(target=call, name="pad-configd-pair", daemon=True)
        with self._lk:
            self._configd_thread, self._configd_until = t, self.clock() + limit
        t.start()
        while t.is_alive():
            t.join(self.w["status_job"])
            if self._cancel.is_set():
                self.log.info("O usuário clicou em parar; o pareamento do configd continuará até terminar (pode levar um ou dois minutos). Não será possível iniciar outro antes disso", cat="Controle")
                self._fail(jid, "pair", "cancelled")
                return None
            if mac:
                self._tick_from_device(jid, mac)
        if "e" in box:
            e = box["e"]
            if isinstance(e, RpcError) and e.code == 14:
                self.log.info("O configd não permite que o Studio pareie (aceita apenas root); usando bluetoothctl", cat="Controle", raw=str(e))
                return self._pair_via_bt(jid, mac, "permission", str(e))
            if isinstance(e, NoPermission):
                self.log.warn("O Studio não tem permissão para se conectar ao configd; usando bluetoothctl", cat="Controle", raw=str(e), hint=ROBOT_GROUP)
                return self._pair_via_bt(jid, mac, "socket_perm", str(e))
            if isinstance(e, Unreachable):
                return self._pair_via_bt(jid, mac, "configd_down", str(e))
            if isinstance(e, Timeout):
                self._fail(jid, "pair", "timeout", str(e), retry=self.wiz.get("retry"))
                return None
            raw = getattr(e, "message", None) or str(e)
            self._fail(jid, "pair", classify(raw), raw, retry=self.wiz.get("retry"))
            return None
        r = box.get("r")
        if not isinstance(r, dict):
            self._fail(jid, "pair", "other", f"A resposta do configd não é um objeto: {r!r}")
            return None
        if r.get("outcome") == "paired":
            pad = r.get("pad") if isinstance(r.get("pad"), dict) else {}
            self.log.info(f"Pareamento concluído pelo configd: {pad.get('name')} {pad.get('mac')}", cat="Controle", dedup=False)
            return pad
        reason, detail = r.get("reason"), r.get("detail")
        code = {"not_found": "not_found", "ambiguous": "ambiguous", "timeout": "timeout", "no_adapter": "no_adapter",
                "rejected": "rejected"}.get(reason, "other")
        if reason == "rejected":
            sub = classify(detail)          # A mensagem original de recusa costuma indicar um motivo mais específico (falha de autenticação, chave ausente etc.)
            if sub in ("auth_failed", "key_missing", "le_abort", "dhkey", "pin", "not_bondable"):
                code = sub
        if reason == "not_found" and detail and "in range" in str(detail):
            code = "not_found_pad"
        self._fail(jid, "pair", code, f"{reason}：{detail}" if detail else reason, retry=self.wiz.get("retry"))
        return None

    def _pair_via_bt(self, jid, mac, why_code, why_raw):
        """Se configd não permitir o pareamento (usuário diferente de root) ou estiver indisponível, conclui pelo bluetoothctl em uma única sessão (experiência com 10-15:
        comandos separados são recusados; executar tudo na mesma sessão funciona, conforme arquivo de registro de problemas, linha 272)."""
        bt = self.bt
        if bt is None or not mac:
            # Sem MAC, não é possível parear manualmente (não se sabe qual dispositivo escolher); informa o motivo do configd
            self._fail(jid, "pair", why_code, why_raw, retry={"op": "scan", "seconds": SCAN_S} if not mac else self.wiz.get("retry"))
            return None
        with self._lk:
            self.wiz["via"] = "bluetoothctl (pareamento pelo Studio: " + {"permission": "o configd não permite que o Studio pareie",
                                                               "socket_perm": "o Studio não consegue se conectar ao configd (sem permissão)"}.get(why_code, "configd indisponível") + "）"
        classic = next((d["classic"] for d in self.wiz.get("devices") or [] if d.get("mac") == mac), None)
        if classic is None:
            classic = isinstance(bt.info(mac).get("cls"), int)

        def step(key, state, note=None):
            if self._mine(jid):
                self._step(jid, key, state, note)

        try:
            try:
                bt.pair_device(mac, classic, self._cancel, step)
            except BtError as e:
                # Microduck nº 2, revisão 10-19: ao remover o pareamento e tentar novamente logo em seguida, bluetoothctl 5.82 retorna Failed to register agent object.
                # Encerra a sessão, abre outra e tenta novamente (apenas uma tentativa).
                if "Failed to register agent object" not in (e.raw or "") or self._cancel.is_set():
                    raise
                self.log.warn("Falha ao registrar agente no bluetoothctl; encerrando a sessão e tentando uma vez em uma nova", cat="Controle",
                              step="agent", raw=e.raw)
                try:
                    bt.close()
                except Exception:  # noqa: BLE001
                    pass
                bt.pair_device(mac, classic, self._cancel, step)
        except BtError as e:
            if self._cancel.is_set():
                self._fail(jid, "pair", "cancelled")
                return None
            key = next((s["key"] for s in self.wiz["steps"] if s["state"] == "doing"), "pair")
            self._fail(jid, key, e.code, e.raw, retry=self.wiz.get("retry"))
            return None
        finally:
            try:
                bt.close()
            except Exception:  # noqa: BLE001
                pass
        info = bt.info(mac)
        return {"mac": mac, "name": info.get("name"), "paired": info.get("paired", True),
                "trusted": info.get("trusted", True), "connected": info.get("connected", True)}

    def _tick_from_device(self, jid, mac):
        """Durante o pareamento pelo configd, observa se Paired, Trusted e Connected mudam em bluetoothctl info / pad.status."""
        info = {}
        if self.bt is not None:
            try:
                info = self.bt.info(mac) or {}
            except Exception:  # noqa: BLE001
                info = {}
        p = self._pad_in_status(mac) or {}
        if info.get("paired") or p.get("paired"):
            self._step(jid, "pair", "ok")
        if info.get("trusted") or p.get("trusted"):
            self._step(jid, "trust", "ok")
        if info.get("connected") or p.get("connected"):
            self._step(jid, "connect", "ok")

    def _after_pair(self, jid, pad):
        mac = (pad.get("mac") or "").upper()
        name = pad.get("name") or mac
        with self._lk:
            self.wiz.update(mac=mac or self.wiz.get("mac"), result_name=name)
        self._step(jid, "pair", "ok", name)
        if pad.get("trusted") is False:
            self._step(jid, "trust", "fail", FAILS["not_trusted"][0] + "：" + FAILS["not_trusted"][1])
        else:
            self._step(jid, "trust", "ok")
        # helper/configd pode retornar um dispositivo pareado cujo Connect ainda está ocupado; as tentativas de reconexão têm limites de quantidade e tempo, sem remover chaves nem reiniciar o Bluetooth.
        tries, retry_at = 0, self.clock() + self.w["reconnect_after"]

        def reconnect(end):
            nonlocal tries, retry_at
            with self._lk:
                if not self._mine(jid):
                    self._fail(jid, None, "cancelled")
                    return False
                if self.tap_state == "attached" and not self._pair_input_matches(mac):
                    self._fail(jid, "padd", "wrong_input")
                    return False
                drv = (self._status or {}).get("driver") if isinstance(self._status, dict) else None
                if drv is not None and drv != "active":
                    self._fail(jid, "padd", "padd_down", f"Estado do padd: {drv}")
                    return False
                bus = (self._robot or {}).get("bus")
                if self._posture() in DRIVING or (isinstance(bus, dict) and bus.get("policy_enabled") is True):
                    self._fail(jid, None, "driving")
                    return False
                now = self.clock()
                if (tries >= 2 or now < retry_at or end <= now or not MAC_RE.fullmatch(mac)
                        or pad.get("trusted") is False or not callable(getattr(self.bt, "reconnect", None))):
                    return True
                tries += 1
                stage = self.wiz.get("phase")
            self._step(jid, stage, "doing", f"Aguardando dispositivo de entrada; tentando restabelecer a conexão ({tries}/2)…")
            try:
                self.bt.reconnect(mac, timeout=min(self.w["reconnect_timeout"], end - now))
            except BtError as e:
                self.log.info("A reconexão do controle ainda não terminou; aguardando o dispositivo de entrada", cat="Controle", raw=e.raw)
            retry_at = self.clock() + self.w["reconnect_interval"]
            return True

        # Conexão: quando configd retorna paired, o dispositivo pode ainda não estar conectado (“bonded; it will connect on its own”, robotctl main.rs:4238-4247)
        self._step(jid, "connect", "doing", "Aguardando conexão…")
        with self._lk:
            connected = bool(pad.get("connected")) or self._pair_input_matches(mac)
        end = self.clock() + self.w["connect"]
        while not connected and self.clock() < end:
            if self._sleep(self.w["status_job"]):
                self._fail(jid, "connect", "cancelled")
                return
            self._poll_status()
            with self._lk:
                connected = bool((self._pad_in_status(mac) or {}).get("connected")) or self._pair_input_matches(mac)
            if not connected and not reconnect(end):
                return
            with self._lk:
                connected = connected or self._pair_input_matches(mac)
            if not self._mine(jid):
                self._fail(jid, "connect", "cancelled")
                return
        if not connected:
            self._fail(jid, "connect", "not_connected", f"{name} {mac}; em pad.status após {self.w['connect']:g} s sem conexão",
                       retry={"op": "pair", "mac": mac} if mac else None)
            return
        self._step(jid, "connect", "ok")
        # Considera o controle reconhecido quando configd informa que o padd está ativo e o acesso paralelo confirma que ele foi aberto
        self._step(jid, "padd", "doing", "Aguardando o padd abrir o controle…")
        with self._lk:
            self.wiz["phase"] = "padd"
        self._ensure_worker()
        end = self.clock() + self.w["padd"]
        while self.clock() < end:
            self._poll_status()
            drv = (self._status or {}).get("driver") if isinstance(self._status, dict) else None
            with self._lk:
                attached = self.tap_state == "attached"
                matching = self._pair_input_matches(mac)
                tap_dead = self.tap is None or self.tap_state in ("absent", "denied", "error")
            if drv is not None and drv != "active":
                self._fail(jid, "padd", "padd_down", f"Estado do padd: {drv}")
                return
            if attached:
                if not matching:
                    self._fail(jid, "padd", "wrong_input")
                    return
                break
            if tap_dead and drv == "active":
                self._step(jid, "padd", "ok", "O padd está em execução; sem acesso paralelo não é possível confirmar a leitura dos botões")
                break
            if not reconnect(end):
                return
            if self._sleep(self.w["status_job"]):
                self._fail(jid, "padd", "cancelled")
                return
        else:
            # Um evento attached real recebido durante a última conexão/espera também vale e não pode ser substituído por um temporizador posterior.
            with self._lk:
                matching = self._pair_input_matches(mac)
            if not matching:
                actual = self._pad_in_status(mac) or {}
                if not self._mine(jid):
                    code = "cancelled"
                else:
                    code = "not_connected" if actual.get("connected") is False else "no_input"
                self._fail(jid, "padd", code, f"{self.w['padd']:g} s sem confirmação de attached pelo acesso paralelo do padd ({self.tap_state}: {self.tap_why})",
                           retry={"op": "pair", "mac": mac} if mac else None)
                return
            tap_dead = False
        self._pair_keys_ready(jid, mac, unverified=tap_dead)

    def _pair_input_matches(self, mac):
        """Confirma o sucesso apenas pelo acesso paralelo deste controle; outro controle conectado não conta. O chamador mantém _lk bloqueado."""
        unique = str((self.live.device or {}).get("unique") or "").upper()
        return self.tap_state == "attached" and bool(mac) and unique == mac.upper()

    def _pair_keys_ready(self, jid, mac, *, unverified=False):
        with self._lk:
            if not self._mine(jid):
                self._fail(jid, None, "cancelled")
                return
            if self.tap_state == "attached":
                if not self._pair_input_matches(mac):
                    self._fail(jid, "padd", "wrong_input")
                    return
                unverified = False
            elif unverified and self.tap is not None and self.tap_state not in ("absent", "denied", "error"):
                self._fail(jid, "padd", "no_input")
                return
            if not unverified and not self._pair_input_matches(mac):
                self._fail(jid, "padd", "no_input")
                return
            dev = (self.live.device or {}).get("name")
            self._step(jid, "connect", "ok")
            if not unverified:
                self._step(jid, "padd", "ok", dev)
            self.live.seen = set()
            self.wiz.update(phase="keys", state="waiting", error=None, retry=None)
        self._step(jid, "keys", "doing")
        self.log.info(f"Controle pareado; iniciando teste dos botões: {dev or mac}", cat="Controle", dedup=False)

    def _keys_tick(self):
        with self._lk:
            if self.wiz.get("phase") != "keys" or self.wiz.get("state") != "waiting":
                return
            seen = self.live.seen
            buttons = [r for r in seen if r not in ("ls", "rs")]
            enough = len(buttons) >= KEYS_NEED and "ls" in seen and "rs" in seen
        if enough:
            self._keys_done(manual=False)

    def _keys_done(self, manual):
        with self._lk:
            if self.wiz.get("phase") != "keys":
                raise Refused("O assistente não está na etapa de teste dos botões")
            n = len(self.live.seen)
            for s in self.wiz["steps"]:
                if s["key"] == "keys":
                    s["state"] = "ok"
                    s["note"] = f"{n} botões pressionados" + (" (concluído manualmente)" if manual else "")
            self.wiz.update(state="done", error=None)
            if self.wiz.get("started") is not None:
                self.wiz["elapsed_s"] = self.clock() - self.wiz["started"]
        self.log.info(f"Teste dos botões concluído ({n} pressionados)", cat="Controle")
        return {}

    def _cancel_job(self):
        with self._lk:
            alive = self._job_alive()
            self._cancel.set()
        self._wake.set()
        if not alive and self.wiz.get("state") in ("waiting",):
            with self._lk:
                self._fail(self._job_id, None, "cancelled")
        return {}

    def _forget(self, mac, by=None):
        with self._lk:
            p = self._pad_in_status(mac) or {}
            if p.get("connected") and self._posture() in DRIVING:
                raise Refused("Este controle está conectado e o Microduck está andando. Removê-lo fará o robô parar imediatamente (a versão modificada do padd também o fará sentar). Clique em ‘Parar (ficar em pé)’ antes de remover o pareamento.")
        removed, via = None, None
        try:
            available = bool(self.helper.available())
        except Exception:  # noqa: BLE001
            available = False
        use_helper = self._helper_pad_ok is not False and available
        if not available:
            self._helper_pad_ok = False
        if use_helper:
            try:
                ok, result, detail = self.helper.pad_forget(by or "Studio", mac)
            except Exception as e:  # noqa: BLE001
                raise Refused(f"Falha ao executar o Assistente: {type(e).__name__}: {e}") from None
            detail = detail if isinstance(detail, dict) else {}
            if result == "bad_verb":
                self.log.info("O Assistente é antigo e não reconhece pad-forget; usando configd / bluetoothctl", cat="Controle",
                              raw=detail.get("msg"), hint="Instale a versão nova do Assistente para usar robotctl pad forget oficial")
                self._helper_pad_ok = False
            else:
                self._helper_pad_ok = True
                if not ok:
                    raise Refused(helper_api.friendly(result, detail, "pad-forget")) from None
                removed = detail.get("removed")
                if removed is None:
                    removed = True
                via = "Assistente (robotctl pad forget oficial)"
        if removed is None and self.configd is not None:
            try:
                r = self.configd.call("pad.forget", {"mac": mac}, 5.0)
                removed, via = bool((r or {}).get("removed")), "configd"
            except RpcError as e:
                if e.code != 14:
                    raise Refused(f"O configd não removeu o controle: {e.message}") from None
            except (Unreachable, Timeout):
                pass
        if removed is None and self.bt is not None:
            try:
                removed, via = self.bt.remove(mac), "bluetoothctl"
            except BtError as e:
                err = explain(e.code, e.raw)
                raise Refused(f"{err['msg']}：{err['fix']}") from None
        if removed is None:
            err = explain("permission")
            raise Refused(f"{err['msg']}: {err['fix']} (remover pareamento: sudo robotctl pad forget {mac})")
        self.log.info(f"Pareamento removido do controle {mac}: {'removido' if removed else 'não estava salvo'} (via {via})", cat="Controle", dedup=False,
                      hint="O controle ainda mantém o Microduck salvo; para parear novamente, coloque-o outra vez em modo de pareamento")
        self._poll_status()
        return {"removed": removed}

    # ================= Teste da parada de emergência =================
    #
    # Critérios (revisão 1):
    #   1. Registra no início quantas vezes o controle superior de relaxamento foi acionado (estop.press_count em robotd.py); para aprovar, o contador não pode mudar e não pode haver relaxamento em andamento.
    #   2. Ao pressionar Select, consulta busStatus e registra o horário; a consulta deve ocorrer depois de pressionar e antes de soltar,
    #      e o torque deve estar ligado (para provar que não havia sido relaxado antes, por exemplo pelo controle superior ou pela proteção contra queda).
    #   3. Manter pressionado por 2 segundos reprova o teste: essa ação do padd senta e desliga (robot.shutdown), não é parada de emergência (padd main.rs:192-193, 725-739).
    #   4. Após soltar, consulta busStatus a cada 0,25 s; só aceita torque confirmado como OFF em uma resposta consultada após a soltura (mesmo critério do controle superior: estop.py:43-61).

    def _estop_test(self, action):
        now = self.clock()
        if action == "cancel":
            with self._lk:
                if self.test.get("state") not in FINAL:
                    self.test = {"state": "idle"}
                    self.log.info("Teste de emergência cancelado (o usuário clicou em ‘Cancelar teste’)", cat="Segurança")
            self._test_evt.set()
            return {}
        if action != "start":
            raise Refused("As únicas ações válidas para o teste de emergência são start e cancel")
        if self.robot is None:
            raise Refused("O endereço do programa principal não está configurado neste Microduck")
        with self._lk:
            if self._job_alive():
                raise Refused("Pareamento em andamento; teste depois que terminar")
            if self.test.get("state") not in FINAL:
                raise Refused("O teste já está em andamento")
            checks = self._estop_checks(now, self._status_view(now))
            bad = next((c for c in checks["checks"] if c["ok"] is not True and c["key"] in ("pad", "padd", "robotd")), None)
            if bad or not checks["ok"]:
                c = bad or next(c for c in checks["checks"] if c["ok"] is not True)
                raise Refused(f"Não é possível testar agora: esta condição não passou — {c['label']} ({c['why'] or 'desconhecido'})")
            if self.tap_state != "attached":
                raise Refused("Não é possível ler os botões do controle pelo acesso paralelo do padd; primeiro confirme nesta página que o desenho do controle reage aos botões pressionados")
            token = object()
            self.test = {"state": "need_torque", "started": now, "why": None, "fix": None, "ms": None,
                         "held_long": False, "failed_at": None, "_token": token, "_phase_at": now,
                         "_presses0": self._relax_presses, "_noted0": self._relax_noted, "_pressed_at": None, "_released_at": None,
                         "_on_while_pressed": None, "_press_err": None}
            self._test_evt.clear()
        self.log.info("Iniciando teste de emergência: primeiro confirmaremos que o torque está ligado e depois aguardaremos um toque breve em Select", cat="Segurança", dedup=False,
                      ctx={"presses": self._relax_presses})
        threading.Thread(target=self._estop_runner, args=(token,), name="pad-estop-test", daemon=True).start()
        self._ensure_worker()
        return {}

    def _on_select(self, down, now):
        """Chamado pela thread de acesso paralelo enquanto mantém o bloqueio. Atualiza o estado e desperta a thread de teste; não consulta o robotd aqui."""
        t = self.test
        st = t.get("state")
        if down and st == "armed":
            t.update(state="pressed", _pressed_at=now, _on_while_pressed=None)
            self._test_evt.set()
        elif down and st == "need_torque":
            t["why"] = "Ainda verificando se o torque está ligado; aguarde a etapa 2 acender antes de pressionar Select"
        elif not down and st == "pressed":
            t.update(state="released", _released_at=now)
            self.log.info(f"Select solto após {now - t['_pressed_at']:.2f} s; aguardando confirmação de relaxamento", cat="Segurança")
            self._test_evt.set()

    def _probe_bus(self):
        """Consulta busStatus uma vez e retorna (horário da consulta, resposta ou None, motivo do erro ou None, horário de recebimento)."""
        asked = self.clock()
        try:
            r = self.robot.call("robot.busStatus", {}, 2.0)
        except (Unreachable, Timeout, RpcError) as e:
            return asked, None, str(e), self.clock()
        return asked, (r if isinstance(r, dict) else None), (None if isinstance(r, dict) else "A resposta não é um objeto"), self.clock()

    def _test_fail(self, token, at, why, fix=None):
        with self._lk:
            t = self.test
            if t.get("_token") is not token or t.get("state") in FINAL:
                return
            t.update(state="failed", failed_at=at, why=why, fix=fix)
        self.log.warn(f"Teste de emergência reprovado: {why}", cat="Segurança", step=at, hint=fix)

    def _nap_test(self, s):
        """Aguarda; pressionar/soltar Select ou relaxar o torque desperta a thread. O estado em self.test é a referência; o evento serve apenas para acordá-la."""
        self._test_evt.wait(s)
        self._test_evt.clear()

    def _estop_runner(self, token):
        try:
            self._estop_loop(token)
        except Exception as e:  # noqa: BLE001
            self.log.error("Erro no Studio durante o teste de emergência", cat="Segurança", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="Problema no Studio; exporte o pacote de diagnóstico. Use o controle superior de relaxamento ou Select")
            self._test_fail(token, "studio", f"Erro no Studio: {type(e).__name__}: {e}")

    def _estop_loop(self, token):  # noqa: C901
        w = self.w
        while not self._closing:
            with self._lk:
                t = self.test
                if t.get("_token") is not token or t.get("state") in FINAL:
                    return
                st, now = t["state"], self.clock()
                p0, pressed_at, released_at = t["_presses0"], t["_pressed_at"], t["_released_at"]
                relax_pressed = (self._relax_presses is not None and p0 is not None and self._relax_presses > p0) \
                    or self._relax_noted > t["_noted0"] or bool((self._robot or {}).get("estop_active"))
                if st == "pressed" and now - pressed_at > w["select_long"]:
                    t["held_long"] = True
            if relax_pressed:
                self._test_fail(token, "relax", "O controle superior de relaxamento (ou o de outra página) também foi acionado durante o teste; esta tentativa não conta",
                                "Depois que o relaxamento for confirmado, pressione Start para ficar em pé e clique em ‘Testar novamente’")
                return
            if st == "need_torque":
                if now - t["started"] > w["torque"]:
                    self._test_fail(token, "torque", f"{w['torque']:g} s sem confirmar que o torque ligou", "Pressione Start no controle para o robô ficar em pé e clique em ‘Testar novamente’")
                    return
                asked, bus, err, _ = self._probe_bus()
                if bus is not None and _torque_on(bus):
                    with self._lk:
                        if self.test is t and t["state"] == "need_torque":
                            t.update(state="armed", _phase_at=asked, why=None)
                    continue
                self._nap_test(w["probe"] * 2)
            elif st == "armed":
                if now - t["_phase_at"] > w["press"]:
                    self._test_fail(token, "press", f"{w['press']:g} s sem detectar o pressionamento de Select",
                                    "Você pressionou Select? No Xbox é o botão Exibir, no Switch é − e no PlayStation é Create. O botão correspondente fica vermelho na ilustração quando pressionado.")
                    return
                asked, bus, err, _ = self._probe_bus()
                with self._lk:
                    still = self.test is t and t["state"] == "armed"
                if still and bus is not None and (relaxed(bus) is True or torque_off(bus)):
                    self._test_fail(token, "early_off", "O torque foi desligado antes de pressionar Select; pode ter sido o controle superior, a proteção contra quedas ou outro programa",
                                    "Pressione Start para o robô ficar em pé e clique em ‘Testar novamente’")
                    return
                self._nap_test(w["probe"] * 2)
            elif st == "pressed":
                if t["_on_while_pressed"] is None and t["_press_err"] is None:
                    asked, bus, err, _ = self._probe_bus()
                    with self._lk:
                        rel = t["_released_at"]
                        if asked >= pressed_at and (rel is None or asked <= rel):
                            if bus is None:
                                t["_press_err"] = err or "sem resposta"
                            else:
                                t["_on_while_pressed"] = _torque_on(bus)
                    continue
                if now - pressed_at >= w["shutdown_hold"]:
                    self._test_fail(token, "long", f"Select foi mantido pressionado por {w['shutdown_hold']:g} s: o padd envia o comando de sentar, relaxar e desligar (robot.shutdown),"
                                    "que não é parada de emergência. Esta tentativa não conta", "O Microduck pode estar sentando e desligando: aguarde parar (se desligar, ligue novamente) e repita o teste, soltando Select logo após pressioná-lo")
                    return
                self._nap_test(0.05)
            elif st == "released":
                held = released_at - pressed_at
                if held >= w["shutdown_hold"]:
                    self._test_fail(token, "long", f"Select foi pressionado por {held:.1f} s (a partir de {w['shutdown_hold']:g} s, o comando senta e desliga; não é parada de emergência): esta tentativa não conta",
                                    "Teste novamente: pressione e solte rapidamente")
                    return
                if t["_on_while_pressed"] is not True:
                    if t["_on_while_pressed"] is False:
                        self._test_fail(token, "pressed_off", "O torque já estava desligado enquanto Select estava pressionado; soltar Select não acionou o relaxamento. Esta tentativa não conta",
                                        "Pressione Start para o robô ficar em pé e clique em ‘Testar novamente’")
                    else:
                        self._test_fail(token, "pressed_unknown",
                                        f"Não foi possível ler o torque enquanto Select estava pressionado ({t['_press_err'] or 'o botão foi solto antes da consulta'} ); esta tentativa não conta",
                                        "Teste novamente: mantenha pressionado por cerca de meio segundo (no máximo 1,5 s)")
                    return
                if now - released_at > w["readback"]:
                    self._test_fail(token, "readback", f"O torque ainda não foi confirmado desligado {w['readback']:g} s após soltar Select",
                                    "O padd talvez não tenha encaminhado o relaxamento ao programa principal (consulte as linhas do padd no log). Use o controle superior de relaxamento ou desligue a alimentação.")
                    return
                asked, bus, err, got = self._probe_bus()
                if bus is not None and asked >= released_at and relaxed(bus) is True:
                    with self._lk:
                        if self.test is not t or t["state"] != "released":
                            return
                        relax_pressed = (self._relax_presses is not None and p0 is not None and self._relax_presses > p0) \
                            or self._relax_noted > t["_noted0"]
                        if not relax_pressed:
                            t.update(state="passed", ms=int((got - released_at) * 1000), why=None)
                    if relax_pressed:
                        continue
                    self.log.info(f"Teste de emergência aprovado: tempo entre soltar Select e confirmar o relaxamento {t['ms']} ms", cat="Segurança", dedup=False,
                                  ctx={"held_s": round(held, 2), "asked_after_release_ms": int((asked - released_at) * 1000)})
                    self._estop_passed_record()            # Etapa 4 do roteiro inicial (revisão O6: registra no momento da aprovação)
                    return
                self._nap_test(w["probe"])
            else:
                return


def robot_view(rd, posture=None):
    """Obtém os dados de retorno do robotd no loop de eventos e os entrega a PadOps (não lê objetos mutáveis de outra thread). rd é studio.robotd.Robotd.
    A postura é calculada por state.posture com a mesma tabela; dados antigos de policies / state / health são descartados (MAX_AGE em state.py)."""
    now = time.monotonic()

    def fresh(sample, key):
        age = sample.age(now)
        return sample.value if age is not None and age <= MAX_AGE[key] else None

    pol, st, health = fresh(rd.policies, "policies"), fresh(rd.state, "state"), fresh(rd.health, "health")
    if posture is None:
        posture = _posture(rd.present, rd.bus.value, pol, st)
    applied = ((st or {}).get("move") or {}).get("applied") if isinstance(st, dict) else None
    batt = ((health or {}).get("battery") or {}).get("percent") if isinstance(health, dict) else None
    return {"present": rd.present, "bus": rd.bus.value, "bus_at": rd.bus.at, "posture": posture,
            "state": st if isinstance(st, dict) else None, "state_at": rd.state.at,
            "policies_at": rd.policies.at,
            "policies": pol if isinstance(pol, dict) else None, "applied": applied, "battery_pct": batt,
            "estop_active": rd.estop.active, "estop_presses": rd.estop.press_count, "paused": rd.paused,
            "pad_status": rd.pad.value, "pad_status_at": rd.pad.at, "pad_status_error": rd.pad.error}


def _mask_mac(mac):
    """Mascara AA:BB:CC:DD:EE:FF como AA:BB:CC:… para não incluir o endereço completo no pacote de diagnóstico."""
    m = str(mac or "")
    return (m[:8] + ":…") if len(m) >= 8 else m


def _mask_name(name):
    n = str(name or "")
    return (n[: max(1, len(n) // 2)] + "…") if len(n) > 2 else n


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------- Portas reais: JSON-RPC síncrono (um objeto por linha; lib.rs:9-12) ----------------

def _connect(addr, timeout):
    kind, *rest = parse_addr(addr)
    try:
        if kind == "unix":
            if not hasattr(socket, "AF_UNIX"):
                raise Unreachable("O Python deste computador não oferece suporte a sockets Unix; use um endereço tcp:")
            path = rest[0]
            if not os.path.exists(path):
                raise Unreachable(f"{path} não existe")
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout)
                s.connect(path)
            except BaseException:
                s.close()
                raise
            return s
        host, port = rest
        return socket.create_connection((host, port), timeout)
    except Unreachable:
        raise
    except PermissionError as e:
        raise NoPermission(f"Sem permissão para conectar a {addr} ({ROBOT_GROUP})") from e
    except (ConnectionRefusedError, FileNotFoundError) as e:
        raise Unreachable(f"Não foi possível conectar a {addr}: conexão recusada") from e
    except socket.timeout:
        raise Timeout(f"Não foi possível conectar a {addr} em {timeout:g} s") from None
    except OSError as e:
        raise Unreachable(f"Não foi possível conectar a {addr}: {type(e).__name__}: {e}") from e


class _Lines:
    def __init__(self, sock):
        self.s, self.buf = sock, b""

    def readline(self, deadline):
        """Lê uma linha (bytes); retorna None se o outro lado fechar a conexão e lança socket.timeout ao expirar o prazo."""
        while b"\n" not in self.buf:
            left = deadline - time.monotonic()
            if left <= 0:
                raise socket.timeout()
            self.s.settimeout(left)
            chunk = self.s.recv(65536)
            if not chunk:
                return None
            self.buf += chunk
            if len(self.buf) > LINE_LIMIT:
                raise Unreachable(f"A linha enviada pelo outro lado é longa demais (mais de {LINE_LIMIT} bytes)")
        line, _, self.buf = self.buf.partition(b"\n")
        return line


def rpc_call(addr, method, params=None, timeout=3.0):
    """Abre uma conexão, faz uma consulta e fecha (o pareamento ocupa a conexão por um ou dois minutos e não pode bloquear outras solicitações)."""
    deadline = time.monotonic() + timeout
    s = _connect(addr, timeout)
    try:
        req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        rd = _Lines(s)
        while True:
            line = rd.readline(deadline)
            if line is None:
                raise Unreachable("O outro lado encerrou a conexão")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("id") != 1:
                continue
            if "error" in msg:
                err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                raise RpcError(method, err.get("code"), err.get("message", ""), err.get("data"))
            return msg.get("result")
    except socket.timeout:
        raise Timeout(f"{method} não respondeu em {timeout:g} s") from None
    except (Unreachable, RpcError):
        raise
    except OSError as e:
        raise Unreachable(f"A conexão foi interrompida: {type(e).__name__}: {e}") from e
    finally:
        s.close()


class ConfigdPort:
    def __init__(self, addr="unix:/run/configd.sock"):
        self.addr = addr

    def call(self, method, params=None, timeout=3.0):
        return rpc_call(self.addr, method, params, timeout)


class RobotPort:
    """robot.move / head / mouth são notificações (sem id e sem resposta; lib.rs:522-529), enviadas por uma conexão persistente que tenta reconectar uma vez se cair.
    As chamadas que exigem resposta (init, enable, do, sound, busStatus etc.) abrem uma nova conexão a cada solicitação (rpc_call)."""

    def __init__(self, addr="unix:/run/robotd.sock"):
        self.addr = addr
        self._s = None
        self._lk = threading.Lock()

    def call(self, method, params=None, timeout=3.0):
        return rpc_call(self.addr, method, params, timeout)

    def notify(self, method, params):
        line = (json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, separators=(",", ":")) + "\n").encode()
        with self._lk:
            for attempt in (1, 2):
                try:
                    if self._s is None:
                        self._s = _connect(self.addr, 1.0)
                    self._s.settimeout(1.0)
                    self._s.sendall(line)
                    return
                except (OSError, Unreachable, Timeout) as e:
                    self._close()
                    if attempt == 2:
                        raise e if isinstance(e, (Unreachable, Timeout)) else Unreachable(f"{type(e).__name__}: {e}")

    def _close(self):
        if self._s is not None:
            try:
                self._s.close()
            except OSError:
                pass
        self._s = None


class PaddTap:
    """Acesso paralelo do padd: envia pad.input uma vez e passa a ler pad.report (tap.rs:536-599). Reconecta após 2 segundos se cair (como robotctl monitor).
    Se ocorrer um erro inesperado no callback ou na análise, registra no log e reconecta; a thread não pode encerrar silenciosamente (revisão 15)."""

    def __init__(self, addr="unix:/run/padd/pad.sock", reconnect_s=2.0, log=None):
        self.addr, self.reconnect_s, self.log = addr, reconnect_s, log
        self._stop = threading.Event()
        self._t = None
        self._s = None

    def start(self, on_report, on_state):
        self.stop()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, args=(on_report, on_state, self._stop), name="pad-tap", daemon=True)
        self._t.start()

    def alive(self):
        return self._t is not None and self._t.is_alive() and not self._stop.is_set()

    def stop(self):
        self._stop.set()
        s = self._s
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _loop(self, on_report, on_state, stop):
        while not stop.is_set():
            try:
                self._once(on_report, on_state, stop)
            except Exception as e:  # noqa: BLE001
                if self.log:
                    self.log.error("Erro na thread de leitura dos botões do controle; reconectando em 2 s", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                                   hint="Problema no Studio; exporte o pacote de diagnóstico")
                try:
                    on_state("error", f"Erro no Studio: {type(e).__name__}: {e}")
                except Exception:  # noqa: BLE001
                    pass
            stop.wait(self.reconnect_s)

    def _once(self, on_report, on_state, stop):
        try:
            s = _connect(self.addr, 2.0)
        except NoPermission as e:
            on_state("denied", str(e))
            return
        except Unreachable:
            on_state("absent", "Não foi possível conectar ao acesso paralelo dos botões do padd (/run/padd/pad.sock): o padd pode não estar em execução ou esta versão pode não oferecer o acesso paralelo. A página não exibirá os botões em tempo real, mas o controle continuará funcionando normalmente.")
            return
        except Timeout as e:
            on_state("error", str(e))
            return
        self._s = s
        try:
            s.sendall(b'{"jsonrpc":"2.0","id":1,"method":"pad.input","params":{}}\n')
            on_state("waiting", None)
            rd = _Lines(s)
            while not stop.is_set():
                try:
                    line = rd.readline(time.monotonic() + 1.0)
                except socket.timeout:
                    continue
                if line is None:
                    on_report({"report": "detached", "why": "O padd encerrou o acesso paralelo"})
                    break
                # IMU integrado ao controle (como no G50 Pro): enquanto houver assinantes, o padd envia todos os lotes de dados do IMU (fork padd tap.rs:506-528);
                # eles não são necessários aqui. Ignora a linha pela string antes de analisar (tag interna do serde "report":"imu", lib.rs:4609-4635; imu_attached não é afetado):
                # analisar e descartar dezenas de linhas por segundo desperdiçaria CPU (revisão O12 da reorganização do resumo)
                if b'"report":"imu"' in line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("id") == 1 and "error" in msg:
                    err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                    on_state("error", f"O padd recusou a assinatura: {err.get('message')}")
                    break
                if msg.get("method") == "pad.report" and isinstance(msg.get("params"), dict):
                    on_report(msg["params"])
        except (OSError, Unreachable) as e:
            if not stop.is_set():
                on_state("error", f"Acesso paralelo interrompido: {e}")
        finally:
            self._s = None
            try:
                s.close()
            except OSError:
                pass


# ---------------- Bluetooth real: bluetoothctl ----------------

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x01\x02]")
_PROMPT = re.compile(r"^(?:\[[^\]\[]*\][#>]\s*)+")
_EVENT = re.compile(r"^\[(NEW|CHG|DEL)\]\s+Device\s+([0-9A-Fa-f:]{17})\s*(.*)$")
_PROP = re.compile(r"^\s*([A-Za-z][A-Za-z ]*?):\s*(.*)$")
_ASK_YES = re.compile(r"\(yes/no\)")
_ASK_KINDS = ("Accept pairing", "Authorize service", "Request authorization")
_ASK_PIN = re.compile(r"Enter PIN code|Enter passkey|Confirm passkey", re.I)
BT_FAIL = r"Failed|not available|No default controller|Invalid command|org\.bluez\.Error\.(?!AlreadyExists|AlreadyConnected)|Enter PIN code|Enter passkey|Confirm passkey"
BT_ENV = {**os.environ, "LC_ALL": "C", "TERM": "dumb"}


def clean_line(raw):
    """Remove cores, retornos de carro e prompts (no pipe, o bluetoothctl também pode juntar o prompt à saída na mesma linha)."""
    line = _ANSI.sub("", raw or "").replace("\r", "").strip()
    return _PROMPT.sub("", line).strip()


def _yes(v):
    return None if v is None else str(v).strip().lower().startswith("yes")


def _num(v):
    if v is None:
        return None
    m = re.search(r"\((-?\d+)\)", str(v)) or re.search(r"(-?0x[0-9a-fA-F]+|-?\d+)", str(v))
    if not m:
        return None
    s = m.group(1)
    try:
        n = int(s, 16) if "0x" in s.lower() else int(s)
    except ValueError:
        return None
    return n


def parse_props(text):
    """Converte as linhas “chave: valor” de `bluetoothctl info / show` em um dict (chaves em minúsculas). UUIDs são reunidos em uma lista."""
    out = {"uuids": []}
    for raw in (text or "").splitlines():
        line = clean_line(raw)
        m = _PROP.match(line)
        if not m:
            continue
        k, v = m.group(1).strip().lower(), m.group(2).strip()
        if k == "uuid":
            out["uuids"].append(v)
        elif k not in out:
            out[k] = v
    return out


def device_from_props(mac, p):
    rssi = _num(p.get("rssi"))
    if isinstance(rssi, int) and rssi > 0x7FFFFFFF:
        rssi -= 1 << 32
    return {"mac": mac.upper(), "name": p.get("name"), "alias": p.get("alias"), "icon": p.get("icon"),
            "cls": _num(p.get("class")), "appearance": _num(p.get("appearance")), "rssi": rssi,
            "paired": _yes(p.get("paired")), "trusted": _yes(p.get("trusted")), "connected": _yes(p.get("connected"))}


def _rfkill_blocked(base):
    """True: Bluetooth bloqueado por rfkill; False: rfkill para Bluetooth existe, mas não está bloqueado; None: não encontrado."""
    try:
        names = os.listdir(base)
    except OSError:
        return None
    found = None
    for n in names:
        try:
            if _read_text(os.path.join(base, n, "type")).strip() != "bluetooth":
                continue
            soft = _read_text(os.path.join(base, n, "soft")).strip()
            hard = _read_text(os.path.join(base, n, "hard")).strip()
        except OSError:
            continue
        found = bool(found) or soft == "1" or hard == "1"
    return found


def _run(argv, timeout=8.0):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           env=BT_ENV, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return 127, f"Comando não encontrado: {argv[0]}"
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        return 124, f"{' '.join(argv)} {timeout:g} s sem terminar: {out[-300:]}"


def _spawn(argv):
    # Pipe binário e sem buffer: lê blocos e separa as linhas manualmente (as perguntas do agente são prompts sem quebra de linha; leitura por linha travaria: revisão 4)
    return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            bufsize=0, env=BT_ENV)


class BtSession:
    """Uma sessão persistente do bluetoothctl: busca, pareamento, confiança e conexão ocorrem no mesmo cliente (como na ferramenta original da placa;
    em 10-15, comandos separados são recusados, conforme arquivo de registro de problemas, linha 272).

    Agente (revisão 5): ao iniciar, o bluetoothctl pode registrar automaticamente um agente padrão; por isso, começa a sessão com agent off. A busca não precisa de agente;
    registra NoInputNoOutput, ocupa o agente padrão e responde yes automaticamente apenas durante pair_device; ao terminar, executa agent off e libera o agente (configd também o ocupa apenas durante o pareamento:
    configd bluez.rs:995-1013）。"""

    def __init__(self, argv, spawn=None):
        self.p = (spawn or _spawn)(argv)
        self.cv = threading.Condition()
        self.lines = deque(maxlen=4000)
        self.seq = 0
        self.devices = {}
        self.closed = False
        self.discovering = False     # ao iniciar, bluetoothctl emite [NEW] para os dispositivos em cache; eles não contam como “vistos” antes do começo da busca
        self.answer_yes = False      # responde yes automaticamente apenas durante o pareamento
        self.asked = []              # perguntas feitas pelo agente e respostas enviadas (registradas no log em caso de erro)
        self._tail_answered = False
        self._quit = False
        self._t = threading.Thread(target=self._reader, name="bt-session", daemon=True)
        self._t.start()

    def _chunks(self):
        out = self.p.stdout
        try:
            fd = out.fileno()
        except (AttributeError, OSError, ValueError):
            fd = None
        if fd is not None:
            dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
            while True:
                try:
                    b = os.read(fd, 4096)
                except OSError:
                    return
                if not b:
                    tail = dec.decode(b"", final=True)
                    if tail:
                        yield tail
                    return
                yield dec.decode(b)
        else:
            for x in out:                         # processo simulado nos testes: blocos de texto (não necessariamente linhas completas)
                yield x.decode("utf-8", "replace") if isinstance(x, bytes) else x

    def _reader(self):
        buf = ""
        try:
            for chunk in self._chunks():
                buf += chunk
                parts = buf.split("\n")
                buf = parts.pop()
                with self.cv:
                    for raw in parts:
                        line = clean_line(raw)
                        answered, self._tail_answered = self._tail_answered, False
                        if line:
                            self._add(line, prompt_done=answered)
                    tail = clean_line(buf)
                    if tail and not self._tail_answered and (_ASK_YES.search(tail) or _ASK_PIN.search(tail)):
                        # O prompt não termina com quebra de linha; não espere o fim da linha, responda imediatamente (revisão 4)
                        self._tail_answered = True
                        self._add(tail, prompt_done=False)
                    self.cv.notify_all()
                if len(buf) > 65536:
                    buf = buf[-4096:]
        except (OSError, ValueError):
            pass
        with self.cv:
            self.closed = True
            self.cv.notify_all()

    def _add(self, line, prompt_done):
        self.seq += 1
        self.lines.append((self.seq, line))
        if not prompt_done:
            self._event(line)

    def _event(self, line):
        if re.search(r"Discovery started|Controller .*Discovering: yes", line):
            self.discovering = True
        elif re.search(r"Discovery stopped|Controller .*Discovering: no", line):
            self.discovering = False
        m = _EVENT.match(line)
        if m:
            what, mac, rest = m.group(1), m.group(2).upper(), m.group(3)
            if what == "DEL":
                self.devices.pop(mac, None)
                return
            d = self.devices.setdefault(mac, {"mac": mac})
            pm = _PROP.match(rest)
            if self.discovering or (pm and pm.group(1).strip().lower() == "rssi"):
                d["seen_at"] = time.monotonic()
            if what == "CHG" and pm:
                k, v = pm.group(1).strip().lower(), pm.group(2).strip()
                if k == "rssi":
                    n = _num(v)
                    d["rssi"] = n - (1 << 32) if isinstance(n, int) and n > 0x7FFFFFFF else n
                elif k == "class":
                    d["cls"] = _num(v)
                elif k == "appearance":
                    d["appearance"] = _num(v)
                elif k in ("paired", "trusted", "connected", "bonded"):
                    d[k] = _yes(v)
                elif k in ("name", "alias", "icon"):
                    d[k] = v
            elif what == "NEW" and rest and not re.match(r"^[0-9A-Fa-f]{2}[-:]", rest):
                d.setdefault("name", rest)
            return
        # Perguntas do agente: aceita pareamento e autoriza serviços apenas durante a janela; fora dela responde no. Solicitação de PIN é tratada como falha (pin) por expect
        if _ASK_YES.search(line) and any(k in line for k in _ASK_KINDS):
            ans = "yes" if self.answer_yes else "no"
            self.asked.append(f"{line} → {ans}")
            try:
                self.send(ans)
            except BtError:
                pass
        elif _ASK_YES.search(line) and _ASK_PIN.search(line):
            self.asked.append(f"{line} → no")
            try:
                self.send("no")
            except BtError:
                pass

    def send(self, cmd):
        try:
            self.p.stdin.write((cmd + "\n").encode("utf-8"))
            self.p.stdin.flush()
        except (OSError, ValueError, AttributeError) as e:
            raise BtError("bluez_down", f"bluetoothctl já foi encerrado: {e}") from None

    def expect(self, ok, fail=BT_FAIL, timeout=8.0, since=None, cancel=None):
        since = self.seq if since is None else since
        end = time.monotonic() + timeout
        ok_re, fail_re = re.compile(ok, re.I), re.compile(fail, re.I) if fail else None
        with self.cv:
            while True:
                for n, line in list(self.lines):
                    if n <= since:
                        continue
                    since = n
                    if ok_re.search(line):
                        return line
                    if fail_re and fail_re.search(line):
                        raise BtError(classify(line), line)
                if self.closed:
                    raise BtError("bluez_down", "bluetoothctl foi encerrado")
                if cancel is not None and cancel.is_set():
                    raise BtError("cancelled", "O usuário clicou em parar")
                left = end - time.monotonic()
                if left <= 0:
                    raise BtError("timeout", f"{timeout:g} s sem aguardar: {ok}")
                self.cv.wait(min(left, 0.2))

    def cmd(self, text, ok, fail=BT_FAIL, timeout=8.0, cancel=None):
        since = self.seq
        self.send(text)
        return self.expect(ok, fail, timeout, since, cancel)

    def _wait(self, t):
        try:
            self.p.wait(t)
            return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:  # noqa: BLE001
            return True

    def close(self):
        """quit → fecha stdin → aguarda 2 s → terminate (sudo encaminha SIGTERM ao bluetoothctl, mas não SIGKILL: revisão 6) → aguarda 1 s → kill → aguarda."""
        if self._quit:
            return
        self._quit = True
        try:
            self.send("quit")
        except BtError:
            pass
        try:
            self.p.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        if self._wait(2.0):
            return
        for fn in ("terminate", "kill"):
            try:
                getattr(self.p, fn)()
            except Exception:  # noqa: BLE001
                pass
            if self._wait(1.0):
                return


class BluetoothCtl:
    """Implementação real de BluetoothPort: bluetoothctl (incluído no BlueZ) e /sys/class/rfkill. prefix pode ser ("sudo", "-n"):
    nesse caso, a sessão executa sudo -n stdbuf -oL bluetoothctl (stdbuf vem depois de sudo; antes dele, não funciona com sudo setuid: revisão 6)."""

    def __init__(self, run=_run, spawn=None, prefix=(), rfkill_dir="/sys/class/rfkill", exe="bluetoothctl", stdbuf=None):
        self.run, self.spawn, self.prefix, self.rfkill_dir, self.exe = run, spawn, tuple(prefix), rfkill_dir, exe
        self.stdbuf = bool(shutil.which("stdbuf")) if stdbuf is None else stdbuf
        self.t = {"pair": 30.0, "connect": 20.0, "trust": 8.0, "find": 15.0, "settle": 8.0}    # Tempo máximo por etapa (reduzido nos testes)
        self._session = None
        self._lk = threading.Lock()

    def _argv(self, *a):
        return [*self.prefix, self.exe, *a]

    def _session_argv(self):
        return [*self.prefix, *(("stdbuf", "-oL") if self.stdbuf else ()), self.exe]

    def adapter(self):
        blocked = _rfkill_blocked(self.rfkill_dir)
        rc, out = self.run(self._argv("show"), 6.0)
        text = "\n".join(clean_line(x) for x in out.splitlines())
        if rc == 127:
            return {"present": False, "error": None, "blocked": blocked, "raw": text, "missing": True}
        if re.search(r"AccessDenied|Access denied", text):
            return {"present": None, "error": text, "code": "bt_permission", "blocked": blocked, "raw": text}
        # Se bluetoothd não estiver em execução, bluetoothctl exibirá “Waiting to connect to bluetoothd...” até expirar (revisão 17: isso não significa falta de adaptador)
        if re.search(r"Waiting to connect to bluetoothd|org\.bluez was not provided|ServiceUnknown", text):
            return {"present": None, "error": text[-400:], "code": "bluez_down", "blocked": blocked, "raw": text[-400:]}
        if "No default controller" in text or "Controller" not in text:
            return {"present": False, "blocked": blocked, "raw": text[-400:]}
        p = parse_props(text)
        return {"present": True, "powered": _yes(p.get("powered")), "pairable": _yes(p.get("pairable")),
                "discovering": _yes(p.get("discovering")), "blocked": blocked, "raw": text[-400:]}

    def _simple(self, ok, *a, timeout=8.0):
        rc, out = self.run(self._argv(*a), timeout)
        text = clean_line(out.replace("\n", " "))
        if re.search(ok, out, re.I):
            return out
        raise BtError(classify(out) if rc != 124 else "timeout", text[-400:])

    def power_on(self):
        return self._simple(r"Changing power on succeeded|Powered: yes", "power", "on")

    def pairable_on(self):
        return self._simple(r"Changing pairable on succeeded|Pairable: yes", "pairable", "on")

    def pairable_off(self):
        return self._simple(r"Changing pairable off succeeded|Pairable: no", "pairable", "off")

    def info(self, mac):
        rc, out = self.run(self._argv("info", mac), 5.0)
        if rc != 0 or "not available" in out:
            return {}
        return device_from_props(mac, parse_props(out))

    def reconnect(self, mac, timeout=5.0):
        """Restabelece apenas a conexão com o dispositivo pareado escolhido; não registra agente, não busca dispositivos e não remove pareamentos."""
        if not isinstance(mac, str) or not MAC_RE.fullmatch(mac):
            raise BtError("other", "Endereço do controle inválido")
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise BtError("timeout", "Não há tempo restante para reconectar")
        return self._simple(rf"Connection successful|AlreadyConnected|Device {re.escape(mac)} Connected: yes",
                            "connect", mac, timeout=min(timeout, self.t["connect"]))

    def _open(self):
        with self._lk:
            if self._session is None or self._session.closed:
                s = BtSession(self._session_argv(), self.spawn)
                self._session = s
                try:
                    # Pode haver um agente padrão registrado ao iniciar; remova-o (a busca não precisa de agente)
                    s.cmd("agent off", r"Agent unregistered|No agent is registered|Agent is not registered|not registered",
                          fail=None, timeout=2.0)
                except BtError:
                    pass
            return self._session

    def scan_start(self):
        s = self._open()
        try:
            s.cmd("scan on", r"Discovery started|Discovering: yes", timeout=8.0)
        except BtError:
            self.close()          # Se a sessão não iniciar, encerre-a para que a próxima tentativa abra uma nova (revisão 6)
            raise

    def scan_stop(self):
        s = self._session
        if s is not None and not s.closed:
            try:
                s.cmd("scan off", r"Discovery stopped|Discovering: no", fail=None, timeout=5.0)
            except BtError:
                pass

    def devices(self):
        """Dispositivos vistos na sessão; consulta info uma vez na primeira aparição para obter nome, categoria e outros dados."""
        s = self._session
        if s is None:
            return []
        with s.cv:
            snap = {k: dict(v) for k, v in s.devices.items()}
        out = []
        for mac, d in snap.items():
            if "_info" not in s.devices.get(mac, {}):
                info = self.info(mac)
                with s.cv:
                    if mac in s.devices:
                        s.devices[mac]["_info"] = info
            info = s.devices.get(mac, {}).get("_info") or {}
            merged = {**info, **{k: v for k, v in d.items() if v is not None and not k.startswith("_")}}
            out.append(merged)
        return out

    def pair_device(self, mac, classic, cancel, step):
        """Conclui o fluxo em uma sessão. Bluetooth clássico (tipo Switch Pro): pair → trust → connect (ordem que funcionou no G50 com 10-15);
        LE (Xbox): primeiro connect (pode criar o vínculo sozinho; aguarda até 5 s) → se não vincular, pair → trust → connect novamente (bluez.rs:713-795).
        Os sinais de sucesso são associados a este MAC (revisão 11): Paired / Connected de outro dispositivo não contam."""
        s = self._open()
        m = re.escape(mac)
        try:
            try:
                try:
                    s.cmd("agent NoInputNoOutput", r"Agent registered", fail=BT_FAIL + r"|already registered", timeout=5.0)
                except BtError as e:
                    # bluetoothctl 5.82 registra o agente padrão somente depois de conectar ao bluetoothd; agent off no início da sessão é cedo demais (retorna “No agent is
                    # registered”, e o agente padrão só é registrado em seguida), causando “Agent is already registered” (Microduck nº 2, 10-19). Remove-o e registra novamente
                    if "already registered" not in (e.raw or ""):
                        raise
                    s.cmd("agent off", r"Agent unregistered", timeout=3.0)
                    s.cmd("agent NoInputNoOutput", r"Agent registered", fail=BT_FAIL + r"|already registered", timeout=5.0)
                s.cmd("default-agent", r"Default agent request successful", timeout=5.0)
            except BtError as e:
                raise BtError("agent" if e.code in ("other", "timeout") else e.code, e.raw) from None
            s.answer_yes = True
            if mac not in s.devices:
                s.cmd("scan on", r"Discovery started|Discovering: yes", timeout=8.0)
                try:
                    s.expect(rf"Device {m}", fail=None, timeout=self.t["find"], since=0, cancel=cancel)
                except BtError as e:
                    if e.code == "timeout":
                        raise BtError("not_found", f"Não encontrou {mac} após buscar por {self.t['find']:g} s; o controle saiu do modo de pareamento?") from None
                    raise
            try:
                s.cmd("scan off", r"Discovery stopped|Discovering: no", fail=None, timeout=5.0)
            except BtError:
                pass
            ok_pair = rf"Pairing successful|AlreadyExists|Device {m} (Paired|Bonded): yes"
            if not classic:
                step("connect", "doing", "Controles como Xbox tentam conectar primeiro e podem parear automaticamente")
                try:
                    s.cmd(f"connect {mac}", rf"Connection successful|AlreadyConnected|Device {m} Connected: yes",
                          timeout=self.t["connect"], cancel=cancel)
                except BtError as e:
                    if e.code == "cancelled":
                        raise
                try:
                    s.expect(rf"Device {m} (Paired|Bonded): yes", fail=None, timeout=5.0, since=0, cancel=cancel)
                    step("pair", "ok")
                except BtError as e:
                    if e.code == "cancelled":
                        raise
            if not (s.devices.get(mac, {}).get("paired")):
                step("pair", "doing")
                s.cmd(f"pair {mac}", ok_pair, timeout=self.t["pair"], cancel=cancel)
            step("pair", "ok")
            step("trust", "doing")
            s.cmd(f"trust {mac}", rf"{m} trust succeeded|Device {m} Trusted: yes", timeout=self.t["trust"], cancel=cancel)
            step("trust", "ok")
            step("connect", "doing")
            ok_conn = rf"Connection successful|AlreadyConnected|Device {m} Connected: yes"
            mark = s.seq
            try:
                s.cmd(f"connect {mac}", ok_conn, timeout=self.t["connect"], cancel=cancel)
            except BtError as e:
                # Logo após o pareamento, controles Bluetooth clássicos também iniciam a conexão com o Microduck: BlueZ retorna InProgress (br-connection-busy, Microduck nº 2, 10-19, G50 Pro).
                # Aguarda a conexão automática; se não ocorrer, tenta conectar novamente
                if e.code != "busy":
                    raise
                step("connect", "doing", "O controle está tentando se conectar; aguardando")
                try:
                    s.expect(rf"Device {m} Connected: yes", fail=None, timeout=self.t["settle"], since=mark, cancel=cancel)
                except BtError as e2:
                    if e2.code != "timeout":
                        raise
                    s.cmd(f"connect {mac}", ok_conn, timeout=self.t["connect"], cancel=cancel)
            step("connect", "ok")
        finally:
            s.answer_yes = False
            try:
                s.cmd("agent off", r"Agent unregistered|No agent is registered|not registered", fail=None, timeout=3.0)
            except BtError:
                pass

    def remove(self, mac):
        rc, out = self.run(self._argv("remove", mac), 8.0)
        if "Device has been removed" in out:
            return True
        if "not available" in out:
            return False
        raise BtError(classify(out), clean_line(out.replace("\n", " "))[-400:])

    def close(self):
        with self._lk:
            s, self._session = self._session, None
        if s is not None:
            s.close()


def default_pad(log, configd_addr="unix:/run/configd.sock", robotd_addr="unix:/run/robotd.sock",
                tap_addr="unix:/run/padd/pad.sock", bt_prefix=(), state_dir=None):
    """Conexão padrão no Microduck (usada por app.py / __main__.py). Computadores sem bluetoothctl não recebem uma porta Bluetooth."""
    bt = BluetoothCtl(prefix=bt_prefix) if shutil.which("bluetoothctl") else None
    from .audio_interaction import AudioClient
    return PadOps(log, configd=ConfigdPort(configd_addr), bt=bt, tap=PaddTap(tap_addr, log=log),
                  robot=RobotPort(robotd_addr), state_dir=state_dir, audio=AudioClient())
