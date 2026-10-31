"""Backend da página da IMU: envia o estado da IMU para a interface e recebe seus comandos (seguindo o padrão de handle de servo_ops).

Plano: scratchpad console/imu-page-plan.md (escrito pelo subagente 10-18, com referências). Nesta etapa, implementamos apenas o que já é possível:
- view(): chip, estado das leituras, orientação de montagem (armazenada por chip) e horário da última calibração em pé;
- solve: envia as leituras coletadas pela interface a imu_calib.solve para calcular a orientação de montagem (somente cálculo).

O resultado aprovado da calibração completa em pé é salvo em imu-pending.json no diretório state (persiste após reiniciar o Studio) e, por fim, a lista de configuração inicial
grava-o no robotd ao selecionar “Gravar no programa”. A imagem de fábrica usa o modo de calibração: a calibração inicial coleta repouso e inclinação para a frente de busStatus.last_sample.imu,
depois envia o resultado para verify-imu do programa principal (alinhar em ≤5° e inclinar para a frente 15–30° em até 20 segundos); o próprio programa principal grava o arquivo de calibração.
A placa do barramento é detectada automaticamente na inicialização do programa principal; a detecção de chips I²C continua usando microduck-firstboot.
"""
import asyncio
import json
import math
import os
import time

from . import helper, imu_calib
from .robotd import fresh_calib
from .rpc import RpcError, Timeout, Unreachable, call_once

MAX_SAMPLES = 6000          # limite de leituras por solve (5 etapas × até 600 por etapa, com margem), para evitar pacotes enormes enviados pela interface
ON_DUCK = ("A IMU no barramento com ID 200 é detectada automaticamente na inicialização do programa principal. Conecte a IMU I²C antes da primeira inicialização; se conectá-la depois, execute por SSH: "
           "sudo microduck-firstboot --detect-imu-only --force")
# Critérios para “conferida” (revisão O4 da reorganização do painel): concluir uma calibração em pé; a diferença entre a orientação calculada e a usada pelo programa principal deve ser < 2°, e a inclinação em pé deve ser ≤ 5°
# (5° é stand_confirm_deg em imu_calib.RULES: o robotd aceita no máximo 5° ao verificar a orientação com o robô em pé)
CHECK_MAX_DIFF_DEG = 2.0


class Refused(Exception):
    """Esta operação não pode ser realizada agora; o motivo é exibido diretamente na interface."""


def imu_bus_metadata(bus):
    """Validate raw presence before projection; mirrored in the standalone helper."""
    bus = bus if isinstance(bus, dict) else {}
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    infos = [part["imu_bus"] for part in (native, bus) if "imu_bus" in part]
    profiles = [part["configured_imu_profile"] for part in (native, bus) if "configured_imu_profile" in part]
    error = None
    for info in infos:
        if (not isinstance(info, dict) or info.get("protocol") not in ("feetech", "dxl2")
                or info.get("profile", "legacy") not in ("legacy", "qinmo")
                or (info.get("profile") == "qinmo" and info.get("protocol") != "feetech")):
            error = "O programa principal informou um protocolo ou tipo de IMU incompatível ou inconsistente. Confirme antes de usar a orientação antiga ou continuar a calibração."
    if any(profile not in ("legacy", "qinmo") for profile in profiles):
        error = "O programa principal informou um protocolo ou tipo de IMU incompatível ou inconsistente. Confirme antes de usar a orientação antiga ou continuar a calibração."
    if not error:
        bindings = [(info["protocol"], info.get("profile", "legacy")) for info in infos]
        if (any(binding != bindings[0] for binding in bindings[1:])
                or any(profile != profiles[0] for profile in profiles[1:])
                or (bindings and profiles and bindings[0][1] != profiles[0])):
            error = "O programa principal informou um protocolo ou tipo de IMU incompatível ou inconsistente. Confirme antes de usar a orientação antiga ou continuar a calibração."
    return (infos[0] if infos and isinstance(infos[0], dict) else None,
            profiles[0] if profiles else None, error)


def bus_imu_of(bus):
    """Protocolo e placa do barramento detectados. No modo de movimento, os dados ficam em native; no modo de calibração, ficam no nível superior."""
    info, _configured, _error = imu_bus_metadata(bus)
    if info is None:
        return None
    out = {"protocol": info.get("protocol"), "board": info.get("board"),
           "identity": list(info["identity"]) if isinstance(info.get("identity"), list) else None}
    for key in ("profile", "gyro_dps_per_lsb", "identification"):
        if key in info:
            out[key] = info[key]
    return out


def configured_profile(bus):
    return imu_bus_metadata(bus)[1]


def bus_profile_error(bus, calib=None, source="bus"):
    """Missing old fields mean legacy; explicit unsupported evidence never does."""
    if source not in (None, "bus"):
        return None
    info, configured, error = imu_bus_metadata(bus)
    if error:
        return error
    calib = calib if isinstance(calib, dict) else {}
    cal = calib.get("calibration") if isinstance(calib.get("calibration"), dict) else calib
    bound = cal.get("imu_bus_profile", "legacy")
    protocol = cal.get("imu_bus_protocol", "feetech")
    if (bound not in ("legacy", "qinmo") or protocol not in ("feetech", "dxl2")
            or (bound == "qinmo" and protocol != "feetech")):
        return "O programa principal informou um tipo de IMU incompatível. Não é possível usar a orientação antiga nem continuar a calibração; peça à manutenção que confira o programa principal e a configuração."
    if info is None and (configured is not None or bound != "legacy"):
        return "A IMU do barramento não está conectada, então não é possível confirmar o tipo. Não é possível usar a orientação antiga nem continuar a coleta."
    return None


