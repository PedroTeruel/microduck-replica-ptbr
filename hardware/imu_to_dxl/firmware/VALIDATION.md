# Registro de validação do firmware

Objeto: `imu_to_dxl` 0.2.0 (protocolo Feetech), STM32G031F8P6 + LSM6DSV16X. Os registros da versão 0.1.0 (Dynamixel 2.0) estão preservados mais abaixo.
Este documento distingue os testes no computador dos resultados obtidos em hardware real.

## 0.2.0 · Protocolo Feetech (2026-09-22)

As alterações ficaram restritas à camada de protocolo (`protocol.c/.h`, `control_table.c/.h`, interface em `main.c`, `board_reboot` e número da versão). A IMU, a inicialização da placa, os arquivos de inicialização e o projeto Keil não foram modificados.

| Item | Resultado |
|---|---|
| Recompilação com Keil MDK 5.41 + Arm Compiler 6.22 | 0 erros, 0 avisos (`-Wall -Wextra`) |
| Flash | 10.724 / 65.536 bytes (a versão 0.1.0 usava 11.612; CRC16 e preenchimento de bytes deixaram de ser necessários) |
| RAM, incluindo pilha de 2 KiB | 4.664 / 8.192 bytes |
| SHA-256 da imagem decodificada do HEX | `66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` |
| Conferência do MAP | `sample=0x2000006C` (60 bytes, `imu.o`), `tick_ms=0x20000A34` (4 bytes, `board.o`). `tools/servo-web/imu_bridge.py` foi atualizado e conferido com a própria lógica de verificação MAP. |

| Testes no computador (MSVC, sem hardware) | Resultado | Cobertura |
|---|---|---|
| Teste C do protocolo `Tests/protocol_test.c` (reescrito) | 104 verificações, 0 falhas | Comparação byte a byte com os vetores de teste da seção 10 do protocolo do barramento; resposta de cada comando; fila `sync_read` (aguarda resposta anterior, pula dispositivo offline, cancela por tráfego de outro dispositivo, timeout da transação); validação da lista de IDs; ressincronização do checksum; falso cabeçalho dentro do payload; intervalo entre bytes; liberação e expiração da resposta; retorno do timestamp. |
| Testes de mutação | 9/9 bugs inseridos manualmente foram detectados | Byte ERROR, fila, ressincronização, PING de difusão, liberação, reconhecimento do tamanho, T_resp, salto de lacuna e comando do controlador interpretado como resposta anterior. |
| Teste C da tabela de registradores `Tests/control_table_test.c` (reescrito) | 32 verificações aprovadas | Layout dos blocos, saída zerada quando não está pronto, bits de estado BIT0–3, contagem de BIT3 entre leituras e reinicialização da IMU, área de diagnóstico e limites. |
| Testes de simulação C da IMU | 16 cenários aprovados | Sem alterações em relação à versão anterior. |
| **Barramento simulado usando o código real do protocolo** `Tests/bus_sim_test.py` | **24/24** | `protocol.c` e `control_table.c` compilados em uma DLL e inseridos entre 15 servos simulados em `sim_bus`. Todos os critérios do controlador de `tools/imu200/imu200.py check` passaram: contadores avançam 2–3 por quadro; a janela de 12 bytes repete no máximo 3–4 quadros; cerca de 75/80 quadros são aceitos pelo controlador, com pequena variação entre execuções. O firmware foi consultado a cada microssegundo enquanto outros dispositivos transmitiam e com o barramento ocioso: **nenhuma transmissão indevida**. O p99 do `sync_read` com 16 dispositivos no barramento virtual foi cerca de 3,9 ms (T_resp dos servos simulados definido em 30 µs; o “tempo da transação” do teste mede o relógio de parede Python, sem esse custo simulado). O T_resp lógico do protocolo é 50 µs, sem incluir tempo de CPU. A ordem das respostas é correta quando o dispositivo 200 está no meio e há um dispositivo anterior offline. O painel de depuração também foi exercitado com polling `--imu-bus` ao vivo. |

**Revisão de código (subagente, 2026-09-22):** não encontrou problemas de envio no momento errado nem de omissão de respostas em `protocol.c`. As alterações feitas após a revisão foram: (1) durante o enfileiramento, um quadro cujo quinto byte é um código de comando não conta como resposta anterior — o controlador pode enviar a um servo anterior um comando de mesmo tamanho sem esperar esta placa, causando colisão; isso só aparece durante a depuração; (2) a interrupção de recepção em `board.c` só limpa os dados em caso de overflow; ruído e erro de quadro apenas incrementam contadores. Antes, uma indicação de ruído descartava o ciclo inteiro. Essa é uma alteração de registradores que **não pode ser coberta pelo teste no computador e precisa ser verificada no barramento real**; (3) o teste do barramento simulado passou a detectar transmissões indevidas e usar tempo virtual.

