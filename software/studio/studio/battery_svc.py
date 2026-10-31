"""Integra a estimativa da bateria ao Studio (battery-plan.md v2 §6 B2/B3): um ciclo de 1 Hz alimenta o estimador; summarize apenas lê o resultado, usado por battery.op na página.

Por que usar um ciclo separado (revisão B-R7): summarize é executado 10 vezes por segundo em cada página. Alimentar o estimador ali geraria 30 amostras repetidas por segundo com três páginas abertas.
Aqui há uma atualização por segundo, deduplicada pelo horário da amostra de busStatus (Sample.at). Ao controlar as servos (o Studio ocupa o barramento e o robotd fica parado por projeto),
as tensões vêm de cada servo em servo.snapshot(); o mesmo registrador é usado e a estimativa não reinicia ao alternar entre fontes.

As configurações ficam em state_dir/battery-settings.json (leitura, gravação e validação em studio/battery.py); alterações substituem imediatamente as configurações do estimador e valem no próximo ciclo.
Apenas avisos: este módulo não envia comandos ao robô.
"""
import asyncio
import os
import time

from . import battery as B
from .state import JOINT_CN, MAX_AGE

TICK_S = 1.0
BUS_STALE_S = 3.0       # Sem atualização de busStatus por esse período, o ciclo não recebe dados novos (após 10 s, o estimador reinicia sozinho).
# Para desenvolvimento (testes de ponta a ponta e capturas de tela): acelera o relógio do estimador por esse fator (30 s para estimar e 60 s para avisar viram 1,5 s e 3 s com fator 20).
# Durante a aceleração, cada ciclo usa a leitura mais recente como nova amostra (sem deduplicar pelo horário de busStatus). Não configure no robô.
SPEED_ENV = "STUDIO_BATTERY_SPEED"


