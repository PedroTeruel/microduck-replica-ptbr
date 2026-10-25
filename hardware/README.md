# 硬件工程

三块自制电路板、瑞莎主控与官方开源 HAT 的统一入口。

| 板卡 | 购买 / 工程入口 | 设计预览 | 资料 |
|---|---|---|---|
| **总线 IMU 板 v2** | [imu_to_dxl_1V0A](新版/imu_to_dxl_1V0A/) | [3D](../assets/hw/imu-to-dxl-1v0a-3d.png) · [PCB](../assets/hw/imu-to-dxl-1v0a-pcb.png) | 嘉立创 EDA 专业版工程、原理图 PDF、PCB STEP；[新版说明](新版/README.md) |
| **舵机总线 HUB** | [wire_hub_1V0A](新版/wire_hub_1V0A/) | [3D](../assets/hw/wire-hub-1v0a-3d.png) · [PCB](../assets/hw/wire-hub-1v0a-pcb.png) | 嘉立创 EDA 专业版工程、PCB STEP；[新版说明](新版/README.md) |
| **电池接口板** | [POGO_PIN_1V0A](新版/POGO_PIN_1V0A/) | [3D](../assets/hw/pogo-pin-1v0a-3d.png) · [PCB](../assets/hw/pogo-pin-1v0a-pcb.png) | 嘉立创 EDA 专业版工程、PCB STEP；[新版说明](新版/README.md) |
| **瑞莎 Radxa ZERO 3W 主控** | [主控购买（淘宝）](https://item.taobao.com/item.htm?id=763812025816) | [官方板卡图](../assets/hw/radxa-zero3w-official.webp) | [官方资料](https://docs.radxa.com/en/zero/zero3) · [硬件设计文件](https://docs.radxa.com/en/zero/zero3/download#hardware-design)：原理图、2D 尺寸与 3D 模型 |
| **官方 RPI Robot HAT** | [Pollen Robotics KiCad 工程](https://github.com/pollen-robotics/elec_RPI_Robot_HAT) | [官方设计图](../assets/hw/rpi-robot-hat-official.png) | [生产打样文件](https://github.com/pollen-robotics/elec_RPI_Robot_HAT/tree/main/production)：Gerber、BOM、贴片坐标、原理图与 STEP |

各板的设计状态、接线和验证记录见对应工程说明。

[老版总线 IMU 板及固件](imu_to_dxl/README.md)保留电路工程、原理图、接线表、板上 BOM 与固件资料。

[整机装配采购清单](../BOM/README.md) · [硬件入门](../docs/硬件入门.md) · [返回首页](../README.md)
