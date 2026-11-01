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
    sys.exit("pyserial não está instalado: pip install pyserial")

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
    sys.exit(f"Foram encontradas várias portas seriais {ports}; use --port para indicar a porta do barramento (normalmente COM6; "
             f"COM5 é a porta de depuração DAP-LINK).")


def u16s(v):
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


def cmd_scan(a):
    bus = Bus(pick_port(a.port))
    print("Varredura de 1 a 253 a 1 Mbps...")
    found = []
    for id_ in range(1, 254):
        if bus.ping(id_):
            ver = bus.read(id_, 0, 5)
            tag = "  <- placa MD-IMU (deste projeto)" if id_ == IMU_ID else ""
            if ver:
                if id_ == IMU_ID:
                    model = ver[3] | (ver[4] << 8)
                    fw = f"{ver[0]}.{ver[1]}"
                else:
                    model = ver[0] | (ver[1] << 8)
                    fw = ver[2]
                print(f"  ID {id_:3d}  model=0x{model:04X} fw={fw}"
                      f"  bytes iniciais={ver.hex(' ')}{tag}")
            else:
                print(f"  ID {id_:3d}  (PING respondeu, falha ao ler a versão){tag}")
            found.append(id_)
    bus.close()
    print(f"Total: {len(found)} dispositivos: {found}")


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
                print(f"ID {a.id}: sem resposta")
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
            sys.exit(f"ID {a.id}: sem resposta")
        if mode[0] != 0 and not a.force:
            sys.exit(f"Modo do servo = {mode[0]} (o modo de posição deve ser 0); "
                     f"adicione --force para continuar mesmo assim")
        print(f"O servo vai se mover: {a.lo} ({a.lo/POS_PER_DEG:.0f}°) <-> "
              f"{a.hi} ({a.hi/POS_PER_DEG:.0f}°), velocidade {a.speed}, "
              f"{a.loops} ciclos de ida e volta. Ctrl+C interrompe a qualquer momento.")
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
                            print("  Sem resposta!")
                            break
                        s = decode_status(b)
                        err = abs(s["pos"] - target)
                        print(f"  alvo={target:4d} posição={s['pos']:4d} "
                              f"({s['deg']:5.1f}°) erro={err:4d} "
                              f"em movimento={s['moving']}")
                        if err < 20 and not s["moving"]:
                            break
                        time.sleep(0.05)
                    else:
                        print("  Tempo esgotado antes de chegar à posição")
        finally:
            bus.write(a.id, REG_TORQUE_EN, (0,))
            print("Torque desativado")
    finally:
        bus.close()


def cmd_write(a):
    if a.id == IMU_ID:
        print("Atenção: o firmware da placa IMU (ID 200) fixa o ID e a taxa de transmissão, "
              "e ignora as gravações correspondentes; somente alguns registradores podem ser gravados, "
              "como 84 (marcador) e 240 (reinicialização).")
    bus = Bus(pick_port(a.port))
    data = [int(x, 0) for x in a.data]
    ok = bus.write(a.id, a.addr, data)
    print("OK" if ok else "Sem resposta/falha")
    bus.close()


def main():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", default="COM6",
                        help="Porta serial do barramento (padrão: COM6; COM5 é a porta de depuração DAP-LINK)")
    p = argparse.ArgumentParser(description="Ferramenta para servos Feetech (FT-SCS, 1 Mbps)",
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
