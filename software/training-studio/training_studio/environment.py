"""Read-only prerequisite probes; never installs or synchronizes dependencies."""
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from .config import RECIPES


def runtime_environment():
    """Use the same rendering backend for prerequisite probes and engine jobs."""
    environment = os.environ.copy()
    environment.setdefault("MUJOCO_GL", "egl")
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def inspect_environment(training_root, demo=False):
    root = Path(training_root).resolve()
    linux = platform.system() == "Linux"
    checks = []

    def add(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("Modo de execução", True, "DEMO: curvas sintéticas e checkpoints de texto; não realiza treinamento de política." if demo else "Treinamento local real; não usa serviços em nuvem.")
    add("Controle de processos Linux", linux or demo, "O processo filho de demonstração permite pausa cooperativa." if demo else "A pausa real exige Linux SIGSTOP/SIGCONT; mesmo pausado, continua ocupando VRAM e recursos computacionais.")
    files_ok = all((root / p).is_file() for p in ("pyproject.toml", "uv.lock", "scripts/export.py", "src/mjlab_microduck/train_cli.py"))
    add("Mecanismo de treinamento", files_ok or demo, str(root))
    uv = shutil.which("uv")
    add("uv", bool(uv) or demo, uv or "uv não encontrado; esta ferramenta não instala dependências automaticamente.")
    venv = root / ".venv" / "bin" / "python"
    add("Ambiente fixado instalado", demo or venv.is_file(), "O modo real exige que .venv tenha sido preparado com uv.lock; execução com --frozen --no-sync --offline.")
    gpu = None
    dependency_versions = {}
    if not demo and linux and files_ok and uv and venv.is_file():
        environment = runtime_environment()
        probe = (
            "import json\n"
            "try:\n"
            " from mujoco import GLContext\n"
            "except Exception as exc:\n"
            " print(json.dumps({'gl_error':type(exc).__name__+': '+str(exc)}))\n"
            " raise SystemExit(0)\n"
            "import importlib.metadata as m,torch,mjlab_microduck.tasks; "
            "from mjlab.tasks.registry import list_tasks; "
            "from mjlab.rl.config import RslRlBaseRunnerCfg\n"
            "versions = {}\n"
            "for name in ['mjlab','rsl-rl-lib','torch','mujoco-warp']:\n"
            " try:\n"
            "  versions[name] = m.version(name)\n"
            " except m.PackageNotFoundError:\n"
            "  pass\n"
            "print(json.dumps({'gl':True,'version':m.version('mjlab'),'cuda':torch.cuda.is_available(),"
            "'dependency_versions':versions,"
            "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"
            "'tasks':list_tasks(),'resume':all(k in RslRlBaseRunnerCfg.__dataclass_fields__ for k in ['resume','load_run','load_checkpoint'])}))"
        )
        try:
            # Registering all frozen task configs took 24 s on a working WSL GPU
            # environment; allow cold imports without treating them as failure.
            output = subprocess.run([uv, "run", "--frozen", "--no-sync", "--offline", "python", "-c", probe],
                                    cwd=root, env=environment, text=True, capture_output=True, timeout=60, check=False)
            data = json.loads(output.stdout.strip().splitlines()[-1]) if output.returncode == 0 else {}
            gl_detail = "Importação do backend gráfico aprovada." if data.get("gl") else data.get("gl_error") or output.stderr[-1200:] or "O backend gráfico não passou na verificação."
            add("Backend gráfico MuJoCo", data.get("gl"), f"MUJOCO_GL={environment['MUJOCO_GL']}; {gl_detail}")
            expected = {recipe["task_id"] for recipe in RECIPES}
            ok = data.get("version") == "1.3.0" and data.get("cuda") and data.get("resume") and expected.issubset(data.get("tasks", []))
            gpu = data.get("gpu")
            dependency_versions = data.get("dependency_versions", {})
            add("CUDA e mjlab 1.3.0", ok, gpu or output.stderr[-1200:] or ("O backend gráfico não passou; a verificação de CUDA e das tarefas não continuou." if data.get("gl_error") else "CUDA, registro da tarefa ou interface de recuperação não passou na verificação."))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            add("CUDA e mjlab 1.3.0", False, str(exc))
    else:
        add("CUDA e mjlab 1.3.0", demo, "A demonstração não precisa de GPU." if demo else "Pré-requisitos insuficientes; a verificação da GPU não foi iniciada.")
    return {"ready": all(c["ok"] for c in checks), "pause_supported": demo or linux,
            "checks": checks, "gpu": gpu, "training_root": str(root),
            "dependency_versions": dependency_versions,
            "dependency_versions_source": "installed Python distributions" if dependency_versions else "unavailable"}
