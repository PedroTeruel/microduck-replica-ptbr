# imu_to_dxl Firmware 0.2.0

Usado na placa **STM32G031F8P6 + LSM6DSV16X** feita por um integrante da equipe. A base de hardware é
`fanhao375/microduck-replica` 的 `a1f4979c425bd9228622be89f2bfa4d1de7fbde3`
(`2026-09-08`, inclui J4/J5 e RX_EN). Em 2026-09-20 foi concluída a primeira inicialização na placa real: conexão J-Link SWD,
gravação e verificação de leitura do firmware, parada do Keil em `main`, clock de 64 MHz e amostragem do IMU foram verificados.
No teste curto, o identificador do IMU foi `0x70`, `ready=1` e os erros SPI/FIFO ficaram em 0; o barramento externo e os servos ainda não foram testados.

**Na versão 0.2.0 (2026-09-22), o protocolo do barramento foi substituído por Feetech SCS/STS** e implementado item a item conforme o [protocolo do barramento](../总线协议.md): ID 200, bloco de 15 bytes no endereço 56 e enfileiramento de sync_read. O IMU, a placa e o projeto Keil não foram alterados. Os testes do host no computador e a validação do “código real do protocolo em um barramento simulado” (`Tests/bus_sim_test.py`, usando os critérios `check` de [`tools/imu200`](../../../tools/imu200)) foram aprovados. O firmware foi gravado na placa de desenvolvimento original e o IMU continua funcionando. **O barramento real e os servos ainda não foram testados.**
Os limites da compilação, dos testes de desktop e da primeira validação na placa real estão em [VALIDATION.md](VALIDATION.md).

Este diretório reúne o diagrama de princípios e a PCB, e contém o código-fonte, o projeto Keil e o único artefato pré-compilado preservado
[`Build/imu_to_dxl.hex`](Build/imu_to_dxl.hex). O console de depuração serial [`tools/servo-web`](../../../tools/servo-web) sobrepõe os ângulos das articulações dos servos e a postura do tronco do IMU na mesma página Web. Há três modos de leitura: `--imu-bus` (barramento dos servos, mesma chamada sync_read do controlador), `--imu-swd` (ST-Link / DAPLink) e `--imu-jlink` (J-Link).

O observador SWD/J-Link decodifica do HEX a imagem Flash de **10.724 bytes** a partir de `0x08000000`, confere o SHA-256
`66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` e valida a imagem na placa.
Somente esta versão base pode usar o layout de RAM revisado: `sample=0x2000006C` (60 bytes),
`tick=0x20000A34` (4 bytes), conferido no MAP da versão 0.2.0. Não é necessário recompilar para usar apenas a página de postura; depois de alterar o firmware, revise novamente
o checksum da Flash e o endereço/tamanho destes dois símbolos. Não reutilize endereços antigos ao ler um programa novo.

Para depurar o código-fonte com breakpoints, compile novamente o `.axf` no seu ambiente. A compilação também gera `.map` e `.bin` para conferência durante o desenvolvimento;
这些文件及测试产物由 `.gitignore` 排除，不提交到仓库。

Fluxo de dados: LSM6DSV16X → SPI1 → STM32 → USART2 + buffer externo → barramento half-duplex de fio único → controlador Linux.
Implementa o **protocolo Feetech SCS/STS, ID 200, 1 Mbps** e se apresenta como um servo no barramento (a versão 0.1.0 usava Dynamixel Protocol 2.0).
O código não movimenta servos, não grava nos Option Bytes do MCU e não grava configurações de firmware na Flash.

**Validação no barramento real:** conecte um adaptador half-duplex (URT-2) e execute `python tools/imu200/imu200.py check --port COMx`. Os 13 critérios foram derivados do código-fonte do controlador; todos devem passar antes de integrar o sistema. A verificação elétrica (liberação de DE, níveis lógicos e medição real de T_resp) ainda exige um analisador lógico.

## 1. 直接开始

### Keil

1. Para usar J-Link, abra `MDK-ARM/imu_to_dxl_jlink.uvprojx`.
2. No seu Keil, selecione uma instalação licenciada do Arm Compiler 6 (foram verificados 6.24 e 6.22; versões antigas como MDK 5.24, que incluem 6.7, não compilam: os cabeçalhos CMSIS 6 exigem ≥ 6.10 e podem resultar no erro `cmsis_clang.h` não encontrado) e o pacote do dispositivo `STM32G031F8Px`.
3. Pressione **F7** para compilar; `Build/imu_to_dxl.hex` é o arquivo para gravação e `.axf` é usado para depurar o código-fonte com breakpoints.
4. Em Debug → Settings, selecione seu J-Link e confira SWD, o algoritmo de Flash de 64 KB do STM32G0xx e Run to main.
   `JLinkSettings.JLinkScript` define a velocidade de transferência em **100 kHz** após conectar e reiniciar; mantenha esse arquivo.
   A primeira placa apresentou falhas de transferência ao baixar a 4 MHz. Na primeira conexão, recomenda-se começar pelos 100 kHz já validados.
