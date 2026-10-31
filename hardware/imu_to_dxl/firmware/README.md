# imu_to_dxl Firmware 0.2.0

Usado na placa **STM32G031F8P6 + LSM6DSV16X** feita por um integrante da equipe. A base de hardware é
`fanhao375/microduck-replica` 的 `a1f4979c425bd9228622be89f2bfa4d1de7fbde3`
(`2026-09-08`, inclui J4/J5 e RX_EN). Em 2026-09-20 foi concluída a primeira inicialização na placa real: conexão J-Link SWD,
gravação e verificação de leitura do firmware, parada do Keil em `main`, clock de 64 MHz e amostragem do IMU foram verificados.
No teste curto, o identificador do IMU foi `0x70`, `ready=1` e os erros SPI/FIFO ficaram em 0; o barramento externo e os servos ainda não foram testados.

**Na versão 0.2.0 (2026-09-22), o protocolo do barramento foi substituído por Feetech SCS/STS** e implementado item a item conforme o [protocolo do barramento](../总线协议.md): ID 200, bloco de 15 bytes no endereço 56 e enfileiramento de sync_read. O IMU, a placa e o projeto Keil não foram alterados. Os testes do host no computador e a validação do “código real do protocolo em um barramento simulado” (`Tests/bus_sim_test.py`, usando os critérios `check` de [`tools/imu200`](../../../tools/imu200)) foram aprovados. O firmware foi gravado na placa de desenvolvimento original e o IMU continua funcionando. **O barramento real e os servos ainda não foram testados.**
Os limites da compilação, dos testes de desktop e da primeira validação na placa real estão em [VALIDATION.md](VALIDATION.md).

Este diretório reúne o diagrama de princípios e a PCB, e contém o código-fonte, o projeto Keil e o único artefato pré-compilado preservado
[`Build/imu_to_dxl.hex`](Build/imu_to_dxl.hex). O console de depuração serial [`tools/servo-web`](../../../tools/servo-web) sobrepõe os ângulos das articulações dos servos e a postura do tronco do IMU na mesma página Web. Há três modos de leitura: `--imu-bus` (barramento dos servos, mesma chamada sync_read do controlador), `--imu-swd` (ST-Link / DAPLink) e `--imu-jlink` (J-Link).

O observador SWD/J-Link decodifica do HEX a imagem Flash de **10.724 bytes** a partir de `0x08000000`, confere o SHA-256
`66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` e valida a imagem na placa.
Somente esta versão base pode usar o layout de RAM revisado: `sample=0x2000006C` (60 bytes),
`tick=0x20000A34` (4 bytes), conferido no MAP da versão 0.2.0. Não é necessário recompilar para usar apenas a página de postura; depois de alterar o firmware, revise novamente
o checksum da Flash e o endereço/tamanho destes dois símbolos. Não reutilize endereços antigos ao ler um programa novo.

Para depurar o código-fonte com breakpoints, compile novamente o `.axf` no seu ambiente. A compilação também gera `.map` e `.bin` para conferência durante o desenvolvimento;
Esses arquivos e os artefatos de teste são excluídos pelo `.gitignore` e não são enviados ao repositório.

Fluxo de dados: LSM6DSV16X → SPI1 → STM32 → USART2 + buffer externo → barramento half-duplex de fio único → controlador Linux.
Implementa o **protocolo Feetech SCS/STS, ID 200, 1 Mbps** e se apresenta como um servo no barramento (a versão 0.1.0 usava Dynamixel Protocol 2.0).
O código não movimenta servos, não grava nos Option Bytes do MCU e não grava configurações de firmware na Flash.

**Validação no barramento real:** conecte um adaptador half-duplex (URT-2) e execute `python tools/imu200/imu200.py check --port COMx`. Os 13 critérios foram derivados do código-fonte do controlador; todos devem passar antes de integrar o sistema. A verificação elétrica (liberação de DE, níveis lógicos e medição real de T_resp) ainda exige um analisador lógico.

## 1. Comece por aqui

### Keil

