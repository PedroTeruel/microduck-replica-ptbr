#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bus_monitor.py - one tool, one serial port, one Feetech FT-SCS bus:
Microduck IMU board (ID 200) + Feetech servos, all read with ONE broadcast
SYNC READ (instruction 0x82) of the shared 12-byte status block at address 56.

IMU block at 56:  gyro i16 x3 + quaternion x/y/z (fp16)
Servo block 56:  position, speed, load (6B), voltage, temperature, moving.

HARD-WON BUS RULE: ID 200 must NOT be the first ID in the SYNC READ list.
Feetech servo firmware (3.46) predicts the next slot and starts transmitting
~180 us early, which collides with the IMU's checksum byte when the IMU
speaks first.  Lists are therefore built as [servo IDs...] + [200]; the IMU
last (or alone) position is 100% reliable.

By default a gentle demo sweep is started on every detected servo (torque on,
goal alternates between --demo-lo and --demo-hi).  Goal updates use one
broadcast SYNC WRITE (0x83, addr 42, 2 bytes); servos that do not react fall
back to individual WRITE automatically.  Torque is switched off on exit.
Use --no-demo to just watch.

Examples:
  python bus_monitor.py --port COM6              # scan + dashboard + demo
  python bus_monitor.py --port COM6 --plot       # live curves
  python bus_monitor.py --port COM6 --no-demo    # watch only
  python bus_monitor.py --port COM6 --srv-id 2,3 # poll only these IDs
  python bus_monitor.py --port COM6 --srv-id 0   # IMU only
"""

import argparse
import math
import os
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

# Reuse the protocol code from the single-purpose tools in this folder.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imu_monitor import ft_frame, checksum  # noqa: E402

GYRO_SCALE_DPS = 0.0175

# Shared 12-byte status block polled from IMU and servos at address 56.
STS_POS = 56
STS_BLOCK_LEN = 12

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
INST_SYNC_READ = 0x82
INST_SYNC_WRITE = 0x83

REG_TORQUE_EN = 40
REG_ACC = 41
REG_GOAL_POS = 42
REG_GOAL_SPEED = 46
REG_MODE = 33


def pick_port(port):
    if port:
        return port
    ports = list_ports.comports()
    if not ports:
        sys.exit("no serial port found; plug in the bus adapter or use --port")
    if len(ports) == 1:
        print("using %s (%s)" % (ports[0].device, ports[0].description))
        return ports[0].device
    print("several serial ports; choose one with --port (bus is usually COM6,")
    print("COM5 is the DAP-LINK debug UART):")
    for p in ports:
        print("  %-8s %s" % (p.device, p.description))
    sys.exit(1)


class StreamParser:
    """Incremental parser for FT-SCS status frames on one RX stream.

    Frame: FF FF ID LEN ERR DATA... CK; total length 4+LEN.  DATA may
    contain FF FF, so framing is driven by the LENGTH byte and a frame is
    only accepted when the checksum verifies."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            i = self.buf.find(b"\xff\xff")
            if i < 0:
                # Keep one trailing FF: it may start a frame in next chunk.
                del self.buf[:-1]
                return out
            if i:
                del self.buf[:i]
            if len(self.buf) < 4:
                return out
            ln = self.buf[3]
            if ln < 2 or ln > 132:
                del self.buf[:2]  # false header / garbage length: resync
                continue
            need = 4 + ln
            if len(self.buf) < need:
                return out
            frame = bytes(self.buf[:need])
            del self.buf[:need]
            if checksum(frame[2:-1]) != frame[-1]:
                continue
            # tuple: (device ID, error byte, data bytes)
            out.append((frame[2], frame[4], frame[5:-1]))


def decode_servo_block(b):
    """Decode the 12-byte STS status block (addr 56..67)."""
    pos = b[0] | (b[1] << 8)
    spd = b[2] | (b[3] << 8)
    load = b[4] | (b[5] << 8)
    return {
        "pos": pos, "deg": pos / (4096.0 / 360.0),
        "spd": (spd & 0x7FFF) * (-1 if spd & 0x8000 else 1),
        "load": (load & 0x3FF) * (-1 if load & 0x8000 else 1),
        "volt": b[6] / 10.0, "temp": b[7], "moving": b[10],
    }


