"""Inspeção dos servos (servo_report.py): executa no simulador em nível de protocolo,
confere os critérios e garante que nenhum comando de gravação seja enviado.
Run: python -m pytest -q test_servo_report.py
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

import feetech
import servo_report
from sim_bus import SimSerial

IDS = [20, 21, 22, 23]


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.port = SimSerial([20, 22, 23])            # ID 21 não está no barramento (servo queimado ou desconectado).
        sv = {s.id: s for s in self.port.servos.values()}
        sv[20].r[19] = 1 + 4 + 8 + 32                  # Todas as proteções necessárias estão ativadas.
        sv[22].r[19] = 4                               # Padrão de fábrica: somente superaquecimento ativado.
        sv[23].r[19] = 1 + 4 + 8
        sv[23].r[65] = 8                               # Alerta de sobrecorrente ativo.
        sv[23].off = -300
        for s in sv.values():
            s.r[14], s.r[15] = 84, 40                  # Faixa de tensão 4,0–8,4 V; tensão simulada de 7,4 V.
        self.sent = []
        handle = self.port._handle
        self.port._handle = lambda sid, instr, p: (self.sent.append(instr), handle(sid, instr, p))[1]
        self.bus = feetech.FeetechBus(None, ser=self.port)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_report(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            base, rows = servo_report.run(self.bus, IDS, "SIM", self.tmp.name)
        return base, {r["id"]: r for r in rows}, out.getvalue()

    def test_flags_and_files(self):
        base, rows, out = self.run_report()
        self.assertFalse(rows[21]["online"])
        self.assertIn("PING sem resposta", rows[21]["red"][0])
        self.assertEqual((rows[20]["red"], rows[20]["yellow"]), ([], []))
        self.assertTrue(any("desativadas: Sobrecorrente, Tensão" in x for x in rows[22]["red"]))
        self.assertTrue(any("Proteção contra sobrecarga" in x for x in rows[22]["yellow"]))
        self.assertTrue(any("Registrador de estado 65 = 8: alerta ativo — Sobrecorrente" in x for x in rows[23]["red"]))
        self.assertTrue(any("Deslocamento de -300 passos" in x for x in rows[23]["yellow"]))
        md = open(base + ".md", encoding="utf-8").read()
        self.assertIn("Servos online: 3/4; com alertas vermelhos: 3", md)
        raw = json.load(open(base + ".json", encoding="utf-8"))
        self.assertEqual(len(raw["servos"][0]["raw"]), feetech.DUMP_END)

    def test_read_only(self):
        self.run_report()
        writes = {feetech.WRITE, feetech.SYNC_WRITE, feetech.CALIBRATE, feetech.REBOOT}
        self.assertTrue(self.sent)
        self.assertFalse(writes & set(self.sent), f"Comandos de gravação enviados: {set(self.sent) & writes}")


if __name__ == "__main__":
    unittest.main()
