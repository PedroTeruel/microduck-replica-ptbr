# servo-web 网页上位机使用说明

通过 RK3566 上的 servo-web 网页上位机，在电脑浏览器里实时查看 IMU 姿态和舵机状态。

---

## 1. 前提条件

| 项目 | 要求 |
|---|---|
| IMU 板固件 | 已烧录飞特 FT-SCS 协议固件 v1.0.0（ID=200，1Mbps） |
| RK3566 | servo-web 已克隆到 `/gitclone/microduck-replica/tools/servo-web/` |
| 总线串口 | `/dev/ttyS2`（RK3566 板载串口，直连 IMU 总线） |
| 网络 | RK3566 与电脑在同一局域网（wlan0 IP 如 `<鸭子 IP>`） |
| 浏览器 | Chrome / Edge / Firefox（需支持 WebSocket 和 ES Module） |

## 2. 启动服务

### 2.1 SSH 或串口登录 RK3566

```bash
# 通过 SSH（需已配置 SSH）
ssh root@<鸭子 IP>

# 或通过 USB 串口控制台（COM8 @ 1500000 baud）
# 用串口助手或 Python pyserial 连接，登录 root
```

### 2.2 停掉冲突服务

servo-web 和 robotd 会抢 `/dev/ttyS2` 总线，启动前必须先停 robotd：

```bash
systemctl stop robotd
```

### 2.3 启动 server.py

```bash
cd /gitclone/microduck-replica/tools/servo-web
nohup python3 server.py \
  --port /dev/ttyS2 \
  --imu-bus \
  --host 0.0.0.0 \
  --http-port 8080 \
  > /tmp/servo-web.log 2>&1 &
```

参数说明：

| 参数 | 含义 |
|---|---|
| `--port /dev/ttyS2` | 总线串口设备 |
| `--imu-bus` | 启用 IMU 总线模式（ID 200 跟舵机在同一条 sync_read 里读） |
| `--host 0.0.0.0` | 监听所有网卡（允许外部访问） |
| `--http-port 8080` | HTTP/WebSocket 端口 |
| `> /tmp/servo-web.log 2>&1 &` | 后台运行，日志写 /tmp/servo-web.log |

### 2.4 确认服务已启动

```bash
# 查看进程
ps aux | grep server.py

# 查看日志（应显示总线已打开、IMU 已启用）
tail -20 /tmp/servo-web.log
```

正常日志示例：

```
[总线] 打开 /dev/ttyS2 @ 1000000 8N1
[IMU] 总线 IMU 已启用：ID 200 跟舵机在同一条 sync_read 里读（有网页连着才轮询）
```

## 3. 网页访问

### 3.1 打开网页

在电脑浏览器访问：

```
http://<鸭子 IP>:8080/
```

> IP 地址以 RK3566 实际 wlan0 IP 为准，可用 `ip addr show wlan0` 查看。

### 3.2 页面结构

页面标题为「鸭子舵机调试台」，从上到下依次为：

1. **连接状态**：左上角绿点 = WebSocket 已连接
2. **舵机扫描区**：点击「扫描」按钮扫描总线设备
3. **舵机控制区**：扭矩开关、目标位置/速度滑块
4. **IMU 姿态面板**（`躯干姿态 · IMU`）：
   - 模式标签：`总线 · ID 200`
   - 状态标签：`等待数据` → `实时跟随`（收到有效数据后变绿）
   - 横滚 / 俯仰 / 偏航角度（度）
   - 采样数、读取频率（Hz）、参考电压（V）
   - 加速度 g（三轴）、角速度 °/s（三轴）
   - 错误计数：IMU / SPI / FIFO
   - 操作按钮：「当前姿态显示归零」「原始姿态」
   - 安装方向下拉框（可选不同安装方向）
5. **姿态管理区**：保存/加载/发送预设姿态
6. **3D 可视化区**：躯干姿态（按 IMU 四元数转）+ 关节姿态（按舵机位置转）
7. **日志区**：底部实时日志

### 3.3 开始查看 IMU 数据

**网页连上后会自动开始读取 IMU 数据，不需要额外设定。**

