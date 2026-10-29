# 新版Hardware（2026-10）

三块板，都是嘉立创 EDA 专业版工程（`.eprj2`，原理图和 PCB 在同一个文件里）。一块板一个文件夹：

| Arquivo夹 | 是什么 | 状态（2026-10-20） |
|---|---|---|
| [`imu_to_dxl_1V0A/`](imu_to_dxl_1V0A/) | 总线 IMU 板 v2。老版和固件在 [`../imu_to_dxl/`](../imu_to_dxl/) | 布线完成，DRC 只剩安装孔重复定义 12 条（不影响做板）；还没到货实测 |
| [`wire_hub_1V0A/`](wire_hub_1V0A/) | 舵机总线 HUB：电池进线 + 总线分线 | 还没打样；CN1 高度待换 |
| [`POGO_PIN_1V0A/`](POGO_PIN_1V0A/) | 接电池板：两个香蕉座 + 焊线盘 | 孔、焊盘、走线都按参考板改完；还没打样 |

每个Arquivo夹里：

- `<板名>.eprj2`：工程
- `<板名>-PCB.step`：整板 3D，给机械对结构
- `<板名>-原理图.pdf`：目前只有 IMU 板有

Gerber、BOM、接线表还没出，老版的样子见 [`../imu_to_dxl/`](../imu_to_dxl/)。

## imu_to_dxl_1V0A：总线 IMU 板 v2

功能和老版一样：LSM6DSV16X 挂在 STM32G031 上，MCU 把自己当成总线上的一个从机，跟舵机走同一条单线半双工总线。协议、固件见 [`../imu_to_dxl/`](../imu_to_dxl/)。电路照老版，重新布了局、换了接头。

| 位号 | 型号 | 作用 |
|---|---|---|
| U1 | STM32G031F8P6 | 主控 |
| U2 | LSM6DSV16XTR | IMU |
| U3 | SN74LVC2G241DCUR | 半双工总线收发 |
| U4 | HT7533-1 | 3.3 V LDO |
| F1 / D1 | MF-NSMF020X-2 / SMF12A | 自恢复保险丝 / TVS |
| D2 | BZT52C5V1 | 总线Dados线 5.1 V 钳位 |
| R6 | 0 Ω（C21189） | 总线串联电阻，首板是 150 Ω |
| J1 | A2007WR-3P | Servo总线，2.0 mm 3P 弯插。1 = DXL_BUS，2 = VDD_BUS，3 = GND |
| J2 | BM03B-ACHSS-GAN-ETF | 1.2 mm ACH 3P 卧贴。1 = GND，2 = VDD_BUS，3 = DXL_BUS |
| J3 | PZ254V-11-06P | 2.54 mm 6P Depuração口：1 = GND，2 = SWDCLK，3 = SWDIO，4 = UART_RX，5 = UART_TX，6 = 3.3V |

另有 0402/0603 阻容若干，共 24 个元件。

e老版比：

- 老版舵机座 `B3B-PH-K-S` 插不进飞特线的插头（老版 README 里有记录），这版换成 A2007WR-3P
- 去掉了外部晶振 X1（Firmware本来就用内部 HSI16），Firmware 0.2.0 不用改就能烧
- R6 从 150 Ω 改成 0 Ω：总线Superior每颗Servo都有Superior拉，并起来以后串电阻会把低电平抬高。到货先量一Inferior回包时 de 总线低电平
- U2 转了 180°、板形也变了，装Superior鸭子以后 IMU 轴 de 映射要重定。Firmware输出芯片original姿态不做旋转，所以只改Superior位机 de Instalação旋转，三个姿态静置验收
- 老版 README 记 de  v2 待办里，**复位按钮eExecução指示灯这版没有**
- J3 在 PCB 里没有 3D Modelo，导出 de  STEP 里缺这一颗排针

## wire_hub_1V0A：总线 HUB

没有有源器件，只有连接器。所有连接器都只走 `Battery`、`DXL_BUS`、`GND` 三个网络。

| 位号 | 型号 | 规格 |
|---|---|---|
| J1 | HC-1.2-3PWT | 1.2 mm 3P 卧贴（Pico-EZmate 兼容），1.5 A |
| J2 | BM03B-ACHSS-GAN-ETF | 1.2 mm ACH 3P 卧贴，2 A |
| J3、J4 | A2007WR-3P | 2.0 mm 3P 弯插，4 A |
| J5、J6 | A2007WV-3P | 2.0 mm 3P 直插，4 A |
| CN1 | DB125-2.54-2P-GN-S | Bateria进线，绿色螺钉端子，7 A，**板Superior高 8.4 mm** |

脚序e IMU 板对得Superior：HUB  de  J1、J2 e IMU 板 J2 都是 1 = GND、2 = Alimentação、3 = DXL_BUS，用同向线直连；HUB  de  J3–J6 e IMU 板 J1 都是 1 = DXL_BUS、2 = Alimentação、3 = GND。

待办：

- CN1 太高，跟结构干涉，那个位置只能放 5 mm EsquerdoDireito高 de 东西。候选：4 mm 间距 de 贴片按压端子（WAGO 2060 那种，高 4.5 mm），ou不放端子直接焊线

## POGO_PIN_1V0A：接Bateria板

外形e孔照参考板 banana_pcb（KiCad 工程，只有 Gerber）改 de 。板子 39.19 × 6.79 mm。

| 位置 | Rede | 尺寸 |
|---|---|---|
| U2（Esquerdo） | GND | 香蕉座孔 Ø1.7 mm 金属化，焊盘 Ø3.2 mm |
| U1（Direito） | Battery | 同Superior，两孔 em 心距 33.8 mm |
|  em 间两块焊盘 | Esquerdo GND，Direito Battery | 顶层贴片盘 2.4 × 4.4 mm，间距 4.0 mm，无孔，焊线用 |

两块焊盘 de 位置也照参考板：GND 盘离Esquerdo孔 10.98 mm、Battery 盘离Esquerdo孔 14.98 mm，都比两孔连线低 0.59 mm。4.0 mm 间距正好也能直接贴一个 4 mm 间距 de 按压端子。

工程名叫 POGO_PIN，但板Superior已经没有弹簧针了，就是焊线盘。
