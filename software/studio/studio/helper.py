"""Controla o assistente root (/usr/local/sbin/microduck-helper) para parar e iniciar o robotd principal (transferência do barramento dos servos).

O Studio não é root. O sudoers autoriza somente o caminho completo de microduck-helper, então usamos `sudo -n`
para chamá-lo e enviar um JSON pela entrada padrão; nenhuma outra permissão é concedida. O assistente aceita os verbos fixos bus-take / bus-give-back /
bus-abort / pad-pair / pad-forget / wifi-hotspot-down / wifi-hotspot-up / calib-read / calib-commit /
ssh-status / ssh-password / imu-recalibrate e valida cada parâmetro;
ele próprio lê o estado do robotd, sem confiar nos dados enviados pela interface (deploy/INSTALL.md).

- bus-take: para o robotd, cria o bloqueio (impede o robotd de iniciar), confirma que a porta serial foi liberada e então o Studio abre o barramento. Não desativa o torque.
- bus-give-back {"soft": true}: o Studio já desativou todo o torque no barramento → remove o bloqueio, inicia o robotd e aguarda o sucesso das quatro etapas de inicialização.
- bus-give-back {"marker": {...}}: devolve sem desativar o torque (grava um marcador de transferência para o robotd do fork ler e assumir a retenção).
  Só é reconhecido se o robotd do fork estiver instalado e o drop-in habilitar Environment; versões antigas ignoram o marcador e desativam todo o torque como antes (result=limp).
- pad-pair: executa como root o comando oficial `robotctl pad pair --json`. Na placa weird-ble, o robotctl primeiro para o btd e reinicia a alimentação do adaptador,
  permitindo parear controles recentes do tipo Switch Pro. Versões antigas do assistente retornam bad_verb e o chamador recorre a configd / bluetoothctl.
- pad-forget: executa como root o comando oficial `robotctl pad forget MAC`.
- wifi-hotspot-down / wifi-hotspot-up: desliga/liga o hotspot do robô durante a configuração da rede (nmcli connection down / up
  Microduck-Hotspot). Se o hotspot já estiver desligado/ligado, conta como sucesso; esses comandos usam wifi.lock, não o helper.lock do barramento.
- calib-read: lê somente o arquivo de calibração atual e retorna o conteúdo interpretado e o modo atual (calibração/movimento); não bloqueia nem grava nada.
- calib-commit: grava os offsets e as orientações dos servos e da IMU no arquivo de calibração do robotd (hd1910-calibration.toml);
  na imagem de fábrica, também remove o drop-in commissioning e reinicia o programa principal no modo de movimento. Para ter sucesso, exige
  mode=motion, phase=control e correspondência campo a campo com calibration-status. O processo roda em uma unidade systemd separada,
  portanto, reiniciar o Studio só torna a saída temporariamente indisponível; o resultado final fica em /run/microduck-helper/last-result.json.
  dry_run retorna apenas o TOML que seria gravado. Versões antigas do assistente retornam bad_verb e o chamador orienta a reinstalação.

Sem o assistente instalado (desenvolvimento no computador, bancada ou demonstração), há uma alternativa: bus_take não faz nada (deixa a verificação própria de servo.open
robotd_active relatar o erro) e bus_give_back também não faz nada (o programa principal é iniciado manualmente após devolver o barramento).
"""
import json
import os
import queue
import re
import stat
import subprocess
import sys
import threading
import time

HELPER = "/usr/local/sbin/microduck-helper"
FLAG = "/run/microduck-helper/bus-held"       # Permanece ativo enquanto o barramento está sob controle do Studio; o drop-in do robotd impede sua inicialização
LAST_RESULT = "/run/microduck-helper/last-result.json"
IMU_REDO_MANIFEST = "/var/lib/microduck-helper/imu-recalibrate/manifest.json"
NATIVE_UPDATE_JOURNAL = "/var/lib/microduck-helper/native-update/journal.json"
NATIVE_UPDATE_ACTIVE = "/var/lib/microduck-helper/native-update/active"
NATIVE_UPDATE_EXCLUSIONS = (NATIVE_UPDATE_ACTIVE, "/run/microduck-helper/native-update-restore",
    "/etc/systemd/system/robotd.service.d/zzzzzzz-microduck-native-update.conf", *(
        "/etc/systemd/system/"+unit+".service.d/zzzzzzz-microduck-native-update.conf"
        for unit in ("padd", "gamesir-xboxd", "duck-echo")))

