# -*- coding: utf-8 -*-
"""Implementação mínima do barramento Feetech STS/SMS: formato dos pacotes,
leitura e gravação, leitura/gravação síncronas e reinicialização.

Baseada em docs/飞特资料/SCS通信协议-v1.0-2026-06-09.md e no manual da tabela de
memória STS com codificador magnético v1.1-2026-08-27. Não depende do SDK Feetech.
Segue a ordem de bytes da série com codificador magnético: little-endian.
"""
import struct
import threading
import time

import serial

PING, READ, WRITE, REG_WRITE, ACTION = 0x01, 0x02, 0x03, 0x04, 0x05
RECOVERY, REBOOT, BACKUP, RESET_TURNS, CALIBRATE = 0x06, 0x08, 0x09, 0x0A, 0x0B
SYNC_READ, SYNC_WRITE = 0x82, 0x83
INSTR_NAMES = {0x01: "PING", 0x02: "READ", 0x03: "WRITE", 0x04: "REG_WRITE", 0x05: "ACTION",
               0x06: "Restaurar parâmetros", 0x08: "REBOOT", 0x09: "Fazer backup dos parâmetros", 0x0A: "Zerar voltas", 0x0B: "Calibrar posição",
               0x82: "SYNC_READ", 0x83: "SYNC_WRITE"}
BROADCAST = 0xFE

# Tabela de memória: endereço -> (nome, bytes, região). Usada na exportação de registradores.
REGISTERS = {
    0: ("Versão principal do firmware", 1, "Somente leitura"), 1: ("Versão secundária do firmware", 1, "Somente leitura"), 2: ("Ordem de bytes END (0=little-endian)", 1, "Somente leitura"),
    3: ("Versão principal do servo", 1, "Somente leitura"), 4: ("Versão secundária do servo", 1, "Somente leitura"),
    5: ("ID", 1, "EEPROM"), 6: ("Taxa de transmissão (0=1M)", 1, "EEPROM"), 7: ("Endereço reservado (registrador de atraso de resposta STS)", 1, "EEPROM"),
    8: ("Nível de resposta", 1, "EEPROM"), 9: ("Limite mínimo de ângulo", 2, "EEPROM"), 11: ("Limite máximo de ângulo", 2, "EEPROM"),
    13: ("Limite máximo de temperatura", 1, "EEPROM"), 14: ("Tensão máxima de entrada", 1, "EEPROM"), 15: ("Tensão mínima de entrada", 1, "EEPROM"),
    16: ("Torque máximo", 2, "EEPROM"), 18: ("Fase", 1, "EEPROM"), 19: ("Condições de desligamento", 1, "EEPROM"),
    20: ("Condições do alerta do LED", 1, "EEPROM"), 21: ("P do controlador de posição", 1, "EEPROM"), 22: ("D do controlador de posição", 1, "EEPROM"),
    23: ("I do controlador de posição", 1, "EEPROM"), 24: ("Torque mínimo de partida", 1, "EEPROM"), 25: ("Limite integral", 1, "EEPROM"),
    26: ("Zona morta positiva", 1, "EEPROM"), 27: ("Zona morta negativa", 1, "EEPROM"), 28: ("Corrente de proteção", 2, "EEPROM"),
    30: ("Resolução angular", 1, "EEPROM"), 31: ("Deslocamento de posição", 2, "EEPROM"), 33: ("Modo de operação", 1, "EEPROM"),
    34: ("Torque de sustentação", 1, "EEPROM"), 35: ("Tempo de proteção", 1, "EEPROM"), 36: ("Torque de sobrecarga", 1, "EEPROM"),
    37: ("P do controlador de velocidade", 1, "EEPROM"), 38: ("Tempo de proteção contra sobrecorrente", 1, "EEPROM"), 39: ("I do controlador de velocidade", 1, "EEPROM"),
    40: ("Chave do torque", 1, "SRAM"), 41: ("Aceleração", 1, "SRAM"), 42: ("Posição-alvo", 2, "SRAM"),
    44: ("Velocidade em malha aberta PWM", 2, "SRAM"), 46: ("Velocidade de operação", 2, "SRAM"), 48: ("Limite de torque", 2, "SRAM"),
    55: ("Sinalizador de bloqueio", 1, "SRAM"),
    56: ("Posição atual", 2, "Retorno"), 58: ("Velocidade atual", 2, "Retorno"), 60: ("Carga atual", 2, "Retorno"),
    62: ("Tensão atual (0,1 V)", 1, "Retorno"), 63: ("Temperatura atual (°C)", 1, "Retorno"), 64: ("Sinalizador de gravação assíncrona", 1, "Retorno"),
    65: ("Bits de estado do servo", 1, "Retorno"), 66: ("Sinalizador de movimento", 1, "Retorno"), 67: ("Posição-alvo (leitura de retorno)", 2, "Retorno"),
    69: ("Corrente atual (6,5 mA)", 2, "Retorno"),
    80: ("Limite de velocidade de movimento", 1, "Fábrica"), 81: ("DTs (ms)", 1, "Fábrica"), 82: ("Fator da unidade de velocidade", 1, "Fábrica"),
    83: ("Limite mínimo de velocidade", 1, "Fábrica"), 84: ("Limite máximo de velocidade", 1, "Fábrica"), 85: ("Limite de aceleração", 1, "Fábrica"),
    86: ("Multiplicador de aceleração", 1, "Fábrica"),
}
STATUS_BITS = {0: "Tensão", 1: "Codificador magnético", 2: "Temperatura", 3: "Corrente", 5: "Carga"}
DUMP_END = max(REGISTERS) + 1   # 87: endereço final da tabela de registradores (86)


