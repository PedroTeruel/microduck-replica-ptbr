# Índice de ferramentas

[Voltar ao início](../README.md#资料导航) · [Documentação completa](../docs/README.md) · [English](README.en.md)

Para configurar a rede, calibrar e controlar o robô no dia a dia, use o [Studio](../software/studio/README.md). Este índice reúne as ferramentas para gravar o cartão, depurar a comunicação serial, consultar materiais Feetech e analisar o desenvolvimento.

## 1. Gravação e ferramentas para Windows

| Tarefa | Download ou acesso | Instruções |
|---|---|---|
| Gravar a imagem do robô | **[Rufus 4.15 portátil, EXE](rufus/rufus-4.15p.exe)** · [Como usar](rufus/README.md) | Windows x64, sem instalação. Também estão incluídos o código-fonte original, a licença e os hashes de verificação. |
| Configurar servos Feetech | **[Arquivo compactado FD 1.9.8.5](飞特/FD1.9.8.5%28250729%29.7z)** · [Instruções](飞特/README.md) | Descompacte e execute o FD para configurar os IDs e parâmetros e consultar o estado dos servos. |
| Enviar e receber dados seriais brutos | [UartAssist.zip do repositório oficial Feetech](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | Assistente serial genérico. Envie dados de acordo com o protocolo do dispositivo. |
| Resolver falhas de identificação do adaptador serial | [Drivers CH343 / CH340](飞特/README.md#驱动与串口助手) | Primeiro, confirme o modelo do chip do adaptador no Gerenciador de Dispositivos. |

### Escolha dos parâmetros da porta serial

| Situação | Configuração comum | Procedimento |
|---|---|---|
| Acesso ao computador de placa única pela porta serial USB | 115200, 8N1 | [Instruções de conexão à placa](radxa/镜像使用说明.md); usado para o terminal do sistema. |
| Barramento de servos Feetech configurado por este projeto | 1000000, 8N1 | [Instruções de depuração dos servos](飞特/README.md); alimente os servos separadamente e use o adaptador TTL correspondente. |

8N1 significa oito bits de dados, sem paridade e um bit de parada. Se a taxa de transmissão do dispositivo tiver sido alterada, use o valor configurado nele.

## 2. Materiais oficiais Feetech e SDKs

**[Índice de materiais Feetech](../docs/飞特资料/README.md):** acesso centralizado aos manuais atuais do site oficial, cópias offline do repositório, folhas de dados dos modelos e SDKs.

- **Protocolos e tabelas de memória:** [protocolo SCS](http://doc.feetech.cn/#/f?q=2506ba160b93) · [tabela de memória STS](http://doc.feetech.cn/#/f?q=2506abfb1cb0) · [tabela de memória SMS](http://doc.feetech.cn/#/f?q=2602a06ca658). A versão do site oficial foi conferida em 2026-10-25; a data de cada cópia offline está indicada separadamente.
- **SDKs oficiais:** [Python](https://gitee.com/ftservo/FTServo_Python) · [Linux](https://gitee.com/ftservo/FTServo_Linux) · [Arduino](https://gitee.com/ftservo/FTServo_Arduino) · [STM32 HAL](https://gitee.com/ftservo/FTServo_stm32HAL).

## 3. Ferramentas de depuração deste repositório

| Ferramenta | Localização | Uso |
|---|---|---|
| Bancada web para servos | [tools/servo-web/](servo-web/README.md) | Depuração serial, consulta do estado, orientação e sequências, visualização 3D e modo de simulação. |
| Testador HD1910M | [tools/FeeTech_HD1910M_Servo/](FeeTech_HD1910M_Servo/README.md) | Ferramenta de linha de comando em Rust para varredura, leitura e configuração de registradores e monitoramento. Use a tabela de memória deste modelo. |
| Testador STS3215 | [tools/sts3215Servo_testtool/](sts3215Servo_testtool/README.md) | Ferramenta de linha de comando em Rust para varredura, leitura do estado e testes individuais ou em lote. Destinada ao STS3215. |
| Verificação do protocolo da IMU de barramento | [tools/imu200/](imu200/) | [`imu200.py`](imu200/imu200.py) oferece simulação, vetores de teste e verificação na placa física. Voltada ao bloco Feetech de 15 bytes no endereço 56; veja o [protocolo do barramento](../hardware/imu_to_dxl/总线协议.md). |

## 4. Registros e análise

| Ferramenta | Localização | Uso |
|---|---|---|
| Análise de marcha | [tools/gait-analysis/](gait-analysis/README.md) | Análise, no computador, de erros de acompanhamento, oscilação e movimento dos pés em registros JSONL. |
| Coleta e análise na placa principal | [tools/radxa/onboard-analysis/](radxa/onboard-analysis/README.md) | Coleta dados de juntas, IMU, comandos e outros registros para depuração no robô físico. |
| Análise de contatos de peças dobradas | [tools/fold_contact/](fold_contact/README.md) | Análise geométrica de contato entre peças na simulação upstream, como referência para estudos de calibração. |
| Desenhos de montagem e análise de furos | [scripts/](../scripts/) | Gera desenhos de montagem, exporta malhas de análise e examina furos. Consulte as [instruções para reproduzir a análise](../docs/项目研究归档.md#重现). |

## 5. Scripts antigos de gravação da imagem

[tools/radxa/](radxa/README.md) contém scripts antigos para gravar o cartão, configurar a inicialização e depurar a rede. O processo atual de construção da imagem completa está em [software/image/](../software/image/README.md). Para gravar o cartão pela primeira vez, consulte o [guia de uso](../docs/上手指南/README.md).
