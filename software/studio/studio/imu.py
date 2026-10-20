"""IMU 页的后端：给页面推 IMU 的状态，接页面的指令（照 servo_ops 的 handle 写法）。

方案：scratchpad console/imu-page-plan.md（子代理 10-18 写的，带出处）。这一步只接「现在就能做」的：
- view()：芯片、读数状态、安装方向（每种芯片各存一份）、最近一次站着校准的时间；
- solve：页面采到的读数交给 imu_calib.solve 算安装方向（纯计算）。

完整站着校完、结果 ok 的那一份记进 state 目录的 imu-pending.json（Studio 重启也不丢），最后由上手清单
的「写进主程序」一次写进 robotd。出厂镜像跑标定模式：粗校从 busStatus.last_sample.imu 采静止和前倾，
算完直接交给主程序的 verify-imu（摆正 ≤5°，20 秒内往前低头 15–30°），主程序自己写标定文件。
识别芯片、换芯片仍不在 Studio 里做；提示用户用 SSH 跑 microduck-firstboot。
"""
import asyncio
import json
import math
import os
import time

from . import imu_calib
from .robotd import fresh_calib
from .rpc import RpcError, Timeout, Unreachable, call_once

MAX_SAMPLES = 6000          # 一次 solve 最多收这么多读数（5 步 × 每步 ≤ 600 还有富余），防页面发个巨包
ON_DUCK = ("识别芯片、换芯片不在网页里做：IMU 要在第一次开机前接好；之后才接的，要用 SSH 运行 "
           "sudo microduck-firstboot --detect-imu-only --force")
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
        self.job = None              # 粗校采数 / 交给主程序验证的进度
        self.detected = None         # 最近一次识别芯片的结果（这一步还没有）
        self.last_result = None      # 最近一次 solve 的结果：写入只认这一份
        # 总览上手清单的「IMU 核对过」记录（审查 O4）：app 接上 Onboarding.note_imu_check。不是写入鸭子：写入照旧要上鸭子再接
        self.on_check = None
        self.commit = None           # 写进主程序的后端（app 接上）：标定模式「站姿使能」要跟它同一套方向

    # ---- 推给页面 ----

    def view(self):
        bus = self.rd.bus.value if isinstance(self.rd.bus.value, dict) else {}
        native = bus.get("native") if isinstance(bus.get("native"), dict) else {}
        # 标定状态只认这次 hello 之后读到的（总览重排审查 O5：robotd 重启后旧的「已确认」不能当真）
        source, mount = mount_of(bus, fresh_calib(self.rd))
        ls = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
        s_imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        reader = native.get("imu_reader")
        if reader is None and bus.get("mode") == "commissioning":
            reader = {"state": ("streaming" if s_imu.get("ready") else "missing"), "errors": 0}
        return {
            "t": "imu", "mode": bus.get("mode"), "source": source, "chip_setting": None, "mount": mount,
            "reader": reader, "age_ms": native.get("imu_age_ms", s_imu.get("age_ms")),
            "ready": native.get("imu_ready", s_imu.get("ready")),
            "valid": s_imu.get("valid"), "gravity": s_imu.get("gravity"),
            "hold": bus.get("hold") if isinstance(bus.get("hold"), dict) else None,
            "detected": self.detected, "stand_calib_at": self._stand_calib_at(), "job": self.job,
        }

    def _stand_calib_at(self):
        try:
            with open(os.path.join(self.state_dir, "imu-stand-calib.json"), encoding="utf-8") as f:
                return json.load(f).get("at")
        except (OSError, ValueError):
            return None

    # ---- 页面的指令 ----

    async def _bus_once(self):
        """标定模式采数走新连接直接读 busStatus；测试 / 台架没有地址时退到已缓存的那份。"""
        addr = getattr(self.rd, "addr", None)
        if addr and addr != "none":
            r = await call_once(addr, "robot.busStatus", {}, timeout=1.5, name="粗校读数")
            return r if isinstance(r, dict) else {}
        v = getattr(getattr(self.rd, "bus", None), "value", None)
        return v if isinstance(v, dict) else {}

    async def _rpc_once(self, method, params, timeout, name):
        """新开一条连接问一次。台架 / 测试里的假 rd 没有地址时，退到它的 cmd 连接。"""
        addr = getattr(self.rd, "addr", None)
        if addr and addr != "none":
            return await call_once(addr, method, params, timeout=timeout, name=name)
        conn = getattr(self.rd, "cmd", None)
        call = getattr(conn, "call", None)
        if call is None:
            raise Unreachable("没有跟主程序的连接：等它起来再试")
        return await call(method, params, timeout)

    @staticmethod
    def _sample_g(bus):
        ls = bus.get("last_sample") if isinstance(bus.get("last_sample"), dict) else {}
        imu = ls.get("imu") if isinstance(ls.get("imu"), dict) else {}
        g = imu.get("gravity")
        if imu.get("valid") is not True or not isinstance(g, list) or len(g) != 3:
            return None, imu
        try:
            v = [float(x) for x in g]
        except (TypeError, ValueError):
            return None, imu
        if not all(math.isfinite(x) for x in v) or sum(x * x for x in v) < 1e-9:
            return None, imu
        return v, imu

    async def _capture(self, args, by=None):
        phase = args.get("phase")
        if phase not in ("still", "fwd", "back"):
            raise Refused("粗校采数只认 still / fwd / back")
        seconds = args.get("seconds", 3.0 if phase != "back" else 2.0)
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0.5 <= float(seconds) <= 8.0:
            raise Refused("采数时间要在 0.5–8 秒之间")
        out, t0, last_tilt = [], time.monotonic(), None
        label = {"still": "摆正，别动", "fwd": "往前低头", "back": "往后仰"}[phase]
        self.job = {"kind": "coarse", "title": "粗校采数", "msg": f"{label}：{float(seconds):g} 秒",
                    "target_deg": 20 if phase == "fwd" else 0, "hold": 0.0}
        while time.monotonic() - t0 < float(seconds):
            bus = await self._bus_once()
            if bus.get("mode") != "commissioning":
                self.job = {"kind": "coarse", "title": "粗校采数", "failed": True,
                            "msg": "主程序已经不在标定模式了"}
                if bus.get("mode") == "motion":
                    raise Refused("主程序已经在运动模式：站起来以后用站着校准")
                raise Refused("主程序没在标定模式：等它回到标定模式再粗校")
            g, imu = self._sample_g(bus)
            if g is not None:
                out.append({"step": phase, "t": time.monotonic() - t0, "g": g})
                tilt = imu.get("tilt_deg")
                if isinstance(tilt, (int, float)):
                    last_tilt = float(tilt)
            self.job.update({"hold": min(1.0, (time.monotonic() - t0) / float(seconds)),
                             "tilt_deg": last_tilt})
            await asyncio.sleep(0.1)
        if len(out) < 15:
            self.job = {"kind": "coarse", "title": "粗校采数", "failed": True,
                        "msg": f"只采到 {len(out)} 个有效读数"}
            raise Refused(f"只采到 {len(out)} 个有效 IMU 读数（至少 15 个）：检查模块接线，或者重新接好再开机")
        self.job = {"kind": "coarse", "title": "粗校采数", "msg": f"{label}采好了",
                    "done": True, "tilt_deg": last_tilt, "target_deg": 20 if phase == "fwd" else 0}
        self.log.info(f"IMU 粗校采到「{label}」{len(out)} 个读数", cat="IMU",
                      ctx={"by": by, "phase": phase, "source": self.view().get("source")})
        return {"phase": phase, "n": len(out), "samples": out}

    @staticmethod
    def _translate_verify_error(err):
        text = getattr(err, "message", None) or str(err)
        low = text.lower()
        if "needs a live" in low or "last_sample" in low:
            msg = "主程序没有 IMU 读数：检查模块接线，确认主程序在标定模式并且读数在更新"
        elif "from upright" in low or "stand the robot upright" in low:
            msg = "没有摆正：双手托起鸭子，让主程序看到的倾角 ≤5°；如果怎么摆都超，安装方向可能不对"
        elif "from nose-down" in low or "about the vertical axis" in low:
            msg = "低头方向不对：模块装法可能反了，或者绕竖直轴转了约 90°。对照模块实际装法重做"
        elif "no nose-down tip" in low or "within 20 s" in low:
            msg = "超时没看到往前低头：摆正以后要在 20 秒内往前低头 15–30° 并停住"
        elif "cancelled by relax" in low:
            msg = "验证被卸力打断了：扶好鸭子，重新做一次"
        else:
            msg = f"主程序没通过验证：{text}"
        return msg + "。主程序什么都没存（Nothing saved）"

    async def _hold(self, by=None):
        """标定模式「站姿使能」（用户 10-21：「咱标定也能站姿不就好了吗？非要切到运动模式」）。
        fork 标定模式的 hold-home：15 颗一起 3 秒转到 HOME、锁住，IMU 照常读，站着校准就在标定模式里做。
        方向跟第 3 步「写进主程序」同一套，零位用主程序文件里的（出厂 2048）。失能 = 顶上的「卸力」（robot.relax）。"""
        bus = await self._bus_once()
        if bus.get("mode") != "commissioning":
            raise Refused("主程序不在标定模式：运动模式下用遥控卡的「站起来」")
        if self.commit is None:
            raise Refused("这只鸭子没开「写进主程序」的后端，算不出 15 颗的方向")
        from .commit import Refused as CommitRefused
        try:
            dirs = self.commit.hold_directions()
        except CommitRefused as e:
            raise Refused(str(e)) from e
        try:
            # fork 的 command_timeout：3 秒爬升 + 2 秒稳住 + 10 秒；再加余量
            r = await self._rpc_once("robot.busCommand",
                                     {"action": "hold-home", "directions": dirs, "duration_ms": 3000},
                                     20.0, "站姿使能")
        except (RpcError, Timeout, Unreachable) as e:
            text = getattr(e, "message", None) or str(e)
            low = text.lower()
            if "unknown variant" in low or "hold-home" in low and "unknown" in low:
                msg = "主程序版本太旧，标定模式还不会站：要更新主程序"
            elif "still" in low and "from home" in low:
                msg = f"有关节转不到站姿（{text}）：多半是方向反了或者被卡住，已经卸力。去舵机页核对方向"
            elif "relax" in low:
                msg = "站起来的途中被卸力打断了"
            else:
                msg = f"没站起来：{text}"
            self.log.warn(f"标定模式站姿使能没成：{msg}", cat="IMU", raw=text, ctx={"by": by, "directions": dirs})
            raise Refused(msg) from e
        self.log.info("标定模式站姿使能：站住了", cat="IMU", raw=json.dumps(r, ensure_ascii=False)[:400],
                      ctx={"by": by, "directions": dirs})
        return r

    async def _verify(self, args, by=None):
        bus = await self._bus_once()
        if bus.get("mode") != "commissioning":
            raise Refused("主程序已经在运动模式：站起来以后用站着校准")
        mount = args.get("mount_wxyz") or args.get("mount")
        if args.get("confirmed") is not True or not isinstance(mount, list) or len(mount) != 4:
            raise Refused("要先对照模块实际装法勾选确认，再交给主程序验证")
        last = self.last_result if isinstance(self.last_result, dict) else {}
        if not last.get("ok") or last.get("mode") != "coarse" or last.get("mount") != mount:
            raise Refused("这份方向不是刚刚粗校算出来的：重新算一次再验证")
        self.job = {"kind": "coarse", "title": "交给主程序验证",
                    "msg": "摆正，然后 20 秒内往前低头 15–30°", "target_deg": 20}
        try:
            # fork 的 command_timeout 是 20 秒窗口 + 10 秒；再加 5 秒余量
            r = await self._rpc_once("robot.busCommand",
                                     {"action": "verify-imu", "confirmed": True, "mount_wxyz": mount},
                                     35.0, "验证 IMU 方向")
        except (RpcError, Timeout, Unreachable) as e:
            msg = self._translate_verify_error(e)
            self.job = {"kind": "coarse", "title": "主程序验证没通过", "failed": True, "msg": msg,
                        "raw": getattr(e, "message", None) or str(e)}
            self.log.warn(f"IMU 粗校验证没通过：{msg}", cat="IMU", raw=str(e),
                          ctx={"by": by, "source": self.view().get("source")})
            raise Refused(msg) from e
        # 成功以后主程序已经写进标定文件：马上重读一次 calibration-status，第 2 步才能变 ✓
        try:
            status = await self._rpc_once("robot.busCommand", {"action": "calibration-status"},
                                          5.0, "重读标定状态")
            if isinstance(status, dict) and hasattr(self.rd, "calib"):
                self.rd.calib.set(status)
        except (RpcError, Timeout, Unreachable):
            status = None
        self.last_result = None
        self.job = {"kind": "coarse", "title": "主程序验证通过", "done": True,
                    "msg": "已经写进标定文件，IMU 方向已确认"}
        self.log.info("IMU 粗校验证通过：主程序已把安装方向写进标定文件", cat="IMU",
                      ctx={"by": by, "source": self.view().get("source"), "mount": mount})
        return {"ok": True, "note": "主程序验证通过，安装方向已经写进标定文件", "reply": r, "calibration": status}

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
            if mode == "coarse" and self.view().get("mode") == "motion":
                raise Refused("主程序已经在运动模式：站起来以后用站着校准")
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
                self.log.info("IMU 安装方向算出来了（还没写进主程序）", cat="IMU", raw=detail,
                              ctx={"by": by, "source": view["source"], "mode": mode, "old_verified": old_verified})
                if mode == "full":
                    try:
                        from .commit import save_pending
                        save_pending(self.state_dir, view["source"], res.get("mount"), res.get("quality"), by)
                    except Exception as e:  # noqa: BLE001 —— 存不下不影响这一次的结果给页面看
                        self.log.error("这次的 IMU 方向没记下来", cat="IMU", raw=f"{type(e).__name__}: {e}", exc=True,
                                       hint="重校的时候还会再记一次；一直不行就导出诊断包")
                    res["check"] = self._check(res, view, old, old_verified, by)
            else:
                redo = "、".join(res.get("redo") or []) or "—"
                self.log.warn(f"IMU 校准没过：{res.get('reason')}（要补做：{redo}）", cat="IMU", raw=detail, step="算安装方向",
                              ctx={"by": by, "source": view["source"], "mode": mode},
                              hint="照页面上的提示重做那一步；还不行就导出诊断包")
            return res
        if op == "hold":
            return await self._hold(by)
        if op == "coarse-capture":
            return await self._capture(args, by)
        if op == "verify":
            return await self._verify(args, by)
        if op in ("save", "coarse", "detect", "set_chip"):
            if op == "save":
                raise Refused("新的 IMU 方向已经记下了：去「上手清单」第 3 步点「写进主程序」")
            if op == "coarse":
                raise Refused("粗校请用页面上的「粗校」三步按钮：采静止、采前倾、交给主程序验证")
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
