# sts3215Servo_testtool — STS3215 Servo Rust TesteFerramentas

用 Rust por meio de USB 转 TTL 转接板Controle飞特（FEETECH）STS3215 总线Servo de 学习/Teste项目。
Protocolo为自己实现 de 最小版 STS/SCS 串口Protocolo，代码集 em 在两个Arquivo：

- `src/sts.rs` — 协议库：帧打包/校验、ping、读写寄存器、状态解析（`ServoStatus`）
- `src/main.rs` — 命令行工具：扫描、读取信息、运动、单个测试、批量测试

## HardwareFiação

```
USB 转接板(如飞特 URT-1 / Waveshare Bus Servo Adapter) --TTL--> STS3215 舵机
舵机需要独立供电（7.4V 版本用 7.4V，12V 版本用 12V），不要从 USB 取电！
```

默认串口 `/dev/ttyUSB0`，默认波特率 1,000,000（STS3215 出厂值）。

## 常用Comando

```bash
source ~/.cargo/env          # 首次使用加载 cargo 环境
cargo build --release        # 编译
cargo run -- scan                       # 扫描总线上的舵机（带进度条）
cargo run -- info 1                     # 读 ID=1 舵机的位置/电压/温度/电流/负载
cargo run -- read 1 42 2                # 读任意寄存器：ID=1 地址42起2字节(十六进制)
cargo run -- move 1 2048                # ID=1 转到中位 2048
cargo run -- move 1 3072 --speed 800    # 指定速度转动
cargo run -- test 1                     # 完整测试 ID=1：位置扫描+电流/负载采样
cargo run -- test-all                   # 扫描并批量测试所有舵机，输出汇总表
cargo run -- raw 1                      # 底层诊断：打印原始收发字节
cargo run -- set-id 1 2                 # 把 ID=1 改成 ID=2（总线上只能接这一个！）
cargo run -- --port /dev/ttyUSB1 scan   # 指定串口
cargo run -- --baud 115200 scan         # 指定波特率
```

## Comando示例 e 实际效果

以Inferior输出均在 树莓派 5 + 飞特Oficial转接板(CH340) + STS3215(7.4V 版, ID=1) Superior实测。

### scan —— 扫描总线

```bash
$ cargo run -- scan
扫描中 [##############################] 254/254  已发现 1 个
  ID   1  在线  型号=777  电压=7.4V (范围 4.0~8.0V)  温度保护=70°C
共发现 1 个舵机。
```

电压超出"范围"时（比如误接 9V），Instruções触发了过压/欠压报警，Servo LED 会闪烁。

### info —— Leitura实时状态

```bash
$ cargo run -- info 1
舵机 ID 1:
  位置     : 2049 / 4095   (180.1°)
  速度     :    0 步/秒
  负载     :  0.0 %
  电压     :  7.4 V
  温度     :   30 °C
  电流     :    0 mA
  运动中   : 否
```

有报警时会多一行 `⚠ 报警 : 状态码 0x01`（bit0=电压异常）。位置换算：4096 步 = 360°。

### move —— 转到指定位置

```bash
$ cargo run -- move 1 2048 --speed 1000
舵机 1 -> 目标 2048，等待到位...
到位: 当前位置 2049 (180.1°)
```

- `pos`：目标位置 0~4095（2048 是中位）
- `--speed`：步/秒，越大越快；`--time ms`：期望耗时，0 表示不限
- 实测定位精度：偏差 ≤1 步（约 0.09°）

### test —— 单个ServoCompletoTeste

```bash
$ cargo run -- test 1
== 测试舵机 ID 1 ==
  型号=777  电压=7.4V  温度=30°C  位置=2049
  目标 2048 -> 实际 2049  偏差   1  OK
  目标 1024 -> 实际 1025  偏差   1  OK
  目标 3072 -> 实际 3072  偏差   0  OK
  目标 2048 -> 实际 2049  偏差   1  OK
-- 报告: 舵机 1 --
  型号=777  电压=7.4V  温度=30°C
  峰值电流=84mA  峰值负载=38.8%  最大位置偏差=1
  结果: ✅ PASS
```

### test-all —— 批量Teste（多Servo）

接多个Servo时 de 效果示意（每个Servo先各自输出一份Completo报告，最后汇总）：

