"""Simula os dados de execução e ajuste de parâmetros no robotd falso (plano v2 T1–T3).
fake_robotd.py usa este módulo em três situações:
- Após set_posture: after_posture(fake, p) acrescenta active_action_scale / active_target_filters / scale_use quando a política está ativa.
  Os registros disponíveis foram feitos com a política desligada; serão substituídos por registros reais em pé, andando e sentado.
  Para walk_unloaded, reproduz o fork (revisão T-R1): etapa 3 bem-sucedida com “Estratégia desativada conforme configuração”,
  loaded_models vazio, sem erros de slot nem change_error.
- fake.set: fake_set(fake, params) reconhece estas chaves:
    startup {steps:{...}} / null        substitui as quatro etapas calculadas pela postura; null restaura o cálculo e notifica assinantes
    servo_parameters {kp,kd,torque_limit} / null / "absent"   native.hd1910.servo_parameters; "absent" remove a chave, como no firmware original
    walk_profile {action_scale,head_lowpass,legs_lowpass}    substitui loaded_models.walk.runtime_execution_profile
    guard {...}                          altera campos em home_start_guard
    last_enable_refusal "motivo" / null
    slot_error {slot: "motivo" / null}  robot.policies.slots[].error
    change_error "motivo" / null       robot.policies.change_error
    regs null                            esvazia registers_before_arm (sem torque aplicado)
- Ao receber robot.startupSubscribe: startup_stream(fake, reader, writer, rid) retorna as quatro etapas atuais e envia robot.startup quando houver mudanças.
  Termina quando o cliente envia uma linha ou desconecta (como fork robotd main.rs:4671-4686). Se errors contiver este método, retorna erro, simulando um robotd antigo.
As descrições das etapas são aproximadas e foram escritas para este projeto; a frase “Estratégia desativada conforme configuração” é literal, pois startup.py a reconhece.
"""
import asyncio
import copy
import json

POLICY_OFF = "Estratégia desativada conforme configuração"


def _ok(detail):
    return {"status": "success", "detail": detail}


def startup_report(fake):
    if getattr(fake, "startup_override", None) is not None:
        return {"steps": copy.deepcopy(fake.startup_override.get("steps") or {}), "build": fake.bus.get("build")}
    p = fake.posture
    s1 = _ok("Configuração, bloqueio de instância, IPC e thread de controle iniciados")
    if p == "starting":
        steps = {"1": s1, "2": {"status": "waiting", "detail": fake.bus.get("error") or "Aguardando dados atualizados de todas as juntas; nenhum alvo foi enviado"}}
    elif p == "stuck_calib":
        steps = {"1": s1, "2": {"status": "waiting", "detail": fake.bus.get("error")}}
    elif p == "commissioning":
        # Segue o fork feetech_commissioning.rs: a etapa 2 fica em starting antes de abrir o barramento, ou waiting se falhar; após a primeira leitura bem-sucedida, as quatro etapas concluem.
        # Fork antigo (comm_stuck): as quatro etapas também concluem, mas busStatus continua retornando o relatório de inicialização.
        cp = fake.comm_phase() if hasattr(fake, "comm_phase") and fake.mode == "commissioning" else "up"
        if cp == "waiting":
            steps = {"1": s1, "2": {"status": "waiting", "detail": "torque readback at register 40: Feetech Sync Read timeout"}}
        elif cp == "boot" and not getattr(fake, "comm_stuck", False):
            steps = {"1": s1, "2": {"status": "starting", "detail": "Modo de calibração: lendo calibração existente, desligando e confirmando torque e inicializando a IMU"}}
        else:
            steps = {"1": s1, "2": _ok("Modo de calibração: primeiro retorno válido recebido"), "3": _ok("Modo de calibração: modelos de política não são carregados"),
                     "4": _ok("Modo de calibração: primeiro ciclo concluído; política de movimento desativada")}
    elif p == "walk_unloaded":
        steps = {"1": s1, "2": _ok("Primeiro retorno válido das juntas e da IMU recebido"), "3": _ok(POLICY_OFF), "4": _ok("Primeiro ciclo de controle concluído")}
    else:
        steps = {"1": s1, "2": _ok("Primeiro retorno válido das juntas e da IMU recebido"), "3": _ok("Modelo incluído no pacote disponível"), "4": _ok("Primeiro ciclo de controle concluído")}
    return {"steps": steps, "build": fake.bus.get("build")}


