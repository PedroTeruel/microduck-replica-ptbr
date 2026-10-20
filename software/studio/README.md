# Microduck Studio

装在鸭子上的网页中控。电脑或手机浏览器打开 `http://<鸭子 IP>:8000/` 就能看鸭子现在的状态、一键卸力，也能站立/走路、配对蓝牙手柄（走官方 `robotctl pad pair`）、标定舵机、校准 IMU 方向、把这两样和方向一次写进主程序，按「上手清单」做装机检查。鸭子开热点等配网时，还能用手机选家里的 WiFi、填密码。

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
  state.py          把原始数据汇总成推给页面的状态（姿势、电量、舵机、IMU、手柄、待办、配网）
  net.py            配网：读 netcheck 的 net.json、configd 的 net.status / scan / connect / forget、开关热点
  app.py            网页服务：静态文件、登录、日志、诊断包、WebSocket
web/                页面（Preact + htm，three.js 画 3D 鸭子；全部本地文件，不走 CDN；wifi.js 是连 WiFi 卡片和设置）
deps/               钉死版本的 Python 依赖（starlette、uvicorn 等，见 deps/VERSIONS.txt）
dev/
  record_robotd.py  在鸭子上只读录一份 robotd 的真实回包（给假 robotd 和测试用）
  fake_robotd.py    假 robotd + 假 configd：回放录的数据，电脑上不接鸭子也能跑
tests/              单元测试 + 真机录的数据 fixtures/now-20261018.jsonl
```

## 在电脑上跑（不接鸭子）

需要 Python 3.13（跟板子一样；Windows 上是 `py -3.13`）。

```bash
py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl \
    --net-mode hotspot --net-state-file ./state-dev/net.json   # 假 robotd + 假热点配网，听 17001/17002
py -3.13 -I run.py --listen 127.0.0.1:18080 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002 \
    --net-state ./state-dev/net.json --dev-autologin --state-dir ./state-dev --log-dir ./logs-dev
```

浏览器开 `http://127.0.0.1:18080/`。`--dev-autologin` 只认本机请求、只能配 `127.0.0.1`，方便截图测试；鸭子上不要用。
假 robotd 可以用 `--mode commissioning|motion` 选主程序模式（出厂场景是 `--mode commissioning --calib factory`），用 `--posture limp|policy|commissioning|starting` 换姿势；`--net-mode hotspot|wifi|none` 写一份假 net.json。
不给 `--net-state` 时读 `/run/microduck/net.json`；文件不在（电脑上、老镜像）就不显示 WiFi。不给 `--duck-label` 时，界面用主机名（鸭子上是 `duck-xxxx`）。

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
3. 装 root 小助手：`cd deploy && sudo sh install.sh radxa`。0.5.1 的小助手负责舵机总线交接、手柄配对、热点开关，以及 `calib-read` / `calib-commit`（把标定写进主程序、切运动模式）；关热点前会写 `/run/microduck/studio-connecting.json`，让 netcheck 在连接期间别插手。步骤、卸载和上机核对见 `deploy/INSTALL.md`。
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

出厂镜像让 robotd 跑标定模式：`/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf` 里 `ExecStart` 带 `--commissioning`。这样 `calibration-status` 和 `busStatus.last_sample` 马上能读，IMU 页粗校、舵机页中位都能做。上手清单第 3 步写成功后，小助手删掉这个文件、`daemon-reload`、重启 robotd，主程序回到运动模式。`systemctl show robotd -p ExecStart` 里有 `--commissioning`、但那个文件不在时，小助手拒绝自动切（`foreign_commissioning`），去日志页导出诊断包。

电池用台架电源供电时，在「设置 → 电池」里把型号选成「台架电源」：只显示电压，不算电量、也不报电量。
Studio 默认没有密码，同一网络里谁都能打开。在「更多 → 登录密码」里可以直接设置；设过以后要先登录才能改，也可以清掉。命令行 `python3 -I run.py set-password` 仍然可用，但要用 radxa 用户运行，别加 `sudo`（root 写的密码文件 Studio 读不了）。

## 镜像里 vs 手动装

