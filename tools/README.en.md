# Tool index

[Home](../README.en.md#documentation) · [All documentation](../docs/README.en.md) · [简体中文](README.md)

Use [Studio](../software/studio/README.md) for routine Wi-Fi setup, calibration and control. This page groups flashing tools, serial debugging, Feetech references and developer analysis. Most linked guides are in Chinese.

## 1. Flashing and Windows tools

| Task | Download or entry | Notes |
|---|---|---|
| Flash the duck image | **[Rufus 4.15 portable EXE](rufus/rufus-4.15p.exe)** · [Instructions](rufus/README.md) | Windows x64; original source, licence and checksums included |
| Debug Feetech servos | **[FD 1.9.8.5 archive](飞特/FD1.9.8.5%28250729%29.7z)** · [Instructions](飞特/README.md) | Extract and run FD to configure IDs and parameters and read state |
| Send raw serial data | [UartAssist.zip in Feetech's repository](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | Generic serial helper; send data matching the device protocol |
| Fix adapter recognition | [CH343 / CH340 driver links](飞特/README.md#驱动与串口助手) | Check the adapter's chip model in Device Manager first |

### Serial settings

| Connection | Typical settings | Guide |
|---|---|---|
| Main-board USB serial terminal | 115200, 8N1 | [Board connection guide](radxa/镜像使用说明.md) |
| Feetech bus configured for this project | 1000000, 8N1 | [Servo guide](飞特/README.md); use a suitable TTL adapter and separate servo power |

8N1 means 8 data bits, no parity and one stop bit. Use the device's actual baud rate if it has been changed.

## 2. Feetech references and SDKs

The [Feetech reference index](../docs/飞特资料/README.md) links current official manuals, dated offline copies, model specifications and SDKs.

- Protocols: [SCS](http://doc.feetech.cn/#/f?q=2506ba160b93) · [STS register map](http://doc.feetech.cn/#/f?q=2506abfb1cb0) · [SMS register map](http://doc.feetech.cn/#/f?q=2602a06ca658). Official versions checked on 2026-10-25; offline copies retain separate snapshot dates.
- Official SDKs: [Python](https://gitee.com/ftservo/FTServo_Python) · [Linux](https://gitee.com/ftservo/FTServo_Linux) · [Arduino](https://gitee.com/ftservo/FTServo_Arduino) · [STM32 HAL](https://gitee.com/ftservo/FTServo_stm32HAL).

## 3. Repository debugging tools

| Tool | Repository location | Purpose |
|---|---|---|
| Servo web console | [tools/servo-web/](servo-web/README.md) | Serial debugging, state readings, poses, sequences and 3D display; includes simulation mode |
| HD1910M tester | [tools/FeeTech_HD1910M_Servo/](FeeTech_HD1910M_Servo/README.md) | Rust CLI for scanning, registers, configuration and monitoring; uses this model's register map |
| STS3215 tester | [tools/sts3215Servo_testtool/](sts3215Servo_testtool/README.md) | Rust CLI for scanning, state readings and single or batch tests; targets STS3215 |
| Bus IMU protocol checks | [tools/imu200/](imu200/) | [imu200.py](imu200/imu200.py): simulation, test vectors and physical checks for the Feetech address-56, 15-byte block; see the [bus protocol](../hardware/imu_to_dxl/总线协议.md) |

## 4. Recording and analysis

| Tool | Repository location | Purpose |
|---|---|---|
| Gait analysis | [tools/gait-analysis/](gait-analysis/README.md) | Analyse JSONL recordings for tracking error, vibration and foot motion on a computer |
| Onboard recording and analysis | [tools/radxa/onboard-analysis/](radxa/onboard-analysis/README.md) | Record joints, IMU and commands for physical debugging |
| Fold-contact analysis | [tools/fold_contact/](fold_contact/README.md) | Investigate part contact using upstream simulation geometry |
| Assembly drawings and hole analysis | [scripts/](../scripts/) | Generate drawings, export analysis meshes and scan hole features; see [reproduction commands](../docs/project-research-archive.en.md#reproducing-this) |

## 5. Earlier card-building scripts

[tools/radxa/](radxa/README.md) preserves earlier card-building, bootloader and network debugging scripts. The current complete image is built from [software/image/](../software/image/README.md); start with the [first-use guide](../docs/上手指南/README.md) when flashing a card.
