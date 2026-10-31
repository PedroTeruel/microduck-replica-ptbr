# -*- coding: utf-8 -*-
"""Implementação mínima do barramento Feetech STS/SMS: formato de pacotes, leitura e gravação, operações síncronas e reinicialização.

Implementado com base nos documentos de protocolo Feetech SCS e no manual da tabela de memória STS com encoder magnético incluídos no repositório.
não depende do SDK Feetech. A ordem de bytes segue a série com encoder magnético: little-endian.

Adaptado de tools/servo-web/feetech.py (v0.15.4, código nosso já usado em hardware real). No Studio, foram feitas duas alterações:
- Estatísticas de comunicação por servo (per_id): número de consultas, respostas, perdas, perdas consecutivas e alarmes de status.
  servo-web só mantém totais do barramento (pedido do usuário em 18/10: “verificar perda de quadros nas respostas de cada servo”); segue os critérios de
  communication_stats（missing / timeout / consecutive）。
-Importa serial somente quando necessário: pyserial não é necessário ao usar o simulador (sim_bus).
"""
import struct
import threading
import time

PING, READ, WRITE, REG_WRITE, ACTION = 0x01, 0x02, 0x03, 0x04, 0x05
RECOVERY, REBOOT, BACKUP, RESET_TURNS, CALIBRATE = 0x06, 0x08, 0x09, 0x0A, 0x0B
SYNC_READ, SYNC_WRITE = 0x82, 0x83
INSTR_NAMES = {0x01: "PING", 0x02: "READ", 0x03: "WRITE", 0x04: "REG_WRITE", 0x05: "ACTION",
               0x06: "Restaurar parâmetros", 0x08: "REBOOT", 0x09: "Fazer backup dos parâmetros", 0x0A: "Limpar contagem de voltas", 0x0B: "Calibrar posição",
               0x82: "SYNC_READ", 0x83: "SYNC_WRITE"}
BROADCAST = 0xFE

# Tabela de memória: endereço -> (nome, quantidade de bytes, área). Usada na exportação dos registradores.
REGISTERS = {
    0: ("Versão principal do firmware", 1, "Somente leitura"), 1: ("Versão secundária do firmware", 1, "Somente leitura"), 2: ("END (ordem de bytes; 0=little-endian)", 1, "Somente leitura"),
    3: ("Versão principal do servo", 1, "Somente leitura"), 4: ("Versão secundária do servo", 1, "Somente leitura"),
    5: ("ID", 1, "EEPROM"), 6: ("Taxa de transmissão (0=1M)", 1, "EEPROM"), 7: ("Endereço reservado (registrador de atraso de resposta do STS)", 1, "EEPROM"),
    8: ("Nível de resposta de status", 1, "EEPROM"), 9: ("Limite mínimo de ângulo", 2, "EEPROM"), 11: ("Limite máximo de ângulo", 2, "EEPROM"),
    13: ("Limite máximo de temperatura", 1, "EEPROM"), 14: ("Tensão de entrada máxima", 1, "EEPROM"), 15: ("Tensão de entrada mínima", 1, "EEPROM"),
    16: ("Torque máximo", 2, "EEPROM"), 18: ("Fase", 1, "EEPROM"), 19: ("Condição para desativar torque", 1, "EEPROM"),
    20: ("Condição de alerta do LED", 1, "EEPROM"), 21: ("P do controlador de posição", 1, "EEPROM"), 22: ("D do controlador de posição", 1, "EEPROM"),
    23: ("I do controlador de posição", 1, "EEPROM"), 24: ("Torque mínimo de partida", 1, "EEPROM"), 25: ("Limite integral", 1, "EEPROM"),
    26: ("Zona morta positiva", 1, "EEPROM"), 27: ("Zona morta negativa", 1, "EEPROM"), 28: ("Corrente de proteção", 2, "EEPROM"),
    30: ("Resolução angular", 1, "EEPROM"), 31: ("Offset de posição", 2, "EEPROM"), 33: ("Modo de operação", 1, "EEPROM"),
    34: ("Torque de retenção", 1, "EEPROM"), 35: ("Tempo de proteção", 1, "EEPROM"), 36: ("Torque de sobrecarga", 1, "EEPROM"),
    37: ("P do controlador de velocidade", 1, "EEPROM"), 38: ("Tempo de proteção contra sobrecorrente", 1, "EEPROM"), 39: ("I do controlador de velocidade", 1, "EEPROM"),
    40: ("Interruptor de torque", 1, "SRAM"), 41: ("Aceleração", 1, "SRAM"), 42: ("Posição desejada", 2, "SRAM"),
    44: ("Velocidade PWM em malha aberta", 2, "SRAM"), 46: ("Velocidade de operação", 2, "SRAM"), 48: ("Limite de torque", 2, "SRAM"),
    # 50–52: o manual STS indica “sem definição”; no HD-1910, estes endereços guardam P / D / I em operação (RAM, copiados de 21–23 ao ligar).
    # O programa principal grava esses valores ao habilitar o torque（fork duck-control/src/hd1910.rs:77-79、149、257-267；hd1910_test.rs:44-47）
    50: ("P do controlador de posição（em operação）", 1, "SRAM"), 51: ("D do controlador de posição（em operação）", 1, "SRAM"), 52: ("I do controlador de posição（em operação）", 1, "SRAM"),
    55: ("Sinalizador de trava", 1, "SRAM"),
    56: ("Posição atual", 2, "Retorno"), 58: ("Velocidade atual", 2, "Retorno"), 60: ("Carga atual", 2, "Retorno"),
    62: ("Tensão atual(0.1V)", 1, "Retorno"), 63: ("Temperatura atual(°C)", 1, "Retorno"), 64: ("Sinalizador de gravação assíncrona", 1, "Retorno"),
    65: ("Bits de status do servo", 1, "Retorno"), 66: ("Sinalizador de movimento", 1, "Retorno"), 67: ("Posição desejada (leitura de retorno)", 2, "Retorno"),
    69: ("Corrente atual(6.5mA)", 2, "Retorno"),
    80: ("Limite de velocidade de movimento", 1, "Fábrica"), 81: ("DTs(ms)", 1, "Fábrica"), 82: ("Fator da unidade de velocidade", 1, "Fábrica"),
    83: ("Limite mínimo de velocidade", 1, "Fábrica"), 84: ("Limite máximo de velocidade", 1, "Fábrica"), 85: ("Limite de aceleração", 1, "Fábrica"),
    86: ("Multiplicador de aceleração", 1, "Fábrica"),
}
STATUS_BITS = {0: "Tensão", 1: "Encoder magnético", 2: "Temperatura", 3: "Corrente", 5: "Carga"}
DUMP_END = max(REGISTERS) + 1   # 87: endereço final da tabela de registradores: 86