WebSocket 连接建立后，server.py 的轮询循环自动启动，每帧 sync_read 会带上 ID 200。
IMU 面板状态从「等待数据」变为「实时跟随」，角度和采样数据开始实时刷新。

### 3.4 验证 IMU 数据是否正常

在 IMU 面板中检查：

| 字段 | 正常值 | 异常排查 |
|---|---|---|
| 状态标签 | `实时跟随`（绿色） | 若显示「等待数据」/「数据无效」：检查 IMU 板供电、固件是否已烧录 |
| 模式标签 | `总线 · ID 200` | 若不显示 IMU 面板：确认 server.py 用了 `--imu-bus` 参数 |
| 横滚/俯仰/偏航 | 随板子转动而变化 | 数字不动：检查总线接线、/dev/ttyS2 是否被占用 |
| 采样数 | 持续递增 | 不递增：总线无应答，检查 IMU 板是否上电 |
| 读取 Hz | 30~60 Hz | 为 0 或极低：检查是否有其他进程占用总线 |
| 加速度 / 角速度 | 三轴有数值 | 全 `—`：validPacket 未通过，检查 ready/configured 字段 |

### 3.5 舵机操作（可选）

1. 点击「扫描」按钮，等待扫描完成（约 2 秒）
2. 在线舵机列表会显示在扫描区
3. 点击「扭矩开」使能舵机扭矩
4. 拖动滑块设置目标位置，或点击预设姿态按钮
5. 操作完毕点击「扭矩关」

> **安全提示**：扭矩开启后舵机有保持力，请先确认舵盘活动范围内无干涉。

## 4. 测试步骤

### 4.1 基础连接测试

1. 确认 IMU 板已上电、总线已连接到 `/dev/ttyS2`
2. 停掉 robotd：`systemctl stop robotd`
3. 启动 server.py（见第 2.3 节）
4. 查看日志无报错：`tail -20 /tmp/servo-web.log`
5. 电脑浏览器打开 `http://<鸭子 IP>:8080/`
6. 左上角绿点亮起 = WebSocket 连接成功
7. IMU 面板出现，状态显示「实时跟随」

### 4.2 IMU 数据验证

1. 静置 IMU 板，观察角度值稳定（横滚/俯仰接近 0°）
2. 缓慢倾斜板子，横滚/俯仰角应跟随变化
3. 水平旋转板子，偏航角应变化（注意：六轴偏航会漂移，属正常现象）
4. 采样数持续递增、读取频率在 30~60 Hz 范围
5. 错误计数（IMU/SPI/FIFO）保持 0

### 4.3 归零和原始姿态操作

1. 将板子摆到期望的「零位」姿态
2. 点击「当前姿态显示归零」—— 当前姿态设为 0°（仅影响页面显示，不写硬件）
3. 转动板子，角度相对零位显示
4. 点击「原始姿态」—— 切换回含安装方向的原始姿态显示

### 4.4 舵机联合测试

1. 点击「扫描」，确认舵机在线
2. 点击「扭矩开」
3. 拖动位置滑块，舵机应跟随运动
4. 同时观察 IMU 面板数据不受影响（IMU 与舵机同帧读取）
5. 测试完毕点击「扭矩关」

### 4.5 多设备同帧读取验证

1. 总线上接 IMU 板 + 1~2 个飞特舵机
2. 启动 server.py，打开网页
3. 扫描到 IMU（ID 200）+ 舵机
4. IMU 面板「实时跟随」+ 舵机位置数据同时刷新
5. 读取频率稳定（不因多设备而明显下降）
6. 日志无 ck_err / timeout 报错

## 5. 停止服务

```bash
# 查找进程 ID
ps aux | grep server.py

# 停止
kill <PID>

# 或一条命令搞定
pkill -f 'python3 server.py'

# 恢复 robotd（如果需要）
systemctl start robotd
```

## 6. 常见问题

