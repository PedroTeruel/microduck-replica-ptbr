# Microduck Studio

装在鸭子上的网页中控。电脑或手机浏览器打开 `http://<鸭子 IP>:8000/` 就能看鸭子现在的状态、一键卸力，也能站立/走路、配对蓝牙手柄（走官方 `robotctl pad pair`）、标定舵机、校准 IMU 方向、把这两样和方向一次写进主程序，按「上手清单」做装机检查。鸭子开热点等配网时，还能用手机选家里的 WiFi、填密码。

## 它做什么、不做什么

- 平时跟鸭子主程序 robotd 说话（`/run/robotd.sock`，接口 v40）；舵机页要直接调舵机，先让 robotd 交出总线，用完再交还。
- PáginaSuperior de 一切状态都来自 robotd  de 回读：比如「已卸力 ✓」要等 busStatus 里扭矩确认关了才显示，不是「按过了」就算。
- 停掉 Studio 不影响鸭子；停掉 robotd **不会**让Servo卸力（Servo保持最后 de 指令），Página会提示。
- **Studio 退出不卸力**：Servo页 de 总线会话开着时 Studio 退出（重启、升级），只关串口，保持着 de Servo照样保持。
  开总线时在 state 目录写 `servo-session.json`（串口、开始时间、谁开的），点「交还主程序」成功才删；Studio 起来时见到它、
  robotd 又不在，就自动重新接管总线（只读打开，不改扭矩），每一页顶Superior de 提示条照旧；接管不Superior，提示条写
  「Superior次退出时可能还有Servo保持着，去Servo页接管后才能卸力」，顶Superior de 卸力按钮带你去Servo页。robotd 在：它起来时已经全部松开，删掉标记。
- Servo会话期间每 5 秒看一眼 robotd  de  socket：被手动起来了（它会把Servo全部松开、跟 Studio 抢串口）就记错误、Studio 关总线（不写Servo），
  提示条变红。要回主程序，点「交还主程序」，别手动 `systemctl start robotd`。

## Diretório

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
  models.py         模型库、默认恢复、实际切换回读、手柄改键
  model_package.py  模型部署包解析与 robotd 无硬件预检
  sensors.py        摄像头来源配置与 ToF 按需快照（独立于运动控制）
  net.py            配网：读 netcheck 的 net.json、configd 的 net.status / scan / connect / forget、开关热点
  app.py            网页服务：静态文件、登录、日志、诊断包、WebSocket
web/                页面（Preact + htm，three.js 画 3D 鸭子；全部本地文件，不走 CDN；wifi.js 是连 WiFi 卡片和设置；
                    probe.svg 是连 WiFi 以后找鸭子新地址用的小图）
deps/               钉死版本的 Python 依赖（starlette、uvicorn 等，见 deps/VERSIONS.txt）
dev/
  record_robotd.py  在鸭子上只读录一份 robotd 的真实回包（给假 robotd 和测试用）
  fake_robotd.py    假 robotd + 假 configd：回放录的数据，电脑上不接鸭子也能跑
tests/              单元测试 + 真机录的数据 fixtures/now-20261018.jsonl
```

## 在电脑Superior跑（不接鸭子）

需要 Python 3.13（跟板子一样；Windows 上是 `py -3.13`）。

```bash
py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl \
    --net-mode hotspot --net-state-file ./state-dev/net.json   # 假 robotd + 假热点配网，听 17001/17002
py -3.13 -I run.py --listen 127.0.0.1:18080 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002 \
    --net-state ./state-dev/net.json --dev-autologin --state-dir ./state-dev --log-dir ./logs-dev
```

浏览器开 `http://127.0.0.1:18080/`。`--dev-autologin` 只认本机请求、只能配 `127.0.0.1`，方便截图测试；鸭子上不要用。
假 robotd 可以用 `--mode commissioning|motion` 选主程序模式（出厂场景是 `--mode commissioning --calib factory`），用 `--posture limp|policy|commissioning|starting` 换姿势；`--net-mode hotspot|wifi|none` 写一份假 net.json。
标定模式照 fork 的真实行为：起来后先回启动报告（`phase=configuring_bus`），第一次读成功才回实时快照；`--commissioning-stuck-status` 模拟旧 fork（启动报告永远不清，Studio 一直看到「启动中」）。
不给 `--net-state` 时读 `/run/microduck/net.json`；文件不在（电脑上、老镜像）就不显示 WiFi。不给 `--duck-label` 时，界面用主机名（鸭子上是 `duck-xxxx`）。

Windows 的 Python 没有 Unix socket，所以地址写成 `tcp:主机:端口`；鸭子上是 `unix:/run/robotd.sock`（默认）。

## 摄像头e ToF

Esquerdo侧「手柄」之后是「摄像头」「ToF」两个独立Página，手机底栏也有入口。

总览／手柄页的状态栏依次显示电池、舵机、IMU、摄像头、ToF、手柄、主板。摄像头仅通过本机 mediad socket 的只读 `hello` 判断“服务在线”，不把配置文件或测试画面当作真实摄像头已连接；点开页面才能查看实际视频。ToF 根据新帧显示在线，fake/sim 明确标为模拟数据。状态栏每10秒检查一次，切页或后台取消，过期状态清空；检查不会请求视频帧、建立 WebRTC 或启动系统服务。

当前镜像尚无“开机自动识别摄像头／ToF 硬件，再按检测结果启停服务”的统一策略。firstboot 的自动识别针对 IMU；镜像默认 `media.source="test"` 避免缺摄像头反复崩溃，但媒体服务仍可能运行。网页未连接可能是网络或服务问题，不能直接据此认定没装硬件并关闭服务。

