"""Acompanha as quatro etapas de inicialização do robotd (plano de ajuste v2 §2.3, §5 T1; scratchpad console/tuning-plan.md).

O robotd divide sua inicialização em quatro etapas e as envia por robot.startupSubscribe (fork robotd main.rs:4671-4686, 1445-1456):
    primeira resposta = estado atual das quatro etapas: {"steps": {"1": {"status", "detail"}, ...}, "build": ...}
    mudanças posteriores chegam como notificações {"method": "robot.startup", "params": o mesmo formato}; termina quando o cliente envia uma linha ou desconecta.
status pode ser starting / waiting / success / failed. As descrições originais das quatro etapas estão em main.rs:1205, 1482, 1773-1808, 2184-2232 e 4137.

Este módulo tem três funções:
- StartupTrack acompanha os resultados (startup_loop em robotd.py grava; tune.py e state.py leem). Cada hello invalida os dados anteriores, pois robotd pode ter reiniciado.
  Registra quando o Studio viu cada estado pela primeira vez (time.monotonic(): segundos desde a inicialização do robô).
- startup_loop abre uma conexão de assinatura quando robotd está presente e ainda há etapas pendentes; encerra quando todas concluem ou uma falha.
  Versões antigas do robotd não oferecem esse método: registra “não compatível” e não tenta novamente durante o mesmo hello.
- startup_todo ajusta as tarefas pendentes da página inicial (chamado por state.py): durante a inicialização, mostra “Etapa N/4: descrição”; destaca em vermelho a política de caminhada não carregada apesar da etapa 3 concluída.

Este módulo não importa state.py (state.py precisa importá-lo).
"""
import asyncio
import sys
import time

from .rpc import RpcError, Unreachable, encode, open_conn, read_message

STEPS = ("1", "2", "3", "4")
STEP_NAMES = {"1": "Configuração e thread de controle", "2": "Barramento dos servos e IMU", "3": "Carregamento do modelo", "4": "Primeiro ciclo de controle"}
READ_TIMEOUT_S = 2.0          # Intervalo sem mensagens antes de verificar se robotd reiniciou ou se o Studio deve pausar.
RETRY_S = (1.0, 2.0, 5.0)
POLICY_OFF = "Estratégia desativada conforme configuração"   # fork main.rs:2229: etapa 3 concluída, mas a política de caminhada não foi carregada (revisão T-R1)


class StartupTrack:
    def __init__(self):
        self.epoch = None          # Identifica a sessão hello (rd.hello.at).
        self.steps = {}            # "1".."4" -> {"status", "detail", "at"}; at = primeira vez que o Studio observou o estado (monotonic).
        self.build = None
        self.done = False          # As quatro etapas tiveram sucesso ou uma falhou; não assina novamente neste hello.
        self.unsupported = None    # Motivo pelo qual um robotd antigo não oferece startupSubscribe.
        self.error = None          # Erro da assinatura mais recente (haverá novas tentativas).
        self.at = None             # Atualização mais recente (monotonic).

    def reset(self, epoch):
        self.__init__()
        self.epoch = epoch

    def update(self, report, now=None):
        """Processa um relatório das quatro etapas (resposta ou notificação); ignora valores que não sejam dict."""
        if not isinstance(report, dict):
            return
        now = time.monotonic() if now is None else now
        steps = report.get("steps") if isinstance(report.get("steps"), dict) else {}
        for k in STEPS:
            row = steps.get(k)
            if not isinstance(row, dict):
                continue
            status, detail = row.get("status"), row.get("detail")
            old = self.steps.get(k)
            if old and old["status"] == status and old["detail"] == detail:
                continue
            at = old["at"] if old and old["status"] == status else now
            self.steps[k] = {"status": status if isinstance(status, str) else None,
                             "detail": detail if isinstance(detail, str) else None, "at": at}
        if isinstance(report.get("build"), str):
            self.build = report["build"]
        self.at = now
        self.error = None
        self.done = (all((self.steps.get(k) or {}).get("status") == "success" for k in STEPS)
                     or any((self.steps.get(k) or {}).get("status") == "failed" for k in STEPS))

    def current(self):
        """Retorna (número da etapa, dados): a primeira que não teve sucesso; retorna (None, None) se todas concluíram."""
        for k in STEPS:
            row = self.steps.get(k)
            if not row or row.get("status") != "success":
                return k, row
        return None, None

    def policy_off(self):
        """Etapa 3 concluída; a descrição literal é “Estratégia desativada conforme configuração”."""
        row = self.steps.get("3") or {}
        return row.get("status") == "success" and POLICY_OFF in (row.get("detail") or "")

    def view(self, now=None):
        """As quatro linhas enviadas à interface. No robô, at_s representa segundos desde a inicialização (monotonic no Linux); no computador, não tem esse significado, indicado por boot_clock."""
        rows = []
        for k in STEPS:
            row = self.steps.get(k)
            rows.append({"n": int(k), "name": STEP_NAMES[k], "status": (row or {}).get("status"),
                         "detail": (row or {}).get("detail"),
                         "at_s": round(row["at"], 1) if row and row.get("at") is not None else None})
        n, row = self.current()
        return {"rows": rows, "known": bool(self.steps), "done": self.done, "now": int(n) if n else None,
                "unsupported": self.unsupported, "error": self.error, "build": self.build,
                "boot_clock": sys.platform.startswith("linux")}


