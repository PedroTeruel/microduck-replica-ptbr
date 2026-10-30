# Andamento do projeto

**Projeto**: réplica do Microduck
**Início**: 2026-08-28
**Data de referência do histórico**: 2026-09-03 (correção sobre o estado de código aberto do hardware: a placa HAT oficial está aberta)
**Repositório**: https://github.com/fanhao375/microduck-replica (público)

> **Atualização dos arquivos de modelo (2026-09-28)**: peças estruturais, CAD e arquivos de impressão foram reunidos no repositório [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). Os antigos STL de `print/` e `cad/` foram removidos do repositório principal; esses diretórios agora contêm apenas instruções de acesso. As análises por lote e quantidades abaixo são registros históricos. O andamento físico atual está no [diário de construção](构建日志.md), e a conferência de versões está no [registro do CAD](docs/CAD结构件版本核对-20260928.md).

---

## Objetivo

Reproduzir o **Microduck** da Pollen Robotics (pato bípede de 25 cm, US$ 399, previsto para venda no Natal de 2026).
O software é de código aberto; o hardware é **parcialmente aberto**: a placa HAT tem o projeto KiCad completo e os arquivos de produção ([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Apache-2.0), mas a placa `imu_to_dxl`, o CAD mecânico editável, a BOM completa e as instruções de montagem não foram publicados.

> **Correção de 2026-09-03**: a conclusão anterior de que “o hardware não é aberto e não há esquemas de PCB” estava **errada**. A busca ficou restrita ao repositório principal `microduck` e não encontrou o repositório de hardware da mesma organização, cujo nome começa com `elec_`.

Este projeto usa o **modelo de simulação MJCF e os 47 arquivos STL** publicados oficialmente para reconstruir as informações necessárias à réplica mecânica.

---

## Estado atual (2026-09-29)

| Área | Confirmado | O que falta |
|---|---|---|
| Mecânica Feetech | Robô montado; demonstração de levantar/sentar concluída em 18/09; modelos reunidos no repositório CAD | Testar as 14 articulações nesta rodada; o ID 29 do bico foi excluído a pedido do usuário e não foi aceito; conferir individualmente os zeros de montagem e os limites de curso |
| Armbian e HAT | Imagem própria conectada após corrigir o DHCP; articulações acessíveis pela HAT em `/dev/ttyS2`; bancada de depuração 0.15.4 instalada | Aceitação de comunicação prolongada durante movimento e configuração das proteções |
| Leitura de estados mantendo pose a 50 Hz | Em 3.000 ciclos, 14 servos (42.000 estados), nenhum erro nessa janela; frequência real de 46,8664 Hz; manteve a pose e as configurações | Não inclui IMU, inferência nem gravação de movimento; não equivale ao ciclo completo de controle a 50 Hz; ainda há respostas ocasionalmente ausentes em outras janelas |
| Câmera | O cabo flat oficial B1, orientado corretamente, capturou 40 quadros a 1920×1080 | Repetir o teste de configuração Armbian neste projeto e verificar a taxa contínua de quadros |
| IMU e Rust | Há registros de testes de software/simulação da interface Feetech no firmware 0.2.0; o fork Rust `feetech` já tem uma implementação de adaptação | Ainda faltam testes do barramento misto real, temporização das respostas e aceitação com tudo instalado no robô |
| Treinamento | Projeto HD1910, parâmetros M6 e verificações de treinamento curto integrados em `software/training` | Calibração local, conferência do modelo e marcha no robô físico |
| Imagem pública | As instruções antigas de primeiro acesso foram atualizadas para `root / 1234`; o pato só é criado depois do assistente; foi adicionada uma imagem candidata com correção de DHCP | A candidata só passou por verificações offline e ainda não foi gravada e testada; a imagem-base não inclui o runtime do robô |

Fontes: [resumo dos 3.000 ciclos](tools/radxa/50Hz保持姿势读状态-20260928.md), [instruções da imagem](tools/radxa/ImagemInstruções de uso.md) e [registro da câmera](tools/radxa/摄像头记录-20260928.md). A próxima etapa é fazer validações de pequena amplitude, articulação por articulação, com o robô apoiado; depois, validar as proteções e integrar IMU e execução do modelo. As análises antigas são preservadas como histórico e suas tarefas pendentes não substituem a aceitação física atual.

## Referência da análise histórica (2026-09-03)

| Área | Estado | Observações |
|---|---|---|
| Geometria das peças | ✅ Concluído | 47 STL |
| Relações de montagem | ✅ Concluído | Precisão de 0,1 mm; vista explodida pronta |
| Conjunto CAD | ✅ Concluído | Transformações globais aplicadas; pode ser importado diretamente |
| Parâmetros das articulações | ✅ Concluído | Eixos e cursos das 14 articulações controladas |
| Massa e inércia | ✅ Concluído | 15 corpos rígidos |
| Lista de fixadores | ✅ Concluído | Reconstruída a partir das características dos furos; sistema M2 |
| Seleção dos atuadores | ✅ Concluído | 15 XL330, parâmetros BAM M6 |
| Especificação dos rolamentos | ✅ Concluído | Ø22×16×4 e Ø15×10×3 |
| **Solução eletrônica** | ✅ Concluído | Reconstruída integralmente a partir do código Rust; consulte o “Lote 6” |
| Seleção do controlador | ✅ Concluído | **Módulo comercial Radxa Zero 3W**, não uma placa-base personalizada |
| **Placa HAT** | ✅ Código oficial aberto | KiCad + Gerber + BOM + coordenadas de montagem; pronta para fabricação (4 camadas) |
| **Placa `imu_to_dxl`** | ✅ Projeto próprio concluído (ainda não fabricada) | Não há projeto público; chip, endereços e protocolo foram reconstruídos; este repositório contém esquemático e PCB |
| **Plano de cabeamento** | ❌ Em falta | O projeto oficial não publicou informações |
| **Software de controle** | ✅ Disponível | Com o mesmo controlador, executar diretamente o Rust oficial; só é necessário portar ao trocar o controlador |
| **Retreinamento da política** | ✅ Não necessário | Com hardware igual, as 9 ONNX oficiais podem ser usadas; alterações no robô ou controle exigem retreino |

---

## Trabalho concluído

### Lote 1 · Levantamento de materiais

- ~~Confirmar que **o hardware do Microduck não é aberto**~~: o repositório `microduck` continha apenas software Rust; os cinco subdiretórios de `docs/` tinham documentação de software e não havia arquivos `.stl/.step/.f3d/bom`. **Essa conclusão estava errada** (corrigida em 2026-09-03). A busca cobriu apenas o repositório principal, sem consultar o repositório de hardware da mesma organização, com prefixo `elec_`. A placa HAT tem projeto **totalmente aberto** em [`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT) (Apache-2.0; inclui KiCad, Gerber, BOM e coordenadas de montagem). Lição: para saber se uma parte de um projeto é aberta, pesquisar a organização inteira, não apenas o repositório principal.
- Confirmar que `microduck_rl` contém 47 STL e o MJCF completo, única fonte da geometria.
- Confirmar que a licença do modelo 3D é CC BY-NC-SA (não comercial) e a do código é Apache-2.0.
- Descartar o caminho do Open Duck Mini v2 (consulte “Registro de decisões”).

### Lote 2 · Desenhos de montagem

- Renderização offline com MuJoCo, fundo branco, resolução 1600×2100.
- Quatro vistas comuns, duas vistas explodidas e uma comparação com cores.
- Deslocamento progressivo das peças ao longo da cadeia cinemática (48 mm por nível), aumentando em direção à extremidade.
- Implementação própria da projeção de coordenadas globais para pixels, usada para desenhar linhas de chamada e evitar sobreposição na composição.
- Resultado: sete desenhos em `assembly-drawings/`; script `scripts/render_assembly.py`.

### Lote 3 · Conjunto CAD

- Os 47 STL do upstream usam o **sistema de coordenadas de cada peça**; importá-los diretamente no CAD empilharia tudo na origem.
- Obter do MJCF a transformação global de cada geom, aplicá-la e exportar as peças agrupadas por corpo rígido.
- Resultado em `cad/`: um arquivo do robô completo (796.792 faces triangulares) e 15 componentes, em milímetros.
- Dimensões externas medidas do robô: **144 × 141 × 264 mm**, compatíveis com os 25 cm nominais da documentação oficial.
- Script: `scripts/export_assembly_stl.py`.

### Lote 4 · Reconstrução dos fixadores

- Implementado o reconhecimento de características de furos: soldar os vértices → criar o grafo de adjacência das faces → separar superfícies suaves pelo ângulo diedro de 35° → ajustar um cilindro a cada superfície (eixo = vetor próprio de menor covariância das normais) → projetar e ajustar um círculo para obter o diâmetro → distinguir furos e saliências pela direção das normais.
- A varredura das 47 peças levou 2,5 s.
- Resultados: `docs/紧固件反推.md`, `docs/hole_analysis.json` e `scripts/analyze_holes.py`.

### Lote 10 · Documentação em inglês

- Contexto: a lista awesome indicava explicitamente “In Chinese”; os dados de tráfego mostravam somente 5 visitas pelo Google contra 132 pelo Bing, com pouca entrada de leitores anglófonos.
- Priorizamos por visitas e começamos por `硬件方案逆向.md` (segundo documento mais acessado no site, 84 visitas), porque traz conteúdo difícil de encontrar em outro lugar. A página de anatomia 3D de @mishig25, funcionário do Hugging Face (36 mil visualizações), já cobria a aparência geral do robô; documentos de especificações se sobrepunham a ela, mas os endereços dos chips, o protocolo do barramento e o layout do bloco de dados de 12 bytes só estavam neste repositório.
- Resultados: `docs/hardware-teardown.en.md` (426 linhas) e `docs/actuator-selection.en.md` (459 linhas), ambos com links para as versões em chinês.
- O índice de documentos no README em inglês passou a usar 🇬🇧 para indicar quais documentos têm versão em inglês.

### Lote 9 · Análise e seleção dos atuadores

- Responde a duas perguntas frequentes: por que usar servos em vez de motores de passo de malha fechada e se seria possível trocar por STS3215 mais baratos sem alterar a mecânica.
- **Comparação de dados físicos**: ambos os patos bípedes têm 15 corpos rígidos; o modelo XL330 pesa **737,2 g** e o STS3215, **2.107,1 g**, diferença de 2,86 vezes. O Open Duck Mini v2 é a resposta “versão STS3215” (42 cm / 2,1 kg).
- **Comparação dos parâmetros dos atuadores**: diferença de 32× em kp, 3,5× em forcerange, 11× em damping e frictionloss e 15,5× em armature — cada parâmetro difere por uma ordem de grandeza.
- Resultado contraintuitivo: o modelo do XL330 tem mais folga (±1,0° contra ±0,5°).
- Conclusão: **não há uma opção intermediária** — manter XL330 (servo a ¥ 4.500) ou mudar para STS3215, o que equivale a construir o Open Duck Mini v2.
- **Comparação complementar entre servos da mesma categoria**: Feetech STS3032 (20 g / 23,2×12,1×28,5 mm / 0,44 N·m / 4,8–6 V) é menor que o XL330 e tem peso semelhante, mas torque de cerca de 85% (na mesma tensão) e limite superior de tensão de 6 V. O SCS0009 pesa apenas 11 g, mas oferece somente 0,23 N·m; a própria Pollen o usa na parte superior do Amazing Hand.
- A lacuna de mercado está clara: “18–20 g / ≥0,9 N·m / 7,4 V / barramento”; atualmente, apenas a Robotis atende a todos os critérios.
- **Avaliação detalhada do Unitree S288** (manual oficial de 11 páginas): 19,5 g / 34×20×23 mm / **redução de 288,35:1, exatamente igual à do XL330** / fixação M2 / half-duplex de fio único. A mecânica é quase intercambiável.
- Duas melhorias relevantes do S288: **controle de impedância** (τ = τ_ff + k_p·Δp + k_d·Δω) e **encoder no eixo de saída** (OutPos de 13 bits); este último eliminaria toda a complexidade de modelagem da folga.
- Três restrições importantes do S288: alimentação de 12,6 V (3S) contra 7,4 V (2S) do Microduck; espaço de endereços do barramento limitado a 0–14, insuficiente para 16 dispositivos (a IMU teria de usar SPI); **especificação de torque duvidosa** (nenhuma das interpretações, no eixo do rotor ou na saída, parece consistente). Foram preparadas quatro perguntas para o fabricante.
- Resultado: `docs/执行器选型.md` reescrito (de 106 para 424 linhas).

### Lote 8 · Informações da comunidade no X e validação externa ⭐

- Leitura de publicações públicas do X por comandos de busca e leitura de tópicos do opencli para Twitter.
- **Principal resultado: confirmação externa independente das conclusões da análise reversa** — a desmontagem de hardware de @tspy (169 curtidas) identificou Radxa ZERO 3W / RK3566, exatamente como este repositório.
- Registro de popularidade: três publicações oficiais somaram aproximadamente 8,6 milhões de visualizações; o GitHub cresceu 3,7 vezes em três dias.
- Registro de projetos comunitários: síntese de voz R2D2, rastreamento com ponteiro laser, mortal para trás e breakdance.
- **Ruído identificado e marcado**: muitas moedas meme tentavam aproveitar a popularidade; a seção de respostas de “Microdino” tinha acusações de golpe e respostas vagas sobre CAD. **Foi considerado pouco confiável e não foi citado.**
- Premissa explícita: **em 31/08 ainda não havia unidades disponíveis no mercado**; todas as desmontagens públicas eram inferências, não inspeções de hardware físico.
- Resultado: `docs/社区动态.md` (150 linhas).

### Lote 7 · Conferência das especificações oficiais e atualizações da comunidade

- A Pollen publicou especificações parciais em 2026-08-27; comparamos cada item com os resultados da análise reversa deste repositório.
- Confirmações mútuas: RK3566, NP-F550, ToF 8×8 e largura de 140 mm.
- Informações complementares oficiais: RAM de 1 GB + eMMC de 32 GB (**SKU exato do Radxa Zero 3W**, confirmação indireta da escolha do controlador; sem comprovação no código-fonte, recomendamos 2 GB/16 GB para a réplica), NPU de 0,8 TOPS e duas antenas NFC.
- Resultados exclusivos da análise reversa: modelo do controlador, solução do barramento principal e endereços/protocolos de todos os chips.
- **Contradição encontrada**: a Pollen informa duas IMUs, mas o código-fonte usa apenas uma (BMI088 marcado como inativo).
- Registro da posição da Pollen sobre código aberto: ela pediu explicitamente à imprensa que **não** descreva o produto como “open-source hardware” (mas acrescentou “for now”).
- Registro de três issues comunitárias sem resposta: #175 STEP / #173 arquivos-fonte de impressão / #174 esquema da placa de alimentação.

### Lote 6 · Análise reversa da solução de hardware ⭐

- Ideia central: **para controlar o hardware real durante a execução, o software precisa definir caminhos de dispositivos, endereços I²C, deslocamentos dos registradores, baud rate e protocolo — o código é a especificação.**
- Reconstrução da solução eletrônica completa a partir de `duck-control/src/{model,imu,bus}.rs`, `deploy/*.dts`, `deploy/robotd.toml`, `tof/` e `mediad/`.
- Resultados: `docs/硬件方案逆向.md` (394 linhas, análise completa) e `docs/硬件规格速查.md` (270 linhas, consulta rápida em uma página).

### Lote 5 · Seleção dos atuadores

- Organização da configuração BAM M6, das faixas de três itens de randomização de domínio e da modelagem da folga do encoder.
- Extração dos parâmetros PD nativos de cinco grupos de calibração BAM medidos, em `joints_properties.xml`.
- Resultado: `docs/执行器选型.md`.

---
## Principais descobertas

1. **O robô inteiro usa parafusos M2.**
   Há 77 furos passantes Ø2,2, 28 escareados Ø4,4 e 20 furos-piloto Ø1,6 para rosca.
   A combinação de furos Ø2,2 e Ø4,4 corresponde a parafusos M2 de cabeça cilíndrica Allen, passantes e escareados.
   Conferência cruzada: o próprio `xl330.stl` tem furos Ø2,0×4 + Ø1,6×8, compatíveis com a montagem M2 do XL330.
   As peças estruturais têm aproximadamente **146 furos passantes**.

2. **São 15 servos, não 14.**
   A malha `xl330` é referenciada **15 vezes** no MJCF do robô completo. Quatorze entram no espaço de ações da política (5 na perna esquerda + 4 no pescoço/cabeça + 5 na perna direita); o 15º aciona o bico/mandíbula por uma articulação `passive_*`.
   Isso coincide com a menção a “15 servos” no README oficial; contar somente a lista de articulações deixa um de fora.

3. **A cabeça representa um quarto da massa do robô.**
   O tronco pesa 199 g, o conjunto da cabeça 189 g e o robô completo 737 g. O centro de gravidade é alto, o que ajuda a explicar a dificuldade de treinar a política de marcha.

4. **A modelagem da folga é um detalhe importante de sim2real.**
   O encoder magnético real do servo fica no lado **de saída** da folga das engrenagens; a malha de posição do firmware fecha o controle sobre `ângulo da articulação + ângulo da folga`. Enquanto o servo gira livremente na zona morta, a posição medida e o erro PD não mudam.

5. **Construir pode custar mais do que comprar.**
   Os 15 XL330 custam de US$ 359 (loja internacional ROBOTIS) a € 629 (MyBotShop), de um valor um pouco abaixo a bem acima do preço de US$ 399 do robô. Consulte a BOM para a conferência dos preços.

6. **⭐ O controlador principal é um módulo comercial, não uma placa-base personalizada — a conclusão anterior estava errada.**
   (Adendo de 2026-08-31: a conclusão também foi confirmada pela desmontagem independente de @tspy no X.)
   A árvore de dispositivos fixa `compatible = "radxa,zero-3w", "rockchip,rk3566"`, identificando o **Radxa Zero 3W**, vendido no mercado (formato Pi Zero, 65×30 mm, compatível com o STL).
   Isso derrubou diretamente a conclusão de que a eletrônica seria uma barreira intransponível.

7. **A IMU está ligada ao barramento Dynamixel, não ao I²C.**
   Placa `imu_to_dxl` v2 própria: LSM6DSV16X, ID 200 no barramento, registrador 124, bloco de 12 bytes (6 bytes de giroscópio + 6 bytes de quaternion SFLP fp16). A IMU e os 15 servos são lidos na **mesma operação `sync_read`**, sem custo adicional para o barramento nem necessidade de executar a fusão de orientação no controlador principal.

8. **Não há medidor de carga nem ADC.**
   A tensão da bateria é lida diretamente do valor de alimentação que o servo informa pelo protocolo Dynamixel.
   Portanto, 6,6–8,2 V é a “faixa de uso sob carga”, não a faixa elétrica das células. Ao reproduzir, **não é necessário projetar um circuito de monitoramento da bateria**.

---

## Registro de decisões

| Decisão | Conclusão | Motivo |
|---|---|---|
| Fazer o Microduck ou o Open Duck Mini v2 | **Fazer o Microduck** | O usuário pediu explicitamente o próprio Microduck. Embora o Open Duck Mini v2 tenha BOM/CAD/STL e guia de montagem abertos, é outro robô |
| Repositório público ou privado | **Público** | Escolha do usuário. CC BY-NC-SA permite redistribuição; atribuição, mesma licença e aviso de uso não comercial já estão configurados |
| Agrupar os seis repositórios upstream | **Não agrupar** | Os scripts de análise obtêm as fontes com `scripts/fetch_upstream.sh`. Em 2026-09-04 foram disponibilizadas cópias STL em `print/`; foram removidas em 2026-09-28 para evitar confusões, e os downloads de modelos apontam para o repositório CAD. As fontes e licenças do projeto de treinamento estão em `software/training/UPSTREAM.md` |
| Licença | **Duas licenças** | Código original em `scripts/` → Apache-2.0; `assembly-drawings/` e `cad/` são obras derivadas CC BY-SA-NC → mantêm a mesma licença pela cláusula ShareAlike |
| Como lidar com a barreira de PCB | **Reproduzir a mecânica e construir a eletrônica** | Uma reprodução 100% fiel era impossível. O usuário informou que consegue fabricar PCBs, então este caminho é viável |

---

## Arquivo de tarefas antigas (estado histórico)

### Prioridade alta

- [x] **Projetar a placa `imu_to_dxl`** — **esquemático e PCB concluídos** (2026-09-07).
      STM32G031F8P6 + LSM6DSV16X + buffer half-duplex SN74LVC2G241;
      placa de duas camadas, 45 × 22 mm, plano GND contínuo na camada inferior, as 22 redes conectadas e DRC sem violações.
      **Ainda não fabricada nem validada em hardware** → [projeto e resultados da revisão](hardware/imu_to_dxl/)
- [ ] **Validar a fabricação da `imu_to_dxl`** — antes do pedido, normalizar os componentes e revisar a serigrafia; conferir com o STEP do conjunto se a altura do conector (8 mm vertical) cabe na cavidade do tronco.
- [x] ~~**Reconstruir o contorno da PCB**~~ — **cancelado**: o projeto KiCad oficial e os Gerbers já fornecem o contorno exato, as posições dos furos e as aberturas dos conectores; não é preciso inferir isso dos STL.
- [ ] **Decidir se fabricaremos a HAT** — pode ser omitida por completo se não forem necessários gravação de áudio ou alto-falante; ligar o ToF diretamente ao i2c3 e usar um UBEC comercial para alimentação.

### Prioridade média

- [x] ~~Traduzir para inglês~~ **Concluído**: os três documentos de análise reversa de hardware, seleção dos atuadores e reconstrução dos fixadores foram traduzidos integralmente, além do README — quatro documentos bilíngues. `社区动态.md` e `PROGRESS.md` não foram traduzidos naquela etapa: o primeiro envelhece rapidamente, e o segundo era um registro interno de progresso.
- [ ] Ainda não traduzir `硬件规格速查.md` — há grande sobreposição com o conteúdo da página de anatomia 3D de @mishig25.
- [ ] **Verificar se os STL podem ser impressos** — validar se as 47 malhas são estanques e se têm bordas não manifold; determinar se podem ser fatiadas diretamente.
- [ ] **Avaliar o processo de impressão** — malhas de simulação não têm tolerâncias de encaixe; avaliar quais furos precisam ser ampliados e quais superfícies precisam de suporte.
- [ ] **Analisar os canais de fiação** — inferir, a partir das cavidades internas do conjunto, os caminhos disponíveis para os fios.

### Prioridade baixa

- [ ] **Plano para o software de controle** — como o Rust de execução está ligado ao RK3566, avaliar o custo de portá-lo contra reescrever o ciclo de controle em Python.
- [ ] **Retreinar a política** — a eletrônica diferente invalida as ONNX oficiais; retreinar com `microduck_rl` (requer GPU CUDA ou execução na Hugging Face com `--hf-jobs`).

---

## Riscos e limitações conhecidas

1. **STL de simulação não são peças de engenharia prontas para impressão.** A simulação garante apenas a forma e a inércia, não tolerâncias de encaixe, furos roscados, suportes para porcas de inserção térmica nem espaço para os fios. Imprimir diretamente provavelmente impede a montagem.
2. **A lista de fixadores é uma inferência, não um desenho técnico.** O comprimento dos parafusos foi estimado pela profundidade dos furos, portanto é uma faixa, não uma medição. A contração da impressão também altera o diâmetro real (em FDM, Ø2,2 costuma ficar 0,1–0,3 mm menor).
3. **A placa `imu_to_dxl` precisa ser projetada do zero.** Não há projeto público; só é possível criar o projeto com base no protocolo reconstruído. (O projeto KiCad e os Gerbers da HAT oficial estão disponíveis; **isso não é um bloqueio**.)
4. **A política oficial não é portável entre eletrônicas.** As nove ONNX ficam inválidas ao trocar o sistema eletrônico; é necessário retreinar.
5. **Há restrição de uso não comercial.** Todo conteúdo geométrico derivado está sujeito à CC BY-SA-NC e não pode ser usado em produtos comerciais.

---

## Índice de arquivos

| Caminho | Conteúdo |
|---|---|
| `README.md` | Visão geral do projeto, estrutura de montagem, parâmetros das articulações e análise de viabilidade |
| `PROGRESS.md` | Este documento |
| `NOTICE.md` | Atribuições e fontes |
| `assembly-drawings/` | Sete desenhos de montagem |
| `cad/`, `print/` | Acesso aos downloads no repositório CAD; os antigos STL e tabelas de comparação foram removidos, e os resultados de análises históricas podem ser consultados no histórico Git |
| `docs/紧固件反推.md` | Sistema de parafusos M2, quantidades de compra e especificação dos rolamentos |
| `docs/执行器选型.md` | Parâmetros do XL330, BAM M6, cinco grupos de PD calibrados e modelagem da folga |
| `docs/硬件规格速查.md` | Folha de referência rápida das especificações de hardware |
| `docs/硬件方案逆向.md` | Reconstrução completa da solução eletrônica e evidências |
| `docs/社区动态.md` | Informações do X/GitHub, validações externas, ruídos e riscos |
| `docs/hole_analysis.json` | Dados brutos da varredura dos furos |
| `scripts/` | Quatro scripts para obter fontes upstream, renderizar desenhos, exportar CAD e analisar furos |