class BatteryService:
    def __init__(self, robotd, log, state_dir=None, servo=None, onboard=None, speed=None):
        self.rd, self.log, self.state_dir, self.servo, self.onboard = robotd, log, state_dir, servo, onboard
        self.settings = B.load_settings(state_dir, log)
        self.est = B.Estimator(self.settings)
        self.names = None
        self.errors = 0
        if speed is None:
            try:
                speed = float(os.environ.get(SPEED_ENV) or 1.0)
            except ValueError:
                speed = 1.0
        self.speed = max(1.0, speed)
        self._t0 = time.monotonic()
        if self.speed != 1.0:
            log.warn(f"Desenvolvimento: estimativa da bateria acelerada em {self.speed:g}x", cat=B.LOG_CAT, raw=f"{SPEED_ENV}={self.speed:g}",
                     hint="Use apenas em testes de ponta a ponta e capturas de tela; não configure esta variável no robô")

    def clock(self, now=None):
        """Horário usado pelo estimador (ampliado pelo fator de aceleração)."""
        now = time.monotonic() if now is None else now
        return self._t0 + (now - self._t0) * self.speed

    # ---- Um ciclo ----

    def sample(self, now):
        """Entrada deste ciclo: (tensão, atual, classe, chave, origem, nomes) ou None (sem dados novos)."""
        sv = self.servo
        if sv is not None and getattr(sv, "state", None) == "open":
            snap = sv.snapshot()
            rows = snap.get("rows") if isinstance(snap, dict) else None
            vs, fr = B.servo_session_volts(rows)
            if vs is None:
                return None
            names = [r.get("cn") if isinstance(r, dict) else None for r in rows]
            # A tabela das servos não tem horário de amostragem: deduplica por segundo (o estimador também deduplica pelo horário se não receber uma chave).
            return vs, fr, B.classify_servo_session(rows), ("servo", int(now)), "servo", names
        bus = self.rd.bus.value
        age = self.rd.bus.age(now)
        if bus is None or age is None or age > BUS_STALE_S:
            return None
        vs, fr = B.robotd_volts(bus)
        if vs is None:
            return None
        st_age = self.rd.state.age(now)
        st = self.rd.state.value if st_age is not None and st_age <= MAX_AGE["state"] else None
        joints = ((bus.get("native") or {}).get("joints") or []) if isinstance(bus.get("native"), dict) else []
        names = [JOINT_CN.get(j.get("name"), j.get("name")) if isinstance(j, dict) else None for j in joints]
        cls = B.classify_robotd(bus, st) if st is not None else None
        if cls is None and st is None and isinstance(bus.get("native"), dict):
            # Sem atualizações do fluxo de estado (o robotd não envia robot.state quando ninguém está vendo a página): usa apenas busStatus. Torque desligado significa repouso;
            # torque ligado e estratégia desligada significa postura HOME (sem caminhar); com a estratégia ligada, pode estar em movimento, então o estado é desconhecido.
            torque = bus["native"].get("torque_state_confirmed")
            if torque is False:
                cls = "rest"
            elif torque is True and bus.get("policy_enabled") is False:
                cls = "light"
        return vs, fr, cls, ("bus", self.rd.bus.at), "robotd", names

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        s = self.sample(now)
        t = self.clock(now)
        if s is None:
            events = self.est.feed(t, None)
        else:
            vs, fr, cls, key, source, names = s
            self.names = names
            events = self.est.feed(t, vs, fr, cls, key=key if self.speed == 1.0 else None, source=source)
        B.log_events(self.log, events)
        return events

    def view(self, now=None):
        """Usado por summarize (10 vezes por segundo em cada página): apenas lê a memória, sem contar uma nova amostra."""
        now = time.monotonic() if now is None else now
        h = self.rd.health
        health = h.value if h.age(now) is not None and h.age(now) <= MAX_AGE["health"] else None
        rd = (health or {}).get("battery") if isinstance(health, dict) else None
        shutdown = getattr(self.onboard, "battery_shutdown", None) if self.onboard is not None else None
        return self.est.view(self.clock(now), rd=rd, names=self.names, shutdown=shutdown)

    async def loop(self):
        while True:
            await asyncio.sleep(TICK_S / self.speed)
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.errors += 1
                self.log.error("Erro ao estimar a bateria", cat=B.LOG_CAT, raw=f"{type(e).__name__}: {e}", exc=True,
                               hint="Problema no Studio. Exporte e compartilhe o pacote de diagnóstico; isso não impede o robô de ficar em pé ou andar")
                await asyncio.sleep(5.0)

    # ---- battery.op da página ----

    async def handle(self, args, by="?"):
        """{op:"get"} → configurações e explicações; {op:"set", values:{…}} → valida, salva e aplica imediatamente;
        {op:"calibrate", measured_v} → calcula a calibração da leitura (não salva; a página pede confirmação antes de chamar set). Valores inválidos geram ValueError com uma mensagem para o usuário."""
        op = (args or {}).get("op")
        if op == "get":
            return self._payload()
        if op == "set":
            values = (args or {}).get("values")
            good, errors = B.validate_settings(values, self.settings)
            if errors:
                raise ValueError("；".join(errors))
            old = dict(self.settings)
            if good == old:
                return self._payload()
            try:
                saved = await asyncio.to_thread(B.save_settings, self.state_dir, good)
            except B.SettingsError as e:
                self.log.warn("Não foi possível salvar as configurações da bateria", cat=B.LOG_CAT, raw=str(e), hint="O diretório de estado pode estar cheio ou sem permissão de gravação")
                raise ValueError(str(e)) from None
            self.settings = saved
            self.est.set_settings(saved)
            self.log.info(f"Configurações da bateria alteradas: {B.settings_changes(old, saved)}", cat=B.LOG_CAT, raw=f"by={by}")
            return self._payload()
        if op == "calibrate":
            mv = (args or {}).get("measured_v")
            r = self.est.calibrate(self.clock(), mv)
            if r["ok"]:
                self.log.info(f"“Medi a tensão da bateria”: {r['reason']} (ainda não foi salvo; aguardando confirmação)", cat=B.LOG_CAT, raw=f"by={by}")
            return dict(r, current=self.settings["cal_offset_v"])
        raise ValueError(f"Operação de bateria desconhecida: {op}")

    def _payload(self):
        return {"settings": dict(self.settings), "defaults": dict(B.DEFAULTS), "ranges": {k: list(v) for k, v in B.RANGES.items()},
                "presets": dict(B.PRESETS), "path": B.settings_path(self.state_dir)}
