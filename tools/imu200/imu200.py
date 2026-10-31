# -*- coding: utf-8 -*-
"""Bloco IMU ID 200: codificação/decodificação, placa simulada e verificação da placa real.

O módulo `imu_to_dxl` deve se apresentar no barramento dos servos como um servo de ID 200. A cada tick,
o controlador usa `sync_read` (endereço 56, comprimento 15) para ler a IMU e os 15 servos de uma vez.
O protocolo completo está em [`hardware/imu_to_dxl/总线协议.md`](../../hardware/imu_to_dxl/总线协议.md);
este arquivo é sua **versão executável**:

  python imu200.py demo                  # simula a placa e executa o código real do controlador em memória
  python imu200.py vectors               # imprime vetores de teste em hexadecimal para implementar o firmware
  python imu200.py check --port COM6     # verifica a placa real e mostra PASS/FAIL para cada critério

Os critérios seguem o código real do controlador (`duck-control/src/imu.rs` e `bus.rs` do fork),
em vez de se basearem apenas no texto do protocolo. Portanto, se passar aqui, o controlador aceitará
os dados. Os logs seguem o padrão do repositório: `logs/imu200-data.log` (incluindo os dados brutos
enviados e recebidos em hexadecimal) e uma linha JSONL por quadro para facilitar o diagnóstico.
"""
import argparse
import json
import math
import os
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "servo-web"))
import feetech  # noqa: E402  Implementação do protocolo Feetech já incluída no repositório.

IMU_ID = 200
BLOCK_ADDR = 56           # Mesmo intervalo de endereços dos servos, para incluir o ID 200 no sync_read.
BLOCK_LEN = 15            # O controlador usa 12 bytes (imu.rs: IMU_BLOCK_LEN = 12); os 3 restantes completam o bloco.
IMU_WINDOW = 12           # Janela analisada pelo controlador e comparada byte a byte pelo StaleImuTracker.
GYRO_LSB_DPS = 0.0175     # Faixa de ±500 dps, 17,5 mdps/LSB (imu.rs: GYRO_RAD_PER_LSB).
GYRO_MAX_LSB = 28571      # LSB na faixa máxima de ±500 dps; exceder indica faixa incorreta no firmware.
READY_FRAMES = 25         # O controlador acumula 25 quadros válidos de quaternion para ficar pronto (imu.rs: quat_samples).
NORM_SQ_MAX = 1.02        # Critério de imu.rs: margem de arredondamento de meia precisão em escala máxima.
STALE_RUN_MAX = 25        # bus.rs: 25 quadros consecutivos com 12 bytes iguais fazem o StaleImuTracker acusar congelamento.
TICK_BUDGET_MS = 6.0      # Documento de arquitetura, item 4 da seção 5: orçamento para ler 16 dispositivos.
MOUNT = (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0)   # imu.rs: DEFAULT_MOUNT, rotação de +90° em Y.

JOINT_IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
FULL_IDS = [IMU_ID] + JOINT_IDS        # Lista enviada a cada tick pelo controlador, com o ID 200 primeiro.


# ---- Logs: mesmo formato do servo-web; mensagens de depuração vão apenas para o arquivo. ----
LOG_DIR = os.path.join(HERE, "logs")
_log_file = None


def log(msg, cat="Barramento", level="info"):
    global _log_file
    tag = {"info": "", "warn": "[AVISO]", "error": "[ERRO]", "debug": "[DEPURAÇÃO]"}[level]
    line = f"{time.strftime('%H:%M:%S')} [{cat}]{tag} {msg}"
    try:
        if _log_file is None:
            os.makedirs(LOG_DIR, exist_ok=True)
            _log_file = open(os.path.join(LOG_DIR, f"imu200-{time.strftime('%Y-%m-%d')}.log"),
                             "a", encoding="utf-8")
        _log_file.write(line + "\n")
        _log_file.flush()
    except OSError:
        pass
    if level != "debug":
        print(line)


def attach_trace(bus):
    """Inclui os dados brutos enviados e recebidos no log.

    Limpa trace_skip porque, por padrão, ele filtra SYNC_READ, justamente o pacote que
    precisamos analisar.
    """
    bus.trace_skip = set()
    bus.trace = lambda s: log(s, "Barramento", "debug")


