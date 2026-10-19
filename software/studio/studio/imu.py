"""IMU 页的后端：给页面推 IMU 的状态，接页面的指令（照 servo_ops 的 handle 写法）。

方案：scratchpad console/imu-page-plan.md（子代理 10-18 写的，带出处）。这一步只接「现在就能做」的：
- view()：芯片、读数状态、安装方向（每种芯片各存一份）、最近一次站着校准的时间；
- solve：页面采到的读数交给 imu_calib.solve 算安装方向（纯计算）。

写入保存、粗校、识别芯片、换芯片要在鸭子上执行系统命令（service.sh、imu-module-install.sh、重启主程序，
写的时候鸭子会软倒一次），sudo 白名单要用户拍板、路径要上鸭子核实，先回一句人话说清楚，下一步再接。
"""
import asyncio
import json
import os
import time

from . import imu_calib
from .robotd import fresh_calib

MAX_SAMPLES = 6000          # 一次 solve 最多收这么多读数（5 步 × 每步 ≤ 600 还有富余），防页面发个巨包
ON_DUCK = "这一步要在鸭子上执行系统命令（写的时候鸭子会软倒一次），要先确认权限和主程序的脚本路径：下一步上鸭子时接"
# 「核对过」的门槛（总览重排审查 O4）：站着完整校一次，算出来的跟主程序现在用的方向差 < 2°、站姿倾斜 ≤ 5°
# （5° 是 imu_calib RULES 的 stand_confirm_deg：robotd 自己验方向时直立只放 5°）
CHECK_MAX_DIFF_DEG = 2.0


class Refused(Exception):
    """这个操作现在不能做，原因直接给页面看。"""


def mount_of(bus, calib):
    """(用的哪颗芯片, {"quat", "verified"} 或 None)。IMU 页和总览上手清单共用这一个挑法（审查 C3）：
    先看 calibration-status 顶上 robotd 挑好的 imu_mount，再看 imu_mounts[芯片]，最后才是总线小板那一份。
    别拿 calibration.imu_mount_verified 判模块 IMU（那是总线小板的）。"""
    bus = bus if isinstance(bus, dict) else {}
    native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
    calib = calib if isinstance(calib, dict) else {}
    cal = calib.get("calibration") if isinstance(calib.get("calibration"), dict) else calib
    # 用的哪颗芯片：busStatus 的 native.imu_source；robotd 卡在等总线时 busStatus 里没有它，
    # 退到 calibration-status 顶上的 imu_source（模块芯片别被当成总线小板，IMU 子代理复核 #4）；
    # 两边都没有、但 busStatus 有 native → 总线小板（方案 6.5）
    source = native.get("imu_source") or calib.get("imu_source") or ("bus" if native else None)
    top = calib.get("imu_mount") if isinstance(calib.get("imu_mount"), dict) else None
    mounts = cal.get("imu_mounts") if isinstance(cal.get("imu_mounts"), dict) else {}
    if top and top.get("quat") and calib.get("imu_source") in (None, source):
        mount = {"quat": top.get("quat"), "verified": top.get("verified")}     # robotd 自己挑好的那份
    elif source in mounts and isinstance(mounts[source], dict):
        mount = {"quat": mounts[source].get("quat"), "verified": mounts[source].get("verified")}
    elif cal.get("imu_mount_quat"):
        mount = {"quat": cal.get("imu_mount_quat"), "verified": cal.get("imu_mount_verified")}
    else:
        mount = None
    return source, mount


