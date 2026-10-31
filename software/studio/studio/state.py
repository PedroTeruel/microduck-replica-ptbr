"""Agrupa dados brutos de robotd/configd em um objeto pequeno enviado à página (sempre usa arrays; campos ausentes indicam estado desconhecido).

A classificação da postura segue a tabela review-impl-plan I2: verifica mode antes de phase:
    absent         socket do robotd ausente ou conexão recusada
    starting       phase é configuring_bus / waiting_for_bus / configuration_error (inclui o relatório de inicialização antes da primeira leitura válida no modo de calibração;
                   forks antigos podem ficar nesse estado por mais de 30 s; nesse caso, a página informa que a inicialização continua: starting_secs)
    commissioning  instantâneo de mode == "commissioning" (ready / moving / read_error / stop_unconfirmed / power_pending:
                   o programa principal iniciou; robotd fica somente para leitura e recusa init/enable/do)
    sitting        robot.policies.sitting
    limp           native.torque_state_confirmed == False
    walking        policy_enabled e move.applied diferente de zero
    policy         policy_enabled (robô parado com a política em execução)
    holding        torque ligado, homed, home_start_guard.ready e política desligada (mantém HOME após init; as juntas também chegaram à posição)
    homing         torque ligado, ainda não chegou a HOME
    unknown        dados insuficientes

Retorna estados usados nos textos, sem botões (estes ficam em S1b).
"""
import math
import time

from .estop import STARTING_LONG_S, STARTING_PHASES
from .startup import startup_todo

JOINT_NAMES = ["left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
               "neck_pitch", "head_pitch", "head_yaw", "head_roll", "mouth",
               "right_hip_yaw", "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle"]
JOINT_CN = {"left_hip_yaw": "Giro do quadril esquerdo", "left_hip_roll": "Inclinação do quadril esquerdo", "left_hip_pitch": "Flexão do quadril esquerdo", "left_knee": "Joelho esquerdo",
            "left_ankle": "Tornozelo esquerdo", "neck_pitch": "Pescoço", "head_pitch": "Inclinação da cabeça", "head_yaw": "Giro da cabeça", "head_roll": "Rolagem da cabeça",
            "mouth": "Boca", "right_hip_yaw": "Giro do quadril direito", "right_hip_roll": "Inclinação do quadril direito", "right_hip_pitch": "Flexão do quadril direito",
            "right_knee": "Joelho direito", "right_ankle": "Tornozelo direito"}
STALE_S = 3.0
# Idade máxima de cada dado (revisão de código #18: uma consulta com falha não pode manter valores antigos para classificar postura, carga ou temperatura).
MAX_AGE = {"health": 8.0, "policies": 6.0, "state": 1.5, "pad": 15.0}
CPU_WARN_C = 80          # Esta placa fica a 78 °C em repouso; avisar a 75 °C manteria o alerta sempre aceso e faria as pessoas deixarem de notá-lo.


def _fresh(sample, key, now):
    age = sample.age(now)
    return sample.value if age is not None and age <= MAX_AGE[key] else None


def _ms(age):
    return None if age is None else int(age * 1000)


def starting_secs(rd, bus, now=None):
    """Retorna por quantos segundos o programa principal informa continuamente uma etapa de inicialização desde a conexão atual (robotd.Robotd.starting_since, registrado durante a consulta).
    Retorna None se não estiver inicializando ou se o estado for desconhecido. Após STARTING_LONG_S, a página deixa de dizer “geralmente termina em 10 s” (teste em hardware de 10-20: o modo de calibração de um fork antigo sempre informa configuring_bus)."""
    since = getattr(rd, "starting_since", None)
    if since is None or not isinstance(bus, dict) or bus.get("phase") not in STARTING_PHASES:
        return None
    return max(0, int((time.monotonic() if now is None else now) - since))


STILL_STARTING = "O programa principal pode ter iniciado sem atualizar o estado (problema de versões antigas) ou pode estar travado durante a inicialização. Veja a última mensagem do programa na página de logs."