「连 WiFi」卡片依赖复刻镜像里的几样东西，不是 Studio 自己带的：

- netcheck 写的配网状态 `/run/microduck/net.json`；
- NetworkManager 里的 `Microduck-Hotspot` 热点配置；
- configd 以 `--allow-user btd,radxa` 运行，Studio 才有权限调 `net.scan` / `net.connect` / `net.forget`；
- mDNS 配置，手机才能用 `duck-xxxx.local` 找到鸭子。

按 `deploy/INSTALL.md` 手动装 Studio 和 root 小助手、但没有复刻镜像 overlay 的鸭子，没有这几样，页面就不显示「连 WiFi」卡片；总览、手柄、舵机、IMU、日志这些照常使用。

## 页面和 Studio 之间的约定（WebSocket `/ws`）

握手时检查 Host 和 Origin，不对就拒绝握手（浏览器只看到 1006，日志里写原因）；没登录的先接受再用 4401 关掉，页面看到 4401 就跳登录页。

| 方向 | 消息 | 说明 |
|---|---|---|
| Studio → 页面 | `{"t":"hello","version","duck"}` | 连上先发一次 |
| | `{"t":"state", …}` | 页面可见时 10 Hz；字段见 `studio/state.py` 的 `summarize` |
| | `{"t":"hb"}` | 页面在后台时 1 Hz（这时不订阅 robotd 的实时状态，省 CPU） |
| | `{"t":"log","entry":{…}}` | 新日志 |
| | `{"t":"result","id","ok","reason","data"}` | 命令回执；扫 WiFi 的网络列表等数据放在 `data` |
| | `{"t":"pad", …}` | 手柄快照：手柄那一块在屏幕上时 10 Hz，不在 1 Hz（总览的手柄格要用）；长列表没变时带 `lists_same`、不带列表 |
| 页面 → Studio | `{"t":"hb","seq","visible","route","pad_visible"}` | 每秒一次；进出手柄区那一刻马上再发一次。`pad_visible` = 手柄那一块在屏幕上（#/pad 只是总览上的锚点） |
| | `{"t":"cmd","id","name","args"}` | relax、servo.*、imu.op、calib.op（`preview` / `commit`：上手清单第 3 步）、pad.op、onboard.op（上手清单的「已经校过，核对一下」、跳过、取消跳过）、net.op（`scan` / `connect` / `forget`） |

舵机会话在 `state` 里的几个字段（每一页顶上的提示条用）：`servo_session`（开着才有：`holding` 几颗保持着、`unknown` 几颗读不到扭矩、
`restored` 是不是 Studio 重启后接着管的）、`servo_handback_s`（交还以后、主程序连上以前一直有）、`servo_orphan`（上次退出时开着、这次没接管上）、
`servo_conflict_s`（会话期间 robotd 被手动起来了，10 分钟内）。`servo.close {if_idle:true}`（离开舵机页）只在 15 颗扭矩当场读到都是 0、
没有别的页面在舵机页、没在校准 / 运动时才交还；`servo.close {}`（点「交还主程序」）先等在路上的舵机操作做完再卸力交还。

`state.net` 是配网状态：`known=false` 表示没有 net.json（整块 WiFi 隐藏）；否则有 `mode`（wifi / hotspot / none）、当前 `ssid` / `signal` / `ip4`、`hostname`、
`url_local`（端口跟 `--listen` 一致）、鸭子热点 `hotspot {ssid, ip, psk}`、上次结果 `last_try`、`busy`。`net.op connect` 先回「开始切换」，真正关热点、调 configd 在后台做；
结果写到 state 目录的 `net-last-try.json`（不含密码）。家里的 WiFi 密码只从页面传到 configd 一次，不进日志、state 或诊断包。