总览往Inferior滑到手柄区，Esquerdo侧 3D 鸭子abaixo有摄像头预览，Direito侧Preservado手柄 e 遥控。桌面Esquerdo栏整体吸顶，按可用高度安排姿态e视频，空间不足时随Página滚动；手机Superior按手柄图、3D、摄像头、遥控 de 顺序排列。只有预览卡在屏幕内、总览可见，且只读Verificação报告Configuração为摄像头、视频Serviço在线时，才自动接入既有 WebRTC 视频。Teste源、未知FonteeServiço离线显示占位，每10秒重新Verificação，不自动播放Teste图案。切页、滚出卡片或进入后台会取消Leitura并释放视频Conexão；独立摄像头页仍可主动播放Teste源。该布局复用同一套视频客户端，不Inicialização系统Serviço，也不等于已实现摄像头Hardware热插拔自动Configuração。

- **摄像头**：接现有 mediad  de 局域网 WebRTC 视频（默认信令端口 8443），pode开始、停止e重新Conexão。Página等实际画面开始Atualização才显示播放；切走或进入后台会释放Conexão。只Leitura视频 e 画面元Dados，不打开电脑/手机摄像头，不发送运动指令。画面按Execução端报告 de Instalação角度显示。
- **来源标记**：镜像的 `[media] source="test"` 表示测试图案，能播放也不能代表真实摄像头接好了。配置为 camera 时也只显示「配置：摄像头」，配置文件不能证明当前运行状态；视频服务标为模拟设备时另行注明。当前版本会忽略旧的 `media.camera` 开关，Studio 不据此猜测真实来源。
- **ToF**：通过 `/run/tofd/tof.sock` 的 `tof.stream` 获取 8×8 距离分区，显示有效格数、最近/最远有效毫米值及逐格原始状态。5/9 且距离为正才计入统计；无目标（255）和测量失败分别显示。服务未连接、未接传感器、等待首帧、格式错误和过期数据均有独立说明。fake/sim 数据会标注「模拟数据」。
- 传感器Leitura独立于 robotd  de 运动Conexão，只在相关Página可见时进行；没有自动避障、导航或后台录像功能，不更改系统ServiçoeConfiguração。

高级安装可通过 `--tof unix:/run/tofd/tof.sock`、`--camera-socket unix:/run/mediad/media.sock` 和 `--camera-signaling-port 8443` 指定本机服务；`--tof none` 或 `--camera-socket none` 明确关闭对应的只读探测。开发测试可将 socket 指向受控的 `tcp:127.0.0.1:端口`。网页不接受任意 socket 或视频服务器地址。摄像头信令使用打开 Studio 的主机名，远程仅转发 8000 端口的 SSH 隧道不会自动转发视频链路。

本地 `tests/test_sensors_e2e.py` 使用明确标记的假 ToF 和浏览器 RTC 测试实现，验证真实网页播放、导航、错误及资源释放；这些软件测试不代替摄像头、编码器和 ToF 硬件验收。

## Web动作录制、回放 e 灵动

遥控区增加「动作录制 e 回放」。先按原流程站稳并准备好走，关闭实体手柄后，点击「开始录制」，操作Web摇杆、头/身体/嘴部、叫声，或点击“Sentar／Levantar”（Web十字Inferior也可）。只录“Sentar→站起”也能保存成一段；坐站期间等状态提示确认后再操作Inferior一步。pode同时打开「灵动」生成随机 de 小幅头嘴动作，开始坐站时会先停止灵动。暂停录制不计入等待时间，结束后输入名称保存。

从列表选择一段，播放 1、3 或 5 次；suporta暂停、继续、停止、改名、删除，保存Conteúdo在刷新或重启后Preservado。灵动也可单独开启。运动仍由 robotd 执行，Web不会接管Servo总线，也不会因为开启灵动就自动站起或Superior力。

记录最终获准发送 de Controle指令 e 节奏，不保证重复相同空间路线；不录摄像头视频、麦克风音频、Superior力/卸力、开始走/停止策略或设置修改。Sentare站起作为明确目标步骤保存，回放时LeituraAtual姿态，不盲目重按切换键；等新鲜策略阶段e连续实际/目标关节回读确认后再执行Inferior一步，等待时回放时间轴暂停。含坐站 de 记录以 v2 保存，旧 v1 记录仍可读；回退到仅suporta v1  de 程序会略过 v2，恢复新程序后仍可Leitura，不应删除原记录。

以坐着结束 de 记录可播放一次；选择多次循环时，最后é necessário录回站姿，否则Página会解释原因，不自动补一个站起步骤。普通暂停/停止或离开Web只取消后续步骤、清除连续Controle，已经交给主程序 de 坐站仍会Concluído；若需立即卸力，使用现有急停。坐站阶段/回读不明确、15 秒等待超时或回执丢失时停止后续步骤并Instruções原因，不自动重试切换。

踢腿、翻滚、捡取等Modelo技能仍不录制，普通遥控 de 技能不受影响。刚做过这些Modelo技能后，é necessário手动停止策略、重新开始走并等新鲜回读确认就绪，再Inicialização录制/灵动，不能用猜测 de 持续时间判断技能Concluído。

一次只有一个Página会话。按键/摇杆手动接管会先停止自动回放；实体手柄Conexão、Web离开遥控区、后台、失焦、断线、急停或状态异常都会停止自动输出，重连不续播。暂停清除速度e头/身体/嘴部目标，继续时恢复暂停处 de 锁存姿态，速度等待后续新鲜动作帧；Modelo/ControleConfiguração变化后不再回放旧片段。每轮结尾回 em 、退出身体锁存并合嘴，迟到 de 连续目标会合并，避免补发一串过时动作。

每段最多 60 秒、6,000 个事件、1 MiB；最多 20 段，名称最长 32 字符。版本化 JSON 文件保存在 Studio state 目录的 `motion-recordings/`，原子写入；损坏记录跳过并在页面提示，不影响其他控制或可用记录。卸载/升级时需保留此用户数据目录。