5. Pressione **Ctrl+F5** para iniciar a depuração e parar em `main`; **F10** avança sobre a instrução, **F11** entra nela e **F5** executa.
   A pausa altera o tempo de amostragem e do barramento; em testes contínuos de comunicação, execute em velocidade total.

A configuração ST-LINK original de `MDK-ARM/imu_to_dxl.uvprojx` foi mantida. Ao trocar para J-Link, selecione novamente a sonda em Debug → Settings.

### VS Code

Abra esta pasta no VS Code para editar o código-fonte e execute o comando de compilação abaixo no terminal integrado.
Este fluxo usa VS Code para edição e Keil para compilação e depuração de hardware; não é necessário instalar CubeMX, CubeIDE ou GCC para compilar.
O código-fonte inclui os cabeçalhos CMSIS necessários e o driver ST do IMU; a primeira compilação não precisa baixar dependências da Internet.

Também é possível executar no terminal PowerShell deste diretório:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1
```

O caminho padrão do compilador `E:\Keil_v5\ARM\ARMCLANG` é apenas um exemplo. Em outro computador, use `-ToolchainRoot` para indicar uma instalação licenciada do Arm Compiler.
Os arquivos temporários de compilação ficam em `Build` neste projeto; cada software continua gerenciando as licenças do sistema operacional e das ferramentas instaladas.
A compilação substitui o firmware pré-compilado em `Build`; se quiser manter a versão validada pela página Web, preserve o artefato original antes.

## 2. Conteúdo do projeto

| Arquivo | Conteúdo |
|---|---|
| `Core/Inc/board_config.h` | Opções da placa, clock, baud rate e velocidade SPI centralizados |
| `Core/Src/board.c` | Clock, GPIO, SPI, USART, SWD, bases de tempo em ms/µs e watchdog |
| `Core/Src/imu.c` | Verificação de identidade, leitura de retorno da inicialização, FIFO, aceleração/giroscópio brutos, SFLP e novas tentativas após falhas |
| `Core/Src/protocol.c` | Escravo Feetech SCS/STS: análise de quadros (ressincronização por checksum), respostas às instruções, enfileiramento sync_read e temporização das respostas |
| `Core/Src/control_table.c` | Bloco de 15 bytes no endereço 56, bits de estado e registradores de diagnóstico |
| `Core/Src/main.c` | Agendamento do loop principal, comandos seriais e logs de estado |
| `Drivers/` | Código-fonte ST/CMSIS e licenças em versões fixas |
| `MDK-ARM/` | Projeto Keil, layout de linkedição e script de conexão lenta J-Link |
| `Tests/` | Testes de protocolo, sensores simulados e registradores que rodam sem placa; `bus_sim_test.py` compila o código real do protocolo como DLL e valida em um barramento simulado |

Não usa alocação dinâmica, RTOS ou HAL. O código da placa usa as definições oficiais de registradores CMSIS da ST; o sensor usa o driver oficial independente de plataforma.
A recepção do barramento externo no STM32 usa uma fila circular acionada por interrupção, que guarda o horário de chegada de cada byte; protocolo, amostragem e formatação dos logs são executados no loop principal.
O envio dos logs usa outra fila acionada por interrupção e não bloqueia a recepção do barramento.

## 3. 默认HardwareConfiguração

| 功能 | 芯片引脚 / Configuração |
|---|---|
| MCU | STM32G031F8P6，TSSOP20，64KB Flash / 8KB RAM |
| 系统时钟 | HSI16 → PLL，M=1、N=8、R=2，64MHz，Flash 2 wait states |
| 外部时钟选项 | `BOARD_USE_HSE_BYPASS=1`，X1 16MHz 有源时钟接封装脚2；启动失败退回 HSI 路线并记录状态 |
| IMU SPI | SPI1 mode3、8bit、Software CS；64MHz Inferior 2MHz；PA4=CS、PA5=SCK、PA6=MISO、PA7=MOSI |
| IMU INT | 首版轮询 FIFO，PA0/封装脚15 em 断信号暂不使用 |
| 总线串口 | USART2，PA2=TX、PA3=RX，AF1，1Mbps、8N1；不启用 USART 单引脚 HDSEL |
| 总线 DE | PA1 → U3.1 `1OE#`，**低有效**；GPIO 控制，等 USART TC 后才释放 |
| 总线 RX_EN | PB7 → U3.7 `2OE`，**高有效**；发送期间关闭、PA3 上拉；同封装脚 PB8 保持模拟输入 |
| 调试串口 | USART1，PA9/PA10 经 SYSCFG 重映射到封装脚16/17，115200、8N1；`BOARD_LOG_UART_SWAP=0` |
| SWD | PA13=SWDIO、PA14=SWCLK，Preservado复位默认Depuração功能 |
| 看门狗 | 默认开启，约2秒，LSI 误差影响实际时长；Depuração器暂停时冻结 |