**Placa física (placa de desenvolvimento original, ST-LINK/V2, 2026-09-22):** gravação com CubeProgrammer e verificação da leitura concluídas. Após desligar e ligar, o pyOCD leu a RAM: WHO_AM_I=0x70, ready=1, cerca de 121 Hz e zero erros SPI/FIFO/quatérnio. O protocolo Feetech estava ocioso e os contadores de envio e recebimento eram zero (o barramento não estava conectado). **O barramento real, os servos, o T_resp medido e a temporização de liberação DE ainda não foram testados.** Atenção: a placa contém a versão 0.2.0 anterior à revisão. Para usar o observador SWD/J-Link, grave novamente o HEX do repositório; o observador reconhece somente esta versão pelo hash.

Observação: depois da primeira gravação em um G0 virgem, um software reset entra no bootloader incluído pela ST (`FLASH_ACR.EMPTY` só é atualizado na inicialização por hardware). Desligue e ligue a placa uma vez para iniciar o programa do usuário. Veja também o registro de problemas do repositório.

---

Registros anteriores da versão 0.1.0 (protocolo Dynamixel 2.0).

## Base pré-compilada (2026-09-15)

| Item | Resultado |
|---|---|
| Recompilação com Keil µVision 5.43.1 + Arm Compiler 6.24 | 0 erros, 0 avisos |
| Compilação CLI com `Tools/build.ps1` | Sucesso; os arquivos BIN/HEX fornecidos com o projeto vieram desta entrada. |
| Flash | 11.612 / 65.536 bytes |
| RAM, incluindo pilha de 2 KiB | 5.096 / 8.192 bytes |
| Dados estáticos | 3.048 bytes |
| Ponteiro inicial da pilha | `0x20002000` |
| Vetores SysTick / USART1 / USART2 | Entradas Thumb válidas em Flash |

Este diretório mantém o código-fonte correspondente e `Build/imu_to_dxl.hex`. O SHA-256 da imagem Flash de 11.612 bytes decodificada do HEX a partir de `0x08000000` é igual ao do BIN original:

`69bdaea7224900addd6eb5bd28001e26e07073c129383d9c1ece380d2bfce19a`

A revisão do MAP original encontrou `sample=0x20000064` (60 bytes) e `tick=0x20000BE0` (4 bytes).
Esse layout só vale para a imagem acima. O observador J-Link em `tools/servo-web` extrai a base Flash do HEX e verifica a imagem estritamente; não depende do BIN/MAP commitado e não aceita artefatos arbitrários recompilados.
Durante o desenvolvimento, ainda é possível gerar `.axf` para depuração com pontos de interrupção e conferir símbolos no `.map` local. Depois de modificar o firmware, revise novamente o layout de leitura e os hashes.

## Testes no computador (2026-09-15)

| Teste | Resultado | Cobertura |
|---|---|---|
| Teste C do protocolo | 106 verificações, 0 falhas | CRC, preenchimento de bytes, quadros danificados, ordem de resposta, campos somente leitura, timeout/retorno do contador, limites e recuperação após ruído. |
| Simulação C da IMU | 16 cenários aprovados | ID incorreto, componente ausente, falha de leitura após configuração, FIFO, limites de ponto flutuante, dados congelados, recuperação automática e snapshot expirado. |
| Teste C dos registradores | 14 casos aprovados | Little-endian, limites com sinal, mapeamento de diagnóstico, limites, proteção de somente leitura e comandos finitos. |
| Teste das ferramentas de coleta Python | 4 casos aprovados | Quadro PING conhecido, preenchimento, decodificação de diagnóstico e orientação inválida. |

Repita os testes do computador com `Tools/test.ps1`; MSVC e Python devem estar instalados. Os testes de SPI/FIFO usam registradores e tempo simulados, e não equivalem à validação elétrica do barramento e do sensor.

Depois da preparação do lançamento em 2026-09-21, os quatro grupos de testes foram executados novamente com o ambiente MSVC explicitamente configurado: 106 verificações de protocolo, 16 cenários de IMU, 14 verificações de registradores e 4 testes Python passaram. Também foram verificadas a sintaxe dos scripts PowerShell/Python e a mensagem de erro quando falta um compilador. O firmware não foi recompilado e não foi conectado a hardware. O hash do HEX continuou igual ao do pacote original.