实现拆分为 `studio/motion_store.py`（文件校验/保存）、`studio/motion_studio.py`（会话/时间轴/灵动）、`studio/motion_posture.py`（坐站目标和回读判断）、`web/motion-studio.js`（界面）与 `web/motion-heartbeat.js`（页面存活）。通过既有 `pad.op` 的 `op=motion` 接入，原 `pad.motion` 状态不改名。当前开发与验收记录见 [网页动作实现计划](../../docs/superpowers/plans/2026-10-25-web-motion-studio.md)及[坐站扩展计划](../../docs/superpowers/plans/2026-10-25-web-posture-recording.md)；本地模拟通过和实际鸭子验收分别记录。

2026-10-25：c18783c 已部署到Atual鸭子 de 原Controle网址，只重启 Studio；351 项SoftwareVerificação e 静态资源/UsuárioDados/ControleServiço身份回读por meio de。该设备有Web登录保护，未为核对快照而绕过登录，实际动作效果仍待Usuário确认。源码冻结包、备份 e 回退范围见[部署验收](../../docs/superpowers/verification/2026-10-25-web-motion-studio.md)。Imageme通用在线升级未Atualização。

同日用户截图确认入口后，发现停止策略的技能恢复屏障错误地等待静态配置开关关闭。db970dd 已按 `bus.policy_enabled` 实时运行状态修正，并提示确认停下后点“开始走”；205 项后端及完整浏览器恢复/录放流程通过，已更新到原鸭子，仅重启 Studio。真实头嘴动作效果仍待用户确认，详见同一验收记录的后续修正。

同日后续 aa825fc 已把Sentar/站起加入录制，389 项SoftwareVerificação e 独立审查por meio de并部署。Usuário确认“能保存，回放坐站也正常”；真机范围、状态等待e v2 回退边界见[坐站验收](../../docs/superpowers/verification/2026-10-25-web-posture-recording.md)。

## 台架模式：主控没烧，用飞特Depuração板在电脑Superior调Servo

把飞特Depuração板（或 USB 转 TTL）插到电脑Superior，接好ServoeAlimentação，Depois：

```bash
py -3.13 -I run.py --bench
```

它不连主程序，自动打开浏览器进「Servo」页；在页头 de 「串口」Inferior拉里选 COM 口，点「Conexão」就能调（跟 servo-web 一样）。
没接Hardware想先看看：串口选「演示（没接Servo）」，Studio 在Software里假装有 15 颗Servo。

## 装到鸭子Superior

1. 拷贝：把 `software/studio` 整个目录拷到鸭子的 `/home/radxa/studio-dev`（`scp -r`、U 盘解压包都行）。
2. 自检：在鸭子上运行 `python3 -I run.py --selfcheck`（只读：打印版本，对 robotd / configd / padd 各问一次）。
3. 装 root 小助手：`cd deploy && sudo sh install.sh radxa`。0.7.2 的小助手负责舵机总线交接、手柄配对、热点开关、`calib-read` / `calib-commit`（把标定写进主程序、切运动模式）、`ssh-status` / `ssh-password`（「更多」页的 SSH 开关），以及 `imu-recalibrate`（重新校验已保存的 IMU 安装方向）；关热点前会写 `/run/microduck/studio-connecting.json`，让 netcheck 在连接期间别插手。从舵机页交还时，标定模式的实时快照也算主程序起来了（0.5.1 只认运动模式的 `control`，标定模式下每次都等满 30 秒判「起不来」）。步骤、卸载和上机核对见 `deploy/INSTALL.md`。
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

配对Resultado不等于按键已经就绪。helper/configd 返回已绑定后，向导在等待Conexãoe padd 输入时最多补做两次目标手柄 de ConexãoPor favor求，每次最多 5 秒且不超过Atual等待窗口；不清除配对、不重启蓝牙。只有同一 MAC  de  padd 输入报告才能确认就绪，其他已Conexão手柄不算。状态ServiçoAtualização较慢、或输入刚在超时边界到达时，以实际输入为准；同一手柄稍后恢复也会清掉向导旧 de “未Conexão／读不到按键”提示。Usuário已取消、padd 未Execução或开始走路时，不继续补连。旧版没有输入旁路 de 降级Instruções仍明确标注“没法再核对”。

这项补连针对Web配对流程；手柄已经配过、只是休眠时，先短按 Home / Xbox 键唤醒，不必每次忘掉重配。此项修复不提供后台无限重连，也不代表断电后所有型号 de 回连行为已逐一验收。

出厂镜像让 robotd 跑标定模式：`/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf` 里 `ExecStart` 带 `--commissioning`。这样 `calibration-status` 和 `busStatus.last_sample` 马上能读，IMU 页粗校、舵机页中位都能做。上手清单第 3 步写成功后，小助手删掉这个文件、`daemon-reload`、重启 robotd，主程序回到运动模式。`systemctl show robotd -p ExecStart` 里有 `--commissioning`、但那个文件不在时，小助手拒绝自动切（`foreign_commissioning`），去日志页导出诊断包。

IMU 页 de 「IMU Instalação方向」始终Preservado入口：已经保存并Validação过 de Instalação四元数，也能点「重新标定方向」。先扶住鸭子并卸力，二次确认后，运动模式por meio de新版 root 小助手暂时回到标定模式；已经在标定模式 de 直接重新采集。沿用原来 de 静止 3 秒、整个躯干前倾 15–30° 采 3 秒、计算方向e主程序Validação。**点击「交给主程序Validação」前，先把实物回正并停住**，再按提示前倾。小助手 de 重标定恢复会话保持卸力；出厂标定模式也suportaInferior述站姿采数，站着精校流程Inalterado。

