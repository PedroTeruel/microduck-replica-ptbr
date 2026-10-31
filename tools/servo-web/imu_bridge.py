"""STM32 IMU observation through the locally installed J-Link DLL.

The application makes no flash/program, Reset, Halt, memory-write, or probe
update API calls. It requests that the SDK disable work-RAM initialization on
connect and implicit Go on close. This is not a guarantee of zero target side effects:
device-specific SDK connection/debug initialization may still alter state.
Validate behavior against the actual DLL/target logs. The config's resume flag opts
in to Go() only after firmware verification if the CPU is halted. All DLL calls
belong to one worker thread.

SwdReader is the same observation through pyOCD, for ST-Link or CMSIS-DAP
(DAPLink) probes: check target voltage, attach without reset/halt, verify the
board Flash against the HEX, then read the same RAM snapshot. J-Link probes are
refused there (use JLinkReader), see the SwdReader docstring.
"""
from __future__ import annotations

import ctypes as ct
from dataclasses import dataclass
import hashlib
import logging
import math
import os
from pathlib import Path
import re
import struct
import threading
import time
from typing import Any

LOGGER = logging.getLogger("imu_bridge")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIRMWARE = PROJECT_ROOT / "hardware/imu_to_dxl/firmware/Build/imu_to_dxl.hex"
DEFAULT_MAP = None  # Optional locally generated map, never required by the checkout.
VALIDATED_SHA256 = "66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e"
# These symbols were reviewed against the map for the exact image above:
# firmware 0.2.0 (Feetech protocol), Keil MDK 5.41 / Arm Compiler 6.22, 10724 bytes.
# (0.1.0, Dynamixel 2.0: 69bdaea7..., sample 0x20000064, tick 0x20000BE0.)
# A different build must be reviewed before adding a new digest/layout pair.
SAMPLE_ADDRESS = 0x2000006C
TICK_ADDRESS = 0x20000A34
SNAPSHOT_SIZE = 60
SENSOR_STALE_MS = 100
HOST_STALE_MS = 350
SWD_FREQUENCY_HZ = 100_000  # Igual ao caminho J-Link: a gravação da primeira placa falhou em 4 MHz.


class BridgeError(RuntimeError):
    pass


def validate_probe_settings(dll_path: Path | None, serial: int | None) -> tuple[Path, int]:
    """Require an explicit probe identity and installed DLL before hardware access."""
    if isinstance(serial, bool) or not isinstance(serial, int) or not 1 <= serial <= 0xFFFFFFFF:
        raise BridgeError("No modo de hardware real, informe um --probe-serial / probe_serial válido (número de série J-Link inteiro positivo, diferente de zero).")
    if dll_path is None:
        raise BridgeError("No modo de hardware real, informe --dll / dll com o caminho local da JLink_x64.dll instalada.")
    path = Path(dll_path).expanduser().resolve()
    if not path.is_file():
        raise BridgeError(f"Arquivo DLL do J-Link não encontrado: {path}; informe o caminho real da instalação.")
    return path, serial


@dataclass(frozen=True)
class FirmwareLayout:
    image: bytes
    sha256: str
    sample_address: int
    tick_address: int


def read_firmware_image(firmware: Path) -> bytes:
    """Decode the committed Intel HEX without a BIN/MAP or extra dependency.

    Accept only contiguous STM32G031 main-flash data with checked record
    checksums, lengths, addresses and EOF. Never silently fill holes or accept
    overlapping records. The SHA check below still pins every decoded byte.
    """
    firmware = Path(firmware)
    if firmware.suffix.lower() != ".hex":
        return firmware.read_bytes()  # Optional local BIN, still digest-checked.
    cells = {}
    upper = 0
    eof = False
    try:
        lines = firmware.read_text(encoding="ascii").splitlines()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            if eof or not line.startswith(":"):
                raise ValueError(f"unexpected record at line {number}")
            record = bytes.fromhex(line[1:])
            if len(record) < 5 or len(record) != record[0] + 5 or sum(record) & 0xFF:
                raise ValueError(f"record length/checksum at line {number}")
            size, address, kind = record[0], int.from_bytes(record[1:3], "big"), record[3]
            payload = record[4:-1]
            if kind == 0:
                start = upper + address
                if not size or address + size > 0x10000 or not 0x08000000 <= start < start + size <= 0x08010000:
                    raise ValueError(f"data outside main flash at line {number}")
                for offset, value in enumerate(payload):
                    if start + offset in cells:
                        raise ValueError(f"overlapping data at line {number}")
                    cells[start + offset] = value
            elif kind == 1 and size == 0 and address == 0:
                eof = True
            elif kind == 4 and size == 2 and address == 0:
                upper = int.from_bytes(payload, "big") << 16
            elif kind == 5 and size == 4 and address == 0:
                if not 0x08000000 <= int.from_bytes(payload, "big") < 0x08010000:
                    raise ValueError("entry point outside main flash")
            else:
                raise ValueError(f"unsupported HEX record at line {number}")
        if not eof or not cells or min(cells) != 0x08000000 or len(cells) != max(cells) - 0x08000000 + 1:
            raise ValueError("missing EOF or non-contiguous flash image")
        return bytes(cells[address] for address in range(0x08000000, max(cells) + 1))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError(f"Arquivo HEX do firmware inválido: {exc}") from exc