1. Para usar J-Link, abra `MDK-ARM/imu_to_dxl_jlink.uvprojx`.
2. No seu Keil, selecione uma instalação licenciada do Arm Compiler 6 (foram verificados 6.24 e 6.22; versões antigas como MDK 5.24, que incluem 6.7, não compilam: os cabeçalhos CMSIS 6 exigem ≥ 6.10 e podem resultar no erro `cmsis_clang.h` não encontrado) e o pacote do dispositivo `STM32G031F8Px`.
3. Pressione **F7** para compilar; `Build/imu_to_dxl.hex` é o arquivo para gravação e `.axf` é usado para depurar o código-fonte com breakpoints.
4. Em Debug → Settings, selecione seu J-Link e confira SWD, o algoritmo de Flash de 64 KB do STM32G0xx e Run to main.
   `JLinkSettings.JLinkScript` define a velocidade de transferência em **100 kHz** após conectar e reiniciar; mantenha esse arquivo.
   A primeira placa apresentou falhas de transferência ao baixar a 4 MHz. Na primeira conexão, recomenda-se começar pelos 100 kHz já validados.
5. Pressione **Ctrl+F5** para iniciar a depuração e parar em `main`; **F10** avança sobre a instrução, **F11** entra nela e **F5** executa.
   A pausa altera o tempo de amostragem e do barramento; em testes contínuos de comunicação, execute em velocidade total.

A configuração ST-LINK original de `MDK-ARM/imu_to_dxl.uvprojx` foi mantida. Ao trocar para J-Link, selecione novamente a sonda em Debug → Settings.

### VS Code

Abra esta pasta no VS Code para editar o código-fonte e execute o comando de compilação abaixo no terminal integrado.
Este fluxo usa VS Code para edição e Keil para compilação e depuração de hardware; não é necessário instalar CubeMX, CubeIDE ou GCC para compilar.
O código-fonte inclui os cabeçalhos CMSIS necessários e o driver ST do IMU; a primeira compilação não precisa baixar dependências da Internet.

Também é possível executar no terminal PowerShell deste diretório:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1
```

O caminho padrão do compilador `E:\Keil_v5\ARM\ARMCLANG` é apenas um exemplo. Em outro computador, use `-ToolchainRoot` para indicar uma instalação licenciada do Arm Compiler.
Os arquivos temporários de compilação ficam em `Build` neste projeto; cada software continua gerenciando as licenças do sistema operacional e das ferramentas instaladas.
A compilação substitui o firmware pré-compilado em `Build`; se quiser manter a versão validada pela página Web, preserve o artefato original antes.

## 2. Conteúdo do projeto

| Arquivo | Conteúdo |
|---|---|
| `Core/Inc/board_config.h` | Opções da placa, clock, baud rate e velocidade SPI centralizados |
| `Core/Src/board.c` | Clock, GPIO, SPI, USART, SWD, bases de tempo em ms/µs e watchdog |
| `Core/Src/imu.c` | Verificação de identidade, leitura de retorno da inicialização, FIFO, aceleração/giroscópio brutos, SFLP e novas tentativas após falhas |
| `Core/Src/protocol.c` | Escravo Feetech SCS/STS: análise de quadros (ressincronização por checksum), respostas às instruções, enfileiramento sync_read e temporização das respostas |
| `Core/Src/control_table.c` | Bloco de 15 bytes no endereço 56, bits de estado e registradores de diagnóstico |
| `Core/Src/main.c` | Agendamento do loop principal, comandos seriais e logs de estado |
| `Drivers/` | Código-fonte ST/CMSIS e licenças em versões fixas |
| `MDK-ARM/` | Projeto Keil, layout de linkedição e script de conexão lenta J-Link |
| `Tests/` | Testes de protocolo, sensores simulados e registradores que rodam sem placa; `bus_sim_test.py` compila o código real do protocolo como DLL e valida em um barramento simulado |

Não usa alocação dinâmica, RTOS ou HAL. O código da placa usa as definições oficiais de registradores CMSIS da ST; o sensor usa o driver oficial independente de plataforma.
A recepção do barramento externo no STM32 usa uma fila circular acionada por interrupção, que guarda o horário de chegada de cada byte; protocolo, amostragem e formatação dos logs são executados no loop principal.
O envio dos logs usa outra fila acionada por interrupção e não bloqueia a recepção do barramento.

## 3. Configuração de hardware padrão

| Função | Pino do chip / configuração |
|---|---|
| MCU | STM32G031F8P6, TSSOP20, 64 KB Flash / 8 KB RAM |
| Clock do sistema | HSI16 → PLL, M=1, N=8, R=2, 64 MHz, Flash com 2 wait states |
| Opção de clock externo | `BOARD_USE_HSE_BYPASS=1`; clock ativo X1 de 16 MHz ligado ao pino 2 do encapsulamento; em caso de falha na inicialização, volta à configuração HSI e registra o estado |
| SPI do IMU | SPI1 modo 3, 8 bits, CS por software; 64 MHz divididos para 2 MHz; PA4=CS, PA5=SCK, PA6=MISO, PA7=MOSI |
| INT do IMU | Primeira versão consulta o FIFO; sinal de interrupção PA0/pino 15 do encapsulamento não é usado por enquanto |
| Serial do barramento | USART2, PA2=TX, PA3=RX, AF1, 1 Mbps, 8N1; USART não usa HDSEL de pino único |
| DE do barramento | PA1 → U3.1 `1OE#`, **ativo em nível baixo**; controlado por GPIO e liberado somente após USART TC |
| RX_EN do barramento | PB7 → U3.7 `2OE`, **ativo em nível alto**; desabilitado durante a transmissão, PA3 com pull-up; PB8, no mesmo encapsulamento, permanece como entrada analógica |
| Serial de depuração | USART1, PA9/PA10 remapeados pelo SYSCFG para os pinos 16/17 do encapsulamento, 115200, 8N1; `BOARD_LOG_UART_SWAP=0` |
| SWD | PA13=SWDIO, PA14=SWCLK; mantém a função de depuração padrão após o reset |
| Watchdog | Habilitado por padrão, cerca de 2 s; a tolerância do LSI afeta a duração real; fica congelado quando o depurador pausa a execução |