POS_PER_DEG = 4096.0 / 360.0


class ServoState:
    def __init__(self, sid, window):
        self.id = sid
        self.ok = 0
        self.req = 0
        self.latest = None
        self.mode = None
        self.in_demo = False
        # SYNC WRITE capability is assumed and disproved by observation:
        # broadcast writes carry no status reply, so support is detected by
        # watching whether the servo actually starts moving after one.
        self.sync_write_ok = True
        self.probe_from = None      # position when the probe toggle started
        self.probe_target = None
        self.probe_deadline = 0.0
        win = max(8, int(50 * window))
        self.ts = deque(maxlen=win)
        self.pos = deque(maxlen=win)
        self.load = deque(maxlen=win)


class BusMonitor:
    def __init__(self, args, srv_ids):
        self.ser = serial.Serial(args.port, args.baud, timeout=0.005,
                                 write_timeout=0.5)
        self.imu_id = args.imu_id if args.imu_id else None
        self.imu_period = 1.0 / args.imu_rate
        self.window = args.window
        self.demo = (not args.no_demo) and bool(srv_ids)
        self.demo_lo, self.demo_hi = args.demo_lo, args.demo_hi
        self.demo_speed, self.demo_period = args.demo_speed, args.demo_period

        self.servos = {sid: ServoState(sid, args.window) for sid in srv_ids}
        self.torque_ids = []  # servos whose torque we switched on (-> off)
        self.t0 = time.monotonic()

        self.lock = threading.Lock()
        win_i = int(args.imu_rate * args.window)
        self.imu_ts = deque(maxlen=win_i)
        self.gyro = [deque(maxlen=win_i) for _ in range(3)]
        self.quat = [deque(maxlen=win_i) for _ in range(4)]
        self.imu_latest = None  # (gyro tuple, quat tuple or None)

        self.n_imu_req = self.n_imu_ok = 0
        self.running = True
        self.parser = StreamParser()
        # Servos that missed a SYNC WRITE; individual rewrites are issued by
        # the worker AFTER a sync poll fully settled (never mid-reply).
        self._fallback_goals = {}

    # -- low level -----------------------------------------------------------
    def _txrx(self, frame, matcher, wait=0.006):
        """Send one frame, drain/parse RX until a matching reply or timeout.

        Strictly one outstanding transaction: never start a new TX while a
        reply may still be inbound, otherwise the two collide on the
        half-duplex wire."""
        self.ser.write(frame)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            for pkt in self.parser.feed(self.ser.read(
                    self.ser.in_waiting or 1)):
                self._dispatch(pkt)
                if matcher(pkt):
                    return True
        return False

    def _sync_poll(self, wait=0.020):
        """One broadcast SYNC READ for addr 56/12 over all devices.

        List order is servo IDs first, IMU LAST (see module docstring)."""
        ids = sorted(self.servos)
        if self.imu_id is not None:
            ids.append(self.imu_id)
        if not ids:
            return
        # Start a clean transaction: late replies left over from the previous
        # poll must not satisfy this round's "seen" set, otherwise we would
        # return early and the next TX (e.g. a SYNC WRITE) could collide with
        # a status frame still arriving on the half-duplex wire.
        self.parser.buf.clear()
        self.ser.reset_input_buffer()
        params = bytes([STS_POS, STS_BLOCK_LEN]) + bytes(ids)
        for sv in self.servos.values():
            sv.req += 1
        self.n_imu_req += 1
        self.ser.write(ft_frame(254, INST_SYNC_READ, params))
        deadline = time.monotonic() + wait
        seen = set()
        while time.monotonic() < deadline:
            for pkt in self.parser.feed(self.ser.read(
                    self.ser.in_waiting or 1)):
                if pkt[0] in ids:
                    self._dispatch(pkt)
                    seen.add(pkt[0])
            if len(seen) >= len(ids):
                return

    def _dispatch(self, pkt):
        sid, error, data = pkt
        if sid == self.imu_id:
            self._on_imu(error, data)
        elif sid in self.servos:
            self._on_srv(sid, data)

    def _on_imu(self, error, data):
        if error or len(data) < 12:
            return
        gx, gy, gz = struct.unpack("<3h", data[:6])
        qx, qy, qz = struct.unpack("<3e", data[6:12])
        gyro = (gx * GYRO_SCALE_DPS, gy * GYRO_SCALE_DPS, gz * GYRO_SCALE_DPS)
        if qx == 0.0 and qy == 0.0 and qz == 0.0:
            quat = None
        else:
            w2 = 1.0 - qx * qx - qy * qy - qz * qz
            quat = (qx, qy, qz, math.sqrt(w2) if w2 > 0 else 0.0)
        t = time.monotonic() - self.t0
        with self.lock:
            self.imu_ts.append(t)
            for i in range(3):
                self.gyro[i].append(gyro[i])
            for i in range(3):
                self.quat[i].append(quat[i] if quat else float("nan"))
            self.quat[3].append(quat[3] if quat else float("nan"))
            self.imu_latest = (gyro, quat)
        self.n_imu_ok += 1

    def _on_srv(self, sid, data):
        if len(data) < 11:
            return
        s = decode_servo_block(data)
        sv = self.servos[sid]
        t = time.monotonic() - self.t0
        with self.lock:
            sv.ts.append(t)
            sv.pos.append(s["deg"])
            sv.load.append(s["load"])
            sv.latest = s
        sv.ok += 1
        self._check_sync_write_probe(sv, s["pos"])

    # -- setup ---------------------------------------------------------------
    def scan(self):
        """PING 1..253; returns sorted servo IDs (everything but ID 200)."""
        print("扫描总线 1..253 ...")
        found = []
        for sid in range(1, 254):
            if self._ping(sid, wait=0.003):
                if sid == self.imu_id:
                    continue
                found.append(sid)
                print("  发现舵机 ID %d" % sid)
        if self.imu_id is not None:
            print("  IMU 板 ID %d%s" % (self.imu_id,
                  "（应答正常）" if self._ping(self.imu_id) else "（无应答!）"))
        print("共 %d 个舵机: %s" % (len(found), found))
        return found

    def _ping(self, sid, wait=0.003):
        return self._txrx(ft_frame(sid, INST_PING), wait=wait,
                          matcher=lambda p, s=sid: p[0] == s)

    def start_demo(self):
        """Torque on + first goal for every polled servo via individual
        writes; subsequent toggles use one broadcast SYNC WRITE.

        The mode register (33) is logged for reference only: e.g. the
        DH1901 reports mode=4 yet goal-position control works, so a hard
        gate on mode==0 would wrongly skip real servos."""
        for sv in self.servos.values():
            mode_b = self._read_reg(sv.id, REG_MODE, 1)
            sv.mode = mode_b[0] if mode_b else None
            self._w1(sv.id, REG_TORQUE_EN, 1)          # torque on
            self._w1(sv.id, REG_ACC, 30)               # acceleration
            self._w2(sv.id, REG_GOAL_SPEED,
                     self.demo_speed & 0x7FFF)         # speed
            self._w2(sv.id, REG_GOAL_POS, self.demo_lo)
            sv.in_demo = True
            self.torque_ids.append(sv.id)
            print("  舵机 %d: demo 开始（mode=%s, 目标 %d <-> %d, 速度 %d）"
                  % (sv.id, sv.mode, self.demo_lo, self.demo_hi,
                     self.demo_speed))

    def shutdown(self):
        """Switch torque off on every servo we enabled; close the port."""
        for sid in self.torque_ids:
            try:
                self._w1(sid, REG_TORQUE_EN, 0)
                print("舵机 %d 扭矩已关闭" % sid)
            except serial.SerialException:
                pass
        self.ser.close()

    def _read_reg(self, sid, addr, n, wait=0.005):
        """Read n bytes from one register; returns data bytes or None."""
        box = []

        def m(p, s=sid):
            if p[0] == s and p[1] == 0:
                box.append(p[2])
                return True
            return p[0] == s

        if self._txrx(ft_frame(sid, INST_READ, bytes((addr, n))),
                      matcher=m, wait=wait) and box:
            return box[0]
        return None

    def _w1(self, sid, addr, val):
        self._txrx(ft_frame(sid, INST_WRITE, bytes((addr, val))),
                   matcher=lambda p, s=sid: p[0] == s)

    def _w2(self, sid, addr, val):
        self._txrx(ft_frame(sid, INST_WRITE,
                            bytes((addr, val & 0xFF, (val >> 8) & 0xFF))),
                   matcher=lambda p, s=sid: p[0] == s)

    # -- demo / SYNC WRITE fallback ------------------------------------------
    def _sync_write_goals(self, targets):
        """One broadcast SYNC WRITE of goal position (addr 42, 2B each)."""
        params = bytearray([REG_GOAL_POS, 2])
        for sid, target in targets:
            params += bytes((sid, target & 0xFF, (target >> 8) & 0xFF))
        self.ser.write(ft_frame(254, INST_SYNC_WRITE, bytes(params)))

    def _check_sync_write_probe(self, sv, pos):
        """Watch the sweep after a SYNC WRITE: only motion TOWARD the new
        goal counts (residual travel from the previous goal must not give a
        false positive).  Broadcast writes return no status, so motion is
        the only capability signal."""
        if sv.probe_deadline == 0.0 or sv.probe_target is None:
            return
        toward = ((pos - sv.probe_from) if sv.probe_target > sv.probe_from
                  else (sv.probe_from - pos))
        if toward > 100:
            sv.probe_deadline = 0.0  # observed motion toward goal: it works
            return
        if time.monotonic() >= sv.probe_deadline:
            sv.sync_write_ok = False
            self._fallback_goals[sv.id] = sv.probe_target
            sv.probe_deadline = 0.0
            print("  舵机 %d 不支持 SYNC WRITE，已回退到逐写" % sv.id)

    def update_demo(self, target):
        sync, solo = [], []
        for sv in self.servos.values():
            if not sv.in_demo:
                continue
            start = sv.latest["pos"] if sv.latest else self.demo_lo
            if sv.sync_write_ok:
                sync.append((sv.id, target))
                sv.probe_from = start
                sv.probe_target = target
                sv.probe_deadline = time.monotonic() + 1.2
            else:
                solo.append((sv.id, target))
        if sync:
            self._sync_write_goals(sync)
        for sid, goal in solo:
            self._w2(sid, REG_GOAL_POS, goal)

    # -- worker ---------------------------------------------------------------
    def run(self):
        next_poll = time.monotonic()
        last_print = 0.0
        # The first homing swing (from the horn's power-on position to
        # demo-lo) can take longer than one period; wait it out so the SYNC
        # WRITE capability probe never starts mid-travel.
        first_demo = max(self.demo_period, 6.0) if self.demo else 0.0
        demo_next = time.monotonic() + first_demo
        while self.running:
            now = time.monotonic()
            try:
                if now >= next_poll:
                    self._sync_poll()
                    # Catch up if we fell behind (e.g. a slow USB poll or
                    # system jitter) so we never fire polls back-to-back.
                    while next_poll < time.monotonic():
                        next_poll += self.imu_period
                    # Sync poll fully settled: now safe to TX fallback goals.
                    if self._fallback_goals:
                        goals = self._fallback_goals
                        self._fallback_goals = {}
                        for sid, goal in goals.items():
                            self._w2(sid, REG_GOAL_POS, goal)

                if self.demo and now >= demo_next:
                    demo_next = now + self.demo_period
                    self.update_demo(self._demo_target(now))
            except serial.SerialException as e:
                print("\nserial error: %s" % e)
                self.running = False
                return

            if time.monotonic() - last_print >= 0.5:
                last_print = time.monotonic()
                self._print_line()
            sleep_for = min(next_poll - time.monotonic(),
                            demo_next - time.monotonic() if self.demo else 1.0)
            if sleep_for > 0:
                time.sleep(min(0.005, sleep_for))

    def _demo_target(self, now):
        k = int((now - self.t0) / self.demo_period)
        return self.demo_lo if k & 1 else self.demo_hi

    # -- display ---------------------------------------------------------------
    def _print_line(self):
        with self.lock:
            imu = self.imu_latest
            lines = ["t=%6.1f" % (time.monotonic() - self.t0)]
            if self.imu_id is not None:
                if imu:
                    g, q = imu
                    qs = ("q %6.3f %6.3f %6.3f w %6.3f" % q) if q \
                        else "q (SFLP w)"
                    lines.append("IMU %d/%d gyro %6.2f %6.2f %6.2f %s"
                                 % (self.n_imu_ok, self.n_imu_req,
                                    g[0], g[1], g[2], qs))
                else:
                    lines.append("IMU %d/%d: 无应答"
                                 % (self.n_imu_ok, self.n_imu_req))
            out = [" | ".join(lines)]
        for sv in self.servos.values():
            if sv.latest:
                s = sv.latest
                out.append("  [%d]%s 位置%4d(%5.1f°) 速度%+5d 扭矩%+4d "
                           "电压%4.1fV 温度%2d°C mv=%d [%d/%d]"
                           % (sv.id, " demo" if sv.in_demo else "     ",
                              s["pos"], s["deg"], s["spd"], s["load"],
                              s["volt"], s["temp"], s["moving"],
                              sv.ok, sv.req))
            else:
                out.append("  [%d]  无应答 [%d/%d]"
                           % (sv.id, sv.ok, sv.req))
        print("\n".join(out))

    def snapshot(self):
        with self.lock:
            return (list(self.imu_ts), [list(q) for q in self.gyro],
                    [list(q) for q in self.quat],
                    {sid: (list(sv.ts), list(sv.pos), list(sv.load))
                     for sid, sv in self.servos.items()})

    def stop(self):
        self.running = False


