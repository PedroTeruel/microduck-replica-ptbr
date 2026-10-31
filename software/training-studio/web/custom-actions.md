# Laboratório de Ações: comece com sua primeira ação

Para: HD1910 Microduck · 23/10/2026

## 1. Primeiros passos

Abra “Laboratório de Ações” pela navegação lateral ou pela página inicial do Studio. Essa biblioteca independente de receitas permite buscar, filtrar por categoria e consultar prévias ou instruções em texto. Escolha “Equilíbrio em uma perna” e comece com a meta recomendada: **apoio na perna esquerda, elevar a outra perna 1 cm e sustentar por 3 segundos**. Esquerda e direita são sempre relativas ao robô.

1. **Escolha a meta da ação.** Ajuste a perna de apoio, a altura de elevação e o tempo de sustentação. O modelo 3D ajuda a entender a meta; não é uma simulação física nem um resultado de treinamento.
2. **Clique em “Iniciar teste curto”.** São usados 64 ambientes e 5 iterações para confirmar que o ambiente, o treinamento e o salvamento funcionam. Algumas iterações geralmente não bastam para aprender a ação.
3. **Depois que o teste curto passar, inicie o treinamento real.** Você pode manter os parâmetros recomendados. O progresso em iterações indica quanto do cálculo foi concluído, não quanto a ação foi aprendida.
4. **Selecione um checkpoint e clique em “Avaliar”.** A avaliação do equilíbrio executa oito tentativas, cada uma com preparação, elevação, sustentação e apoio do pé. Confira o número de sucessos e a reprodução real.
5. **Ajuste com base no vídeo.** Comece com pouca elevação e sustentação curta. Se mudar a meta, execute outro teste curto. Salve experimentos separados para comparar metas e resultados.

Sem um vídeo de avaliação de checkpoint, girar o pato 3D não permite saber se ele aprendeu. A demonstração usa dados sintéticos e serve apenas para conhecer a interface; para treinar a ação, use o modo real com GPU.

### Modelos treinados e V8 oficial

A aba “Modelos pré-treinados” do Laboratório de Ações reúne a coleção oficial de políticas V8 e os modelos HD1910 do lançamento kissqy V167. Pesquise por origem, tipo de ação ou palavras-chave. Os detalhes mostram versão, hardware, identificador do checkpoint, link de obtenção e licença. Alguns pesos kissqy estão dentro do pacote completo de lançamento; os detalhes indicam sua localização no pacote.

**A coleção oficial de políticas chegou à V8, mas novos experimentos neste Studio ainda começam do zero; o V8 não é carregado automaticamente.** O manifesto oficial V8 se destina a XL330, enquanto os modelos treinados por kissqy se destinam a HD1910. Não se deve trocar esses pesos só porque os nomes ou dimensões de entrada coincidem. O modelo padrão VelStand do V8 combina caminhada, postura parada e recuperação após queda; a coleção também mantém modelos antigos separados de caminhada e postura. [Manifesto oficial V8](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json)

“Obter ONNX” abre o arquivo de pesos do publicador; “Ver pacote de lançamento” abre a página do pacote original. Nenhuma dessas opções instala o modelo nem altera o robô. O catálogo atual não oferece simulação local, avaliação ou retomada de treinamento para modelos externos. ONNX serve para inferência e não contém o estado completo do treinamento PPO. Para continuar um treinamento, são necessários checkpoints PT compatíveis, configuração, normalização e outros dados; não basta enviar ONNX como se fosse o mesmo arquivo.

### Recursos exibidos durante o treinamento

“Recursos do executor” nos detalhes mostra modelo, uso, temperatura e memória da GPU; modelo, uso e temperatura da CPU; e uso da memória RAM. A atualização ocorre aproximadamente a cada três segundos, e a interface explica quando não consegue ler um campo. A temperatura da CPU normalmente não está disponível no WSL. CPU e memória representam o que a máquina virtual consegue acessar; a GPU mostra o uso da placa inteira, incluindo outros processos. Ao abrir um experimento encerrado, os recursos ainda mostram o estado atual da máquina, e não o consumo histórico daquele treinamento.

Iterações e velocidade de amostragem vêm do log do experimento. Logo após a inicialização, antes da primeira iteração aparecer, ainda não há uma taxa de processamento. Ao encerrar o experimento, a última métrica registrada permanece disponível. Número de iterações não equivale a passos da simulação física nem à taxa de sucesso da ação.

## 2. O que significam as três opções

