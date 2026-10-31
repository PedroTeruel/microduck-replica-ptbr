# Treinamento em simulação Microduck HD1910

O código de treinamento para Feetech HD-1910, os modelos, parâmetros, lock de dependências e testes são mantidos neste diretório. Clone ou baixe `microduck-replica` para obter o projeto completo; não é necessário buscar uma branch de treinamento nem inicializar submódulos.

O projeto usa os **parâmetros BAM M6 públicos para 1910 da [LuwuDynamics](src/mjlab_microduck/robot/hd1910/README.md)**. A estrutura de treinamento e a geometria Microduck vêm de [Pollen Robotics](https://github.com/pollen-robotics/microduck_rl); o modelo do atuador vem de [Rhoban/BAM](https://github.com/Rhoban/bam). Os parâmetros não foram identificados por este projeto. Este repositório adiciona configurações de tarefa HD1910, adaptação da inicialização do controlador Feetech e testes de regressão.

## Início rápido

Use Linux com GPU NVIDIA/CUDA ou WSL2 configurado para GPU; é necessário Git e [uv](https://docs.astral.sh/uv/). No terminal Linux/WSL, execute:

```bash
git clone https://github.com/fanhao375/microduck-replica.git
cd microduck-replica/software/training
uv sync --frozen --python 3.12

# Faça primeiro um teste curto, com 64 ambientes e 5 iterações
uv run --frozen train Mjlab-Velocity-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.logger tensorboard
```

Se o repositório já foi baixado, entre diretamente em `software/training/` para instalar e executar. A submissão opcional pela nuvem HF Jobs exige um clone Git para empacotar o código de acordo com as regras de exclusão do Git; para o treinamento local acima, também é possível usar o ZIP baixado. Logs e checkpoints ficam em `logs/rsl_rl/microduck_hd1910_velocity/` e não são distribuídos com o código-fonte. Cinco iterações verificam carregamento, execução de passos e salvamento, mas não bastam para aprender a caminhar.

| Tarefa | Uso |
|---|---|
| `Mjlab-Velocity-Flat-MicroDuck-HD1910` | Velocidade em piso plano para HD1910 |
| `Mjlab-Velocity-Rough-MicroDuck-HD1910` | Velocidade em terreno irregular para HD1910 |

Este projeto é uma linha de base de integração à simulação; ainda não há uma política de caminhada medida e aprovada nesta máquina. Massa e inércia continuam usando os valores da simulação Microduck original. Será necessário ajustá-las com medições dos servos Feetech reais e conferir zeros, direções, limites, alimentação, IMU e temporização da comunicação.

## Instruções e testes

- [Instruções, registro de validação e explicação do problema de inicialização](docs/hd1910-baseline.md): o item ausente é o histórico de ângulos-alvo do controlador Feetech; a correção não altera os parâmetros M6 de terceiros.
- [Origem, versões fixadas e licenças](UPSTREAM.md).
- [README do projeto de treinamento original](README.upstream.md): preserva as instruções de tarefas e ferramentas upstream; a tarefa padrão é destinada a XL330, enquanto a versão Feetech usa a entrada HD1910 indicada na tabela acima.

Execute neste diretório os testes de integração e regressão (incluindo passos na GPU):

```bash
uv run --frozen --with pytest python -m pytest -q \
  tests/test_hd1910_cfg.py tests/test_hd1910_rollout.py \
  tests/test_ground_pick_cfg.py tests/test_nan_guard.py tests/test_obs_nan_guard.py \
  tests/test_hf_source_snapshot.py
```

A exportação de políticas usa `scripts/export.py`, que incorpora ao ONNX a normalização das observações. Checkpoints de testes curtos servem para validar o fluxo e não devem ser distribuídos como marcha aprovada para o robô real.

## Licença

O código, as configurações, os parâmetros e a documentação deste diretório usam [Apache-2.0](LICENSE), preservando as atribuições de terceiros. **O modelo 3D e as malhas seguem a licença CC BY-NC-SA declarada pelo upstream**; sua inclusão neste repositório não os converte para Apache-2.0. Consulte [UPSTREAM.md](UPSTREAM.md) e o [NOTICE.md](../../NOTICE.md) da raiz.