def posture(present, bus, policies, state):
    if present is False:
        return "absent"
    if not isinstance(bus, dict):
        return "unknown"
    mode, phase = bus.get("mode"), bus.get("phase")
    if phase in STARTING_PHASES:
        return "starting"
    if mode == "commissioning":
        return "commissioning"
    if mode != "motion":
        return "unknown"
    if isinstance(policies, dict) and policies.get("sitting") is True:
        return "sitting"
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    confirmed = native.get("torque_state_confirmed")
    if confirmed is False:
        return "limp"
    if bus.get("policy_enabled") is True:
        applied = ((state or {}).get("move") or {}).get("applied") if isinstance(state, dict) else None
        if isinstance(applied, list) and any(abs(v) > 0.01 for v in applied if isinstance(v, (int, float))):
            return "walking"
        return "policy"
    if confirmed is True:
        if bus.get("homed") is not True:
            return "homing"
        # homed significa apenas que o controlador considera que chegou a HOME; a posição real das juntas pode estar um pouco atrasada.
        # O home_start_guard do programa principal verifica também a posição real (≤ joint_tolerance_deg), a inclinação do corpo e a estabilidade por vários ciclos.
        # Só usa homed como alternativa quando o robotd não fornece esse campo (versões antigas).
        guard = bus.get("home_start_guard")
        if isinstance(guard, dict) and isinstance(guard.get("ready"), bool):
            return "holding" if guard["ready"] else "homing"
        return "holding"
    return "unknown"


def tilt_deg(gravity):
    """Usa o mesmo algoritmo de robotd home_start.rs: calcula o ângulo entre a gravidade e a vertical para baixo (0, 0, -1)."""
    if not isinstance(gravity, (list, tuple)) or len(gravity) != 3:
        return None
    n = math.sqrt(sum(g * g for g in gravity))
    if n < 1e-6:
        return None
    c = max(-1.0, min(1.0, -gravity[2] / n))
    return math.degrees(math.acos(c))


def cpu_view(health, health_age, bus, present, servo=None, ob=None):
    """Dados do indicador de temperatura da placa (revisões O8 e O5 da reorganização da visão geral). Campos:
        c          °C: maior temperatura entre as zonas térmicas (cpu_temp_c de robotd health, fork soc.rs:25-64); None se indisponível
        throttled  controle térmico do kernel reduz a frequência (level > 0 do cooling device) → alerta vermelho na página; None significa desconhecido, **não normal**
        limited    level é 0, mas a frequência permitida é inferior à máxima: frequência limitada, provavelmente sem relação com temperatura (intenção original em fork lib.rs:3615-3651)
        khz / max_khz / level / max_level   repassados como recebidos (khz é a frequência permitida, não a frequência instantânea)
        hot        ≥ 80 °C (com histerese: só apaga abaixo de 77 °C; controlada por onboard.Onboarding.cpu_hot; sem esse objeto, não há histerese)
        src        robotd / studio (se robotd não informar, Studio lê /sys/class/thermal; disponível no robô, mas não necessariamente no computador de desenvolvimento)
        why        motivo da ausência (programa principal não informou / controle das servos / modo de depuração / aguardando barramento / health expirado)
    robotd coleta uma vez por segundo no ciclo de controle do modo de movimento (fork main.rs:117-120, 4148-4154); não coleta em modo de depuração nem enquanto aguarda o barramento."""
    out = {"c": None, "throttled": None, "limited": None, "khz": None, "max_khz": None, "level": None, "max_level": None,
           "hot": False, "src": None, "why": None}
    h = health if isinstance(health, dict) else None
    c = (h or {}).get("cpu_temp_c")
    thr = (h or {}).get("cpu_throttle") if isinstance((h or {}).get("cpu_throttle"), dict) else None
    src = "robotd" if isinstance(c, (int, float)) else None
    board = getattr(ob, "board", None) if ob is not None else None
    if not isinstance(c, (int, float)) and isinstance(board, dict) and isinstance(board.get("c"), (int, float)):
        c, thr, src = board["c"], board.get("throttle"), "studio"
    if isinstance(c, (int, float)):
        out.update(c=round(float(c), 1), src=src)
        out["hot"] = bool(ob.cpu_hot) if ob is not None else c >= CPU_WARN_C
    else:
        if servo is not None and getattr(servo, "state", None) in ("open", "opening"):
            why = "Controle das servos: o programa principal fica parado por projeto e não informa a temperatura"
        elif present is False:
            why = "O programa principal não está em execução"
        elif (bus or {}).get("mode") == "commissioning":
            why = "O programa principal não informa a temperatura no modo de depuração"
        elif (bus or {}).get("phase") in STARTING_PHASES:
            why = "O programa principal está aguardando o barramento das servos e não informa a temperatura"
        elif h is None:
            why = f"Health sem atualização há {health_age:.0f} s" if health_age is not None else "Health ainda não recebido"
        else:
            why = "O programa principal não informou a temperatura"
        out["why"] = why
    if isinstance(thr, dict):
        lv, mx, khz, mk = thr.get("level"), thr.get("max_level"), thr.get("khz"), thr.get("max_khz")
        out.update(level=lv, max_level=mx, khz=khz, max_khz=mk)
        nums = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lv, khz, mk))
        if nums:
            out["throttled"] = lv > 0
            out["limited"] = lv == 0 and mk > 0 and khz < mk
    elif out["c"] is not None:
        out["throttled"] = None          # Há temperatura, mas sem dados de redução de frequência: estado desconhecido, não “normal”.
    return out