总线 ID 200 的 IMU 由主程序启动时自动识别，支持 FT6、IMU-to-DXL（Feetech）；SFLP 124/12（Dynamixel 2.0）。标定、运动模式的 IMU 页都显示实际协议和板卡。板卡名称表示识别到的寄存器布局，不证明厂商。需要手动指定时改主程序配置 `bus.imu_protocol = "auto" / "feetech" / "dxl2"`，网页没有运行中切换协议的按钮。I²C 的 BNO085、LSM6DSV16X 流程不变。

Qinmo 的一次性网页选择、受控重连和必须完成的安装方向验证见[使用指南](../../docs/Qinmo-IMU-网页使用.md)。配置类型与实际连接分别显示；Qinmo 明确标为已配置，不能凭 ID200 或布局自动认证厂商。新版 helper 0.7.2 还保留 `imu_bus_profile`（缺省 legacy），同为 Feetech 的类型变化也会使旧方向和待写结果失效。本地软件验证不代表实物验收，未部署或更新已发布镜像。

总线安装方向的 `imu_bus_protocol` 由主程序验证成功后写入；旧标定没有这个字段时只兼容 Feetech。检测到的协议不匹配时，页面提示重新标定，跳过第 2 步也不能把旧方向当成已验证。主程序通过运动模式的失能状态保留重做入口。第 3 步与小助手 0.7.1 保留并读回该字段；重做完成可采用新绑定，取消恢复原文件。协议、板卡布局或原始身份字节改变，会作废当前采集、在途计算和旧的站姿校准结果。DXL2 板卡不提供采样序号、状态位、传感器读数年龄；主程序使用主机接收新鲜度和原始字节冻结检查，页面不填造这些诊断值。

出厂标定模式做第一次Instalação方向标定，也pode先手动点「站姿使能」：等 HOME 保持站稳（误差 ≤5°），双手扶住整个躯干采静止e前倾，再回正交给主程序Validação。允许已卸力或明确站稳两种状态；起身 em 、扭矩未知、运动 em  e 卸力待确认仍拒绝。por meio de小助手从运动模式进入 de 重标定恢复会话仍要求全程卸力，避免恢复模式时重启主程序影响站姿。采数不会自动Superior力或发起运动。

重标定会话Preservadooriginal标定eInicializaçãoConfiguração，刷新Web或重启 Studio 后可继续，也可「取消并恢复原Parâmetros」。Validaçãopor meio de后逐项读回Atual芯片e新方向，只恢复原来 de 运动Licença e Execução模式，Servo零位（包括非 2048  de 零位）、方向、限位、其他 IMU e未知Configuração均Preservado；恢复Sucesso仍保持卸力。Falha会Preservado恢复入口，不会把未读回 de 方向报成Concluído。此流程é necessário同时Atualização Studio、root 小助手e sudoers；不会调用Superior手清单第 3 步来重写Servo标定。

**标定模式的状态要新版 fork**：fork robotd 一起来先写一份启动报告（`{"mode":"commissioning","phase":"configuring_bus",...}`），`robot.busStatus` 只要它的 phase 还是启动阶段就一直回它；第一次读成功以后才回标定模式的实时快照（phase 是 `ready` / `moving` / `read_error` / `stop_unconfirmed` / `power_pending`，带 `last_sample`）。旧版 fork 的标定模式从来不清启动报告，Studio 会永远看到「启动中」、拿不到 `last_sample`（10-20 真机验收就是这样）；fork 已经改成第一次读成功以后清掉，用 20261020 之后的镜像（或重装那份 robotd）。Studio 这边：实时快照的这几个 phase 都算「主程序起来了」（`read_error` 是起来了、只是读舵机出错，照原样写主程序的原话）；连续报启动阶段超过 30 秒（从这次连上算），总览头图改成「主程序一直报『启动中』」、给「去日志页」，顶栏、待办、上手清单头上也不再说「通常 10 秒」。

Bateria用台架Alimentação供电时，在「设置 → Bateria」里把型号选成「台架Alimentação」：只显示电压，不算电量、也不报电量。
Studio 默认没有密码，同一网络里谁都能打开。在「更多 → 登录密码」里可以直接设置；设过以后要先登录才能改，也可以清掉。命令行 `python3 -I run.py set-password` 仍然可用，但要用 radxa 用户运行，别加 `sudo`（root 写的密码文件 Studio 读不了）。

## Superior手清单：去做、已Concluído、跳过

每一行任何时候都有三个按钮（Usuário 10-20：「可能有人之前做过重新走一遍」「允许人家直接跳过」）：

- **去做**：去那一步 de Página；测出了问题 de 行写「重新做」。
- **已Concluído**：我以前做过（比如二号鸭零位早用 Studio  de Servo页校过），这一行 ✓、写「你标了已Concluído（时间）」。以前 de 「已经校过，核对一Inferior」就是它。
- **跳过**：先不做，这一行 ↷。

标过 de 行给「重新做」e「取消」（跳过 de 是「取消跳过」）。标记绑这一步 de 指纹（Servo零位、IMU 方向、标定、手柄……），指纹变了就不算、回到「该做」；标 de 时候读不到指纹，等读到了再绑Superior。
以前锁着 de 情况——主程序说没做完、读不到（?）、测出了问题、测急停、调Servo时——现在都能点，但「已Concluído」「跳过」要点两次，第二Inferior按钮Superior写后果（「确定跳过？主程序说标定没做完：跳过了鸭子也站不起来」这种），后端没收到确认也拒。
第 1 步标了已Concluído或跳过，第 3 步「写进主程序」 de 准备情况里「Servo零位」算满足（15 颗按 2048 写零位，零位要是用 Studio  de Servo页校过 de 才对）。
第 2 步标了已完成或跳过、主程序里正在用的那颗 IMU 方向没确认、IMU 页也没站着校过（没有 `imu-pending.json`）时，第 3 步**按默认装法写这颗 IMU 并标成已确认**（10-21 真机验收：全点跳过以后 fork 要 IMU 方向已确认才肯进运动模式，鸭子一直停在标定模式）：

