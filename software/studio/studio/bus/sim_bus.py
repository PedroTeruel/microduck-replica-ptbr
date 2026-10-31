# -*- coding: utf-8 -*-
"""(Adaptado de tools/servo-web/sim_bus.py no mesmo repositório. O Studio o usa para executar a página dos servos no computador sem conectar servos; os testes também o utilizam.)

Simulador HD-1910 em nível de protocolo: emula uma porta serial, recebe pacotes de comando Feetech e responde de acordo com a tabela de registradores.

Diferente do FakeBus em server.py, que simula a interface de alto nível e não exercita feetech.py;
este simulador permite que o FeetechBus real envie e receba bytes; formato dos pacotes, checksum, leitura e escrita síncronas, travas, torque e pré-condições da calibração central seguem o comportamento do hardware real.

  bus = feetech.FeetechBus(None, ser=SimSerial([20, 21, ...]))

Comportamentos do hardware real simulados (com referências):
- Ao gravar 128 no interruptor de torque: o HD-1910 (firmware 3.46) retorna “sucesso”, mas não faz nada（2026-09-20 testado em quatro rodadas; o mesmo ocorre desbloqueado e com o torque desligado;
  o manual de protocolo também informa que HLS ≥3.43 não oferece suporte）。accept_128=True segue a regra STS: só calibra quando o sinalizador de trava = 0 e o interruptor de torque = 0
- 0x0B calibração de posição: altera a leitura da posição atual para o valor do parâmetro (padrão sem parâmetro = 2048).support_0b=False simula um servo que não reconhece esse comando
- Registrador de offset 31: offset_adds seleciona “posição = valor bruto + offset” ou “valor bruto − offset”; o manual não especifica, então ambos os casos são simulados
- Queda por gravidade: ao desligar o torque, as articulações montadas no robô cedem para baixo(no hardware real, o pescoço cedeu 80 passos em 130 ms ≈ 0,62 passo/ms)。
  droop define quantos passos cede por milissegundo —— sem essa simulação, não é possível detectar erros como “esperar demais com o torque desligado e calibrar a posição caída como zero”
- Atraso do barramento: no hardware real, cada ida e volta (envio do pacote + espera da resposta + temporizador de latência USB) leva cerca de 1–2 ms. latency_ms simula esse atraso,
  e também avança um relógio virtual: a queda é calculada por esse relógio, tornando os testes determinísticos e independentes da velocidade do computador; time.sleep também é contabilizado
- A tabela de registradores termina em 86; leituras além dela retornam somente os bytes restantes (no hardware real, ler 10 bytes a partir do endereço 80 retorna 7)
- O 15º bit de posição, velocidade e corrente indica o sinal; o registrador de offset 31 também usa esse bit (uma leitura real retornou 34279 = -1511)
- REBOOT (0x08) não responde
- P / D / I dois conjuntos: EEPROM 21–23 com padrão de fábrica 32 / 40 / 0; em operação usa RAM 50–52 (copiados da EEPROM na inicialização e reinicialização),
  limite de torque 48 na inicialização = torque máximo 16 (dados reais: eeprom_pdi / temporary_pdi em registers_before_arm no diagnóstico do programa principal)
"""
import struct
import time

from . import feetech

TABLE_END = 87


def enc15(v):
    return (0x8000 | (-v & 0x7FFF)) if v < 0 else (v & 0x7FFF)


