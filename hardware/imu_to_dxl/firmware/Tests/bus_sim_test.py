# -*- coding: utf-8 -*-
"""Simula o barramento usando o código de protocolo do firmware real: compila
protocol.c + control_table.c em uma DLL (Tests/bus_sim_shim.c), conecta-a ao
simulador de servos em nível de protocolo e testa com as ferramentas do controlador:

- check() de tools/imu200/imu200.py: aceitação da seção 11 de 总线协议.md, com critérios do controlador
- consulta --imu-bus do painel servo-web: mesma sync_read do controlador, com ID 200 primeiro
- regra de fila: ID 200 no meio e um dispositivo anterior offline (seção 5)

O tempo do barramento é simulado em microssegundos: pacotes do controlador e
respostas dos outros servos chegam ao firmware a 1 Mbps (10 µs/byte). A resposta
do firmware e seu instante são determinados pelo próprio código C. Os servos
continuam simulados por sim_bus. Nenhum hardware é conectado.

  python Tests/bus_sim_test.py            # cl.exe no PATH ou busca automática do Visual Studio via vswhere
"""
import ctypes
import math
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
REPO = os.path.abspath(os.path.join(FW, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "servo-web"))
sys.path.insert(0, os.path.join(REPO, "tools", "imu200"))
import feetech          # noqa: E402
import imu200           # noqa: E402
from sim_bus import SimSerial   # noqa: E402

JOINTS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
BYTE_US = 10            # 1 Mbps
SERVO_TRESP_US = 30     # Atraso de resposta simulado do servo (valor real ainda precisa ser medido; seção 12).
SOURCES = ["Tests/bus_sim_shim.c", "Core/Src/protocol.c", "Core/Src/control_table.c"]


def build_dll():
    out_dir = os.path.join(FW, "Build", "host-tests")
    os.makedirs(out_dir, exist_ok=True)
    dll = os.path.join(out_dir, "bus_sim_shim.dll")
    srcs = [os.path.join(FW, s) for s in SOURCES] + [os.path.join(FW, "Core", "Inc", h)
                                                     for h in ("protocol.h", "control_table.h", "imu.h")]
    if os.path.exists(dll) and os.path.getmtime(dll) > max(os.path.getmtime(s) for s in srcs):
        return dll
    cmd = (f'cl /nologo /LD /std:c11 /W4 /WX /Od /I Core\\Inc /FoBuild\\host-tests\\ '
           f'/Fe:Build\\host-tests\\bus_sim_shim.dll ' + " ".join(s.replace("/", "\\") for s in SOURCES))
    if not shutil.which("cl"):
        vswhere = r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
        root = subprocess.run([vswhere, "-latest", "-products", "*", "-requires",
                               "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property",
                               "installationPath"], capture_output=True, text=True).stdout.strip()
        vcvars = os.path.join(root, "VC", "Auxiliary", "Build", "vcvars64.bat")
        cmd = f'call "{vcvars}" >nul 2>nul && {cmd}'
    # Passe o comando inteiro como uma única string para cmd /s /c: na forma de lista, Python escapa as aspas segundo as regras do runtime C, que o cmd não entende.
    r = subprocess.run(f'cmd /d /s /c "{cmd}"', cwd=FW, capture_output=True, text=True,
                       encoding="mbcs", errors="replace")
    if r.returncode:
        raise SystemExit("Falha ao compilar a DLL:\n" + r.stdout + r.stderr)
    return dll


