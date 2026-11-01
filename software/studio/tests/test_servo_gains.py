"""Ao habilitar o torque, os ganhos P/D e o limite devem corresponder aos do programa principal (padrão P5, D0 e limite 1000).

Compara com o firmware do fork: grava RAM 48..51 em um pacote, confere a leitura de retorno e preserva a EEPROM e a flag de trava.
Usa o simulador de protocolo; os servos iniciam com P32, D40 e limite 1000 de fábrica.
"""
import json
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "deps")]

from studio.bus import feetech  # noqa: E402
from studio.log import Log  # noqa: E402
from studio.servo import IDS, ServoSession  # noqa: E402
from studio.servo_ops import MainGains, _walk_contract, contract_kp, load_servo_params  # noqa: E402

FORK = Path(os.environ["MICRODUCK_FORK"]) if os.environ.get("MICRODUCK_FORK") else None
FORK_WALK = FORK / "packaging" / "models" / "1cbf8730eadd75a5704332c9f3c10f60" / "deployment-contract.json" if FORK else None


def run_gains(sv):
    """Ganhos P/D e limite de torque em operação no servo simulado: RAM 50, 51 e 48..49."""
    return sv.r[50], sv.r[51], sv.r[48] | sv.r[49] << 8


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def bump(path, n):
    """Altera o mtime para garantir que duas gravações próximas sejam detectadas."""
    t = time.time() + n
    os.utime(path, (t, t))


class Recorder:
    """Registra cada pacote do barramento para verificar a ordem e os registradores gravados."""

    def __init__(self, ser):
        self.packets = []
        orig = ser._handle

        def handle(sid, instr, p):
            self.packets.append((sid, instr, bytes(p)))
            return orig(sid, instr, p)
        ser._handle = handle

    def writes(self):
        """Retorna WRITE e SYNC_WRITE como uma lista de índice, endereço e dados por ID."""
        out = []
        for n, (sid, instr, p) in enumerate(self.packets):
            if instr == feetech.WRITE:
                out.append((n, p[0], {sid: p[1:]}))
            elif instr == feetech.SYNC_WRITE:
                addr, ln, rest = p[0], p[1], p[2:]
                out.append((n, addr, {rest[k]: rest[k + 1:k + 1 + ln] for k in range(0, len(rest), ln + 1)}))
        return out

    def first_torque_on(self, sid):
        return next((n for n, a, d in self.writes() if a == 40 and d.get(sid, b"\x00")[:1] == b"\x01"), None)

    def gains_writes(self, sid):
        return [n for n, a, d in self.writes() if a == 48 and len(d.get(sid, b"")) == 4]


# ---------------- Parâmetros de torque do programa principal (sem acesso ao barramento) ----------------

class MainGainsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.params = self.dir / "servo-test-parameters.json"
        self.toml = self.dir / "robotd.toml"
        self.warns = []

    def tearDown(self):
        self.tmp.cleanup()

    def mg(self, tomls=None):
        return MainGains(params_path=str(self.params), robotd_tomls=tomls if tomls is not None else (str(self.toml),),
                         log=lambda msg, cat="Barramento", level="info": self.warns.append((cat, level, msg)))

    def test_no_files_is_v167_default_5_0_1000(self):
        g = MainGains(params_path=str(self.dir / "nope" / "servo-test-parameters.json"), robotd_tomls=()).get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (5, 0, 1000, "Padrão do programa principal"))
        self.assertIn("sem configuração do programa principal", g["detail"])
        self.assertIsNone(g["warn"])

    def test_valid_file_wins(self):
        write_json(self.params, {"kp": 3, "kd": 1, "torque_limit": 681})
        g = self.mg().get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (3, 1, 681, "Arquivo de parâmetros"))
        self.assertEqual(self.warns, [])

    def test_bad_or_out_of_range_file_falls_back_and_warns(self):
        """Verifica os mesmos arquivos inválidos do teste do firmware, além de 5.0, true e chaves duplicadas."""
        bad = ['{"kp":256,"kd":0,"torque_limit":681}', '{"kp":3,"kd":0,"torque_limit":1001}', '{"kp":3,"kd":0}',
               '{"kp":0,"kd":0,"torque_limit":681}', '{"kp":33,"kd":0,"torque_limit":681}',
               '{"kp":3,"kd":65,"torque_limit":681}', '{"kp":3,"kd":0,"torque_limit":199}',
               '{"kp":3,"kd":0,"torque_limit":681,"extra":1}', 'not json', '{"kp":5.0,"kd":0,"torque_limit":1000}',
               '{"kp":true,"kd":0,"torque_limit":1000}', '{"kp":3,"kp":4,"kd":0,"torque_limit":1000}', '[1,2,3]']
        for n, text in enumerate(bad):
            with self.subTest(text=text):
                write_json(self.params, text)
                with self.assertRaises(ValueError):
                    load_servo_params(str(self.params))
                self.warns.clear()
                g = self.mg().get()
                self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (5, 0, 1000, "Padrão do programa principal"))
                self.assertIn("inválido", g["warn"])
                self.assertEqual([(c, lv) for c, lv, _ in self.warns], [("Barramento", "warn")])

    def test_boundaries_accepted(self):
        for kp, kd, lim in ((1, 0, 200), (32, 64, 1000)):
            write_json(self.params, {"kp": kp, "kd": kd, "torque_limit": lim})
            self.assertEqual(load_servo_params(str(self.params)), (kp, kd, lim))

    def test_contract_kp_fw_used_without_file(self):
        model = self.dir / "models" / "walk"
        model.mkdir(parents=True)
        write_json(model / "deployment-contract.json", {"model": {"actuators": [{"kp_fw": 4.0}]}})
        self.toml.write_text(f'[policy]\nwalk = "{(model / "policy.onnx").as_posix()}"\n', encoding="utf-8")
        g = self.mg().get()
        self.assertEqual((g["kp"], g["kd"], g["limit"], g["source"]), (4, 0, 1000, "Padrão do programa principal"))
        self.assertIn("kp_fw", g["detail"])
        # Se kp_fw no contrato for inválido, usa P5.
        for bad in ({"model": {"actuators": [{"kp_fw": 4.5}]}}, {"model": {"actuators": [{"kp_fw": 40}]}},
                    {"model": {"actuators": [{}, {}]}}, {"model": {}}):
            write_json(model / "deployment-contract.json", bad)
            bump(model / "deployment-contract.json", len(json.dumps(bad)))
            self.assertEqual(self.mg().get()["kp"], 5, bad)

    def test_walk_path_resolution_like_robotd(self):
        self.toml.write_text("[policy]\nmode = \"walk\"\n", encoding="utf-8")
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/policies/current/deployment-contract.json")
        self.toml.write_text('[policy]\nwalk = "none"\n', encoding="utf-8")     # "none" não é um caminho válido; usa o padrão.
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/policies/current/deployment-contract.json")
        self.toml.write_text('[policy]\nwalk = "/opt/robot/feetech-ft5-r5/models/abc/policy.onnx"\n', encoding="utf-8")
        self.assertEqual(_walk_contract(str(self.toml)), "/opt/robot/feetech-ft5-r5/models/abc/deployment-contract.json")

    @unittest.skipUnless(FORK_WALK is not None and FORK_WALK.is_file(), "Defina MICRODUCK_FORK para o diretório do firmware do fork.")
    def test_real_fork_walk_contract_is_5(self):
        """O modelo de caminhada incluído no fork usa kp_fw igual a 5."""
        self.assertEqual(contract_kp(str(FORK_WALK)), 5)

    def test_cached_by_mtime(self):
        write_json(self.params, {"kp": 3, "kd": 1, "torque_limit": 681})
        mg = self.mg()
        self.assertEqual(mg.get()["kp"], 3)
        write_json(self.params, {"kp": 7, "kd": 1, "torque_limit": 681})
        bump(self.params, 5)
        self.assertEqual(mg.get(max_age=60)["kp"], 3)           # Não consulta o arquivo durante max_age.
        self.assertEqual(mg.get()["kp"], 7)                     # Recarrega quando o arquivo muda.
        self.params.unlink()
        self.assertEqual(mg.get()["source"], "Padrão do programa principal")      # Volta ao padrão após remover o arquivo.


# ---------------- No barramento: todos os caminhos que habilitam torque ----------------

class SimBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sessions = []

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.tmp.cleanup()

    def open(self, params=None):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        s = ServoSession(Log(Path(d) / "logs", echo=False, background=False), sim=True, state_dir=d)
        ok, why = s.open("teste")
        self.assertTrue(ok, why)
        end = time.monotonic() + 2
        while len(s.rows) < 15 and time.monotonic() < end:
            time.sleep(0.02)
        self.sessions.append(s)
        # Sem /etc/robot no computador, usa 5/0/1000; testes de arquivo apontam MainGains para um diretório temporário.
        pp = os.path.join(d, "etc", "servo-test-parameters.json")
        if params is not None:
            os.makedirs(os.path.dirname(pp))
            write_json(pp, params)
        s.ops.gains = MainGains(params_path=pp, robotd_tomls=(), log=s.ops.log)
        return s

    @staticmethod
    def sim(s, i):
        return s.sim_serial.servos[i]


