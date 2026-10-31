# Laboratório de Ações: equilíbrio em uma perna

Data: 23/10/2026. O usuário autorizou a implementação da primeira atividade sem código na interface de treinamento existente.

## Fluxo do usuário

Conforme o layout definido pelo usuário, o Laboratório de Ações é uma página independente `#/actions` dentro do mesmo painel de treinamento, lado a lado com a bancada na navegação lateral e na barra inferior do celular. A página inicial mantém o acesso à biblioteca. Primeiro, ela reúne as receitas existentes de caminhada em piso plano, terreno irregular e equilíbrio em uma perna, com busca, filtro por categoria, prévia e descrição textual. Ao escolher uma receita, o usuário abre o painel existente de novo treinamento; não é criado outro produto nem outro servidor.

No equilíbrio em uma perna, o usuário escolhe qual perna apoia o robô (esquerda ou direita), a altura de elevação da outra perna e o tempo de sustentação. Os parâmetros avançados de treinamento continuam recolhidos. Os cartões da biblioteca usam os metadados `catalog` do backend para categoria, tags, tipo de prévia, origem e estado de validação. Só a prévia 3D em exibição é carregada por vez, para evitar criar muitas cenas WebGL quando houver mais receitas. A descrição textual também é um tipo completo de cartão; nem toda receita precisa de vídeo.

O diagrama 3D mostra as pernas esquerda e direita e a direção da elevação, com o rótulo “Ilustração da meta · não representa resultado de treinamento”. O desenho não afirma fornecer cinemática precisa nem validar o equilíbrio. Experimentos criados salvam os parâmetros da ação como somente leitura; copiar um experimento ou promover um teste curto a treinamento real mantém os mesmos parâmetros. Para alterar a meta da ação, é necessário executar um novo teste curto correspondente. O resultado real da política só pode ser observado no vídeo de avaliação física do checkpoint selecionado.

## Contrato fixo

- Receita `hd1910-single-leg`, tarefa `Mjlab-Balance-Flat-MicroDuck-HD1910`, diretório de experimento `microduck_hd1910_balance`.
- As requisições e os registros recebem o objeto `skill`: `support_side` aceita `left/right`; `lift_height_m` vai de 0.005 a 0.02, padrão 0.01; `hold_seconds` vai de 1 a 5, padrão 3. Rejeitar booleanos usados como números, valores não finitos, campos desconhecidos e parâmetros de habilidade enviados junto com receitas de caminhada.
- Os metadados das receitas incluem `experiment_name`. A receita de uma perna fornece `skill_defaults` e `skill_limits`, e a interface apresenta centímetros e segundos dentro dos limites fornecidos pelo backend. Novas receitas começam com 256 ambientes, 1.000 iterações e checkpoint a cada 25 iterações; o teste curto continua fixo em 64 ambientes, 5 iterações e checkpoint a cada iteração.
- Os parâmetros da ação são incluídos na correspondência do teste curto, na retomada, na origem da exportação e na avaliação. Registros antigos de caminhada sem `skill` permanecem compatíveis. Não aceitar nomes arbitrários de tarefas, caminhos ou trechos de comandos.
- O serviço fornece o diretório de logs de cada receita por uma lista de permissões. A identificação dos logs, a busca de PT, os caminhos de retomada e a validação de checkpoints para avaliação e exportação devem usar a mesma regra.

## Mecanismo de treinamento

Copiar profundamente a configuração de velocidade HD1910, preservando Feetech BAM, observação de 61 dimensões, ação de 14 dimensões, 50 Hz, proteção contra NaN e a randomização física correspondente. Adicionar comando, recompensa e progresso de fases específicos. Remover recompensas de caminhada ou currículo que compensem a elevação do pé ou sobrescrevam o comando. Treinar somente a perna de apoio selecionada; não ativar perdas de imagem incondicionais.

