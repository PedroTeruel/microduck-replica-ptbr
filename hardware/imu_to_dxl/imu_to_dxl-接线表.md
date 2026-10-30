# Tabela de fiação da imu_to_dxl

> Para conferir a montagem manual. As referências dos componentes coincidem com as de `microduck-replica/BOM.md`.
> Estado: proposta de projeto, ainda sem validação física.

## Lista de componentes (inclui códigos da JLC)

| Ref. | Componente | Encapsulamento | Código JLC |
|---|---|---|---|
| U1 | STM32G031F8P6 | TSSOP-20 | C529334 |
| U2 | LSM6DSV16XTR | LGA-14 | C5267406 |
| U3 | SN74LVC2G241DCUR | VSSOP-8 | C10430 |
| U4 | HT7533-1 (entrada de 30 V, 100 mA) | SOT-89 | C14289 |
| F1 | PPTC MF-NSMF020X-2 (24 V / corrente de manutenção de 200 mA) | 1206 | C210358 |
| D1 | TVS SMF12A | SOD-123FL | C2943870 |
| R1, R2, R4, R5 | 10 kΩ | **0603** | C25804 |
| R6 | 150 Ω | **0603** | C22808 |
| D2 | Diodo Zener BZT52C5V1, 5,1 V | **SOD-123** | C151588 |
| C1–C4, C8 | 100 nF, 50 V | **0603** | C14663 |
| C5 | 4,7 µF / 16 V X5R | 0603 | C19666 |
| C6 | 10 µF / 25 V X5R | 0805 | C15850 |
| C7 | 10 µF / 10 V | 0603 | C19702 |
| J1, J2 | B3B-EH-A (3 pinos, **2,5 mm**, cabo Dynamixel / HAT oficial) | Vertical | C160259 |
| **J4, J5** | **B3B-PH-K-S (3 pinos, 2,0 mm, compatível com `AMP2.0-3P` Feetech)** | Vertical | A confirmar |
| J3 | Barra de pinos de 6 vias para SWD + serial, PZ254V-11-06P | Vertical | C492405 |

## Tabela de redes (23 redes)

### VDD_BUS — tensão original do barramento dos servos (bateria 2S, 6,0–8,4 V)

J1.2 · J2.2 · **J4.2** · **J5.2** · F1.1

> `VDD_BUS` passa diretamente por trilhas largas nos quatro conectores: `J1.2 → J2.2 → J5.2 → J4.2`, com 0,76 mm em todo o trecho.

### VDD_F — depois do fusível

F1.2 · cátodo D1 · C6.1 · C8.1 · U4.2 (Vin)

### +3V3

U4.3 (Vout) · C7.1 · U1.4 (VDD/VDDA) · C4.1 · C5.1 · R2.2 ·
U2.5 (Vdd_IO) · U2.8 (Vdd) · C1.1 · C2.1 · R1.2 ·
U3.8 (VCC) · C3.1 · J3.6 · **R7.2**

### GND

Ânodo D1 · C6.2 · C8.2 · U4.1 (GND) · C7.2 ·
U1.5 (VSS/VSSA) · C4.2 · C5.2 ·
U2.2 (SDx) · U2.3 (SCx) · U2.6 (GND) · U2.7 (GND) · C1.2 · C2.2 ·
U3.4 (GND) · C3.2 · J1.1 · J2.1 · J3.1 · **J4.3** · **J5.3** · C9.2 · X1.2

### Reset

| Rede | Pontos de conexão |
|---|---|
| NRST | U1.6 (PF2-NRST) · R2.1 |

A outra extremidade de R2 (R2.2) liga-se a +3V3 e forma um pull-up de 10 kΩ.

### Quatro resistores pull-up (R1/R2/R4/R5, cada outro terminal ligado a +3V3)