class GainsOnBusTest(SimBase):
    def test_sim_powers_up_with_factory_gains(self):
        s = self.open()
        sv = self.sim(s, 22)
        self.assertEqual(run_gains(sv), (32, 40, 1000))
        self.assertEqual((sv.r[21], sv.r[22], sv.r[23]), (32, 40, 0))

    def test_torque_on_writes_5_0_1000_before_torque_only_ram(self):
        s = self.open()
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
        sv = self.sim(s, 22)
        self.assertEqual(r["on"], [22])
        self.assertEqual(sv.r[40], 1)
        self.assertEqual(run_gains(sv), (5, 0, 1000))
        self.assertEqual((sv.r[21], sv.r[22], sv.r[52], sv.r[55]), (32, 40, 0, 1))   # Preserva EEPROM, I e a flag de trava.
        self.assertEqual(r["gains"], {"kp": 5, "kd": 0, "limit": 1000, "source": "Padrão do programa principal"})
        g = rec.gains_writes(22)
        self.assertEqual(len(g), 1)
        self.assertLess(g[0], rec.first_torque_on(22))                       # Grava P/D/limite antes de habilitar o torque.
        self.assertEqual(rec.writes()[[n for n, *_ in rec.writes()].index(g[0])][2][22], struct.pack("<H", 1000) + bytes([5, 0]))
        touched = {a for _, a, d in rec.writes() if 22 in d}
        self.assertFalse(touched & {21, 22, 23, 55}, touched)                # Não altera P/D/I na EEPROM nem a trava.
        # A tabela exibe os valores P/D/limite lidos de volta.
        snap = s.snapshot()
        row = {x["id"]: x for x in snap["rows"]}[22]
        self.assertEqual((row["p_run"], row["d_run"], row["limit"], row["gains_ok"]), (5, 0, 1000, True))
        self.assertEqual((snap["gains"]["kp"], snap["gains"]["kd"], snap["gains"]["limit"]), (5, 0, 1000))
        self.assertEqual(snap["gains"]["differ_on"], [])

    def test_only_writes_servos_that_differ(self):
        s = self.open()
        self.sim(s, 20).r[50], self.sim(s, 20).r[51] = 5, 0              # O servo 20 já usa 5/0/1000.
        rec = Recorder(s.sim_serial)
        s.ops.handle({"op": "torque", "on": 1, "ids": [20, 21]})
        self.assertEqual(rec.gains_writes(20), [])
        self.assertEqual(len(rec.gains_writes(21)), 1)
        s.ops.handle({"op": "torque", "on": 0, "ids": [20, 21]})
        rec.packets.clear()
        s.ops.handle({"op": "torque", "on": 1, "ids": [20, 21]})              # Os valores já coincidem; não grava novamente.
        self.assertEqual([a for _, a, _ in rec.writes() if a == 48], [])
        self.assertEqual((self.sim(s, 20).r[40], self.sim(s, 21).r[40]), (1, 1))

    def test_rewrites_after_servo_reboot(self):
        s = self.open()
        s.ops.handle({"op": "torque", "on": 1, "ids": [23]})
        s.ops.handle({"op": "reboot", "id": 23})                              # Após reiniciar, RAM volta aos valores P32/D40 de fábrica.
        self.assertEqual(run_gains(self.sim(s, 23)), (32, 40, 1000))
        s.ops.handle({"op": "torque", "on": 1, "ids": [23]})
        self.assertEqual(run_gains(self.sim(s, 23)), (5, 0, 1000))

    def test_params_file_values_used(self):
        s = self.open(params={"kp": 3, "kd": 1, "torque_limit": 681})
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22, 12]})
        self.assertEqual(r["on"], [22, 12])
        for i in (22, 12):
            self.assertEqual(run_gains(self.sim(s, i)), (3, 1, 681))
        self.assertEqual(r["gains"]["source"], "Arquivo de parâmetros")
        self.assertEqual(s.snapshot()["gains"]["source"], "Arquivo de parâmetros")

    def test_bad_params_file_uses_default_and_warns(self):
        s = self.open(params={"kp": 0, "kd": 0, "torque_limit": 681})       # O fork não aceita o kp=0 usado pela versão antiga.
        s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
        self.assertEqual(run_gains(self.sim(s, 22)), (5, 0, 1000))
        warns = s.log.recent(cats=["Barramento"], min_level="warn")
        self.assertTrue(any("inválido" in e["msg"] for e in warns), warns)
        self.assertIn("é inválido", s.snapshot()["gains"]["warn"])

    def test_readback_mismatch_refuses_torque_and_logs_register(self):
        s = self.open()
        self.sim(s, 22).readonly = {50}                                       # Não permite gravar P.
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [22, 21]})
        self.assertEqual(r["on"], [21])
        self.assertEqual(self.sim(s, 22).r[40], 0)                           # O torque continua desligado.
        self.assertEqual(self.sim(s, 21).r[40], 1)
        self.assertIn("50 (P): gravado 5, retornou 32", r["bad"]["22"])
        self.assertIsNone(rec.first_torque_on(22))
        errs = s.log.recent(cats=["Barramento"], min_level="error")
        self.assertTrue(any("#22" in e["msg"] and "50 (P)" in e["msg"] for e in errs), errs)

    def test_no_reply_refuses_torque(self):
        s = self.open()
        self.sim(s, 24).muted = {48}                                          # Não responde às leituras a partir do registrador 48.
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [24]})
        self.assertEqual(r["on"], [])
        self.assertIn("Não foi possível ler P/D/limite", r["bad"]["24"])
        self.assertEqual(self.sim(s, 24).r[40], 0)

    def test_already_on_with_other_gains_is_only_checked(self):
        """Não altera os ganhos com torque ativo, pois mudar P sob carga pode ceder a articulação; apenas confere e sinaliza."""
        s = self.open()
        sv = self.sim(s, 13)
        sv.r[40] = 1                                                          # Torque habilitado externamente, com P32/D40 de fábrica.
        s._read_torque()
        rec = Recorder(s.sim_serial)
        r = s.ops.handle({"op": "torque", "on": 1, "ids": [13]})
        self.assertEqual(r["on"], [13])
        self.assertIn("13", r["differ"])
        self.assertEqual(run_gains(sv), (32, 40, 1000))
        self.assertEqual(rec.gains_writes(13), [])
        snap = s.snapshot()
        self.assertEqual(snap["gains"]["differ_on"], [13])
        self.assertFalse({x["id"]: x for x in snap["rows"]}[13]["gains_ok"])
        # Ao soltar e reter novamente, aplica os valores corretos.
        s.ops.handle({"op": "torque", "on": 0, "ids": [13]})
        s.ops.handle({"op": "torque", "on": 1, "ids": [13]})
        self.assertEqual(run_gains(sv), (5, 0, 1000))
        self.assertEqual(s.snapshot()["gains"]["differ_on"], [])

    def test_manual_register_write_flags_header(self):
        s = self.open()
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})
        s.ops.handle({"op": "write_reg", "id": 20, "addr": 50, "size": 1, "value": 10})   # Continua permitido para usuários avançados.
        self.assertEqual(self.sim(s, 20).r[50], 10)
        g = s.snapshot()["gains"]
        self.assertEqual([(m["id"], m["addr"], m["value"]) for m in g["manual"]], [(20, 50, 10)])
        self.assertEqual(g["differ_on"], [20])
        self.assertTrue(any("alterou manualmente" in e["msg"] for e in s.log.recent(cats=["Barramento"], min_level="warn")))
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})                  # Com torque ativo, apenas confere; não altera novamente.
        self.assertEqual(self.sim(s, 20).r[50], 10)
        s.ops.handle({"op": "torque", "on": 0, "ids": [20]})
        s.ops.handle({"op": "torque", "on": 1, "ids": [20]})                  # Após soltar, grava os valores do programa principal.
        self.assertEqual(self.sim(s, 20).r[50], 5)
        self.assertEqual(s.snapshot()["gains"]["manual"], [])
        # O P da EEPROM (21) só vale após ligar; preserva a alteração manual, mas aplica P5 em operação.
        s.ops.handle({"op": "write_reg", "id": 21, "addr": 21, "size": 1, "value": 20, "unlock": True})
        s.ops.handle({"op": "write_reg", "id": 21, "addr": 48, "size": 2, "value": 700})
        self.assertEqual(self.sim(s, 21).r[21], 20)
        s.ops.handle({"op": "torque", "on": 1, "ids": [21]})
        self.assertEqual(run_gains(self.sim(s, 21)), (5, 0, 1000))
        self.assertEqual([(m["id"], m["addr"]) for m in s.snapshot()["gains"]["manual"]], [(21, 21)])


