# Validação do Laboratório de Ações · 23/10/2026

A primeira versão integrou ao painel de treinamento existente um experimento de equilíbrio em uma perna para HD1910. O usuário escolhe a perna de apoio, a altura do pé levantado e o tempo de sustentação e usa o fluxo existente de treinamento, pausa/retomada, checkpoints, avaliação e exportação. A pedido do usuário, depois foi criada a página independente `#/actions`, com as três receitas internas atuais. Publicação pela comunidade e instalação automática ainda não existem.

## Validação da biblioteca independente de ações

Os metadados do catálogo, commit `6ca4d5f`, e a interface, commit `109083a`, foram integrados a `studio-dev` por `a8e498f`. A página continua no serviço existente, na porta 8094. As mudanças adicionaram somente catálogo, navegação e documentação; não alteraram o mecanismo de treinamento já validado.

- Os testes Node de estado e atualização de parâmetros passaram: **21/21**. Os testes de regressão das receitas no backend passaram: **13/13**.
- Edge/Playwright verificaram separadamente o serviço de demonstração isolado e o serviço real: entrada pela bancada, navegação lateral, acesso direto, atualização da página, voltar/avançar no navegador, categorias, busca por vários termos e limpeza quando não há resultados.
- As três receitas validam prévias de modelo, texto e meta de equilíbrio em uma perna. O catálogo não cria uma visualização WebGL por conta própria: abrir a prévia carrega apenas uma visualização e fechá-la libera os recursos. Fechar, usar Escape, ciclo de foco por Tab e restauração do foco passaram.
- Os cartões e detalhes abrem a configuração de treinamento da receita correta, com o teste curto como padrão. A navegação e a seleção não enviaram nenhuma requisição POST para criar tarefas.
- Verificação em larguras de 1440, 768, 390 e 320 px. A navegação móvel com cinco itens não transbordou horizontalmente; os controles inferiores das gavetas de prévia e treinamento permaneceram visíveis. As verificações geométricas aguardaram o fim da animação de entrada; as capturas de tela foram conferidas manualmente.
- O serviço original estava com GPU pronta e sem tarefas ativas. O experimento antigo de terreno plano `caa6a1c5de10` e o experimento de uma perna `a930fbbab951` foram preservados. O resultado do equilíbrio continuou em 0/8 e o vídeo pôde ser reproduzido. Não houve erros de página nem recursos com falha.
- A revisão de código independente não encontrou problemas restantes P1/P2. Não foi iniciado outro treinamento na GPU e não foi adicionada publicação online pela comunidade.

As evidências estão no diretório externo `本地记录/training-action-lab-20261023/catalog-browser.mjs`, em `catalog-validation/` e `catalog-validation-stable/`, com relatórios e capturas para desktop e celular. O processo de inclusão está descrito em [Como adicionar uma receita](recipe-contribution.md).

## Escopo da validação

- Backend Windows: 73 testes, 70 aprovados e 3 testes exclusivos de Linux ignorados; backend WSL: 73/73 aprovados.
- Testes Node de estado e parâmetros: 18/18 aprovados.
- Regressões de parâmetros do mecanismo, configuração, geometria da sola, HD1910 e NaN: 46/46 aprovadas.
- Teste real com CUDA, 4 ambientes e 30 passos: comando para a perna direita, ator de 61 dimensões, ação de 14 dimensões, 50 Hz, critic/recompensa finitos e reinicialização parcial correta.
- Edge/Playwright, em 1440 e 390 px: edição da meta, conversão de centímetros, rascunhos separados por receita, cópia, bloqueio do teste curto após mudar parâmetros, identificação de avaliação demonstrativa e reprodução real. Sem erros de página nem transbordamento horizontal.
- A revisão independente da especificação e do código encontrou um problema na semente aleatória da inicialização da avaliação; ele foi corrigido e testado novamente. Não restaram problemas P1/P2.

O teste em CPU emitiu um aviso existente sobre tipos tuple/list na configuração. O teste na GPU avisou que o nome do actuator também correspondia ao site. Nenhum dos avisos impediu a execução. A inferência em CPU do ONNX Runtime exibiu um aviso de detecção de dispositivo GPU do WSL, mas a inferência em CPU terminou normalmente. Esses avisos não demonstram falha do treinamento na GPU.

## Treinamento real e artefatos

Hardware: RTX 5060 Ti de 16 GB e WSL2 Ubuntu 22.04; torch 2.9.1+cu128, mjlab 1.3.0 e rsl-rl-lib 5.0.1. Os arquivos de lock das dependências não foram alterados.

