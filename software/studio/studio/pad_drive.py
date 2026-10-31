"""Parte da página do controle responsável por movimentar o Microduck: concessão do controle, controles virtuais (botões e analógicos desenhados), ficar em pé, começar a andar, sentar, executar habilidades, sons, ações e combinações.

PadOps (pad.py) herda esta classe e compartilha bloqueios, leituras de retorno do robotd e logs. Regras de segurança:
- **Concessão do controle** (revisões 19 e 25): a página que move os analógicos, mantém gatilhos/X pressionados ou executa ações recebe o controle; outra página só pode assumir ao clicar em “Assumir”. A concessão é liberada após 6 segundos sem movimento ou sinal de botão mantido. Apenas deixar a página aberta não a renova (watch e drive open não renovam; revisões 2 I1 e 3 V5). Comandos pontuais (ficar em pé, andar, sentar, habilidade, som) não recebem a concessão; são recusados enquanto outra página move os analógicos, exceto “Parar (ficar em pé)”, que qualquer pessoa pode acionar sem fila.
- **Visibilidade da área do controle** (3 V5; revisão O1 da reorganização do resumo): “visível” significa rota / ou /pad, página visível e área do controle dentro da janela. Ao entrar, envia drive {open, seq}; ao sair, drive {on:false, seq}. seq cresce por página e a conexão guarda o último recebido; mensagens mais antigas são descartadas porque o pool de threads pode reordená-las. Conexões que saem são marcadas como closed: comandos atrasados de analógicos, botões e ações são descartados até um novo open. **Toda conexão começa como closed** (new_conn) e não fica ativa antes de open. **Uma conexão encerrada (gone) nunca pode voltar**: open é recusado.
- **O movimento exige manter o analógico pressionado**: a página envia sticks a 10 Hz enquanto pressionado (ou move no protocolo antigo) e envia stop ao soltar. O servidor não repete comandos; se a conexão cair, o deadman de 500 ms do robotd interrompe o movimento (duck-control safety.rs:226-237). Sequências são armazenadas por conexão e não são apagadas ao trocar a concessão; quadros anteriores ao último stop daquela conexão são descartados (barreira compartilhada pelos três canais). O quadro mais recente é acompanhado separadamente por canal (move / head / body, 3 V6). Verificação e envio usam o mesmo bloqueio.
- **Cabeça e corpo mantêm o último valor** (3 V1): robot.head e robot.pose não expiram no robotd (fork robotd intents.rs:327-341). pose com active:true zera a velocidade do controlador e força a rede de postura (fork control.rs:595-607); um valor deixado pela página impede tanto a página quanto o controle físico de mover o robô. Por isso, _latch registra cabeça/corpo definidos pela página e todos os caminhos os limpam (cabeça toda em zero; corpo {"active": false}, inclusive no espelhamento, pois o padd reenvia a cada 0,1 s no modo corpo: padd:1570, 1625-1631): voltar a andar, soltar o controle, sair da página, perder a concessão, troca após 6 s, relaxamento (quatro origens), conexão de controle físico, Parar/Start, saída da postura “pronto para andar” e encerramento do Studio. Os pontos de relaxamento rodam no loop de eventos e apenas definem uma sinalização (_request_clear); uma thread envia a limpeza 0,1 s depois do relaxamento.
  **Armadilha**: PoseParams usa active:true por padrão (fork lib.rs:2320-2346); enviar robot.pose {} ativa o modo corpo. Para sair, sempre envie active:false. Quando o Studio detecta o programa principal pela primeira vez, envia robot.pose {"active": false} para limpar qualquer estado deixado antes de uma reinicialização.
- **Watchdog** (3 V11): se a cabeça/corpo recebeu um quadro diferente de zero e não recebe outro por 0,6 s, recentraliza (continua no modo corpo). Se não houver sinal de vida do modo por 3 s, sai dele (envia active:false). Um botão mantido é liberado após 0,45 s sem atualização (X: 0,3 s). Tudo roda na thread em segundo plano a 25 Hz (_tick_loop).
- **Botões mantidos** (3 V4): LT / RT / X usam o canal keys (a página informa pressionamento, soltura e manutenção a cada 0,15 s). A thread envia a ação conforme os botões ativos: a boca usa LT ou RT × mouth_percent; LT mantém wheee com hold:true e envia hold:false ao soltar; RT toca um som curto ao pressionar; X envia robot.do a cada 40 ms enquanto pressionado (rolagem contínua, padd:1182-1211). Não reutiliza _run_action e é exclusivo em relação a ações de cabeça/boca em andamento.
- **Controle físico conectado** (espelhamento): o padd envia velocidade zero a cada 0,1 s mesmo sem interação (padd main.rs:962-977) e envia boca em cada ciclo (padd main.rs:1351-1363). Nesse caso, a página recusa analógicos, botões, modos e ações pontuais do desenho (src:"svg"), pois o padd sobrescreveria os comandos a cada 0,1 s; drive on também é recusado. A página não envia Parar quando não está ativa e nunca interrompe o controle físico; a limpeza de cabeça/corpo é exceção. Os botões grandes (ficar em pé, começar a andar, sentar, habilidade e som) são solicitações pontuais e continuam disponíveis.
- **Após relaxar**, por 2 s recusa ficar em pé, andar, sentar, habilidades, analógicos e ações (inicialização, retorno à postura e relaxamento compartilham um único espaço de solicitação; vence a mais recente: robotd intents.rs:24-36, 149-157). O relaxamento é detectado por três origens: run_relax no app chama note_relax() (botão superior, espaço ou Select desenhado), contador de relaxamento do robotd.py mudou ou leitura de retorno detectou torque ligado→desligado (Select físico, robotctl, queda ou bateria baixa: revisão 2 I2).
- **A postura sentada deve vir de robot.policies.sitting recente** (revisão 2 S2): se não for possível ler, recusa sentar/ficar em pé em vez de adivinhar. Caso contrário, um Microduck sentado poderia ficar em pé após dois comandos consecutivos (lib.rs:2362-2368: são chamadas diferentes).

Referências da interface oficial (pollen-robotics/microduck; “fork” indica o firmware derivado):
| Ação na página | Envio ao robotd | Referência |
| Ficar em pé (torque relaxado) | robot.init (solicitação) | lib.rs:553-558; main.rs:4550-4563; fork main.rs:5898-5908 (recusado se o barramento não estiver pronto) |
| Ficar em pé (sentado) | robot.do {"skill":"sit_toggle"} | lib.rs:2362-2370 (sentado exige sit_toggle; init conflita com o bloqueio); main.rs:659-669 |
| Começar a andar | robot.enable {"on":true,"toggle":false} | lib.rs:2685-2704; main.rs:4518-4548; fork main.rs:5780-5850 (verificações HOME/IMU/política) |
| Parar (ficar em pé) | robot.stop, depois robot.enable {"on":false} | lib.rs:537-540; main.rs:4513-4516 (stop apenas zera a velocidade) |
| Sentar | robot.do {"skill":"sit_toggle"} | main.rs:4223-4255 (recusado se a política não estiver ativa ou HOME não tiver sido atingida); main.rs:4158-4168 |
| Habilidade | robot.do {"skill":nome} | lib.rs:2338-2346 (nomes em robot.policies.skills); main.rs:4136-4176 |
| Tocar som | robot.sound {"tag":…} (solicitação) | lib.rs:590-600, 2094-2140; main.rs:4300-4319 |
| Analógicos (andar) | notificação robot.move {vx,vy,vyaw} | lib.rs:2041-2051; main.rs:3589-3597, 3631-3636 |
| Analógicos (modo cabeça) | notificação robot.head (conversão em sticks_to_intent) | fork padd:1427-1445 |
| Analógicos (modo corpo) | notificação robot.pose {z,roll,pitch,active} | fork padd:316-320, 1447-1460; fork lib.rs:2320-2346 |
| Manter LT / RT / X | notificações robot.mouth / robot.sound / robot.do | fork padd:1182-1211, 1351-1396 |
| Acenar, inclinar a cabeça, abrir a boca | notificações robot.head / robot.mouth | Consulte o cabeçalho de pad_combo.py |
| Direcional direita (desenho) | robot.rebootMotors {"ids":[]} (solicitação; vazio = todos) | padd oficial main.rs:530, 750-765; fork (handover) main.rs:2731-2758 (relaxa o corpo antes de reiniciar e depois deixa o torque relaxado), 6050-6056 (nunca recusa) |
| Manter direcional para cima por 3 s | robot.setMode {"mode":"roller" / "walk"} (solicitação) | padd oficial main.rs:247-252, 766-806; fork (handover) main.rs:5700-5736 (recusa sem modelo de rodas; igual na versão autodetect), 2870-2930 |

Direcional direita e para cima seguem a implementação oficial (decisão do usuário em 10-19): direita envia o comando ao tocar, sem confirmação nem concessão de controle, e não espera outra solicitação pendente (via de emergência como relaxamento). Após recebê-lo, o programa principal registra um relaxamento (note_relax: bloqueia torque por 2 s, interrompe ações e limpa cabeça/corpo). Para cima exige manter pressionado por 3 s na página e envia expect com o modo desejado; o backend confere novamente robot.policies.mode e recusa se divergir.

Start do controle virtual (3 V7, V8): a página calcula a ação de Start a partir de motion.start e envia start {expect}; o backend recusa se a ação calculada for diferente de expect (“O estado mudou; pressione novamente”). Diferenças para o Start físico (fork padd:1113-1148, fork robotd:5795-5873): sentado, o controle físico usa robot.init direto para voltar a HOME; a página usa sit_toggle (rede sitstand, mais suave). Durante a caminhada, o controle físico desativa o toggle (retorno gradual a HOME); a página envia stop + enable off (define HOME diretamente).
"""
import itertools
from contextlib import nullcontext
import json
import math
import os
import re
import threading

from . import pad_combo as C
from .estop import STARTING_PHASES, relaxed, torque_off
from .log import log_cmd
from .pad_combo import Refused
from .rpc import RpcError, Timeout, Unreachable
from .updates import neutral_robot_command

MAX_V = 0.3               # velocidade máxima em m/s: padd padrão --max-linear 0.3（padd main.rs:158-164），mesmo valor do controle web oficial
MAX_W = 1.5               # velocidade angular máxima em rad/s: padd padrão --max-angular 1.5（padd main.rs:166-168）
V_CEIL, W_CEIL = 0.6, 3.0   # valores maiores lidos da configuração são limitados a este teto para evitar movimento excessivo em caso de erro
HEAD_RAD = 2.5            # amplitude máxima da cabeça em rad: padd padrão --max-head 2.5（fork padd:201-205，「the network itself decides how far」）
HEAD_CEIL = 2.5           # também limita valores maiores definidos na configuração
HEAD_CHOICES = (0.5, 1.0, 2.5)   # valores de head_rad aceitos no arquivo --input-settings（fork padd/src/input_settings.rs:16-21）
BODY_Z_UP, BODY_Z_DOWN, BODY_ANGLE = 0.010, 0.025, 0.2618   # amplitude máxima no modo corpo（fork padd:316-320）
BODY_TRAIN_ANGLE = 0.26   # faixa de treinamento roll/pitch ±0.26 rad, z −0.025..+0.010 m (fork lib.rs:2320-2325); limita antes de enviar
DEADZONE = 0.1            # zona morta do analógico, aplicada separadamente por eixo e sem reescalonamento（fork padd:184-187 e 1342-1349）
LEASE_S = 6.0             # libera a concessão após este intervalo sem mover o analógico ou renovar um botão mantido
RELAX_GUARD_S = 2.0
HOLD_S = 0.45             # uma ação mantida envia sinal a cada 0,15 s; interrompe se o sinal faltar por este período
KEYS_HOLD_S = 0.45        # botões mantidos (LT/RT): atualizados a cada 0,15 s; sem novo sinal, considera solto (3 V4)
X_HOLD_S = 0.3            # X usa prazo menor: a janela de repetição é 0,15 s（fork control.rs:42-47）; se a página cair, repete no máximo uma vez
STICK_STALE_S = 0.6       # recentraliza cabeça/corpo após este intervalo sem novo quadro diferente de zero (3 V11)
MODE_HB_S = 3.0           # encerra o modo cabeça/corpo se não receber sinal de vida por este intervalo (3 V11)
TICK_S = 0.04             # thread em segundo plano a 25 Hz: botões mantidos, watchdog e limpeza
RELAX_CLEAR_DELAY_S = 0.1   # limpeza de cabeça/corpo causada pelo relaxamento é enviada depois da solicitação de relaxamento (3 V1, item 5)
MOVE_MIN_GAP_S = 0.04     # intervalo mínimo entre quadros do mesmo canal; aguarda e envia o mais recente quando chegam muito próximos (revisão 21)
WALK_STOP_WAIT_S = 1.0
CMD_TIMEOUT_S = 3.0
BINDINGS_STALE_S = 10.0   # atualiza pad.bindings antes de executar um botão desenhado se estiver desatualizado (3 V14; padd relê a configuração a cada segundo, padd:806-817)
LOW_BATTERY = 10          # não é mais usado: bateria baixa não impede ficar em pé (decisão do usuário em 10-18: bateria apenas gera aviso; consulte studio/battery.py)
PADD_UNIT = "/etc/systemd/system/padd.service"        # arquivo da unidade instalado em scripts/board-test.sh (oficial):800-806
PADD_DROPIN_DIR = "/etc/systemd/system/padd.service.d"
PADD_INPUT_ACK = "/run/padd/input-settings.json"      # recibo gravado pelo padd depois de aplicar ajustes de amplitude（fork padd/src/input_settings.rs:63-74）
# usa um pool separado de threads rápidas, sem disputar com solicitações lentas com quatro threads (3 V13), sem disputar com pareamento, Bluetooth e solicitações pontuais lentas
FAST_OPS = ("move", "stop", "sticks", "keys", "mode", "action_hold", "action_stop", "drive", "watch")
FAST_WORKERS = 4
GONE_KEEP = 500           # quantidade de conexões encerradas/desativadas mantidas no histórico
INF = float("inf")

POSTURE_CN = {"absent": "Programa parado", "starting": "Programa iniciando", "commissioning": "Comissionamento", "sitting": "Sentado",
              "limp": "Torque relaxado", "walking": "Andando", "policy": "Em pé (pronto para andar)", "holding": "Em pé (mantendo postura)",
              "homing": "Ficando em pé", "unknown": "Postura desconhecida", "servo_session": "Ajustando servos"}
