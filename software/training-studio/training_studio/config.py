"""Validated public configuration. No user input becomes a shell fragment."""
import copy
import json
import math


class StudioError(Exception):
    def __init__(self, error, status=400, detail=None):
        super().__init__(error)
        self.error, self.status, self.detail = error, status, detail


DEFAULTS = {"num_envs": 2048, "iterations": 1000, "save_interval": 50,
            "seed": 42, "learning_rate": 0.001}
BALANCE_RECIPE = "hd1910-single-leg"
SKILL_DEFAULTS = {"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}
SKILL_LIMITS = {"support_side": ["left", "right"],
                "lift_height_m": {"min": 0.005, "max": 0.02, "step": 0.005},
                "hold_seconds": {"min": 1, "max": 5, "step": 1}}
RECIPES = [
    {"id": "hd1910-flat", "title": "HD1910: caminhada em piso plano", "description": "Pratique manter o equilíbrio, andar para a frente e virar em piso plano. Faça primeiro um teste curto para confirmar que o ambiente funciona.",
     "catalog": {"category": "Caminhada", "tags": ["Piso plano", "Passada básica", "Curvas"],
                 "preview_kind": "robot_model", "source_label": "Incluído no projeto",
                 "verification_state": "pipeline", "verification_label": "Teste curto concluído",
                 "instructions": ["Comece em pé, apoiado nos dois pés.", "Pratique caminhar e virar seguindo o alvo de velocidade.", "Após o treinamento, avalie a passada real na pré-visualização do checkpoint."]},
     "task_id": "Mjlab-Velocity-Flat-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_velocity", "defaults": dict(DEFAULTS),
     "hardware": "Linux + GPU NVIDIA CUDA; modelo de servo HD1910", "validation": "Passou por teste curto de 5 iterações com 64 ambientes em WSL / RTX 5060 Ti; valida somente o fluxo, não significa que já aprendeu a caminhar."},
    {"id": "hd1910-rough", "title": "HD1910: terreno irregular", "description": "Pratique manter o equilíbrio e caminhar em terreno irregular. Primeiro conclua um teste curto com a mesma configuração.",
     "catalog": {"category": "Caminhada", "tags": ["Terreno irregular", "Passada", "Equilíbrio"],
                 "preview_kind": "text", "source_label": "Incluído no projeto",
                 "verification_state": "unverified", "verification_label": "Aguardando validação na GPU",
                 "instructions": ["Pratique caminhar em terreno irregular.", "Mantenha o corpo estável com mudanças no alvo de velocidade e no terreno.", "Por enquanto, há somente instruções da tarefa; ainda não existe uma reprodução real validada por este projeto."]},
     "task_id": "Mjlab-Velocity-Rough-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_velocity", "defaults": dict(DEFAULTS),
     "hardware": "Linux + GPU NVIDIA CUDA; modelo de servo HD1910", "validation": "Ainda não foi validado na GPU; após o treinamento, confira a reprodução antes de decidir se usará no robô."},
    {"id": BALANCE_RECIPE, "title": "HD1910: equilíbrio em um pé", "description": "Escolha o pé de apoio, a altura em que o outro pé será levantado e por quanto tempo. Treine o movimento completo de levantar, manter e apoiar o pé.",
     "catalog": {"category": "Equilíbrio", "tags": ["Apoio em um pé", "Elevação do pé", "Alvo personalizado"],
                 "preview_kind": "balance_target", "source_label": "Incluído no projeto",
                 "verification_state": "pipeline", "verification_label": "Teste curto concluído",
                 "instructions": ["Comece apoiado nos dois pés e transfira o peso para o pé de apoio.", "Levante o outro pé e mantenha a altura e o tempo definidos.", "A ação só termina depois de apoiar o pé e recuperar o apoio nos dois pés."]},
     "task_id": "Mjlab-Balance-Flat-MicroDuck-HD1910", "experiment_name": "microduck_hd1910_balance",
     "defaults": dict(DEFAULTS, num_envs=256, save_interval=25),
     "skill_defaults": dict(SKILL_DEFAULTS), "skill_limits": copy.deepcopy(SKILL_LIMITS),
     "hardware": "Linux + GPU NVIDIA CUDA; modelo de servo HD1910",
     "validation": "Foram concluídos testes curtos reais na GPU, avaliação e exportação para os dois lados; a política atual de 5 iterações teve 0/8 sucessos, ainda não aprendeu o movimento e não foi validada no robô real."},
]
RECIPE_BY_ID = {r["id"]: r for r in RECIPES}


def validate_skill(recipe_id, value):
    if not isinstance(recipe_id, str) or recipe_id not in RECIPE_BY_ID:
        raise StudioError("Receita de treinamento desconhecida")
    if recipe_id != BALANCE_RECIPE:
        if value is not None:
            raise StudioError("Receitas de caminhada não aceitam parâmetros de equilíbrio em um pé")
        return None
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(SKILL_DEFAULTS):
        raise StudioError("Os parâmetros da ação contêm campos desconhecidos ou não são um objeto JSON")
    result = dict(SKILL_DEFAULTS, **value)
    if result["support_side"] not in ("left", "right"):
        raise StudioError("support_side precisa ser left ou right")
    for name in ("lift_height_m", "hold_seconds"):
        number, limits = result[name], SKILL_LIMITS[name]
        if type(number) not in (int, float) or not limits["min"] <= number <= limits["max"] or not math.isfinite(number):
            raise StudioError(f"{name} precisa ser um número finito entre {limits['min']} e {limits['max']}")
        result[name] = float(number)
    return result


def skill_command_contract(skill):
    """Portable copy of engine balance_parameters contract; parity is tested.

    The Studio runtime need not have the engine's Python package installed.
    Update the version together with the engine when command semantics change.
    """
    skill = validate_skill(BALANCE_RECIPE, skill)
    return {
        "version": "microduck.single_leg_balance.v1",
        "actor_observation_size": 61, "action_size": 14, "control_hz": 50,
        "twist_slots": ["support_sign (+1 left, -1 right)",
                        "scheduled swing sole clearance (metres)",
                        "phase / 3 (0 init, 1 lift, 2 hold, 3 return)"],
        "phase_seconds": {"init": 1.0, "lift": 1.0,
                          "hold": skill["hold_seconds"], "return": 1.5},
        "return_includes_settle_seconds": .5,
        "cycle_seconds": skill["hold_seconds"] + 3.5,
        "head_body_commands": "Near-zero pose command padding; deployment uses zeros.",
        "runtime_adapter_required": True,
        "runtime_note": "A matching phase scheduler is required; this is not a velocity policy.",
        "hardware_validated": False, "skill": skill,
    }


def recipe_config(recipe_id, value, kind):
    if not isinstance(value, dict):
        raise StudioError("A configuração precisa ser um objeto JSON")
    return validate_config(dict(RECIPE_BY_ID[recipe_id]["defaults"], **value), kind)


def validate_config(config, kind):
    if kind not in ("smoke", "train"):
        raise StudioError("O tipo de tarefa precisa ser smoke ou train")
    if not isinstance(config, dict) or set(config) - set(DEFAULTS):
        raise StudioError("A configuração contém campos desconhecidos ou não é um objeto JSON")
    result = dict(DEFAULTS, **config)
    for name, lower, upper in (("num_envs", 16, 16384), ("iterations", 1, 100000),
                               ("save_interval", 1, 10000), ("seed", 0, 2147483647)):
        value = result[name]
        if type(value) is not int or not lower <= value <= upper:
            raise StudioError(f"{name} precisa ser um inteiro entre {lower} e {upper}")
    if result["num_envs"] % 4:
        raise StudioError("num_envs precisa ser múltiplo de 4 (restrição do minibatch PPO)")
    lr = result["learning_rate"]
    if type(lr) not in (int, float) or not 0.000001 <= lr <= 0.01 or not math.isfinite(lr):
        raise StudioError("learning_rate precisa estar entre 0.000001 e 0.01")
    result["learning_rate"] = float(lr)
    if kind == "smoke":
        result.update(num_envs=64, iterations=5, save_interval=1)
    return result


def validate_profile(profile):
    if profile is None:
        return None
    if not isinstance(profile, dict) or profile.get("schema") != "microduck-studio-duck-profile/v1":
        raise StudioError("O schema do perfil precisa ser microduck-studio-duck-profile/v1")
    allowed = {"schema", "exported_at", "note", "duck", "body", "imu", "joints", "servo", "walk_model", "policy_global", "voltage"}
    if set(profile) - allowed:
        raise StudioError("O perfil contém campos de nível superior desconhecidos")
    try:
        encoded = json.dumps(profile, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise StudioError("O perfil contém números não finitos ou valores JSON inválidos") from None
    if len(encoded) > 65536:
        raise StudioError("O perfil não pode exceder 64 KiB")

    def walk(value, depth=0):
        if depth > 10:
            raise StudioError("O perfil tem aninhamento profundo demais")
        if isinstance(value, dict):
            if len(value) > 128:
                raise StudioError("O objeto do perfil tem campos demais")
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > 100:
                    raise StudioError("O nome de campo do perfil é inválido")
                walk(child, depth + 1)
        elif isinstance(value, list):
            if len(value) > 256:
                raise StudioError("O array do perfil é longo demais")
            for child in value:
                walk(child, depth + 1)
        elif isinstance(value, str):
            if len(value) > 4096 or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
                raise StudioError("O texto do perfil é inválido ou longo demais")
        elif type(value) in (int, float):
            if abs(value) > 1e12 or not math.isfinite(value):
                raise StudioError("O número do perfil está fora dos limites")
        elif value is not None and type(value) is not bool:
            raise StudioError("O tipo do valor do perfil é inválido")

    walk(profile)
    for key in ("duck", "body", "imu", "servo", "walk_model", "policy_global", "voltage"):
        if profile.get(key) is not None and not isinstance(profile[key], dict):
            raise StudioError(f"O campo {key} do perfil precisa ser um objeto ou null")
    for key, value in (profile.get("body") or {}).items():
        if key.endswith("_g") and value is not None and (type(value) not in (int, float) or not 0 < value <= 10000):
            raise StudioError("A massa do perfil precisa estar entre 0 e 10.000 g")
    quat = (profile.get("imu") or {}).get("mount_quat_wxyz")
    if (profile.get("imu") or {}).get("verified") is not None and type(profile["imu"]["verified"]) is not bool:
        raise StudioError("IMU verified precisa ser booleano ou null")
    if quat is not None and (not isinstance(quat, list) or len(quat) != 4 or
                             any(type(v) not in (int, float) for v in quat) or
                             not 0.8 <= sum(v * v for v in quat) <= 1.2):
        raise StudioError("O quaternion da IMU precisa conter 4 números finitos e normalizados")
    joints = profile.get("joints")
    if joints is not None:
        if not isinstance(joints, list) or len(joints) > 32:
            raise StudioError("O perfil de juntas precisa ser um array com no máximo 32 itens")
        ids = set()
        for joint in joints:
            if not isinstance(joint, dict):
                raise StudioError("Cada perfil de junta precisa ser um objeto")
            jid = joint.get("id")
            if jid is not None:
                if type(jid) is not int or not 1 <= jid <= 253 or jid in ids:
                    raise StudioError("O ID da junta precisa ser único e estar entre 1 e 253")
                ids.add(jid)
            if joint.get("direction") is not None and (type(joint["direction"]) not in (int, float) or joint["direction"] not in (-1, 1)):
                raise StudioError("A direção da junta precisa ser -1 ou 1")
            for key in ("min_rad", "max_rad"):
                if joint.get(key) is not None and (type(joint[key]) not in (int, float) or abs(joint[key]) > 4 * math.pi):
                    raise StudioError("O ângulo da junta está fora dos limites")
            if joint.get("min_rad") is not None and joint.get("max_rad") is not None and joint["min_rad"] >= joint["max_rad"]:
                raise StudioError("O ângulo mínimo da junta precisa ser menor que o máximo")
    voltage = profile.get("voltage") or {}
    if set(voltage) - {"adapt", "nominal_v", "mult"}:
        raise StudioError("O perfil de tensão contém campos desconhecidos")
    if voltage.get("adapt") is not None and type(voltage["adapt"]) is not bool:
        raise StudioError("O campo adapt da tensão precisa ser booleano ou null")
    for key, upper in (("nominal_v", 30), ("mult", 10)):
        value = voltage.get(key)
        if value is not None and (type(value) not in (int, float) or not 0 < value <= upper):
            raise StudioError("O valor numérico do perfil de tensão está fora dos limites")
    return copy.deepcopy(profile)