def servo_session_view(servo):
    """Retorna dados curtos da sessão das servos para a faixa de aviso; None se não estiver ativa. unknown = quantidade de servos sem leitura de torque (podem continuar mantendo a postura; revisão D3c);
    restored = sessão retomada após reiniciar o Studio (revisão D1)."""
    if servo is None or getattr(servo, "state", None) not in ("open", "opening"):
        return None
    holding = servo.holding() if hasattr(servo, "holding") else None
    return {"state": servo.state, "holding": holding, "latched": bool(getattr(servo, "latched", False)),
            "unknown": servo.unknown() if hasattr(servo, "unknown") else 0,
            "restored": bool(getattr(servo, "restored", False)), "closing": bool(getattr(servo, "closing", False)),
            "port": "Demonstração (sem servos conectadas)" if getattr(servo, "sim", False) else getattr(servo, "port", None)}


def servo_orphan_view(servo):
    """A sessão das servos estava ativa quando o Studio foi encerrado pela última vez, mas não foi retomada agora (revisão D1): algumas servos podem continuar segurando a postura; para desligar o torque, retome a sessão na página das servos."""
    o = getattr(servo, "orphan", None) if servo is not None else None
    if not o or getattr(servo, "state", None) in ("open", "opening"):
        return None
    return {"why": o.get("why")}