DRIVING = ("policy", "walking")
MODES = ("drive", "head", "body")
MODE_CN = {"drive": "Andar", "head": "Modo cabeça", "body": "Modo corpo"}
DRIVE_MODE_CN = {"walk": "Andar", "roller": "Rodas"}     # modo de robot.setMode / robot.policies (segure o direcional para cima por 3 s)
HELD_KEYS = ("lt", "rt", "x")
KEY_CN = {"a": "A", "x": "X", "lb": "LB", "rb": "RB", "dpad_down": "Direcional para baixo", "lt": "LT", "rt": "RT"}
BIND_KEYS = ("a", "x", "lb", "rb", "dpad_down")
# associações padrão oficiais (fork robotd-params lib.rs:175-215), usadas quando pad.bindings não puder ser lido
DEFAULT_BIND = {"a": "ground_pick", "x": "roulade", "lb": "kick_left", "rb": "kick_right", "dpad_down": "sit_toggle"}
HEAD_ZERO = {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}
POSE_OFF = {"active": False}                                   # sempre envia active:false (o padrão é true)
POSE_CENTER = {"z": 0.0, "roll": 0.0, "pitch": 0.0, "active": True}
_FLAG = re.compile(r"--(max-linear-backward|max-linear|max-angular)(?:=|\s+)(\S+)")
_FLAG_HEAD = re.compile(r"--max-head(?:=|\s+)(\S+)")
_FLAG_PATH = re.compile(r"--(input-settings|config)(?:=|\s+)(\S+)")
NO_SIT_INFO = "Não foi possível saber se está sentado (robot.policies indisponível ou desatualizado); aguarde alguns segundos e tente novamente. Uma leitura incorreta poderia fazer o Microduck sentado ficar em pé."
MIRROR_SVG = "Controle físico conectado: o desenho apenas acompanha o controle; os comandos da página são ignorados porque o padd os sobrescreveria a cada 0,1 s."
MODE_IDLE = "A política não está em execução: os analógicos não movem cabeça/corpo (Y/B ainda alternam o modo; ele só funciona depois de ‘Começar a andar’)."


def plain_refusal(reason):
    """Converte recusas do robotd em mensagens claras; mantém intactos os motivos originais em chinês do fork."""
    r = str(reason or "")
    low = r.lower()
    if "policy is not driving" in low:
        return "A política não está em execução: clique em ‘Começar a andar’ (ou pressione Start duas vezes no controle)"
    if "home pose" in low and "still" in low:
        return "Ainda está voltando à postura inicial; aguarde um segundo e tente novamente"
    if "no skill named" in low:
        return f"Esta unidade não tem essa habilidade (mensagem original: {r}）"
    if "no skills configured" in low:
        return "Nenhuma habilidade foi configurada nesta unidade"
    if "no voice" in low:
        return "Não há áudio nesta unidade: o áudio está desativado ou o pacote de sons está vazio (execute sounds ensure-bank no Microduck)"
    if "read-only" in low:
        return "O programa principal está somente para leitura (modo de comissionamento); ações não são aceitas"
    if "roller onnx models are not installed" in low:
        return "O modelo de rodas não está instalado nesta unidade; não é possível alternar, continuará andando"
    if "nothing to switch between" in low:
        return "A política de caminhada não está instalada; não há modo para alternar"
    if "requires stationary home" in low:
        return "Para alternar, o robô precisa estar parado na postura inicial e sem executar uma habilidade"
    return f"O programa principal recusou: {r}" if r else "O programa principal recusou sem informar o motivo"


def _exec_line(texts):
    """Retorna o último ExecStart efetivo nos arquivos de unidade e drop-ins do padd [(caminho, texto)]; ExecStart= vazio limpa os anteriores."""
    exec_line, exec_src = None, None
    for path, text in texts:
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if line.startswith("ExecStart="):
                val = line[len("ExecStart="):].strip()
                exec_line, exec_src = (val or None), (path if val else None)
    return exec_line, exec_src


def parse_speed_limits(texts):
    """Analisa textos dos arquivos de unidade e drop-ins do padd [(caminho, texto)] e retorna {"v", "w", "src"}. Ignora números inválidos (como 1.2.3) sem lançar exceção (revisão 2 I3)."""
    exec_line, exec_src = _exec_line(texts)
    found, bad = {}, []
    for k, v in _FLAG.findall(exec_line or ""):
        try:
            x = float(v)
        except ValueError:
            bad.append(f"--{k} {v}")
            continue
        if math.isfinite(x) and x > 0:
            found[k] = x
        else:
            bad.append(f"--{k} {v}")
    v = min([found[k] for k in ("max-linear", "max-linear-backward") if k in found] or [MAX_V])
    w = found.get("max-angular", MAX_W)
    if found:
        src = f"Configuração do padd ({exec_src})"
    elif texts:
        src = "Padrões oficiais (padd.service sem alterações)"
    else:
        src = "Padrões oficiais (não foi possível ler a configuração do padd)"
    if bad:
        src += f"；parâmetros não reconhecidos foram ignorados: {' e '.join(bad)}"
    capped = v > V_CEIL or w > W_CEIL
    return {"v": min(v, V_CEIL), "w": min(w, W_CEIL), "src": src + (" (valores acima do limite são limitados ao teto)" if capped else "")}


def parse_padd_inputs(texts):
    """Lê --max-head, --input-settings e --config de ExecStart (3 V9, V18). O drop-in do fork se parece com
     (fork packaging/gamepad.py:94): startup_gate.py … --exec …/padd --socket … --config /etc/robot/feetech-ft5/robotd.toml
    --max-head 2.5 --input-settings /etc/robot/feetech-ft5/pad-settings.json Valores inválidos são ignorados sem lançar exceção."""
    exec_line, exec_src = _exec_line(texts)
    out = {"max_head": None, "input_settings": None, "config": None, "bad": [], "src": exec_src}
    for v in _FLAG_HEAD.findall(exec_line or ""):
        try:
            x = float(v)
        except ValueError:
            out["bad"].append(f"--max-head {v}")
            continue
        if math.isfinite(x) and x > 0:
            out["max_head"] = x
        else:
            out["bad"].append(f"--max-head {v}")
    for k, v in _FLAG_PATH.findall(exec_line or ""):
        out["input_settings" if k == "input-settings" else "config"] = v
    return out


def _padd_settings(d):
    """Verifica se o padd aceita estes ajustes de amplitude (fork padd/src/input_settings.rs:7-21): só pode haver mouth_percent e head_rad
    (deny_unknown_fields: um campo extra invalida tudo, revisão R10); boca de 0 a 100 e cabeça aceita somente 0.5 / 1.0 / 2.5. Se aceito, retorna (cabeça, boca); senão, None."""
    if not isinstance(d, dict) or set(d) != {"mouth_percent", "head_rad"}:
        return None
    m, h = d["mouth_percent"], d["head_rad"]
    if not (isinstance(m, (int, float)) and not isinstance(m, bool) and math.isfinite(m) and 0 <= m <= 100):
        return None
    if not (isinstance(h, (int, float)) and not isinstance(h, bool) and float(h) in HEAD_CHOICES):
        return None
    return float(h), float(m)


def input_limits(inputs, settings_text=None, settings_error=None, ack=None):
    """Calcula a amplitude de cabeça e boca como o padd (fork padd/src/input_settings.rs:9-27, 36-46, 63-80): começa com boca em 100% e cabeça em --max-head (padrão 2.5);
    se o padd aceitar o arquivo --input-settings (_padd_settings), usa ambos os valores; caso contrário, mantém os anteriores.
    ack: settings no recibo gravado pelo padd (_read_inputs verifica se o padd que escreveu o recibo continua ativo e se o arquivo corresponde); esses valores em uso têm prioridade.
    Retorna {"head", "mouth" (porcentagem), "src"}."""
    head = inputs.get("max_head") or HEAD_RAD
    src = f"--max-head {head:g}" if inputs.get("max_head") else "Padrões oficiais (cabeça 2,5 rad, boca 100%)"
    mouth = 100.0
    path = inputs.get("input_settings")
    got = _padd_settings(ack) if path and ack is not None else None
    if got is not None:
        head, mouth = got
        src = f"Em uso pelo padd (recibo {PADD_INPUT_ACK})"
    elif path:
        if settings_error is not None:
            src += f"; não foi possível ler {path} ({settings_error}); mantendo os valores anteriores"
        else:
            try:
                got = _padd_settings(json.loads(settings_text or ""))
            except ValueError:
                got = None
            if got is not None:
                head, mouth = got
                src = f"Ajustes de amplitude do padd（{path}）"
            else:
                src += f"; o padd não aceita os dados em {path} (somente mouth_percent e head_rad, cabeça 0.5/1.0/2.5, boca 0–100); mantendo os valores anteriores"
    if inputs.get("bad"):
        src += f"；parâmetros não reconhecidos foram ignorados: {' e '.join(inputs['bad'])}"
    if head > HEAD_CEIL:
        head, src = HEAD_CEIL, src + f" (cabeça acima de {HEAD_CEIL:g} rad limitada a {HEAD_CEIL:g})"
    return {"head": head, "mouth": mouth, "src": src}


def _dz(v):
    return 0.0 if abs(v) < DEADZONE else v


def sticks_to_intent(mode, lx, ly, rx, ry, lim, head_rad):
    """Analógico da página (-1..1, x positivo à direita e y positivo para baixo, como TouchStick) convertido no quadro enviado ao robotd (revisão 3, anexo 2; segue o fork padd,
     incluindo os sinais: padd:1437-1439“mapeamento alfa do protótipo, incluindo os sinais… verificado no hardware”).
    No padd, y positivo aponta para cima: LX = dz(lx) e LY = −dz(ly) e RX = dz(rx) e RY = −dz(ry)。Retorna (method, params)."""
    LX, LY, RX, RY = _dz(lx), -_dz(ly), _dz(rx), -_dz(ry)
    r = lambda x: round(x, 4) + 0.0    # noqa: E731 — +0.0 remove -0.0
    if mode == "head":                  # padd:1427-1445
        return "robot.head", {"neck_pitch": r(RY * head_rad), "head_pitch": r(-LY * head_rad),
                              "head_yaw": r(-LX * head_rad), "head_roll": r(RX * head_rad)}
    if mode == "body":                  # padd:1447-1460; depois limita à faixa de treinamento（fork lib.rs:2320-2325）
        z = LY * (BODY_Z_UP if LY >= 0 else BODY_Z_DOWN)
        clampa = lambda a: max(-BODY_TRAIN_ANGLE, min(BODY_TRAIN_ANGLE, a))   # noqa: E731
        return "robot.pose", {"z": r(max(-BODY_Z_DOWN, min(BODY_Z_UP, z))), "roll": r(clampa(RX * BODY_ANGLE)),
                              "pitch": r(clampa(RY * BODY_ANGLE)), "active": True}
    v, w = lim["v"], lim["w"]           # padd:1415-1426: vx = LY×0.3, vy = −LX×0.3 e vyaw = −RX×1.5; o eixo Y do analógico direito não é usado
    return "robot.move", {"vx": r(LY * v), "vy": r(-LX * v), "vyaw": r(-RX * w)}


class _Abort(Exception):
    pass


