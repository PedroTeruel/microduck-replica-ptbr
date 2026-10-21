#!/usr/bin/env python3
"""Feetech FT-SCS servo tool for the Microduck IMU bus.

Same single-wire bus as the IMU board (ID 200).  The board stays silent for
frames addressed to other IDs, so a servo can be scanned and exercised while
the IMU board is online.

Commands:
  scan                    ping IDs 1..253, show responders
  read <id> [--watch]     present position/speed/load/voltage/temperature
  test <id>               torque on, sweep between two positions, torque off
  write <id> <addr> b...  raw register write (advanced, e.g. re-addressing)

Examples:
  python tools\\servo_tool.py scan --port COM6
  python tools\\servo_tool.py read 1 --port COM6 --watch
  python tools\\servo_tool.py test 1 --port COM6 --lo 1024 --hi 3072
"""
import argparse
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial 未安装: pip install pyserial")

# STS/SCS register map (decimal addresses, matches the firmware ft table)
REG_ID = 5
REG_MODE = 21
REG_TORQUE_EN = 40
REG_ACC = 41
REG_GOAL_POS = 42     # 2B LE
REG_GOAL_SPEED = 46   # 2B LE, bit15 = direction (ignored in position mode)
REG_POS = 56          # 2B LE, 0..4095
REG_SPEED = 58        # 2B LE, bit15 = dir
REG_LOAD = 60         # 2B LE, bit15 = dir
REG_VOLT = 62         # 0.1 V
REG_TEMP = 63         # degC
REG_MOVING = 66

IMU_ID = 200
POS_PER_DEG = 4096.0 / 360.0


def ft_frame(id_, inst, params=b""):
    n = len(params) + 2
    ck = (~(id_ + n + inst + sum(params))) & 0xFF
    return bytes((0xFF, 0xFF, id_, n, inst)) + params + bytes((ck,))


class Bus:
    def __init__(self, port, baud=1_000_000, timeout=0.03):
        self.s = serial.Serial(port, baud, timeout=timeout)
        self.timeout = timeout

    def close(self):
        self.s.close()

    def _read_status(self, want_id):
        """Read one status packet FF FF id len 00 data ck, verify checksum."""
        deadline = time.time() + self.timeout + 0.02
        buf = b""
        while time.time() < deadline:
            buf += self.s.read(64)
            i = buf.find(b"\xff\xff")
            if i < 0 or len(buf) - i < 4:
                continue
            id_ = buf[i + 2]
            n = buf[i + 3]
            if len(buf) - i < 4 + n:
                continue
            pkt = buf[i:4 + n + 1]
            body = pkt[2:-1]
            ck = pkt[-1]
            if id_ != want_id:
                buf = buf[i + 1:]
                continue
            if (~(id_ + n + pkt[i + 4] + sum(pkt[i + 5:-1]))) & 0xFF == ck:
                return pkt[i + 5:-1]  # data bytes
            return None  # addressed us but checksum bad
        return None

    def transact(self, id_, inst, params=b""):
        self.s.reset_input_buffer()
        self.s.write(ft_frame(id_, inst, params))
        return self._read_status(id_)

    def ping(self, id_):
        return self.transact(id_, 0x01) is not None

    def read(self, id_, addr, ln):
        r = self.transact(id_, 0x02, bytes((addr, ln)))
        if r is None or len(r) != ln:
            return None
        return r

    def write(self, id_, addr, data):
        return self.transact(id_, 0x03, bytes((addr,)) + bytes(data)) is not None

    def read_u16(self, id_, addr):
        r = self.read(id_, addr, 2)
        return None if r is None else r[0] | (r[1] << 8)


def pick_port(name):
    ports = [p.device for p in list_ports.comports()]
    if name:
        return name
    if len(ports) == 1:
        return ports[0]
    sys.exit(f"检测到多个串口 {ports}，请用 --port 指定总线口（通常是 COM6；"
             f"COM5 是 DAP-LINK 调试口）")


