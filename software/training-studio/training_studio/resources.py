"""Read-only execution-host telemetry, sampled off the HTTP/job threads.

CPU utilization is a delta of host counters, never process utilization. On WSL,
CPU/RAM describe the Linux VM while nvidia-smi reports the entire physical GPU.
No package installation, CUDA context, training process, or history is created.
"""
import copy
import csv
import ctypes
import io
import math
import os
import platform
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


INTERVAL_SECONDS = 3
GPU_TIMEOUT_SECONDS = 2


def empty_snapshot(mode, *, system=None, is_wsl=False):
    return {
        "mode": mode, "scope": "execution_host", "platform": system or platform.system(),
        "is_wsl": is_wsl,
        "scope_note": ("执行端整体资源，包含其他进程；WSL CPU/内存为虚拟机可见值，GPU 为整张显卡。"
                       if is_wsl else "执行端整体资源，包含其他进程；不是单次训练的独占消耗。"),
        "status": "pending", "sampled_at": None, "age_seconds": None, "stale": False,
        "refresh_interval_seconds": INTERVAL_SECONDS,
        "cpu": {"model": None, "count": None, "utilization_pct": None,
                "utilization_reason": "等待资源采样。", "temperature_c": None,
                "temperature_reason": "等待温度采样。"},
        "memory": {"used_bytes": None, "total_bytes": None, "reason": "等待内存采样。"},
        "gpus": [], "gpu_reason": "等待显卡采样。", "errors": [],
    }


def _number(value, minimum=0, maximum=None):
    try:
        number = float(value)
        if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
            return None
        return number
    except (ValueError, TypeError):
        return None


def parse_nvidia_csv(output):
    """Keep valid devices/fields, reporting unavailable values as null, not 0."""
    devices, errors, indices = [], [], set()
    for row in csv.reader(io.StringIO(output), skipinitialspace=True):
        if not row:
            continue
        if len(row) != 6 or not row[0].strip().isdigit() or int(row[0]) in indices:
            errors.append({"component": "gpu", "reason": "显卡探测返回无法识别的记录。"})
            continue
        index = int(row[0]); indices.add(index)
        device = {"index": index, "name": row[1].strip() or None, "unavailable_reasons": {}}
        for field, raw, maximum in zip(
            ("utilization_pct", "temperature_c", "memory_used_mib", "memory_total_mib"),
            row[2:], (100, 150, None, None),
        ):
            device[field] = _number(raw, maximum=maximum)
            if device[field] is None:
                device["unavailable_reasons"][field] = "显卡驱动未提供有效读数。"
        total, used = device["memory_total_mib"], device["memory_used_mib"]
        if total is not None and total <= 0:
            device["memory_total_mib"] = None
            device["unavailable_reasons"]["memory_total_mib"] = "显卡驱动返回无效显存容量。"
        if total is not None and used is not None and used > total:
            device["memory_used_mib"] = None
            device["unavailable_reasons"]["memory_used_mib"] = "显存读数不一致。"
        devices.append(device)
    return devices, errors


