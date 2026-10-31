# -*- coding: utf-8 -*-
"""Simulador de protocolo HD-1910: emula uma porta serial, recebe pacotes de comando Feetech e responde conforme a tabela de registradores.

Ao contrário do FakeBus em server.py, que simula a interface de alto nível e não exercita feetech.py,
este simulador permite que o FeetechBus real troque bytes com ele. Formato dos pacotes, checksum, leitura e gravação síncronas, trava, torque e pré-condições da calibração do ponto central seguem o comportamento real.

  bus = feetech.FeetechBus(None, ser=SimSerial([20, 21, ...]))

Comportamentos reais simulados (com referências):
- Gravação de 128 no interruptor de torque: o HD-1910 (firmware 3.46) retorna “sucesso”, mas não faz nada (quatro testes em 2026-09-20, inclusive destravado e com torque desligado; HLS ≥3.43 também não é compatível segundo o manual). Com accept_128=True, aplica a regra STS: calibra somente com o indicador de trava = 0 e o interruptor de torque = 0.
- Calibração de posição 0x0B: altera a leitura da posição atual para o parâmetro (padrão 2048). support_0b=False simula um servo que não reconhece esse comando.
- Registrador de deslocamento 31: offset_adds escolhe entre posição = valor bruto + deslocamento ou posição = valor bruto − deslocamento; o manual não define a convenção, então ambas são simuladas.
- Queda pela gravidade: ao desligar o torque, as articulações instaladas no Microduck cedem (no teste real, o pescoço caiu 80 passos em 130 ms, cerca de 0,62 passo/ms). droop define quantos passos caem por milissegundo. Sem isso, não seria possível detectar falhas como esperar demais após desligar o torque e calibrar a posição caída como zero.
- Latência do barramento: cada ida e volta real (envio do pacote, espera da resposta e temporizador de latência USB) leva cerca de 1–2 ms. latency_ms simula esse atraso e atualiza um relógio virtual; a queda é calculada com esse relógio, deixando os testes determinísticos e independentes da velocidade da máquina. time.sleep também é contabilizado.
- A tabela de registradores termina em 86; leituras além dela retornam somente os bytes restantes (em um teste real, a leitura de 10 bytes a partir do endereço 80 retornou 7).
- O bit 15 indica sinal em posição, velocidade e corrente. O deslocamento do registrador 31 também usa o bit 15 como sinal (foi lido o valor 34279, equivalente a -1511).
- REBOOT (0x08) não retorna pacote.
"""
import struct
import time

import feetech

TABLE_END = 87


def enc15(v):
    return (0x8000 | (-v & 0x7FFF)) if v < 0 else (v & 0x7FFF)


