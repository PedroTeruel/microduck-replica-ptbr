"""Biblioteca de modelos do Studio; a configuração só é considerada aplicada após confirmação de leitura do programa principal."""
import asyncio
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path

from .model_package import PackageError, extract_package, validate_policy
from .rpc import call_once

SCHEMA = 'microduck-studio-model-library/v1'
META = '.studio-model.json'
BASE = '/opt/robot/feetech-ft5-r5'
PREFLIGHT = BASE + '/robotd'
SLOTS = ('walk', 'sitstand', 'ground_pick', 'kick_left', 'kick_right', 'roulade', 'stand')
LABELS = dict(zip(SLOTS, ('Caminhar / manter', 'Sentar / levantar', 'Abaixar a cabeça para pegar objetos', 'Chute com a perna esquerda', 'Chute com a perna direita', 'Cambalhota para a frente', 'Em pé (independente)')))
SKILLS = {'sitstand': 'sit_toggle', 'ground_pick': 'ground_pick', 'kick_left': 'kick_left',
          'kick_right': 'kick_right', 'roulade': 'roulade'}
DEFAULT_KEYS = {'a': 'ground_pick', 'x': 'roulade', 'lb': 'kick_left', 'rb': 'kick_right', 'dpad_down': 'sit_toggle'}
BUTTONS = {'a': 'A', 'x': 'X', 'lb': 'LB', 'rb': 'RB', 'dpad_down': 'Direcional para baixo'}
JOINTS = ('left_hip_yaw,left_hip_roll,left_hip_pitch,left_knee,left_ankle,neck_pitch,'
          'head_pitch,head_yaw,head_roll,right_hip_yaw,right_hip_roll,right_hip_pitch,right_knee,right_ankle').split(',')
READBACK_TIMEOUT = 25.0
READBACK_POLL = 0.2