def bus_protocol_mismatch(bus, calib, source="bus"):
    info = bus_imu_of(bus) if source == "bus" else None
    calib = calib if isinstance(calib, dict) else {}
    cal = calib.get("calibration") if isinstance(calib.get("calibration"), dict) else calib
    configured = configured_profile(bus) if source == "bus" else None
    return bool(bus_profile_error(bus, calib, source)
                or (info and (info["protocol"] != cal.get("imu_bus_protocol", "feetech")
                    or info.get("profile", "legacy") != cal.get("imu_bus_profile", "legacy")
                    or (configured is not None and configured != info.get("profile", "legacy")))))


def calibration_context(bus, source, redo):
    metadata_error = imu_bus_metadata(bus)[2] if source in (None, "bus") else None
    info = bus_imu_of(bus) if source == "bus" else None
    transport = (info["protocol"], info["board"], tuple(info["identity"] or []),
                 info.get("profile", "legacy"), configured_profile(bus), metadata_error) if info else (
                     (None, configured_profile(bus), metadata_error)
                     if configured_profile(bus) is not None or metadata_error else None)
    return source, transport, bus.get("mode"), redo.get("session_id"), bool(redo.get("active"))


def mount_of(bus, calib):
    """(chip em uso, {"quat", "verified"} ou None). A página da IMU e a lista de configuração inicial usam a mesma seleção (revisão C3):
    primeiro, verifica imu_mount escolhido pelo robotd no topo de calibration-status; depois, imu_mounts[chip]; por último, os dados da placa do barramento.
    Não use calibration.imu_mount_verified para verificar a IMU do módulo (esse campo pertence à placa do barramento)."""
    bus = bus if isinstance(bus, dict) else {}
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    calib = calib if isinstance(calib, dict) else {}
    cal = calib.get("calibration") if isinstance(calib.get("calibration"), dict) else calib
    # Chip em uso: native.imu_source de busStatus. Se o robotd estiver aguardando o barramento, esse campo não estará em busStatus;
    # nesse caso, use imu_source no topo de calibration-status (não confunda o chip do módulo com a placa do barramento; conferência do subagente da IMU, nº 4);
    # se nenhum dos dois estiver presente, mas busStatus tiver native, trata-se da placa do barramento (plano 6.5)
    last_sample = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
    sample = last_sample.get("imu") if isinstance(last_sample.get("imu"), dict) else {}
    source = (native.get("imu_source") or sample.get("source") or calib.get("imu_source")
              or ("bus" if native or bus_imu_of(bus) else None))
    top = calib.get("imu_mount") if isinstance(calib.get("imu_mount"), dict) else None
    mounts = cal.get("imu_mounts") if isinstance(cal.get("imu_mounts"), dict) else {}
    if top and top.get("quat") and calib.get("imu_source") in (None, source):
        mount = {"quat": top.get("quat"), "verified": top.get("verified")}     # selecionado pelo próprio robotd
    elif source in mounts and isinstance(mounts[source], dict):
        mount = {"quat": mounts[source].get("quat"), "verified": mounts[source].get("verified")}
    elif cal.get("imu_mount_quat"):
        mount = {"quat": cal.get("imu_mount_quat"), "verified": cal.get("imu_mount_verified")}
    else:
        mount = None
    if mount and bus_protocol_mismatch(bus, calib, source):
        mount["verified"] = False
    return source, mount