| Ref. | O que mantém em nível definido | Motivo |
|---|---|---|
| **R1** | `SPI_CS` | Durante a energização e o reset, PA4 fica em alta impedância; se CS flutuar, a IMU pode ser identificada incorretamente como modo I²C ou interpretar ruído como comando. **Necessário** |
| **R2** | `NRST` | O chip já tem pull-up interno fraco de ~40 kΩ; acrescentar 10 kΩ aumenta a imunidade a ruído. Reforço |
| **R4** | `DE` | `1OE#` **habilita transmissão em nível baixo**. Durante o reset, PA1 fica em alta impedância; se esse pino flutuar baixo, o buffer transmite e pode conflitar com os 15 servos. **Necessário** |
| **R5** | `DXL_DATA` | Quando ninguém aciona o barramento, a entrada CMOS `2A` pode flutuar, consumir corrente de passagem e fazer a UART interpretar ruído como bit de início. A placa define o nível de repouso sem depender do controlador |

> R4 e R5 foram adicionados em 2026-09-06, seguindo a revisão da comunidade. Antes, havia pull-up somente em CS; **foi uma omissão não aplicar o mesmo princípio ao DE**.

### IMU (SPI de quatro fios + duas interrupções)

| Rede | U1 (STM32) | U2 (LSM6DSV16X) | Outros |
|---|---|---|---|
| SPI_CS | 11 · PA4 | 12 · CS | R1.1 (R1.2 ligado a +3V3 como pull-up) |
| SPI_SCK | 12 · PA5 | 13 · SCL | |
| SPI_MISO | 13 · PA6 | 1 · SDO/SA0 | |
| SPI_MOSI | 14 · PA7 | 14 · SDA | |
| IMU_INT1 | 7 · PA0 | 4 · INT1 | |
| IMU_INT2 | 15 · PB0/PA8 | 9 · INT2 | |

### Barramento half-duplex (U3 = buffer duplo SN74LVC2G241)