| Opção | Faixa atual | Significado |
| --- | --- | --- |
| Perna de apoio | Esquerda / direita | É a perna que permanece no chão enquanto a outra se eleva |
| Altura de elevação | 0,5–2 cm | Distância desejada entre a sola do pé elevado e o chão |
| Tempo de sustentação | 1–5 segundos | Tempo mantendo a postura estável; não é a duração total da ação |

A sequência é: preparação com os dois pés → elevação → sustentação → apoio e recuperação com os dois pés. O ciclo completo dura aproximadamente o tempo de sustentação mais 3,5 segundos. Esse é o objetivo da tarefa; a política encontra como controlar as articulações, não copia a pose da prévia.

Esta é uma **receita experimental de simulação**. O modelo comporta as alturas de elevação indicadas, mas isso não prova que a política consiga manter o equilíbrio nem que o hardware real tenha o mesmo comportamento. Massa, inércia, alimentação e erros dos servos também afetam o resultado. Um perfil de pato importado fica salvo para consulta; o sistema não altera automaticamente o modelo físico.

## 3. Como saber se a ação foi aprendida

Uma curva de recompensa crescente indica que a política está se aproximando da pontuação de treinamento. A avaliação da ação também verifica se o pé designado permanece apoiado, se o outro pé sai do chão, se a postura e a velocidade do corpo ficam controladas pelo tempo necessário e se o robô termina recuperado sobre os dois pés. Ficar com o pé suspenso depois de cair, levantá-lo apenas por um instante ou cair após a sustentação não conta como sucesso completo.

O relatório preserva o resultado, o tempo de sustentação e a causa de falha de cada tentativa, com vídeo de todas elas. **Um resultado de 0/8 também é mostrado sem ocultação.** Oito tentativas formam uma amostra pequena para repetir a verificação; antes da implantação, ainda são necessárias validações com mais posturas iniciais, perturbações e hardware real.

| O que aparece no vídeo | Próximo passo |
| --- | --- |
| Cai logo no começo | Confira o modelo, a tarefa e os valores; não aumente apenas o número de iterações |
| Fica em pé, mas não levanta o pé | Confira a meta e o progresso do treinamento; tente uma meta de elevação menor |
| Abaixa o pé logo depois de levantá-lo | Reduza primeiro o tempo de sustentação e confira o apoio e a inclinação do corpo |
| Sustenta, mas cai ao apoiar o pé | A fase de retorno ainda não foi aprendida; o ciclo completo conta como falha |
| A pontuação é alta, mas o movimento está errado | Preserve o vídeo e a configuração, ajuste as regras da tarefa e não use a pontuação como substituto da avaliação |

Pausar mantém os processos e a memória da GPU. Fechar o navegador não encerra o treinamento; pausar também não desliga o computador em nuvem nem interrompe a cobrança da plataforma. Depois de encerrar, é possível continuar a partir de um checkpoint salvo.

## 4. Como experimentar outras ações

**Não é preciso começar aprendendo a programar nem usando uma IA.** Para ações já integradas, basta escolher uma receita, ajustar parâmetros, executar o treinamento e assistir à avaliação. Uma ação totalmente nova precisa ser integrada às regras do mecanismo; ainda não é possível descrever uma ação em uma frase e pedir que o sistema treine qualquer movimento automaticamente.

A direção futura do Laboratório de Ações é uma **biblioteca comunitária de receitas**. Autores definirão a meta da ação, as regras de treinamento e o método de validação; após revisão, a receita será incluída para que outras pessoas possam selecioná-la e ajustar parâmetros. Atualmente há três receitas de treinamento internas e vinte modelos pré-treinados do upstream. Os modelos são obtidos dos publicadores originais; envio pela comunidade e instalação automática ainda não estão implementados.

| Ideia | Opção atual ou próximo passo |
| --- | --- |
| Apoiar na perna esquerda ou direita e variar altura e duração | Equilíbrio em uma perna no Laboratório de Ações |
| Caminhar no plano ou adaptar-se a terreno irregular | Receitas existentes de caminhada |
| Mover a cabeça, acenar ou executar uma sequência fixa | Pode ser feito com uma coreografia de keyframes de articulação; este Studio ainda não inclui esse editor |
| Pular e aterrissar em pé | Ainda não integrado; primeiro valide os limites dos servos e as condições de aterrissagem |
| Girar exatamente uma volta e parar | Ainda não integrado; exige acompanhar o ângulo acumulado e definir a condição de parada |
| Enviar um vídeo de dança para o pato imitar | Ainda não suportado; requer mapeamento de movimentos e treinamento por imitação |

Ao descrever uma ação nova, especifique: **pose inicial → movimento de cada parte → duração → pose final → condições de falha**. Exemplo: “Comece de pé com os dois pés no chão, apoie na perna direita, levante a esquerda 1 cm por 2 segundos e termine de pé sobre os dois pés; não use a cabeça para se apoiar no chão”.

