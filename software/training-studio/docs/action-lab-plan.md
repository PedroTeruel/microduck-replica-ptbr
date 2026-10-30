# Plano de implementação do Laboratório de Ações

> **Para agentes de implementação:** execute as tarefas deste plano e faça revisões independentes da especificação e da qualidade.

**Objetivo:** permitir que o usuário configure uma meta de equilíbrio em uma perna na interface de treinamento existente, usando o mecanismo real para treinar, avaliar, salvar e exportar.

**Arquitetura:** uma tarefa HD1910 dedicada controla a ação física. O serviço envia um conjunto limitado de parâmetros de habilidade ao treinamento, à avaliação e à exportação e os registra. A interface Preact ganha um painel com configuração visual. Uma lista de permissões de receitas define os caminhos dos experimentos, e as regras existentes de propriedade dos processos continuam valendo.

**Tecnologias:** serviço na biblioteca padrão do Python 3.12, mjlab 1.3.0 / rsl-rl 5.0.1, CUDA no WSL2, Preact/Three.js, unittest/pytest/Node/Playwright.

## 1. Ambiente e linha de base

- [x] Criar um espaço de trabalho separado a partir de `9d0fe05`, mantendo o serviço estável na porta 8094.
- [x] No backend Windows, 56 testes (53 aprovados, 3 ignorados); no Node, 11 testes aprovados.
- [x] Criar o ambiente virtual offline em `/root/.cache/microduck-action-lab-20261023`, apontando o modo editável para o novo espaço de trabalho, sem alterar o ambiente estável.

## 2. Novo mecanismo de equilíbrio

Arquivos: `software/training/src/mjlab_microduck/tasks/microduck_balance_env_cfg.py`, `tasks/mdp.py`, `tasks/__init__.py`, `scripts/export.py`; novos testes em `tests/test_balance_cfg.py` e `tests/test_balance_mdp.py`.

- [x] Escrever primeiro testes para configuração, fases, perna esquerda/direita, parâmetros inválidos e critérios de sucesso; confirmar que a nova tarefa falha por ainda não existir.
- [x] Implementar comandos dedicados, aplicação de parâmetros, recompensa, contagem de sucessos e configuração física HD1910 correta. Os campos são `support_side`, `lift_height_m` e `hold_seconds`.
- [x] Validar pela CLI real que os parâmetros alteram a configuração do ambiente e que avaliação e exportação usam a mesma função de aplicação.
- [x] Executar testes em CPU e medir geometria e postura para registrar os limites de viabilidade da meta. Os testes devem verificar que levantar o pé depois de cair não conta como sucesso, que a troca entre esquerda e direita funciona e que é preciso apoiar o pé novamente após completar o tempo de sustentação.

## 3. Integração de receitas e parâmetros no serviço

Arquivos: `training_studio/config.py`, `commands.py`, `service.py`, `environment.py`, `evaluate.py`; novo teste em `tests/test_skills.py`.

- [x] Com um subprocesso de demonstração real em CPU, confirmar que alterar os parâmetros da habilidade impede a qualificação para treinamento real; registros antigos de caminhada continuam válidos e parâmetros inválidos não iniciam processos.
- [x] Fazer `validate_skill(recipe_id, value)` retornar parâmetros normalizados ou None. `experiment_for(run)` consulta apenas a lista de permissões do servidor e valida o ID da tarefa. Todos os caminhos de logs e checkpoints passam por essa validação.
- [x] Manter os mesmos parâmetros de habilidade ao criar e retomar registros, gerar ZIPs de origem e avaliar. O comando real usa somente opções fixas e valores validados.
- [x] Avaliar ciclos completos com várias tentativas, salvar cada resultado e suas estatísticas por item; mostrar o resumo abaixo do checkpoint selecionado. Resultados de falha também devem aparecer.
- [x] Executar todos os testes de backend no Windows e WSL e os testes de integração da transmissão de parâmetros ao mecanismo.

## 4. Operação sem código na mesma interface

Arquivos: `web/skillform.js`, `state.js`, `newrun.js`, `views.js`, `ui.js`, `styles.css`, `tests/state.test.mjs`.

- [x] Escrever primeiro testes Node para normalização de parâmetros, correspondência do teste curto, conversão de unidades e resumo.
- [x] Adicionar à página inicial a entrada para o Laboratório de Ações, novas receitas e controles básicos de habilidade com limites fornecidos pelo backend; preservar rascunhos por receita.
- [x] Reutilizar o Duck3D para exibir um diagrama dos objetivos com rótulos claros. Não inventar valores cinemáticos em centímetros a partir do desenho. Mostrar instruções para todas as fases e identificar a perna esquerda ou direita em texto.
- [x] Remover a exibição fixa incorreta que tratava toda receita que não fosse rough como terreno plano. Detalhes do experimento, cópia, comparação e avaliação de checkpoints mostram a meta de ação e o resultado correspondentes.
- [x] Testar no navegador em larguras de 1440 e 390 px: configuração da ação, troca de receita, rascunhos, bloqueio ao mudar parâmetros, envio de parâmetros, detalhes e distinção entre resultados reais e de demonstração, sem transbordamento nem erros de página.

## 5. Validação real e entrega

- [x] Fazer revisão independente da especificação e depois da qualidade do código; corrigir os problemas encontrados.
- [x] Isolar o estado do novo serviço e iniciar pelo navegador um teste curto real de equilíbrio com 64 ambientes e 5 iterações; verificar logs, PT e YAML da configuração da ação.
- [x] Avaliar várias execuções do ciclo completo da ação, reproduzir o vídeo e exportar ONNX; verificar entradas, saídas, valores finitos e consistência entre PT e ONNX.
- [x] Se o teste curto comprovar apenas o fluxo, informar claramente a taxa de sucesso e preservar o modelo do experimento, sem afirmar que a ação foi aprendida. Se for necessário ajustar a recompensa, consultar primeiro as falhas medidas.
- [x] Atualizar o guia de uso e o registro de validação, integrar ao espaço de trabalho estável após o commit, preservar alterações do usuário e trocar o serviço somente depois de confirmar que não há tarefas ativas.