PLL Inicialização异常时会Preservado HSI16 Execução，串口 BRR e计时器按实际主频计算。此时 SPI 也降为 0.5MHz，
Serviço延迟会增加，属于故障诊断模式，应Verificação时钟状态，不作为Concluído性能验收 de Configuração。

### J3 Fiação必须以[Princípio图 PDF](../imu_to_dxl-Princípio图.pdf)e实板Rede为准

| J3 脚号 | 最新Princípio图信号 | 接法 |
|---|---|---|
| 1 | GND | J-Link/ST-LINK/USB-TTL 共地 |
| 2 | SWDCLK | J-Link/ST-LINK SWCLK |
| 3 | SWDIO | J-Link/ST-LINK SWDIO |
| 4 | UART_RX，U1封装脚17 | USB-TTL TX，3.3V 电平 |
| 5 | UART_TX，U1封装脚16 | USB-TTL RX，3.3V 电平 |
| 6 | 3.3V | Depuração器电压参考；不要把 5V 接到aqui |

J3  de  SWD 四根线使用 **1、2、3、6** 脚；不要将旧 de 四针排线整排插到1–4脚，
第4脚是串口输入，不能当作供电或电压参考。首次Superior电先按焊盘/EDA Rede核实。
J3 没有引出 NRST；如需 under-reset Conexão，需在实际 NRST 测点另接。
Depuração器若带Alimentação输出，不要 e 另一Alimentação盲目并联；先确认它是 VTref 输入还是Alimentação输出。

J1/J2：1=GND、2=VDD_BUS、3=DATA；J4/J5：1=DATA、2=VDD_BUS、3=GND。
总线Testeé necessário单线半双工 USB 适配器；普通 USB-TTL 仅usado para J3 日志。

## 4. IMU 行为

- WHO_AM_I 应为 `0x70`。软件复位后按步骤配置，并回读 ODR、量程及 SFLP 使能。
- 加速度 ±4g，0.122mg/LSB；陀螺仪 ±500dps，17.5mdps/LSB。
- 加速度、陀螺仪、SFLP e FIFO 批处理均为120Hz，供50Hz主控Leitura。
- FIFO 按标签区分加速度、陀螺仪e四元数；每轮最多16条，不假设三者在同一条记录 em 。
- 初始化、SPI 失败、FIFO 溢出或数据过期时 `ready=0`；约1秒后自动重试。
- gyro 或 quaternion 任一超过100ms未Atualização即失效。即使主循环忙、未执行采样轮询，Leitura快照也会再次Verificação年龄。
- Leitura接口保持一致快照，不在 em 断里Atualização姿态。传感器Instalação旋转留给主控，避免 e Oficial坐标变换重复。
- 本版不保存实测偏置；SFLP 从Superior电默认状态开始估计。六轴姿态不提供绝对航向参考。

合法的单位姿态 `xyz=0,0,0` 与上游全零“未就绪”哨兵重合。已收到有效 FIFO 姿态时，仅将 x 的半精度
编码设为 IEEE 负零 `0x8000`，数学数值仍为0；真正未就绪始终返回全零。详见驱动说明和回归测试。

**运行时故障处理边界：** 已检查的官方主控在收到全零姿态后可能保留上次姿态，其 `ready()` 不会因此自动撤销。
正式站立/运动联调前，主控应额外读取本版诊断 `ready`、采样计数和年龄，并执行失效处理。
本版 PC 采集脚本已经Leitura这些字段；不能把“单板返回全零”当作整机已经具备自动停车行为。

## 5. 通信 e 寄存器

