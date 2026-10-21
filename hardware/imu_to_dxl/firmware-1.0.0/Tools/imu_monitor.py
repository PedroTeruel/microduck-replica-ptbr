#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
imu_monitor.py - Microduck ID 200 IMU monitor over Feetech FT-SCS

Sends a broadcast Sync Read (instruction 0x82) for the 12-byte IMU fast block
at register address 56 at a fixed rate, decodes the FT-SCS status packet, and
prints gyro XYZ (dps) and the SFLP quaternion (x, y, z binary16; w recovered
by the host).  ID 200 is the sole ID in the list: on a shared bus the IMU
must never be the FIRST entry of a multi-device Sync Read (Feetech servo
firmware starts its reply early and collides); alone/last is reliable.

Examples:
  python imu_monitor.py                     # default bus port COM6, 50 Hz
  python imu_monitor.py --port COM6         # explicit port, 50 Hz, 1 Mbps
  python imu_monitor.py --plot              # live curves (needs matplotlib)
  python imu_monitor.py --csv imu_log.csv   # log every good sample
  python imu_monitor.py --seconds 10        # run for a fixed duration

Install deps with the SAME interpreter you run:
  python -m pip install pyserial
  python -m pip install matplotlib          # only needed for --plot
"""

import argparse
import math
import struct
import sys
import threading
import time
from collections import deque

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial is not installed. Run:  python -m pip install pyserial")

# --- FT-SCS protocol constants ---------------------------------------------

HEADER = b"\xff\xff"
BROADCAST_ID = 0xFE
INST_SYNC_READ = 0x82

IMU_ADDR = 56           # address of the fast 12-byte block
IMU_LEN = 12
GYRO_SCALE_DPS = 0.0175  # LSM6DSV16X +/-500 dps: 17.5 mdps per LSB


# --- Feetech FT-SCS framing ------------------------------------------------

def checksum(body):
    """~(sum of ID..last data byte) & 0xFF; FF FF header and CK excluded."""
    return (~sum(body)) & 0xFF


def ft_frame(device_id, instruction, parameters=b""):
    """Build FF FF ID LEN INST P... CK (LEN = 1 instruction + n params + 1)."""
    length = len(parameters) + 2
    body = bytes([device_id, length, instruction]) + parameters
    return HEADER + body + bytes([checksum(body)])


def build_sync_read(dev_id, addr=IMU_ADDR, count=IMU_LEN):
    """Broadcast FT-SCS Sync Read: addr(u8), count(u8), ID list."""
    return ft_frame(BROADCAST_ID, INST_SYNC_READ,
                    bytes([addr, count, dev_id]))


def parse_reply(buf, expected_id):
    """
    Parse one FT-SCS status packet out of buf.
    Returns:
        ("ok", error_byte, data_bytes, consumed_length)
        ("bad_ck", consumed_length)
        ("incomplete",)          # header seen but the frame is truncated
        ("resync", consumed)     # bogus length byte
        None                     # no FF FF header at all
    """
    k = buf.find(HEADER)
    if k < 0:
        return None
    p = buf[k:]
    if len(p) < 4:
        return ("incomplete",)
    length = p[3]
    if length < 2 or length > 132:
        return ("resync", k + 2)
    total = 4 + length
    if len(p) < total:
        return ("incomplete",)
    consumed = k + total
    if checksum(p[2:total - 1]) != p[total - 1]:
        return ("bad_ck", consumed)
    if p[2] != expected_id:
        return ("other", consumed)
    data = p[5:total - 1]
    return ("ok", p[4], bytes(data), consumed)


# --- sampler ---------------------------------------------------------------

class Monitor:
    def __init__(self, args):
        self.ser = serial.Serial(args.port, args.baud, timeout=0.005,
                                 write_timeout=0.5)
        self.req = build_sync_read(args.dev_id)
        self.expected_id = args.dev_id
        self.period = 1.0 / args.rate
        self.print_hz = args.print_hz

        self.lock = threading.Lock()
        win = int(args.rate * args.window)
        self.t0 = time.monotonic()
        self.ts = deque(maxlen=win)
        self.gyro = [deque(maxlen=win) for _ in range(3)]
        self.quat = [deque(maxlen=win) for _ in range(4)]
        self.latest = None  # (t, (gx,gy,gz), (qx,qy,qz,qw))

        self.n_ok = 0
        self.n_ck = 0
        self.n_to = 0
        self.n_err = 0

        self.running = True
        self._warned = False
        self._csv = None
        if args.csv:
            self._csv = open(args.csv, "w", newline="", encoding="utf-8")
            self._csv.write("t,gyro_x,gyro_y,gyro_z,qx,qy,qz,qw\n")

    def stop(self):
        self.running = False

    def close(self):
        try:
            self.ser.close()
        finally:
            if self._csv:
                self._csv.close()

    def snapshot(self):
        with self.lock:
            return (list(self.ts), [list(q) for q in self.gyro],
                    [list(q) for q in self.quat])

    def _decode(self, data):
        gx, gy, gz = struct.unpack("<3h", data[:6])
        qx, qy, qz = struct.unpack("<3e", data[6:12])
        gyro = (gx * GYRO_SCALE_DPS, gy * GYRO_SCALE_DPS, gz * GYRO_SCALE_DPS)
        if qx == 0.0 and qy == 0.0 and qz == 0.0:
            quat = None  # SFLP not ready yet
        else:
            w2 = 1.0 - qx * qx - qy * qy - qz * qz
            quat = (qx, qy, qz, math.sqrt(w2) if w2 > 0 else 0.0)
        return gyro, quat

    def _transaction(self):
        """Send one Sync Read and accumulate RX until a complete ID-matched
        status frame arrives. Tolerates adapter TX echo and split USB chunks
        via the same accumulate/resync strategy as imu_probe.py; a corrupted
        frame is counted but skipped instead of failing the whole poll."""
        try:
            self.ser.reset_input_buffer()
            self.ser.write(self.req)
            self.ser.flush()
        except serial.SerialException as e:
            print("\nserial error: %s" % e)
            self.stop()
            return None
        buf = bytearray()
        deadline = time.monotonic() + 0.03
        while time.monotonic() < deadline:
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                buf += chunk
            while True:
                r = parse_reply(bytes(buf), self.expected_id)
                if r is None or r[0] == "incomplete":
                    break
                if r[0] == "ok":
                    return r
                # bad_ck/resync/other: drop the consumed junk (e.g. the
                # adapter echoing our own broadcast request) and reparse.
                if r[0] == "bad_ck":
                    self.n_ck += 1
                buf = bytearray(buf[r[1]:])
        return None

    def run(self):
        next_send = time.monotonic()
        last_print = 0.0
        while self.running:
            now = time.monotonic()
            if now < next_send:
                time.sleep(min(next_send - now, 0.005))
                continue
            next_send += self.period
            if next_send < now - self.period:
                next_send = now + self.period

            r = self._transaction()

            if r is None:
                self.n_to += 1
            elif r[0] == "ok":
                _, err, data, _consumed = r
                if err != 0:
                    self.n_err += 1
                elif len(data) >= IMU_LEN:
                    gyro, quat = self._decode(data)
                    t = time.monotonic() - self.t0
                    with self.lock:
                        self.ts.append(t)
                        for i in range(3):
                            self.gyro[i].append(gyro[i])
                            self.quat[i].append(quat[i] if quat else float("nan"))
                        self.quat[3].append(quat[3] if quat else float("nan"))
                        self.latest = (t, gyro, quat)
                    self.n_ok += 1
                    if self._csv and quat:
                        self._csv.write(
                            "%.3f,%.4f,%.4f,%.4f,%.5f,%.5f,%.5f,%.5f\n"
                            % ((t,) + gyro + quat))
                        if self.n_ok % 25 == 0:
                            self._csv.flush()

            self._maybe_warn(now)
            if self.print_hz and now - last_print >= 1.0 / self.print_hz:
                last_print = now
                self._print_line()

    def _maybe_warn(self, now):
        if self._warned:
            return
        attempts = self.n_ok + self.n_ck + self.n_to
        if attempts >= 40 and self.n_ok == 0:
            self._warned = True
            print("\n[!] no reply after %.1f s. Check:" % (now - self.t0))
            print("    - port is correct and another master tool is closed")
            print("      (one master only on the bus)")
            print("    - device ID is still 200 (fixed in this firmware)")
            print("    - baud rate is 1000000 and wiring/power is OK\n")

    def _print_line(self):
        with self.lock:
            latest = self.latest
        if latest and latest[2]:
            t, g, q = latest
            sys.stdout.write(
                "\rt=%6.2fs ok=%-5d ck=%-3d to=%-4d | "
                "gyro %7.2f %7.2f %7.2f dps | q %6.3f %6.3f %6.3f %6.3f   "
                % (t, self.n_ok, self.n_ck, self.n_to, g[0], g[1], g[2],
                   q[0], q[1], q[2], q[3]))
        elif latest:
            t, g, _ = latest
            sys.stdout.write(
                "\rt=%6.2fs ok=%-5d ck=%-3d to=%-4d | "
                "gyro %7.2f %7.2f %7.2f dps | SFLP not ready   "
                % (t, self.n_ok, self.n_ck, self.n_to, g[0], g[1], g[2]))
        else:
            sys.stdout.write(
                "\rwarming up... ok=%d ck=%d to=%d"
                % (self.n_ok, self.n_ck, self.n_to))
        sys.stdout.flush()


# --- plotting --------------------------------------------------------------

def run_plot(mon):
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        from matplotlib.animation import FuncAnimation
    except ImportError:
        sys.exit("matplotlib is not installed. Run:  python -m pip install matplotlib")

    fig, (ax_g, ax_q) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    fig.suptitle("Microduck ID %d IMU - Sync Read @56 (FT-SCS)" % mon.expected_id)

    ax_g.set_ylabel("gyro [dps]")
    ax_q.set_ylabel("quaternion")
    ax_q.set_xlabel("time [s]")
    ax_g.grid(True, alpha=0.3)
    ax_q.grid(True, alpha=0.3)

    colors_g = ("#d62728", "#2ca02c", "#1f77b4")
    labels_g = ("gx", "gy", "gz")
    colors_q = ("#d62728", "#2ca02c", "#1f77b4", "#9467bd")
    labels_q = ("qx", "qy", "qz", "qw")

    # Fixed Line2D objects, only set_data() is called per frame.
    lines_g = [ax_g.plot([], [], color=c, label=l, lw=1.2)[0]
               for c, l in zip(colors_g, labels_g)]
    lines_q = [ax_q.plot([], [], color=c, label=l, lw=1.2)[0]
               for c, l in zip(colors_q, labels_q)]
    ax_g.legend(loc="upper right", ncol=3, fontsize=8)
    ax_q.legend(loc="upper right", ncol=4, fontsize=8)

    def update(_frame):
        ts, gyro, quat = mon.snapshot()
        if ts:
            for i, line in enumerate(lines_g):
                line.set_data(ts, gyro[i])
            for i, line in enumerate(lines_q):
                line.set_data(ts, quat[i])
            ax_g.relim()
            ax_g.autoscale_view()
            ax_q.relim()
            ax_q.autoscale_view()
        return lines_g + lines_q

    # Charts are a view; 10 fps refresh is plenty and stays stable.
    # The FuncAnimation object MUST stay referenced: without a binding it is
    # garbage-collected immediately and the window never redraws.
    anim = FuncAnimation(fig, update, interval=100, blit=False,
                         cache_frame_data=False)
    fig.tight_layout()
    plt.show()
    return anim


# --- main ------------------------------------------------------------------

def pick_port(port):
    if port:
        return port
    ports = list_ports.comports()
    if not ports:
        sys.exit("no serial port found. Plug in the bus adapter or pass --port.")
    if len(ports) == 1:
        print("using %s (%s)" % (ports[0].device, ports[0].description))
        return ports[0].device
    print("several serial ports found; choose one with --port:")
    for p in ports:
        print("  %-8s %s" % (p.device, p.description))
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Microduck ID 200 IMU monitor")
    ap.add_argument("--port", default="COM6",
                    help="bus adapter serial port (default COM6; "
                         "COM5 is the DAP-Link log UART)")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--id", type=int, default=200, dest="dev_id")
    ap.add_argument("--rate", type=int, default=50, help="sync read Hz")
    ap.add_argument("--window", type=float, default=10.0,
                    help="plot/history window in seconds")
    ap.add_argument("--plot", action="store_true", help="show live curves")
    ap.add_argument("--csv", help="write good samples to this CSV file")
    ap.add_argument("--seconds", type=float, default=0.0,
                    help="stop after N seconds (0 = run until Ctrl+C)")
    ap.add_argument("--print-hz", type=float, default=10.0,
                    help="console refresh rate, 0 disables")
    args = ap.parse_args()
    args.port = pick_port(args.port)

    mon = Monitor(args)
    worker = threading.Thread(target=mon.run, daemon=True)
    worker.start()
    stop_at = time.monotonic() + args.seconds if args.seconds else None
    try:
        if args.plot:
            run_plot(mon)
        else:
            while mon.running:
                time.sleep(0.1)
                if stop_at and time.monotonic() >= stop_at:
                    break
    except KeyboardInterrupt:
        pass
    finally:
        mon.stop()
        worker.join(timeout=1.0)
        mon.close()
        if mon.print_hz:
            print("\nstopped: ok=%d ck_err=%d timeout=%d hw_err=%d"
                  % (mon.n_ok, mon.n_ck, mon.n_to, mon.n_err))


if __name__ == "__main__":
    main()