def sign15(v):
    """BIT15 é o bit de sinal de valores de 16 bits (posição, velocidade e corrente)."""
    return -(v & 0x7FFF) if v & 0x8000 else v


def sign10(v):
    """BIT10 é o bit de sinal (carga)."""
    return -(v & 0x3FF) if v & 0x400 else v


class BusError(Exception):
    pass


class BusTimeout(BusError):
    """Sem resposta ou resposta incompleta. Com nível de resposta 0, comandos de gravação não respondem; cabe ao chamador decidir se isso é um erro."""


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


class FeetechBus:
    def __init__(self, port, baud=1_000_000, timeout=0.02, ser=None):
        # ser Usado pelo simulador (sim_bus.SimSerial); no hardware real, usa a porta serial
        if ser is None:
            import serial   # noqa: PLC0415 — pyserial só é necessário para a porta serial real
            ser = serial.Serial(port, baud, timeout=timeout, write_timeout=0.1)
        self.ser = ser
        # Mutex da porta serial. Não use o nome self.lock: ele ocultaria o método lock(sid) abaixo, que ativa a trava EEPROM (problema observado em hardware real em 20/09/2026).
        self._io = threading.Lock()
        # Registro bruto de envio e recebimento: começa quando um callback trace(texto) é definido. Operações sem suporte da Feetech ainda retornam “sucesso”,
        # e somente a inspeção hexadecimal permite distinguir entre “executado” e “simulado”. A consulta de status a 10 Hz não é registrada para evitar poluir o log.
        self.trace = None
        self.trace_skip = {SYNC_READ, SYNC_WRITE}
        self._last = (None, None)
        self.stats = {"tx": 0, "rx_ok": 0, "timeout": 0, "bad_checksum": 0, "bad_id": 0}
        # Por servo: {id: {"asked", "ok", "missed", "alarm", "streak", "max_streak"}}。
        # O ID em um quadro com checksum inválido não é confiável; só é contabilizado nas estatísticas do barramento.
        self.per_id = {}

    def _note(self, sid, ok, err=0):
        c = self.per_id.get(sid)
        if c is None:
            c = self.per_id[sid] = {"asked": 0, "ok": 0, "missed": 0, "alarm": 0, "streak": 0, "max_streak": 0}
        c["asked"] += 1
        if ok:
            c["ok"] += 1
            c["streak"] = 0
            if err:
                c["alarm"] += 1
        else:
            c["missed"] += 1
            c["streak"] += 1
            c["max_streak"] = max(c["max_streak"], c["streak"])

    def close(self):
        self.ser.close()

    # ---- Pacotes ----
    @staticmethod
    def _packet(sid, instr, params=b""):
        length = len(params) + 2
        chk = (~(sid + length + instr + sum(params))) & 0xFF
        return bytes([0xFF, 0xFF, sid, length, instr]) + bytes(params) + bytes([chk])

    def _send(self, sid, instr, params=b""):
        self.ser.reset_input_buffer()
        pkt = self._packet(sid, instr, params)
        self.ser.write(pkt)
        self.stats["tx"] += 1
        self._last = (sid, instr)
        if self.trace and instr not in self.trace_skip:
            note = ""
            if instr in (READ, WRITE) and params:
                reg = REGISTERS.get(params[0])
                note = f"  Endereço{params[0]}" + (f"「{reg[0]}」" if reg else "") + (
                    f"  gravação {list(params[1:])}" if instr == WRITE else f" leitura {params[1]} bytes")
            self.trace(f"→ #{sid} {INSTR_NAMES.get(instr, hex(instr))} {hexs(pkt)}{note}")

    def _read_status(self, expect_id=None):
        """Lê um quadro de resposta e retorna (id, error, params)."""
        # Procura FF FF
        hdr = b""
        deadline = time.monotonic() + self.ser.timeout * 3
        while time.monotonic() < deadline:
            b = self.ser.read(1)
            if not b:
                break
            hdr = (hdr + b)[-2:]
            if hdr == b"\xff\xff":
                break
        who = f"id {expect_id}" if expect_id is not None else "servo"
        if hdr != b"\xff\xff":
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} sem resposta (cabeçalho não recebido em {self.ser.timeout * 3 * 1000:.0f} ms)")
        rest = self.ser.read(2)
        if len(rest) < 2:
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} resposta interrompida no ID/comprimento (recebido ff ff {hexs(rest)})")
        sid, length = rest[0], rest[1]
        body = self.ser.read(length)
        if len(body) < length:
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} resposta incompleta: comprimento {length}, recebidos apenas {len(body)} (ff ff {hexs(rest + body)})")
        err, params, chk = body[0], body[1:-1], body[-1]
        if ((~(sid + length + err + sum(params))) & 0xFF) != chk:
            self.stats["bad_checksum"] += 1
            raise BusError(f"{who} checksum incorreto (ff ff {hexs(rest + body)})")
        if expect_id is not None and sid != expect_id:
            self.stats["bad_id"] += 1
            raise BusError(f"esperava resposta do id {expect_id}, recebido id {sid} (ff ff {hexs(rest + body)})")
        self.stats["rx_ok"] += 1
        if self.trace and self._last[1] not in self.trace_skip:
            self.trace(f"← #{sid} status 0x{err:02X} {hexs(b'\xff\xff' + rest + body)}"
                       + (f"  dados {list(params)}" if params else ""))
        return sid, err, bytes(params)

    # ---- Comandos ----
    def ping(self, sid):
        with self._io:
            self._send(sid, PING)
            try:
                _, err, _ = self._read_status(sid)
                return err
            except BusError:
                return None

    def read(self, sid, addr, n):
        with self._io:
            self._send(sid, READ, bytes([addr, n]))
            try:
                _, err, params = self._read_status(sid)
            except BusError:
                self._note(sid, False)
                raise
            self._note(sid, True, err)
            if len(params) != n:
                raise BusError(f"id {sid} leu {n} bytes a partir do endereço {addr}, mas recebeu apenas {len(params)} bytes")
            return err, params

    def write(self, sid, addr, data, wait=True):
        with self._io:
            self._send(sid, WRITE, bytes([addr]) + bytes(data))
            if not wait or sid == BROADCAST:
                return None
            try:
                _, err, _ = self._read_status(sid)
                return err
            except BusTimeout:
                # Com nível de resposta 0, gravações não respondem e isso não conta como erro; o chamador recebe None e decide
                return None

    def write_u8(self, sid, addr, v):
        return self.write(sid, addr, [v & 0xFF])

    def write_u16(self, sid, addr, v):
        return self.write(sid, addr, struct.pack("<H", v & 0xFFFF))

    def read_u8(self, sid, addr):
        return self.read(sid, addr, 1)[1][0]

    def read_u16(self, sid, addr):
        return struct.unpack("<H", self.read(sid, addr, 2)[1])[0]

    def sync_write(self, addr, length, id_values):
        """id_values: [(id, bytes), ...]; cada sequência de bytes tem comprimento igual a length."""
        params = bytes([addr, length])
        for sid, data in id_values:
            assert len(data) == length
            params += bytes([sid]) + bytes(data)
        with self._io:
            self._send(BROADCAST, SYNC_WRITE, params)

    def sync_read(self, ids, addr, n):
        """Retorna {id: (err, params) ou None}; organiza pela ID da resposta, sem descartar respostas posteriores quando um pacote falta."""
        out = dict.fromkeys(ids)
        with self._io:
            self._send(BROADCAST, SYNC_READ, bytes([addr, n]) + bytes(ids))
            for _ in ids:
                try:
                    sid, err, params = self._read_status()
                except BusTimeout:
                    break
                except BusError:
                    continue
                if sid not in out:
                    self.stats["bad_id"] += 1
                elif len(params) == n and out[sid] is None:
                    out[sid] = (err, params)
            for sid, v in out.items():
                self._note(sid, v is not None, v[0] if v else 0)
        return out

    def reboot(self, sid):
        """0x08, sem resposta; volta após cerca de 800 ms."""
        with self._io:
            self._send(sid, REBOOT)

    def calibrate_to(self, sid, value=None):
        """Calibração de posição 0x0B: altera a leitura da posição atual do servo para value (padrão: posição central 2048); o próprio servo calcula e armazena o offset.
        Manual de protocolo 4.9: STS ≥3.10 e HLS ≥3.43 aceitam parâmetros. O HD-1910 (firmware 3.46) não reconhece a gravação de 128 no interruptor de torque; use este comando.
        Retorna o byte de status da resposta; retorna None se não houver resposta."""
        params = b"" if value is None else struct.pack("<H", value & 0xFFFF)
        with self._io:
            self._send(sid, CALIBRATE, params)
            try:
                return self._read_status(sid)[1]
            except BusTimeout:
                return None

    def unlock(self, sid):
        return self.write_u8(sid, 55, 0)

    def lock(self, sid):
        return self.write_u8(sid, 55, 1)

    # ---- Ações combinadas ----
    def state(self, sid):
        """56..70: posição, velocidade, carga, tensão, temperatura, gravação assíncrona, status, movimento, alvo e corrente = 15 bytes."""
        err, p = self.read(sid, 56, 15)
        return self._decode_state(err, p)

    @staticmethod
    def _decode_state(err, p):
        pos, spd, load = struct.unpack_from("<HHH", p, 0)
        goal, cur = struct.unpack_from("<HH", p, 11)
        return {
            "err": err, "pos": sign15(pos), "speed": sign15(spd), "load": sign10(load),
            "volt": p[6] / 10.0, "temp": p[7], "status": p[9], "moving": p[10],
            "goal": sign15(goal), "current_ma": sign15(cur) * 6.5,
            "status_text": "".join(n for b, n in STATUS_BITS.items() if p[9] >> b & 1) or "",
        }

    def states(self, ids):
        """Obtém tudo com uma chamada sync_read; IDs sem resposta têm valor None."""
        raw = self.sync_read(ids, 56, 15)
        return {sid: (self._decode_state(*v) if v else None) for sid, v in raw.items()}

    def dump(self, sid):
        """Lê todos os endereços de 0 a 86 e decodifica usando REGISTERS."""
        raw = b""
        for start in range(0, DUMP_END, 10):          # A tabela do HD-1910 termina em 86; leituras além dela retornam apenas os bytes restantes
            n = min(10, DUMP_END - start)
            for attempt in range(4):
                try:
                    raw += self.read(sid, start, n)[1]
                    break
                except BusError as e:
                    if attempt == 3:
                        raise BusError(f"Erro ao exportar a partir do endereço {start}: {e}")
                    time.sleep(0.01)
        rows = []
        for addr in sorted(REGISTERS):
            name, size, area = REGISTERS[addr]
            v = raw[addr] if size == 1 else struct.unpack_from("<H", raw, addr)[0]
            rows.append({"addr": addr, "name": name, "area": area, "size": size, "value": v})
        return {"rows": rows, "raw": list(raw)}

    def set_id(self, old, new):
        self.unlock(old)
        # A resposta ao pacote que altera a ID pode usar a ID nova ou antiga; não aguarda por ela. O buffer de recepção será limpo antes do próximo pacote.
        self.write(old, 5, [new & 0xFF], wait=False)
        time.sleep(0.02)
        self.lock(new)
        return self.ping(new) is not None