def sign15(v):
    """Valor de 16 bits em que BIT15 indica o sentido (posição, velocidade, corrente)."""
    return -(v & 0x7FFF) if v & 0x8000 else v


def sign10(v):
    """BIT10 indica o sentido da carga."""
    return -(v & 0x3FF) if v & 0x400 else v


class BusError(Exception):
    pass


class BusTimeout(BusError):
    """Sem resposta ou resposta incompleta. No nível de resposta 0, comandos de gravação
    não retornam pacote; cabe ao chamador decidir se isso representa uma falha."""


def hexs(b):
    return " ".join(f"{x:02x}" for x in b)


class FeetechBus:
    def __init__(self, port, baud=1_000_000, timeout=0.02, ser=None):
        # ser é usado pelo simulador (sim_bus.SimSerial); o hardware real usa a porta serial.
        self.ser = ser if ser is not None else serial.Serial(port, baud, timeout=timeout, write_timeout=0.1)
        # Exclusão mútua da porta serial. Não chamar de self.lock: isso ocultaria o método
        # lock(sid), que bloqueia a EEPROM (problema observado no hardware em 2026-09-20).
        self._io = threading.Lock()
        # Registro bruto de envio e recebimento: começa ao definir uma função trace(texto).
        # A Feetech pode responder "sucesso" a operações não suportadas; os dados
        # hexadecimais ajudam a distinguir execução real de uma resposta aparente. A
        # consulta de estado a 10 Hz é omitida para não dominar o log.
        self.trace = None
        self.trace_skip = {SYNC_READ, SYNC_WRITE}
        self._last = (None, None)
        self.stats = {"tx": 0, "rx_ok": 0, "timeout": 0, "bad_checksum": 0, "bad_id": 0}

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
                note = f"  endereço {params[0]}" + (f" ({reg[0]})" if reg else "") + (
                    f" grava {list(params[1:])}" if instr == WRITE else f" lê {params[1]} byte(s)")
            self.trace(f"→ #{sid} {INSTR_NAMES.get(instr, hex(instr))} {hexs(pkt)}{note}")

    def _read_status(self, expect_id=None):
        """读一个应答帧，返回 (id, error, params)。"""
        # Procura FF FF.
        hdr = b""
        deadline = time.monotonic() + self.ser.timeout * 3
        while time.monotonic() < deadline:
            b = self.ser.read(1)
            if not b:
                break
            hdr = (hdr + b)[-2:]
            if hdr == b"\xff\xff":
                break
        who = f"ID {expect_id}" if expect_id is not None else "servo"
        if hdr != b"\xff\xff":
            self.stats["timeout"] += 1
            raise BusTimeout(f"{who} sem resposta (cabeçalho do quadro não recebido em {self.ser.timeout * 3 * 1000:.0f} ms)")
        rest = self.ser.read(2)
        if len(rest) < 2:
            self.stats["timeout"] += 1
            raise BusTimeout(f"resposta de {who} interrompida em ID/tamanho (recebido ff ff {hexs(rest)})")
        sid, length = rest[0], rest[1]
        body = self.ser.read(length)
        if len(body) < length:
            self.stats["timeout"] += 1
            raise BusTimeout(f"resposta incompleta de {who}: tamanho {length}, recebidos {len(body)} byte(s) (ff ff {hexs(rest + body)})")
        err, params, chk = body[0], body[1:-1], body[-1]
        if ((~(sid + length + err + sum(params))) & 0xFF) != chk:
            self.stats["bad_checksum"] += 1
            raise BusError(f"soma de verificação inválida na resposta de {who} (ff ff {hexs(rest + body)})")
        if expect_id is not None and sid != expect_id:
            self.stats["bad_id"] += 1
            raise BusError(f"esperada resposta do ID {expect_id}, recebido ID {sid} (ff ff {hexs(rest + body)})")
        self.stats["rx_ok"] += 1
        if self.trace and self._last[1] not in self.trace_skip:
            frame_hex = hexs(b'\xff\xff' + rest + body)
            data_suffix = f"  dados {list(params)}" if params else ""
            self.trace(f"← #{sid} estado 0x{err:02X} {frame_hex}" + data_suffix)
        return sid, err, bytes(params)

    # ---- Instruções ----
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
            _, err, params = self._read_status(sid)
            if len(params) != n:
                raise BusError(f"ID {sid}: solicitada leitura de {n} byte(s) a partir do endereço {addr}, mas recebidos apenas {len(params)}")
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
                # No nível de resposta 0, gravações não retornam pacote; o chamador decide
                # como interpretar o None recebido.
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
        """id_values: [(id, bytes), ...]; cada sequência de bytes deve ter length bytes."""
        params = bytes([addr, length])
        for sid, data in id_values:
            assert len(data) == length
            params += bytes([sid]) + bytes(data)
        with self._io:
            self._send(BROADCAST, SYNC_WRITE, params)

    def sync_read(self, ids, addr, n):
        """Retorna {id: (err, params) ou None}; associa cada resposta ao ID recebido,
        sem descartar as respostas seguintes quando um pacote estiver ausente."""
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
        return out

    def reboot(self, sid):
        """0x08 não retorna resposta; o servo volta após aproximadamente 800 ms."""
        with self._io:
            self._send(sid, REBOOT)

    def calibrate_to(self, sid, value=None):
        """Calibração de posição 0x0B: define a leitura da posição atual do servo como
        value (2048, posição central, se omitido); o próprio servo calcula e salva o
        deslocamento. Seção 4.9 do manual: STS ≥3.10 e HLS ≥3.43 aceitam parâmetros.
        O HD-1910 (firmware 3.46) não reconhece a gravação 128 na chave de torque, então
        esta instrução é a alternativa necessária. Retorna o byte de estado da resposta;
        retorna None se não houver resposta."""
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

    # ---- Operações combinadas ----
    def state(self, sid):
        """56..70: posição, velocidade, carga, tensão, temperatura, gravação assíncrona,
        estado, movimento, alvo e corrente = 15 bytes."""
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
        """Obtém todos os dados em uma operação sync_read; IDs com falha recebem None."""
        raw = self.sync_read(ids, 56, 15)
        return {sid: (self._decode_state(*v) if v else None) for sid, v in raw.items()}

    def dump(self, sid):
        """Lê os registradores 0–86 e decodifica-os usando REGISTERS."""
        raw = b""
        for start in range(0, DUMP_END, 10):          # A tabela do HD-1910 termina em 86; leituras além dela retornam apenas os bytes disponíveis.
            n = min(10, DUMP_END - start)
            for attempt in range(4):
                try:
                    raw += self.read(sid, start, n)[1]
                    break
                except BusError as e:
                    if attempt == 3:
                        raise BusError(f"falha ao exportar a partir do endereço {start}: {e}")
                    time.sleep(0.01)
        rows = []
        for addr in sorted(REGISTERS):
            name, size, area = REGISTERS[addr]
            v = raw[addr] if size == 1 else struct.unpack_from("<H", raw, addr)[0]
            rows.append({"addr": addr, "name": name, "area": area, "size": size, "value": v})
        return {"rows": rows, "raw": list(raw)}

    def set_id(self, old, new):
        self.unlock(old)
        # A resposta ao pacote de alteração de ID pode usar o ID novo ou o antigo.
        # Não aguarde por ela; o buffer de recepção será limpo antes do próximo pacote.
        self.write(old, 5, [new & 0xFF], wait=False)
        time.sleep(0.02)
        self.lock(new)
        return self.ping(new) is not None