class ResourceSampler:
    def __init__(self, *, system=None, proc_root=Path('/proc'), sys_root=Path('/sys'), run=None):
        self.system = system or platform.system()
        self.proc_root, self.sys_root = Path(proc_root), Path(sys_root)
        self.run = run or subprocess.run
        self._previous_cpu = None

    def _cpu_delta(self, total, idle):
        previous, self._previous_cpu = self._previous_cpu, (total, idle)
        if previous is None:
            return None, "等待下一次采样计算 CPU 利用率。"
        total_delta, idle_delta = total - previous[0], idle - previous[1]
        if total_delta <= 0 or not 0 <= idle_delta <= total_delta:
            return None, "CPU 计数器重置或采样间隔不足。"
        return round(100 * (total_delta - idle_delta) / total_delta, 1), None

    def _linux(self, data):
        cpu, memory = data['cpu'], data['memory']
        cpu['count'] = os.cpu_count()
        try:
            release = (self.proc_root / 'sys/kernel/osrelease').read_text().lower()
            data['is_wsl'] = 'microsoft' in release or 'wsl' in release
            if data['is_wsl']:
                data['scope_note'] = empty_snapshot('real', is_wsl=True)['scope_note']
        except OSError:
            pass
        try:
            for line in (self.proc_root / 'cpuinfo').read_text().splitlines():
                key, separator, value = line.partition(':')
                if separator and key.strip() in ('model name', 'Hardware'):
                    cpu['model'] = value.strip() or None
                    break
        except OSError:
            pass
        try:
            fields = (self.proc_root / 'stat').read_text().splitlines()[0].split()
            if fields[0] != 'cpu' or len(fields) < 5:
                raise ValueError('invalid CPU counters')
            # guest/guest_nice (fields 9/10) are already included in user/nice.
            values = [int(value) for value in fields[1:9]]
            if any(value < 0 for value in values):
                raise ValueError('negative CPU counters')
            total, idle = sum(values), values[3] + (values[4] if len(values) > 4 else 0)
            cpu['utilization_pct'], cpu['utilization_reason'] = self._cpu_delta(total, idle)
        except (OSError, ValueError, IndexError):
            self._previous_cpu = None
            cpu['utilization_reason'] = "无法读取 Linux CPU 计数器。"
        try:
            values = {}
            for line in (self.proc_root / 'meminfo').read_text().splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[0] in ('MemTotal:', 'MemAvailable:') and fields[2] == 'kB':
                    values[fields[0][:-1]] = int(fields[1]) * 1024
            total, available = values.get('MemTotal'), values.get('MemAvailable')
            memory['total_bytes'] = total if total is not None and total > 0 else None
            if total is None or total <= 0 or available is None or not 0 <= available <= total:
                raise ValueError('missing memory counters')
            memory.update(used_bytes=total - available, reason=None)
        except (OSError, ValueError):
            memory['reason'] = "无法读取有效 MemTotal/MemAvailable；未用空闲内存代替可用内存。"
        temperatures = []
        # Only CPU-labelled sources; ACPI zones and GPU temperatures are not CPU.
        try:
            for sensor in (self.sys_root / 'class/hwmon').glob('hwmon*'):
                try:
                    name = (sensor / 'name').read_text().strip().lower()
                    if name not in {'coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'cpu-thermal'}:
                        continue
                    for path in sensor.glob('temp*_input'):
                        try:
                            value = _number(path.read_text().strip(), maximum=150000)
                            if value is not None:
                                temperatures.append(value / 1000)
                        except OSError:
                            continue
                except OSError:
                    continue
            for zone in (self.sys_root / 'class/thermal').glob('thermal_zone*'):
                try:
                    name = (zone / 'type').read_text().strip().lower()
                    if name not in {'x86_pkg_temp', 'cpu-thermal', 'cpu_thermal'}:
                        continue
                    value = _number((zone / 'temp').read_text().strip(), maximum=150000)
                    if value is not None:
                        temperatures.append(value / 1000)
                except OSError:
                    continue
        except OSError:
            pass
        cpu['temperature_c'] = max(temperatures) if temperatures else None
        cpu['temperature_reason'] = None if temperatures else (
            "WSL 未暴露可读取的 CPU 温度传感器。" if data['is_wsl'] else "系统未暴露可读取的 CPU 温度传感器。")

    def _windows(self, data):
        from ctypes import wintypes
        cpu, memory = data['cpu'], data['memory']
        cpu.update(model=platform.processor() or None, count=os.cpu_count(),
                   temperature_reason="Windows 未提供可用的 CPU 温度接口。")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                cpu['model'] = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip() or cpu['model']
        except (OSError, ImportError):
            pass
        try:
            idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            if not api.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                raise OSError('GetSystemTimes failed')
            def ticks(value):
                return (value.dwHighDateTime << 32) + value.dwLowDateTime
            cpu['utilization_pct'], cpu['utilization_reason'] = self._cpu_delta(ticks(kernel) + ticks(user), ticks(idle))
        except (OSError, AttributeError):
            self._previous_cpu = None
            cpu['utilization_reason'] = "无法读取 Windows CPU 计数器。"
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
                    (name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_available',
                                                           'virtual_total', 'virtual_available', 'extended')]
            status = MemoryStatus(); status.length = ctypes.sizeof(status)
            if not ctypes.WinDLL('kernel32', use_last_error=True).GlobalMemoryStatusEx(ctypes.byref(status)):
                raise OSError('GlobalMemoryStatusEx failed')
            if not 0 <= status.available <= status.total or not status.total:
                raise OSError('Invalid memory counters')
            memory.update(total_bytes=status.total, used_bytes=status.total - status.available, reason=None)
        except (OSError, AttributeError):
            memory['reason'] = "无法读取 Windows 物理内存计数器。"

    def _gpu(self, data):
        executable = shutil.which('nvidia-smi')
        if not executable and self.system == 'Linux' and Path('/usr/lib/wsl/lib/nvidia-smi').is_file():
            executable = '/usr/lib/wsl/lib/nvidia-smi'
        if not executable:
            data['gpu_reason'] = "未找到 nvidia-smi，无法读取 NVIDIA 显卡资源。"
            return
        try:
            kwargs = {'capture_output': True, 'text': True, 'encoding': 'utf-8', 'errors': 'replace',
                      'check': False, 'timeout': GPU_TIMEOUT_SECONDS}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = self.run([executable, '--query-gpu=index,name,utilization.gpu,temperature.gpu,memory.used,memory.total',
                               '--format=csv,noheader,nounits'], **kwargs)
            if result.returncode != 0:
                data['gpu_reason'] = "显卡驱动探测失败，暂时无法读取 GPU 资源。"
                return
            data['gpus'], errors = parse_nvidia_csv(result.stdout)
            data['errors'].extend(errors)
            data['gpu_reason'] = None if data['gpus'] else "驱动未返回可用显卡记录。"
        except subprocess.TimeoutExpired:
            data['gpu_reason'] = "显卡资源探测超过 2 秒，已结束本次探测。"
        except (OSError, ValueError, csv.Error):
            data['gpu_reason'] = "无法运行或解析显卡资源探测。"

    def __call__(self):
        data = empty_snapshot('real', system=self.system)
        if self.system == 'Linux':
            self._linux(data)
        elif self.system == 'Windows':
            self._windows(data)
        else:
            data['cpu'].update(model=platform.processor() or None, count=os.cpu_count(),
                               utilization_reason="当前平台暂不支持 CPU 利用率采样。",
                               temperature_reason="当前平台暂不支持 CPU 温度采样。")
            data['memory']['reason'] = "当前平台暂不支持物理内存采样。"
        self._gpu(data)
        for component, reason in (('cpu.utilization', data['cpu']['utilization_reason']),
                                  ('cpu.temperature', data['cpu']['temperature_reason']),
                                  ('memory', data['memory']['reason']), ('gpu', data['gpu_reason'])):
            if reason:
                data['errors'].append({'component': component, 'reason': reason})
        for gpu in data['gpus']:
            for field, reason in gpu['unavailable_reasons'].items():
                data['errors'].append({'component': f"gpu.{gpu['index']}.{field}", 'reason': reason})
        any_metrics = (data['cpu']['utilization_pct'] is not None or data['cpu']['temperature_c'] is not None
                       or data['memory']['used_bytes'] is not None or bool(data['gpus']))
        data['status'] = 'partial' if data['errors'] else 'ready'
        if not any_metrics:
            data['status'] = 'unavailable'
        return data


