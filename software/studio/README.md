# Microduck Studio

装在鸭子上的网页中控。电脑或手机浏览器打开 `http://<鸭子 IP>:8000/` 就能看鸭子现在的状态、一键卸力，也能站立/走路、配对蓝牙手柄（走官方 `robotctl pad pair`）、标定舵机、校准 IMU 方向，按「上手清单」做装机检查。

## 它做什么、不做什么

- 平时跟鸭子主程序 robotd 说话（`/run/robotd.sock`，接口 v40）；舵机页要直接调舵机，先让 robotd 交出总线，用完再交还。
- 页面上的一切状态都来自 robotd 的回读：比如「已卸力 ✓」要等 busStatus 里扭矩确认关了才显示，不是「按过了」就算。
- 停掉 Studio 不影响鸭子；停掉 robotd **不会**让舵机卸力（舵机保持最后的指令），页面会提示。
- **Studio 退出不卸力**：舵机页的总线会话开着时 Studio 退出（重启、升级），只关串口，保持着的舵机照样保持。
  开总线时在 state 目录写 `servo-session.json`（串口、开始时间、谁开的），点「交还主程序」成功才删；Studio 起来时见到它、
  robotd 又不在，就自动重新接管总线（只读打开，不改扭矩），每一页顶上的提示条照旧；接管不上，提示条写
  「上次退出时可能还有舵机保持着，去舵机页接管后才能卸力」，顶上的卸力按钮带你去舵机页。robotd 在：它起来时已经全部松开，删掉标记。
- 舵机会话期间每 5 秒看一眼 robotd 的 socket：被手动起来了（它会把舵机全部松开、跟 Studio 抢串口）就记错误、Studio 关总线（不写舵机），
  提示条变红。要回主程序，点「交还主程序」，别手动 `systemctl start robotd`。

## 目录

```
run.py              启动入口（python3 -I run.py …）：把 deps/ 放进搜索路径再进 studio
run_tests.py        跑全部测试
studio/
  log.py            日志：分类、分级、毫秒时间、去重、脱敏、按天滚动；命令记「发出 → 回执 · 耗时」
  auth.py           管理员密码（scrypt）、登录会话、失败退避、Host/Origin 校验
  rpc.py            robotd/configd 的 JSON-RPC 连接（一条连接一次一个请求）
  robotd.py         连接：轮询 / 实时状态流 / 命令 / configd 各一条常驻；卸力每次新开一条（robotd 重启后不会撞上死连接）
  estop.py          卸力状态机：ready → pending → confirmed / unavailable；只认「卸力回执之后才发出的」回读
  state.py          把原始数据汇总成推给页面的状态（姿势、电量、舵机、IMU、手柄、待办）
  app.py            网页服务：静态文件、登录、日志、诊断包、WebSocket
web/                页面（Preact + htm，three.js 画 3D 鸭子；全部本地文件，不走 CDN）
deps/               钉死版本的 Python 依赖（starlette、uvicorn 等，见 deps/VERSIONS.txt）
dev/
  record_robotd.py  在鸭子上只读录一份 robotd 的真实回包（给假 robotd 和测试用）
  fake_robotd.py    假 robotd + 假 configd：回放录的数据，电脑上不接鸭子也能跑
tests/              单元测试 + 真机录的数据 fixtures/now-20261018.jsonl
```

## 在电脑上跑（不接鸭子）

需要 Python 3.13（跟板子一样；Windows 上是 `py -3.13`）。

```bash
py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl   # 假 robotd，听 17001/17002
py -3.13 -I run.py --listen 127.0.0.1:18080 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002 \
    --duck-label "② 二号鸭" --dev-autologin --state-dir ./state-dev --log-dir ./logs-dev
```

浏览器开 `http://127.0.0.1:18080/`。`--dev-autologin` 只认本机请求、只能配 `127.0.0.1`，方便截图测试；鸭子上不要用。
假 robotd 可以用 `--posture limp|policy|commissioning|starting` 换姿势。

