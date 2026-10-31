"""Limites de importação de modelos e pré-verificação sem hardware; não grava a configuração do robotd nem acessa o barramento.

Aqui são verificados apenas os dados básicos de identidade do contrato exportado. O mapeamento de observações, os filtros, o adaptador de tarefa e a compatibilidade completa do grafo ONNX
são validados pelo robotd instalado localmente, por meio de validate-policy. O sucesso da extração não substitui essa validação.
"""
from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
import stat
import subprocess
import tarfile
import tempfile
import unicodedata
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_FILES = 64
PREFLIGHT_TIMEOUT = 45

REQUIRED = frozenset(("policy.onnx", "manifest.json", "deployment-contract.json"))
OPTIONAL = frozenset(("deployment-execution.json", "deployment-runtime.json", "model-info.json"))
JOINT_NAMES = (
    "left_hip_yaw", "left_hip_roll", "left_hip_pitch", "left_knee", "left_ankle",
    "neck_pitch", "head_pitch", "head_yaw", "head_roll", "right_hip_yaw",
    "right_hip_roll", "right_hip_pitch", "right_knee", "right_ankle",
)
BAM_SHA256 = "ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb"


class PackageError(ValueError):
    """Erro legível que pode ser exibido diretamente a quem está importando."""


def _safe_name(raw: str, directory: bool) -> PurePosixPath:
    if not raw or "\\" in raw or ":" in raw or raw.startswith("/") or "\x00" in raw:
        raise PackageError(f"O arquivo compactado contém um caminho inseguro：{raw!r}")
    name = raw[:-1] if directory and raw.endswith("/") else raw
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise PackageError(f"O arquivo compactado contém um caminho inválido：{raw!r}")
    if any(ord(c) < 32 for c in name):
        raise PackageError("O caminho no arquivo compactado contém caracteres de controle")
    return PurePosixPath(name)


def _zip_entries(archive):
    for info in archive.infolist():
        if info.orig_filename != info.filename:
            raise PackageError("O caminho no arquivo compactado contém um caractere nulo")
        kind = stat.S_IFMT(info.external_attr >> 16)
        directory = info.is_dir()
        allowed = (0, stat.S_IFDIR) if directory else (0, stat.S_IFREG)
        if kind not in allowed:
            raise PackageError("O arquivo compactado contém um link ou arquivo de dispositivo especial")
        if info.flag_bits & 1:
            raise PackageError("Arquivos compactados de modelos criptografados não são aceitos")
        yield info.filename, directory, info.file_size, lambda i=info: archive.open(i, "r")


def _tar_entries(archive):
    for info in archive:
        if (not info.isdir() and not info.isfile()) or info.issparse():
            raise PackageError("O arquivo compactado contém links, arquivos esparsos ou arquivos de dispositivo especial")
        yield info.name, info.isdir(), info.size, lambda i=info: archive.extractfile(i)


class _TarStream:
    """tarfile lê em bloco os metadados PAX e nomes longos antes de retornar um item; limitamos essas alocações primeiro."""
    def __init__(self, stream):
        self.stream = stream

    def read(self, size=-1):
        if size < 0 or size > 1024 * 1024:
            raise PackageError("Os metadados do arquivo compactado são grandes demais para uma leitura segura")
        return self.stream.read(size)

    def tell(self):
        return self.stream.tell()

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.tell() + offset
        # Cabeçalhos tar e preenchimento final não contam no tamanho descompactado, mas continuam sujeitos a um limite.
        if whence not in (0, 1) or not 0 <= position <= MAX_EXPANDED_BYTES + MAX_FILES * 1024 + 10240:
            raise PackageError("O tamanho descompactado excede o limite")
        return self.stream.seek(offset, whence)


@contextmanager
def _tar_archive(path):
    with gzip.open(path, "rb") as stream:
        with tarfile.open(fileobj=_TarStream(stream), mode="r:") as archive:
            yield archive


def _layout(entries):
    """Verifica todo o arquivo compactado antes de ler os arquivos, para não ignorar entradas perigosas em arquivos desconhecidos."""
    files, directories, seen = [], [], set()
    total = 0
    for raw, directory, size, opener in entries:
        if len(seen) >= MAX_FILES:
            raise PackageError(f"O arquivo compactado contém itens demais (máximo: {MAX_FILES} arquivos ou diretórios)")
        path = _safe_name(raw, directory)
        key = unicodedata.normalize("NFC", str(path)).casefold()
        if key in seen:
            raise PackageError(f"O arquivo compactado contém um caminho duplicado: {path}")
        seen.add(key)
        if directory:
            directories.append(path)
            continue
        if size < 0 or size > MAX_FILE_BYTES:
            raise PackageError("Um arquivo do modelo excede o limite de 128 MiB")
        total += size
        if total > MAX_EXPANDED_BYTES:
            raise PackageError("O conteúdo descompactado excede o limite de 256 MiB")
        files.append((path, size, opener))
    roots = [path.parent for path, _, _ in files if path.name == "policy.onnx"]
    if len(roots) > 1:
        raise PackageError("Há vários modelos no arquivo compactado. Importe um diretório de modelo por vez.")
    if not roots:
        raise PackageError("Falta policy.onnx no pacote do modelo")
    root = roots[0]
    for path, _, _ in files:
        if path.parent != root or path.name not in REQUIRED | OPTIONAL:
            raise PackageError(f"O pacote contém um arquivo não aceito: {path}. Inclua somente o modelo e o contrato de implantação; remova logs de treinamento e outros arquivos.")
    if any(path != root and path not in root.parents for path in directories):
        raise PackageError("O pacote contém um diretório adicional não aceito")
    missing = REQUIRED - {path.name for path, _, _ in files}
    if missing:
        raise PackageError("Faltam arquivos no pacote do modelo: " + "、".join(sorted(missing)))
    return files