class ModelError(ValueError):
    def __init__(self, message, *, code=None, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _json(path, limit=8 << 20):
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('O arquivo é um link simbólico ou excede o tamanho permitido.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('É necessário fornecer um objeto JSON.')
    return value


def _atomic_json(path, value):
    """Grava em um arquivo temporário no mesmo diretório e faz a substituição atômica para evitar registros parciais após falta de energia."""
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        if os.name != 'nt':
            dfd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _signature(contract):
    """HOME/P são parâmetros globais instalados na inicialização do processo e não podem ser alterados durante a execução."""
    try:
        if (type(contract.get('input_dim')) is not int or contract['input_dim'] != 61 or
                type(contract.get('output_dim')) is not int or contract['output_dim'] != 14 or
                contract.get('obs_normalizer') != 'baked_in_onnx'):
            raise ValueError('A interface de observação deve ter entrada normalizada de 61 dimensões e ação de 14 dimensões.')
        model = contract['model']
        names = contract['onnx_metadata']['joint_names'].split(',')
        if names != JOINTS:
            raise ValueError('A ordem das articulações é diferente.')
        rows = model['joints']
        if not isinstance(rows, list):
            raise ValueError('O conjunto de articulações HOME está incompleto.')
        homes = {}
        for name in JOINTS:
            matches = [r for r in rows if isinstance(r, dict) and r.get('name') == name]
            if len(matches) != 1:
                raise ValueError('Nome de articulação HOME ausente ou duplicado: ' + name)
            homes[name] = matches[0]['home_rad']
        if any(isinstance(homes[n], bool) or not isinstance(homes[n], (float, int))
               or not math.isfinite(homes[n]) for n in JOINTS):
            raise ValueError('HOME contém um ângulo inválido.')
        actuators = model['actuators']
        if not isinstance(actuators, list) or len(actuators) != 1:
            raise ValueError('Os parâmetros P dos servos estão incompletos.')
        kp = actuators[0]['kp_fw']
        if isinstance(kp, bool) or not isinstance(kp, (int, float)) or not math.isfinite(kp) or int(kp) != kp:
            raise ValueError('Os parâmetros P dos servos são inválidos.')
        return {'joints': names, 'home': [float(homes[n]) for n in JOINTS], 'kp_fw': int(kp)}
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError) as exc:
        raise ModelError(f'Não foi possível confirmar o contrato de controle do modelo (HOME / P dos servos / ordem das articulações): {exc}') from exc


class Models:
    def __init__(self, rd, log, state_dir, tune=None, root='/', validator=None, rpc=None):
        self.rd, self.log, self.tune = rd, log, tune
        self.root = Path(root)
        self.directory = Path(state_dir) / 'models'
        self.catalog = self.directory / 'library.json'
        self.validator, self.rpc = validator, rpc
        self._lock = asyncio.Lock()
        self._disk_lock = threading.RLock()

    def _local(self, path):
        if not isinstance(path, str) or not path.startswith('/'):
            raise ModelError('O caminho do modelo do programa principal deve ser absoluto.')
        return self.root / path.lstrip('/')

    def _remote(self, path):
        path = Path(path).resolve()
        if str(self.root) == '/':
            return str(path)
        try:
            return '/' + path.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            # Usado com um diretório state independente no computador; em produção, state fica em /var/lib.
            return path.as_posix()

    def _managed(self, path):
        try:
            self._local(path).resolve().relative_to(self.directory.resolve())
            return True
        except (ValueError, ModelError, OSError):
            return False

    def _init_dir(self):
        if self.directory.is_symlink():
            raise ModelError('O diretório da biblioteca de modelos não pode ser um link simbólico.')
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80 or any(ord(c) < 32 for c in value):
            raise ModelError('O nome do modelo deve ter de 1 a 80 caracteres visíveis.')
        return value.strip()

    async def _call(self, method, params=None, timeout=2.0):
        if self.rpc is not None:
            return await self.rpc(method, params or {}, timeout=timeout)
        return await call_once(self.rd.addr, method, params, timeout=timeout, name='models', log=self.log)

    async def _snapshot(self):
        names = ('robot.policies', 'robot.busStatus', 'pad.bindings', 'robot.skills')
        values = await asyncio.gather(*(self._call(n) for n in names), return_exceptions=True)
        snap, errors = {}, []
        for name, val in zip(('policies', 'bus', 'bindings', 'skills'), values):
            if self._report_valid(name, val):
                snap[name] = val
            else:
                snap[name] = None
                errors.append(name)
        snap['error'] = 'Falha na conexão ou na leitura de retorno do programa principal; não foi possível confirmar a configuração ativa.' if errors else None
        return snap

    @staticmethod
    def _report_valid(name, value):
        """Um objeto vazio ou relatório parcial não é uma leitura de retorno confiável e não prova que nenhum modelo esteja em uso."""
        if not isinstance(value, dict):
            return False
        def path_ok(path):
            return path is None or isinstance(path, str) and path.startswith('/')
        def rows_ok(key, check):
            rows = value.get(key)
            return isinstance(rows, list) and all(isinstance(row, dict) and check(row) for row in rows)
        if name == 'policies':
            if not isinstance(value.get('enabled'), bool) or not isinstance(value.get('skills'), list) or not all(isinstance(s, str) for s in value['skills']):
                return False
            if not rows_ok('slots', lambda r: isinstance(r.get('slot'), str) and r['slot'] in SLOTS and
                           path_ok(r.get('path')) and isinstance(r.get('overridden'), bool)):
                return False
            return sorted(r['slot'] for r in value['slots']) == sorted(SLOTS)
        if name == 'bus':
            lm = value.get('loaded_models')
            return isinstance(value.get('mode'), str) and isinstance(lm, dict) and all(
                isinstance(k, str) and (v is None or isinstance(v, dict) and path_ok(v.get('path'))) for k, v in lm.items())
        if name == 'bindings':
            return rows_ok('bindings', lambda r: isinstance(r.get('button'), str) and r['button'] in BUTTONS and
                           isinstance(r.get('skill'), str) and isinstance(r.get('overridden'), bool)) and sorted(
                               r['button'] for r in value['bindings']) == sorted(BUTTONS)
        if name == 'skills':
            return rows_ok('skills', lambda r: isinstance(r.get('name'), str) and path_ok(r.get('path'))) and isinstance(
                value.get('built_in'), list) and all(isinstance(n, str) for n in value['built_in'])
        return False

    @staticmethod
    def _idle_reason(snap):
        bus, pol = snap.get('bus'), snap.get('policies')
        if not isinstance(bus, dict) or not isinstance(pol, dict):
            return 'Falha na conexão ou na leitura de retorno do programa principal; não foi possível confirmar que os servos estão sem torque.'
        native = bus.get('native')
        if not isinstance(native, dict) or native.get('torque_enabled') is not False or native.get('torque_state_confirmed') is not False:
            return 'Desative o torque e aguarde a confirmação do programa principal antes de alterar modelos ou botões.'
        if bus.get('policy_enabled') is not False:
            return 'Interrompa a política e desative o torque antes de alterar modelos ou botões.'
        if bus.get('mode') != 'motion' or pol.get('enabled') is not True:
            return 'O executor de modelos não está ativo neste modo. Volte ao modo de movimento e mantenha os servos sem torque.'
        if snap.get('error'):
            return snap['error']
        return None

    async def _require_idle(self):
        snap = await self._snapshot()
        reason = self._idle_reason(snap)
        if reason:
            raise ModelError(reason, status=409, code='not_idle')
        return snap

    @staticmethod
    def _rows(value, key):
        rows = value.get(key) if isinstance(value, dict) else None
        return rows if isinstance(rows, list) else []

    def _load_catalog(self):
        if not self.catalog.exists():
            return {'schema': SCHEMA, 'defaults': {}}, None
        try:
            data = _json(self.catalog, 1 << 20)
            if data.get('schema') != SCHEMA or not isinstance(data.get('defaults'), dict):
                    raise ValueError('Formato da biblioteca incompatível.')
            for slot, d in data['defaults'].items():
                if slot not in SLOTS or not isinstance(d, dict) or d.get('id') != 'builtin-' + slot:
                    raise ValueError('Registro do modelo padrão inválido.')
                path = d.get('path')
                disabled = d.get('disabled') is True and slot != 'walk' and path is None
                if not disabled and (not isinstance(path, str) or not path.startswith('/') or self._managed(path)):
                    raise ValueError('O caminho padrão de restauração é inválido ou aponta para a biblioteca importada.')
                self._name(d.get('name'))
                if d.get('sha256') is not None and (not isinstance(d['sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', d['sha256'])):
                    raise ValueError('Resumo do modelo padrão inválido.')
                sig = d.get('signature')
                if sig is not None:
                    if not isinstance(sig, dict) or sig.get('joints') != JOINTS or not isinstance(sig.get('home'), list) or len(sig['home']) != len(JOINTS):
                        raise ValueError('Registro do contrato HOME padrão inválido.')
                    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in sig['home']):
                        raise ValueError('O HOME padrão contém um ângulo inválido.')
                    if type(sig.get('kp_fw')) is not int or not 1 <= sig['kp_fw'] <= 32:
                        raise ValueError('Registro padrão dos parâmetros P dos servos inválido.')
            return data, None
        except (OSError, ValueError, RecursionError, OverflowError) as exc:
            return {'schema': SCHEMA, 'defaults': {}}, f'Registro dos modelos padrão corrompido; as alterações de configuração foram interrompidas: {exc}'

    def _read_library(self, snap=None):
        with self._disk_lock:
            self._init_dir()
            catalog, error = self._load_catalog()
            if not self.catalog.exists() and snap and not snap.get('error'):
                defaults = self._capture_defaults(snap)
                if defaults:
                    catalog['defaults'] = defaults
                    _atomic_json(self.catalog, catalog)
            entries = []
            for child in sorted(self.directory.iterdir()):
                if not re.fullmatch(r'[a-f0-9]{32}', child.name) or child.is_symlink() or not child.is_dir():
                    continue
                try:
                    entry = _json(child / META, 64 << 10)
                    if entry.get('id') != child.name or entry.get('slot') not in SLOTS or not isinstance(entry.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', entry['sha256']):
                        raise ValueError('Registro de identidade do modelo inválido.')
                    entry['name'] = self._name(entry.get('name'))
                    entry['path'] = self._remote(child / 'policy.onnx')
                    entry['source'] = 'imported'
                    entry['installed'] = self._local(entry['path']).is_file() and not self._local(entry['path']).is_symlink()
                    entries.append(entry)
                except (ValueError, OSError, RecursionError) as exc:
                    error = error or f'Não foi possível ler o registro do modelo {child.name[:8]}: {exc}'
            builtins = [dict(d, source='builtin', slot=s,
                             installed=self._local(d['path']).is_file() and not self._local(d['path']).is_symlink())
                        for s, d in catalog['defaults'].items() if not d.get('disabled')]
            return catalog, builtins + entries, error

    def _capture_defaults(self, snap):
        """Dá preferência ao pacote incluído na imagem; registra o caminho explícito original somente ao criar a biblioteca pela primeira vez."""
        candidates, names = {}, {}
        try:
            profile = _json(self._local(BASE + '/management-profile.json'))
            for row in self._rows(profile, 'builtin_models'):
                if not isinstance(row, dict) or row.get('slot') not in SLOTS:
                    continue
                ident = row.get('id')
                if isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_-]+', ident):
                    candidates[row['slot']] = BASE + '/models/' + ident + '/policy.onnx'
                    names[row['slot']] = row.get('name')
        except (OSError, ValueError):
            pass
        for row in self._rows(snap.get('policies'), 'slots'):
            if isinstance(row, dict) and row.get('slot') in SLOTS:
                candidates.setdefault(row['slot'], row.get('path'))
        defaults = {}
        tune_names = (getattr(self.tune, 'disk', {}) or {}).get('builtin_names', {})
        for slot, path in candidates.items():
            if not isinstance(path, str) or not path.startswith('/') or self._managed(path):
                continue
            local = self._local(path)
            if not local.is_file() or local.is_symlink():
                continue
            sig, task, sha = None, None, None
            try:
                con = _json(local.with_name('deployment-contract.json'))
                sig, task = _signature(con), con.get('task')
            except (OSError, ValueError):
                pass
            try:
                sha = hashlib.sha256(local.read_bytes()).hexdigest()
            except OSError:
                pass
            defaults[slot] = {'id': 'builtin-' + slot, 'path': path,
                              'name': names.get(slot) or tune_names.get(local.parent.name) or LABELS[slot],
                              'task': task, 'sha256': sha, 'signature': sig}
        for row in self._rows(snap.get('policies'), 'slots'):
            slot = row.get('slot')
            if slot in SLOTS and slot != 'walk' and slot not in defaults and row.get('path') is None:
                defaults[slot] = {'id': 'builtin-' + slot, 'path': None, 'name': LABELS[slot] + ' (não instalado por padrão)',
                                  'task': None, 'sha256': None, 'signature': None, 'disabled': True}
        return defaults

    def _validator_available(self):
        return self.validator is not None or self._local(PREFLIGHT).is_file()

    def _runtime_env(self):
        env = dict(os.environ)
        if str(self.root) != '/' or os.name == 'nt':
            return env
        try:
            result = subprocess.run(['systemctl', 'show', 'robotd.service', '--property=Environment', '--value'],
                                    capture_output=True, text=True, timeout=3, shell=False)
            if result.returncode == 0:
                for item in shlex.split(result.stdout):
                    key, sep, value = item.partition('=')
                    if sep and key in ('ORT_DYLIB_PATH', 'LD_LIBRARY_PATH'):
                        env[key] = value
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return env

    def _preflight(self, path):
        if self.validator is not None:
            result = self.validator(path)
        else:
            if not self._validator_available():
                raise ModelError('Não há um executor de modelos confiável neste dispositivo para validar o ONNX.', status=503)
            result = validate_policy(path, str(self._local(PREFLIGHT)), env=self._runtime_env())
        if not isinstance(result, dict) or result.get('valid') is not True:
            raise ModelError('A validação prévia do executor de modelos falhou: ' + str((result or {}).get('error', 'validade não confirmada') if isinstance(result, dict) else 'resposta inválida'))

    def _install(self, path, name):
        ident = uuid.uuid4().hex
        stage, final = self.directory / ('.stage-' + ident), self.directory / ident
        try:
            self._init_dir()
            data = extract_package(Path(path), stage)
            self._preflight(stage / data['onnx'])
            slot = data.get('slot')
            if slot not in SLOTS:
                raise ModelError('Não foi possível identificar a finalidade de movimento deste modelo; a instalação não está disponível.')
            record = {'id': ident, 'name': self._name(name or data.get('name') or LABELS[slot]),
                      'task': data['task'], 'slot': slot, 'sha256': data['sha256'], 'files': data['files']}
            _atomic_json(stage / META, record)
            os.replace(stage, final)
        except (PackageError, OSError, KeyError, TypeError) as exc:
            raise ModelError(f'Falha ao importar o modelo: {exc}') from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    async def import_package(self, path, name=''):
        if not isinstance(name, str):
            raise ModelError('O nome do modelo deve ser texto.')
        if name:
            self._name(name)
        async with self._lock:
            snap = await self._snapshot()
            _, _, error = await self._disk(self._read_library, snap)
            if error:
                raise ModelError(error, status=409)
            await asyncio.to_thread(self._install, path, name)
        return await self.view()

    @staticmethod
    def _references(snap):
        paths = set()
        for key, field in (('policies', 'slots'), ('skills', 'skills')):
            for row in Models._rows(snap.get(key), field):
                if isinstance(row, dict) and isinstance(row.get('path'), str):
                    paths.add(row['path'])
        lm = (snap.get('bus') or {}).get('loaded_models')
        if isinstance(lm, dict):
            paths.update(v['path'] for v in lm.values() if isinstance(v, dict) and isinstance(v.get('path'), str))
        return paths

    def _configured_refs(self):
        """Se a configuração for gravada, mas o carregamento falhar, o snapshot ativo ainda pode apontar para o arquivo antigo; inclua referências após reinicializações."""
        path = self._local('/etc/robot/feetech-ft5/robotd.toml')
        try:
            if path.stat().st_size > 2 << 20:
                raise ValueError('A configuração excede o tamanho permitido.')
            with path.open('rb') as f:
                data = tomllib.load(f)
            policy = data.get('policy')
            if not isinstance(policy, dict):
                raise ValueError('Configuração policy ausente.')
            rows = policy.get('skill', [])
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError('Formato de policy.skill inválido.')
            paths = [policy.get(s) for s in SLOTS] + [r.get('path') for r in rows]
            if any(p is not None and (not isinstance(p, str) or p != 'none' and not p.startswith('/')) for p in paths):
                raise ValueError('Caminho de configuração do modelo inválido.')
            return {p for p in paths if p and p != 'none'}, None
        except (OSError, ValueError, RecursionError) as exc:
            return set(), f'Não foi possível ler a configuração persistida do programa principal e confirmar se o modelo pode ser excluído: {exc}'

    def _normalize_refs(self, refs):
        try:
            return {self._remote(self._local(path).resolve()) for path in refs}
        except (OSError, RuntimeError) as exc:
            raise ModelError(f'Não foi possível resolver o caminho de referência do modelo e confirmar se ele pode ser excluído: {exc}') from exc

    @staticmethod
    def _delete_reason(item, snap, refs, config_error):
        if item['source'] == 'builtin':
            return 'O modelo padrão integrado não pode ser excluído.'
        if snap['error'] or config_error:
            return snap['error'] or config_error
        policies = snap.get('policies') or {}
        if policies.get('change_error') or any(r.get('error') for r in Models._rows(policies, 'slots')):
            return 'O programa principal apresentou um erro ao carregar modelos; não é possível confirmar referências da configuração anterior. Resolva o problema de carregamento primeiro.'
        if item['path'] in refs:
            return 'O modelo ainda é usado por um slot de execução, habilidade ou configuração persistida. Troque o modelo ou restaure o padrão primeiro.'
        return None

    async def view(self):
        snap = await self._snapshot()
        try:
            catalog, entries, library_error = await asyncio.to_thread(self._read_library, snap)
        except (OSError, ValueError) as exc:
            catalog, entries, library_error = {'defaults': {}}, [], f'Não foi possível ler a biblioteca de modelos: {exc}'
        reason = library_error or self._idle_reason(snap)
        by_path = {i['path']: i['id'] for i in entries}
        slot_rows = {r.get('slot'): r for r in self._rows(snap.get('policies'), 'slots') if isinstance(r, dict)}
        refs = self._references(snap)
        configured, config_error = await asyncio.to_thread(self._configured_refs)
        refs.update(configured)
        try:
            refs = await asyncio.to_thread(self._normalize_refs, refs)
        except ModelError as exc:
            config_error = str(exc)
        slots = []
        for slot in SLOTS:
            row = slot_rows.get(slot, {})
            default = catalog['defaults'].get(slot, {})
            slots.append({'slot': slot, 'label': LABELS[slot], 'model_id': by_path.get(row.get('path')),
                          'path': row.get('path'), 'error': row.get('error'), 'default_id': default.get('id'),
                          'default_disabled': default.get('disabled') is True,
                          'is_default': bool(default and row and row.get('path') == default.get('path') and not row.get('error'))})
        slots_by_name = {s['slot']: s for s in slots}
        bindings = []
        for row in self._rows(snap.get('bindings'), 'bindings'):
            if not isinstance(row, dict) or row.get('button') not in BUTTONS:
                continue
            b, skill = row['button'], row.get('skill')
            slot = next((s for s, sk in SKILLS.items() if sk == skill), None)
            bindings.append({'button': b, 'label': BUTTONS[b], 'slot': slot, 'skill': skill,
                             'model_id': slots_by_name.get(slot, {}).get('model_id'), 'default_skill': DEFAULT_KEYS[b],
                             'overridden': row.get('overridden'), 'error': row.get('error')})
        items = []
        active = (snap.get('bus') or {}).get('active_model')
        for entry in entries:
            path, slot = entry['path'], entry['slot']
            chosen = [s['slot'] for s in slots if s.get('path') == path]
            delete_reason = self._delete_reason(entry, snap, refs, config_error)
            file_reason = None if entry['installed'] else 'O arquivo policy.onnx do modelo está ausente ou é inseguro. Importe-o novamente.'
            items.append({'id': entry['id'], 'name': entry['name'], 'source': entry['source'], 'task': entry.get('task'),
                          'suggested_slot': slot, 'allowed_slots': [slot], 'slots': chosen,
                          'running': bool(isinstance(active, dict) and active.get('path') == path),
                          'buttons': [b['button'] for b in bindings if b.get('model_id') == entry['id']],
                          'can_delete': delete_reason is None, 'reason': file_reason or delete_reason,
                          'sha12': (entry.get('sha256') or '')[:12] or None, 'path': path, 'installed': entry['installed']})
        available = await asyncio.to_thread(self._validator_available)
        reason = reason or (None if available else 'Não há um executor de modelos confiável neste dispositivo para validar o modelo.')
        return {'items': items, 'slots': slots, 'bindings': bindings,
                'buttons': [{'button': b, 'label': l} for b, l in BUTTONS.items()],
                'capabilities': {'import': available and not library_error, 'select': reason is None,
                                 'rename': not library_error, 'delete': not snap['error'] and not config_error and not library_error,
                                 'reason': reason, 'import_reason': library_error or (None if available else 'Não há um executor de modelos confiável neste dispositivo para validar o modelo.')},
                'error': library_error or snap['error']}

    async def _library(self, snap):
        catalog, entries, error = await self._disk(self._read_library, snap)
        if error:
            raise ModelError(error, status=409, code='library_corrupt')
        return catalog, entries

    @staticmethod
    async def _disk(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except ModelError:
            raise
        except (OSError, ValueError) as exc:
            raise ModelError(f'Falha ao ler ou salvar os arquivos do modelo: {exc}', status=503) from exc

    @staticmethod
    def _item(entries, ident):
        item = next((i for i in entries if i['id'] == ident), None)
        if item is None:
            raise ModelError('Modelo não encontrado. Atualize a lista.')
        return item

    def _rename(self, item, catalog, name):
        with self._disk_lock:
            if item['source'] == 'builtin':
                catalog['defaults'][item['slot']]['name'] = name
                _atomic_json(self.catalog, catalog)
            else:
                path = self.directory / item['id'] / META
                record = _json(path, 64 << 10)
                record['name'] = name
                _atomic_json(path, record)

    def _delete(self, item):
        if not re.fullmatch(r'[a-f0-9]{32}', item['id']):
            raise ModelError('Identidade do diretório do modelo inválida.')
        target = self.directory / item['id']
        if target.is_symlink() or target.resolve().parent != self.directory.resolve():
            raise ModelError('O caminho do diretório do modelo não é seguro.')
        shutil.rmtree(target)

    def _check_compatibility(self, item, catalog, snap):
        baseline = (catalog['defaults'].get('walk') or {}).get('signature')
        if not isinstance(baseline, dict):
            raise ModelError('Falta o contrato HOME/parâmetros P do modelo de caminhada carregado na inicialização; não é possível confirmar uma troca segura durante a execução.')
        target = _signature(_json(self._local(item['path']).with_name('deployment-contract.json')))
        current_path = next((r.get('path') for r in self._rows(snap['policies'], 'slots')
                             if isinstance(r, dict) and r.get('slot') == 'walk'), None)
        if not current_path:
            raise ModelError('Não foi possível confirmar o contrato de controle do modelo de caminhada atual.')
        current = _signature(_json(self._local(current_path).with_name('deployment-contract.json')))
        for candidate in (current, target):
            if candidate.get('joints') != baseline.get('joints'):
                raise ModelError('A ordem das articulações do modelo difere do contrato de controle carregado na inicialização; a troca durante a execução foi bloqueada.')
            if candidate.get('kp_fw') != baseline.get('kp_fw'):
                raise ModelError('Os parâmetros P dos servos diferem do contrato carregado na inicialização; implante novamente e reinicie o programa principal.')
            a, b = candidate.get('home'), baseline.get('home')
            if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b) or any(abs(x - y) > 1e-8 for x, y in zip(a, b)):
                raise ModelError('A postura HOME do modelo difere do contrato carregado na inicialização; implante novamente e reinicie o programa principal.')
        if item['source'] == 'imported':
            digest = hashlib.sha256(self._local(item['path']).read_bytes()).hexdigest()
            if digest != item['sha256']:
                raise ModelError('O arquivo do modelo importado foi alterado e não passou na verificação SHA256. Importe-o novamente.')
        self._preflight(self._local(item['path']))

    def _check_selection_files(self, item, catalog, snap):
        try:
            self._check_compatibility(item, catalog, snap)
        except ModelError:
            raise
        except (OSError, ValueError, OverflowError) as exc:
            raise ModelError(f'Não foi possível ler ou validar os arquivos do modelo e o contrato de implantação: {exc}') from exc

    async def _write_rpc(self, method, params):
        result = await self._call(method, params, timeout=8.0)
        if not isinstance(result, dict) or result.get('accepted') is not True:
            raise ModelError('O programa principal recusou a alteração da configuração: ' + str((result or {}).get('reason', 'aceitação não confirmada') if isinstance(result, dict) else 'nenhum resultado retornado'), status=409)

    async def _wait_loaded(self, slot, path, expected_skill=None):
        deadline = time.monotonic() + READBACK_TIMEOUT
        last = 'Ainda não foi confirmado pela leitura de retorno que o modelo foi carregado.'
        while True:
            snap = await self._snapshot()
            rows = {r.get('slot'): r for r in self._rows(snap.get('policies'), 'slots') if isinstance(r, dict)}
            row = rows.get(slot, {})
            lm = (snap.get('bus') or {}).get('loaded_models')
            lm = lm if isinstance(lm, dict) else {}
            actual = lm.get(slot)
            expected = None if path == 'none' else path
            error = snap['error'] or (snap.get('policies') or {}).get('change_error') or row.get('error')
            skill_ok = True
            if expected_skill:
                sk, skpath = expected_skill
                cfg = next((r for r in self._rows(snap.get('skills'), 'skills') if isinstance(r, dict) and r.get('name') == sk), {})
                loaded = lm.get(sk)
                skill_ok = cfg.get('path') == skpath and isinstance(loaded, dict) and loaded.get('path') == skpath
            loaded_ok = actual is None if expected is None else isinstance(actual, dict) and actual.get('path') == expected
            if not error and row and row.get('path') == expected and isinstance(row.get('overridden'), bool) and loaded_ok and skill_ok:
                return
            last = str(error or ('O caminho do slot e o modelo carregado ainda divergem.' if not loaded_ok else 'O modelo da habilidade e a leitura do slot ainda divergem.'))
            if time.monotonic() >= deadline:
                raise ModelError('O carregamento do modelo não foi confirmado: ' + last, status=503, code='load_unconfirmed')
            await asyncio.sleep(READBACK_POLL)

    async def _select(self, item, slot, catalog, snap):
        if slot not in SLOTS or item['slot'] != slot:
            raise ModelError('A finalidade deste modelo não corresponde ao slot de execução selecionado.')
        if not item.get('installed'):
            raise ModelError('O arquivo policy.onnx do modelo está ausente ou é inseguro. Importe-o novamente.')
        await asyncio.to_thread(self._check_selection_files, item, catalog, snap)
        # A validação prévia pode levar alguns segundos; confirme novamente que os servos estão sem torque antes de gravar a configuração.
        snap = await self._require_idle()
        old = next((r.get('path') for r in self._rows(snap['policies'], 'slots')
                    if isinstance(r, dict) and r.get('slot') == slot), None)
        if old is None and slot == 'walk':
            raise ModelError('O caminho do modelo de caminhada atual é desconhecido; não é possível registrar a origem para reversão.')
        canonical = SKILLS.get(slot)
        if canonical and canonical not in snap['policies'].get('skills', []) and canonical not in snap['skills'].get('built_in', []):
            raise ModelError('O programa principal não oferece esta habilidade de movimento; alterar apenas o slot do modelo não confirma sua ativação.')
        skill = next((r for r in self._rows(snap['skills'], 'skills')
                      if isinstance(r, dict) and r.get('name') == canonical and isinstance(r.get('path'), str)), None)
        changed_skill = skill is not None and slot not in ('sitstand', 'ground_pick') and skill['path'] != item['path']
        expected_skill = (canonical, item['path']) if changed_skill else None
        try:
            await self._write_rpc('robot.loadPolicy', {'slot': slot, 'path': item['path']})
            if changed_skill:
                await self._require_idle()
                await self._write_rpc('robot.setSkill', {'name': canonical, 'path': item['path']})
            await self._wait_loaded(slot, item['path'], expected_skill)
        except Exception as exc:
            try:
                await self._require_idle()
                await self._write_rpc('robot.loadPolicy', {'slot': slot, 'path': old or 'none'})
                if changed_skill:
                    await self._write_rpc('robot.setSkill', {'name': canonical, 'path': skill['path']})
                await self._wait_loaded(slot, old or 'none', (canonical, skill['path']) if changed_skill else None)
            except Exception as rollback:
                raise ModelError(f'Falha ao trocar o modelo: {exc}; a reversão para a configuração anterior também não foi confirmada: {rollback}', status=503, code='rollback_failed') from exc
            raise ModelError(f'Falha ao trocar o modelo: {exc}; configuração do modelo anterior restaurada.', status=503, code='load_failed') from exc

    async def _restore_disabled(self, slot, snap):
        old = next((r.get('path') for r in self._rows(snap['policies'], 'slots') if r['slot'] == slot), None)
        try:
            await self._require_idle()
            await self._write_rpc('robot.loadPolicy', {'slot': slot, 'path': 'none'})
            await self._wait_loaded(slot, 'none')
        except Exception as exc:
            try:
                await self._require_idle()
                await self._write_rpc('robot.loadPolicy', {'slot': slot, 'path': old or 'none'})
                await self._wait_loaded(slot, old or 'none')
            except Exception as rollback:
                raise ModelError(f'Falha ao restaurar o padrão não instalado: {exc}; a reversão também não foi confirmada: {rollback}', status=503, code='rollback_failed') from exc
            raise ModelError(f'Falha ao restaurar o padrão não instalado: {exc}; configuração anterior restaurada.', status=503, code='load_failed') from exc

    async def _wait_bindings(self, expected):
        deadline = time.monotonic() + READBACK_TIMEOUT
        while True:
            try:
                data = await self._call('pad.bindings')
                rows = {r.get('button'): r for r in self._rows(data, 'bindings') if isinstance(r, dict)}
                if all(b in rows and rows[b].get('skill') == spec['skill'] and
                       rows[b].get('overridden') is spec['overridden'] and not rows[b].get('error')
                       for b, spec in expected.items()):
                    return
            except Exception:
                pass
            if time.monotonic() >= deadline:
                raise ModelError('A configuração dos botões foi gravada, mas não foi confirmada pela leitura de retorno.', status=503)
            await asyncio.sleep(READBACK_POLL)

    async def _bind(self, args, snap):
        op = args['op']
        rows = {r.get('button'): r for r in self._rows(snap['bindings'], 'bindings') if isinstance(r, dict)}
        changes = []
        if op == 'reset_bindings':
            changes = [(b, None) for b in BUTTONS]
        else:
            button = args.get('button')
            if not isinstance(button, str) or button not in BUTTONS:
            raise ModelError('São aceitos somente os botões A, X, LB, RB e direcional para baixo.')
            skill = ''
            if op == 'bind':
                slot = args.get('slot')
                if not isinstance(slot, str) or slot not in SKILLS:
                    raise ModelError('Caminhar e ficar em pé de forma independente não são habilidades individuais que possam ser vinculadas.')
                selected = next((r for r in self._rows(snap['policies'], 'slots')
                                 if isinstance(r, dict) and r.get('slot') == slot), {})
                if not selected.get('path') or selected.get('error'):
                    raise ModelError('Ainda não há um modelo disponível para este movimento. Selecione um modelo primeiro.')
                skill = SKILLS[slot]
                current = rows.get(button, {}).get('skill')
                if current and current != skill and args.get('replace') is not True:
                    label = next((LABELS[s] for s, sk in SKILLS.items() if sk == current), current)
                    raise ModelError(f'{BUTTONS[button]} está vinculado a “{label}”. Confirme a substituição antes de alterar.', status=409, code='binding_conflict')
            changes = [(button, skill)]
        if any(b not in rows or not isinstance(rows[b].get('skill'), str) or not isinstance(rows[b].get('overridden'), bool) for b, _ in changes):
            raise ModelError('A leitura de retorno da configuração original dos botões está incompleta; não é possível registrar a origem para reversão.', status=503)
        attempted = []
        try:
            expected = {}
            for button, skill in changes:
                await self._require_idle()
                attempted.append(button)
                params = {'button': button}
                if skill is not None:
                    params['skill'] = skill
                await self._write_rpc('pad.bind', params)
                target_skill = DEFAULT_KEYS[button] if skill is None else skill
                expected[button] = {'skill': target_skill, 'overridden': target_skill != DEFAULT_KEYS[button]}
            await self._wait_bindings(expected)
        except Exception as exc:
            try:
                for button in reversed(attempted):
                    await self._require_idle()
                    params = {'button': button}
                    if rows[button]['overridden']:
                        params['skill'] = rows[button]['skill']
                    await self._write_rpc('pad.bind', params)
                await self._wait_bindings({b: rows[b] for b in attempted})
            except Exception as rollback:
                raise ModelError(f'Falha ao alterar os botões: {exc}; a reversão para a configuração anterior também não foi confirmada: {rollback}', status=503, code='rollback_failed') from exc
            raise ModelError(f'Falha ao alterar os botões: {exc}; configuração anterior dos botões restaurada.', status=503, code='binding_failed') from exc

    async def handle(self, args, by=None):
        if not isinstance(args, dict) or args.get('op') not in ('rename', 'select', 'restore', 'delete', 'bind', 'unbind', 'reset_bindings'):
            raise ModelError('Operação de gerenciamento de modelos não suportada.')
        op = args['op']
        async with self._lock:
            snap = await self._snapshot()
            catalog, entries = await self._library(snap)
            if op == 'rename':
                item = self._item(entries, args.get('id'))
                await self._disk(self._rename, item, catalog, self._name(args.get('name')))
            elif op == 'delete':
                item = self._item(entries, args.get('id'))
                refs, config_error = await asyncio.to_thread(self._configured_refs)
                refs.update(self._references(snap))
                refs = await asyncio.to_thread(self._normalize_refs, refs)
                reason = self._delete_reason(item, snap, refs, config_error)
                if reason:
                    raise ModelError(reason, status=409, code='model_in_use')
                await self._disk(self._delete, item)
            else:
                reason = self._idle_reason(snap)
                if reason:
                    raise ModelError(reason, status=409, code='not_idle')
                if op in ('select', 'restore'):
                    slot = args.get('slot')
                    if slot not in SLOTS:
                        raise ModelError('Slot de execução do modelo desconhecido.')
                    ident = args.get('id') if op == 'select' else (catalog['defaults'].get(slot) or {}).get('id')
                    if not ident:
                        raise ModelError('Não há um modelo padrão integrado salvo para este movimento; não é possível restaurá-lo.')
                    if op == 'restore' and catalog['defaults'][slot].get('disabled'):
                        await self._restore_disabled(slot, snap)
                    else:
                        item = self._item(entries, ident)
                        await self._select(item, slot, catalog, snap)
                else:
                    await self._bind(args, snap)
        if self.log:
            self.log.write('Configuração de gerenciamento de modelos confirmada', cat='Modelos', raw=f'op={op}; by={by or "web"}')
        return await self.view()