Se a inicialização da PLL falhar, o sistema continua com HSI16 e calcula BRR serial e temporizadores com a frequência real do clock. Nesse caso, o SPI também cai para 0,5 MHz,
e a latência do serviço aumenta. Esse é um modo de diagnóstico de falha: confira o estado do clock; não o use como configuração aprovada para desempenho final.

### Para a fiação J3, consulte o [diagrama de princípios em PDF](../imu_to_dxl-Princípio图.pdf) e as conexões da placa real

| Pino J3 | Sinal no diagrama de princípios atual | Conexão |
|---|---|---|
| 1 | GND | Terra comum para J-Link/ST-LINK/USB-TTL |
| 2 | SWDCLK | SWCLK do J-Link/ST-LINK |
| 3 | SWDIO | SWDIO do J-Link/ST-LINK |
| 4 | UART_RX, pino 17 do encapsulamento U1 | TX do USB-TTL, nível de 3,3 V |
| 5 | UART_TX, pino 16 do encapsulamento U1 | RX do USB-TTL, nível de 3,3 V |
| 6 | 3.3V | Referência de tensão do depurador; não conecte 5 V aqui |

Para SWD em J3, use os quatro fios nos pinos **1, 2, 3 e 6**. Não encaixe uma antiga fita de quatro vias nos pinos 1–4:
o pino 4 é entrada serial e não serve como alimentação ou referência de tensão. Antes de energizar pela primeira vez, confira as ilhas de solda e a rede no EDA.
J3 não expõe NRST; para conectar em under-reset, ligue também ao ponto NRST real.
Se o depurador tiver saída de alimentação, não a conecte em paralelo às cegas com outra fonte; primeiro confirme se é entrada VTref ou saída de alimentação.

J1/J2: 1=GND, 2=VDD_BUS, 3=DATA; J4/J5: 1=DATA, 2=VDD_BUS, 3=GND.
O teste do barramento exige um adaptador USB half-duplex de fio único; um USB-TTL comum serve somente para os logs de J3.

## 4. Comportamento do IMU