| 现象 | 排查方向 |
|---|---|
| 浏览器打不开页面 | RK3566 是否开机、IP 是否正确、防火墙是否放行 8080 端口 |
| 左上角灰点（连不上） | server.py 是否在运行；`ps aux \| grep server.py` 确认进程 |
| IMU 面板不显示 | server.py 是否加了 `--imu-bus` 参数；日志是否显示「IMU 已启用」 |
| 状态显示「等待数据」 | IMU 板是否上电、总线接线是否正确、`/dev/ttyS2` 是否被 robotd 占用 |
| 角度全显示 `—` | validPacket 未通过：确认 imu_bus.py live 帧含 `ready=1, configured=1` |
| 采样数不递增 | 总线无应答：检查 IMU 板固件是否已烧飞特协议版、供电是否正常 |
| 读取频率为 0 | 没有网页连着（轮询只在有 WebSocket 客户端时启动）；或正在校准 |
| 扫描不到舵机 | 舵机供电是否正常（VDD_BUS）、ID 是否在扫描范围、总线接线 |
| 舵机不动 | 扫描后是否点了「扭矩开」、模式/速度寄存器是否正确 |
| 日志报 ck_err / timeout | 总线干扰、引线过长、终端电阻缺失；SYNC READ 列表 ID 200 是否末位 |
| `/dev/ttyS2` 被占用 | `fuser /dev/ttyS2` 查看占用进程，先 kill 或 `systemctl stop robotd` |

## 7. 飞特 FT-SCS 协议

### 7.1 帧格式

IMU 板使用飞特 FT-SCS（Feetech Servo Communication Serial）半双工总线协议，
与飞特 SCS/STS 舵机共线运行。所有帧使用相同格式：

```
请求帧：  FF FF  ID  LEN  INST  P1..Pn  CK
应答帧：  FF FF  ID  LEN  ERR   D1..Dd  CK
```

| 字段 | 说明 |
|---|---|
| `FF FF` | 帧头（2 字节，固定 0xFF 0xFF） |
| `ID` | 设备地址（1 字节；0xFE=广播，1~252=单播） |
| `LEN` | 长度（1 字节；= 2 + 参数/数据字节数） |
| `INST`/`ERR` | 指令码（请求方）/ 错误码（应答方） |
| `P1..Pn`/`D1..Dd` | 参数（请求方）/ 数据（应答方） |
| `CK` | 校验和（1 字节） |

帧总长度 = 4 + LEN 字节。

### 7.2 校验和算法

```
CK = ~(ID + LEN + INST/ERR + sum(P1..Pn/D1..Dd)) & 0xFF
```

- 对 ID 到最后一个数据字节的所有字节累加取低 8 位
- 取反后取低 8 位
- FF FF 帧头不参与校验和计算

固件实现（`protocol.c`）：

```c
uint8_t proto_checksum(const uint8_t *bytes, uint16_t length) {
    uint16_t sum = 0;
    for (uint16_t i = 0; i < length; ++i)
        sum += bytes[i];
    return ~(uint8_t)(sum & 0xFF);
}
```

### 7.3 指令集

| 指令码 | 名称 | 说明 |
|---|---|---|
| 0x01 | PING | 单播应答空状态帧；广播 PING 不应答 |
| 0x02 | READ | 读寄存器（addr u8, count u8）；单播 |
| 0x03 | WRITE | 写寄存器（addr u8, data...）；单播 ACK，广播静默 |
| 0x82 | SYNC READ | 广播读（addr, count, id...）；各 ID 按列表顺序依次应答 |
| 0x83 | SYNC WRITE | 广播写（addr, dlen, [id, data]...）；静默 |

IMU 板的身份寄存器（地址 0~9）只读，WRITE 会被拒绝返回 ERR_ACCESS(7)。
地址 85（user_marker）可写 1 字节，地址 240 写 0xA5 触发 IMU 重新初始化。

### 7.4 错误码

| 码值 | 名称 | 含义 |
|---|---|---|
| 0 | OK | 成功 |
| 1 | RESULT | 结果错误 |
| 2 | INSTRUCTION | 指令错误 |
| 3 | CRC | 校验和错误 |
| 4 | RANGE | 地址范围错误 |
| 5 | LENGTH | 长度错误 |
| 6 | LIMIT | 限制错误 |
| 7 | ACCESS | 访问错误（只读区写入、身份区写入等） |

### 7.5 SYNC READ 有序应答规则

SYNC READ 是广播指令，多个设备按 ID 列表顺序依次应答。IMU 板（ID=200）的
应答规则（`protocol.c`）：

