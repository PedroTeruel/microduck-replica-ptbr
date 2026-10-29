# Interface de configuração de provedores de IA: validação e estado da entrega

**Data:** 27/10/2026 (horário de Tóquio; o trabalho começou em 26/10). O usuário confirmou: “ainda não ativei; primeiro prepare a interface de configuração”.

**Estado:** instalado por SSH no duck-0de6; após a implantação, passaram as verificações HTTP, dos arquivos em execução e dos dados do usuário. Código, interface simulada, fluxo do navegador e testes de isolamento do dispositivo passaram. Depois que o usuário confirmou que o pato estava parado, a leitura ainda mostrou a política habilitada, em pé, com velocidade zero em todas as articulações; foi então enviado o mesmo `robot.stop → robot.enable {on:false,toggle:false}` usado pela Web, que respondeu accepted e confirmou `policy_enabled=false` antes de atualizar o serviço Web. Não houve reativação automática nem troca de modelo.

## Código congelado e recursos

- Implementação `907a4a2f2abc0e013044954b829a7e2eb257e9a4`; correção de contexto para respostas longas `7536e0e48d1a0e92ced15f97417b0247a02a827d`; correção de cancelamento de solicitações/timeout para respostas lentas `991bb50278c185f13248c03519b8e21c4eb0b800`. Os arquivos finais em execução foram congelados em 991bb50.
- A parte superior de Configurações contém “Conversas com IA”; o painel de voz inclui uma entrada. Até 10 conexões; modelo de texto Doubao Ark e endpoint personalizado compatível; nome/Base URL/Model ID/chave ou modo local explicitamente sem chave; salvar rascunho, seleção atual, edição/exclusão, teste real breve de conexão, conversa de texto com várias mensagens e opção para limpar.
- Salvar e selecionar não acessa o provedor. Uma configuração incompleta não pode ser selecionada, testada nem usada em conversa. Usar somente endereço, modelo e autenticação salvos pelo usuário. Instruções separam Chat Completions comum do protocolo de voz em tempo real específico do Doubao; não alegar conexão de voz com o hardware.
- Arquivo privado único, gravação atômica e permissões POSIX 0600. A chave não é retornada como campo secreto e não entra no armazenamento persistente do navegador, logs ou pacote de diagnóstico; o campo é limpo após salvar. Trocar endereço/provedor não reutiliza a chave antiga. A senha Web já estava configurada, com sessão, proteção de Origin/CSRF; todas as respostas de IA usam no-store.
- O módulo de IA não depende de portas do robô e não executa ações, RPC nem código retornados pelo modelo. Não altera os serviços atuais de áudio, R3, música, modelo de movimento nem rede.

## Verificações executadas

| Escopo | Resultado |
| --- | --- |
| Armazenamento do novo recurso/cliente/HTTP real | 23 testes iniciais passaram; incluem leitura/gravação atômica, preservação de arquivo corrompido, mudanças de chave/URL, rascunho, login/CSRF, redação de dados sensíveis no diagnóstico, solicitação local simulada, limite de requisições e timeout. |
| Regressão ampla relacionada | 161 testes passaram em 120,400 s, antes das correções finais de resposta longa e deadline. O Windows preservou avisos de threads/recursos AF_UNIX de áudio padrão existentes; não foi declarado como validação Linux limpa. |
| Node | 29 verificações relacionadas passaram; também passaram 5 verificações direcionadas para resposta longa e ciclo de vida dos componentes. |
| Revisão independente da especificação | 24 verificações Python e 5 Node passaram, sem omissões nem implementação fora do escopo. |
| Revisão independente de qualidade | 16 verificações de cliente/HTTP passaram em 2,899 s; após corrigir o único problema importante de rede, a versão 991bb50 foi aprovada. |
| Edge local real final | Passou em 5,595 s, sem erros no painel de controle. Layouts 320/390/1440; rascunhos e duas conexões; salvar/selecionar sem solicitações externas; seleção atual preservada após recarregar; chave não exibida; teste breve; conversa após várias mensagens/resposta longa; 401/redação da chave em eco; limpeza e exclusão. O robô simulado não produziu ações por IA. |
| Testes de isolamento no pato | Usando módulo de staging congelado e diretório de teste temporário, passaram 21 testes em 1,283 s, incluindo Linux 0600 e recuperação de resposta lenta/cancelamento. O backend Web em execução não foi substituído, a configuração real do usuário não foi alterada e nenhum serviço público de IA foi acessado. |

