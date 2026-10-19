"""调 root 小助手（/usr/local/sbin/microduck-helper）停、起主程序 robotd（舵机总线交接）。

Studio 不是 root。sudoers 只放行 microduck-helper 这一个全路径，所以这里用 `sudo -n`
调它、stdin 传一个 JSON，别的权限一点没有。小助手认 bus-take / bus-give-back /
bus-abort / pad-pair / pad-forget 五个动词，参数逐个校验，robotd 的状态它自己去读，不信网页传来的（deploy/INSTALL.md）。

- bus-take：停 robotd、立旗（robotd 起不来）、确认串口空出来 → Studio 打开总线。不卸力。
- bus-give-back {"soft": true}：Studio 已经在总线上全卸了 → 撤旗、起 robotd、等启动四步成功。
- bus-give-back {"marker": {...}}：不卸力交还（写交接标记，fork 的 robotd 读走并接手保持）。
  要 fork 的 robotd 装上、drop-in 打开 Environment 才认；旧版不认，会照老规矩全卸（result=limp）。
- pad-pair：以 root 跑官方 `robotctl pad pair --json`。weird-ble 板上 robotctl 会先停 btd、把适配器断电再开，
  所以这条主路能配上新 Switch Pro 类手柄。旧版小助手回 bad_verb，调用方据此退回 configd / bluetoothctl。
- pad-forget：以 root 跑官方 `robotctl pad forget MAC`。

没装小助手（电脑上开发、台架、演示）就优雅回退：bus_take 当没做（交给 servo.open 自己的
robotd_active 检查去报错），bus_give_back 当没做（交还以后主程序由人手动起）。
"""
import json
import os
import subprocess
import sys

HELPER = "/usr/local/sbin/microduck-helper"
FLAG = "/run/microduck-helper/bus-held"       # 接管期间立着：robotd 的 drop-in 看到它就不肯起来

_avail = None


def flag_present():
    """接管旗在不在（只在 Linux 上查；电脑 / 测试里 patch 这个函数）。"""
    if not sys.platform.startswith("linux"):
        return False
    return os.path.exists(FLAG)


def available():
    """小助手在不在、sudoers 放行没（结果缓存：装不装在运行中不会变）。
    用 `sudo -n microduck-helper bus-nope` 探：能调就返回 2（动词不认识，说明文件在、sudoers 放行）；
    返回别的 = 没装 / 没放行 / 不在 Linux。"""
    global _avail
    if _avail is not None:
        return _avail
    if not sys.platform.startswith("linux") or not os.path.exists(HELPER):
        _avail = False
        return False
    try:
        r = subprocess.run(["sudo", "-n", HELPER, "bus-nope"], capture_output=True, text=True, timeout=5)
        _avail = r.returncode == 2
    except (OSError, subprocess.TimeoutExpired):
        _avail = False
    return _avail


def _call(verb, payload, timeout):
    """跑 `sudo -n microduck-helper <verb>`，stdin 传 JSON。回 (ok, result, detail)。
    ok = 最后一行 done 的 exit 是 0；result / detail 是 done 那一行的 detail 字段。"""
    try:
        proc = subprocess.run(["sudo", "-n", HELPER, verb], input=json.dumps(payload, ensure_ascii=False),
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}", None
    result, detail = None, None
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("step") == "done":
            d = obj.get("detail") or {}
            result, detail = d.get("result"), d
    if result is None:
        err = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        return False, err or f"exit {proc.returncode}", None
    return detail.get("exit") == 0, result, detail


def bus_take(by, allow_seated=False, timeout=30):
    """停 robotd、把舵机总线交给 Studio（不卸力）。回 (ok, result, detail)。"""
    return _call("bus-take", {"by": by, "allow_seated": allow_seated}, timeout)


def bus_give_back(by, *, soft=True, marker=None, timeout=60):
    """交还总线、起 robotd。soft=True 是软交还（Studio 已全卸）；传 marker 是不卸力交还（fork 接手保持）。
    回 (ok, result, detail)。"""
    payload = {"by": by, "soft": True} if soft else {"by": by, "marker": marker}
    return _call("bus-give-back", payload, timeout)


def bus_abort(by, timeout=10):
    """中止交接（交接倒数期间页面按了卸力）：KILL robotd、删标记、把总线还给 Studio。回 (ok, result, detail)。"""
    return _call("bus-abort", {"by": by}, timeout)


def pad_pair(by, mac=None, timeout=60):
    """官方 robotctl pad pair（小助手以 root 跑）。回 (ok, result, detail)。
    detail["pair"] 是 PadPairResult；detail["stderr"] 是 robotctl 的几行提示（暂停 btd、警告等）。"""
    payload = {"by": by, "timeout": timeout}
    if mac:
        payload["mac"] = mac
    return _call("pad-pair", payload, timeout + 45)


def pad_forget(by, mac, timeout=60):
    """官方 robotctl pad forget（小助手以 root 跑）。回 (ok, result, detail)。"""
    return _call("pad-forget", {"by": by, "mac": mac}, timeout)


_TAKE_WHY = {
    "taken": "主程序停了，总线交给你了",
    "refused": "主程序没停（策略在跑、正在回站姿，或者坐姿没放行）",
    "no_guard": "没装 robotd 的保护（drop-in），不肯停主程序",
    "busy": "小助手正忙（板端脚本在跑，或者另一个总线操作没跑完）",
    "stop_failed": "主程序停不下来（KILL 也没停）",
    "port_busy": "串口还被占着",
}

_GIVE_WHY = {
    "soft": "主程序起来了",
    "soft_failed": "主程序起不来",
    "adopted": "主程序接手保持了（没卸力）",
    "limp": "主程序没认交接标记，照老规矩全卸了",
    "retake": "主程序没起来，总线拿回来了（Studio 还保持着）",
    "retake_failed": "总线没拿回来",
    "aborted": "交还被中止了（按了卸力）",
    "refused": "串口还被占着",
    "no_session": "没有调舵机的会话（旗不在）",
    "detach_failed": "交还起不来（systemd-run 失败）",
}

_PAD_WHY = {
    "paired": "配上了",
    "pair_failed": "没配上（robotctl 说失败）",
    "no_robotctl": "鸭子上没有官方 robotctl（/usr/local/bin/robotctl）",
    "timeout": "robotctl 超时了，已经停下",
    "bad_output": "robotctl 的回包看不懂",
    "forgotten": "忘掉了",
    "forget_failed": "没忘掉",
    "busy": "小助手正忙（另一个配对或忘掉没做完）",
}

_COMMON = {
    "bad_args": "参数不对",
    "bad_marker": "交接标记不对",
    "bad_verb": "动词不认识",
    "not_root": "没权限（要用 root）",
    "error": "小助手自己出错",
}


def friendly(result, detail, verb):
    """把 result 换成人话（result 的值见 deploy/INSTALL.md §1）。detail 里的小助手原话一并带上。"""
    if verb in ("pad-pair", "pad-forget"):
        table = _PAD_WHY
    else:
        table = _TAKE_WHY if verb == "bus-take" else _GIVE_WHY
    text = table.get(result) or _COMMON.get(result) or (result or "没成")
    if result == "pair_failed" and isinstance(detail, dict) and detail.get("reason"):
        text = f"{text}（{detail['reason']}）"
    msg = detail.get("msg") if isinstance(detail, dict) else None
    if msg and msg not in text:
        text = f"{text}：{msg}"
    return text