1. **ID 200 在列表首位**（`i == 2`）：直接应答，但飞特舵机会提前开口导致冲突
   （实测仅 3/30 成功），**禁止这样排**
2. **ID 200 在列表中位/末位**：等待前一个 ID 的应答帧通过总线后，再发自己的应答
   （实测 30/30 成功）
3. **前驱无应答/校验错误**：IMU 板跳过本轮，避免总线冲突
4. **超时保护**：等待前驱超过 25ms（`PROTO_TRANSACTION_TIMEOUT_US`）自动取消

> **主机必须将 ID 200 排在舵机之后**（`[舵机ID..., 200]`）或单独成组（`[200]`）。

---

## 8. 寄存器定义

### 8.1 身份区（地址 0~9，只读）

| 地址 | 字段 | 值 | 说明 |
|---|---|---|---|
| 0 | 固件版本 Major | 1 | |
| 1 | 固件版本 Minor | 0 | |
| 2 | 字节序 | 0 | 0=小端 |
| 3-4 | 型号 | 0x4D44 | 低字节在前（3=0x44, 4=0x4D） |
| 5 | 设备 ID | 200 | 固定，不可写 |
| 6 | 波特率码 | 0 | 0 = 1,000,000 bit/s |
| 7 | 保留 | 0 | |
| 8 | 状态级别 | 1 | 返回错误码（非 0 时） |
| 9 | 保留 | 0 | |

### 8.2 快速块（地址 56~70，15 字节）

与飞特舵机状态块同址（56），一条 SYNC READ 56/15 同时读取 IMU 板和所有舵机。

| 偏移 | 地址 | 字段 | 类型 | 说明 |
|---|---|---|---|---|
| 0-1 | 56-57 | 陀螺仪 X | i16 LE | 量程 ±500 dps，17.5 mdps/LSB |
| 2-3 | 58-59 | 陀螺仪 Y | i16 LE | 同上 |
| 4-5 | 60-61 | 陀螺仪 Z | i16 LE | 同上 |
| 6-7 | 62-63 | 四元数 X | fp16 (binary16) | SFLP 格式，x 分量 |
| 8-9 | 64-65 | 四元数 Y | fp16 | SFLP 格式，y 分量 |
| 10-11 | 66-67 | 四元数 Z | fp16 | SFLP 格式，z 分量 |
| 12 | 68 | 采样计数 | u8 | SFLP 记录计数低 8 位，每帧 +1~4 |
| 13 | 69 | 状态位 | u8 bitfield | 见 8.3 |
| 14 | 70 | 保留 | u8 | 固定为 0，server.py 校验 |

四元数 w 分量不在总线上传输，主机重建：

```python
norm2 = x*x + y*y + z*z
w = sqrt(max(0, 1 - norm2))    # 若 norm2 > 1 则归一化 xyz
```

陀螺仪换算：

```python
gyro_dps = raw_i16 * 0.0175    # 17.5 mdps/LSB → dps
```

### 8.3 状态位定义（地址 69）

| 位 | 名称 | 值 | 含义 |
|---|---|---|---|
| BIT0 | FUSION_NOT_READY | 0x01 | 融合未就绪（四元数全 0 或刚上电） |
| BIT1 | IMU_COMM_FAIL | 0x02 | IMU 通信失败（SPI/复位/配置/FIFO/数据过期/四元数） |
| BIT2 | SELF_TEST_FAIL | 0x04 | 自检失败（WHO_AM_I 不符 = 0x70） |
| BIT3 | READER_TOO_SLOW | 0x08 | 主机读太慢（两次读之间 SFLP 刷新 ≥5 次） |

固件设置逻辑（`control_table.c`）：

```c
if (!s->ready || quat_fp16 全 0)      bits |= BIT0;  // 融合未出数
if (error 是 SPI/RESET/CONFIG/STALE/FIFO/QUAT) bits |= BIT1;  // 通信失败
if (error 是 ID)                      bits |= BIT2;  // 自检失败
if (sample_count 增量 >= 5)           bits |= BIT3;  // 读太慢
```

server.py 对状态位的处理：