- 总线小板（`bus`）：文件里现有的 `imu_mount_quat`（出厂就是官方装法 `[0.7071067811865476, 0, 0.7071067811865476, 0]`）；
- BNO085（`bno08x`）：`[0.5, 0.5, 0.5, 0.5]`，fork `duck-control/src/trunk_imu.rs` 的 `BNO08X_DEFAULT_MOUNT`；
- LSM6DSV16X（`lsm6dsv16x`）：`[0.7071067811865476, 0, 0.7071067811865476, 0]`，复刻推荐装法（模块 x 朝下、z 朝前，二号鸭 10-17 实测）。fork 自己给的默认是单位四元数（「小板没有公认的朝上方向」），不用它。

准备情况里写「你标了第 2 步已完成：IMU 按默认装法写（芯片：哪种装法）。装得不一样的，站起来会往一边倒——写完以后在 IMU 页站着校一次，再写一次主程序」；点「写进主程序」的第二下写「确定？IMU 按默认装法写」。IMU 页站着校过（有 `imu-pending.json`）就照旧用它，主程序里方向已确认就照旧用主程序的；IMU 页记下的是另一颗芯片的、或者主程序还没报用的是哪颗，不猜，照旧挡住。小助手 `calib-commit` 照旧只收 `imu: {source, quat}`。这样**跳过第 1、2 步 → 第 3 步写进主程序 → 运动模式**一路能通。

## 打开 Studio  de 地址怎么选

开着 Clash 系统代理的 Windows 电脑打不开 `duck-xxxx.local`（走了代理，502）；不带点的 `duck-xxxx` 能开（Windows 用 LLMNR 问到鸭子，代理按 `<local>` 绕过）。所以页面上按设备写：

- Windows 电脑：`http://duck-xxxx:8000/`（开着代理也能打开）；
- 苹果手机、Mac：`http://duck-xxxx.local:8000/`；
- 安卓手机，或者都打不开：去路由器的设备列表找 `duck-xxxx`，用它的 IP；
- 电脑开着 Clash  de  TUN 模式还打不开：在 Clash 里把局域网（192.168.0.0/16）设成直连。

「更多」页有一块「这只鸭子的地址」，列出现在能用的 IP（configd `net.status` 的 `ip4`，热点模式是 10.42.0.1）、`duck-xxxx`、`duck-xxxx.local`，每个能复制；总览顶栏鼠标停在鸭子名字上也看得到 IP。连 WiFi 的列表里滤掉了鸭子自己的热点（按 net.json 的 `hotspot_ssid`；没有就滤「`Microduck-` 开头、已保存」的）。

**连 WiFi 以后自动跳到鸭子的新地址**（10-21 用户：「连 WiFi 弄了三下」）：点了连接，页面记下要找的 `http://duck-xxxx:8000/` 和 `http://duck-xxxx.local:8000/`（主机名来自 net.json，端口跟 `--listen` 一致）。
Página跟鸭子 de Conexão断了（WebSocket 断了，ou 5 秒没收到消息）以后，卡片换成「鸭子正在连『家里 WiFi』……Por favor把这台设备连回『家里 WiFi』（电脑插着网线 de 不用管），找到鸭子会自动打开」，列出这两个地址（能点）e「找不到时：去路由器设备列表找 duck-xxxx  de  IP」。
每 2 秒用 `new Image()` 加载 `<地址>probe.svg?t=<时间>`（`web/probe.svg`，跟别的静态文件一样不用登录、不缓存；跨域加载图片不要 CORS），哪个先加载成功就跳过去；一次探测最多等 6 秒，没回话之前不重复探同一个地址。
最多找 3 分钟，找不到就换回原来那段按设备打开 de Instruções。Página重新连Superior原来 de 地址（Ponto de acesso回来了，Instruções没连Superior）时停止探测，照旧显示Falha原因。

## Imagem里 vs 手动装

「连 WiFi」卡片依赖复刻Imagem里 de 几样东西，不是 Studio 自己带 de ：

- netcheck 写的配网状态 `/run/microduck/net.json`；
- NetworkManager 里的 `Microduck-Hotspot` 热点配置；
- configd 以 `--allow-user btd,radxa` 运行，Studio 才有权限调 `net.scan` / `net.connect` / `net.forget`；
- mDNS 配置，手机才能用 `duck-xxxx.local` 找到鸭子。

按 `deploy/INSTALL.md` 手动装 Studio 和 root 小助手、但没有复刻镜像 overlay 的鸭子，没有这几样，页面就不显示「连 WiFi」卡片；总览、手柄、舵机、IMU、日志这些照常使用。

## 页面和 Studio 之间的约定（WebSocket `/ws`）

握手时Verificação Host e Origin，不对就拒绝握手（浏览器只看到 1006，日志里写原因）；没登录 de 先接受再用 4401 关掉，Página看到 4401 就跳登录页。

