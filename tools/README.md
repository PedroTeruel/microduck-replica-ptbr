# 工具导航

[返回首页](../README.md#资料导航) · [完整文档](../docs/README.md) · [English](README.en.md)

日常配网、标定和遥控使用 [Studio](../software/studio/README.md)。这里按烧卡、串口调试、飞特资料和开发分析整理工具。

## 1. 烧卡与 Windows 工具

| 要做什么 | 下载或入口 | 说明 |
|---|---|---|
| 烧录鸭子镜像 | **[Rufus 4.15 便携版 EXE](rufus/rufus-4.15p.exe)** · [使用步骤](rufus/README.md) | Windows x64，免安装；另附原版源码、许可与校验值 |
| 调试飞特舵机 | **[FD 1.9.8.5 压缩包](飞特/FD1.9.8.5%28250729%29.7z)** · [使用说明](飞特/README.md) | 解压后运行 FD，配置 ID、参数并读回状态 |
| 收发原始串口数据 | [飞特官方仓库的 UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | 通用串口助手；需按设备协议发送数据 |
| 串口转接板识别异常 | [CH343 / CH340 驱动入口](飞特/README.md#驱动与串口助手) | 先在设备管理器确认转接芯片型号 |

### 串口参数怎么选

| 场景 | 常用设置 | 操作说明 |
|---|---|---|
| 主板 USB 串口登录 | 115200，8N1 | [主板连接说明](radxa/镜像使用说明.md)；用于系统终端 |
| 本项目已配置的飞特舵机总线 | 1000000，8N1 | [舵机调试说明](飞特/README.md)；舵机另行供电，使用对应 TTL 转接板 |

8N1 指 8 个数据位、无校验、1 个停止位；若设备改过波特率，以实际配置为准。

## 2. 飞特官方资料与 SDK

**[飞特资料索引](../docs/飞特资料/README.md)**：官网现行手册、仓库离线副本、型号规格书和 SDK 的统一入口。

- 协议与内存表：[SCS 通信协议](http://doc.feetech.cn/#/f?q=2506ba160b93) · [STS 内存表](http://doc.feetech.cn/#/f?q=2506abfb1cb0) · [SMS 内存表](http://doc.feetech.cn/#/f?q=2602a06ca658)。官网版本核对日期为 2026-10-25，离线副本日期单独标明。
- 官方 SDK：[Python](https://gitee.com/ftservo/FTServo_Python) · [Linux](https://gitee.com/ftservo/FTServo_Linux) · [Arduino](https://gitee.com/ftservo/FTServo_Arduino) · [STM32 HAL](https://gitee.com/ftservo/FTServo_stm32HAL)。

## 3. 本仓调试工具

| 工具 | 仓库位置 | 用途 |
|---|---|---|
| 网页舵机调试台 | [tools/servo-web/](servo-web/README.md) | 串口调试、读回状态、姿态与序列、3D 显示；支持模拟模式 |
| HD1910M 测试工具 | [tools/FeeTech_HD1910M_Servo/](FeeTech_HD1910M_Servo/README.md) | Rust 命令行：扫描、寄存器读取与配置、监控；按该型号内存表使用 |
| STS3215 测试工具 | [tools/sts3215Servo_testtool/](sts3215Servo_testtool/README.md) | Rust 命令行：扫描、读状态、单颗与批量测试；面向 STS3215 |
| 总线 IMU 协议检查 | [tools/imu200/](imu200/) | [imu200.py](imu200/imu200.py)：模拟、测试向量与真板检查；针对飞特地址 56 的 15 字节块，协议见[总线说明](../hardware/imu_to_dxl/总线协议.md) |

## 4. 记录与分析

| 工具 | 仓库位置 | 用途 |
|---|---|---|
| 步态分析 | [tools/gait-analysis/](gait-analysis/README.md) | 在电脑上分析 JSONL 记录的跟踪误差、颤动和脚部运动 |
| 主板采集与分析 | [tools/radxa/onboard-analysis/](radxa/onboard-analysis/README.md) | 采集关节、IMU、指令等记录，配合实机调试 |
| 折叠接触分析 | [tools/fold_contact/](fold_contact/README.md) | 根据上游仿真几何分析零件接触，作为标定研究参考 |
| 装配图与孔位分析脚本 | [scripts/](../scripts/) | 生成装配图、导出分析网格和扫描孔位；[重现步骤](../docs/项目研究归档.md#重现) |

## 5. 历史做卡脚本

[tools/radxa/](radxa/README.md) 保留早期做卡、引导与联网调试脚本。当前整套镜像的构建入口是 [software/image/](../software/image/README.md)，首次烧卡请看[使用指南](../docs/上手指南/README.md)。
