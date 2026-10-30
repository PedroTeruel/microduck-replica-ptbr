# Firmware 1.0.0 da imu_to_dxl (FT-SCS)

> Esta versão foi derivada da 0.1.0 (Dynamixel 2.0) e adaptada ao protocolo Feetech. É uma implementação independente da 0.2.0 em [../firmware/](../firmware/): ambas usam bloco de 15 bytes e modelo 0x4D44, mas as regiões de diagnóstico diferem (esta versão: 90..185; versão 0.2.0: 124..247). Para uso no Microduck, o programa principal deve ser do fork a partir do commit 4734cbb (ou da imagem de réplica a partir de 20261021b), que coloca esta placa depois dos servos na leitura. Consulte [../README.md](../README.md) para escolher a versão.

Firmware da placa IMU **STM32G031F8P6 + LSM6DSV16X** para o Microduck. Base de hardware: `fanhao375/microduck-replica` @ `a1f4979c` (inclui J4/J5 e RX_EN).

O firmware usa o **protocolo Feetech FT-SCS**, migrado do Dynamixel 2.0. A placa IMU tem **ID=200, 1 Mbps, 8N1** e compartilha o mesmo barramento half-duplex de fio único com os servos Feetech SCS/STS. Uma única SYNC READ lê a IMU e todos os servos.
O conteúdo segue o contrato `duck-control` do GitHub `pollen-robotics/microduck` (giroscópio i16×3 + quaternion SFLP fp16 x/y/z; o controlador reconstrói w; 50 Hz).

Fluxo de dados: LSM6DSV16X → SPI1 → STM32 → USART2 + buffer externo → barramento half-duplex de fio único → controlador principal.
Execução bare-metal, sem RTOS, memória dinâmica ou HAL; ID e baud rate fixos; não grava Option Bytes nem configuração Flash.

## Início rápido

```powershell
# 1) Compilar o firmware (equivalente a Ctrl+Shift+B)
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'

# 2) Gravar (use obrigatoriamente OpenOCD; a linha de comando UV4 pode indicar sucesso falso)
& 'openocd.exe' -f interface/cmsis-dap.cfg `   # substitua pelo caminho do OpenOCD no seu computador
  -f target/stm32g0x.cfg -c 'adapter speed 4000' `
  -c 'program Build/imu_to_dxl.hex verify reset exit'

# 3) Instalar as dependências do computador e usar (COM6 = adaptador do barramento half-duplex)
python -m pip install -r Tools\requirements.txt
python Tools\servo_tool.py scan --port COM6        # varrer IMU (200) + servos
python Tools\bus_monitor.py --port COM6 --no-demo  # monitorar IMU e servos sem movimento
python Tools\imu_monitor.py --port COM6 --plot     # gráfico da IMU a 50 Hz
python Tools\imu_probe.py --port COM6 --seconds 30 # aceitação somente leitura (código de saída 0 = aprovado)
```

**Regra obrigatória do barramento:** na lista de IDs da SYNC READ do controlador, o ID 200 deve vir depois dos servos (último ou penúltimo), nunca deve ser o primeiro. Também pode ser lido em um grupo separado. Consulte a seção 6 de [Instruções de uso](docs/Instruções de uso.md).

## Índice da documentação

| Documento | Conteúdo |
|---|---|
| [docs/Instruções de uso.md](docs/Instruções de uso.md) | Fiação (J1/J2/J4/J5/J3), ambiente, compilação e gravação, uso completo das quatro ferramentas Python, configuração inicial na placa, solução de problemas e testes sem hardware |
| [docs/实现Princípio.md](docs/实现Princípio.md) | Máquina de estados dos quadros FT-SCS e checksum, mapa de registradores/diagnóstico, prevenção de colisões pela posição na SYNC READ, temporização DE half-duplex, orçamento de tempo a 50 Hz, cadeia de amostragem da IMU e contrato do controlador |
| [VALIDATION.md](VALIDATION.md) | Testes no computador e registro de aceitação em hardware real |
| [DEPENDENCIES.md](DEPENDENCIES.md) | Versões e licenças do código de terceiros e da cadeia de ferramentas |

## Estrutura de diretórios

`
Core/Inc, Core/Src   Código-fonte do firmware (board / imu / protocol / control_table / main)
Drivers/             CMSIS em versão fixa e driver ST LSM6DSV16X (inclui licença)
MDK-ARM/             Projeto Keil (somente DAP: imu_to_dxl_dap.uvprojx + script de linkedição)
Tools/               build.ps1, test.ps1 e quatro ferramentas Python
Tests/               Testes C/Python sem hardware (93 de protocol, 18 de control_table, 16 cenários de IMU e 9 de probe)
Build/               Artefatos de compilação (ignorados pelo Git: hex/bin/axf/map)
.vscode/             Tarefas de compilação do VS Code
`

## Resumo dos fatos importantes

- Quadro: `FF FF ID LEN INST P... CK`; `LEN` = número de parâmetros + 2, comprimento total `4+LEN`; checksum `~(ID+LEN+INST+ΣP)&0xFF`.
- Instruções: PING (0x01) / READ (0x02) / WRITE (0x03) / SYNC READ (0x82) / SYNC WRITE (0x83); PING de broadcast é silencioso e não há atraso de resposta.
- Bloco rápido no endereço 56 (igual ao bloco de estado do servo): 56..61 gyro i16×3 (±500 dps, 17,5 mdps/LSB); 62..67 qx/qy/qz fp16; 68..73 aceleração; 75 flags; 76 WHO_AM_I=0x70; 84 `user_marker` legível e gravável; 90..185 bloco de diagnóstico 24×u32; gravar 0xA5 em 240 reinicializa a IMU.
- Amostragem: IMU a 120 Hz (FIFO+SFLP), controlador a 50 Hz. Antes de ficar pronta, gyro/quaternion retornam zero; o controlador deve detectar dados inválidos usando `ready`, contador de amostras e idade da amostra.
- Portas locais: COM6 para o barramento half-duplex a 1 Mbps; COM5 para logs DAP-Link a 115200 (DTR/RTS precisam estar em nível alto).

## Referências

- [Hardware desta placa](https://github.com/fanhao375/microduck-replica/tree/a1f4979c425bd9228622be89f2bfa4d1de7fbde3/hardware/imu_to_dxl)
- [Manual de dados STM32G031](https://www.st.com/resource/en/datasheet/stm32g031f8.pdf)
- [Manual de dados LSM6DSV16X](https://www.st.com/resource/en/datasheet/lsm6dsv16x.pdf)
- [Interface duck-control do controlador upstream](https://github.com/pollen-robotics/microduck/blob/5984efb770855432b03dafd3d879e9929981e45b/duck-control/src/bus.rs)
- [Protocolo Feetech FT-SCS](https://www.feetechrc.com/)

O código novo é fornecido sob a licença MIT; arquivos de terceiros mantêm seus respectivos direitos autorais e licenças (consulte o diretório Drivers).