# ---- Meia precisão: usa IEEE 754 binary16, que pode ser reproduzido no firmware. ----
def f32_to_f16(x):
    return struct.unpack("<H", struct.pack("<e", x))[0]


def f16_to_f32(h):
    return struct.unpack("<e", struct.pack("<H", h))[0]


def encode_block(gyro_dps=(0.0, 0.0, 0.0), quat_xyz=(0.0, 0.0, 0.0), counter=0, status=0):
    """Codifica 15 bytes: gyro x/y/z (i16 little-endian, 17,5 mdps/LSB), quat x/y/z (half), contador, estado e reserva.

    Giroscópio e quaternion são validados pelos critérios do controlador. O pior erro desta ferramenta
    seria gerar um bloco que o controlador certamente rejeitaria sem avisar.
    """
    raw = [int(round(v / GYRO_LSB_DPS)) for v in gyro_dps]
    if any(abs(v) > GYRO_MAX_LSB for v in raw):
        raise ValueError(f"Giroscópio fora da faixa: {gyro_dps} dps; ±500 dps correspondem a ±{GYRO_MAX_LSB} LSB")
    norm_sq = sum(v * v for v in quat_xyz)
    if not all(math.isfinite(v) for v in quat_xyz) or norm_sq > NORM_SQ_MAX:
        raise ValueError(f"O controlador rejeitaria o quaternion {quat_xyz}: norma² = {norm_sq:.3f} > {NORM_SQ_MAX}")
    return (struct.pack("<hhh", *raw)
            + struct.pack("<HHH", *(f32_to_f16(v) for v in quat_xyz))
            + bytes([counter & 0xFF, status & 0xFF, 0]))


def _qmul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def decode_block(b):
    """Decodifica 15 bytes seguindo cada critério de imu.rs:

    - Se as três componentes do quaternion forem 0, a fusão ainda não produziu dados; o controlador
      reutiliza o quadro anterior e não o contabiliza para ficar pronto.
    - Se alguma componente não for finita ou se norma² > 1.02, o controlador **rejeita** o quadro.
      A validação da ferramenta precisa ser igualmente rigorosa, senão um firmware defeituoso passará
      aqui, mas imu_ready() ficará sempre falso no equipamento.
    - Calcula w = √(1 − norma²), multiplica pelo conjugado de mount e rejeita também se a norma ≤ 0.5.
    """
    if len(b) != BLOCK_LEN:
        raise ValueError(f"Esperados {BLOCK_LEN} bytes; recebidos {len(b)}")
    gx, gy, gz = struct.unpack_from("<hhh", b, 0)
    packed = struct.unpack_from("<HHH", b, 6)
    qx, qy, qz = (f16_to_f32(h) for h in packed)
    finite = all(math.isfinite(v) for v in (qx, qy, qz))
    norm_sq = (qx * qx + qy * qy + qz * qz) if finite else float("inf")
    accepted, quat, gravity = False, None, None
    if any(packed) and finite and norm_sq <= NORM_SQ_MAX:
        w = math.sqrt(max(0.0, 1.0 - norm_sq))
        q = _qmul((w, qx, qy, qz), (MOUNT[0], -MOUNT[1], -MOUNT[2], -MOUNT[3]))
        n = math.sqrt(sum(v * v for v in q))
        if n > 0.5:
            accepted = True
            quat = tuple(v / n for v in q)
            # Gravidade no referencial do tronco; em pé, [0, 0, -1] (igual a imu.rs).
            w0, x0, y0, z0 = quat
            gravity = (-2 * (x0 * z0 - w0 * y0), -2 * (y0 * z0 + w0 * x0),
                       -(1 - 2 * (x0 * x0 + y0 * y0)))
    return {
        "gyro_raw": (gx, gy, gz),
        "gyro_dps": (gx * GYRO_LSB_DPS, gy * GYRO_LSB_DPS, gz * GYRO_LSB_DPS),
        "quat_packed": packed,
        "quat_xyz": (qx, qy, qz),
        "quat_trunk": quat,
        "gravity": gravity,
        "norm_sq": norm_sq,
        "finite": finite,
        "counter": b[12],
        "status": b[13],
        "reserved": b[14],
        "accepted": accepted,                  # Indica se o controlador contará este quadro para ficar pronto.
        "window_hex": b[:IMU_WINDOW].hex(),     # Estes são os 12 bytes comparados pelo StaleImuTracker.
    }


