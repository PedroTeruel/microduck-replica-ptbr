"""Durable local job ownership and subprocess lifecycle management."""
import copy
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .commands import ANSI, EXPERIMENT, build_train_argv, experiment_for, parse_metric
from .config import (RECIPES, RECIPE_BY_ID, StudioError, recipe_config,
                     skill_command_contract, validate_profile, validate_skill)
from .environment import inspect_environment, runtime_environment
from .resources import ResourceMonitor
from .pretrained import pretrained_models


ACTIVE = {"starting", "running", "paused", "stopping"}
TERMINAL = {"stopped", "completed", "failed", "interrupted"}
MAX_LOGS = 400
MAX_METRICS = 2000
CHECKPOINT_STABLE_SECONDS = 1.0


def smoke_family(recipe_id, mode, config, profile, skill=None):
    """Full archived profile equality; only parallelism/length/save cadence are excluded."""
    def normalize(value):
        if isinstance(value, dict):
            return {key: normalize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        if type(value) is float and value.is_integer():
            return int(value)
        return value
    return json.loads(json.dumps({"recipe_id": recipe_id, "mode": mode, "seed": config["seed"],
                                  "learning_rate": config["learning_rate"], "profile": normalize(profile),
                                  "skill": validate_skill(recipe_id, skill)},
                                 sort_keys=True, ensure_ascii=False, allow_nan=False))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".studio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class StudioService:
    def __init__(self, state_dir, training_root, demo=False, demo_interval=0.45):
        self.state_dir = Path(state_dir).resolve()
        self.training_root = Path(training_root).resolve()
        self.mode = "demo" if demo else "real"
        self.demo_interval = demo_interval
        self._condition = threading.Condition(threading.RLock())
        self._runs = {}
        self._children = {}
        self._readers = {}
        self._operation_threads = {}
        self._stop_requested = set()
        self._started = {}
        self._checkpoint_observations = {}
        self._process_locks = {}
        self._leader_watchers = {}
        self._active = None
        self._closing = False
        self._resource_monitor = ResourceMonitor(mode=self.mode)
        self._environment = inspect_environment(self.training_root, demo)
        (self.state_dir / "runs").mkdir(parents=True, exist_ok=True)
        for path in (self.state_dir / "runs").glob("*/run.json"):
            try:
                run = json.loads(path.read_text(encoding="utf-8"))
                if not re.fullmatch(r"[a-f0-9]{12}", run["id"]) or path.parent.name != run["id"]:
                    continue
                interrupted = run.get("status") in ACTIVE
                if interrupted:
                    run.update(status="interrupted", phase="服务重启，原任务已中断", error="服务重启后不恢复旧进程；可从已保存检查点创建新任务。")
                if run.get("operation", {}).get("status") == "running":
                    run["operation"].update(status="failed", error="服务重启，中断的操作不会自动重试。")
                    interrupted = True
                self._runs[run["id"]] = run
                if interrupted:
                    self._save(run)
            except (OSError, ValueError, KeyError, TypeError):
                # A corrupt record is left on disk for inspection; it grants no process ownership.
                continue

    def _save(self, run):
        run["updated_at"] = now()
        run["logs"] = run.get("logs", [])[-MAX_LOGS:]
        run["metrics"] = run.get("metrics", [])[-MAX_METRICS:]
        atomic_json(self._run_dir(run["id"]) / "run.json", run)

    def _run_dir(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{12}", run_id):
            raise StudioError("未找到任务", 404)
        return self.state_dir / "runs" / run_id

    def _get(self, run_id):
        if run_id not in self._runs:
            raise StudioError("未找到任务", 404)
        return self._runs[run_id]

    def _log(self, run, line):
        run["logs"].append(f"{now()}  {line[:3000]}")
        run["logs"] = run["logs"][-MAX_LOGS:]

    def _public(self, run):
        result = copy.deepcopy(run)
        result.pop("engine_log_dir", None)
        result.pop("artifacts", None)
        for checkpoint in result.get("checkpoints", []):
            checkpoint.pop("engine_path", None)
        return result

    def environment(self):
        return copy.deepcopy(self._environment)

    def resources(self):
        # Independent cached sampler: never holds the training/operation lock.
        return self._resource_monitor.snapshot()

    def refresh_environment(self):
        # Diagnostics may start a bounded read-only uv probe. Keep it outside the job lock.
        result = inspect_environment(self.training_root, self.mode == "demo")
        with self._condition:
            self._environment = result
            return copy.deepcopy(result)

    def state(self):
        with self._condition:
            return {"mode": self.mode, "environment": self.environment(), "recipes": copy.deepcopy(RECIPES),
                    "pretrained_models": pretrained_models(),
                    "runs": [self._public(r) for r in sorted(self._runs.values(), key=lambda r: r["created_at"], reverse=True)],
                    "active_run_id": self._active}

    def get_run(self, run_id):
        with self._condition:
            return self._public(self._get(run_id))

    def child_pid(self, run_id):
        with self._condition:
            child = self._children.get(run_id)
            return child.pid if child and self._peek(child) is None else None

    def _process_lock(self, child):
        return self._process_locks.setdefault(id(child), threading.RLock())

    def _peek(self, child):
        """Observe Linux exit without releasing its PID/PGID reservation."""
        with self._process_lock(child):
            if child.returncode is not None:
                return child.returncode
            if sys.platform == "linux":
                result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
                if result is None:
                    return None
                return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
            return child.poll()

    def _wait_exit(self, child, timeout):
        deadline = time.monotonic() + timeout
        while True:
            code = self._peek(child)
            if code is not None:
                return code
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("owned training child", timeout)
            time.sleep(0.025)

    def _start_leader_watcher(self, run_id, child):
        if sys.platform != "linux":
            return
        def watch():
            try:
                while self._peek(child) is None:
                    time.sleep(0.025)
                # Descendants may inherit stdout after the leader exits. Cleanup
                # must run independently of a reader waiting for pipe EOF.
                self._terminate(child)
            except Exception as exc:
                with self._condition:
                    run = self._runs[run_id]
                    detail = f"进程退出监视或清理失败：{exc}"
                    self._log(run, detail)
                    run["error"] = detail
                    run["phase"] = "进程清理失败，请查看日志；资源仍由本服务保留"
                    if run.get("operation", {}).get("status") == "running":
                        run["operation"].update(status="failed", error=detail)
                    else:
                        run["status"] = "failed"
                    self._save(run)
                    self._condition.notify_all()
            finally:
                with self._condition:
                    self._leader_watchers.pop(id(child), None)
        watcher = threading.Thread(target=watch, daemon=True, name=f"studio-leader-{run_id}")
        self._leader_watchers[id(child)] = watcher
        watcher.start()

    def _ensure_available(self):
        if self._closing:
            raise StudioError("服务正在关闭", 409)
        if self._active is not None:
            raise StudioError("已有任务占用训练资源；暂停任务仍占用资源。", 409)

    def create_run(self, payload, *, parent=None, checkpoint=None):
        if not isinstance(payload, dict) or set(payload) - {"name", "recipe_id", "kind", "config", "profile", "skill"}:
            raise StudioError("任务请求包含未知字段或格式无效")
        recipe_id = payload.get("recipe_id", "hd1910-flat")
        if not isinstance(recipe_id, str) or recipe_id not in RECIPE_BY_ID:
            raise StudioError("未知训练配方")
        recipe = RECIPE_BY_ID[recipe_id]
        kind = payload.get("kind", "smoke")
        config = recipe_config(recipe_id, payload.get("config", {}), kind)
        profile = validate_profile(payload.get("profile"))
        skill = validate_skill(recipe_id, payload.get("skill"))
        name = payload.get("name") or (recipe["title"] + (" · 冒烟测试" if kind == "smoke" else " · 训练"))
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or any(ord(c) < 32 for c in name):
            raise StudioError("任务名称最多 100 字，不能包含控制字符")
        with self._condition:
            self._ensure_available()
            if not self._environment["ready"]:
                raise StudioError("真实训练环境未就绪", 409, self.environment())
            family = smoke_family(recipe_id, self.mode, config, profile, skill)
            if kind == "train" and not any(r["kind"] == "smoke" and r["status"] == "completed" and
                                            json.dumps(smoke_family(r["recipe_id"], r["mode"], r["config"], r.get("profile"), r.get("skill")), sort_keys=True) == json.dumps(family, sort_keys=True)
                                            for r in self._runs.values()):
                raise StudioError("请先用同一配方、动作目标、随机种子、学习率和鸭子档案完成 64 环境、5 轮短试跑。", 409)
            run_id = uuid.uuid4().hex[:12]
            start_iteration = checkpoint["iteration"] if checkpoint else 0
            run = {"id": run_id, "name": name.strip(), "recipe_id": recipe_id, "task_id": recipe["task_id"],
                   "kind": kind, "mode": self.mode, "status": "starting", "phase": "启动子进程",
                   "created_at": now(), "updated_at": now(), "config": config,
                   "experiment_name": recipe["experiment_name"], "skill": skill,
                   "progress": {"iteration": start_iteration, "total": start_iteration + config["iterations"], "elapsed_seconds": 0},
                   "metrics": [], "checkpoints": [], "logs": [], "artifacts": []}
            run["smoke_family"] = family
            run["engine_source"] = self._engine_source()
            if skill is not None:
                run["command_contract"] = skill_command_contract(skill)
                self._skill_file(run)
            if parent:
                run["parent_id"] = parent["id"]
                run["resume_checkpoint_id"] = checkpoint["id"]
            if profile is not None:
                run["profile"] = profile
                run["profile_summary"] = {"applied_to_physics": False, "schema": profile["schema"],
                                          "joint_count": len(profile.get("joints") or []),
                                          "note": "仅归档与追溯；档案参数未自动应用到训练物理。"}
                self._log(run, run["profile_summary"]["note"])
            if self.mode == "demo":
                argv = [sys.executable, "-u", str(Path(__file__).with_name("demo_worker.py")),
                        "--iterations", str(config["iterations"]), "--save-interval", str(config["save_interval"]),
                        "--interval", str(self.demo_interval), "--start-iteration", str(start_iteration)]
                cwd = Path(__file__).parent
            else:
                argv = build_train_argv(run, self.training_root, checkpoint.get("engine_path") if checkpoint else None)
                cwd = self.training_root
            self._runs[run_id] = run
            self._active = run_id
            self._save(run)
            try:
                child = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                         bufsize=1, start_new_session=os.name != "nt",
                                         env=runtime_environment())
            except OSError as exc:
                run.update(status="failed", phase="启动失败", error=str(exc))
                self._active = None
                self._save(run)
                raise StudioError("启动训练进程失败", 409, str(exc)) from None
            self._children[run_id] = child
            self._start_leader_watcher(run_id, child)
            self._started[run_id] = (time.monotonic(), 0.0)
            reader = threading.Thread(target=self._monitor, args=(run_id, child), daemon=True, name=f"studio-{run_id}")
            self._readers[run_id] = reader
            reader.start()
            return self._public(run)

    def _elapsed(self, run):
        started = self._started.get(run["id"])
        if started:
            run["progress"]["elapsed_seconds"] = round(time.monotonic() - started[0], 2)

    def _skill_file(self, run):
        """Revalidate saved targets before any evaluator/exporter sees them."""
        skill = validate_skill(run["recipe_id"], run.get("skill"))
        if skill is None:
            return None
        path = self._run_dir(run["id"]) / "skill.json"
        atomic_json(path, skill)
        if "skill.json" not in run["artifacts"]:
            run["artifacts"].append("skill.json")
        return path

    def _demo_event(self, run, event):
        kind = event.get("event")
        if kind == "ready":
            run.update(status="running", phase="演示训练中")
            self._log(run, event["message"])
        elif kind == "paused":
            run.update(status="paused", phase="已暂停（子进程已确认）")
            self._log(run, "子进程确认暂停；迭代已冻结。")
        elif kind == "resumed":
            run.update(status="running", phase="演示训练中")
            self._log(run, "从内存中的同一子进程继续。")
        elif kind == "metric":
            metric = {key: event[key] for key in ("iteration", "reward", "episode_length", "fps")}
            run["metrics"].append(metric)
            run["progress"]["iteration"] = event["iteration"]
            self._log(run, f"DEMO iteration {event['iteration']}/{run['progress']['total']} | reward {event['reward']}")
        elif kind == "checkpoint":
            iteration = event["iteration"]
            filename = f"checkpoints/demo_{iteration}.json"
            record = {"demo": True, "warning": "合成演示记录，不是策略权重，无法部署。",
                      "task_id": run["task_id"], "iteration": iteration, "config": run["config"],
                      "skill": run.get("skill")}
            atomic_json(self._run_dir(run["id"]) / filename, record)
            run["artifacts"].append(filename)
            run["checkpoints"].append({"id": f"demo-{iteration}", "iteration": iteration,
                                        "name": Path(filename).name, "created_at": now(), "demo": True,
                                        "task_id": run["task_id"], "relative_path": filename})
            self._log(run, f"DEMO 保存演示记录 {Path(filename).name}（无模型权重）")

    def _real_line(self, run, line):
        line = ANSI.sub("", line).strip()
        if not line:
            return
        self._log(run, line)
        if run["status"] == "starting":
            run.update(status="running", phase="真实训练中")
        match = re.search(r"Logging experiment in directory:\s*(.+)", line)
        if match:
            path = Path(match[1].strip())
            if not path.is_absolute():
                path = self.training_root / path
            path = path.resolve()
            log_root = (self.training_root / "logs" / "rsl_rl" / experiment_for(run)).resolve()
            if path.parent == log_root and path.name.endswith("_studio_" + run["id"]):
                run["engine_log_dir"] = str(path)
        data = parse_metric(line)
        if data:
            if "iteration" in data:
                run["progress"]["iteration"] = data["iteration"]
                run["metrics"].append({"iteration": data["iteration"]})
            if run["metrics"]:
                run["metrics"][-1].update(data)
        self._scan_checkpoints(run)

    def _scan_checkpoints(self, run, complete=False):
        if self.mode != "real" or not run.get("engine_log_dir"):
            return
        folder = Path(run["engine_log_dir"]).resolve()
        root = (self.training_root / "logs" / "rsl_rl" / experiment_for(run)).resolve()
        if folder.parent != root or not folder.name.endswith("_studio_" + run["id"]):
            return
        known = {c["id"] for c in run["checkpoints"]}
        observations = self._checkpoint_observations.setdefault(run["id"], {})
        for path in sorted(folder.glob("model_*.pt")):
            match = re.fullmatch(r"model_(\d+)\.pt", path.name)
            if match and path.resolve().parent == folder and path.is_file() and path.stat().st_size:
                checkpoint_id = "model-" + match[1]
                if checkpoint_id not in known:
                    stat = path.stat()
                    signature = (stat.st_size, stat.st_mtime_ns)
                    previous = observations.get(str(path))
                    observed_at = time.monotonic()
                    if not previous or previous[:2] != signature:
                        observations[str(path)] = (*signature, observed_at)
                        if not complete:
                            continue
                    elif not complete and observed_at - previous[2] < CHECKPOINT_STABLE_SECONDS:
                        continue
                    # torch.save in the pinned engine uses ZIP serialization. A partial write
                    # lacks the end directory; a nonempty path alone is never a checkpoint.
                    if not self._complete_checkpoint(path):
                        continue
                    run["checkpoints"].append({"id": checkpoint_id, "iteration": int(match[1]), "name": path.name,
                                                "created_at": now(), "demo": False, "task_id": run["task_id"],
                                                "engine_path": str(path.resolve())})
                    known.add(checkpoint_id)
        run["checkpoints"].sort(key=lambda c: c["iteration"])

    @staticmethod
    def _complete_checkpoint(path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                return any(n.endswith("/data.pkl") for n in names) and any(n.endswith("/version") for n in names)
        except (OSError, zipfile.BadZipFile):
            return False

    def _monitor(self, run_id, child):
        try:
            for line in child.stdout:
                with self._condition:
                    run = self._runs[run_id]
                    if self.mode == "demo":
                        try:
                            self._demo_event(run, json.loads(line))
                        except (ValueError, KeyError, TypeError):
                            self._log(run, line.strip())
                    else:
                        self._real_line(run, line)
                    self._elapsed(run)
                    self._save(run)
                    self._condition.notify_all()
            # Reap under the same condition used by pause, so checking liveness and
            # signalling cannot race an out-of-lock wait()/PID release.
            while True:
                with self._condition:
                    code = self._peek(child)
                    if code is not None:
                        break
                time.sleep(0.025)
            self._terminate(child)
            with self._condition:
                run = self._runs[run_id]
                # No writer remains after exit; complete ZIP files are safe even
                # if stop/failure happened before the stability observation window.
                self._scan_checkpoints(run, complete=True)
                self._elapsed(run)
                if run_id in self._stop_requested:
                    run.update(status="stopped", phase="已停止；保留已保存的检查点")
                    self._log(run, "任务已停止；未保证停止瞬间的最后迭代已保存。")
                elif code == 0:
                    run.update(status="completed", phase="冒烟测试完成（不是训练成品）" if run["kind"] == "smoke" else "训练完成，需评估实际策略")
                    if self.mode == "real":
                        run["progress"]["iteration"] = run["progress"]["total"]
                else:
                    run.update(status="failed", phase="子进程失败", error=f"训练进程退出码 {code}，请查看日志。")
                self._save(run)
                self._children.pop(run_id, None)
                if self._active == run_id:
                    self._active = None
                self._condition.notify_all()
        except Exception as exc:
            with self._condition:
                run = self._runs[run_id]
                run.update(status="failed", phase="日志处理失败", error=str(exc))
                self._log(run, f"日志处理失败：{exc}")
                self._stop_requested.add(run_id)
            self._terminate(child)
            with self._condition:
                self._children.pop(run_id, None)
                if self._active == run_id:
                    self._active = None
                self._save(run)
                self._condition.notify_all()
        finally:
            if child.stdout:
                child.stdout.close()
            if child.stdin:
                child.stdin.close()

    def _wait_status(self, run, expected):
        deadline = time.monotonic() + 4
        while run["status"] not in expected:
            if run["status"] in TERMINAL or time.monotonic() >= deadline:
                raise StudioError("子进程未确认状态变化，请查看任务日志。", 409)
            self._condition.wait(timeout=min(0.1, deadline - time.monotonic()))

    def _send(self, child, command):
        try:
            child.stdin.write(command + "\n")
            child.stdin.flush()
        except (OSError, ValueError):
            raise StudioError("训练进程已结束", 409) from None

    def pause(self, run_id):
        with self._condition:
            run = self._get(run_id)
            if run["status"] not in {"starting", "running"} or run_id not in self._children:
                raise StudioError("只有运行中的任务可以暂停", 409)
            child = self._children[run_id]
            if self._peek(child) is not None:
                raise StudioError("训练进程已结束", 409)
            if self.mode == "demo":
                self._send(child, "pause")
                self._wait_status(run, {"paused"})
            elif sys.platform == "linux":
                try:
                    with self._process_lock(child):
                        if self._peek(child) is not None:
                            raise StudioError("训练进程已结束", 409)
                        os.killpg(child.pid, signal.SIGSTOP)
                    # waitid observes the kernel's stopped state, rather than optimistic UI state.
                    deadline = time.monotonic() + 3
                    while True:
                        with self._process_lock(child):
                            if self._peek(child) is not None:
                                raise StudioError("训练进程已结束，未确认暂停。", 409)
                            acknowledgement = os.waitid(os.P_PID, child.pid, os.WSTOPPED | os.WNOHANG)
                        if acknowledgement is not None and acknowledgement.si_pid == child.pid:
                            break
                        if time.monotonic() >= deadline:
                            # Never leave an unacknowledged group stopped indefinitely.
                            with self._process_lock(child):
                                if self._peek(child) is None:
                                    os.killpg(child.pid, signal.SIGCONT)
                            raise StudioError("等待内核暂停确认超时，已尝试继续进程。", 409)
                        self._condition.wait(timeout=0.025)
                except (OSError, ChildProcessError):
                    raise StudioError("进程未能确认暂停", 409) from None
                run.update(status="paused", phase="已暂停；仍占用显存和计费资源")
                self._log(run, "进程组已 SIGSTOP 暂停；策略与优化器保留在内存，仍占用 GPU。")
                self._save(run)
            else:
                raise StudioError("真实暂停仅支持 Linux", 409)
            return self._public(run)

    def _checkpoint(self, run, payload):
        experiment = experiment_for(run)
        validate_skill(run["recipe_id"], run.get("skill"))
        if not isinstance(payload, dict) or set(payload) - {"checkpoint_id"}:
            raise StudioError("请提供有效的 checkpoint_id")
        selected = payload.get("checkpoint_id")
        checkpoint = next((c for c in run["checkpoints"] if c["id"] == selected), None)
        if not checkpoint or checkpoint.get("task_id") != run["task_id"] or bool(checkpoint.get("demo")) != (self.mode == "demo"):
            raise StudioError("检查点不存在，或不属于此任务与模式", 400)
        if self.mode == "demo":
            self.artifact_path(run["id"], checkpoint["relative_path"])
        else:
            path = Path(checkpoint.get("engine_path", "")).resolve()
            folder = Path(run.get("engine_log_dir", "")).resolve()
            expected = (self.training_root / "logs" / "rsl_rl" / experiment).resolve()
            if folder.parent != expected or not folder.name.endswith("_studio_" + run["id"]) or path.parent != folder or not path.is_file() or not re.fullmatch(r"model_\d+\.pt", path.name) or not self._complete_checkpoint(path):
                raise StudioError("检查点文件已缺失或来源不正确", 409)
        return checkpoint

    def resume(self, run_id, payload):
        with self._condition:
            run = self._get(run_id)
            if run["status"] == "paused":
                if payload:
                    raise StudioError("暂停中的任务直接从内存继续，请勿指定检查点")
                child = self._children.get(run_id)
                if not child or self._peek(child) is not None:
                    raise StudioError("原训练进程已不存在", 409)
                if self.mode == "demo":
                    self._send(child, "resume")
                    self._wait_status(run, {"running"})
                else:
                    with self._process_lock(child):
                        if self._peek(child) is not None:
                            raise StudioError("原训练进程已不存在", 409)
                        os.killpg(child.pid, signal.SIGCONT)
                    run.update(status="running", phase="真实训练中")
                    self._log(run, "SIGCONT：继续内存中的同一训练进程。")
                    self._save(run)
                return self._public(run)
            if run["status"] not in TERMINAL:
                raise StudioError("当前任务无法恢复", 409)
            checkpoint = self._checkpoint(run, payload)
            return self.create_run({"name": run["name"][:95] + " · 续训", "recipe_id": run["recipe_id"], "kind": run["kind"],
                                    "config": run["config"], "profile": run.get("profile"), "skill": run.get("skill")}, parent=run, checkpoint=checkpoint)

    def _terminate(self, child):
        with self._process_lock(child):
            # Reaped leaders release the numeric group ID. Never signal one.
            if child.returncode is not None:
                return
            try:
                if os.name != "nt":
                    # Linux exit observations use WNOWAIT everywhere. The unreaped
                    # leader reserves PID/PGID through the final group signal.
                    try:
                        os.killpg(child.pid, signal.SIGCONT)
                        os.killpg(child.pid, signal.SIGTERM)
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline:
                            if not self._group_running(child.pid):
                                break
                            time.sleep(0.025)
                        else:
                            os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif child.poll() is None:
                    child.terminate()
                # All group signals finish before this sole reaping point.
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
                child.wait(timeout=4)

    @staticmethod
    def _group_running(group_id):
        if sys.platform == "linux":
            # A reserved zombie leader does not consume GPU and must not keep
            # shutdown waiting. Its non-zombie descendants still need cleanup.
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[2]) == group_id and int(fields[3]) == group_id and fields[0] not in ("Z", "X"):
                        return True
                except (OSError, ValueError, IndexError):
                    continue
            return False
        try:
            os.killpg(group_id, 0)
            return True
        except ProcessLookupError:
            return False

    def stop(self, run_id):
        with self._condition:
            run = self._get(run_id)
            if run["status"] not in ACTIVE or run_id not in self._children:
                raise StudioError("当前任务无法停止", 409)
            run.update(status="stopping", phase="正在停止；保留已有检查点")
            self._stop_requested.add(run_id)
            self._save(run)
            child = self._children[run_id]
            if self.mode == "demo":
                self._send(child, "stop")
        if self.mode == "demo":
            try:
                self._wait_exit(child, timeout=2)
            except subprocess.TimeoutExpired:
                self._terminate(child)
        else:
            self._terminate(child)
        reader = self._readers.get(run_id)
        if reader and reader is not threading.current_thread():
            reader.join(timeout=5)
        with self._condition:
            return self._public(self._get(run_id))

    def artifact_path(self, run_id, relative):
        with self._condition:
            run = self._get(run_id)
            if not isinstance(relative, str) or "\\" in relative or ":" in relative or relative.startswith("/") or any(p in ("", ".", "..") for p in relative.split("/")):
                raise StudioError("无效产物路径", 403)
            if relative not in run.get("artifacts", []):
                raise StudioError("未找到产物", 404)
            root = self._run_dir(run_id).resolve()
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise StudioError("未找到产物", 404)
            return path

    def operate(self, run_id, kind, payload):
        if kind not in {"evaluate", "export"}:
            raise StudioError("未知操作")
        with self._condition:
            run = self._get(run_id)
            self._ensure_available()
            if run["status"] not in TERMINAL or run["mode"] != self.mode:
                raise StudioError("请先停止训练，再评估或导出对应模式的检查点。", 409)
            checkpoint = self._checkpoint(run, payload)
            if self.mode == "real" and not self._environment["ready"]:
                raise StudioError("真实训练环境未就绪", 409)
            run["operation"] = {"status": "running", "kind": kind, "checkpoint_id": checkpoint["id"], "started_at": now()}
            self._active = run_id
            self._save(run)
            thread = threading.Thread(target=self._operation, args=(run_id, kind, copy.deepcopy(checkpoint)), daemon=True)
            self._operation_threads[run_id] = thread
            thread.start()
            return self._public(run)

    def _artifact_url(self, run_id, relative):
        return f"/api/artifacts/{run_id}/" + quote(relative, safe="/")

    def _operation_child(self, run, argv):
        with self._condition:
            if self._closing:
                raise RuntimeError("服务正在关闭")
            child = subprocess.Popen(argv, cwd=self.training_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt",
                                     env=runtime_environment())
            self._children[run["id"]] = child
            self._start_leader_watcher(run["id"], child)
        try:
            for line in child.stdout:
                with self._condition:
                    self._log(run, line.strip())
                    self._save(run)
            while True:
                code = self._peek(child)
                if code is not None:
                    break
                time.sleep(0.025)
            if code != 0:
                raise RuntimeError(f"{run['operation']['kind']} 子进程退出码 {code}")
        finally:
            # Keep ownership until the process group is stopped even when pipe
            # decoding, iteration or persistence raises before child.wait().
            self._terminate(child)
            child.stdout.close()
            with self._condition:
                self._children.pop(run["id"], None)

    def _operation(self, run_id, kind, checkpoint):
        run = self._runs[run_id]
        try:
            folder = self._run_dir(run_id)
            suffix = checkpoint["id"]
            skill = validate_skill(run["recipe_id"], run.get("skill"))
            skill_file = self._skill_file(run)
            evaluation_summary = None
            provenance = {"mode": self.mode, "task_id": run["task_id"], "recipe_id": run["recipe_id"],
                          "experiment_name": experiment_for(run), "skill": skill,
                          "run_id": run_id, "checkpoint": {k: v for k, v in checkpoint.items() if k != "engine_path"},
                          "config": run["config"], "profile": run.get("profile"), "profile_applied_to_physics": False,
                          "created_at": now(), "smoke_test_only": run["kind"] == "smoke",
                          "engine_source": run.get("engine_source", {"unavailable": True, "note": "旧任务未保存训练启动时的源信息。"})}
            if skill is not None:
                provenance["command_contract"] = run.get("command_contract") or skill_command_contract(skill)
            outputs = []
            if kind == "evaluate":
                if self.mode == "demo":
                    relative = f"evaluations/{suffix}/demo-replay.svg"
                    path = folder / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540"><rect width="960" height="540" fill="#111c25"/><text x="48" y="95" fill="#ffcf63" font-family="sans-serif" font-size="32">DEMO · Synthetic workflow preview</text><text x="48" y="145" fill="white" font-family="sans-serif" font-size="20">No trained policy or physics rollout. Not robot performance.</text><g transform="translate(430,285)"><animateTransform attributeName="transform" type="translate" values="400,285;470,275;400,285" dur="2s" repeatCount="indefinite"/><rect x="0" y="0" width="100" height="60" rx="18" fill="#ffcf63"/><rect x="65" y="-48" width="65" height="60" rx="15" fill="#ffcf63"/><circle cx="109" cy="-24" r="6" fill="#172530"/><path d="M14 60l-12 55m70-55 20 55" stroke="#a9c8cf" stroke-width="14"/></g></svg>', encoding="utf-8")
                    outputs = [relative]
                    if skill is not None:
                        evaluation_summary = {"demo": True, "skill": skill,
                                              "note": "演示预览：没有策略或物理评估，不提供动作成功率。"}
                        summary_relative = f"evaluations/{suffix}/evaluation.json"
                        atomic_json(folder / summary_relative, evaluation_summary)
                        outputs.append(summary_relative)
                else:
                    eval_folder = folder / "evaluations" / suffix
                    eval_folder.mkdir(parents=True, exist_ok=True)
                    argv = ["uv", "run", "--frozen", "--no-sync", "--offline", "python", str(Path(__file__).with_name("evaluate.py")),
                            run["task_id"], "--checkpoint-file", checkpoint["engine_path"], "--output-dir", str(eval_folder)]
                    if skill_file:
                        argv += ["--balance-config", str(skill_file), "--seed", str(run["config"]["seed"])]
                    else:
                        argv += ["--steps", "250"]
                    self._operation_child(run, argv)
                    if skill is not None:
                        evaluation_summary = self._balance_evaluation_summary(eval_folder / "evaluation.json", skill)
                    videos = sorted(eval_folder.glob("*.mp4"))
                    if not videos:
                        raise RuntimeError("评估没有生成实际视频，请查看渲染器日志。")
                    outputs = [p.relative_to(folder).as_posix() for p in videos]
                    outputs += [p.relative_to(folder).as_posix() for p in eval_folder.glob("*.json")]
                url = self._artifact_url(run_id, outputs[0])
                property_name = "video_url"
            else:
                export_folder = folder / "exports" / suffix
                export_folder.mkdir(parents=True, exist_ok=True)
                policy = export_folder / "policy.onnx"
                if self.mode == "real":
                    argv = ["uv", "run", "--frozen", "--no-sync", "--offline", "python", "scripts/export.py", run["task_id"],
                            "--checkpoint-file", checkpoint["engine_path"], "--onnx-file", str(policy), "--num-envs", "1"]
                    if skill_file:
                        argv += ["--balance-config", str(skill_file)]
                    self._operation_child(run, argv)
                    if not policy.is_file() or policy.stat().st_size == 0:
                        raise RuntimeError("引擎未生成 ONNX 文件")
                    provenance["onnx_normalizer"] = "engine scripts/export.py runner.export_policy_to_onnx (built-in observation normalizer)"
                    provenance["checkpoint_sha256"] = self._sha256(Path(checkpoint["engine_path"]))
                else:
                    provenance["warning"] = "DEMO：仅配置、档案和文本检查点；没有 PT/ONNX 权重，不可部署。"
                relative = f"exports/{suffix}/{'demo-records' if self.mode == 'demo' else 'policy-bundle'}.zip"
                evidence = [item for item in run["artifacts"] if item.startswith(f"evaluations/{suffix}/")]
                provenance["evaluation_evidence"] = ["evaluation/" + Path(item).name for item in evidence]
                with zipfile.ZipFile(folder / relative, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2))
                    archive.writestr("config.json", json.dumps(run["config"], indent=2))
                    if skill_file:
                        archive.write(skill_file, "skill.json")
                        archive.writestr("command-contract.json", json.dumps(provenance["command_contract"], ensure_ascii=False, indent=2))
                    for item in evidence:
                        archive.write(self.artifact_path(run_id, item), "evaluation/" + Path(item).name)
                    if run.get("profile") is not None:
                        archive.writestr("duck-profile.json", json.dumps(run["profile"], ensure_ascii=False, indent=2))
                    if self.mode == "real":
                        archive.write(policy, "policy.onnx")
                        archive.write(checkpoint["engine_path"], "checkpoint/" + checkpoint["name"])
                        params = Path(checkpoint["engine_path"]).parent / "params"
                        for name in ("env.yaml", "agent.yaml"):
                            if (params / name).is_file():
                                archive.write(params / name, "engine-config/" + name)
                    else:
                        archive.write(self.artifact_path(run_id, checkpoint["relative_path"]), "checkpoint/" + checkpoint["name"])
                outputs = [relative]
                url = self._artifact_url(run_id, relative)
                property_name = "export_url"
            with self._condition:
                for item in outputs:
                    if item not in run["artifacts"]:
                        run["artifacts"].append(item)
                selected = next(c for c in run["checkpoints"] if c["id"] == checkpoint["id"])
                selected[property_name] = url
                if evaluation_summary is not None:
                    selected["evaluation_summary"] = evaluation_summary
                run["operation"].update(status="completed", completed_at=now())
                self._log(run, f"{'DEMO ' if self.mode == 'demo' else ''}{kind} 完成；检查点 {checkpoint['name']}")
        except Exception as exc:
            with self._condition:
                run["operation"].update(status="failed", error=str(exc))
                self._log(run, f"{kind} 失败：{exc}")
        finally:
            with self._condition:
                if self._active == run_id:
                    self._active = None
                self._save(run)
                self._condition.notify_all()

    @staticmethod
    def _balance_evaluation_summary(path, skill):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise RuntimeError("单脚平衡评估摘要格式无效")
        # Reject NaN/Infinity and incomplete evidence instead of displaying an
        # invented physical result from a process that merely exited cleanly.
        json.dumps(summary, allow_nan=False)
        trials, successes = summary.get("trials"), summary.get("successes")
        results = summary.get("trial_results")
        if (summary.get("demo") is not False or summary.get("skill") != skill
                or type(trials) is not int or trials != 8
                or type(successes) is not int or not 0 <= successes <= trials
                or type(summary.get("success_rate")) not in (int, float)
                or summary["success_rate"] != successes / trials
                or not isinstance(results, list) or len(results) != trials
                or any(not isinstance(result, dict) or type(result.get("success")) is not bool for result in results)
                or sum(result["success"] for result in results) != successes
                or not isinstance(summary.get("note"), str)):
            raise RuntimeError("单脚平衡评估摘要缺少匹配的完整周期证据")
        return summary

    @staticmethod
    def _sha256(path):
        result = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                result.update(chunk)
        return result.hexdigest()

    def _engine_source(self):
        result = {"training_root": str(self.training_root), "git_commit": None, "files_sha256": {},
                  "dependency_versions": copy.deepcopy(self._environment.get("dependency_versions", {})),
                  "dependency_versions_source": self._environment.get("dependency_versions_source", "unavailable"),
                  "lock_dependency_versions": {}}
        for relative in ("pyproject.toml", "uv.lock", "scripts/export.py", "src/mjlab_microduck/train_cli.py",
                         "src/mjlab_microduck/tasks/__init__.py", "src/mjlab_microduck/tasks/microduck_hd1910_env_cfg.py",
                         "src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py",
                         "src/mjlab_microduck/balance_parameters.py", "src/mjlab_microduck/tasks/mdp.py",
                         "src/mjlab_microduck/tasks/microduck_balance_env_cfg.py"):
            path = self.training_root / relative
            if path.is_file():
                result["files_sha256"][relative] = self._sha256(path)
        try:
            output = subprocess.run(["git", "-C", str(self.training_root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=3, check=False)
            if output.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", output.stdout.strip()):
                result["git_commit"] = output.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            with (self.training_root / "uv.lock").open("rb") as source:
                lock = tomllib.load(source)
            for package in lock.get("package", []):
                if package.get("name") in ("mjlab", "rsl-rl-lib", "torch", "mujoco-warp") and package.get("version"):
                    versions = result["lock_dependency_versions"].setdefault(package["name"], [])
                    if package["version"] not in versions:
                        versions.append(package["version"])
        except (OSError, ValueError):
            pass
        return result

    def shutdown(self):
        with self._condition:
            self._closing = True
            children = list(self._children.items())
        self._resource_monitor.close()
        for run_id, child in children:
            with self._condition:
                run = self._runs[run_id]
                training = run["status"] in ACTIVE
            if training:
                try:
                    self.stop(run_id)
                except StudioError:
                    self._terminate(child)
            else:
                self._terminate(child)
        for thread in list(self._operation_threads.values()):
            if thread is not threading.current_thread():
                thread.join(timeout=8)
        with self._condition:
            watchers = list(self._leader_watchers.values())
        for watcher in watchers:
            if watcher is not threading.current_thread():
                watcher.join(timeout=4)