async def startup_loop(rd):
    """Tarefa em segundo plano iniciada por robotd.py (protegida por _supervise, como a consulta periódica). Somente leitura: envia apenas robot.startupSubscribe."""
    track = rd.startup
    fails = 0
    while True:
        if rd.addr == "none":
            return
        epoch = rd.hello.at
        if rd.paused or rd.present is not True or epoch is None:
            await asyncio.sleep(1.0)
            continue
        if track.epoch != epoch:
            track.reset(epoch)            # robotd enviou hello novamente (provavelmente reiniciou); invalida as quatro etapas anteriores.
        if track.done or track.unsupported:
            await asyncio.sleep(1.0)
            continue
        try:
            await _follow(rd, track, epoch)
            fails = 0
        except (Unreachable, OSError, asyncio.TimeoutError) as e:
            fails += 1
            track.error = f"Falha ao assinar as etapas de inicialização: {e}"
            await asyncio.sleep(RETRY_S[min(fails - 1, len(RETRY_S) - 1)])


async def _follow(rd, track, epoch):
    r, w = await asyncio.wait_for(open_conn(rd.addr), 3.0)
    try:
        try:
            w.write(encode(1, "robot.startupSubscribe", {}))
            await w.drain()
        except (ConnectionError, OSError) as e:
            raise Unreachable(f"Não foi possível enviar a solicitação: {type(e).__name__}: {e}") from e
        while True:
            if rd.hello.at != epoch or rd.paused:
                return                    # robotd reiniciou ou o Studio está ajustando os servos; o loop externo retomará.
            try:
                msg = await read_message(r, READ_TIMEOUT_S)
            except asyncio.TimeoutError:
                continue
            if msg is None:
                continue
            if msg.get("id") == 1:
                if "error" in msg:
                    err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                    e = RpcError("robot.startupSubscribe", err.get("code"), err.get("message", ""))
                    track.unsupported = f"Esta versão do programa principal não informa as etapas de inicialização ({e})"
                    rd.log.info("O programa principal não informa as etapas de inicialização (versão antiga sem robot.startupSubscribe)", cat="robotd", raw=str(e))
                    return
                track.update(msg.get("result"))
            elif msg.get("method") == "robot.startup":
                track.update(msg.get("params"))
            else:
                continue
            _log_change(rd, track)
            if track.done:
                return
    finally:
        try:
            w.close()
        except Exception:  # noqa: BLE001 — erros ao fechar a conexão não são relevantes.
            pass