class DriveMixin:
    # ================= Inicialização =================

    def _drive_init(self, state_dir):
        self.state_dir = state_dir
        self._send_lk = threading.Lock()      # A verificação e o envio ao robotd usam este bloqueio: a ordem aqui é a ordem de execução (adquira-o antes de _lk)
        self._seqs = {}                       # conexão → estado de sequência; não limpa ao trocar a concessão
        self._gone = {}                       # conexões encerradas (mark_gone) → True; nunca recuperam a concessão
        self._closed = {}                     # conexões que saíram da página (drive off) → True; apenas drive open/on libera
        self._halt_after_gone = {}
        self._conn_ids = itertools.count(1)
        self._last_sent_at = {}               # canal → horário do último envio (mínimo de 40 ms entre quadros do mesmo canal)
        self._web_driving = False
        self.virtual = {"owner": None, "last": [0.0, 0.0, 0.0], "at": None}
        self._driver = None                   # {"conn", "by", "since", "seen"}
        self._cmd_busy = False
        self._last_cmd = None                 # resultado mais recente de ficar em pé/andar/sentar/habilidade/som (enviado a todas as páginas)
        self._relax_presses = None
        self._relax_noted = 0                 # número de chamadas de note_relax (usado no teste de emergência; relaxamento superior durante o teste o invalida)
        self._relax_at = -1e9
        self._torque_was = None
        self._action = None                   # ação ou combinação em execução
        self._last_action = None
        self._pad_said = False                # registra uma única vez que o controle físico está conectado e a página deve ceder
        self._limits = parse_speed_limits([])
        self._inputs = input_limits({})       # amplitude de cabeça/boca (3 V9)
        self._imu_head, self._imu_head_why = None, None   # enabled de [pad_imu_head_control] (3 V18)
        self.list_dir = os.listdir
        self._user_combos = C.load_user_combos(state_dir, self.log)
        # ---- Rodada 3: controle virtual ----
        self._latch = {"head": None, "body": None}   # cabeça/corpo definidos pela página: {"conn", "nonzero", "at"}; None = nunca definidos ou já limpos
        self._modes = {}                      # conexão → modo head/body e sinal de vida; ausente significa andar
        self._mode_exit = {}                  # conexão → motivo/horário de saída forçada do modo pelo backend (enviado à página correspondente)
        self._clears = []                     # limpezas pendentes [{"conn", "why", "due", "tries"}] (_request_clear apenas atualiza esta lista)
        self._keys = {}                       # conexão → botões mantidos (consulte _keys_op)
        # conexão → {"skill", "x_down"}: o pressionamento de X foi aceito e ainda está pressionado; só então a habilidade se repete (revisão R5)
        self._x_armed = {}
        self._was_driving = False
        self._pose_reset = "pending"          # na primeira detecção do programa principal, envia robot.pose {"active": false} uma vez
        self._pose_reset_tries = 0
        self._bindings_due = 0.0
        self._tick_evt = threading.Event()
        self._tick_stop = threading.Event()
        self._tick_said = set()               # registra apenas uma vez cada tipo de falha de envio da thread em segundo plano
        self._tick_thread = None

    def _drive_start(self):
        """Chamado no final de PadOps.__init__: inicia a thread de segundo plano a 25 Hz, que dorme quando não há trabalho. Mantém a referência para aguardar a thread parar ao fechar (revisão R8)."""
        self._tick_thread = threading.Thread(target=self._tick_loop, name="pad-tick", daemon=True)
        self._tick_thread.start()

    def new_conn(self):
        """Atribui um nome à conexão da página (contador global; não use id(ws), pois o Python pode reutilizar IDs de objetos liberados; revisão 2 I4).
        **Uma conexão nova começa fora da área do controle** (revisão O1 da reorganização do resumo): a página só envia
        drive {open}；Sem open, analógicos, botões mantidos e modos de cabeça/corpo são descartados (comandos pontuais não dependem disso: 3 V5)."""
        conn = f"ws{next(self._conn_ids)}"
        with self._lk:
            self._remember(self._closed, conn)
        return conn

    def executor_for(self, args):
        """Usado por app: move, sticks e keys usam um pool de threads rápido separado (revisão 2, geral 4 e 3 V13); None seleciona o pool padrão."""
        fast_motion = (args or {}).get("op") == "motion" and (args or {}).get("action") in ("heartbeat", "stop", "pause", "record_pause", "idle_stop")
        return self._fast_pool if (args or {}).get("op") in FAST_OPS or fast_motion else None

    # ================= Quem controla =================

    def _pad_attached(self, now):
        """Verifica se há um controle físico conectado: (True / False / None, descrição). None significa que não foi possível determinar (revisão 2, geral 3).
        O campo attached do canal lateral é a indicação mais direta; se não houver, consulta pad.status do configd recebido nos últimos 15 s (controle conectado e padd em execução)."""
        if self.tap is not None and self._tap_on and self.tap_state == "attached":
            alive = getattr(self.tap, "alive", None)
            if alive is None or alive():
                return True, "Controle físico detectado pelo acesso paralelo do padd"
        st = self._status if isinstance(self._status, dict) else None
        fresh = st is not None and self._status_at is not None and now - self._status_at < 15
        if fresh:
            if any(isinstance(p, dict) and p.get("connected") for p in st.get("pads") or []) and st.get("driver") == "active":
                return True, "configd informa que o controle está conectado e padd está em execução"
            return False, None
        if self._worker_error:
            return None, f"Erro na thread de monitoramento do controle（{self._worker_error}），atualize a página do controle para reiniciar"
        if self.tap is not None and self._tap_on and self.tap_state in ("denied", "error"):
            return None, f"configd indisponível e botões ilegíveis（{self.tap_why or self.tap_state}）"
        return False, None

    def _owner(self, now):
        if self._pad_attached(now)[0]:
            return "pad"
        if self.virtual["at"] is not None and now - self.virtual["at"] < 0.6 and self._web_driving:
            return "web"
        return None

    def _lease_holder(self, now):
        d = self._driver
        return d if d is not None and now - d["seen"] < LEASE_S else None

    def _seq_of(self, conn):
        q = self._seqs.get(conn)
        if q is None:
            # keys: último número de sequência dos botões mantidos. Fica aqui, e não em _keys[conn], porque esse registro é removido ao soltar;
            # assim, uma pressão antiga que chegue atrasada não pode pressionar o botão novamente (revisão R4)
            q = self._seqs[conn] = {"hi": -1, "stop": -1, "life": -1, "mode": -1, "keys": -1, "latest": {}, "sent": {}}
            if len(self._seqs) > GONE_KEEP * 2:
                for k in list(self._seqs)[:GONE_KEEP]:
                    if k != conn and (self._driver or {}).get("conn") != k:
                        self._seqs.pop(k, None)
        return q

    def _remember(self, table, conn):
        table[conn] = True
        while len(table) > GONE_KEEP:
            table.pop(next(iter(table)))

    def _take_lease(self, conn, by, now, force=False, reopen=False):
        """Obtém a concessão do controle (chamado sob _lk). Conexões encerradas nunca recebem a concessão; conexões fora da página (closed) só a recuperam com drive on (reopen).
        Foi removida a exceção que liberava a concessão ao iniciar uma ação (3 V5: ao iniciar uma ação e trocar de página, off pode chegar antes de action_start e a ação ainda começaria).
        Se outra página ainda tem a concessão, recusa, exceto com force (botão “Assumir”). Ao trocar a concessão após 6 s sem atividade, limpa cabeça/corpo definidos pela página anterior
        e botões mantidos/modos (3 V1, item 4); envia a limpeza pela thread em segundo plano."""
        if conn in self._gone:
            raise Refused("Esta página já foi desconectada")
        if conn in self._closed and not reopen:
            raise Refused("Esta página não está na área do controle (rolou para fora, mudou de página ou ainda não chegou nela); volte até o controle e tente novamente")
        d = self._driver
        if d is not None and d["conn"] == conn:
            d["seen"] = now
            if by:
                d["by"] = by
            if reopen:
                self._closed.pop(conn, None)
            return None
        held = self._lease_holder(now)
        if held is not None and not force:
            raise Refused(f"{held['by'] or 'outra página'}está controlando（{now - held['since']:.0f}  s). Clique em “Assumir” para tomar o controle")
        if reopen:
            self._closed.pop(conn, None)
        self._driver = {"conn": conn, "by": by, "since": now, "seen": now}
        if d is not None and d["conn"] != conn and held is None:
            self.log.info(f"Concessão do controle virtual transferida: {by or 'página'} (a página anterior, {d['by'] or 'página'}, estava inativa há {now - d['seen']:.0f} s; concessão liberada automaticamente)",
                          cat="Segurança", dedup=False)
            self._request_clear(d["conn"], "Concessão transferida após 6 s sem atividade")
        return held or d

    def _touch_lease(self, conn, now):
        d = self._driver
        if d is not None and d["conn"] == conn:
            d["seen"] = now

    def _drive(self, args, conn, by):
        """A página entra na área do controle (open), sai (on:false) ou clica em “Assumir” (on:true, force). open/off inclui uma sequência crescente da página;
        guarda a última por conexão e descarta as anteriores (3 V5: o pool de threads pode inverter a ordem de off e do open seguinte)."""
        now = self.clock()
        seq = self._seq(args)
        if args.get("open"):
            with self._lk:
                if conn in self._gone:
                    raise Refused("Esta página já foi desconectada")
                q = self._seq_of(conn)
                if seq is not None and seq <= q["life"]:
                    return {"dropped": "Obsoleto (a página saiu e voltou depois)"}
                if seq is not None:
                    q["life"] = seq
                self._closed.pop(conn, None)            # libera apenas closed: não assume a concessão nem interrompe (deixar a página aberta não bloqueia outras pessoas)
            return {"open": True}
        if args.get("on"):
            with self._lk:
                attached, _ = self._pad_attached(now)
                if attached:
                    raise Refused("Controle físico conectado: a página apenas espelha os movimentos; o controle virtual não pode ser ativado porque o padd sobrescreveria os comandos a cada 0,1 s")
                q = self._seq_of(conn)
                if seq is not None and seq <= q["life"]:
                    return {"dropped": "Obsoleto (a página saiu da área do controle depois)"}
                if seq is not None:
                    q["life"] = seq
                prev = self._take_lease(conn, by, now, force=bool(args.get("force")), reopen=True)
            if prev is not None and prev.get("conn") != conn:
                self.log.warn(f"{by or 'uma página'}assumiu o controle (antes era  {prev.get('by') or 'outra página'}）", cat="Segurança",
                              hint="Os analógicos, botões e ações da página anterior deixam de funcionar imediatamente", dedup=False)
                self._halt(f"Concessão assumida por {by or 'outra página'} assumiu o controle", prev.get("conn"))
            return {"driver": by}
        with self._lk:
            q = self._seq_of(conn)
            if seq is not None and seq <= q["life"]:
                return {"dropped": "Obsoleto (a página voltou à área do controle depois)"}
            if seq is not None:
                q["life"] = seq
            if conn not in self._gone:
                self._remember(self._closed, conn)
            top = max(q["hi"], seq if seq is not None else -1)
            q["stop"] = max(q["stop"], top)                  # quadros do analógico enviados antes de sair são invalidados
            q["hi"] = max(q["hi"], top)
            mine = self._driver is not None and self._driver["conn"] == conn
            background_music = self.motion_studio.background_music(conn)
            if mine and not background_music:
                self._driver = None
        if background_music:
            # The drive area closes and late manual frames stay fenced, while
            # standalone music remains owned by this still-connected socket.
            pass
        elif mine:
            self._halt("Saiu da área do controle", conn)            # agenda a limpeza e o envio
        else:
            self._request_clear(conn, "Saiu da área do controle")
            self._flush_clears(force=True)
        # Motivo informado pela página（mudou de página / saiu da área do controle / foi para segundo plano：总览重排审查 O1).a mesma mensagem é registrada uma vez por minuto (deduplicação de logs)，
        # rolar para dentro e para fora não polui o log; o motivo da página é truncado e usado apenas no registro
        why = str(args.get("why") or "")[:40]
        self.log.info(f"{by or 'página'}Saiu da área do controle：{why or 'motivo não informado'}", cat="Controle")
        return {}

    def mark_gone(self, conn):
        """WebSocket da página desconectado: app chama **sincronamente** no loop de eventos (só adquire o bloqueio, sem acessar a rede). Todas as instruções posteriores dessa conexão são descartadas,
        ela não pode recuperar o controle; uma ação em andamento é interrompida e cabeça/corpo definidos por ela são limpos pela thread de segundo plano. O comando “Parar” é enviado em drop_client (no pool de threads)."""
        if conn is None:
            return False
        with self._lk:
            if conn in self._gone:
                return False
            self._remember(self._gone, conn)
            self.motion_studio.invalidate("A página foi desconectada", conn)
            self._closed.pop(conn, None)
            self._seq_of(conn)["stop"] = INF
            mine = self._driver is not None and self._driver["conn"] == conn
            if mine:
                self._driver = None
            a = self._action
            act = a is not None and a["conn"] == conn
            if act:
                a["why"] = a["why"] or "A página foi desconectada"
                a["stop"].set()
            self._request_clear(conn, "A página foi desconectada")
            self._mode_exit.pop(conn, None)         # a página não existe mais; não é necessário notificá-la (revisão R9)
            need = (mine and self._web_driving) or act
            self._halt_after_gone[conn] = need
        return need

    def drop_client(self, conn, by=None):
        """A página foi desconectada (app chama no pool de threads, depois de mark_gone): envia “Parar” uma vez se ela estava ativa e limpa cabeça/corpo que definiu. Também funciona sem chamar mark_gone antes."""
        with self._lk:
            need = self._halt_after_gone.pop(conn, None)
        if need is None:
            self.mark_gone(conn)
            with self._lk:
                need = self._halt_after_gone.pop(conn, False)
        if need:
            self.log.info(f"A página foi desconectada（{by or conn}）：controle virtual liberado; envia “Parar” uma vez", cat="Segurança", dedup=False)
            self._halt("A página foi desconectada", conn)
        else:
            self._flush_clears(force=True)

    def _halt(self, why, conn=None, clear_all=False):
        """Interrompe o controle virtual：interrompe a ação da conexão, solta botões mantidos, limpa cabeça/corpo e sai do modo，它的序号以内的帧作废 e 发一次 0。
        clear_all: limpa cabeça/corpo, botões mantidos e modos de todas as páginas（点「Parar (ficar em pé)」：三 V1 第 7 条).
        no espelhamento (controle físico conectado), não envia move 0 se a página não estiver ativa, para não interromper o controle físico（审查二 一般 2）；cabeça/corpo的清理镜像时也发（三 V1).
        Se o envio falhar, o robotd para por conta própria após 0,5 s sem receber comandos."""
        self.motion_studio.invalidate(why, None if clear_all else conn)
        self.motion_studio.tick()
        self._action_stop(conn, why)
        self._request_clear(None if clear_all else conn, why)
        if self.robot is None:
            return
        with self._send_lk:
            with self._lk:
                now = self.clock()
                if conn is not None:
                    q = self._seq_of(conn)
                    q["stop"] = max(q["stop"], q["hi"])     # não incrementa; o próximo quadro da página continua válido（审查二 一般 1）
                was = self._web_driving
                self._web_driving = False
                attached, _ = self._pad_attached(now)
                send = was or not attached
                if send:
                    self.virtual.update(last=[0.0, 0.0, 0.0], at=now)
            if send:
                try:
                    self._notify_output("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
                except (Unreachable, Timeout) as e:
                    self.log.warn("Falha ao enviar “Parar”", cat="Segurança", step="robot.move", raw=str(e),
                                  hint="O Microduck para após 0,5 s sem comando (deadman do robotd)")
        self._flush_clears(force=True)
        if was:
            self.log.info(f"Controle virtual liberado（{why}）", cat="Controle")

    # ================= Limpeza de cabeça/corpo (3 V1) e modos =================

    def _mode_of(self, conn):
        m = self._modes.get(conn)
        return m["mode"] if m else "drive"

    def _request_clear(self, conn, why, delay=0.0, say=True):
        """Agenda a limpeza de cabeça/corpo definidos por conn (conn=None limpa os de todas as páginas), sai dos modos de cabeça/corpo e solta botões mantidos.
        **Altera somente a memória; não acessa a rede nem lança exceções**: pode ser chamado no loop de eventos (note_relax, feed_robot, mark_gone). O envio real ocorre em _flush_clears.
        Sempre agenda a limpeza, mesmo que _latch ainda não tenha registro (revisão R1): o primeiro quadro de cabeça/corpo pode estar em trânsito e ainda não ter atualizado _latch.
        Aquele quadro mantém _send_lk entre a segunda verificação e a gravação de _latch; _flush_clears também usa _send_lk, então espera e vê o registro. Se não houver registro, descarta a limpeza.
        say=False significa que o chamador registra a saída do modo, evitando duplicar a mesma mensagem."""
        try:
            with self._lk:
                now = self.clock()
                self._clears.append({"conn": conn, "why": why, "due": now + delay, "tries": 0})
                for c in [c for c, x in self._mode_exit.items() if now - x["at"] > 10]:
                    self._mode_exit.pop(c, None)          # visível para a página por 10 s; depois expira para evitar crescimento contínuo (revisão R9)
                for c in list(self._modes):
                    if conn is None or c == conn:
                        m = self._modes.pop(c)
                        self._mode_exit[c] = {"why": why, "at": now}
                        if say:
                            self.log.info(f"Saiu do modo {MODE_CN[m['mode']]}（{why}）", cat="Controle", dedup=False)
                for c, st in self._keys.items():
                    if conn is None or c == conn:
                        st["end"] = st.get("end") or why
                if conn is None:
                    self._x_armed.clear()
                else:
                    self._x_armed.pop(conn, None)
            self._tick_evt.set()
        except Exception:  # noqa: BLE001 —— erros aqui não podem interromper o relaxamento ou a desconexão
            pass

    def _flush_clears(self, force=False):
        """Envia limpezas vencidas (chamado na thread: thread de segundo plano, _halt, drive off e drop_client). Envia zeros para a cabeça e {"active": false} para o corpo.
        Só envia para valores realmente definidos pela página (registrados em _latch). A decisão e o envio usam _send_lk, sem intercalar com a verificação e o envio dos quadros dos analógicos."""
        if self.robot is None:
            with self._lk:
                self._clears.clear()
            return
        with self._send_lk:
            with self._lk:
                now = self.clock()
                due = [c for c in self._clears if force or c["due"] <= now]
                if not due:
                    return
                ids = {id(c) for c in due}
                self._clears = [c for c in self._clears if id(c) not in ids]
                sends = []
                for kind, method, params in (("head", "robot.head", HEAD_ZERO), ("body", "robot.pose", POSE_OFF)):
                    lat = self._latch[kind]
                    if lat is None:
                        continue
                    hit = next((c for c in due if c["conn"] is None or c["conn"] == lat["conn"]), None)
                    if hit is not None:
                        self._latch[kind] = None
                        sends.append((kind, method, params, hit, lat))
            for kind, method, params, req, lat in sends:
                try:
                    self._notify_output(method, dict(params))
                    self.log.info(("cabeça recentralizada" if kind == "head" else "corpo voltou ao centro e saiu do modo corpo") + f" ({req['why']})",
                                  cat="Controle", raw=f"{method} {json.dumps(params)}", dedup=False)
                except (Unreachable, Timeout) as e:
                    with self._lk:
                        if self._latch[kind] is None:
                            self._latch[kind] = lat                 # ainda consta como definido pela página: tenta novamente em 1 s, até 3 vezes
                        if req["tries"] < 2:
                            self._clears.append(dict(req, due=self.clock() + 1.0, tries=req["tries"] + 1))
                    self.log.warn("Não foi possível recentralizar cabeça/corpo", cat="Segurança", step=method, raw=str(e),
                                  hint=("tente novamente em 1 s" if req["tries"] < 2 else "3 tentativas de envio falharam: ") +
                                  "se o modo corpo continuar ativo, o Microduck não poderá andar; pressione B duas vezes ou relaxe o torque e depois fique em pé")

    def _mode_op(self, args, conn, by):
        """Processa Y/B do controle virtual (alternar entre modo cabeça, modo corpo e modo Andar) e heartbeat a cada segundo nos modos cabeça/corpo (3 V6 e V11).
        Entrar no modo não envia comandos, como no padd; se a página estiver andando, envia “Parar” uma vez. Ao sair do modo, limpa cabeça/corpo definidos por esta página.
        É possível alternar mesmo sem a política em execução, como no padd; os quadros dos analógicos serão descartados (3 V12)."""
        mode = args.get("mode")
        if mode not in MODES:
            raise Refused(f"Modo desconhecido: {mode}")
        seq = self._seq(args)
        now = self.clock()
        stop_first = False
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou，a solicitação antiga de modo foi descartada", "mode": self._mode_of(conn)}
            if conn in self._gone:
                raise Refused("Esta página já foi desconectada")
            cur = self._mode_of(conn)
            if mode != "drive":
                if conn in self._closed:
                    return {"dropped": "Esta página está fora da área do controle", "mode": cur}
                if self._pad_attached(now)[0]:
                    raise Refused(MIRROR_SVG)
            if args.get("hb"):
                # O heartbeat (uma vez por segundo nos modos de cabeça/corpo) só renova a presença; **não entra no modo**. Se o backend já encerrou o modo
                # (relaxamento, política parada, 3 s sem heartbeat, controle assumido ou controle físico conectado), o heartbeat não pode reativá-lo; o backend é a referência (revisões R3 e 3 V6).
                # O heartbeat não altera a sequência do modo; uma mensagem antiga que chegar atrasada também será recusada.
                if mode == cur:
                    if mode != "drive":
                        self._modes[conn]["hb"] = now
                    return {"mode": cur}
                why = (self._mode_exit.get(conn) or {}).get("why")
                return {"mode": cur, "dropped": f"O backend já saiu de {MODE_CN.get(mode, mode)}" + (f"（{why}）" if why else "")}
            q = self._seq_of(conn)
            if seq is not None:
                if seq <= q["mode"]:
                    return {"dropped": "Antiga", "mode": cur}
                q["mode"] = seq
            ex = self._mode_exit.get(conn)
            if mode == "drive":
                self._mode_exit.pop(conn, None)         # voltar ao modo Andar indica que a página recebeu a saída do modo pelo backend (o frontend envia isso ao acompanhar o backend)
            elif cur == "drive" and ex is not None:
                # O backend acabou de sair do modo por esta página, mas ela ainda não voltou a “Andar”. Um pedido para entrar no modo cabeça/corpo provavelmente chegou
                # antes de a página receber a notificação de saída (heartbeat anterior à atualização do estado); não reativa o modo (revisões R3 e 3 V6). Depois que a página voltar a “Andar”, pode entrar novamente.
                return {"dropped": f"O backend já saiu de {MODE_CN[mode]}（{ex['why']}）：volte ao modo Andar e pressione novamente", "mode": cur}
            note = MODE_IDLE if mode != "drive" and self._posture() not in DRIVING else None
            if mode == cur:
                if mode != "drive":
                    self._modes[conn]["hb"] = now
                return {"mode": cur, "note": note}
            if cur != "drive":
                self._modes.pop(conn, None)
                # Sempre agenda (revisão R1): o primeiro quadro de cabeça/corpo desta página pode estar em trânsito; _flush_clears aguarda sob _send_lk até ele atualizar _latch
                self._clears.append({"conn": conn, "why": f"saída do modo {MODE_CN[cur]}", "due": now, "tries": 0})
            if mode != "drive":
                self._modes[conn] = {"mode": mode, "hb": now}
                d = self._driver
                stop_first = self._web_driving and d is not None and d["conn"] == conn
            q["stop"] = max(q["stop"], q["hi"])            # invalida quadros dos analógicos anteriores à troca de modo
        self.log.info(f"Controle virtual {'Y' if 'head' in (mode, cur) else 'B'} → {MODE_CN[mode]} ({by or 'página'})"
                      + (f"：{note}" if note else ""), cat="Controle", dedup=False)
        if stop_first:
            self._stop_move({}, conn, by)                  # padd envia move 0 a cada ciclo nos modos cabeça/corpo (padd:1427-1448)
        self._flush_clears(force=True)
        return {"mode": mode, "note": note}

    # ================= relaxamento de torque（审查二 I2） =================

    def note_relax(self, by=None, why="Torque relaxado"):
        """顶上「relaxamento de torque」 e 空格 e 图上 Select 按下的那一刻：app 的 run_relax 在事件循环里同步调（只占锁 e 不碰网络，不抛).
        记下relaxamento de torque时间（2 秒内不接受上力） e 叫停正在做的动作 e cabeça/corpo的清理排到relaxamento de torque之后 (3 V1, item 5)。
        图上十字右（重启舵机，programa principal会先relaxamento de torque de todo o corpo）收下以后也调，why 写它。"""
        try:
            with self._lk:
                self._relax_at = self.clock()
                self._relax_noted += 1
                self.motion_studio.invalidate(why)
                a = self._action
                if a is not None:
                    a["why"] = a["why"] or why
                    a["stop"].set()
            self._request_clear(None, why, RELAX_CLEAR_DELAY_S)
            self._test_evt.set()
        except Exception:  # noqa: BLE001 —— relaxamento de torque路上不能因为手柄页出错
            pass

    def _relax_seen(self, view, now):
        """feed_robot 里调（拿着锁）：relaxamento de torque计数变了 e 或者回读扭矩从开变关（手柄 Select e robotctl e 摔倒 e 低电量），都记成relaxamento de torque。
        返回 True = 这一下是新的relaxamento de torque。"""
        new = False
        presses = view.get("estop_presses")
        if isinstance(presses, int) and not isinstance(presses, bool):
            if self._relax_presses is not None and presses > self._relax_presses:
                new = True
            self._relax_presses = presses
        bus = view.get("bus")
        if isinstance(bus, dict) and bus.get("mode") in ("motion", "commissioning"):
            on = bool((bus.get("native") or {}).get("torque_state_confirmed") is True) if bus.get("mode") == "motion" \
                else bus.get("torque_state") == "on"
            off = torque_off(bus) or relaxed(bus) is True
            if self._torque_was is True and off:
                new = True
            self._torque_was = True if on else (False if off else self._torque_was)
        if new:
            self._relax_at = now
        return new

    def _drive_feed(self, view):
        """feed_robot 里调（拿着锁，事件循环里：只改内存）：Studio 第一次看到programa principal在 → 排一次 pose 复位；
        姿势sair「准备好走」→ 退出模式 e 清掉cabeça/corpo（三 V1 第 8 条 e V12)."""
        self.motion_studio.policy_feed(view)
        if self._pose_reset == "pending" and view.get("present") is True:
            self._pose_reset = "due"
            self._tick_evt.set()
        drv = self._posture() in DRIVING
        if not drv and not self.motion_studio.posture_allowed():
            self.motion_studio.invalidate("策略sair准备好走的状态")
        left = self._was_driving and not drv
        self._was_driving = drv
        if left and (self._modes or self._latch["head"] is not None or self._latch["body"] is not None):
            self._request_clear(None, f"策略Interrompida（Agora {POSTURE_CN.get(self._posture(), self._posture())}）")

    def _relax_block(self, now):
        r = self._robot or {}
        if r.get("estop_active"):
            return "正在relaxamento de torque，等它确认完再说"
        guard = self.w.get("relax_guard", RELAX_GUARD_S)
        if now - self._relax_at < guard:
            return f"刚卸了力：{guard:g} 秒内不接受让它动的指令（防止刚relaxamento de torque又被顶起来）"
        return None

    # ================= 速度上限（审查 24） e cabeça/boca幅度（三 V9） =================

    def _speed_limits(self, now=None):
        """padd 的满杆速度是命令行参数（padd main.rs:158-168），padd.service 的 ExecStart 没带参数（padd/systemd/padd.service:36）
        就是Padrão oficial。文件在后台线程里读（_refresh_files），这里只拿缓存（审查二 一般 9)."""
        return self._limits

    def _read_padd_texts(self):
        texts = []
        try:
            texts.append((PADD_UNIT, self.read_text(PADD_UNIT)))
        except Exception:  # noqa: BLE001 —— 没这个文件 / 没权限：用Padrão oficial
            pass
        try:
            for name in sorted(self.list_dir(PADD_DROPIN_DIR)):
                if name.endswith(".conf"):
                    p = os.path.join(PADD_DROPIN_DIR, name)
                    texts.append((p, self.read_text(p)))
        except Exception:  # noqa: BLE001
            pass
        return texts

    def _read_inputs(self, texts):
        """cabeça/boca幅度（三 V9）+ padd 读配置的地方（--config，没写就是 robotd.toml padrão路径：fork padd/src/main.rs 的 Args).
        先看 padd 自己写的回执 /run/padd/input-settings.json（fork input_settings.rs:63-74：它真用上了才写，里面是它正在用的数），
        写回执的那个 padd 还活着 e 文件路径对得上就以它为准（审查 R10）；没有再自己按 padd 的规矩读文件。"""
        inputs = parse_padd_inputs(texts)
        text, err, ack = None, None, None
        if inputs["input_settings"]:
            try:
                text = self.read_text(inputs["input_settings"])
            except FileNotFoundError:
                err = "文件不在"
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            try:
                a = json.loads(self.read_text(PADD_INPUT_ACK))
                pid = a.get("pid") if isinstance(a, dict) else None
                alive = isinstance(pid, int) and not isinstance(pid, bool) and self.exists(f"/proc/{pid}")
                if alive and a.get("path") == inputs["input_settings"]:
                    ack = a.get("settings")
            except Exception:  # noqa: BLE001 —— 没有回执（padd 没读过这个文件 e 电脑上）：自己读
                pass
        return input_limits(inputs, text, err, ack), inputs["config"]

    # ================= 网页摇杆 =================

    def _seq(self, args):
        seq = args.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int):
            return None
        return seq

    def _gate(self, conn, now):
        """comando contínuo（摇杆的 move / head / pose e 按住的键）共同的挡（在 _lk 里调).
        返回 None = 放行；返回 dict = 悄悄丢掉（páginaJá 走了）；不能做就抛 Refused（原因给página看)."""
        if conn in self._gone:
            return {"dropped": "A página já foi desconectada"}
        if conn in self._closed:
            return {"dropped": "Esta página está fora da área do controle"}
        attached, _ = self._pad_attached(now)
        if attached:
            if not self._pad_said:
                self._pad_said = True
                self.log.info("Controle físico conectado: o controle virtual apenas acompanha e não envia comandos", cat="Controle")
            raise Refused("Controle físico conectado: o controle virtual apenas acompanha e não envia comandos（padd 哪怕没人碰也每 0.1 秒发一次「停」，"
                          "e sobrescreveria os comandos da página). Desligue o controle físico para usar o controle virtual")
        self._pad_said = False
        ok, why = self._robot_ok(now)
        if ok is not True:           # 审查 14：不知道programa principal在不在运动模式，也不放行
            raise Refused(f"Não é possível controlar agora: {why or 'Não foi possível ler o estado do programa principal'}")
        block = self._relax_block(now)
        if block:
            raise Refused(block)
        return None

    def _send_intent(self, chan, method, params, conn, by, seq, mode=None):
        """发一帧comando contínuo（move / head / pose 通知）：过 _gate e 按序号挡Antigo e 拿方向盘 e 同一通道 40 ms 内只发最新的。
        检查和发送在 _send_lk 里，robotd 收到的顺序就是这里定的顺序。mode：cabeça/corpo帧发之前再看一眼模式没变（三 V6).
        返回 (结果 dict, 发出去了吗)。"""
        now = self.clock()
        motion_epoch = self.motion_studio.epoch
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou; o comando antigo foi descartado"}, False
            g = self._gate(conn, now)
            if g:
                return g, False
            if mode is not None and self._mode_of(conn) != mode:
                return {"dropped": f"模式对不上：后端Agora 是「{MODE_CN[self._mode_of(conn)]}」", "mode": self._mode_of(conn)}, False
            q = self._seq_of(conn)
            if seq is None:
                seq = q["hi"] + 1        # página没给序号：按到达的先后排
            if seq <= q["stop"] or seq <= q["sent"].get(chan, -1):
                return {"dropped": "Comando antigo (o botão já foi solto)"}, False
            self._take_lease(conn, by, now)
            q["hi"] = max(q["hi"], seq)
            q["latest"][chan] = max(q["latest"].get(chan, -1), seq)
            gap = MOVE_MIN_GAP_S - (now - self._last_sent_at.get(chan, -1e9))
        if self.robot is None:
            raise Refused("O endereço do programa principal não está configurado para este Microduck")
        if self._clears:
            self._flush_clears()         # 方向盘刚换了人：先把原来那个página的cabeça/corpo清掉
        if gap > 0:
            self._cancel_wait(gap)
        with self._send_lk:
            with self._lk:
                d, q = self._driver, self._seq_of(conn)
                if (not self.motion_studio.request_current() or motion_epoch != self.motion_studio.epoch or conn in self._gone or conn in self._closed or seq != q["latest"].get(chan) or seq <= q["stop"]
                        or d is None or d["conn"] != conn or (mode is not None and self._mode_of(conn) != mode)):
                    return {"dropped": "被更新的指令替掉了，或者Já 松手"}, False
                q["sent"][chan] = seq
                self._last_sent_at[chan] = self.clock()
            try:
                self._notify_output(method, params)
            except (Unreachable, Timeout) as e:
                raise Refused(f"Falha ao enviar: {e}") from None
            with self._lk:
                if chan in ("head", "body"):
                    nonzero = any(abs(v) > 1e-9 for k, v in params.items() if k != "active")
                    self._latch[chan] = {"conn": conn, "nonzero": nonzero, "at": self.clock()}
                    self._tick_evt.set()
        return {"merged": gap > 0}, True

    def _move(self, args, conn=None, by=None, mode="drive"):
        """Andar的一帧（Antigo move 通道和 sticks 的Andar模式都走这里).mode：这一帧是哪个模式下的，后端模式不是它就丢——
        查完模式到发出去之间切到了cabeça / modo corpo，也不会在cabeça / modo corpo里发出速度（审查 R6 e 三 V6)."""
        try:
            vals = [float(args.get(k, 0) or 0) for k in ("vx", "vy", "vyaw")]
        except (TypeError, ValueError):
            raise Refused("A velocidade deve ser um número") from None
        if not all(math.isfinite(v) for v in vals):
            raise Refused("A velocidade deve ser finita")
        lim = self._speed_limits()
        vx = max(-lim["v"], min(lim["v"], vals[0]))
        vy = max(-lim["v"], min(lim["v"], vals[1]))
        vyaw = max(-lim["w"], min(lim["w"], vals[2]))
        with self._lk:
            start = not self._web_driving and any((vx, vy, vyaw))
        r, sent = self._send_intent("move", "robot.move", {"vx": vx, "vy": vy, "vyaw": vyaw}, conn, by, self._seq(args),
                                    mode=mode)
        if not sent:
            return r
        with self._lk:
            self._web_driving = any((vx, vy, vyaw))
            self.virtual.update(last=[vx, vy, vyaw], at=self.clock())
        if start:
            self.log.info(f"网页遥控开始开（{by or 'página'}，robot.move）", cat="Controle")
        return {"sent": [vx, vy, vyaw], "merged": r["merged"]}

    def _sticks(self, args, conn=None, by=None):
        """网页手柄的摇杆（图上的两个 e 下面两个大的共用这一个通道，三 V6 e V20）：{mode, lx, ly, rx, ry, seq}，
        -1..1 e x 向右 e y 向下为正。后端按 padd 的公式换算（sticks_to_intent），模式以后端记的为准：对不上就丢 e 告诉página。"""
        mode = args.get("mode", "drive")
        if mode not in MODES:
            raise Refused(f"Modo desconhecido: {mode}")
        try:
            vals = [float(args.get(k, 0) or 0) for k in ("lx", "ly", "rx", "ry")]
        except (TypeError, ValueError):
            raise Refused("Os valores dos analógicos devem ser números") from None
        if not all(math.isfinite(v) for v in vals):
            raise Refused("Os valores dos analógicos devem ser finitos")
        lx, ly, rx, ry = (max(-1.0, min(1.0, v)) for v in vals)
        now = self.clock()
        with self._lk:
            cur = self._mode_of(conn)
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou; a solicitação antiga dos analógicos foi descartada", "mode": cur}
            if conn in self._gone or conn in self._closed:
                return {"dropped": "A página já saiu da área do controle", "mode": cur}
            if mode != cur:
                why = (self._mode_exit.get(conn) or {}).get("why")
                return {"dropped": f"模式对不上：后端Agora 是「{MODE_CN[cur]}」" + (f"（{why}）" if why else ""), "mode": cur}
            if cur != "drive":
                self._modes[conn]["hb"] = now
                if self._posture() not in DRIVING:
                    self._gate(conn, now)           # 镜像 e relaxamento de torque这些照样先说
                    return {"dropped": MODE_IDLE, "mode": cur}
                a = self._action
                if cur == "head" and a is not None and any(C.head_at(s, 0.0) is not None for s in a["steps"]):
                    raise Refused(f"Executando “{a['name']}」（也在动cabeça）：aguarde terminar ou solte o botão primeiro")
        method, params = sticks_to_intent(cur, lx, ly, rx, ry, self._speed_limits(), self._inputs["head"])
        if cur == "drive":
            r = self._move(dict(params, seq=args.get("seq")), conn, by, mode="drive")
            return dict(r, mode=self._mode_of(conn))
        r, sent = self._send_intent(cur, method, params, conn, by, self._seq(args), mode=cur)
        if sent:
            return {"sent": params, "mode": cur, "merged": r["merged"]}
        return dict(r, mode=cur)

    def _cancel_wait(self, s):
        threading.Event().wait(s)

    def _stop_move(self, args=None, conn=None, by=None):
        """松手：Andar模式发一次 move 0；modo cabeçacabeça recentralizada e modo corpocorpo recentralizado（还在modo corpo：{0,0,0,active:true}，三 附 2).
        不在服务端重复发：浏览器断了，robotd 的 deadman 500 ms 后自己清零（safety.rs:226-237），cabeça/corpo靠看门狗。
        镜像时网页没在开就不发 move 0（不去打断实体手柄）；别的情况多发一次 0 不危险，照发。"""
        if self.robot is None:
            return {}
        args = args or {}
        with self._send_lk:
            with self._lk:
                if not self.motion_studio.request_current():
                    return {"dropped": "A sessão de movimento mudou; a solicitação antiga para parar foi descartada"}
                now = self.clock()
                q = self._seq_of(conn)
                seq = self._seq(args)
                if seq is None:
                    seq = q["hi"] + 1
                q["stop"] = max(q["stop"], seq)
                q["hi"] = max(q["hi"], seq)
                d = self._driver
                mine = d is None or d["conn"] == conn
                if d is not None and d["conn"] == conn:
                    d["seen"] = now
                attached, _ = self._pad_attached(now)
                send = self._web_driving or not attached
                center = None
                mode = self._mode_of(conn)
                lat = self._latch.get(mode) if mode != "drive" else None
                if lat is not None and lat["conn"] == conn and lat["nonzero"]:
                    center = ("robot.head", HEAD_ZERO) if mode == "head" else ("robot.pose", POSE_CENTER)
                    lat.update(nonzero=False, at=now)
            if send:
                try:
                    self._notify_output("robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0})
                except (Unreachable, Timeout) as e:
                    raise Refused(f"Falha ao enviar “Parar” (o Microduck também interrompe sozinho após 0,5 s sem receber comandos): {e}") from None
            if center is not None:
                try:
                    self._notify_output(center[0], dict(center[1]))
                except (Unreachable, Timeout) as e:
                    with self._lk:
                        lat.update(nonzero=True)            # 看门狗 0.6 秒后再试
                    raise Refused(f"Não foi possível recentralizar (nova tentativa em 0,6 s): {e}") from None
            with self._lk:
                was = self._web_driving and mine
                if mine and send:
                    self._web_driving = False
                    self.virtual.update(last=[0.0, 0.0, 0.0], at=self.clock())
        if was:
            self.log.info("Controle virtual liberado", cat="Controle")
        return {"sent": send, **({"centered": True} if center is not None else {})}

    # ================= 按住的键：LT / RT / X (3 V4) =================

    def _keys_op(self, args, conn, by):
        """{held:[按着的], down:[这一下刚按下的], seq}。página按下 e 松开时发，按住期间每 0.15 秒也发一次。
        只认「后端Já 记着的」和「这一下刚按下的」：后端中途叫Interrompida（relaxamento de torque e 被接管……），página的心跳再报着也不会自己续上，
        要松开重按（回给página ended).真正发给 robotd 的在后台线程（_keys_plan)."""
        held, down = args.get("held"), args.get("down") or []
        if not isinstance(held, list) or not isinstance(down, list) or any(k not in HELD_KEYS for k in held + down):
            raise Refused("held / down só podem conter lt, rt e x")
        seq = self._seq(args)
        now = self.clock()
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou; a solicitação antiga dos botões foi descartada", "held": []}
            if conn in self._gone or conn in self._closed:
                return {"dropped": "A página já saiu da área do controle", "held": []}
            st = self._keys.get(conn)
            q = self._seq_of(conn)
            if seq is not None:
                if seq <= q["keys"]:
                    return {"dropped": "Antiga", "held": sorted(st["held"]) if st is not None and not st.get("end") else []}
                q["keys"] = seq
            had = set(st["held"]) if st is not None and not st.get("end") else set()
            want = set(held)
            pressed = (set(down) & want) - had
            keep = (want & had) | pressed
            ended = sorted(want - keep)
            if pressed:
                attached, _ = self._pad_attached(now)
                if attached:
                    raise Refused(MIRROR_SVG)
                base = self._base_block(now)
                if base:
                    raise Refused(base)
                a = self._action
                if pressed & {"lt", "rt"} and a is not None and any(C.mouth_at(s, 0.0) is not None for s in a["steps"]):
                    raise Refused(f"Executando “{a['name']}」（也在动嘴）：aguarde terminar ou solte o botão primeiro")
                self._take_lease(conn, by, now)
            if st is None or st.get("end"):
                if not keep:
                    return {"held": [], "ended": ended}
                st = self._keys[conn] = {"held": {}, "started": now, "by": by, "mouth": False, "rt": False,
                                         "wheee": False, "x_down": None, "end": None,
                                         **({k: st[k] for k in ("mouth", "wheee")} if st is not None else {})}
            released = set(st["held"]) - keep
            for k in released:
                st["held"].pop(k, None)
                if k == "x":
                    self._x_armed.pop(conn, None)
            for k in keep:
                st["held"][k] = now
            if "x" in pressed:
                st["x_down"] = now
                self._x_armed.pop(conn, None)     # 新的一下：上一下 X 的 arm 作废（审查 R5）
            if keep:
                self._touch_lease(conn, now)
        for k in sorted(pressed):
            self.log.info(f"Controle virtual: {KEY_CN[k]} pressionado ({by or 'página'})", cat="Controle", dedup=False)
        for k in sorted(released):
            self.log.info(f"Controle virtual: {KEY_CN[k]} solto", cat="Controle", dedup=False)
        self._tick_evt.set()
        return {"held": sorted(keep), "ended": ended}

    def _keys_abort(self, conn, st, now):
        """按住的键要不要中途叫停（在 _lk 里调）：原因照搬 _abort_reason。"""
        if conn in self._gone or conn in self._closed:
            return "A página saiu da área do controle"
        if self._pad_attached(now)[0]:
            return "Controle físico conectado"
        d = self._driver
        if d is None or d["conn"] != conn:
            return "Controle assumido por outra página"
        if self._relax_at >= st["started"] or (self._robot or {}).get("estop_active"):
            return "Torque relaxado"
        return self._base_block(now)

    def _keys_plan(self, now, sends, logs):
        """后台线程每拍调（在 _lk 里）：按「按着哪些键」排这一拍要发的（fork padd:1351-1396 e 1182-1211)."""
        for conn, st in list(self._keys.items()):
            why = st.get("end") or self._keys_abort(conn, st, now)
            if why:
                fresh = set()
            else:
                fresh = {k for k, at in st["held"].items() if now - at < (X_HOLD_S if k == "x" else KEYS_HOLD_S)}
            lt, rt, x = "lt" in fresh, "rt" in fresh, "x" in fresh
            mouth = (lt or rt) and self._relax_block(now) is None       # 刚卸了力：只叫 e 不动嘴
            if mouth or st["mouth"]:
                sends.append(("robot.mouth", {"open": round(self._inputs["mouth"] / 100.0, 3) if mouth else 0.0}, None))
                st["mouth"] = mouth
            if rt and not st["rt"]:
                sends.append(("robot.sound", {"tag": "chirp"}, None))        # RT 按下那一下（padd 是过 0.3 的上升沿）
            st["rt"] = rt
            if lt:
                sends.append(("robot.sound", {"tag": "wheee", "hold": True}, None))
                st["wheee"] = True
            elif st["wheee"]:
                sends.append(("robot.sound", {"tag": "wheee", "hold": False}, None))   # 不带 hold 等于 true（intents.rs:443-452）
                st["wheee"] = False
            arm = self._x_armed.get(conn)
            if x and arm is not None and arm["x_down"] == st.get("x_down") \
                    and self._posture() in DRIVING and self._relax_block(now) is None:
                sends.append(("robot.do", {"skill": arm["skill"]}, None))   # 连滚：robotd 只刷新 0.15 秒的窗口（control.rs:429-434）
            gone = set(st["held"]) - fresh
            if gone:
                reason = why or "a página não informou que continua pressionado por 0,45 s (soltou, mudou de página ou perdeu a conexão)"
                logs.append(("安全" if why in (None, "Torque relaxado") else "手柄",
                             f"网页手柄 {' e '.join(KEY_CN[k] for k in sorted(gone))} Interrompida：{reason}"))
                for k in gone:
                    st["held"].pop(k, None)
                if "x" in gone:
                    self._x_armed.pop(conn, None)
            if why:
                st["end"] = why
            if not st["held"] and not st["mouth"] and not st["wheee"]:
                del self._keys[conn]

    def _key_press(self, args, conn, by):
        """网页手柄图上的一次性键：A / X / LB / RB / 十字下（三 V14 e V16).按 pad.bindings 做（读不到用Padrão oficial）：
        绑的是 sit_toggle → 按坐没坐走「Ficar em pé / Sentar」；空 = 关掉了；有 error = Este Microduck没有。X 按下这一下的请求被接受了，
        按住才连滚（_keys_plan 每拍发通知，方案 C)."""
        key = args.get("key")
        if key not in BIND_KEYS:
            raise Refused(f"Botão desconhecido: {key}")
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        if self.robot is not None and now - self._bindings_at > BINDINGS_STALE_S:
            self._fetch_bindings()
        with self._lk:
            mv = self._motion_view(self.clock())
        row = mv["keys"][key]
        name = KEY_CN[key]
        if not row["ok"]:
            self.log.info(f"网页手柄 {name}：não pode ser pressionado（{row['why']}）", cat="Controle")
            raise Refused(row["why"])
        self.log.info(f"网页手柄 {name} → {row['does']}（{by or 'página'}）", cat="Controle", dedup=False)
        label = f"网页手柄 {name} → {row['does']}"
        if row["op"] == "skill":
            with self._lk:
                st = self._keys.get(conn)
                x_down0 = st.get("x_down") if st is not None else None    # 这一下 X 是哪一下（keys 通道可能还没到：None）
            r = self._motion_cmd("skill", {"name": row["skill"]}, conn, by, label=label)
            if key == "x":
                # arm 绑在发请求的那一下 X 上（审查 R5）：_keys_plan 只在「Agora 按着的这一下」的 x_down 跟它一样时才连滚。
                # 快速点一下 e 松手以后请求才回话：记下的是上一下的 x_down，下一下 X 新按下时 _keys_op 先扔掉它，也对不上，
                # 下一下的请求被拒了也不会照着它连滚。keys 通道比请求晚到（x_down0 是 None）：X 还按着就用Agora 这一下
                with self._lk:
                    st = self._keys.get(conn)
                    if x_down0 is None and st is not None and not st.get("end") and "x" in st["held"]:
                        x_down0 = st.get("x_down")
                    if x_down0 is not None:
                        self._x_armed[conn] = {"skill": row["skill"], "x_down": x_down0}
                self._tick_evt.set()
            return r
        return self._motion_cmd(row["op"], {}, conn, by, label=label)

    def _start(self, args, conn, by):
        """Start do controle virtual（三 V7 e V8）：按Agora 的姿势挑「Parar (ficar em pé)/ Começar a andar / Ficar em pé」，跟página看到的（expect）不一样就拒。"""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            st = self._motion_view(now)["start"]
        expect = args.get("expect")
        if expect is not None and expect != st["op"]:
            self.log.info(f"网页手柄 Start：página以为是「{expect}」，后端判的是「{st['label']}」，没发", cat="Controle")
            raise Refused(f"O estado mudou; pressione novamente（Agora 按 Start 会「{st['label']}」）")
        if not st["ok"]:
            self.log.info(f"Controle virtual Start: comando indisponível（{st['why']}）", cat="Controle")
            raise Refused(st["why"])
        self.log.info(f"Controle virtual Start → {st['label']}（{by or 'página'}）", cat="Controle", dedup=False)
        return self._motion_cmd(st["op"], {}, conn, by, label=f"Controle virtual Start → {st['label']}")

    def _reboot(self, args, conn, by):
        """网页手柄图上的十字右：重启全部舵机（照官方：按一下就发 e 不用确认).不看方向盘 e 不占「上一个还没回话」：
        跟relaxamento de torque一样是救急的路。programa principal先relaxamento de torque de todo o corpo再重启（fork handover 版 main.rs:2731-2758），收下以后这边记一次relaxamento de torque。"""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            mv = self._motion_view(now)
        row = mv["reboot"]
        what = "Controle virtual: direcional para a direita → reiniciar todos os servos"
        if not row["ok"]:
            self.log.info(f"Controle virtual: não foi possível usar o direcional para a direita（{row['why']}）", cat="Controle")
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": row["why"], "at": now}
            raise Refused(row["why"])
        self.log.info(f"{what}（{by or 'página'}）", cat="Controle", dedup=False)
        try:
            r = self._call(what, "robot.rebootMotors", {"ids": []}, by, {"posture": mv["posture"]})
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        self.note_relax(by, "重启舵机（programa principal先relaxamento de torque de todo o corpo）")
        note = r.get("reason") if isinstance(r, dict) else None
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": "reboot"}

    def _drive_mode(self, args, conn, by):
        """网页手柄图上十字上按住 3 秒：Andar ⇄ Rodas（照官方 padd:766-806).3 秒在página上算，到了发 {expect: 要切到的}；
        跟后端判的不一样就拒（状态刚变了).programa principal收下会叫一声（Andar）/ 两声（Rodas） e 回站姿 e 换上那个模式的策略
        （fork handover 版 main.rs:2870-2930）；没装Rodas模型它会拒。"""
        now = self.clock()
        if args.get("src") == "svg" and self._pad_attached(now)[0]:
            raise Refused(MIRROR_SVG)
        with self._lk:
            mv = self._motion_view(now)
            row = mv["drive_mode"]
            target = row["target"]
            what = f"Controle virtual: segure o direcional para cima por 3 s → alternar para{DRIVE_MODE_CN.get(target, '另一个模式')}"
            why = row["why"]
            expect = args.get("expect")
            if why is None and expect is not None and expect != target:
                why = f"O estado mudou; mantenha pressionado novamente（Agora 会{row['does'].replace('按住 3 秒：', '')}）"
            if why is None and self._cmd_busy:
                why = "O comando anterior ainda não respondeu; aguarde"
            if why is None:
                held = self._lease_holder(now)
                if held is not None and held["conn"] != conn:
                    why = f"{held['by'] or 'outra página'}está movendo os analógicos; aguarde soltar ou clique em “Assumir”"
            if why is not None:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": why, "at": now}
            else:
                self._cmd_busy = True
        if why is not None:
            self.log.info(f"Controle virtual: não foi possível alternar（{why}）", cat="Controle")
            raise Refused(why)
        self.log.info(f"{what}（{by or 'página'}）", cat="Controle", dedup=False)
        try:
            r = self._call(what, "robot.setMode", {"mode": target}, by, {"posture": mv["posture"], "mode": row["current"]})
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        finally:
            with self._lk:
                self._cmd_busy = False
        note = r.get("reason") if isinstance(r, dict) else None
        if note and "already" in note.lower():
            note = f"Já 是{DRIVE_MODE_CN[target]}了"
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": "drive_mode", "target": target}

    # ================= 后台线程：按住的键 e 看门狗 e 清理（25 Hz，没事做就睡） =================

    def _tick_work(self):
        return bool(self.motion_studio.session or self.motion_studio._pending_cleanup or self._keys or self._clears or self._modes or self._pose_reset == "due"
                    or (self._latch["head"] or {}).get("nonzero") or (self._latch["body"] or {}).get("nonzero"))

    def _tick_loop(self):
        while not self._tick_stop.is_set():
            try:
                self._tick_once()
            except Exception as e:  # noqa: BLE001 —— 这个线程不能悄悄死掉：按住的键 e 看门狗都靠它
                key = f"{type(e).__name__}: {e}"[:200]
                if key not in self._tick_said:
                    self._tick_said.add(key)
                    self.log.error("手柄页的后台线程出错（按住的键 e 看门狗）", cat="Controle", raw=key, exc=True,
                                   hint="这是 Studio 的问题，导出诊断包发出来；线程会接着跑")
            with self._lk:
                busy = self._tick_work()
            if busy:
                self._tick_stop.wait(TICK_S)
            else:
                self._tick_evt.wait(1.0)
                self._tick_evt.clear()

    def _tick_once(self):
        if self._update_blocked():
            with self._lk:
                held=bool(self._modes or self._keys or self._latch['head'] or self._latch['body'])
            if held:self._request_clear(None,'A proteção de atualização do software/programa principal continua ativa',say=False)
        self.motion_studio.tick()
        self._flush_clears()                       # 它自己拿 _send_lk：放在下面那把锁之前（Lock 不能重入）
        sends, logs = [], []                       # sends：(方法, 参数, 标记 None / "pose_reset" / "watchdog")
        # 决定和发送在同一把 _send_lk 里（审查 R2，跟 _flush_clears e _stop_move 一个写法）：看门狗决定「回中（active:true）」
        # 以后 e 发出去之前，别的线程不能插进来先发退出（active:false），再被这个回中重新打开——那样 _latch Já 清了，再也没人清
        with self._send_lk:
            with self._lk:
                now = self.clock()
                if self._pose_reset == "due":
                    self._pose_reset = "sending"
                    sends.append(("robot.pose", dict(POSE_OFF), "pose_reset"))
                if self._pad_attached(now)[0] and (self._modes or self._keys or self._latch["head"] or self._latch["body"]):
                    self._request_clear(None, "Controle físico conectado")               # 三 V1 第 6 条（configd 那条路也算）
                for kind, center in (("head", HEAD_ZERO), ("body", POSE_CENTER)):
                    lat = self._latch[kind]
                    if lat is not None and lat["nonzero"] and now - lat["at"] > STICK_STALE_S:
                        lat.update(nonzero=False, at=now)
                        sends.append(("robot.head" if kind == "head" else "robot.pose", dict(center), "watchdog"))
                        logs.append(("安全", f"{'cabeça' if kind == 'head' else 'corpo'}的摇杆 {STICK_STALE_S:g} 秒没有新的一帧（página卡住了？）："
                                           f"{'cabeça recentralizada' if kind == 'head' else 'corpo recentralizado'}"))
                for c, m in list(self._modes.items()):
                    if now - m["hb"] > MODE_HB_S:
                        why = f"A página ficou {MODE_HB_S:g} s sem informar que continua no modo {MODE_CN[m['mode']]}"
                        logs.append(("安全", f"{why}：退出"))
                        self._request_clear(c, why, say=False)          # 同一件事只记「安全」这一行（V19）
                self._keys_plan(now, sends, logs)
            for method, params, tag in (sends if self.robot is not None else []):
                try:
                    self._notify_output(method, params)
                except (Unreachable, Timeout) as e:
                    if tag == "pose_reset":
                        with self._lk:
                            self._pose_reset_tries += 1
                            self._pose_reset = "pending" if self._pose_reset_tries < 3 else "failed"
                    if method not in self._tick_said:
                        self._tick_said.add(method)
                        self.log.warn(f"网页手柄的 {method} Falha ao enviar", cat="Controle", step=method, raw=str(e),
                                      hint="programa principal robotd 不在？嘴 e cabeça没收到也不危险：robotd 自己不动")
                    continue
                self._tick_said.discard(method)
                if tag == "pose_reset":
                    with self._lk:
                        self._pose_reset = "done"
                    self.log.info("Studio 连上programa principal：发了一次 robot.pose {\"active\": false}（清掉上一次可能留下的modo corpo）",
                                  cat="Controle")
        for cat, msg in logs:
            self.log.write(msg, cat=cat, level="info", dedup=False)

    def _drive_close(self):
        """Studio 关闭（pad.close 里调，在线程里）：先停后台线程 e aguarde parar，再尽力把cabeça/corpo清掉 e 按住的键松开（三 V1 第 9 条)."""
        self._tick_stop.set()
        self._tick_evt.set()
        t = self._tick_thread
        if t is not None and t is not threading.current_thread():
            t.join(0.5)       # 等它这一拍发完：不然它排好的「张嘴」可能落在下面的「合嘴」后面，嘴一直张着（审查 R8）
        self.motion_studio.close()
        try:
            self._request_clear(None, "Studio foi fechado")
            self._flush_clears(force=True)
            sends = []
            with self._lk:
                for st in self._keys.values():
                    if st["mouth"]:
                        sends.append(("robot.mouth", {"open": 0.0}))
                    if st["wheee"]:
                        sends.append(("robot.sound", {"tag": "wheee", "hold": False}))
                self._keys.clear()
            if self.robot is not None:
                with self._send_lk:
                    for method, params in sends:
                        try:
                            self._notify_output(method, params)
                        except (Unreachable, Timeout):
                            pass
        except Exception:  # noqa: BLE001 —— best effort durante o encerramento
            pass

    # ================= Ficar em pé / Começar a andar / Sentar / habilidades / sons: disponibilidade =================

    def _update_blocked(self):
        try:return getattr(self,'update_guard',lambda:False)() is True
        except Exception:return True

    def _base_block(self, now):
        """Situações que impedem qualquer ação, independentemente da postura (também bloqueiam sons: no modo de comissionamento, o programa principal é somente leitura，fork main.rs:5379-5396)."""
        if self._update_blocked():return 'A proteção de atualização do software/programa principal continua ativa'
        r = self._robot or {}
        if self._robot_at is None or now - self._robot_at > 3:
            return "O Studio ainda não recebeu o estado do programa principal"
        if r.get("paused"):
            return "Os servos estão sendo ajustados: o programa principal está pausado (a sessão da página de servos ainda está aberta). Clique em “Devolver ao programa principal” no topo da página"
        if r.get("present") is False:
            return "O robotd do programa principal não está em execução"
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else None
        if bus is None or r.get("bus_at") is None or now - r["bus_at"] > 3:
            return "Não foi possível ler o estado do programa principal"
        if bus.get("phase") in STARTING_PHASES:
            return "O programa principal ainda está iniciando"
        if bus.get("mode") == "commissioning":
            return "Modo de comissionamento: o programa principal está somente para leitura e não aceita ações"
        if bus.get("mode") != "motion":
            return f"O programa principal está no modo {bus.get('mode')}"
        return None

    def _policies(self):
        p = (self._robot or {}).get("policies")
        return p if isinstance(p, dict) else None

    def _known_skills(self):
        """Nomes aceitos por robot.do：ground_pick（装了这个槽）+ sit_toggle（装了 sitstand）+ skills（robotd main.rs:4136-4156).
        Se não for possível ler robot.policies, retorna None."""
        p = self._policies()
        if p is None:
            return None
        slots = {s.get("slot"): s for s in p.get("slots") or [] if isinstance(s, dict)}
        names = []
        if (slots.get("ground_pick") or {}).get("path"):
            names.append("ground_pick")
        if (slots.get("sitstand") or {}).get("path"):
            names.append("sit_toggle")
        names += [s for s in p.get("skills") or [] if isinstance(s, str)]
        return names

    def _posture(self):
        r = self._robot or {}
        return "servo_session" if r.get("paused") else (r.get("posture") or "unknown")

    def _skill_why(self, name, need_drive, known, pol):
        """Verifica se uma habilidade pode ser executada agora. Usado pelo botão de habilidade, pelas habilidades em combinações e quando a combinação chega a essa etapa (revisão 2, geral 6)."""
        if known is None:
            return "Não foi possível ler as habilidades disponíveis (robot.policies só pode ser consultado no modo de movimento)"
        if name not in known:
            return f"Este Microduck não tem a habilidade “{C.SKILL_CN.get(name, name)}」"
        if need_drive:
            return need_drive
        if name == "roller_stand" and pol.get("mode") != "roller":
            return "Requer o modelo de rodas e o modo Rodas（手柄十字上按住 3 秒切换）"
        return None

    def _bind_map(self):
        """Retorna as associações dos cinco botões configuráveis (3 V14): {botão: {"skill", "error", "overridden", "src"}}.
        Se pad.bindings não puder ser lido ou não listar um botão, usa o padrão oficial (robotd-params lib.rs:175-215)."""
        rows = {b.get("button"): b for b in self.bindings or [] if isinstance(b, dict)}
        out = {}
        for k in BIND_KEYS:
            b = rows.get(k)
            if b is not None and isinstance(b.get("skill"), str):
                out[k] = {"skill": b["skill"], "error": b.get("error") or None, "overridden": bool(b.get("overridden")),
                          "src": "pad.bindings"}
            else:
                out[k] = {"skill": DEFAULT_BIND[k], "error": None, "overridden": False,
                          "src": "Padrão oficial" + (" (pad.bindings indisponível)" if self.bindings is None else "")}
        return out

    def _key_rows(self, buttons, sitting, skills, skills_why, known, need_drive, pol):
        """Descreve a função e a disponibilidade dos botões A / X / LB / RB / direcional para baixo no controle virtual. A página mostra estes dados e _key_press os revalida ao pressionar."""
        out = {}
        for k, b in self._bind_map().items():
            skill = b["skill"]
            row = {"key": k, "skill": skill, "src": b["src"], "overridden": b["overridden"], "op": None,
                   "does": C.SKILL_CN.get(skill, skill) if skill else " (desativado)"}
            if b["error"]:
                row.update(ok=False, why=f"绑的「{skill}」Este Microduck não pode usar：{b['error']}")
            elif not skill:
                row.update(ok=False, why="Este botão foi desativado (definido como vazio em [pad] no robotd.toml)")
            elif skill == "sit_toggle":
                # 不直接发 robot.do sit_toggle：按坐没坐走「Ficar em pé / Sentar」（审查二 S2，三 V14）
                if sitting is None:
                    row.update(ok=False, why=NO_SIT_INFO, op="sit")
                else:
                    btn = buttons["stand" if sitting else "sit"]
                    row.update(ok=btn["ok"], why=btn["why"], op=btn["op"], does=btn["label"])
            else:
                s = next((x for x in skills if x["name"] == skill), None)
                why = s["why"] if s is not None else (skills_why or self._skill_why(skill, need_drive, known, pol))
                row.update(ok=why is None, why=why, op="skill")
            out[k] = row
        return out

    def _motion_view(self, now):  # noqa: C901
        """推给página：每个按钮能não pode ser pressionado e 为什么不能。服务端按的时候也用这一份再判一遍。"""
        base = self._base_block(now)
        relax = self._relax_block(now)
        block = base or relax
        pose = self._posture()
        pol = self._policies() or {}
        sit_raw = pol.get("sitting")
        sitting = sit_raw if isinstance(sit_raw, bool) else None      # None = 读不到（审查二 S2：不靠猜）
        homed = pol.get("homed") if isinstance(pol.get("homed"), bool) else None
        r = self._robot or {}
        bus = r.get("bus") if isinstance(r.get("bus"), dict) else {}
        policy_on = bus.get("policy_enabled") is True
        torque_on = (bus.get("native") or {}).get("torque_state_confirmed") is True
        batt = r.get("battery_pct")
        job = self._job_alive()
        # 还没站稳（state.posture 判 homing）：programa principal的 home_start_guard 说了原因就带上（比如「机身未直立」），不然人不知道在等什么
        guard = bus.get("home_start_guard") if isinstance(bus.get("home_start_guard"), dict) else {}
        unsteady = "还在Ficar em pé，站稳了再点" + (f"（{guard['reason']}）" if guard.get("ready") is False
                                             and isinstance(guard.get("reason"), str) and guard["reason"] else "")

        def b(op, label, call, why):
            return {"op": op, "label": label, "call": call, "ok": why is None, "why": why}

        # Ficar em pé：坐着要 sit_toggle（还要策略在跑 e 到了 HOME），没坐着才 init；坐没坐读不到就不让点
        stuck = None
        if block:
            stand = b("stand", "Ficar em pé", None, block)
        elif sitting is None:
            stand = b("stand", "Ficar em pé", None, NO_SIT_INFO)
        elif sitting:
            if policy_on and torque_on and (homed is True or bus.get("homed") is True):
                stand = b("stand", "Ficar em pé", "robot.do sit_toggle",
                          None if "sit_toggle" in (self._known_skills() or []) else "Este Microduck没装Sentar / 站起的模型")
            else:
                stuck = ("坐着 e 但策略没在跑（多半是坐着时卸了力）：网页Agora 站不起来——发 init 会跟Sentar的锁存打架，"
                         "发 sit_toggle programa principal又要策略在跑才收。先把它扶起来放平再点「Ficar em pé」，或者用手柄 Start")
                stand = b("stand", "Ficar em pé", None, stuck)
        elif pose == "limp":
            # 电量低不拦（用户 10-18：电池只警告）：只在按钮下面提示一句，照样能点。
            # 以前那句「Ficar em pé很快又会自己Sentar关机」在我们的鸭子上不对：按 robotd 配置的 [safety] battery_empty_shutdown 说（任务 1 附）
            stand = b("stand", "Ficar em pé", "robot.init", None)
            if isinstance(batt, (int, float)) and not isinstance(batt, bool) and batt < 15:
                if self.battery_shutdown is True:
                    stand["note"] = f"电量只剩 {batt:.0f}%，先充电再玩；没电它到 6.6 V 会自己Sentar关机"
                else:
                    stand["note"] = f"电量只剩 {batt:.0f}%，先充电再玩；没电它不会自己Sentar"
        elif pose == "homing":
            stand = b("stand", "Ficar em pé", None, unsteady)
        elif pose in ("holding", "policy", "walking"):
            stand = b("stand", "Ficar em pé", None, "Já está em pé")
        else:
            stand = b("stand", "Ficar em pé", None, f"Não foi possível ler a postura atual（{POSTURE_CN.get(pose, pose)}）")
        # Começar a andar / 停下（停下谁都能点 e relaxamento de torque后也能点）
        if pose in DRIVING and not base:
            walk = b("walk_stop", "Parar (ficar em pé)", "robot.stop → robot.enable {on:false}", None)
        elif block:
            walk = b("walk", "Começar a andar", None, block)
        elif job:
            walk = b("walk", "Começar a andar", None, "Buscando/emparelhando um controle (isso ocupa o Bluetooth); aguarde terminar antes de começar a andar")
        elif stuck:
            walk = b("walk", "Começar a andar", None, "坐着又没在跑策略：看「Ficar em pé」那里的说明")
        elif sitting is None:
            walk = b("walk", "Começar a andar", None, NO_SIT_INFO)
        elif sitting:
            walk = b("walk", "Começar a andar", None, "Sentado: clique primeiro em “Ficar em pé”")
        elif pose == "holding":
            walk = b("walk", "Começar a andar", "robot.enable {on:true}", None)
        elif pose == "limp":
            walk = b("walk", "Começar a andar", None, "Torque relaxado: clique primeiro em “Ficar em pé”")
        elif pose == "homing":
            walk = b("walk", "Começar a andar", None, unsteady)
        else:
            walk = b("walk", "Começar a andar", None, f"Não foi possível ler a postura atual（{POSTURE_CN.get(pose, pose)}）")
        # Sentar：没坐着（读得到） e 策略在跑 e 到了 HOME e 没在走
        known = self._known_skills()
        if block:
            sit = b("sit", "Sentar", None, block)
        elif sitting is None:
            sit = b("sit", "Sentar", None, NO_SIT_INFO)
        elif sitting:
            sit = b("sit", "Sentar", None, "Já está sentado")
        elif known is not None and "sit_toggle" not in known:
            sit = b("sit", "Sentar", None, "Este Microduck没装Sentar的模型（sitstand）")
        elif pose == "policy" and policy_on:
            sit = b("sit", "Sentar", "robot.do sit_toggle", None if homed is not False else "Ainda está voltando à postura em pé; aguarde um segundo")
        elif pose == "walking":
            sit = b("sit", "Sentar", None, "Em movimento: solte o analógico e aguarde parar")
        elif pose == "holding":
            sit = b("sit", "Sentar", None, "Para sentar, a política precisa estar em execução (regra oficial): clique em “Começar a andar” e depois em “Sentar”")
        elif pose == "limp":
            sit = b("sit", "Sentar", None, "Torque relaxado: clique primeiro em “Ficar em pé”")
        else:
            sit = b("sit", "Sentar", None, f"Agora {POSTURE_CN.get(pose, pose)}，坐不了")
        # 网页手柄的 Start：在走 / 准备好走 → 停下；站着保持 → Começar a andar；别的 → Ficar em pé（三 V7，附 1 第一行）
        if walk["op"] == "walk_stop":
            pick = walk
        elif pose == "holding":
            pick = walk
        else:
            pick = stand
        start = {"op": pick["op"], "label": pick["label"], "ok": pick["ok"], "why": pick["why"], "call": pick["call"]}
        # 十字右：重启全部舵机。官方按一下就发 e robotd 从不拒（过载保护跳了的鸭子正要它），所以relaxamento de torque之后也能按
        reboot = {"ok": base is None, "why": base, "does": "重启全部舵机：鸭子先软下来（扶住），之后按 Start 站回来"}
        # 十字上按住 3 秒：Andar ⇄ Rodas。Agora 是哪个看 robot.policies 的 mode（官方 padd 是开机问一次 robot.mode）
        cur = pol.get("mode") if pol.get("mode") in DRIVE_MODE_CN else None
        target = {"walk": "roller", "roller": "walk"}.get(cur)
        mode_why = block or (None if target else "读不到Agora 是Andar还是Rodas（robot.policies 读不到）")
        drive_mode = {"ok": mode_why is None, "why": mode_why, "current": cur, "target": target,
                      "does": f"按住 3 秒：切到{DRIVE_MODE_CN[target]}" if target else "按住 3 秒：Andar ⇄ Rodas"}
        # 技能
        need_drive = None
        if block:
            need_drive = block
        elif pose not in DRIVING:
            need_drive = "要「准备好走」（策略在跑）才能做：先点「Começar a andar」" if pose == "holding" else \
                f"Agora {POSTURE_CN.get(pose, pose)}：先Ficar em pé e 点「Começar a andar」"
        elif sitting is None:
            need_drive = NO_SIT_INFO
        elif sitting:
            need_drive = "Sentado: fique em pé primeiro"
        elif homed is False:
            need_drive = "Ainda está voltando à postura em pé; aguarde um segundo"
        skills = []
        for name in [n for n in (known or []) if n != "sit_toggle"]:
            why = self._skill_why(name, need_drive, known, pol)
            skills.append({"name": name, "label": C.SKILL_CN.get(name, name), "ok": why is None, "why": why})
        skills_why = None if known is not None else "Não foi possível ler as habilidades disponíveis (robot.policies só pode ser consultado no modo de movimento)"
        # 声音（叫一声不动关节，relaxamento de torque后也能叫：main.rs:4300-4307）
        sounds = [{"tag": t, "label": lab, "ok": base is None, "why": base} for t, lab in C.SOUNDS.items()]
        # 动作 e 组合动作
        attached, _ = self._pad_attached(now)
        held_mouth = any({"lt", "rt"} & set(st["held"]) for st in self._keys.values() if not st.get("end"))
        head_mode = any(m["mode"] == "head" for m in self._modes.values()) or bool((self._latch["head"] or {}).get("nonzero"))
        limp = pose == "limp" or relaxed(bus) is True

        def combo_row(c, builtin):
            why = None
            if C.needs_policy(c["steps"]):
                why = need_drive
            if why is None and attached:
                why = "实体手柄连着：它每一拍都发一次嘴和速度，会盖掉动作。先把手柄关掉"
            if why is None:
                why = base or relax
            if why is None:
                for s in c["steps"]:
                    if s["do"] == "skill":
                        why = self._skill_why(s["name"], need_drive, known, pol)
                        if why:
                            break
            if why is None and held_mouth and any(C.mouth_at(s, 0.0) is not None for s in c["steps"]):
                why = "正在按着 LT / RT 张嘴：先松开"
            if why is None and head_mode and any(C.head_at(s, 0.0) is not None for s in c["steps"]):
                why = "modo cabeça开着 e 摇杆在管cabeça：先按 Y voltar ao modo Andar"
            text = C.describe(c["steps"])
            if why is None and limp and not C.needs_policy(c["steps"]):
                text += "（软着：嘴不会动，站好了才动）"
            return {"id": c["id"], "name": c["name"], "builtin": builtin, "text": text,
                    "seconds": round(C.duration(c["steps"]), 1), "ok": why is None, "why": why}

        actions = [combo_row(c, True) for c in C.ACTIONS]
        combos = [combo_row(c, True) for c in C.BUILTIN_COMBOS] + [combo_row(c, False) for c in self._user_combos]
        a = self._action
        running = None if a is None else {"id": a["id"], "name": a["name"], "by": a["by"], "step": a["step"],
                                          "steps": len(a["steps"]), "elapsed_s": round(now - a["started"], 1)}
        # LT / RT：嘴按 fork 的规矩（三 V10）——只要programa principal在运动模式就能按；软着 e 刚relaxamento de torque时只有声音
        trig_why = base
        if trig_why is None and a is not None and any(C.mouth_at(s, 0.0) is not None for s in a["steps"]):
            trig_why = f"Executando “{a['name']}」（也在动嘴）：aguarde terminar"
        triggers = {"ok": trig_why is None, "why": trig_why, "mouth_pct": self._inputs["mouth"],
                    "note": "软着：只有声音，嘴不会动（站好了才动嘴）" if trig_why is None and (limp or relax) else None}
        last = None
        if self._last_cmd is not None and now - self._last_cmd["at"] < 15:
            last = {k: v for k, v in self._last_cmd.items() if k != "at"}
            last["age_s"] = round(now - self._last_cmd["at"], 1)
        last_action = None
        if self._last_action is not None and now - self._last_action["at"] < 15:
            last_action = {k: v for k, v in self._last_action.items() if k != "at"}
        buttons = {"stand": stand, "walk": walk, "sit": sit}
        return {"posture": pose, "posture_cn": POSTURE_CN.get(pose, pose), "block": block, "sitting": sitting,
                "buttons": buttons, "start": start, "reboot": reboot, "drive_mode": drive_mode,
                "keys": self._key_rows(buttons, sitting, skills, skills_why, known, need_drive, pol),
                "triggers": triggers, "driving": pose in DRIVING,
                "skills": skills, "skills_why": skills_why,
                "sounds": sounds, "actions": actions, "combos": combos, "running": running, "last": last,
                "last_action": last_action, "busy": self._cmd_busy}

    # ================= Ficar em pé / Começar a andar / Sentar / 技能 / 声音：按 =================

    def _call(self, what, method, params, by, ctx=None, posture_target=None, ordered=False):
        if posture_target is None:
            return self._call_rpc(what, method, params, by, ctx)
        motion = self.motion_studio
        with (nullcontext() if ordered else self._send_lk):
            with self._lk:
                if not motion.request_current():
                    raise Refused("A sessão de movimento mudou，a solicitação antiga foi descartada")
                recording = motion.session and motion.state == "recording"
                # Old robotd/manual fixtures without state evidence retain their
                # original control path. Automation always requires complete data.
                legacy = (not recording and not ordered and not motion.posture.pending
                          and "state" not in (self._robot or {}))
                if recording:
                    motion._boundary(record=True)
                    motion._refresh_request()
            if legacy:
                return self._call_rpc(what, method, params, by, ctx)
            if recording:
                motion._flush_outputs()
            with self._lk:
                if recording and (not motion.session or motion.session.get("invalid")):
                    raise Refused("A sessão de movimento terminou; a solicitação de sentar/ficar em pé foi cancelada")
                token = motion.begin_posture(posture_target, manual=not recording and not ordered)
                origin = motion.recording_origin()
            if not token["command"]:
                with self._lk:
                    motion.posture.accepted(token, self.clock())
                return {"accepted": True, "reason": "A postura desejada já foi atingida"}
            return self._call_rpc(what, method, params, by, ctx, posture_token=token, record_origin=origin)

    def _call_rpc(self, what, method, params, by, ctx=None, posture_token=None, record_origin=None):
        """一个要回话的请求：记「发出 → 回执 · 耗时」（log_cmd，分类「命令」），拒绝的原因翻成人话抛 Refused。"""
        if self.robot is None:
            raise Refused("O endereço do programa principal não está configurado para este Microduck")
        if self._update_blocked() and not neutral_robot_command(method,params):
            raise Refused('A proteção de atualização do software/programa principal continua ativa，旧a solicitação da ação foi cancelada')
        with self._lk:
            if not self.motion_studio.request_current():
                raise Refused("A sessão de movimento mudou，a solicitação antiga foi descartada")
        if method == "robot.sound":
            record_origin = self.motion_studio.recording_origin()
        skill_fence = self.motion_studio.note_skill() if method == "robot.do" and posture_token is None else None
        with log_cmd(self.log, what, method, who=by, args=params or None, ctx=ctx) as t:
            try:
                r = self.robot.call(method, params, CMD_TIMEOUT_S)
            except Unreachable as e:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, None, reason="连接中断")
                t.fail(f"Falha ao enviar: {e}", hint="O robotd do programa principal está em execução? Consulte a página de resumo")
                raise Refused(f"Falha ao enviar: {e}") from None
            except Timeout:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, None, reason="Tempo limite da resposta")
                t.fail(f"programa principal {CMD_TIMEOUT_S:g} 秒没回话", hint="它可能卡住了：看日志里 robotd 那几行，必要时relaxamento de torque")
                raise Refused(f"programa principal {CMD_TIMEOUT_S:g} 秒没回话：它可能卡住了") from None
            except RpcError as e:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, False)
                why = plain_refusal(e.message)
                t.fail(f"programa principal报错：{e.message}", raw={"code": e.code, "message": e.message}, hint=why)
                raise Refused(why) from None
            if isinstance(r, dict) and r.get("accepted") is False:
                if posture_token:
                    self.motion_studio.posture_reply(posture_token, False)
                self.motion_studio.rejected_skill(skill_fence)
                why = plain_refusal(r.get("reason"))
                t.fail(f"O programa principal recusou: {r.get('reason')}", raw=r, hint=why)
                raise Refused(why)
            if posture_token:
                if not isinstance(r, dict) or r.get("accepted") is not True:
                    self.motion_studio.posture_reply(posture_token, None, reason="Formato de resposta ambíguo")
                    raise Refused(self.motion_studio.posture.error)
                self.motion_studio.posture_reply(posture_token, True, origin=record_origin)
            t.ok(r, note=(r.get("reason") or "") if isinstance(r, dict) else "")
        if method == "robot.sound":
            self.motion_studio.accepted_from(record_origin, method, params)
        return r

    def _motion_cmd(self, op, args, conn, by, label=None):  # noqa: C901
        """comando pontual：不拿方向盘（审查二 I1).别人正在推摇杆时不让点（停下 e 叫一声除外）；一次只发一个
        （停下 e 叫一声除外：声音不动关节，不占「上一个还没回话」，三 V15).label：网页手柄图上按的，日志里写「网页手柄 A → …」。"""
        now = self.clock()
        what = {"stand": "Ficar em pé", "walk": "Começar a andar", "walk_stop": "Parar (ficar em pé)", "sit": "Sentar"}.get(op)
        urgent = op == "walk_stop"
        exclusive = op not in ("walk_stop", "sound")
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou，a solicitação antiga foi descartada"}
            if self._cmd_busy and exclusive:
                raise Refused("O comando anterior ainda não respondeu; aguarde")
            mv = self._motion_view(now)
            if op == "skill":
                name = args.get("name")
                row = next((s for s in mv["skills"] if s["name"] == name), None)
                if row is None:
                    raise Refused(mv["skills_why"] or f"Este Microduck não tem a habilidade “{C.SKILL_CN.get(name, name)}」")
                what = f"技能：{row['label']}"
                ok, why = row["ok"], row["why"]
            elif op == "sound":
                tag = args.get("tag")
                row = next((s for s in mv["sounds"] if s["tag"] == tag), None)
                if row is None:
                    raise Refused(f"Som desconhecido: {tag}")
                what = f"叫一声：{row['label']}"
                ok, why = row["ok"], row["why"]
            else:
                btn = next((x for x in mv["buttons"].values() if x["op"] == op), None)
                if btn is None:
                    pose = mv["posture_cn"]
                    msg = {"walk": "Já 「准备好走」了：推摇杆就走" if mv["posture"] in DRIVING else f"Agora {pose}，「Começar a andar」用不了",
                           "walk_stop": f"Agora {pose}，没在走"}.get(op, "Este comando não pode ser usado agora")
                    self._last_cmd = {"what": label or what, "by": by, "ok": False, "reason": msg, "at": now}
                    raise Refused(msg)
                ok, why = btn["ok"], btn["why"]
            what = label or what
            if ok and op not in ("sound", "walk_stop"):
                held = self._lease_holder(now)
                if held is not None and held["conn"] != conn:
                    ok, why = False, f"{held['by'] or 'outra página'}está movendo os analógicos; aguarde soltar ou clique em “Assumir”"
            if not ok:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": why, "at": now}
                raise Refused(why)
            if exclusive:
                self._cmd_busy = True
            pose = mv["posture"]
            stand_call = mv["buttons"]["stand"]["call"]
        try:
            ctx = {"posture": pose}
            if op == "stand":
                if stand_call == "robot.init":
                    r = self._call(what, "robot.init", {}, by, ctx)
                else:
                    r = self._call(what + "（坐着：sit_toggle）", "robot.do", {"skill": "sit_toggle"}, by, ctx, posture_target="stand")
            elif op == "walk":
                r = self._call(what, "robot.enable", {"on": True, "toggle": False}, by, ctx)
            elif op == "walk_stop":
                with self._lk:
                    d = self._driver
                self._halt("点了停下", d["conn"] if d else None, clear_all=True)   # 三 V1 第 7 条：谁置的cabeça/corpo都清
                self._call("停下：先把速度清零", "robot.stop", {}, by, ctx)
                # 走着的时候先等速度归零（最多 1 秒）再回站姿（review-impl-plan I2「走着」一行).
                # 按次数等，不看注入的时钟：时钟Interrompida（测试 e 或者别的毛病）也不会卡死在这里
                for _ in range(int(WALK_STOP_WAIT_S / 0.05)):
                    applied = (self._robot or {}).get("applied")
                    if not (isinstance(applied, list) and any(abs(v) > 0.01 for v in applied if isinstance(v, (int, float)))):
                        break
                    self._cancel_wait(0.05)
                r = self._call(what, "robot.enable", {"on": False, "toggle": False}, by, ctx)
            elif op == "sit":
                r = self._call(what, "robot.do", {"skill": "sit_toggle"}, by, ctx, posture_target="sit")
            elif op == "skill":
                r = self._call(what, "robot.do", {"skill": args.get("name")}, by, ctx)
            else:
                r = self._call(what, "robot.sound", {"tag": args.get("tag")}, by, ctx)
        except Refused as e:
            with self._lk:
                self._last_cmd = {"what": what, "by": by, "ok": False, "reason": str(e), "at": self.clock()}
            raise
        finally:
            if exclusive:
                with self._lk:
                    self._cmd_busy = False
        note = r.get("reason") if isinstance(r, dict) else None
        with self._lk:
            self._last_cmd = {"what": what, "by": by, "ok": True, "reason": note, "at": self.clock()}
        return {"accepted": True, "reason": note, "did": op}

    # ================= 动作 e 组合动作（按住才做，松手就停） =================

    def _find_combo(self, cid):
        for c in C.ACTIONS + C.BUILTIN_COMBOS + self._user_combos:
            if c["id"] == cid:
                return c
        return None

    def _action_start(self, args, conn, by):
        """press：página这一次按下的序号（代码审查 C7).之后的 action_hold 带同一个序号才算续命：página上一次按下留下的
        定时器（回执回来之前又松开 e 又按下）续不了这一次的命。"""
        cid = args.get("id")
        combo = self._find_combo(cid)
        if combo is None:
            raise Refused(f"Ação desconhecida: {cid}")
        press = self._seq({"seq": args.get("press")})
        now = self.clock()
        with self._lk:
            if not self.motion_studio.request_current():
                return {"dropped": "A sessão de movimento mudou，a solicitação antiga da ação foi descartada"}
            a = self._action
            if a is not None:
                if a["conn"] == conn and a["id"] == cid:
                    a["hold"] = now
                    a["press"] = press
                    return {"running": cid}
                raise Refused(f"Executando “{a['name']}」（{a['by'] or 'página'}）：aguarde terminar ou solte o botão primeiro")
            mv = self._motion_view(now)
            row = next((x for x in mv["actions"] + mv["combos"] if x["id"] == cid), None)
            if row is None or not row["ok"]:
                raise Refused((row or {}).get("why") or "Não é possível executar agora")
            self._take_lease(conn, by, now)          # sair了手柄页的连接拿不到（三 V5：不再有 action 的口子）
            a = {"id": cid, "name": combo["name"], "conn": conn, "by": by, "started": now, "hold": now, "press": press,
                 "stop": threading.Event(), "why": None, "step": 0, "steps": list(combo["steps"]),
                 "motion_epoch": self.motion_studio.epoch}
            self._action = a
        self.log.info(f"Iniciando a ação「{combo['name']}」（{by or 'página'}）", cat="Controle", raw=C.describe(combo["steps"]), dedup=False)
        threading.Thread(target=self._run_action, args=(a,), name="pad-action", daemon=True).start()
        return {"started": cid, "seconds": round(C.duration(combo["steps"]), 1)}

    def _action_hold(self, conn, press=None):
        """página说「还按着」。带了序号 e 跟这个动作开始时的不一样：是上一次按下留下的，不续（代码审查 C7)."""
        press = self._seq({"seq": press})
        with self._lk:
            a = self._action
            if (a is not None and a["conn"] == conn and conn not in self._gone
                    and (press is None or a.get("press") is None or press == a["press"])):
                a["hold"] = self.clock()
                self._touch_lease(conn, a["hold"])
                return {"running": a["id"]}
        return {"running": None}

    def _action_stop(self, conn, why="foi solto"):
        with self._lk:
            a = self._action
            if a is None or (conn is not None and a["conn"] != conn):
                return {}
            a["why"] = a["why"] or why
            a["stop"].set()
        return {}

    def _abort_reason(self, a, needs_policy):
        now = self.clock()
        with self._lk:
            if a["stop"].is_set():
                return a["why"] or "Interrompida"
            if now - a["hold"] > HOLD_S:
                return f"página {HOLD_S:g} 秒没说「还按着」（松手 e 切页或断网）"
            if self._relax_at >= a["started"]:
                return "Torque relaxado"
            r = self._robot or {}
            if r.get("estop_active"):
                return "Torque relaxado"
            if needs_policy and relaxed(r.get("bus")) is True:     # 只动嘴的（三 V10）软着也照做：robotd 自己不动
                return "O torque foi desligado (relaxado)"
            if self._pad_attached(now)[0]:
                return "Controle físico conectado"
            d = self._driver
            if d is None or d["conn"] != a["conn"]:
                return "Controle assumido por outra página"
            base = self._base_block(now)
            if base:
                return base
            if needs_policy and self._posture() not in DRIVING:
                return "策略Interrompida"
        return None

    def _notify_output(self, method, params):
        if self._update_blocked() and not neutral_robot_command(method,params):return False
        if method == "robot.do":
            self.motion_studio.note_skill()
        self.robot.notify(method, params)
        self.motion_studio.accepted(method, params)
        return True

    def _notify_quiet(self, method, params, action=None, cleanup=False):
        with self._send_lk:
            with self._lk:
                if action is not None and (self._action is not action
                        or action.get("motion_epoch") != self.motion_studio.epoch
                        or (action["stop"].is_set() and not cleanup)):
                    return False
            return self._notify_output(method, params)

    def _run_action(self, a):  # noqa: C901
        steps, needs = a["steps"], C.needs_policy(a["steps"])
        moves_head = any(C.head_at(s, 0.0) is not None for s in steps)
        moves_mouth = any(C.mouth_at(s, 0.0) is not None for s in steps)
        result, level = "Concluída", "info"
        try:
            if self.robot is None:
                raise _Abort("O endereço do programa principal não está configurado para este Microduck")
            for i, step in enumerate(steps):
                with self._lk:
                    a["step"] = i
                why = self._abort_reason(a, needs)
                if why:
                    raise _Abort(why)
                if step["do"] == "sound":
                    self._call(f"动作「{a['name']}」：叫一声", "robot.sound", {"tag": step["tag"]}, a["by"])
                elif step["do"] == "skill":
                    with self._lk:
                        mv = self._motion_view(self.clock())
                    row = next((s for s in mv["skills"] if s["name"] == step["name"]), None)
                    why = (row or {}).get("why") if row else f"Este Microduck não tem a habilidade “{C.SKILL_CN.get(step['name'], step['name'])}」"
                    if why:
                        raise _Abort(why)
                    if self._abort_reason(a, needs):     # 查完到发出之间也可能relaxamento de torque：发之前再看一眼
                        raise _Abort(self._abort_reason(a, needs))
                    self._call(f"动作「{a['name']}」：{C.SKILL_CN.get(step['name'], step['name'])}", "robot.do",
                               {"skill": step["name"]}, a["by"])
                t0 = self.clock()
                dur = C.step_seconds(step)
                while True:
                    why = self._abort_reason(a, needs)
                    if why:
                        raise _Abort(why)
                    t = self.clock() - t0
                    if t >= dur:
                        break
                    h, m = C.head_at(step, t), C.mouth_at(step, t)
                    if h is not None:
                        self._notify_quiet("robot.head", dict(zip(("neck_pitch", "head_pitch", "head_yaw", "head_roll"), h)), action=a)
                    if m is not None:
                        self._notify_quiet("robot.mouth", {"open": m}, action=a)
                    a["stop"].wait(C.TICK_S)
        except _Abort as e:
            result, level = f"Interrompida：{e}", "info"
        except Refused as e:
            result, level = f"Não concluída：{e}", "warn"
        except (Unreachable, Timeout) as e:
            result, level = f"Não concluída：não foi possível enviar（{e}）", "warn"
        except Exception as e:  # noqa: BLE001 —— 不该发生；发生了也要回正 e 合嘴 e 说清楚
            result, level = f"Erro no Studio：{type(e).__name__}: {e}", "error"
            self.log.error(f"动作「{a['name']}」出错", cat="Controle", raw=f"{type(e).__name__}: {e}", exc=True,
                           hint="这是 Studio 的问题，导出诊断包发出来")
        finally:
            # cabeça的目标没有过期 e 嘴不带时间戳：不回正 e 不合上就会一直留着（pad_combo.py 文件cabeça).
            # 这个动作里有cabeça/boca的步就都发一次（不管做到哪一步了）；打断之后不再发 robot.do / robot.sound
            for used, method, params in ((moves_head, "robot.head", {"neck_pitch": 0.0, "head_pitch": 0.0, "head_yaw": 0.0, "head_roll": 0.0}),
                                         (moves_mouth, "robot.mouth", {"open": 0.0})):
                if used and self.robot is not None:
                    try:
                        self._notify_quiet(method, params, action=a, cleanup=True)
                    except (Unreachable, Timeout) as e:
                        self.log.warn("动作结束时没能回正 / 合嘴", cat="Controle", step=method, raw=str(e),
                                      hint="cabeça可能还歪着 e 嘴可能还张着：再按一次那个动作，或者让它Sentar再Ficar em pé")
            with self._lk:
                if self._action is a:
                    self._action = None
                self._last_action = {"id": a["id"], "name": a["name"], "by": a["by"], "result": result,
                                     "ok": result == "Concluída", "at": self.clock()}
            cat = "Segurança" if ("relaxamento de torque" in result or "没说" in result or "软了" in result) else "手柄"
            self.log.write(f"动作「{a['name']}」{result}", cat=cat, level=level, step=f"第 {a['step'] + 1}/{len(steps)} 步",
                           dedup=False)

    # ================= 自己编的组合动作：存 e 删（编辑界面下一轮做） =================

    def _combo_save(self, args):
        builtin = {c["id"] for c in C.ACTIONS + C.BUILTIN_COMBOS}
        combo = C.clean_combo(args.get("combo"), builtin)
        with self._lk:
            others = [c for c in self._user_combos if c["id"] != combo["id"]]
            if len(others) >= C.MAX_USER_COMBOS:
                raise Refused(f"Limite de combinações:  {C.MAX_USER_COMBOS} ; exclua algumas antes de adicionar outra")
            new = others + [combo]
        path = C.save_user_combos(self.state_dir, new)
        with self._lk:
            self._user_combos = new
        self.log.info(f"Combinação salva「{combo['name']}」", cat="Controle", step=path, raw=C.describe(combo["steps"]))
        return {"saved": combo["id"]}

    def _combo_delete(self, args):
        cid = args.get("id")
        with self._lk:
            if not any(c["id"] == cid for c in self._user_combos):
                raise Refused("Esta combinação personalizada não existe (combinações internas não podem ser excluídas)")
            new = [c for c in self._user_combos if c["id"] != cid]
        C.save_user_combos(self.state_dir, new)
        with self._lk:
            self._user_combos = new
        self.log.info(f"Combinação excluída {cid}", cat="Controle")
        return {"deleted": cid}