已保存的加密网络也要每次填密码：官方 configd 遇到加密网络、没给密码就回 `unsupported`。密码错了会先 `net.forget` 掉这次写坏的配置，再马上开回热点；
`timeout`、`other`、Studio 自己等 configd 超时，也会马上开回热点。Studio 等 60 秒没回话单独记「鸭子的配网程序 60 秒没回话」，不跟 configd 的 `timeout` 混在一起。
小助手关热点前写 `/run/microduck/studio-connecting.json`（90 秒内 netcheck 不插手），开热点成功后删掉。

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
- 卸力：不被慢查询挡住、回读确认、hd1910 标志没清不算确认、标定模式、robotd 重启后第一次就成功、确认后别人再上力不会自动补发；
- 轮询：一项出错不挡别的项；只在有人看时订阅，没心跳当没人看；robotd 掉线又回来；
- 姿势判定（用真机录的数据）；通过 WebSocket 发卸力的完整来回；
- 手柄配对：小助手 `pad-pair` / `pad-forget` 的参数校验、robotctl 成功 / 失败 / 超时解析；向导的主路、旧小助手回退、bluetoothctl 代理注册失败重试、padd 30 秒等待。
- 配网：小助手热点动词、连接窗口文件；net.json 缺失 / 损坏 / 各模式；扫描缓存；连接顺序、失败原因（bad_key 先 forget 再开热点）、热点恢复、同时只连一个；密码不进日志 / state / last-try / 诊断包。
- 登录密码：网页首次设置、登录后才改、清掉；改密码保留当前浏览器会话；root 运行 `set-password` 被拒；热点模式且没密码时的卡片提示。
- 写进主程序：小助手 `calib-read` 只读 / 不拿锁、`calib-commit` 先拿锁再查旗、标定模式删 drop-in 后切运动模式、`mode=motion` + `phase=control` + `calibration-status` 逐项读回一致才算成功、`waiting_for_bus` 的标定错误 / 总线错误分开报、读回不一致 / `.saved.toml` 写失败 / 重启失败都回滚（文件和模式分开报，回滚后起不来如实写）、策略在跑拒绝、`ExecStart` 里有 `--commissioning` 但 drop-in 不在拒绝、备份按序号留 10 组；Studio 两种模式的准备情况、`calib-read` 兜底、超时读 `last-result.json`、pending / centered 变化让第 3 步变「该做」、撤销中位校准删记录；两份组 TOML 代码输出一致。

## 现状（第一版）

能用的：
- **总览**：实时状态、3D 鸭子、电池、主板温度、一键卸力（空格也行）。
- **舵机页**：扫描、单颗或全部中位校准（直接写进舵机）、方向、姿势、P/D/限力。
- **IMU 页**：出厂标定模式下粗校（托起摆正 + 往前低头，交给主程序 `verify-imu` 自己验），能站以后站着精校。
- **写进主程序**：上手清单第 3 步把舵机零位、方向、IMU 方向一次写进 robotd 的标定。出厂镜像是标定模式；写成功后小助手删掉 commissioning drop-in、重启主程序切运动模式。成功不只看重启：还要 `mode=motion`、`phase=control`，并且 `calibration-status` 读回逐项一致；不成就把文件和模式换回去。Studio 重启后会读 `last-result.json` 把上次结果放回第 3 步卡片。
- **手柄**：配对（走官方 `robotctl pad pair`）、网页手柄、测急停。
- **遥控**：站起来 / 开始走 / 坐下、技能、动作和组合动作。
- **调手感、模型**：只看。
- **日志**：日志页和诊断包；手机底栏从「更多」也能进日志、导出诊断包。
- **连 WiFi**：鸭子开热点时用手机选家里的 WiFi、填密码；设置里能看当前网络、换网、忘掉已保存的网络。
- **登录密码**：在「更多 → 登录密码」设置、修改或清掉；热点模式又没密码时，总览的连 WiFi 卡片会提示先设密码。

还不能的（下一版）：
- 在网页上**改**调手感参数（走路幅度、平滑、P/D/限力）。

## 参考

本项目基于官方开源的 Microduck，开发中参考了社区多个开源项目的思路；代码由我们自己编写，开发中使用了 AI 辅助编程。

## 许可

Apache-2.0（跟仓库一致）。`web/vendor/` 下的 Preact、htm、three.js 都是 MIT，许可证在 `web/vendor/licenses/`；3D 模型的来源见 `web/model/NOTICE.md`；`deps/` 下各包的许可证在各自的 dist-info 里。