class ImuBackend:
    def __init__(self, robotd, log, state_dir=".", root="/"):
        self.rd, self.log, self.state_dir = robotd, log, state_dir
        self.root = root
        self._seen_context = None
        self._context_generation = 0
        self._redo_busy = False
        self.job = None              # progresso da coleta inicial / envio para verificação pelo programa principal
        self.detected = None         # resultado da detecção de chip mais recente (ainda não há nenhum)
        self.last_result = None      # resultado mais recente de solve; somente este resultado pode ser gravado
        # Registro “IMU conferida” da lista de configuração inicial (revisão O4): app conecta a Onboarding.note_imu_check. Isto não grava nada no robô; para gravar, continue sendo necessário conectar-se ao robô.
        self.on_check = None
        self.commit = None           # Backend para gravar no programa principal (conectado pelo app): “habilitar postura em pé” no modo de calibração precisa usar a mesma orientação

    # ---- Envio à interface ----

    def view(self):
        bus = self.rd.bus.value if isinstance(self.rd.bus.value, dict) else {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # O estado da calibração só é válido se lido depois deste hello (revisão O5 da reorganização do painel: uma antiga confirmação não é confiável após reiniciar o robotd)
        calib = fresh_calib(self.rd)
        source, mount = mount_of(bus, calib)
        redo = self._redo_view(bus, source)
        context = calibration_context(bus, source, redo)
        if self._seen_context is not None and context != self._seen_context:
            self._context_generation += 1
            self.last_result = None
            if context[1] != self._seen_context[1] and self.job and (self.job.get("done") or self.job.get("failed")):
                self.job = None
        self._seen_context = context
        ls = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
        s_imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        reader = native.get("imu_reader")
        if reader is None and bus.get("mode") == "commissioning":
            reader = {"state": ("streaming" if s_imu.get("ready") else "missing"), "errors": 0}
        return {
            "t": "imu", "mode": bus.get("mode"), "source": source, "chip_setting": None, "mount": mount,
            "imu_bus": bus_imu_of(bus) if source == "bus" else None,
            "configured_imu_profile": configured_profile(bus),
            "profile_error": bus_profile_error(bus, calib, source),
            "metadata_error": imu_bus_metadata(bus)[2] if source in (None, "bus") else None,
            "profile_selection": self._profile_view(bus, source, redo),
            "mount_protocol_mismatch": bus_protocol_mismatch(bus, calib, source),
            "reader": reader, "age_ms": native.get("imu_age_ms", s_imu.get("age_ms")),
            "ready": native.get("imu_ready", s_imu.get("ready")),
            "valid": s_imu.get("valid"), "gravity": s_imu.get("gravity"),
            "hold": bus.get("hold") if isinstance(bus.get("hold"), dict) else None,
            "detected": self.detected, "stand_calib_at": self._stand_calib_at(), "job": self.job,
            "redo": redo,
        }

    def _redo_view(self, bus, source):
        redo = helper.imu_redo_state(root=self.root)
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
        reason = redo.get("reason")
        if redo.get("active"):
            reason = reason or "A sessão de calibração inicial da IMU já está ativa: continue ou cancele."
        elif self._redo_busy:
            reason = "Alternando para o modo de calibração inicial da IMU."
        elif source in (None, "bus") and imu_bus_metadata(bus)[2]:
            reason = imu_bus_metadata(bus)[2]
        elif bus.get("mode") != "motion" or bus.get("phase") != "control":
            reason = "Para refazer, use a etapa de controle do modo de movimento do programa principal; no modo de calibração de fábrica, faça diretamente a calibração inicial."
        elif (bus.get("policy_enabled") is not False or bus.get("home_recovery")
              or native.get("torque_state_confirmed") is not False or bus.get("torque_off_pending") is True
              or hd.get("restore_pending") is not False or hd.get("temporary_gains_applied") is not False):
            reason = "Segure o robô e desative o torque; aguarde o programa principal confirmar que todos os servos estão desativados e os ganhos temporários foram restaurados."
        elif source not in ("bus", "bno08x", "lsm6dsv16x"):
            reason = "A origem atual da IMU ainda não foi lida."
        elif helper.flag_present():
            reason = "A página dos servos está usando o barramento; devolva o controle ao programa principal primeiro."
        return {**redo, "can_start": reason is None, "reason": reason}

    def _profile_view(self, bus, source, redo):
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        hd = native.get("hd1910") if isinstance(native.get("hd1910"), dict) else {}
        reason = None
        if imu_bus_metadata(bus)[2]:
            reason = imu_bus_metadata(bus)[2]
        elif configured_profile(bus) not in ("legacy", "qinmo"):
            reason = "O programa principal ainda não permite selecionar o tipo pela interface. Peça à manutenção que atualize o programa principal."
        elif source not in (None, "bus"):
            reason = "A IMU atual usa I²C; não é necessário selecionar o tipo da placa do barramento."
        elif redo.get("active") or self._redo_busy:
            reason = "Conclua ou cancele a sessão atual de calibração da orientação de montagem."
        elif helper.flag_present():
            reason = "A página dos servos está usando o barramento; devolva o controle ao programa principal primeiro."
        elif bus.get("mode") == "motion" and bus.get("phase") == "control":
            if (bus.get("policy_enabled") is not False or bus.get("home_recovery")
                    or native.get("torque_state_confirmed") is not False or bus.get("torque_off_pending") is True
                    or hd.get("restore_pending") is not False or hd.get("temporary_gains_applied") is not False):
                reason = "Segure o robô e desative o torque; aguarde o programa principal confirmar que todos os servos estão desativados e os ganhos temporários foram restaurados."
        elif bus.get("mode") not in ("motion", "commissioning") or bus.get("phase") not in (
                "configuring_bus", "waiting_for_bus", "ready"):
            reason = "Segure o robô, desative o torque e aguarde o programa principal ficar pronto para reconexão."
        return {"can_start": reason is None, "reason": reason}

    def blocks_updates(self):
        return self._redo_busy or helper.imu_redo_state(root=self.root).get("active", False)

    def _coarse_guard(self, bus):
        calib = fresh_calib(self.rd)
        source, _ = mount_of(bus, calib)
        if error := bus_profile_error(bus, calib, source):
            self.last_result = None
            raise Refused(error)
        redo = helper.imu_redo_state(root=self.root)
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        hold = bus.get("hold") if isinstance(bus.get("hold"), dict) else {}
        transitioning = (bus.get("torque_off_pending") not in (None, False)
                         or bus.get("power_pending") or bus.get("motion") or bus.get("home_recovery")
                         or bus.get("policy_enabled") is True or bus.get("policy_motion_enabled") is True)
        error = hold.get("max_error_deg")
        settled_hold = (not redo.get("active") and bus.get("mode") == "commissioning"
                        and bus.get("phase") == "holding" and bus.get("torque_state") == "all_enabled"
                        and hold.get("stage") == "holding" and native.get("torque_state_confirmed") is not False
                        and isinstance(error, (int, float)) and not isinstance(error, bool)
                        and math.isfinite(error) and 0 <= error <= 5)
        relaxed = (bus.get("torque_state") == "off" and native.get("torque_state_confirmed") is not True
                   and not hold)
        if transitioning or not (relaxed or settled_hold):
            raise Refused("A calibração inicial da IMU exige torque desativado ou que o robô esteja estável na postura em pé habilitada no modo de calibração (erro em relação a HOME ≤5°);"
                          "não colete dados enquanto o robô estiver se levantando, em movimento ou sem confirmação de torque desativado. Segure o robô com as duas mãos.")
        if redo.get("active"):
            if redo.get("phase") not in ("commissioning", "finish_failed"):
                raise Refused(redo.get("reason") or "A mudança de modo para refazer a calibração inicial da IMU não foi concluída. Cancele ou restaure a sessão primeiro.")
            source, _ = mount_of(bus, fresh_calib(self.rd))
            if source != redo.get("source"):
                self.last_result = None
                raise Refused("A origem da IMU mudou durante a sessão de repetição. Cancele e recomece.")
        return redo

    async def _redo_op(self, args, by=None):
        if args.get("confirmed") is not True:
            raise Refused("Confirme primeiro que está segurando o robô e que o torque está desativado; depois refaça ou cancele a calibração inicial da IMU.")
        if self._redo_busy:
            raise Refused("A calibração inicial da IMU está alternando de modo. Aguarde a conclusão.")
        selecting = args["op"] == "profile-select"
        if selecting and (set(args) - {"op", "profile", "confirmed"} or args.get("profile") not in ("legacy", "qinmo")):
            raise Refused("O tipo da IMU deve ser detectado automaticamente pela placa atual ou ser Qinmo.")
        action = "enter" if args["op"] in ("redo-start", "profile-select") else "cancel"
        redo = helper.imu_redo_state(root=self.root)
        if action == "enter":
            bus = await self._bus_once()
            source, _ = mount_of(bus, fresh_calib(self.rd))
            metadata_error = imu_bus_metadata(bus)[2]
            if metadata_error and (selecting or source in (None, "bus")):
                raise Refused(metadata_error)
            if selecting and configured_profile(bus) not in ("legacy", "qinmo"):
                raise Refused("O programa principal ainda não permite selecionar o tipo pela interface. Peça à manutenção que atualize o programa principal.")
            info = bus_imu_of(bus)
            if selecting and info is not None and info.get("profile", "legacy") not in ("legacy", "qinmo"):
                raise Refused(bus_profile_error(bus))
            if not selecting and bus.get("mode") != "motion":
                raise Refused("No modo de calibração de fábrica, faça diretamente a calibração inicial; somente o modo de movimento exige uma sessão de repetição.")
            if redo.get("active"):
                raise Refused("A sessão de repetição da calibração inicial da IMU já está ativa: continue ou cancele.")
            if not helper.available():
                raise Refused("Para refazer a calibração inicial da IMU, instale a nova versão do assistente root e do sudoers (deploy/install.sh).")
        elif not redo.get("active") or not redo.get("session_id"):
            raise Refused("Não há sessão de repetição da calibração inicial da IMU para cancelar.")
        self._redo_busy = True
        self.last_result = None
        self.job = {"kind": "coarse", "title": "Alternando a calibração inicial da IMU", "msg": "Segure o robô, mantenha o torque desativado e aguarde a mudança do programa principal."}
        try:
            kw = {"confirmed": True}
            if selecting:
                kw["profile"] = args["profile"]
            if action == "cancel":
                kw["session_id"] = redo["session_id"]
            ok, result, detail = await asyncio.to_thread(helper.imu_recalibrate, by or "Studio", action, **kw)
            if not ok:
                raise Refused(helper.friendly(result, detail, "imu-recalibrate"))
            if selecting:
                from .commit import clear_pending
                clear_pending(self.state_dir)
            self.job = None
            self.view()
            note = ("O tipo e a orientação originais foram restaurados; mantenha o modo de calibração. Agora você pode selecionar e verificar novamente."
                    if action == "cancel" and (detail or {}).get("original_mode") in ("startup", "commissioning") else None)
            return {"ok": True, "result": result, "redo": detail, "note": note}
        except Refused as err:
            self.job = {"kind": "coarse", "title": "A mudança para a calibração inicial da IMU não foi concluída", "failed": True, "msg": str(err)}
            raise
        finally:
            self._redo_busy = False

    def _stand_calib_at(self):
        try:
            with open(os.path.join(self.state_dir, "imu-stand-calib.json"), encoding="utf-8") as f:
                return json.load(f).get("at")
        except (OSError, ValueError):
            return None

    # ---- Comandos da interface ----

    async def _bus_once(self):
        """No modo de calibração, uma nova conexão lê busStatus diretamente; em testes/bancada sem endereço, usa-se o valor armazenado em cache."""
        addr = getattr(self.rd, "addr", None)
        if addr and addr != "none":
            r = await call_once(addr, "robot.busStatus", {}, timeout=1.5, name="Leitura da calibração inicial")
            return r if isinstance(r, dict) else {}
        v = getattr(getattr(self.rd, "bus", None), "value", None)
        return v if isinstance(v, dict) else {}

    async def _rpc_once(self, method, params, timeout, name):
        """Abre uma nova conexão para consultar uma vez. Se o rd simulado em testes/bancada não tiver endereço, usa a conexão cmd dele."""
        addr = getattr(self.rd, "addr", None)
        if addr and addr != "none":
            return await call_once(addr, method, params, timeout=timeout, name=name)
        conn = getattr(self.rd, "cmd", None)
        call = getattr(conn, "call", None)
        if call is None:
            raise Unreachable("Sem conexão com o programa principal. Aguarde sua inicialização e tente novamente.")
        return await call(method, params, timeout)

    @staticmethod
    def _sample_g(bus):
        ls = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
        imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        g = imu.get("gravity")
        if imu.get("valid") is not True or not isinstance(g, list) or len(g) != 3:
            return None, imu
        try:
            v = [float(x) for x in g]
        except (TypeError, ValueError):
            return None, imu
        if not all(math.isfinite(x) for x in v) or sum(x * x for x in v) < 1e-9:
            return None, imu
        return v, imu

    async def _capture(self, args, by=None):
        phase = args.get("phase")
        if phase not in ("still", "fwd", "back"):
            raise Refused("A coleta inicial aceita somente still / fwd / back.")
        seconds = args.get("seconds", 3.0 if phase != "back" else 2.0)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0.5 <= float(seconds) <= 8.0:
            raise Refused("O tempo de coleta deve ficar entre 0,5 e 8 segundos.")
        out, t0, last_tilt = [], time.monotonic(), None
        capture_context = None
        capture_generation = self._context_generation
        label = {"still": "Deixe o robô nivelado e parado", "fwd": "Incline para a frente", "back": "Incline para trás"}[phase]
        self.job = {"kind": "coarse", "title": "Coleta inicial", "msg": f"{label}：{float(seconds):g} s",
                    "target_deg": 20 if phase == "fwd" else 0, "hold": 0.0}
        while time.monotonic() - t0 < float(seconds):
            bus = await self._bus_once()
            if bus.get("mode") != "commissioning":
                self.job = {"kind": "coarse", "title": "Coleta inicial", "failed": True,
                            "msg": "O programa principal não está mais no modo de calibração."}
                if bus.get("mode") == "motion":
                    raise Refused("O programa principal já está no modo de movimento. Depois de colocar o robô em pé, use a calibração em pé.")
                raise Refused("O programa principal não está no modo de calibração. Aguarde até que volte a esse modo para fazer a calibração inicial.")
            self._coarse_guard(bus)
            source, _ = mount_of(bus, fresh_calib(self.rd))
            redo = helper.imu_redo_state(root=self.root)
            context = calibration_context(bus, source, redo)
            if (self._context_generation != capture_generation
                    or (capture_context is not None and context != capture_context)):
                self.last_result = None
                raise Refused("Coleta inicialA origem da IMU, a placa do barramento, o modo ou a sessão mudou durante a coleta. Colete os dados novamente.")
            capture_context = context
            g, imu = self._sample_g(bus)
            if g is not None:
                out.append({"step": phase, "t": time.monotonic() - t0, "g": g})
                tilt = imu.get("tilt_deg")
                if isinstance(tilt, (int, float)):
                    last_tilt = float(tilt)
            self.job.update({"hold": min(1.0, (time.monotonic() - t0) / float(seconds)),
                             "tilt_deg": last_tilt})
            await asyncio.sleep(0.1)
        if self._context_generation != capture_generation:
            self.last_result = None
            raise Refused("Coleta inicialO contexto da IMU mudou durante a coleta. Colete os dados novamente.")
        if len(out) < 15:
            self.job = {"kind": "coarse", "title": "Coleta inicial", "failed": True,
                        "msg": f"Apenas {len(out)} leituras válidas foram coletadas"}
            raise Refused(f"Apenas {len(out)} leituras válidas da IMU foram coletadas (mínimo: 15). Verifique a conexão do módulo ou reconecte-o antes de reiniciar.")
        self.job = {"kind": "coarse", "title": "Coleta inicial", "msg": f"{label}coletado",
                    "done": True, "tilt_deg": last_tilt, "target_deg": 20 if phase == "fwd" else 0}
        self.log.info(f"Calibração inicial da IMU: {len(out)} leituras coletadas para “{label}”.", cat="IMU",
                      ctx={"by": by, "phase": phase, "source": self.view().get("source")})
        return {"phase": phase, "n": len(out), "samples": out}

    @staticmethod
    def _translate_verify_error(err):
        text = getattr(err, "message", None) or str(err)
        low = text.lower()
        if "needs a live" in low or "last_sample" in low:
            msg = "O programa principal não está recebendo leituras da IMU. Verifique a conexão do módulo, confirme o modo de calibração e veja se as leituras estão sendo atualizadas."
        elif "from upright" in low or "stand the robot upright" in low:
            msg = "O robô não está nivelado. Segure-o com as duas mãos para que o programa principal detecte inclinação ≤5°. Se o limite continuar sendo excedido, a orientação de montagem pode estar incorreta."
        elif "from nose-down" in low or "about the vertical axis" in low:
            msg = "A direção da inclinação está incorreta. O módulo pode estar invertido ou girado cerca de 90° em torno do eixo vertical. Confira a montagem física e refaça."
        elif "no nose-down tip" in low or "within 20 s" in low:
            msg = "Tempo esgotado sem detectar inclinação para a frente. Depois de nivelar o robô, incline-o 15–30° para a frente em até 20 segundos e mantenha a posição."
        elif "cancelled by relax" in low:
            msg = "A verificação foi interrompida ao desativar o torque. Segure o robô e tente novamente."
        else:
            msg = f"O programa principal reprovou a verificação: {text}"
        return msg + " O programa principal não salvou nada (Nothing saved)."

    async def _hold(self, by=None):
        """“Habilitar postura em pé” no modo de calibração (pedido do usuário em 21/10: “Se a calibração também pode deixar o robô em pé, por que é preciso mudar para o modo de movimento?”).
        No fork, hold-home do modo de calibração move os 15 servos juntos até HOME em 3 segundos, trava-os e mantém as leituras da IMU; a calibração em pé é feita no próprio modo de calibração.
        A orientação é a mesma da etapa 3, “Gravar no programa”; os offsets são os do arquivo do programa principal (2048 de fábrica). Torque desativado = opção “Desativar torque” no topo (robot.relax)."""
        if helper.imu_redo_state(root=self.root).get("active"):
            raise Refused("Mantenha o torque desativado durante a repetição da calibração inicial da IMU; não habilite a postura em pé.")
        bus = await self._bus_once()
        if bus.get("mode") != "commissioning":
            raise Refused("O programa principal não está no modo de calibração. No modo de movimento, use “Ficar em pé” no cartão do controle.")
        if self.commit is None:
            raise Refused("O backend “Gravar no programa” não está habilitado neste robô; não é possível calcular a orientação dos 15 servos.")
        from .commit import Refused as CommitRefused
        try:
            dirs = self.commit.hold_directions()
        except CommitRefused as e:
            raise Refused(str(e)) from e
        try:
            # command_timeout do fork: 3 segundos para subir + 2 segundos para estabilizar + 10 segundos, com margem adicional
            r = await self._rpc_once("robot.busCommand",
                                     {"action": "hold-home", "directions": dirs, "duration_ms": 3000},
                                     20.0, "Habilitar postura em pé")
        except (RpcError, Timeout, Unreachable) as e:
            text = getattr(e, "message", None) or str(e)
            low = text.lower()
            if "unknown variant" in low or "hold-home" in low and "unknown" in low:
                msg = "A versão do programa principal é antiga demais para deixar o robô em pé no modo de calibração. Atualize o programa principal."
            elif "still" in low and "from home" in low:
                msg = f"Uma articulação não conseguiu chegar à postura em pé ({text}). Provavelmente está invertida ou travada; o torque foi desativado. Confira a orientação na página dos servos."
            elif "relax" in low:
                msg = "O movimento para ficar em pé foi interrompido ao desativar o torque."
            else:
                msg = f"Não foi possível ficar em pé: {text}"
            self.log.warn(f"Falha ao habilitar a postura em pé no modo de calibração: {msg}", cat="IMU", raw=text, ctx={"by": by, "directions": dirs})
            raise Refused(msg) from e
        self.log.info("Postura em pé habilitada no modo de calibração; o robô está estável.", cat="IMU", raw=json.dumps(r, ensure_ascii=False)[:400],
                      ctx={"by": by, "directions": dirs})
        return r

    async def _verify(self, args, by=None):
        bus = await self._bus_once()
        if bus.get("mode") != "commissioning":
            raise Refused("O programa principal já está no modo de movimento. Depois de colocar o robô em pé, use a calibração em pé.")
        redo = self._coarse_guard(bus)
        self.view()  # invalidate a result from a different mode/source/session before consuming it
        source, _ = mount_of(bus, fresh_calib(self.rd))
        context = calibration_context(bus, source, redo)
        generation = self._context_generation
        verified_info = bus_imu_of(bus)
        verified_bus = {"imu_bus": verified_info} if verified_info is not None else {}
        if self._seen_context != context:
            self.last_result = None
        mount = args.get("mount_wxyz") or args.get("mount")
        if args.get("confirmed") is not True or not isinstance(mount, list) or len(mount) != 4:
            raise Refused("Confira a montagem física do módulo e marque a confirmação antes de enviar para verificação pelo programa principal.")
        last = self.last_result if isinstance(self.last_result, dict) else {}
        if not last.get("ok") or last.get("mode") != "coarse" or last.get("mount") != mount:
            raise Refused("Esta orientação não foi calculada na calibração inicial mais recente. Recalcule e verifique novamente.")
        self.job = {"kind": "coarse", "title": "Enviar ao programa principal para verificação",
                    "msg": "Nivele o robô e incline-o 15–30° para a frente em até 20 segundos.", "target_deg": 20}
        try:
            # command_timeout do fork: janela de 20 segundos + 10 segundos, com mais 5 segundos de margem
            r = await self._rpc_once("robot.busCommand",
                                     {"action": "verify-imu", "confirmed": True, "mount_wxyz": mount},
                                     35.0, "Verificar orientação da IMU")
        except (RpcError, Timeout, Unreachable) as e:
            msg = self._translate_verify_error(e)
            self.job = {"kind": "coarse", "title": "Verificação reprovada pelo programa principal", "failed": True, "msg": msg,
                        "raw": getattr(e, "message", None) or str(e)}
            self.log.warn(f"Verificação da calibração inicial da IMU reprovada: {msg}", cat="IMU", raw=str(e),
                          ctx={"by": by, "source": self.view().get("source")})
            raise Refused(msg) from e
        # A verifier reply alone is not success: read the exact active source and normalized mount back.
        try:
            status = await self._verified_readback(source, mount, transport=context[1], generation=generation)
            current_redo = helper.imu_redo_state(root=self.root)
            if redo.get("active"):
                if not current_redo.get("active") or current_redo.get("session_id") != redo.get("session_id"):
                    raise Refused("A sessão de repetição mudou após a verificação da IMU; não foi possível voltar ao modo de movimento.")
                ok, result, detail = await asyncio.to_thread(
                    helper.imu_recalibrate, by or "Studio", "finish", session_id=redo["session_id"],
                    source=source, quat=self._normalized_quat(mount))
                if not ok:
                    raise Refused(helper.friendly(result, detail, "imu-recalibrate"))
                status = await self._verified_readback(source, mount,
                    motion=redo.get("original_mode") != "commissioning", transport=context[1])
            elif current_redo.get("active"):
                raise Refused("Outra sessão de repetição foi iniciada durante a verificação da IMU; operação não concluída.")
            from .commit import clear_pending, load_pending, pending_matches
            pending = load_pending(self.state_dir)
            if pending and not pending_matches(pending, source, verified_bus):
                try:
                    clear_pending(self.state_dir)
                except OSError as err:
                    raise Refused("O programa principal verificou a orientação de montagem, mas não foi possível limpar o resultado antigo da calibração em pé. Refaça a calibração em pé antes de gravar no programa principal.") from err
        except (RpcError, Timeout, Unreachable, Refused) as err:
            msg = str(err) if isinstance(err, Refused) else f"Após a resposta da verificação, o programa principal não confirmou a leitura da calibração: {err}"
            self.job = {"kind": "coarse", "title": "A leitura da calibração da IMU ainda não foi confirmada", "failed": True, "msg": msg}
            self.last_result = None
            raise Refused(msg) from err
        self.last_result = None
        self.job = {"kind": "coarse", "title": "Verificação aprovada pelo programa principal", "done": True,
                    "msg": "Orientação da IMU confirmada e gravada no arquivo de calibração."}
        self.log.info("Calibração inicial da IMU aprovada: o programa principal gravou a orientação de montagem no arquivo de calibração.", cat="IMU",
                      ctx={"by": by, "source": self.view().get("source"), "mount": mount})
        return {"ok": True, "note": "Verificação aprovada pelo programa principal; orientação de montagem gravada no arquivo de calibração.", "reply": r, "calibration": status}

    @staticmethod
    def _normalized_quat(quat):
        if (not isinstance(quat, list) or len(quat) != 4
                or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) for x in quat)):
            raise Refused("O quaternion da IMU retornado é inválido.")
        norm = math.sqrt(sum(x*x for x in quat))
        if norm < 1e-9:
            raise Refused("O quaternion da IMU retornado é inválido.")
        return [x/norm for x in quat]

    async def _verified_readback(self, source, mount, motion=False, transport=None, generation=None):
        status = await self._rpc_once("robot.busCommand", {"action": "calibration-status"}, 5.0, "Reler o estado da calibração")
        bus = await self._bus_once()
        if generation is not None and self._context_generation != generation:
            raise Refused("O contexto mudou durante a verificação da IMU. Colete os dados novamente e repita a verificação.")
        if calibration_context(bus, source, {})[1] != transport:
            raise Refused("A placa do barramento mudou durante a verificação da IMU. Colete os dados novamente e repita a verificação.")
        if not isinstance(status, dict) or status.get("imu_source") != source:
            raise Refused("A origem atual da IMU não foi lida corretamente pelo programa principal.")
        got_source, got_mount = mount_of(bus, status)
        if got_source != source or not got_mount or got_mount.get("verified") is not True:
            raise Refused("A origem da IMU ou o campo verified não foi lido corretamente pelo programa principal.")
        expected, got = self._normalized_quat(mount), self._normalized_quat(got_mount.get("quat"))
        if not all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-8) for a, b in zip(got_mount["quat"], got)):
            raise Refused("O quaternion da IMU retornado pelo programa principal não está normalizado.")
        if not all(math.isclose(a, b, rel_tol=0.0, abs_tol=1e-8) for a, b in zip(expected, got)):
            raise Refused("A orientação retornada pelo programa principal não corresponde à orientação que acabou de ser verificada.")
        cal = status.get("calibration") if isinstance(status.get("calibration"), dict) else {}
        stored = ({"quat": cal.get("imu_mount_quat"), "verified": cal.get("imu_mount_verified")}
                  if source == "bus" else (cal.get("imu_mounts") or {}).get(source) or {})
        raw = stored.get("quat")
        if (stored.get("verified") is not True or not isinstance(raw, list) or len(raw) != 4
                or not all(isinstance(a, (int, float)) and not isinstance(a, bool)
                           and math.isclose(a, b, rel_tol=0.0, abs_tol=1e-8) for a, b in zip(raw, expected))):
            raise Refused("Os campos originais de calibração da IMU retornados pelo programa principal são inconsistentes.")
        if motion and (bus.get("mode") != "motion" or bus.get("phase") != "control"):
            raise Refused("A orientação da IMU foi verificada, mas o modo de movimento ainda não foi confirmado na leitura de retorno.")
        if hasattr(self.rd, "calib"):
            self.rd.calib.set(status)
        return status

    async def handle(self, args, by=None):
        op = args.get("op")
        if op in ("redo-start", "redo-cancel", "profile-select"):
            return await self._redo_op(args, by)
        if op == "solve":
            samples = args.get("samples")
            if not isinstance(samples, list) or not samples:
                raise Refused("Nenhuma leitura recebida.")
            if len(samples) > MAX_SAMPLES:
                raise Refused(f"Leituras demais ({len(samples)}; máximo: {MAX_SAMPLES}).")
            mode = args.get("mode", "full")
            if mode not in ("full", "coarse"):
                raise Refused(f"Modo de calibração desconhecido: {mode}")
            if mode == "coarse" and self.view().get("mode") == "motion":
                raise Refused("O programa principal já está no modo de movimento. Depois de colocar o robô em pé, use a calibração em pé.")
            # A orientação antiga válida é somente a do programa principal (não a enviada pela interface); rules/home_gravity recebidos da interface também não são encaminhados (revisão A3).
            view = self.view()
            if view.get("profile_error"):
                raise Refused(view["profile_error"])
            context = self._seen_context
            generation = self._context_generation
            redo = helper.imu_redo_state(root=self.root)
            if redo.get("active") and mode != "coarse":
                raise Refused("Durante a repetição da calibração inicial da IMU, use a coleta inicial de repouso/inclinação para a frente e mantenha o torque desativado.")
            if mode == "coarse":
                self._coarse_guard(await self._bus_once())
            old = (view["mount"] or {}).get("quat")
            old_verified = bool((view["mount"] or {}).get("verified"))
            res = await asyncio.to_thread(lambda: imu_calib.solve(
                samples, frame="body", old_mount=old, mode=mode, old_verified=old_verified))
            self.view()
            if self._seen_context != context or self._context_generation != generation:
                self.last_result = None
                raise Refused("A origem da IMU, a placa do barramento, o modo ou a sessão mudou após a coleta. Colete os dados e calcule novamente.")
            self.last_result = res
            detail = json.dumps({k: res.get(k) for k in ("mount", "quality", "confirm", "parts", "redo") if k in res},
                                ensure_ascii=False)[:1500]
            if res.get("ok"):
                self.log.info("A orientação de montagem da IMU foi calculada (ainda não foi gravada no programa principal).", cat="IMU", raw=detail,
                              ctx={"by": by, "source": view["source"], "mode": mode, "old_verified": old_verified})
                if mode == "full":
                    try:
                        from .commit import save_pending
                        save_pending(self.state_dir, view["source"], res.get("mount"), res.get("quality"), by,
                                     imu_bus=view.get("imu_bus"))
                    except Exception as e:  # noqa: BLE001 —— Não conseguir salvar não impede a exibição do resultado atual na interface.
                        self.log.error("Não foi possível salvar a orientação atual da IMU.", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                                       hint="O resultado será salvo novamente na próxima calibração; se continuar falhando, exporte o pacote de diagnóstico.")
                    res["check"] = self._check(res, view, old, old_verified, by)
            else:
                redo = "、".join(res.get("redo") or []) or "—"
                self.log.warn(f"Calibração da IMU reprovada: {res.get('reason')} (etapas a refazer: {redo})", cat="IMU", raw=detail, step="Calcular orientação de montagem",
                              ctx={"by": by, "source": view["source"], "mode": mode},
                              hint="Refaça a etapa seguindo as instruções da interface; se ainda não funcionar, exporte o pacote de diagnóstico.")
            return res
        if op == "hold":
            return await self._hold(by)
        if op == "coarse-capture":
            try:
                return await self._capture(args, by)
            except (Exception, asyncio.CancelledError) as err:
                self.job = {"kind": "coarse", "title": "Coleta inicial não concluída", "failed": True,
                            "msg": str(err) or "Coleta interrompida: colete novamente ou cancele a repetição."}
                raise
        if op == "verify":
            return await self._verify(args, by)
        if op in ("save", "coarse", "detect", "set_chip"):
            if op == "save":
                raise Refused("A nova orientação da IMU foi salva. Vá à etapa 3 da “Lista de configuração inicial” e selecione “Gravar no programa”.")
            if op == "coarse":
                raise Refused("Para a calibração inicial, use os três botões da interface: coletar em repouso, coletar inclinado para a frente e enviar ao programa principal para verificação.")
            raise Refused(ON_DUCK)
        raise Refused(f"Comando desconhecido: {op}")

    def _check(self, res, view, old, old_verified, by):
        """Após concluir a calibração completa em pé (solve full, ok), compara a orientação calculada com a usada pelo programa principal. Se forem próximas, registra “conferida” na lista inicial (revisão O4).
        Registra somente a conferência; **não grava nada no robô** (para gravar, é necessário conectar-se a ele). Retorna {recorded, diff_deg, tilt_deg, why} para a interface."""
        parts = res.get("parts") or {}
        diff, tilt = parts.get("total_deg"), parts.get("stand_tilt_deg")
        why = None
        if not old or not old_verified:
            why = "A orientação salva pelo programa principal ainda não foi confirmada (verified não é true). Faça a calibração inicial e grave a orientação antes de conferi-la."
        elif not isinstance(diff, (int, float)) or not isinstance(tilt, (int, float)):
            why = "Não foi possível calcular a diferença angular desta vez."
        elif tilt > imu_calib.RULES["stand_confirm_deg"]:
            why = (f"Inclinação na postura em pé: {tilt:.1f}° (deve ser ≤ {imu_calib.RULES['stand_confirm_deg']:.0f}°). Provavelmente o zero das pernas não foi calibrado corretamente,"
                   "a mesa está desnivelada ou alguém tocou no robô enquanto ele estava parado.")
        elif diff >= CHECK_MAX_DIFF_DEG:
            why = f"A orientação usada pelo programa principal difere {diff:.1f}° do resultado atual (deve ser < {CHECK_MAX_DIFF_DEG:g}°). Grave a nova orientação (é necessário conectar-se ao robô)."
        ok = why is None
        out = {"recorded": False, "ok": ok, "diff_deg": diff, "tilt_deg": tilt, "why": why}
        hook = self.on_check
        # Não registra orientações ainda não confirmadas (a etapa correspondente na lista continua como “não feita”). Registra também diferenças grandes: a lista informa a diferença mais recente e marca que é preciso refazer.
        if hook is not None and old and old_verified and isinstance(diff, (int, float)):
            try:
                out["recorded"] = bool(hook({"source": view["source"], "quat": old, "verified": True,
                                             "diff_deg": diff, "tilt_deg": tilt, "ok": ok, "by": by}))
            except Exception as e:  # noqa: BLE001 —— Falha ao registrar não afeta o cálculo da orientação.
                self.log.error("Erro ao registrar “IMU conferida”.", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                               hint="Este é um problema do Studio; o resultado da calibração continua disponível.")
        if ok:
            self.log.info(f"Orientação da IMU conferida: diferença de {diff:.1f}° em relação à orientação usada pelo programa principal; inclinação em pé de {tilt:.1f}°.", cat="IMU",
                          ctx={"by": by, "source": view["source"]})
        else:
            self.log.info(f"A orientação da IMU não foi marcada como conferida desta vez: {why}", cat="IMU", ctx={"by": by, "source": view["source"]})
        return out
