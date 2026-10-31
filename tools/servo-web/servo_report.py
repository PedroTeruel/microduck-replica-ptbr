# -*- coding: utf-8 -*-
"""Inspeção dos servos: um comando lê as configurações de proteção e o estado atual
de cada servo e salva um relatório. **Somente leitura; não grava em nenhum registrador.**

  python servo_report.py --port COM5                 # Padrão: 15 unidades, IDs 20-24,30-34,10-14
  python servo_report.py --port COM5 --ids 21        # Quando apenas o servo 21 está conectado ao barramento
  python servo_report.py --port COM5 --scan-all      # Varre 0–253 se o ID for desconhecido (servos novos vêm com ID 1)

O relatório é salvo em logs/inspecao-data-hora.md (legível por pessoas) e no arquivo
.json correspondente (valores brutos dos registradores 0–86 de cada servo).
A porta serial não pode estar em uso pelo painel de depuração (server.py) ou pelo FD;
feche-os antes. Os critérios seguem a etapa 5 do registro de depuração: as proteções
contra superaquecimento (4), sobrecorrente (8) e sobretensão (1) devem estar ativadas;
itens desativados são destacados em vermelho."""
import argparse
import json
import os
import sys
import time

import feetech

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_IDS = "20-24,30-34,10-14"
NAMES = {20: "Quadril esquerdo yaw", 21: "Quadril esquerdo roll", 22: "Quadril esquerdo pitch", 23: "Joelho esquerdo", 24: "Tornozelo esquerdo",
         30: "Pescoço pitch", 31: "Cabeça pitch", 32: "Cabeça yaw", 33: "Cabeça roll", 34: "Boca",
         10: "Quadril direito yaw", 11: "Quadril direito roll", 12: "Quadril direito pitch", 13: "Joelho direito", 14: "Tornozelo direito"}
# Significado de cada bit das condições de desligamento (19) e do estado (65).
BITS = {1: "Tensão", 2: "Codificador magnético", 4: "Superaquecimento", 8: "Sobrecorrente", 32: "Sobrecarga"}
MUST = (4, 8, 1)          # Etapa 5 do registro de depuração: superaquecimento vem ativado; ative sobrecorrente e sobretensão


def parse_ids(text):
    ids = []
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            ids.extend(range(int(a), int(b) + 1))
        elif part:
            ids.append(int(part))
    return ids


def bits_text(v):
    on = [n for b, n in BITS.items() if v & b]
    return ", ".join(on) if on else "nenhuma"


def examine(bus, sid):
    """Lê um servo: PING → exporta 0–86 → decodifica → classifica alertas.
    Retorna uma linha de resultado; a etapa com falha fica registrada em step."""
    row = {"id": sid, "name": NAMES.get(sid, ""), "online": False, "red": [], "yellow": [], "info": []}
    step = "PING"
    try:
        if bus.ping(sid) is None:
            row["red"].append("PING sem resposta: verifique alimentação, cabos, ID ou possível dano ao driver")
            return row
        row["online"] = True
        step = "Exportar registradores 0–86"
        d = bus.dump(sid)
    except Exception as e:
        row["red"].append(f"Falha na etapa \"{step}\": {type(e).__name__}: {e}")
        return row
    v = {r["addr"]: r["value"] for r in d["rows"]}
    row["raw"] = d["raw"]
    s15 = feetech.sign15
    row.update({
        "firmware": f"{v[0]}.{v[1]}", "servo_ver": f"{v[3]}.{v[4]}",
        "unload": v[19], "status": v[65], "temp_c": v[63], "volt": v[62] / 10,
        "volt_range": (v[15] / 10, v[14] / 10), "temp_limit": v[13],
        # Converte as unidades de 38 / 35 para 10 ms e também registra o valor bruto.
        # A unidade ainda não foi confirmada no hardware real.
        "protect_ma": round(v[28] * 6.5), "overcurrent_raw": v[38], "protect_time_raw": v[35],
        "overload_pct": v[36], "max_torque": v[16], "torque_limit": v[48],
        "angle_limit": (v[9], v[11]), "offset": s15(v[31]), "pos": s15(v[56]), "goal": s15(v[42]),
        "current_ma": round(s15(v[69]) * 6.5), "load_pct": feetech.sign10(v[60]) / 10,
        "torque_on": v[40], "lock": v[55], "mode": v[33], "baud": v[6], "reply_level": v[8],
    })
    missing = [BITS[b] for b in MUST if not v[19] & b]
    if missing:
        row["red"].append(f"Condições de desligamento 19 = {v[19]} (ativadas: {bits_text(v[19])}); desativadas: {', '.join(missing)}")
    if not v[19] & 32:
        row["yellow"].append("Proteção contra sobrecarga (32) desativada: ela desliga o servo se a carga exceder o torque de sobrecarga pelo tempo de proteção; oferece uma camada extra em caso de travamento")
    if v[65]:
        row["red"].append(f"Registrador de estado 65 = {v[65]}: alerta ativo — {bits_text(v[65])}")
    lo, hi = row["volt_range"]
    if not lo <= row["volt"] <= hi:
        row["red"].append(f"Tensão de {row['volt']:.1f} V fora da faixa configurada no servo ({lo:.1f}–{hi:.1f} V)")
    if v[63] >= 60:
        row["yellow"].append(f"Temperatura de {v[63]} °C elevada (torque é desligado no limite de {v[13]} °C)")
    if abs(row["offset"]) > 200:
        row["yellow"].append(f"Deslocamento de {row['offset']} passos ({row['offset'] * 360 / 4096:+.1f}°), muito alto: o disco do servo pode ter sido montado com vários dentes de diferença ou girado meia volta")
    if v[33] != 4:
        row["yellow"].append(f"Modo de operação 33 = {v[33]}; o registro de depuração recomenda 4 (PD de posição pura)")
    if (v[9], v[11]) == (0, 4095):
        row["info"].append("Sem limites de ângulo configurados (0–4095): o servo tentará alcançar qualquer posição comandada, inclusive além do limite mecânico")
    return row


