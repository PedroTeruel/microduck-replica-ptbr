# Software

> Este diretório mantém os modelos de simulação upstream necessários ao treinamento. **Ele não é a fonte para imprimir as peças mecânicas mais recentes do robô.** Os modelos CAD ficam no repositório [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad). Incluir parâmetros para servos Feetech não significa que a geometria CAD, a massa ou a inércia tenham sido atualizadas.

O runtime oficial [`pollen-robotics/microduck`](https://github.com/pollen-robotics/microduck) foi desenvolvido para os servos Dynamixel XL330. Como a linha principal deste repositório usa Feetech HD-1910, o programa principal precisa de adaptações.

## Visão geral do software em uso

| Software | Função | Localização e uso | Licença |
|---|---|---|---|
| **Imagem de réplica** | Sistema completo pronto para gravar no cartão: programa principal, modelos, Studio, primeira inicialização e configuração da rede | [`image/`](image/). Usuários: [gravação e primeiro uso](image/烧录和第一次使用.md); responsáveis pela imagem: [construção da imagem](image/README.md). Veja as versões publicadas em [Releases](https://github.com/fanhao375/microduck-replica/releases/latest). | Scripts de construção Apache-2.0; consulte as licenças de cada componente em `/usr/share/doc/microduck/` na imagem. |
| **Microduck Studio** | Painel web instalado no robô para consultar o estado, aliviar o torque, calibrar servos e IMU, gravar configurações no programa principal, usar o controle e consultar registros | [`studio/`](studio/). Quem usa a imagem de réplica não precisa instalá-lo separadamente. | Código Apache-2.0. |
| **Atualização de software pela web** | Pacote de componentes assinado, serviço de atualização independente, envio offline, instalação e reversão | [`updater/`](updater/). Já vem na imagem 20261027; em cartões antigos, é necessário ativá-lo uma vez por SSH. Consulte as [instruções](../docs/软件更新与语音使用说明-20261027.md). | Apache-2.0. |
| **Comandos locais de voz para sentar e levantar** | Um clique no R3 ativa a escuta; reconhece “sentar” e “levantar” em mandarim e confirma com um som | [`duck-echo/`](duck-echo/). A imagem 20261027 inclui o modelo em chinês e as dependências ARM64. Não exige chave de serviço na nuvem. | Código Apache-2.0; o modelo e as dependências têm suas próprias licenças. |
| **Programas principais `robotd`, `padd` e `mediad`** | Adaptações do runtime oficial 0.15.1 para o barramento de servos Feetech HD-1910, módulo IMU I²C, fusão do giroscópio e controle UDP | Código-fonte em [fanhao375/Microduck-kissqy](https://github.com/fanhao375/Microduck-kissqy). A branch e o commit usados na imagem estão nas [instruções de construção](image/README.md). Os binários já vêm na imagem de réplica. | Apache-2.0. |
| **Modelos de marcha e movimentos** | Quatro modelos para caminhar, sentar e levantar, abaixar a cabeça para pegar objetos, dar cambalhota, chutar com os dois pés e usar as rodas | Incluídos na imagem de réplica. Veja a função de cada modelo, o botão correspondente e os créditos em [descrição dos modelos](image/overlay/usr/share/doc/microduck/模型说明.txt). | Licenças pessoais e não comerciais dos autores; **não são licenças de código aberto**. Não distribua com produtos pagos. |
| **Projeto de treinamento** | Treinamento em simulação para HD-1910 | [`training/`](training/). | Código Apache-2.0; malhas 3D CC BY-NC-SA. |
| **Microduck Training Studio** | Ambiente web de treinamento no computador para gerenciar experimentos, ver curvas, avaliar e exportar modelos | [`training-studio/README.md`](training-studio/README.md). É executado separadamente do Studio instalado no robô. | Código Apache-2.0; consulte as licenças de dependências e recursos no próprio diretório. |
| **servo-web (antigo)** | Bancada web para depuração de servos, usada em setembro antes da criação do Studio | [`tools/servo-web/`](../tools/servo-web/). | Apache-2.0. |

Encontre ferramentas independentes para testar servos, verificar a IMU e analisar a marcha no [índice de ferramentas](../tools/README.md). O [índice de hardware](../hardware/README.md) reúne as placas e o firmware.

## Treinamento em simulação para HD1910

**[`training/`](training/)** contém um projeto Python completo de treinamento: modelos, parâmetros LuwuDynamics 1910 M6, configurações de tarefas para HD1910, adaptação de inicialização do controlador Feetech, dependências fixadas e testes. Basta clonar este repositório; não é necessário baixar a branch `microduck_rl` separadamente.

[Início rápido](training/README.md) · [Instruções de execução e explicação dos problemas de inicialização](training/docs/hd1910-baseline.md) · [Origem e licenças](training/UPSTREAM.md). Esta é a base atual de integração com a simulação; o treinamento de marcha ainda não foi testado neste computador.

## Depuração da placa IMU sem o robô

O firmware STM32G031 + LSM6DSV16X e os materiais de hardware estão em [`hardware/imu_to_dxl/firmware/`](../hardware/imu_to_dxl/firmware/). A visualização da orientação foi integrada à [`tools/servo-web/`](../tools/servo-web/). Execute `python server.py --port COM5 --imu-jlink imu-jlink.json`: o mesmo modelo recebe os ângulos das juntas dos servos e a orientação do tronco lida pelo J-Link. Se estiver apenas com a placa, use `--fake` no lugar dos parâmetros da porta serial.

**Escopo já verificado: firmware e simulação, além de observação na bancada SWD.** O código-fonte 0.2.0 incluído implementa o protocolo Feetech SCS/STS, ID 200, bloco de 15 bytes no endereço 56 e fila de leitura síncrona. Os testes do host e a simulação do barramento estão registrados em [`VALIDATION.md`](../hardware/imu_to_dxl/firmware/VALIDATION.md). Há registros de gravação e observação da IMU em uma placa real, mas ainda não foram concluídas a validação do barramento misto real, a temporização de resposta e liberação, nem a validação com o robô completo. As notas antigas que diziam que a implementação continuava na base Dynamixel e não cumpria o contrato estão desatualizadas; elas não devem ser confundidas com a validação ainda pendente no barramento real.

## Histórico: primeiro backend Feetech, de setembro (não utilizado)

> O programa principal em uso hoje é o fork mencionado na visão geral acima. A seção abaixo descreve o primeiro backend Feetech, escrito em setembro sobre a versão oficial 0.14.1. Ele não foi testado em uma placa e está mantido apenas como referência.
>
> [`fanhao375/microduck` · branch `feetech`](https://github.com/fanhao375/microduck/tree/feetech): atualizada em relação à versão oficial **0.14.1**; todos os testes dos três crates passaram (duck-control 80 / robotd-params 151 / robotd 93).

| Arquivo | Linhas | Implementação |
|---|---:|---|
| [`duck-control/src/bus_feetech.rs`](https://github.com/fanhao375/microduck/blob/feetech/duck-control/src/bus_feetech.rs) | 744 (novo) | **Implementação principal de `FeetechIo`:** um `sync_read` por ciclo no endereço 56 com 15 bytes; conversão da posição com tabela de direção; limites para os alvos; `set_gain` grava somente P (Feetech não tem um equivalente direto para I/D); `reboot` desliga o torque antes do comando `0x08`; na inicialização, verifica ordem de bytes END, nível de resposta, modo de operação, baud rate e fase; `imu_ready()` sempre retorna false. Inclui 11 testes unitários. |
| [`duck-control/src/bus_select.rs`](https://github.com/fanhao375/microduck/blob/feetech/duck-control/src/bus_select.rs) | 149 (novo) | Enumeração `AnyBus` para escolher um dos dois backends. `Box<dyn RobotIo>` não compila; veja o motivo na seção 3.1 do [documento de arquitetura](飞特适配架构.md). |
| `robotd-params/` | +50 | Adiciona `[bus] protocol = "dynamixel2" \| "feetech-sts"` e `[bus.feetech] p_scale / directions` e registra os campos no sistema de parâmetros. |
| `robotd/src/main.rs` | +63 | Troca `BusIo` por `AnyBus`, passa o protocolo ao abrir o barramento e informa diretamente parâmetros inválidos, sem tentar novamente. |
| `duck-control/src/model.rs` | +8 | Valor esperado do modo de operação de fábrica 4 do HD-1910. |
| `deploy/robotd.toml` | — | Adiciona duas chaves e os comentários correspondentes. |

Para compilar, é necessário ter Rust instalado:

```bash
git clone -b feetech https://github.com/fanhao375/microduck.git
cd microduck && cargo test -p duck-control -p robotd-params -p robotd
```

**Por que manter isso no fork em vez de copiar para este repositório:** `FeetechIo` é um arquivo do crate `duck-control` no workspace Rust oficial. Ele usa o trait oficial `RobotIo`, o tipo genérico `Safety<T>` e o sistema de parâmetros; copiado isoladamente, não compila. Na branch do fork, `git rebase` permite acompanhar as atualizações oficiais — em 2026-09-20, foram integrados 55 commits sem conflitos — e, no futuro, também será possível enviar um PR ao projeto oficial. O runtime oficial usa Apache-2.0, e manter as alterações no fork deixa a origem clara.

| Arquivo | Conteúdo |
|---|---|
| [`飞特适配架构.md`](飞特适配架构.md) | Arquitetura existente do runtime oficial (pontos de integração, trabalho a cada ciclo e sequência de inicialização), diferenças entre os dois fabricantes de servos, plano de adaptação, **arquitetura do firmware da placa `imu_to_dxl` (§4)**, testes de bancada, itens a investigar, relação entre construção, implantação e política, modos de falha e registros de revisão. |

O contrato de interface do firmware da placa — bloco de 15 bytes, temporização, regras de fila e testes de aceitação — está documentado separadamente em [`hardware/imu_to_dxl/总线协议.md`](../hardware/imu_to_dxl/总线协议.md). A ferramenta correspondente é [`tools/imu200/`](../tools/imu200/), com placa simulada, vetores de teste e validação na placa real.

As instruções para gravar a placa e instalar o runtime oficial estão em [Sem HAT](../docs/不打HAT.md) e em [`tools/radxa/`](../tools/radxa/).

Os documentos oficiais Feetech sobre o protocolo e as tabelas de memória (cópias da edição de 2026) estão em [`docs/飞特资料/`](../docs/飞特资料/).

Antes de alterar o código, confirme a comunicação com os servos: [`tools/servo-web/`](../tools/servo-web/) é uma bancada web conectada à porta serial. Ela permite arrastar os controles, consultar as respostas, exportar os registradores e ver o pato 3D acompanhar os movimentos; os itens 0 a 8 da lista de bancada do documento de arquitetura usam essa ferramenta.
