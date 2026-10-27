# 网页录制回放与灵动：实现及单机部署验收

日期：2026-10-25（东京时间；设备日志为 +08:00）。用户授权“开始吧……灵动……先做在网页版里头”，随后明确选择鸭子现有控制网址。

## 本轮结果与范围

运行代码提交：`c18783c9a2b2e2635124c6c4d53007e3fefb3ba6`，已快进合入 `studio-dev`。原有未提交的路线/语音记录保留，没有重置工作区或改动语音源码。

现有遥控区新增录制、暂停/继续、结束/命名保存、草稿丢弃、选择回放 1/3/5 次、暂停/继续/停止、改名/删除。旧舵机页灵动风格改为通过正常 `robot.head`/`robot.mouth` 意图输出，可单独开启或在录制中开启；生成后的目标被记录，回放不再随机生成。

首版每段 60 秒/6,000 事件/1 MiB，最多 20 段。内容保存在 Studio state 的 `motion-recordings/`，刷新与重启后保留。录制只包含被接受的网页移动、头/身体/嘴和已知声音，不含麦克风音频、摄像头视频、站坐/上力、设置或模型技能。缺少可靠技能完成回读，因此录制时在发送前拒绝踢腿、翻滚、捡取等技能；不把“停止发指令”当作物理技能已停止。

录制/灵动/回放要求现有策略就绪、状态新鲜、无实体手柄冲突，且不自动站起或使能。每会话独立令牌，100ms 心跳、500ms 失效；退出控制区、后台/失焦、断网、接管、手柄连接、卸力和状态变化会停止，重连不续播。暂停清除连续目标；继续恢复头/身体/嘴姿态，速度等待后续有效帧。迟到目标合并，不集中补发过时运动。模型文件内容/配置指纹不匹配拒绝旧记录。

## 软件验证

最终通过 **351 项软件检查**：203 项动作/原手柄后端（44 + 159）、140 项 HTTP/原虚拟手柄/总览/传感器回归、7 项 Node 心跳测试、1 项新动作浏览器端到端测试。独立需求及代码审查的问题均有复现测试并修复，最终审查无待处理发现。

在 `software/studio` 运行（Windows Python 3.13，运行时依赖使用现有 `deps/`）：

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio','tests.test_pad'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

浏览器测试使用真实 Studio、fake robotd 和 Edge，走通灵动录制、暂停/继续、命名保存、回放暂停/继续/停止、3 次有限循环、改名、刷新保留、切页停止和删除。实际发出的有效动作帧：录制 30、普通回放 18、三轮回放 82，见到轮次 `[1,2,3]`，控制台错误 `[]`。回放会合并迟到连续帧，所以不要求每个过时样本都补发。桌面 1440px、手机 390/320px 截图已人工检查；最终集成到 `studio-dev` 后又通过 44 项动作测试。

证据在工作区 `artifacts/web-motion-20261025/`：`backend-final.log`、`regression.log`、`browser-final2/browser.json` 和 `browser-final2/shots/`。最终 203 与 140 项均为 OK。更早一轮原配对测试在 Windows 删除临时日志时遇到文件占用；其断言完成，单项连续 5 次及最终整套均通过。保留说明，不把既有 teardown 资源竞争报成新的配对修复。

## duck-0de6 部署回读

部署目标为用户选择的 `http://duck-0de6:8000/#/pad`。先用冻结 Git 字节比较设备文件，确认依赖版本一致、安装路径无越界或符号链接、Python 能编译；即时回读 `motion/control`、`policy_enabled=false`，没有舵机会话标记，才切换程序。

更新 12 个文件：

```text
studio/motion_store.py       studio/motion_studio.py
studio/pad.py                studio/pad_drive.py
web/app.js                  web/pad.js
web/pad.css                 web/sensors.js
web/sensors.css              web/motion-heartbeat.js
web/motion-studio.js         web/motion-studio.css
```

其中 app/sensors/pad 的匹配资源包含此前本地内联摄像头及配对恢复版本，避免仅替换入口文件导致依赖不完整。未启用真实摄像头，未改网络、模型、主程序、padd、蓝牙或语音服务。

仅停止并重新启动 `microduck-studio`，PID 从 980 变为 15333，当前 active。部署前后 `robotd=1105`、`padd=1138`、`duck-echo=1110` 及各自单调启动时间相同，三个服务均 active，语音 enabled。安装的 12 个文件均与清单 SHA-256 一致。

`/`、`/healthz`、`/pad.js` 及三个新静态文件均返回 HTTP 200；服务的 JS/CSS 字节哈希与安装文件一致，静态资源 `Cache-Control: no-cache`。日志显示 Studio 正常连上接口 v40 主程序，无本次启动异常。原有 11 个用户数据文件与停止服务时备份逐字节一致。