```bash
$ cargo run -- test-all
扫描中 [##############################] 254/254  已发现 2 个
发现 2 个舵机: [1, 2]
... (每个舵机各输出一份 test 报告) ...
==== 批量测试汇总 ====
ID   型号     电压V    温度°C  峰值电流mA   峰值负载%    位置偏差   结果
1    777      7.4      30      84          38.8        1        PASS
2    777      7.4      29      79          35.2        1        PASS
```

> 注：Superior面 ID=2 一行为示意Dados，实测时以你 de Servo实际读数为准。

### read —— 读任意寄存器（学习内存表用）

```bash
$ cargo run -- read 1 14 2
舵机 1 地址 14 起的 2 字节: 50 28      # 电压上限 0x50=80→8.0V，下限 0x28=40→4.0V
$ cargo run -- read 1 3 2
舵机 1 地址 3 起的 2 字节: 09 03       # 型号 = 0x0309 = 777 (小端序)
```

### raw —— 底层诊断（排查通讯问题）

```bash
$ cargo run -- raw 1
PING:
  发送: FF FF 01 02 01 FB
  收到: FF FF 01 02 01 FB               # 正常应答(error=01 表示有电压报警)
READ 状态区(地址56,15字节):
  发送: FF FF 01 04 02 38 0F B1
  收到: FF FF 01 11 01 EB 0F 00 00 ...  # 15 字节状态原始数据
```

"收到"为空 = Servo没应答（查供电/Fiação/波特率）； e 发送完全相同且无第二个包 = 转接板回显。

### set-id —— 修改Servo ID

```bash
$ cargo run -- set-id 1 2    # ⚠ 总线上只能接这一个舵机
ID 1 在线，准备修改为 2 ...
✅ 修改成功：ID 1 -> 2（断电重启后依然有效）
```

## 多Servo：先改 ID 再Superior总线

新Servo出厂 ID 都是 1，多个同 ID Servo接在同一总线Superior会**同时应答、互相冲突**
（扫描可能只显示 1 个，或一个都扫不到）。正确做法：

1. 总线Superior**只接一个**Servo
2. `cargo run -- set-id 1 2` 改成新 ID（EEPROM 操作：自动解锁→写入→锁定，断电不丢）
3. 断电，接SuperiorInferior一个，重复改为 3、4、...
4. 全部接好后 `cargo run -- scan` 应该能看到所有舵机，ID 各不相同

> ⚠ 注意：`set-id` 执行时如果总线上有多个同 ID 舵机，它们会被**一起**改成同一个新 ID。

## 实测记录

- 出厂默认：ID=1，波特率 1M，型号读数 777
- 供电务必匹配Versão：7.4V 版(C001)电压Superior限约 8.0V，接 9V 会触发**过压报警**（LED 闪烁、状态码 0x01）；12V 版(C018)则用 12V
- 位置精度实测：目标/实际偏差仅 1 步（约 0.09°）

## TesteConteúdo（test / test-all）

1. ping 应答 + Leitura型号
2. 基线读数：电压、温度、位置
3. 位置扫描： em 位 2048 → 1024 → 3072 → 2048，运动 em 每 20ms 采样一次
4. 统计峰值电流(mA)、峰值负载(%)、最大位置偏差
5. 判定 PASS/FAIL（电压异常、报警位、偏差超限、温升过大都会标出）

## 自己写Teste脚本

在 `main.rs` 里照着 `test_one()` 写即可，核心 API：

```rust
let mut bus = StsBus::open("/dev/ttyUSB0", 1_000_000)?;
bus.ping(1)?;                      // 是否在线
bus.move_to(1, 2048, 1000, 0)?;    // 转动：id, 位置, 速度, 时间
let s = bus.read_status(1)?;       // 一次读回全部状态
println!("{}V {}mA {}°C", s.voltage, s.current_ma, s.temperature);
bus.set_torque(1, false)?;         // 释放力矩（可手掰）
```

寄存器地址见 `sts.rs` 里的 `reg` 模块，完整定义查飞特《STS3215 串口协议手册》。

## 常见问题

- **权限拒绝**：`sudo usermod -aG dialout $USER` 后重新登录
- **扫描不到舵机**：检查供电（舵机灯是否亮）、波特率（`--baud 115200` 试试）、TX/RX 是否接反
- **校验e错误**：总线Superior有干扰或线太长，缩短线缆、Verificação接地