As fases são: estabilizar, elevar o pé, sustentar, apoiar o pé e terminar estável com os dois pés. O ciclo completo e seus parâmetros permanecem fixos por experimento. A recompensa e a condição de sucesso devem verificar a perna de apoio correta, altura do pé, postura do tronco, deslizamento, contato proibido do corpo com o chão e recuperação após apoiar o pé. Isso impede obter recompensa enganando o sistema ao cair e manter o pé suspenso. Registrar separadamente a semântica do novo comando; dimensões de entrada e saída iguais, por si só, não provam que o comando possa ser usado diretamente no runtime do robô antigo.

A CLI de treinamento transmite parâmetros por campos tipados em `CommandConfig`. A avaliação e a exportação aplicam os parâmetros salvos usando a mesma função de validação antes de criar o ambiente. Preservar o caminho atual de exportação com normalização; não alterar o arquivo de lock das dependências nem o comportamento das receitas de caminhada existentes.

## Critérios de validação

1. Testes de configuração e recompensa em CPU: limites, mapeamento esquerda/direita, limites das fases, condições de término/sucesso, valores finitos, contrato 61/14/50 e isolamento da fábrica antiga. Confirmar que as posturas candidatas e a geometria suportam a meta.
2. Regressão do serviço: correspondência do teste curto, registros antigos, caminhos isolados por receita, parâmetros inválidos, pausa/retomada e parâmetros/origem na exportação.
3. Interface: rascunhos, conversão de unidades, troca entre esquerda e direita, bloqueio após alterar parâmetros, cópia, exibição dos resultados e layout móvel. A ilustração da meta não pode servir como evidência de avaliação.
4. GPU real: 64 ambientes e 5 iterações, salvamento de PT, várias avaliações com o ciclo completo, vídeo real, exportação ONNX e comparação de inferência. Registrar o número real de sucessos; terminar o processo de treinamento com sucesso não significa que a ação tenha sido bem-sucedida.
5. Integrar ao espaço de trabalho estável, preservando os experimentos e o estado do serviço. Reiniciar o serviço somente quando não houver tarefas ativas.

## Limites

A primeira versão conclui o fluxo configurável de treinamento para equilíbrio em uma perna. Saltos e giros precisos não aparecem como modelos disponíveis para execução. Convergência em treinamento longo e resultados no robô real devem ser relatados com evidências próprias, sem substituí-las por ilustrações ou testes curtos.

## Direção futura: biblioteca comunitária de receitas de ação

O usuário esclareceu também que o Laboratório de Ações deve permitir que autores da comunidade criem tarefas de ação para que usuários comuns possam selecioná-las e treiná-las, sem precisar escrever código de recompensa do zero. O equilíbrio em uma perna da primeira versão é um exemplo completo desse fluxo. Publicação comunitária, revisão, download e instalação automática ainda não foram implementados.

Uma receita planejada deve incluir autor e origem, licença, versão, hardware e versão do mecanismo compatíveis, instruções da ação, parâmetros ajustáveis e seus limites, regras de treinamento, critérios de sucesso e falha, condições de avaliação e vídeo de exemplo. Os parâmetros devem ser usados no treinamento, na retomada, na avaliação e na exportação; se o usuário alterar a meta, seu registro de experimento deve ser preservado.

O fluxo de contribuição deve priorizar pull requests no repositório: o autor implementa a tarefa e os testes; os mantenedores revisam compatibilidade e evidências de validação; a receita é adicionada à lista de opções; o usuário faz um teste curto antes de iniciar o treinamento real. Atualmente, as tarefas ainda são registradas por uma lista de permissões no serviço. No futuro, a página não deve tratar scripts enviados livremente como recursos internos já revisados.

O estado de validação nos cartões deve distinguir “fluxo de treinamento aprovado”, “ação concluída sob condições específicas” e “validado em robô real”. Encerrar com sucesso uma execução ou passar algumas iterações curtas não basta para afirmar que a ação foi aprendida. Pesos de políticas existentes são artefatos separados e opcionais: devem indicar a origem e a meta correspondente, sem serem confundidos com a receita de treinamento.

A página deve passar a renderizar cartões e formulários de parâmetros com base nos metadados das receitas, reduzindo gradualmente os nomes de ações fixos no código. Primeiro, estabilizar o contrato das receitas e o exemplo de contribuição; depois, criar um fluxo de compartilhamento. Esta rodada não criou contas, serviço de envio ou backend comunitário.