O navegador fez solicitações HTTP reais a um provedor simulado local, que as recebeu; o fluxo distingue salvar/selecionar de teste/conversa efetivos. A chave simulada só existiu no estado temporário do teste; não era credencial do usuário e não entrou na imagem nem nos arquivos implantados.

## Problemas encontrados na revisão e correções

1. A substituição global de chaves curtas após serializar JSON alterava nomes de campos/identificadores. A exibição foi alterada para tratamento estruturado das strings, protegendo campos de esquema/identidade e redigindo separadamente a saída do modelo; foi adicionada regressão para `key='model'`.
2. A saída do modelo era limitada a 4000 caracteres, mas a validação antiga das mensagens de histórico aceitava só 2000; respostas longas faziam a rodada seguinte falhar. Ajustado para usuário 2000, assistente 4000 e total 12000; remove rodadas antigas completas em vez de cortar o conteúdo de uma rodada. No navegador real, a conversa continuou após resposta de 2501 caracteres.
3. O cliente antigo só verificava o tempo total após `getresponse()`; envio lento da linha de status/cabeçalhos podia ocupar duas vagas de trabalho por muito tempo, e timeout de espera async não encerrava a thread. Reprodução independente: timeout de 0,05 s levou realmente 0,812 s; depois de dois cancelamentos, chamadas seguintes continuavam ocupadas. A correção adicionou cancelamento por solicitação, preservação do socket real, interrupção watchdog de I/O conectado e limpeza em finally. Nova verificação: limite de 0,05 s encerrou em 0,062 s; após dois cancelamentos, a terceira chamada se recuperou em 0,015 s.

Limite: a resolução DNS do sistema da biblioteca padrão do Python não pode ser interrompida diretamente. Se a resolução/conexão só retornar depois do prazo, ela será fechada sem enviar credenciais nem solicitação. Não afirmamos que o DNS de todos os sistemas operacionais respeite um prazo absoluto. As solicitações de configuração não bloqueiam o loop de eventos Web e a concorrência de chamadas com erro é limitada.

## Pacote instalado

- Origem 991bb50, 8 arquivos em execução; staging: `/home/radxa/.web-ai-settings-20261026-86ab26ebd5`.
- Foram substituídos somente 8 arquivos de execução do Studio e reiniciado microduck-studio; PID 11672 → 27725. PIDs e horários de início de robotd 1097, padd 1135 e duck-echo 6325 permaneceram inalterados; todos os serviços estavam active, e o serviço de voz, enabled.
- O script de instalação confirmou novamente `policy_enabled=false` antes de parar o serviço Web, fazer backup e atualizar atomicamente. Backup em `/home/radxa/.microduck-backups/web-ai-settings-20261026-86ab26ebd5`, permissões 0700, com arquivos originais em execução, manifesto e dados do usuário; o script possui retorno em caso de falha.
- Verificação independente após implantação, `exit_code=0`: página inicial, healthz e todos os recursos relacionados responderam HTTP 200; hashes dos recursos Web e do disco coincidiram, assim como os hashes dos 8 itens do manifesto. Uma solicitação de configuração de IA sem login retornou 401; hashes dos 12 arquivos de dados originais do usuário permaneceram iguais. Após login, o fluxo foi validado no Edge local real com provedor simulado; não houve bypass do login no local nem gravação de chave ou teste de conexão na configuração real do dispositivo.
- Evidências: `deployment/apply_frozen_remote.result.json`, `deployment/device-verification.json`, `deployment/stop_before_update_remote.result.json`. Nesta rodada não foi recriada a imagem, ativada OTA nem alterado o Wi-Fi.
- Sem chave API real do usuário, não foi validada a nuvem Doubao nem outro provedor real; microfone/alto-falante, voz de ponta a ponta e acionamento de ações por IA ainda não estão conectados.

Instruções: [Guia de configuração](../../AI对话接入配置-20261027.md). Evidências em `artifacts/ai-provider-settings-20261026/` na raiz do workspace; o inventário de software classifica este recurso como F26. O problema físico do movimento musical continua sem aprovação, conforme o registro original.