- `WHO_AM_I` deve ser `0x70`. Após o reset por software, configura o dispositivo em etapas e lê de volta ODR, faixa e ativação SFLP.
- Acelerômetro ±4g, 0,122 mg/LSB; giroscópio ±500 dps, 17,5 mdps/LSB.
- Acelerômetro, giroscópio, SFLP e processamento em lote FIFO operam a 120 Hz para leitura pelo controlador a 50 Hz.
- O FIFO distingue aceleração, giroscópio e quaternion por tags; processa no máximo 16 registros por rodada e não presume que os três estejam no mesmo registro.
- `ready=0` durante a inicialização, falha SPI, overflow FIFO ou dados expirados; uma nova tentativa ocorre após cerca de 1 s.
- Se os dados do gyro ou do quaternion não forem atualizados por mais de 100 ms, são considerados inválidos. Mesmo quando o loop principal está ocupado e não consulta a amostragem, a leitura do snapshot verifica a idade novamente.
- A interface de leitura mantém um snapshot consistente e não atualiza a postura em uma interrupção. A rotação de instalação do sensor fica a cargo do controlador, para evitar aplicar duas vezes a transformação de coordenadas do upstream.
- Esta versão não salva offsets medidos; o SFLP começa a estimar a partir do estado padrão ao ligar. A postura de seis eixos não fornece uma referência absoluta de rumo.

Uma postura unitária válida `xyz=0,0,0` coincide com o marcador de “não pronto” composto por zeros do upstream. Depois de receber uma postura FIFO válida, somente a codificação fp16 de x é definida como zero negativo IEEE `0x8000`, cujo valor matemático continua sendo 0; quando realmente não está pronto, todos os valores permanecem zero. Consulte a descrição do driver e os testes de regressão.

**Limite do tratamento de falhas durante a execução:** o controlador oficial examinado pode manter a postura anterior ao receber uma postura toda zerada; seu `ready()` não é automaticamente revogado por isso.
Antes da integração oficial de movimentos ou postura em pé, o controlador deve ler também `ready`, o contador de amostras e a idade dos dados de diagnóstico desta versão, e tratar dados inválidos.
O script de aquisição no PC desta versão já lê esses campos; o fato de “a placa isolada retornar zeros” não significa que o sistema completo pare automaticamente.

## 5. Comunicação e registradores