| 状态 | server.py 行为 |
|---|---|
| BIT0 置位 | 帧 status="stale"（融合还没出数，刚上电约 0.5 秒内正常） |
| BIT1 置位 | 帧 status="error"（通信失败，检查焊接/接线） |
| BIT2 置位 | 帧 status="error"（自检失败，检查 IMU 芯片焊接） |
| BIT3 置位 | live 帧附加慢读提示，不影响数据有效性 |
| byte 14 ≠ 0 | 帧 status="error"（保留字节非 0，固件不符合协议） |

### 8.4 扩展区（地址 71~85）

| 地址 | 字段 | 类型 | 说明 |
|---|---|---|---|
| 71-76 | 加速度 X/Y/Z | i16 × 3 LE | 量程 ±4 g，0.122 mg/LSB |
| 77 | WHO_AM_I | u8 | LSM6DSV16X = 0x70 (112) |
| 78 | 错误码 | u8 | imu_error_t 枚举值 |
| 79 | 时钟状态 | u8 | |
| 80 | 看门狗使能 | u8 | |
| 81-84 | 采样计数 | u32 LE | SFLP 记录总数（全 32 位） |
| 85 | 用户标记 | u8 | 可写，RAM（断电丢失） |

### 8.5 诊断区（地址 90~185，96 字节）

24 个小端 u32 字，按顺序：

| 偏移 | 地址 | 名称 | 说明 |
|---|---|---|---|
| 0 | 90 | gyro_count | 陀螺仪采样总数 |
| 1 | 94 | accel_count | 加速度采样总数 |
| 2 | 98 | uptime_ms | 运行时间（毫秒） |
| 3 | 102 | gyro_age_ms | 距上次陀螺仪数据毫秒数 |
| 4 | 106 | quat_age_ms | 距上次四元数毫秒数 |
| 5 | 110 | spi_errors | SPI 通信错误次数 |
| 6 | 114 | fifo_overflows | FIFO 溢出次数 |
| 7 | 118 | invalid_quaternions | 无效四元数次数 |
| 8 | 122 | recovery_count | IMU 恢复次数 |
| 9 | 126 | rx_overflows | UART RX 溢出 |
| 10 | 130 | uart_errors | UART 错误 |
| 11 | 134 | checksum_errors | 协议校验错误 |
| 12 | 138 | malformed_packets | 畸形包数 |
| 13 | 142 | receive_timeouts | 接收超时 |
| 14 | 146 | rx_packets | 接收包数 |
| 15 | 150 | tx_packets | 发送包数 |
| 16 | 154 | cancelled_replies | 取消的应答数 |
| 17 | 158 | reset_flags | 复位标志 |
| 18 | 162 | clock_hz | 时钟频率 |
| 19 | 166 | tx_timeouts | 发送超时 |
| 20 | 170 | log_dropped | 日志丢弃数 |
| 21 | 174 | diag_revision | 诊断表版本（=1） |
| 22 | 178 | tx_busy_drops | 总线忙丢弃数 |
| 23 | 182 | reserved | 保留 |

---

## 9. 校验逻辑

### 9.1 固件侧校验（接收请求帧）

`protocol.c` 的 `proto_feed()` 逐字节接收，校验流程：

1. **帧头搜索**：等待 2 个 0xFF；额外 0xFF 容忍；非 0xFF 重置
2. **ID 校验**：0x00 和 0xFF 无效，重置
3. **LEN 校验**：LEN < 2 或 > 132（`PROTO_MAX_FRAME_LEN`）丢弃
4. **校验和校验**：`complete_packet()` 对 ID~倒数第二字节求校验和，
   与最后一字节比对；不匹配 → `checksum_errors++`，不执行指令
5. **指令校验**：参数数量、地址范围、SYNC READ ID 列表唯一性等

### 9.2 server.py 侧校验（解析 15 字节块）

`imu_bus.py` 的 `feed()` 对 ID 200 返回的 15 字节块逐项校验：