def after_posture(fake, p):
    bus = fake.bus
    if not isinstance(bus.get("native"), dict):
        return                                    # Modo de depuração ou aguardando o barramento: busStatus não contém esses campos
    b0 = fake._bus0
    if p == "walk_unloaded":
        bus["loaded_models"] = None
        bus["active_model"] = None
    elif bus.get("loaded_models") is None and b0.get("loaded_models") is not None:
        bus["loaded_models"] = copy.deepcopy(b0["loaded_models"])
    wp = getattr(fake, "walk_profile", None)
    walk = (bus.get("loaded_models") or {}).get("walk") if isinstance(bus.get("loaded_models"), dict) else None
    if wp and isinstance(walk, dict) and isinstance(walk.get("runtime_execution_profile"), dict):
        walk["runtime_execution_profile"].update(wp)
    prof = (walk or {}).get("runtime_execution_profile") if isinstance(walk, dict) else None
    if p == "policy" and isinstance(prof, dict):
        mult = bus.get("voltage_scale_mult") or 1.0
        bus["active_action_scale"] = round(prof["action_scale"] * mult, 6)
        bus["active_target_filters"] = {"head_lowpass": prof["head_lowpass"], "legs_lowpass": prof["legs_lowpass"]}
        bus["scale_use"] = "joint_uniform"
        bus["active_model"] = {k: walk.get(k) for k in ("path", "sha256", "task")}
    else:
        bus["active_action_scale"] = None
        bus["active_target_filters"] = None
        bus["scale_use"] = "held"
        if p != "walk_unloaded":
            bus["active_model"] = None


def fake_set(fake, params):
    bus = fake.bus
    native = bus.get("native") if isinstance(bus.get("native"), dict) else None
    hd = native.get("hd1910") if native is not None and isinstance(native.get("hd1910"), dict) else None
    if "startup" in params:
        fake.startup_override = params["startup"] if isinstance(params["startup"], dict) else None
    if "servo_parameters" in params and hd is not None:
        v = params["servo_parameters"]
        if v == "absent":
            hd.pop("servo_parameters", None)
        else:
            hd["servo_parameters"] = v
    if isinstance(params.get("walk_profile"), dict):
        fake.walk_profile = dict(params["walk_profile"])
        after_posture(fake, fake.posture)
    if isinstance(params.get("guard"), dict) and isinstance(bus.get("home_start_guard"), dict):
        bus["home_start_guard"].update(params["guard"])
    if "last_enable_refusal" in params:
        bus["last_enable_refusal"] = params["last_enable_refusal"]
    if isinstance(params.get("slot_error"), dict) or "change_error" in params:
        fake.policies = copy.deepcopy(fake.policies or {})
        for s in fake.policies.get("slots") or []:
            if isinstance(s, dict) and s.get("slot") in (params.get("slot_error") or {}):
                s["error"] = params["slot_error"][s["slot"]]
        if "change_error" in params:
            fake.policies["change_error"] = params["change_error"]
    if "regs" in params and hd is not None and params["regs"] is None:
        hd["registers_before_arm"] = []


async def startup_stream(fake, reader, writer, rid):
    err = (getattr(fake, "errors", None) or {}).get("robot.startupSubscribe")
    if err:
        writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "error": err}) + "\n").encode())
        await writer.drain()
        return
    last = startup_report(fake)
    writer.write((json.dumps({"jsonrpc": "2.0", "id": rid, "result": last}, ensure_ascii=False) + "\n").encode())
    await writer.drain()
    fake.startup_subs = getattr(fake, "startup_subs", 0) + 1
    line = asyncio.ensure_future(reader.readline())
    try:
        while True:
            done, _ = await asyncio.wait({line}, timeout=0.1)
            if done:
                return                            # O cliente enviou uma linha ou desconectou; encerra como robotd
            cur = startup_report(fake)
            if cur != last:
                last = cur
                writer.write((json.dumps({"jsonrpc": "2.0", "method": "robot.startup", "params": cur},
                                         ensure_ascii=False) + "\n").encode())
                await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        line.cancel()
        fake.startup_subs -= 1