# --- plotting ---------------------------------------------------------------

def run_plot(mon):
    try:
        import matplotlib
        matplotlib.use("TkAgg")  # the blit loop below is Tk-specific
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("matplotlib/tkinter is not installed. Run:  "
                 "python -m pip install matplotlib")

    fig, axs = plt.subplots(2, 1, figsize=(9.5, 6.5), sharex=True)
    fig.suptitle("Microduck IMU id %s @ %.0f Hz SYNC READ @56 (FT-SCS)"
                 % (mon.imu_id, 1.0 / mon.imu_period))
    ax_g, ax_q = axs
    ax_g.set_ylabel("gyro [dps]")
    ax_q.set_ylabel("quaternion")
    ax_q.set_xlabel("time [s]")
    for ax in (ax_g, ax_q):
        ax.grid(True, alpha=0.3)

    # Fixed y-limits + a manual blit loop instead of FuncAnimation: a full
    # canvas redraw at 10 fps pins a whole core on this machine and the
    # window freezes.  Blitting repaints only the line artists on top of a
    # cached background (~2% CPU).  Cost: the y-ranges are static.
    ax_g.set_ylim(-260, 260)
    ax_q.set_ylim(-1.05, 1.05)
    for ax in (ax_g, ax_q):
        ax.set_xlim(0, mon.window)

    cg = ("#d62728", "#2ca02c", "#1f77b4")
    lines_g = [ax_g.plot([], [], color=c, label=l, lw=1.2)[0]
               for c, l in zip(cg, ("gx", "gy", "gz"))]
    cq = ("#d62728", "#2ca02c", "#1f77b4", "#9467bd")
    lines_q = [ax_q.plot([], [], color=c, label=l, lw=1.2)[0]
               for c, l in zip(cq, ("qx", "qy", "qz", "qw"))]
    ax_g.legend(loc="upper right", ncol=3, fontsize=8)
    ax_q.legend(loc="upper right", ncol=4, fontsize=8)

    state = {"bg": None, "right": float(mon.window)}

    def full_redraw():
        fig.canvas.draw()
        state["bg"] = fig.canvas.copy_from_bbox(fig.bbox)

    def on_resize(_evt):
        full_redraw()

    def tick():
        ts_i, gyro, quat, _srv = mon.snapshot()
        if ts_i:
            t_right = ts_i[-1]
            if t_right >= state["right"] - 0.5:
                # Slide the time window in 2 s chunks: every x-limit change
                # invalidates the blit background and forces one full redraw
                # (~100 ms here), so sliding every frame would eat the CPU.
                state["right"] += 2.0
                for ax in (ax_g, ax_q):
                    ax.set_xlim(state["right"] - mon.window, state["right"])
                full_redraw()
            for i, line in enumerate(lines_g):
                line.set_data(ts_i, gyro[i])
            for i, line in enumerate(lines_q):
                line.set_data(ts_i, quat[i])
        if state["bg"] is not None:
            fig.canvas.restore_region(state["bg"])
            for ax, lines in ((ax_g, lines_g), (ax_q, lines_q)):
                for ln in lines:
                    ax.draw_artist(ln)
            fig.canvas.blit(fig.bbox)
        fig.canvas.get_tk_widget().after(100, tick)

    fig.canvas.mpl_connect("resize_event", on_resize)
    fig.tight_layout()
    full_redraw()
    fig.canvas.get_tk_widget().after(100, tick)
    plt.show()


