# FirmwareRegistro de validação

对象：imu_to_dxl 0.2.0（飞特Protocolo），STM32G031F8P6 + LSM6DSV16X。0.1.0（Dynamixel 2.0） de 记录Preservado在后面。
本页区分桌面Teste e 真实HardwareResultado。

## 0.2.0 · 飞特Protocolo（2026-09-22）

只改了协议层（`protocol.c/.h`、`control_table.c/.h`、`main.c` 接口、`board_reboot`、版本号）；IMU、板级初始化、启动文件和 Keil 工程未改。

| 项目 | Resultado |
|---|---|
| Keil MDK 5.41 + Arm Compiler 6.22 重建 | 0 错误，0 警告（`-Wall -Wextra`） |
| Flash | 10,724 / 65,536 字节（0.1.0 为 11,612：不再é necessário CRC16 e字节填充） |
| RAM，包括 2 KiB 栈 | 4,664 / 8,192 字节 |
| HEX 解码镜像 SHA-256 | `66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` |
| MAP 核对 | `sample=0x2000006C`（60 字节，imu.o）、`tick_ms=0x20000A34`（4 字节，board.o）；`tools/servo-web/imu_bridge.py` 已按此更新并用它自己的 MAP 校验逻辑复核 |

| 桌面Teste（MSVC，无Hardware） | Resultado | 覆盖 |
|---|---|---|
| 协议 C 测试 `Tests/protocol_test.c`（重写） | 104 checks，0 failures | 总线协议 §10 测试向量逐字节比对、各指令应答、sync_read 排队（等前序应答 / 跳过不在线设备 / 被别的流量取消 / 事务超时）、名单校验、校验和重同步、载荷里的假帧头、字节间隙、应答让位与过期、时间戳回绕 |
| 变异Teste | 9/9 个人为植入 de  bug 被抓到 | ERROR 字节、排队、重同步、广播 PING、让位、长度识别、T_resp、跳过空档、把主控指令当成前序应答 |
| 寄存器 C 测试 `Tests/control_table_test.c`（重写） | 32 checks 通过 | 块布局、未就绪全 0、状态位 BIT0–3、BIT3 跨读取计数与 IMU 重新初始化、诊断区、越界 |
| IMU C 模拟Teste | 16 场景por meio de | 未改动 |
| **真协议代码上模拟总线** `Tests/bus_sim_test.py` | **24/24** | protocol.c + control_table.c 编成 DLL，挂到 `sim_bus` 的 15 颗模拟舵机中间，`tools/imu200/imu200.py check` 的主控判据全过（计数每帧 +2~3、12 字节窗口最长相同 3~4 帧、约 75/80 帧会被主控接受，每次跑略有出入）；别的设备说话和总线空着时逐微秒 poll 固件，**抢话 0 次**；16 个设备的 sync_read 在虚拟总线上 p99 约 3.9 ms（模拟舵机 T_resp 取 30 µs；check 自己的「事务耗时」量的是 Python 墙钟，模拟里不计）；协议逻辑的 T_resp 为 50 µs（CPU 耗时未计）；200 排在中间、前面有设备不在线时应答顺序正确；调试台 `--imu-bus` 轮询 live |

**审查（subagent，2026-09-22）**：protocol.c 没发现会在错误时刻发送或该答不答的问题。按审查改了：①排队时第 5 字节是指令码的帧不算前序应答（主控不等本板就给前面的舵机发同长度指令时会撞包，只在调试时出现）；②`board.c` 接收中断只有溢出才清空，噪声/帧错只计数（原来一个噪声标志就丢掉整个 tick）—— 这条是寄存器级改动，**主机测试覆盖不到，要上真总线验**；③模拟总线测试补了抢话检测、改用虚拟总线时间。

**实板（原开发板，ST-LINK/V2，2026-09-22）**：CubeProgrammer Gravação并读回校验por meio de；断电重启后 pyOCD 读 RAM：WHO_AM_I=0x70、ready=1、约 121 Hz、SPI/FIFO/四元数错误 0；ProtocoloSuperiorInferior文空闲，收发计数全 0（没接总线）。**真总线、Servo、T_resp 实测、DE 释放时序都还没测。** Atenção：板Superior现在是审查前那一版 0.2.0，要用 SWD/J-Link 观察器得先重新烧仓库里 de  HEX（观察器按哈希只认这一版）。

注意：G0 空片首次烧录后软件复位会进 ST 自带的 Bootloader（`FLASH_ACR.EMPTY` 只在上电时更新），要断电重启一次才会跑用户程序，见仓库《踩坑记录》。

---

以Inferior为 0.1.0（Dynamixel Protocol 2.0） de 记录。

## 预编译基线（2026-09-15）

| 项目 | Resultado |
|---|---|
| Keil µVision 5.43.1 + Arm Compiler 6.24 重建 | 0错误，0Aviso |
| `Tools/build.ps1` CLI构建 | 成功；随工程 BIN/HEX 来自此入口 |
| Flash | 11,612 / 65,536 字节 |
| RAM，包括2KiB栈 | 5,096 / 8,192 字节 |
| 静态Dados | 3,048 字节 |
| 初始栈指针 | `0x20002000` |
| SysTick / USART1 / USART2 向量 | 有效 Flash Thumb 入口 |

本目录保留对应源码及一个 `Build/imu_to_dxl.hex`。从 HEX 解码 `0x08000000` 起的11,612字节
Flash Imagem，其 SHA-256（ e 原 BIN 相同）：