Windows 的 Python 没有 Unix socket，所以地址写成 `tcp:主机:端口`；鸭子上是 `unix:/run/robotd.sock`（默认）。

## 台架模式：主控没烧，用飞特调试板在电脑上调舵机

把飞特调试板（或 USB 转 TTL）插到电脑上，接好舵机和电源，然后：

```bash
py -3.13 -I run.py --bench
```

它不连主程序，自动打开浏览器进「舵机」页；在页头的「串口」下拉里选 COM 口，点「连接」就能调（跟 servo-web 一样）。
没接硬件想先看看：串口选「演示（没接舵机）」，Studio 在软件里假装有 15 颗舵机。

## 装到鸭子上

1. 拷贝：把 `software/studio` 整个目录拷到鸭子的 `/home/radxa/studio-dev`（`scp -r`、U 盘解压包都行）。
2. 自检：在鸭子上运行 `python3 -I run.py --selfcheck`（只读：打印版本，对 robotd / configd / padd 各问一次）。
3. 装 root 小助手：`cd deploy && sudo sh install.sh radxa`。它负责舵机总线交接和手柄配对，步骤、卸载和上机核对见 `deploy/INSTALL.md`。
4. 开机服务：照 `deploy/microduck-studio.service` 文件头的命令装：

   ```bash
   sudo install -m 644 microduck-studio.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now microduck-studio
   ```

   撤：

   ```bash
   sudo systemctl disable --now microduck-studio && sudo rm /etc/systemd/system/microduck-studio.service && sudo systemctl daemon-reload
   ```

5. 打开 `http://<鸭子 IP>:8000/`，按页面上的「上手清单」走。

手柄配对的主路是 root 小助手调官方 `/usr/local/bin/robotctl pad pair --json`：`/var/lib/robot/weird-ble` 板上它会先停 `btd`、给蓝牙适配器断电再开，配完把 `btd` 起回来。没装或旧版小助手时退回 configd → bluetoothctl；这块板这样可能配不上，向导会提示重装小助手，或者在鸭子上运行 `sudo robotctl pad pair`。

电池用台架电源供电时，在「设置 → 电池」里把型号选成「台架电源」：只显示电压，不算电量、也不报电量。
Studio 默认没有密码，同一网络里谁都能打开；想加密码就运行 `python3 -I run.py set-password`。

## 页面和 Studio 之间的约定（WebSocket `/ws`）

握手时检查 Host 和 Origin，不对就拒绝握手（浏览器只看到 1006，日志里写原因）；没登录的先接受再用 4401 关掉，页面看到 4401 就跳登录页。

| 方向 | 消息 | 说明 |
|---|---|---|
| Studio → 页面 | `{"t":"hello","version","duck"}` | 连上先发一次 |
| | `{"t":"state", …}` | 页面可见时 10 Hz；字段见 `studio/state.py` 的 `summarize` |
| | `{"t":"hb"}` | 页面在后台时 1 Hz（这时不订阅 robotd 的实时状态，省 CPU） |
| | `{"t":"log","entry":{…}}` | 新日志 |
| | `{"t":"result","id","ok","reason"}` | 命令回执 |
| | `{"t":"pad", …}` | 手柄快照：手柄那一块在屏幕上时 10 Hz，不在 1 Hz（总览的手柄格要用）；长列表没变时带 `lists_same`、不带列表 |
| 页面 → Studio | `{"t":"hb","seq","visible","route","pad_visible"}` | 每秒一次；进出手柄区那一刻马上再发一次。`pad_visible` = 手柄那一块在屏幕上（#/pad 只是总览上的锚点） |
| | `{"t":"cmd","id","name","args"}` | relax、servo.*、imu.op、pad.op、onboard.op（上手清单的「已经校过，核对一下」、跳过、取消跳过） |

