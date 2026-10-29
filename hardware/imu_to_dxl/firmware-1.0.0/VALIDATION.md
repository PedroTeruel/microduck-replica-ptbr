# Registro de validação do firmware

Alvo: **imu_to_dxl 1.0.0 (versão Feetech FT-SCS) / STM32G031F8P6 + LSM6DSV16X**.
Data da validação: 2026-09. Inclui testes no computador, compilação e gravação reais e teste do barramento compartilhado no equipamento.
Esta versão migrou completamente do Dynamixel 2.0 para Feetech FT-SCS; os registros da versão antiga não se aplicam.

## 1. Compilação

| Item | Resultado |
|---|---|
| Compilação CLI com ArmClang (Keil MDK, C:\Keil_v5), Tools/build.ps1 | Sucesso, 0 erros |
| Projeto Keil | Mantém somente o conjunto DAP: MDK-ARM/imu_to_dxl_dap.uvprojx |
| Flash (Code + RO + RW) | **10.920/65.536 bytes** (10,66 KB) |
| RAM (RW + ZI, incluindo pilha de 2 KiB) | **5.092/8.192 bytes** (4,97 KB) |
| Artefatos de construção | Build/imu_to_dxl.hex/.bin/.axf/.map + imu_to_dxl.build.json (inclui SHA256) |
| Gravação | OpenOCD + CMSIS-DAP, comando program ... verify reset exit; verificação OK |

Observação: o comando de gravação da linha de comando UV4 pode informar sucesso incorretamente (código de saída 0 sem apagar/gravar de fato). Considere a gravação pelo OpenOCD como referência.

## 2. Testes no computador sem hardware

Tools/test.ps1 (gcc, WinLibs mingw64) foi executado e passou:

| Teste | Resultado | Principais verificações |
|---|---|---|
| Tests/protocol_test.c | **93 verificações, 0 falhas** (proto_context com 1.104 bytes) | Montagem de quadros e vetores de checksum Feetech (PING, READ 56/12), PING/READ/WRITE, PING de broadcast sem resposta, resposta imediata ao primeiro ID no SYNC READ, resposta de IDs posteriores após detectar quadro válido do ID anterior, pular ID ausente após timeout de 25 ms, invalidar com novo quadro do host, recuperação de quadro malformado/timeout de byte, limites de LEN e ressincronização após ruído, proteção de região somente leitura |
| Tests/control_table_test.c | **18 aprovados** | Codificação little-endian, empacotamento do giroscópio/fp16/aceleração, flags/WHO_AM_I, mapeamento do bloco de diagnóstico de 24 palavras, limites, região 0–9 somente leitura, marcador 84 e 240=0xA5 |
| Tests/imu_test.c | **16 cenários aprovados** | WHO_AM_I incorreto, falha ao ler configuração de volta, FIFO/SFLP, limites de fp16 (sentinela de zero negativo), dados congelados marcados como stale, recuperação automática, expiração de snapshot sem polling |
| Tests/probe_test.py | **9/9 aprovados** | Construção de quadros de sondagem, decodificação dos blocos 56/40 e 90/96, nomes dos 24 campos de diagnóstico, tratamento de orientação inválida |

## 3. Teste de comunicação no equipamento

Ambiente: adaptador half-duplex COM6 (1 Mbps); IMU ID=200; servos Feetech IDs 2 e 3 (firmware 3.46, 8,0 V).

| Ferramenta / cenário | Resultado |
|---|---|
| imu_probe.py, polling unicast (blocos de diagnóstico 56/40 + 90/96) | **249/250** (um timeout momentâneo, 0,4%); código de saída 0 |
| imu_probe.py --sync (SYNC READ broadcast para um único ID) | Normal; todos os ready=1 |
| imu_monitor.py, SYNC READ a 50 Hz de 56/12 (lista [200]) | **251/251, sem erro de checksum ou timeout** |
| bus_monitor.py --no-demo (um SYNC READ para [2,3,200]) | **598/598 = 100%** |
| bus_monitor.py demo (SYNC READ + SYNC WRITE broadcast da posição-alvo) | **741/741 = 100%, sem fallback para gravação individual** |
| servo_tool.py scan/read/test/write | Reconhece corretamente os servos e o ID 200 (model=0x4D44, fw=1) |
| Desligamento automático do torque ao sair | Normal (o servo habilitado pelo demo recebeu a escrita 40=0) |

## 4. Teste da posição no SYNC READ (conclusão importante)

30 rodadas com várias ordens de IDs (servos Feetech, firmware 3.46, 1 Mbps):

| Lista SYNC READ | Respostas da IMU | Conclusão |
|---|---:|---|
| [200,2,3] (IMU primeiro) | **3/30** | O servo prevê o envio 180 µs após o início do quadro anterior e colide com o byte de checksum da IMU |
| [2,200,3] (IMU no meio) | 30/30 | Responde após detectar um quadro válido do ID 2 |
| [2,3,200] (IMU no fim) | 30/30 | Responde após detectar um quadro válido do ID 3 |
| [200] (sozinha) | 30/30 | Sem colisão |

Regra consolidada: **o host deve colocar o ID 200 depois dos servos ou consultá-lo em um grupo separado; nunca deve colocá-lo primeiro.**
Em um ciclo de 50 Hz (20 ms), os três dispositivos ocupam aproximadamente 650 µs do barramento (requisição de cerca de 110 µs + cerca de 180 µs por resposta), com margem de 3,3%. O gargalo é a colisão elétrica, não o orçamento de tempo.

## 5. Observações da placa

- Banner de inicialização: imu_to_dxl 1.0.0 | STM32G031F8 | FT-SCS ID=200 1000000 8N1. A linha periódica de estado mostra ready=1 id=0x70 ... ck=0; os valores do giroscópio/quaternion mudam ao girar a placa com a mão.
- Os logs CDC do DAP-Link (COM5, 115200) só aparecem quando DTR e RTS estão altos.
- Durante a execução prolongada estável, os contadores de diagnóstico SPI/FIFO/UART/checksum não aumentaram (consulte o bloco de diagnóstico 90–185).

## 6. Limites dos testes

Os testes C no computador usam registradores e relógio simulados; não equivalem a medições do chip. Os testes de comunicação no equipamento cobriram a posição no barramento compartilhado, leitura/escrita e operação conjunta com o demo, mas não cobriram execução contínua por horas, temperaturas/tensões extremas, integração da pose sob carga do robô completo, nem desvios e variação térmica do SFLP. Antes da integração com movimento real, ainda é necessário concluir a validação da seção 5 das instruções de uso; o controlador principal também deve parar com segurança conforme os campos ready, contagem de amostras e idade dos dados.
