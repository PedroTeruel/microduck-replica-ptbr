# -*- coding: utf-8 -*-
"""Lê a placa IMU (ID 200) pelo barramento TTL dos servos. Por padrão, usa o protocolo
Feetech fornecido pelo repositório (56/15); opcionalmente, aceita o DXL2 (124/12).

Servos e IMU podem usar protocolos diferentes: o estado dos servos continua decodificado
por Feetech SCS, e o bloco da IMU é processado aqui. Os critérios para o bloco Feetech
de 15 bytes seguem o controlador principal (duck-control/imu.rs e bus.rs do fork) e
correspondem aos de tools/imu200/imu200.py:

- Todos os três componentes do quaternion iguais a 0 → a fusão ainda não produziu dados
  (o controlador mantém o quadro anterior e não marca o estado como pronto).
- Valor não finito ou norm² > 1,02 → o controlador rejeita o quadro.
- Os 12 primeiros bytes idênticos por 25 quadros consecutivos → o controlador informa
  que a orientação está congelada.
- O byte reservado (byte 14) deve ser 0; os bits BIT1/BIT2 indicam falhas reportadas
  pela própria placa.

Após 5 respostas ausentes consecutivas da placa, pausa as leituras e envia um PING
separado ao ID 200 a cada 2 s. No modo Feetech, mantém a leitura síncrona dos servos e
da IMU; no modo DXL2, consulta a IMU separadamente, enquanto os servos continuam usando
requisições Feetech.
"""
import math
import struct
import threading
import time

from imu_bridge import BridgeError, HOST_STALE_MS, decode_quaternion, empty_frame

IMU_ID = 200
FEETECH_BLOCK_ADDR = 56
FEETECH_BLOCK_LEN = 15
DXL2_BLOCK_ADDR = 124
DXL2_BLOCK_LEN = 12
BLOCK_ADDR = FEETECH_BLOCK_ADDR
BLOCK_LEN = FEETECH_BLOCK_LEN
WINDOW = 12               # O controlador só compara os 12 primeiros bytes; StaleImuTracker também usa somente esses bytes.
FROZEN_FRAMES = 25        # bus.rs: informa congelamento após 25 quadros idênticos consecutivos.
GYRO_DPS_PER_LSB = 0.0175
MISS_DEGRADE = 5          # Após esse número de respostas ausentes do ID 200, remove-o temporariamente de sync_read.
RETRY_S = 2.0             # Depois da remoção, envia PING separado neste intervalo.

BIT_FUSION_NOT_READY = 0x01
BIT_IMU_COMM_FAIL = 0x02
BIT_SELF_TEST_FAIL = 0x04
BIT_READER_TOO_SLOW = 0x08
SLOW_READER_HZ = 30      # BIT3 indica mais de 4 atualizações entre leituras (amostragem de 120 Hz), aproximadamente abaixo de 30 Hz de leitura.


def decode_block(block):
    """Decodifica um bloco Feetech de 15 bytes ou DXL2 de 12 bytes, sem transformação de coordenadas."""
    if len(block) not in (FEETECH_BLOCK_LEN, DXL2_BLOCK_LEN):
        raise BridgeError(f"Tamanho do bloco {len(block)}; esperado 12 (DXL2) ou 15 (Feetech)")
    gyro = struct.unpack_from("<3h", block, 0)
    packed = struct.unpack_from("<3H", block, 6)
    is_dxl2 = len(block) == DXL2_BLOCK_LEN
    return {"gyro_raw": list(gyro), "gyro_dps": [v * GYRO_DPS_PER_LSB for v in gyro],
            "quat_fp16": list(packed), "counter": None if is_dxl2 else block[12],
            "bits": 0 if is_dxl2 else block[13], "reserved": 0 if is_dxl2 else block[14],
            "window": bytes(block[:WINDOW])}