No mesmo dia, após a revisão do PR #32 e a migração para `hardware/imu_to_dxl/firmware/`, `Tools/test.ps1` foi executado novamente a partir do novo caminho. Os quatro grupos passaram; também passaram a verificação de sintaxe dos dois scripts PowerShell e a verificação de caminhos relativos dos dois projetos Keil.
A migração não alterou Core, Drivers, Startup, testes, ferramentas de construção nem HEX. Não houve recompilação nem conexão a uma placa real.

## Integração à bancada de depuração serial (2026-09-21)

- Depois de mover o firmware para este diretório, `Tools/test.ps1` foi executado novamente: passaram as 106 verificações de protocolo, 16 cenários de IMU, 14 testes de registradores e 4 testes Python. Não houve recompilação nem gravação do firmware.
- `tools/servo-web/selftest.py`: passou; o teste de simulação de servos no nível do protocolo foi mantido.
- `python -m pytest test_imu_bridge.py test_imu_server.py`: 45 testes e 59 subcenários passaram, incluindo análise/verificação do HEX, proteções de RAM e sonda, transmissão simultânea de servo e IMU pelo mesmo WebSocket, IMU desativada, ciclo de vida e registros unificados.
- `node --test test_imu_attitude.cjs`: 13 testes passaram, cobrindo orientação de montagem padrão Y+90°, zeragem do quatérnio e orientação bruta, expiração dos dados e desconexão.
- No navegador, `--fake --imu-demo` verificou o mesmo modelo: a junta simulada 30 mudou de 2048 para 2300 e, mesmo com o retorno em 2297, a orientação do tronco da IMU continuou atualizando. Orientação de montagem, pose bruta, zeragem e registros classificados da IMU funcionaram. Ao parar o serviço, a interface mostrou desconexão e congelou a pose; ao reiniciar sem parâmetros de IMU, o painel foi ocultado e a bancada original mostrou 15/15 servos simulados online. Não foram usados servos ou placa reais.
- A chamada DLL do J-Link, a velocidade SWD e a decodificação de amostras do sensor mantiveram a implementação anterior. No novo caminho, a base Flash é decodificada do único HEX e o hash fixo está ligado ao layout RAM verificado no MAP original. Após a conexão, a Flash da placa ainda é comparada.
- Os resultados acima são de regressão sem hardware. Ainda não houve validação simultânea de servos e IMU reais, orientação de montagem no local nem equilíbrio do robô completo.

## Validação da placa de desenvolvimento original (2026-09-20)

- Conexão SWD com J-Link a 100 kHz, gravação do firmware e verificação da leitura passaram; o Keil conseguiu parar em `main`.
- Clock do sistema de 64 MHz e amostragem da IMU verificados; WHO_AM_I=`0x70`, ready=1 e contadores de erro SPI/FIFO em zero.
- O navegador leu a orientação real via J-Link e atualizou aproximadamente a 20 Hz. A tensão de referência foi cerca de 3,29 V; isso não é uma medição de corrente de entrada, ripple ou temperatura.
- Observou-se que a conexão do J-Link 9.78 reinicia o programa da placa. A zeragem web muda apenas a referência de exibição; não grava parâmetros de calibração.

Esses resultados se aplicam somente à placa de desenvolvimento original. Cada outra placa exige verificação própria da fiação e da primeira energização.

## Validações ainda pendentes

- O barramento externo de linha única e os servos ainda não foram testados na placa real. É necessário verificar no local o erro de baud rate da USART, a temporização de liberação DE, os níveis elétricos, a imunidade a interferência na linha compartilhada e a latência máxima de resposta.
- A versão 0.2.0 implementa o contrato Feetech de 15 bytes no endereço 56 e passou pela verificação de `tools/imu200` no barramento simulado. Na placa real, ainda é necessário executar `imu200.py check --port` e medir primeiro o T_resp do servo Feetech (seção 5 do protocolo do barramento).
- Coordenadas de montagem, deriva térmica, convergência SFLP de longo prazo, margem da pilha, recuperação do watchdog e estabilidade prolongada ainda precisam de testes específicos.
- Antes de iniciar o movimento, o controlador deve ler o estado de diagnóstico e tratar dados expirados. Uma placa isolada retornar orientação zerada não significa que o robô completo tenha capacidade de parada automática.

Não se declara concluída a validação do equilíbrio, dos movimentos do robô completo nem do barramento Feetech real.
