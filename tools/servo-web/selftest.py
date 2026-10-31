# -*- coding: utf-8 -*-
"""Autoteste do backend do console: executa operações que escrevem nos servos usando server.handle e FeetechBus reais com o simulador de protocolo sim_bus.

  python selftest.py

Após alterar a comunicação com os servos em feetech.py ou server.py, execute este teste antes de usar o hardware real.
Não acessa servos reais nem os diretórios poses/ e calib/ do repositório (usa diretórios temporários).
"""
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
import feetech
import server
from sim_bus import SimSerial

IDS = [20, 21, 22, 23, 24, 30, 31, 32, 33, 34, 10, 11, 12, 13, 14]
FAILS = []


def check(cond, what):
    print(("  ✓ " if cond else "  ✗ ") + what)
    if not cond:
        FAILS.append(what)


def main():
    tmp = tempfile.mkdtemp(prefix="servo-web-selftest-")
    server.CALIB_DIR = os.path.join(tmp, "calib")
    server.POSES_DIR = os.path.join(tmp, "poses")
    server.LOG_DIR = os.path.join(tmp, "logs")
    server.DIRS_FILE = os.path.join(tmp, "directions.json")   # Igual ao hardware: os 15 servos com −1; não lê o arquivo do repositório.
    with open(server.DIRS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(i): -1 for i in IDS}, f)
    os.makedirs(server.POSES_DIR)
    # Posiciona os servos longe de 2048.
    start = {i: 2048 + (k * 37 - 250) for k, i in enumerate(IDS)}
    port = SimSerial(IDS, phys=start)
    server.BUS = feetech.FeetechBus(None, ser=port)
    server.IDS = IDS
    server.PRESENT = []
    H = server.handle
    sv = {s.r[5]: s for s in port.servos.values()}

    print("Busca e leitura do estado")
    H({"op": "scan"})
    check(server.PRESENT == IDS, f"Os 15 servos estão online ({len(server.PRESENT)})")
    st = server.BUS.states(IDS)
    check(all(st[i]["pos"] == start[i] for i in IDS), "As posições da leitura sincronizada correspondem")

    print("Salva uma pose com torque ativado, sem mover os servos")
    H({"op": "torque", "on": 1})
    H({"op": "save_pose", "name": "Pose de teste"})
    before = {i: sv[i].phys for i in IDS}

    print("Calibração de um toque para a posição zero (torque ativado, 0x0B)")
    r = H({"op": "calib_mid_all", "ids": IDS})
    check(len(r["ok"]) == 15 and not r["bad"], f"15 servos calibrados ({len(r['ok'])} sucessos, falhas: {r['bad']})")
    check(all(sv[i].calibrations == 1 for i in IDS), "Cada servo foi realmente calibrado (sem ser puxado para outra posição)")
    check(all(sv[i].phys == before[i] for i in IDS), "As posições físicas não mudaram")
    st = server.BUS.states(IDS)
    check(all(abs(st[i]["pos"] - 2048) <= 1 for i in IDS), "Todos leem 2048 após a calibração")
    check(all(sv[i].r[55] == 1 for i in IDS), "Todos foram bloqueados novamente")
    check(all(sv[i].r[40] == 1 for i in IDS), "O torque foi reativado")
    poses = server.list_poses()
    p = [x for x in poses if x["name"] == "Pose de teste"][0]
    check(all(abs(p["goals"][i] - 2048) <= 1 for i in IDS), "A pose salva foi convertida para o novo zero (a mesma pose agora corresponde a 2048)")

    print("Voltar ao zero não deve mover os servos")
    H({"op": "goals", "goals": {str(i): 2048 for i in IDS}})
    server.BUS.states(IDS)
    check(all(sv[i].phys == before[i] for i in IDS), "A posição física permanece igual após enviar 2048")

    print("Desfaz a calibração")
    r = H({"op": "calib_undo"})
    check(len(r["ok"]) == 15, f"Deslocamentos restaurados para os 15 servos ({len(r['ok'])})")
    st = server.BUS.states(IDS)
    check(all(st[i]["pos"] == start[i] for i in IDS), "As leituras voltaram aos valores anteriores à calibração")
    check(all(sv[i].phys == before[i] for i in IDS), "A posição física também permaneceu igual ao desfazer")
    check(all(sv[i].r[55] == 1 for i in IDS), "Todos foram bloqueados após desfazer")
    p = [x for x in server.list_poses() if x["name"] == "Pose de teste"][0]
    check(all(p["goals"][i] == start[i] for i in IDS), "A pose salva voltou aos valores originais")

    print("Uma pose salva após calibrar também deve ser ajustada ao desfazer")
    H({"op": "calib_mid_all", "ids": IDS})
    H({"op": "save_pose", "name": "Salva após calibrar"})
    phys_at_save = {i: sv[i].phys for i in IDS}     # Posição física de cada junta no momento em que a pose é salva.
    H({"op": "calib_undo"})
    after = [x for x in server.list_poses() if x["name"] == "Salva após calibrar"][0]["goals"]
    # Garantia: após desfazer, enviar esta pose retorna as juntas à posição física em que ela foi salva.
    want = {i: round(phys_at_save[i] + sv[i].off) for i in IDS}
    worst = max(abs(after[i] - want[i]) for i in IDS)
    check(worst <= 2, f"Após desfazer, os valores da pose ainda representam a posição física em que foi salva (diferença máxima: {worst} passos)")
    server.delete_pose([x for x in server.list_poses() if x["name"] == "Salva após calibrar"][0]["file"])

    print("Calibra pela pose dobrada oficial: alvos = ângulos FOLD oficiais × sentido; o zero passa a 2048 e as poses salvas são convertidas")
    fold_ids = IDS                                      # Pernas dobradas e cabeça/pescoço alinhados conforme o padrão oficial; calibra os 15 juntos.
    H({"op": "save_pose", "name": "Salva antes da dobra"})
    saved_before = [x for x in server.list_poses() if x["name"] == "Salva antes da dobra"][0]["goals"]
    phys = {i: sv[i].phys for i in IDS}
    _, want = server.official_targets("@official:FOLD")
    r = H({"op": "calib_mid_all", "ids": fold_ids, "ref": "@official:FOLD"})
    st = server.BUS.states(IDS)
    check(sorted(r["ok"]) == sorted(fold_ids), f"Os 15 servos foram calibrados ({len(r['ok'])} sucessos, falhas: {r['bad']})")
    check(all(want[i] == 2048 for i in (20, 21, 24, 30, 31, 32, 33, 34, 10, 11, 14)),
          "Os alvos são 2048, exceto para joelho e inclinação do quadril (inclui alinhar cabeça/pescoço e fechar a boca)")
    check(all(abs(st[i]["pos"] - want[i]) <= 1 for i in fold_ids),
          "As leituras correspondem à pose dobrada oficial (" + " ".join(f"{i}→{want[i]}" for i in fold_ids) + ")")
    check(all(sv[i].phys == phys[i] for i in IDS), "A posição física não mudou")
    check((want[22], want[23], want[12], want[13]) == (1025, 1025, 3071, 3071),
          f"Com todos os sentidos em −1: inclinação do quadril esquerdo/joelho esquerdo = 1025; quadril direito/joelho direito = 3071 ({want[22]} {want[23]} {want[12]} {want[13]})")
    saved_after = [x for x in server.list_poses() if x["name"] == "Salva antes da dobra"][0]["goals"]
    check(all(abs((saved_after[i] - saved_before[i]) - (st[i]["pos"] - start_fold)) <= 1
              for i, start_fold in ((i, saved_before[i]) for i in fold_ids)),
          "A pose salva antes da dobra foi convertida (mesma posição física, novas leituras)")
    r = H({"op": "calib_undo"})
    check(len(r["ok"]) == 15 and all(sv[i].phys == phys[i] for i in IDS), "A calibração pela pose dobrada pode ser desfeita sem mover as juntas")
    check([x for x in server.list_poses() if x["name"] == "Salva antes da dobra"][0]["goals"] == saved_before, "A pose voltou aos valores originais após desfazer")
    server.delete_pose([x for x in server.list_poses() if x["name"] == "Salva antes da dobra"][0]["file"])

    print("Calibra pela pose dobrada oficial com torque desligado (uso real: posicionar à mão); abre a pose manualmente após calibrar e reativa o torque sem saltos")
    H({"op": "torque", "on": 0})
    for i in IDS:                                       # Posiciona manualmente para calibrar; o zero ainda não foi calibrado. O joelho direito difere 150° por causa da montagem.
        sv[i].phys = want[i] - sv[i].off + (1700 if i == 13 else 5)
    plan = H({"op": "calib_plan", "ids": IDS, "ref": "@official:FOLD", "for": "all"})
    rows = {x["id"]: x for x in plan["rows"]}
    check(rows[22]["target"] == 1025 and rows[22]["diff_deg"] == -0.4 and rows[13]["diff_deg"] == -149.4,
          f"Prévia: posição atual → alvo e diferença angular (#22 {rows[22]['pos']}→{rows[22]['target']} {rows[22]['diff_deg']}°, #13 {rows[13]['diff_deg']}°)")
    phys = {i: sv[i].phys for i in IDS}
    r = H({"op": "calib_mid_all", "ids": IDS, "ref": "@official:FOLD"})
    st = server.BUS.states(IDS)
    check(sorted(r["ok"]) == sorted(IDS) and list(r["big"]) == ["13"], f"Os 15 foram calibrados; #13, com grande diferença, foi calibrado e sinalizado ({r['big']})")
    check(all(abs(st[i]["pos"] - want[i]) <= 1 for i in IDS), "As leituras correspondem à pose dobrada usada na calibração")
    check(all(sv[i].r[40] == 0 for i in IDS), "O torque estava desligado e continua desligado")
    check(all(sv[i].goal == st[i]["pos"] for i in IDS), "Registrador de alvo = leitura atual")
    check(all(sv[i].phys == phys[i] for i in IDS), "As juntas não se moveram")
    for i in IDS:                                       # Abre o pato manualmente.
        sv[i].phys = 2048 - sv[i].off
    r = H({"op": "torque", "on": 1})
    server.BUS.states(IDS)
    check(len(r["aligned"]) == 15 and not r["bad"], f"Os alvos dos 15 servos foram alinhados às posições atuais antes de ativar o torque ({len(r['aligned'])})")
    check(all(sv[i].phys == 2048 - sv[i].off for i in IDS), "As juntas não se moveram ao ativar o torque e não voltaram bruscamente à pose dobrada")
    H({"op": "calib_undo"})

    print("Enviar uma pose com torque desligado e reativá-lo não deve causar saltos")
    H({"op": "torque", "ids": [24], "on": 0})
    H({"op": "goals", "goals": {"24": 2800}})          # O alvo enviado com torque desligado permanece no servo.
    sv[24].phys = 1900 - sv[24].off
    H({"op": "torque", "ids": [24], "on": 1})
    server.BUS.states([24])
    check(sv[24].phys == 1900 - sv[24].off and sv[24].goal == 1900, "Ao ativar o torque, permanece no lugar (o alvo mudou para 1900, não 2800)")

    print("Calibração por pose: posiciona o pato agachado e ajusta as leituras aos valores salvos na pose 'Agachado'")
    H({"op": "save_pose", "name": "Agachado"})
    H({"op": "save_pose", "name": "Outra pose"})
    ref = [x for x in server.list_poses() if x["name"] == "Agachado"][0]
    other_before = [x for x in server.list_poses() if x["name"] == "Outra pose"][0]["goals"]
    legs = [22, 23, 24, 12, 13, 14]
    H({"op": "torque", "ids": legs, "on": 0})          # Deixa o pato agachado no chão com o torque das pernas desligado.
    for i in legs:                                     # Simula a reinstalação do braço do servo: a leitura muda 7 passos na mesma posição física.
        sv[i].off += 7
    phys = {i: sv[i].phys for i in IDS}
    r = H({"op": "calib_mid_all", "ids": legs, "ref": ref["file"]})
    st = server.BUS.states(IDS)
    check(sorted(r["ok"]) == sorted(legs), f"As seis juntas das pernas foram calibradas ({r['ok']}; falhas: {r['bad']})")
    check(all(st[i]["pos"] == ref["goals"][i] for i in legs), "As leituras voltaram aos valores salvos na pose 'Agachado'")
    check(all(sv[i].phys == phys[i] for i in IDS), "A posição física não mudou")
    now = {x["name"]: x["goals"] for x in server.list_poses()}
    check(now["Agachado"] == ref["goals"], "A pose de referência não foi alterada")
    check(now["Outra pose"] == other_before, "A outra pose também não foi alterada (usa o mesmo referencial)")
    H({"op": "calib_undo"})
    st = server.BUS.states(IDS)
    check(all(st[i]["pos"] == ref["goals"][i] + 7 for i in legs), "Ao desfazer, as leituras voltam a ficar deslocadas em 7 passos")

    print("Servo não reconhece 0x0B: usa automaticamente a alternativa (calcula e grava o deslocamento no registrador 31)")
    sv[31].support_0b = False
    H({"op": "goals", "goals": {"31": 2300}})
    server.BUS.states([31])
    p31 = sv[31].phys
    r = H({"op": "calibrate", "id": 31})
    st = server.BUS.states([31])
    check(r["ok"] == [31], f"A alternativa calibrou o servo (falhas: {r['bad']})")
    check(abs(p31 + sv[31].off - 2048) <= 2, "A alternativa também calibra a posição preparada para 2048")
    check(abs(sv[31].phys - p31) <= 20 and sv[31].r[40] == 1 and sv[31].r[55] == 1, "A junta não foi puxada; torque restaurado e servo bloqueado")
    sv[31].support_0b = True

    print("Nem 0x0B nem a gravação do deslocamento são aceitos: restaura o deslocamento e não deixa a operação pela metade")
    sv[31].support_0b = False
    sv[31].ignore_offset_writes = True
    H({"op": "goals", "goals": {"31": 2300}})     # Afasta da posição para que "já estar em 2048" não seja considerado sucesso.
    server.BUS.states([31])
    o31 = sv[31].off
    r = H({"op": "calibrate", "id": 31})
    check(not r["ok"] and "31" in r["bad"], f"A falha foi informada ({r['bad'].get('31', '')[:40]})")
    check(sv[31].off == o31, "O deslocamento original foi restaurado")
    sv[31].support_0b = True
    sv[31].ignore_offset_writes = False

    print("Gravar 128 não tem efeito no HD-1910 (o simulador corresponde ao hardware real)")
    sv[32].calibrations = 0
    server.BUS.unlock(32)
    server.BUS.write_u8(32, 40, 0)
    server.BUS.write_u8(32, 40, 128)
    server.BUS.lock(32)
    check(sv[32].calibrations == 0, "Desbloquear, desligar o torque e gravar 128 não calibra")

    print("Botão de calibração central de um único servo")
    r = H({"op": "calibrate", "id": 32})
    check(r["ok"] == [32] and sv[32].calibrations == 1, "Um único servo também segue o mesmo fluxo")

    print("Desconexão durante o processo: não consegue ler a posição após 0x0B")
    sv[33].mute_after_calib = {56}
    r = H({"op": "calibrate", "id": 33})
    sv[33].mute_after_calib.clear(); sv[33].muted.clear()
    why = r["bad"].get("33", "")
    check("parou em '" in why, f"A causa da falha informa em qual etapa parou ({why[:40]}…)")
    check(sv[33].r[55] == 1, "O servo foi bloqueado novamente mesmo após o erro (finally)")
    check(sv[33].r[40] == 0, "Se não consegue ler a posição, não reativa o torque para evitar puxar a junta ao alvo antigo")
    line = [e for e in server.LOG if e["cat"] == "Calibração" and e["msg"].startswith("#33") and e["level"] == "warn"]
    check(bool(line) and "bloqueio✓" in line[-1]["msg"], "A linha do log contém o resultado de cada etapa")
    with open(server.log_path(), encoding="utf-8") as f:
        text = f.read()
    check("Traceback" in text and "[Calibração][ERRO]" in text, "O arquivo de log contém a categoria e o traceback")
    H({"op": "torque", "id": 33, "on": 1})

    print("Dados seriais brutos de envio e recepção gravados no arquivo de log")
    server.BUS.trace = server.bus_trace
    H({"op": "calibrate", "id": 32})
    text = open(server.log_path(), encoding="utf-8").read()
    check("→ #32 calibração de posição" in text, "O pacote 0x0B enviado foi registrado (incluindo hexadecimal)")
    check("endereço 40 'interruptor de torque'" in text and "endereço 31" in text, "As leituras e gravações de registradores incluem endereço e nome")
    check("← #32 estado 0x00" in text, "A resposta do servo também foi registrada")
    check("SYNC_READ" not in text, "A consulta de estado a 10 Hz não é registrada para evitar encher o log")
    server.BUS.trace = None

    print("Categorias do log")
    cats = {e["cat"] for e in server.LOG}
    check({"Barramento", "Movimento", "Calibração", "Poses"} <= cats, f"Categorias encontradas: {sorted(cats)}")
    ok_line = [e for e in server.LOG if e["cat"] == "Calibração" and e["msg"].startswith("#20 ")]
    check(bool(ok_line) and "deslocamento" in ok_line[0]["msg"] and "0x0B→2048✓" in ok_line[0]["msg"], "O log registra o deslocamento antes/depois e cada etapa também para calibrações bem-sucedidas")
    if ok_line:
        print("    Exemplo: " + ok_line[0]["msg"])

    print("Juntas sujeitas a ceder (no hardware, o pescoço cede 0,62 passos/ms; cada pacote do barramento leva 1,5 ms)")
    port.latency_ms = 1.5
    for i in IDS:
        sv[i].droop = 0.62
    H({"op": "torque", "on": 1})
    server.BUS.states(IDS)
    held = {i: sv[i].phys for i in IDS}          # Torque ativado; os servos mantêm a posição.
    r = H({"op": "calib_mid_all", "ids": IDS})
    st = server.BUS.states(IDS)
    check(len(r["ok"]) == 15, f"Os 15 servos foram calibrados ({len(r['ok'])} sucessos, falhas: {list(r['bad'])[:3]})")
    # Métrica real de precisão: a posição física preparada deve ser lida como 2048 no novo referencial.
    # Não é possível evitar alguns passos de queda por gravidade; o objetivo é impedir que isso deteriore o zero.
    worst = max(abs(held[i] + sv[i].off - 2048) for i in IDS)
    check(worst <= 2, f"A posição preparada é lida como 2048 após calibrar (erro máximo: {worst:.0f} passos = {worst * 360 / 4096:.2f}°)")
    yank = max(abs(sv[i].phys - held[i]) for i in IDS)
    check(yank <= 20, f"A junta não foi puxada (movimento máximo: {yank:.1f} passos, devido à queda durante os milissegundos sem torque)")
    for i in IDS:
        sv[i].droop = 0.0
    port.latency_ms = 0.0
    H({"op": "calib_undo"})

    print("Exportação dos registradores")
    r = H({"op": "dump", "id": 20})
    check(len(r["raw"]) == feetech.DUMP_END, f"Lidos {len(r['raw'])} bytes, até o endereço 86")

    print("Desbloqueio, gravação de registrador e alteração do ID")
    H({"op": "write_reg", "id": 21, "addr": 21, "size": 1, "value": 40, "unlock": True})
    check(sv[21].r[21] == 40 and sv[21].r[55] == 1, "Gravou P=40 e bloqueou o servo novamente")
    ok = server.BUS.set_id(34, 35)
    check(ok and sv[34].r[5] == 35 and sv[34].r[55] == 1, "ID alterado de 34 → 35 com sucesso e servo bloqueado")

    shutil.rmtree(tmp)
    print()
    print("Todos os critérios passaram" if not FAILS else f"Critérios não aprovados ({len(FAILS)}): {FAILS}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