class ImuBackend:
    def __init__(self, robotd, log, state_dir="."):
        self.rd, self.log, self.state_dir = robotd, log, state_dir
        self.job = None              # 正在做的粗校 / 写入 / 换芯片的进度（这一步还没有）
        self.detected = None         # 最近一次识别芯片的结果（这一步还没有）
        self.last_result = None      # 最近一次 solve 的结果：写入只认这一份
        # 总览上手清单的「IMU 核对过」记录（审查 O4）：app 接上 Onboarding.note_imu_check。不是写入鸭子：写入照旧要上鸭子再接
        self.on_check = None

    # ---- 推给页面 ----

    def view(self):
        bus = self.rd.bus.value if isinstance(self.rd.bus.value, dict) else {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # 标定状态只认这次 hello 之后读到的（总览重排审查 O5：robotd 重启后旧的「已确认」不能当真）
        source, mount = mount_of(bus, fresh_calib(self.rd))
        return {
            "t": "imu", "source": source, "chip_setting": None, "mount": mount,
            "reader": native.get("imu_reader"), "age_ms": native.get("imu_age_ms"), "ready": native.get("imu_ready"),
            "detected": self.detected, "stand_calib_at": self._stand_calib_at(), "job": self.job,
        }

    def _stand_calib_at(self):
        try:
            with open(os.path.join(self.state_dir, "imu-stand-calib.json"), encoding="utf-8") as f:
                return json.load(f).get("at")
        except (OSError, ValueError):
            return None

    # ---- 页面的指令 ----

    async def handle(self, args, by=None):
        op = args.get("op")
        if op == "solve":
            samples = args.get("samples")
            if not isinstance(samples, list) or not samples:
                raise Refused("没收到读数")
            if len(samples) > MAX_SAMPLES:
                raise Refused(f"读数太多（{len(samples)} 个，最多 {MAX_SAMPLES}）")
            mode = args.get("mode", "full")
            if mode not in ("full", "coarse"):
                raise Refused(f"不认识的校准方式：{mode}")
            # 旧方向只认主程序那份（不收页面传的），页面传来的 rules / home_gravity 也不透传（审查 A3）
            view = self.view()
            old = (view["mount"] or {}).get("quat")
            old_verified = bool((view["mount"] or {}).get("verified"))
            res = await asyncio.to_thread(lambda: imu_calib.solve(
                samples, frame="body", old_mount=old, mode=mode, old_verified=old_verified))
            self.last_result = res
            detail = json.dumps({k: res.get(k) for k in ("mount", "quality", "confirm", "parts", "redo") if k in res},
                                ensure_ascii=False)[:1500]
            if res.get("ok"):
                self.log.info("IMU 安装方向算出来了（还没写入）", cat="IMU", raw=detail,
                              ctx={"by": by, "source": view["source"], "mode": mode, "old_verified": old_verified})
                if mode == "full":
                    res["check"] = self._check(res, view, old, old_verified, by)
            else:
                redo = "、".join(res.get("redo") or []) or "—"
                self.log.warn(f"IMU 校准没过：{res.get('reason')}（要补做：{redo}）", cat="IMU", raw=detail, step="算安装方向",
                              ctx={"by": by, "source": view["source"], "mode": mode},
                              hint="照页面上的提示重做那一步；还不行就导出诊断包")
            return res
        if op in ("save", "coarse", "detect", "set_chip"):
            raise Refused(ON_DUCK)
        raise Refused(f"不认识的指令：{op}")

    def _check(self, res, view, old, old_verified, by):
        """完整站着校完（solve full、ok）：跟主程序现在用的方向比一比，够近就给上手清单记一笔「核对过」（审查 O4）。
        只记一笔核对，**不往鸭子写任何东西**（写入要上鸭子再接）。回给页面看的 {recorded, diff_deg, tilt_deg, why}。"""
        parts = res.get("parts") or {}
        diff, tilt = parts.get("total_deg"), parts.get("stand_tilt_deg")
        why = None
        if not old or not old_verified:
            why = "主程序存的方向还没确认过（verified 不是 true）：先粗校、写入，才谈得上核对"
        elif not isinstance(diff, (int, float)) or not isinstance(tilt, (int, float)):
            why = "这次没算出差多少度"
        elif tilt > imu_calib.RULES["stand_confirm_deg"]:
            why = (f"站姿倾斜 {tilt:.1f}°（要 ≤ {imu_calib.RULES['stand_confirm_deg']:.0f}°）：多半是腿的零位没校好、"
                   "桌子不平或者静止时手碰着了")
        elif diff >= CHECK_MAX_DIFF_DEG:
            why = f"主程序现在用的方向跟这次算的差 {diff:.1f}°（要 < {CHECK_MAX_DIFF_DEG:g}°）：要写入新方向（写入要上鸭子再接）"
        ok = why is None
        out = {"recorded": False, "ok": ok, "diff_deg": diff, "tilt_deg": tilt, "why": why}
        hook = self.on_check
        # 方向没确认过的不记（清单那一步本来就是「没做」）；差得多的也记：最近一次核对说「差 x°」，清单照实写「要重做」
        if hook is not None and old and old_verified and isinstance(diff, (int, float)):
            try:
                out["recorded"] = bool(hook({"source": view["source"], "quat": old, "verified": True,
                                             "diff_deg": diff, "tilt_deg": tilt, "ok": ok, "by": by}))
            except Exception as e:  # noqa: BLE001 —— 记不上不影响算方向
                self.log.error("记「IMU 核对过」时出错", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                               hint="这是 Studio 的问题；校准结果照常能看")
        if ok:
            self.log.info(f"IMU 方向核对过：跟主程序现在用的差 {diff:.1f}°、站姿倾斜 {tilt:.1f}°", cat="IMU",
                          ctx={"by": by, "source": view["source"]})
        else:
            self.log.info(f"IMU 方向这次没算「核对过」：{why}", cat="IMU", ctx={"by": by, "source": view["source"]})
        return out
