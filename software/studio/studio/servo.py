"""Sessão do barramento da página dos servos: o Studio abre o barramento (como servo-web), lê os 15 servos e desativa o torque pelo barramento.

Esta etapa (página dos servos 4a) é **somente leitura**: exceto por desligar o torque, não grava nada nos servos. A retenção e a calibração central são adicionadas nas etapas seguintes.

Por que o Studio abre o barramento: nenhuma das duas versões do robotd consegue “habilitar e manter o torque de um único servo” (a oficial grava os 15 de uma vez;
o firmware original da placa desliga o torque assim que move chega ao destino), conforme scratchpad console/servo-page-plan.md. Assim, como servo-web, a página dos servos
usa o Studio para se comunicar diretamente com os servos enquanto o robotd está parado. **Este é o único ponto de entrada para o barramento: ServoSession.open().**

Threads: as operações do barramento Feetech são bloqueantes (pyserial); a consulta roda em uma thread (50 Hz) e os resultados ficam no snapshot,
que a interface consulta a 10 Hz. O desligamento de torque não entra na fila: é enviado diretamente pela thread chamadora (cada pacote do barramento usa um lock e se intercala com as consultas),
e aguarda no máximo o pacote que já está sendo recebido (alguns milissegundos).

Desligar o torque = parada de emergência com trava (plano 1.3, revisão S4): envia sync_write 40=0 → lê de volta com sync_read 40 → regrava individualmente os servos que não retornaram 0,
por no máximo três rodadas. Após travar, qualquer habilitação de torque, gravação de alvo ou offset verifica latched; somente uma ação explícita “Destravar” libera.

Devolução/saída (revisões de código D2 e D3, lote 3): as operações dos servos (servo_ops.handle) rodam em threads, e uma devolução pode concorrer com uma retenção recém-solicitada —
no mesmo lote, “reter” pode chegar antes de “sair”; em 35 de 40 casos, os servos continuavam com torque após a devolução. Por isso:
- - cada operação registra início/fim (op_begin/op_end; app registra no event loop, antes mesmo de a thread começar);
- - devolução/saída define closing primeiro (rejeita novas operações e não permite que habilitar torque manualmente limpe a trava de desligamento); espera as operações em andamento terminarem (com timeout; se expirar, não devolve),
  - lê o torque naquele instante (sem usar o cache de 1 s), desliga-o e fecha o barramento;
- - saída (leave): não devolve durante calibração, movimento ou animação; só devolve se conseguir ler naquele instante o torque dos 15 servos e todos forem 0. Considere servos sem leitura como ainda retidos.
"""
import contextlib
import json
import os
import subprocess
import sys
import threading
import time

from .bus import feetech

IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]     # na mesma ordem de JOINT_NAMES do robotd
NAMES = {
    20: ("Guinada do quadril esquerdo", "Left Hip Yaw"), 21: ("Rolagem do quadril esquerdo", "Left Hip Roll"), 22: ("Inclinação do quadril esquerdo", "Left Hip Pitch"),
    23: ("Joelho esquerdo", "Left Knee"), 24: ("Tornozelo esquerdo", "Left Ankle"),
    30: ("Inclinação do pescoço", "Neck Pitch"), 31: ("Inclinação da cabeça", "Head Pitch"), 32: ("Guinada da cabeça", "Head Yaw"),
    33: ("Rolagem da cabeça", "Head Roll"), 34: ("Boca", "Mouth"),
    10: ("Guinada do quadril direito", "Right Hip Yaw"), 11: ("Rolagem do quadril direito", "Right Hip Roll"), 12: ("Inclinação do quadril direito", "Right Hip Pitch"),
    13: ("Joelho direito", "Right Knee"), 14: ("Tornozelo direito", "Right Ankle"),
}
GROUP = {**{i: "R" for i in (10, 11, 12, 13, 14)}, **{i: "L" for i in (20, 21, 22, 23, 24)},
         **{i: "H" for i in (30, 31, 32, 33, 34)}}
# A direção de aumento das leituras do HD-1910 é oposta à do modelo (XL330); conferência individual em hardware real no servo-web em 20/09/2026: os 15 servos usam −1
DEFAULT_DIRECTIONS = {i: -1 for i in IDS}
POLL_HZ = 50
TORQUE_EVERY_S = 1.0          # lê o interruptor de torque separadamente, uma vez por segundo
STATIC_REGS = {13: "temp_limit", 21: "p", 22: "d", 33: "mode", 8: "resp_level", 19: "unload",
               50: "p_run", 51: "d_run"}    # 21/22 ficam na EEPROM; P/D em operação no HD-1910 ficam na RAM 50/51 (servo_ops grava aqui antes de habilitar torque)