def report_md(rows, port, t):
    L = [f"# Inspeção dos servos {t}", "", f"Porta serial {port}; somente leitura, nenhum registrador foi gravado. Consulte os critérios no início de servo_report.py.", ""]
    online = [r for r in rows if r["online"]]
    reds = [r for r in rows if r["red"]]
    L.append(f"**Servos online: {len(online)}/{len(rows)}; com alertas vermelhos: {len(reds)}**" + (f": {' '.join(str(r['id']) for r in reds)}" if reds else ""))
    L += ["", "| ID | Junta | Online | Condições de desligamento 19 | Estado 65 | Temperatura | Tensão | Corrente | Leitura | Deslocamento | Torque | Firmware |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["online"]:
            L.append(f"| {r['id']} | {r['name']} | ✗ | | | | | | | | | |")
            continue
        L.append(f"| {r['id']} | {r['name']} | ✓ | {r['unload']}（{bits_text(r['unload'])}） | {r['status']}（{bits_text(r['status'])}） "
                 f"| {r['temp_c']} °C | {r['volt']:.1f} V | {r['current_ma']} mA | {r['pos']} | {r['offset']:+d} "
                 f"| {'Ativado' if r['torque_on'] else 'Desativado'} | {r['firmware']} |")
    L += ["", "## Problemas por servo", ""]
    for r in rows:
        items = [f"- 🔴 {x}" for x in r["red"]] + [f"- 🟡 {x}" for x in r["yellow"]] + [f"- {x}" for x in r["info"]]
        if items:
            L += [f"**#{r['id']} {r['name']}**", *items, ""]
    L += ["## Parâmetros de proteção (servos online)", "", "| ID | Corrente de proteção | Tempo de proteção contra sobrecorrente 38 | Torque de sobrecarga | Tempo de proteção 35 | Limite de temperatura | Torque máximo 16 | Limite de torque 48 | Limite de ângulo |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in online:
        L.append(f"| {r['id']} | {r['protect_ma']} mA | {r['overcurrent_raw']} (em unidades de 10 ms: {r['overcurrent_raw'] * 10} ms) | {r['overload_pct']} % "
                 f"| {r['protect_time_raw']} (em unidades de 10 ms: {r['protect_time_raw'] * 10} ms) "
                 f"| {r['temp_limit']} °C | {r['max_torque']} | {r['torque_limit']} | {r['angle_limit'][0]}–{r['angle_limit'][1]} |")
    return "\n".join(L) + "\n"


def run(bus, ids, port, out_dir):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for sid in ids:
        r = examine(bus, sid)
        if r["online"] or len(ids) <= 32:          # Em varreduras de 0–253, mantém apenas os servos online.
            rows.append(r)
        mark = "✗" if not r["online"] else ("🔴" if r["red"] else ("🟡" if r["yellow"] else "✓"))
        if r["online"] or len(ids) <= 32:
            print(f"#{sid:<3} {r['name']:<8} {mark}  " + "；".join(r["red"] + r["yellow"])[:160], flush=True)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, "inspecao-" + time.strftime("%Y%m%d-%H%M%S"))
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(report_md(rows, port, t))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"time": t, "port": port, "servos": rows}, f, ensure_ascii=False, indent=1)
    return base, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inspeção dos servos (somente leitura)")
    ap.add_argument("--port", required=True, help="Porta serial, por exemplo COM5 ou /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=1_000_000)
    ap.add_argument("--ids", default=DEFAULT_IDS)
    ap.add_argument("--scan-all", action="store_true", help="Varre os IDs 0–253 e relata somente os servos online")
    ap.add_argument("--out", default=os.path.join(HERE, "logs"))
    a = ap.parse_args(argv)
    ids = list(range(0, 254)) if a.scan_all else parse_ids(a.ids)
    try:
        bus = feetech.FeetechBus(a.port, a.baud)
    except Exception as e:
        raise SystemExit(f"Não foi possível abrir a porta serial {a.port}: {type(e).__name__}: {e} (feche o painel de depuração ou o FD, se estiverem usando a porta)")
    try:
        base, rows = run(bus, ids, a.port, a.out)
    finally:
        bus.close()
    reds = [r["id"] for r in rows if r["red"]]
    print(f"\nOnline: {sum(r['online'] for r in rows)}/{len(rows)}; alertas vermelhos: {reds or 'nenhum'}")
    print(f"Relatório: {base}.md\nRegistradores brutos: {base}.json")
    return 1 if reds else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
