# Linha de base de treinamento em simulação HD1910 M6

Esta linha de base usa **parâmetros de dinâmica BAM M6 para 1910 publicados por [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)**; os dados não foram identificados por este projeto. O [registro de origem](../src/mjlab_microduck/robot/hd1910/README.md) inclui o commit fixado, SHA-256 do arquivo original, configuração associada e cópia da licença Apache-2.0. Agradecemos o trabalho de código aberto de LuwuDynamics, [Pollen Robotics](https://github.com/pollen-robotics/microduck_rl) e [Rhoban/BAM](https://github.com/Rhoban/bam).

## Conteúdo integrado

| Item | Configuração atual |
|---|---|
| Tarefa em piso plano | `Mjlab-Velocity-Flat-MicroDuck-HD1910` |
| Tarefa em terreno | `Mjlab-Velocity-Rough-MicroDuck-HD1910` |
| Parâmetros dos servos | `1910_m6.json` da LuwuDynamics, preservado sem alterações |
| Ganho/tensão | `kp_fw=5`; tensão aleatória de 7,4–8,0 V, queda mínima de 7,0 V |
| Atraso de controle | 3–6 passos de simulação; passo atual de 5 ms, ou 15–30 ms |
| Interface da política | 50 Hz, observação de 61 dimensões, ação de 14 dimensões; ordem original Microduck preservada |
| Modelo | Geometria, massa, inércia e postura padrão Microduck locais |
| Logs | Diretório separado `microduck_hd1910_velocity`, TensorBoard local por padrão |

As tarefas de treinamento XL330 originais continuam disponíveis. A configuração de fábrica Microduck é copiada e o atuador é substituído por HD1910, sem afetar as outras tarefas. O modelo de 0,8 kg do XgoDuck, zeros do codificador, direção e ONNX não foram copiados para este projeto. Massa e inércia da simulação ainda são as do Microduck original; deverão ser corrigidas com medições do hardware Feetech real.

### Correção de compatibilidade local

A correção é para inicializar o estado de execução do controlador de simulação. Ela não reinicializa a rede neural nem ajusta novamente os parâmetros dos servos. O modelo Feetech usa `q_target_smooth` para armazenar os ângulos-alvo da etapa anterior e limitar a variação do alvo por passo. Esse histórico precisa existir antes do primeiro cálculo.

No BAM `62bd8ce` fixado, `q_target_smooth` do controlador Feetech só era criado ao ler logs de identificação; o treinamento mjlab não usa esse fluxo. A simulação real na GPU reproduziu a ausência do campo durante o primeiro reset:

```text
AttributeError: 'STS3215Actuator' object has no attribute 'q_target_smooth'
```

`actuator/feetech_bam.py` agora inicializa o estado. No primeiro cálculo após cada reset, começa a limitação de velocidade do alvo a partir da posição articular atual daquele ambiente. Ao reiniciar um ambiente, somente o histórico dele é limpo; os outros ambientes paralelos mantêm seu próprio estado. Usar a posição atual como origem evita carregar para a nova tentativa o alvo da iteração anterior ou um ângulo zero genérico. A adaptação não altera os parâmetros da LuwuDynamics nem a instalação do BAM.

O problema foi reproduzido na combinação de BAM/mjlab fixada neste projeto; isso não implica que o runtime do robô real do upstream tenha o mesmo problema. Os testes de regressão cobrem inicialização, cálculos consecutivos e isolamento dos históricos após reset de um único ambiente.

## Obter o código

Código de treinamento, modelo e parâmetros estão reunidos em [microduck-replica/software/training](../README.md). Use Linux com CUDA ou WSL2 configurado para GPU e execute:

```bash
git clone https://github.com/fanhao375/microduck-replica.git
cd microduck-replica/software/training
uv sync --frozen --python 3.12
```

Se você já clonou ou baixou este repositório, entre em `software/training/`; não é necessário submódulo nem outro repositório de treinamento. Consulte [UPSTREAM.md](../UPSTREAM.md) para a versão importada e as licenças.

## Como executar

Execute os comandos abaixo dentro de `software/training/`; os logs são salvos ali por padrão:

```bash
# Lista as tarefas registradas
uv run --frozen list-envs

# Faz um teste curto do fluxo de treinamento e salvamento
uv run --frozen train Mjlab-Velocity-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.logger tensorboard --agent.run-name hd1910_m6_smoke

# Testes de integração e regressão, incluindo passos reais na GPU
uv run --frozen --with pytest python -m pytest -q \
  tests/test_hd1910_cfg.py tests/test_hd1910_rollout.py \
  tests/test_ground_pick_cfg.py tests/test_nan_guard.py tests/test_obs_nan_guard.py \
  tests/test_hf_source_snapshot.py
```

Por padrão, uv cria o ambiente em `software/training/.venv/`. Se o código estiver no disco do Windows, defina `UV_PROJECT_ENVIRONMENT` antes do primeiro `uv sync` para colocar o ambiente virtual no sistema de arquivos Linux do WSL; os comandos seguintes devem reutilizar esse mesmo caminho. A versão Feetech usa as tarefas HD1910 da tabela acima; as tarefas padrão do [README original](../README.upstream.md) destinam-se a XL330.

A submissão opcional pela nuvem `--hf-jobs` exige um checkout Git; o ZIP baixado serve somente para treinamento local. O pacote pós-migração usa o projeto de treinamento como raiz e não inclui outros diretórios do repositório, como hardware ou fotos. Esta rodada verificou o empacotamento local, sem submeter tarefas pagas à nuvem.

## Registro de validação

Em 24/09/2026, antes da migração, foi concluído no WSL Ubuntu 22.04, Python 3.12.14 e RTX 5060 Ti um teste curto PPO com 64 ambientes e 5 iterações, totalizando 7.680 passos de ambiente. `Episode_Termination/nan_state` ficou em zero em todas as iterações. Os logs confirmaram `kt=0.6238`, `R=4.9102` e 14 atuadores HD1910.

- Os 26 testes de configuração, regressão e passos na GPU passaram; incluem a verificação do histórico de alvos quando somente um ambiente é reiniciado.
- Um checkpoint do teste curto foi exportado para ONNX pelo exportador padrão do projeto, com a normalização das observações incorporada ao grafo.
- ONNX checker e inferência em CPU passaram: entrada `[1, 61]`, saída `[1, 14]`, valores finitos e metadados das articulações na ordem do Microduck local.
- mjlab emitiu um aviso de que a expressão ampla de correspondência de articulações também combinava com um site. A verificação encontrou 14 atuadores, sem adicionar atuadores de site. A expressão segue a convenção upstream `^(?!passive_).*`.
- Revisão independente de código conferiu ordem do reset, isolamento do histórico do alvo, isolamento da configuração XL330 original e validação da origem; não encontrou correções necessárias. Isso não substitui a validação de correspondência com o robô real.
- Medição de postura padrão: 4 ambientes, tensão fixa de 7,4 V, sem força externa e sem reset automático; perturbações iniciais de roll/pitch das articulações e do tronco de ±0,01 rad, sustentadas por 3 s. A inclinação máxima foi 4,47°/6,17°/5,94°/5,03° e a altura final do tronco ficou em cerca de 0,1153–0,1156 m. Esta amostra limitada não caiu, mas não prova estabilidade para qualquer tensão, perturbação ou hardware real.

Os scripts de medição, JSON, logs e artefatos de exportação foram preservados no diretório ignorado local `artifacts/hd1910/` antes da migração. O checkpoint curto ficou em `logs/rsl_rl/microduck_hd1910_velocity/2026-09-24_20-40-50_hd1910_m6_smoke/` daquele espaço de trabalho. Esses artefatos de validação local não foram distribuídos com o snapshot do código. O checkpoint é somente um artefato do teste de integração; ele não aprendeu a caminhar e não pode ser usado como marcha em um robô real.

### Revalidação após a migração para microduck-replica

No mesmo dia, foi criado um ambiente isolado no caminho `software/training/` usando o arquivo de lock, e a instalação foi concluída. Os 26 testes acima passaram novamente. Mais quatro testes offline de empacotamento passaram, cobrindo layout de repositório/projeto independente, alterações locais não enviadas, código-fonte novo e artefatos ignorados. O teste PPO de 64 ambientes e 5 iterações também foi concluído novamente, com 7.680 passos e `nan_state` igual a zero em todas as iterações; os parâmetros carregados permaneceram `kt=0.6238` e `R=4.9102`. SHA-256 do arquivo original e referência da origem coincidiram.

A revisão independente encontrou problemas no caminho de empacotamento HF Jobs e no texto da licença de geometria; outro revisor confirmou e as correções foram aplicadas. A revisão final não encontrou novos problemas executáveis. Nesta revalidação não foram repetidas a medição de postura nem a exportação ONNX; esses dados pertencem ao registro anterior à migração. Logs e checkpoint dessa nova execução continuam somente no diretório local ignorado.

## Quando o hardware real estiver disponível

Primeiro confira os 15 servos e conclua calibração individual de zero, direção e limites; depois conecte a IMU ao controlador. Registre P/D reais, modo de operação, alimentação e temporização do barramento e compare o modelo com pequenos testes de degrau. P=5 nesta linha de base é uma configuração de treinamento upstream; o firmware Arduino upstream usa P=6 e D=20 durante a execução. Não trate os dois conjuntos como parâmetros já validados para o mesmo hardware. Nesta rodada não houve conexão nem controle de um robô real e nenhuma EPROM foi gravada.

A política treinada pelo usuário e o modelo do servo são camadas distintas de origem. Enquanto estes parâmetros M6 forem usados, as publicações de modelo ou resultados de treinamento devem continuar atribuindo os parâmetros à LuwuDynamics.