BATTERY_FULL_V, BATTERY_EMPTY_V = 8.2, 6.6      # Algoritmo idêntico ao de duck-control/src/model.rs
LEAVE_WAIT_S = 3.0            # Tempo máximo de espera para operações dos servos em andamento ao sair da página (se não terminar, não devolve)
HANDBACK_WAIT_S = 10.0        # Ao selecionar “Devolver ao programa principal”: mesmo critério (a calibração detecta closing antes do próximo servo)
# Se alguma destas operações estiver ativa, o trabalho não terminou e a saída não devolve o barramento (revisão D3a, lote 3: sair durante a calibração em lote interrompia os servos restantes pela trava de torque)
BUSY_OPS = {"calibrate": "Calibração em andamento", "undo": "Desfazendo calibração", "timing": "Medindo temporização do barramento", "scan_all": "Varredura completa em andamento",
            "scan": "Varredura em andamento", "set_id": "Alterando ID", "reboot": "Reiniciando servo", "write_reg": "Gravando registrador"}


class Refused(Exception):
    """Esta operação não pode ser realizada agora (torque travado, barramento fechado, devolução em andamento ou parâmetros inválidos). O motivo é exibido diretamente à interface; servo_ops também usa esta exceção."""


def angle_deg(raw, direction):
    return None if raw is None else direction * (raw - 2048) * 360.0 / 4096


def battery_percent(volts):
    if not volts or volts <= 0:
        return None
    return max(0.0, min(1.0, (volts - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V))) * 100


