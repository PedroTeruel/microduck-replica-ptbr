#!/usr/bin/env python3
"""Read-only bench probe for the MD-IMU board (ID 200) on Feetech FT-SCS.

Install Tools/requirements.txt into a project-local venv first.
Example: python Tools/imu_probe.py --port COM6 --seconds 30 --csv Build/imu.csv
Use a USB single-wire half-duplex bus adapter; the log UART is a different port.
No torque, position, Flash, baud, or other write instructions are sent.

Register layout (firmware control table, per 总线协议.md):
  0..9     identity (ver major/minor, endian, model 0x4D44, ID 200, baud, level)
  56..70   15-byte fast block: gyro i16 x3 + SFLP quat x/y/z fp16 + counter +
           status bits + reserved(0)
  71..85   raw accel i16 x3, who_am_i, error, clock, watchdog, sample_count u32,
           user_marker
  90..185  96-byte diagnostic block (24 little-endian u32 words)
"""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
import struct
import time

DEVICE_ID = 200
MODEL_NUMBER = 0x4D44
BROADCAST_ID = 254
INST_PING = 0x01
INST_READ = 0x02
INST_SYNC_READ = 0x82

ADDR_FAST = 56      # gyro (6) + quaternion fp16 (6)
LEN_FAST = 12
ADDR_BLOCK = 56     # 15-byte fast block + extensions, 40 bytes through 95
LEN_BLOCK = 40
ADDR_DIAG = 90
LEN_DIAG = 96

DIAG_NAMES = (
    "gyro_count", "accel_count", "uptime_ms", "gyro_age_ms", "quat_age_ms",
    "spi_errors", "fifo_overflows", "invalid_quaternions", "recovery_count",
    "rx_overflows", "uart_errors", "checksum_errors", "malformed_packets",
    "receive_timeouts", "rx_packets", "tx_packets", "cancelled_replies",
    "reset_flags", "clock_hz", "tx_timeouts", "log_dropped",
    "diag_revision", "tx_busy_drops", "reserved",
)


def checksum(body: bytes) -> int:
    """~(sum of ID..last data byte) & 0xFF; header FF FF and CK excluded."""
    return (~sum(body)) & 0xFF


def packet(device_id: int, instruction: int, parameters: bytes = b"") -> bytes:
    length = len(parameters) + 2  # instruction byte + parameters + checksum
    body = bytes([device_id, length, instruction]) + parameters
    return b"\xff\xff" + body + bytes([checksum(body)])


class Bus:
    def __init__(self, serial_port, device_id: int = DEVICE_ID):
        self.port = serial_port
        self.device_id = device_id

    def request(self, instruction: int, parameters: bytes = b"",
                broadcast: bool = False, timeout: float = 0.15) -> bytes:
        self.port.reset_input_buffer()
        self.port.write(packet(BROADCAST_ID if broadcast else self.device_id,
                               instruction, parameters))
        self.port.flush()
        deadline = time.monotonic() + timeout
        pending = bytearray()
        while time.monotonic() < deadline:
            pending.extend(self.port.read(max(1, self.port.in_waiting)))
            while True:
                start = pending.find(b"\xff\xff")
                if start < 0:
                    # Keep one possible leading FF for the next chunk.
                    del pending[:-1]
                    break
                if start:
                    del pending[:start]
                if len(pending) < 6:
                    break
                device = pending[2]
                length = pending[3]
                if length < 2 or length > 132:
                    del pending[:2]
                    continue
                size = 4 + length
                if len(pending) < size:
                    break
                frame = bytes(pending[:size])
                del pending[:size]
                if checksum(frame[2:-1]) != frame[-1]:
                    continue
                error = frame[4]
                data = frame[5:-1]
                # Ignore other devices' status packets on the shared bus.
                if device != self.device_id:
                    continue
                if error:
                    raise RuntimeError(
                        f"device returned protocol error 0x{error:02x}")
                return data
        raise TimeoutError(
            "no valid ID 200 status packet; check bus adapter, baud, wiring "
            "and power")

    def read(self, address: int, count: int) -> bytes:
        data = self.request(INST_READ, bytes([address, count]))
        if len(data) != count:
            raise RuntimeError(f"expected {count} data bytes, got {len(data)}")
        return data

    def sync_read_alone(self, address: int, count: int) -> bytes:
        """Broadcast SYNC READ with ID 200 as the only list entry.

        The IMU must never be the FIRST entry of a multi-device sync read:
        Feetech servo firmware 3.46 starts its reply one byte time before our
        checksum bit cell in that position and corrupts it. Alone/last is
        perfectly reliable."""
        data = self.request(INST_SYNC_READ,
                            bytes([address, count, self.device_id]),
                            broadcast=True)
        if len(data) != count:
            raise RuntimeError(f"expected {count} data bytes, got {len(data)}")
        return data