def validate_firmware_layout(binary: Path, map_file: Path | None = None) -> FirmwareLayout:
    """Tie the RAM schema to the exact validated executable, never just a name."""
    image = read_firmware_image(binary)
    digest = hashlib.sha256(image).hexdigest()
    if digest != VALIDATED_SHA256:
        raise BridgeError("O arquivo de firmware difere da versão validada. Confira o layout e os endereços da RAM antes de ler; não tente adivinhar os dados.")
    if map_file is None:
        return FirmwareLayout(image, digest, SAMPLE_ADDRESS, TICK_ADDRESS)
    text = map_file.read_text(encoding="utf-8", errors="replace")

    def symbol(name: str, size: int, address: int, object_name: str) -> int:
        matches = re.findall(
            rf"^\s*{re.escape(name)}\s+0x([0-9a-fA-F]+)\s+Data\s+(\d+)\s+([^\r\n]+)",
            text, re.MULTILINE,
        )
        if len(matches) != 1:
            raise BridgeError(f"O símbolo {name} está ausente ou não é único no mapa de linkedição.")
        found, found_size, owner = matches[0]
        value = int(found, 16)
        if int(found_size) != size or value != address or not owner.startswith(object_name + "("):
            raise BridgeError(f"O endereço, tamanho ou módulo de {name} não corresponde ao firmware validado.")
        if not 0x20000000 <= value < value + size <= 0x20002000:
            raise BridgeError(f"{name} está fora da faixa de SRAM do STM32G031.")
        return value

    sample = symbol("sample", SNAPSHOT_SIZE, SAMPLE_ADDRESS, "imu.o")
    tick = symbol("tick_ms", 4, TICK_ADDRESS, "board.o")
    return FirmwareLayout(image, digest, sample, tick)


def decode_quaternion(packed: tuple[int, int, int]) -> list[float]:
    """ST SFLP stores binary16 xyz; w is reconstructed nonnegative.

    0000/0000/0000 is the firmware's unavailable marker. 8000/0000/0000
    (IEEE negative zero) is a valid identity rotation, not the marker.
    """
    if not any(packed):
        raise BridgeError("O quaternion indica que a IMU ainda não está pronta.")
    xyz = struct.unpack("<3e", struct.pack("<3H", *packed))
    if not all(math.isfinite(value) for value in xyz):
        raise BridgeError("O quaternion contém NaN ou valor infinito.")
    squared = sum(value * value for value in xyz)
    if squared > 1.02:
        raise BridgeError("O quaternion está fora da faixa válida do SFLP.")
    values = [*xyz, math.sqrt(max(0.0, 1.0 - squared))]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def empty_frame(mode: str, status: str, message: str) -> dict[str, Any]:
    return {
        "type": "imu", "service": "microduck-imu-viewer", "mode": mode, "status": status,
        "connected": False, "live": False, "quaternion_xyzw": None,
        "accel_g": None, "gyro_dps": None, "sample_count": None,
        "gyro_count": None, "accel_count": None, "ready": 0,
        "configured": 0, "who_am_i": None, "error": None,
        "errors": {key: None for key in ("imu", "spi", "fifo", "quaternion", "recovery")},
        "voltage_mv": None, "age_ms": None, "hz": 0.0,
        "coherence": "best_effort", "message": message,
        "timestamp_ms": int(time.time() * 1000),
    }


