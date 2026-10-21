# 固件依赖与构建工具

本工程将编译所需的芯片与传感器驱动源码保存在工程目录内。日常编译不需要再次下载 STM32CubeMX、HAL 或联网取得驱动。

| 组件 | 固定来源 | 许可证与本地改动 |
| --- | --- | --- |
| CMSIS Core 6.2.0 | 已安装的 `C:\Keil_v5\ARM\PACK\ARM\CMSIS\6.2.0`，对应 [ARM-software/CMSIS_6 v6.2.0](https://github.com/ARM-software/CMSIS_6/tree/v6.2.0) | Apache-2.0；仅复制 Cortex-M0+ 与 Arm Compiler 6 所需头文件，内容未修改；许可证 `Drivers/CMSIS/LICENSE` |
| STM32G0 CMSIS Device v1.4.5 | [STMicroelectronics/cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0/tree/f576c24e123edf3332988ecd49512c0f35f85186)，commit `f576c24e123edf3332988ecd49512c0f35f85186`，2026-03-05 | Apache-2.0；器件头与 system 源文件未修改；许可证 `Drivers/CMSIS/Device/ST/STM32G0xx/LICENSE.md` |
| STM32G031 启动代码 | 同一 ST commit 的 `Source/Templates/arm/startup_stm32g031xx.s` | 栈从 1024 改为 2048 字节；堆从 512 改为 0 字节，不使用动态内存。向量表、Reset_Handler 和弱 IRQ 名均保留 ST 实现 |
| LSM6DSV16X PID 驱动 | [STMicroelectronics/lsm6dsv16x-pid](https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07)，commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07` | ST BSD-3-Clause；`Drivers/LSM6DSV16X/LICENSE`；驱动原文件与来源记录置于同目录 |
| Keil 器件支持包 | 本机 `Keil.STM32G0xx_DFP.2.1.0` | 提供设备描述、SVD 和 `CMSIS/Flash/STM32G0xx_64.FLM` 烧录算法。此版本不再包含 Device:Startup/HAL，故本工程自行收录官方 CMSIS 启动文件，避免 RTE 重复添加 |
| Arm Compiler for Embedded 6.24 | `C:\Keil_v5\ARM\ARMCLANG` | 本机 `Keil MDK STMicroelectronics Edition - Cortex-M0/M0+/M23` 授权。工程使用 Arm Compiler 6、旧语法 armasm 与 MicroLIB；只隐藏旧汇编器弃用通知 A1950W，不隐藏代码告警 |

## 构建入口

打开固件目录后，在 PowerShell 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'
```

或在 VS Code 按 `Ctrl+Shift+B`。工具安装路径不同可传 `-ToolchainRoot '<安装目录>\ARMCLANG'`。

Keil 直接打开 `MDK-ARM/imu_to_dxl_dap.uvprojx`（仓库只保留这一套 DAP 工程），Build 后输出 `Build/imu_to_dxl.axf`、`.hex`、`.bin` 和 `.map`。两种入口都使用 Cortex-M0+、C11、`-Oz`、软件浮点、短枚举、MicroLIB、`STM32G031xx`、`HSE_VALUE=16000000`。构建脚本另外生成详细日志与产物 SHA-256 清单（`Build/imu_to_dxl.build.json`）。

链接文件限定 Flash 为 `0x08000000..0x0800FFFF`、数据 RAM 为 `0x20000000..0x200017FF`，最后 2 KiB `0x20001800..0x20001FFF` 专用于栈，初始 SP 为 `0x20002000`。若调整栈大小，必须同时修改启动文件与 scatter 文件。

Keil 工程配置 CMSIS-DAP（DAP-Link）、SWD、STM32G0 64 KiB Flash 算法。**命令行烧录请用 OpenOCD**（`interface/cmsis-dap.cfg` + `target/stm32g0x.cfg`，4MHz），UV4 命令行存在"退出码 0 但未实际擦写"的假成功问题。实机烧录与共线通信已验证，记录见 `VALIDATION.md`。

无硬件主机测试使用 gcc（WinLibs 的 `mingw64`，装在哪都行，MinGW-w64）编译 C 用例；上位机工具依赖 Python 3.8+、pyserial（曲线功能另需 matplotlib），清单见 `Tools/requirements.txt`。

本机 Codex 沙箱使用不同用户身份时，Arm 许可检查会报告“assigned to another user”；在实际用户身份下许可检查成功。该差异不会要求普通用户更改已激活的许可，也不涉及破解或替换工具。

## 文件完整性

`Drivers/CMSIS/dependency-hashes.json` 记录当前收录的 CMSIS、启动代码及传感器驱动文件的 SHA-256，便于后续升级时辨认变更。ST 源 commit 元数据见 `Drivers/CMSIS/Device/ST/STM32G0xx/source-commit.json`。