class SimImu200:
    """Placa simulada: pode ser conectada a sim_bus.SimSerial e lida pelo código real do controlador.

    Comportamentos definidos no arquivo de protocolo:
    - O bloco é atualizado quando a IMU produz dados (120 Hz por padrão), **não a cada leitura**.
      O contador representa amostras; com o controlador lendo a 50 Hz, avança 2 ou 3 por quadro.
      Incrementá-lo a cada leitura esconderia a falha "IMU parada, processador do barramento ativo".
    - O processador do barramento inicia antes da IMU: responde após bus_up_ms e só fornece quaternion
      após imu_ready_ms; até lá, retorna zeros.
    - O giroscópio inclui ruído: mesmo parado, o chip real varia nos bits menos significativos, fazendo
      o bloco mudar byte a byte. Se a suavização do firmware deixar os 12 bytes iguais, o controlador
      acusa congelamento após 0,5 segundo.
    - answer=False simula uma placa sem resposta (na máquina real, a leitura sync_read inteira falha
      e os dados dos 15 servos também são perdidos).
    """

    def __init__(self, sid=IMU_ID, sample_hz=120, bus_up_ms=0, imu_ready_ms=500,
                 answer=True, noise=True):
        self.r = bytearray(feetech.DUMP_END)
        self.r[0], self.r[1] = 0, 1           # Firmware versão 0.1, sem se passar por um servo 3.46.
        self.r[2], self.r[5], self.r[6], self.r[8] = 0, sid, 0, 1   # END little-endian, ID, 1 Mbps, nível de resposta 1.
        self.sample_hz, self.bus_up_ms, self.imu_ready_ms = sample_hz, bus_up_ms, imu_ready_ms
        self.answer, self.noise = answer, noise
        self.counter, self.samples, self.last_ms = 0, 0, 0.0
        self.muted = set()
        self.block = encode_block(counter=0, status=0x01)

    @property
    def id(self):
        return self.r[5]

    def tick(self, clock_ms=0.0):
        """Avança as amostras pelo relógio virtual: gera dados a cada 1/sample_hz segundo, sem depender das leituras."""
        while clock_ms - self.last_ms >= 1000.0 / self.sample_hz:
            self.last_ms += 1000.0 / self.sample_hz
            self.samples += 1
            self.counter = (self.counter + 1) & 0xFF
            t = self.last_ms / 1000.0
            n = (self.samples % 7 - 3) * 0.02 if self.noise else 0.0   # Pequena variação para mudar o bloco byte a byte.
            if self.last_ms < self.imu_ready_ms:
                self.block = encode_block(gyro_dps=(0, 0, 0), quat_xyz=(0, 0, 0),
                                          counter=self.counter, status=0x01)
            else:
                yaw = 0.3 * math.sin(t)
                self.block = encode_block(
                    gyro_dps=(5.0 * math.sin(t) + n, -2.0 + n, 0.5 + n),
                    quat_xyz=(0.0, 0.0, math.sin(yaw / 2)),
                    counter=self.counter, status=0x00)

    def alive(self, clock_ms):
        return self.answer and clock_ms >= self.bus_up_ms

    def read(self, addr, n, clock_ms=0.0):
        self.tick(clock_ms)
        if addr == BLOCK_ADDR and n == BLOCK_LEN:
            return self.block
        return bytes(self.r[addr:min(addr + n, feetech.DUMP_END)])

    def write(self, addr, data):
        pass          # O protocolo não prevê escrita; se ocorrer, a placa confirma sem alterar os dados.