| 方向 | 消息 | Instruções |
|---|---|---|
| Studio → 页面 | `{"t":"hello","version","duck"}` | 连上先发一次 |
| | `{"t":"state", …}` | 页面可见时 10 Hz；字段见 `studio/state.py` 的 `summarize` |
| | `{"t":"hb"}` | 页面在后台时 1 Hz（这时不订阅 robotd 的实时状态，省 CPU） |
| | `{"t":"log","entry":{…}}` | 新日志 |
| | `{"t":"result","id","ok","reason","data"}` | 命令回执；扫 WiFi 的网络列表等数据放在 `data` |
| | `{"t":"pad", …}` | 手柄快照：手柄那一块在屏幕上时 10 Hz，不在 1 Hz（总览的手柄格要用）；长列表没变时带 `lists_same`、不带列表 |
| 页面 → Studio | `{"t":"hb","seq","visible","route","pad_visible"}` | 每秒一次；进出手柄区那一刻马上再发一次。`pad_visible` = 手柄那一块在屏幕上（#/pad 只是总览上的锚点） |
| | `{"t":"cmd","id","name","args"}` | relax、servo.*、imu.op、calib.op（`preview` / `commit`：上手清单第 3 步）、pad.op、onboard.op（上手清单的 `done` 已完成、`skip` 跳过、`undone` / `unskip` 取消，`{step, confirmed}`：要点两次的第二下才带 `confirmed: true`；老的 `confirm_servo` 还认）、net.op（`scan` / `connect` / `forget`） |

舵机会话在 `state` 里的几个字段（每一页顶上的提示条用）：`servo_session`（开着才有：`holding` 几颗保持着、`unknown` 几颗读不到扭矩、
`restored` 是不是 Studio 重启后接着管的）、`servo_handback_s`（交还以后、主程序连上以前一直有）、`servo_orphan`（上次退出时开着、这次没接管上）、
`servo_conflict_s`（会话期间 robotd 被手动起来了，10 分钟内）。`servo.close {if_idle:true}`（离开舵机页）只在 15 颗扭矩当场读到都是 0、
没有别的页面在舵机页、没在校准 / 运动时才交还；`servo.close {}`（点「交还主程序」）先等在路上的舵机操作做完再卸力交还。

`state.starting_s` / `state.starting_long`：主程序从这次连上起连续报启动阶段多少秒、超没超过 30 秒（总览头图、顶栏、待办改口「一直报启动中」用）。

`state.net` 是配网状态：`known=false` 表示没有 net.json（整块 WiFi 隐藏）；否则有 `mode`（wifi / hotspot / none）、当前 `ssid` / `signal` / `ip4`、`hostname`、
`url_local`（`duck-xxxx.local`，端口跟 `--listen` 一致）、`url_host`（不带点的 `duck-xxxx`）、`ip_now`（现在能用的 IP：热点模式是热点地址）、
`urls`（「这只鸭子的地址」那几行：`{kind: ip / host / local, url, note}`）、鸭子热点 `hotspot {ssid, ip, psk}`、上次结果 `last_try`、`busy`。`net.op scan` 滤掉鸭子自己的热点。`net.op connect` 先回「开始切换」（页面拿 `url_host` / `url_local` 当以后要找的地址），真正关热点、调 configd 在后台做；
结果写到 state 目录的 `net-last-try.json`（不含密码）。家里的 WiFi 密码只从页面传到 configd 一次，不进日志、state 或诊断包。

已保存的加密网络也要每次填密码：官方 configd 遇到加密网络、没给密码就回 `unsupported`。密码错了会先 `net.forget` 掉这次写坏的配置，再马上开回热点；
`timeout`、`other`、Studio 自己等 configd 超时，也会马上开回热点。Studio 等 60 秒没回话单独记「鸭子的配网程序 60 秒没回话」，不跟 configd 的 `timeout` 混在一起。
小助手关热点前写 `/run/microduck/studio-connecting.json`（90 秒内 netcheck 不插手），开热点成功后删掉。

Página判断「连不Superior」只看收到消息 de 间隔（1 秒变灰、3 秒报警），不看两边 de 钟（鸭子 de 钟可能是 1970 年）。

## Logs

Os registros ficam em `logs/studio-YYYY-MM-DD.log`, são mantidos por 14 dias e não excedem 50 MB no total. Cada linha registra uma ação:

```
2026-10-18T00:41:56.194+09:00 [comando] → liberar torque (computador 127.0.0.1) · etapa: robot.relax
2026-10-18T00:41:56.197+09:00 [comando] ← liberar torque: sucesso · 3 ms · enviado, aguardando confirmação de leitura · etapa: robot.relax · resposta original: {"accepted": true}
```

Em caso de erro, o registro informa “parou em: etapa · resposta original: … · sugestão: … · estado atual: {…}”. Senhas e tokens são ocultados automaticamente. Mensagens idênticas dentro de um minuto são registradas uma vez, com a quantidade de ocorrências agrupadas.

A página “Logs” mostra os 500 registros mais recentes e permite exportar um pacote de diagnóstico com logs, estado naquele momento, respostas originais do robotd, versões e logs de sistema do robotd. Use-o ao pedir ajuda nos grupos.

Cada comando registra envio e resposta, duração e estado atual. O código dessa funcionalidade é original deste projeto.

## Testes

```bash
py -3.13 -I run_tests.py               # computador
python3 -I run_tests.py                # robô
```

Regressão direcionada da integração do barramento com a IMU (inclui página Edge sem interface gráfica; os testes de navegador são ignorados se Edge não estiver disponível ou Node for anterior à versão 22):

```bash
py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','tests.test_imu_backend','tests.test_commit','tests.test_helper_calib','tests.test_helper_imu_redo','tests.test_imu_bus_ui','tests.test_imu_wizard_e2e'])"
```

Cobertura:

- Login: sessões, espera após cinco senhas incorretas, CSRF ao sair, matriz Host 421/Origin e fechamento com 4401 do WebSocket sem autenticação.
- Logs: formatação, ocultação de dados, deduplicação e limpeza por dia, mesmo com o relógio parado em 1970.
- JSON-RPC: linhas incompletas ou muito longas, JSON inválido ou que não seja objeto e reconexão após timeout.
- Liberação de torque: não fica bloqueada por consultas lentas; confirma pela leitura; a ausência do sinalizador HD1910 não conta como confirmação; cobre modo de calibração, sucesso na primeira tentativa após reinício do robotd e não reenvia automaticamente um comando de torque aplicado por outro processo após a confirmação.
- Polling: erro em um item não bloqueia os demais; assina o fluxo em tempo real somente enquanto há alguém observando; heartbeat ausente significa que não há observador; cobre queda e retorno do robotd.
- Detecção de postura com dados gravados no robô; ida e volta completa do comando de liberação pelo WebSocket.
- Pareamento do controle: valida argumentos do auxiliar `pad-pair`/`pad-forget`; interpreta sucesso, falha e timeout do robotctl; fluxo principal do assistente, fallback para o auxiliar antigo, nova tentativa após falha de registro do proxy bluetoothctl, espera de 30 s do padd, reconexão limitada após parear, entrada real antes do serviço de estado, limites de timeout e cancelamento e recuperação de estado quando chega tarde uma entrada do mesmo controle.
- Configuração de rede: verbos do ponto de acesso no auxiliar e arquivo de janela de conexão; net.json ausente, inválido ou em cada modo; cache de busca; ordem de conexão e causas de falha (bad_key remove a configuração antes de reativar o ponto de acesso); restauração do ponto de acesso; somente uma conexão por vez; senha ausente de logs, state, last-try e pacote de diagnóstico.
- Senha de login: configuração inicial pela página, alteração somente após login, remoção, manutenção da sessão atual após alterar a senha, recusa de `set-password` como root e orientação do cartão quando estiver no modo de ponto de acesso sem senha.
- Estado de calibração: fake robotd envia primeiro o relatório de inicialização com quatro campos e depois do primeiro read retorna o snapshot do fork; `--commissioning-stuck-status` mantém o relatório inicial. O snapshot real indica que o controlador iniciou (resumo, requisitos e entrega ao auxiliar); se um fork antigo continuar em `configuring_bus`, a entrega considera que ele não iniciou e explica o estado real. Depois de 30 s contínuos no estado inicial, a interface informa que continua mostrando “iniciando”.
- Os três botões da lista inicial: “concluído”/“pular” em todos os casos antes bloqueados, confirmação em duas etapas com texto correto e recusa do backend sem confirmação; registro e invalidação de conclusão; associação posterior da impressão digital quando não foi possível lê-la; item 1 concluído satisfaz a verificação do zero dos servos no item 3; item 2 concluído sem direção confirmada grava a orientação padrão da IMU (placa do barramento, BNO085 ou LSM6DSV16X), verifica quaternion do auxiliar e passa na validação do modo de movimento; usa `imu-pending.json` quando existe, usa a orientação confirmada pelo controlador e mantém o bloqueio quando o chip não corresponde.
- Botões “ativar postura”/“desativar” da página da IMU: no modo de calibração, solicita confirmação e envia `imu.op hold`; o controlador recebe 15 direções e 3000 ms em `hold-home`; depois de ficar em pé, a página informa “modo de calibração (em pé)”; desativar usa `relax`. No modo de movimento, o comando é igual a “levantar” no controle e a “liberar torque” no topo, verificado de ponta a ponta no navegador.
- Endereços nos modos de ponto de acesso/Wi-Fi, exclusão do ponto de acesso do robô dos resultados da busca e apresentação dos três tipos de endereço no aviso de troca de rede.
- Localização do robô após conectar ao Wi-Fi: `probe.svg` não exige login e não fica em cache; apresenta os dois nomes de host; lógica exercitada no código real de `web/wifi.js` com relógio falso, duas buscas a cada 2 s, redirecionamento pelo primeiro endereço disponível, desistência após 3 minutos, parada quando o ponto de acesso retorna e sem repetir uma sondagem pendente; teste do aviso de desconexão, retorno do ponto de acesso e redirecionamento no navegador.
- Gravação no controlador: `calib-read` do auxiliar é somente leitura e não adquire bloqueio; `calib-commit` adquire o bloqueio e verifica os sinalizadores; sai do modo de calibração removendo drop-in; só confirma após ler de volta `mode=motion`, `phase=control` e todos os campos de `calibration-status`; erros de `waiting_for_bus` e do barramento são separados; divergência de leitura, falha em `.saved.toml` e falha de reinício provocam rollback, com erros de arquivo e modo separados; recusa enquanto a política está ativa ou quando `ExecStart` contém `--commissioning` mas falta o drop-in; mantém os dez backups mais recentes em ordem. Testa o estado de prontidão nos dois modos, fallback para `calib-read`, leitura de `last-result.json` após timeout, atualização do item 3 quando pending/centered muda, remoção do registro ao desfazer calibração de centro e saída de código idêntica dos dois TOMLs de grupo.
- Comando “gravar no controlador”: o auxiliar `calib-read` é somente leitura e não obtém o lock; `calib-commit` obtém o lock antes de verificar os sinalizadores; remove o drop-in de calibração antes de trocar para modo de movimento; sucesso exige leitura de `mode=motion`, `phase=control` e igualdade campo a campo de `calibration-status`; distingue erro de calibração `waiting_for_bus` de erro do barramento; divergência de leitura, falha de gravação `.saved.toml` e falha de reinício causam rollback com mensagens separadas para arquivo e modo; recusa se a política estiver rodando ou se `ExecStart` tiver `--commissioning` sem drop-in; mantém dez backups numerados. O Studio testa prontidão nos dois modos, fallback de `calib-read`, consulta de `last-result.json` após timeout, alteração do item 3 quando pending/centered muda, remoção do registro ao desfazer calibração central e saída igual dos dois arquivos TOML de grupo.

## Estado atual (primeira versão)

Disponível:

- **Visão geral:** estado em tempo real, pato 3D, bateria, temperatura da placa e liberação de torque em um toque (também pela barra de espaço).
- **Servos:** busca, calibração de zero individual ou de todos (grava diretamente nos servos), direção, postura, P/D e limite de torque.
- **IMU:** calibração inicial no modo de fábrica (segurar o robô alinhado e incliná-lo para a frente; o controlador valida com `verify-imu`) e calibração fina em pé quando possível. Os botões “ativar postura” e “desativar (liberar torque)” aparecem acima de “calibração em pé”, com indicação de postura atual, relaxada ou em processo de levantar. No modo de movimento, “ativar postura” usa o mesmo comando `pad.op stand` do controle remoto, com nova validação do estado pelo backend. No modo de calibração também é possível ficar em pé, conforme solicitação do usuário de 21/10: envia `imu.op hold` para o comando `hold-home` do fork; os 15 servos giram juntos da posição atual até HOME por 3 s e mantêm torque, enquanto a IMU continua sendo lida. A direção segue a usada no item 3 e o zero vem do arquivo do controlador (2048 de fábrica). No modo de calibração, o Studio consulta `busStatus` a cada 0,1 s; `last_sample.imu` alimenta a leitura em tempo real, a inclinação da área “agora” e a calibração em pé. Também é possível calibrar em pé antes de confirmar a direção, calculando a orientação completa nova que será gravada no item 3. A gravação no controlador fica bloqueada enquanto o robô está em pé, pois reiniciar o controlador faria o robô cair; se estiver relaxado, a calibração em pé orienta ativar a postura primeiro.
- **Acesso remoto por SSH** (página “Mais”, pedido em 21/10 para permitir reparos sem regravar o cartão): a imagem de fábrica aceita somente chaves e não contém chaves de usuários nem senha remota padrão. O usuário configura primeiro a senha da página (sem ela o backend recusa, para impedir que qualquer pessoa conectada ao ponto de acesso habilite SSH) e depois define uma senha SSH própria de 8–64 caracteres, que não seja fácil de adivinhar. `POST /api/ssh {action: on}` chama `ssh-password` no auxiliar: define a senha de radxa com `chpasswd` via stdin, grava `/etc/ssh/sshd_config.d/05-microduck-ssh-password.conf` antes de `10-microduck.conf`, valida com `sshd -t` e `sshd -T` se login por senha está realmente habilitado e só então recarrega o serviço. Se algo falhar, remove o arquivo e reverte. Desativar remove esse arquivo e recarrega o serviço. **A senha só passa pelo stdin do auxiliar; não aparece na linha de comando, nos logs nem nos arquivos de resultado**, conferido nos testes. O cartão mostra o comando `ssh radxa@<endereco-atual>`. Alternativa: cadastrar uma chave pela página usando `studio/sshkeys.py`. Como o Studio já roda como radxa, grava diretamente no próprio `~/.ssh/authorized_keys`, sem o auxiliar. Aceita uma chave pública completa de uma linha (ed25519/rsa/ecdsa/sk-*), verifica que o tipo em base64 corresponde ao prefixo e rejeita opções como `command=` e chaves privadas. Não duplica fingerprints SHA256; a remoção é por fingerprint. Recusa links simbólicos e aplica permissões 700 ao diretório e 600 ao arquivo. Assim como para senha SSH, exige primeiro definir a senha de login da página.
- **Gravar no controlador:** o item 3 da lista inicial grava de uma vez o zero dos servos, a direção e a orientação da IMU na calibração do robotd. A imagem de fábrica usa modo de calibração; após sucesso, o auxiliar remove o drop-in de commissioning e reinicia o controlador em modo de movimento. Não basta o reinício: também exige `mode=motion`, `phase=control` e leitura de volta igual campo a campo de `calibration-status`; caso contrário, restaura arquivos e modo. Após reiniciar o Studio, o resultado anterior é recuperado de `last-result.json` no cartão do item 3.
- **Controle:** pareamento pelo comando oficial `robotctl pad pair`, controle pelo navegador e teste de emergência.
- **Controle remoto:** levantar, iniciar caminhada, sentar, habilidades, ações e sequências.
- **Ajuste de movimento:** somente leitura. **Gerenciamento de modelos:** importar pacote de implantação, renomear, selecionar modelo, restaurar o integrado, configurar teclas de ação e remover modelos importados. Consulte [Importação de modelos](MODEL_IMPORT.md) para o formato.
- **Logs:** página de logs e pacote de diagnóstico; no celular, ambos também ficam acessíveis em “Mais”.
- **Conectar ao Wi-Fi:** quando o robô está em modo de ponto de acesso, o celular pode selecionar a rede doméstica e informar a senha. Depois da troca, a página localiza o novo endereço do robô e redireciona; as configurações também mostram a rede atual e permitem trocar de rede ou esquecer uma salva.
- **Senha de login:** configurar, alterar ou remover em “Mais → Senha de login”. No modo de ponto de acesso sem senha, o cartão de Wi-Fi na visão geral orienta configurá-la primeiro.

Ainda não disponível nesta versão:

- Alterar pela web os parâmetros de movimento (amplitude da caminhada, suavização, P/D e limites de torque).

## Referências

Este projeto se baseia no código aberto oficial do Microduck e considera ideias de vários projetos abertos da comunidade. O código foi escrito pelos autores deste repositório, com auxílio de ferramentas de IA durante o desenvolvimento.

## Licença

Apache-2.0, conforme o restante do repositório. Preact, htm e three.js em `web/vendor/` usam MIT; as licenças estão em `web/vendor/licenses/`. A origem dos modelos 3D está em `web/model/NOTICE.md`. As licenças dos pacotes em `deps/` estão nos respectivos diretórios `dist-info`.
