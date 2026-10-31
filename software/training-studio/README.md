# Microduck Training Studio

Painel visual de treinamento do Microduck. Por padrão, usa parâmetros recomendados; as opções avançadas podem ser expandidas. Oferece curvas de treinamento, modelo 3D, reprodução da avaliação de checkpoints, pausa/retomada, comparação de experimentos e exportação de artefatos.

A interface segue o estilo do Studio do robô: tons claros de cinza, identidade visual do pato, botões pretos e navegação inferior em celulares.

O Laboratório de Ações tem duas abas: **Receitas de treinamento** e **Modelos pré-treinados**. O catálogo fixo inclui dez modelos XL330 da coleção oficial V8 e dez modelos HD1910 de kissqy V167, com origem, hardware, versão, licença e link para obtenção no upstream. Modelos ONNX externos não são instalados, avaliados nem retomados automaticamente, e não são registrados como experimentos locais; novas receitas ainda começam o treinamento do zero. Alguns pesos comunitários só estão disponíveis no pacote de firmware completo do autor.

Os detalhes do treinamento exibem recursos atuais do executor, atualizados aproximadamente a cada três segundos: modelo/uso/temperatura/memória da GPU, modelo/uso/temperatura da CPU e memória RAM. Linux/WSL usam `/proc`, sensores de temperatura da CPU disponíveis e `nvidia-smi` com tempo limite; Windows usa contadores do sistema e ferramentas do driver. Não é necessário instalar dependências de monitoramento. Campos ausentes permanecem vazios e têm a causa indicada. Os valores representam o executor inteiro; CPU e memória do WSL refletem o que está visível no subsistema. Não representam consumo exclusivo nem histórico de um experimento.

O mecanismo de treinamento está em [`../training`](../training/README.md), e o controlador do robô está em [`../studio`](../studio/README.md). Este diretório é um serviço independente que usa o projeto de treinamento existente; não é necessário atualizar a imagem do robô.

## Experimente localmente

É necessário Python 3.12. O serviço usa somente a biblioteca padrão e a página não precisa ser compilada nem carrega dependências de CDN. Preserve o diretório vizinho `studio/web`, que fornece as bibliotecas e os modelos 3D distribuídos com o repositório.

```console
cd software/training-studio
python run.py --demo --open
```

No Windows, também é possível clicar duas vezes em `start-demo.cmd`; no Linux/macOS, execute `sh start-demo.sh`. Endereço padrão: <http://127.0.0.1:8093>.

O modo de demonstração inicia um subprocesso leve isolado e gera **métricas sintéticas, checkpoints textuais e uma reprodução ilustrativa em SVG claramente identificada** para demonstrar o fluxo da interface. Ele não treina uma política na GPU. O pacote exportado na demonstração contém apenas registros, sem pesos ONNX/PT implantáveis.

## Treinamento real

Use um computador Linux com GPU NVIDIA preparada ou Windows com WSL2, com este projeto de treinamento e as dependências fixadas pelo repositório. O modo real verifica o backend gráfico do MuJoCo, mjlab 1.3.0, CUDA e o registro da tarefa HD1910. Ele não instala pacotes automaticamente, não solicita computador em nuvem nem realiza pagamentos. Consulte [Teste curto local](docs/local-smoke.md) para as instruções locais.

```sh
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py
```

Em outro terminal local, encaminhe a porta (substitua o usuário e o endereço pelos dados do seu computador em nuvem):

```sh
ssh -N -L 8093:127.0.0.1:8093 usuario@endereco-do-computador
```

Depois, abra <http://127.0.0.1:8093>. Use `--training-root /caminho/software/training` para indicar o local do mecanismo e `--state-dir /diretorio-persistente/training-studio` para indicar onde salvar os registros. Fechar a página não interrompe o treinamento; **encerrar o serviço do Studio encerra os subprocessos que ele iniciou**. Para execuções longas, mantenha `run.py` ativo em um multiplexador de terminal ou gerenciador de serviços no computador em nuvem.

Por padrão, o serviço só aceita conexões locais. Se realmente precisar acessá-lo por outra rede, defina `STUDIO_ACCESS_TOKEN` e inicie com `--host 0.0.0.0`; a página solicitará o token. Para acessar um computador em nuvem a partir do próprio computador, prefira o encaminhamento SSH acima. O acesso direto pela rede local exige o endereço de escuta da máquina que hospeda o serviço. O token fica apenas na sessão atual do navegador; a API e os downloads de artefatos exigem `X-Studio-Token`. A validação de Host/Origin permanece ativada.

