# Registro de validação do Training Studio · 22/10/2026

## Validação de ponta a ponta

| Ambiente | Verificação | Resultado |
|---|---|---|
| Windows / Python 3.12 | `python -m unittest discover -s tests -v` | 54 testes: 51 aprovados e 3 exclusivos de Linux ignorados |
| WSL Ubuntu 22.04 / Python 3.11 | Mesmo comando de testes de backend | 54/54 aprovados |
| Node.js | `node --test tests/state.test.mjs` | 11/11 aprovados |
| Edge / Playwright | `node dev/browser-check.mjs` | Fluxos aprovados em desktop 1440×1000 e celular 390×844; sem erros de página nem transbordamento horizontal |

A validação no navegador iniciou um serviço de demonstração isolado, mas usou a API HTTP real, sem interface simulada nem contorno de CSP. Cobriu token de acesso, carregamento do CAD, teste curto fixo de 64 ambientes e 5 iterações, recolhimento de opções avançadas, treinamento real, pausa após salvar checkpoint, congelamento de iterações, retomada após atualizar a página, encerramento, avaliação de checkpoint antigo, download autenticado, conteúdo do pacote exportado, criação de continuação a partir de um checkpoint selecionado, comparação de experimentos, busca, lista de modelos, nova verificação do ambiente e gaveta móvel. Alterar parâmetros de aprendizado exige um novo teste curto; o rascunho do treinamento real original é preservado.

Os testes exclusivos de Linux usaram sinais do sistema operacional e subprocessos de CPU reais; não simularam `killpg` nem `waitid`:

- Depois de SIGSTOP, os contadores do processo principal e dos descendentes pararam; após SIGCONT, voltaram a avançar.
- Encerrar o serviço enquanto estava pausado limpou o grupo de processos pertencente a ele.
- Se o processo principal terminou, mas um descendente ainda mantinha stdout aberto, tanto o treinamento quanto a avaliação conseguiram terminar e limpar o descendente.

## Revisão e correções

Backend e frontend passaram por revisões independentes de especificação e qualidade de código, sem itens bloqueadores ao final. As revisões levaram a corrigir: treinamento real ainda permitido após divergência de configuração; correspondência imprecisa de checkpoints; parâmetros de controle de pausa carregando indevidamente parâmetros do checkpoint; cache da verificação de ambiente sem atualização; corrida na limpeza ao sair; salvamento incompleto de checkpoint; tarefa que não terminava por causa do pipe de logs; nome de continuação excessivamente longo; omissão de evidências de avaliação e de informações de origem na exportação.

## Limites da validação

A validação de 22/10/2026 não iniciou treinamento em GPU NVIDIA. Em 23/10/2026 foi acrescentado o teste local real de GPU descrito abaixo. O computador em nuvem de destino, treinamentos longos e o robô físico ainda precisam de validação separada. A integração foi conferida com as interfaces de mjlab 1.3.0 e rsl-rl-lib 5.0.1 fixadas no projeto. Um teste curto não prova que o robô aprendeu a caminhar.

O ZIP de demonstração não inclui pesos PT/ONNX. O perfil do pato é arquivado para conferência e não altera automaticamente o modelo físico. Pausar não desliga o computador em nuvem nem interrompe a cobrança da plataforma.

## Revisão de alinhamento visual com o Studio · 23/10/2026

- Foram adotados as cores reais do painel, a fonte, a identidade do pato, a barra lateral clara, os botões pretos em formato cápsula, os cartões brancos e a área 3D cinza; no celular, a navegação passou a ter quatro itens na barra inferior.
- `node --test tests/state.test.mjs`: 11/11 aprovados. O fluxo completo no navegador com o serviço de demonstração real passou: autenticação, CAD, controle de tarefa, exportação da avaliação, comparação e gaveta móvel, sem erros de página ou recursos com falha.
- Uma revisão independente conferiu quatro rotas nas larguras de 1440, 1024, 960, 840, 701, 700, 390 e 320 px. Não houve transbordamento horizontal; a rota selecionada ficou correta. O botão da gaveta móvel não ficou coberto pela barra inferior e o foco por Tab permaneceu no diálogo nos dois sentidos.
- Foi corrigido o dimensionamento do gráfico no celular: o SVG agora usa a largura real do contêiner e mantém coordenadas a 12 px em telas de 320 e 390 px. Testes com dados vazios, um ou vários pontos e mudança da largura passaram.
- Essa rodada alterou somente frontend e documentação, não o backend de treinamento. A validação real local descrita abaixo foi acrescentada posteriormente.

## Teste curto local com GPU · 23/10/2026

Ambiente: Windows/WSL2 Ubuntu 22.04, NVIDIA GeForce RTX 5060 Ti de 16 GB, driver 617.14, Python 3.12.14, torch 2.9.1+cu128, mjlab 1.3.0 e rsl-rl-lib 5.0.1 efetivamente instalados. O ambiente virtual isolado foi preparado com o cache offline usando o projeto `software/training` e seu arquivo de lock; definições do mecanismo e lock não foram alterados.