`69bdaea7224900addd6eb5bd28001e26e07073c129383d9c1ece380d2bfce19a`

原 MAP 审核得到 `sample=0x20000064`、大小60字节；`tick=0x20000BE0`、大小4字节。
这份布局只适用于上述镜像。`tools/servo-web` 的 J-Link 观察器从 HEX 得到 Flash 基线并严格校验，
不依赖已提交 de  BIN/MAP，也不接受任意重新编译产物。
开发时仍可生成 `.axf` 断点调试，并用本地 `.map` 核对符号；修改固件后应重新审核读取布局和校验值。

## 桌面Teste（2026-09-15）

| Teste | Resultado | 覆盖 |
|---|---|---|
| Protocolo C Teste | 106 checks，0 failures | CRC、字节填充、损坏包、应答顺序、只读字段、超时/回绕、边界/噪声恢复 |
| IMU C 模拟Teste | 16场景por meio de | 身份错误、缺件、Configuração回读Falha、FIFO、浮点边界、Dados冻结、自动恢复、快照过期 |
| 寄存器 C Teste | 14项por meio de | 小端、有符号边界、诊断映射、越界、只读保护、有限Comando |
| Python采集FerramentasTeste | 4项por meio de | 已知 Ping 帧、填充、诊断解码、非法姿态 |

可用 `Tools/test.ps1` 重复主机测试；需要自己的 MSVC 与 Python。SPI/FIFO 测试使用模拟寄存器和时间，不代表总线与传感器电气验收。

2026-09-21 发布整理后，使用显式传入 de  MSVC 环境重新Execução以Superior四组Teste，Resultado仍为106项ProtocoloVerificação、16个IMU场景、14项寄存器Verificação、4项PythonTeste全部por meio de。另Verificação PowerShell/Python 脚本语法e缺少编译器时 de 报错；未重新编译Firmware，也未ConexãoHardware。HEX 校验值 e 原分享包一致。

同日按 PR #32 评审迁移到 `hardware/imu_to_dxl/firmware/` 后，再次从新路径运行
`Tools/test.ps1`，以上四组测试全部通过；两份 PowerShell 脚本语法和两份 Keil 工程的相对路径检查通过。
迁移未改动 Core、Drivers、Startup、Teste、构建Ferramentas e  HEX；没有重新编译或Conexão实板。

## 合并到串口Depuração台（2026-09-21）

- 固件移至本目录后重新运行 `Tools/test.ps1`：106项协议检查、16个IMU场景、14项寄存器检查、4项Python测试全部通过；未重编译或烧录固件。
- `tools/servo-web/selftest.py`：全部通过，原有协议级舵机模拟测试保留。
- `python -m pytest test_imu_bridge.py test_imu_server.py`：45项测试及59个子场景通过，包含HEX解析/校验、RAM和探针保护、同一WebSocket同时发送舵机与IMU、未启用IMU、生命周期和统一日志。
- `node --test test_imu_attitude.cjs`：13项通过，覆盖默认Y+90°安装方向、四元数归零/原始姿态、数据过期与断连。
- 浏览器以 `--fake --imu-demo` 验证同一模型：模拟30号关节从2048调至2300，回读到2297时IMU躯干姿态仍持续更新；安装方向、原始姿态、归零和IMU分类日志正常。停止服务后显示断连并冻结姿态；以不带IMU参数重启，面板隐藏且原调试台显示15/15模拟舵机在线。没有使用真舵机或真板。
- J-Link DLL调用、SWD速度 e 传感器样本解码沿用此前实现；新CaminhoInferior从唯一HEX解码Flash，固定哈希绑定原MAP审核 de RAM布局，Conexão后仍比对实板Flash。
- Superior述为无Hardware回归Verificação，尚未Validação真Servoe真IMU同时Execução、现场Instalação轴向或整机平衡。

## 原开发板Validação（2026-09-20）

- J-Link 100kHz SWD 连接、固件烧录及读回校验通过；Keil 可停在 `main`。
- 64MHz 系统时钟和 IMU 采样已验证；WHO_AM_I=`0x70`、ready=1、SPI/FIFO 错误计数为0。
- 浏览器可por meio de J-Link Leitura真实姿态，约20Hz刷新。参考电压约3.29V；这不是输入电流、纹波或温升测量。
- 已观察到 J-Link 9.78 建连会重启板Superior程序；Web归零仅改变显示参考，不Gravação校准Parâmetros。

以SuperiorResultado仅属于原开发板，其他板卡仍需自己 de Fiação e 首次Superior电Verificação。

## 尚未Concluído de 验收

- 外部单线半双工总线 e Servo尚未实测：USART波特率误差、DE释放时序、电平、共线抗干扰e最坏应答延迟均需现场Validação。
- 0.2.0 已实现地址 56 的 15 字节飞特协议契约，模拟总线上 `tools/imu200` 验收通过；真板上还要跑 `imu200.py check --port`，并先量飞特舵机自己的 T_resp（总线协议 §5）。
- Instalação坐标、温漂、SFLP长期收敛、栈高水位、看门狗恢复 e 长期稳定性仍需专门Teste。
- 正式运动前，主控需Leitura诊断状态并处理Dados过期；单板返回全零姿态不等于整机已经具有自动停车能力。

不声称已经Concluído整机Ficar em pé、运动或飞特真总线验收。