class SimServo:
    def __init__(self, sid, phys=2048):
        self.r = bytearray(TABLE_END)
        r = self.r
        r[0], r[1], r[2], r[3], r[4] = 3, 46, 0, 3, 10      # Firmware 3.46, END=0, little-endian.
        r[5], r[6], r[8] = sid, 0, 1                        # ID, baud rate 1M, nível de resposta 1.
        struct.pack_into("<HH", r, 9, 0, 4095)
        r[13], r[15] = 70, 40
        struct.pack_into("<H", r, 16, 1000)
        r[18], r[21], r[22], r[33] = 52, 32, 32, 4          # Fase 52, P/D 32, modo 4.
        struct.pack_into("<H", r, 48, 1000)
        r[55] = 1                                           # Travado de fábrica.
        r[62], r[63] = 74, 30
        self.phys = phys          # Leitura física do encoder, sem deslocamento.
        self.off = 0              # Deslocamento: posição informada = phys + off.
        self.goal = None
        self.calibrations = 0     # Número de calibrações do ponto central; usado nos testes.
        self.muted = set()        # Endereços sem resposta, simulando desconexão durante a operação.
        self.accept_128 = False   # O HD-1910 não reconhece 128.
        self.support_0b = True
        self.ignore_offset_writes = False   # Simula servos que também ignoram gravações de deslocamento.
        self.offset_adds = True   # Posição informada = phys + off; False: phys − off. O manual não define a convenção, então ambas devem funcionar.
        self.droop = 0.0          # Passos de queda por milissegundo com torque desligado; medição real no pescoço: 0,62.
        self._t = 0.0             # Relógio virtual do barramento em milissegundos na última atualização.
        self.mute_after_calib = set()   # Endereços que deixam de responder após a calibração.

    @property
    def id(self):
        return self.r[5]

    def pos(self):
        return self.phys + (self.off if self.offset_adds else -self.off)

    def tick(self, clock_ms=0.0):
        """Com o torque ligado, vai diretamente ao alvo (a dinâmica não é simulada); com o torque desligado, cede conforme droop.

        clock_ms é o relógio virtual do barramento, avançado por SimSerial a cada pacote e pelo tempo real de sleep."""
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
                continue                                     # Retorna sucesso sem executar ação.
            self.r[a] = b
        # Atualiza os registradores de vários bytes.
        if addr <= 42 < addr + len(data):
            self.goal = feetech.sign15(struct.unpack_from("<H", self.r, 42)[0])
        if addr <= 31 < addr + len(data) and not self.ignore_offset_writes:
            self.off = feetech.sign15(struct.unpack_from("<H", self.r, 31)[0])
        if addr <= 40 < addr + len(data) and self.r[40] == 1 and self.goal is None:
            self.goal = self.pos()

    def recalibrate(self, value):
        # phys pode ser fracionário devido à queda; arredonda o deslocamento, pois os registradores reais só armazenam inteiros.
        self.off = round((value - self.phys) if self.offset_adds else (self.phys - value))
        self.calibrations += 1
        self.muted |= self.mute_after_calib

    def read(self, addr, n, clock_ms=0.0):
        self.tick(clock_ms)
        return bytes(self.r[addr:min(addr + n, TABLE_END)])


class SimSerial:
    """Porta serial simulada: write() recebe comandos e gera respostas dos servos no barramento; read() as retorna."""

    def __init__(self, ids, phys=None):
        self.timeout = 0.02
        self.servos = {i: SimServo(i, (phys or {}).get(i, 2048)) for i in ids}
        self.rx = bytearray()
        self.latency_ms = 0.0     # Atraso em ms por ida e volta; URT-2 real leva cerca de 1–2 ms.
        self.clock = 0.0          # Relógio virtual do barramento em ms: soma a latência de cada pacote e os sleeps reais do chamador.
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
                continue                                         # Checksum inválido: servos reais ignoram o pacote.
            self._handle(sid, instr, params)
        return len(data)

    # ---- Servos ----
    def _by_id(self, sid):
        for s in self.servos.values():
            if s.id == sid:
                return s
        return None

    def _advance(self):
        """Avança o relógio virtual: atraso de uma ida e volta no barramento mais o tempo real de espera desde a última atualização (time.sleep também conta para a queda)."""
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
                # alive() é usado pela placa de IMU simulada para representar “processador do barramento ainda não iniciou” e “placa não responde”.
                if s and addr not in getattr(s, "muted", ()) and getattr(s, "alive", lambda _: True)(self.clock):
                    self._reply(s, s.read(addr, ln, self.clock))
            return
        s = self._by_id(sid)
        if s is None:
            return
        if instr == feetech.PING:
            if sid == feetech.BROADCAST or not getattr(s, "alive", lambda _: True)(self.clock):
                return                                       # Conforme o manual, não use PING broadcast quando há vários dispositivos no barramento.
            self._reply(s)
        elif instr == feetech.READ:
            if p[0] in s.muted or not getattr(s, "alive", lambda _: True)(self.clock):
                return
            self._reply(s, s.read(p[0], p[1], self.clock))
        elif instr == feetech.WRITE:
            s.write(p[0], p[1:])
            self._reply(s)                                       # Ao alterar o ID, responde usando o novo ID.
        elif instr == feetech.CALIBRATE:
            if s.support_0b:
                s.recalibrate(2048 if len(p) < 2 else feetech.sign15(p[0] | p[1] << 8))
            self._reply(s)
        elif instr == feetech.REBOOT:
            s.r[40] = 0                                          # Não responde ao comando; o torque fica desligado após a reinicialização.
