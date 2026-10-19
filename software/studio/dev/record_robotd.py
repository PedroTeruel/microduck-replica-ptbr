"""在鸭子上录 robotd 的真实回包，给假 robotd 和测试用（只读，不发任何会让鸭子动的命令）。

    python3 -I dev/record_robotd.py --label limp --seconds 3 > limp.jsonl

每行一个 JSON：{"kind": "reply", "method": ..., "params": ..., "reply": ...}，
订阅的状态帧是 {"kind": "notify", "dt": 收到时距开始几秒, "msg": ...}。
标签（软着 / 保持 / 策略中 / 坐着 / 调试模式……）写在第一行 {"kind": "meta"}。
只用标准库，板上直接跑。
"""
import argparse
import json
import socket
import sys
import time

READ_ONLY = [
    ("hello", {}),
    ("robot.health", {}),
    ("robot.busStatus", {}),
    ("robot.policies", {}),
    ("robot.busCommand", {"action": "calibration-status"}),
]


def call(path, method, params, timeout=5.0):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    s.connect(path)
    s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}) + "\n").encode())
    f = s.makefile("rb")
    line = f.readline(1 << 22)
    s.close()
    return json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--socket", default="/run/robotd.sock")
    ap.add_argument("--configd", default="/run/configd.sock")
    ap.add_argument("--label", required=True)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--hz", type=int, default=10)
    a = ap.parse_args()
    out = sys.stdout
    out.write(json.dumps({"kind": "meta", "label": a.label, "at": time.strftime("%F %T")}, ensure_ascii=False) + "\n")
    for method, params in READ_ONLY:
        try:
            reply = call(a.socket, method, params)
        except OSError as e:
            reply = {"_error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps({"kind": "reply", "method": method, "params": params, "reply": reply}, ensure_ascii=False) + "\n")
    for method in ("pad.status", "system.info"):
        try:
            reply = call(a.configd, method, {})
        except OSError as e:
            reply = {"_error": f"{type(e).__name__}: {e}"}
        out.write(json.dumps({"kind": "reply", "socket": "configd", "method": method, "params": {}, "reply": reply}, ensure_ascii=False) + "\n")
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(2.0)
    s.connect(a.socket)
    s.sendall((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "robot.subscribe", "params": {"hz": a.hz}}) + "\n").encode())
    f = s.makefile("rb")
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.seconds:
        try:
            line = f.readline(1 << 22)
        except socket.timeout:
            break
        if not line:
            break
        out.write(json.dumps({"kind": "notify", "dt": round(time.monotonic() - t0, 3), "msg": json.loads(line)}, ensure_ascii=False) + "\n")
    s.close()


if __name__ == "__main__":
    main()
