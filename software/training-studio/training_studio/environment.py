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

    add("运行模式", True, "DEMO：合成曲线与文本检查点，不进行策略训练。" if demo else "真实本地训练，不调用云服务。")
    add("Linux 进程控制", linux or demo, "演示子进程支持合作式暂停。" if demo else "真实暂停需要 Linux SIGSTOP/SIGCONT；暂停仍占用显存和计费资源。")
    files_ok = all((root / p).is_file() for p in ("pyproject.toml", "uv.lock", "scripts/export.py", "src/mjlab_microduck/train_cli.py"))
    add("训练引擎", files_ok or demo, str(root))
    uv = shutil.which("uv")
    add("uv", bool(uv) or demo, uv or "未找到 uv；本工具不自动安装依赖。")
    venv = root / ".venv" / "bin" / "python"
    add("已安装的锁定环境", demo or venv.is_file(), "真实模式要求已按 uv.lock 准备 .venv；运行时 --frozen --no-sync --offline。")
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
            gl_detail = "图形后端导入通过。" if data.get("gl") else data.get("gl_error") or output.stderr[-1200:] or "图形后端未通过检查。"
            add("MuJoCo 图形后端", data.get("gl"), f"MUJOCO_GL={environment['MUJOCO_GL']}；{gl_detail}")
            expected = {recipe["task_id"] for recipe in RECIPES}
            ok = data.get("version") == "1.3.0" and data.get("cuda") and data.get("resume") and expected.issubset(data.get("tasks", []))
            gpu = data.get("gpu")
            dependency_versions = data.get("dependency_versions", {})
            add("CUDA 与 mjlab 1.3.0", ok, gpu or output.stderr[-1200:] or ("图形后端未通过，未继续检查 CUDA 与任务。" if data.get("gl_error") else "CUDA、任务注册或恢复接口未通过检查。"))
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            add("CUDA 与 mjlab 1.3.0", False, str(exc))
    else:
        add("CUDA 与 mjlab 1.3.0", demo, "演示不需要 GPU。" if demo else "前置条件不足，未启动 GPU 探测。")
    return {"ready": all(c["ok"] for c in checks), "pause_supported": demo or linux,
            "checks": checks, "gpu": gpu, "training_root": str(root),
            "dependency_versions": dependency_versions,
            "dependency_versions_source": "installed Python distributions" if dependency_versions else "unavailable"}
