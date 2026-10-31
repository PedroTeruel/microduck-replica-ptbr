# Créditos e atribuições / Attribution

Este repositório documenta uma **réplica independente do Microduck**. Não é afiliado nem endossado pela Pollen Robotics.

## Fontes upstream

| Fonte | Autor | Licença |
|---|---|---|
| [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl) | Pollen Robotics | Código Apache-2.0; **modelos 3D CC BY-NC-SA** (o README upstream escreve “BY-SA-NC”) |
| [pollen-robotics/microduck](https://github.com/pollen-robotics/microduck) | Pollen Robotics | Apache-2.0 |
| Parâmetros 1910 M6 e configurações de referência de [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | LuwuDynamics | Apache-2.0 |
| Modelos de atuadores e biblioteca de identificação de [Rhoban/BAM](https://github.com/Rhoban/bam) (dependência de treinamento) | Rhoban | Apache-2.0 |

O Microduck é um produto comercial da Pollen Robotics e seu hardware é **parcialmente aberto**:

- A placa **RPI Robot HAT foi publicada oficialmente** ([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Apache-2.0, incluindo o projeto KiCad e arquivos de fabricação).
- A placa `imu_to_dxl`, os arquivos CAD editáveis das peças mecânicas, a BOM completa e os documentos de montagem não foram publicados.

Todas as informações geométricas deste repositório vêm dos **modelos de simulação MJCF e malhas STL** publicados no repositório upstream `microduck_rl`. As conclusões sobre a eletrônica foram obtidas do código-fonte, da árvore de dispositivos e dos arquivos de configuração do repositório `microduck`.

> Correção (2026-09-03): uma versão anterior deste documento dizia que o hardware não era aberto. Isso estava incorreto: a placa HAT é aberta.

## Conteúdo derivado neste repositório

O conteúdo abaixo foi gerado ou organizado neste projeto a partir do MJCF e STL publicados upstream. É considerado **trabalho derivado sob CC BY-NC-SA** e distribuído sob a mesma licença:

| Caminho | Conteúdo | Relação com upstream |
|---|---|---|
| `assembly-drawings/` | Todas as imagens renderizadas e vistas explodidas | Renderizadas a partir do MJCF e STL upstream |
| Malhas 3D em `software/training/` | Geometria de simulação usada no treinamento | Mantém a origem e licença do modelo upstream; não se destina à impressão de peças físicas |
| `tools/servo-web/model/` | Modelo exibido na bancada web de depuração | Convertido do MJCF/STL upstream; não corresponde ao CAD físico mais recente |
| `software/studio/web/model/` | Microduck 3D exibido no Studio | Convertido do modelo de simulação upstream, somente com o formato externo; não corresponde ao CAD físico mais recente |
| `docs/hole_analysis.json` | Dados da análise geométrica dos furos | Calculados a partir de STL upstream |

> **Migração dos downloads de modelos (2026-09-28):** `print/` e `cad/` agora direcionam para as instruções do [repositório CAD](https://github.com/fanhao375/microduck-replica-cad). Os STL individuais antigos, STL de montagem e tabelas de comparação foram removidos da versão atual para evitar que sejam confundidos com os arquivos de impressão mais recentes. Os modelos antigos no histórico Git continuam sendo trabalhos derivados dos STL upstream, renomeados, classificados ou transformados para montagem, e permanecem sob CC BY-NC-SA. A remoção das cópias para download não altera a autoria ou licença dos arquivos históricos.

**Conteúdo original deste projeto:**

| Caminho | Conteúdo | Licença |
|---|---|---|
| `scripts/` | Scripts de renderização, exportação e análise de furos | **Apache-2.0** |
| `tools/stl_viewer.html` | Visualizador STL WebGL sem dependências | **Apache-2.0** |
| Código em `software/studio/` | Painel web Microduck Studio (exceto `web/vendor/`, `deps/` e `web/model/`) | **Apache-2.0** |
| `software/image/` | Scripts de construção da imagem, primeira inicialização e configuração de rede | **Apache-2.0** |
| `software/updater/` | Construção de pacotes assinados, adaptação do mecanismo de atualização original, coordenação da atualização web e ferramenta de primeira inicialização | **Apache-2.0**; updaterd original da Pollen Robotics, origem 1fa8438 |
| Código em `software/duck-echo/` | Interação local por voz R3, gravação e música; não inclui chaves privadas da máquina de build nem gravações de usuários | **Apache-2.0**; modelos Vosk externos e dependências ARM64 seguem suas próprias licenças, com origem e hashes registrados |
| `docs/*.md`, `*.md` | Documentação e análises de engenharia reversa | **CC BY-NC-SA 4.0** |
| Fotos em `build-log/` | Fotos da construção física | **CC BY-NC-SA 4.0**, fotografadas e autorizadas por participantes do projeto |
| Materiais originais do projeto em `assets/` | Capa, QR code do grupo e imagens de apresentação; exceto as fotos oficiais de placas indicadas abaixo | Mesma licença |

## Imagens oficiais de placas

As duas imagens abaixo são incluídas sem alterações, mantendo seus autores e licenças originais. Elas não estão cobertas pela licença CC BY-NC-SA dos documentos ou materiais originais deste projeto:

| Caminho | Fonte e autor | Licença |
|---|---|---|
| `assets/hw/radxa-zero3w-official.webp` | [Documentação oficial Radxa ZERO 3](https://docs.radxa.com/en/zero/zero3), Radxa Computer (Shenzhen) Co., Ltd. | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `assets/hw/rpi-robot-hat-official.png` | [Repositório oficial da HAT da Pollen Robotics](https://github.com/pollen-robotics/elec_RPI_Robot_HAT), Pollen Robotics | [Apache-2.0](https://github.com/pollen-robotics/elec_RPI_Robot_HAT/blob/main/LICENSE) |

Os endereços das imagens, versões fixadas e hashes estão no [registro de fontes das imagens](assets/hw/official-board-images.md).

## Projeto de treinamento incluído

[`software/training/`](software/training/) contém o projeto de treinamento completo para que quem reproduz o robô possa obter código, parâmetros e modelos de simulação em um único download. As versões upstream importadas e o escopo das alterações estão em [UPSTREAM.md](software/training/UPSTREAM.md).

- O código, as ferramentas e a documentação original da Pollen Robotics mantêm a licença **Apache-2.0**. As tarefas HD1910, adaptações de inicialização, testes e instruções adicionados neste diretório também usam Apache-2.0. O texto da licença está em [`software/training/LICENSE`](software/training/LICENSE).
- Os **modelos e malhas 3D** no diretório de treinamento mantêm os avisos upstream CC BY-NC-SA e não são cobertos pela licença Apache do código.
- `1910_m6.json` de LuwuDynamics é mantido sem alterações. A fonte fixada, o hash e uma cópia da licença estão em [`software/training/src/mjlab_microduck/robot/hd1910/`](software/training/src/mjlab_microduck/robot/hd1910/). Este projeto não identificou esses parâmetros de forma independente; referências à origem continuarão presentes se forem usados para treinar políticas.
- Rhoban/BAM é instalado por dependência em versão fixada, mantendo a atribuição e a licença correspondentes.

A licença CC BY-NC-SA dos documentos deste projeto não cobre a documentação Apache no diretório de treinamento.

## Outros softwares de terceiros

**Software de terceiros distribuído sem alterações:**

| Caminho | Conteúdo | Fonte | Licença |
|---|---|---|---|
| `tools/飞特/` | Software Feetech FD 1.9.8.5 para depuração + driver CH340 | [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug), cópia de 2026-09-11 | **MIT** (FTServo 2024; LICENSE no mesmo diretório) |
| `tools/rufus/` | Rufus 4.15 portátil para Windows x64 e código-fonte da mesma versão | [pbatard/rufus v4.15](https://github.com/pbatard/rufus/releases/tag/v4.15), download sem alterações em 2026-10-25 | **GPL-3.0-or-later**; licença, arquivo de código-fonte, hashes e registro de origem no diretório |
| `software/studio/web/vendor/` | Bibliotecas frontend do Studio: Preact, htm 3.1.1 e three.js 0.160.0 | Versões oficiais de cada projeto | Preact e three.js **MIT**; htm **Apache-2.0** (licenças em `web/vendor/licenses/`) |
| `software/studio/deps/` | Dependências Python do Studio (anyio, click, h11, idna, pyserial, sniffio, starlette, typing_extensions, uvicorn, wsproto) | Wheels originais do pypi.org; versões e hashes em `deps/VERSIONS.txt` | MIT / BSD-3-Clause / PSF-2.0 etc.; licenças em `*.dist-info` de cada pacote |

> Trechos de código upstream citados nos documentos (comentários, constantes e definições de registradores) vêm de `pollen-robotics/microduck`, seguem a licença **Apache-2.0** e incluem o caminho do arquivo citado.

## Repositório associado: projetos SolidWorks

[**fanhao375/microduck-replica-cad**](https://github.com/fanhao375/microduck-replica-cad) mantém os arquivos editáveis SolidWorks / STEP, os arquivos de impressão e o manual de montagem de 21 páginas. Há versões para Feetech e XL330; a lista de arquivos corresponde à publicação desse repositório. O repositório principal não mantém cópias independentes dos modelos de impressão.

| Conteúdo | Autor | Licença |
|---|---|---|
| Projetos SolidWorks, manual de montagem e desenhos de componentes | **机械行者Robo** (Xiaohongshu 270594280 / Douyin 1852366168) | **CC BY-NC-SA 4.0** |

Esses projetos são **modelos paramétricos editáveis reconstruídos a partir das malhas STL upstream** e constituem trabalhos derivados sob CC BY-NC-SA, distribuídos sob a mesma licença. **Os direitos autorais pertencem ao autor**; mantenha a atribuição ao republicar ou redistribuir. Os arquivos ficam em repositório separado porque os arquivos SolidWorks ocupam cerca de 340 MB descompactados e aumentariam o tamanho de cada clone deste repositório.

## Nome da licença

O nome padronizado é **CC BY-NC-SA 4.0** (Atribuição — Não Comercial — CompartilhaIgual). O README upstream usa “BY-SA-NC”; neste repositório, essa forma se refere à mesma licença.

> Observação: o arquivo `LICENSE` do repositório upstream `microduck_rl` contém somente Apache-2.0; **os termos CC aparecem em uma única linha do README**. A adoção de CC BY-NC-SA, mais restritiva, para os modelos 3D neste repositório é uma medida conservadora. Se o upstream confirmar que os modelos estão apenas sob Apache-2.0, a licença deste projeto será ajustada de acordo.

## Declaração de conformidade

Todas as conclusões deste repositório foram baseadas em:

- **Código-fonte e árvore de dispositivos** publicados pela Pollen Robotics (`pollen-robotics/microduck`, Apache-2.0).
- **Modelos de simulação e malhas** publicados (`pollen-robotics/microduck_rl`).
- **Projeto KiCad** publicado (`pollen-robotics/elec_RPI_Robot_HAT`, Apache-2.0).
- **Parâmetros 1910 M6 e configurações associadas** publicados pela LuwuDynamics (`LuwuDynamics/xgoduck_rl`, Apache-2.0).
- Manuais e fichas técnicas de componentes publicados pelos fabricantes.

**Não foram usadas informações não públicas, nenhum produto físico foi desmontado e nenhum projeto não publicado foi acessado.** O firmware da placa `imu_to_dxl` não está em nenhum repositório aberto; este repositório apenas reproduz o comportamento observável dela no barramento.

## Uso não comercial

Os modelos 3D upstream estão sob **CC BY-NC-SA**; trabalhos derivados **não podem ser usados para fins comerciais**. Este repositório destina-se somente a estudo, pesquisa e réplicas pessoais.

## Atribuição

> Baseado no modelo Microduck da Pollen Robotics (CC BY-NC-SA)
> https://github.com/pollen-robotics/microduck_rl
