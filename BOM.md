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

⚠️ **Leia antes de encomendar a fabricação:**

1. **Esta placa não tem circuito de carga nem entrada USB-C.** O arquivo `pwr_supply_charge.kicad_sch` do repositório é uma **folha esquemática órfã** (`main.kicad_sch` não a inclui, e o cabeçalho ainda mostra o nome de outro projeto). Carregue a bateria com um carregador externo.
2. **Para abrir o projeto KiCad, instale primeiro [`lib_KiCAD`](https://github.com/pollen-robotics/lib_KiCAD)**; caso contrário, os símbolos não serão resolvidos. Isso não é necessário se você for fabricar a placa diretamente pelos Gerbers.

### Placa 2: `imu_to_dxl` — não há projeto público; é preciso desenhar a placa

| | |
|---|---|
| Status | 🔧 **Em reconstrução neste repositório**; consulte a [análise reversa da solução de hardware, seção 3](docs/硬件方案逆向.md) |
| Função | Apresenta a IMU como um servo Dynamixel escravo (ID **200**) no barramento dos servos |

**BOM de referência** (projeto deste repositório, não oficial):

| Referência | Componente | Código LCSC | Observações |
|---|---|---|---|
| U1 | **STM32G031F8P6** | `C529334` | MCU em TSSOP-20. ⚠️ **Esta é a escolha recomendada neste repositório, não uma conclusão da análise reversa**; não foi possível descobrir o MCU da placa oficial (veja a [análise reversa de hardware](docs/硬件方案逆向.md)). A versão F8 (64 KB de Flash), em vez da F6 (32 KB), deixa espaço para o firmware com dois protocolos.<br>**A ST foi escolhida por dois recursos concretos, não apenas pelo ecossistema**: ① é da mesma fabricante da IMU, e já existem o driver [`lsm6dsv16x-pid`](https://github.com/STMicroelectronics/lsm6dsv16x-pid) e o exemplo SFLP [`lsm6dsv16x_sensor_fusion.c`](https://github.com/STMicroelectronics/STMems_Standard_C_drivers/blob/master/lsm6dsv16x_STdC/examples/lsm6dsv16x_sensor_fusion.c); a inicialização do SFLP precisa configurar FIFO, taxa de fusão e escala na ordem certa, senão não gera dados. ② O USART do STM32G0 tem **DE (Driver Enable) por hardware**, que alterna automaticamente a direção do modo half-duplex; a 1 Mbps cada bit dura apenas 1 µs, a mesma ordem de grandeza da oscilação de uma comutação por software |
| U2 | **LSM6DSV16XTR** | `C5267406` | IMU de seis eixos com fusão de sensores SFLP por hardware, encapsulamento LGA-14 |
| U3 | **SN74LVC2G241DCUR** | `C10430` | Buffer tri-state para comunicação half-duplex em um único fio |
| U4 | **HT7533-1** | `C14289` | LDO de 3,3 V, **tensão máxima de 30 V** (componente da biblioteca básica, sem taxa de abastecimento) |
| J1/J2 | B3B-EH-A(LF)(SN) | `C160259` | Conectores Dynamixel de 3 pinos, **passo de 2,5 mm**, mesmo código usado no HAT oficial; os cabos são compatíveis |
| **J4/J5** | **B3B-PH-K-S(LF)(SN)** | A definir | Conectores Feetech de 3 pinos, **passo de 2,0 mm, verticais** (adicionados em 2026-09-08). O `AMP2.0-3P` da Feetech tem passo diferente do JST EH e não encaixa nele; por isso há os dois tipos de conector, cada qual para seu servo.<br>⚠️ **A ordem dos pinos é exatamente inversa à de J1/J2**: `1=DXL_BUS / 2=VDD_BUS / 3=GND`; consulte a [tabela de ligação](hardware/imu_to_dxl/imu_to_dxl-接线表.md).<br>⚠️ **Código da peça ainda não definido**: a especificação Feetech informa apenas o modelo do conector do cabo, não o da placa. O conjunto de três furos tem passo de 2,0 mm e é compatível com outras séries de mesmo passo; para trocar a série, basta alterar o footprint, não os pads. A peça tem cerca de **6,0 mm** de altura, adequada ao espaço interno de 6,65 mm do tronco e mais baixa que o conector EH vertical de 8 mm |
| **J3** | **PZ254V-11-06P** (6 pinos, passo de 2,54 mm) | `C492405` | **Conector combinado para SWD e serial**. Pinagem: `1=GND 2=SWDCLK 3=SWDIO 4=UART_TX 5=UART_RX 6=+3V3`. Os quatro primeiros pinos não mudam; o cabo SWD de 4 pinos existente continua servindo nos pinos 1–4.<br>A UART vem dos pinos 16/17 do U1 (`PA11[PA9]`/`PA12[PA10]`), remapeados por `SYSCFG_CFGR1` para **PA9 = `USART1_TX` / PA10 = `USART1_RX`** (DS12992 Rev. 3, nota 4 da Tabela 12).<br>**Sem USB**: o G031 não tem periférico USB (não há ocorrências de USB no manual; a seção de suporte ao desenvolvimento cita apenas SWD). Adicionar USB exigiria um CH340/CP2102 e não compensa numa placa de 45 × 22 mm. A depuração usa SWD + RTT (`probe-rs` oferece RTT com CMSIS-DAP sem parar a CPU); para usar `printf` serial comum, conecte os pinos 4/5.<br>⚠️ O Cortex-M0+ **não tem SWO/ITM**; não conte com `printf` por SWO |
| C1–C4, C8 | **100 nF 0603**, 50 V | `C14663` | Desacoplamento (mesmo código do HAT oficial). C1/C2 ficam nos pinos 8/5 do U2, C3 no pino 8 do U3 e C4 no pino 4 do U1 |
| **C5** | **4,7 µF / 16 V / 0603 / X5R**<br>Samsung `CL10A475KO8NNNC` | `C19666` | **Reserva local de energia do MCU**; junto com C4, atende à exigência da ST de `100 nF + 4,7 µF`.<br>A **Figura 13 (“Power supply scheme”), página 44, do DS12992 Rev. 3** especifica `1 x 100 nF + 1 x 4.7 μF` na linha `VDD/VDDA` e recomenda colocar os componentes o mais perto possível do pino ou na face oposta da placa, diretamente sob ele.<br>Componente da **biblioteca básica** da LCSC.<br>⚠️ Antes, esta lista também especificava 100 nF para C5. Dois capacitores iguais de 100 nF em paralelo apenas duplicam a capacitância, sem alterar a curva de resposta; ainda faltaria capacitância em baixas frequências, em desacordo com o manual |
| **C6** | **10 µF / 25 V / 0805 / X5R**<br>Samsung `CL21A106KAYNNNE` | `C15850` | **Entrada do LDO**, diretamente no barramento de 8,4 V. Componente da **biblioteca básica** da LCSC (sem taxa de abastecimento).<br>⚠️ Com polarização contínua de 8,4 V, um X5R perde cerca de 30–40% da capacitância e fica com aproximadamente 6–7 µF, ainda suficiente para a entrada do LDO |
| C7 | 10 µF 0603 10 V | `C19702` | Saída do LDO (3,3 V); 10 V são suficientes |
| **R1/R2/R4/R5/R7** | **10 kΩ 0603** | `C25804` | Cinco resistores de pull-up, todos ligados a 3,3 V:<br>**R1 = SPI_CS** (obrigatório): durante a energização e a reinicialização, PA4 fica em alta impedância; sem pull-up, a IMU pode interpretar o CS flutuante como modo I²C.<br>**R2 = NRST**: o chip já tem um pull-up interno fraco de cerca de 40 kΩ; o resistor externo melhora a imunidade a ruído.<br>**R4 = DE** (obrigatório; adicionado em 2026-09-06): nível baixo em `1OE#` habilita a transmissão. Durante a reinicialização, PA1 fica em alta impedância; se o pino flutuar para baixo, o buffer de transmissão será habilitado e esta placa poderá enviar dados ao barramento, colidindo com os 15 servos. Uma revisão da comunidade observou que o pull-up havia sido incluído no CS, mas esquecido no DE.<br>**R5 = DXL_DATA** (adicionado em 2026-09-06): quando o barramento está ocioso, ninguém dirige o sinal; a entrada CMOS `2A` flutuante pode conduzir corrente, e a UART pode interpretar ruído como bit de início. A placa deve definir seu próprio nível de repouso, sem depender do controlador.<br>**R7 = RX_EN** (adicionado em 2026-09-07): `2OE` era ligado diretamente a 3,3 V (recepção sempre ativa). O pull-up por R7, junto com um fio até `U1.1 (PB7/PB8)`, mantém o comportamento padrão e permite ao firmware desativar a recepção durante a transmissão para evitar eco. PB7 fica em alta impedância durante a reinicialização do MCU; R7 mantém `2OE` em nível alto |
| **R6** | **150 Ω 0603** | `C22808` | **Resistor em série na origem da linha de dados** (adicionado em 2026-09-06). Junto com D2, oferece proteção semelhante à do HAT: limita a corrente de curto-circuito e suaviza as bordas para reduzir EMI.<br>A 1 Mbps, o atraso causado pelos 150 Ω e pela capacitância do barramento corresponde a cerca de 3% do tempo de um bit, o que é aceitável.<br>Referência: o esquema oficial do HAT (`dynamixel.kicad_sch`) usa R33 de 150 Ω + TH1 de 100 Ω em série, totalizando 250 Ω |
| **D2** | **BZT52C5V1-7-F**<br>Diodo zener de 5,1 V, **SOD-123** | `C151588` | **Limitador de tensão da linha de dados** (adicionado em 2026-09-06). Mesmo modelo do D4 do HAT oficial, mas com encapsulamento diferente: o HAT usa `BZT52C5V1S` (SOD-323, `C151348`); esta placa usa **SOD-123** (`C151588`), mais fácil de reparar.<br>Ligue o cátodo a `DXL_BUS` e o ânodo ao terra. O nível alto especificado para o sinal Feetech é de 2–5 V, e a entrada 74LVC suporta até 5,5 V; portanto, ela não seria danificada por esse nível. Porém, antes **não havia nenhum componente para proteger contra picos na linha**, e conectar servos com a alimentação ligada é comum |
| **D1** | **TVS `SMF12A`**, SOD-123FL | `C2943870` | ⚠️ **Instale junto ao conector de 3 pinos.** Tensão de trabalho de **12 V**, acima dos 8,4 V da bateria totalmente carregada (sem fuga durante o uso normal); ruptura entre 13,3–14,7 V; **tensão de limitação de 19,9 V**, abaixo dos 25 V suportados por C6. Potência de pico de 200 W.<br>O encapsulamento mede 3,7 × 1,8 mm, metade do tamanho de um SMA. Para maior capacidade, use a versão SMA `SMAJ12A` (400 W): ST `C132952` / Littelfuse `C148213` |
| **F1** | **PPTC `MF-NSMF020X-2`**, BOURNS, 1206 | `C210358` | Evita que uma falha nesta placa derrube todo o barramento dos servos (a mesma ideia do termistor TH1 de 100 Ω no HAT oficial).<br>**Tensão nominal de 24 V** (barramento de 8,4 V, margem de 2,9×) · corrente de manutenção **200 mA** · disparo a 460 mA · tempo de disparo de 0,6 s · AEC-Q200.<br>⚠️ **Não escolha os modelos 0805 comuns**: a maioria tem tensão nominal de apenas **6 V** (por exemplo, `0805L150SLYR`, que também é de 1,5 A, e não 150 mA); não serve para um barramento de 8,4 V. **A tensão nominal do PPTC é uma exigência rígida** |
| J4 | Conector de pinos 2×2 ou 1×4 (opcional, DNP) | — | Expõe os quatro sinais SPI da IMU. Se no futuro a IMU for ligada diretamente ao controlador por SPI, basta não montar o MCU e instalar fios; não será necessário redesenhar a placa |

#### Clock: este encapsulamento não permite ligar um cristal passivo

Consulte a coluna TSSOP-20 da **Tabela 12 (“Pin assignment and description”), página 36, do DS12992 Rev. 3**:

| Pino | Nome | Função alternativa |
|---|---|---|
| 2 | `PC14-OSC32_IN` | `OSC32_IN`, **`OSC_IN`** |
| 3 | `PC15-OSC32_OUT` | `OSC32_OUT`（**没有 `OSC_OUT`**）；交替功能里有 `OSC_EN` |

Na coluna TSSOP-20, `PF0-OSC_IN` / `PF1-OSC_OUT` aparecem como `-`, **ou seja, não estão disponíveis**. Um cristal passivo precisa dos dois pinos, `OSC_IN` e `OSC_OUT`, para oscilar. Portanto:

| Opção | Viabilidade |
|---|---|
| Cristal passivo de alta frequência (8/16 MHz + dois capacitores) | ❌ Não há pino `OSC_OUT` |
| **Oscilador ativo no modo bypass de HSE** (clock de ponta única no pino 2) | ✅ O pino 3 também pode habilitá-lo como `OSC_EN` |
| Cristal passivo de 32,768 kHz (LSE) | ✅ Os pinos 2/3 estão disponíveis, mas **LSE não pode fornecer clock ao PLL** (manual, p. 21: o PLL só aceita HSE ou HSI16); só pode ser usado para calibrar o HSI16 |

**Por padrão, use HSI16.** Os dados da **Tabela 41, página 64, do manual**:

| Parâmetro | Condição | Faixa |
|---|---|---|
| Frequência de fábrica | V<sub>DD</sub> = 3,0 V, T<sub>A</sub> = 30 °C | 15,88–16,08 MHz, ou **−0,75% / +0,5%** |
| Variação com a temperatura | 0 a 85 °C | **±1%** |
| Variação com a temperatura | −40 a 125 °C | −2% / +1,5% |
| Variação com a tensão | 1,62–3,6 V | ±0,1% (desprezível) |

Somadas, as variações podem chegar a **−1,85% / +1,55%** entre 0 e 85 °C. A tolerância típica de uma UART assíncrona a 1 Mbps é da ordem de ±3%; o clock do controlador (Raspberry Pi) vem de um cristal e quase não consome essa margem. **Funciona, mas usa cerca de dois terços da tolerância disponível.**

→ A proposta original era **reservar o espaço do cristal e não montá-lo por padrão (DNP)**, soldando-o depois apenas se surgisse um problema.
**Em 2026-09-07, a decisão mudou para montagem padrão**; veja abaixo “Por que deixar de usar DNP e montar o componente”.

##### Componentes do clock (montados por padrão desde 2026-09-07)

| Referência | Componente | Código LCSC | Observações |
|---|---|---|---|
| **X1** | **F322516MUBCE2O** (Yajingxin)<br>Oscilador ativo de 16 MHz · CMOS · 1,8–3,3 V · ±10 ppm à temperatura ambiente · **5 mA** · SMD3225-4P | `C5917307` | Opera em **bypass de HSE**. Pinos: `1=OE / 2=GND / 3=OUT / 4=VDD`.<br>**Foi escolhido porque, entre os candidatos com o mesmo encapsulamento, consome menos corrente: 5 mA**. Veja abaixo “Por que escolher o modelo de 5 mA” |
| **C9** | 100 nF 0603 | `C14663` | Desacoplamento da alimentação VDD de X1; **instale junto ao pino 4 de X1** (distância medida: 2,39 mm) |
| **R3** | 33 Ω 0603 | `C23140` | **Resistor de amortecimento em série na saída do clock**. As bordas rápidas da onda quadrada de 16 MHz podem gerar ringing e EMI até em uma trilha curta. Para economizar, pode ser substituído por 0 Ω |

> A escolha original era `C387369` (Singo S3D16.000000B20F30T, 10 mA). Ao fazer o pedido, descobrimos que **esse componente não estava disponível no estoque de montagem da LCSC** (estava classificado como componente de estoque privado, com estoque privado igual a zero); por isso, foi substituído.

###### Por que deixar de usar DNP e montar o componente

O motivo original para usar DNP era válido: no pior caso, o HSI16 varia −1,85%/+1,55%, dentro da tolerância de ±3% da UART a 1 Mbps. O firmware também poderia ajustar `HSITRIM` por captura de entrada do timer e reduzir o erro para menos de 0,3%.

**Mas ainda não foi escrita nenhuma linha do firmware de autocalibração do `HSITRIM`.** A primeira versão da placa nunca foi energizada; se ocorrer um erro de comunicação, tentar descobrir se a causa é a deriva do HSI16 ou um bug do firmware seria uma investigação que desperdiça tempo. Um oscilador de ¥ 1,9 elimina essa dúvida — **na primeira versão, vale pagar para remover incertezas quando isso é possível.**

###### Por que escolher o modelo de 5 mA

Todos os candidatos do mesmo encapsulamento têm precisão mais que suficiente (o HSI16 que será substituído varia até ±18.500 ppm; qualquer um dos modelos é mil vezes mais preciso). **O único parâmetro com impacto no projeto desta placa é a corrente de operação:**

```
Corrente total original da placa: 5–10 mA → queda de 5,1 V no LDO → dissipação de cerca de 51 mW
Oscilador de 5 mA → total de 11 mA → 56 mW → aumento de 6–9 °C na temperatura de junção do SOT-89
Oscilador de 10 mA → total de 16 mA → 82 mW → aumento de 8–13 °C na temperatura de junção
```

Ambos são seguros (F1 suporta 200 mA, muito acima desses valores), mas **o dobro da dissipação se soma diretamente à preocupação levantada na revisão de que “o aquecimento do LDO pode afetar a IMU”**. O modelo de 5 mA custa apenas ¥ 0,4 a mais; não há motivo para escolher o de 10 mA.

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