舵机会话在 `state` 里的几个字段（每一页顶上的提示条用）：`servo_session`（开着才有：`holding` 几颗保持着、`unknown` 几颗读不到扭矩、
`restored` 是不是 Studio 重启后接着管的）、`servo_handback_s`（交还以后、主程序连上以前一直有）、`servo_orphan`（上次退出时开着、这次没接管上）、
`servo_conflict_s`（会话期间 robotd 被手动起来了，10 分钟内）。`servo.close {if_idle:true}`（离开舵机页）只在 15 颗扭矩当场读到都是 0、
没有别的页面在舵机页、没在校准 / 运动时才交还；`servo.close {}`（点「交还主程序」）先等在路上的舵机操作做完再卸力交还。

页面判断「连不上」只看收到消息的间隔（1 秒变灰、3 秒报警），不看两边的钟（鸭子的钟可能是 1970 年）。

## 日志

`logs/studio-YYYY-MM-DD.log`，留 14 天、总共不超过 50 MB。一行一件事：

```
2026-10-18T00:41:56.194+09:00 [命令] → 卸力（电脑 127.0.0.1） · 步骤：robot.relax
2026-10-18T00:41:56.197+09:00 [命令] ← 卸力 成功 · 3 ms · 已发出，等回读确认 · 步骤：robot.relax · 原文：{"accepted": true}
```

出错时写明「卡在：哪一步 · 原文：… · 建议：… · 现场：{…}」。密码、令牌自动打码。同一句话 1 分钟内重复只记一次，并注明合并了几次。
页面「日志」页能看最近 500 条，也能导出诊断包（日志 + 当时的状态 + robotd 原始回包 + 版本 + robotd 的系统日志），发群里求助用。

日志里每条命令都记发出和回执、带耗时和现场，代码是我们自己写的。

## 测试

```bash
py -3.13 -I run_tests.py               # 电脑
python3 -I run_tests.py                # 鸭子
```

覆盖：
- 登录：会话、密码错 5 次退避、退出要 CSRF；Host 421、Origin 矩阵；没登录的 WebSocket 收到 4401；
- 日志：格式、脱敏、去重、按天清理（钟停在 1970 也能清）；
- JSON-RPC：半行、超长行、乱码和非对象 JSON、超时重连；
- 卸力：不被慢查询挡住、回读确认、hd1910 标志没清不算确认、调试模式、robotd 重启后第一次就成功、确认后别人再上力不会自动补发；
- 轮询：一项出错不挡别的项；只在有人看时订阅，没心跳当没人看；robotd 掉线又回来；
- 姿势判定（用真机录的数据）；通过 WebSocket 发卸力的完整来回；
- 手柄配对：小助手 `pad-pair` / `pad-forget` 的参数校验、robotctl 成功 / 失败 / 超时解析；向导的主路、旧小助手回退、bluetoothctl 代理注册失败重试、padd 30 秒等待。

## 现状（第一版）

能用的：
- **总览**：实时状态、3D 鸭子、电池、主板温度、一键卸力（空格也行）。
- **舵机页**：扫描、单颗或全部中位校准（直接写进舵机）、方向、姿势、P/D/限力。
- **IMU 页**：摆两个姿势，算出 IMU 的安装方向。
- **手柄**：配对（走官方 `robotctl pad pair`）、网页手柄、测急停。
- **遥控**：站起来 / 开始走 / 坐下、技能、动作和组合动作。
- **调手感、模型**：只看。
- **日志**：日志页和诊断包。

还不能的（下一版）：
- 把舵机零位 / 方向、IMU 方向**写进主程序的标定**。现在只能算出来，写进去要另外动手。下一版在上手清单最后加一步「写进主程序」，写一次永久生效。
- 在网页上**改**调手感参数（走路幅度、平滑、P/D/限力）。
- 开机配网（随镜像一起做）。

## 参考

本项目基于官方开源的 Microduck，开发中参考了社区多个开源项目的思路；代码由我们自己编写，开发中使用了 AI 辅助编程。

## 许可

Apache-2.0（跟仓库一致）。`web/vendor/` 下的 Preact、htm、three.js 都是 MIT，许可证在 `web/vendor/licenses/`；3D 模型的来源见 `web/model/NOTICE.md`；`deps/` 下各包的许可证在各自的 dist-info 里。