def u16s(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def cmd_scan(a):
    bus = Bus(pick_port(a.port))
    print(f"扫描 1..253 @ 1 Mbps ...")
    found = []
    for id_ in range(1, 254):
        if bus.ping(id_):
            ver = bus.read(id_, 0, 5)
            tag = "  <- MD-IMU 板（本项目）" if id_ == IMU_ID else ""
            if ver:
                if id_ == IMU_ID:
                    model = ver[3] | (ver[4] << 8)
                    fw = f"{ver[0]}.{ver[1]}"
                else:
                    model = ver[0] | (ver[1] << 8)
                    fw = ver[2]
                print(f"  ID {id_:3d}  model=0x{model:04X} fw={fw}"
                      f"  表头={ver.hex(' ')}{tag}")
            else:
                print(f"  ID {id_:3d}  (ping 应答, 读版本失败){tag}")
            found.append(id_)
    bus.close()
    print(f"共 {len(found)} 个: {found}")


def decode_status(b):
    pos = b[0] | (b[1] << 8)
    spd = b[2] | (b[3] << 8)
    load = b[4] | (b[5] << 8)
    return {
        "pos": pos, "deg": pos / POS_PER_DEG,
        "spd": (spd & 0x7FFF) * (-1 if spd & 0x8000 else 1),
        "load": (load & 0x3FF) * (-1 if load & 0x8000 else 1),
        "volt": b[6] / 10.0, "temp": b[7], "moving": b[10],
    }


def cmd_read(a):
    bus = Bus(pick_port(a.port))
    try:
        while True:
            b = bus.read(a.id, REG_POS, 15)
            if b is None:
                print(f"ID {a.id} 无应答")
                if not a.watch:
                    break
            else:
                s = decode_status(b)
                print(f"pos={s['pos']:4d} ({s['deg']:6.1f}°)  "
                      f"spd={s['spd']:5d}  load={s['load']:4d}  "
                      f"V={s['volt']:4.1f}  T={s['temp']:2d}°C  "
                      f"moving={s['moving']}")
                if not a.watch:
                    break
            time.sleep(1.0 / a.rate)
    except KeyboardInterrupt:
        pass
    finally:
        bus.close()


def cmd_test(a):
    bus = Bus(pick_port(a.port))
    try:
        mode = bus.read(a.id, REG_MODE, 1)
        if mode is None:
            sys.exit(f"ID {a.id} 无应答")
        if mode[0] != 0 and not a.force:
            sys.exit(f"舵机 mode={mode[0]}（位置模式需为 0），"
                     f"加 --force 强行继续")
        print(f"舵机将转动: {a.lo}({a.lo/POS_PER_DEG:.0f}°) <-> "
              f"{a.hi}({a.hi/POS_PER_DEG:.0f}°), 速度 {a.speed}, "
              f"{a.loops} 个来回, Ctrl+C 随时停止")
        bus.write(a.id, REG_TORQUE_EN, (1,))
        bus.write(a.id, REG_ACC, (a.acc,))
        bus.write(a.id, REG_GOAL_SPEED, u16s(a.speed & 0x7FFF))
        try:
            for i in range(a.loops):
                for target in (a.lo, a.hi):
                    bus.write(a.id, REG_GOAL_POS, u16s(target))
                    t0 = time.time()
                    while time.time() - t0 < 8.0:
                        b = bus.read(a.id, REG_POS, 11)
                        if b is None:
                            print("  无应答!")
                            break
                        s = decode_status(b)
                        err = abs(s["pos"] - target)
                        print(f"  目标={target:4d} pos={s['pos']:4d} "
                              f"({s['deg']:5.1f}°) err={err:4d} "
                              f"moving={s['moving']}")
                        if err < 20 and not s["moving"]:
                            break
                        time.sleep(0.05)
                    else:
                        print("  到位超时")
        finally:
            bus.write(a.id, REG_TORQUE_EN, (0,))
            print("扭矩已关闭")
    finally:
        bus.close()


def cmd_write(a):
    if a.id == IMU_ID:
        print("注意: IMU 板(ID 200)固件中 ID/波特率固定，相关写操作会被忽略；"
              "仅 84(marker)/240(重初始化) 等少量寄存器可写。")
    bus = Bus(pick_port(a.port))
    data = [int(x, 0) for x in a.data]
    ok = bus.write(a.id, a.addr, data)
    print("OK" if ok else "无应答/失败")
    bus.close()


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", default="COM6",
                        help="总线串口（默认 COM6；COM5 是 DAP-LINK 调试口）")
    p = argparse.ArgumentParser(description="Feetech 舵机工具（FT-SCS, 1 Mbps）",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", parents=[common]).set_defaults(fn=cmd_scan)

    r = sub.add_parser("read", parents=[common])
    r.add_argument("id", type=int)
    r.add_argument("--watch", action="store_true")
    r.add_argument("--rate", type=float, default=5.0)
    r.set_defaults(fn=cmd_read)

    t = sub.add_parser("test", parents=[common])
    t.add_argument("id", type=int)
    t.add_argument("--lo", type=int, default=1024)
    t.add_argument("--hi", type=int, default=3072)
    t.add_argument("--speed", type=int, default=300)
    t.add_argument("--acc", type=int, default=30)
    t.add_argument("--loops", type=int, default=3)
    t.add_argument("--force", action="store_true")
    t.set_defaults(fn=cmd_test)

    w = sub.add_parser("write", parents=[common])
    w.add_argument("id", type=int)
    w.add_argument("addr", type=lambda x: int(x, 0))
    w.add_argument("data", nargs="+")
    w.set_defaults(fn=cmd_write)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
