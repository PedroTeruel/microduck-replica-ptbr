# Lista de materiais do robô completo (BOM)

> **Para peças impressas, materiais e quantidades de montagem, consulte a versão correspondente no [repositório CAD](https://github.com/fanhao375/microduck-replica-cad#装配-bom).** As contagens de referências MJCF e estimativas geométricas deste documento analisam o projeto original e não representam a lista mais recente de peças Feetech para impressão.

> **O repositório tem quatro listas e um guia de impressão, cada qual com sua função:**
>
> | Documento | Abrangência | Fora do escopo |
> |---|---|---|
> | **BOM** (este documento) | **Visão geral**: todos os materiais, quantidades (contadas pelas referências de `geom` no MJCF), faixa de custos e itens ainda não resolvidos | Onde comprar cada item e como imprimir |
> | [Lista de compras de eletrônica](docs/电控采购清单.md) | **Onde comprar a eletrônica**: placa principal, câmera, ToF, alimentação, duas PCBs e fios; links reais do Taobao e alertas | Base das quantidades e peças mecânicas |
> | [Lista de compras mecânicas](docs/机械采购清单.md) | **Onde comprar as peças mecânicas**: rolamentos, fixadores e consumíveis; links reais do Taobao | Peças eletrônicas |
> | [Consulta rápida de especificações de hardware](docs/硬件规格速查.md) | **Parâmetros**: interfaces, tensão, protocolos e valores que precisam corresponder no software | Preços e lojas |
> | [print/README](print/README.md) | **Impressão**: escolha versão, material e quantidade no repositório CAD | Compras |
>
> Os números das peças e parafusos usados na montagem correspondem aos do [repositório CAD](https://github.com/fanhao375/microduck-replica-cad#装配-bom).


**Português (Brasil)** · [English](BOM.en.md)

Tudo o que é necessário para montar um Microduck. As quantidades foram obtidas pela contagem das referências a `geom` em `robot_walk.xml` no projeto original (**38 tipos de malha / 75 instâncias**); não são estimativas.

> ⚠️ **A Pollen nunca publicou uma BOM.** Esta lista foi reconstruída a partir dos arquivos públicos MJCF e STL, do código Rust e do projeto KiCad.
> Cada item informa sua base. Os preços variam muito conforme a região e a data; **use-os apenas como ordem de grandeza**.
>
> Conferido em **2026-09-04**. ⚠️ **A revisão de referência do projeto original ainda precisa ser confirmada**: os antigos arquivos STL de `print/` deste repositório (já removidos) eram idênticos, byte a byte, aos da cópia local de trabalho de `microduck_rl`, um clone raso de profundidade 1 cujo HEAD era **`d424a0c` (2026-08-27)**.
> As revisões `29e887e` e `8dfc08f` (reexportação) citadas anteriormente não existem na base de objetos local; **portanto, não foi possível verificar a afirmação de que a contagem de `geom` era igual antes e depois da reexportação**. Todas as contagens abaixo vêm de `d424a0c`.

---

## 1. Visão geral dos custos

| Categoria | Quantidade | Ordem de grandeza |
|---|---|---|
| **Servos** | 15 | **US$ 359 – € 629** (consulte abaixo; grande variação regional) |
| Placa principal e sensores | 4 tipos | cerca de US$ 80–120 |
| Bateria e alimentação | 2 itens | cerca de US$ 30–50 |
| Rolamentos | 14 | cerca de US$ 15–30 |
| Fixadores | cerca de 325 peças | cerca de US$ 15–25 |
| **Fabricação de PCBs (2 placas)** | 2 | cerca de US$ 60–150 (com montagem) |
| Filamento de impressão | — | cerca de US$ 15–30 |

**Os servos são de longe o maior custo**, e a diferença entre fornecedores é enorme: a loja internacional da ROBOTIS cobra US$ 23,90 × 15 ≈ **US$ 359** (menos que o preço de varejo do robô); nos EUA, US$ 27,49 × 15 ≈ **US$ 412** (aproximadamente o preço do robô); na Europa, com impostos, são **€ 603–629** (bem acima).

> O preço de US$ 399 depende da produção em escala da Seeed e da cadeia de fornecimento da Pollen. **Uma montagem individual não consegue chegar a esse valor.**

---

## 2. Servos (principal componente do custo)

| Modelo | Quantidade | Base |
|---|---|---|
| **Dynamixel XL330-M288-T** | **15** | A malha `xl330` é referenciada 15 vezes em `robot_walk.xml` |

- 14 servos fazem parte do espaço de ações da política; **o 15.º aciona o bico/mandíbula** por meio de articulações `passive_*`.
- IDs: perna esquerda 20–24 / pescoço, cabeça e boca 30–34 / perna direita 10–14.
- ⚠️ **O modelo foi inferido**: o código-fonte informa apenas `motor_name="xl330"`, sem sufixo. A justificativa para M288-T está em [Seleção dos atuadores](docs/执行器选型.md#型号是怎么定下来的).

**Preços de referência** (2026-09-04):

| Fornecedor | Unitário | 15 unidades |
|---|---|---|
| ROBOTIS EUA | **US$ 27,49** | **US$ 412** |
| Generation Robots (Europa, sem impostos) | € 33,50 | € 503 |
| Generation Robots (Europa, com impostos) | € 40,20 | € 603 |
| MyBotShop | €41.95 | €629 |

> ⚠️ **Aviso de sobretensão**: o XL330 é especificado para 3,7–6,0 V, mas o Microduck o alimenta com 6,6–8,2 V.
> No esquema oficial do HAT, a interface Dynamixel está ligada diretamente a `+BATT` (a tensão da bateria); o único conversor de 5 V da placa alimenta o Raspberry Pi.
> Essa é uma escolha do projeto original, não um erro de digitação. Consulte [A tensão real: o XL330 opera em sobretensão](docs/执行器选型.md#-电压真相xl330-被超压执行).

> 🛒 **Links de compra no Taobao**: [lista de compras de eletrônica](docs/电控采购清单.md) (placa principal, câmera, ToF, alimentação, PCBs e fios) e [lista de compras mecânicas](docs/机械采购清单.md) (rolamentos, fixadores, porcas de inserção, trava-roscas e consumíveis).

---

## 3. Componentes eletrônicos

| Componente | Modelo | Quantidade | Base / observação |
|---|---|---|---|
| Placa principal | **Radxa Zero 3W** | 1 | Árvore de dispositivos: `compatible = "radxa,zero-3w"`. Há versões com diferentes capacidades de RAM/eMMC. O material oficial informa **1 GB de RAM e 32 GB de armazenamento** (sem especificar eMMC); **para a réplica, basta uma placa sem eMMC de 1 GB ou 2 GB e um cartão microSD de 32 GB**. Compre de distribuidores oficiais; veja a [lista de compras de eletrônica](docs/电控采购清单.md) (correção de 2026-10-12: a recomendação anterior de 2 GB/16 GB eMMC era desnecessária). A imagem do sistema precisa incluir o kernel de fabricante Rockchip (família Armbian), senão o NPU não estará disponível |
| Câmera | Raspberry Pi Camera v2 (**IMX219**) | 1 | `setup-board.sh` usa o overlay `radxa-zero3-rpi-camera-v2`. ⚠️ **A câmera fica montada com rotação de um quarto de volta, corrigida por software**: o padrão atual de `--rotate` em `mediad/src/main.rs:82` é **90°**. O comentário do código diz que a câmera da cabeça foi montada com um quarto de volta e que esse é o único lugar onde isso está registrado. Os 180° de `media-bringup.md:472` são dados do protótipo alpha. **Considere o valor do código: 90°.** |
| Sensor de profundidade | Módulo **VL53L5CX** (ou L8CX) | 1 | O firmware reconhece os dois modelos (revisões `0x02` e `0x0C`); **o L7CX é rejeitado**. Recomendamos o L5CX: sua placa mede 15,8 × 10 mm; as placas comuns do L8CX, com 33,4 mm, não cabem na carcaça do rosto ([medição prática](踩坑记录.md#买东西)). Endereço `0x29` ou `0x52`; interface Stemma/Qwiic |
| Bateria | **Sony NP-F550** (2S, 7,4 V) | 1 | ⚠️ Consulte a correção abaixo |
| Suporte da bateria | Suporte genérico para a série NP-F | 1 | O projeto original inclui apenas a peça impressa `power_support`, **sem modelo dos contatos**; será necessário resolver por conta própria como captar a energia |
| Alto-falante | Alto-falante compacto | 1 | Uma malha `speaker`; o HAT tem amplificador PAM8406 e terminais Wago |

### ⚠️ Correção do modelo da bateria: NP-F550, não F970

O arquivo de malha do projeto original se chama `np_f970`, **mas o nome é enganoso**:

| | |
|---|---|
| Dimensões medidas da malha | **70,8 × 38,6 × 20,6 mm** — dimensões de uma **NP-F550/F570** |
| NP-F970 verdadeira | Cerca de **60 mm** de espessura e 300 g |
| Modelo citado no código-fonte | **Somente NP-F550** (`model.rs`, `robotd-design.md`); não há nenhuma ocorrência de F970 no repositório |

**A F970 não cabe e seus 300 g consumiriam mais de um terço do limite de 800 g do robô.**
Versões anteriores deste repositório mencionavam “NP-F970” em vários lugares; essas referências foram corrigidas.

---

## 4. Placas de circuito (2; ambas precisam ser encomendadas a uma fábrica)

### Placa 1: RPI Robot HAT — projeto oficial aberto; baixe os arquivos e encomende a fabricação

| | |
|---|---|
| | |
|---|---|
| Origem | [`pollen-robotics/elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT) (Apache-2.0) |
| Arquivos de fabricação | `production/`: Gerbers, BOM, coordenadas de montagem, PDF do esquema e STEP |
| **Camadas** | **4** (`F.Cu / In1.Cu / In2.Cu / B.Cu`) |
| **Espessura** | **1,0 mm** (KiCad `(thickness 1)`. Os 0,84 mm medidos no STL são uma aproximação da malha de simulação; use o valor do KiCad ao encomendar) |
| Dimensões | **65,0 × 30,9 mm** (medidas na camada `Edge.Cuts` do KiCad, cantos R3,5). É 0,9 mm mais larga que uma Pi Zero |

> ⚠️ **Não use o STL nem o STEP convertido dele para projetar encaixes mecânicos.** A malha de simulação mede **65,025 × 30,025 × 0,840 mm**,
> diferente em **0,875 mm na largura e 0,16 mm na espessura** do contorno da placa real. A diferença de largura representa 3% no lado de 30 mm; ranhuras, espaçadores e furos não vão alinhar. **Para encaixes, use sempre 65,0 × 30,9 × 1,0 mm e considere como referência o contorno `Edge_Cuts` dos Gerbers.**
> Use STL/STEP apenas para verificar interferências 3D e posicionamento aproximado.
>
> (Para comparação: a malha `pcb__raspberry_pi_zero_2_w` mede 65,000 × 30,000 × 1,600 mm, as dimensões padrão da Pi Zero. Ela é precisa, mas serve apenas como bloco de referência; o robô real usa a Radxa Zero 3W.)
| BOM | 47 linhas / **123 componentes**, dos quais **5 linhas são DNP** (não montar) |
| Posições de montagem | `POS.csv` tem **117 linhas**, incluindo 3 fiduciais (FID1–3) e H3 → **113 componentes reais** |
| Soldagem manual | ❌ **Não é viável**: há um codec VQFN-32 e uma IMU LGA-16; encomende montagem SMT |

**Componentes principais** (para estimativa de custo e substituições):

| Referência | Componente | Função |
|---|---|---|
| U2 | TLV320AIC3104IRHBR | Codec de áudio (I²C `0x18`) |
| U1 | PAM8406D | Amplificador classe D |
| MK1 | Microfone MEMS (LCSC **C7587901**) | Integrado à placa. ⚠️ O campo Value da BOM oficial informa apenas `Microphone_MEMS`, e o esquema identifica o componente como “Onboard Mic.”, **sem especificar o modelo**. A referência LMA2718, anteriormente usada neste repositório, não tinha fonte e foi removida |
| U11 | BMI088 | IMU — **instalada, mas não usada pelo software** (a chamada “segunda IMU”) |
| U8 | SIT3088E | Transceptor RS-485 |
| U10 | LM5050-1 | OR-ing por diodo ideal e detecção de desligamento. ⚠️ Fica na linha `+5V`, depois do conversor buck; não protege a entrada da bateria contra inversão de polaridade |
| U9 | AP63205 | Conversor abaixador de tensão |
| U4 | CAT24C32 | EEPROM — **DNP** (não montar); portanto, este HAT não se identifica automaticamente |
| J13/J14 | JST EH 3P | Dynamixel **TTL** |
| J3/J11 | JST EH 4P | Dynamixel **RS-485** |
| J5–J8 | JST SH 1 mm 4P | Qwiic / Stemma (para o ToF) |

⚠️ **打样前必读**：

1. **这块板没有充电电路，也没有 USB-C 输入**。仓库里的 `pwr_supply_charge.kicad_sch`
   是**孤儿图纸**（`main.kicad_sch` 没挂它，标题栏还写着别的项目名）。电池要用外部充电器充。
2. **打开 KiCad 工程需要先装 [`lib_KiCAD`](https://github.com/pollen-robotics/lib_KiCAD)**，
   否则一片未解析符号。只打样则不é necessário，直接用 Gerber。

### 板 2：`imu_to_dxl` —— 全网无公开工程，必须自己画

| | |
|---|---|
| 状态 | 🔧 **este repositório正在重建**，见 [Hardware方案逆向 §三](docs/Hardware方案逆向.md) |
| 功能 | 把 IMU 伪装成一个 Dynamixel 从机（ID **200**）挂在Servo总线Superior |

**参考 BOM**（este repositório设计，非Oficial）：

| 位号 | 器件 | 立创编号 | Instruções |
|---|---|---|---|
| U1 | **STM32G031F8P6** | `C529334` | MCU，TSSOP-20。⚠️ **这是本仓库的选型建议，不是逆向所得** —— 官方那块板的 MCU 型号无从还原（见 [硬件方案逆向](docs/硬件方案逆向.md#那-imu_to_dxl-板上是什么-mcu)）。选 F8（64 KB Flash）而非 F6（32 KB）是为双协议固件留余量。<br>**选 ST 的理由不是"生态好"，是两个具体特性**：① 和 IMU 同厂，[`lsm6dsv16x-pid`](https://github.com/STMicroelectronics/lsm6dsv16x-pid) 驱动与 [`lsm6dsv16x_sensor_fusion.c`](https://github.com/STMicroelectronics/STMems_Standard_C_drivers/blob/master/lsm6dsv16x_STdC/examples/lsm6dsv16x_sensor_fusion.c) SFLP 例程现成 —— SFLP 初始化要配 FIFO、融合率、量程，顺序错了不出数；② STM32G0 的 USART 有**硬件 DE（Driver Enable）**，半双工方向自动切换，1 Mbps 下一个 bit 才 1 µs，软件切的抖动就在这个量级 |
| U2 | **LSM6DSV16XTR** | `C5267406` | 六轴 IMU + SFLP 硬件融合，LGA-14 |
| U3 | **SN74LVC2G241DCUR** | `C10430` | 三态缓冲，做单线半双工 |
| U4 | **HT7533-1** | `C14289` | 3.3V LDO，**耐压 30 V**（基础库免上料费） |
| J1/J2 | B3B-EH-A(LF)(SN) | `C160259` | Dynamixel 3P，**2.5 mm**，**与官方 HAT 同料号**，线束通用 |
| **J4/J5** | **B3B-PH-K-S(LF)(SN)** | 待定 | **飞特 3P，2.0 mm 立式**（2026-09-08 新增）。飞特 `AMP2.0-3P` 与 JST EH **间距不同、插不进对方**，所以两套座子并存，用哪种舵机插哪一组。<br>⚠️ **脚序与 J1/J2 完全相反**：`1=DXL_BUS / 2=VDD_BUS / 3=GND`，见 [接线表](hardware/imu_to_dxl/imu_to_dxl-接线表.md)。<br>⚠️ **料号待定** —— 飞特规格书只给了线端型号，板端没给。焊盘阵是三孔 2.0 mm 间距，与其它 2.0 mm 系列通用，换系列只改封装不动焊盘。<br>本体高约 **6.0 mm**，比 EH 立式的 8 mm 更适合 6.65 mm 的躯干内腔 |
| **J3** | **PZ254V-11-06P**（6P，2.54 mm） | `C492405` | **SWD + 串口 printf 合一**。脚序 `1=GND 2=SWDCLK 3=SWDIO 4=UART_TX 5=UART_RX 6=+3V3` —— 前 4 脚不变，原来的 4 针 SWD 排线插 1–4 仍可用。<br>UART 来自 U1 脚 16/17（`PA11[PA9]`/`PA12[PA10]`），经 `SYSCFG_CFGR1` 重映射成 **PA9 = `USART1_TX` / PA10 = `USART1_RX`**（DS12992 Rev 3, Table 12 脚注 4）。<br>**不上 USB**：G031 没有 USB 外设（手册全文零命中，Development support 只有 SWD），加 USB 要多一颗 CH340/CP2102，45×22 mm 板上不划算。调试走 SWD + RTT（`probe-rs` 支持 CMSIS-DAP 上跑 RTT，不停 CPU）；要普通 printf 就插 4/5 脚。<br>⚠️ Cortex-M0+ **没有 SWO/ITM**，别指望 SWO printf |
| C1–C4, C8 | **100 nF 0603** 50 V | `C14663` | 去耦（同官方 HAT 料号）。C1/C2 贴 U2 的 8/5 脚，C3 贴 U3 的 8 脚，C4 贴 U1 的 4 脚 |
| **C5** | **4.7 µF / 16 V / 0603 / X5R**<br>Samsung `CL10A475KO8NNNC` | `C19666` | **MCU 本地储能**，与 C4 一起构成 ST 要求的 `100 nF + 4.7 µF`。<br>依据 **DS12992 Rev 3, Figure 13「Power supply scheme」(p.44)**：`VDD/VDDA` 一路明确标注 `1 x 100 nF + 1 x 4.7 μF`，并 Caution 要求"尽可能贴近引脚，或放在 PCB 背面正对该脚"。<br>立创**基础库**。<br>⚠️ 本表此前把 C5 也写成 100 nF —— 两颗相同的 100 nF 并联只是容量翻倍，频响曲线不变、低频段仍然是空的，不符合手册 |
| **C6** | **10 µF / 25 V / 0805 / X5R**<br>Samsung `CL21A106KAYNNNE` | `C15850` | **LDO 输入**，直接挂 8.4 V 总线。立创**基础库**（免上料费）。<br>⚠️ 8.4 V 直流偏压下 X5R 衰减约 30–40%，实际约 6–7 µF —— 对 LDO 输入够用 |
| C7 | 10 µF 0603 10 V | `C19702` | LDO 输出（3.3 V），10 V 够用 |
| **R1/R2/R4/R5/R7** | **10 kΩ 0603** | `C25804` | 五个上拉，全部接到 3.3 V：<br>**R1 = SPI_CS**（必须）—— 上电与复位期间 PA4 是高阻，CS 浮着可能被 IMU 误判成 I²C 模式<br>**R2 = NRST** —— 芯片内部已有 ~40 kΩ 弱上拉，外面再加一个提高抗干扰<br>**R4 = DE**（必须，2026-09-06 补）—— `1OE#` 低电平使能发送。复位期间 PA1 高阻，这脚若浮成低电平，发送缓冲就打开，本板会往总线上灌数据、和 15 个舵机全撞车。此前只在 CS 上加了上拉、DE 上漏了，由社区评审指出<br>**R5 = DXL_DATA**（2026-09-06 补）—— 总线空闲时无人驱动，`2A` 这个 CMOS 输入浮着会有穿透电流，UART 也可能把噪声当起始位。本板应当自己定义空闲电平，不依赖主机<br>**R7 = RX_EN**（2026-09-07 补）—— `2OE` 原本硬接 3.3 V（接收常开）。改成经 R7 上拉、同时引一根线到 `U1.1 (PB7/PB8)`：默认行为完全不变，但固件多了一个「发送时关掉接收、免去回显」的选项。MCU 复位期间 PB7 高阻，靠 R7 保证 `2OE` 为高 |
| **R6** | **150 Ω 0603** | `C22808` | **数据线源端串阻**（2026-09-06 补）。与 D2 一起构成 HAT 同款的数据线保护：限制短路电流、软化边沿降 EMI。<br>1 Mbps 下 150 Ω 与总线电容构成的延迟约占比特时间的 3%，可接受。<br>依据：官方 HAT `dynamixel.kicad_sch` 用的是 `R33 150R + TH1 100R` 串联共 250 Ω |
| **D2** | **BZT52C5V1-7-F**<br>5.1 V 稳压管，**SOD-123** | `C151588` | **数据线钳位**（2026-09-06 补）。与官方 HAT 的 `D4` **同型号不同封装** —— HAT 用 `BZT52C5V1S`（SOD-323，`C151348`），本板改用 **SOD-123**（`C151588`）便于返修。<br>阴极接 `DXL_BUS`、阳极接地。飞特信号高电平规格是 2–5 V，74LVC 输入耐 5.5 V 本身不会坏，但此前**没有任何对付线上尖峰的器件**；舵机带电插拔是常态 |
| **D1** | **TVS `SMF12A`**，SOD-123FL | `C2943870` | ⚠️ **必须贴在 3P 连接器旁**。截止 **12 V** > 满电 8.4 V（正常工作不漏电）；击穿 13.3–14.7 V；**钳位 19.9 V** < C6 的 25 V。峰值功率 200 W。<br>封装 3.7 × 1.8 mm，比 SMA 小一半。要更大耐量可换 SMA 版 `SMAJ12A`（400 W）：ST `C132952` / Littelfuse `C148213` |
| **F1** | **PPTC `MF-NSMF020X-2`**，BOURNS，1206 | `C210358` | 本板故障时不拖垮整条舵机总线（官方 HAT 用 TH1 100R 热敏是同一思路）。<br>**额定 24 V**（母线 8.4 V，余量 2.9×）· 保持 **200 mA** · 跳闸 460 mA · 跳闸时间 0.6 s · AEC-Q200。<br>⚠️ **别选 0805 的常见型号** —— 那一档大多只有 **6 V** 额定（如 `0805L150SLYR`，而且它是 1.5 A 不是 150 mA），挂 8.4 V 母线直接不合格。**PPTC 的电压等级是硬约束** |
| J4 | 2×2 或 1×4 排针（可选，DNP） | — | 把 IMU  de  SPI 四线引出。将来若改成 SPI 直连主控，MCU 不贴、飞线即可，不用推翻整块板 |

#### 时钟：这个封装接不了无源晶振

查 **DS12992 Rev 3, Table 12「Pin assignment and description」(p.36)**，TSSOP20 那一列：

| 脚 | 名字 | 附加功能 |
|---|---|---|
| 2 | `PC14-OSC32_IN` | `OSC32_IN`, **`OSC_IN`** |
| 3 | `PC15-OSC32_OUT` | `OSC32_OUT`（**没有 `OSC_OUT`**）；交替功能里有 `OSC_EN` |

`PF0-OSC_IN` / `PF1-OSC_OUT` 在 TSSOP20 这一列是 `-`，**没引出来**。无源晶振要
`OSC_IN` + `OSC_OUT` 两个脚才能起振，所以：

| 方案 | 可行性 |
|---|---|
| 无源高速晶振（8/16 MHz + 两颗电容） | ❌ 没有 `OSC_OUT` |
| **有源晶振走 HSE 旁路**（单端时钟灌进 2 脚） | ✅ 3 脚还能当 `OSC_EN` 使能它 |
| 32.768 kHz 无源晶振（LSE） | ✅ 2/3 脚都有，但 **LSE 不能给 PLL 供时钟**（手册 p.21：PLL 只能吃 HSE 或 HSI16），只能拿来校准 HSI16 |

**默认用 HSI16。** 手册 **Table 41 (p.64)**  de Dados：

| 项 | 条件 | 范围 |
|---|---|---|
| 出厂频率 | V<sub>DD</sub> = 3.0 V, T<sub>A</sub> = 30 °C | 15.88–16.08 MHz，即 **−0.75% / +0.5%** |
| 温漂 | 0 ~ 85 °C | **±1%** |
| 温漂 | −40 ~ 125 °C | −2% / +1.5% |
| 电压漂移 | 1.62–3.6 V | ±0.1%（可忽略） |

叠加后 0–85 °C 内最坏约 **−1.85% / +1.55%**。1 Mbps 异步 UART  de 典型容差在 ±3% 量级，
主机侧（树莓派）是晶振精度、基本不占预算 —— **能跑，但吃掉约三分之二 de 余量**。

→ 原方案是**留出晶振位、默认不贴（DNP）**，出问题再拿烙铁焊Superior去。
**2026-09-07 改为默认贴片**，理由见abaixo「为什么从 DNP 改成贴片」。

##### 时钟位（2026-09-07 起**默认贴片**）

| 位号 | 器件 | 立创编号 | Instruções |
|---|---|---|---|
| **X1** | **F322516MUBCE2O**（雅晶鑫）<br>16 MHz **有源晶振** · CMOS · 1.8–3.3 V · ±10 ppm 常温 · **5 mA** · SMD3225-4P | `C5917307` | 走 **HSE 旁路**。脚位 `1=OE / 2=GND / 3=OUT / 4=VDD`。<br>**选它是因为 5 mA 是同封装候选里最低的** —— 见下方「为什么挑 5 mA 那颗」 |
| **C9** | 100 nF 0603 | `C14663` | X1 的 VDD 去耦，**贴着 X1 的 4 脚放**（实测 2.39 mm） |
| **R3** | 33 Ω 0603 | `C23140` | 时钟输出**源端串联阻尼**。16 MHz 方波边沿陡，一段走线就够产生振铃和 EMI。要省可换 0 Ω |

> 原选型是 `C387369`（星通时频 S3D16.000000B20F30T，10 mA）。下单时发现
> **立创贴片备料库没有这颗**（被归到「使用私有库存 de 元器件」，私有库 0），故更换。

###### 为什么从 DNP 改成贴片

DNP  de original理由本身成立：HSI16 最坏 −1.85%/+1.55%，1 Mbps UART 容差 ±3%，够用；
固件还能用定时器输入捕获反调 `HSITRIM`，误差压到 0.3% 以内。

**但那套 `HSITRIM` 自校准固件一行都还没写。** 第一版板子从没上电过，真出现通信误码时，
「是 HSI16 漂了还是Firmware写错了」会是个纯浪费时间 de 分叉。一颗 ¥1.9  de 晶振把这个分叉直接砍掉
—— **第一版能用钱买掉 de 不确定性都该买掉。**

###### 为什么挑 5 mA 那颗

同封装 de 候选精度都远远够用（要替代 de  HSI16 是 ±18500 ppm，随便哪颗都好一千倍），
**唯一跟本板设计有互动 de Parâmetros是工作电流**：

```
板上原本总电流 5–10 mA  →  LDO 压降 5.1 V  →  耗散约 51 mW
选 5 mA 晶振  → 总 11 mA → 56 mW → SOT-89 结温升 6~9 °C
选 10 mA 晶振 → 总 16 mA → 82 mW → 结温升 8~13 °C
```

两者都安全（F1 是 200 mA 保持，远不到），但**耗散翻倍会直接叠在评审提 de 
「LDO 发热影响 IMU」那条Superior**。5 mA 那颗只贵 ¥0.4，没有理由选 10 mA  de 。

###### ⚠️ 换料时 de 陷阱：四脚同封装，引脚定义相反

立创搜 `3225` 出来的**绝大多数是无源晶体**，其中 `C13738`（YSX321SL，基础库、
免换料费、十几万现货）看起来最像 —— 同样 SMD3225-4P、同样四个焊盘。
**但它贴Superior去，一Superior电就是 3.3 V 对地短路。**

| 脚 | 有源晶振（本板按此画） | 4 脚无源晶体 |
|---|---|---|
| 1 | 使能 OE | 晶体端子 |
| 2 | GND | **金属外壳（接地）** |
| 3 | 输出 OUT | 晶体端子 |
| 4 | **VDD** | **金属外壳（接地）** |

无源晶体的 2 脚和 4 脚是同一片金属盖、内部短接。本板 `X1.2 = GND`、`X1.4 = 3.3V`，
贴Superior去等于用那片盖子把 3.3 V e地连起来。

**换料时只认「有源晶振 / 振荡器 / OSC」这个标签**，写 `XTAL` / `晶体谐振器` /
`无源` 的一律不行。而且这条不是可选项 —— G031 的 TSSOP-20 **没引出 `OSC_OUT`**，
无源晶振在这颗 MCU Superior本来就接不了。

接法：

```
                     3.3V
                       │
   3.3V ── 1 OE   VDD 4 ┴── C9 100nF ── GND
           ┌───────────┐
           │    X1     │
           └───────────┘
    GND ── 2 GND  OUT 3 ── R3 33Ω ── OSC_IN ── U1 脚2 (PC14/OSC_IN)
```

`OE` 也可以改接 U1 脚 3（`PC15` 的 `OSC_EN` 交替功能）做软件使能，但那样固件要多管一件事，
默认直接接 3.3 V 常开。

> ⚠️ **这三颗都不进 BOM、但要进 PCB** —— 嘉立创Inferior单时不会给你贴、也不收料钱，
> 焊盘照样在板上。原理图里已按 `Add into BOM = no` / `Convert to PCB = yes` 设好。

#### 封装口径：阻容一律 0603，不用 0402

**2026-09-06 决定**：所有阻容从 0402 改为 **0603**，D2 从 SOD-323 改为 **SOD-123**。

理由不是「手焊不了 0402」——这块板Superior有 **LGA-14  de  LSM6DSV16X**（底部焊盘，
3 × 2.5 mm），本来就必须Superior热风或回流，有了那套Ferramentas 0402 也不难。

**真正 de 理由是Depuração期返修**：串阻要从 150 Ω 试到 33 Ω、某个Superior拉要摘掉、
去耦要加一颗——这些改动在 0603 Superior拿烙铁几秒钟就能做，0402 得重新架热风。
一块没打样Validação过 de 板子，第一版必然要改几次。

代价很小：板Superior 11 个 0402 换成 0603，多占约 16 mm²，
不到 45 × 22 mm 板面积 de  2%。而且 **0603 这几个值全在立创基础库**
（10 kΩ `C25804`、150 Ω `C22808`、33 Ω `C23140`、100 nF `C14663`），
比原来 0402  de 扩展库料还省Superior料费。

> C6（10 µF/25 V）保持 0805，C5（4.7 µF）e C7（10 µF）本来就是 0603。

#### 板框 e Instalação

Oficial**没有公开这块板 de 任何几何**（MJCF 里没有它 de 网格）。唯一 de 物证是固定它 de Peças impressas
`banana_pcb_locker`，实测反推：

| 量 | 值 | Fonte |
|---|---|---|
| 锁扣总长 | **54.05 mm** | 网格实测 |
| **两个定位耳 em 心距** | **≈ 34 mm** | 按 X 切片统计耳片位置 |
| 每个耳片 | ≈ 4 × 2.3 × 2.0 mm | 同Superior |
| 主体弧高 | 6.7 mm（Z 48.97→55.63） | 这就是「香蕉形」 de 由来 |

→ 推断原版板：**两个Instalação点间距 34 mm、长边 ≤ 54 mm、外形是弧 de **。

> 💡 **但锁扣本身是打印件**（最新文件与数量见 [CAD 仓库](https://github.com/fanhao375/microduck-replica-cad)）—— 所以**板框和锁扣可以一起重新设计**，
> 不必迁就原版 de 弧。原版做成弧大概是为了贴合躯干内壁省空间；自己复刻用**直板 + 改锁扣**
> 简单得多，弧形 PCB 布线e拼板都麻烦。

**建议板框：40 × 18 mm（宽松则 45 × 22），两个 M2 Instalação孔间距 34 mm，2 层板。**

- 元件净面积约 230 mm²（Conexão器主导：两个 JST EH 3P 各约 10 × 6 mm），
  两层板按 2–3 倍算需 460–700 mm² → 40 × 18 = 720 mm² 刚好
- 孔距保持 34 mm，**可直接用原版打印锁扣**
- ⚠️ **别为省钱压尺寸**：嘉立创 2 层板 100 × 100 mm 以内同价，画 25×20 e画 50×50 花一样 de 钱。
  尺寸只该由装配约束决定
- ⚠️ **Atenção元件高度**：锁扣内腔高 6.65 mm，而 JST EH 直插Conexão器本体高约 8 mm ——
  要么用卧式（side entry）封装，要么这块板根本不是被那个锁扣压 de 

#### 布局要点（比加器件更管用，而且不花钱）

**板型：2 层板，45 × 22 mm，贴片件全部放正面。**

| 决定 | 为什么 |
|---|---|
| **2 层足够** | 十几个器件、1 Mbps 不算高速。**最é necessário de 是Completo地平面**，2 层底层整片铺地就能做到，比多两层重要得多。成本Superior 2 层比 4 层便宜数倍 |
| **贴片件全在正面** | ① SMT 打样只贴一面，**费用直接减半**（双面要过两次炉）② 底层不被元件e过孔打断，**地平面Completo** |
| **连接器 THT，排在同一条边** | `B3B-EH-A` 与 SWD 排针都是插件。留着自己手焊能省一笔插件费（脚大、间距 2.5 mm，很好焊）。<br>⚠️ 但过孔会在底层地平面上开洞 —— **三个连接器都排在同一侧**，洞就集中在一边，不会把地平面切碎 |
| 45 × 22 而不是 40 × 18 | 单面布局é necessário 2–3 倍元件净面积（约 230 mm²）→ 460–700 mm²。45×22 ＝ 990 mm² 宽裕。<br>**反正嘉立创 100 × 100 以内同价，没必要压尺寸** |

**给 IMU  de 三条（Dados手册要求 + 常识，不花钱）：**

1. **`VDD` 与 `VDDIO` 各自 100 nF 就近去耦** —— 手册明确要求
2. **Completo地平面，IMU 正Inferior方不走高速线**
3. **IMU  de Alimentação走线 e  UART 收发部分分开**

> **不做Eletrônica隔离。** Oficial HAT Superior de 音频 codec、BMI088、ToF 全都直接挂同一套Alimentação，零隔离，
> 而机器人是能走 de 。更关键 de 是：真隔离要独立Alimentação，这块板就不能从总线取电了 ——
> **"挂在总线Superior de 第 16 个设备"这个设计前提就没了。**
>
> 💡 Alimentação入口留一个 **0 Ω 跳线位**：默认贴 0 Ω 直通；将来实测发现Alimentação噪声影响陀螺读数，
> 换成磁珠即可。成本一样，风险为零 —— 直接放磁珠反而可能 e 大电容形成 LC 谐振，放大某个频段。

#### ⚠️ 过压保护：它eServo共用一条母线

**这是这块板最容易被忽略的风险。** 15 个舵机挂在同一条 `+BATT` 上，减速、反转、堵转释放时
**反电动势会把母线抬高**；这块板挂在总线末端，线缆电感加Superior快速换向，输入端看到 de 尖峰比Bateria端更凶。

> Atenção威胁 de 性质是**正向过压，不是反接** —— 所以串联二极管不解决这个问题。

三道防线，按重要性排：

| 防线 | 器件 | 挡什么 | 状态 |
|---|---|---|---|
| **① 宽压 LDO** | `HT7533-1`（工作 30 V / 极限 33 V） | 持续过压。8.4 V 母线即使被抬到 17 V 也纹丝不动，**余量 3.5×** | ✅ 已选 |
| **② TVS** | `SMAJ12A`，**贴在连接器旁** | µs 级尖峰。截止 12 V > 满电 8.4 V（不漏电），钳位 19.9 V < C6 的 25 V | ⚠️ 本次补入 |
| **③ PPTC** | hold 100–200 mA | 本板短路时不把整条总线拉垮 —— 15 个Servo跟着掉电，机器人直接摔 | ⚠️ 本次补入 |

> **TVS  de 位置比型号更重要**：要贴在 3P Conexão器旁边，越靠近入口越好。放到 LDO 边Superior就晚了 ——
> 尖峰已经在板Superior跑了一圈。
>
> ⚠️ **反电动势 de 实际幅度este repositório没有实测**，取决于线缆电感 e 换向速度。Servo到货后拿示波器
> 在总线Superior量一次，再回来核对aqui de 选型。

> ⚠️ **另外两个坑，都会烧板：**
>
> **1. LDO 耐压。** 总线满电 8.4 V，常见型号全部不够（Inferior列为**工作电压Superior限 / 绝对最大值**）：
> AP2112K **6.0 / 6.5 V**、ME6211 **6.0 / 6.5 V**、TLV75533 **5.5 / 6.0 V**。
> 必须选 HT7533-1（工作 30 V，绝对最大 33 V）或同级。
>
> **2. 输入电容耐压 —— 此前本表选错了。** `C19702` 是 **10 V** X5R，挂在 8.4 V 总线上
> 只剩 1.2× 余量，且 X5R 在 8.4 V 直流偏置Inferior**实际容量不到标称 de 一半**，还要承受Servo
> 启停 de 瞬态。**C6 必须换 ≥25 V 料号**（0805 更稳妥）；C7 在 3.3 V 输出侧，10 V 够用。

---

## 五、Mecânica件

### 轴承（共 14 个）

| 规格 | Quantidade | 依据 |
|---|---|---|
| **Ø22 × 16 × 4** | **11** | `seeed_bearing__configuration__22x16x4` 引用 11 次 |
| **Ø15 × 10 × 3** | **3** | `seeed_bearing__configuration_default` 引用 3 次 |

### 紧Firmware（M2 为主，约 325 件）

整机 M2 级孔（Ø1.9–2.5 mm、包角 ≥300°）**按装配体用量加权共 237 个**，
其 em  **60 个在Servo本体Superior**（15 × 4）、21 个在轴承/PCB/Bateria等标准件Superior，
**结构件Superior约 156 个**。

> ⚠️ **口径Instruções**：este repositório早期写 de 「213 个」复算不出来，已更正为 237。
> 差异来自两点：早期统计**没有按装配体用量加权**（`leg` 实际 ×4、`hip_l` ×2 等），
> 且**混入了未使用 de 网格**。孔径分布表 e 本数字口径不同，见 [紧Firmware反推](docs/紧Firmware反推.md)。
>
> abaixo de Compra量按 325 件给，对 237 个孔位仍有 **1.37×** 余量，**不影响Inferior单**。

| 规格 | 建议Quantidade | 用途 |
|---|---|---|
| M2×4 内六角圆柱头 | 60 | 薄壁位 |
| M2×6 内六角圆柱头 | **80**（主力） | |
| M2×8 内六角圆柱头 | 40 | 孔深 3–5 mm |
| M2×12 内六角圆柱头 | 15 | 少量深孔 |
| M2 螺母 | 50 | 无攻丝处 |
| **M2 热熔螺母** | **60** | Peças impressas推荐，比直接攻丝牢得多 |
| M2.5×6 | 20 | 少量 Ø2.7 孔位 |

推导过程见 [紧Firmware反推](docs/紧Firmware反推.md)。

### Peças impressas e 轮滑变体

**模型、数量、材料和装配说明统一查看 [CAD 仓库](https://github.com/fanhao375/microduck-replica-cad#装配-bom)。** 先选飞特 HD-1910 或 XL330，再核对具体附件版本。本仓不再提供第二份打印 STL，也不再把上游 MJCF 的重复网格数量当成实际打印数量。

飞特 v2.1 已把轮滑变体 de 独立轮辋 e 轮胎改为 TPU 合体轮胎；09-15 旧 3MF 尚未同步此项。详见 [打印入口 e Versão提示](print/README.md)。走路用件e轮滑替换件也不能混用。

---

## 六、还没解决 de 空白

复刻到最后会卡在这两处，公开资料给不出答案：

1. **电池取电触点。** CAD 里只有打印件 `power_support`（×2），**没有任何触点 PCB 或簧片的模型**。
   Oficial用金属簧片还是市售 NP-F 转接板，判断不了。最省事 de 办法是买现成 de  NP-F Bateria转接板。
2. **线束。** Servo之间 de  Dynamixel 3P Conexão线长度、摄像头 MIPI 排线长度，Oficial没有任何图纸。
   Servo一般自带短线，但机器人内部走线长度要实测。

---

## DadosFonte

| Dados | Fonte |
|---|---|
| 零件数量 | 上游 `robot_walk.xml` 的 geom `mesh=` 引用计数 |
| 轮滑变体数量 | 上游 `robot_groundcontact_rollers.xml` |
| 螺丝Quantidade | STL 孔位几何反推，见 [紧Firmware反推](docs/紧Firmware反推.md) |
| 电子件型号 | Rust 源码、设备树、`robotd.toml`，见 [硬件方案逆向](docs/硬件方案逆向.md) |
| HAT 板参数 | 官方 KiCad 工程与 `production/` 生产文件 |
| 舵机规格 | [Robotis e-manual](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/) |
| 立创编号 | 嘉立创 EDA 元件库实时查询 |
