# Esquemático e PCB da `imu_to_dxl` · revisão solicitada

> ⚠️ **Esta é uma réplica feita por terceiros, não um projeto oficial.**
> A Pollen nunca publicou o esquemático, os Gerbers nem o contorno desta placa (não há registros públicos; consulte a [análise reversa de hardware](../../docs/硬件方案逆向.md)). Este diretório contém resultados de inferência a partir do modelo MJCF, do código-fonte oficial em tempo de execução e do projeto aberto da HAT, além da seleção de componentes feita por nós. **A placa ainda não foi fabricada nem validada fisicamente.**
> Se encontrar problemas, abra uma [issue](https://github.com/fanhao375/microduck-replica/issues).

![Esquemático da imu_to_dxl](../../assets/hw/imu_to_dxl-原理图.png)

| Arquivo | Descrição |
|---|---|
| [`imu_to_dxl-原理图.pdf`](imu_to_dxl-原理图.pdf) | PDF vetorial; amplie para ver os detalhes |
| [**`imu_to_dxl-交互式BOM.html`**](imu_to_dxl-交互式BOM.html) | **Para soldagem**: BOM interativa exportada pelo JLC EDA. Baixe e abra diretamente no navegador (funciona offline). Clique no código do componente para destacar a posição correspondente na placa e marque cada tipo após soldar. Ao clicar diretamente na página do GitHub, será exibido o código-fonte |
| [**`firmware/`**](firmware/) | Firmware STM32G031 + LSM6DSV16X, projeto Keil, testes no computador e arquivo HEX pré-compilado; desde a versão 0.2.0 usa o protocolo Feetech SCS/STS (ID 200), ainda sem teste no barramento real |
| [**`firmware-1.0.0/`**](firmware-1.0.0/) | Outra versão do firmware Feetech, 1.0.0, criada a partir da versão 0.1.0 (Dynamixel). **Testada em barramento compartilhado com servos Feetech reais** (endereçamento e leitura/gravação); inclui ferramentas de computador para varredura, monitoramento do barramento, gráficos da IMU e um guia em chinês. Assim como a versão 0.2.0, usa blocos de 15 bytes e o modelo 0x4D44; desde a imagem de réplica 20261021b, ambas são reconhecidas pelo programa principal |
| [**`总线协议.md`**](总线协议.md) | **Para quem desenvolve o firmware**: definição byte a byte do bloco de 15 bytes, requisitos de temporização, regras de ordenação, critérios do controlador principal, vetores de teste e método de aceitação |
| [`imu_to_dxl-接线表.md`](imu_to_dxl-接线表.md) | Lista cada pino por rede para facilitar a conferência |
| [`imu_to_dxl.eprj2`](imu_to_dxl.eprj2) | Projeto JLC EDA Professional, pronto para abrir e editar |
| [`../../BOM.md`](../../BOM.md) | BOM completa, com códigos JLC e justificativa da seleção de cada componente |

**Acesso ao firmware e à visualização da orientação:** [`firmware/README.md`](firmware/README.md) registra a inicialização da placa, a amostragem da IMU e o escopo da validação.

**Como escolher entre as duas versões do firmware:** para conectar ao pato e usar junto com o programa principal do fork, ambas servem. A partir da imagem de réplica 20261021b, o programa principal reconhece esta placa e, durante a leitura de todo o corpo, precisa colocá-la **depois dos servos**: na versão 1.0.0, quando foi colocada em primeiro lugar, respondeu somente 3 de 30 tentativas; os servos seguintes falavam imediatamente por causa dos temporizadores e corrompiam os bytes de checksum dela. No meio ou no fim, respondeu 30/30 vezes. Para usar o `servo-web` com SWD / J-Link e visualizar a orientação, só serve o HEX 0.2.0 em `firmware/`: o visualizador valida o hash e os endereços de memória; com a versão 1.0.0, recusa-se a ler. Nenhuma das versões foi testada por longos períodos no robô completo.

O [`tools/servo-web`](../../tools/servo-web) pode sobrepor a orientação da placa à visão 3D do pato na bancada de servos: os ângulos das articulações vêm dos servos e o quaternion do tronco vem da IMU.
Há três modos de leitura: `--imu-bus` (barramento dos servos, no mesmo `sync_read` do controlador; lê os 15 bytes do ID 200 no endereço 56), `--imu-swd` (ST-Link / DAPLink) e `--imu-jlink` (J-Link).
A verificação `imu200.py check` no barramento real ainda não foi feita.

---

## Função da placa

Os 15 servos do Microduck oficial ficam em um barramento Dynamixel half-duplex. Esta placa é **o 16.º dispositivo do mesmo barramento**, apresentando-se como um servo Dynamixel escravo (ID 200). O controlador principal solicita os dados de orientação lendo seus registradores.

A IMU da placa é a **LSM6DSV16X**, que contém um bloco de fusão de sensores **SFLP por hardware** e fornece diretamente um quaternion de orientação. Assim, o cálculo da orientação não consome processamento do controlador nem largura de banda adicional do barramento.

`
Controlador principal (Raspberry Pi / Taisenpai)
      │ barramento half-duplex de fio único, 1 Mbps
      ├── 15 servos
      └── imu_to_dxl (esta placa, ID 200)
             ├── LSM6DSV16X   SPI de quatro fios + duas interrupções
             ├── STM32G031F8P6 recebe/monta pacotes e lê a IMU
             └── SN74LVC2G241 buffer half-duplex do transceptor
`

## Componentes escolhidos e justificativas

| Ref. | Componente | Motivo da escolha |
|---|---|---|
| **U1** | STM32G031F8P6 | ① A USART tem **DE por hardware** (Driver Enable para RS485). A 1 Mbps, cada bit dura apenas 1 µs; a oscilação de um pino de direção controlado por software tem essa mesma ordem de grandeza. Em comparação, o manual do **STM32F401 não contém “Driver Enable”**; seria necessário alternar por software.<br>② É do mesmo fabricante da IMU, e já existem o driver ST `lsm6dsv16x-pid` e exemplos de SFLP |
| **U2** | LSM6DSV16XTR | Fusão SFLP interna, fornece o quaternion diretamente |
| **U3** | SN74LVC2G241DCUR | Dois buffers para half-duplex de fio único. Canal 1 recebe pela esquerda e transmite pela direita; canal 2 recebe pela direita e transmite pela esquerda, correspondendo ao traçado. Com alimentação de 3,3 V, **as entradas toleram 5,5 V**, suportando o sinal de 5 V dos servos |
| **U4** | HT7533-1 | **Suporta 30 V** — permanece operacional se as duas proteções anteriores falharem |
| **F1** | PPTC MF-NSMF020X-2 | **24 V / 200 mA de corrente de manutenção**. Em caso de falha da placa, interrompe primeiro a própria alimentação sem derrubar todo o barramento dos servos |
| **D1** | TVS SMF12A | Tensão de corte de 12 V, acima dos 8,4 V de bateria carregada; limita a 19,9 V, abaixo dos 25 V suportados por C6 |
| **C6** | 10 µF / **25 V** | Ligado ao barramento de 8,4 V. Capacitores MLCC perdem capacitância com polarização CC; não há margem suficiente usando componentes de 6,3 V / 10 V |
| **C5** | 4,7 µF | Em conjunto com C4 de 100 nF, cumpre a combinação exigida pela ST — **DS12992 Rev 3, Figura 13** indica explicitamente `1 × 100 nF + 1 × 4,7 μF` em `VDD/VDDA` |

## Decisões que podem ser discutidas

### 1. `2OE` fica em nível alto fixo; durante a transmissão haverá eco

`U3.1 (1OE#)` controla o buffer de transmissão por DE; `U3.7 (2OE)` fica **ligado diretamente a 3,3 V, mantendo o buffer de recepção sempre ativo**.

- Custo: durante a transmissão, o MCU recebe de volta no RX os próprios bytes e o firmware os descarta conforme o tamanho enviado.
- Benefício: PA3 fica sempre sendo acionado e **não flutua**.

A alternativa seria ligar `2OE` também ao DE, desativando a recepção enquanto transmite. Nesse caso, o RX flutuaria durante a transmissão e poderia gerar um falso bit de início quando fosse reativado. Escolhi a primeira opção; **comentários e objeções são bem-vindos**.

### 2. Sem cristal; apenas os pads foram reservados

O encapsulamento TSSOP-20 **não expõe `OSC_OUT`** (DS12992 Rev 3, Tabela 12: o pino 2 `PC14` tem a função alternativa `OSC_IN`; o pino 3 `PC15` oferece apenas `OSC32_OUT`). Portanto, **não é possível conectar um cristal passivo**.

Precisão do HSI16 (Tabela 41): de fábrica −0,75%/+0,5%, variação térmica de ±1% entre 0–85 °C; pior caso aproximado de **−1,85%/+1,55%**. A tolerância típica para UART assíncrona a 1 Mbps é ±3%, suficiente, mas sem muita margem.

A placa tem **X1 (cristal ativo de 16 MHz em bypass HSE) + C9 + R3**; inicialmente, X1 não seria montado, mas desde 2026-09-08 passou a ser **montado por padrão** (o firmware ainda inicia com HSI16; só mudará para HSE bypass se testes a 1 Mbps apresentarem erros). O pino de habilitação do X1 fica ligado permanentemente a 3,3 V; PC15 não está conectado a ele, então o MCU não pode desligar o cristal. Consulte “Registro da revisão · 2026-09-16”.
Além disso, o firmware pode medir com captura de entrada do timer o período dos bits recebidos do controlador e ajustar o `HSITRIM`; cada passo representa 0,2–0,4%, e o erro pode cair para menos de 0,3%, sem custo.

### 3. Dois conectores J1/J2 foram mantidos; a largura de cobre resolve a corrente

As três linhas de J1 e J2 são conectadas em paralelo. **Se a placa ficar no meio da cadeia, toda a corrente dos servos a jusante passa por seus conectores e trilhas de cobre.**

Especificação oficial do Feetech HD-1910-C001: corrente nominal **500 mA** / corrente de travamento **1,8 A**.

Essa restrição **não é exclusiva desta placa**: os servos já são ligados em cadeia, e os conectores entre eles transportam a mesma corrente.
A HAT tem **quatro portas de servo**; os 15 servos são distribuídos em quatro ramais, no máximo quatro por ramal, ou cerca de **2 A por ramal**, dentro do limite de 3 A. O projeto oficial aceita essa condição; usar conectores equivalentes nesta placa não é pior.

**Por isso, os dois conectores foram mantidos**: para instalar a placa na extremidade, omite-se J2; para colocá-la em série, J2 é instalado. A flexibilidade custa praticamente nada.
Na PCB, as redes `VDD_BUS` e `GND` devem usar **trilhas largas** entre J1 e J2 (≥ 2 mm ou plano de cobre).

> Uma revisão recomendou manter apenas um conector 3P. Isso funciona quando a placa é definitivamente o nó final. Porém, **se ela for o primeiro nó da cadeia** (a saída da HAT entra primeiro na placa e depois segue para os servos), são necessários dois conectores.
> A topologia oficial não pode ser confirmada; manter ambos é mais seguro.

### 4. O firmware detecta o protocolo automaticamente; não há jumper nem chave DIP

As camadas físicas Feetech e Dynamixel são idênticas (half-duplex de fio único / 1 Mbps / três fios / GND-VCC-DATA); o que muda é o formato do pacote:

| | Cabeçalho | Campos seguintes | Checksum |
|---|---|---|---|
| Dynamixel V2 | `FF FF` | **`FD 00`** | CRC-16 |
| Feetech SCS | `FF FF` | `ID` + `LENGTH` | `~(ID+LEN+INST+parâmetros)` |

A documentação oficial Feetech especifica `Length = N de parâmetros + 2`, portanto o mínimo é 2 e **nunca é 0**; IDs válidos vão de 0 a 253. Logo, `FF FF FD 00` só pode ser Dynamixel V2 e **a distinção é inequívoca**.

Ao receber o primeiro pacote com checksum válido, o firmware fixa o protocolo e continua a comunicação usando esse formato; **não o desbloqueia automaticamente durante a execução**. Uma proposta inicial de reavaliar após 100 pacotes consecutivos com erro foi descartada em uma revisão de 2026-09-17: o ruído no barramento poderia deixar a placa sem resposta por 2 s e fazer o controlador manter a pose após três ciclos sem dados. Consulte §3.5 de [`software/飞特适配架构.md`](../../software/飞特适配架构.md).
Isso é mais confiável do que uma chave DIP, cujos contatos podem falhar com a vibração de um robô em movimento.

### 5. J3 tem seis pinos para expor também o printf serial

Segundo o PDF do esquemático de 2026-09-08, a ordem é:
`1=GND 2=SWDCLK 3=SWDIO 4=UART_RX 5=UART_TX 6=+3V3`.
SWD usa os pinos **1, 2, 3 e 6**; o pino 6 fornece a referência de tensão do depurador. **Não conecte um cabo antigo de quatro pinos nos pinos 1–4**: o pino 4 é a entrada serial, não 3,3 V. Antes de ligar, confira a marcação do pino 1 na placa e a definição dos pinos do depurador.

A UART sai dos pinos 16/17 de U1 (`PA11[PA9]` / `PA12[PA10]`) e é remapeada para `USART1_TX/RX` por `SYSCFG_CFGR1`.

**Sem USB direto**: o G031 não tem periférico USB (a seção “Development support” do manual cita somente “serial wire debug (SWD)”). Adicionar USB exigiria mais um CH340/CP2102, sem valer a pena numa placa de 45 × 22 mm.
A depuração é feita por SWD + RTT (`probe-rs` oferece RTT com CMSIS-DAP sem parar a CPU).

> Cortex-M0+ **não tem SWO/ITM**; não conte com printf por SWO.

---

## Contorno da placa e furos de montagem

| Item | Valor |
|---|---|
| Contorno | **45 × 22 mm**, PCB de duas camadas |
| Cantos | Arredondamento **R2** |
| Furos | **2 furos não metalizados M2, Ø2,2 mm**, em diagonal |
| Posições (origem no canto inferior esquerdo da placa) | MH1 (2,667; 2,413), MH2 (42,672; 19,685) mm |
| Distância entre centros | X: 40,00 mm / Y: 17,27 mm / diagonal: 43,57 mm |
| Distância dos furos à borda | MH1: **1,31 mm** / MH2: **1,22 mm** (mínimo exigido pela JLC: 0,4 mm) |

O ponto médio entre os furos é (22,67; 11,05), enquanto o centro da placa é (22,50; 11,00); a diferença é 0,17 mm. **Invertida em 180°, a montagem ainda deve alinhar quase perfeitamente** (desvio de 0,34 mm).

> ⚠️ **As posições dos furos foram alteradas em 2026-09-08.** O projeto original usava MH1 (5,5; 3,5) / MH2 (39,5; 18,5), distância de 34 mm no eixo X, para alinhar intencionalmente com a distância entre as duas abas da peça impressa `banana_pcb_locker`.
> Ao adicionar J4/J5, o anel de folga de MH2 ocupava a única faixa livre para componentes montados por furo no lado direito. Por isso, os dois furos foram deslocados para perto dos cantos, aumentando a distância X para 40 mm.
> **A contrapartida é que a placa deixa de ser compatível com o fecho original; a mecânica também deve receber uma barra de pressão modificada.**
> De qualquer modo, a afirmação no documento de análise reversa de que “o fecho pressiona a `imu_to_dxl`” era somente uma inferência (consulte a [análise reversa de hardware](../../docs/硬件方案逆向.md)); a única restrição confirmada é que a IMU fique rigidamente fixada ao `trunk_base`.

Arquivo do contorno: `imu_to_dxl-板框-45x22-R2.dxf` (unidade em mm, oito segmentos fechados: quatro retas e quatro arcos de 90°).

> **Por que o DXF é fornecido separadamente:** nesta versão, a interface de criação de primitivas do JLC EDA Professional só aceita camadas de cobre. Criar linhas/arcos na camada de contorno (layer 11) retorna “parâmetro incorreto”; alterar a camada e a origem do documento também não resolveu. Por isso, o contorno deve ser importado por DXF (`Arquivo → Importar → DXF`, camada de destino **contorno da placa**, unidade mm, origem alinhada a 0,0).
> Os dois furos M2 não estão no DXF: já foram criados na PCB como pads NPTH reais.

## PCB: layout e roteamento

![Montagem da camada superior da PCB imu_to_dxl](../../assets/hw/imu_to_dxl-PCB.png)

*Roteamento renderizado a partir das medições do projeto (camada superior vermelha / inferior azul / pads amarelos / vias GND verdes / vias de sinal roxas; o fundo azul representa o plano GND inferior e os contornos roxos indicam `J4`/`J5`).*
*Estado em 2026-09-08: 29 componentes, 227 segmentos de trilha, 31 vias e 172 alívios em lágrima; inclui `R7`, `J4` e `J5`; `X1`/`R3`/`C9` passaram a ser montados.*
*Os arquivos `.eprj2`, PDF da PCB, PDF do esquemático, STEP e as duas imagens em `assets/` estão todos atualizados para a versão final de 2026-09-08.*

PCB de **45 × 22 mm, duas camadas e cobre de 1 oz**, cantos R2 arredondados e dois furos M2 não metalizados em diagonal.
Todos os componentes de montagem superficial ficam na frente; os três conectores de furo estão em duas bordas: `J1`/`J2` (barramento dos servos) embaixo e `J3` (SWD + serial) em cima.

### Zonas

| Zona | Conteúdo | Motivo |
|---|---|---|
| Borda inferior | Conectores do barramento `J1`/`J2` (JST EH 2,5 mm) | O chicote vem pelo tronco e sai pela borda mais próxima |
| Inferior direita | **Saída do barramento Feetech `J5`** (2,0 mm) | No mesmo lado de `J1`/`J2`; o cobre conecta diretamente `VDD_BUS` aos quatro conectores |
| Borda direita | **Entrada do barramento Feetech `J4`** (2,0 mm) | Única faixa livre para um conector de furo; o furo MH2 foi deslocado para abrir espaço |
| Lado direito | `F1` → `D1` → `C6`/`C8` → `U4` → `C7` | A alimentação segue um caminho contínuo, separada da região digital |
| Centro | Buffer `U3` + limitador `D2` + resistor em série `R6` | Entre MCU e conectores do barramento, reduz o caminho de transmissão e recepção |
| Centro superior | MCU `U1`, IMU `U2` e respectivos capacitores de desacoplamento | |
| Lado esquerdo | Posição do clock `X1`/`R3`/`C9` | Agora montados por padrão, no canto para não ocupar áreas mais úteis |
| Borda superior | Pinos de depuração `J3` | Orientados para fora para facilitar a conexão |

### Roteamento

| Item | Valor |
|---|---|
| Componentes | **29** (inclui `R7` adicionado em 09-07 e `J4`/`J5` adicionados em 09-08) |
| Trilhas | **227 segmentos** (197 na camada superior / 30 na inferior) |
| Largura | Sinais principalmente 0,25 mm; **passagem direta do barramento 0,76 mm** |
| Vias | **31, Ø0,6 mm / furo de 0,3 mm** |
| Alívios em lágrima | 172 |
| Plano de cobre | **GND contínuo em toda a camada inferior**; sem plano na superior |

Há 30 segmentos de trilha na camada inferior; o **plano de terra permanece quase contínuo**, servindo como caminho de retorno para SPI e para o barramento half-duplex de 1 Mbps.
Os pads GND da camada superior têm vias de terra próximas.

### Resultados da revisão · 2026-09-08

Além do DRC integrado do JLC, um script rasterizou novamente a placa usando o **formato real dos pads** (circular, oblongo ou retangular) e fez uma verificação independente:

| Verificação | Resultado |
|---|---|
| DRC do JLC | **0 violações** |
| **Pinagem dos conectores** | **Todos os quatro corretos**: `J1`/`J2` = `GND`/`VDD_BUS`/`DXL_BUS`; `J4`/`J5` = `DXL_BUS`/`VDD_BUS`/`GND` (ordem inversa; ver a seção de pinagem abaixo) |
| Conectividade das redes | **As 23 redes conectadas** (componentes rasterizados e pads/vias que atravessam camadas, incluindo o plano inferior) |
| Menor distância entre redes diferentes | **0,152 mm = 5,98 mil** (geometria exata, não rasterizada). O mínimo da JLC para placa dupla face é 0,127 mm; margem de 20% |
| Cobre até a borda | Mínimo **0,37 mm** |
| Distância entre furos (entre as paredes) | Mínimo **0,751 mm**, requisito ≥ 0,4 mm |
| Furo até a borda | MH1 **1,31 mm** / MH2 **1,22 mm** |
| Folga M2 | Na região de 2,5 mm de MH1 há apenas uma via **GND** (a 1,81 mm): mesmo que o parafuso encoste, será em GND, sem risco; MH2 fica a 4,59 mm da via mais próxima |
| Especificação das vias | Ø0,6 mm / furo 0,3 mm; atende ao mínimo da JLC para placa dupla face |
| Distância do desacoplamento | `U1.4`→`C4`: 2,27; `U2.8`→`C1`: 2,00; `U2.5`→`C2`: 2,01; `U3.8`→`C3`: 1,96; `X1.1`→`C9`: 2,39 mm (todos <2,4 mm); `U4.3`→`C7`: 2,94 mm. ⚠️ O capacitor de 100 nF `C8` na entrada do LDO `U4.2` fica a **6,64 mm** (um pouco distante); o capacitor de 10 µF `C6`, que atende transitórios, fica a 4,29 mm, e o LDO é linear, sem chaveamento |

**Verificação de corrente:** a conexão direta `VDD_BUS` entre os quatro conectores (`J1.2 → J2.2 → J5.2 → J4.2`) tem **0,76 mm de largura em todo o percurso**. Com cobre de 1 oz, a elevação de temperatura de 10 K corresponde a cerca de 2,0 A; com 30 K, a 3,2 A.
Um contato JST EH suporta 3 A, portanto **a trilha e o conector têm capacidade da mesma ordem**; alargar a trilha não aumenta o limite do conjunto.
Também existe um segmento de 4,7 mm e 0,51 mm de largura em `J1.2 → F1.1`, no ramal que alimenta **apenas esta placa**; o PPTC de 200 mA que vem antes é suficiente.

> **Problema encontrado e corrigido em 2026-09-08:** ao rotear `DXL_BUS` para `J4`/`J5`, uma via de Ø0,3 mm caiu exatamente sobre o furo de Ø1,0 mm de `J2.3` (distância entre centros de 0,001 mm). O DRC do JLC acusou `Hole to Hole (DXL_BUS): J2_3 ↔ e75` — furos feitos na usinagem não podem se sobrepor, nem mesmo na mesma rede.
> `J2.3` já é um furo metalizado e as camadas superior e inferior estavam conectadas; a via era redundante. Depois de removê-la, a conectividade permaneceu intacta e o DRC ficou sem violações.

**Ainda não validado:** a placa **não foi fabricada e não há unidade física**. As verificações acima abrangem apenas geometria e regras de projeto, não substituem testes no hardware.

### Pendências

- Antes do pedido, executar a **normalização dos componentes** (o DRC do esquemático acusou “propriedades do componente incompatíveis com o código do fornecedor”).
- Conferir a serigrafia: referências sobre os pads; marcação do pino 1 de `U1`; marcas de cátodo de `D1`/`D2`; marcações dos pinos 1 de `J1`.
- **Altura dos conectores:** `J1`/`J2`/`J3` usam JST EH / pinos verticais de 2,54 mm, com cerca de **8 mm** de altura. Se a cavidade do tronco tiver mesmo 6,65 mm, será necessário usar `S3B-EH-A` horizontal e atualizar footprint e BOM. Comparar o STEP exportado com o conjunto mecânico resolve a questão.
  **`J4`/`J5` não devem ter esse problema**: o corpo do `B3B-PH-K-S` tem cerca de **6,0 mm** e cabe na cavidade de 6,65 mm.
- **Confirmar o modelo do conector do lado da placa:** a especificação Feetech informa apenas que o cabo termina em `AMP2.0-3P`, sem identificar o modelo na placa. Este projeto usa provisoriamente `B3B-PH-K-S` (JST PH, 2,0 mm, vertical). O padrão de três furos com espaçamento de 2,0 mm é compartilhado por outras séries; **uma troca futura exige somente alterar o footprint, sem modificar pads nem refazer o roteamento**.
- **Reexportar os arquivos de produção antes de encomendar** — os componentes passaram de 27 para 29; é necessário enviar novamente os Gerbers, a BOM e as coordenadas de montagem ao JLC.

## Pontos em que gostaria de receber comentários específicos

1. **Manter `2OE` sempre habilitado** (decisão 1 acima) — o que é pior: eco durante a transmissão ou RX flutuando?
2. **Corrente de passagem por J1/J2 e largura do cobre** (decisão 3) — 2 mm são suficientes?
3. **Margem para usar HSI16 a 1 Mbps** (decisão 2) — compartilhe experiências de medições reais.
4. **As três proteções contra sobretensão são suficientes?** Barramento de 8,4 V + força contraeletromotriz dos servos.
5. **Conectores:** consulte abaixo “⚠️ A pinagem Feetech varia conforme o modelo e é invertida”. Os conectores de 2,0 mm `J4`/`J5` já estão no esquemático e na PCB (2026-09-08), mas **o modelo exato da série do conector da placa ainda não foi testado com uma peça física** — a especificação Feetech só informa `AMP2.0-3P` no cabo; falta confirmar o modelo da placa com o fabricante.

## ⚠️ A pinagem Feetech muda conforme o modelo e pode ser invertida

**Este é o ponto com maior risco de dano na placa. As especificações dos dois fabricantes estão corretas: os dois modelos realmente têm pinagens opostas.**

| | Conector | Pino 1 | Pino 2 | Pino 3 |
|---|---|---|---|---|
| **`HD-1910-C001`** (modelo usado neste repositório) | **`AMP2.0-3P`** (2,0 mm) | **Signal/TTL** | Vcc | **GND** |
| `HL-2915-C002` (outro modelo; não copie esta ligação) | `AMP-3` | **GND** | Vcc | **Signal/TTL** |
| `J1`/`J2` desta placa (JST EH 2,5 mm, igual à HAT oficial) | `B3B-EH-A` | GND | VDD_BUS | DXL_BUS |
| `J4`/`J5` desta placa (2,0 mm, para o cabo Feetech) | `B3B-PH-K-S` | **DXL_BUS** | VDD_BUS | **GND** |

A pinagem dos quatro conectores foi conferida novamente pela netlist da PCB; todas estão corretas (2026-09-08).
**Os espaçamentos são diferentes e os conectores não encaixam um no outro (2,0 contra 2,5 mm); isso impede fisicamente a ligação errada e deixa somente a possibilidade de erro no desenho da placa.**

Fonte: especificação Feetech “HD-1910-C001 串型规格书”, A/0, 2026-09-07, páginas 3/7, itens 6–7; especificação “HL-2915-C002 串型规格书”, A/0, 2026-02-27, páginas 4/8, itens 6–7. Ambas foram enviadas pelo fabricante para confirmação do cliente; **por convenção, este repositório não redistribui os PDFs**. Solicite-os à Feetech.

> Antes, o repositório registrava apenas a linha do `HL-2915`, mas recomendava o `HD-1910` como substituto — **uma armadilha**, corrigida em 2026-09-08 com a nova especificação A/0.
>
> ⚠️ **O `HL-2915-C002` é um servo de 9–14 V (nominal 12 V) e não pode ser ligado ao barramento 2S desta solução (6,6–8,2 V)** — só começa a operar a 9 V. Ele foi usado inicialmente como referência provisória para a pinagem Feetech; não o escolha para este projeto.
>
> ⚠️ **O espaçamento também é incompatível**: `AMP2.0` tem 2,0 mm e `JST EH`, 2,5 mm; **um não encaixa no outro**. Neste caso, isso serve como proteção contra ligações incorretas.

## Confirmado / ainda não validado

**Confirmado por fontes primárias**

- **`HD-1910-C001`**: pinos `1=Signal/TTL · 2=Vcc · 3=GND`, conector `AMP2.0-3P`, comprimento do cabo de 15±0,5 cm — especificação Feetech “HD-1910-C001 串型规格书”, A/0 (2026-09-07), página 3/7, itens 6–7.
- O HD-1910-C001 usa **barramento TTL de três pinos**, opera a **4–8,4 V**, torque de travamento de 9/12/15 kg·cm a 4,8/6/7,4 V, corrente nominal de **500/690/900 mA**, corrente de travamento de **1,2/1,6/2,0 A**, consumo em repouso de 20 mA, encoder magnético de 12 bits e redução 1/320 — mesma especificação, páginas 2/7 e 3/7.
- **O motor tem três proteções eletrônicas integradas** (mesma especificação, página 4/7, itens 7–11):
  **sobrecorrente** (desliga a saída após >0,5 A durante 2 s; limite e duração configuráveis; **desativada de fábrica**);
  **sobretensão/subtensão** (proteção acima de 10 V ou abaixo de 4 V; faixa configurável; **desativada de fábrica**);
  **sobretemperatura** (desliga o torque acima de 80 °C; **ativada de fábrica**).
  **Habilite as duas primeiras antes de instalar** — a detecção da falha ocorre no motor, sem necessidade de consulta contínua pelo controlador.
- Estão disponíveis seis itens de telemetria: tensão de entrada, carga, corrente de operação, velocidade, temperatura de operação e posição (mesma especificação, item 7-10). O runtime oficial realmente os utiliza: lê `present_current` junto com a posição a cada ciclo e a tensão/temperatura aproximadamente uma vez por segundo. Além disso, **a tensão é a única forma de monitorar a bateria no robô completo** (`duck-control/src/{bus,model}.rs`).
- O modo de operação padrão de fábrica é o **modo 4 “posição PD pura (Sim2Real)”**, apropriado para executar aprendizado por reforço (mesma especificação, item 7-12).
- Formato dos pacotes, `Length = N+2`, algoritmo de checksum e leitura sincronizada `0x82` — protocolo oficial Feetech “舵机SCS通信协议”.
- A ausência de pinos HSE no STM32G031, a precisão do HSI16 e os requisitos de desacoplamento `100 nF + 4,7 µF` — ST DS12992 Rev 3.
- Conectividade do esquemático — verificada rede a rede com um script; sem pinos desconectados indevidamente, curtos ou redes com nomes duplicados.

**Ainda não validado**

- **A placa completa ainda não foi fabricada**, portanto não existe uma unidade física.
- O contorno de 45 × 22 mm e o espaçamento X de 34 mm entre furos M2 foram inferidos da peça impressa `banana_pcb_locker`; não são dimensões oficiais.
- A escolha do MCU é uma recomendação de projeto deste repositório, **não um resultado de análise reversa** — não há como determinar qual MCU a placa oficial usa.

---

## Registro das revisões

### 2026-09-16 · Oito observações externas; revisão própria encontrou o pino de habilitação de X1 desconectado

A placa já estava em produção na JLC; estes itens passaram a compor a lista de inspeção da primeira placa recebida.

| Observação da revisão | Decisão | Fundamentação |
|---|---|---|
| ① X1 ligado a PC14/OSC32_IN está errado; PC14 seria apenas um pino LSE | **Não adotada; a revisão estava errada** | DS12992 Rev 3, Tabela 12 (p. 36): a função alternativa do pino 2 do TSSOP20 inclui tanto `OSC32_IN` quanto `OSC_IN`. Na p. 60, o modo HSE bypass desliga o oscilador e o pino de entrada recebe o clock externo como sinal GPIO normal. Os encapsulamentos pequenos não expõem PF0/PF1; a entrada do clock externo HSE foi atribuída ao pino 2. O cristal passivo não pode ser usado (falta `OSC_OUT`), como este diretório já registrava |
| ② Deixar `OCS_Aux` / `SDO_Aux` de U2 sem conexão é uma falha | **Não adotada**; texto da documentação uniformizado | DS13510, pp. 10/48: ambos os pinos podem ser ligados a `Vdd_IO` ou deixados em aberto; há pull interno ativo por padrão (`PIN_CTRL.OIS_PU_DIS = 0`). Deixá-los sem conexão é a configuração padrão do manual. A v2 pode reservar footprints de 0 Ω |
| ③ `2OE` sempre ativo gera eco; recomenda-se desativar a recepção durante o envio | O hardware passou a permitir ambas as opções; a escolha fica no firmware | Em 7 de setembro, `2OE` foi ligado à rede `RX_EN`, conectada a PB7; veja o registro abaixo |
| ④ Proteção do ramal lógico não equivale à proteção contra sobretensão de todo o robô | Concordamos; essa distinção já estava documentada | A TVS limita picos, o PPTC atua lentamente e o LDO protege apenas o ramal lógico; consulte a revisão comparativa com a HAT oficial |
| ⑤ A corrente que passa por J1/J2 é uma limitação do sistema | Concordamos; já foi documentado | Esta placa fica no fim da cadeia; conector EH de 3 A |
| ⑥ O conector do lado da placa em J4/J5 não foi testado fisicamente | **Concordamos; deveria ser verificado antes da primeira placa** | A Feetech só confirmou `AMP2.0-3P` no cabo. Comprar alguns conectores e testar com o cabo do servo o encaixe do `B3B-PH-K-S`, o lado da trava e a pinagem |
| ⑦ Sugestões de layout (IMU no centro, LDO afastado, pontos de teste e NRST em J3) | Adotadas na v2 | — |
| ⑧ Oito itens para validar na primeira placa | Adotados como critérios de aceitação | Barramento em alta impedância durante reset; transmissão e recepção a 1 Mbps com 00/FF/55/AA; registrar CRC/timeouts/overrun em 30.000 comunicações; desvio do zero da IMU conforme a temperatura; medir a polaridade de cada pino; conferir que PC14 não seja acionado sem X1 instalado |

**Verificação própria (2026-09-16):** conferimos cada pino pelas linhas vetoriais do PDF do esquemático. Os únicos pinos sem conexão são os quatro que realmente deveriam ficar abertos: U1.3 (PC15), U1.20 (PB3–PB6), U2.10 (OCS_Aux) e U2.11 (SDO_Aux). O pino 1 de X1, `Tri-state`, está ligado a 3,3 V para habilitação permanente (o pequeno círculo vermelho no símbolo marca o pino 1 no EasyEDA; não indica ausência de conexão). A tabela de cabos dizia que o pino 3 (PC15) poderia funcionar como `OSC_EN`, mas essa conexão **não está desenhada**: PC15 está aberto e não pode desligar X1. Para permitir controle de clock pelo MCU na primeira placa, instalar um fio PC15 → X1.1 e remover a ligação correspondente a 3,3 V, ou não instalar X1 e usar HSI16.

### 2026-09-17 · Testes da primeira placa recebida

- Chegaram cinco placas; a saída de **3,3 V está normal** (a cadeia F1 → D1 → U4 funciona).
- **O corpo de J4/J5 (`B3B-PH-K-S`) não encaixa no plugue do cabo Feetech**: o passo de 2,0 mm está correto, mas o formato do plugue não entra na carcaça PH. A observação ⑥ da revisão estava certa. Na primeira placa, lixamos a carcaça e deixamos somente os pinos; assim foi possível conectar e usar. **Na v2, trocar o conector**: testar com um cabo Feetech real — consultar o fabricante sobre o modelo do conector na placa ou experimentar alguns conectores horizontais de 3 pinos e 2,0 mm.
- Ainda não medimos o clock X1, NRST, alimentação da IMU e continuidade SWD. Os requisitos do firmware e do controlador principal estão em [§4 da adaptação Feetech](../../software/飞特适配架构.md#4-小板固件方案-a--imu_to_dxl).

### 2026-09-22 · Firmware em execução (ST-LINK/V2)

- O firmware está em [`firmware/`](firmware/) (base escrita por um colega, PR #32; desde a versão 0.2.0 usa o protocolo Feetech). A gravação e a verificação de leitura passaram pelo ST-LINK/V2 nos pinos 1/2/3/6 de J3. Medições da IMU: WHO_AM_I=0x70, aproximadamente 121 Hz, aceleração resultante de 1,007 g em repouso e contador de erros em 0.
- **Problema da memória G0 em branco:** após a primeira gravação, um reset por software não iniciava o programa e o MCU permanecia no bootloader da ST (PC=0x1FFF…). `FLASH_ACR.EMPTY` só é atualizado ao ligar. **Desligar e ligar uma vez** resolve. O botão de reset (NRST) não repete a verificação e não resolve.
- **Itens para a v2** (faltaram na depuração da primeira placa):
  - **Botão de reset + NRST em J3**: combinar com a sugestão ⑦ da revisão. Se o programa travar e não for possível conectar por SWD, manter o reset pressionado e conectar em modo under-reset para recuperar a placa; também facilita reiniciar o firmware.
  - **LED de execução**: ligar a **U1.20** (PB3–PB6, único GPIO completamente livre no momento) por um resistor limitador. Adicionar um sinal de vida ao firmware: piscar devagar em operação normal e rapidamente quando houver falha da IMU, para mostrar que a placa está funcionando sem conectar o depurador.

### 2026-09-07 · Três sugestões de layout e seleção (nenhuma adotada; justificativas registradas)

Um revisor sugeriu trocar resistores/capacitores por 0402, colocar a IMU no centro da placa e afastar o LDO da IMU. Medimos cada item; **decidimos manter o layout**, mas vale registrar os motivos — em especial porque as sugestões ② e ③ tratam do mesmo ponto.

**① Trocar passivos por 0402 — não trocar; a questão não é se podem ser soldados à mão**

O revisor acrescentou que seria melhor não soldar manualmente e pedir a montagem da JLC. A sugestão é válida, mas a escolha de 0402 não depende disso: o registro de 2026-09-06 neste diretório já começava dizendo que **a razão não era a impossibilidade de soldar 0402 à mão**. A placa já tem a LSM6DSV16X em encapsulamento LGA-14 (pads inferiores de 3×2,5 mm), então de qualquer modo será necessário usar ar quente.

A razão real é a **facilidade de retrabalho durante a depuração**: testar o resistor em série R6 de 150 Ω até 33 Ω, talvez remover o pull-up ou acrescentar capacitores de desacoplamento.
Uma placa de primeira versão sem validação certamente precisará de algumas mudanças. A montagem da JLC cobre somente a primeira montagem; qualquer retrabalho posterior ainda exigirá soldagem manual.

Quanto ao benefício, trocar 16 passivos por 0402 economizaria **12,5 mm², apenas 1,3% da área da placa**, que atualmente usa somente **36%** da área disponível. Não há falta de espaço. Resistores de 10 kΩ e capacitores de 100 nF em 0402 também fazem parte do catálogo básico da JLC; a redução de custo existe para ambos os tamanhos e não é um argumento para a troca.

**② Colocar a IMU no centro · ③ Afastar o LDO da IMU — ambas são boas ideias, mas os efeitos têm magnitudes diferentes**

Medições:

`
Centro da placa (22,5; 11,0) = ponto médio dos dois furos M2 (intencional no projeto original)
U2 (IMU): 7,47 mm do centro da placa e 3,00 mm da linha entre os parafusos
U3 (buffer): 0,41 mm do centro da placa  ← o componente lógico ocupa o ponto mais rígido
Distância entre U2 e U4 (LDO): 6,37 mm
`

**Ordem de grandeza do aquecimento:** a corrente total da placa é de aproximadamente 5–10 mA (G031 ~3 mA + LSM6DSV16X ~0,65 mA + buffer ~1 mA + pull-ups). A queda no LDO é 8,4 − 3,3 = 5,1 V, resultando em **cerca de 51 mW dissipados** no pior caso, com a bateria carregada. Para um SOT-89 sobre uma área pequena de cobre, θJA é ~100–160 °C/W, elevando a temperatura da junção em **5–7 °C**. A 6,4 mm, com o plano GND inferior entre eles, a diferença de temperatura na IMU seria de **aproximadamente 1–3 °C**. O desvio térmico do zero do giroscópio LSM6DSV16X é ~0,05°/s/°C, o que representa **um viés de ~0,1°/s**.
Durante a marcha, o giroscópio mede dezenas de graus por segundo, e os 15 servos no tronco consomem correntes da ordem de amperes — fontes de calor dezenas ou centenas de vezes maiores que 51 mW.
**A preocupação é legítima, mas não é o efeito dominante.**

**O aspecto mais útil da sugestão ②** é que o centro da placa coincide com o ponto médio dos parafusos e, portanto, com a região menos sujeita à deformação. Hoje, quem está nesse lugar é o U3, componente que não depende da posição. Trocar U2 e U3 traria três benefícios: a IMU passaria de 7,47 mm a 0,4 mm do centro e de 6,37 mm a **11,3 mm** do LDO (quase o dobro).

**Por que não mudar agora:** a PCB já passa no DRC sem violações e todas as trilhas estão conectadas. Trocar os componentes exigiria reorganizar a área central e refazer o roteamento das quatro linhas SPI, duas interrupções e sinais DE/TX/RX/DXL_DATA do buffer. Pela escala física da placa, o ganho seria “mais cautela”, não “resolver um problema conhecido”. **Decidir depois da fabricação e das medições reais** — se o viés do giroscópio variar claramente com a carga do LDO ou houver muito ruído de vibração, incluir a mudança na v2.

**Um ponto mais importante:** a posição e a orientação da IMU **dentro do robô** são fixadas pelo modelo de treinamento e são muito mais importantes que um deslocamento de 7 mm dentro da placa. A montagem no tronco determina essa orientação, já confirmada e registrada na [análise reversa de hardware](../../docs/硬件方案逆向.md): `trunk = [+raw_z, +raw_y, −raw_x]`, rotação de +90° no eixo Y. Mover a IMU na placa não altera essa transformação.

### 2026-09-07 · Reservar uma linha de controle para `2OE` (R7 + RX_EN)

Foi sugerido reservar uma ligação entre o pino EN do buffer e o MCU. Trata-se de `U3.7 (2OE)`, habilitação da saída do buffer de recepção, que antes estava ligada diretamente a +3V3 e mantinha a recepção sempre ativa. **Sugestão adotada.**

**Alterações**

| | |
|---|---|
| Desconectado | Ligação direta entre `U3.7 (2OE)` e `+3V3` |
| Adicionado | **R7 = 10 kΩ 0603** (`C25804`), mesmo componente de R1/R2/R4/R5, sem novo código de peça |
| Nova rede | **`RX_EN` = `U1.1 (PB7/PB8)` · `U3.7 (2OE)` · `R7.1`** |
| Mantido | `R7.2 → +3V3` (pull-up) |

**Por que U1.1:** os pinos livres de U1 eram 1 (PB7/PB8), 3 (PC15) e 20 (PB3/PB4/PB5/PB6). O pino 3 é PC15, compartilhado com LSE no G0 e com capacidade de acionamento limitada; o pino 20 reúne quatro GPIOs e foi reservado para maior flexibilidade. O pino 1 é GPIO comum e fica na mesma fileira inferior que `DE`/`MCU_TX`/`MCU_RX`, facilitando o roteamento.

**O comportamento padrão não muda:** durante o reset do MCU, PB7 fica em alta impedância e R7 mantém `2OE` em nível alto, deixando o buffer de recepção habilitado. O firmware não precisa mudar nada. É apenas uma **opção reservada**: para eliminar o eco durante a transmissão, configurar PB7 como saída push-pull e levá-lo a nível baixo; ao mesmo tempo, habilitar o pull-up interno do pino `MCU_RX` para que RX não flutue quando `2Y` ficar em alta impedância. Isso resolve justamente a preocupação que antes nos fez rejeitar ligar `2OE` ao DE.

**Conferência após a alteração:** componentes 26→27, redes 23→24, `RX_EN` com três pinos; `U3.7` saiu da rede `+3V3` e `R7.2` permaneceu nela. O DRC da JLC indicou **zero violações**; a distância mínima entre redes distintas aumentou de 0,153 para **0,160 mm**. Os demais itens continuaram iguais à primeira revisão de 2026-09-07.

**Correção relacionada:** a lista de “pinos sem conexão” em `imu_to_dxl-接线表.md` incluía incorretamente os pinos 2, 16 e 17 (ligados, respectivamente, a `OSC_IN`, `UART_TX` e `UART_RX`). A lista foi corrigida. Os únicos pinos realmente livres são agora 3 e 20.

### 2026-09-07 · Três dúvidas sobre o buffer U3 (duas sugestões rejeitadas; desenho ajustado em um ponto)

Um revisor consultou o manual do SN74LVC2G241 e levantou três questões sobre a ligação de U3. Conferimos uma a uma. A netlist foi lida diretamente da PCB (as redes da PCB vêm do esquemático e são equivalentes às conexões nele):

`
Pino 1 de U3  1OE# → DE          pino 5  2A  → DXL_DATA
Pino 2 de U3  1A   → MCU_TX      pino 6  1Y  → DXL_DATA
Pino 3 de U3  2Y   → MCU_RX      pino 7  2OE → 3,3 V
Pino 4 de U3  GND  → GND         pino 8  VCC → 3,3 V

DXL_DATA: 4 pinos: R5.2, R6.1, U3.5, U3.6 — não inclui U3.7
DE:       3 pinos: R4.2, U1.8, U3.1
MCU_TX:   2 pinos: U1.9, U3.2
MCU_RX:   2 pinos: U1.10, U3.3
`

**① “A é entrada e Y é saída; portanto o pino 3 deve ir a DXL_DATA e o pino 5 a MCU_RX” — a premissa está certa, mas a conclusão está invertida**

O manual está correto: o componente contém dois drivers de linha de 1 bit com habilitação independente e a direção dos dados é sempre **A → Y**.
Mas trocar os fios com base nisso seria um erro:

- `MCU_RX` é a rede que o buffer precisa acionar (vai para a entrada de recepção do MCU); deve estar na **saída Y** — agora está corretamente no pino 3 (2Y) ✅
- `DXL_DATA` é a rede que recebe os dados enviados pelos servos no barramento; deve estar na **entrada A** — agora está corretamente no pino 5 (2A) ✅

Com a troca sugerida, o canal 2 ficaria `MCU_RX (2A) → DXL_DATA (2Y)`, ou seja, enviaria para o barramento o sinal que sai da entrada RX do MCU, que não gera níveis. Além disso, `1Y` e `2Y` acionariam `DXL_DATA` ao mesmo tempo e entrariam em conflito elétrico.

A separação atual é a configuração half-duplex padrão: **canal 1 transmite** (`MCU_TX → barramento`, controlado por DE) e **canal 2 recebe** (`barramento → MCU_RX`, sempre ativo). **Sugestão rejeitada.**

**② “2OE precisa de um resistor pull-up em série, senão o pull-up é forte demais” — a preocupação elétrica não se aplica, mas o desenho será ajustado**

`2OE` é uma entrada lógica CMOS, com corrente de entrada da ordem de ±1 µA; ligá-la diretamente a VCC é a prática padrão do manual.
O resistor em série não traz benefício e pode aumentar a captação de ruído na entrada de alta impedância.

A preocupação com o pull-up só seria aplicável se esse nó fosse uma **linha de dados**, mas não é: `DXL_DATA` contém apenas R5.2, R6.1, U3.5 e U3.6, **não U3.7**. O pull-up do barramento é `R5 = 10 kΩ`, valor adequado.

**Ainda assim, a observação foi útil:** a confusão surgiu porque o símbolo de 3,3 V ligado a `2OE` aparece exatamente sobre o nó `DXL_DATA` no desenho e parece conectado a ele. A pendência é deslocar esse símbolo e contornar a trilha para eliminar a ambiguidade. É um problema de apresentação, não de conexão elétrica.

**③ “Para ficar normalmente habilitado, 1OE# deve ser ligado ao nível baixo” — a desativação padrão é intencional; sugestão rejeitada**

`1OE#` é ativo em nível baixo. `R4` o mantém em nível alto, deixando **o canal 1 (`MCU_TX → barramento`) desativado por padrão**. Isso é intencional:

- Antes de o firmware iniciar, e durante falha ou reset do MCU, esta placa **não pode acionar o barramento**. Os 15 servos compartilham a linha; se ela ficar presa, toda a comunicação é perdida.
- Se `1OE#` fosse conectado permanentemente ao nível baixo, `MCU_TX` acionaria o barramento continuamente. O nível alto em repouso manteria a linha presa e os servos nunca conseguiriam responder, inviabilizando half-duplex.

Para transmitir, o MCU leva `DE` ao nível **baixo**. O Driver Enable por hardware da USART STM32 aceita essa polaridade; basta configurar o bit `CR3.DEP = 1`, sem inversor externo.

> A conclusão concorda com o item ① do comentário da comunidade de 2026-09-06, que recomendava manter DE em nível alto por padrão: o resistor R4 foi adicionado exatamente para garantir que o barramento não seja acionado por padrão. Não se deve inverter isso aqui.

**Pendência:** deslocar no esquemático o símbolo de 3,3 V de `U3.7`, evitando que pareça conectado ao nó `DXL_DATA`.

### 2026-09-06 · Comentários da comunidade (três itens; dois corrigidos)

**① O pino DE precisa de pull-up — corrigido; estava faltando**

`U3.1 (1OE#)` habilita a transmissão em nível baixo. Durante a energização e o reset, `PA1` do MCU fica em alta impedância. Sem pull-up, o pino flutuaria; se assumisse nível baixo, o buffer de transmissão seria habilitado e a placa acionaria o barramento, provocando conflito com os 15 servos.

Foi adicionado **R4 de 10 kΩ entre DE e 3,3 V**.

O pull-up R1 em `SPI_CS` já tinha sido adicionado pelo mesmo motivo, mas não aplicamos o mesmo princípio ao DE — foi uma omissão.

**② Os dois pontos de `DXL_DATA` devem ser unidos e receber pull-up — corrigido**

Eletricamente já eram a mesma rede (`U3.5 2A` / `U3.6 1Y` / `J1.3` / `J2.3`), mas o desenho mostrava dois segmentos curtos com etiquetas distintas, dando a impressão de que não estavam ligados. O nó agora aparece explicitamente conectado.

O pull-up também era necessário: quando ninguém aciona o barramento, a entrada CMOS `2A` poderia flutuar e consumir corrente de passagem; a UART também poderia interpretar ruído como bit de início. A placa deve definir o nível de repouso sem depender do controlador principal. Foi adicionado **R5 de 10 kΩ entre DXL_DATA e 3,3 V**.

**③ Manter apenas um conector 3P — sugestão rejeitada; veja a justificativa do item 3 acima**

A sugestão funcionaria se a placa fosse certamente o nó final. Como ela pode ser o primeiro nó da cadeia, são necessários dois conectores; a topologia oficial não está disponível. Ambos foram mantidos, e a corrente é tratada com trilhas largas.

Após as alterações, DE passou de 2 para 3 pinos e `DXL_DATA`, de 4 para 5. O desenho não tem pinos flutuantes indevidos, curtos nem redes duplicadas.

### 2026-09-06 · Revisão comparativa com a HAT oficial (duas proteções acrescentadas)

Comparamos os componentes do esquemático `dynamixel.kicad_sch` do repositório [`pollen-robotics/elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT).

**Circuito TTL half-duplex da HAT**

`
                        ┌── R31 10k ── +3V3
   IO_15 (RX) ◄── U6 ───┘                    ┌── R32 10k ── +3V3
              (1G125, OE# ativo baixo)        │
                        ▲                     ▼
   IO_14 (TX) ──┬── U7 ──────────────────────► ● ── R33 150R ──┬── TH1 100R ── J13.3 / J14.3
                │ (1G126, OE ativo alto)                      D4 5V1
                └── R27 10k ── Q1 (PNP) ── Dynamixel_dir        ⏚
`

**Comparação item a item**

| | HAT oficial | Esta placa |
|---|---|---|
| Buffers de transmissão/recepção | Dois componentes, 1G125 + 1G126 | Um SN74LVC2G241 | Mesma lógica |
| Controle de direção | Derivado automaticamente do TX (Q1 + RC) | **DE por hardware da USART2** | Melhor nesta placa, conforme explicado abaixo |
| Pull-up do barramento | R32 10 kΩ | R5 10 kΩ | Igual |
| **Resistor em série na linha de dados** | R33 150 Ω + TH1 100 Ω | ❌ Ausente → **R6 de 150 Ω acrescentado** | |
| **Limitador de tensão na linha de dados** | D4 5V1 | ❌ Ausente → **D2 5V1 acrescentado** (mesmo código de peça `C151348`) | |
| Proteção da alimentação | Nenhuma (`+BATT` vai diretamente ao conector) | PPTC F1 + TVS D1 | Melhor nesta placa |

**Por que o controle de direção desta placa é melhor:** na HAT, a direção é derivada do TX e volta ao estado de recepção após um atraso RC. **Se for liberada cedo demais, o último bit de parada é truncado**, problema comum nessa abordagem. Aqui, o DE por hardware da `USART2` pode ser ajustado com precisão de 1/16 de bit por `DEAT`/`DEDT`, evitando esse problema.

**Topologia final da linha de dados**, agora semelhante à da HAT:

`
U3.6 (1Y) ──┬─ DXL_DATA ─┬── R5 10k → 3,3 V
U3.5 (2A) ──┘            │
                         └── R6 150 Ω ──┬── DXL_BUS ── J1.3 / J2.3
                                       │
                                    D2 5V1
                                       ⏚
`

O pull-up fica **no lado do buffer** (R5 antes de R6), na mesma posição relativa de R32 da HAT. Assim, mesmo sem o barramento conectado, a entrada CMOS `2A` tem nível definido.

Esta placa usa somente o resistor em série de 150 Ω (a HAT soma 250 Ω), pois já há 250 Ω no lado da HAT; resistência em excesso no barramento reduziria a velocidade das bordas.

Verificação: `DXL_DATA` (lado do buffer) tem 4 pinos; `DXL_BUS` (lado do conector), também 4. O esquemático não tem pinos indevidamente abertos, curtos nem redes com nomes duplicados.

**Correção de um erro anterior neste documento:** o componente `TH1 100R` da HAT é um termistor em série com a **linha de dados**, não com a alimentação. A linha de `+BATT` até o pino 2 de J13/J14 é uma trilha direta e larga, sem limitação de corrente.

### 2026-09-06 · Passivos padronizados em 0603

Todos os passivos 0402 foram trocados por **0603**; D2 passou de SOD-323 para **SOD-123**.

A razão não é que “0402 seja impossível de soldar à mão” — a placa tem uma LSM6DSV16X em **LGA-14**, com pads inferiores de 3 × 2,5 mm, que já exige estação de ar quente ou refluxo. Com as mesmas ferramentas, 0402 também pode ser soldado.

**O motivo real é facilitar o retrabalho durante a depuração:** testar o resistor em série entre 150 Ω e 33 Ω, remover um pull-up ou acrescentar um capacitor de desacoplamento. Essas tarefas levam segundos com um ferro em 0603; em 0402 exigem novamente a estação de ar quente. Uma placa de primeira versão que nunca foi fabricada nem validada certamente precisará de alterações.

O custo de área é pequeno: 11 componentes ocupam cerca de 16 mm² a mais, menos de 2% dos 45 × 22 mm da placa. Além disso, todos os valores 0603 usados estão no catálogo básico da JLC (10 kΩ `C25804` · 150 Ω `C22808` · 33 Ω `C23140` · 100 nF `C14663`), mais baratos que os componentes 0402 do catálogo estendido.

> C6 (10 µF/25 V) permanece 0805; C5 (4,7 µF) e C7 (10 µF) já eram 0603.

As peças foram reposicionadas nas mesmas coordenadas e com a mesma orientação. A medição confirmou que **as coordenadas dos pinos não mudaram e nenhuma trilha se rompeu**.
Uma armadilha: a ordem dos pinos do símbolo SOD-123 é oposta à do SOD-323; ao trocar, **a polaridade de D2 foi invertida** (o cátodo foi para o lado do terra e, em operação, prenderia o barramento em 0,7 V). Isso foi detectado comparando os nomes dos pinos e corrigido.
O parâmetro `rotation` de `create()` tem sinal invertido nesta API: passar 90 grava 270.