def decode(block: bytes, diag: bytes) -> dict:
    """Decode the 40-byte 56..95 block and the 96-byte 90..185 diagnostic.

    Block layout (offsets within the 40-byte read):
      0..5   gyro i16 x3
      6..11  SFLP quaternion x/y/z IEEE fp16
      12     sample counter (u8, low byte)
      13     status bits: BIT0 not ready, BIT1 comm fail, BIT2 self-test fail,
             BIT3 reader too slow
      14     reserved (0)
      15..20 raw accel i16 x3
      21     WHO_AM_I
      22     IMU error code
      23     clock status
      24     watchdog enabled
      25..28 sample_count u32
      29     user_marker
    """
    if len(block) != LEN_BLOCK:
        raise ValueError(f"fast block must be {LEN_BLOCK} bytes")
    if len(diag) != LEN_DIAG:
        raise ValueError(f"diagnostic block must be {LEN_DIAG} bytes")
    gyro_raw = struct.unpack_from("<3h", block, 0)
    xyz = struct.unpack_from("<3e", block, 6)
    norm2 = sum(x * x for x in xyz)
    valid = all(math.isfinite(x) for x in xyz) and norm2 <= 1.02
    w = math.sqrt(max(0.0, 1.0 - norm2)) if valid else float("nan")
    if valid and norm2 > 1.0:
        xyz = tuple(x / math.sqrt(norm2) for x in xyz)
    status = block[13]
    result = dict(zip(DIAG_NAMES, struct.unpack_from("<24I", diag, 0)))
    result.update(
        sample_count=struct.unpack_from("<I", block, 25)[0],
        counter=block[12],
        ready=not (status & 0x01) and valid,
        comm_fail=bool(status & 0x02),
        self_test_fail=bool(status & 0x04),
        reader_too_slow=bool(status & 0x08),
        who_am_i=block[21], error=block[22], clock_status=block[23],
        watchdog=bool(block[24]), user_marker=block[29],
        gyro_x_dps=gyro_raw[0] * .0175,
        gyro_y_dps=gyro_raw[1] * .0175,
        gyro_z_dps=gyro_raw[2] * .0175,
        q_x=xyz[0], q_y=xyz[1], q_z=xyz[2], q_w=w)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="bus adapter COM port, e.g. COM6")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--hz", type=float, default=50)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--sync", action="store_true",
                        help="exercise SYNC READ with ID 200 alone in the list")
    args = parser.parse_args()
    if not (0 < args.hz <= 100 and args.seconds > 0):
        parser.error("require 0 < hz <= 100 and seconds > 0")
    try:
        import serial
    except ImportError:
        parser.error("pyserial is missing: python -m pip install -r Tools/requirements.txt")
    file = None
    good = faults = not_ready = repeated = 0
    previous = None
    try:
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            file = args.csv.open("w", newline="", encoding="utf-8-sig")
        writer = None
        with serial.Serial(args.port, 1000000, timeout=.01, write_timeout=.2) as port:
            bus = Bus(port)
            ident = bus.read(0, 5)
            model = int.from_bytes(ident[3:5], "little")
            if model != MODEL_NUMBER:
                raise RuntimeError(
                    f"unexpected model 0x{model:04X}; this tool targets the "
                    f"custom MD-IMU board (0x{MODEL_NUMBER:04X})")
            print(f"ID=200 model=0x{model:04X} firmware={ident[0]}.{ident[1]} "
                  f"endian={ident[2]} baud=1000000; read-only, no write commands")
            start = next_sample = next_report = time.monotonic()
            while time.monotonic() - start < args.seconds:
                try:
                    if args.sync:
                        fast = bus.sync_read_alone(ADDR_FAST, LEN_FAST)
                        # Sync read returns only the 12 fast bytes; pad a block
                        # by fetching the remaining pieces the normal way.
                        block = fast + bus.read(ADDR_FAST + LEN_FAST,
                                                LEN_BLOCK - LEN_FAST)
                    else:
                        block = bus.read(ADDR_BLOCK, LEN_BLOCK)
                    diag = bus.read(ADDR_DIAG, LEN_DIAG)
                    row = decode(block, diag)
                    row = {"host_seconds": time.monotonic() - start, **row}
                    good += 1
                    not_ready += not row["ready"]
                    repeated += previous == row["sample_count"]
                    previous = row["sample_count"]
                    if file:
                        if writer is None:
                            writer = csv.DictWriter(file, fieldnames=list(row))
                            writer.writeheader()
                        writer.writerow(row)
                    if time.monotonic() >= next_report:
                        print(json.dumps(row, ensure_ascii=False))
                        next_report = time.monotonic() + 1
                except (TimeoutError, RuntimeError, ValueError) as error:
                    faults += 1
                    print(f"communication error: {error}")
                next_sample += 1 / args.hz
                time.sleep(max(0, next_sample - time.monotonic()))
                if next_sample < time.monotonic() - 1:
                    next_sample = time.monotonic()
        print(f"reads={good} errors={faults} not_ready={not_ready} "
              f"repeated_sample_count={repeated}")
        return 0 if good and not faults and not not_ready else 1
    finally:
        if file:
            file.close()


if __name__ == "__main__":
    raise SystemExit(main())