## Um ciclo completo de uso

“Laboratório de Ações” na navegação abre a biblioteca independente de receitas (`#/actions`); a página inicial também mantém um atalho. É possível buscar, filtrar por categoria, ver uma prévia do modelo ou ler a descrição e iniciar o treinamento com a receita selecionada. Caminhada em piso plano, terreno irregular e equilíbrio em uma perna têm estados de validação distintos. Consulte [Como contribuir com uma receita de ação](docs/recipe-contribution.md) para saber como adicionar receitas da comunidade.

A receita experimental de **equilíbrio em uma perna para HD1910** permite escolher a perna de apoio, a altura do pé (0,5–2 cm) e o tempo de sustentação (1–5 segundos), sem alterar código. O ciclo completo inclui preparação, elevação, sustentação e apoio com recuperação. A ilustração 3D da meta não representa equilíbrio físico nem resultado de treinamento. Saltos, giros precisos e imitação por vídeo ainda não estão integrados.

As instruções sem conhecimento prévio, a interpretação dos resultados e os passos para criar novas ações estão em [Guia do Laboratório de Ações](web/custom-actions.md), também acessível pela barra lateral e pela janela de novo treinamento.

1. Em “Ambiente de computação”, confirme que a verificação passou. Depois de instalar dependências, é possível verificar novamente.
2. Crie um experimento e selecione primeiro **Caminhada em piso plano HD1910**. O primeiro teste curto usa sempre **64 ambientes e 5 iterações** para conferir carregamento, simulação e salvamento. O teste curto não é um resultado de treinamento.
3. Depois que o teste curto passar, inicie o treinamento real. É possível expandir e ajustar ambientes paralelos, iterações, intervalo de salvamento, semente e taxa de aprendizado; ao recolher o painel, o resumo das alterações continua visível. Se alterar a meta da ação, taxa de aprendizado, semente aleatória ou perfil importado, será preciso concluir outro teste curto com a configuração correspondente. O número de ambientes e iterações pode ser ampliado para o treinamento real.
4. Consulte as métricas originais, as iterações e os logs do treinamento. A porcentagem indica o progresso em relação ao total planejado, não o domínio da ação. O modelo 3D pode ser girado; **o modelo CAD e as animações de demonstração não servem para avaliar a política**.
5. Pause, retome ou encerre a tarefa. Selecione um checkpoint para avaliação: tarefas de caminhada geram uma reprodução de 250 passos; tarefas de equilíbrio executam oito tentativas do ciclo completo com sementes registradas. Vídeos e causas de falha são preservados mesmo quando uma tentativa termina antes do prazo. A página apresenta o número de sucessos e informa se houve sustentação e recuperação após apoiar o pé. A reprodução corresponde ao checkpoint escolhido, não mostra o treinamento ao vivo.
6. Compare experimentos reais da mesma tarefa e do mesmo modo. Depois de confirmar o checkpoint necessário, exporte o pacote do modelo e siga o processo existente de validação em simulação e no robô físico.

| Ação | Comportamento |
|---|---|
| Pausar | No Linux, usa SIGSTOP no grupo de processos, preservando política, otimizador e memória da GPU. No modo de demonstração, a interface só atualiza depois de confirmar a pausa do subprocesso. |
| Retomar | Continua o processo pausado. Se a tarefa foi encerrada ou concluída, cria um novo experimento a partir do checkpoint selecionado e registra a origem. |
| Encerrar | Termina o processo de treinamento que o serviço iniciou e preserva checkpoints já gravados. Não garante salvar uma iteração ainda em andamento. |
| Avaliar | Depois que o treinamento para, executa inferência limitada em passos sobre o checkpoint selecionado e gera um vídeo. |
| Exportar | Chama `scripts/export.py` do mecanismo e preserva a normalização de observações nele implementada; inclui ONNX, checkpoint, configuração e registro da origem. |

A pausa continua ocupando memória da GPU e **não desliga o computador em nuvem nem interrompe a cobrança da plataforma**. Um serviço executa apenas uma operação de treinamento, avaliação ou exportação por vez. Se o serviço for reiniciado, tarefas antigas ainda não finalizadas serão marcadas como desconectadas; o sistema não opera em outros processos usando apenas um PID registrado.