_avail = None


def flag_present():
    """Verifica se o marcador de tomada de controle existe (somente no Linux; computadores/testes substituem esta função)."""
    if not sys.platform.startswith("linux"):
        return False
    return os.path.exists(FLAG)


def available(refresh=False):
    """Verifica se o assistente está instalado e autorizado pelo sudoers (resultado em cache: isso não muda durante a execução).
    Testa com `sudo -n microduck-helper bus-nope`: se puder executar, retorna 2 (verbo desconhecido, indicando que o arquivo existe e o sudoers autoriza);
    Qualquer outro retorno indica que não está instalado, autorizado ou em execução no Linux. Com refresh=True, testa novamente (necessário a cada conexão de rede)."""
    global _avail
    if refresh:
        _avail = None
    if _avail is not None:
        return _avail
    if not sys.platform.startswith("linux") or not os.path.exists(HELPER):
        _avail = False
        return False
    try:
        r = subprocess.run(["sudo", "-n", HELPER, "bus-nope"], capture_output=True, text=True, timeout=5)
        _avail = r.returncode == 2
    except (OSError, subprocess.TimeoutExpired):
        _avail = False
    return _avail


def _call(verb, payload, timeout, on_line=None):
    """Executa `sudo -n microduck-helper <verb>` e envia JSON pela entrada padrão. Retorna (ok, result, detail).
    ok indica que exit na última linha done é 0; result/detail vêm do campo detail dessa linha.
    Se on_line for informado, encaminha cada linha de progresso durante a execução (por exemplo, ao gravar a calibração); caso contrário, aguarda o fim para interpretar a saída."""
    data = json.dumps(payload, ensure_ascii=False)
    if on_line is None:
        try:
            proc = subprocess.run(["sudo", "-n", HELPER, verb], input=data,
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"{type(e).__name__}", None
        result, detail = None, None
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("step") == "done":
                d = obj.get("detail") or {}
                result, detail = d.get("result"), d
        if result is None:
            err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
            return False, err or f"exit {proc.returncode}", None
        return detail.get("exit") == 0, result, detail
    return _call_stream(verb, data, timeout, on_line)


def _call_stream(verb, data, timeout, on_line):
    """Executa o mesmo comando, encaminhando a saída padrão linha por linha (o assistente emite uma linha por etapa). Combina stderr com stdout,
    para que erros do próprio sudo não bloqueiem o pipe."""
    try:
        proc = subprocess.Popen(["sudo", "-n", HELPER, verb], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    except OSError as e:
        return False, f"{type(e).__name__}", None
    try:
        proc.stdin.write(data)
        proc.stdin.close()
    except OSError:
        pass
    lines = queue.Queue()

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    result, detail, noise = None, None, []
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            try:
                proc.kill()
            except OSError:
                pass
            return False, "TimeoutExpired", None
        try:
            line = lines.get(timeout=min(0.2, left))
        except queue.Empty:
            if proc.poll() is not None:
                break
            continue
        if line is None:
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            noise.append(line)
            continue
        if obj.get("step") == "done":
            d = obj.get("detail") or {}
            result, detail = d.get("result"), d
        elif on_line is not None:
            on_line(obj)
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
    if result is None:
        return False, "\n".join(noise[-5:]) or f"exit {proc.returncode}", None
    return detail.get("exit") == 0, result, detail


def bus_take(by, allow_seated=False, timeout=30):
    """Para o robotd e transfere o barramento dos servos ao Studio (sem desativar o torque). Retorna (ok, result, detail)."""
    return _call("bus-take", {"by": by, "allow_seated": allow_seated}, timeout)


def bus_give_back(by, *, soft=True, marker=None, timeout=60):
    """Devolve o barramento e inicia o robotd. soft=True indica devolução suave (o Studio já desativou todo o torque); marker indica devolução sem desativar o torque (o fork assume a retenção).
    Retorna (ok, result, detail)."""
    payload = {"by": by, "soft": True} if soft else {"by": by, "marker": marker}
    return _call("bus-give-back", payload, timeout)


def bus_abort(by, timeout=10):
    """Cancela a transferência (a interface desligou o torque durante a contagem regressiva): envia KILL ao robotd, remove o marcador e devolve o barramento ao Studio. Retorna (ok, result, detail)."""
    return _call("bus-abort", {"by": by}, timeout)


def pad_pair(by, mac=None, timeout=60):
    """Executa o pareamento oficial robotctl pad pair como root pelo assistente. Retorna (ok, result, detail).
    detail["pair"] contém PadPairResult; detail["stderr"] contém mensagens do robotctl (pausa do btd, avisos etc.)."""
    payload = {"by": by, "timeout": timeout}
    if mac:
        payload["mac"] = mac
    return _call("pad-pair", payload, timeout + 45)


def pad_forget(by, mac, timeout=60):
    """Executa o comando oficial robotctl pad forget como root pelo assistente. Retorna (ok, result, detail)."""
    return _call("pad-forget", {"by": by, "mac": mac}, timeout)


def wifi_hotspot_down(by, ssid=None, timeout=30):
    """Desliga o hotspot do robô (o assistente aguarda no máximo 10 s). Se já estiver desligado, conta como sucesso. O SSID é gravado no arquivo da janela de conexão para consulta do netcheck."""
    payload = {"by": by}
    if ssid:
        payload["ssid"] = ssid
    return _call("wifi-hotspot-down", payload, timeout)


def wifi_hotspot_up(by, timeout=40):
    """Liga o hotspot do robô (o assistente aguarda no máximo 30 s). Se já estiver ligado, conta como sucesso. Retorna (ok, result, detail)."""
    return _call("wifi-hotspot-up", {"by": by}, timeout)


def calib_read(by=None, timeout=10):
    """Lê somente o arquivo de calibração e o modo atual do programa principal (calib-read). Retorna (ok, result, detail)."""
    payload = {"by": by} if by else {}
    return _call("calib-read", payload, timeout)


def imu_recalibrate(by, action, *, confirmed=None, session_id=None, source=None, quat=None, profile=None, timeout=180):
    """Fixed root verb; commands, services and file paths are never accepted."""
    payload = {"by": by, "action": action}
    for name, value in (("confirmed", confirmed), ("session_id", session_id), ("source", source), ("quat", quat), ("profile", profile)):
        if value is not None:
            payload[name] = value
    return _call("imu-recalibrate", payload, timeout)


def imu_redo_state(*, root="/"):
    """Read the persistent root-owned public manifest. No sudo in the 10 Hz view loop."""
    empty = {"active": False, "phase": "idle", "session_id": None, "source": None}
    path = os.path.join(root, IMU_REDO_MANIFEST.lstrip("/"))
    try:
        for target in (os.path.dirname(os.path.dirname(os.path.dirname(path))), os.path.dirname(os.path.dirname(path)),
                       os.path.dirname(path), path):
            st = os.lstat(target)
            if stat.S_ISLNK(st.st_mode) or (root == "/" and (st.st_uid != 0 or st.st_mode & 0o022)):
                raise ValueError("proprietário ou permissões inseguros no arquivo ou diretório da sessão")
        if not stat.S_ISREG(st.st_mode) or st.st_size > 65536:
            raise ValueError("formato inválido do arquivo da sessão")
        with open(path, encoding="utf-8") as stream:
            m = json.load(stream)
        if (m.get("schema") != "microduck-imu-recalibrate/1" or type(m.get("active")) is not bool
                or not re.fullmatch(r"[0-9a-f]{32}", m.get("session_id", ""))
                or m.get("source") not in ("bus", "bno08x", "lsm6dsv16x")):
            raise ValueError("conteúdo inválido do arquivo da sessão")
        if not m["active"]:
            return empty
        return {key: m.get(key) for key in ("active", "phase", "session_id", "source", "reason", "expected_quat", "profile", "original_mode")}
    except FileNotFoundError:
        return empty
    except (OSError, ValueError, TypeError, AttributeError) as err:
        return {**empty, "active": True, "phase": "recovery_required", "reason": f"Não foi possível ler a sessão de calibração inicial da IMU：{err}"}


def robotd_update(by, action, *, confirmed=None, timeout=180):
    """Separate fixed native update stage; no caller paths, binaries or commands."""
    payload = {"by": by, "action": action}
    if confirmed is not None:
        payload["confirmed"] = confirmed
    return _call("robotd-update", payload, timeout)


def native_update_state(*, root="/"):
    """Bounded persistent motion guard. Malformed/unreadable state fails closed."""
    empty = {"active": False, "phase": "idle", "running_verified": False}
    path = os.path.join(root, NATIVE_UPDATE_JOURNAL.lstrip("/"))
    exclusions = any(os.path.lexists(os.path.join(root,p.lstrip('/'))) for p in NATIVE_UPDATE_EXCLUSIONS)
    try:
        parts = NATIVE_UPDATE_JOURNAL.strip("/").split("/")
        for index in range(1, len(parts)+1):
            target = os.path.join(root, *parts[:index])
            st = os.lstat(target)
            if ((index < len(parts) and not stat.S_ISDIR(st.st_mode))
                    or (index == len(parts) and not stat.S_ISREG(st.st_mode))
                    or (root == "/" and (st.st_uid != 0 or st.st_mode & 0o022))):
                raise ValueError("proprietário ou permissões inseguros no registro de atualização")
        if st.st_size > 65536:
            raise ValueError("o registro de atualização excede o tamanho permitido")
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        if (not isinstance(value, dict) or value.get("schema") != "microduck-native-update/1"
                or type(value.get("active")) is not bool
                or type(value.get("restore_pending", False)) is not bool
                or type(value.get("cleanup_pending", False)) is not bool
                or not re.fullmatch(r"[0-9a-f]{32}", value.get("transaction_id", ""))
                or value.get("phase") not in ("prepared","guarding","guarded","replacing","replaced","verified_commissioning",
                    "restoring_normal","verified_motion","factory_handoff_pending","completed","rolled_back",
                    "recovering","old_restored","recovery_required")
                or (value.get("reason") is not None and (not isinstance(value["reason"], str) or len(value["reason"]) > 300))):
            raise ValueError("formato inválido do registro de atualização")
        public = ("active", "phase", "transaction_id", "available", "installed_sha256", "target_sha256", "running_verified", "mode", "reason")
        result = {key:value.get(key) for key in public if key in value}
        result['active'] = result['active'] or value.get('restore_pending') is True or value.get('cleanup_pending') is True or exclusions
        return result
    except FileNotFoundError:
        if exclusions:
            return {**empty,"active":True,"phase":"recovery_required","reason":"O marcador de proteção da atualização do programa principal existe, mas o registro está ausente"}
        return empty
    except (OSError, ValueError, TypeError, AttributeError):
        return {**empty, "active": True, "phase": "recovery_required", "reason": "Não foi possível ler o registro de atualização do programa principal; restaure a atualização primeiro"}


def ssh_status(timeout=10):
    """Verifica se o login SSH por senha está ativo, se ssh está em execução e quantas chaves estão cadastradas no Radxa (ssh-status, somente leitura). Retorna (ok, result, detail)."""
    return _call("ssh-status", {}, timeout)


def ssh_password(by, on, password=None, timeout=40):
    """Ativa (define a senha escolhida pelo usuário no Radxa) ou desativa o login SSH por senha (ssh-password). A senha é enviada somente pela entrada padrão do assistente e não aparece nos logs."""
    payload = {"by": by, "on": bool(on)}
    if on:
        payload["password"] = password
    return _call("ssh-password", payload, timeout)


def last_result():
    """Lê o resultado completo gravado pelo assistente na última execução (usado após reiniciar o Studio ou atingir o timeout). Retorna None se não houver resultado."""
    try:
        with open(LAST_RESULT, encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def calib_commit(by, joints, imu, dry_run=False, timeout=180, on_line=None):
    """Grava os offsets e as orientações dos servos e da IMU no programa principal (calib-commit pelo assistente). Retorna (ok, result, detail).
    dry_run=True retorna somente o TOML que seria gravado (detail["toml"]), sem gravar arquivo nem reiniciar. on_line recebe o progresso de cada etapa."""
    payload = {"by": by, "joints": joints, "imu": imu, "dry_run": bool(dry_run)}
    return _call("calib-commit", payload, timeout, on_line=on_line)


_COMMIT_WHY = {
    "committed": "Gravado no programa principal, que entrou no modo de movimento",
    "preview": "Pré-visualização pronta (nenhum arquivo foi gravado)",
    "bus_held": "A página dos servos ainda está usando o barramento. Selecione “Devolver ao programa principal” nela.",
    "no_calibration": "Arquivo de calibração do programa principal não encontrado no robô",
    "bad_calibration": "Não foi possível ler o arquivo de calibração atual do programa principal",
    "joint_mismatch": "Os 15 servos desta operação não correspondem ao arquivo de calibração do programa principal",
    "invalid": "O conteúdo a gravar não passou na validação",
    "bad_toml": "O arquivo de calibração gravado não corresponde ao ser relido",
    "restart_failed": "Gravação concluída, mas o programa principal não iniciou; o arquivo original foi restaurado",
    "not_motion": "Gravação concluída, mas o programa principal não entrou no modo de movimento em 30 segundos",
    "calib_rejected": "A calibração não passou na validação do programa principal",
    "bus_unavailable": "O programa principal não conseguiu abrir o barramento dos servos",
    "readback_mismatch": "O programa principal entrou no modo de movimento, mas a calibração lida de volta diverge",
    "write_failed": "Ocorreu um erro durante a gravação; o arquivo original foi restaurado",
    "foreign_commissioning": "O modo de calibração do programa principal não foi configurado pela imagem; não será alterado automaticamente",
    "refused": "O programa principal não permite gravar agora (o robô pode estar andando ou em pé)",
    "backup_failed": "Falha ao fazer backup da calibração original",
    "read_failed": "Não foi possível ler o arquivo de calibração atual",
    "bad_verb": "O assistente está desatualizado; reinstale com deploy/install.sh",
    "busy": "O assistente está ocupado (outra operação ainda não terminou)",
    "detach_failed": "Não foi possível iniciar o assistente em uma unidade separada",
    "TimeoutExpired": "O assistente não retornou o resultado final após 180 segundos",
}

_TAKE_WHY = {
    "taken": "O programa principal parou; o barramento está sob seu controle",
    "refused": "O programa principal não parou (há uma política em execução, está retornando à postura em pé ou a postura sentada não foi autorizada)",
    "no_guard": "A proteção (drop-in) do robotd não está instalada; o programa principal não será parado",
    "busy": "O assistente está ocupado (há um script na placa ou outra operação do barramento em andamento)",
    "stop_failed": "Não foi possível parar o programa principal (nem KILL conseguiu)",
    "port_busy": "A porta serial ainda está em uso",
}

_GIVE_WHY = {
    "soft": "O programa principal iniciou",
    "soft_failed": "Não foi possível iniciar o programa principal",
    "adopted": "O programa principal assumiu a retenção (sem desativar o torque)",
    "limp": "O programa principal não reconheceu o marcador de transferência e desativou todo o torque como antes",
    "retake": "O programa principal não iniciou; o barramento foi retomado (o Studio continua mantendo o estado)",
    "retake_failed": "Não foi possível retomar o barramento",
    "aborted": "A devolução foi cancelada (o torque foi desativado)",
    "refused": "A porta serial ainda está em uso",
    "no_session": "Não há sessão de controle dos servos (marcador ausente)",
    "detach_failed": "Não foi possível iniciar a devolução (systemd-run falhou)",
}

_PAD_WHY = {
    "paired": "Pareado",
    "pair_failed": "Falha ao parear (robotctl retornou erro)",
    "no_robotctl": "O robotctl oficial não está instalado no robô (/usr/local/bin/robotctl)",
    "timeout": "O robotctl excedeu o tempo limite e foi interrompido",
    "bad_output": "Resposta do robotctl inválida",
    "forgotten": "Removido",
    "forget_failed": "Não foi possível remover",
    "busy": "O assistente está ocupado (outro pareamento ou remoção ainda não terminou)",
}

_WIFI_WHY = {
    "hotspot_down": "Hotspot desligado",
    "already_down": "O hotspot já estava desligado",
    "down_failed": "Não foi possível desligar o hotspot",
    "hotspot_up": "Hotspot ligado novamente",
    "already_up": "O hotspot já estava ligado",
    "up_failed": "Não foi possível ligar o hotspot",
    "timeout": "Tempo limite excedido",
    "nmcli_failed": "Não foi possível consultar a conexão de rede atual (erro do nmcli)",
    "busy": "O assistente está ocupado (outra operação de Wi-Fi ainda não terminou)",
    "bad_verb": "O assistente está desatualizado; reinstale com deploy/install.sh",
}

_COMMON = {
    "bad_args": "Parâmetros inválidos",
    "bad_marker": "Marcador de transferência inválido",
    "bad_verb": "Verbo desconhecido",
    "not_root": "Sem permissão (é necessário root)",
    "error": "O próprio assistente encontrou um erro",
}


def friendly(result, detail, verb):
    """Converte result em uma mensagem legível (os valores possíveis estão em deploy/INSTALL.md §1). Inclui também a mensagem original do assistente em detail."""
    if verb == "imu-recalibrate":
        if result in ("bad_verb", "denied", "not_root") or "sudo" in str(result).lower():
            return "Para refazer a calibração inicial da IMU, é necessária a nova versão do assistente root (0.7.0 ou posterior) e do sudoers. Atualize com deploy/install.sh"
        return ((detail or {}).get("reason") or (detail or {}).get("msg") or
                f"A mudança para a calibração inicial da IMU não foi concluída: {result}. Você pode continuar ou cancelar a sessão.")
    if verb in ("pad-pair", "pad-forget"):
        table = _PAD_WHY
    elif verb in ("wifi-hotspot-down", "wifi-hotspot-up"):
        table = _WIFI_WHY
    elif verb == "calib-commit":
        table = _COMMIT_WHY
    else:
        table = _TAKE_WHY if verb == "bus-take" else _GIVE_WHY
    msg = detail.get("msg") if isinstance(detail, dict) else None
    if verb in ("ssh-status", "ssh-password"):
        # A mensagem original do assistente já é uma frase completa (“a verificação da configuração do sshd falhou e foi revertida: …”).
        if msg and result not in ("ssh_status", "ssh_password_on", "ssh_password_off"):
            return msg
        if result == "bad_verb":
            return "O assistente está desatualizado e não oferece suporte a SSH. Reinstale com deploy/install.sh (recurso disponível a partir da versão 0.6.0)."
        return _COMMON.get(result) or (result or "Falhou")
    # No calib-commit, a mensagem original do assistente já é uma frase completa (por exemplo, termina com “o arquivo original foi restaurado”); use-a diretamente;
    # Para os demais verbos, mantenha o formato “resultado: mensagem original” (convenção de friendly em test_helper).
    if msg and verb == "calib-commit" and result not in ("committed", "preview"):
        return msg
    # Após a devolução, o programa principal responde, mas permanece na etapa de inicialização (modo de calibração de forks antigos): não diga que “não iniciou”; a mensagem do assistente já é completa.
    if msg and verb == "bus-give-back" and isinstance(detail, dict) and detail.get("still_starting"):
        return msg
    text = table.get(result) or _COMMON.get(result) or (result or "Falhou")
    if result == "pair_failed" and isinstance(detail, dict) and detail.get("reason"):
        text = f"{text}（{detail['reason']}）"
    if msg and msg not in text:
        text = f"{text}：{msg}"
    return text