该设备现有网页登录保护，未经登录 `/api/session` 为 401；没有修改或绕过认证来取动作快照。应用打开控制页的请求为 queued，现有 Edge 最小化，因而不声称已经在真实登录页面看见入口或完成动作试验。已向用户发出刷新/登录及灵动试用问题；**真机动作效果仍待用户确认**。本轮未主动发送站起、行走、灵动或回放指令给真实鸭子。

私有备份：`/home/radxa/.microduck-backups/web-motion-20261025-e6610b5e21`，目录权限 0700，含更新前运行文件、用户 state、清单及成功回执。本地 `artifacts/web-motion-20261025/device-before/full-runtime/` 保存更新前相关程序，`deployment-manifest.json`、`deployment-result.json`、`device-verification.json` 保存完整核对结果；不纳入公开包。

单机切换脚本在安装/服务健康检查失败时会恢复旧文件并重启 Studio。本次未触发失败回退；自动回退分支未做真机故障注入，不能称为已验证的通用 OTA 回退。人工恢复时先确保鸭子停止、没有舵机会话，再停止 Studio；按备份清单恢复原文件，删除清单中此前不存在的新文件，仅重新启动 Studio 并验证 HTTP。原 state 保留；备份内用户 state 仅作损坏恢复，不覆盖后来新保存的录制。

## 冻结交付与后续

本地交付目录：工作区 `artifacts/web-motion-20261025/release/`，包含按 Git 提交生成的 Studio 源码归档、版本/哈希清单和本验收副本。包不含设备 state、个人密码、SSH 钥匙、家庭 Wi-Fi、配对或录制数据；它是维护与后续组件发布的可追溯输入，尚不是网页一键升级器。

没有新建镜像、启用 updaterd 或发布到远端。现有镜像仍保持原版本。下一步先完成用户动作试用，再把语音和 Studio 整理成统一版本组件，设计通用安装/迁移/回退与新卡/旧系统两条验收；手柄/语音绑定保存回放仍是后续需求。

## 用户截图后的状态判断修正

用户随后提供了真实网页截图，确认已出现“动作录制与回放”及“灵动”入口；按钮灰色，站姿是“站着（保持）”，却仍提示“上个模型技能没有可验证的完成状态，先手动停下策略”。日志显示用户已经执行过坐/站及“停下（站好）”。

只读回读发现：`robot.policies.enabled=true`、`homed=true`、`sitting=false`，而 `robot.busStatus.policy_enabled=false`、`mode=motion`、`phase=control`、`homed=true`。主程序源码明确前者来自启动配置 `[policy] enabled`，不是运行开关。首版 `policy_feed` 错误地要求配置开关与运行开关同时为 false，导致真实机器停止策略后仍无法记录停止边界。原测试人为把两个开关同时置 false，未覆盖真机的配置保持 true 情况。

修正提交：`db970dd470f7cc1586b1ce3a4ed6a2792b1f71ce`。改用新鲜 `bus.policy_enabled=false` 确认实际停下；此后仍须观察运行开关 true、配置允许、双方 homed 及既有就绪条件，成功的 RPC 回执不单独解除阻塞。确认停下后的提示改成“点击上方「开始走」，等新鲜回读确认「准备好走」”。没有删除技能屏障或放宽普通开始动作的状态要求。

新增两项后端回归：配置持续启用时，停止→重新启用→新鲜就绪可恢复录制/灵动；只有配置禁用、运行开关仍开不能代替停止证据。测试先重现失败，再通过修改；最终 **205 项动作/原手柄后端通过**，独立审查也重跑 205 项通过且无待处理发现。浏览器额外走通“模型技能→停止站好→灰色且提示开始走→开始走→按钮恢复”，再执行完整录制回放/保存/切页流程；1 项浏览器测试通过，`skill_gate_recovered=true`、控制台错误 `[]`、1440/390/320px 均通过。首轮的 140 项其他回归和 7 项 Node 测试没有在本次窄修正后重跑，不将它们宣称为新版本全量重测。

已通过 SSH 部署 db970dd，仅更新 `studio/motion_studio.py`，仅重启 Studio（15333→21540）。原机器人、手柄和语音进程仍为 1105/1138/1110，启动时间保持一致；四个服务 active，语音 enabled。安装文件 SHA-256 为 `966c16c1f833baef6d314af899a0ad166a9c0ef8bda0ea2f60b9a015dd4f676b`，HTTP 与静态资源检查通过，原有 12 个用户数据文件逐字节保持。

本次私有备份为 `/home/radxa/.microduck-backups/web-motion-20261025-8ac5417e9b`（0700）。设备读取证据在工作区 `artifacts/web-motion-20261025/live-skill-gate-readback.json`，浏览器证据在同目录 `skill-gate-browser/`；单机更新清单、成功回执、服务/文件回读及新的冻结源码交付在 `artifacts/web-motion-20261025-skill-gate/`，原首轮记录保留。

已告知用户刷新、点“开始走”、等待“准备好走”再开启“灵动”。网页入口已由用户截图确认，修正后的真实头嘴动作效果仍待用户回复；没有由本轮脚本主动发出运动指令，没有更新镜像或启用通用在线升级。
