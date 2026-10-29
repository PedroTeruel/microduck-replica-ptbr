<a id="microduck-复刻"></a>
# Réplica do Microduck

**Português brasileiro** · [简体中文 no repositório original](https://github.com/fanhao375/microduck-replica/blob/master/README.md) · [English](README.en.md)

> **Tradução pt-BR:** mantida no fork [PedroTeruel/microduck-replica-ptbr](https://github.com/PedroTeruel/microduck-replica-ptbr), a partir de [fanhao375/microduck-replica](https://github.com/fanhao375/microduck-replica), revisão `4d9b19b`. Alteração: tradução da documentação em 2026-10-29. Créditos, imagens e destinos dos links originais foram preservados; os relatos de testes abaixo pertencem ao projeto de origem. Consulte [o escopo, as licenças e o andamento da tradução](TRADUCAO.md). A tradução da documentação completa ainda está em andamento.


Projeto independente de réplica completa do robô [Microduck da Pollen Robotics](https://pollen-robotics.com/microduck/), com materiais para compra de componentes, impressão, montagem, calibração, controle e treinamento.

**A versão com Feetech HD-1910 foi validada no robô físico: ficar em pé, caminhar, dar uma cambalhota para a frente e se levantar novamente.** A configuração principal usa **15 servos Feetech HD-1910**. O projeto fornece uma **imagem de sistema pronta para gravação** e o **painel web Microduck Studio** para configurar a rede, calibrar e controlar o robô pelo navegador do celular ou computador.

**O procedimento de primeiro uso também foi executado no robô físico:** gravar a imagem → configurar a rede pelo ponto de acesso → calibrar servos e IMU → parear o controle e testar a parada de emergência → ficar em pé e caminhar. [Registros de validação no robô físico](docs/Histórico de atualizações.md#最近Atualização)

<a id="鸭子现在 de 样子"></a>
## O robô em ação

**2026-10-24 · Movimentos validados no robô físico:** os dois vídeos abaixo mostram uma cambalhota para a frente seguida da recuperação da postura em pé e uma caminhada sobre a mesa.

<table>
<tr>
<th align="center">Cambalhota e recuperação</th>
<th align="center">Caminhada sobre a mesa</th>
</tr>
<tr>
<td align="center" valign="middle"><a href="assets/demos/2026-10-24-roll-and-rise.mp4"><img src="assets/demos/2026-10-24-roll-and-rise.gif" alt="O robô físico dá uma cambalhota e se levanta" width="260"></a></td>
<td align="center" valign="middle"><a href="assets/demos/2026-10-24-walking.mp4"><img src="assets/demos/2026-10-24-walking.gif" alt="Microduck com Feetech caminhando sobre a mesa" width="400"></a></td>
</tr>
<tr>
<td align="center"><a href="assets/demos/2026-10-24-roll-and-rise.mp4">MP4 completo · cerca de 8 segundos</a></td>
<td align="center"><a href="assets/demos/2026-10-24-walking.mp4">MP4 completo · cerca de 6 segundos</a></td>
</tr>
</table>

Os GIFs são prévias sem som; os arquivos MP4 incluem o vídeo completo e o áudio.

**[Baixar a imagem](https://github.com/fanhao375/microduck-replica/releases/latest)** · **[Guia de primeiro uso (PDF / web)](docs/上手指南/README.md)** · **[CAD e peças para impressão](https://github.com/fanhao375/microduck-replica-cad)** · **[Tutoriais de montagem](#-装配视频教程)** · **[Lista de materiais (BOM)](BOM/README.md)** · **[Projetos de hardware](hardware/README.md)**

---

<a id="Versões compatíveis"></a>
### Versões compatíveis

- **Feetech HD-1910 + Radxa Zero 3W:** use a imagem de sistema e o painel web Studio deste projeto.
- **Dynamixel XL330:** há arquivos CAD e materiais de montagem específicos; é necessário usar software de execução compatível.

[Escolher peças para impressão e lista de compras](#Peças impressas e Lista de compras) · [Comparação detalhada dos servos](docs/执行器选型.md)

---

<a id="Comunidade"></a>
## Comunidade

O grupo no WeChat reúne pessoas trabalhando na réplica para discutir o progresso, problemas encontrados e compra de componentes.

O código abaixo é do **Grupo de Réplica do Microduck 13** (o WeChat desativa a entrada por QR code quando o grupo chega a 200 membros).

<div align="center">
  <img src="assets/wechat-group-13.png" alt="QR code do grupo Microduck 13 no WeChat" width="280">
  <br>
  <sub><b>Grupo Microduck 13 · QR code válido até antes de 2026-11-04</b> (os códigos de grupo do WeChat expiram após 7 dias)<br>
  Se estiver expirado, abra uma <a href="https://github.com/fanhao375/microduck-replica/issues">issue</a> para avisar o mantenedor original e solicitar um novo código</sub>
</div>

---

<a id="-Vídeos de montagem"></a>
## 📺 Vídeos de montagem

**[Série no Bilibili “MicroDuck 从零安装教程” (montagem do zero)](https://space.bilibili.com/312747174/lists/9279084?type=season)** — gravada por **机械行者Robo**, autor dos desenhos CAD e da lista de materiais de montagem. Começa pela lista de peças e monta um subconjunto por episódio. São 8 episódios; até 2026-10-12, 6 haviam sido publicados.

Ao lado da lista de episódios estão as contas do autor, na ordem **Bilibili, Xiaohongshu e Douyin**. Escaneie o código ou clique na imagem para acessá-las.

<table>
<thead>
<tr><th>Episódio</th><th>Conteúdo</th><th nowrap>Duração</th><th>Bilibili</th><th>Xiaohongshu</th><th>Douyin</th></tr>
</thead>
<tbody>
<tr>
<td nowrap><a href="https://www.bilibili.com/video/BV1RoHX68EFV/">Episódio 1</a></td><td width="260"><a href="https://www.bilibili.com/video/BV1RoHX68EFV/">Lista de peças e acessórios</a></td><td nowrap>1:32</td>
<td rowspan="6" align="center" valign="middle" width="210"><a href="https://space.bilibili.com/312747174"><img src="assets/social/bilibili-qr.jpg" alt="Bilibili：机械行者Robo" width="200"></a><br><sub><b>机械行者Robo</b><br>UID 312747174</sub></td>
<td rowspan="6" align="center" valign="middle" width="210"><a href="https://www.xiaohongshu.com/user/profile/5ad950114eacab046016f038"><img src="assets/social/xiaohongshu-qr.jpg" alt="Xiaohongshu：机械行者" width="200"></a><br><sub><b>机械行者</b><br>ID Xiaohongshu 270594280</sub></td>
<td rowspan="6" align="center" valign="middle" width="210"><a href="https://www.douyin.com/user/MS4wLjABAAAArLa_6yE3GE-AoRURoQnIHdbbI7yM-GHhzlgLZ-XbeYE"><img src="assets/social/douyin-qr.jpg" alt="Douyin：机械行者Robo" width="200"></a><br><sub><b>机械行者Robo</b><br>ID Douyin 1852366168</sub></td>
</tr>
<tr><td nowrap><a href="https://www.bilibili.com/video/BV1Xppb6tECr/">Episódio 2</a></td><td><a href="https://www.bilibili.com/video/BV1Xppb6tECr/">Montagem da parte inferior das pernas</a></td><td nowrap>2:21</td></tr>
<tr><td nowrap><a href="https://www.bilibili.com/video/BV1ycpb6yEwB/">Episódio 3</a></td><td><a href="https://www.bilibili.com/video/BV1ycpb6yEwB/">Montagem das coxas</a></td><td nowrap>5:13</td></tr>
<tr><td nowrap><a href="https://www.bilibili.com/video/BV1Kwpg6wE9G/">Episódio 4</a></td><td><a href="https://www.bilibili.com/video/BV1Kwpg6wE9G/">Montagem do tronco</a></td><td nowrap>2:29</td></tr>
<tr><td nowrap><a href="https://www.bilibili.com/video/BV1EEpg6nEkD/">Episódio 5</a></td><td><a href="https://www.bilibili.com/video/BV1EEpg6nEkD/">Montagem do pescoço</a></td><td nowrap>0:40</td></tr>
<tr><td nowrap><a href="https://www.bilibili.com/video/BV1aKpE6hEzj/">Episódio 6</a></td><td><a href="https://www.bilibili.com/video/BV1aKpE6hEzj/">Montagem da cabeça</a></td><td nowrap>5:50</td></tr>
</tbody>
</table>

<a id="Peças impressas e Lista de compras"></a>
### Peças para impressão e lista de compras

Escolha os arquivos de impressão conforme a versão dos servos e depois providencie os componentes correspondentes.

| Material | Versão compatível | Acesso |
|---|---|---|
| **Peças para impressão e CAD** | **Feetech HD-1910** | [Seção Feetech](https://github.com/fanhao375/microduck-replica-cad#飞特-hd-1910-打印资料): projeto de impressão, arquivos CAD e notas de atualização |
| **Peças para impressão e CAD** | **Dynamixel XL330** | [Seção XL330](https://github.com/fanhao375/microduck-replica-cad#dynamixel-xl330-打印资料): arquivos CAD e instruções de impressão específicos |
| **Lista de compras para montagem** | **Feetech HD-1910** | **[Visualizar online](BOM/README.md)** · **[Baixar Excel](BOM/装配BOM-Mecânica行者Robo-2026-10-23-带Compra链接.xlsx)**: organizada por Mecânica行者Robo, versão de 2026-10-23, com quantidades, materiais e links de compra |

As peças de encaixe das duas versões de servos não são intercambiáveis. As versões dos arquivos e as datas de atualização são mantidas nas respectivas seções do repositório CAD. Esta lista de compras segue a configuração Feetech; os servos XL330 e a eletrônica correspondente precisam ser conferidos separadamente.

---

<a id="现在做到哪了"></a>
## Estado atual do projeto

Até **2026-10-25**, **a réplica completa com Feetech, o procedimento de primeiro uso e os movimentos haviam sido validados no robô físico**. As seções abaixo apresentam os resultados e as extensões do projeto. Consulte o [histórico de atualizações](docs/Histórico de atualizações.md) para conhecer o escopo dos testes e o desenvolvimento.

---

<a id="-Software--复刻Imagem e -microduck-studio"></a>
## 💻 Software · Imagem de sistema e Microduck Studio

**2026-10-28 · Atualização de software (sem regravar o cartão SD):** quem já tem a opção de atualização nas configurações deve instalar primeiro o pacote web / voz `2026.10.28`. Após reconectar, sustente o robô e desative o torque dos servos, confirme explicitamente a atualização do programa principal e selecione `Qinmo · Feetech` na página da IMU para verificar a orientação. A atualização automática do programa principal só aceita a base conhecida 20261027; as placas existentes continuam usando detecção automática por padrão. A validação física do Qinmo e da atualização completa desta versão ainda está pendente. Os movimentos sincronizados com música e a conversa livre por voz com IA continuam sem solução. [Pacote e arquivos de instalação inicial](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.28) · [Atualização para usuários existentes](docs/软件更新与Qinmo使用说明-20261028.md) · [Uso do Qinmo pela web](docs/Qinmo-IMU-网页使用.md)

**Imagem da réplica 20261027: atualização de software pela web e comandos locais de voz para sentar e levantar.** A página de configurações permite verificar, baixar ou enviar pacotes assinados, com reversão em caso de falha na instalação. Um toque em R3 ativa ou desativa a escuta de “sentar / levantar”; o modelo de reconhecimento em chinês está incluído e dispensa conta na nuvem. A gravação e reprodução de movimentos pela web, o modo de movimentos espontâneos e o gerenciamento de modelos foram mantidos. Cartões existentes precisam instalar a opção de atualização uma vez por SSH; depois, as atualizações rotineiras dispensam regravação.

Esta versão mantém o programa principal, os modelos de marcha e a detecção automática de IMU no barramento com ID 200 da versão 20261023c. As verificações de software, transações assinadas, navegador e leitura da imagem foram aprovadas. O primeiro uso de um cartão novo, a atualização / reversão de cartões existentes e o reconhecimento de voz em condições reais ainda aguardam validação física. Os movimentos da cabeça e do corpo acompanhando música ainda precisam de correção; a conversa livre por voz com IA não foi integrada. [Imagem e somas de verificação](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) · [Pacote de atualização](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) · [Atualização e comandos de voz](docs/软件更新与语音使用说明-20261027.md) · [Escopo da validação](docs/superpowers/verification/2026-10-27-web-updates.md)

<p align="center"><a href="software/studio/README.md"><img src="assets/studio-overview-20261025-demo.jpg" alt="Demonstração do Microduck Studio com leituras simuladas" width="920"></a><br><sub>Demonstração do Studio com leituras simuladas</sub></p>

**[Baixar a imagem](https://github.com/fanhao375/microduck-replica/releases/latest)** · **[Guia de primeiro uso](docs/上手指南/README.md)** · **[Documentação do Studio](software/studio/README.md)**

A imagem é gratuita e destinada apenas a réplicas pessoais sem fins comerciais; consulte as licenças de cada componente na página da versão. A câmera usa uma fonte de teste por padrão; veja nas notas da versão os limites da validação da câmera física e do sensor ToF.

---

<a id="-Mecânica--一站式打印 e 装配"></a>
## 🔧 Mecânica · Impressão e montagem

**Mecânica行者Robo mantém materiais separados para Feetech HD-1910 e Dynamixel XL330.** Os modelos, projetos de impressão e notas de atualização estão concentrados no repositório CAD. Escolha a versão correspondente aos seus servos.

| O que você precisa | Acesso |
|---|---|
| **Impressão em um só projeto** | **[Bambu MakerWorld (Feetech)](https://makerworld.com.cn/zh/models/2963569-microduck#profileId-3478428)** · [Projeto 3MF para Bambu Studio](https://github.com/fanhao375/microduck-replica-cad#打印) |
| **Modelos e arquivos de impressão** | **[Seção Feetech HD-1910](https://github.com/fanhao375/microduck-replica-cad#飞特-hd-1910-打印资料)** · **[Seção XL330](https://github.com/fanhao375/microduck-replica-cad#dynamixel-xl330-打印资料)** |
| **Tutoriais de montagem** | **[Manual de montagem em PDF](https://github.com/fanhao375/microduck-replica-cad/blob/master/安装说明书/microduck装配安装说明书.pdf)** · **[Vídeos por episódio](#-装配视频教程)**; use as peças estruturais correspondentes à sua versão |
| **Lista de compras** | **[Visualizar BOM online](BOM/README.md)** · **[Baixar Excel](BOM/装配BOM-Mecânica行者Robo-2026-10-23-带Compra链接.xlsx)**: versão Feetech de 2026-10-23; os servos XL330 e sua eletrônica precisam ser conferidos separadamente |

[Repositório CAD e versões publicadas](https://github.com/fanhao375/microduck-replica-cad/releases) · [Diário de construção](构建日志.md)

---

<a id="-Eletrônica--五块Placa de circuito"></a>
## 🔌 Eletrônica · Cinco placas de circuito

Este repositório fornece os projetos da placa IMU de barramento, do hub de servos e da placa de conexão da bateria. A placa principal é a **Radxa ZERO 3W**, acompanhada da **RPI Robot HAT**, disponibilizada como hardware aberto pela Pollen Robotics.

<table>
<tr>
<th>Placa IMU de barramento</th>
<th>Hub de servos</th>
<th>Placa de conexão da bateria</th>
<th>Placa principal Radxa<br>Radxa ZERO 3W</th>
<th>HAT oficial<br>RPI Robot HAT</th>
</tr>
<tr>
<td align="center" valign="middle" width="170"><a href="assets/hw/imu-to-dxl-1v0a-3d.png"><img src="assets/hw/imu-to-dxl-1v0a-3d.png" alt="Prévia 3D da placa IMU de barramento" width="160"></a></td>
<td align="center" valign="middle" width="170"><a href="assets/hw/wire-hub-1v0a-3d.png"><img src="assets/hw/wire-hub-1v0a-3d.png" alt="Prévia 3D do hub de servos" width="160"></a></td>
<td align="center" valign="middle" width="170"><a href="assets/hw/pogo-pin-1v0a-3d.png"><img src="assets/hw/pogo-pin-1v0a-3d.png" alt="Prévia 3D da placa de conexão da bateria" width="160"></a></td>
<td align="center" valign="middle" width="170"><a href="assets/hw/radxa-zero3w-official.webp"><img src="assets/hw/radxa-zero3w-official.webp" alt="Imagem oficial da Radxa ZERO 3W" width="160"></a></td>
<td align="center" valign="middle" width="170"><a href="assets/hw/rpi-robot-hat-official.png"><img src="assets/hw/rpi-robot-hat-official.png" alt="Imagem oficial da RPI Robot HAT da Pollen Robotics" width="160"></a></td>
</tr>
<tr>
<td align="center" valign="top"><a href="assets/hw/imu-to-dxl-1v0a-pcb.png">Prévia da PCB</a><br><a href="hardware/新版/imu_to_dxl_1V0A/">Arquivos do projeto</a></td>
<td align="center" valign="top"><a href="assets/hw/wire-hub-1v0a-pcb.png">Prévia da PCB</a><br><a href="hardware/新版/wire_hub_1V0A/">Arquivos do projeto</a></td>
<td align="center" valign="top"><a href="assets/hw/pogo-pin-1v0a-pcb.png">Prévia da PCB</a><br><a href="hardware/新版/POGO_PIN_1V0A/">Arquivos do projeto</a></td>
<td align="center" valign="top"><a href="https://item.taobao.com/item.htm?id=763812025816">Comprar no Taobao</a><br><a href="https://docs.radxa.com/en/zero/zero3">Documentação oficial</a> · <a href="https://docs.radxa.com/en/zero/zero3/download#hardware-design">Arquivos de projeto</a></td>
<td align="center" valign="top"><a href="https://github.com/pollen-robotics/elec_RPI_Robot_HAT">Projeto KiCad</a><br><a href="https://github.com/pollen-robotics/elec_RPI_Robot_HAT/tree/main/production">Arquivos de fabricação</a></td>
</tr>
</table>

As três primeiras imagens são prévias 3D das placas desenvolvidas pelo projeto; as imagens da Radxa e da HAT vêm de materiais oficiais. Clique para ver as imagens originais; consulte os [créditos das imagens](assets/hw/official-board-images.md). A Radxa fornece esquemas, dimensões 2D e modelos 3D. Os arquivos EasyEDA Pro, modelos STEP e o estado da validação física das três placas estão nas respectivas descrições.

[Todos os projetos de hardware](hardware/README.md) · [Notas sobre as três placas](hardware/新版/README.md) · [Firmware da IMU de barramento](hardware/imu_to_dxl/README.md)

---

<a id="-Algoritmos--飞特Oficial-bam"></a>
## 🧠 Modelagem de atuadores · BAM oficial da Feetech

O [**BAM oficial da Feetech para HD-1910**](https://gitee.com/ftservo/ftservo-bam) fornece modelos dinâmicos dos servos e parâmetros identificados como referência para treinamento em simulação. Este repositório inclui o [projeto de treinamento](software/training/README.md) e a [bancada web de treinamento](software/training-studio/README.md), ambos de código aberto. Consulte as [notas dos parâmetros](docs/HD-1910-M6参数来源.md) para conhecer a configuração dos modelos e as fontes utilizadas.

---

<a id="-Código abertoPlataforma de treinamento--microduck-training-studio"></a>
## 🖥️ Plataforma aberta de treinamento · Microduck Training Studio

O projeto também desenvolveu o **Microduck Training Studio**: pelo navegador do computador, você pode criar experimentos de treinamento, visualizar curvas, pausar e retomar execuções, avaliar checkpoints e exportar modelos ONNX. A plataforma de treinamento e o Studio executado no robô são serviços independentes.

<p align="center"><a href="software/training-studio/README.md"><img src="assets/training-studio-20261025-demo.jpg" alt="Interface do Microduck Training Studio: modelo 3D, controles de treinamento e curvas de demonstração sintéticas" width="920"></a><br><sub>Demonstração da plataforma: prévia do modelo 3D e curvas com dados sintéticos</sub></p>

O fluxo com uma execução curta em GPU real, reprodução da avaliação e exportação de modelos já foi validado. Treinamentos longos e a validação física de políticas treinadas pelo projeto ainda estão pendentes.

**[Plataforma de treinamento e instruções](software/training-studio/README.md)** · **[Guia do laboratório de movimentos](software/training-studio/web/custom-actions.md)** · **[Projeto de treinamento](software/training/README.md)** · [Registro de validação](software/training-studio/docs/verification.md)

---

<a id="-Ferramentas--烧卡Depuração e 资料"></a>
## 🧰 Ferramentas · Gravação, depuração e referências

Os programas e utilitários de desenvolvimento estão organizados no [índice de ferramentas](tools/README.md). Escolha conforme a tarefa.

| Tarefa | Ferramentas e acesso |
|---|---|
| Gravar a imagem | **[Rufus portátil EXE](tools/rufus/rufus-4.15p.exe)** · [Guia de gravação](tools/rufus/README.md) |
| Depurar a comunicação serial e os servos | **[Feetech FD e utilitários seriais](tools/飞特/README.md)** · [Bancada web 3D](tools/servo-web/README.md) |
| Consultar referências Feetech ou integrar um SDK | **[Manuais oficiais, especificações e SDKs](docs/飞特资料/README.md)**, com versões oficiais e datas das cópias offline |
| Testar servos e investigar problemas | [Testador HD1910M](tools/FeeTech_HD1910M_Servo/README.md) · [Testador STS3215](tools/sts3215Servo_testtool/README.md) · [Análise de marcha](tools/gait-analysis/README.md) |

---

<a id="-鸭友Contribuição"></a>
## 🦆 Contribuições da comunidade

Este repositório é um trabalho coletivo. Aqui estão os créditos pelo código incorporado e pelas conclusões verificadas em testes físicos.

| Quem | Contribuição |
|---|---|
| [@yoyojacky](https://github.com/yoyojacky) | **Ferramenta em Rust para testar servos Feetech** ([PR #27](https://github.com/fanhao375/microduck-replica/pull/27), incorporado). Implementação própria e mínima do protocolo STS/SCS: montagem de quadros, soma de verificação, ping, leitura e escrita de registradores e interpretação do estado. A linha de comando permite varrer o barramento com barra de progresso, ler o estado, mover para uma posição e executar testes individuais ou em lote. Informa desvio de posição, corrente e carga de pico, tensão e temperatura, com resultado PASS/FAIL. Um comando gera a tabela de aceitação em bancada → [`tools/sts3215Servo_testtool/`](tools/sts3215Servo_testtool/) |
| [@Abo1ish](https://github.com/Abo1ish) | **Firmware da placa IMU e visualização de orientação na bancada** ([PR #32](https://github.com/fanhao375/microduck-replica/pull/32), incorporado). Base de firmware STM32G031 para a placa imu_to_dxl cujo firmware oficial não foi disponibilizado. Validado na placa física, com testes no computador e um [`VALIDATION.md`](hardware/imu_to_dxl/firmware/VALIDATION.md) que explicita seus limites → [`hardware/imu_to_dxl/firmware/`](hardware/imu_to_dxl/firmware/). Também integrou a leitura da orientação da IMU via J-Link à bancada web, fazendo o tronco do modelo 3D acompanhar a placa real (`--imu-jlink`; sem placa, use `--imu-demo`) → [`tools/servo-web/`](tools/servo-web/) |
| Integrante do grupo no WeChat | **Procedimento de inicialização da Radxa Zero 3W V1.12J.** Nesse lote, com Wi-Fi AIC8800DS2, substituir apenas o carregador de inicialização da Radxa não bastava. Os testes mostraram que também era necessária a árvore de dispositivos da Radxa B1: **bootloader B1 + DTB B1 + kernel Armbian 6.1.115 + sistema Trixie**. A combinação funcionou e foi registrada no [diário de problemas](Problemas encontrados.md#Software) e no [guia da imagem](tools/radxa/ImagemInstruções de uso.md#6-Se你 de 板子不是这一批) |

---

<a id="鸭友 de 项目"></a>
## Projetos da comunidade

Alguns participantes desenvolvem projetos relacionados ao Microduck em seus próprios repositórios. Estes são alguns destaques:

| Projeto | Autor | Descrição |
|---|---|---|
| [microduck-color-studio](https://github.com/LathamZ/microduck-color-studio) ([experimentar online](https://lathamz.github.io/microduck-color-studio/)) | [@LathamZ](https://github.com/LathamZ) | **Estúdio 3D de cores: escolha a aparência do robô no navegador antes de imprimir.** Permite colorir 70 peças individualmente, escolher materiais (PLA / fosco / PETG / metal / fibra de carbono / TPU) e iluminação. Recomenda paletas com base nos filamentos disponíveis: usar apenas o estoque, adicionar uma cor ou aplicar detalhes em acrílico. Importa arquivos 3MF próprios, inclusive da versão Feetech, e exporta **3MF colorido com múltiplas mesas** e STL por peça. Inclui predefinições para Bambu P1S / A1 mini / H2D. Interface em chinês e inglês, também acessível pelo celular |
| [MICDUCK_FTHD1901_REBUILD](https://github.com/fengj4780-sudo/MICDUCK_FTHD1901_REBUILD) | [@fengj4780-sudo](https://github.com/fengj4780-sudo) | **Melhorias estruturais para a versão Feetech e reforços CNC opcionais.** Parte dos [desenhos editáveis em SolidWorks](https://github.com/fanhao375/microduck-replica-cad): adapta os servos Feetech (chamados HD1901 naquele repositório; arquivos de peças HD-1910-C001), reforça peças frágeis, corrige interferências na montagem e repara modelos danificados. **Cinco peças das pernas podem ser fabricadas por CNC** para melhorar a distribuição de esforços. Ainda estão em prototipagem; o autor estima cerca de ¥45 pelas cinco, com frete. A impressão também é possível e oferece maior resistência que a versão original. Inclui 3MF para impressão em um clique (Bambu H2D, 0,4 mm, 5 mesas) e os desenhos SolidWorks modificados |
| [Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy) | [@kissqy](https://github.com/kissqy) | **Referência de treinamento e controle do robô com Feetech HD1910.** Fornece painel de treinamento, instruções de preparação do ambiente e gerenciamento de tarefas, exportação de modelos ONNX, painel de controle do robô, firmware e vídeos. Recomendado como referência prática para o fluxo de treinamento |

O convite do projeto original: desenvolveu algo relacionado ao robô — ferramenta, tutorial, modificação ou política? Abra uma issue com o link para inclusão na lista.

O projeto original recebe contribuições por [issue](https://github.com/fanhao375/microduck-replica/issues) ou PR. **A tradução deste fork é mantida separadamente, sem envio de pull request ao original.**
Hardware, firmware, algoritmos, documentação e dados medidos são bem-vindos. **Dados de testes físicos são especialmente valorizados:** a regra do projeto é registrar os resultados com honestidade, positivos ou negativos.

---

<a id="资料导航"></a>
## Índice da documentação

Os caminhos são relativos à raiz deste repositório. O CAD mecânico é mantido em um repositório separado.

| Área | Localização | Descrição e acesso |
|---|---|---|
| Uso e montagem | [Repositório CAD](https://github.com/fanhao375/microduck-replica-cad) · [BOM/](BOM/README.md) | [Guia de primeiro uso](docs/上手指南/README.md) · [Lista de compras](BOM/README.md) · [Vídeos de montagem](#-装配视频教程) |
| Software e imagem | [software/](software/README.md) | [Painel Studio](software/studio/README.md) · [Construção da imagem](software/image/README.md) |
| Plataforma e projeto de treinamento | [software/training-studio/](software/training-studio/README.md)<br>[software/training/](software/training/README.md) | Bancada web, ambiente de simulação e exportação de modelos |
| Eletrônica e firmware | [hardware/](hardware/README.md) | [Projetos de placas](hardware/README.md) · [Firmware da IMU](hardware/imu_to_dxl/README.md) |
| Depuração e análise | [tools/](tools/README.md) | [Índice de ferramentas](tools/README.md) · Gravação de cartões, depuração serial, referências Feetech e análise |
| Documentação e registros | [docs/](docs/README.md) | [Índice completo em pt-BR](docs/README.pt-BR.md) · [Problemas encontrados](Problemas encontrados.md) · [Depuração](Registro de depuração.md) · [Construção](Diário de construção.md) |
| Histórico e comunidade | [docs/](docs/README.md#深入研究 e 归档) | [Acompanhamento do projeto oficial](docs/Acompanhamento do projeto oficial.md) · [Histórico de atualizações](docs/Histórico de atualizações.md) · [Contribuições da comunidade](docs/Contribuições da comunidade.md) |

---

<a id="Licença e Fonte"></a>
## Licenças e fontes

Código, recursos de simulação e modelos incluídos na imagem têm licenças distintas. Consulte [licenças e atribuições](NOTICE.md) e os [termos dos modelos](software/image/overlay/usr/share/doc/microduck/ModeloInstruções.txt). **A imagem da réplica destina-se apenas a construções pessoais sem fins comerciais e não pode ser distribuída com produtos pagos.**

Este projeto independente não tem vínculo com a Pollen Robotics nem é endossado por ela.

<a id="-suportaAutor"></a>
### ❤️ Apoie o autor original

Este projeto cresceu com trabalho de montagem, depuração, desenvolvimento de software e documentação. Se os materiais e ferramentas ajudaram você, deixe uma estrela ⭐, relate problemas ou compartilhe sua experiência de construção. Também é possível oferecer uma contribuição voluntária ao autor original para apoiar a manutenção. Obrigado a todos que contribuem com o projeto.

<p align="center"><a href="assets/wechat-support.jpg"><img src="assets/wechat-support.jpg" alt="QR code de contribuição voluntária via WeChat; clique para ver a imagem original" width="240"></a><br><sub>Apoio voluntário via WeChat · Clique para ver a imagem original</sub></p>
