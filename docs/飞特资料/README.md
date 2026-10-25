# 飞特舵机资料与 SDK

[返回工具导航](../../tools/README.md) · [飞特官方电子手册](http://doc.feetech.cn/#/prodinfodownload?srcType=FTServo-emanual-ab4947a479784a71a8cb7928)

## 官网现行资料

2026-10-25 核对飞特文档站的官方索引和正文接口。下表更新时间来自官网 `lastModifiedDate`，不等同于文档封面的发布日期。

| 资料 | 官网标注版本 | 官网最后更新时间（UTC+8） |
|---|---|---|
| [SCS 通信协议](http://doc.feetech.cn/#/f?q=2506ba160b93) | 1.0 | 2026-10-08 |
| [STS 内存表](http://doc.feetech.cn/#/f?q=2506abfb1cb0) | 1.1 | 2026-10-08 |
| [SMS 内存表](http://doc.feetech.cn/#/f?q=2602a06ca658) | 1.1 | 2026-10-08 |
| [FD 调试软件及串口工具](https://gitee.com/ftservo/fddebug) | 按官方仓库发布 | [本仓下载与说明](../../tools/飞特/README.md) |
| [HD-1910-C001 规格书](../../tools/FeeTech_HD1910M_Servo/HD-1910-C001串型规格书20260907.pdf) | 文件标注 2026-09-07 | 本仓已有型号规格书 |

## 离线副本（2026-09-17 快照）

下面是 2026-09-17 保存的电子手册副本，便于检索及对照[飞特适配架构](../../software/飞特适配架构.md)。**官网已有后续修改，离线副本保留原日期；当前内容以官网为准。**

| 文件 | 版本 | 官网更新日期 | 用途 |
|---|---|---|---|
| [`SCS通信协议-v1.0-2026-06-09.md`](SCS通信协议-v1.0-2026-06-09.md) | v1.0 | 2026-06-09 | 包格式、指令表。**这版有重启指令 0x08、参数备份 0x09、状态重置 0x0A**，2019 版没有 |
| [`磁编码STS内存表手册-v1.1-2026-08-27.md`](磁编码STS内存表手册-v1.1-2026-08-27.md) | v1.1 | 2026-08-27 | HD-1910 所属的 STS 系列内存表：EEPROM / SRAM 分区、出厂值、锁标志语义、状态位定义 |
| [`磁编码SMS内存表手册-v1.1-2026-08-27.md`](磁编码SMS内存表手册-v1.1-2026-08-27.md) | v1.1 | 2026-08-27 | 同上，SMS（RS485）版。跟 STS 的差别：7 是应答返回延时（STS 是预留）、33 运行模式范围 0~2、40 扭矩开关没有阻尼值 2、83 是 Hts、相位 BIT5 含义不同 |
| `磁编码SMS&STS&HTS-十六进制指令生成表-250508.xlsx` | 250508 | 2025-05-08 | 官方 Excel，填参数自动生成十六进制指令帧，串口助手直接发；有解锁 / 改 ID / 清圈数 / 中位校准的现成例子 |

HD-1910-C001 的定制差异（出厂模式 4、扭矩、减速比）见 [HD-1910 训练前数据清单](../HD-1910训练前数据清单.md)，型号规格书见上表。

## 官方 SDK

| 开发环境 | 官方源码 |
|---|---|
| Python | [FTServo_Python](https://gitee.com/ftservo/FTServo_Python) |
| Linux / C++ | [FTServo_Linux](https://gitee.com/ftservo/FTServo_Linux) |
| Arduino | [FTServo_Arduino](https://gitee.com/ftservo/FTServo_Arduino) |
| STM32 HAL | [FTServo_stm32HAL](https://gitee.com/ftservo/FTServo_stm32HAL) |

## 版本核对方法

怎么拉的（文档站的接口，下次更新用）：

```text
索引  http://longbos.com:9009/workflow/yf-specification/getBysrcType/FTServo-emanual-ab4947a479784a71a8cb7928
正文  http://longbos.com:9009/workflow/yf-specification/getQr/<q>     q 取索引正文里 #/f?q=… 的值
       STS 内存表 2506abfb1cb0 · SMS 内存表 2602a06ca658 · SCS 协议 2506ba160b93
返回 JSON，data.mdcontent 是 Markdown 正文，data.lastModifiedDate 是更新时间
```
