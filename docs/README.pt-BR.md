# Índice da documentação

[Voltar ao início](../README.md) · [Versão original em chinês](README.md) · [English](README.en.md)

Encontre os materiais por tarefa. Para montar o robô pela primeira vez, comece pelo guia de uso e montagem; análises antigas ficam no arquivo histórico.

## Uso e montagem

| Material | Conteúdo |
|---|---|
| [Guia de primeiro uso](上手指南/README.md) | Gravação da imagem, rede, calibração, controle e guia em PDF |
| [CAD e peças para impressão](https://github.com/fanhao375/microduck-replica-cad) | Modelos e projetos para Feetech HD-1910 / XL330 |
| [Lista de materiais (BOM)](../BOM/README.md) | Prévia online e planilha da versão Feetech de 2026-10-23 |
| [Vídeos de montagem](../README.md#-Vídeos de montagem) | Vídeos do Bilibili organizados por componente |

## Software e treinamento

| Material | Conteúdo |
|---|---|
| [Painel web Studio](../software/studio/README.md) | Calibração, controle remoto, estado do dispositivo e modelos |
| [Construção e publicação da imagem](../software/image/README.md) | Como construir a imagem e notas de publicação |
| [Atualização de software e voz local](软件更新与语音使用说明-20261027.md) | Inicialização de cartões antigos, atualização / reversão assinada e comandos R3 |
| [Plataforma de treinamento](../software/training-studio/README.md) | Experimentos web, avaliação e exportação de modelos |
| [Projeto de treinamento](../software/training/README.md) | Ambiente e comandos de treinamento |
| [Lista de dados antes do treinamento](HD-1910训练前数据清单.md) | Geometria, servos, IMU e itens de medição |
| [Fontes do software e nossas alterações](软件来源与我们的改动.md) | Fontes upstream e modificações deste projeto |
| [Acompanhamento das atualizações oficiais](官方更新跟踪.md) | Versões oficiais, branches de desenvolvimento, PRs pendentes, câmera, ações de expressão e recomendações de adaptação |

## Ferramentas

[Índice de ferramentas](../tools/README.md): downloads e instruções para gravação de cartões, depuração serial, consulta de materiais e análise.

- [Rufus portátil e gravação de cartão](../tools/rufus/README.md) · [Drivers Feetech FD e assistente serial](../tools/飞特/README.md) · [Manuais oficiais Feetech e SDK](飞特资料/README.md)
- [Bancada web de depuração de servos](../tools/servo-web/README.md) · [Ferramenta de teste HD1910M](../tools/FeeTech_HD1910M_Servo/README.md) · [Ferramenta de teste STS3215](../tools/sts3215Servo_testtool/README.md)
- [Verificação do protocolo da IMU](../tools/imu200/imu200.py) · [Análise da marcha](../tools/gait-analysis/README.md) · [Scripts de análise da placa principal](../tools/radxa/onboard-analysis/README.md)

## Eletrônica e diagnóstico

| Material | Conteúdo |
|---|---|
| [Projetos de hardware](../hardware/README.md) · [Firmware da IMU](../hardware/imu_to_dxl/README.md) | Arquivos de projeto, conexões e escopo da validação do firmware |
| [Introdução ao hardware](硬件入门.md) · [Consulta rápida de especificações](硬件规格速查.md) | Funções e parâmetros dos módulos |
| [Problemas encontrados](../踩坑记录.md) | Sintomas, causas e soluções |
| [Registros de depuração](../调试记录.md) · [Diário de construção](../构建日志.md) | Testes no robô e montagem mecânica |

## Pesquisa e arquivo

Registros antigos de análise e compra preservam as datas, propostas e escopo de validação. Para montar, consulte primeiro os guias atuais e a BOM.

| Material | Conteúdo |
|---|---|
| [Histórico de atualizações](历史更新.md) | Registros diários de atualização reunidos fora da página inicial |
| [Contribuições da comunidade e projetos de outros donos](社区贡献.md) | Créditos dos contribuidores, histórico de integração e projetos da comunidade |
| [Arquivo de pesquisa do projeto](项目研究归档.md) | Vistas explodidas, estrutura de montagem, parâmetros das juntas, viabilidade inicial e comandos de reprodução |
| [Reconstrução da solução de hardware](硬件方案逆向.md) | Derivações eletrônicas e fontes das evidências |
| [Seleção de atuadores](执行器选型.md) · [Reconstrução dos fixadores](紧固件反推.md) | Comparação de servos e análise dos furos |
| [Análise de compras eletrônicas](电控采购清单.md) · [Análise de compras mecânicas](机械采购清单.md) | Seleções, compras e custos registrados anteriormente |
| [Solução sem HAT](不打HAT.md) | Alternativa e instruções de conexão |
| [Navegação do ecossistema](生态导航.md) · [Atualizações da comunidade](社区动态.md) | Recursos upstream, modelos e informações da comunidade |

Consulte também as [licenças e atribuições](../NOTICE.md) e os [termos de uso dos modelos](../software/image/overlay/usr/share/doc/microduck/模型说明.txt). Os arquivos originais e seus créditos permanecem no repositório.

> Tradução mantida no fork [PedroTeruel/microduck-replica-ptbr](https://github.com/PedroTeruel/microduck-replica-ptbr). A documentação usa CC BY-NC-SA 4.0, exceto pastas com licença própria.
