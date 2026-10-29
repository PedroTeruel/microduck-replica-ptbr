# Hardware novo (2026-10)

São três placas, todas em projetos EasyEDA Pro (`.eprj2`), com esquema e PCB no mesmo arquivo. Cada placa tem uma pasta própria:

| Pasta | Placa | Estado em 2026-10-20 |
|---|---|---|
| [`imu_to_dxl_1V0A/`](imu_to_dxl_1V0A/) | Placa IMU de barramento v2. A versão antiga e o firmware estão em [`../imu_to_dxl/`](../imu_to_dxl/). | Roteamento concluído. O DRC ainda aponta 12 definições duplicadas de furos de montagem, sem impacto na fabricação. A placa ainda não chegou para testes. |
| [`wire_hub_1V0A/`](wire_hub_1V0A/) | Hub do barramento de servos: entrada da bateria e distribuição do barramento. | Ainda sem protótipo; é preciso trocar o conector CN1, que ficou alto demais. |
| [`POGO_PIN_1V0A/`](POGO_PIN_1V0A/) | Placa de conexão da bateria, com dois conectores banana e pontos para soldar fios. | Furos, pads e trilhas foram revisados com base na placa de referência; ainda sem protótipo. |

Cada pasta contém:

- `<nome-da-placa>.eprj2`: projeto da placa;
- `<nome-da-placa>-PCB.step`: modelo 3D da placa completa, para conferir a estrutura mecânica;
- `<nome-da-placa>-原理图.pdf`: esquema; por enquanto, somente o da placa IMU está disponível.

Os arquivos Gerber, a BOM e a tabela de conexões ainda não estão disponíveis. Veja a aparência da placa antiga em [`../imu_to_dxl/`](../imu_to_dxl/).

## imu_to_dxl_1V0A: placa IMU de barramento v2

A função é a mesma da placa antiga: a LSM6DSV16X fica conectada a um STM32G031, e o microcontrolador atua como um dispositivo escravo no mesmo barramento de linha única e meia-duplex dos servos. Consulte o [protocolo e o firmware](../imu_to_dxl/). O circuito foi mantido, mas o layout foi refeito e os conectores foram trocados.

| Referência | Modelo | Função |
|---|---|---|
| U1 | STM32G031F8P6 | Microcontrolador principal |
| U2 | LSM6DSV16XTR | IMU |
| U3 | SN74LVC2G241DCUR | Transceptor do barramento meia-duplex |
| U4 | HT7533-1 | LDO de 3,3 V |
| F1 / D1 | MF-NSMF020X-2 / SMF12A | Fusível rearmável / TVS |
| D2 | BZT52C5V1 | Limitador de 5,1 V na linha de dados do barramento |
| R6 | 0 Ω (C21189) | Resistor em série com o barramento; na primeira placa era 150 Ω |
| J1 | A2007WR-3P | Barramento de servos, conector angular 3P de 2,0 mm. 1 = DXL_BUS, 2 = VDD_BUS, 3 = GND. |
| J2 | BM03B-ACHSS-GAN-ETF | Conector ACH 3P horizontal de 1,2 mm. 1 = GND, 2 = VDD_BUS, 3 = DXL_BUS. |
| J3 | PZ254V-11-06P | Porta de depuração 6P de 2,54 mm: 1 = GND, 2 = SWDCLK, 3 = SWDIO, 4 = UART_RX, 5 = UART_TX, 6 = 3.3V. |

Há também 24 resistores, capacitores e outros componentes 0402/0603.

### Diferenças em relação à placa antiga

- O conector de servo antigo `B3B-PH-K-S` não encaixava no plugue dos cabos Feetech, como registrado no README antigo. Nesta versão, foi trocado por A2007WR-3P.
- O cristal externo X1 foi removido: o firmware já usa o oscilador interno HSI16. O firmware 0.2.0 pode ser gravado sem modificações.
- R6 passou de 150 Ω para 0 Ω. Cada servo já tem um resistor de pull-up no barramento; em paralelo, o resistor em série pode elevar o nível baixo. Quando a placa chegar, meça o nível baixo do barramento durante a resposta.
- U2 foi girado 180° e o formato da placa também mudou. Depois de montar a placa no robô, será preciso redefinir o mapeamento dos eixos da IMU. O firmware não gira a orientação original fornecida pelo chip; ajuste apenas a rotação de montagem no computador de placa única e valide a imobilidade nos três eixos.
- A lista de pendências da v2 no README antigo não foi implementada nesta placa: **ela não tem botão de reset nem LED de estado da execução**.
- A PCB não tem modelo 3D do conector J3; ele não aparece no arquivo STEP exportado.

## wire_hub_1V0A: hub do barramento

Não há componentes ativos, somente conectores. Todos usam as três redes `Battery`, `DXL_BUS` e `GND`.

| Referência | Modelo | Especificação |
|---|---|---|
| J1 | HC-1.2-3PWT | Conector horizontal 3P de 1,2 mm, compatível com Pico-EZmate, 1,5 A. |
| J2 | BM03B-ACHSS-GAN-ETF | Conector ACH horizontal 3P de 1,2 mm, 2 A. |
| J3, J4 | A2007WR-3P | Conector angular 3P de 2,0 mm, 4 A. |
| J5, J6 | A2007WV-3P | Conector reto 3P de 2,0 mm, 4 A. |
| CN1 | DB125-2.54-2P-GN-S | Entrada da bateria, borne verde com parafuso, 7 A; **altura de 8,4 mm acima da placa**. |

A pinagem corresponde à da placa IMU. J1 e J2 do hub e J2 da placa IMU usam 1 = GND, 2 = alimentação, 3 = DXL_BUS; conecte-os com um cabo reto. J3–J6 do hub e J1 da placa IMU usam 1 = DXL_BUS, 2 = alimentação, 3 = GND.

Pendência:

- CN1 é alto demais e interfere na estrutura. Nesse local, só cabem componentes de até 5 mm. Opções: um borne SMD de pressão com passo de 4 mm, como WAGO 2060, com 4,5 mm de altura, ou soldar os fios diretamente sem borne.

## POGO_PIN_1V0A: placa de conexão da bateria

O contorno e os furos foram adaptados da placa de referência `banana_pcb` (projeto KiCad disponível somente em Gerber). A placa mede 39,19 × 6,79 mm.

| Posição | Rede | Dimensões |
|---|---|---|
| U2 (esquerda) | GND | Furo metalizado de Ø1,7 mm para conector banana, pad de Ø3,2 mm. |
| U1 (direita) | Battery | Igual ao anterior; distância entre os centros dos furos: 33,8 mm. |
| Dois pads entre eles | GND à esquerda, Battery à direita | Pads SMD na camada superior de 2,4 × 4,4 mm, separados por 4,0 mm, sem furos, para soldar fios. |

A posição dos pads também segue a placa de referência: o pad GND fica a 10,98 mm do furo esquerdo e o pad Battery, a 14,98 mm. Ambos ficam 0,59 mm abaixo da linha entre os centros dos furos. A separação de 4,0 mm também permite instalar diretamente um borne de pressão com passo de 4 mm.

Apesar do nome POGO_PIN, a placa não tem pinos de mola: ela usa pads para soldar fios.