def _copy_file(opener, destination, size):
    if size == 0:
        raise PackageError(f"O arquivo do modelo está vazio: {destination.name}")
    count = 0
    with opener() as source, destination.open("xb") as target:
        while chunk := source.read(min(1024 * 1024, size - count + 1)):
            count += len(chunk)
            if count > size or count > MAX_FILE_BYTES:
                raise PackageError("O tamanho real de um arquivo não corresponde ao declarado ou excede o limite")
            target.write(chunk)
    if count != size:
        raise PackageError(f"Arquivo compactado incompleto: {destination.name}")


def _json_object(path):
    # O parser JSON aloca memória adicional para strings, listas e dicionários; não podemos usar o mesmo limite de arquivo único do ONNX.
    if path.stat().st_size > MAX_JSON_BYTES:
        raise PackageError(f"Os metadados JSON de {path.name} excedem o limite de 8 MiB")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PackageError(f"O JSON de {path.name} contém um campo duplicado: {key}")
            result[key] = value
        return result

    def finite_number(value):
        number = float(value)
        if not math.isfinite(number):
            raise PackageError(f"Os números no JSON de {path.name} devem ser finitos")
        return number

    def invalid_constant(value):
        raise PackageError(f"O JSON de {path.name} contém um número inválido: {value}")

    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=pairs,
                           parse_float=finite_number, parse_constant=invalid_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise PackageError(f"JSON inválido em {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"O JSON de {path.name} deve ser um objeto")
    return value


def _finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def _contract_basics(contract):
    if (contract.get("schema") != "microduck-deployment-contract/v1"
            or contract.get("task_adapter") not in ("hd1910-v1", "hd1910-v2", "hd1910-official0151")
            or type(contract.get("input_dim")) is not int or contract["input_dim"] != 61
            or type(contract.get("output_dim")) is not int or contract["output_dim"] != 14
            or contract.get("obs_normalizer") != "baked_in_onnx"
            or not isinstance(contract.get("task"), str) or not contract["task"].strip()):
        raise PackageError("O contrato de implantação deve ser da versão 1, compatível com HD1910, e conter observações normalizadas de 61 dimensões e ações de 14 dimensões")
    model = contract.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("joints"), list):
        raise PackageError("O contrato de implantação não contém as posições Home das articulações em model.joints")
    joints = model["joints"]
    for name in JOINT_NAMES:
        rows = [row for row in joints if isinstance(row, dict) and row.get("name") == name]
        if len(rows) != 1 or not _finite(rows[0].get("home_rad")):
            raise PackageError(f"A posição Home da articulação está ausente, duplicada ou inválida no contrato de implantação: {name}")
    metadata = contract.get("onnx_metadata")
    if not isinstance(metadata, dict) or metadata.get("joint_names") != ",".join(JOINT_NAMES):
        raise PackageError("A ordem das articulações ONNX no contrato de implantação não corresponde à do programa principal")
    actuators = model.get("actuators")
    if not isinstance(actuators, list) or len(actuators) != 1 or not isinstance(actuators[0], dict):
        raise PackageError("O contrato de implantação não contém exatamente um conjunto de parâmetros do atuador HD1910 BAM")
    actuator = actuators[0]
    parameter = actuator.get("parameter_file")
    p = actuator.get("kp_fw")
    if (not isinstance(parameter, dict) or parameter.get("sha256") != BAM_SHA256
            or not _finite(p) or not 1 <= p <= 32 or int(p) != p):
        raise PackageError("A validação dos parâmetros HD1910 BAM ou o valor P do firmware no contrato de implantação é inválido")
    actions = contract.get("actions")
    if not isinstance(actions, dict) or not isinstance(actions.get("joint_pos"), dict):
        raise PackageError("O contrato de implantação não contém o mapeamento de ações actions.joint_pos")
    observations = contract.get("observations")
    if not isinstance(observations, dict) or not isinstance(observations.get("terms"), dict):
        raise PackageError("O contrato de implantação não contém o mapeamento de observações observations.terms")


