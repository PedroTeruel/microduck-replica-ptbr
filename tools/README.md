# Índice de ferramentas

[Voltar ao início](../README.md#资料导航) · [Documentação completa](../docs/README.md) · [English](README.en.md)

日常配网、标定e遥控使用 [Studio](../software/studio/README.md)。aqui按烧卡、串口Depuração、飞特资料e开发分析整理Ferramentas。

## 1. 烧卡 e  Windows Ferramentas

| 要做什么 | Baixar或入口 | Instruções |
|---|---|---|
| Gravação鸭子Imagem | **[Rufus 4.15 便携版 EXE](rufus/rufus-4.15p.exe)** · [使用步骤](rufus/README.md) | Windows x64，免Instalação；另附原版源码、Licença e 校验值 |
| Depuração飞特Servo | **[FD 1.9.8.5 压缩包](飞特/FD1.9.8.5%28250729%29.7z)** · [Instruções de uso](飞特/README.md) | 解压后Execução FD，Configuração ID、Parâmetros并读回状态 |
| 收发原始串口数据 | [飞特官方仓库的 UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | 通用串口助手；需按设备协议发送数据 |
| 串口转接板识别异常 | [CH343 / CH340 驱动入口](飞特/README.md#驱动 e 串口助手) | 先在设备管理器确认转接芯片型号 |

### 串口Parâmetros怎么选

| 场景 | 常用设置 | Procedimento |
|---|---|---|
| Placa principal USB 串口登录 | 115200，8N1 | [Placa principalConexãoInstruções](radxa/ImagemInstruções de uso.md)；usado para系统终端 |
| este projeto已Configuração de 飞特Servo总线 | 1000000，8N1 | [ServoDepuraçãoInstruções](飞特/README.md)；Servo另行供电，使用对应 TTL 转接板 |

8N1 指 8 个Dados位、无校验、1 个停止位；若设备改过波特率，以实际Configuração为准。

## 2. 飞特Oficial资料 e  SDK

**[飞特资料索引](../docs/飞特资料/README.md)**：官网现行手册、仓库离线副本、型号规格书e SDK  de 统一入口。

- 协议与内存表：[SCS 通信协议](http://doc.feetech.cn/#/f?q=2506ba160b93) · [STS 内存表](http://doc.feetech.cn/#/f?q=2506abfb1cb0) · [SMS 内存表](http://doc.feetech.cn/#/f?q=2602a06ca658)。官网版本核对日期为 2026-10-25，离线副本日期单独标明。
- 官方 SDK：[Python](https://gitee.com/ftservo/FTServo_Python) · [Linux](https://gitee.com/ftservo/FTServo_Linux) · [Arduino](https://gitee.com/ftservo/FTServo_Arduino) · [STM32 HAL](https://gitee.com/ftservo/FTServo_stm32HAL)。

## 3. 本仓DepuraçãoFerramentas

| Ferramentas | 仓库位置 | 用途 |
|---|---|---|
| WebServoDepuração台 | [tools/servo-web/](servo-web/README.md) | 串口Depuração、读回状态、姿态 e 序列、3D 显示；suporta模拟模式 |
| HD1910M TesteFerramentas | [tools/FeeTech_HD1910M_Servo/](FeeTech_HD1910M_Servo/README.md) | Rust Comando行：扫描、寄存器Leitura e Configuração、监控；按该型号内存表使用 |
| STS3215 TesteFerramentas | [tools/sts3215Servo_testtool/](sts3215Servo_testtool/README.md) | Rust Comando行：扫描、读状态、单颗 e 批量Teste；面向 STS3215 |
| 总线 IMU ProtocoloVerificação | [tools/imu200/](imu200/) | [imu200.py](imu200/imu200.py)：模拟、Teste向量 e 真板Verificação；针对飞特地址 56  de  15 字节块，Protocolo见[总线Instruções](../hardware/imu_to_dxl/总线Protocolo.md) |

## 4. 记录 e 分析

| Ferramentas | 仓库位置 | 用途 |
|---|---|---|
| 步态分析 | [tools/gait-analysis/](gait-analysis/README.md) | 在电脑Superior分析 JSONL 记录 de 跟踪误差、颤动ePé运动 |
| Placa principal采集 e 分析 | [tools/radxa/onboard-analysis/](radxa/onboard-analysis/README.md) | 采集关节、IMU、指令等记录，配合实机Depuração |
| 折叠接触分析 | [tools/fold_contact/](fold_contact/README.md) | conformeupstream仿真几何分析零件接触，作为标定研究参考 |
| 装配图 e 孔位分析脚本 | [scripts/](../scripts/) | 生成装配图、导出分析网格e扫描孔位；[重现步骤](../docs/Arquivo de pesquisa do projeto.md#重现) |

## 5. Histórico做卡脚本

[tools/radxa/](radxa/README.md) Preservado早期做卡、引导 e 联网Depuração脚本。Atual整套Imagem de 构建入口是 [software/image/](../software/image/README.md)，首次烧卡Por favor看[使用指南](../docs/Superior手指南/README.md)。
