# Dependências e ferramentas de construção do firmware

O código-fonte dos drivers do microcontrolador e do sensor necessários à compilação está incluído neste diretório. Os drivers não são baixados pela internet durante a construção. Keil, Arm Compiler, o pacote de suporte ao dispositivo e as ferramentas de depuração devem ser instalados legalmente por quem utiliza o projeto. Os arquivos temporários ficam no diretório `Build` do projeto.

| Componente | Fonte fixada | Licença e alterações locais |
|---|---|---|
| CMSIS Core 6.2.0 | [ARM-software/CMSIS_6 v6.2.0](https://github.com/ARM-software/CMSIS_6/tree/v6.2.0) | Apache-2.0. Inclui somente os cabeçalhos necessários ao Cortex-M0+ e ao Arm Compiler 6, sem modificações. Licença: `Drivers/CMSIS/LICENSE`. |
| STM32G0 CMSIS Device v1.4.5 | [STMicroelectronics/cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0/tree/f576c24e123edf3332988ecd49512c0f35f85186), commit `f576c24e123edf3332988ecd49512c0f35f85186` | Apache-2.0. Os cabeçalhos do dispositivo e o arquivo-fonte do sistema não foram modificados. Licença: `Drivers/CMSIS/Device/ST/STM32G0xx/LICENSE.md`. |
| Código de inicialização STM32G031 | `Source/Templates/arm/startup_stm32g031xx.s` do mesmo commit da ST | A pilha foi ampliada de 1024 para 2048 bytes; o heap passou de 512 para 0 bytes. A tabela de vetores, `Reset_Handler` e os nomes fracos de IRQ continuam iguais aos da ST. |
| Driver PID LSM6DSV16X | [STMicroelectronics/lsm6dsv16x-pid](https://github.com/STMicroelectronics/lsm6dsv16x-pid/tree/2808e5cd6b85f91b66758e1dd0faab5f043aba07), commit `2808e5cd6b85f91b66758e1dd0faab5f043aba07` | ST BSD-3-Clause. A licença, o driver original e o registro da fonte estão em `Drivers/LSM6DSV16X/`. |
| Pacote de suporte a dispositivos Keil | Versão verificada `Keil.STM32G0xx_DFP.2.1.0` | Fornece a descrição do dispositivo, SVD e `CMSIS/Flash/STM32G0xx_64.FLM`. O projeto também inclui os arquivos oficiais CMSIS de inicialização, para evitar que o RTE os adicione duas vezes. |
| Arm Compiler for Embedded | Versão verificada 6.24 (0.1.0) e 6.22 (0.2.0, Keil MDK 5.41); CMSIS 6 requer 6.10 ou superior | Requer licença válida da ferramenta. Usa Arm Compiler 6, sintaxe antiga de armasm e MicroLIB; somente o aviso de depreciação do assembler antigo A1950W é ocultado. |

## Como construir

Edite o código no VS Code e execute o comando abaixo em um terminal PowerShell no diretório do firmware:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Tools\build.ps1 -ToolchainRoot 'E:\Keil_v5\ARM\ARMCLANG'
```

Substitua o caminho de exemplo pelo diretório de instalação do Arm Compiler no seu computador. O repositório não inclui configuração de tarefas do VS Code.
A compilação substitui o firmware em `Build`. Se você só usa a página web de orientação, mantenha o `Build/imu_to_dxl.hex` fornecido com o projeto; não é necessário recompilar.
O repositório mantém apenas esse HEX pré-compilado. `.bin`, `.map`, `.axf`, registros de compilação e resultados de teste ficam localmente e são ignorados pelo `.gitignore`.

No Keil, abra `MDK-ARM/imu_to_dxl_jlink.uvprojx` (J-Link) ou `imu_to_dxl.uvprojx` (ST-LINK). Na primeira utilização, confira o compilador, o pacote do dispositivo, a sonda e o algoritmo de gravação instalados no seu computador. O script J-Link configura a velocidade SWD verificada de 100 kHz. A construção gera `.axf/.hex/.bin/.map`; o script de linha de comando também gera o registro da compilação e a lista de hashes SHA-256 dos artefatos.

Ambas as formas de construção usam Cortex-M0+, C11, `-Oz`, ponto flutuante por software, enums curtos, MicroLIB, `STM32G031xx` e `HSE_VALUE=16000000`.
Mapa de memória do linker: Flash `0x08000000..0x0800FFFF`; RAM de dados `0x20000000..0x200017FF`; os últimos 2 KiB (`0x20001800..0x20001FFF`) são usados pela pilha; SP inicial `0x20002000`. Se alterar o tamanho da pilha, altere também o arquivo de inicialização e o arquivo scatter.

O observador SWD/J-Link em `tools/servo-web` decodifica 10.724 bytes da imagem HEX (versão 0.2.0) e usa o SHA-256
`66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e`
para confirmar as posições verificadas de `sample=0x2000006C` (60 bytes) e `tick=0x20000A34` (4 bytes), sem depender de um MAP commitado no repositório.
Após recompilar, confira os símbolos e seus tamanhos no MAP local e aprove o novo hash da imagem antes de atualizar o observador.

## Testes no computador e integridade dos arquivos

Os testes C no computador requerem MSVC. Primeiro, abra **x64 Native Tools Command Prompt** ou **Developer PowerShell**; depois, execute `Tools/test.ps1 -PythonExe 'caminho-do-seu-Python'`. A entrada de testes não instala programas nem conecta ao hardware.

`Drivers/CMSIS/dependency-hashes.json` registra o SHA-256 dos arquivos de drivers incluídos. Os metadados do commit ST estão em `Drivers/CMSIS/Device/ST/STM32G0xx/source-commit.json`. O escopo da construção e da validação na placa física está em [VALIDATION.md](VALIDATION.md).