# Cada caminho que habilita torque: nome, preparação, ação e servo observado. A preparação ocorre antes de simular falha de gravação.
def _hold_one(t, s):
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})


def _hold_all(t, s):
    s.ops.handle({"op": "torque", "on": 1})


def _idle(t, s):
    s.ops.handle({"op": "idle", "on": True})
    s.ops.handle({"op": "idle", "on": False})
    if s.ops._idle_thread:
        s.ops._idle_thread.join(5)


def _calib_from_off(t, s):
    s.ops.handle({"op": "calibrate", "ids": "22"})                           # Retém automaticamente após calibrar (torque_on_aligned).


def _prep_on_stale(t, s):
    """Se o servo 22 estiver retido com P32/D40 de fábrica na RAM, grava os valores corretos antes de restaurar o torque."""
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
    sv = t.sim(s, 22)
    sv.r[50], sv.r[51] = 32, 40


def _prep_calibrated_stale(t, s):
    s.ops.handle({"op": "torque", "on": 1, "ids": [22]})
    s.ops.handle({"op": "calibrate", "ids": "22"})
    sv = t.sim(s, 22)
    sv.r[50], sv.r[51] = 32, 40


def _undo(t, s):
    s.ops.handle({"op": "undo"})


PATHS = [
    ("Reter um servo", None, _hold_one, 22),
    ("Habilitar torque em todos", None, _hold_all, 22),
    ("Movimento livre (torque da cabeça)", None, _idle, 31),
    ("Retenção automática após calibrar", None, _calib_from_off, 22),
    ("Restaurar torque após calibração", _prep_on_stale, _calib_from_off, 22),
    ("Restaurar torque ao desfazer calibração", _prep_calibrated_stale, _undo, 22),
]


