"""Operações da página dos servos: adaptadas de server.py do servo-web (tools/servo-web v0.15.4 no mesmo repositório; código nosso, verificado em hardware real).

Recursos adaptados:
- Liga/desliga o torque: antes de ligar, alinha o alvo à leitura atual;
- Grava alvos pelo controle deslizante; movimentos suaves ou em fluxo; leitura de retorno do alvo e reenvio se não houver resposta; “Parar”;
- Posturas oficiais (zero/em pé/sentado/recolhido; joelhos flexionados somente 88° ao recolher); posturas salvas (salvar, executar e mover para a lixeira);
- Calibração central: individual ou em lote; pré-visualização; detecta o sinal do offset; confirma torque desligado pela leitura de retorno; se 0x0B não for aceito, grava no registrador 31; compensa a queda por gravidade;
  Sempre finaliza gravando a leitura atual como alvo; backup e desfazer; recalcula as posturas salvas após a calibração;
- Varredura (conhecidos/especificados/todos de 0 a 253), exportação dos registradores 0–86, gravação de registrador (desbloqueia EEPROM), alteração de ID e reinicialização 0x08,
  teste de temporização sync_read e orientação ±;
- Animação (pequenos movimentos aleatórios da cabeça): no servo-web roda na página; aqui foi movida para uma thread do backend e pode ser interrompida mesmo ao fechar a página.

Alterações do Studio (pedidos do usuário e revisão do plano):
- **Com a trava de torque ativa** (session.latched), rejeita habilitação de torque, gravação de alvo, movimento, calibração, desfazer, gravação de registrador e alteração de ID até alguém selecionar “Destravar”;
- **Retém automaticamente após calibrar** (pedido do usuário: manter os servos logo após a calibração central): alinha e habilita o torque nos servos calibrados com sucesso;
- **Usa somente o zero oficial 2048 como referência** (pedido do usuário: não usar a postura recolhida);
- **Os ganhos ao habilitar torque são iguais aos do programa principal** (pedido de 19/10): antes de ligar o torque, grava na RAM P/D/limite de torque usados pelo programa principal
  (arquivo de parâmetros; se não existir, P5 · D0 · limite 1000). Se não conseguir gravar, não habilita o torque; consulte MainGains e apply_gains;
- Arquivos no diretório state do Studio (servo-calib/, servo-poses/); backups da calibração simulada ficam em diretório temporário, separados dos servos reais.
"""
import json
import math
import os
import random
import struct
import tempfile
import threading
import time

from .bus import feetech
from .servo import IDS, Refused  # noqa: F401 —— Refused fica em servo.py (op_begin da sessão também a lança); reexporta aqui por compatibilidade

CALIB_TOLERANCE = 2      # quantos passos a leitura após calibrar pode diferir do alvo
DROOP_TOLERANCE = 3      # queda máxima em passos durante os poucos milissegundos com torque desligado para não compensar
OFFSET_LIMIT = 2047      # faixa segura do registrador de offset 31 (|offset| ≤ 2047 em todas as codificações; não grava acima disso)
CALIB_BIG_DEG = 30       # se a postura atual diferir do alvo por mais graus, a interface pede confirmação e o log registra separadamente (sem bloquear)
FOLD_KNEE_SEND = 88 * math.pi / 180     # Ao executar “recolher”, flexiona os joelhos somente 88°; os 90° oficiais fazem os tornozelos baterem nos servos da coxa
JOINT = {20: "left_hip_yaw", 21: "left_hip_roll", 22: "left_hip_pitch", 23: "left_knee", 24: "left_ankle",
         30: "neck_pitch", 31: "head_pitch", 32: "head_yaw", 33: "head_roll", 34: "mouth",
         10: "right_hip_yaw", 11: "right_hip_roll", 12: "right_hip_pitch", 13: "right_knee", 14: "right_ankle"}
# Posturas oficiais: keyframes de microduck_rl scene.xml (iguais aos do servo-web), em radianos e seguindo o modelo, indexadas por ID do servo. A boca só tem posição zero
OFFICIAL = {
    "zero": ("Zero", {i: 0.0 for i in IDS}),
    "stand": ("Em pé", {20: 0, 21: -0.0873, 22: -0.4579, 23: -0.0049, 24: 0.453, 30: 0.3491, 31: 0.3491, 32: 0, 33: 0,
                     10: 0, 11: 0.0873, 12: 0.4579, 13: 0.0049, 14: -0.453}),
    "sit": ("Sentado", {20: 0, 21: 0, 22: -0.5236, 23: 1.0472, 24: 0, 30: 0.5, 31: 1.6, 32: 0, 33: 0,
                   10: 0, 11: 0, 12: 0.5236, 13: -1.0472, 14: 0}),
    "fold": ("Recolhido", {20: 0, 21: 0, 22: 1.57, 23: 1.57, 24: 0, 30: 1, 31: 1, 32: 0, 33: 0,
                      10: 0, 11: 0, 12: -1.57, 13: -1.57, 14: 0}),
}
# Gravar estes registradores pode ter consequências graves; a interface os destaca em vermelho e explica o efeito (revisão G3)
DANGER = {5: "ID: pode causar conflito; mantenha somente este servo no barramento ao alterar", 6: "Taxa de transmissão: alterar causa perda de conexão", 8: "Nível de resposta: com valor 0, comandos de gravação não respondem",
          9: "Limite mínimo de ângulo", 11: "Limite máximo de ângulo", 19: "Condição de desativação (proteções): desativar superaquecimento/sobrecorrente impede o desligamento automático",
          33: "Modo de operação: no modo de velocidade, o servo gira continuamente", 40: "Interruptor de torque: use o controle da interface, não grave por aqui"}
DEG = 4096 / 360
# Animação: cada movimento é [graus relativos ao centro, segundos]. 32 guinada, 33 rolagem, 31 inclinação da cabeça, 30 inclinação do pescoço, 34 boca (positivo = abrir). {} = parado
GESTURES = [
    (3, lambda s: [({33: 14 * s, 32: 8 * s}, 0.5), ({}, random.uniform(0.6, 1.4)), ({33: 0, 32: 0}, 0.6)]),           # inclina a cabeça
    (3, lambda s: [({32: 30 * s, 33: -5 * s, 31: 4}, 0.6), ({}, random.uniform(0.8, 1.8)), ({32: 0, 33: 0, 31: 0}, 0.7)]),  # olha para o lado
    (2, lambda s: [({32: -20}, 0.3), ({32: 20}, 0.38), ({32: -12}, 0.32), ({32: 0}, 0.35)]),                            # balança a cabeça
    (2, lambda s: [({31: 12}, 0.3), ({31: -7}, 0.34), ({31: 6}, 0.3), ({31: 0}, 0.35)]),                                # faz que sim
    (2, lambda s: [({34: 16}, 0.22), ({34: 0}, 0.26), ({34: 13}, 0.22), ({34: 0}, 0.28)]),                              # grasna duas vezes
    (2, lambda s: [({33: 12 * s, 31: -8, 34: 9}, 0.55), ({}, random.uniform(0.5, 1.0)), ({34: 0}, 0.25), ({33: 0, 31: 0}, 0.6)]),  # curiosa
    (2, lambda s: [({32: 18 * s, 31: 6}, 0.45), ({32: -18 * s, 31: 6}, 0.7), ({32: 0, 31: 0}, 0.5)]),                   # olha ao redor
    (1, lambda s: [({33: 7, 32: 6}, 0.18), ({33: -7, 32: -6}, 0.2), ({33: 0, 32: 0}, 0.25)]),                           # dá uma sacudida
]
CAT = {"Movimento": "Barramento", "Registradores": "Barramento", "Orientações": "Calibração", "Posturas": "Calibração"}


def enc_sm(v):
    """Codificação sinal-magnitude: nos registradores 31 (offset), 42 (posição-alvo) e 46 (velocidade), BIT15 é o bit de sinal; não é complemento de dois.
    Para gravar -5, use 0x8005; com 0xFFFB, o servo interpreta -32763 e vai em velocidade máxima até o limite."""
    v = int(v)
    return (0x8000 | (-v & 0x7FFF)) if v < 0 else (v & 0x7FFF)


def fmt_off(v):
    if v is None:
        return "?"
    if v < 0:
        return str(v)
    return f"{feetech.sign15(v)}(bruto: {v})" if v & 0x8000 else str(v)


def _ack(err):
    """Resposta a um comando de gravação: 0 = normal; None = sem resposta; qualquer outro valor = alarme nos bits de status do servo."""
    return "✓" if err == 0 else ("(sem resposta)" if err is None else f"(status 0x{err:02X})")


