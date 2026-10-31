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
这些文件及测试产物由 `.gitignore` 排除，不提交到仓库。

Fluxo de dados: LSM6DSV16X → SPI1 → STM32 → USART2 + buffer externo → barramento half-duplex de fio único → controlador Linux.
Implementa o **protocolo Feetech SCS/STS, ID 200, 1 Mbps** e se apresenta como um servo no barramento (a versão 0.1.0 usava Dynamixel Protocol 2.0).
O código não movimenta servos, não grava nos Option Bytes do MCU e não grava configurações de firmware na Flash.

**Validação no barramento real:** conecte um adaptador half-duplex (URT-2) e execute `python tools/imu200/imu200.py check --port COMx`. Os 13 critérios foram derivados do código-fonte do controlador; todos devem passar antes de integrar o sistema. A verificação elétrica (liberação de DE, níveis lógicos e medição real de T_resp) ainda exige um analisador lógico.

## 1. 直接开始

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

## 4. IMU 行为

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

| 指令 | 行为 |
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

多字节字段全部小端。

| 地址 | 字节数 | Conteúdo / 权限 |
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

## 6. 板到后 de 顺序

1. 核实HardwareVersão、J3方向 e Alimentação，先单板限流Superior电，Verificação3.3V、短路、发热e复位。
2. SWD识别 STM32，Baixar HEX，确认 main 可断点、复位e断电重启都可Inicialização。
3. 接 J3 日志串口，115200/8N1。应有Versão信息；每秒输出 ready、id、错误eDados。
   `s`打印状态，`l`切换周期日志，`r`重新初始化IMU，`?`查看帮助。
4. Verificação WHO_AM_I=0x70、ready=1、采样计数增长，翻面/转动三轴核对加速度 e 姿态方向。
5. 只接 IMU 的总线（URT-2 等半双工适配器），运行 `python tools/imu200/imu200.py check --port COMx --only-imu`（只问 200），再接舵机跑完整的 `check`。
6. 用逻辑分析仪Verificação1Mbps、DE极性、最后停止位后释放、RX恢复 e 最坏回复延迟。
7. 接入一个Servo，再接Completo总线；ID200放第一。记录错误、丢包、FIFO e 采样年龄。
8. Concluído主控失效处理eInstalação方向核对后，再进行支撑状态Inferior de 整机联调。

### 电脑验收Ferramentas

总线验收用 [`tools/imu200/imu200.py`](../../../tools/imu200/imu200.py)（0.1.0 的 `Tools/imu_probe.py` 说的是 Dynamixel 协议，已随协议更换删除）。需要 Python 3.10+ 和 pyserial：

```powershell
python tools/imu200/imu200.py check --port COM5   # 13 项逐条 PASS/FAIL，判据照主控源码
python tools/imu200/imu200.py demo                # 不接硬件，看假小板怎么答
```

把 COM5 替换为**半双工总线适配器**端口；J3日志口不能响应这些协议指令。日志落在 `tools/imu200/logs/`（原始收发十六进制 + 每帧一行 JSONL）。
é necessárioInstalação可Execução de  Python，Windows 应用商店入口占位符不能Execução这些脚本；编译Firmware本身无需 Python。

## 7. Validação e 已知限制

Teste代码使用实际 C 编译器Execução；SPI/FIFOTeste用模拟寄存器e时间，不等同于芯片实测。
安装 MSVC 后，在其 **x64 Native Tools Command Prompt / Developer PowerShell** 中运行 `Tools/test.ps1` 重复主机测试。
该入口要求 `cl` 已在 PATH 中；可传 `-PythonExe` 指定自己的 Python。单独运行两份 C 测试 `.cmd` 时，
也可将自己的 `vcvars64.bat` 完整路径作为第一个参数。测试脚本不会安装编译器，也不连接硬件。
当前验证记录见 `VALIDATION.md`，第三方源版本见 `DEPENDENCIES.md`。

待实板确认：Alimentação e 装配、HSI波特率误差、SPI模式/边沿/片选时序、TX使能时序、总线Eletrônica电平、
FIFO实际Atualização率、SFLP初始收敛e坐标方向、温漂、看门狗恢复 e 长时间共线Execução。
SoftwareTestepor meio de不能替代这些验收。

## 8. 资料依据

- [本板硬件](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [STM32G031数据手册](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [LSM6DSV16X数据手册](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [ST IMU驱动](https://github.com/STMicroelectronics/lsm6dsv16x-pid)
- 飞特《SCS 通信协议》与内存表：仓库 [`docs/飞特资料/`](../../../docs/飞特资料/)
- [本板总线Protocolo（接口契约）](../总线Protocolo.md)
- [所检查的上游主控接口](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)

este projeto新写代码按 MIT Licença提供；TerceiroArquivoPreservado各自版权eLicença，见各 Drivers Diretório。