def summarize(rd, duck, servo=None, now=None, ob=None, bat=None, net=None, commit=None, auth=None):
    """bat: estimativa da bateria (studio/battery_svc.BatteryService, atualizada em um ciclo de 1 Hz); aqui apenas lê o resultado. Se não for informado, usa a escala linear antiga do robotd."""
    now = time.monotonic() if now is None else now
    bus = rd.bus.value
    health, pol, st = _fresh(rd.health, "health", now), _fresh(rd.policies, "policies", now), _fresh(rd.state, "state", now)
    bus_age, st_age = rd.bus.age(now), rd.state.age(now)
    native = (bus or {}).get("native") if isinstance((bus or {}).get("native"), dict) else {}

    # Atualidade: tempo desde que o Studio recebeu dados novos (o navegador acrescenta a idade do transporte).
    freshest = min([a for a in (bus_age, st_age) if a is not None], default=None)
    robotd_ok = rd.present is True and bus_age is not None and bus_age < STALE_S

    # Faixa de indicadores
    b = (health or {}).get("battery") or {}
    battery = {"pct": b.get("percent"), "volts": b.get("volts")}
    joints = native.get("joints") if isinstance(native.get("joints"), list) else []
    fresh = [j for j in joints if isinstance(j, dict) and j.get("feedback_fresh") is True]
    motors = (health or {}).get("motors") or {}
    hottest = None
    if isinstance(motors.get("max_c"), (int, float)):
        hottest = {"name": JOINT_CN.get(motors.get("hottest"), motors.get("hottest")), "c": motors.get("max_c")}
    servos = {"online": len(fresh) if joints else None, "total": len(joints) or 15, "hottest": hottest,
              "stale": [JOINT_CN.get(j.get("name"), j.get("name")) for j in joints
                        if isinstance(j, dict) and j.get("feedback_fresh") is False]}
    imu_h = (health or {}).get("imu") or {}
    if imu_h.get("ready") is False:
        imu_status = "missing"
    elif (imu_h.get("consecutive_stale_blocks") or 0) >= 25:
        imu_status = "frozen"
    elif native.get("imu_mount_verified") is False:
        imu_status = "unverified"      # Orientação ainda não confirmada: uma montagem inclinada pode fazer o robô disparar para a frente (causa do avanço brusco em 10-12).
    elif imu_h.get("ready") is True:
        imu_status = "ok"
    else:
        imu_status = None
    pad_v = _fresh(rd.pad, "pad", now)
    pads = (pad_v.get("pads") or []) if isinstance(pad_v, dict) else None
    pad = {"known": pads is not None, "connected": bool(pads and any(p.get("connected") for p in pads if isinstance(p, dict))),
           "name": next((p.get("name") for p in (pads or []) if isinstance(p, dict) and p.get("connected")), None),
           "driver": pad_v.get("driver") if isinstance(pad_v, dict) else None}
    pad["estop_ok"] = bool(pad["connected"] and pad["driver"] == "active" and (bus or {}).get("mode") == "motion")

    cpu = cpu_view(health, rd.health.age(now), bus, rd.present, servo, ob)
    loop = (health or {}).get("control_loop") or {}

    # 3D: repassa os ângulos das juntas na ordem JOINT_NAMES (sem aplicar direção); usa safety.gravity para a gravidade.
    # Também repassa dados antigos (a página altera a cor conforme joints_age_ms); a postura usa apenas st atualizado.
    st_any = rd.state.value if isinstance(rd.state.value, dict) else {}
    js = st_any.get("joints")
    grav = (st_any.get("safety") or {}).get("gravity")

    st_age_live = st_age
    state_t_ns = st_any.get("t_ns")
    hold = (bus or {}).get("hold") if isinstance((bus or {}).get("hold"), dict) else None
    if (bus or {}).get("mode") == "commissioning":
        # O modo de calibração não fornece robot.state: lê IMU de busStatus.last_sample (consulta de 10 Hz nesse modo).
        # Assim, a página IMU mostra dados ao vivo e permite calibrar em pé (pedido do usuário em 10-21).
        ls = (bus or {}).get("last_sample") if isinstance((bus or {}).get("last_sample"), dict) else {}
        s_imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        g = s_imu.get("gravity")
        if s_imu.get("valid") is True and isinstance(g, list) and len(g) == 3:
            grav = g
            st_age_live = bus_age
            state_t_ns = ls.get("at_us") * 1000 if isinstance(ls.get("at_us"), int) else None
    pose = posture(rd.present, bus, pol, st)
    est = rd.estop.status(present=rd.present is not False, bus=bus, bus_age_s=bus_age, now=now)
    if servo_orphan_view(servo) is not None and rd.present is not True:
        # A sessão ficou ativa no encerramento anterior e não foi retomada (revisão D1): robotd está ausente e o barramento não foi assumido; para desligar o torque, retome na página das servos.
        est = {"state": "unavailable", "why": "Algumas servos podem continuar segurando a postura desde a última sessão do Studio; retome o controle na página das servos para desligar o torque"}
    if servo is not None and servo.state in ("open", "opening"):
        # Ao controlar as servos, robotd fica parado por projeto. Confirma o torque pela leitura do barramento e estima a bateria pela média das tensões das 15 servos (mesmo algoritmo oficial).
        pose = "servo_session"
        robotd_ok = True
        freshest = 0.0                  # A consulta ao programa principal está pausada; usa a atualidade do barramento das servos (lido a 50 Hz).
        est = servo.estop_status()
        snap = servo.snapshot()
        if snap.get("avg_volts"):
            battery = {"pct": snap.get("battery_pct"), "volts": snap.get("avg_volts")}
        servos = {"online": snap.get("online"), "total": snap.get("total"), "hottest": None, "stale": []}
    if bat is not None:
        battery = bat.view(now)         # Estimativa pela tabela de tensão (durante o controle, usa as leituras do barramento do Studio): battery-plan.md v2.
    starting_s = starting_secs(rd, bus, now) if pose == "starting" else None
    return {
        "t": "state",
        "robotd_ok": robotd_ok,
        "robotd_age_ms": _ms(freshest),
        "health_age_ms": _ms(rd.health.age(now)),
        "present": rd.present,
        "mode": (bus or {}).get("mode"),
        "phase": (bus or {}).get("phase"),
        "build": (bus or {}).get("build"),
        "posture": pose,
        "start_error": (bus or {}).get("error") if pose == "starting" else None,
        # Duração contínua da inicialização desde a conexão atual e se passou de 30 s: altera os textos da visão geral, da barra superior e das tarefas.
        "starting_s": starting_s,
        "starting_long": starting_s is not None and starting_s >= STARTING_LONG_S,
        "battery": battery,
        "servos": servos,
        "imu": {"status": imu_status},
        "pad": pad,
        "cpu": cpu,
        "loop": {"hz": loop.get("achieved_hz"), "target": loop.get("target_hz"), "missed": loop.get("missed")},
        "joints": js if isinstance(js, list) and len(js) == 15 else None,
        "joints_age_ms": _ms(st_age_live),
        "state_t_ns": state_t_ns,   # Timestamp deste quadro do robotd; a página IMU usa para deduplicar (um quadro não deve contar como duas leituras).
        "gravity": grav if isinstance(grav, list) and len(grav) == 3 else None,
        "tilt_deg": tilt_deg(grav),
        "guard": (bus or {}).get("home_start_guard"),
        "hold": hold,                  # Ativação de postura em pé no modo de calibração: {stage: ramping|holding, max_error_deg, directions}
        "estop": est,
        # startup_todo (plano de ajuste T1): substitui “ainda inicializando” pela etapa informada e acrescenta aviso se o modelo de caminhada não foi carregado.
        "todo": startup_todo(rd, todo(health, bus, servos, imu_status, cpu, loop, battery, pose, rd.health.age(now),
                     battery_shutdown=getattr(ob, "battery_shutdown", None) if ob is not None else None,
                     starting_s=starting_s), pol, bus),
        # Lista de primeiros passos: o backend avalia a cada 0,5 s (onboard.Onboarding.tick); aqui apenas lê o cache (revisão O6: esta função roda 10 vezes por segundo em cada página).
        "onboarding": ob.view() if ob is not None else None,
        # Gravação no programa principal: estado de prontidão e progresso da tarefa em segundo plano (CommitService; None se o backend não estiver disponível).
        "commit": (commit.view(rd, servo) if commit is not None else None),
        # Sessão das servos (faixa de aviso no topo de cada página): inclui enquanto ativa; continua aberta se sair da página sem devolver o controle enquanto alguma servo mantém a postura (pedido do usuário em 10-18).
        "servo_session": servo_session_view(servo),
        # Tempo desde a devolução: se o programa principal foi parado manualmente, a página mantém o aviso até ele iniciar no robô e conectar (app.servo_watch remove o aviso após a conexão; revisão D12).
        "servo_handback_s": (int(now - servo.handed_back_at) if servo is not None and servo.state == "closed"
                             and getattr(servo, "handed_back_at", None) is not None else None),
        "servo_helper": bool(getattr(servo, "helper_available", False)),   # Assistente root disponível: a faixa informa que está reiniciando o programa principal (revisão D12).
        # Servos sem confirmação de torque desligado ou sem resposta de referência após a devolução (F6); motivo e recuperação se o programa principal não iniciar (F7).
        "servo_handback_note": getattr(servo, "handback_note", None) if servo is not None else None,
        "servo_giveback_error": getattr(servo, "giveback_error", None) if servo is not None else None,
        "servo_giveback_hint": getattr(servo, "giveback_hint", None) if servo is not None else None,
        # O marcador da sessão não foi gravado (F10): após reiniciar, o Studio não saberá que ela continua ativa.
        "servo_marker_error": getattr(servo, "marker_error", None) if servo is not None else None,
        # Sessão ativa no encerramento anterior e não retomada (revisão D1); ou programa principal iniciado manualmente durante a sessão (revisão D9, dentro de 10 min).
        "servo_orphan": servo_orphan_view(servo),
        "servo_conflict_s": (int(now - servo.conflict_at) if servo is not None and getattr(servo, "conflict_at", None) is not None
                             and servo.state == "closed" and now - servo.conflict_at < 600 else None),
        # Configuração de rede (studio/net.py): sem net.json, known é False e a seção Wi-Fi fica oculta.
        "net": net.view(now) if net is not None else {"known": False},
        "auth": {"has_password": auth.has_password() if auth is not None else None},
        "duck": duck,
        "name_on_duck": (rd.sysinfo.value or {}).get("name"),
    }