## 5. Como o projeto oficial treina

O projeto oficial usa aprendizado por reforço PPO. Ele experimenta movimentos em muitas simulações, ajusta a política com base nas recompensas e depois exporta ONNX. Para desenvolver uma ação, comece por uma tarefa semelhante, confirme as condições físicas, defina a meta e os critérios de avaliação e execute um teste curto. [Projeto oficial](https://github.com/pollen-robotics/microduck_rl) · [Guia oficial de desenvolvimento](https://github.com/pollen-robotics/microduck_rl/blob/develop/AGENTS.md#building-a-new-env--the-workflow)

O Studio transforma tarefas implementadas em receitas selecionáveis. O equilíbrio em uma perna é uma tarefa experimental HD1910 criada neste repositório. O projeto oficial também tem tarefas SitStand, StandUp, BallKick e Roulade, mas elas precisam ser adaptadas a HD1910. A tarefa Spin usa um modelo com pés de roda e não pode ser aplicada diretamente aos pés atuais. [Registro oficial de tarefas](https://github.com/pollen-robotics/microduck_rl/blob/develop/src/mjlab_microduck/tasks/__init__.py)

## 6. Avançado: adicionar uma ação

Se você só quer experimentar as ações existentes, pode pular esta seção.

1. Meça o modelo, a faixa das articulações, os atuadores e os contatos. Confirme que a meta é alcançável e valide a estabilidade após perturbações.
2. Reutilize a configuração de atuadores e a interface de observação HD1910; crie uma tarefa e um nome de experimento separados.
3. Defina o comando da meta, as recompensas e as condições de falha. A condição de sucesso deve ser independente da recompensa e incluir a fase final de recuperação.
4. Teste a configuração, as pernas esquerda/direita, valores de limite e se movimentos incorretos são rejeitados como sucesso.
5. Execute 64 ambientes por 5 iterações e confira logs, checkpoints, avaliação do ciclo completo e exportação.
6. Comece com uma meta fácil e só aumente a dificuldade depois de avaliar o vídeo.
7. Integre parâmetros de ação limitados e garanta que treinamento, retomada, avaliação e exportação usem a mesma meta.

Os caminhos abaixo são relativos a `software/training/`:

| Arquivo | Função |
| --- | --- |
| `src/mjlab_microduck/balance_parameters.py` | Parâmetros, ciclo, critérios de sucesso e contrato dos comandos |
| `src/mjlab_microduck/tasks/microduck_balance_env_cfg.py` | Ambiente de equilíbrio HD1910 e configuração do experimento |
| `src/mjlab_microduck/tasks/mdp.py` | Comando, recompensa e medições físicas |
| `src/mjlab_microduck/tasks/__init__.py` | Registro da tarefa |
| `scripts/export.py` | Preserva a normalização das observações e exporta a meta |

A receita do Studio fica em `software/training-studio/training_studio/config.py`. Logs e checkpoints são resolvidos por diretório de receita; adicionar apenas um cartão na página não cria uma ação treinável.

## 7. Teste curto pela linha de comando

Este procedimento requer dependências preparadas no Linux/WSL2 e deve ser executado em `software/training/`. Os comandos abaixo usarão a GPU de verdade.

```bash
uv run --frozen list-envs

uv run --frozen train Mjlab-Balance-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.save-interval 1 --agent.logger tensorboard \
  --env.commands.twist.support-side left \
  --env.commands.twist.lift-height-m 0.01 \
  --env.commands.twist.hold-seconds 3
```

As dependências locais estão fixadas em mjlab 1.3.0; consulte `UPSTREAM.md` para a versão upstream. Os nomes de tarefas na documentação online mais recente não garantem suporte local; use a saída atual de `list-envs`.

## 8. O que falta depois da exportação

O pacote exportado preserva o checkpoint, a meta da ação, a configuração de treinamento, as evidências de avaliação e o ONNX com normalização das observações. A política de equilíbrio continua usando **observação de 61 dimensões, ação de 14 dimensões e 50 Hz**, mas o significado dos comandos mudou.

**Dimensões iguais não significam compatibilidade direta com o controlador de caminhada existente.** O lado de implantação precisa interpretar o contrato de comandos do pacote para fornecer a perna de apoio, a meta de elevação e a fase da ação, além de conferir a ordem das articulações, os zeros e as saídas. A implantação do equilíbrio em uma perna ainda não foi validada em hardware real. Primeiro confirme os resultados em simulação e depois faça um teste físico controlado.