def decode_snapshot(raw: bytes, tick_ms: int, *, voltage_mv: int | None = None,
                    coherence: str = "best_effort") -> dict[str, Any]:
    if len(raw) != SNAPSHOT_SIZE:
        raise BridgeError(f"Tamanho de snapshot inválido: {len(raw)}; esperado {SNAPSHOT_SIZE}.")
    ready, who_am_i, configured, error = raw[:4]
    gyro = struct.unpack_from("<3h", raw, 4)
    accel = struct.unpack_from("<3h", raw, 10)
    packed = struct.unpack_from("<3H", raw, 16)
    sample_count, gyro_count, accel_count, last_gyro, last_quat, spi, fifo, invalid, recovery = struct.unpack_from("<9I", raw, 24)
    gyro_age = (tick_ms - last_gyro) & 0xFFFFFFFF
    quat_age = (tick_ms - last_quat) & 0xFFFFFFFF
    # A modular difference in the upper half of uint32 means the captured
    # sensor timestamp is ahead of tick, not that this sample is 49 days old.
    # Normal timer wrap (e.g. last=0xfffffff8, tick=3) still yields +11 ms.
    inconsistent_time = gyro_age >= 0x80000000 or quat_age >= 0x80000000
    age = None if inconsistent_time else max(gyro_age, quat_age)
    frame = empty_frame("live", "stale", "Aguardando amostra válida da IMU.")
    frame.update({
        "connected": True, "ready": ready, "who_am_i": who_am_i,
        "configured": configured, "error": error,
        "sample_count": sample_count, "gyro_count": gyro_count, "accel_count": accel_count,
        "errors": {"imu": error, "spi": spi, "fifo": fifo, "quaternion": invalid, "recovery": recovery},
        "age_ms": age, "voltage_mv": voltage_mv, "coherence": coherence,
        "tick_ms": tick_ms, "last_gyro_ms": last_gyro, "last_quat_ms": last_quat,
        "raw_accel": list(accel), "raw_gyro": list(gyro), "quat_fp16": list(packed),
    })
    if inconsistent_time:
        frame.update(coherence="inconsistent", message="Os timestamps do snapshot são inconsistentes; orientação pausada até uma nova leitura.")
    elif who_am_i != 0x70 or ready not in (0, 1) or configured not in (0, 1):
        frame.update(status="error", message="Identificador ou estado da IMU inválido; exibição da orientação interrompida.")
    elif error:
        frame.update(status="error", message=f"A IMU informou o código de erro {error}.")
    elif not ready or not configured or not sample_count:
        frame["message"] = "A IMU ainda não está pronta; aguardando inicialização e amostras válidas."
    elif age >= SENSOR_STALE_MS:
        frame["message"] = f"A amostra do sensor expirou ({age} ms); orientação pausada."
    else:
        try:
            quaternion = decode_quaternion(packed)
        except BridgeError as exc:
            frame.update(status="error", message=str(exc))
        else:
            frame.update(
                status="live", live=True, quaternion_xyzw=quaternion,
                accel_g=[value * 0.000122 for value in accel],
                gyro_dps=[value * 0.0175 for value in gyro],
                message="Lendo a placa real; a orientação acompanhará seus movimentos.",
            )
    return frame


class FreshnessTracker:
    """Detect a frozen CPU even if both RAM timestamps freeze together."""
    def __init__(self) -> None:
        self.count: int | None = None
        self.changed_at: float | None = None

    def apply(self, frame: dict[str, Any], now: float) -> dict[str, Any]:
        if frame["sample_count"] != self.count:
            self.count = frame["sample_count"]
            self.changed_at = now
        elif self.changed_at is not None and (now - self.changed_at) * 1000 >= HOST_STALE_MS:
            frame.update(status="stale", live=False, quaternion_xyzw=None, accel_g=None,
                         gyro_dps=None, message="O contador de amostras parou de avançar; orientação pausada.")
        return frame


class HardwareStatus(ct.Structure):
    _fields_ = [("VTarget", ct.c_uint16)] + [(name, ct.c_uint8) for name in ("tck", "tdi", "tdo", "tms", "tres", "trst")]