| Rede | Pontos de conexão |
|---|---|
| MCU_TX | U1.9 (PA2 · USART2_TX) · U3.2 (1A) |
| MCU_RX | U1.10 (PA3 · USART2_RX) · U3.3 (2Y) |
| DE | U1.8 (PA1 · USART2_DE) · U3.1 (1OE#) · **R4.1** |
| DXL_DATA | U3.6 (1Y) · U3.5 (2A) · **R5.1** · **R6.1** — lado do buffer |
| **DXL_BUS** | **R6.2** · **cátodo D2** · J1.3 · J2.3 · **J4.1** · **J5.1** — lado dos conectores |
| **RX_EN** | **U1.1 (PB7/PB8)** · **U3.7 (2OE)** · **R7.1** — habilitação do buffer de recepção, adicionado em 2026-09-07 |

`U3.7 (2OE)` antes estava ligado diretamente a +3V3. Em 2026-09-07, foi movido para a rede `RX_EN`: há um pull-up R7 de 10 kΩ a +3V3 e uma ligação ao pino **U1.1 (PB7/PB8)**.

**O comportamento padrão não muda** — durante o reset do MCU, PB7 fica em alta impedância; R7 mantém `2OE` alto e o buffer de recepção permanece habilitado. Sem alterações no firmware, o funcionamento continua igual. É uma opção reservada: para desabilitar a recepção durante a transmissão, colocar PB7 em nível baixo como saída push-pull e também habilitar o pull-up interno do pino `MCU_RX` para evitar que RX flutue quando `2Y` estiver em alta impedância.

### Porta de depuração J3 (6 pinos, `PZ254V-11-06P` / `C492405`)

| Pino | Rede | Origem |
|---|---|---|
| 1 | GND | |
| 2 | SWDCLK | U1.19 (PA14) |
| 3 | SWDIO | U1.18 (PA13) |
| 4 | **UART_RX** | **U1.17** `PA12[PA10]` → remapeado para **PA10** = `USART1_RX`; ligar ao TX do USB-TTL (nível de 3,3 V) |
| 5 | **UART_TX** | **U1.16** `PA11[PA9]` → remapeado para **PA9** = `USART1_TX`; ligar ao RX do USB-TTL (nível de 3,3 V) |
| 6 | +3V3 | Referência de tensão VTref do depurador; não ligar a 5 V |

**Correção de 2026-09-21:** conferimos o [PDF do esquemático de 2026-09-08](imu_to_dxl-Princípio图.pdf). SWD usa os pinos **1, 2, 3 e 6**; os pinos 4/5 são seriais. Não conecte em bloco um cabo antigo de quatro pinos nos pinos 1–4 nem use o pino 4 como 3,3 V ou VTref. Antes de conectar, confira a marcação do pino 1 na placa e a pinagem do depurador.

O remapeamento dos pinos 16/17 é configurado por `SYSCFG_CFGR1` (DS12992 Rev 3, nota 4 da Tabela 12).

**Sem USB direto:** o STM32G031 **não tem periférico USB** (a busca no manual não encontrou USB; “Development support” menciona somente “serial wire debug (SWD)”). Adicionar USB exigiria um CH340/CP2102 e não compensa numa placa de 45×22 mm. SWD basta para depurar:

| Método | Necessário | Descrição |
|---|---|---|
| **RTT** (recomendado) | Pinos 1, 2, 3 e 6 de J3 | `probe-rs` oferece RTT via CMSIS-DAP, lê diretamente a RAM do alvo e **não interrompe a CPU**, sem afetar o ciclo de controle de 50 Hz |
| printf serial | Pinos 4/5 de J3 + qualquer USB-TTL | Usa USART1 |
| Semihosting | Somente J3 | Cada printf interrompe a CPU e prejudica o ciclo de controle; **não use** |
| ~~SWO / ITM~~ | — | **Não existem no Cortex-M0+**; só em M3 ou superior |

### Conectores de servo — duas séries; ⚠️ **as pinagens são opostas**

A placa tem quatro conectores de barramento dos servos em dois pares; os três fios de cada par estão ligados em paralelo (mesmo nó elétrico), **mas a ordem dos pinos entre os pares é oposta**, pois os cabos dos dois fabricantes têm pinagens diferentes.

**`J1` / `J2` — `B3B-EH-A`, 2,5 mm, para cabos Dynamixel / HAT oficial**

| Pino | Rede |
|---|---|
| 1 | GND |
| 2 | VDD_BUS |
| 3 | **DXL_BUS** |

**`J4` / `J5` — `B3B-PH-K-S`, 2,0 mm, para cabos Feetech HD-1910**

| Pino | Rede |
|---|---|
| 1 | **DXL_BUS** |
| 2 | VDD_BUS |
| 3 | **GND** |

> ⚠️ **Não copie a pinagem de `J1` para `J4`.** A especificação Feetech “HD-1910-C001 串型规格书”, A/0, p. 3/7, itens 6–7, informa que o cabo tem `1=Signal / 2=Vcc / 3=GND`, em ordem inversa à ligação Dynamixel. Felizmente, os passos de **2,0 mm e 2,5 mm não se encaixam**; isso impede fisicamente a troca e deixa apenas o risco de erro no desenho. A pinagem dos quatro conectores foi conferida novamente na netlist da PCB em 2026-09-08 e está correta.
>
> Note também que `AMP2.0` tem 2,0 mm e `JST EH`, 2,5 mm: o cabo Feetech não entra em `J1`/`J2`.
> ⚠️ Teste físico da primeira placa (2026-09-17): a carcaça do `B3B-PH-K-S` não encaixa no plugue Feetech; funcionou somente após remover a carcaça e manter os pinos. Na v2, usar um conector testado com o cabo real.
> O inverso também vale: conecte cada tipo de servo somente ao par correto.

> 📌 **O pino 3 estava identificado incorretamente como `DXL_DATA` nesta tabela.** Após a inclusão do resistor em série R6 de 150 Ω em 2026-09-06, o lado do buffer (`DXL_DATA`) e o lado dos conectores (`DXL_BUS`) são redes distintas. O conector usa `DXL_BUS`. Corrigido em 2026-09-08.

## Pinos sem conexão

- U1: **3 (PC15-OSC32_OUT) e 20 (PB3/PB4/PB5/PB6)**
  - O pino 3 chega aos pads e, junto com o pino 2, forma a posição reservada para cristal ativo (não montado por padrão); consulte abaixo a seção “Clock”.
  - O pino 20 é o único GPIO completamente livre (agrupa PB3/PB4/PB5/PB6 e oferece mais flexibilidade), reservado para uso futuro.
  - O pino 1 (PB7/PB8) estava livre, mas desde 2026-09-07 é usado por `RX_EN`.
  - O pino 2 (PC14-OSC32_IN) está ligado a `OSC_IN`; os pinos 16/17 (PA9/PA10) estão ligados a `UART_TX`/`UART_RX`. Antes estavam listados por engano como livres; corrigido em 2026-09-07.
- U2: 10 (OCS_Aux) e 11 (SDO_Aux) — SPI auxiliar não utilizado; ST DS13510 permite deixá-los abertos. Como opção conservadora, ligar OCS_Aux a Vdd_IO.

**U2.2 (SDx) e U2.3 (SCx) devem ser ligados ao terra**; não os deixe em aberto — ST DS13510 Rev 1, Tabela 1.

## Clock: usar o HSI16 interno e deixar a posição do cristal reservada, sem montá-lo

**Este encapsulamento não aceita cristal passivo.** DS12992 Rev 3, Tabela 12 (p. 36): o pino 2 do TSSOP20 (`PC14-OSC32_IN`) tem a função alternativa `OSC_IN`, mas o pino 3 (`PC15-OSC32_OUT`) oferece somente `OSC32_OUT`, **não `OSC_OUT`**. `PF0`/`PF1``§ também não são expostos neste encapsulamento. Um cristal passivo precisa dos dois pinos de oscilador.

| Opção | Viabilidade |
|---|---|
| Cristal passivo de alta frequência | ❌ Falta `OSC_OUT` |
| Cristal ativo em HSE bypass (clock externo no pino 2; pino 3 pode ser `OSC_EN`) | ✅ |
| Cristal LSE passivo de 32,768 kHz | ✅, mas não alimenta o PLL; serve apenas para calibrar o HSI16 |

Precisão do HSI16 (Tabela 41, p. 64): −0,75%/+0,5% de fábrica, desvio térmico de ±1% entre 0–85 °C e desvio com tensão de ±0,1%. Pior caso aproximado: **−1,85% / +1,55%**. A tolerância típica da UART a 1 Mbps é ±3%; funciona, mas sem muita margem.

**Implementação:** levar os pinos 2/3 aos pads e reservar a posição para cristal ativo 3225 e desacoplamento. Inicialmente não seria montado; desde 2026-09-08, X1/R3/C9 são montados por padrão.
O firmware começa com HSI16 e muda para HSE bypass somente se testes a 1 Mbps apresentarem erros.
A habilitação `Tri-state` de X1 no esquemático fica **ligada permanentemente a 3,3 V**. A opção de usar o pino 3 (PC15) como `OSC_EN` não foi desenhada, e PC15 permanece livre. Para controlar o cristal pelo MCU na primeira placa, instalar um fio PC15 → X1.1; consulte “Registro das revisões · 2026-09-16” no README.

## Instruções sobre a polaridade de habilitação

`1OE#` habilita o buffer de transmissão em nível baixo; `2OE` em nível alto mantém aberto o buffer de recepção.

- PA1 é o pino de DE por hardware da USART2; configurar `CR3.DEP = 1` (DE ativo em nível baixo) deixa a troca entre transmissão e recepção a cargo do hardware.
- Com a recepção sempre ativa, os bytes enviados retornam pelo RX como eco; o firmware só precisa descartá-los conforme o tamanho transmitido.
- Uma alternativa é ligar `2OE` também ao DE, desligando o buffer de recepção durante a transmissão. Porém, o pino RX do MCU ficaria flutuando e poderia gerar um falso bit de início ao reativar. Não recomendado.
- **Ajuste de 2026-09-07:** `2OE` deixou de ficar ligado diretamente a +3V3; agora tem pull-up R7 de 10 kΩ e uma ligação a `U1.1 (PB7/PB8)`. O padrão continua com o buffer sempre ativo (comportamento inalterado), mas o firmware pode desativar a recepção colocando PB7 em nível baixo e habilitando o pull-up interno do RX para evitar que flutue. Mais flexível que ligar ao DE: o firmware escolhe se e quando desativar.

## Especificações reais do HD-1910-C001 (página oficial Feetech durante a pré-venda)

A Feetech fez um servo especificamente para o pato pequeno. O título da página era “**Servo de código aberto para o pato pequeno — servo serial de barramento, desenvolvido especialmente para o brinquedo de IA**”.
O corpo do servo identifica a interface como **“conector de três pinos · barramento serial TTL”**.

| Item | Valor |
|---|---|
| Faixa de tensão | **5 V – 8,4 V** |
| Torque de travamento | **10 kg·cm = 0,98 N·m** |
| Carga nominal | **3,0 kg·cm = 0,294 N·m** |
| Velocidade sem carga | 0,09 s/60° (110 RPM) |
| **Corrente em repouso** | **21 mA** |
| **Corrente sem carga** | **140 mA** |
| **Corrente nominal** | **500 mA** |
| **Corrente de travamento** | **1,8 A** |
| Dimensões externas | 34 × 20 × 23 mm |
| Massa | 22,5 ± 2 g |
| Carcaça | PA + fibra |

As dimensões são da mesma categoria do XL330 (20×34×26 mm), com mecânica quase intercambiável; o torque é quase duas vezes o do XL330-M288 (0,52 N·m).

> ⚠️ Não aplique a este servo os parâmetros elétricos da especificação `HL-2915-C002` — é um modelo de 12 V (9–14 V).
> Só podem ser compartilhados os dados gerais de conector e protocolo.

### ⚠️ Risco de sobrecorrente no caminho direto J1↔J2

Os três fios de J1/J2 estão ligados um a um. **Se a placa ficar no meio da cadeia, toda a corrente dos servos a jusante passa por seus conectores e trilhas de cobre:**

| Condição | Por servo | ×15 |
|---|---:|---:|
| Repouso | 21 mA | 0,3 A |
| Movimento sem carga | 140 mA | 2,1 A |
| **Carga nominal** | **500 mA** | **7,5 A** |
| Travamento | 1,8 A | 27 A |

A corrente nominal do **JST EH é somente 3 A**.

> O F1 (PPTC de 200 mA) **não é afetado**: está somente em série no ramal de alimentação desta placa (`VDD_BUS → F1 → VDD_F → U4`), não no caminho direto J1→J2.

**Escolha entre duas opções:**

1. **Colocar a placa na extremidade da cadeia** (nó folha), usar somente J1 e deixar J2 vazio ou conectar apenas um servo — passam cerca de 12 mA pela placa. **Recomendado**.
2. Se for obrigatório colocá-la no meio da cadeia, usar **cobre largo** (≥ 2 mm ou plano de cobre) para `VDD_BUS` e `GND` entre J1 e J2 e confirmar que a corrente dos servos a jusante não passe de 3 A.

## Pinagem Feetech (confirmada pela especificação oficial)

**Fonte:** especificação Feetech “HL-2915-C002 串型规格书”, A/0, 2026-02-27, p. 4, itens 6–7.

`
6-7  Conectores e cabos
     Tipo             AMP-3
     Material         PP
     Comprimento      15 cm / 25 cm
     Definição dos pinos: 1 GND
                          2 Vcc
                          3 Signal/TTL
`

**`1=GND / 2=Vcc / 3=Signal`, exatamente igual ao Dynamixel → a ligação atual de J1/J2 está correta.**

Evidência relacionada: o componente do conector no conjunto `HD-1910-C001.stp` chama-se **`AMP-3P`**, e o conjunto contém `HL-2915-C002-20260409_ASM` — os dois modelos compartilham a plataforma, portanto a definição da interface é comum.

### Outros dados úteis da mesma especificação

| Item | Valor | Significado |
|---|---|---|
| 7-2 Tipo de protocolo | Half Duplex Asynchronous, **8 bits / 1 stop / sem paridade** | Igual ao projeto desta placa |
| 7-4 Baud rate | 38.400 a 1 Mbps; **padrão de fábrica: 1 Mbps** | Mesma velocidade Dynamixel |
| 7-3 Faixa de IDs | 0–253; **ID padrão de fábrica: 1** | Reprogramar individualmente os 15 servos; ID 200 da placa não conflita |
| 12 **Nível lógico alto** | **2–5 V** | Consulte abaixo |
| 12 Nível lógico baixo | 0–0,45 V | |
| 6-6 Sensor angular | Encoder magnético de 12 bits | Encoder magnético ⇒ **ordem little-endian** |

**Confira os níveis de sinal nos dois sentidos:**

1. Esta placa aciona o barramento — o `SN74LVC2G241` alimentado a 3,3 V fornece ~3,3 V, dentro da faixa de nível alto de 2–5 V exigida pelo servo ✅
2. Os servos acionam o barramento — podem fornecer **5 V**; alimentado a 3,3 V, o 74LVC **tolera 5,5 V na entrada** ✅ (essa é a razão de escolher LVC em vez de LV/HC).

> ⚠️ A especificação usada aqui é do **HL-2915-C002 (12 V, 9–14 V)**, não do HD-1910 (5–8,4 V).
> **Não misture parâmetros elétricos** — faixas de alimentação, corrente de travamento e limites de proteção contra sobretensão são diferentes.
> Só são comuns os dados de **conector e protocolo**.

### Contexto: as camadas físicas das séries Feetech são diferentes

O texto dos manuais oficiais de tabelas de memória das séries (em <http://doc.feetech.cn>, interface `getQr/{q}`):

| Série | Nível físico | Baud rate padrão |
|---|---|---|
| **STS** (encoder magnético) | **TTL, barramento único** | **1M** |
| SCS (potenciômetro) | TTL, barramento único | 1M / 500k |
| SMS (encoder magnético) | **RS485** | 115200 |
| HLS (encoder magnético) | Não indicado | 1M |
| SHC | CANopen | 125k |

A afirmação “Feetech = TTL de fio único” **vale somente para STS/SCS/HL**; SMS usa RS485. Consulte o manual antes de trocar de série.

## Detecção automática de protocolo (sem jumper ou chave DIP)

Os cabeçalhos dos pacotes das duas famílias são naturalmente distinguíveis; o critério são os **bytes 3 e 4**:

| | Cabeçalho | Campos seguintes | Checksum |
|---|---|---|---|
| Dynamixel V2 | `FF FF` | **`FD 00`** | CRC-16 (poly 0x8005) |
| Feetech STS/SCS | `FF FF` | `ID` + `LENGTH` | `~(ID+LENGTH+INST+parâmetros)` |

A distinção é inequívoca: o byte 3 Feetech é o ID (que pode ser `0xFD`), mas o **byte 4, LENGTH, nunca é 0** (mínimo de 2: instrução + checksum). Portanto `FF FF FD 00` só pode ser V2.

`
Estado: desconhecido / V1 bloqueado / V2 bloqueado

Quando desconhecido e chega um pacote iniciado por FF FF:
    se byte[2]==0xFD e byte[3]==0x00:
        decodificar como V2 e calcular CRC-16 → se válido, contar uma confirmação V2
    caso contrário:
        decodificar como V1 e calcular ~sum → se válido, contar uma confirmação V1
    após 3 confirmações consecutivas iguais → bloquear o protocolo

Depois de bloqueado: analisar e responder somente usando o protocolo selecionado
Fallback: 100 pacotes consecutivos sem conseguir analisar → desbloquear e detectar novamente
`

As definições seguintes são baseadas no texto oficial Feetech **“Servo SCS Communication Protocol”**:

- Quadro: **1 bit de início + 8 bits de dados + sem paridade + 1 bit de parada**, total de 10 bits.
- Cabeçalho: dois bytes `0xFF` consecutivos.
- Faixa de ID: **0–253** (`0x00`–`0xFD`); **ID de broadcast = 254 (`0xFE`)**.
- Tamanho dos dados: **`Length = N` parâmetros + 2**; mínimo 2, nunca 0 — base da distinção inequívoca de protocolo.
- Checksum = `~(ID + Length + Instruction + Param1 + … + ParamN)`, usando somente o byte menos significativo quando a soma excede 255.
- Leitura sincronizada `0x82`, escrita sincronizada `0x83`, PING `0x01`, leitura `0x02`, escrita `0x03`.
- ⚠️ A ordem dos bytes de parâmetros com mais de um byte depende do tipo de servo: **servos com potenciômetro usam big-endian** (byte alto primeiro); **servos com encoder magnético usam little-endian** (byte baixo primeiro).

Três pontos importantes:

1. **É necessário bloquear a escolha; não decida pacote a pacote** — ruído pode fazer um pacote parecer `FD 00` e causar alternância indevida.
2. **Responder usando o mesmo protocolo** — o ramo de seleção precisa se aplicar tanto à análise quanto à montagem de pacotes.
3. **Permitir desbloqueio de segurança** — trocar a marca do servo não exige regravar o firmware.

Ambos os lados usam ID de escravo **200**, que não conflita com os 15 servos (normalmente IDs 1–15).

> O `Return Delay Time` dos STS Feetech tem padrão 0 e o manual indica “Not functional on STS”; esse registrador não tem efeito e o atraso das respostas é determinado integralmente pelo firmware.

## Encapsulamentos: todos os passivos em 0603

Usar **0603** para todos os resistores/capacitores e **SOD-123** para D2, sem 0402/SOD-323.

A razão não é soldagem manual — a LSM6DSV16X LGA-14 já exige ar quente. **A razão real é facilitar retrabalho durante a depuração**: mudar o resistor em série de 150 Ω para 33 Ω, remover um pull-up ou acrescentar um capacitor de desacoplamento. Em 0603, cada alteração leva segundos com um ferro. Uma placa de primeira versão ainda sem validação física certamente precisará de modificações.

Custo: 11 componentes ocupam cerca de 16 mm² a mais, menos de 2% da área da placa. Os valores 0603 usados estão todos no catálogo **básico** da JLC (10 kΩ `C25804` · 150 Ω `C22808` · 33 Ω `C23140` · 100 nF `C14663`), com menor custo de montagem que a biblioteca estendida 0402.

> C6 (10 µF/25 V) permanece 0805; C5 (4,7 µF) e C7 (10 µF) já eram 0603.

## Proteção da linha de dados (seguindo a HAT)

`
U3.6 (1Y) ──┬─ DXL_DATA ─┬── R5 10k → 3,3 V
U3.5 (2A) ──┘            │
                         └── R6 150Ω ──┬── DXL_BUS ── J1.3 / J2.3
                                       │
                                    D2 5V1
                                       ⏚
`

| Componente | Função |
|---|---|
| **R6 150 Ω** | Resistor em série na origem: limita a corrente de curto e suaviza as bordas para reduzir EMI. A 1 Mbps, o atraso representa cerca de 3% do tempo de bit |
| **D2 5V1** | Limitador de tensão; cátodo em `DXL_BUS`, ânodo no terra |

**O pull-up fica no lado do buffer** (R5 antes de R6): mesmo sem barramento conectado, a entrada CMOS `U3.5 (2A)` mantém um nível definido e não flutua. Mesma posição de R32 na HAT.

> A HAT oficial usa `R33 150R + TH1 100R` em série (250 Ω no total), além do limitador `D4 5V1` (`dynamixel.kicad_sch`). **D2 e D4 da HAT são o mesmo componente em encapsulamentos diferentes** — a HAT usa SOD-323 (`C151348`) e esta placa, SOD-123 (`C151588`), mais fácil de retrabalhar.
> Esta placa usa somente 150 Ω, pois a HAT já tem 250 Ω; resistência demais em série no barramento deixa as bordas lentas.

## Três proteções contra sobretensão

1. **F1** PPTC: corrente de manutenção de 200 mA / 24 V — limita corrente e protege contra curtos.
2. **D1** TVS SMF12A — limita picos de força contraeletromotriz dos servos.
3. **U4** HT7533-1, tensão máxima de 30 V — o próprio LDO suporta a condição caso as duas proteções anteriores falhem.

## Pontos importantes do layout

- Placa de duas camadas, 45 × 22 mm; componentes de montagem superficial na face superior.
- Três conectores de furo (J1/J2/J3) alinhados na mesma borda.
- Dois furos de montagem M2, espaçados 34 mm (compatíveis com o `banana_pcb_locker` original).
- C1/C2 próximos aos pinos Vdd / Vdd_IO de U2, com trilhas curtas.
- C4 (100 nF) e C5 (4,7 µF) próximos ao pino 4 de U1 — a Fig. 13 de ST DS12992 recomenda colocá-los o mais perto possível do pino ou no verso, diretamente opostos.
- Trilhas `DXL_DATA` largas e afastadas do SPI.