def infer_offset_sign(before, after, d_off, slack=8):
    """Infere o sinal do offset após uma calibração: a leitura muda de before para after e o offset muda d_off. Como leitura = bruto + s × offset, after − before ≈ s × d_off
    (a articulação pode ceder alguns passos nesse intervalo; mantém uma margem). Só aceita se um sinal corresponder e o outro claramente não; se o offset mudar pouco demais para distinguir, retorna None."""
    if before is None or after is None or d_off is None or abs(d_off) < 4:
        return None
    moved = after - before
    miss = {s: abs(moved - s * d_off) for s in (1, -1)}
    s = min(miss, key=miss.get)
    if miss[s] > max(slack, abs(d_off) // 2) or miss[-s] - miss[s] < abs(d_off):
        return None
    return s


def parse_ids(text):
    """“20-24,30-34,10-14”→ [20..24, 30..34, 10..14]."""
    out = []
    for part in str(text or "").replace(", ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    if any(not 0 <= i <= 253 for i in out):
        raise Refused("ID deve estar entre 0 e 253")
    return out


# ---------------- P/D/limite de torque ao habilitar torque: iguais aos do programa principal (pedido de 19/10) ----------------
# “P e D devem corresponder aos do programa principal; os padrões também são P5, D0 e limite 1000”: o Studio aplica os mesmos ganhos do nosso fork do robotd ao habilitar os servos
# são os mesmos usados ao habilitar o torque; não usa os padrões da EEPROM do servo (P32/D40, muito mais rígidos).
# Assim, a rigidez ao ajustar os servos é igual à usada ao andar; uma futura transferência sem desligar torque também passará na verificação do programa principal, sem trocar P (alterar P sob carga pode fazer a articulação ceder).
ROBOT_ETC = "/etc/robot/feetech-ft5"
SERVO_PARAMS = ROBOT_ETC + "/servo-test-parameters.json"       # no mesmo diretório do arquivo de calibração(fork hd1910_test.rs:21-22)
ROBOTD_TOMLS = (ROBOT_ETC + "/robotd.toml", "/etc/robot/robotd.toml")   # Mesma lista de onboard.ROBOTD_CONFIGS
POLICY_DIR = "/opt/robot/policies/current"                     # diretório usado se [policy] walk não estiver definido (fork robotd-params lib.rs:41, 1611–1666)
DEFAULT_GAINS = (5, 0, 1000)      # V167 sem arquivo de parâmetros: P = 5 quando firmware_p() não encontra contrato (deployment.rs:78–80 em deployment.rs); D0 e limite 1000(hd1910.rs:257-267)
GAIN_REGS = {21: "P da EEPROM", 22: "D da EEPROM", 48: "limite de torque", 49: "Byte alto do limite de torque", 50: "P", 51: "D"}
GAINS_RECHECK_S = 3.0             # A interface verifica os ganhos a 10 quadros/s; consulta stat do arquivo no máximo a cada 3 s e relê somente se mtime mudar


def _stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def load_servo_params(path):
    """Lê servo-test-parameters.json conforme fork hd1910_test.rs:21–42: exatamente as chaves kp, kd e torque_limit (deny_unknown_fields),
    todas inteiras (serde u8/u16 não aceita 5.0 nem true), P 1–32, D 0–64 e limite 200–1000. Valores inválidos geram ValueError indicando o problema."""
    def pairs(items):
        keys = [k for k, _ in items]
        if len(set(keys)) != len(keys):
            raise ValueError("Há chaves duplicadas")
        return dict(items)
    with open(path, "rb") as f:
        obj = json.loads(f.read().decode("utf-8"), object_pairs_hook=pairs)
    if not isinstance(obj, dict) or set(obj) != {"kp", "kd", "torque_limit"}:
        raise ValueError("Deve conter exatamente três chaves: kp, kd e torque_limit")
    for k in ("kp", "kd", "torque_limit"):
        if type(obj[k]) is not int:
            raise ValueError(f"{k} deve ser inteiro, não {obj[k]!r}")
    if not 1 <= obj["kp"] <= 32:
        raise ValueError("P (kp) deve estar entre 1 e 32")
    if not 0 <= obj["kd"] <= 64:
        raise ValueError("D (kd) deve estar entre 0 e 64")
    if not 200 <= obj["torque_limit"] <= 1000:
        raise ValueError("O limite de torque (torque_limit) deve estar entre 200 e 1000")
    return obj["kp"], obj["kd"], obj["torque_limit"]


def _walk_contract(toml_path):
    """Lê deployment-contract.json no diretório do modelo indicado por [policy] walk em robotd.toml (fork deployment.rs:147–150).
    Se walk estiver ausente ou for “none”, usa o padrão conforme mode (velstand.onnx para walk, roller.onnx para roller, dentro de POLICY_DIR)."""
    import tomllib     # noqa: PLC0415 —— Python 3.11+; no robô é 3.11
    with open(toml_path, "rb") as f:
        policy = tomllib.load(f).get("policy") or {}
    walk = policy.get("walk")
    if not isinstance(walk, str) or not walk.strip() or walk.strip().lower() == "none":
        walk = POLICY_DIR + "/" + ("roller.onnx" if policy.get("mode") == "roller" else "velstand.onnx")
    elif not (walk.startswith("/") or os.path.isabs(walk)):
        walk = "/" + walk                 # caminho relativo: o diretório de trabalho do robotd no systemd é / (isabs também atende aos testes no computador)
    return walk.rsplit("/", 1)[0] + "/deployment-contract.json"


def contract_kp(path):
    """Valor P do servo no contrato do modelo de caminhada: model.actuators[0].kp_fw, inteiro de 1 a 32 (fork deployment.rs:556–568). Valor inválido gera ValueError."""
    with open(path, encoding="utf-8") as f:
        v = json.load(f)
    acts = ((v.get("model") or {}).get("actuators")) if isinstance(v, dict) else None
    if not isinstance(acts, list) or len(acts) != 1 or not isinstance(acts[0], dict):
        raise ValueError("model.actuators deve conter exatamente um item")
    p = acts[0].get("kp_fw")
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p != int(p) or not 1 <= p <= 32:
        raise ValueError(f"kp_fw deve ser um inteiro de 1 a 32, não {p!r}")
    return int(p)


class MainGains:
    """P/D/limite de torque usados pelo programa principal ao habilitar os servos (dois fluxos do fork robotd, duck-control/src/hd1910.rs:106–191):
    1. Se servo-test-parameters.json existir e for válido, usa-o (arm_with_file);
    2. Se não existir: comportamento original V167 — P vem de kp_fw do contrato do modelo de caminhada (carregado em firmware_p por robotd selftrained_profile.rs:11–27), D=0 e limite=1000;
       se não conseguir ler o contrato, P=5 (padrão de firmware_p());
    3. Se o arquivo estiver inválido ou fora do limite, o programa principal para em “aguardando barramento” e não habilita o torque (fork docs/project/replica-v167.zh-CN.md:16, 39). O Studio usa o comportamento 2 e registra um aviso.
    No computador (bancada --bench ou servos simulados), esses arquivos não existem; usa 5/0/1000. Mantém cache por mtime e não relê se o arquivo não mudar.
    get() retorna {"kp", "kd", "limit", "source" ("arquivo de parâmetros"/"padrão do programa principal"), "detail", "warn"}."""

    def __init__(self, params_path=SERVO_PARAMS, robotd_tomls=ROBOTD_TOMLS, log=None):
        self.params_path, self.robotd_tomls, self.log = params_path, tuple(robotd_tomls), log
        self._lock = threading.Lock()
        self._key, self._value, self._checked = None, None, 0.0
        self._walk = (None, None)          # (chave de robotd.toml, caminho do contrato): não reinterpreta se o TOML não mudar

    def get(self, max_age=0.0):
        with self._lock:
            now = time.monotonic()
            if self._value is not None and now - self._checked < max_age:
                return self._value
            self._checked = now
            toml = next((p for p in self.robotd_tomls if _stat(p)), None)
            tkey = (toml, _stat(toml) if toml else None)
            if self._walk[0] != tkey:
                try:
                    contract = _walk_contract(toml) if toml else None
                except Exception as e:  # noqa: BLE001
                    contract = ("bad", f"{type(e).__name__}: {e}")
                self._walk = (tkey, contract)
            contract = self._walk[1]
            key = (_stat(self.params_path), tkey, contract,
                   _stat(contract) if isinstance(contract, str) else None)
            if key != self._key or self._value is None:
                self._key, self._value = key, self._compute(toml, contract)
                if self._value["warn"] and self.log:
                    self.log(self._value["warn"], "Barramento", "warn")
            return self._value

    def _compute(self, toml, contract):
        kp, kd, limit = DEFAULT_GAINS
        warn = None
        if _stat(self.params_path):
            try:
                kp, kd, limit = load_servo_params(self.params_path)
                return {"kp": kp, "kd": kd, "limit": limit, "source": "Arquivo de parâmetros",
                        "detail": f"{self.params_path} (o programa principal grava este arquivo ao habilitar o torque)", "warn": None}
            except Exception as e:  # noqa: BLE001
                warn = (f"O arquivo de parâmetros dos servos {self.params_path} é inválido ({e}); o programa principal ficará em “aguardando barramento” e não habilitará o torque;"
                        f"O Studio aplicará os valores padrão do programa principal. Corrija ou remova este arquivo")
        etc = os.path.dirname(self.params_path)
        if toml is None and not os.path.isdir(etc):
            detail = f"Não há configuração do programa principal nesta máquina ({etc}); usando os padrões V167: P5, D0, limite de torque 1000"
        elif isinstance(contract, str):
            try:
                kp = contract_kp(contract)
                detail = f"Programa principal V167: P usa kp_fw do contrato do modelo de caminhada ({contract}), D0 e limite 1000"
            except Exception as e:  # noqa: BLE001
                detail = f"Não foi possível ler kp_fw do contrato do modelo de caminhada {contract} ({type(e).__name__}: {e}); usando o padrão do programa principal: P5, D0 e limite 1000"
        else:
            why = contract[1] if isinstance(contract, tuple) else "robotd.toml não encontrado"
            detail = f"Não foi possível ler o modelo de caminhada ({why}); usando o padrão do programa principal: P5, D0 e limite 1000"
        return {"kp": kp, "kd": 0, "limit": 1000, "source": "Padrão do programa principal", "detail": detail, "warn": warn}


def gains_bytes(g):
    """Um pacote para RAM 48..51: [byte baixo do limite, byte alto do limite, P, D] (payload do fork hd1910_test.rs:44–47)."""
    return struct.pack("<H", g["limit"]) + bytes([g["kp"], g["kd"]])


def gains_text(b):
    return "sem leitura" if b is None else f"P{b[2]} · D{b[3]} · limite de torque {b[0] | b[1] << 8}"


class ServoOps:
    def __init__(self, session, state_dir):
        self.s = session
        self.state_dir = state_dir
        self.offset_sign = None          # +1: leitura = bruto + offset; -1: leitura = bruto − offset. O manual não especifica; detecta antes da calibração
        self.speed_unit = 1.0            # quantos passos/s corresponde a uma unidade do registrador de velocidade 46 (definido por BIT2 da fase 18)
        self.max_speed_reg = 3000        # valor para “sem limite de velocidade” (quando BIT3 da fase = 1, 0 = máximo)
        self.stream_last = {}
        self.calib_lock = threading.Lock()   # impede a consulta de estado de disputar o barramento durante a calibração (a articulação pode ceder na janela com torque desligado)
        self._motion = None
        self._motion_stop = threading.Event()
        self.idle_running = False
        self._idle_thread = None
        self._sim_calib_dir = None
        # P/D/limite de torque ao habilitar (iguais aos do programa principal, MainGains); manual: valores P/D/limite gravados manualmente pelo painel de registradores {id: {endereço: leitura de retorno}}
        self.gains = MainGains(log=self.log)
        self.manual = {}
        self._gains_logged = None

    # ---- Utilitários ----

    @property
    def bus(self):
        if self.s.bus is None or self.s.state != "open":
            raise Refused("O barramento dos servos está fechado; selecione “Iniciar ajuste dos servos” primeiro.")
        return self.s.bus

    def log(self, msg, cat="Barramento", level="info", exc=False):
        self.s.log.write(msg, cat=CAT.get(cat, cat), level=level, exc=exc)

    def guard(self):
        if self.s.latched:
            raise Refused("O torque de todos os servos foi desligado. Selecione “Ligar torque de todos” ou “Reter” em um servo antes de movê-lo")

    def dirs(self):
        return self.s.directions

    def present(self):
        return [i for i in IDS if (self.s.rows.get(i) or {}).get("at")] or list(IDS)

    def calib_dir(self):
        if self.s.sim:
            if not self._sim_calib_dir or not os.path.isdir(self._sim_calib_dir):
                self._sim_calib_dir = tempfile.mkdtemp(prefix="studio-sim-calib-")
            return self._sim_calib_dir
        return os.path.join(self.state_dir, "servo-calib")

    def poses_dir(self):
        return os.path.join(self.state_dir, "servo-poses")

    def read_off(self, i):
        return feetech.sign15(self.bus.read_u16(i, 31))

    def read_pos(self, i):
        return feetech.sign15(self.bus.read_u16(i, 56))

    def write_off(self, i, v):
        return self.bus.write_u16(i, 31, enc_sm(v))

    def wait_off_change(self, i, was, ms=20):
        """Após gravar o offset, consulta se foi aplicado e aguarda no máximo ms milissegundos (normalmente leva 1–2 ms; dormir sempre 20 ms deixaria a articulação ceder pela gravidade)."""
        end = time.monotonic() + ms / 1000.0
        off = was
        while True:
            off = self.read_off(i)
            if off != was or time.monotonic() >= end:
                return off, off != was

    def read_phase(self):
        """Lê a fase 18 ao abrir o barramento para determinar a unidade de velocidade; mantém a velocidade, aceleração e alvo atuais dos servos."""
        if self.s.sim:
            return
        try:
            ph = self.bus.read_u8(self.present()[0], 18)
            self.speed_unit = 1.0 if ph & 0x04 else 50.0
            self.max_speed_reg = 0 if ph & 0x08 else int(3000 / self.speed_unit)
            self.log(f"Fase 18 = {ph} → unidade de velocidade {self.speed_unit:g} passos/s; valor sem limite: {self.max_speed_reg}")
        except Exception as e:  # noqa: BLE001
            self.log(f"Falha ao ler a fase; considera unidade de velocidade de 1 passo/s: {type(e).__name__}: {e}", "Sistema", "warn")

    def release_speed(self, ids):
        """Remove o limite de velocidade e define aceleração máxima (41=0, 46=sem limite). Grava somente esses dois registradores; **não altera o alvo 42**."""
        ids = list(ids)
        if ids:
            self.bus.sync_write(41, 1, [(i, bytes([0])) for i in ids])
            self.bus.sync_write(46, 2, [(i, struct.pack("<H", enc_sm(self.max_speed_reg))) for i in ids])

    # ---- P/D/limite de torque ao habilitar (iguais ao programa principal) ----

    def _read_gains(self, ids):
        """Lê RAM 48..51 de volta (mesmo sync_read 48×4 usado por verify em fork hd1910_test.rs:70–81); consulta individualmente os servos sem resposta (o barramento pode perder um pacote).
        Retorna {id: 4 bytes ou None}; também registra os valores lidos em session.static (a tabela mostra P/D/limite em operação)."""
        got = self.bus.sync_read(ids, 48, 4)
        out = {}
        for i in ids:
            v = got.get(i)
            data = bytes(v[1]) if v else None
            if data is None:
                try:
                    data = bytes(self.bus.read(i, 48, 4)[1])
                except feetech.BusError:
                    data = None
            out[i] = data
            if data is not None:
                st = self.s.static.setdefault(i, {})
                st["torque_limit"], st["p_run"], st["d_run"] = data[0] | data[1] << 8, data[2], data[3]
        return out

    def _log_gains(self, g):
        if self._gains_logged != g:
            self._gains_logged = g
            self.log(f"Ganhos ao habilitar torque: P{g['kp']} · D{g['kd']} · limite {g['limit']} (iguais aos do programa principal · {g['source']}: {g['detail']})")

    def _clear_manual(self, i):
        """P/D/limite de torque em operação deste servo voltaram a corresponder ao programa principal: remove da lista os valores alterados manualmente na RAM (48–51); mantém EEPROM 21/22."""
        m = self.manual.get(i)
        if m:
            for a in (47, 48, 49, 50, 51):            # 47: uma gravação de 2 bytes a partir de 47 também afeta 48
                m.pop(a, None)
            if not m:
                self.manual.pop(i, None)

    def apply_gains(self, ids):
        """Antes de habilitar o torque, grava P/D/limite dos servos desligados com os valores do programa principal (MainGains), seguindo o fluxo do fork com arquivo de parâmetros
        (duck-control/src/hd1910.rs:159–191 arm_with_file, hd1910_test.rs:44–81): um pacote de 4 bytes na RAM 48..51
        [byte baixo do limite, byte alto do limite, P, D], grava com sync_write e valida com sync_read 48×4. Não altera EEPROM 21/22 nem o sinalizador de trava 55
        (não controlado pela RAM; o fork também não grava), nem 52 (I), 41 (aceleração) ou 46 (velocidade).
        Diferença em relação ao fork: grava somente os servos cuja leitura diverge do valor desejado (o fork grava sempre os 15) e tenta novamente os divergentes.
        Retorna {id: motivo} para servos sem leitura ou com retorno divergente; o chamador não habilita o torque neles."""
        ids = [int(i) for i in ids]
        if not ids:
            return {}
        g = self.gains.get()
        self._log_gains(g)
        want = gains_bytes(g)
        before, wrote, cur = {}, [], {}
        try:
            cur = self._read_gains(ids)
            before = dict(cur)
            todo = [i for i in ids if cur[i] != want]
            for _ in range(2):
                if not todo:
                    break
                self.bus.sync_write(48, 4, [(i, want) for i in todo])
                wrote += [i for i in todo if i not in wrote]
                cur.update(self._read_gains(todo))
                todo = [i for i in todo if cur[i] != want]
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            bad = {i: f"Erro no barramento ao gravar P/D/limite({err})" for i in ids if cur.get(i) != want}
            self.log(f"Falha ao gravar P/D/limite antes de habilitar torque: {err}; estes servos permanecerão desligados: {sorted(bad)}", "Barramento", "error", exc=True)
            return bad
        bad = {}
        for i in ids:
            if cur[i] == want:
                self._clear_manual(i)
                continue
            if cur[i] is None:
                bad[i] = "Não foi possível ler P/D/limite (sem resposta dos registradores 48–51)"
            else:
                c = cur[i]
                diff = [f"{a} ({name}): gravado {w}, retornou {r}" for a, name, w, r in (
                    (48, "limite de torque", g["limit"], c[0] | c[1] << 8), (50, "P", g["kp"], c[2]), (51, "D", g["kd"], c[3])) if w != r]
                bad[i] = "Falha ao gravar P/D/limite: registradores " + ", ".join(diff)
            self.log(f"#{i} Gravação de P/D/limite antes de habilitar (P{g['kp']} · D{g['kd']} · torque {g['limit']}): {bad[i]}; torque não habilitado neste servo", "Barramento", "error")
        ok = [i for i in wrote if i not in bad]
        if ok:
            self.log(f"P/D/limite gravados antes de habilitar torque: P{g['kp']} · D{g['kd']} · limite {g['limit']} ({g['source']}): "
                     + " ".join(f"#{i}(antes: {gains_text(before.get(i))})" for i in ok))
        return bad

    def check_gains(self, ids):
        """Servos com torque já ativo: somente confere, não grava (no fork, arm também só confere quando o torque está ligado: hd1910.rs:116–140, 169–179;
        alterar P com torque ativo pode fazer a articulação sob carga ceder). Retorna {id: descrição} para os servos diferentes do programa principal (continuam sendo considerados energizados e aparecem em amarelo no cabeçalho)."""
        ids = [int(i) for i in ids]
        if not ids:
            return {}
        want = gains_bytes(self.gains.get())
        try:
            cur = self._read_gains(ids)
        except Exception as e:  # noqa: BLE001
            self.log(f"Falha ao conferir P/D/limite dos servos energizados: {type(e).__name__}: {e}", "Barramento", "warn")
            return {}
        differ = {}
        for i in ids:
            if cur[i] == want:
                self._clear_manual(i)
            elif cur[i] is not None:
                differ[i] = (f"Torque já ativo; ganhos {gains_text(cur[i])} diferem dos do programa principal ({gains_text(want)}); nenhum valor foi alterado"
                             "(alterar P com torque ativo pode fazer a articulação sob carga ceder); para alterar, solte e depois retenha")
        if differ:
            self.log("Os ganhos dos servos energizados diferem dos do programa principal; não foram alterados: " + " ".join(f"#{i} {gains_text(cur[i])}" for i in differ)
                     + f"(programa principal: {gains_text(want)}); para alterar, solte e depois retenha", "Barramento", "warn")
        return differ

    def _gains_then_torque(self, i, trail, label="Ligar torque"):
        """Ao restaurar o torque deste servo durante calibração/desfazer, grava primeiro P/D/limite do programa principal (apply_gains); se falhar, não restaura. Retorna se foi restaurado."""
        bad = self.apply_gains([i])
        if bad:
            trail.append(f"✗{bad[i]}; torque não restaurado")
            return False
        trail.append(label + _ack(self.bus.write_u8(i, 40, 1)))
        return True

    def gains_view(self, rows=None):
        """Usado no cabeçalho “Ganhos: P5 · D0 · limite 1000 (iguais ao programa principal · origem)”. Também adiciona aos rows (linhas do snapshot) os valores P/D/limite em operação
        P/D/limite (RAM 50/51/48; lidos ao abrir o barramento, antes de habilitar torque e após gravar registradores) e gains_ok (se correspondem aos do programa principal; None se não for possível ler).
        Chamado no event loop: não acessa o barramento e consulta stat do arquivo no máximo a cada GAINS_RECHECK_S segundos."""
        g = self.gains.get(max_age=GAINS_RECHECK_S)
        want = (g["kp"], g["kd"], g["limit"])
        differ_on = []
        for r in rows or []:
            st = self.s.static.get(r["id"]) or {}
            run = (st.get("p_run"), st.get("d_run"), st.get("torque_limit"))
            r["p_run"], r["d_run"], r["limit"] = run
            r["gains_ok"] = None if None in run else run == want
            if r["gains_ok"] is False and r.get("torque") == 1:
                differ_on.append(r["id"])
        manual = [{"id": i, "addr": a, "value": v, "what": GAIN_REGS.get(a, "")}
                  for i, m in sorted(list(self.manual.items())) for a, v in sorted(list(m.items()))]
        return {"kp": g["kp"], "kd": g["kd"], "limit": g["limit"], "source": g["source"], "detail": g["detail"],
                "warn": g["warn"], "manual": manual, "differ_on": differ_on}

    # ---- Torque ----

    def torque_on_aligned(self, ids):
        """Antes de ligar o torque, alinha o alvo (42) à leitura atual: se alguém moveu o servo à mão ou executou uma postura/calibração com o torque desligado, o alvo ainda pode ser antigo,
        e o servo pode avançar bruscamente ao energizar. Lê o torque → grava P/D/limite nos servos desligados (iguais ao programa principal, apply_gains) → lê a posição → grava alvo = posição
        → relê 42 para conferir → liga o torque (mesma ordem do fork: arm grava ganhos → pré-carrega a posição lida → liga o torque, feetech.rs:1836–1873).
        Servos que já estão ligados mantêm alvo e P/D/limite (somente conferidos). Não liga os servos se falhar a gravação dos ganhos, a leitura da posição ou a gravação do alvo."""
        self.guard()
        bus = self.bus
        tq = bus.sync_read(ids, 40, 1)
        already = [i for i in ids if tq.get(i) and tq[i][1][0] == 1]
        need = [i for i in ids if i not in already]
        aligned, bad = {}, {}
        # Pedido de 19/10: ganhos ao habilitar torque iguais aos do programa principal (não usar P32/D40 de fábrica da EEPROM). Não liga os servos cujos ganhos não puder gravar
        bad.update({i: w + " ; torque não ligado" for i, w in self.apply_gains(need).items()})
        differ = self.check_gains(already)
        need = [i for i in need if i not in bad]
        st = bus.states(need) if need else {}
        for i in need:
            if not st.get(i):
                bad[i] = "Não foi possível ler a posição; torque não ligado (poderia avançar até um alvo antigo)"
                continue
            p = st[i]["pos"]
            got = None
            try:
                for _ in range(2):
                    bus.write_u16(i, 42, enc_sm(p))
                    got = feetech.sign15(bus.read_u16(i, 42))
                    if got == p:
                        aligned[i] = p
                        break
                else:
                    bad[i] = f"Alvo gravado {p}, leitura de retorno {got}; torque não ligado"
            except Exception as e:  # noqa: BLE001
                bad[i] = f"Erro ao gravar o alvo ({type(e).__name__}: {e}); torque não ligado"
        on = already + [i for i in need if i in aligned]
        if on:
            self.guard()                                   # Alguém desligou o torque durante o alinhamento; não liga
            bus.sync_write(40, 1, [(i, bytes([1])) for i in on])
        self.s._read_torque()
        self.log(f"Torque ligado → {on}" + (f" ; alvo alinhado à posição atual antes de ligar: " + " ".join(f"#{i}→{p}" for i, p in aligned.items()) if aligned else "")
                 + (f"; não ligado " + " ".join(f"#{i}({w})" for i, w in bad.items()) if bad else ""), "Movimento",
                 "warn" if bad else "info")
        g = self.gains.get(max_age=GAINS_RECHECK_S)
        return {"on": on, "bad": {str(i): w for i, w in bad.items()}, "differ": {str(i): w for i, w in differ.items()},
                "gains": {k: g[k] for k in ("kp", "kd", "limit", "source")}}

    def torque_off(self, ids):
        self.bus.sync_write(40, 1, [(i, bytes([0])) for i in ids])
        self.s._read_torque()
        self.log(f"Torque desligado → {ids}", "Movimento")
        return {"off": ids}

    # ---- Movimento ----

    def goal(self, sid, pos):
        self.guard()
        pos = max(0, min(4095, int(pos)))
        self.bus.write_u16(int(sid), 42, enc_sm(pos))
        return {"id": sid, "pos": pos}

    def goals_verify(self, want):
        """Grava o alvo e confere pela leitura de retorno; reenvia os que não responderem, até quatro tentativas."""
        want = {int(i): max(0, min(4095, int(p))) for i, p in want.items()}
        attempt = 0
        for attempt in range(4):
            self.bus.sync_write(42, 2, [(i, struct.pack("<H", p)) for i, p in want.items()])
            time.sleep(0.02)
            st = self.bus.states(list(want))
            want = {i: p for i, p in want.items() if not st.get(i) or (st[i]["goal"] & 0xFFFF) != p}
            if not want:
                break
        if want:
            self.log(f"Leitura de retorno do alvo: não foi possível gravar o alvo dos {len(want)} servos após quatro tentativas: {sorted(want)}", "Movimento", "warn")
        return {"missing": sorted(want), "attempts": attempt + 1}

    def move(self, goals, seconds=2.0, mode="profile", acc=30):
        """Move da posição atual até goals ({id: leitura}). profile = suave (o servo executa uma curva trapezoidal); stream = contínuo (interpolação a 20 Hz aqui).
        Executa em uma thread em segundo plano e retorna imediatamente; “Parar” ou desligar o torque interrompe o movimento."""
        self.guard()
        goals = {int(i): max(0, min(4095, int(p))) for i, p in goals.items() if int(i) in IDS}
        if not goals:
            raise Refused("Nenhum servo selecionado para mover")
        self.stop(quiet=True)
        self._motion_stop.clear()
        t = threading.Thread(target=self._run_move, args=(goals, float(seconds), mode, int(acc)), name="servo-move", daemon=True)
        self._motion = t
        t.start()
        return {"started": len(goals), "seconds": seconds, "mode": mode}

    def _run_move(self, goals, seconds, mode, acc):
        try:
            if mode == "profile" and seconds > 0:
                self._profile(goals, seconds, acc)
                if self._motion_stop.wait(seconds + 0.4):
                    return
            else:
                st = self.bus.states(list(goals))
                start = {i: (st[i]["pos"] if st.get(i) else p) for i, p in goals.items()}
                t0 = time.monotonic()
                while True:
                    if self.s.halted:
                        return
                    tt = 1.0 if seconds <= 0 else min(1.0, (time.monotonic() - t0) / seconds)
                    g = {i: round(start[i] + (p - start[i]) * tt) for i, p in goals.items()}
                    if tt >= 1:
                        break
                    self._stream(g, 0.05)
                    if self._motion_stop.wait(0.05):
                        return
            if not self.s.halted:
                self.goals_verify(goals)
                self.release_speed(list(goals))
                for i in goals:
                    self.stream_last.pop(i, None)
        except Refused:
            pass
        except Exception as e:  # noqa: BLE001
            self.log(f"Erro de movimento: {type(e).__name__}: {e}", "Movimento", "error", exc=True)

    def _profile(self, want, seconds, acc):
        """Grava 41..47 em um pacote: aceleração (1), alvo (2), duração (2)=0 e velocidade (2); o servo executa sua própria curva trapezoidal."""
        self.guard()
        acc = max(1, min(254, acc))
        st = self.bus.states(list(want))
        items = []
        for i, p in want.items():
            cur = st[i]["pos"] if st.get(i) else p
            sps = abs(p - cur) / max(0.2, seconds)
            reg = max(1, min(32767, int(round(sps / self.speed_unit)))) if sps > 0 else 1
            items.append((i, bytes([acc]) + struct.pack("<H", enc_sm(p)) + struct.pack("<H", 0) + struct.pack("<H", reg)))
        self.bus.sync_write(41, 7, items)
        for i in want:
            self.stream_last.pop(i, None)

    def _stream(self, want, dt):
        """Fluxo contínuo: define o alvo a cada quadro e ajusta a velocidade máxima para chegar exatamente em dt, com aceleração máxima."""
        self.guard()
        fresh = [i for i in want if i not in self.stream_last]
        if fresh:
            st = self.bus.states(fresh)
            for i in fresh:
                self.stream_last[i] = st[i]["pos"] if st.get(i) else want[i]
        items = []
        for i, p in want.items():
            sps = abs(p - self.stream_last[i]) / dt * 1.2
            reg = max(3, min(32767, int(round(sps / self.speed_unit))))
            items.append((i, bytes([0]) + struct.pack("<H", enc_sm(p)) + struct.pack("<H", 0) + struct.pack("<H", reg)))
            self.stream_last[i] = p
        self.bus.sync_write(41, 7, items)

    def stop(self, quiet=False):
        """Parar: interrompe transições/animações e define o alvo como a posição atual (no modo suave, o servo já recebeu o destino e está se movendo sozinho; assim para onde está)."""
        self._motion_stop.set()
        self.idle_running = False
        if self._motion and self._motion.is_alive():
            self._motion.join(timeout=0.5)
        if quiet:
            return {}
        if self.s.state == "open":
            st = self.bus.states(self.present())
            g = {i: s["pos"] for i, s in st.items() if s}
            if g and not self.s.halted:
                self.goals_verify(g)
            self.log("Movimento parado; alvo definido como a posição atual", "Movimento")
        return {}

    def official_goals(self, key, for_send=True):
        if key not in OFFICIAL:
            raise Refused(f"Postura oficial desconhecida: {key}")
        label, rad = OFFICIAL[key]
        rad = dict(rad)
        if key == "fold" and for_send:
            rad[23], rad[13] = FOLD_KNEE_SEND, -FOLD_KNEE_SEND
        d = self.dirs()
        return label, {i: int(round(2048 + a * 4096 / (2 * math.pi) * d.get(i, -1))) for i, a in rad.items()}

    def go_official(self, key, seconds, mode, acc):
        label, goals = self.official_goals(key)
        self.log(f"Indo para a postura oficial “{label}” ({seconds:g} s, {'suave' if mode == 'profile' else 'contínuo'})", "Movimento")
        return self.move(goals, seconds, mode, acc)

    # ---- Animação ----

    def idle(self, on):
        if not on:
            self.idle_running = False
            return {"idle": False}
        self.guard()
        head = [i for i in (30, 31, 32, 33, 34) if i in self.present()]
        if len(head) < 3:
            raise Refused("Os servos da cabeça estão offline")
        self.torque_on_aligned(head)
        st = self.bus.states(head)
        center = {i: st[i]["pos"] for i in head if st.get(i)}
        self.stop(quiet=True)
        self.idle_running = True
        self._idle_thread = threading.Thread(target=self._run_idle, args=(center,), name="servo-idle", daemon=True)
        self._idle_thread.start()
        self.log(f"Animação iniciada; centro {center}", "Movimento")
        return {"idle": True}

    def _run_idle(self, center):
        d = self.dirs()

        def head(delta, sec):
            goals = {i: max(0, min(4095, round(center[i] + deg * DEG * d.get(i, -1)))) for i, deg in delta.items() if i in center}
            if goals:
                self._profile(goals, sec, 35)
            time.sleep(sec + 0.06)

        bag = [g for w, g in GESTURES for _ in range(w)]
        last = None
        try:
            while self.idle_running and not self.s.halted:
                g = random.choice(bag)
                if g is last:
                    g = random.choice(bag)
                last = g
                for delta, sec in g(random.choice([-1, 1])):
                    if not self.idle_running or self.s.halted:
                        break
                    if delta:
                        head(delta, sec)
                    else:
                        time.sleep(sec)
                if self.idle_running:
                    time.sleep(random.uniform(0.3, 1.5))
            if not self.s.halted and self.s.state == "open":
                head({i: 0 for i in center}, 0.7)
                self.release_speed(list(center))
            self.log("Animação concluída; cabeça voltou ao centro", "Movimento")
        except Refused:
            pass
        except Exception as e:  # noqa: BLE001
            self.log(f"Erro na animação: {type(e).__name__}: {e}", "Movimento", "error", exc=True)
        finally:
            self.idle_running = False

    # ---- Calibração central ----

    def backup_calibration(self, ids):
        rows = {}
        for i in ids:
            try:
                ver = self.bus.read(i, 0, 5)[1]
                rows[str(i)] = {"offset": self.bus.read_u16(i, 31), "pos": self.read_pos(i),
                                "torque": self.bus.read_u8(i, 40), "lock": self.bus.read_u8(i, 55),
                                "firmware": f"{ver[0]}.{ver[1]}"}
            except Exception as e:  # noqa: BLE001
                rows[str(i)] = {"error": f"{type(e).__name__}: {e}"}
                self.log(f"#{i} Não foi possível ler durante o backup: {type(e).__name__}: {e}", "Calibração", "warn")
        d = self.calib_dir()
        os.makedirs(d, exist_ok=True)
        now = time.time()
        fn = f"eeprom-{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}{int(now * 1000) % 1000:03d}.json"
        _save_json(os.path.join(d, fn), {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "servos": rows})
        return fn, rows

    def probe_offset_sign(self, i):
        """Detecta o sinal do offset: adiciona +1 e observa a direção da leitura (move apenas um passo, 0,09°, fora da janela de calibração)."""
        if self.offset_sign is not None:
            return self.offset_sign
        try:
            o0, r0 = self.read_off(i), self.read_pos(i)
            if abs(o0 + 1) > OFFSET_LIMIT:
                return None
            self.bus.unlock(i)
            self.write_off(i, o0 + 1)
            self.wait_off_change(i, o0)
            r1 = self.read_pos(i)
            self.write_off(i, o0)
            self.wait_off_change(i, o0 + 1)
            self.bus.lock(i)
            if r1 == r0:
                self.log(f"Teste do sinal do offset: #{i} não mudou a leitura com offset +1 ({r0}); sinal desconhecido, tenta ambos os sinais no modo de contingência", "Calibração", "warn")
                return None
            self.offset_sign = 1 if r1 > r0 else -1
            self.log(f"Teste do sinal do offset: #{i}, offset +1 → leitura {r0}→{r1}; leitura = bruto {'+' if self.offset_sign > 0 else '−'} offset", "Calibração")
            return self.offset_sign
        except Exception as e:  # noqa: BLE001
            self.log(f"Falha ao detectar o sinal do offset: {type(e).__name__}: {e}", "Calibração", "warn")
            return None

    def calibrate_by_offset(self, i, target, trail):
        """Contingência: se o servo não aceitar nem 0x0B, calcula o offset e grava no registrador 31. Se falhar, restaura o offset original."""
        o0, r0 = self.read_off(i), self.read_pos(i)
        signs = [self.offset_sign] if self.offset_sign else [1, -1]
        ok, pos, off = False, r0, o0
        try:
            for sign in signs:
                cand = o0 + sign * (target - r0)
                if abs(cand) > OFFSET_LIMIT:
                    trail.append(f"offset {cand:+d} fora da faixa; ignorado")
                    continue
                self.write_off(i, cand)
                off, _ = self.wait_off_change(i, off)
                pos = self.read_pos(i)
                trail.append(f"offset gravado {cand} → leitura {pos}")
                if abs(pos - target) <= CALIB_TOLERANCE:
                    ok = True
                    return True, pos, off
            return False, pos, off
        finally:
            if not ok and off != o0:
                try:
                    self.write_off(i, o0)
                    off, _ = self.wait_off_change(i, off)
                    trail.append(f"Falhou; offset restaurado para {o0}")
                except Exception as e:  # noqa: BLE001
                    self.log(f"#{i} Também falhou ao restaurar o offset após erro na contingência: {type(e).__name__}: {e}", "Calibração", "error")

    def calibrate_one(self, i, before, target=2048):
        """Calibração de posição de um servo: define a leitura da posição atual como target (2048 = zero oficial).
        A validação não usa a resposta, mas verifica se o registrador de offset mudou (o HD-1910 pode retornar “sucesso” para comandos que não reconhece).
        A articulação cede pela gravidade com o torque desligado: queda d = pre − target + sinal × Δoffset; calcula e compensa.
        Ao finalizar, sempre grava a leitura atual como alvo (não target, para não puxar a articulação mesmo se a estimativa estiver errada), restaura o torque, trava e restaura a velocidade."""
        bus = self.bus
        was_on = before.get("torque") == 1
        old_off = before.get("offset")
        trail, step, ok, pre, pos, off, why = [], "Limite de velocidade", False, None, None, None, ""
        method, droop = "0x0B", 0
        gains_bad = False             # falha ao gravar P/D/limite antes de restaurar o torque; também não restaura ao finalizar
        try:
            bus.write_u8(i, 41, 10)                                    # se a estimativa estiver errada, a articulação ainda se moverá lentamente
            bus.write_u16(i, 46, enc_sm(200))
            step = "Desbloquear"
            trail.append("Desbloquear" + _ack(bus.unlock(i)))
            step = "Ler posição atual"
            pre = self.read_pos(i)
            o_before = self.read_off(i)
            if was_on:
                step = "Desligar torque"
                bus.write_u8(i, 40, 0)
                if bus.read_u8(i, 40) != 0:                           # se este pacote se perder, 0x0B será executado com o torque ligado
                    bus.write_u8(i, 40, 0)
                    if bus.read_u8(i, 40) != 0:
                        raise feetech.BusError("Não foi possível desligar o torque (leitura de retorno diferente de 0); a operação foi interrompida")
                trail.append("Torque desligado ✓")
            # Lê novamente após desligar o torque e antes de 0x0B: se o sinal do offset não foi detectado (não dá para detectar com torque ligado: o servo força o alvo e a leitura não muda),
            # compara a leitura atual e a leitura após 0x0B com a mudança do offset para determinar o sinal (em 19/10, corrigido três vezes no servo nº 24 do segundo robô)
            post = self.read_pos(i) if was_on else pre
            step = "Calibração de posição 0x0B"
            trail.append(f"0x0B→{target}" + _ack(bus.calibrate_to(i, target)))
            step = "Confirmação da mudança de offset"
            off, changed = self.wait_off_change(i, o_before)
            pos = self.read_pos(i)
            ok = changed or abs(pre - target) <= CALIB_TOLERANCE
            if not ok:
                step = "Contingência: gravar offset no registrador 31"
                trail.append("0x0B não alterou o offset; usando gravação direta")
                ok, pos, off = self.calibrate_by_offset(i, target, trail)
                method = "Gravar offset 31"
            if ok:
                step = "Calcula e compensa a queda"
                sign = self.offset_sign
                if sign is None:
                    sign = infer_offset_sign(post, pos, off - o_before)
                    if sign is not None:
                        self.offset_sign = sign
                        trail.append(f"Sinal do offset inferido nesta calibração: leitura = bruto {'+' if sign > 0 else '−'} offset")
                if sign is None:
                    # Se o sinal for desconhecido, não compensa; um palpite errado dobraria o erro (antes assumia +1, mas no HD-1910 é −)
                    droop = 0
                    if abs(pre - pos) > DROOP_TOLERANCE:
                        trail.append("Não foi possível inferir o sinal do offset; queda não compensada (o zero após a calibração pode diferir alguns passos: desligue o torque, posicione à mão e calibre novamente)")
                else:
                    droop = pre - target + sign * (off - o_before)
                if abs(droop) > DROOP_TOLERANCE and abs(off - sign * droop) <= OFFSET_LIMIT:
                    self.write_off(i, off - sign * droop)
                    off, _ = self.wait_off_change(i, off)
                    pos = self.read_pos(i)
                    trail.append(f"Cedeu {droop:+d} passos com o torque desligado; ajuste adicional do offset: {-sign * droop:+d}")
                elif abs(droop) > DROOP_TOLERANCE:
                    trail.append(f"Cedeu {droop:+d} passos, mas a compensação excederia a faixa; não foi aplicada")
            step = "Gravar alvo"
            trail.append(f"Alvo {pos}" + _ack(bus.write_u16(i, 42, enc_sm(pos))))
            if was_on and not self.s.halted:
                step = "Gravar P/D/limite e ligar torque"                          # Antes de habilitar, grava os ganhos P/D/limite do programa principal; se falhar, não liga (pedido de 19/10)
                gains_bad = not self._gains_then_torque(i, trail)
            if not ok:
                why = f"Nem 0x0B nem a gravação direta alteraram o offset (continua {fmt_off(o_before)}); leitura {pos} difere de {target}"
        except Exception as e:  # noqa: BLE001
            ok = False
            why = f"Falha na etapa “{step}”: {type(e).__name__}: {e}"
            trail.append("✗" + why)
            self.log(f"#{i} {why}", "Calibração", "error")
        finally:
            try:
                p = self.read_pos(i)
                bus.write_u16(i, 42, enc_sm(p))
                # Com a trava de desligamento ativa, não restaura o torque (servo-web restauraria aqui; revisão S4: poderia religar após uma parada de emergência)
                if was_on and not self.s.halted and not gains_bad and bus.read_u8(i, 40) != 1:
                    self._gains_then_torque(i, trail, "Torque restaurado")      # Se não conseguir gravar P/D/limite, não restaura o torque
            except Exception as e:  # noqa: BLE001
                trail.append(f"✗Falha ao finalizar (gravar alvo/restaurar torque): {type(e).__name__}: {e}")
                self.log(f"#{i} Falha ao finalizar; este servo pode estar sem torque e o registrador de alvo pode apontar para a posição antiga: {type(e).__name__}: {e}", "Calibração", "error")
            try:
                bus.lock(i)
                locked = bus.read_u8(i, 55)
                trail.append("Travado ✓" if locked == 1 else f"sinalizador de trava retornou {locked} após bloquear")
            except Exception as e:  # noqa: BLE001
                trail.append(f"✗Falha ao travar: {type(e).__name__}: {e}")
                self.log(f"#{i} Falha ao travar; o servo pode continuar desbloqueado: {type(e).__name__}: {e}", "Calibração", "error")
            try:
                self.release_speed([i])
            except Exception:  # noqa: BLE001
                pass
        gap = "" if pre is None else f", diferença de {(target - pre) * 360 / 4096:+.1f}°"
        head = (f"#{i} leitura {pre if pre is not None else '?'}→{pos if pos is not None else '?'} (alvo {target}{gap}, {method})"
                f" offset {fmt_off(old_off)}→{fmt_off(off)}" + (f" queda de {droop:+d} passos" if droop else "")
                + f" torque originalmente {'ligado' if was_on else 'desligado'}")
        self.log(head + " · " + " ".join(trail) + ("" if ok else f" · Falha: {why}"), "Calibração", "info" if ok else "warn")
        return {"ok": ok, "pre": pre, "pos": pos, "target": target, "droop": droop, "method": method, "why": why}

    def calib_plan(self, ids):
        """Prévia antes da calibração: leitura atual de cada servo, valor a gravar (zero oficial 2048) e diferença em graus. Somente leitura."""
        st = self.bus.states(ids)
        rows = []
        for i in ids:
            s = st.get(i)
            pos = s["pos"] if s else None
            rows.append({"id": i, "joint": JOINT.get(i), "pos": pos, "target": 2048,
                         "diff_deg": None if pos is None else round((2048 - pos) * 360 / 4096, 1)})
        return {"name": "Zero oficial 2048", "rows": rows, "big_deg": CALIB_BIG_DEG, "sim": self.s.sim}

    def calibrate(self, ids):
        """Calibra a posição atual dos servos selecionados para 2048 (zero oficial), um por vez, desligando o torque por apenas alguns milissegundos.
        Os servos calibrados com sucesso são alinhados e energizados para manter a posição (pedido do usuário). As consultas de estado não disputam o barramento durante a operação."""
        self.guard()
        ids = [i for i in ids if i in IDS]
        if not ids:
            raise Refused("Nenhum servo selecionado para calibrar")
        self.stop(quiet=True)
        with self.calib_lock:
            res = self._calibrate(ids)
        if res["ok"] and not self.s.halted:
            res["hold"] = self.torque_on_aligned(res["ok"])
        self.s.refresh_static(ids)
        return res

    def _calibrate(self, ids):
        sim = self.s.sim
        self.log(f"Iniciando calibração de {len(ids)} servos para o zero oficial 2048: {ids}" + ("(simulação: altera somente os servos virtuais, salva o backup em diretório temporário e não move as posturas salvas)" if sim else ""), "Calibração")
        fn, before = self.backup_calibration(ids)
        self.log(f"Offsets, leituras, torque e sinalizador de trava originais salvos em {self.calib_dir()}{os.sep}{fn}", "Calibração")
        self.probe_offset_sign(next((i for i in ids if "offset" in before.get(str(i), {})), ids[0]))
        ok, bad, deltas, big = [], {}, {}, {}
        for i in ids:
            if self.s.latched:
                bad[i] = "A trava de torque está ativa; os servos restantes não foram calibrados"
                continue
            if self.s.closing:
                bad[i] = "Devolução ao programa principal em andamento; os servos restantes não foram calibrados"
                continue
            b = before.get(str(i), {})
            if "offset" not in b:
                bad[i] = "Sem leitura durante o backup; servo não alterado"
                continue
            r = self.calibrate_one(i, b, 2048)
            if r["ok"]:
                ok.append(i)
                if not sim:
                    try:
                        from .commit import record_centered
                        record_centered(self.state_dir, [i], self.s.by)
                    except OSError as e:
                        self.log(f"#{i} Zero calibrado, mas não foi registrado na lista do Studio: {e}", "Calibração", "warn")
                deltas[str(i)] = r["target"] - r["pre"]
                if abs(deltas[str(i)]) * 360 / 4096 > CALIB_BIG_DEG:
                    big[i] = deltas[str(i)] * 360 / 4096
            else:
                bad[i] = r["why"]
        # Grava primeiro a lista de posturas que serão movidas; se houver falha durante a operação, elas poderão ser recuperadas
        bp = os.path.join(self.calib_dir(), fn)
        rec = _load_json(bp)
        plan = [p["file"] for p in self.list_poses() if p.get("goals")] if not sim else []
        rec.update({"ref": None, "targets": {str(i): 2048 for i in ids}, "deltas": deltas, "shifted": plan,
                    "bad": {str(k): v for k, v in bad.items()}, "sim": sim})
        _save_json(bp, rec)
        moved = self.shift_saved_poses(deltas, only=set(plan)) if not sim else []
        if moved != plan:
            rec["shifted"] = moved
            _save_json(bp, rec)
        if moved:
            self.log(f"Posturas salvas ajustadas ao novo zero: {moved}", "Posturas")
        if big:
            self.log(f"A posição atual destes servos difere mais de {CALIB_BIG_DEG}° do zero: " + " ".join(f"#{i} {d:+.1f}°" for i, d in big.items())
                     + ".A meia-volta ao instalar o braço do servo é aceitável; se a orientação ± estiver invertida, o zero calibrado estará errado. Habilite o torque e mova um pouco pelo controle,"
                     "confira se a articulação na visualização 3D gira como a peça real. Se não, desfaça, ajuste ± e calibre novamente", "Calibração", "warn")
        self.log(f"Calibração concluída: {len(ok)} servos com sucesso {ok}" + (f"；{len(bad)} falhas: {sorted(bad)}" if bad else "")
                 + f"；backup {fn}", "Calibração", "warn" if bad or big else "info")
        return {"ok": ok, "bad": {str(k): v for k, v in bad.items()}, "backup": fn,
                "big": {str(k): round(v, 1) for k, v in big.items()}}

    def undo(self):
        """Restaura os offsets do backup mais recente (desliga torque → desbloqueia → grava 31 → trava), define o alvo como a leitura atual e mantém o estado de torque original."""
        self.guard()
        self.stop(quiet=True)
        with self.calib_lock:
            res = self._undo()
        self.s.refresh_static([int(k) for k in res.get("ok", [])])
        return res

    def _undo(self):
        bus = self.bus
        d = self.calib_dir()
        files = sorted(f for f in os.listdir(d) if f.startswith("eeprom-")) if os.path.isdir(d) else []
        if not files:
            raise Refused("Não há calibração central para desfazer" + ("(no modo de simulação, desfaz somente calibrações simuladas)" if self.s.sim else ""))
        fn = files[-1]
        rec = _load_json(os.path.join(d, fn))
        self.log(f"Desfazendo: restaurando os offsets de {fn} ({rec.get('time', '?')})", "Calibração")
        ok, bad = [], {}
        for k, row in rec["servos"].items():
            i = int(k)
            if "offset" not in row:
                self.log(f"#{i} Backup sem offset ({row.get('error', '?')}); ignorado", "Calibração", "warn")
                continue
            trail, step, on = [], "Ler estado atual", False
            gains_bad = False         # falha ao gravar P/D/limite antes de restaurar o torque; também não restaura ao finalizar
            try:
                on = bus.read_u8(i, 40) == 1
                off0, p0 = bus.read_u16(i, 31), self.read_pos(i)
                if on:
                    step = "Desligar torque"
                    bus.write_u8(i, 40, 0)
                    if bus.read_u8(i, 40) != 0:
                        bus.write_u8(i, 40, 0)
                        if bus.read_u8(i, 40) != 0:
                            raise feetech.BusError("Não foi possível desligar o torque (leitura de retorno diferente de 0); gravação do offset cancelada")
                    trail.append("Torque desligado ✓")
                step = "Desbloquear"
                trail.append("Desbloquear" + _ack(bus.unlock(i)))
                step = "Gravar offset"
                trail.append(f"Offset gravado: {fmt_off(row['offset'])}" + _ack(bus.write_u16(i, 31, row["offset"])))
                step = "Leitura de retorno"
                self.wait_off_change(i, feetech.sign15(off0))
                off1, p1 = bus.read_u16(i, 31), self.read_pos(i)
                step = "Gravar alvo"
                trail.append(f"Alvo {p1}" + _ack(bus.write_u16(i, 42, enc_sm(p1))))
                if on and not self.s.halted:
                    step = "Gravar P/D/limite e ligar torque"                      # Antes de habilitar, grava os ganhos P/D/limite do programa principal; se falhar, não liga (pedido de 19/10)
                    gains_bad = not self._gains_then_torque(i, trail)
                good = off1 == row["offset"]
                if good:
                    ok.append(i)
                else:
                    bad[i] = f"Offset gravado {row['offset']}, retornou {off1}"
                self.log(f"#{i} offset {fmt_off(off0)}→{fmt_off(off1)} (backup: {fmt_off(row['offset'])}), leitura {p0}→{p1} · "
                         + " ".join(trail), "Calibração", "info" if good else "warn")
            except Exception as e:  # noqa: BLE001
                bad[i] = f"Falha na etapa “{step}”: {type(e).__name__}: {e}"
                self.log(f"#{i} Desfazer: {bad[i]}", "Calibração", "error")
            finally:
                try:
                    p = self.read_pos(i)
                    bus.write_u16(i, 42, enc_sm(p))
                    if on and not self.s.halted and not gains_bad and bus.read_u8(i, 40) != 1:
                        self._gains_then_torque(i, trail, "Torque restaurado")  # Se não conseguir gravar P/D/limite, não restaura o torque
                except Exception as e:  # noqa: BLE001
                    self.log(f"#{i} Falha ao finalizar o desfazer; este servo pode estar sem torque: {type(e).__name__}: {e}", "Calibração", "error")
                try:
                    bus.lock(i)
                except Exception as e:  # noqa: BLE001
                    self.log(f"#{i} Falha ao travar: {type(e).__name__}: {e}", "Calibração", "error")
        if not rec.get("sim") and "shifted" in rec:
            later, t0 = [], rec.get("time", "")
            for p in self.list_poses():
                if p["file"] not in rec["shifted"] and p.get("goals") and (p.get("time") or "") >= t0[:16]:
                    later.append(p["file"])
            moved = self.shift_saved_poses(rec.get("deltas", {}), sign=-1, only=set(rec["shifted"]) | set(later))
            if moved:
                self.log(f"Posturas salvas recalculadas para o zero original: {moved}", "Posturas")
        if ok and not rec.get("sim"):
            try:
                from .commit import forget_centered
                gone = forget_centered(self.state_dir, ok)
                if gone:
                    self.log(f"Os {len(gone)} servos desfeitos também foram removidos do registro “calibração central concluída”: {gone}", "Calibração")
            except OSError as e:
                self.log(f"Não foi possível remover os servos desfeitos do registro de calibração central do Studio: {type(e).__name__}: {e}", "Calibração", "warn")
        os.rename(os.path.join(d, fn), os.path.join(d, "undone-" + fn))
        self.log(f"Desfazer concluído ({fn} renomeado para undone-{fn}): offsets restaurados em {len(ok)} servos" + (f"; falhas {sorted(bad)}" if bad else ""),
                 "Calibração", "warn" if bad else "info")
        return {"ok": ok, "bad": {str(k): v for k, v in bad.items()}, "backup": fn}

    # ---- Posturas ----

    def list_poses(self):
        out = []
        d = self.poses_dir()
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    try:
                        p = _load_json(os.path.join(d, fn))
                        out.append({"file": fn, "name": p.get("name", fn[:-5]), "time": p.get("time", ""),
                                    "goals": {r["id"]: r["pos"] for r in p.get("rows", [])}})
                    except Exception as e:  # noqa: BLE001
                        self.log(f"Não foi possível ler o arquivo de postura {fn}: {type(e).__name__}: {e}", "Posturas", "warn")
        return out

    def save_pose(self, name):
        st = self.bus.states(self.present())
        rows = [{"id": i, "joint": JOINT.get(i), "pos": s["pos"], "deg": round((s["pos"] - 2048) * 360 / 4096, 1)}
                for i, s in st.items() if s]
        os.makedirs(self.poses_dir(), exist_ok=True)
        safe = "".join(c for c in str(name) if c not in '\\/:*?"<>|').strip()[:40] or "pose"
        fn = f"{safe}-{time.strftime('%Y-%m-%d')}.json"
        _save_json(os.path.join(self.poses_dir(), fn), {"name": safe, "time": time.strftime("%Y-%m-%d %H:%M"), "rows": rows})
        missing = [i for i, v in st.items() if not v]
        self.log(f"Postura salva: {fn} ({len(rows)} servos)" + (f"；sem leitura em {missing}; não foi salvo" if missing else ""), "Posturas",
                 "warn" if missing else "info")
        return {"file": fn}

    def delete_pose(self, fn):
        """Não apaga de verdade: move para a lixeira e acrescenta a data ao nome do arquivo para permitir recuperação."""
        fn = str(fn or "")
        if not fn or os.path.basename(fn) != fn or not fn.endswith(".json"):
            raise Refused(f"Arquivo de postura desconhecido: {fn!r}")
        src = os.path.join(self.poses_dir(), fn)
        if not os.path.isfile(src):
            raise Refused(f"Postura não encontrada: {fn}")
        trash = os.path.join(self.poses_dir(), ".trash")
        os.makedirs(trash, exist_ok=True)
        os.replace(src, os.path.join(trash, f"{time.strftime('%Y%m%d-%H%M%S')}-{fn}"))
        self.log(f"Postura removida: {fn} (movida para a lixeira; mova de volta para recuperar)", "Posturas")
        return {}

    def go_pose(self, fn, seconds, mode, acc):
        p = next((x for x in self.list_poses() if x["file"] == fn), None)
        if not p:
            raise Refused(f"Postura não encontrada: {fn}")
        self.log(f"Executando postura “{p['name']}” ({seconds:g} s)", "Movimento")
        return self.move(p["goals"], seconds, mode, acc)

    def shift_saved_poses(self, deltas, sign=1, only=None):
        """Após recalibrar, a leitura da mesma postura física muda por delta; ajusta as posturas salvas junto."""
        changed = []
        d = self.poses_dir()
        if not os.path.isdir(d) or not any(deltas.values()):
            return changed
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json") or (only is not None and fn not in only):
                continue
            path = os.path.join(d, fn)
            pose = _load_json(path)
            hit = False
            for r in pose.get("rows") or []:
                dl = deltas.get(str(r.get("id")))
                if dl:
                    r["pos"] = int(r["pos"]) + sign * int(dl)
                    r["deg"] = round((r["pos"] - 2048) * 360 / 4096, 1)
                    hit = True
            if hit:
                _save_json(path, pose)
                changed.append(fn)
        return changed

    # ---- Ferramentas do barramento ----

    def scan(self, ids):
        found = [i for i in ids if self.bus.ping(i) is not None]
        lost = [i for i in ids if i not in found] if len(ids) <= 32 else []
        self.log(f"Varredura {ids[0]}..{ids[-1]}: {len(found)} servos online {found}" + (f"；offline {lost}" if lost else ""),
                 "Barramento", "warn" if lost else "info")
        return {"found": found, "lost": lost}

    def dump(self, sid):
        d = self.bus.dump(int(sid))
        r = d["raw"]
        self.log(f"Exportação #{sid}: firmware {r[0]}.{r[1]}, servo {r[3]}.{r[4]}, modo={r[33]}, fase={r[18]}, P/D/I={r[21]}/{r[22]}/{r[23]}"
                 f"(em operação {r[50]}/{r[51]}/{r[52]}, limite de torque {r[48] | r[49] << 8}) "
                 f"offset={fmt_off(r[31] | r[32] << 8)}, torque={r[40]}, trava={r[55]}, nível de resposta={r[8]}", "Registradores")
        return {"id": int(sid), **d}

    def write_reg(self, sid, addr, size, value, unlock):
        self.guard()
        sid, addr, size, value = int(sid), int(addr), int(size), int(value)
        if addr == 40:
            raise Refused("Use o controle da interface para o interruptor de torque; não grave aqui")
        if size not in (1, 2) or not 0 <= addr <= 86:
            raise Refused("Endereço de 0 a 86; 1 ou 2 bytes")
        bus = self.bus
        name = feetech.REGISTERS.get(addr, ("?",))[0]
        rd = bus.read_u8 if size == 1 else bus.read_u16
        old = rd(sid, addr)
        if unlock:
            bus.unlock(sid)
        try:
            err = (bus.write_u8 if size == 1 else bus.write_u16)(sid, addr, value)
        finally:
            if unlock:
                bus.lock(sid)
        new = rd(sid, addr)
        same = new == value & (0xFF if size == 1 else 0xFFFF)
        self.log(f"#{sid} Gravou {addr} “{name}” {old} → {value}{_ack(err)}; leitura de retorno {new}" + ("(gravado com desbloqueio; travado novamente)" if unlock else "")
                 + ("" if same else "(leitura de retorno difere do valor gravado: somente leitura ou fora da faixa?)"), "Registradores", "info" if same else "warn")
        touched = sorted(set(range(addr, addr + size)) & set(GAIN_REGS))
        if touched:
            # Alteração manual de P/D/limite continua permitida para usuários avançados; o cabeçalho informa “alterado manualmente, diferente do programa principal” (pedido de 19/10)
            self.manual.setdefault(sid, {})[addr] = new
            g = self.gains.get(max_age=GAINS_RECHECK_S)
            eeprom = all(a in (21, 22) for a in touched)
            self.log(f"#{sid} alterou manualmente {', '.join(GAIN_REGS[a] for a in touched)} (registrador {addr} = {new}), diferente do programa principal"
                     f"(P{g['kp']} · D{g['kd']} · limite {g['limit']})"
                     + (" : estes valores estão na EEPROM e só são usados na inicialização; o Studio ainda grava os valores em operação (50/51/48) ao habilitar torque" if eeprom else
                        "; enquanto houver torque, mantém estes valores; quando o servo for desligado e energizado novamente, o Studio grava os valores do programa principal"), "Registradores", "warn")
        self.s.refresh_static([sid])
        return {"old": old, "new": new, "same": same}

    def reboot(self, sid):
        sid = int(sid)
        self.bus.write_u8(sid, 40, 0)
        self.bus.reboot(sid)
        self.log(f"#{sid} Reinicialização 0x08 (desliga o torque antes; retorna em cerca de 0,8 s)", "Registradores")
        return {}

    def set_id(self, old, new):
        self.guard()
        old, new = int(old), int(new)
        if not 0 <= new <= 253:
            raise Refused("O novo ID deve estar entre 0 e 253")
        if new != old and self.bus.ping(new) is not None:
            raise Refused(f"O ID {new} já está em uso por outro servo; haverá conflito")
        ok = self.bus.set_id(old, new)
        self.log(f"Alterar ID {old} → {new}: " + ("o novo ID responde ao ping" if ok else "o novo ID não responde ao ping"), "Registradores", "info" if ok else "error")
        return {"ok": ok}

    def timing(self, n=200):
        """Executa sync_read em todos os servos online n vezes e mede duração e falhas."""
        ids = self.present()
        times, fails = [], 0
        with self.calib_lock:                      # Suspende as consultas durante a medição para medir somente o barramento
            for _ in range(int(n)):
                t = time.perf_counter()
                r = self.bus.sync_read(ids, 56, 15)
                times.append((time.perf_counter() - t) * 1000)
                fails += sum(1 for v in r.values() if v is None)
        times.sort()
        res = {"n": n, "ids": len(ids), "min_ms": round(times[0], 2), "avg_ms": round(sum(times) / n, 2),
               "p99_ms": round(times[max(0, int(n * 0.99) - 1)], 2), "max_ms": round(times[-1], 2), "fails": fails}
        self.log(f"Teste de temporização: {res}", "Barramento", "warn" if fails else "info")
        return res

    def set_dir(self, sid, d):
        sid, d = int(sid), (-1 if int(d) < 0 else 1)
        self.s.directions[sid] = d
        path = os.path.join(self.state_dir, "servo-directions.json")
        os.makedirs(self.state_dir, exist_ok=True)
        _save_json(path, {str(k): v for k, v in self.s.directions.items()})
        self.log(f"Orientação #{sid} → {d:+d} (salva em servo-directions.json)", "Orientações")
        return {"dirs": {str(k): v for k, v in self.s.directions.items()}}

    # ---- Comandos da interface ----

    def handle(self, args, tok=None):
        """Processa comandos da interface (executados em uma thread). Retorna um dict; lança Refused se não for possível (motivo exibido na interface).
        Registra início e fim: devolução/saída aguarda operações pendentes; novas solicitações são rejeitadas durante a devolução (revisão D2). app já registrou no event loop (tok),
        por isso não registra novamente aqui; chamadas diretas (testes) são registradas. Operações iniciadas continuam normalmente; devolução/saída espera e depois lê o torque no momento."""
        if tok is not None:
            return self._handle(args)
        with self.s.op_slot(args.get("op")):
            return self._handle(args)

    def _handle(self, args):
        op = args.get("op")
        sec = float(args.get("seconds", 2))
        mode = "stream" if args.get("mode") == "stream" else "profile"
        acc = int(args.get("acc", 30))
        if op == "torque":
            ids = [int(i) for i in (args.get("ids") or [])] or self.present()
            if int(args.get("on", 0)) and self.s.latched and self.s.closing:
                raise Refused("Devolução ao programa principal em andamento: a trava de torque impede nova habilitação")       # A desativação de torque feita durante a devolução não pode ser anulada por habilitação manual (revisão D2)
            if int(args.get("on", 0)) and self.s.latched:
                # Após desligar o torque, uma ação explícita “Ligar torque/Reter” destrava; transições, animações e finalizações de calibração em segundo plano continuam sem reativá-lo
                self.s.latched = False
                self.log("Habilitação manual do torque: trava de desligamento liberada", "Segurança")
            return self.torque_on_aligned(ids) if int(args.get("on", 0)) else self.torque_off(ids)
        if op == "goal":
            return self.goal(args["id"], args["pos"])
        if op == "move":
            return self.move(args.get("goals") or {}, sec, mode, acc)
        if op == "stop":
            return self.stop()
        if op == "official":
            return self.go_official(args.get("key"), sec, mode, acc)
        if op == "idle":
            return self.idle(bool(args.get("on")))
        if op == "calib_plan":
            return self.calib_plan(parse_ids(args.get("ids") or "20-24,30-34,10-14"))
        if op == "calibrate":
            return self.calibrate(parse_ids(args.get("ids") or "20-24,30-34,10-14"))
        if op == "undo":
            return self.undo()
        if op == "poses":
            return {"poses": self.list_poses()}
        if op == "save_pose":
            self.save_pose(args.get("name") or "pose")
            return {"poses": self.list_poses()}
        if op == "delete_pose":
            self.delete_pose(args.get("file"))
            return {"poses": self.list_poses()}
        if op == "go_pose":
            return self.go_pose(args.get("file"), sec, mode, acc)
        if op == "scan":
            return self.scan(parse_ids(args.get("ids") or "20-24,30-34,10-14"))
        if op == "scan_all":
            return self.scan(list(range(0, 254)))
        if op == "dump":
            return self.dump(args["id"])
        if op == "write_reg":
            return self.write_reg(args["id"], args["addr"], args.get("size", 1), args["value"], bool(args.get("unlock")))
        if op == "reboot":
            return self.reboot(args["id"])
        if op == "set_id":
            return self.set_id(args["old"], args["new"])
        if op == "timing":
            return self.timing(int(args.get("n", 200)))
        if op == "set_dir":
            return self.set_dir(args["id"], args["dir"])
        if op == "unlatch":
            self.s.latched = False
            self.log("Trava de desligamento liberada; o torque pode ser habilitado", "Segurança")
            return {}
        if op == "info":
            return {"danger": {str(k): v for k, v in DANGER.items()},
                    "registers": {str(k): v for k, v in feetech.REGISTERS.items()},
                    "official": {k: v[0] for k, v in OFFICIAL.items()}}
        raise Refused(f"Comando desconhecido: {op}")


def _save_json(path, obj):
    """Grava primeiro em .tmp e depois renomeia: uma falha no meio não deixa um arquivo parcial."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
