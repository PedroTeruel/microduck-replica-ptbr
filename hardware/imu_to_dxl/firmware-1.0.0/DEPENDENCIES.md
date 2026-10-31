# Dependências do firmware e ferramentas de compilação

O projeto mantém no próprio diretório o código-fonte dos drivers do microcontrolador e do sensor necessários à compilação. No uso diário, não é necessário baixar novamente STM32CubeMX, HAL nem drivers pela internet.

| Componente | Origem fixada | Licença e alterações locais |
|---|---|---|
| CMSIS Core 6.2.0 | Instalação local em `C:\Keil_v5\ARM\PACK\ARM\CMSIS\6.2.0`, correspondente a [ARM-software/CMSIS_6 v6.2.0](https://github.com/ARM-software/CMSIS_6/tree/v6.2.0) | Apache-2.0; foram copiados somente os cabeçalhos necessários ao Cortex-M0+ e ao Arm Compiler 6, sem alterações. Licença em `Drivers/CMSIS/LICENSE`. |
| STM32G0 CMSIS Device v1.4.5 | [STMicroelectronics/cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0/tree/f576c24e123edf3332988ecd49512c0f35f85186), commit `f576c24e123edf3332988ecd49512c0f35f85186`, de 05/03/2026 | Apache-2.0; o cabeçalho do dispositivo e o arquivo de sistema não foram alterados. Licença em `Drivers/CMSIS/Device/ST/STM32G0xx/LICENSE.md`. |
| Código de inicialização do STM32G031 | `Source/Templates/arm/startup_stm32g031xx.s`, no mesmo commit da ST | A pilha foi ampliada de 1024 para 2048 bytes e o heap reduzido de 512 para 0 bytes, pois não há alocação dinâmica. A tabela de vetores, `Reset_Handler` e os nomes fracos de IRQ mantêm a implementação ST. |
| Driver PID do LSM6DSV16X | [STMicroelectronics/lsm6dsv16x-pid](https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07), commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07` | ST BSD-3-Clause; licença em `Drivers/LSM6DSV16X/LICENSE`. O código original do driver e o registro de origem ficam nesse diretório. |
| Pacote de suporte a dispositivos Keil | `Keil.STM32G0xx_DFP.2.1.0` da instalação local | Fornece descrições dos dispositivos, SVD e algoritmo de gravação `CMSIS/Flash/STM32G0xx_64.FLM`. Essa versão não inclui mais Device:Startup/HAL; o projeto mantém os arquivos oficiais CMSIS de inicialização para evitar duplicação ao adicionar RTE. |
| Arm Compiler for Embedded 6.24 | `C:\Keil_v5\ARM\ARMCLANG` | Licença local `Keil MDK STMicroelectronics Edition - Cortex-M0/M0+/M23`. O projeto usa Arm Compiler 6, sintaxe antiga do armasm e MicroLIB. Somente o aviso de descontinuação A1950W do assembler antigo é ocultado; os avisos de código permanecem habilitados. |

## Compilar

Abra o diretório do firmware e execute no PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 `
  -ToolchainRoot 'C:\Keil_v5\ARM\ARMCLANG'
```

Como alternativa, pressione `Ctrl+Shift+B` no VS Code. Se as ferramentas estiverem instaladas em outro local, informe `-ToolchainRoot '<diretório de instalação>\ARMCLANG'`.

No Keil, abra diretamente `MDK-ARM/imu_to_dxl_dap.uvprojx` (o repositório mantém somente esse projeto DAP). A compilação gera `Build/imu_to_dxl.axf`, `.hex`, `.bin` e `.map`. Ambas as formas usam Cortex-M0+, C11, `-Oz`, ponto flutuante por software, enumerações curtas, MicroLIB, `STM32G031xx` e `HSE_VALUE=16000000`. O script também gera um registro detalhado e a lista de hashes SHA-256 dos artefatos em `Build/imu_to_dxl.build.json`.

O arquivo de link limita a Flash a `0x08000000..0x0800FFFF` e a RAM de dados a `0x20000000..0x200017FF`; os 2 KiB finais, `0x20001800..0x20001FFF`, são reservados para a pilha, cujo SP inicial é `0x20002000`. Se o tamanho da pilha mudar, atualize também o arquivo de inicialização e o arquivo scatter.

O projeto Keil configura CMSIS-DAP (DAP-Link), SWD e o algoritmo de Flash de 64 KiB do STM32G0. **Para gravar pela linha de comando, use OpenOCD** (`interface/cmsis-dap.cfg` + `target/stm32g0x.cfg`, 4 MHz): a linha de comando do UV4 apresenta um falso sucesso, retornando código 0 sem apagar ou gravar de fato. A gravação na placa e a comunicação no barramento compartilhado foram validadas; consulte `VALIDATION.md`.

Os testes no computador, sem hardware, compilam os casos em C com gcc (`mingw64` do WinLibs; a instalação pode estar em qualquer diretório, MinGW-w64). As ferramentas de host exigem Python 3.8 ou posterior e pyserial; os gráficos também requerem matplotlib. Consulte a lista em `Tools/requirements.txt`.

Quando o sandbox local do Codex usa uma identidade de usuário diferente, a verificação da licença Arm pode informar “assigned to another user”. Sob a identidade do usuário real, a verificação da licença é aprovada. Essa diferença não exige que um usuário comum altere uma licença já ativada e não envolve burlar ou substituir as ferramentas.

## Integridade dos arquivos

`Drivers/CMSIS/dependency-hashes.json` registra os hashes SHA-256 atuais dos arquivos CMSIS, do código de inicialização e do driver do sensor incluídos. Use-o para identificar alterações em futuras atualizações. Os metadados dos commits de origem da ST estão em `Drivers/CMSIS/Device/ST/STM32G0xx/source-commit.json`.