class ResourceMonitor:
    """First read starts one daemon; every HTTP read only copies its cache."""
    def __init__(self, mode='real', *, sampler=None, interval=INTERVAL_SECONDS, clock=None):
        self.mode, self.interval = mode, interval
        self._sampler, self._clock = sampler or ResourceSampler(), clock or time.monotonic
        self._lock, self._stop = threading.Lock(), threading.Event()
        self._thread = None
        self._sampled_monotonic = None
        self._failed = False
        self._cache = empty_snapshot(mode, is_wsl='microsoft' in platform.release().lower())

    def snapshot(self):
        with self._lock:
            result = copy.deepcopy(self._cache)
            sampled = self._sampled_monotonic
            failed = self._failed
            if self._thread is None and not self._stop.is_set():
                self._thread = threading.Thread(target=self._loop, daemon=True, name='studio-resources')
                self._thread.start()
        age = max(0., self._clock() - sampled) if sampled is not None else None
        result.update(mode=self.mode, refresh_interval_seconds=self.interval,
                      age_seconds=round(age, 1) if age is not None else None,
                      stale=failed or self._stop.is_set() or (age is not None and age > max(7, 2 * self.interval)))
        return result

    def _loop(self):
        while not self._stop.is_set():
            started = self._clock()
            try:
                data = self._sampler()
                data['sampled_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
                # Strict JSON serialization prevents NaN from poisoning an HTTP response.
                import json
                json.dumps(data, allow_nan=False)
                with self._lock:
                    self._cache, self._sampled_monotonic, self._failed = data, self._clock(), False
            except Exception:
                with self._lock:
                    self._failed = True
                    self._cache['status'] = 'unavailable'
                    self._cache['errors'] = [{'component': 'sampler', 'reason': '资源采样失败，正在等待下次探测。'}]
            if self._stop.wait(max(.1, self.interval - (self._clock() - started))):
                break

    def close(self):
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=GPU_TIMEOUT_SECONDS + .5)