# ---- Verificações de compatibilidade com o controlador ----
def check(bus, sid=IMU_ID, frames=200, hz=50, full_bus=True, frame_log=None):
    """Consulta a placa com os pacotes do controlador e avalia cada critério. Retorna [(passou?, descrição), ...]."""
    out = []

    def ok(cond, what, level=None):
        out.append((bool(cond), what))
        log(("✓ " if cond else "✗ ") + what, "Barramento", level or ("info" if cond else "warn"))
        return cond

    # 1. Inicialização: aguarda ping por até 5 segundos e registra a primeira resposta.
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5.0:
        if bus.ping(sid) is not None:
            break
        time.sleep(0.05)
    boot_ms = (time.monotonic() - t0) * 1000
    if not ok(bus.ping(sid) is not None, f"PING do ID {sid} respondido ({boot_ms:.0f} ms após ligar)"):
        return out

    # 2. READ unicast consegue ler o bloco (usado pelo console de depuração).
    try:
        _, blk = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)
        ok(len(blk) == BLOCK_LEN, f"READ no endereço {BLOCK_ADDR}, comprimento {BLOCK_LEN}: recebidos {len(blk)} bytes")
        d = decode_block(blk)
        ok(d["reserved"] == 0, f"Byte reservado (byte 14) igual a 0 (valor: {d['reserved']})")
    except Exception as e:
        ok(False, f"READ no endereço {BLOCK_ADDR}: {type(e).__name__}: {e}")
        return out

    # 3. Os registradores de versão/modelo (0–4) são legíveis e END usa little-endian.
    try:
        _, head = bus.read(sid, 0, 5)
        ok(head[2] == 0, f"Ordem de bytes END = 0 (little-endian; valor: {head[2]})")
        log(f"Área de versão 0–4 = {list(head)}", "Barramento")
    except Exception as e:
        ok(False, f"READ no endereço 0, comprimento 5: {type(e).__name__}: {e}")

    # 4. O pacote real do controlador: leitura conjunta dos 16 IDs.
    ids = FULL_IDS if full_bus else [sid]
    stats0 = dict(bus.stats)
    counters, accepted, windows, times, misses, partial = [], 0, [], [], 0, 0
    first_quat_ms = ready_ms = None
    t_start = time.monotonic()
    for k in range(frames):
        t = time.perf_counter()
        got = bus.sync_read(ids, BLOCK_ADDR, BLOCK_LEN)
        times.append((time.perf_counter() - t) * 1000)      # Mede apenas esta chamada, sem o sleep do teste.
        v = got.get(sid)
        if not v:
            misses += 1
        else:
            d = decode_block(v[1])
            counters.append(d["counter"])
            windows.append(d["window_hex"])
            if d["accepted"]:
                accepted += 1
                if first_quat_ms is None:
                    first_quat_ms = (time.monotonic() - t_start) * 1000
                if accepted == READY_FRAMES and ready_ms is None:
                    ready_ms = (time.monotonic() - t_start) * 1000
            if frame_log:
                frame_log.write(json.dumps({
                    "frame": k, "ms": round(times[-1], 3), "counter": d["counter"],
                    "gyro_raw": d["gyro_raw"], "quat_packed": d["quat_packed"],
                    "status": d["status"], "accepted": d["accepted"], "window": d["window_hex"],
                }, ensure_ascii=False) + "\n")
        if full_bus and got:
            partial += sum(1 for i in ids if got.get(i) is None and i != sid)
        time.sleep(max(0.0, 1.0 / hz - (time.perf_counter() - t)))
    dstats = {k: bus.stats[k] - stats0.get(k, 0) for k in bus.stats}

    ok(misses == 0, f"Nenhuma perda da IMU em {frames} quadros (perdidos: {misses})")
    if full_bus:
        ok(partial == 0, f"Os 15 servos também responderam no mesmo sync_read (ausentes: {partial})")
    ok(dstats.get("bad_id", 0) == 0,
       f"Respostas alinhadas (bad_id {dstats.get('bad_id', 0)}); um desalinhamento invalida os 15 dispositivos seguintes")
    ok(dstats.get("bad_checksum", 0) == 0, f"Sem erros de checksum ({dstats.get('bad_checksum', 0)})")

    # 5. Contador de amostras: leitura a 50 Hz e amostragem a 120 Hz devem avançar 1–4 por quadro.
    steps = [(b - a) % 256 for a, b in zip(counters, counters[1:])]
    ok(steps and all(1 <= s <= 4 for s in steps),
       f"Contador de amostras avança 1–4 por quadro (valores: {sorted(set(steps))[:5]}); sempre 0 indica IMU parada com processador do barramento ativo")

    # 6. Congelamento: o controlador compara os primeiros 12 bytes e acusa frozen após 25 quadros iguais.
    run = best = 0
    for a, b in zip(windows, windows[1:]):
        run = run + 1 if a == b else 0
        best = max(best, run)
    ok(best < STALE_RUN_MAX,
       f"Janela de 12 bytes permaneceu igual por até {best} quadros (o controlador acusa frozen a partir de {STALE_RUN_MAX})")

    # 7. Verifica se há quadros aceitos suficientes e quanto tempo leva para ficar pronto.
    ok(accepted >= READY_FRAMES,
       f"O controlador aceitou {accepted} de {frames} quadros (são necessários {READY_FRAMES} para ficar pronto)"
       + (f"; pronto em {ready_ms:.0f} ms" if ready_ms else "; ainda não ficou pronto"))
    if first_quat_ms is not None:
        log(f"Primeiro quaternion válido após {first_quat_ms:.0f} ms", "Barramento")

    # 8. Temporização: mede apenas a transação do barramento; o critério é o orçamento do tick, não o timeout.
    times.sort()
    p99 = times[max(0, int(len(times) * 0.99) - 1)]
    ok(p99 < TICK_BUDGET_MS,
       f"Duração da transação: mín. {times[0]:.2f} / média {sum(times)/len(times):.2f} / p99 {p99:.2f} / máx. {times[-1]:.2f} ms"
       f" (orçamento de {TICK_BUDGET_MS} ms, não timeout de 60 ms)")

    # 9. PING em broadcast não deve receber resposta (manual, §4.1: não usar broadcast PING com vários dispositivos no barramento).
    try:
        bus._send(feetech.BROADCAST, feetech.PING)
        time.sleep(0.01)
        noise = bus.ser.read(64)
        ok(not noise, f"PING em broadcast sem resposta (bytes recebidos: {len(noise)})")
    except Exception as e:
        log(f"Teste de PING em broadcast ignorado: {type(e).__name__}: {e}", "Barramento", "warn")

    # 10. Escreve um registrador: deve confirmar sem afetar os dados (o controlador não escreve, mas o console pode fazê-lo por engano).
    try:
        before = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)[1][:IMU_WINDOW]
        bus.write_u8(sid, 40, 0)
        after = bus.read(sid, BLOCK_ADDR, BLOCK_LEN)[1][:IMU_WINDOW]
        ok(True, "Escrever no registrador não danifica a placa (o bloco continua legível)")
        log(f"12 bytes antes e depois da escrita: {before.hex()} → {after.hex()}", "Barramento", "debug")
    except Exception as e:
        ok(False, f"Não foi possível ler o bloco após escrever no registrador: {type(e).__name__}: {e}")

    log(f"Variação das estatísticas do barramento: {dstats}", "Barramento")
    return out