def robotd_active():
    """Verifica se o robotd está em execução. No computador (sem systemctl), considera que não está; no Linux, erro/timeout do systemctl retorna None (estado desconhecido)."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        r = subprocess.run(["systemctl", "is-active", "robotd"], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() in ("active", "activating", "reloading")
    except (OSError, subprocess.TimeoutExpired):
        return None


def boot_id():
    """ID desta inicialização: lê /proc/sys/kernel/random/boot_id; retorna None se não estiver disponível (Windows ou arquivo inexistente)."""
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


BASELINE_PREFIX = "servo-baseline-"
_baseline_mem = {}       # Quando boot_id não está disponível (computador/demonstração), mantém a linha de base somente neste processo: (state_dir, modo de demonstração) -> {id: {"41","46"}}


class ServoSession:
    def __init__(self, log, port=None, sim=False, directions=None, baud=1_000_000, state_dir="."):
        self.log, self.port, self.sim, self.baud, self.state_dir = log, port, sim, baud, state_dir
        self.ops = None                  # servo_ops.ServoOps: existe somente enquanto o barramento está aberto
        self.directions = {**DEFAULT_DIRECTIONS, **(directions or {})}    # as chaves são int: dict(..., **d) falharia porque elas não são strings (em 19/10, o Studio não iniciou após salvar as orientações do segundo robô)
        self.bus = None
        self.state = "closed"            # closed / opening / open / error
        self.error = None
        self.latched = False             # trava de desligamento do torque
        self.relaxing = False
        self.last_relax = None           # {"ok", "ms", "bad", "at"}
        self.static = {}                 # id -> {temp_limit, p, d, mode, ...}
        self.rows = {}                   # id -> estado lido mais recentemente
        self.torque = {}                 # id -> 0/1/None
        self.torque_at = None
        self.hz = 0.0
        self.opened_at = None
        self.by = None
        self._stop = threading.Event()
        self._thread = None
        self._window = []                # (horário, asked, missed) dos últimos segundos, usado para calcular a taxa de perda de quadros
        self.sim_serial = None
        self.handed_back_at = None       # horário monotonic da última devolução; a interface informa “inicie manualmente” até o programa principal reconectar
        self.closing = False             # devolução/saída em andamento: rejeita novas operações e não deixa a habilitação manual do torque limpar a trava (revisão D2)
        self._cv = threading.Condition()
        self._inflight = {}              # operações dos servos em andamento: token -> nome da operação
        self._tok = 0
        self.restored = False            # esta sessão foi retomada após o reinício do Studio (revisão D1)
        self.orphan = None               # a sessão estava aberta no encerramento anterior, mas não foi retomada agora: {"why", "at"} (o botão de desligamento do torque direciona à página dos servos para retomar)
        self.helper_available = None     # disponibilidade do assistente root que inicia/para o robotd; a devolução informa “iniciando o programa principal...” (revisão D12)
        self.conflict_at = None          # detecta se o robotd foi iniciado manualmente durante a sessão (monotonic, revisão D9)
        self.probe_robotd = None         # se deve verificar se o robotd iniciou durante a sessão; None = verifica somente na porta serial real (o servo de demonstração usa um robotd simulado, sempre ativo)
        self.boot_id = None              # boot_id() usado para registrar a linha de base 41/46 na primeira tomada de controle desta inicialização
        self.baseline = {}               # id -> {"41": valor bruto, "46": valor bruto}; restaura antes de devolver
        self.handback_note = None        # servos cuja devolução foi bem-sucedida sem confirmar torque desligado (aviso na interface; removido na próxima tomada de controle)
        self.giveback_error = None       # motivo pelo qual o programa principal não iniciou após a devolução (aviso em vermelho)
        self.giveback_hint = None        # como recuperar se o programa principal não iniciou (com ou sem marcador)
        self.marker_error = None         # não foi possível gravar o marcador da sessão; após reiniciar, o Studio não saberá que o barramento continua aberto

    # ---- Abrir/fechar ----

    def open(self, by=None, port=None, restored=False):
        """Abre o barramento (bloqueante; o chamador deve usar uma thread). Retorna (ok, motivo).
        port: porta serial selecionada na interface (por exemplo, COM5 para um adaptador USB-TTL no computador, como no servo-web); “sim” = servos simulados.
        Não é possível trocar a porta serial enquanto estiver aberta (isso fecharia o barramento real, mas os servos continuariam retidos e não seria possível desligar o torque). Devolva o barramento antes de trocar.
        restored: retoma a sessão anterior após reiniciar o Studio (revisão D1); é definido junto com state="open",
        para que todos vejam que a sessão foi retomada assim que o estado indicar “aberta” (antes era definido depois, fora da thread, criando uma janela)."""
        if port:
            want_sim = port == "sim"
            if self.state == "open" and (want_sim != self.sim or (not want_sim and port != self.port)):
                # Trocar a porta durante o ajuste fecharia o barramento real, mas os 15 servos continuariam retidos e o torque não poderia ser desligado; nunca permita a troca
                return False, "Não troque a porta serial durante o ajuste dos servos. Selecione “Devolver ao programa principal” antes."
            self.sim = want_sim
            if not want_sim:
                self.port = port
        if self.state in ("open", "opening"):
            return True, None
        if not self.sim and not self.port:
            self.state, self.error = "closed", None
            return False, "Selecione uma porta serial (com adaptador USB-TTL conectado ao computador) ou “Demonstração (sem servos conectados)”."
        self.state, self.error, self.by = "opening", None, by
        try:
            if self.sim:
                from .bus.sim_bus import SimSerial
                self.sim_serial = SimSerial(IDS, phys=_sim_home())
                self.bus = feetech.FeetechBus(None, ser=self.sim_serial)
                where = "Demonstração (sem servos conectados; o software simula 15 servos)"
            else:
                active = robotd_active()
                if active is None:
                    raise RuntimeError("Não foi possível verificar se o programa principal está ativo (erro no systemctl). Para não disputar a porta serial, o barramento não será aberto.")
                if active:
                    raise RuntimeError("O robotd principal ainda está usando o barramento dos servos. Pare o programa principal primeiro.")
                self.bus = feetech.FeetechBus(self.port, self.baud)
                where = f"{self.port} @ {self.baud}"
            self.log.info(f"Abrindo o barramento dos servos: {where}", cat="Barramento", raw=f"by={by}")
            found = [i for i in IDS if self.bus.ping(i) is not None]
            missing = [i for i in IDS if i not in found]
            self._read_static(found)
            self._record_baseline(found)
            self._read_torque()
            self.restored = bool(restored)
            self.state, self.opened_at, self.latched = "open", time.monotonic(), False
            from .servo_ops import ServoOps
            self.ops = ServoOps(self, self.state_dir)
            self.ops.read_phase()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="servo-poll", daemon=True)
            self._thread.start()
            msg = f"Barramento dos servos aberto: {len(found)}/15 responderam"
            if missing:
                self.log.warn(msg, cat="Barramento", raw=f"Sem resposta: {missing}", hint="Verifique se os cabos desse servo estão conectados e se ele está alimentado")
            else:
                self.log.info(msg, cat="Barramento")
            return True, None
        except Exception as e:  # noqa: BLE001
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
            self.log.error("Não foi possível abrir o barramento dos servos", cat="Barramento", raw=self.error,
                           hint="No robô, pare primeiro o programa principal; no computador, conecte o adaptador USB-TTL e confira a porta informada.")
            self._close_bus()
            return False, self.error

    def holding(self):
        """Número de servos com torque ativo (leitura de retorno igual a 1; cache de 1 s apenas para a interface; devolução/saída usa read_torque_now). Zero se o barramento estiver fechado."""
        if self.state != "open":
            return 0
        return sum(1 for i in IDS if self.torque.get(i) == 1)

    def unknown(self):
        """Número de servos sem leitura de torque (sem resposta); eles também podem estar retidos. Zero com o barramento fechado."""
        if self.state != "open":
            return 0
        return sum(1 for i in IDS if self.torque.get(i) not in (0, 1))

    @property
    def halted(self):
        """Com a trava de torque ativa ou a devolução em andamento, transições em segundo plano, animações e finalizações de calibração não podem habilitar torque nem mover os servos."""
        return self.latched or self.closing

    # ---- Operações de servo em andamento (revisão D2) ----

    def op_begin(self, name):
        """Registra uma operação de servo (app chama no event loop antes de iniciar a thread). Lança Refused durante devolução ou com o barramento fechado. Retorna o token para op_end."""
        with self._cv:
            if self.closing:
                raise Refused("Devolução ao programa principal em andamento; novas operações de servo foram recusadas")
            if self.state != "open":
                raise Refused("O barramento dos servos está fechado. Selecione “Iniciar ajuste dos servos” primeiro.")
            self._tok += 1
            tok = self._tok
            self._inflight[tok] = str(name or "?")
            return tok

    def op_end(self, tok):
        """Marca a operação como concluída (chamadas repetidas são seguras)."""
        with self._cv:
            if self._inflight.pop(tok, None) is not None:
                self._cv.notify_all()

    @contextlib.contextmanager
    def op_slot(self, name):
        tok = self.op_begin(name)
        try:
            yield
        finally:
            self.op_end(tok)

    def wait_ops(self, timeout):
        """Aguarda a conclusão de todas as operações de servo em andamento; retorna False em caso de timeout."""
        with self._cv:
            return self._cv.wait_for(lambda: not self._inflight, timeout)

    def inflight_names(self):
        with self._cv:
            return sorted(set(self._inflight.values()))

    def _busy_locked(self):
        """Informa o motivo se houver calibração, movimento ou animação em andamento; retorna None caso contrário (chamado com _cv adquirido)."""
        for name in self._inflight.values():
            if name in BUSY_OPS:
                return BUSY_OPS[name]
        ops = self.ops
        if ops is not None:
            if ops.calib_lock.locked():
                return "Calibração em andamento"
            if ops._motion is not None and ops._motion.is_alive() and not ops._motion_stop.is_set():
                return "Há uma ação em andamento"
            if ops.idle_running:
                return "Animação em andamento"
        return None

    def read_torque_now(self):
        """Lê agora o interruptor de torque dos 15 servos (sem cache): {id: 0 / 1 / None (sem resposta)}. Se o barramento falhar, todos retornam None."""
        try:
            got = self._read_torque()
        except Exception as e:  # noqa: BLE001
            self.log.warn("Não foi possível ler o torque", cat="Barramento", raw=f"{type(e).__name__}: {e}")
            return {i: None for i in IDS}
        return {i: (v[1][0] if v else None) for i, v in ((i, got.get(i)) for i in IDS)}

    def leave(self, why, wait_s=LEAVE_WAIT_S, before_close=None):
        """Ao sair da página dos servos/deixar de ser visualizada (bloqueante; executar em uma thread): desliga o torque e fecha o barramento se puder devolvê-lo. Retorna (resultado, detalhes):
            ("closed", None)       já estava fechado
            ("kept", {"why", "holding", "unknown"})   não devolvido (operação em andamento, servos retidos/sem leitura ou operações que não terminaram)
            ("handed_back", None)  torque desligado e barramento fechado (o app cuida do programa principal)"""
        with self._cv:
            if self.state != "open":
                return "closed", None
            busy = self._busy_locked()
            if busy:
                return "kept", {"why": busy, "holding": self.holding(), "unknown": self.unknown()}
            self.closing = True
        try:
            if not self.wait_ops(wait_s):
                return "kept", {"why": f"Ainda há operações de servo em andamento({', '.join(self.inflight_names())})", "holding": self.holding(),
                                "unknown": self.unknown()}
            tq = self.read_torque_now()
            on = [i for i in IDS if tq.get(i) == 1]
            unk = [i for i in IDS if tq.get(i) not in (0, 1)]
            if on or unk:
                parts = ([f"{len(on)}  servos retidos"] if on else []) + ([f"{len(unk)}  servos sem leitura de torque (também podem estar retidos)"] if unk else [])
                return "kept", {"why": ", ".join(parts), "holding": len(on), "unknown": len(unk)}
            ok, reason = self.relax_all(why)
            if not ok:
                self.log.warn("Não foi possível confirmar o desligamento do torque antes da devolução", cat="Segurança", raw=reason, hint="O programa principal também tentará desligar o torque ao iniciar; se houver dúvida, desligue a alimentação")
            bad, _unknown = self._restore_baseline()
            if bad:
                ids = ", ".join(f"#{i}" for i in bad)
                msg = f"{len(bad)}  servos não tiveram aceleração/velocidade restaurada({ids}): barramento não devolvido. O torque dos servos foi desligado; selecione “Devolver ao programa principal” novamente para tentar de novo"
                self.log.error("Falha ao restaurar a linha de base 41/46: barramento não devolvido", cat="Segurança", raw=ids, dedup=False, hint=msg)
                return "kept", {"why": msg, "holding": self.holding(), "unknown": self.unknown()}
            if before_close is not None:
                before_close()          # Remove também a pausa de “ajuste dos servos” antes de fechar o barramento, para que o estado já esteja completo quando closed for observado (requisito de ordenação das revisões D1/D2)
            self.close()
            return "handed_back", None
        finally:
            with self._cv:
                self.closing = False

    def hand_back_bus(self, why, wait_s=HANDBACK_WAIT_S, before_close=None):
        """Ao selecionar “Devolver ao programa principal” (bloqueante; executar em uma thread): define closing → para movimento/animação → aguarda operações pendentes → desliga e lê o torque → fecha o barramento.
        Se não terminar a tempo, não devolve e retorna (False, motivo)."""
        with self._cv:
            if self.state != "open":
                return True, None
            self.closing = True
        try:
            if self.ops is not None:
                self.ops.idle_running = False
                self.ops._motion_stop.set()
            if not self.wait_ops(wait_s):
                names = ", ".join(self.inflight_names()) or "?"
                return False, f"Ainda há operações de servo em andamento ({names}); aguardou {wait_s:.0f} s. Barramento não devolvido. Aguarde e selecione “Devolver ao programa principal” novamente."
            ok, reason = self.relax_all(why)
            if not ok:
                self.log.warn("Não foi possível confirmar o desligamento do torque antes da devolução", cat="Segurança", raw=reason, hint="O programa principal também tentará desligar o torque ao iniciar; se houver dúvida, desligue a alimentação")
            bad, unknown = self._restore_baseline()
            if bad:
                ids = ", ".join(f"#{i}" for i in bad)
                msg = f"{len(bad)}  servos não tiveram aceleração/velocidade restaurada({ids}): barramento não devolvido. O torque dos servos foi desligado; selecione “Devolver ao programa principal” novamente para tentar de novo"
                self.log.error("Falha ao restaurar a linha de base 41/46: barramento não devolvido", cat="Segurança", raw=ids, dedup=False, hint=msg)
                return False, msg
            relax_bad = list((self.last_relax or {}).get("bad") or [])
            note_ids = sorted(set(relax_bad) | set(unknown), key=IDS.index)
            note = (f"{', '.join(f'#{i}' for i in note_ids)} torque não confirmado como desligado; o programa principal tentará novamente ao iniciar. Se houver dúvida, desligue a alimentação"
                    if note_ids else None)
            if before_close is not None:
                before_close()          # Remove a pausa de ajuste dos servos antes de fechar o barramento, para que o estado esteja completo ao observar closed
            self.close()
            return True, note
        finally:
            with self._cv:
                self.closing = False

    def close(self):
        """Fecha o barramento (bloqueante). Fecha somente a porta serial, sem alterar o estado dos servos (também usado ao sair do Studio ou detectar que o robotd foi iniciado manualmente: não desliga torque nem grava).
        Para devolver ao programa principal (desligando e lendo o torque antes de fechar), use hand_back_bus/leave."""
        if self.ops is not None:
            self.ops.idle_running = False
            self.ops._motion_stop.set()
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._close_bus()
        self.ops = None
        if self.state != "closed":
            self.log.info("Barramento dos servos fechado", cat="Barramento", dedup=False)
        self.state = "closed"
        self.rows, self.torque = {}, {}
        self.restored = False

    def _close_bus(self):
        if self.bus is not None:
            try:
                self.bus.close()
            except Exception:  # noqa: BLE001
                pass
        self.bus = None

    # ---- Leitura ----

    def _read_static(self, ids):
        for sid in ids:
            d = {}
            for addr, key in STATIC_REGS.items():
                try:
                    d[key] = self.bus.read_u8(sid, addr)
                except feetech.BusError:
                    d[key] = None
            try:
                d["offset"] = feetech.sign15(self.bus.read_u16(sid, 31))
                d["torque_limit"] = self.bus.read_u16(sid, 48)
            except feetech.BusError:
                d.setdefault("offset", None)
            self.static[sid] = d

    def _baseline_path(self, bid):
        return os.path.join(self.state_dir, f"{BASELINE_PREFIX}{bid}.json")

    def _baseline_load(self, bid):
        """Lê a linha de base desta inicialização. Se boot_id não estiver disponível ou for uma sessão de demonstração, usa a memória do processo (separada por diretório state e modo de demonstração)."""
        if bid is None:
            return _baseline_mem.setdefault((os.path.abspath(self.state_dir), bool(self.sim)), {})
        try:
            with open(self._baseline_path(bid), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        regs = data.get("regs") if isinstance(data, dict) else None
        out = {}
        if isinstance(regs, dict):
            for k, v in regs.items():
                try:
                    sid = int(k)
                except (TypeError, ValueError):
                    continue
                if sid in IDS and isinstance(v, dict) and isinstance(v.get("41"), int) and isinstance(v.get("46"), int):
                    out[sid] = {"41": v["41"] & 0xFF, "46": v["46"] & 0xFFFF}
        return out

    def _baseline_save(self, bid, regs):
        """Grava servo-baseline-<boot_id>.json atomicamente (arquivo temporário seguido de os.replace)."""
        path = self._baseline_path(bid)
        data = {"v": 1, "boot_id": bid, "at": time.time(),
                "regs": {str(i): dict(regs[i]) for i in IDS if i in regs}}
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            self.log.warn("A linha de base 41/46 não foi gravada no arquivo (continua na memória deste processo)", cat="Barramento", step=path,
                          raw=f"{type(e).__name__}: {e}", hint="Verifique se o diretório state está cheio e se há permissões")

    def _record_baseline(self, found):
        """Na primeira tomada de controle desta inicialização, registra os valores brutos de 41 (1 byte) e 46 (2 bytes).
        Se o arquivo deste boot_id já existir, não o sobrescreve; adiciona apenas servos que responderam agora e ainda não constam no arquivo.
        Se boot_id não estiver disponível, mantém os dados somente na memória do processo. Sessões de demonstração também não alteram arquivos de linha de base em state."""
        bid = boot_id()
        self.boot_id = bid
        if self.sim:
            # Os registradores 41/46 dos servos simulados não são reais: não lê, grava nem remove linhas de base em state; mantém tudo na memória
            regs = self._baseline_load(None)
        else:
            if bid is not None:
                current = os.path.basename(self._baseline_path(bid))
                try:
                    names = os.listdir(self.state_dir)
                except OSError:
                    names = []
                for name in names:                  # linhas de base de inicializações anteriores não servem mais
                    if name.startswith(BASELINE_PREFIX) and name.endswith(".json") and name != current:
                        try:
                            os.remove(os.path.join(self.state_dir, name))
                        except OSError:
                            pass
            regs = self._baseline_load(bid)
        added = False
        for sid in found:
            if sid in regs:
                continue
            try:
                regs[sid] = {"41": self.bus.read_u8(sid, 41), "46": self.bus.read_u16(sid, 46)}
            except feetech.BusError as e:
                self.log.warn(f"Linha de base 41/46: não foi possível ler #{sid}; ignorando", cat="Barramento", step="Leitura da linha de base 41/46",
                              raw=f"{type(e).__name__}: {e}", hint="Este servo pode não estar conectado ao barramento agora")
                continue
            added = True
        self.baseline = regs
        if not self.sim and bid is not None and added:
            self._baseline_save(bid, regs)

    def _restore_baseline(self):
        """Antes de devolver, restaura os valores de linha de base 41/46 e relê; tenta novamente no máximo duas vezes.
        Retorna (servos com leitura divergente, servos sem resposta): não devolve no primeiro caso; no segundo, registra apenas um aviso, pois o programa principal também não poderá acessá-los ao iniciar."""
        if self.state != "open" or self.bus is None:
            return [], []
        base = getattr(self, "baseline", None) or {}
        missing = [i for i in IDS if i not in base]
        if missing:
            self.log.info(f"Transferência: ignorando {len(missing)} servos sem linha de base 41/46 (não responderam na tomada de controle desta inicialização)", cat="Barramento",
                          raw=f"Sem linha de base: {missing}", dedup=False)
        bad, unknown = [], []
        for sid in IDS:
            want = base.get(sid)
            if not want:
                continue
            outcome, last = "unknown", None
            for _ in range(3):                      # primeira tentativa + duas repetições
                try:
                    self.bus.write_u8(sid, 41, int(want["41"]) & 0xFF)
                    self.bus.write_u16(sid, 46, int(want["46"]) & 0xFFFF)
                    got41 = self.bus.read_u8(sid, 41)
                    got46 = self.bus.read_u16(sid, 46)
                except feetech.BusError as e:
                    outcome, last = "unknown", e
                    continue
                if got41 == (int(want["41"]) & 0xFF) and got46 == (int(want["46"]) & 0xFFFF):
                    outcome = "ok"
                    break
                outcome, last = "bad", f"leitura 41={got41}, 46={got46}; esperado: {want['41']}, {want['46']}"
            if outcome == "ok":
                continue
            if outcome == "bad":
                bad.append(sid)
                self.log.error(f"Divergência ao restaurar a linha de base 41/46: #{sid}", cat="Segurança", step="Leitura de retorno 41/46",
                               raw=str(last), hint="Se a leitura divergir, não devolve; selecione “Devolver ao programa principal” novamente")
            else:
                unknown.append(sid)
                self.log.warn(f"Restauração da linha de base 41/46: #{sid} não respondeu; sem confirmação", cat="Segurança", step="Gravação/leitura de retorno 41/46",
                              raw=f"{type(last).__name__}: {last}", hint="O programa principal também não poderá acessá-lo ao iniciar")
        return bad, unknown

    def refresh_static(self, ids):
        """Após calibrar ou gravar registradores, relê offsets, P/D etc. desses servos para mostrar os novos valores nas linhas expandidas da tabela."""
        if self.bus is not None:
            self._read_static([i for i in ids if i in IDS])

    def _read_torque(self):
        got = self.bus.sync_read(IDS, 40, 1)
        self.torque = {sid: (v[1][0] if v else None) for sid, v in got.items()}
        self.torque_at = time.monotonic()
        return got

    def _loop(self):
        period = 1.0 / POLL_HZ
        n, t_rate = 0, time.monotonic()
        next_torque = time.monotonic() + TORQUE_EVERY_S
        while not self._stop.is_set():
            t0 = time.monotonic()
            if self.ops is not None and self.ops.calib_lock.locked():
                # Não disputa o barramento durante calibração ou testes de temporização: um sync_read pode bloquear por centenas de milissegundos, coincidindo com a janela de desligamento do torque
                self._stop.wait(0.02)
                continue
            try:
                states = self.bus.states(IDS)
                now = time.monotonic()
                for sid, s in states.items():
                    if s is not None:
                        s["at"] = now
                        self.rows[sid] = s
                if now >= next_torque:
                    self._read_torque()
                    next_torque = now + TORQUE_EVERY_S
            except Exception as e:  # noqa: BLE001 —— por exemplo, cabo serial desconectado; registra uma vez e tenta novamente depois
                self.log.error("Erro ao ler os servos", cat="Barramento", raw=f"{type(e).__name__}: {e}", dedup=True)
                time.sleep(0.5)
            n += 1
            if time.monotonic() - t_rate >= 1.0:
                self.hz = n / (time.monotonic() - t_rate)
                n, t_rate = 0, time.monotonic()
                self._note_window()
            left = period - (time.monotonic() - t0)
            if left > 0:
                self._stop.wait(left)

    def _note_window(self):
        tot = self._totals()
        self._window.append((time.monotonic(), tot[0], tot[1]))
        self._window = self._window[-6:]        # últimos 5 segundos

    def _totals(self):
        per = self.bus.per_id if self.bus else {}
        return (sum(c["asked"] for c in per.values()), sum(c["missed"] for c in per.values()))

    def drop_rate(self):
        if len(self._window) < 2:
            return None
        (_, a0, m0), (_, a1, m1) = self._window[0], self._window[-1]
        return None if a1 == a0 else (m1 - m0) / (a1 - a0)

    # ---- Desligamento do torque ----

    def relax_all(self, by=None):
        """Desliga o torque dos 15 servos no barramento e confirma pela leitura de retorno (bloqueante, alguns milissegundos). Retorna (todos confirmados, motivo)."""
        if self.state != "open" or self.bus is None:
            return False, "O barramento dos servos está fechado"
        self.latched, self.relaxing = True, True
        if self.ops is not None:                 # para primeiro transições e animações em andamento (a trava também impede que gravem depois)
            self.ops.idle_running = False
            self.ops._motion_stop.set()
        t0 = time.monotonic()
        bad = list(IDS)
        try:
            self.bus.sync_write(40, 1, [(sid, b"\x00") for sid in IDS])
            for _ in range(3):
                got = self._read_torque()
                bad = [sid for sid, v in got.items() if v is None or v[1][0] != 0]
                if not bad:
                    break
                for sid in bad:                      # reenvia individualmente aos servos sem confirmação
                    try:
                        self.bus.write_u8(sid, 40, 0)
                    except feetech.BusError:
                        pass
        except Exception as e:  # noqa: BLE001
            self.log.error("Erro ao desligar o torque pelo barramento", cat="Segurança", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="Segure o robô e desligue a alimentação")
        finally:
            self.relaxing = False
        ms = round((time.monotonic() - t0) * 1000)
        self.last_relax = {"ok": not bad, "ms": ms, "bad": bad, "at": time.monotonic()}
        if bad:
            self.log.error(f"Desligamento do torque pelo barramento: {len(bad)} sem confirmação", cat="Segurança", step="Leitura de retorno sync_read 40",
                           raw=f"Sem confirmação: {bad}", ctx={"by": by, "ms": ms}, hint="Talvez um cabo esteja solto e não haja resposta; desligar a alimentação é a opção mais segura", dedup=False)
            return False, f"{len(bad)} servos sem confirmação: {bad}"
        # Registra cada mudança de estado (revisão D13: deduplicar em 1 minuto ocultava a segunda devolução ou desligamento de torque, impedindo reconciliar os eventos)
        self.log.info(f"Torque desligado e confirmado nos 15 servos pelo barramento ({ms} ms)", cat="Segurança", step="Leitura de retorno sync_read 40", raw=f"by={by}", dedup=False)
        return True, None

    # ---- Dados para a interface ----

    def snapshot(self):
        now = time.monotonic()
        rows, volts = [], []
        per = self.bus.per_id if self.bus else {}
        for sid in IDS:
            s = self.rows.get(sid)
            st = self.static.get(sid, {})
            c = per.get(sid, {})
            age = None if not s else now - s["at"]
            fresh = age is not None and age < 0.5
            if fresh and s.get("volt"):
                volts.append(s["volt"])
            cn, en = NAMES[sid]
            rows.append({
                "id": sid, "cn": cn, "en": en, "group": GROUP[sid], "dir": self.directions[sid],
                "raw": s["pos"] if s else None,
                "deg": round(angle_deg(s["pos"], self.directions[sid]), 1) if s else None,
                "volt": s["volt"] if s else None, "temp": s["temp"] if s else None,
                "temp_limit": st.get("temp_limit"), "load": s["load"] if s else None,
                "current_ma": round(s["current_ma"]) if s else None,
                "status": s["status_text"] if s else None, "moving": s["moving"] if s else None,
                "torque": self.torque.get(sid), "fresh": fresh, "age_ms": None if age is None else round(age * 1000),
                "p": st.get("p"), "d": st.get("d"), "mode": st.get("mode"), "offset": st.get("offset"),
                "comm": {k: c.get(k, 0) for k in ("asked", "ok", "missed", "alarm", "streak", "max_streak")},
            })
        avg_v = round(sum(volts) / len(volts), 2) if volts else None
        torque_fresh = self.torque_at is not None and now - self.torque_at < 2.5
        all_off = torque_fresh and all(self.torque.get(i) == 0 for i in IDS)
        dr = self.drop_rate()
        return {
            "t": "servo", "state": self.state, "error": self.error, "sim": self.sim, "source": "bus",
            "port": "Demonstração (sem servos conectados)" if self.sim else self.port,
            "marker_error": self.marker_error,
            "online": sum(1 for r in rows if r["fresh"]), "total": len(IDS),
            "hz": round(self.hz, 1), "avg_volts": avg_v, "battery_pct": battery_percent(avg_v),
            "drop_rate": None if dr is None else round(dr, 4),
            "bus": dict(self.bus.stats) if self.bus else None,
            "holding": sum(1 for i in IDS if self.torque.get(i) == 1),
            "all_off": all_off, "latched": self.latched, "relaxing": self.relaxing, "closing": self.closing,
            "last_relax": None if not self.last_relax else {k: v for k, v in self.last_relax.items() if k != "at"},
            "rows": rows,
            # Cabeçalho “ganhos suaves/firmes: P5 · D0 · limite de torque 1000 (igual ao programa principal)”; também adiciona P/D/limite de torque em operação a cada linha (servo_ops.gains_view)
            "gains": ops.gains_view(rows) if (ops := self.ops) is not None else None,
        }

    def estop_status(self):
        """Dados para o botão superior de desligamento do torque: durante a sessão dos servos, vale a leitura de retorno do barramento."""
        if self.state != "open":
            return {"state": "unavailable", "why": "O barramento dos servos está fechado, somente desligando a alimentação"}
        if self.relaxing:
            return {"state": "pending", "why": "Desligando o torque…"}
        s = self.snapshot()
        if s["all_off"]:
            return {"state": "confirmed", "why": "Torque desligado nos 15 servos (confirmado pelo barramento)"}
        return {"state": "ready", "why": "Ajustando servos: desligamento do torque enviado diretamente pelo barramento"}


def view_from_robotd(bus, directions, state="closed", error=None, sim=False):
    """Mesmo sem assumir o barramento, a página dos servos exibe a tabela com dados de busStatus do programa principal (que já lê os servos), em modo somente leitura.
    O ângulo usa o mesmo cálculo após assumir o barramento (orientação × (leitura − 2048)); os valores coincidem antes e depois.
    position_rad do programa principal usa o próprio zero_raw; não é usado aqui."""
    native = (bus or {}).get("native") if isinstance(bus, dict) and isinstance(bus.get("native"), dict) else {}
    joints = {j.get("id"): j for j in (native.get("joints") or []) if isinstance(j, dict)}
    torque_on = native.get("torque_enabled")
    rows, volts = [], []
    for sid in IDS:
        j = joints.get(sid) or {}
        raw = j.get("position_raw")
        d = DEFAULT_DIRECTIONS[sid] if directions is None else directions.get(sid, -1)
        fresh = j.get("feedback_fresh") is True
        if fresh and isinstance(j.get("volts"), (int, float)):
            volts.append(j["volts"])
        cn, en = NAMES[sid]
        rows.append({
            "id": sid, "cn": cn, "en": en, "group": GROUP[sid], "dir": d,
            "raw": raw, "deg": round(angle_deg(raw, d), 1) if isinstance(raw, int) else None,
            "volt": j.get("volts"), "temp": j.get("temperature_c"), "temp_limit": None,
            "load": j.get("load_raw"), "current_ma": j.get("current_ma"), "status": None, "moving": None,
            "torque": None if torque_on is None else int(bool(torque_on)), "fresh": fresh,
            "age_ms": j.get("sample_age_ms"), "p": None, "d": None, "mode": None, "offset": None,
            "comm": {"asked": None, "ok": None, "missed": j.get("missing_total", 0) or 0, "alarm": 0,
                     "streak": j.get("consecutive_missing", 0) or 0, "max_streak": None},
        })
    avg_v = round(sum(volts) / len(volts), 2) if volts else None
    return {
        "t": "servo", "state": state, "error": error, "sim": sim, "source": "robotd",
        "port": "Programa principal", "online": sum(1 for r in rows if r["fresh"]), "total": len(IDS),
        "hz": None, "avg_volts": avg_v, "battery_pct": battery_percent(avg_v), "drop_rate": None, "bus": None,
        "holding": sum(1 for r in rows if r["torque"] == 1), "all_off": False, "latched": False,
        "relaxing": False, "last_relax": None, "rows": rows,
    }


def _sim_home():
    """Posiciona os servos simulados na postura em pé oficial (leitura = 2048 + orientação × ângulo), visível na visualização 3D."""
    home = {20: 0.0, 21: -0.0873, 22: -0.4579, 23: -0.0049, 24: 0.4530, 30: 0.3491, 31: 0.3491,
            32: 0.0, 33: 0.0, 34: 0.0, 10: 0.0, 11: 0.0873, 12: 0.4579, 13: 0.0049, 14: -0.4530}
    return {sid: round(2048 + DEFAULT_DIRECTIONS[sid] * rad * 4096 / (2 * 3.141592653589793)) for sid, rad in home.items()}


def list_ports():
    """Portas seriais disponíveis no sistema. O nome muda ao reconectar o USB; selecione diretamente na interface (como no servo-web)."""
    try:
        from serial.tools import list_ports as lp
        return [{"device": p.device, "desc": (p.description or "").strip()} for p in lp.comports()]
    except Exception:  # noqa: BLE001
        return []


def load_directions(state_dir):
    """Tabela de orientações: usa servo-directions.json no diretório state, se existir; caso contrário, define todos como −1."""
    p = os.path.join(state_dir, "servo-directions.json")
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return {int(k): int(v) for k, v in d.items() if k.isdigit() and int(v) in (1, -1)}
    except (OSError, ValueError):
        return {}
