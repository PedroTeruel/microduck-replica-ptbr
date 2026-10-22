"""Read-only prerequisite probes; never installs or synchronizes dependencies."""
import json
import platform
import shutil
import subprocess
from pathlib import Path


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
    add("已安装的锁定环境", venv.is_file() or demo, "真实模式要求已按 uv.lock 准备 .venv；运行时 --frozen --no-sync --offline。")
    gpu = None
    if not demo and linux and files_ok and uv and venv.is_file():
        probe = (
            "import json,importlib.metadata as m,torch,mjlab_microduck.tasks; "
            "from mjlab.tasks.registry import list_tasks; "
            "from mjlab.rl.config import RslRlBaseRunnerCfg; "
            "print(json.dumps({'version':m.version('mjlab'),'cuda':torch.cuda.is_available(),"
            "'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,"
            "'tasks':list_tasks(),'resume':all(k in RslRlBaseRunnerCfg.__dataclass_fields__ for k in ['resume','load_run','load_checkpoint'])}))"
        )
        try:
            output = subprocess.run([uv, "run", "--frozen", "--no-sync", "--offline", "python", "-c", probe],
                                    cwd=root, text=True, capture_output=True, timeout=20, check=False)
            data = json.loads(output.stdout.strip().splitlines()[-1]) if output.returncode == 0 else {}
            expected = {"Mjlab-Velocity-Flat-MicroDuck-HD1910", "Mjlab-Velocity-Rough-MicroDuck-HD1910"}
            ok = data.get("version") == "1.3.0" and data.get("cuda") and data.get("resume") and expected.issubset(data.get("tasks", []))
            gpu = data.get("gpu")
            add("CUDA 与 mjlab 1.3.0", ok, gpu or output.stderr[-1200:] or "CUDA、任务注册或恢复接口未通过检查。")
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            add("CUDA 与 mjlab 1.3.0", False, str(exc))
    else:
        add("CUDA 与 mjlab 1.3.0", demo, "演示不需要 GPU。" if demo else "前置条件不足，未启动 GPU 探测。")
    return {"ready": all(c["ok"] for c in checks), "pause_supported": demo or linux,
            "checks": checks, "gpu": gpu, "training_root": str(root)}