| 校验项 | 失败行为 | 对应状态 |
|---|---|---|
| block 长度 = 15 | 不会发生（sync_read 定长） | — |
| 保留字节 (offset 14) == 0 | status="error" | 固件不符合协议 |
| BIT2 (自检失败) 置位 | status="error" | WHO_AM_I 不符 |
| BIT1 (通信失败) 置位 | status="error" | SPI/复位/配置/FIFO |
| BIT0 (未就绪) 置位 或四元数全 0 | status="stale" | 融合未出数 |
| 前 12 字节连续 ≥8 帧完全相同 | status="stale" | 数据冻结 |
| 四元数 fp16 解码异常 | status="error" | 四元数无效 |
| 以上全通过 | status="live" | 正常数据 |

### 9.3 前端校验（显示数据）

`imu_attitude.js` 的 `validPacket()` 要求同时满足所有条件：

| 条件 | 说明 |
|---|---|
| `live === true` | 帧标记为 live |
| `status === "live"` | 状态字符串匹配 |
| `ready === 1` | IMU 就绪（固件 ready 标志） |
| `configured === 1` | IMU 已配置（固件 configured 标志） |
| `connected === true` | 总线连接正常 |
| `quaternion_xyzw` Array(4) | 四元数是 4 元素数组 |
| 4 个元素都是有限数 | 非NaN/Infinity |
| 模长 > 0.5 且 < 1.5 | 四元数合理性检查 |
| `sample_count` 是非负安全整数 | 采样计数有效 |

任一条件不满足，网页上角度/采样/Hz 全显示 `—`，状态标签变黄。

> 注：`ready` 和 `configured` 由 server.py 的 `imu_bus.py` 在 live 帧中设为 1。
> 若缺失（如旧版 imu_bus.py），数据虽在广播但网页显示 `—`。

---

## 10. 数据流与轮询机制

### 10.1 轮询触发条件

server.py 的 `stream_should_poll()` 逻辑：

```
有 WebSocket 客户端 && (有舵机在线 || imu_backend=="bus") && 非校准锁定
```

即：**只有网页连着时才轮询**。IMU 数据通过独立的 `imu_stream` 协程广播，不阻塞舵机流。

### 10.2 sync_read 列表顺序

`read_states_with_imu()` 中 sync_read 的 ID 列表顺序：

```python
ids_sent = servo_ids + ([imu_bus.IMU_ID] if with_imu else [])
#          ^^^^^^^^^^                          ^^^^^^^^^^^^^^^^
#          舵机在前                            IMU 排末位
```

**IMU 必须排末位**，不能排首位：
- 排首位：IMU 直接应答，与飞特舵机同时开口 → 总线冲突 → 帧错位（0xFF 出现在数据区）→ 校验错
- 排末位：IMU 等最后一个舵机应答完再开口 → 不冲突（30/30 成功）
- 单独成组 `[200]`：无其他设备 → 不冲突

> **注意**：当 `PRESENT` 为空（没扫到舵机）时，`ids_sent = [200]`，IMU 单独读不冲突。
> 舵机上线后 `[200] + servo_ids` 会导致冲突 — 这正是之前 IMU 数据时有时无的原因。

### 10.3 数据流

```
飞特舵机 (ID=2..) ──┐
                   ├──> /dev/ttyS2 ──> server.py sync_read ──> WebSocket ──> 浏览器
IMU 板 (ID=200) ──┘    (末位应答)                        ↓                ↓
                                                    imu_bus.py      imu_attitude.js
                                                        ↓                ↓
                                                     feed()          IMU 面板刷新
                                                   (校验+解码)
```

### 10.4 时序参数

| 参数 | 值 | 说明 |
|---|---|---|
| 总线波特率 | 1,000,000 bit/s | 8N1 |
| IMU 采样率 | 120 Hz | 片内 SFLP 融合频率 |
| 主机轮询频率 | ~30~60 Hz | 取决于总线设备数和网页刷新 |
| 字节超时 | 1500 µs | 帧内字节间隔超此值丢弃 |
| 事务超时 | 25,000 µs | SYNC READ 等前驱超此值取消 |
| 应答有效期 | 2,000 µs | 准备好的应答超此值未发则取消 |
| 主机数据过期 | 1,000 ms | 帧发布超此值标记 stale |
| 数据冻结阈值 | 8 帧 | 连续 8 帧前 12 字节完全相同标记冻结 |
| 慢读阈值 | 5 次 | 两次读之间 SFLP 刷新 ≥5 次标记 BIT3 |
