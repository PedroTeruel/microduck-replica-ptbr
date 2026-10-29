# 1910 M6 ParâmetrosFonte / Parameter provenance

本目录的 `1910_m6.json` **采用 LuwuDynamics 公开的 1910 BAM M6 参数**，
不是este projeto自行辨识或测量 de Resultado。感谢 LuwuDynamics  de 公开分享。
即使后续使用这套Parâmetros自行训练走路策略，ServoModeloParâmetros仍应注明此Fonte。

## 固定Fonte

- 项目：[LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)
- 版本：`326d77a1122870bdefa2c36403937502c958e69c`
- [原始参数文件](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck/params/1910_m6.json)
- [配套训练配置](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck_constants.py)
- 原文件 SHA-256：`ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`
- 获取日期：2026-09-24；JSON 按原Arquivo保存，未改动Parâmetros。
- 许可证：上游仓库 **Apache-2.0**；副本见本目录 `LICENSE`。

上游把舵机称为 HLS1910，JSON 的 `actuator: "sts3215"` 用于选择 BAM 中的
飞特Controle器实现，不是把Parâmetros换成 STS3215  de 出厂Modelo。复刻项目维护者已确认
este projeto使用同款 1910；该确认不代表我们已复现upstream辨识实验。

## Atual应用

`Mjlab-Velocity-{Flat,Rough}-MicroDuck-HD1910` 使用这份参数，沿用上游训练设置：
`kp_fw=5`、`vin_range=(7.4, 8.0)`、`vin_min=7.0`、负载压降增益 `(0.0, 0.2)`、
命令延迟 `3–6` 个仿真步。保留本地 Microduck 几何与关节约定。

`max_velocity=100` 是上游用于近似取消目标位置斜率限速的设置，不是宣称
Servo空载转速为 100 rad/s；Modelo仍por meio de供电e反电动势限制速度。
`q_offset` 是参数文件中的辨识偏置，不应抄进实机的逐关节零位表。
JSON 的 `command_delay` 保留来源值；mjlab 的命令队列延迟由上述 lag 配置控制，
不能把两者简单相加宣称为实机总延迟。

original辨识Dados、Teste电压 e FirmwareVersão未随本次查阅 de Parâmetros记录一起提供。
upstream训练使用 P=5，而其 Arduino Execução时暂存增益为 P=6、D=20；两者不能直接
当成一份已Validação de 实机Configuração。本次不修改任何Servo寄存器。

## upstream项目

- LuwuDynamics：1910 Parâmetros e  XgoDuck 配套Configuração，Apache-2.0。
- [Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl)：
  本地训练框架 e 任务代码采用 Apache-2.0；Microduck 3D Modelo e 网格Preservadoupstream
  CC BY-NC-SA 声明（upstream README 写作 BY-SA-NC）。
- [Rhoban / BAM](https://github.com/Rhoban/bam)：执行器模型和辨识框架，Apache-2.0。

`1910_m6.json` is redistributed unchanged from LuwuDynamics/xgoduck_rl at the
revision above under Apache-2.0. It is not an independently identified model by
this replica project. Local integration changes are the additional HD1910 task
configuration and documentation; original attribution is retained.