def run_demo():
    from sim_bus import SimSerial
    port = SimSerial(JOINT_IDS)
    port.latency_ms = 0.25                       # 0,25 ms por pacote, próximo ao tempo de transmissão a 1 Mbps.
    port.servos[IMU_ID] = SimImu200(imu_ready_ms=200)
    bus = feetech.FeetechBus(None, ser=port)
    attach_trace(bus)

    print("== Um sync_read lê a IMU e os 15 servos ao mesmo tempo (como faz o controlador a cada tick) ==")
    for n in range(6):
        got = bus.sync_read(FULL_IDS, BLOCK_ADDR, BLOCK_LEN)
        d = decode_block(got[IMU_ID][1])
        miss = [i for i in JOINT_IDS if got.get(i) is None]
        print(f"  Quadro {n}: contador={d['counter']:>3}, giroscópio {d['gyro_dps'][0]:+6.2f},{d['gyro_dps'][1]:+6.2f},"
              f"{d['gyro_dps'][2]:+6.2f} dps  {'aceito pelo controlador' if d['accepted'] else 'fusão ainda sem dados'}"
              f"  servos ausentes: {len(miss)}")
        time.sleep(0.02)

    print("\n== Verificação de compatibilidade (mesmos critérios de check --port para a placa real) ==")
    bad = sum(not g for g, _ in check(bus, frames=60, frame_log=None))

    print("\n== Placa sem resposta: o sync_read inteiro falha e os dados dos 15 servos também se perdem ==")
    port.servos[IMU_ID].answer = False
    got = bus.sync_read(FULL_IDS, BLOCK_ADDR, BLOCK_LEN)
    lost = [i for i in FULL_IDS if got.get(i) is None]
    print(f"  IMU não respondeu; dados perdidos de {len(lost)}/{len(FULL_IDS)} dispositivos: {lost[:6]}…")
    port.servos[IMU_ID].answer = True

    print("\n== Exemplo de firmware defeituoso: norma² do quaternion = 2 (o controlador e a ferramenta devem rejeitar) ==")
    bad_blk = struct.pack("<hhh", 0, 0, 0) + struct.pack("<HHH", f32_to_f16(1.0), f32_to_f16(1.0),
                                                         f32_to_f16(0.0)) + bytes([9, 0, 0])
    d = decode_block(bad_blk)
    print(f"  norma²={d['norm_sq']:.2f} → aceito pelo controlador? {d['accepted']} (deveria ser False)")
    print(f"\nLogs em {LOG_DIR}")
    return bad