# --- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Combined IMU + multi-servo bus monitor (FT-SCS)")
    ap.add_argument("--port", default="COM6",
                    help="bus adapter serial port (default COM6; "
                         "COM5 is the DAP-Link log UART)")
    ap.add_argument("--baud", type=int, default=1000000)
    ap.add_argument("--imu-id", type=int, default=200,
                    help="IMU board ID; 0 disables IMU polling")
    ap.add_argument("--srv-id", default="",
                    help="comma list of servo IDs to poll (default: scan);"
                         " 0 disables servo polling")
    ap.add_argument("--imu-rate", type=float, default=50.0,
                    help="shared SYNC READ rate in Hz")
    ap.add_argument("--window", type=float, default=10.0)
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--seconds", type=float, default=0.0)
    ap.add_argument("--no-demo", action="store_true",
                    help="do not start the default sweep on detected servos")
    ap.add_argument("--demo-lo", type=int, default=1536)
    ap.add_argument("--demo-hi", type=int, default=2560)
    ap.add_argument("--demo-speed", type=int, default=400)
    ap.add_argument("--demo-period", type=float, default=3.0)
    a = ap.parse_args()
    a.port = pick_port(a.port)

    if a.srv_id == "0":
        srv_ids = []
    elif a.srv_id:
        srv_ids = [int(x) for x in a.srv_id.split(",") if x.strip()]
    else:
        srv_ids = None  # scan

    mon = BusMonitor(a, srv_ids or [])
    if srv_ids is None:
        found = mon.scan()
        mon.servos = {sid: ServoState(sid, a.window) for sid in found}
        # Re-evaluate after the scan; --no-demo must win over found servos.
        mon.demo = (not a.no_demo) and bool(found)
    else:
        mon.demo = mon.demo and bool(srv_ids)
    if mon.demo:
        print("3 秒后开始 demo 摆动（Ctrl+C 取消）...")
        time.sleep(3.0)
        mon.start_demo()

    worker = threading.Thread(target=mon.run, daemon=True)
    worker.start()
    stop_at = time.monotonic() + a.seconds if a.seconds else None
    try:
        if a.plot:
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
        try:
            mon.shutdown()
        except Exception:
            pass
        if mon.imu_id is not None:
            print("stopped: IMU ok=%d/%d | " % (mon.n_imu_ok, mon.n_imu_req)
                  + " | ".join("SRV%d ok=%d/%d" % (sid, sv.ok, sv.req)
                               for sid, sv in sorted(mon.servos.items())))
        else:
            print("stopped: "
                  + " | ".join("SRV%d ok=%d/%d" % (sid, sv.ok, sv.req)
                               for sid, sv in sorted(mon.servos.items())))


if __name__ == "__main__":
    main()