class SimServo:
    def __init__(self, sid, phys=2048):
        self.r = bytearray(TABLE_END)
        r = self.r
        r[0], r[1], r[2], r[3], r[4] = 3, 46, 0, 3, 10      # firmware 3.46, END=0 little-endian
        r[5], r[6], r[8] = sid, 0, 1                        # ID, baud rate 1M, nível de resposta 1
        struct.pack_into("<HH", r, 9, 0, 4095)
        r[13], r[15] = 70, 40
        struct.pack_into("<H", r, 16, 1000)
        r[18], r[21], r[22], r[33] = 52, 32, 40, 4          # fase 52, padrões de fábrica P32 / D40 / I0 (EEPROM 21–23), modo 4
        r[50:53] = r[21:24]                                 # P / D / I em operação (RAM 50–52): copiados da EEPROM ao ligar
        struct.pack_into("<H", r, 48, 1000)
        r[55] = 1                                           # travado de fábrica
        r[62], r[63] = 74, 30
        self.phys = phys          # leitura física do encoder (sem offset)
        self.off = 0              # offset: posição reportada = phys + off
        self.goal = None
        self.calibrations = 0     # número de calibrações centrais realmente executadas (para testes)
        self.muted = set()        # não responde à leitura desses endereços; simula uma desconexão durante a operação
        self.accept_128 = False   # HD-1910 não reconhece 128
        self.support_0b = True
        self.ignore_offset_writes = False   # simula um servo que também não aceita gravações de offset
        self.offset_adds = True   # posição reportada = phys + off; com False, = phys − off (o manual não especifica; ambos os casos devem funcionar)
        self.droop = 0.0          # passos cedidos por milissegundo com o torque desligado; medição real no pescoço: 0,62
        self._t = 0.0             # relógio virtual do barramento no último tick (ms)
        self.mute_after_calib = set()   # adiciona esses endereços a muted assim que a calibração termina
        self.readonly = set()     # gravações nesses endereços retornam “sucesso”, mas não surtem efeito; simula falha de gravação (para verificar que não se ativa o torque se a leitura de retorno divergir)

    @property
    def id(self):
        return self.r[5]

    def pos(self):
        return self.phys + (self.off if self.offset_adds else -self.off)

    def tick(self, clock_ms=0.0):
        """Com o torque ligado, vai diretamente até o destino (o simulador não modela a dinâmica); desligado, cede conforme droop.

        clock_ms é o relógio virtual do barramento, avançado pelo SimSerial com o atraso de cada pacote e o tempo real de sleep."""
        dt_ms, self._t = clock_ms - self._t, clock_ms
        if self.r[40] == 1 and self.goal is not None:
            self.phys = self.goal - (self.off if self.offset_adds else -self.off)
        elif self.droop:
            self.phys -= self.droop * dt_ms
        p = round(self.pos())
        struct.pack_into("<H", self.r, 56, enc15(p))
        struct.pack_into("<H", self.r, 67, enc15(self.goal if self.goal is not None else p))
        struct.pack_into("<H", self.r, 31, enc15(self.off))

    def write(self, addr, data):
        for k, b in enumerate(data):
            a = addr + k
            if a >= TABLE_END:
                break
            if a == 40 and b == 128:
                if self.accept_128 and self.r[40] == 0 and self.r[55] == 0:
                    self.recalibrate(2048)
                continue                                     # retorna sucesso, mas não faz nada
            if a in self.readonly:
                continue
            self.r[a] = b
        # Aplica os registradores de vários bytes
        if addr <= 42 < addr + len(data):
            self.goal = feetech.sign15(struct.unpack_from("<H", self.r, 42)[0])
        if addr <= 31 < addr + len(data) and not self.ignore_offset_writes:
            self.off = feetech.sign15(struct.unpack_from("<H", self.r, 31)[0])
        if addr <= 40 < addr + len(data) and self.r[40] == 1 and self.goal is None:
            self.goal = self.pos()

    def recalibrate(self, value):
        # phys Como a queda pode ser fracionária, o offset é arredondado: os registradores do servo real armazenam somente inteiros
        self.off = round((value - self.phys) if self.offset_adds else (self.phys - value))
        self.calibrations += 1
        self.muted |= self.mute_after_calib

    def read(self, addr, n, clock_ms=0.0):
        self.tick(clock_ms)
        return bytes(self.r[addr:min(addr + n, TABLE_END)])