Pela interface no Edge/Playwright, foi criado no modo real o experimento `caa6a1c5de10`: HD1910 em piso plano, 64 ambientes, 5 iterações, salvamento a cada iteração, seed 42 e taxa de aprendizado 0.001. Não houve API nem dados de treinamento simulados.

| Verificação | Resultado medido |
|---|---|
| Simulação CUDA e atualização PPO | 5 iterações concluídas, 7.680 amostras; 40,54 s incluindo carregamento inicial |
| Métricas e checkpoints | 5 pontos de métricas e `model_0.pt` a `model_4.pt`; o último foi lido com `torch.load(weights_only=True)` e os 76 tensores verificados eram finitos |
| Avaliação da política | Último checkpoint avaliado por 250 passos; vídeo H.264 de 960×540, 50 FPS, 250 quadros e 5 s; quadros inicial e final decodificados |
| Exportação e inferência | O mecanismo exportou ONNX e o pacote do modelo; ONNX checker aprovado; ONNX Runtime em CPU recebeu 61 dimensões e produziu 14 |
| Consistência PT/ONNX | Carregamento estrito dos pesos do ator e normalização via MLPModel do rsl-rl instalado; entrada zero e 31 entradas aleatórias com semente fixa; diferença absoluta máxima `1.9073486328125e-6`, dentro de `atol=1e-5, rtol=1e-4` |
| Navegador após reinício | Modo real pronto; experimento salvo carregado; vídeo de avaliação reproduzido e pacote baixado; sem erros de página |
| Regressões | Python 3.12 no Windows: 53 aprovados e 3 ignorados, de 56; Python 3.12 no WSL: 56/56 aprovados; revisão independente sem itens bloqueadores |

A execução encontrou e corrigiu dois problemas de ambiente. A importação fria da tarefa levava cerca de 24 segundos, acima do limite anterior de 20; o limite passou para 60 segundos. A pré-verificação e o treinamento usavam ambientes GL diferentes, então o serviço podia indicar que estava pronto mesmo sem EGL; agora usam o mesmo ambiente e o backend gráfico escolhido é importado de verdade. Depois de instalar `libegl1` no Ubuntu, o vídeo foi gerado corretamente. Um valor definido explicitamente em `MUJOCO_GL` continua preservado. O serviço corrigido foi reiniciado, passou nas verificações reais EGL/CUDA/tarefas e manteve o experimento e os artefatos existentes acessíveis.

A linha de base desta execução foi o commit Windows `adfb878cf944853aaa720dff4554fdab2dcaadb8` mais a correção local da pré-verificação. O caminho `.git` deste worktree Windows não pode ser acessado diretamente pelo Git no WSL; por isso, `git_commit` ficou nulo no registro e foram preservados hashes SHA-256 dos arquivos. O campo `dependency_versions` resume o lock multiplataforma e mostra torch cu129; cu128 acima foi lido do interpretador efetivamente usado. O resumo não é prova da versão instalada.

As evidências locais estão fora do repositório em `本地记录/training-local-20261023/`: logs originais, snapshot de execução, capturas, script de verificação dos artefatos e `artifact-verification.json`. Logs grandes e modelos não foram adicionados ao Git. SHA-256 dos principais artefatos:

- `model_4.pt`: `0caa0e69f38533d1694960aaa4e7d260625bc6dc803852b15f1e3df82015f9ac`
- `policy.onnx`: `673bc7e787a084df1f3a8593a43ce987d2a05472ee12097b393e1ddb7311da57`
- `rl-video-step-0.mp4`: `e967b6d33b4debc28a10a88fe026dbb2250f3cf51bae44b6c197aa1cc2119f3d`

Esse resultado cobre uma execução curta em piso plano. A consistência PT/ONNX foi verificada separadamente nesta rodada e ainda não faz parte automática de toda exportação. Não foram validados treinamento longo com pausa/retomada na GPU, terreno irregular, plataforma em nuvem nem robô físico. Consulte os passos em [Teste curto local](local-smoke.md).

## Entrada para o guia de ações personalizadas · 23/10/2026

- Foi adicionado um guia em chinês sobre o fluxo oficial de desenvolvimento, os limites atuais, um exemplo de solicitação de equilíbrio em uma perna, a viabilidade de saltos e os critérios para avaliar giros. O fonte é `web/custom-actions.md` e a página estática é `web/guide.html`.
- A barra lateral e a janela de novo treinamento ganharam um link para abrir o guia em outra aba. A revisão independente conferiu os XL330 do upstream e os HD1910 locais, o modelo de roda Spin, tarefas ainda não implementadas, comandos existentes e limites de integração com o diretório fixo de experimentos; não encontrou problemas claros.
- O guia foi validado no serviço real atual com Edge em 1440×1000 e 390×844: abertura pelo link, preservação do nome original da tabela, presença de todos os destinos internos, retorno ao Studio e acesso aos arquivos fonte, sem erros de página nem transbordamento.
- Nesta rodada foram adicionados apenas documentação, estilo estático, ferramenta de geração e links de leitura. Não houve novo treinamento nem mudanças na lógica do mecanismo ou do serviço. Capturas e relatório estão em `本地记录/training-custom-guide-20261023/`.
