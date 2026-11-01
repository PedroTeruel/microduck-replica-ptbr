"""Limites de importação de arquivos ZIP/TAR reais; a pré-verificação do robotd valida a semântica do ONNX sem hardware."""
import copy
import gzip
import hashlib
import io
import json
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from studio import model_package as M
except ImportError:
    M = None


# Campos básicos do contrato de exportação de caminhada HD1910; não substitui a pré-verificação completa do robotd.
JOINTS = (
    "left_hip_yaw,left_hip_roll,left_hip_pitch,left_knee,left_ankle,neck_pitch,"
    "head_pitch,head_yaw,head_roll,right_hip_yaw,right_hip_roll,right_hip_pitch,"
    "right_knee,right_ankle"
).split(",")
HOME = [0, -.0873, -.4579, -.0049, .453, .3491, .3491, 0, 0, 0, .0873, .4579, .0049, -.453]
CONTRACT = {
    "schema": "microduck-deployment-contract/v1",
    "task": "Mjlab-VelStand-Rough-Backlash-MicroDuck",
    "task_adapter": "hd1910-official0151",
    "input_dim": 61, "output_dim": 14, "obs_normalizer": "baked_in_onnx",
    "control_hz": 50.0, "target_firmware": {"version": "0.15.1"}, "slot": "walk",
    "model": {
        "joints": [{"name": n, "home_rad": h} for n, h in zip(JOINTS, HOME)],
        "actuators": [{"kp_fw": 5.0, "parameter_file": {
            "sha256": "ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb"}}],
    },
    "onnx_metadata": {"joint_names": ",".join(JOINTS)},
    "actions": {"joint_pos": {"scale": 1.0, "offset": 0.0, "use_default_offset": True}},
    "observations": {"terms": {name: {} for name in (
        "base_ang_vel", "projected_gravity", "joint_pos", "joint_vel", "actions",
        "command", "head_command", "body_command")}},
    "commands": {"twist": {"ranges": {"lin_vel_x": [-.4, .4]}}},
}


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def bundle():
    policy = b"ONNX bytes are validated by the installed robotd, not this archive reader"
    digest = hashlib.sha256(policy).hexdigest()
    return {
        "policy.onnx": policy,
        "manifest.json": encode({"onnx_sha256": digest, "task": CONTRACT["task"], "name": "velstand"}),
        "deployment-contract.json": encode(CONTRACT),
    }


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M, "O módulo de importação de pacotes de modelos ainda não foi implementado.")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dest = self.root / "extracted"

    def archive(self, files=None, suffix=".zip", prefix=""):
        files = bundle() if files is None else files
        path = self.root / ("upload" + suffix)
        if suffix == ".zip":
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    for name, data in (files.items() if isinstance(files, dict) else files):
                        info = zipfile.ZipInfo(prefix + name)
                        # O ZipInfo do Windows converte barras invertidas; preserva o caminho original fornecido.
                        info.filename = info.orig_filename = prefix + name
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, data)
        else:
            with tarfile.open(path, "w:gz") as archive:
                for name, data in (files.items() if isinstance(files, dict) else files):
                    info = tarfile.TarInfo(prefix + name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
        return path

    def reject(self, files, reason, suffix=".zip"):
        with self.assertRaisesRegex(M.PackageError, reason):
            M.extract_package(self.archive(files, suffix), self.dest)
        self.assertFalse(self.dest.exists(), "Uma falha não deve deixar um modelo parcialmente extraído.")

    def test_zip_and_tar_single_model_prefix_is_flattened(self):
        for suffix in (".zip", ".tar.gz", ".tgz"):
            with self.subTest(suffix=suffix):
                dest = self.root / suffix.replace(".", "_")
                data = M.extract_package(self.archive(prefix="exports/2026/duck/", suffix=suffix), dest)
                self.assertEqual(data["onnx"], "policy.onnx")
                self.assertEqual(data["slot"], "walk")
                self.assertEqual(data["task"], CONTRACT["task"])
                self.assertEqual(data["name"], "velstand")
                self.assertEqual(data["files"], sorted(bundle()))
                self.assertEqual(data["sha256"], hashlib.sha256(bundle()["policy.onnx"]).hexdigest())
                self.assertEqual((dest / "policy.onnx").read_bytes(), bundle()["policy.onnx"])

    def test_directory_entries_and_existing_empty_destination_are_allowed(self):
        path = self.archive(prefix="exports/duck/")
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("exports/", b"")
            archive.writestr("exports/duck/", b"")
        self.dest.mkdir()
        M.extract_package(path, self.dest)
        self.assertTrue((self.dest / "manifest.json").is_file())

    def test_optional_runtime_files_are_kept_without_rewriting(self):
        files = bundle()
        digest = hashlib.sha256(files["policy.onnx"]).hexdigest()
        files.update({
            "deployment-execution.json": encode({"schema": "microduck-runtime-execution/v1", "model_sha256": digest,
                "mode": "uniform", "action_scale": 1.0, "head_lowpass": .5, "legs_lowpass": .7}),
            "deployment-runtime.json": encode({"schema": "microduck-runtime-commands/v1", "model_sha256": digest, "commands": {}}),
            "model-info.json": encode({"name": "Meu modelo de caminhada"}),
        })
        result = M.extract_package(self.archive(files), self.dest)
        self.assertEqual(result["name"], "Meu modelo de caminhada")
        for name, content in files.items():
            self.assertEqual((self.dest / name).read_bytes(), content)

    def test_paths_cannot_escape_or_use_windows_aliases(self):
        for name in ("../policy.onnx", "/policy.onnx", "C:/policy.onnx", "foo\\policy.onnx", "foo/../policy.onnx", "foo//policy.onnx", "foo/./policy.onnx"):
            for suffix in (".zip", ".tgz"):
                with self.subTest(name=name, suffix=suffix):
                    self.reject({**bundle(), name: b"bad"}, "caminho", suffix)

    def test_duplicate_paths_are_refused_in_zip_and_tar(self):
        for suffix in (".zip", ".tar.gz"):
            self.reject(list(bundle().items()) + [("policy.onnx", b"other")], "duplicado", suffix)

    def test_multiple_models_or_unknown_files_are_refused(self):
        self.reject({**bundle(), "second/policy.onnx": b"other"}, "vários modelos")
        self.reject({**bundle(), "logs/train.txt": b"log"}, "arquivo não aceito")
        self.reject({**bundle(), "model.pt": b"checkpoint"}, "arquivo não aceito")

    def test_missing_empty_files_and_malformed_archive_are_refused(self):
        files = bundle(); del files["manifest.json"]
        self.reject(files, "Falta")
        self.reject({**bundle(), "policy.onnx": b""}, "vazio")
        path = self.root / "broken.zip"; path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(M.PackageError, "arquivo compactado|arquivo"):
            M.extract_package(path, self.dest)

    def test_corrupt_deflate_stream_is_a_package_error(self):
        path = self.archive()
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("policy.onnx")
        payload = bytearray(path.read_bytes())
        start = info.header_offset + 30 + len(info.filename.encode("utf-8")) + len(info.extra)
        payload[start] = 0xff  # Tipo de bloco reservado do DEFLATE; o descompactador lançará zlib.error.
        path.write_bytes(payload)
        with self.assertRaisesRegex(M.PackageError, "arquivo compactado|arquivo"):
            M.extract_package(path, self.dest)
        self.assertFalse(self.dest.exists())

    def test_zip_links_and_devices_are_refused(self):
        for mode in (stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK):
            path = self.archive()
            with zipfile.ZipFile(path, "a") as archive:
                info = zipfile.ZipInfo("extra")
                info.create_system = 3; info.external_attr = (mode | 0o777) << 16
                archive.writestr(info, b"policy.onnx")
            with self.assertRaisesRegex(M.PackageError, "link|arquivo de dispositivo especial"):
                M.extract_package(path, self.dest)

    def test_tar_links_devices_and_sparse_entries_are_refused(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.GNUTYPE_SPARSE):
            path = self.archive(suffix=".tgz")
            # Rewrite a real tar archive with the special entry, rather than mocking members.
            with tarfile.open(path, "w:gz") as archive:
                info = tarfile.TarInfo("policy.onnx"); info.type = kind; info.linkname = "outside"
                archive.addfile(info)
            with self.assertRaisesRegex(M.PackageError, "links|arquivos esparsos|arquivo de dispositivo especial"):
                M.extract_package(path, self.dest)

    def test_large_tar_metadata_is_bounded_before_parser_allocation(self):
        path = self.root / "metadata.tgz"
        with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            info = tarfile.TarInfo("policy.onnx")
            info.pax_headers = {"comment": "x" * (2 * 1024 * 1024)}
            info.size = 1; archive.addfile(info, io.BytesIO(b"x"))
        with self.assertRaisesRegex(M.PackageError, "metadados"):
            M.extract_package(path, self.dest)

    def test_accumulated_tar_extension_headers_cannot_bypass_expansion_limit(self):
        path = self.root / "many-pax.tgz"
        pax = tarfile.TarInfo.create_pax_global_header({"comment": "x" * 2000})
        info = tarfile.TarInfo("policy.onnx"); info.size = 1
        with gzip.open(path, "wb") as stream:
            stream.write(pax * 50 + info.tobuf() + b"x" + b"\0" * (511 + 1024))
        with mock.patch.object(M, "MAX_EXPANDED_BYTES", 1):
            with self.assertRaisesRegex(M.PackageError, "descompactado"):
                M.extract_package(path, self.dest)

    def test_size_and_file_count_limits(self):
        archive = self.archive()
        for constant, value, reason in (("MAX_ARCHIVE_BYTES", 1, "arquivo compactado"), ("MAX_FILE_BYTES", 1, "arquivo"),
                                       ("MAX_EXPANDED_BYTES", 1, "descompactado"), ("MAX_FILES", 2, "itens")):
            with mock.patch.object(M, constant, value):
                with self.assertRaisesRegex(M.PackageError, reason):
                    M.extract_package(archive, self.dest)
            self.assertFalse(self.dest.exists())

    def test_checksum_task_and_optional_identities_are_checked(self):
        files = bundle()
        files["policy.onnx"] += b"changed"
        self.reject(files, "SHA256")
        files = bundle()
        manifest = json.loads(files["manifest.json"]); manifest["task"] = "another"
        files["manifest.json"] = encode(manifest)
        self.reject(files, "tarefa")
        for name, schema in (("deployment-runtime.json", "microduck-runtime-commands/v1"),
                             ("deployment-execution.json", "microduck-runtime-execution/v1")):
            self.reject({**bundle(), name: encode({"schema": schema, "model_sha256": "0" * 64})}, "verificação SHA256 do modelo")

    def test_basic_contract_fields_and_joint_home_are_required(self):
        for field, value in (("schema", "other"), ("input_dim", 60), ("output_dim", 15),
                             ("obs_normalizer", "external"), ("task_adapter", "unknown"),
                             ("model", {}), ("observations", {}), ("actions", {})):
            contract = copy.deepcopy(CONTRACT); contract[field] = value
            self.reject({**bundle(), "deployment-contract.json": encode(contract)}, "contrato de implantação")
        contract = copy.deepcopy(CONTRACT); contract["model"]["joints"][0]["home_rad"] = "oops"
        self.reject({**bundle(), "deployment-contract.json": encode(contract)}, "posição Home da articulação")
        contract = copy.deepcopy(CONTRACT); contract["model"]["joints"][0]["home_rad"] = 10 ** 400
        self.reject({**bundle(), "deployment-contract.json": encode(contract)}, "posição Home da articulação")

    def test_json_objects_no_duplicates_or_nonfinite_numbers(self):
        self.reject({**bundle(), "manifest.json": b'[]'}, "JSON.*objeto")
        self.reject({**bundle(), "model-info.json": b'{"name":"a","name":"b"}'}, "JSON.*duplicado")
        self.reject({**bundle(), "model-info.json": b'{"value": NaN}'}, "números.*finitos")

    def test_json_metadata_has_a_smaller_limit_before_parsing(self):
        metadata = encode({"description": "x" * (8 * 1024 * 1024)})
        self.reject({**bundle(), "model-info.json": metadata}, "JSON.*8 MiB")

    def test_task_recommendation_does_not_invent_roller_stand_slot(self):
        contract = copy.deepcopy(CONTRACT)
        contract["task"] = "Mjlab-RollerStandUp-Flat-MicroDuck"; contract["slot"] = None
        files = bundle(); files["deployment-contract.json"] = encode(contract)
        manifest = json.loads(files["manifest.json"]); manifest["task"] = contract["task"]
        files["manifest.json"] = encode(manifest)
        self.assertIsNone(M.extract_package(self.archive(files), self.dest)["slot"])

    def test_existing_destination_is_not_overwritten(self):
        self.dest.mkdir(); marker = self.dest / "keep"; marker.write_text("original")
        with self.assertRaisesRegex(M.PackageError, "diretório novo ou existente e vazio"):
            M.extract_package(self.archive(), self.dest)
        self.assertEqual(marker.read_text(), "original")


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M, "O módulo de pré-verificação de modelos ainda não foi implementado.")

    def test_uses_argument_vector_and_returns_real_preflight_json(self):
        result = {"valid": True, "input": "obs", "observations": 61, "actions": 14}
        with mock.patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, encode(result).decode(), "")) as run:
            self.assertEqual(M.validate_policy(Path("/models/with spaces/policy.onnx"), "/opt/robot/robotd"), result)
        self.assertEqual(run.call_args.args[0], ["/opt/robot/robotd", "validate-policy", str(Path("/models/with spaces/policy.onnx"))])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_runtime_library_environment_can_be_passed_explicitly(self):
        env = {"ORT_DYLIB_PATH": "/opt/robot/lib/libonnxruntime.so"}
        with mock.patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"valid":true}', "")) as run:
            M.validate_policy(Path("/models/policy.onnx"), "robotd", env=env)
        self.assertEqual(run.call_args.kwargs["env"], env)

    def test_failure_invalid_json_and_false_validation_are_not_success(self):
        for code, out, error in ((1, "", "bad graph"), (0, "invalid", ""), (0, '{"valid":false}', ""),
                                 (0, '[true]', ""), (0, '{"valid":1}', ""), (0, '{"valid":true,"x":NaN}', "")):
            with mock.patch.object(M.subprocess, "run", return_value=subprocess.CompletedProcess([], code, out, error)):
                with self.assertRaises(M.PackageError):
                    M.validate_policy(Path("/models/policy.onnx"), "robotd")

    def test_timeout_or_missing_runtime_is_reported_in_portuguese(self):
        for error, reason in ((subprocess.TimeoutExpired("robotd", 45), "tempo limite"),
                              (FileNotFoundError("missing"), "iniciar a pré-verificação")):
            with mock.patch.object(M.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(M.PackageError, reason):
                    M.validate_policy(Path("/models/policy.onnx"), "robotd")


if __name__ == "__main__":
    unittest.main()