帧格式 `FF FF ID LEN INSTR 参数… CHK`，`CHK = ~(ID+LEN+INSTR+Σ参数)`，没有字节填充，所以载荷里也会出现 `FF FF`：接收按长度收完再验校验和，校验错就丢一个字节重新找帧头，不会被载荷里的假帧头带偏。逐条行为见[总线协议 §8](../总线协议.md#8-其它指令怎么应答)：

| 指令 | 行为 |
|---|---|
| `SYNC_READ 0x82`（广播） | 自己在列表第 k 位：k=0 收完指令 50 µs 后发；k>0 等前面 k 个设备的应答帧（ID 在前面、长度对、第 5 字节不是指令码），前面有设备 1 ms 不出声就当它不在线跳过 |
| `PING` / `READ`（单播） | 回状态帧 / 数据，ERROR 恒为 0；广播 PING 不答 |
| `WRITE` / `REG_WRITE`（单播） | 回 ACK，内容一概忽略（主控从不写这块板） |
| `ACTION` `0x06` `0x09` `0x0A` `0x0B`（单播） | ACK，不动作 |
| `REBOOT 0x08` | 不答，真重启 |
| `SYNC_WRITE`、别的广播 | 不答 |

时序（全是推断值，待实测，见总线Protocolo §5/§12；50 µs 是Protocolo逻辑里 de 数，加Superior解析e组包 de  CPU 时间后真实值要逻辑分析仪量）：T_resp 50 µs；帧内字节间隙超过 500 µs 丢弃残帧；排队时总线静默 1 ms 认为前一个设备不在线；等不到轮次 25 ms 放弃；到点后晚 2 ms 还发不出去就放弃，避免在Inferior一笔事务里抢总线。发送前再次原子Verificação新到达 de  RX Dados、USART BUSY e故障标志；忙时放弃这次应答。
接收 em 断里只有**溢出（ORE）**才当总线故障清空收包；噪声 / 帧错标志只计数，字节照收，错了由校验e丢掉 —— 0.1.0 一律清空，一个字节带噪声标志就会把整条 sync_read 扔掉、这一 tick 15 颗Servo跟着丢（0.2.0 审查后改）。

**把 ID200 放在 Sync Read 列表第一位**，与官方 `bus.rs` 相同；放中间也能答（排队规则），但前面的设备缺席时主控侧的解析会错位，见总线协议 §2。

多字节字段全部小端。

| 地址 | 字节数 | Conteúdo / 权限 |
|---|---:|---|
| 0 / 1 | 各1 | FirmwareVersão 0.2（主.次），不冒充Servo de  3.46 |
| 2 | 1 | END = 0（小端） |
| 3 | 2 | 自定义型号 `0x4D44` |
| 5 / 6 / 8 | 各1 | ID 200 / 波特率 0（1Mbps）/ 应答状态级别 1 |
| **56** | **15** | **主控每 tick 读 de 块**：gyro XYZ（int16，17.5 mdps/LSB）、四元数 XYZ（binary16）、采样计数（u8）、状态位、Preservado 0。original轴序，不做坐标变换 |
| 124 | 6 | gyro XYZ，三个 int16，±500dps（诊断，跟块里同一份） |
| 130 | 6 | quaternion XYZ，三个 IEEE binary16；W由主控重建 |
| 136 | 6 | original加速度 XYZ，三个 int16，±4g |
| 142 | 1 | 姿态采样计数低8位 |
| 143 | 1 | bit0=ready、bit1=configured、bit2=error |
| 144 / 145 | 各1 | WHO_AM_I / 错误码 |
| 146 / 147 | 各1 | 时钟状态 / 看门狗开关 |
| 148 / 152 / 156 | 各4 | 姿态 / gyro / accel 采样计数 |
| 160 / 164 / 168 | 各4 | uptime_ms / gyro年龄ms / 姿态年龄ms |
| 172 / 176 / 180 / 184 | 各4 | SPI错误 / FIFO溢出 / 非法四元数 / 恢复次数 |
| 188 / 192 / 196 / 200 | 各4 | RX队列溢出 / UART错误（噪声/帧错/溢出都计）/ 校验e错误 / 非法包 |
| 204 / 208 / 212 / 216 | 各4 | 收包超时 / 有效收包数 / 实际发包数 / 取消应答数 |
| 220 / 224 / 228 / 232 | 各4 | RCC复位原因原值 / 主频Hz / TX超时 / 日志丢弃数 |
| 236 | 1 | este projeto诊断寄存器表Versão 2（飞特Protocolo，块在 56） |
| 240 | 4 | sync_read 排队时判定前面设备不在线、跳过 de 次数 |
| 244 | 4 | 发送前检测到总线忙而放弃应答 de 次数 |

其余 0~255 地址读为 0；写一律 ACK 但不生效（重新初始化 IMU 改用 J3 日志串口的 `r` 命令）。56~70 是主控接口；124 及之后是**本项目自定义诊断扩展**，不宣称与舵机的电压/温度寄存器兼容。

块里 de 状态位（byte 13）：BIT0 融合没就绪（四元数全 0）；BIT1 跟 IMU 通信Falha（SPI/复位超时/Configuração/Dados过期/FIFO）；BIT2 自检Falha（WHO_AM_I 不对）；BIT3 两次读块之间刷新了 4 次以Superior（120 Hz 采样、50 Hz 读每次正常 2~3 次）。
错误码见 `imu.h`：0正常、1启动、2SPI、3身份、4复位超时、5配置、6过期、7FIFO、8四元数。
时钟状态：0=HSI PLL、1=HSE PLL、2=HSEFalha回退HSI PLL、3=PLLFalhaHSI16、4=切换Falha回退。

## 6. 板到后 de 顺序

1. 核实HardwareVersão、J3方向 e Alimentação，先单板限流Superior电，Verificação3.3V、短路、发热e复位。
2. SWD识别 STM32，Baixar HEX，确认 main 可断点、复位e断电重启都可Inicialização。
3. 接 J3 日志串口，115200/8N1。应有Versão信息；每秒输出 ready、id、错误eDados。
   `s`打印状态，`l`切换周期日志，`r`重新初始化IMU，`?`查看帮助。
4. Verificação WHO_AM_I=0x70、ready=1、采样计数增长，翻面/转动三轴核对加速度 e 姿态方向。
5. 只接 IMU 的总线（URT-2 等半双工适配器），运行 `python tools/imu200/imu200.py check --port COMx --only-imu`（只问 200），再接舵机跑完整的 `check`。
6. 用逻辑分析仪Verificação1Mbps、DE极性、最后停止位后释放、RX恢复 e 最坏回复延迟。
7. 接入一个Servo，再接Completo总线；ID200放第一。记录错误、丢包、FIFO e 采样年龄。
8. Concluído主控失效处理eInstalação方向核对后，再进行支撑状态Inferior de 整机联调。

### 电脑验收Ferramentas

总线验收用 [`tools/imu200/imu200.py`](../../../tools/imu200/imu200.py)（0.1.0 的 `Tools/imu_probe.py` 说的是 Dynamixel 协议，已随协议更换删除）。需要 Python 3.10+ 和 pyserial：

```powershell
python tools/imu200/imu200.py check --port COM5   # 13 项逐条 PASS/FAIL，判据照主控源码
python tools/imu200/imu200.py demo                # 不接硬件，看假小板怎么答
```

把 COM5 替换为**半双工总线适配器**端口；J3日志口不能响应这些协议指令。日志落在 `tools/imu200/logs/`（原始收发十六进制 + 每帧一行 JSONL）。
é necessárioInstalação可Execução de  Python，Windows 应用商店入口占位符不能Execução这些脚本；编译Firmware本身无需 Python。

## 7. Validação e 已知限制

Teste代码使用实际 C 编译器Execução；SPI/FIFOTeste用模拟寄存器e时间，不等同于芯片实测。
安装 MSVC 后，在其 **x64 Native Tools Command Prompt / Developer PowerShell** 中运行 `Tools/test.ps1` 重复主机测试。
该入口要求 `cl` 已在 PATH 中；可传 `-PythonExe` 指定自己的 Python。单独运行两份 C 测试 `.cmd` 时，
也可将自己的 `vcvars64.bat` 完整路径作为第一个参数。测试脚本不会安装编译器，也不连接硬件。
当前验证记录见 `VALIDATION.md`，第三方源版本见 `DEPENDENCIES.md`。

待实板确认：Alimentação e 装配、HSI波特率误差、SPI模式/边沿/片选时序、TX使能时序、总线Eletrônica电平、
FIFO实际Atualização率、SFLP初始收敛e坐标方向、温漂、看门狗恢复 e 长时间共线Execução。
SoftwareTestepor meio de不能替代这些验收。

## 8. 资料依据

- [本板硬件](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [STM32G031数据手册](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [LSM6DSV16X数据手册](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [ST IMU驱动](https://github.com/STMicroelectronics/lsm6dsv16x-pid)
- 飞特《SCS 通信协议》与内存表：仓库 [`docs/飞特资料/`](../../../docs/飞特资料/)
- [本板总线Protocolo（接口契约）](../总线Protocolo.md)
- [所检查的上游主控接口](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)

este projeto新写代码按 MIT Licença提供；TerceiroArquivoPreservado各自版权eLicença，见各 Drivers Diretório。
