# Documentação de servos Feetech e SDK

[Voltar à navegação das ferramentas](../../tools/README.md) · [Manuais eletrônicos oficiais da Feetech](http://doc.feetech.cn/#/prodinfodownload?srcType=FTServo-emanual-ab4947a479784a71a8cb7928)

## Documentação oficial atual

Em 25/10/2026, conferimos o índice oficial e as interfaces dos documentos no site da Feetech. As datas de atualização da tabela vêm do campo oficial lastModifiedDate e não correspondem necessariamente à data impressa na capa.

| Documento | Versão indicada no site oficial | Última atualização no site (UTC+8) |
|---|---|---|
| [Protocolo de comunicação SCS](http://doc.feetech.cn/#/f?q=2506ba160b93) | 1.0 | 2026-10-08 |
| [Tabela de memória STS](http://doc.feetech.cn/#/f?q=2506abfb1cb0) | 1.1 | 2026-10-08 |
| [Tabela de memória SMS](http://doc.feetech.cn/#/f?q=2602a06ca658) | 1.1 | 2026-10-08 |
| [Software de depuração FD e ferramentas seriais](https://gitee.com/ftservo/fddebug) | Conforme as publicações do repositório oficial | [Download e instruções neste repositório](../../tools/飞特/README.md) |
| [Ficha técnica HD-1910-C001](../../tools/FeeTech_HD1910M_Servo/HD-1910-C001串型规格书20260907.pdf) | Arquivo marcado como 2026-09-07 | Já há uma ficha deste modelo neste repositório |

## Cópias offline (captura de 17/09/2026)

Abaixo estão cópias dos manuais eletrônicos salvas em 17/09/2026 para busca e comparação com a [arquitetura de integração Feetech](../../software/飞特适配架构.md). **O site oficial recebeu alterações posteriores; as cópias offline mantêm a data original. Use o conteúdo atual do site como referência.**

| Arquivo | Versão | Data de atualização no site oficial | Finalidade |
|---|---|---|---|
| [Protocolo de comunicação SCS v1.0 — 09/06/2026](SCS通信协议-v1.0-2026-06-09.md) | v1.0 | 2026-06-09 | Formato dos pacotes e tabela de comandos. **Esta versão inclui reinicialização 0x08, backup de parâmetros 0x09 e redefinição de estado 0x0A**, ausentes na versão de 2019 |
| [Tabela de memória dos servos STS com encoder magnético v1.1 — 27/08/2026](磁编码STS内存表手册-v1.1-2026-08-27.md) | v1.1 | 2026-08-27 | Tabela de memória da série STS, que inclui o HD-1910: divisões EEPROM/SRAM, valores de fábrica, significado do bloqueio e definição dos bits de estado |
| [Tabela de memória dos servos SMS com encoder magnético v1.1 — 27/08/2026](磁编码SMS内存表手册-v1.1-2026-08-27.md) | v1.1 | 2026-08-27 | Equivalente para a versão SMS (RS485). Diferenças em relação ao STS: endereço 7 é o atraso de resposta (reservado no STS); modo de operação 33 aceita 0–2; chave de torque 40 não tem o valor de amortecimento 2; endereço 83 é Hts; e o significado do BIT5 de fase difere |
| Planilha oficial de geração de comandos hexadecimais SMS/STS/HTS | 250508 | 2025-05-08 | Planilha oficial que monta quadros de comando hexadecimais a partir dos parâmetros, prontos para envio por um terminal serial; inclui exemplos de desbloqueio, alteração de ID, limpeza das voltas acumuladas e calibração do ponto central |

As diferenças específicas do HD-1910-C001 em relação ao modelo personalizado (modo de fábrica 4, torque e relação de redução) estão na [lista de dados necessária antes do treinamento do HD-1910](../HD-1910训练前数据清单.md). A ficha técnica do modelo aparece na tabela acima.

## SDKs oficiais

| Ambiente de desenvolvimento | Código-fonte oficial |
|---|---|
| Python | [FTServo_Python](https://gitee.com/ftservo/FTServo_Python) |
| Linux / C++ | [FTServo_Linux](https://gitee.com/ftservo/FTServo_Linux) |
| Arduino | [FTServo_Arduino](https://gitee.com/ftservo/FTServo_Arduino) |
| STM32 HAL | [FTServo_stm32HAL](https://gitee.com/ftservo/FTServo_stm32HAL) |

## Como conferir versões

Como obter os dados (interface do site de documentação, para a próxima atualização):

- Índice: http://longbos.com:9009/workflow/yf-specification/getBysrcType/FTServo-emanual-ab4947a479784a71a8cb7928
- Conteúdo: http://longbos.com:9009/workflow/yf-specification/getQr/<q>; o valor de q vem do link #/f?q=… no índice.
- Tabela de memória STS: 2506abfb1cb0 · tabela SMS: 2602a06ca658 · protocolo SCS: 2506ba160b93.
- A resposta é JSON. data.mdcontent contém o Markdown do documento; data.lastModifiedDate contém a data de atualização.
