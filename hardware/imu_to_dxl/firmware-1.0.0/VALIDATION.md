# FirmwareRegistro de validação

对象：**imu_to_dxl 1.0.0（飞特 FT-SCS 版）/ STM32G031F8P6 + LSM6DSV16X**。
Validação日期：2026-09。含主机Teste、实际编译Gravação e 实机共线Teste。
本版已从 Dynamixel 2.0 完全迁移到飞特 FT-SCS，旧版记录不再适用。

## 1. 编译

| 项目 | Resultado |
|---|---|
| ArmClang（Keil MDK，C:\Keil_v5）CLI 构建 `Tools/build.ps1` | 成功，0 错误 |
| Keil 工程 | 仅保留 DAP 一套 `MDK-ARM/imu_to_dxl_dap.uvprojx` |
| Flash（Code + RO + RW） | **10,920 / 65,536 字节**（10.66 KB） |
| RAM（RW + ZI，含 2 KiB 栈） | **5,092 / 8,192 字节**（4.97 KB） |
| 构建产物 | `Build/imu_to_dxl.hex/.bin/.axf/.map` + `imu_to_dxl.build.json`（含 SHA256） |
| 烧录 | OpenOCD + CMSIS-DAP，`program ... verify reset exit`，verify OK |

注：UV4 Comando行Gravação会假Sucesso（退出码 0 但未实际擦写），Gravação以 OpenOCD 为准。

## 2. 无Hardware主机Teste

`Tools/test.ps1`（gcc，WinLibs mingw64）实际执行并通过：

| Teste | Resultado | 主要覆盖 |
|---|---|---|
| `Tests/protocol_test.c` | **93 checks，0 failures**（proto_context 1104 字节） | 飞特组帧/校验向量（PING、READ 56/12）、PING/READ/WRITE、广播 PING 静默、SYNC READ 首位立即答、非首位嗅探前位合法帧后答、前位缺失 25ms 超时跳过、新主机帧作废、畸形/字节超时恢复、LEN 边界与噪声重同步、只读区保护 |
| `Tests/control_table_test.c` | **18 项通过** | 小端编码、gyro/fp16/加速度打包、flags/whoami、诊断块 24 字映射、越界、0..9 只读、84 marker、240=0xA5 |
| `Tests/imu_test.c` | **16 场景通过** | WHO_AM_I 错误、配置回读失败、FIFO/SFLP、fp16 边界（负零哨兵）、数据冻结判 stale、自动恢复、无 poll 快照过期 |
| `Tests/probe_test.py` | **9/9 通过** | 探针帧构造、56/40 + 90/96 块解码、24 项诊断字段名、非法姿态处理 |

## 3. 实机通信Teste

环境：半双工适配器 COM6（1Mbps）；IMU ID=200；飞特Servo ID 2、3（Firmware 3.46，8.0V）。

| Ferramentas / 场景 | Resultado |
|---|---|
| `imu_probe.py` 单播轮询（56/40 + 90/96 诊断块） | **249/250**（唯一 1 次瞬时超时，0.4%），退出码 0 |
| `imu_probe.py --sync`（单 ID 广播 SYNC READ） | 正常，全部 ready=1 |
| `imu_monitor.py` 50Hz SYNC READ 56/12（列表 [200]） | **251/251，零校验错误、零超时** |
| `bus_monitor.py --no-demo`（一条 SYNC READ 读 [2,3,200]） | **598/598 = 100%** |
| `bus_monitor.py` demo（SYNC READ + 广播 SYNC WRITE 目标位置） | **741/741 = 100%，无逐写回退** |
| `servo_tool.py scan/read/test/write` | 舵机与 ID200 识别正常（model=0x4D44, fw=1） |
| 退出自动关扭矩 | 正常（对 demo 使能过 de Servo写 40=0） |

## 4. SYNC READ 排位实测（关键结论）

30 轮 × 多种 ID 排序（飞特ServoFirmware 3.46，1Mbps）：

| SYNC READ 列表 | IMU 应答 | 结论 |
|---|---|---|
| `[200,2,3]`（IMU 首位） | **3/30** | 舵机在前帧起点 +180µs 预测发送，撞 IMU 校验和字节 |
| `[2,200,3]`（中位） | 30/30 | 嗅探 ID2 合法帧后应答 |
| `[2,3,200]`（末位） | 30/30 | 嗅探 ID3 合法帧后应答 |
| `[200]`（单独） | 30/30 | 无碰撞 |

结论固化为硬规则：**主机必须把 200 排在Servo之后或单独成组，禁止首位。**
50Hz 周期 20ms，三设备总线占用约 650µs（Por favor求 ~110µs + 每应答 ~180µs），裕量 3.3%，
瓶颈是Eletrônica碰撞而非时间预算。

## 5. 板级观察

- 开机日志横幅 `imu_to_dxl 1.0.0 | STM32G031F8 | FT-SCS ID=200 1000000 8N1`；
  周期状态行 `ready=1 id=0x70 ... ck=0`，陀螺/四元数随手部转动变化。
- DAP-Link CDC 日志（COM5，115200）必须 DTR+RTS 拉高才有输出。
- 长稳Execução期间 spi/fifo/uart/checksum 等诊断计数不增长（详见诊断块 90..185）。

## 6. Teste de 边界

主机 C Teste使用模拟寄存器/时间桩，不等同芯片实测；实机通信Teste覆盖了
共线排位、读写 e  demo 联动，但未覆盖：长时间（小时级）连续Execução、极端温度/电压、
整机负载Inferior de 姿态联调、SFLP 偏置 e 温漂。正式运动联调前仍应按Instruções de uso第 5 节执行Completo验收，
并由主控结合 ready/采样计数/年龄实现失效停车。