def todo(health, bus, servos, imu_status, cpu, loop, battery, pose, health_age=None, battery_shutdown=None, starting_s=None):
    """Converte os dados de health em mensagens claras, começando pelas mais importantes. Inclui apenas o que precisa de atenção.
    Cada item tem uma key: a página deduplica itens já mostrados na lista inicial (como conectar o robô e confirmar a orientação do IMU), para não repetir o mesmo aviso (revisão O15).
    starting_s: duração contínua da inicialização; após 30 s, troca “ainda inicializando” por “continua inicializando” e deixa de dizer que normalmente termina em 10 s."""
    items = []
    # Bateria: quando battery contém mode, usa battery.todo_items; coloca tensão muito baixa/limite crítico no início e também os exibe durante o controle das servos (revisão B-R6).
    # Sem o estimador (battery contém apenas pct/volts), mantém abaixo o formato antigo da escala linear do robotd.
    bat_items = None
    if isinstance(battery, dict) and "mode" in battery:
        from .battery import todo_items as battery_todo
        bat_items = battery_todo(battery)
        items += [i for i in bat_items if i["level"] == "error"]
    if health is None and pose not in ("absent", "unknown", "servo_session"):   # Durante o controle das servos, o programa principal fica parado por projeto; isso não conta como health ausente.
        # Health expirado ou indisponível: não pode indicar “nada para fazer”, pois isso daria uma falsa sensação de segurança.
        when = f"sem atualização há {health_age:.0f} s" if health_age is not None else "ainda não recebido"
        items.append({"key": "health", "level": "warn", "msg": "Health indisponível",
                      "hint": f"Dados de bateria, temperatura e IMU {when}; confira as mensagens do robotd nos logs"})
    if pose == "starting":
        raw = (bus or {}).get("error")
        if starting_s is not None and starting_s >= STARTING_LONG_S:
            items.append({"key": "starting", "level": "warn", "msg": "O programa principal continua inicializando",
                          "hint": f"Já se passaram {starting_s} s. " + (f"Mensagem original: {raw}. Veja a última mensagem do programa na página de logs" if raw
                                                                  else STILL_STARTING)})
        else:
            items.append({"key": "starting", "level": "warn", "msg": "O programa principal do robô está inicializando",
                          "hint": f"Mensagem original: {raw}" if raw else "Normalmente termina em 10 s"})
    if pose == "servo_session":
        items.append({"key": "servo_session", "level": "warn", "msg": "Controle das servos em andamento",
                      "hint": "O programa principal está parado; controle, comandos remotos e movimentos de postura estão indisponíveis. As servos continuam mantendo a posição ao sair da página; selecione “Devolver ao programa principal” para transferir o controle."})
        if bat_items is not None:
            items += [i for i in bat_items if i["level"] != "error"]
        else:
            # Sem estimador, ainda mostra a tarefa da bateria durante o controle das servos (revisão D8); a tensão é a média das leituras das 15 servos no barramento do Studio (convertida em summarize).
            # robotd fica parado nesse momento, então a configuração de desligamento automático não tem efeito.
            pct = battery.get("pct") if isinstance(battery, dict) else None
            if isinstance(pct, (int, float)) and pct < 15:
                items.append({"key": "battery", "level": "error", "msg": f"Restam apenas {pct:.0f}% de bateria",
                              "hint": "Recarregue. O robotd está parado e o robô não se sentará sozinho quando a bateria acabar."})
            elif isinstance(pct, (int, float)) and pct < 30:
                items.append({"key": "battery", "level": "warn", "msg": f"Bateria em {pct:.0f}%",
                              "hint": "A bateria está acabando; o robotd está parado e o robô não se sentará sozinho quando acabar."})
        return items
    if pose == "absent":
        items.append({"key": "absent", "level": "error", "msg": "O programa principal do robô não está em execução", "hint": "Parar o robotd não desliga o torque; as servos podem continuar sustentando o robô."})
    items += [i for i in bat_items or () if i["level"] != "error"]
    pct = battery.get("pct") if bat_items is None else None
    if isinstance(pct, (int, float)):
        if pct < 15:
            # O robô se senta e desliga quando a bateria acaba? Verifica [safety] battery_empty_shutdown do robotd (lido em uma thread por onboard.py):
            # A configuração real do robô nº 2 é false: nada o fará parar quando a bateria acabar. Se não for possível ler, assume que não (melhor recomendar que o usuário pare).
            empty = ("A 6,6 V, o robô se sentará e desligará sozinho" if battery_shutdown is True
                     else "O robô não se sentará sozinho quando a bateria acabar; pare-o, coloque-o sentado e recarregue")
            items.append({"key": "battery", "level": "error", "msg": f"Restam apenas {pct:.0f}% de bateria", "hint": f"Recarregue; {empty}"})
        elif pct < 30:
            items.append({"key": "battery", "level": "warn", "msg": f"Bateria em {pct:.0f}%", "hint": "A bateria está acabando."})
    if imu_status == "frozen":
        items.append({"key": "imu_frozen", "level": "error", "msg": "As leituras do IMU estão congeladas", "hint": "Os dados de postura não atualizam. Não caminhe; verifique o cabo do IMU."})
    elif imu_status == "missing":
        items.append({"key": "imu_missing", "level": "error", "msg": "IMU indisponível", "hint": "Verifique as conexões do módulo IMU."})
    elif imu_status == "unverified":
        items.append({"key": "imu_unverified", "level": "warn", "msg": "A orientação de montagem do IMU ainda não foi confirmada",
                      "hint": "Se estiver inclinado, o robô pode disparar para a frente ao caminhar. Calibre na página “IMU” (este fork não permite nem ficar em pé sem confirmar)."})
    if servos.get("stale"):
        items.append({"key": "servo_stale", "level": "warn", "msg": f"Leitura sem atualização: {', '.join(servos['stale'][:3])}",
                      "hint": "O cabo pode estar frouxo ou sem alimentação."})
    khz, mk = cpu.get("khz"), cpu.get("max_khz")
    if cpu.get("throttled"):
        mhz = f"：{khz // 1000} / {mk // 1000} MHz" if isinstance(khz, int) and isinstance(mk, int) and mk else ""
        items.append({"key": "cpu", "level": "warn", "msg": f"A placa reduziu a frequência por superaquecimento{mhz}", "hint": "O controle ficará mais lento; instale um dissipador ou uma ventoinha pequena."})
    elif cpu.get("hot") and isinstance(cpu.get("c"), (int, float)):
        # Usa a mesma histerese do indicador da placa (acende a ≥ 80 °C e apaga abaixo de 77 °C; revisão O8), evitando oscilações em repouso entre 78 e 80 °C.
        items.append({"key": "cpu", "level": "warn", "msg": f"Placa a {cpu['c']:.0f} °C, temperatura alta", "hint": "Se aquecer mais, reduzirá a frequência e o controle ficará mais lento; instale um dissipador ou uma ventoinha pequena."})
    elif cpu.get("limited") and isinstance(khz, int):
        items.append({"key": "cpu", "level": "warn", "msg": f"Frequência da placa limitada a {khz // 1000} MHz (não por temperatura)",
                      "hint": "Um programa ou uma configuração do sistema reduziu a frequência máxima da CPU; o controle pode ficar mais lento."})
    hz, target = loop.get("achieved_hz") or loop.get("hz"), loop.get("target_hz") or loop.get("target")
    if isinstance(hz, (int, float)) and isinstance(target, (int, float)) and target and hz < 0.95 * target:
        items.append({"key": "loop", "level": "warn", "msg": f"Frequência de controle em apenas {hz:.1f} Hz", "hint": f"Meta: {target:.0f} Hz; verifique a temperatura e a carga da placa."})
    return items