class SimSerial:
    """Serial simulada: write() recebe comandos e gera respostas dos servos no barramento; read() fornece as respostas."""

    def __init__(self, ids, phys=None):
        self.timeout = 0.02
        self.servos = {i: SimServo(i, (phys or {}).get(i, 2048)) for i in ids}
        self.rx = bytearray()
        self.latency_ms = 0.0     # milissegundos por ida e volta; cerca de 1–2 no URT-2 real
        self.clock = 0.0          # relógio virtual do barramento (ms): latency por pacote mais o tempo real de sleep do chamador
        self._wall = time.monotonic()

    # ---- Interface serial ----
    def reset_input_buffer(self):
        self.rx.clear()

    def read(self, n=1):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        return out

    def close(self):
        pass

    def write(self, data):
        data = bytes(data)
        while len(data) >= 6:
            if data[0] != 0xFF or data[1] != 0xFF:
                data = data[1:]
                continue
            sid, length = data[2], data[3]
            pkt = data[:4 + length]
            data = data[4 + length:]
            instr, params = pkt[4], pkt[5:-1]
            if ((~sum(pkt[2:-1])) & 0xFF) != pkt[-1]:
                continue                                         # checksum inválido: o servo real ignora o pacote
            self._handle(sid, instr, params)
        return len(data)

    # ---- Servos ----
    def _by_id(self, sid):
        for s in self.servos.values():
            if s.id == sid:
                return s
        return None

    def _advance(self):
        """Avança o relógio virtual: atraso de uma ida e volta no barramento mais o tempo real decorrido desde a última chamada (time.sleep do código também afeta a queda)."""
        now = time.monotonic()
        self.clock += self.latency_ms + (now - self._wall) * 1000
        self._wall = now
        return self.clock

    def _reply(self, s, params=b""):
        s.tick(self.clock)
        err = s.r[65]
        length = len(params) + 2
        body = bytes([s.id, length, err]) + bytes(params)
        self.rx += bytes([0xFF, 0xFF]) + body + bytes([(~sum(body)) & 0xFF])

    def _handle(self, sid, instr, p):
        self._advance()
        if instr == feetech.SYNC_WRITE:
            addr, ln = p[0], p[1]
            rest = p[2:]
            for k in range(0, len(rest), ln + 1):
                s = self._by_id(rest[k])
                if s:
                    s.write(addr, rest[k + 1:k + 1 + ln])
            return
        if instr == feetech.SYNC_READ:
            addr, ln = p[0], p[1]
            for i in p[2:]:
                s = self._by_id(i)
                # alive() é usado pela placa IMU simulada: simula “controlador do barramento ainda não iniciou” e “a placa não responde”
                if s and addr not in getattr(s, "muted", ()) and getattr(s, "alive", lambda _: True)(self.clock):
                    self._reply(s, s.read(addr, ln, self.clock))
            return
        s = self._by_id(sid)
        if s is None:
            return
        if instr == feetech.PING:
            if sid == feetech.BROADCAST or not getattr(s, "alive", lambda _: True)(self.clock):
                return                                       # Manual: não use PING broadcast quando há vários dispositivos no barramento
            self._reply(s)
        elif instr == feetech.READ:
            if p[0] in s.muted or not getattr(s, "alive", lambda _: True)(self.clock):
                return
            self._reply(s, s.read(p[0], p[1], self.clock))
        elif instr == feetech.WRITE:
            s.write(p[0], p[1:])
            self._reply(s)                                       # responde com o novo ID ao alterar o ID
        elif instr == feetech.CALIBRATE:
            if s.support_0b:
                s.recalibrate(2048 if len(p) < 2 else feetech.sign15(p[0] | p[1] << 8))
            self._reply(s)
        elif instr == feetech.REBOOT:
            s.r[40] = 0                                          # sem resposta; ao voltar, o torque está desligado
            s.r[50:53] = s.r[21:24]                              # P/D/I da RAM e limite de torque voltam aos valores da inicialização (no hardware real, a RAM do servo retorna aos padrões de fábrica após reiniciar)
            s.r[48:50] = s.r[16:18]