| Experimento | Meta | Resultado |
| --- | --- | --- |
| `1eddca56e439`, serviço isolado | Apoio na perna esquerda, pé elevado 1 cm, sustentação de 3 s | 64 ambientes × 5 iterações, 7.680 amostras, 5 arquivos PT; avaliação real e exportação ONNX concluídas |
| `a930fbbab951`, serviço original 8094 | Apoio na perna direita, pé elevado 0,5 cm, sustentação de 1 s | 64 ambientes × 5 iterações, 7.680 amostras, 28,9 s incluindo inicialização, 5 arquivos PT; avaliação real, vídeo em close e exportação concluídos |

Validação final do experimento pela interface oficial `a930fbbab951`:

- As 8 tentativas terminaram antes do prazo por falha física: **0/8 sucessos**, 250 passos no total. O orçamento de cada tentativa incluía o ciclo completo de 4,5 s; as falhas encerraram a tentativa mais cedo, não houve corte arbitrário dos vídeos.
- Vídeo de 960×540, 50 FPS, 250 quadros e 5 s, preservando as oito tentativas. O navegador reproduziu o vídeo. A câmera foi ajustada de 3 m para 0,7 m, deixando o pé claramente visível.
- Semente de inicialização 42 e sementes de reset de 42 a 49. Após a correção, duas avaliações tiveram os mesmos passos de término em cada tentativa; a diferença média de recompensa foi de aproximadamente 3,43e-8, decorrente de ponto flutuante. As oito tentativas compartilharam uma amostra inicial de tensão/resistência e não cobrem toda a distribuição de randomização do hardware.
- Os 76 tensores do checkpoint eram finitos; os pesos do ator e a normalização das observações foram carregados corretamente.
- Checker ONNX e inferência em CPU com 32 conjuntos de entradas zero/aleatórias passaram. Entrada de 61 dimensões, saída de 14; diferença absoluta máxima entre PT e ONNX de `4.0531158447265625e-6`, dentro de `atol=1e-5, rtol=1e-4`.
- O YAML do ambiente, `run.skill`, `skill.json`, resumo de avaliação e os metadados de comando ONNX no ZIP de exportação preservaram a mesma meta.
- O contrato de exportação marca explicitamente `runtime_adapter_required=true` e `hardware_validated=false`. Ter as mesmas dimensões de entrada e saída não significa que o artefato possa ser usado diretamente pelo runtime de caminhada original.

Hashes SHA-256 dos artefatos representativos:

- `model_4.pt`: `b785059649269a9f18065e18050122a3acd571d06f5a96b387d8883cffab3b1e`
- `policy.onnx`: `2076ce787aaf20fc1b9c3dd83eba229d3d6dae09e6471739e7701c5b72e3c878`
- `rl-video-step-0.mp4`: `f547716356ba95f66bb76bef357277fda04151fdc054ab8a3691d3d0a90d8da6`

## Integração e evidências

O desenvolvimento ocorreu em um espaço de trabalho separado, iniciado em `9d0fe05`. O mecanismo `2e5a3f1`, a correção da semente aleatória de inicialização `9261167` e o ajuste de câmera em close `a168cc2` foram integrados a `studio-dev`. Outros commits da barra de estado do controlador e arquivos não rastreados em `software/studio/docs/` também foram preservados. O serviço original só foi reiniciado sem tarefas ativas; o diretório de estado foi mantido e o experimento de caminhada antigo `caa6a1c5de10` continuou acessível. Os serviços temporários 8095/8096 foram encerrados; o usuário continuou usando 8094.

O diretório externo `本地记录/training-action-lab-20261023/` contém scripts do navegador, logs, capturas e validação isolada. `stable-validation/` contém scripts de verificação da interface oficial, relatórios de artefatos e capturas finais. O `run.json` real e os artefatos continuam em `本地记录/training-local-20261023/state/runs/a930fbbab951/`. Modelos e vídeos não foram incluídos no Git.

O caminho Git do worktree Windows não pode ser resolvido diretamente pelo Git no WSL; por isso, `git_commit` pode continuar nulo no registro da execução. Os hashes SHA-256 dos arquivos de origem foram preservados. O registro separa as versões realmente instaladas do arquivo de lock de candidatos multiplataforma, para não indicar a versão candidata cu129 como instalada de fato.

## Limites das conclusões

Esta rodada demonstra que a meta passou pelo treinamento real, salvamento, tentativas do ciclo completo, reprodução e exportação. **Ela não demonstra que a política aprendeu o equilíbrio em uma perna.** A geometria do modelo permite elevar o pé entre 5 e 20 mm, mas não comprova equilíbrio estático confiável. As falhas do treinamento curto foram apresentadas sem ocultação.

Convergência em treinamento longo, pausa/retomada durante um treinamento longo real da nova tarefa, uso em plataforma de nuvem e implantação em robô físico precisam de validações próprias. Os testes existentes de pausa/retomada foram feitos no serviço de teste e não devem ser descritos como medições reais adicionais. Saltos, giros precisos, imitação por vídeo e publicação de receitas da comunidade ainda não fazem parte do que está disponível.
