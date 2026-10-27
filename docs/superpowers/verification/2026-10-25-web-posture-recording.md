# 坐下与站起进入网页录制：验收及部署

日期：2026-10-25（东京时间）。用户指出只录坐下/站起被报“没有有效动作”，随后明确回复“对，把坐下和站起也录进去”。本轮修正原首版排除坐站的范围，见[设计](../specs/2026-10-25-web-posture-recording-design.md)与[计划](../plans/2026-10-25-web-posture-recording.md)。

**结果：已更新原控制网址，用户确认“能保存，回放坐站也正常”。** 该确认覆盖本只鸭子的网页坐站录制、保存及实际回放，不扩大为所有模型技能或长时运动均已验收。

## 冻结版本与行为

安装的运行代码提交为 `aa825fcf7ad153f959ed793e9ed871cabbc24e29`。组成包括 73c9a4f（后端/严格格式/模拟器）、396af04（证据丢失及时间边界）、75ce49d（网页提示和完整浏览器流程）及 aa825fc（保留手动坐站接管）。已快进合入 studio-dev，原未跟踪的语音源码和 UI 笔记保留。

现在只录“坐下→等待→站起→等待”也能生成草稿并保存，遥控按钮及网页十字下均支持。坐站记为白名单目标 `studio.posture {target: sit|stand}`，不是直接保存一个 toggle。回放先查当前姿态，已是目标不重按；按新鲜策略阶段及连续实际/目标关节回读确认后再继续。坐姿标志在起身开始时就会消失，不能以它或 homed 单独判定起身完成。

新模块 `motion_posture.py` 与原会话/时间轴分离。取现有 robot.state 的 policy、样本时间、joints/targets，等待三个不同的新样本；源证据明确要求新鲜且与总线/姿态一致。只读实测八个站立样本的最大静态目标偏差约 0.1305–0.1318 rad，采用 0.18 rad 容差并同时要求连续稳定及正确策略阶段；这不是精确物理位置保证。等待上限 15 秒，未知回执不重试切换，晚回执及回执前采到的帧不能解除新步骤屏障。

缺失/过期阶段或关节信息、目标外姿态变化、原有保护、实体手柄接入、切页/后台/失焦、断线及心跳超时均取消后续自动输出。证据恢复只可解除物理步骤的占用，不会续播取消的会话。普通暂停/停止不物理取消已开始的坐站，页面明确提示当前坐站仍会完成；清除连续控制、冻结/终止后续步骤，不自动回 HOME 或卸力，急停仍走原通道。已知且一致的实际姿态允许用户明确手动接管相反目标，避免严格自动回放检查误挡普通“站起来”；同目标未知重试仍被拒绝。

含坐站记录使用 v2；旧 v1 仍可读，原上限 60 秒/6,000 事件/1 MiB/20 段保持。等待阶段也执行录制时长上限；回放等待会延长实际播放时间。坐着结束的记录可单次播放；多次循环需末尾录回站姿，否则明确拒绝，不补一个隐式站起。踢腿、翻滚、捡取、上力/卸力、策略启停、模型切换及音视频录制仍不在本轮范围。

## 软件检查

固定运行代码通过 **389 项检查**，不重复计算独立审查或集成复测：

| 范围 | 最终结果 | 证据（工作区 artifacts/web-posture-recording-20261025/） |
| --- | --- | --- |
| 坐站、动作和原手柄后端 | 241 项，33.480 秒，OK | backend-final2.log |
| HTTP、原虚拟手柄、总览和传感器回归 | 140 项，330.657 秒，OK | regression-final.log |
| 页面会话/心跳 | 7 项，OK | 本轮 Node 工具输出 |
| 真实 Studio + fake robotd + Edge 全流程 | 1 项，64.262 秒，OK | browser-final.log、browser-final/browser.json |

独立需求审查复现并修复：丢失步骤证据后错误续播、已站起后外来坐姿仍可继续移动、等待绕过 60 秒上限。独立质量审查复现并修复：严格收敛检查误挡普通手动站起/恢复。修复后审查通过，质量审查另跑 82 项通过；合入 studio-dev 后又跑 82 项，7.189 秒，OK。

命令在 software/studio 目录执行：

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_posture','tests.test_motion_studio','tests.test_pad'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

浏览器实际发给 fake robotd 的坐站请求：录制 2 次、单次回放 2 次、三轮回放 6 次；坐下后立即停止只发 1 次，切页也只发 1 次，没有后续站起。保存的 JSON 是 v2，目标顺序为 sit、stand；控制台错误 `[]`，桌面 1440px、手机 390/320px 布局及截图通过。既有灵动、保存/改名/刷新/删除和回放暂停/恢复检查保留。

更早测试先复现原有“坐下结束录制”，再实现。长浏览器测试曾因 Windows 将 headless 标签隐藏而触发正常后台取消；诊断确认 hidden、activity=false 和 stop 请求，后在测试中使用焦点模拟保持测试页活跃，未改产品后台/失焦保护。另一次 241 项运行的原配对测试在临时日志目录清理时遇到 WinError 145；该单项连续五次及最终整套通过，未修改无关配对代码。保留旧日志，不宣称解决了原测试资源竞争。

## 设备切换与用户确认

用户先明确回复“已停下，站着保持”。安装脚本再次确认 motion/control、实时 policy_enabled=false、无舵机会话，才切换 Studio。冻结 Git 字节与依赖版本核对后，只更新七个文件：

```text
studio/motion_posture.py    studio/motion_store.py
studio/motion_studio.py    studio/pad.py
studio/pad_drive.py        web/motion-studio.js
web/motion-studio.css
```

只重启 microduck-studio，PID 从 21540 变为 29493。robotd=1105、padd=1138、duck-echo=1110 的 PID 及单调启动时间前后一致；四个服务 active，语音 enabled。七个安装文件与清单哈希一致，原有 12 个用户数据文件与停止网页服务时的备份逐字节一致。根页面、healthz、pad.js 及动作资源均返回 200，实际服务 JS/CSS 哈希与安装文件一致，静态资源 no-cache。

私有备份为 `/home/radxa/.microduck-backups/web-motion-20261025-aea50f88a1`（0700），包含旧运行文件及 user-state。工作区 `artifacts/web-posture-recording-20261025/deployment/` 保存更新前程序、清单、切换结果和回读；只读真实关节样本在 `actual-posture-samples.json`，不纳入通用交付。已有登录保护保持，未经登录的动作快照未绕过认证。自动测试不主动向真鸭子发坐站或行走命令。

安装后用户按“开始走→开始录制→坐下→等确认→站起→等确认→结束→命名保存→回放一次”试用，回复 **“能保存，回放坐站也正常”**，记为本次真机通过。

## 后续交付与回退边界

冻结源码归档、版本/哈希清单、验收副本保存在工作区 `artifacts/web-posture-recording-20261025/release/`。不包含个人密码、SSH 密钥、家庭 Wi-Fi、配对或 state。本轮没有重建镜像、启用 updaterd 或公开发布；后续统一包/镜像需采用同一冻结来源再验收。

单机切换失败时脚本恢复旧运行文件并只重启 Studio；本次成功，未做真机失败注入。人工回退前先停止策略、确认无舵机会话，停止 Studio，按备份清单恢复旧文件、仅删除清单标记为此前不存在的新增模块，再启动并检查网页。保留后来保存的动作，不直接覆盖为旧 state。回退到仅支持 v1 的代码会略过 v2，不能因此删除或当作坏文件修复；恢复新代码可继续读取。