class EveryTorquePathTest(SimBase):
    def test_every_path_writes_gains_before_torque(self):
        for name, prep, act, sid in PATHS:
            with self.subTest(path=name):
                s = self.open()
                if prep:
                    prep(self, s)
                rec = Recorder(s.sim_serial)
                act(self, s)
                sv = self.sim(s, sid)
                self.assertEqual(sv.r[40], 1, name)
                self.assertEqual(run_gains(sv), (5, 0, 1000), name)
                on = rec.first_torque_on(sid)
                self.assertIsNotNone(on, name)
                g = rec.gains_writes(sid)
                self.assertTrue(g and g[0] < on, f"{name}: grava P/D/limite {g} antes de habilitar o torque {on}.")
                self.assertEqual((sv.r[21], sv.r[22], sv.r[55]), (32, 40, 1), name)    # Preserva a EEPROM e a trava.

    def test_every_path_refuses_torque_when_readback_wrong(self):
        for name, prep, act, sid in PATHS:
            with self.subTest(path=name):
                s = self.open()
                if prep:
                    prep(self, s)
                sv = self.sim(s, sid)
                sv.r[50] = 32
                sv.readonly = {50}                   # Simula falha ao gravar P durante o fluxo de calibração ou desfazer.
                rec = Recorder(s.sim_serial)
                act(self, s)
                self.assertEqual(sv.r[40], 0, f"{name}: se P não puder ser gravado, não habilite o torque.")
                self.assertIsNone(rec.first_torque_on(sid), name)
                errs = s.log.recent(cats=["Barramento"], min_level="error")
                self.assertTrue(any(f"#{sid}" in e["msg"] and "50（P）" in e["msg"] for e in errs), (name, errs))

    def test_all_torque_writes_go_through_gains(self):
        """Confere que os únicos caminhos para habilitar torque gravam P/D/limite antes, por torque_on_aligned ou _gains_then_torque."""
        import re
        on = re.compile(r"write_u8\([^()]*,\s*40,\s*1\)|sync_write\(40,\s*1,.*(bytes\(\[1\]\)|b\"\\x01\")")
        hits = []
        for f in ("servo_ops.py", "servo.py"):
            src = (HERE.parent / "studio" / f).read_text(encoding="utf-8")
            hits += [f"{f}: {ln.strip()}" for ln in src.splitlines() if on.search(ln)]
        self.assertEqual(len(hits), 2, hits)
        self.assertTrue(any("_ack(self.bus.write_u8(i, 40, 1))" in h for h in hits), hits)
        self.assertTrue(any("sync_write(40, 1, [(i, bytes([1])) for i in on])" in h for h in hits), hits)


if __name__ == "__main__":
    unittest.main()
