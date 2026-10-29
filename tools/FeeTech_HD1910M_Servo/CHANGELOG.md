# Atualização日志（CHANGELOG）

本Arquivo记录 HD1910M ServoTesteFerramentas de 所有重要变更。

## [0.2.0] - 2026-10-03

Autor：漂移菌

本次Atualização de 主线：**补齐 e 飞特 FD DepuraçãoSoftware对标 de "零位校准"e"活动区间限制"能力**，
并在 microduck 实机（15 颗 HD-1910，Firmware 3.46）SuperiorConcluído全量Validação。

### 新增功能

#### 1. 零位校准 `zero`（0x0B 位置校准指令）—— 核心新增

等同飞特 FD DepuraçãoSoftware de "设置零位/ em 位校准"按钮：把Servo**AtualMecânica位置**标定为指定读数
（默认 em 位 2048），Servo自动计算并修改 31 号位置偏移寄存器。

> 为什么不能用老办法：HD-1910（HLS 系Firmware ≥3.43）**não suporta**"扭矩开关写 128" de  em 位校准
> （写了回"Sucesso"但偏移寄存器Inalterado）。0x0B 是本机型唯一正确 de 校准指令。

使用方法（装机时逐颗操作）：

```bash
feetech-HD1910M-tester torque off      # 1. 松轴
# 2. 用手把关节摆到机械零位并扶住（中间别等待，重力会压偏）
feetech-HD1910M-tester zero            # 3. 校准：当前位置 → 2048，自动掉电保存
feetech-HD1910M-tester torque on       # 4. 恢复扭矩
feetech-HD1910M-tester zero --to 1024  # 也可以标定为任意读数（0~4095）
```

Comando内部流程：读校准前位置 → 解锁 EPROM → 发 0x0B → 重新Superior锁 → 延时 →
**回读"Atual位置 + 位置偏移"双重确认**（偏差 >4 个单位即报错）。
因为飞特对não suporta de 操作也可能回"Sucesso"，一切以回读为准。

#### 2. 重启命令 `reboot`（0x08）

等效断电重Superior电：SRAM 从 EPROM 重新加载。usado para**不物理断电**Validação EPROM Gravação是否落盘
（robotd 更换Servo流程用 de 也是这条指令）。

```bash
feetech-HD1910M-tester reboot          # 重启后等约 1 秒再通信
```

验证 EPROM 落盘的技巧：先写一个 SRAM 标记值（如 `torque-limit 300`）→ `reboot` →
读回发现恢复为EPROM/Superior电默认值（1000），即证明重启真实发生，此时 EPROM 项读回什么就是什么。

#### 3. Protocolo层新增指令

`Instruction::Reboot = 0x08`、`Instruction::ResetTurns = 0x0A`（多圈圈数重置）、
`Instruction::Calibrate = 0x0B`，附组包单元测试。

### 功能增强

#### `limits` 活动区间限制（9/11 号最小/最大角度）

- 新增 `--deg`：直接按角度输入，如 `limits 90 270 --deg --save`（0~360° 对应 0~4095）
- 新增交叉校验：`min >= max` 直接拒绝；多圈模式的 `0 0` 特判放行
  （原来会被 max-angle 名义Inferior限 1 误拒）
- `--save` 改为**一次解锁/上锁写两个寄存器**（EPROM 往返减半），
  且任何一步Falha都保证重新Superior锁
- Gravação后**回读确认**并按角度显示

```bash
feetech-HD1910M-tester limits 1024 3072 --save   # 原始值：中位 ±90°
feetech-HD1910M-tester limits 90 270 --deg       # 角度值：只改内存，调试用
```

### 修复

- **`set --defer` 异步写之前跳过范围校验**：越界值会被直接编码发出。现在所有写入路径
  （`write_reg` / `sync_write` / `set --defer`）统一走 `Register::check_value()`。

### 内部改进

- `Register::check_value()`：范围校验从三处重复代码收敛为一处
- `ServoError::Malformed` 改为携带 `String`，可报告动态错误信息
- 简化 `pid` 命令中的冗余分支
- 新增单元Teste：0x0B 组包、check_value 边界（共 8 个Teste全过）

### 实机Registro de validação（microduck，15 颗 HD-1910，Firmware 3.46）

- **0x0B 校准实测**：位置 2958（+80°）→ 校准后精确 2048，偏移寄存器自动Gravação 910
  （= 2958−2048，实测确认偏移语义为"反馈值 = original值 − 偏移量"），掉电保存
- **0x08 重启实测可用**（项目文档"台架待验"事项pode划掉）
- **15 颗全量验收**：ID 表（10-14/20-24/30-34）、Firmware 3.46、字节序 0、波特率 1M、
  应答级别 1、模式 4、电压窗口 4.0~10.0V、卸载条件 13（电压+过热+过流）全部达标；
  各关节读数 e 站姿目标偏差 ≤4 个单位

---

## [0.1.0] - 初始Versão

- FT-SCS ProtocoloCompleto实现：PING / READ / WRITE / REG WRITE / ACTION / SYNC WRITE / 恢复出厂
- 覆盖官方 HLS_2 内存表全部寄存器的 `dump` / `get` / `set`（支持键名/十进制/十六进制地址）
- `scan` 总线扫描、`monitor` 实时监控（位置/速度/负载/电压/温度/电流）
- `goto` / `angle` / `swing` 运动控制，`torque` / `torque-limit` / `goal-current` 力控
- 三环 PID 调参（`pid`）、保护参数（`protect`）、ID/波特率设置（`set-id` / `set-baud`）
- EPROM 锁存机制（`lock` / `--save`）：解锁→写入→上锁，保护 EPROM 寿命