def _recommended_slot(contract):
    task = contract["task"]
    if task in ("Mjlab-BallKick-Flat-MicroDuck", "Mjlab-BallKickLeft-Flat-Backlash-MicroDuck"):
        return contract.get("slot") if contract.get("slot") in ("kick_left", "kick_right") else None
    if task.startswith("Mjlab-Velocity-") or task in ("Mjlab-VelStand-Flat-MicroDuck", "Mjlab-VelStand-Rough-Backlash-MicroDuck"):
        return "walk"
    for prefix, slot in (("Mjlab-SitStand-", "sitstand"), ("Mjlab-StandUp-", "stand"),
                         ("Mjlab-GroundPick-", "ground_pick"), ("Mjlab-Roulade-", "roulade")):
        if task.startswith(prefix):
            return slot
    if task in ("Mjlab-RollerCrouch-Flat-Backlash-MicroDuck", "Mjlab-Spin-Flat-MicroDuck"):
        return "ground_pick"
    return None


def _metadata(directory, names):
    manifest = _json_object(directory / "manifest.json")
    contract = _json_object(directory / "deployment-contract.json")
    with (directory / "policy.onnx").open("rb") as policy:
        digest = hashlib.file_digest(policy, "sha256").hexdigest()
    if manifest.get("onnx_sha256") != digest:
        raise PackageError("O SHA256 do ONNX não corresponde à verificação em manifest.json")
    if manifest.get("task") != contract.get("task"):
        raise PackageError("A tarefa em manifest.json não corresponde à do contrato de implantação")
    _contract_basics(contract)
    for name, schema in (("deployment-runtime.json", "microduck-runtime-commands/v1"),
                         ("deployment-execution.json", "microduck-runtime-execution/v1")):
        if name in names:
            value = _json_object(directory / name)
            if value.get("schema") != schema or value.get("model_sha256") != digest:
                raise PackageError(f"O formato de {name} ou a verificação SHA256 do modelo não corresponde")
    info = _json_object(directory / "model-info.json") if "model-info.json" in names else {}
    name = info.get("name") or manifest.get("name")
    return {"onnx": "policy.onnx", "sha256": digest, "task": contract["task"],
            "slot": _recommended_slot(contract), "name": name.strip() if isinstance(name, str) else None,
            "files": sorted(names)}


def extract_package(archive: Path, destination: Path) -> dict:
    """Importa um único modelo ZIP/tar.gz/tgz; entrega o diretório somente em caso de sucesso e não sobrescreve conteúdo existente."""
    archive, destination = Path(archive), Path(destination)
    if destination.is_symlink() or (destination.exists() and
            (not destination.is_dir() or any(destination.iterdir()))):
        raise PackageError("O destino da importação deve ser um diretório novo ou existente e vazio")
    try:
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise PackageError("O arquivo compactado do modelo excede o limite de 64 MiB")
        if archive.name.lower().endswith(".zip"):
            container = zipfile.ZipFile(archive, "r")
            reader = _zip_entries
        elif archive.name.lower().endswith((".tar.gz", ".tgz")):
            container = _tar_archive(archive)
            reader = _tar_entries
        else:
            raise PackageError("São aceitos somente arquivos de modelo .zip, .tar.gz ou .tgz")
        with container as contents:
            files = _layout(reader(contents))
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".model-import-", dir=destination.parent) as temporary:
                stage = Path(temporary) / "model"
                stage.mkdir()
                for path, size, opener in files:
                    _copy_file(opener, stage / path.name, size)
                metadata = _metadata(stage, {path.name for path, _, _ in files})
                if destination.exists():
                    destination.rmdir()
                os.replace(stage, destination)
                return metadata
    except PackageError:
        raise
    except (OSError, EOFError, ValueError, RuntimeError, NotImplementedError,
            zipfile.BadZipFile, tarfile.TarError, zlib.error) as exc:
        raise PackageError(f"Não foi possível ler ou extrair o arquivo compactado do modelo: {exc}") from exc


def validate_policy(path: Path, executable: str, *, env=None) -> dict:
    """Executa a pré-verificação offline do grafo pelo robotd; herda o ambiente do processo ou usa o ambiente de runtime fornecido pelo chamador."""
    try:
        result = subprocess.run([executable, "validate-policy", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=PREFLIGHT_TIMEOUT, shell=False, env=env)
    except subprocess.TimeoutExpired as exc:
        raise PackageError("A pré-verificação do modelo excedeu o tempo limite. Verifique o tamanho do modelo e o ONNX Runtime.") from exc
    except OSError as exc:
        raise PackageError(f"Não foi possível iniciar a pré-verificação do modelo: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "o runtime não informou o motivo").strip()[:2000]
        raise PackageError(f"Falha na pré-verificação do modelo pelo runtime: {detail}")
    try:
        def invalid_constant(value):
            raise ValueError(f"Valor JSON inválido: {value}")
        data = json.loads(result.stdout, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as exc:
        raise PackageError("A pré-verificação do modelo retornou JSON inválido") from exc
    if not isinstance(data, dict) or data.get("valid") is not True:
        raise PackageError("O runtime do modelo não confirmou a aprovação na pré-verificação (valid deve ser true)")
    return data