Formato do quadro: `FF FF ID LEN INSTR parâmetros… CHK`, `CHK = ~(ID+LEN+INSTR+Σparâmetros)`. Como não há byte stuffing, `FF FF` também pode aparecer no payload: a recepção acumula o comprimento indicado e depois valida o checksum; se estiver incorreto, descarta um byte e procura novamente o cabeçalho, sem se confundir com um falso cabeçalho no payload. Consulte o comportamento de cada instrução no [protocolo do barramento §8](../总线协议.md#8-其它指令怎么应答):

| Instrução | Comportamento |
|---|---|
| `SYNC_READ 0x82` (broadcast) | Se estiver na posição k da lista: para k=0, transmite 50 µs após receber a instrução completa; para k>0, aguarda os quadros de resposta dos k dispositivos anteriores (ID anterior, comprimento correto e quinto byte diferente do código de instrução); se algum dispositivo anterior ficar silencioso por 1 ms, considera-o offline e o ignora |
| `PING` / `READ` (unicast) | Retorna quadro de estado/dados, ERROR sempre 0; PING em broadcast não recebe resposta |
| `WRITE` / `REG_WRITE` (unicast) | Retorna ACK; ignora todo o conteúdo (o controlador nunca grava nesta placa) |
| `ACTION` `0x06` `0x09` `0x0A` `0x0B` (unicast) | ACK, sem ação |
| `REBOOT 0x08` | Sem resposta; reinicia de fato |
| `SYNC_WRITE` e outros broadcasts | Sem resposta |

Temporização (todos são valores inferidos, ainda precisam ser medidos; consulte o protocolo do barramento §5/§12. Os 50 µs são o valor na lógica do protocolo; o valor real, incluindo o tempo de CPU para analisar e montar o quadro, deve ser medido com analisador lógico): T_resp 50 µs; descarta o quadro incompleto se o intervalo entre bytes exceder 500 µs; durante o enfileiramento, considera o dispositivo anterior offline após 1 ms de silêncio; desiste da rodada após 25 ms; se não conseguir transmitir até 2 ms depois do horário programado, desiste para não disputar o barramento no meio de outra transação. Antes de transmitir, faz uma verificação atômica de novos dados RX, USART BUSY e flags de erro; se o barramento estiver ocupado, abandona a resposta.
Na interrupção de recepção, somente overflow (**ORE**) é tratado como falha do barramento e limpa o quadro recebido; flags de ruído/framing apenas incrementam contadores, os bytes continuam sendo recebidos e o checksum descarta os inválidos. A versão 0.1.0 limpava tudo, de modo que um byte com flag de ruído descartava o sync_read inteiro e fazia os 15 servos perderem aquele tick (corrigido após revisão da 0.2.0).

**Coloque o ID 200 na primeira posição da lista Sync Read**, como em `bus.rs` oficial. Ele também pode responder no meio da lista (regra de enfileiramento), mas se faltar um dispositivo anterior, a análise no controlador fica desalinhada; consulte o protocolo do barramento §2.

Todos os campos com mais de um byte usam little-endian.

| Endereço | Bytes | Conteúdo / permissão |
|---|---:|---|
| 0 / 1 | 1 cada | Versão do firmware 0.2 (principal/secundária); não se identifica como servo 3.46 |
| 2 | 1 | END = 0 (little-endian) |
| 3 | 2 | Modelo personalizado `0x4D44` |
| 5 / 6 / 8 | 1 cada | ID 200 / baud rate 0 (1 Mbps) / nível de estado da resposta 1 |
| **56** | **15** | **Bloco lido pelo controlador a cada tick**: gyro XYZ (int16, 17,5 mdps/LSB), quaternion XYZ (binary16), contador de amostras (u8), bits de estado e reservado 0. Eixos originais, sem transformação de coordenadas |
| 124 | 6 | gyro XYZ, três int16, ±500 dps (diagnóstico, mesmos dados do bloco) |
| 130 | 6 | quaternion XYZ, três IEEE binary16; o controlador reconstrói W |
| 136 | 6 | Aceleração XYZ original, três int16, ±4g |
| 142 | 1 | 8 bits inferiores do contador de amostras de postura |
| 143 | 1 | bit0=ready, bit1=configured, bit2=error |
| 144 / 145 | 1 cada | WHO_AM_I / código de erro |
| 146 / 147 | 1 cada | Estado do clock / estado do watchdog |
| 148 / 152 / 156 | 4 cada | Contadores de amostras da postura / gyro / acelerômetro |
| 160 / 164 / 168 | 4 cada | uptime_ms / idade do gyro em ms / idade da postura em ms |
| 172 / 176 / 180 / 184 | 4 cada | Erros SPI / overflows FIFO / quaternions inválidos / quantidade de recuperações |
| 188 / 192 / 196 / 200 | 4 cada | Overflow da fila RX / erros UART (ruído/framing/overflow) / erros de checksum / pacotes inválidos |
| 204 / 208 / 212 / 216 | 4 cada | Timeout de recepção / pacotes válidos recebidos / pacotes efetivamente transmitidos / respostas canceladas |
| 220 / 224 / 228 / 232 | 4 cada | Valor bruto da causa de reset RCC / clock em Hz / timeout TX / logs descartados |
| 236 | 1 | Versão 2 da tabela de registradores de diagnóstico deste projeto (protocolo Feetech, bloco no endereço 56) |
| 240 | 4 | Quantidade de dispositivos anteriores ignorados como offline durante o enfileiramento sync_read |
| 244 | 4 | Quantidade de respostas abandonadas após detectar o barramento ocupado antes da transmissão |

As demais leituras nos endereços 0~255 retornam 0; gravações recebem ACK, mas não têm efeito (para reinicializar o IMU, use o comando `r` na serial de logs J3). 56~70 é a interface do controlador; 124 em diante é uma **extensão de diagnóstico personalizada deste projeto**, sem alegação de compatibilidade com os registradores de tensão/temperatura dos servos.

Bits de estado do bloco (byte 13): BIT0 fusão não pronta (quaternion todo zero); BIT1 falha de comunicação com o IMU (SPI/timeout de reset/configuração/dados expirados/FIFO); BIT2 falha no autoteste (`WHO_AM_I` incorreto); BIT3 houve pelo menos 4 atualizações entre duas leituras do bloco (com amostragem de 120 Hz e leitura a 50 Hz, 2–3 atualizações por leitura são normais).
Códigos de erro em `imu.h`: 0 normal, 1 inicialização, 2 SPI, 3 identidade, 4 timeout de reset, 5 configuração, 6 expirado, 7 FIFO, 8 quaternion.
Estado do clock: 0=HSI PLL, 1=HSE PLL, 2=falha HSE com retorno a HSI PLL, 3=falha PLL usando HSI16, 4=falha na troca com retorno.

## 6. Sequência após receber a placa

1. Confira a versão do hardware, a orientação de J3 e a alimentação. Energize primeiro somente a placa, com limite de corrente, e verifique os 3,3 V, curtos, aquecimento e reset.
2. Identifique o STM32 por SWD, grave o HEX e confirme que é possível parar em `main` com breakpoint e iniciar normalmente após reset ou desligar/ligar a alimentação.
3. Conecte a serial de logs J3, 115200/8N1. Deve aparecer a versão; uma linha por segundo informa `ready`, ID, erros e dados.
   `s` imprime o estado, `l` alterna os logs periódicos, `r` reinicializa o IMU e `?` mostra a ajuda.
4. Confira `WHO_AM_I=0x70`, `ready=1` e o aumento do contador de amostras. Vire e gire a placa nos três eixos para conferir a direção da aceleração e da postura.
5. Conecte somente o IMU ao barramento (com adaptador half-duplex como URT-2) e execute `python tools/imu200/imu200.py check --port COMx --only-imu` (consulta somente o ID 200). Depois conecte os servos e execute o `check` completo.
6. Use um analisador lógico para verificar 1 Mbps, polaridade de DE, liberação após o último bit de parada, restauração de RX e pior latência de resposta.
7. Conecte um servo e depois o barramento completo; coloque o ID 200 primeiro. Registre erros, pacotes perdidos, FIFO e idade das amostras.
8. Conclua o tratamento de falhas do controlador e confira a direção de instalação antes de integrar o sistema completo com apoio no chão.

### Ferramentas de validação no computador

Use [`tools/imu200/imu200.py`](../../../tools/imu200/imu200.py) para validar o barramento (`Tools/imu_probe.py` da versão 0.1.0 era para o protocolo Dynamixel e foi removido quando o protocolo mudou). Requer Python 3.10+ e pyserial:

```powershell
python tools/imu200/imu200.py check --port COM5   # 13 critérios, cada um com PASS/FAIL, derivados do código do controlador
python tools/imu200/imu200.py demo                # sem hardware; mostra as respostas da placa simulada
```

Substitua COM5 pela porta do **adaptador half-duplex do barramento**; a porta de logs J3 não responde a essas instruções do protocolo. Os logs ficam em `tools/imu200/logs/` (hexadecimal bruto enviado/recebido e uma linha JSONL por quadro).
É preciso instalar uma distribuição executável do Python; o atalho fictício da Microsoft Store do Windows não executa esses scripts. A compilação do firmware em si não precisa de Python.

## 7. Validação e limitações conhecidas

Os testes executam código compilado por um compilador C real; os testes SPI/FIFO usam registradores e tempo simulados, portanto não equivalem a medições no chip.
Depois de instalar o MSVC, execute `Tools/test.ps1` no **x64 Native Tools Command Prompt / Developer PowerShell** para repetir os testes de host.
O script exige que `cl` esteja no PATH; use `-PythonExe` para indicar seu Python. Para executar separadamente os dois arquivos `.cmd` de teste C,
também é possível passar como primeiro argumento o caminho completo do seu `vcvars64.bat`. O script de teste não instala compilador nem se conecta ao hardware.
O registro atual de validação está em `VALIDATION.md`; as versões das fontes de terceiros estão em `DEPENDENCIES.md`.

Ainda precisam de confirmação na placa real: alimentação e montagem, erro de baud rate do HSI, modo/borda/timing de CS do SPI, temporização de habilitação TX, níveis elétricos do barramento,
taxa real de atualização do FIFO, convergência inicial e eixos do SFLP, deriva térmica, recuperação do watchdog e operação prolongada no barramento compartilhado.
Testes de software não substituem essas validações.

## 8. Referências

- [Hardware desta placa](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [Datasheet STM32G031](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [Datasheet LSM6DSV16X](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [Driver de IMU da ST](https://github.com/STMicroelectronics/lsm6dsv16x-pid)
- Protocolo de comunicação Feetech SCS e tabela de memória: diretório [`docs/飞特资料/`](../../../docs/飞特资料/) do repositório
- [Protocolo do barramento desta placa (contrato da interface)](../总线Protocolo.md)
- [Interface upstream do controlador examinada](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)

O código novo deste projeto é fornecido sob a licença MIT; arquivos de terceiros preservam seus direitos autorais e licenças próprios, consulte cada diretório em `Drivers`.