def run_vectors():
    def frame(sid, instr, params):
        ln = len(params) + 2
        body = [sid, ln, instr] + list(params)
        return "ff ff " + " ".join(f"{b:02x}" for b in body + [(~sum(body)) & 0xFF])

    print("sync_read completo enviado pelo controlador a cada tick (16 IDs, 200 primeiro):")
    print("  " + frame(0xFE, feetech.SYNC_READ, [BLOCK_ADDR, BLOCK_LEN] + FULL_IDS))
    print("\nVersão simplificada que consulta apenas o ID 200 (para depuração):")
    print("  " + frame(0xFE, feetech.SYNC_READ, [BLOCK_ADDR, BLOCK_LEN, IMU_ID]))
    print("\nPING do ID 200:")
    print("  " + frame(IMU_ID, feetech.PING, []))
    print("\nResposta · fusão ainda sem dados (quaternion zerado, estado BIT0=1, contador 0):")
    blk = encode_block(counter=0, status=0x01)
    print("  " + frame(IMU_ID, 0x00, list(blk)) + "\n  Dados do bloco: " + " ".join(f"{b:02x}" for b in blk))
    print("\nResposta · com dados (giroscópio +1,75/−0,875/+0,0525 dps, quaternion z=0,3827, contador 7):")
    blk = encode_block(gyro_dps=(1.75, -0.875, 0.0525), quat_xyz=(0.0, 0.0, 0.3827), counter=7)
    print("  " + frame(IMU_ID, 0x00, list(blk)) + "\n  Dados do bloco: " + " ".join(f"{b:02x}" for b in blk))
    d = decode_block(blk)
    print(f"\nDecodificado: giroscópio {d['gyro_raw']} LSB, quaternion {d['quat_packed']} (half), "
          f"aceito pelo controlador={d['accepted']}, gravidade no referencial do tronco {tuple(round(v, 3) for v in d['gravity'])}")


def main():
    ap = argparse.ArgumentParser(description="Bloco IMU ID 200: simulação, vetores de teste e verificação da placa real")
    ap.add_argument("cmd", choices=["demo", "vectors", "check"])
    ap.add_argument("--port", help="Porta serial da placa real (para check)")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--only-imu", action="store_true", help="Consulta apenas o ID 200, sem os 15 servos")
    a = ap.parse_args()
    if a.cmd == "demo":
        sys.exit(run_demo() and 1)
    if a.cmd == "vectors":
        return run_vectors()
    if not a.port:
        sys.exit("O comando check exige --port, por exemplo: --port COM6")
    bus = feetech.FeetechBus(a.port, a.baud)
    attach_trace(bus)
    os.makedirs(LOG_DIR, exist_ok=True)
    fl = open(os.path.join(LOG_DIR, f"imu200-frames-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"),
              "w", encoding="utf-8")
    try:
        log(f"Verificando o ID {IMU_ID} em {a.port} @ {a.baud}, por {a.frames} quadros", "Barramento")
        bad = sum(not g for g, _ in check(bus, frames=a.frames,
                                          full_bus=not a.only_imu, frame_log=fl))
        print("\nTodos os critérios passaram" if not bad else f"\nCritérios não aprovados: {bad}")
        print(f"Logs: {LOG_DIR}")
        sys.exit(1 if bad else 0)
    finally:
        fl.close()
        bus.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
