# Comparação do Training Studio de kissqy · 23/10/2026

Projeto de referência: [kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy), revisado no commit `525a215a19397767a073b782f57e97cf53683761`. Foram examinados o painel público de controle do treinamento, a documentação e o código-fonte real do backend. O programa de treinamento do outro projeto não foi executado e nenhum código foi incorporado a este repositório.

## O que já está disponível aqui

O fluxo local de demonstração foi exercitado: criar experimento, teste curto, demonstração de treinamento, pausar/retomar/encerrar, persistir registros, avaliar checkpoint selecionado, baixar e continuar, comparar experimentos. O controle de processos Linux foi verificado com subprocessos reais de CPU e sinais do sistema.

O modo de treinamento real foi executado no WSL2 local com RTX 5060 Ti: 64 ambientes, 5 iterações, avaliação em vídeo, exportação ONNX e comparação da inferência PT/ONNX. Consulte o [registro de validação](verification.md). GPU em nuvem de destino, treinamento longo e robô físico ainda não foram validados. Modelos, métricas e reproduções de demonstração não provam que uma política aprendeu a ação.

## Principais diferenças

| Prioridade | Implementação de kissqy | Estado atual deste projeto | Trabalho necessário |
|---|---|---|---|
| P0: validação de treinamento real | Registros públicos de simulação física em CPU com mecanismo fixado, atualização PPO e verificação de consistência PT/ONNX; limitações de treinamento longo em GPU e testes físicos são declaradas | Teste local em GPU com 64 ambientes e 5 iterações e artefatos verificados; falta validação na GPU de destino | Repetir no laboratório de GPU: treinar, salvar PT, reproduzir a política, exportar ONNX e comparar inferências com entradas iguais; guardar as evidências |
| P1: conexão com a nuvem | Configuração SSH na página, preparação do ambiente, encaminhamento de porta e serviço remoto independente que preserva fila e resultados | O usuário prepara dependências, inicia o serviço e encaminha SSH manualmente. Fechar o navegador não interrompe a tarefa, mas fechar o serviço encerra os processos dele | Criar orientação de conexão e serviço de execução reconectável; depois automatizar a preparação do ambiente pela página |
| P1: visualização da ação real | Lê a postura rígida de um ambiente específico durante o treinamento e inicia avaliações físicas interativas em PT/ONNX | A área 3D mostra o CAD; o resultado da política é visto em vídeo de avaliação de 250 passos depois de parar o treinamento | Distinguir visualização do modelo, treinamento ao vivo e avaliação de checkpoint; primeiro adicionar avaliação interativa, depois amostragem ao vivo controlada, considerando o custo |
| P1: validação de exportação | ONNX checker e inferência em runtime; verifica modelo e convenções de articulações, observações, ações, frequência e calibração do firmware | Usa o exportador existente com normalização e inclui origem e registros de avaliação. A inferência foi comparada separadamente nesta amostra, mas ainda não é verificada automaticamente a cada exportação nem foi comprovada a compatibilidade completa de implantação | Incluir o resultado da validação pós-exportação e causas específicas de falha; poder baixar não significa que o modelo está pronto para implantação |
| P2: experimentos em lote | Fila preserva os parâmetros ao enfileirar, executa sequencialmente e trata falhas; página lista 14 tipos de ação e 35 receitas | Uma tarefa ativa por vez, duas receitas HD1910 e cinco parâmetros avançados comuns | Primeiro permitir copiar experimentos e criar uma fila sequencial; depois ampliar as receitas uma a uma, após validação |
| P2: diagnóstico do treinamento | GPU, memória de vídeo, temperatura, tempo restante estimado, recompensas por componente e informações do currículo | Principalmente iterações, recompensa, duração de episódios, taxa de amostragem e logs | Exibir recursos reais e recompensas por componente, orientar sobre estagnação e causas de falha; estimativas de tempo devem ser identificadas como estimativas |

## Decisões de projeto a preservar

- Manter padrões simples e opções avançadas recolhidas. O serviço de kissqy reúne servidor, fila, parâmetros físicos e currículo em uma página longa, com muitos recursos; a entrada para novos usuários deste projeto pode ser mais focada. Essa avaliação vem da comparação das páginas, não de um estudo de usabilidade.
- Compartilhar a aparência clara, identidade do pato, botões e navegação móvel do Studio do robô para reduzir o custo de aprendizado entre ferramentas.
- Manter teste curto fixo e conferir parâmetros de aprendizado, semente e perfil na correspondência de configuração.
- Controlar pausa/retomada do processo de treinamento real. A pausa na fila de kissqy permite que o treinamento atual continue; outro grupo de controles pausa e retoma o visualizador de simulação. Essas operações não devem ser tratadas como a mesma capacidade.
- Preservar comparação de experimentos, avaliação e retomada a partir do checkpoint selecionado, identificação clara de demonstrações e origem dos artefatos.

## Ordem de implementação

1. Concluir o fluxo real de uma tarefa curta na GPU de destino e resolver problemas do ambiente e da interface do mecanismo.
2. Depois, melhorar a conexão remota e a avaliação interativa da política para que o usuário veja a ação que treinou.
3. Completar a validação pós-exportação e a compatibilidade entre modelo e firmware.
4. Adicionar filas, diagnósticos e novas receitas validadas, preservando a simplicidade inicial da interface.

Esta comparação não iniciou recursos de nuvem pagos, não modificou imagens de sistema, não copiou código do outro projeto e não promete convergência do treinamento. Partes originais do repositório de referência são declaradas sob licença pessoal e não comercial; qualquer reutilização futura de código exige revisão específica da licença. Esta rodada analisou somente interações e ideias de implementação.

### Atualizações implementadas depois

Ainda em 23/10 foi adicionada a página independente do Laboratório de Ações, a terceira receita experimental HD1910 de equilíbrio em uma perna e o catálogo de 10 modelos oficiais V8 e 10 modelos kissqy V167. O catálogo informa versão, hardware e links de obtenção, sem integrar avaliação local nem retomada. Novos treinamentos continuam começando do zero. Os pesos comunitários permanecem com seus publicadores, conforme as licenças, e não foram incluídos no pacote deste projeto.

Os detalhes do treinamento passaram a mostrar modelo, uso, temperatura e memória da GPU, modelo, uso e temperatura disponível da CPU e memória RAM, com atualização aproximada a cada três segundos. A temperatura da CPU aparece como indisponível quando não é exposta pelo WSL. Os valores mostram o estado geral atual do executor. Recompensas por componente, currículo, previsão de conclusão, histórico de recursos, gerenciamento remoto de conexão e instalação automática ainda não estão implementados.

## Referências de código e documentação

- [Descrição do projeto de treinamento](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/README.md)
- [Treinamento, avaliação e exportação reais](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/runtime_adapter.py)
- [Amostragem durante o treinamento](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/live_view.py)
- [Implantação e conexão por SSH](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_ssh.py)
- [Serviço remoto independente](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_server_boot.py)
- [Persistência do processo de treinamento](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/durable_manager.py)
- [Snapshots da fila e semântica de pausa](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/training_queue.py)
- [Registros públicos de validação e limites ainda não verificados](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/docs/Verification.md)