## Perfis e resultados

É possível importar JSON no formato `microduck-studio-duck-profile/v1` (até 64 KiB). O perfil fica associado ao experimento para conferência, **mas não substitui automaticamente massa, inércia, zeros das articulações nem configurações dos servos durante o treinamento**. A receita atual HD1910 usa uma linha de base de simulação e ainda precisa ser validada separadamente no hardware do usuário.

Por padrão, os registros do serviço ficam em `state/runs/<id>/`; os logs originais do mecanismo e checkpoints PT continuam em `../training/logs/rsl_rl/`. Preserve ambos ao fazer backup ou migração: os registros da interface apontam para o caminho original dos checkpoints do mecanismo. O ZIP exportado pode ser salvo separadamente, mas esta versão não tem uma opção para enviar um ZIP e retomar o treinamento a partir dele.

O equilíbrio usa o diretório de experimento separado `microduck_hd1910_balance` e aplica `skill.json` ao treinamento, retomada, avaliação e exportação. O pacote exportado inclui o contrato dos comandos. Embora a política ainda use observação de 61 dimensões, ação de 14 dimensões e 50 Hz, o significado dos campos de comando mudou. O runtime de caminhada existente precisa de um adaptador para o agendamento das fases; o equilíbrio em uma perna ainda não foi validado no robô físico.

Foram concluídos testes curtos reais na GPU para as pernas esquerda e direita, oito avaliações e uma verificação de consistência ONNX. A taxa de sucesso da política após cinco iterações é 0/8; isso demonstra somente que o fluxo funciona. Consulte [Validação do Laboratório de Ações](docs/action-lab-verification.md). A proposta da biblioteca comunitária e o fluxo de contribuição estão em [Projeto do Laboratório de Ações](docs/action-lab-design.md#direcao-futura-biblioteca-comunitaria-de-receitas-de-acao); compartilhamento e instalação automática ainda não existem.

A tarefa de caminhada em piso plano HD1910 concluiu no WSL2 com RTX 5060 Ti um treinamento real de 64 ambientes e 5 iterações, salvamento PT, avaliação em vídeo de 250 passos, exportação ONNX e comparação independente da consistência de inferência PT/ONNX. Consulte o [registro de validação](docs/verification.md). Terreno irregular, treinamento longo, computador em nuvem de destino e implantação no robô físico precisam de validações próprias; um teste curto não prova que a ação foi aprendida de forma robusta.

## Validação durante o desenvolvimento

```console
python -m unittest discover -s tests -v
node --test tests/state.test.mjs
```

Os testes no navegador usam Playwright. O script inicia um serviço de demonstração isolado, configura um token de teste, chama a API de verdade e salva capturas de tela. Defina `PLAYWRIGHT_MODULE_ROOT` com o caminho de um `node_modules` existente para reutilizar o Playwright instalado; também é possível instalá-lo no ambiente de desenvolvimento. `BROWSER_EXECUTABLE` pode apontar para o executável do Chrome/Edge e `PYTHON` para Python 3.12. Os testes unitários acima não exigem dependências de navegador.

```console
node dev/browser-check.mjs
```

Por padrão, os resultados são gravados no diretório temporário do sistema; use `BROWSER_CHECK_OUTPUT` para escolher outro local. Os testes não se conectam a serviços em nuvem, GPU ou robô. Consulte [design.md](docs/design.md) para o projeto e o contrato da API, [implementation-plan.md](docs/implementation-plan.md) para a lista de implementação e [verification.md](docs/verification.md) para testes e revisões desta versão.

O arquivo-fonte do guia de ações é `web/custom-actions.md`. Depois de editá-lo, execute `python dev/build-guide.py` em um ambiente de documentação com Python-Markdown para atualizar `web/guide.html` e envie os dois arquivos no mesmo commit. A página usa o HTML gerado; executar o painel de treinamento não exige Markdown nem etapa de build.

## Atribuição

O código original deste diretório usa Apache-2.0; a documentação mantém a licença correspondente do repositório. Modelos compartilhados, bibliotecas Web e mecanismo de treinamento seguem suas próprias licenças, descritas em [NOTICE.md](NOTICE.md).

Uma comparação com projetos semelhantes e as prioridades para os próximos passos estão em [Comparação do Studio de treinamento de kissqy](docs/reference-comparison-2026-10-23.md).
