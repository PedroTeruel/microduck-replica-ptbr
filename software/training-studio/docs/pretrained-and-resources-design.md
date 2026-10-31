# Catálogo de modelos pré-treinados e recursos do executor · 23/10/2026

O usuário pediu para adicionar ao Laboratório de Ações um modelo treinado por kissqy, conferir o V8 oficial e exibir nos detalhes do treinamento o modelo da GPU, temperatura, memória de vídeo, CPU, memória RAM e progresso. Seguindo o Laboratório de Ações independente e o estilo visual já definido, o trabalho foi dividido em duas mudanças que podem ser validadas separadamente.

## Modelos pré-treinados

O Laboratório de Ações distingue receitas de treinamento de modelos pré-treinados. Uma receita cria um novo experimento; um modelo apresenta a origem dos pesos existentes, versão, hardware, finalidade, formato, endereço para obtê-los e escopo da validação. Permite filtrar por origem e palavras-chave e explica as capacidades atuais nos detalhes. A interface não apresenta pesos externos como se fossem o resultado de um treinamento local concluído.

A fonte oficial é fixada em V8 de `pollen-robotics/microduck-policies`, commit `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`; o manifesto declara XL330, 61 entradas, 14 saídas e 50 Hz. A fonte de kissqy é fixada no manifesto de lançamento V167, commit `525a215a19397767a073b782f57e97cf53683761`, para HD1910; inclui o ONNX visível no código e os pesos distribuídos no pacote de lançamento. Os links para obter os modelos apontam para os publicadores originais, preservando atribuição, versão e licença. Modelos sujeitos a licença pessoal e não comercial não são redistribuídos.

A integração atual oferece um catálogo navegável para localizar e obter modelos prontos. ONNX não contém o otimizador PPO completo nem checkpoints de treinamento, portanto não pode usar o fluxo existente de “continuar treinamento”. Ter apenas dimensões 61→14 também não prova compatibilidade de comandos, HOME ou dinâmica dos servos. A página informa claramente que avaliação local e retomada de treinamento ainda não estão integradas e não altera a política atual do robô. Para adicionar outros modelos, basta ampliar o catálogo no serviço.

## Recursos do executor atual

Os detalhes do treinamento ganham um painel de recursos, alimentado pela API independente e somente de leitura `/api/resources`. O backend inicia sob demanda e mantém em cache as leituras do sistema por cerca de três segundos. A sondagem da GPU tem tempo limite e não adquire o bloqueio do treinamento nem afeta a consulta existente de `/api/state`. Há suporte a várias GPUs, com modelo, utilização, temperatura e memória de vídeo. Para a CPU, são exibidos modelo, núcleos, utilização e temperatura quando disponível; para a memória, uso e total. Iterações e taxa de processamento continuam vindo do log real do treinamento.

Esses valores representam os recursos gerais atuais do executor. CPU e memória do WSL referem-se ao que está visível dentro do subsistema; a GPU pode incluir outros processos. Consultar um experimento encerrado não representa o uso histórico de recursos. Se a temperatura ou outro campo não estiver disponível no driver, a API retorna null e a causa, sem inventar zero. A amostra inicial e uma conexão interrompida são identificadas separadamente como “coletando” e “dados desatualizados”. O ambiente de demonstração não gera leituras fictícias de hardware.

## Implementação e validação

1. Adicionar `training_studio/pretrained.py` e um catálogo de modelos versionado. Testar IDs únicos, origem fixa, HTTPS, formato/hardware, impossibilidade de retomar o treinamento e retorno de cópias. Integrar em `state.pretrained_models`.
2. Adicionar `training_studio/resources.py` e a API. Antes de implementar a sondagem, testar valores CSV vazios, múltiplas GPUs, diferenças da CPU, memória, temperatura indisponível, tempo limite, cache e encerramento. Consultar os dados reais da NVIDIA no WSL local.
3. Adicionar `web/pretrained.js` e `web/resources.js` e atualizar a biblioteca de ações e `RunView`. Testar consulta e formatação; validar em desktop e nas larguras 390/320 px os filtros por origem, detalhes, links externos, valores ausentes, desconexão e exibição de recursos.
4. Integrar à branch em uso após revisão independente, regressões Python/Node e teste no navegador. Reiniciar o serviço atual somente quando não houver tarefas ativas e preservar todos os experimentos. Não iniciar treinamento, implantação de modelos nem operações pagas na nuvem.