class JLinkReader:
    def __init__(self, layout: FirmwareLayout, dll_path: Path,
                 serial: int, resume: bool = False) -> None:
        self.layout, self.dll_path, self.serial, self.resume = layout, dll_path, serial, resume
        self.lib: Any = None
        self.opened = False
        self.dll_directory: Any = None
        self.voltage_mv: int | None = None
        self.callback: Any = None

    def command(self, command: str) -> None:
        error = ct.create_string_buffer(1024)
        rc = self.lib.JLINKARM_ExecCommand(command.encode("ascii"), error, len(error))
        if rc < 0 or error.value:
            raise BridgeError(f"Falha ao configurar o J-Link com {command}: {rc} {error.value.decode(errors='replace')}")

    def connect(self) -> None:
        self.dll_path, self.serial = validate_probe_settings(self.dll_path, self.serial)
        if os.name != "nt" or ct.sizeof(ct.c_void_p) != 8:
            raise BridgeError("O modo em tempo real requer Python de 64 bits no Windows e o driver local do J-Link.")
        self.dll_directory = os.add_dll_directory(str(self.dll_path.parent))
        self.lib = ct.CDLL(str(self.dll_path))
        callback_type = ct.CFUNCTYPE(None, ct.c_char_p)
        self.callback = callback_type(lambda msg: LOGGER.info("J-Link: %s", msg.decode(errors="replace")) if msg else None)
        declarations = {
            "ExecCommand": ([ct.c_char_p, ct.POINTER(ct.c_char), ct.c_int], ct.c_int),
            "EMU_SelectByUSBSN": ([ct.c_uint32], ct.c_int),
            "OpenEx": ([callback_type, callback_type], ct.c_char_p),
            "GetHWStatus": ([ct.POINTER(HardwareStatus)], ct.c_int),
            "TIF_Select": ([ct.c_int], ct.c_int), "SetSpeed": ([ct.c_uint32], None),
            "Connect": ([], ct.c_int), "IsConnected": ([], ct.c_int),
            "IsHalted": ([], ct.c_int), "Go": ([], None), "Close": ([], None),
            "ReadMemEx": ([ct.c_uint32, ct.c_uint32, ct.c_void_p, ct.c_uint32], ct.c_int),
        }
        for name, (args, result) in declarations.items():
            method = getattr(self.lib, "JLINKARM_" + name)
            method.argtypes, method.restype = args, result
        for command in ("DisableAutoUpdateFW", "SuppressInfoUpdateFW", "SuppressGUI = 1",
                        "SetRestartOnClose = 0"):
            self.command(command)
        if self.lib.JLINKARM_EMU_SelectByUSBSN(self.serial) < 0:
            raise BridgeError("J-Link especificado não encontrado; confira o USB e feche a sessão de depuração do Keil.")
        error = self.lib.JLINKARM_OpenEx(self.callback, self.callback)
        if error:
            raise BridgeError("Falha ao abrir o J-Link; feche a sessão de depuração do Keil e outros utilitários de sonda. " + error.decode(errors="replace"))
        self.opened = True
        # SDK Close defaults to a Go-equivalent resume. Configure before Open
        # (so unsupported options fail before acquiring a probe) and repeat
        # after Open in case it restored session defaults. This also protects
        # cleanup when subsequent connection/firmware verification fails.
        # https://kb.segger.com/J-Link_Command_Strings#SetRestartOnClose
        self.command("SetRestartOnClose = 0")
        self.read_voltage()
        for command in ("DisableFlashDL", "DisableFlashBPs", "InhibitConnectRetries = 1"):
            self.command(command)
        if self.lib.JLINKARM_TIF_Select(1) != 0:
            raise BridgeError("Não foi possível selecionar a interface SWD.")
        self.lib.JLINKARM_SetSpeed(100)
        self.command("Device = STM32G031F8")
        # Apply after device selection, before target connect. Firmware
        # verification happens later and cannot undo SDK RAM initialization.
        # Both settings are mandatory: command() aborts on rejection.
        # https://kb.segger.com/J-Link_Command_Strings#SetInitWorkRAMOnConnect
        self.command("SetInitWorkRAMOnConnect = 0")
        self.command("SetRestartOnClose = 0")
        connected = self.lib.JLINKARM_IsConnected()
        if connected < 0:
            raise BridgeError("Não foi possível ler o estado da conexão com o alvo.")
        if connected == 0 and self.lib.JLINKARM_Connect() < 0:
            raise BridgeError("Falha na conexão SWD; confira os fios SWDIO, SWCLK, GND e VTref.")
        if self.lib.JLINKARM_IsConnected() != 1:
            raise BridgeError("O J-Link não está conectado ao chip alvo.")
        # Read from the actual target; this never programs the supplied image.
        self.command("InvalidateCache")
        actual = self.read(0x08000000, len(self.layout.image))
        if actual != self.layout.image:
            raise BridgeError("O firmware da placa não corresponde ao arquivo validado; a leitura da RAM e a retomada da execução foram interrompidas.")
        halted = self.lib.JLINKARM_IsHalted()
        if halted not in (0, 1):
            raise BridgeError("Não foi possível ler o estado de execução da CPU; nenhuma tentativa de retomada foi feita.")
        if halted == 1:
            if not self.resume:
                raise BridgeError("A CPU alvo está pausada. O firmware foi validado; para retomar a execução, defina resume: true na configuração da IMU e reinicie o serviço.")
            self.lib.JLINKARM_Go()
            if self.lib.JLINKARM_IsHalted() != 0:
                raise BridgeError("Falha ao retomar a execução; confira se o Keil deixou algum breakpoint ativo.")

    def read_voltage(self) -> int:
        status = HardwareStatus()
        if self.lib.JLINKARM_GetHWStatus(ct.byref(status)) != 0:
            raise BridgeError("Não foi possível ler a tensão de referência da sonda; a conexão pode ter sido interrompida.")
        self.voltage_mv = int(status.VTarget)
        if not 3000 <= self.voltage_mv <= 3500:
            raise BridgeError(f"A tensão de referência do alvo é {self.voltage_mv} mV, fora da faixa validada de 3,3 V.")
        return self.voltage_mv

    def read(self, address: int, size: int) -> bytes:
        if address < 0 or size <= 0 or address + size > 0x100000000:
            raise BridgeError("Endereço ou tamanho da leitura fora da faixa válida.")
        # SEGGER UM08002, JLINKARM_ReadMemEx: AccessWidth=4 forces U32
        # accesses, 1 forces U8; NumBytes remains a byte count. Use aligned
        # words so an updating 32-bit tick/counter is not assembled from four
        # separate byte reads. This does NOT make the entire snapshot atomic.
        width = 4 if address % 4 == 0 and size % 4 == 0 else 1
        buf = (ct.c_uint32 * (size // 4))() if width == 4 else (ct.c_uint8 * size)()
        count = self.lib.JLINKARM_ReadMemEx(address, size, buf, width)
        if count != size:
            raise BridgeError(f"Falha na leitura de 0x{address:08X}: {count}/{size} bytes. Confira os fios e reinicie a conexão.")
        return bytes(buf)

    def snapshot(self) -> dict[str, Any]:
        if self.lib.JLINKARM_IsHalted() != 0:
            raise BridgeError("A CPU alvo está pausada; não foi retomada automaticamente e a exibição da orientação foi interrompida.")
        # No explicit halt per frame. Equal bracketing counters improve detection
        # of torn reads, but are not a seqlock: telemetry explicitly says so.
        return bracketed_snapshot(self.read, self.layout, self.voltage_mv)

    def close(self) -> None:
        if self.opened:
            self.lib.JLINKARM_Close()
            self.opened = False
        if self.dll_directory is not None:
            self.dll_directory.close()
            self.dll_directory = None


def bracketed_snapshot(read, layout: FirmwareLayout, voltage_mv: int | None) -> dict[str, Any]:
    """Usa a mesma leitura de JLinkReader.snapshot: consulta o contador de amostras antes
    e depois do snapshot; valores iguais indicam que a leitura não foi interrompida."""
    address = layout.sample_address
    for attempt in range(2):
        before = struct.unpack("<I", read(address + 24, 4))[0]
        raw = read(address, SNAPSHOT_SIZE)
        tick = struct.unpack("<I", read(layout.tick_address, 4))[0]
        after = struct.unpack("<I", read(address + 24, 4))[0]
        inner = struct.unpack_from("<I", raw, 24)[0]
        coherence = "counter_stable" if before == inner == after else "best_effort"
        frame = decode_snapshot(raw, tick, voltage_mv=voltage_mv, coherence=coherence)
        frame["read_attempts"] = attempt + 1
        if frame["coherence"] != "inconsistent":
            break
    return frame


class SwdReader:
    """Observação via pyOCD para sondas ST-Link / CMSIS-DAP (DAPLink). J-Link deve
    usar --imu-jlink.

    Não grava firmware nem RAM, não reinicia nem pausa a CPU: connect_mode=attach,
    resume_on_disconnect=False (sem retomada implícita ao desconectar) e no_config=True
    (não carrega pyocd.yaml nem scripts do diretório atual). target_override=cortex_m
    conecta usando o Cortex-M genérico e lê apenas a memória, sem pacote de chip nem
    algoritmo de Flash. Como em JLinkReader, compara byte a byte a Flash com o HEX antes
    de ler a RAM.

    Isso não significa impacto nulo no alvo: attach ainda grava registradores de
    depuração (DHCSR.C_DEBUGEN, DEMCR.TRCENA e ativações FPB/DWT). C_DEBUGEN permanece
    ativo após desconectar; nesse intervalo, uma instrução BKPT do firmware pausa a CPU
    em vez de gerar HardFault. Testes com ST-LINK/V2 a 100 kHz não reiniciaram a placa
    durante conexões contínuas.

    O pyOCD pode alimentar J-Link com 5 V pelo pino 19 (jlink.power), atualizar o
    firmware da sonda sem aviso e executar Go ao fechar. Como isso contorna as proteções
    de JLinkReader, sondas J-Link são recusadas aqui.
    """

    def __init__(self, layout: FirmwareLayout, probe_id: str | None = None, resume: bool = False) -> None:
        self.layout, self.probe_id, self.resume = layout, probe_id, resume
        self.session: Any = None
        self.target: Any = None
        self.halted_state: Any = None
        self.voltage_mv: int | None = None
        self.probe_name: str | None = None
        self.probe_uid: str | None = None

    @staticmethod
    def options() -> dict[str, Any]:
        return {"target_override": "cortex_m", "connect_mode": "attach", "frequency": SWD_FREQUENCY_HZ,
                "resume_on_disconnect": False, "auto_unlock": False, "no_config": True}

    def choose_probe(self, probes: list[Any]) -> Any:
        def is_jlink(p: Any) -> bool:
            return type(p).__name__ == "JLinkProbe"
        found = "; ".join(f"{p.description} {p.unique_id}" for p in probes)
        jlink_hint = "Para J-Link, use --imu-jlink (DLL oficial SEGGER com proteções contra alimentação, atualização de firmware e retomada implícita da execução)."
        if not probes:
            raise BridgeError("Nenhuma sonda encontrada (ST-Link / DAPLink); confira USB e drivers, "
                              "e feche programas que ocupem a sonda, como Keil ou CubeProgrammer.")
        if self.probe_id is None or self.probe_id == "auto":
            usable = [p for p in probes if not is_jlink(p)]
            if not usable:
                raise BridgeError("Somente um J-Link foi encontrado. " + jlink_hint)
            if len(usable) > 1:
                raise BridgeError(f"Há {len(usable)} sondas conectadas; selecione uma com --imu-swd <UID>: {found}")
            return usable[0]
        matches = [p for p in probes if p.unique_id == self.probe_id]
        if not matches:
            raise BridgeError(f"Sonda com UID {self.probe_id} não encontrada; sondas conectadas: {found}")
        if is_jlink(matches[0]):
            raise BridgeError("A sonda selecionada é um J-Link. " + jlink_hint)
        return matches[0]

    def connect(self) -> None:
        try:
            from pyocd.core.helpers import ConnectHelper
            from pyocd.core.session import Session
            from pyocd.core.target import Target
        except ImportError as exc:
            raise BridgeError("O modo SWD requer pyOCD: pip install pyocd") from exc
        self.halted_state = Target.State.HALTED
        chosen = self.choose_probe(list(ConnectHelper.get_all_connected_probes(blocking=False)))
        self.probe_name, self.probe_uid = chosen.description, chosen.unique_id
        LOGGER.info("Sonda SWD: %s %s (%s)", self.probe_name, self.probe_uid, type(chosen).__name__)

        # Etapa 1: abre somente a sonda, sem interagir com o chip, e verifica a tensão do alvo.
        probe_only = Session(chosen, options=self.options())
        try:
            probe_only.open(init_board=False)
        except Exception as exc:
            self.close_session(probe_only)
            raise BridgeError(f"Falha ao abrir a sonda ({type(exc).__name__}: {exc}): talvez esteja ocupada pelo Keil ou "
                              "CubeProgrammer, ou o firmware do ST-Link esteja antigo (atualize pelo CubeProgrammer).") from exc
        try:
            self.check_voltage(probe_only.probe)
        finally:
            self.close_session(probe_only)

        # Etapa 2: conecta ao chip em modo attach.
        self.session = Session(chosen, options=self.options())
        try:
            self.session.open()
        except Exception as exc:
            raise BridgeError(f"Falha ao conectar ao chip via SWD ({type(exc).__name__}: {exc}): "
                              "confira os fios SWDIO, SWCLK, GND e VTref e a alimentação da placa.") from exc
        self.target = self.session.target
        # Etapa 3: lê a Flash da placa para comparação; nunca grava nela.
        actual = self.read(0x08000000, len(self.layout.image))
        if actual != self.layout.image:
            raise BridgeError("O firmware da placa não corresponde ao arquivo validado; a leitura da RAM e a retomada foram interrompidas.")
        if self.is_halted():
            if not self.resume:
                raise BridgeError("A CPU alvo está pausada. O firmware foi validado; para retomar, encerre a depuração do Keil e reinicie a alimentação.")
            try:
                self.target.resume()
            except Exception as exc:
                raise BridgeError(f"Falha ao retomar a execução ({type(exc).__name__}: {exc}).") from exc
            if self.is_halted():
                raise BridgeError("Falha ao retomar a execução; confira se o Keil deixou algum breakpoint ativo.")

    def check_voltage(self, probe: Any) -> int | None:
        # No pyOCD, somente ST-Link mede a tensão do alvo (interface privada _link).
        # Sem essa interface (DAPLink), não exibe a tensão nem bloqueia. Se a interface
        # existir mas falhar, trata como erro de conexão.
        link = getattr(probe, "_link", None)
        getter = getattr(link, "get_target_voltage", None)
        if getter is None:
            self.voltage_mv = None
            return None
        try:
            getter()
            volts = link.target_voltage
        except Exception as exc:
            raise BridgeError(f"Falha ao ler a tensão do alvo ({type(exc).__name__}: {exc}); a sonda pode ter desconectado.") from exc
        if not isinstance(volts, (int, float)) or not math.isfinite(volts):
            raise BridgeError("Não foi possível ler a tensão do alvo; confira se J3.6 está conectado ao VTref/TVCC da sonda.")
        self.voltage_mv = int(round(volts * 1000))
        if self.voltage_mv < 500:
            raise BridgeError(f"A tensão do alvo é de apenas {self.voltage_mv} mV: J3.6 pode não estar ligado ao VTref/TVCC ou a placa pode estar desligada.")
        if not 3000 <= self.voltage_mv <= 3500:
            raise BridgeError(f"A tensão de referência do alvo é {self.voltage_mv} mV, fora da faixa validada de 3,3 V.")
        return self.voltage_mv

    def read_voltage(self) -> int | None:
        return self.check_voltage(getattr(self.session, "probe", None))

    def is_halted(self) -> bool:
        try:
            return self.target.get_state() == self.halted_state
        except Exception as exc:
            raise BridgeError(f"Falha ao ler o estado de execução da CPU ({type(exc).__name__}: {exc}): "
                              "a placa pode estar sem alimentação ou os fios SWD podem estar soltos.") from exc

    def read(self, address: int, size: int) -> bytes:
        if address < 0 or size <= 0 or address + size > 0x100000000:
            raise BridgeError("Endereço ou tamanho da leitura fora da faixa válida.")
        try:
            # Lê palavras de 32 bits alinhadas para não reconstruir um contador em
            # atualização a partir de quatro leituras separadas de bytes.
            if address % 4 == 0 and size % 4 == 0:
                words = self.target.read_memory_block32(address, size // 4)
                data = struct.pack(f"<{len(words)}I", *words)
            else:
                data = bytes(self.target.read_memory_block8(address, size))
        except Exception as exc:
            raise BridgeError(f"Falha na leitura de 0x{address:08X} ({type(exc).__name__}: {exc}). "
                              "Confira os fios e reinicie a conexão.") from exc
        if len(data) != size:
            raise BridgeError(f"Falha na leitura de 0x{address:08X}: {len(data)}/{size} bytes.")
        return data

    def snapshot(self) -> dict[str, Any]:
        if self.is_halted():
            raise BridgeError("A CPU alvo está pausada; não foi retomada automaticamente e a exibição da orientação foi interrompida.")
        return bracketed_snapshot(self.read, self.layout, self.voltage_mv)

    @staticmethod
    def close_session(session: Any) -> None:
        try:
            session.close()
        except Exception as exc:
            LOGGER.warning("Erro ao fechar a conexão da sonda: %s: %s", type(exc).__name__, exc)
        # Se a abertura falhar parcialmente, session.close() pode considerar que a
        # sonda não foi aberta, embora o USB esteja ocupado; tenta fechá-la novamente.
        probe = getattr(session, "probe", None)
        if probe is not None and getattr(probe, "is_open", False):
            try:
                probe.close()
            except Exception as exc:
                LOGGER.warning("Erro ao fechar o USB da sonda: %s: %s", type(exc).__name__, exc)

    def close(self) -> None:
        session, self.session, self.target = self.session, None, None
        if session is not None:
            self.close_session(session)


class BridgeService:
    def __init__(self, *, demo: bool = False, resume: bool = False,
                 firmware: Path = DEFAULT_FIRMWARE, map_file: Path | None = DEFAULT_MAP,
                 dll_path: Path | None = None, serial: int | None = None,
                 hz: float = 20.0, connect_attempts: int = 3,
                 backend: str = "jlink", probe_id: str | None = None) -> None:
        if backend not in ("jlink", "swd"):
            raise BridgeError(f"Backend de sonda desconhecido: {backend}")
        if not demo and backend == "jlink":
            dll_path, serial = validate_probe_settings(dll_path, serial)
        self.demo, self.resume, self.backend, self.probe_id = demo, resume, backend, probe_id
        self.firmware, self.map_file, self.dll_path = firmware, map_file, dll_path
        self.serial, self.hz, self.connect_attempts = serial, max(1.0, min(hz, 20.0)), connect_attempts
        self.lock = threading.Lock()
        self.lifecycle_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_publish = time.monotonic()
        connecting = "Conectando ao J-Link e verificando o firmware." if backend == "jlink" else "Conectando à sonda (pyOCD) e verificando o firmware."
        self.frame = empty_frame("demo" if demo else "live", "disconnected", "Iniciando demonstração." if demo else connecting)

    def publish(self, frame: dict[str, Any]) -> None:
        frame["timestamp_ms"] = int(time.time() * 1000)
        frame.setdefault("backend", self.backend)  # Inclui o backend também durante a conexão para que a página não exiba J-Link incorretamente.
        with self.lock:
            self.frame = frame
            self.last_publish = time.monotonic()

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            result = dict(self.frame)
            elapsed_ms = (time.monotonic() - self.last_publish) * 1000
        if result["live"] and elapsed_ms >= HOST_STALE_MS:
            result.update(status="stale", live=False, quaternion_xyzw=None, accel_g=None,
                          gyro_dps=None, hz=0.0, message="O fluxo de dados expirou; orientação pausada.")
        return result

    def start(self) -> None:
        with self.lifecycle_lock:
            if self.thread is not None and self.thread.is_alive():
                raise BridgeError("Cada serviço permite somente uma thread de leitura da sonda.")
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="imu-probe-owner", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        with self.lifecycle_lock:
            self._stop_locked()

    def _stop_locked(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                raise BridgeError("A chamada da sonda ainda está sendo encerrada; não é possível iniciar uma segunda conexão. Tente novamente mais tarde.")

    def disconnect(self) -> None:
        self.stop()
        self.publish(empty_frame("demo" if self.demo else "live", "disconnected", "Conexão liberada; você pode voltar à depuração no Keil ou reiniciar o serviço para conectar novamente."))

    def reconnect(self) -> None:
        with self.lifecycle_lock:
            self._stop_locked()
            self.stop_event.clear()
            self.publish(empty_frame("demo" if self.demo else "live", "disconnected", "Reconectando."))
            self.thread = threading.Thread(target=self._run, name="imu-probe-owner", daemon=True)
            self.thread.start()

    def _run_demo(self) -> None:
        started = time.monotonic()
        while not self.stop_event.is_set():
            elapsed = time.monotonic() - started
            x, y, z = (math.sin(elapsed * factor) * amplitude for factor, amplitude in ((0.7, 0.23), (0.9, 0.3), (0.4, 0.25)))
            frame = empty_frame("demo", "live", "Dados de demonstração: nenhuma placa real conectada ou consultada.")
            frame.update(connected=False, live=True, ready=1, configured=1, error=0,
                         quaternion_xyzw=[x, y, z, math.sqrt(1 - x*x - y*y - z*z)],
                         accel_g=[0.0, 0.0, 1.0], gyro_dps=[0.0, 0.0, 0.0],
                         sample_count=int(elapsed * 120), gyro_count=int(elapsed * 120),
                         accel_count=int(elapsed * 120), age_ms=0, hz=self.hz, coherence="demo",
                         errors={key: 0 for key in ("imu", "spi", "fifo", "quaternion", "recovery")})
            self.publish(frame)
            self.stop_event.wait(1 / self.hz)

    def _run(self) -> None:
        if self.demo:
            self._run_demo()
            return
        reader: JLinkReader | SwdReader | None = None
        try:
            layout = validate_firmware_layout(self.firmware, self.map_file)
            for attempt in range(self.connect_attempts):
                reader = (SwdReader(layout, self.probe_id, self.resume) if self.backend == "swd"
                          else JLinkReader(layout, self.dll_path, self.serial, self.resume))
                try:
                    reader.connect()
                    break
                except Exception as exc:
                    reader.close()
                    if attempt + 1 >= self.connect_attempts:
                        raise
                    frame = empty_frame("live", "disconnected", f"Tentativa de conexão {attempt + 1}/{self.connect_attempts}: {exc}")
                    self.publish(frame)
                    if self.stop_event.wait(3):
                        return
            tracker = FreshnessTracker()
            previous: float | None = None
            smooth_hz = 0.0
            next_voltage_read = time.monotonic() + 2
            while not self.stop_event.is_set():
                started = time.monotonic()
                if started >= next_voltage_read:
                    reader.read_voltage()
                    next_voltage_read = started + 2
                frame = tracker.apply(reader.snapshot(), time.monotonic())
                now = time.monotonic()
                if previous is not None:
                    instant = 1.0 / max(0.0001, now - previous)
                    smooth_hz = instant if smooth_hz == 0 else smooth_hz * 0.8 + instant * 0.2
                previous = now
                frame.update(hz=round(smooth_hz, 1), firmware_sha256=layout.sha256,
                             sample_address=f"0x{layout.sample_address:08X}", backend=self.backend)
                if isinstance(reader, SwdReader):
                    frame.update(probe_name=reader.probe_name, probe_uid=reader.probe_uid)
                else:
                    frame.update(probe_serial=self.serial)
                self.publish(frame)
                self.stop_event.wait(max(0.0, 1 / self.hz - (time.monotonic() - started)))
        except Exception as exc:
            LOGGER.exception("IMU connection stopped")
            frame = empty_frame("live", "error", str(exc) + " Confira os fios e feche a sessão de depuração do Keil antes de reiniciar esta ferramenta.")
            self.publish(frame)
        finally:
            if reader is not None:
                reader.close()