def _log_change(rd, track):
    """Registra apenas etapas travadas ou com falha (as etapas bem-sucedidas já estão no journal do robotd). O módulo de log elimina duplicatas."""
    n, row = track.current()
    if row and row.get("status") == "failed":
        rd.log.error(f"Falha na etapa {n}/4 da inicialização do programa principal", cat="robotd", step=STEP_NAMES[n], raw=row.get("detail"),
                     hint="Consulte as linhas do robotd na página de logs e exporte um pacote de diagnóstico.")
    elif not n and track.policy_off():
        rd.log.warn("O programa principal iniciou, mas a política de caminhada não foi carregada (etapa 3: estratégia desativada conforme configuração)", cat="robotd", step="Carregamento do modelo",
                    hint="Provavelmente há um erro na configuração de execução ou no contrato do modelo de caminhada; o robô consegue ficar em pé, mas não caminhar.")


def _hello_at(rd):
    return getattr(getattr(rd, "hello", None), "at", None)


def walk_unloaded(rd, pol=None, bus=None):
    """Explica em linguagem simples por que o modelo de caminhada não foi carregado; retorna None se não houver problema (revisão T-R1: etapa 3 pode indicar sucesso com a política desligada, mesmo que a verificação de saúde esteja normal).
    Verifica somente no modo de movimento e durante o controle; pol contém robot.policies atualizado, filtrado por MAX_AGE em state.py."""
    if getattr(rd, "paused", None) or getattr(rd, "present", None) is False:
        return None                       # Ajuste dos servos ou programa principal ausente: o estado disponível está desatualizado.
    bus = bus if isinstance(bus, dict) else (rd.bus.value if isinstance(rd.bus.value, dict) else None)
    if not bus or bus.get("mode") != "motion" or bus.get("phase") != "control":
        return None
    if isinstance(pol, dict) and pol.get("enabled") is False:
        return None                       # A política foi desativada na configuração (por exemplo, em uma bancada); isso não é uma falha.
    walk_err = None
    if isinstance(pol, dict):
        for s in pol.get("slots") or []:
            if isinstance(s, dict) and s.get("slot") == "walk" and s.get("error"):
                walk_err = str(s["error"])
    lm = bus.get("loaded_models")
    track = getattr(rd, "startup", None)
    off = bool(track is not None and track.epoch == _hello_at(rd) and track.policy_off())
    missing = "loaded_models" in bus and (not isinstance(lm, dict) or not isinstance(lm.get("walk"), dict))
    if walk_err:
        return f"Falha ao carregar o slot de caminhada: {walk_err}"
    if missing or off:
        return "O programa principal informou que a estratégia está desativada conforme configuração; o modelo de caminhada não foi carregado" if off else "O programa principal não carregou o modelo de caminhada (loaded_models não contém walk)"
    return None


def startup_todo(rd, items, pol=None, bus=None):
    """Executa novamente após state.py calcular todo() (plano de ajuste §3.2):
    - substitui a dica “programa principal do robô ainda está iniciando” pela etapa atual e sua descrição (mantém o texto original de busStatus.error ao final);
    - acrescenta uma tarefa em vermelho quando o modelo de caminhada não foi carregado."""
    try:
        track = getattr(rd, "startup", None)
        if track is not None and track.epoch is not None and track.epoch == _hello_at(rd):
            n, row = track.current()
            for it in items:
                if it.get("key") == "starting" and n and row and row.get("detail"):
                    raw = (bus or {}).get("error") if isinstance(bus, dict) else None
                    hint = f"Etapa {n}/4 ({STEP_NAMES[n]}): {row['detail']}"
                    if raw and raw not in row["detail"]:
                        hint += f"  Texto original: {raw}"
                    it["hint"] = hint
        why = walk_unloaded(rd, pol, bus)
        if why and not any(it.get("key") == "walk_unloaded" for it in items):
            items.insert(0, {"key": "walk_unloaded", "level": "error", "msg": "Modelo de caminhada não carregado",
                             "hint": f"{why}; o robô consegue ficar em pé, mas não caminhar. Consulte “Execução e ajuste de parâmetros” abaixo da página inicial."})
    except Exception:  # noqa: BLE001 — uma falha ao acrescentar a dica não deve interromper o envio do estado.
        pass
    return items
