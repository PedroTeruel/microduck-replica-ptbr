# Como adicionar uma receita de ação

O Laboratório de Ações é a biblioteca de receitas da interface de treinamento. Atualmente, os mantenedores do repositório adicionam tarefas por meio do código e de pull requests. O usuário escolhe uma receita na página, configura os parâmetros e inicia o treinamento. Envio pela web, download remoto, instalação automática e sistema de contas da comunidade ainda não foram implementados.

## O que o autor deve fornecer

Uma receita de ação precisa incluir:

1. Meta da ação, estado inicial e final e condições de falha.
2. Modelo de robô, servos e versões do mecanismo compatíveis.
3. Uma tarefa de treinamento registrada de verdade, regras de recompensa e término, valores padrão razoáveis e um diretório de experimento separado.
4. Tipos, limites e unidades dos parâmetros editáveis. Os parâmetros devem ser usados no treinamento, na retomada, na avaliação e na exportação.
5. Método para avaliar o ciclo completo e critérios de sucesso. A recompensa acumulada não substitui a confirmação de que a ação foi concluída.
6. Testes, registro do teste curto, vídeo original e limitações conhecidas. Se ainda não houver uma reprodução real, podem ser fornecidas instruções em texto.
7. Autor, origem do código, licença e versão. Pesos treinados são um artefato opcional separado e devem identificar a receita e a meta correspondentes.

## Onde incluir a receita

As tarefas do mecanismo ficam em `software/training/src/mjlab_microduck/tasks/` e devem ser registradas no catálogo de tarefas. A interface usa a lista de permissões no servidor em `software/training-studio/training_studio/config.py`; ela não aceita nomes de tarefas ou scripts arbitrários enviados pela página.

O exemplo existente de equilíbrio em uma perna usa `balance_parameters.py`, `microduck_balance_env_cfg.py`, funções correspondentes em `mdp.py` e seus testes. Outros tipos de ação precisam implementar validação de parâmetros adequada e transmiti-los pela CLI; não devem reutilizar sem adaptação os três campos do equilíbrio em uma perna.

Os metadados `catalog` de cada receita definem sua exibição no Laboratório de Ações:

| Campo | Uso |
| --- | --- |
| `category` | Categoria da página, como caminhada ou equilíbrio |
| `tags` | Termos usados na busca |
| `preview_kind` | Tipos aceitos atualmente: `robot_model`, `balance_target`, `text` |
| `source_label` | Descrição da origem no cartão; não substitui autoria no código nem a licença |
| `verification_state` / `verification_label` | Estado da validação e rótulo legível para o usuário |
| `instructions` | Instruções breves ou descrição da meta da ação |

Modelos 3D e diagramas de metas devem ser identificados como conteúdo que não representa resultados de treinamento. Para adicionar vídeos ou imagens de prévia no futuro, também será necessário registrar a política real, a meta, as condições e a origem. Uma animação demonstrativa não pode ser apresentada como vídeo de sucesso do treinamento.

## Revisão e exibição do estado de validação

Revise primeiro o hardware e a interface da tarefa. Depois execute os testes em CPU, um teste curto com 64 ambientes e 5 iterações, a avaliação do ciclo completo da ação e a verificação da exportação. A página deve distinguir:

- **Ainda não validado:** a tarefa e as instruções existem, mas ainda não há evidências de validação correspondentes.
- **Teste curto aprovado:** o fluxo de treinamento e geração de artefatos foi executado; isso não significa que a ação foi aprendida.
- **Resultado da validação da ação:** informa o número de sucessos e tentativas sob metas e condições fixas, além das falhas encontradas.
- **Resultado da validação no robô real:** registra separadamente o hardware, a interface de implantação e as evidências medidas.

Atualmente, a página inclui três receitas internas do projeto. O equilíbrio em uma perna passou por um teste curto real, mas a taxa de sucesso da política em 5 iterações foi 0/8. O treinamento em terreno irregular ainda não foi validado com GPU neste projeto. Futuras receitas da comunidade devem seguir os mesmos critérios de evidência.