class BusImuService:
    """Usa a mesma interface de BridgeService (start/stop/get_status); recebe dados da consulta de estado do server."""

    demo = False
    backend = "bus"

    def __init__(self, poll_hz=None, protocol="feetech"):
        # O painel consulta na frequência poll_hz (10 Hz por padrão). Abaixo de 30 Hz,
        # BIT3 acende em todos os quadros por causa da consulta lenta do painel, não do
        # controlador; portanto, não exibe esse aviso.
        self.poll_hz = poll_hz
        self.protocol = protocol
        self.lock = threading.Lock()
        self.frame = self._frame("disconnected", "Aguardando a primeira leitura sync_read com o ID 200.")
        self.last_publish = time.monotonic()
        self.misses = 0
        self.total_misses = 0
        self.excluded_since = None       # Horário em que o ID foi removido de sync_read; None = ID 200 incluído normalmente.
        self.last_probe = None
        self.last_window = None
        self.same_run = 0
        self.previous_ok = None
        self.smooth_hz = 0.0
        self.frames = 0

    # ---- Ciclo de vida: não possui thread própria; mantém a interface de BridgeService. ----
    def start(self):
        pass

    def stop(self):
        pass

    def set_protocol(self, protocol):
        if protocol not in ("dxl2", "feetech"):
            raise ValueError(f"Protocolo de barramento da IMU não suportado: {protocol}")
        with self.lock:
            if protocol == self.protocol:
                return False
            self.protocol = protocol
            self.misses = 0
            self.excluded_since = None
            self.last_probe = None
            self.last_window = None
            self.same_run = 0
            self.previous_ok = None
            self.smooth_hz = 0.0
            self.frame = self._frame("disconnected", f"Protocolo alterado para {protocol}; aguardando resposta do ID 200.")
            self.last_publish = time.monotonic()
        return True

    def _frame(self, status, message, **extra):
        frame = empty_frame("live", status, message)
        frame.update(backend="bus", probe_name="Barramento dos servos, ID 200", **extra)
        return frame

    def _publish(self, frame):
        frame["timestamp_ms"] = int(time.time() * 1000)
        with self.lock:
            self.frame = frame
            self.last_publish = time.monotonic()

    def get_status(self):
        with self.lock:
            result = dict(self.frame)
            elapsed_ms = (time.monotonic() - self.last_publish) * 1000
        if result["live"] and elapsed_ms >= HOST_STALE_MS:
            result.update(status="stale", live=False, quaternion_xyzw=None, gyro_dps=None, hz=0.0,
                          message="Consulta do barramento interrompida (nenhuma página conectada ou calibração em andamento); orientação pausada.")
        return result

    # ---- Consulta ----
    def include_in_sync(self):
        """Indica se este sync_read deve incluir o ID 200."""
        return self.excluded_since is None

    def due_probe(self, now=None):
        """Durante a remoção temporária, indica se chegou a hora de enviar PING separado ao ID 200."""
        if self.excluded_since is None:
            return False
        now = time.monotonic() if now is None else now
        if self.last_probe is None or now - self.last_probe >= RETRY_S:
            self.last_probe = now
            return True
        return False

    def probe_result(self, answered):
        """Resultado do PING separado: se houver resposta, inclui novamente em sync_read. Retorna se foi reincluído."""
        if answered and self.excluded_since is not None:
            self.excluded_since = None
            self.misses = 0
            self._publish(self._frame("disconnected", "O PING do ID 200 respondeu; ele será incluído novamente no próximo quadro."))
            return True
        return False

    def feed(self, block, now=None):
        """block = bloco de 15 bytes do ID 200; None = sem resposta neste quadro (ou ID não incluído). Retorna o quadro gerado."""
        now = time.monotonic() if now is None else now
        if block is None:
            self.misses += 1
            self.total_misses += 1
            if self.misses >= MISS_DEGRADE and self.excluded_since is None:
                self.excluded_since = now
            frame = self._frame("disconnected",
                                f"ID 200 sem resposta por {self.misses} quadros consecutivos: verifique a alimentação da placa, a conexão do barramento (DATA em J1/J2) "
                                f"e o protocolo da IMU (atual: {self.protocol}); os servos agora são consultados separadamente e o ID 200 recebe PING a cada {RETRY_S:.0f} s.",
                                misses=self.total_misses)
            self._publish(frame)
            return frame
        self.misses = 0
        self.excluded_since = None
        d = decode_block(block)
        extra = {"connected": True, "sample_count": d["counter"], "raw_gyro": d["gyro_raw"],
                 "quat_fp16": d["quat_fp16"], "status_bits": d["bits"] if self.protocol != "dxl2" else None,
                 "misses": self.total_misses,
                 "errors": {"imu": d["bits"] & (BIT_IMU_COMM_FAIL | BIT_SELF_TEST_FAIL), "spi": None,
                            "fifo": None, "quaternion": None, "recovery": None}}
        self.same_run = self.same_run + 1 if d["window"] == self.last_window else 0
        self.last_window = d["window"]
        if d["reserved"] != 0:
            frame = self._frame("error", f"Byte reservado do bloco (byte 14) igual a {d['reserved']}; a especificação exige 0. O firmware não corresponde à seção 3 do protocolo do barramento.", **extra)
        elif d["bits"] & BIT_SELF_TEST_FAIL:
            frame = self._frame("error", "A placa informou falha no autoteste da IMU (BIT2, WHO_AM_I incorreto); confira a soldagem do chip da IMU.", **extra)
        elif d["bits"] & BIT_IMU_COMM_FAIL:
            frame = self._frame("error", "A placa informou falha de comunicação com o chip da IMU (BIT1: SPI, reinicialização, configuração, FIFO ou dados expirados).", **extra)
        elif not any(d["quat_fp16"]) or d["bits"] & BIT_FUSION_NOT_READY:
            frame = self._frame("stale", "A fusão da IMU ainda não produziu dados (quaternion zerado / BIT0); isso é normal por cerca de 0,5 s após ligar.", **extra)
        elif self.same_run + 1 >= FROZEN_FRAMES:
            frame = self._frame("stale", f"Os 12 primeiros bytes permaneceram idênticos por {self.same_run + 1} quadros; o controlador informará orientation is frozen. "
                                "Mesmo parada, a leitura bruta do chip real deve variar nos bits menos significativos; o firmware não deve suavizar nem quantizar o giroscópio.", **extra)
        else:
            try:
                quaternion = decode_quaternion(tuple(d["quat_fp16"]))
            except BridgeError as exc:
                frame = self._frame("error", f"O controlador rejeitaria este quaternion: {exc}", **extra)
            else:
                if self.previous_ok is not None:
                    instant = 1.0 / max(1e-4, now - self.previous_ok)
                    self.smooth_hz = instant if self.smooth_hz == 0 else self.smooth_hz * 0.8 + instant * 0.2
                self.previous_ok = now
                slow = ("; BIT3: o bloco foi atualizado mais de 4 vezes entre leituras; consulta lenta"
                        if d["bits"] & BIT_READER_TOO_SLOW
                        and (self.poll_hz is None or self.poll_hz >= SLOW_READER_HZ) else "")
                frame = self._frame("live", "Lendo o ID 200 pelo barramento dos servos (mesmo sync_read do controlador)" + slow + ".",
                                    live=True, quaternion_xyzw=quaternion, gyro_dps=d["gyro_dps"],
                                    hz=round(self.smooth_hz, 1), age_ms=None, **extra)
        self.frames += 1
        self._publish(frame)
        return frame


class FakeImu200:
    """Placa virtual usada no barramento simulado (--fake): atualiza o bloco a 120 Hz,
    varia os bits menos significativos do giroscópio e gira o quaternion lentamente em Z."""

    def __init__(self, sample_hz=120.0, ready_after_s=0.5):
        self.t0 = time.monotonic()
        self.sample_hz, self.ready_after_s = sample_hz, ready_after_s

    def block(self, now=None):
        t = (time.monotonic() if now is None else now) - self.t0
        n = int(t * self.sample_hz)
        if t < self.ready_after_s:
            return bytes(12) + bytes([n & 0xFF, BIT_FUSION_NOT_READY, 0])
        jitter = (n % 7) - 3
        yaw = 0.6 * math.sin(t * 0.5)
        gyro = (int(17 * math.cos(t * 0.5)) + jitter, jitter, -jitter)
        quat = (0.05, 0.0, math.sin(yaw / 2))   # Inclinação mínima para não zerar todos os componentes de z e parecer que a IMU ainda não está pronta.
        return (struct.pack("<3h", *gyro) + struct.pack("<3e", *quat)
                + bytes([n & 0xFF, 0, 0]))