def f16(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


class FirmwareOnBus(SimSerial):
    """Porta serial simulada de sim_bus; o ID 200 responde com o código real do protocolo do firmware."""

    def __init__(self, dll, joints, ready_ms=100):
        super().__init__(joints)
        self.fw = dll
        self.fw.shim_init()
        self.us = 1000
        self.last_sync_us = -20000
        self.ready_ms = ready_ms
        self.fw_delays = []          # Atraso da resposta do firmware (µs) desde o momento em que recebe a vez.
        self.collisions = []         # Transmissões indevidas do firmware: (instante, bytes).
        self.sync_bus_us = []        # Duração de cada sync_read no barramento virtual (início da instrução → fim da última resposta).

    # ---- Relógio e dados da IMU vistos pelo firmware ----
    def _imu_now(self):
        t = self.us / 1e6
        ms = self.us // 1000
        self.fw.shim_set_millis(ms)
        samples = int(t * 120)
        if ms < self.ready_ms:
            self.fw.shim_set_snapshot(0, 1, 0, 0, 0, 0, 0, 0, samples)
            return
        jitter = samples % 7 - 3            # Os bits menos significativos variam mesmo com o chip real parado.
        yaw = 0.3 * math.sin(t)
        self.fw.shim_set_snapshot(1, 0, int(100 * math.sin(t)) + jitter, -50 + jitter, 3 - jitter,
                                  f16(0.05), f16(0.0), f16(math.sin(yaw / 2)), samples)

    def _idle(self, duration_us):
        """Consulta o firmware a cada microssegundo enquanto o barramento pertence a outro dispositivo (ou está ocioso): transmitir nesse intervalo causa colisão."""
        buf = (ctypes.c_uint8 * 300)()
        for _ in range(duration_us):
            self.us += 1
            self.fw.shim_poll(self.us)
            n = self.fw.shim_take_tx(buf, 300)
            if n > 0:
                self.collisions.append((self.us, bytes(buf[:n]).hex(" ")))

    def _heard(self, data, gap_us):
        """O firmware recebe bytes enviados ao barramento (pacotes do controlador ou respostas de outros servos); continua sendo consultado entre os bytes."""
        self._idle(gap_us)
        for i, b in enumerate(data):
            if i:
                self._idle(BYTE_US - 1)
                self.us += 1
            self.fw.shim_feed(b, self.us)

    def _fw_turn(self, limit_us=6000):
        """Quando chega a vez do firmware (ou quando ele deve permanecer em silêncio), consulta-o a cada microssegundo para observar quando e o que transmite."""
        start = self.us
        buf = (ctypes.c_uint8 * 300)()
        while self.us - start < limit_us:
            self.us += 1
            self.fw.shim_poll(self.us)
            n = self.fw.shim_take_tx(buf, 300)
            if n > 0:
                self.fw_delays.append(self.us - start)
                data = bytes(buf[:n])
                self.us += BYTE_US * n        # A transmissão ocupa o barramento, mas o próprio dispositivo não a recebe (RX_EN desativa o retorno).
                return data
            if self.fw.shim_pending() == 0 and self.us - start > 200:
                return None                   # Não há resposta prevista.
        return None

    def _servo_reply(self, s, params):
        s.tick(self.clock)
        body = bytes([s.id, len(params) + 2, s.r[65]]) + bytes(params)
        return b"\xff\xff" + body + bytes([(~sum(body)) & 0xFF])

    def write(self, data):
        data = bytes(data)
        while len(data) >= 6:
            if data[0] != 0xFF or data[1] != 0xFF:
                data = data[1:]
                continue
            length = data[3]
            pkt, data = data[:4 + length], data[4 + length:]
            self._packet(pkt)
        return len(data)

    def _packet(self, pkt):
        sid, instr, params = pkt[2], pkt[4], pkt[5:-1]
        self._advance()
        # Ritmo do controlador: um sync_read a cada 20 ms (50 Hz), com 2 ms entre os outros pacotes. Não use o relógio real:
        # no Windows, sleep tem resolução de 15,6 ms e tornaria os intervalos virtuais irregulares, ao contrário do hardware real.
        if instr == feetech.SYNC_READ:
            self.us = max(self.us + 2000, self.last_sync_us + 20000)
            self.last_sync_us = self.us
        else:
            self.us += 2000
        self._imu_now()
        self._heard(pkt, 0)
        if instr == feetech.SYNC_READ and sid == feetech.BROADCAST:
            t0 = self.us - BYTE_US * (len(pkt) - 1)
            addr, ln, ids = params[0], params[1], params[2:]
            for i in ids:
                if i == 200:
                    r = self._fw_turn()
                    if r:
                        self.rx += r
                    continue
                s = self._by_id(i)
                if s and addr not in getattr(s, "muted", ()):
                    reply = self._servo_reply(s, s.read(addr, ln, self.clock))
                    self.rx += reply
                    self._heard(reply, SERVO_TRESP_US)
                else:
                    self._idle(300)               # Servo offline: barramento ocioso.
            self.sync_bus_us.append(self.us - t0)
            if 200 not in ids:
                self._idle(3000)                  # Sem consulta ao ID 200: ele deve permanecer em silêncio nesse intervalo.
            return
        if sid == 200 or sid == feetech.BROADCAST:
            r = self._fw_turn()
            if r:
                self.rx += r
            if sid == 200:
                return
        before = len(self.rx)
        self._handle(sid, instr, params)          # Pacote destinado a um servo: sim_bus processa normalmente.
        reply = bytes(self.rx[before:])
        if reply:
            self._heard(reply, SERVO_TRESP_US)

    def counters(self):
        out = (ctypes.c_uint32 * 7)()
        self.fw.shim_counters(out)
        return dict(zip(("rx_packets", "tx_packets", "crc", "malformed", "timeouts", "cancelled", "skipped"), out))


def load():
    lib = ctypes.CDLL(build_dll())
    lib.shim_feed.argtypes = [ctypes.c_uint8, ctypes.c_uint32]
    lib.shim_poll.argtypes = [ctypes.c_uint32]
    lib.shim_set_millis.argtypes = [ctypes.c_uint32]
    lib.shim_take_tx.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int]
    lib.shim_set_snapshot.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int16, ctypes.c_int16, ctypes.c_int16,
                                      ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]
    lib.shim_counters.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
    return lib


def main():
    lib = load()
    results = []

    def ok(cond, what):
        results.append((bool(cond), what))
        print(("  ✓ " if cond else "  ✗ ") + what)

    print("== 1. check() de imu200.py: critérios de aceitação do controlador aplicados ao protocolo real do firmware ==")
    port = FirmwareOnBus(lib, JOINTS)
    bus = feetech.FeetechBus(None, ser=port)
    imu200.log = lambda *a, **k: None          # Mostra somente os resultados, sem inundar a saída.
    for good, what in imu200.check(bus, frames=80, hz=50):
        if what.startswith("Duração da transação"):
            # check mede o relógio de parede do Python; aqui a DLL é consultada a cada microssegundo, então esse tempo não representa o barramento. Use o relógio virtual.
            print(f"  · check: {what} (tempo de parede do Python na simulação; ignorado)")
            continue
        ok(good, "check: " + what)
    c = port.counters()
    ok(c["crc"] == 0 and c["malformed"] == 0 and c["timeouts"] == 0, f"Sem erros de CRC, pacotes inválidos ou quadros incompletos no firmware: {c}")
    delays = sorted(port.fw_delays)
    ok(delays and delays[0] >= 50 and delays[-1] <= 52,
       f"T_resp (lógica do protocolo): o firmware começa a transmitir {delays[0]}–{delays[-1]} µs após receber a vez (especificação: 50 µs; medir o tempo da CPU com analisador lógico)")
    ok(not port.collisions, f"O firmware permanece em silêncio enquanto outro dispositivo transmite ou o barramento está ocioso (colisões: {len(port.collisions)}; exemplos: {port.collisions[:2]})")
    full = sorted(t for t in port.sync_bus_us if t > 2000)   # Leitura conjunta dos 16 dispositivos.
    p99 = full[max(0, int(len(full) * 0.99) - 1)] / 1000
    ok(full and p99 < 6.0, f"sync_read de 16 dispositivos: p99 de {p99:.2f} ms no barramento virtual (orçamento de 6 ms; T_resp simulado do servo = {SERVO_TRESP_US} µs)")

    print("== 2. Área de versões (seção 9) ==")
    _, head = bus.read(200, 0, 9)
    ok(list(head) == [0, 2, 0, 0x44, 0x4D, 200, 0, 0, 1], f"0–8 = {list(head)} (versão 0.2, END 0, modelo, ID 200, 1 Mbps, nível 1)")

    print("== 3. Fila (seção 5): ID 200 no meio, com dispositivo anterior offline ==")
    port = FirmwareOnBus(lib, JOINTS, ready_ms=0)
    bus = feetech.FeetechBus(None, ser=port)
    got = bus.sync_read([20, 21, 200, 22], 56, 15)
    ok(all(got.get(i) for i in (20, 21, 200, 22)), "ID 200 ocupa a terceira posição: os quatro respondem sem colisão nem desalinhamento")
    port.servos[21].muted.add(56)                 # ID 21 não responde a este endereço, simulando um dispositivo anterior offline.
    # Inspeciona os quadros brutos do barramento: feetech.py lê em sequência e a ausência de um servo desalinha as respostas seguintes (especificação, seção 2), como ocorre no controlador.
    port.reset_input_buffer()
    bus._send(feetech.BROADCAST, feetech.SYNC_READ, bytes([56, 15, 20, 21, 200, 22]))
    raw, frames = bytes(port.rx), []
    while len(raw) >= 6 and raw[:2] == b"\xff\xff":
        frames.append(raw[2])
        raw = raw[4 + raw[3]:]
    ok(frames == [20, 200, 22], f"ID 21 offline: ordem das respostas no barramento = {frames} (ID 200 responde após o intervalo e ID 22 também responde)")
    ok(port.counters()["skipped"] == 1, f"Firmware registrou 1 dispositivo offline ignorado ({port.counters()['skipped']})")
    got = bus.sync_read([20, 21, 22], 56, 15)
    ok(200 not in got and not port.collisions,
       f"ID 200 não aparece na lista: o firmware permanece em silêncio durante as respostas dos servos e por mais 3 ms ({len(port.collisions)} transmissões indevidas)")

    print("== 4. Consulta --imu-bus do painel: mesma sync_read do controlador ==")
    import imu_bus
    import server
    port = FirmwareOnBus(lib, JOINTS, ready_ms=0)
    svc = imu_bus.BusImuService()
    server.BUS = feetech.FeetechBus(None, ser=port)
    server.log = lambda *a, **k: None
    for _ in range(5):
        st = server.read_states_with_imu(JOINTS, svc)
        time.sleep(0.02)
    status = svc.get_status()
    ok(status["live"] and all(st[i] for i in JOINTS), f"Orientação ativa e estado dos 15 servos disponível: {status['message']}")
    ok(not port.collisions, f"Nenhuma transmissão indevida do firmware durante a consulta do painel ({len(port.collisions)} colisões)")

    bad = [w for g, w in results if not g]
    print(f"\n{len(results) - len(bad)}/{len(results)} aprovados" + ("" if not bad else "; falhas:\n  " + "\n  ".join(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
