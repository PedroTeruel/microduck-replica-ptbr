# Sentar e levantar nas gravações Web: validação e implantação

Data: 25/10/2026 (horário de Tóquio). O usuário informou que uma gravação contendo apenas sentar e levantar era rejeitada como “sem movimentos válidos” e confirmou: “Sim, inclua sentar e levantar também”. Esta rodada ampliou o escopo da primeira versão, que excluía as transições entre as posturas sentada e em pé. Consulte o [projeto](../specs/2026-10-25-web-posture-recording-design.md) e o [plano](../plans/2026-10-25-web-posture-recording.md).

**Resultado: atualização concluída no endereço de controle existente, e o usuário confirmou: “Consegui salvar; a reprodução de sentar e levantar também funcionou normalmente”.** Essa confirmação cobre a gravação, o salvamento e a reprodução Web de sentar e levantar neste pato; não significa que todas as habilidades de modelo ou movimentos prolongados tenham sido validados.

## Versão congelada e comportamento

O código de execução instalado corresponde ao commit `aa825fcf7ad153f959ed793e9ed871cabbc24e29`. Ele reúne 73c9a4f (backend, formato estrito e simulador), 396af04 (perda de evidências e limites temporais), 75ce49d (mensagens da página e fluxo completo do navegador) e aa825fc (transferência manual do controle durante sentar e levantar). A mudança foi integrada por avanço rápido a `studio-dev`; as anotações de voz e o código-fonte não rastreados foram preservados.

Agora, até uma gravação simples “sentar → esperar → levantar → esperar” pode gerar um rascunho e ser salva. As ações funcionam tanto pelos botões do controle remoto quanto pelo direcional na página. Sentar e levantar são registrados como alvos permitidos `studio.posture {target: sit|stand}`, em vez de salvar uma alternância genérica. Antes da reprodução, o sistema verifica a postura atual e não repete o comando se o robô já estiver na postura desejada. A próxima etapa só começa após confirmar uma fase de política recente e leituras coerentes e contínuas das articulações reais e dos alvos. O indicador de postura sentada desaparece assim que o movimento para levantar começa; ele ou `homed`, isoladamente, não comprovam que a transição terminou.

O novo módulo `motion_posture.py` mantém-se separado da sessão e da linha do tempo originais. Ele consulta a política, o horário das amostras e as articulações/alvos em `robot.state`, aguardando três amostras novas e distintas. As evidências de origem exigem dados recentes e coerentes com o barramento e a postura. Em uma medição somente de leitura, a maior diferença estática entre alvo e valor observado em oito amostras em pé foi de aproximadamente 0,1305–0,1318 rad. Foi adotada a tolerância de 0,18 rad, junto com estabilidade contínua e a fase correta da política; isso não garante uma posição física exata. A espera tem limite de 15 segundos. Uma confirmação desconhecida não provoca nova tentativa de alternância; confirmações tardias e quadros recebidos antes da confirmação não liberam a barreira da etapa seguinte.

Fases ou dados de articulações ausentes ou expirados, mudança para uma postura diferente do alvo, proteções existentes, conexão de controle físico, troca de página, segundo plano/perda de foco, desconexão e expiração do heartbeat cancelam as próximas saídas automáticas. A recuperação das evidências pode liberar a espera da etapa física, mas não retoma uma sessão cancelada. Pausar ou parar normalmente não interrompe fisicamente uma transição já iniciada entre sentado e em pé; a página informa claramente que a transição atual será concluída. Os controles contínuos são limpos e as etapas seguintes são congeladas ou encerradas, sem retorno automático a HOME nem alívio de torque; a parada de emergência continua usando o fluxo existente. Quando a postura real é conhecida e coerente, o usuário pode assumir manualmente o controle e solicitar explicitamente a postura oposta, para que a validação estrita da reprodução automática não impeça o comando manual normal de levantar. Ainda assim, não se repetem tentativas de um alvo cuja situação permanece desconhecida.

Gravações que incluem transições entre posturas usam a versão v2; a v1 continua legível. Permanecem os limites originais de 60 segundos, 6.000 eventos, 1 MiB e 20 gravações. Os intervalos de espera também contam para o limite de duração da gravação; durante a reprodução, a espera aumenta o tempo total real. Uma gravação que termina sentado pode ser reproduzida uma vez. Para repetir em ciclos, é necessário registrar o retorno à postura em pé no final; caso contrário, a repetição é recusada explicitamente, sem inserir uma ação implícita de levantar. Chutes, cambalhotas, coleta de objetos, habilitação/alívio de torque, ativação/desativação da política, troca de modelo e gravação de áudio ou vídeo continuam fora do escopo.

## Validação do software

Foram aprovadas **389 verificações** no código congelado, sem contar a revisão independente nem os testes repetidos após a integração:

| Escopo | Resultado final | Evidência (`artifacts/web-posture-recording-20261025/`) |
| --- | --- | --- |
| Sentar/levantar, movimentos e backend do controle original | 241 verificações, 33,480 s, OK | `backend-final2.log` |
| HTTP, controle virtual original, visão geral e regressão dos sensores | 140 verificações, 330,657 s, OK | `regression-final.log` |
| Sessão e heartbeat da página | 7 verificações, OK | saída das ferramentas Node desta rodada |
| Studio real + `robotd` falso + fluxo completo no Edge | 1 verificação, 64,262 s, OK | `browser-final.log`, `browser-final/browser.json` |

A revisão independente de requisitos reproduziu e corrigiu três falhas: retomada da reprodução após perda das evidências de uma etapa; continuação do movimento depois que uma alteração externa colocava o robô em pé; e possibilidade de o tempo de espera ultrapassar o limite de 60 segundos. A revisão independente de qualidade reproduziu e corrigiu uma falha: a validação estrita impedia levantar manualmente ou recuperar o controle de forma normal. As verificações foram aprovadas após as correções. A revisão de qualidade também executou 82 verificações aprovadas; após a integração em `studio-dev`, outras 82 foram aprovadas em 7,189 s.

Comandos executados no diretório `software/studio`:

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_posture','tests.test_motion_studio','tests.test_pad'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

No navegador, as solicitações de sentar e levantar enviadas ao `robotd` falso foram: 2 durante a gravação, 2 em uma reprodução simples e 6 em três ciclos. Ao parar imediatamente depois de sentar, foi enviada apenas uma solicitação; ao trocar de página, também apenas uma, sem a etapa posterior de levantar. O JSON salvo usa v2, com os alvos `sit` e `stand` nessa ordem. Erros no console: `[]`. Os layouts para desktop de 1440 px e celulares de 390/320 px, incluindo as capturas de tela, foram aprovados. Os testes existentes de movimentos expressivos, salvamento, renomeação, persistência após atualizar a página, exclusão e pausa/retomada da reprodução foram mantidos.

Um teste anterior confirmou primeiro o comportamento antigo, que encerrava a gravação ao sentar. Um teste longo no navegador foi cancelado corretamente porque o Windows ocultou a aba headless; os registros confirmaram `hidden`, `activity=false` e a solicitação de parada. Depois, o teste manteve a página ativa por meio da simulação de foco, sem alterar as proteções de segundo plano ou perda de foco do produto. Em outra execução, os testes pareados originais (241 verificações) encontraram `WinError 145` ao limpar um diretório temporário de logs. O caso isolado passou cinco vezes em sequência e a suíte completa também foi aprovada; o código não relacionado dos testes de pareamento não foi alterado. Os registros antigos foram preservados; não se afirma que a contenção de recursos preexistente dos testes tenha sido resolvida.

## Troca no dispositivo e confirmação do usuário

Primeiro, o usuário confirmou explicitamente que a política estava parada e o robô permaneceria em pé. O script de instalação voltou a verificar `motion/control`, `policy_enabled=false` e a ausência de uma sessão de servo antes de trocar o Studio. Após conferir os bytes do Git congelado e as versões das dependências, foram atualizados somente estes sete arquivos:

```text
studio/motion_posture.py    studio/motion_store.py
studio/motion_studio.py    studio/pad.py
studio/pad_drive.py        web/motion-studio.js
web/motion-studio.css
```

Somente `microduck-studio` foi reiniciado; o PID mudou de 21540 para 29493. Os PIDs e horários monotônicos de início de `robotd=1105`, `padd=1138` e `duck-echo=1110` permaneceram iguais. Os quatro serviços continuaram ativos, e o serviço de voz permaneceu habilitado. Os hashes dos sete arquivos instalados coincidiram com o manifesto; os 12 arquivos existentes de dados do usuário e o backup feito ao parar o serviço Web permaneceram byte a byte iguais. A página raiz, `healthz`, `pad.js` e os recursos de movimento retornaram HTTP 200; os hashes dos JS/CSS servidos corresponderam aos arquivos instalados, e os recursos estáticos estavam configurados como `no-cache`.

O backup privado está em `/home/radxa/.microduck-backups/web-motion-20261025-aea50f88a1` (permissão 0700), com os arquivos de execução anteriores, manifesto e lista de dados protegidos. O diretório `artifacts/web-posture-recording-20261025/deployment/` do workspace contém os programas anteriores à atualização, o manifesto, o resultado da troca e a conferência posterior. As amostras reais de articulações, somente para leitura, estão em `actual-posture-samples.json` e não fazem parte da entrega genérica. A proteção de login existente foi mantida; nenhum snapshot de ações sem autenticação foi acessado. Os testes automatizados não enviaram comandos de sentar ou caminhar ao pato real.

Depois da instalação, o usuário seguiu “começar a caminhar → iniciar gravação → sentar → esperar a confirmação → levantar → esperar a confirmação → encerrar → nomear e salvar → reproduzir uma vez” e respondeu **“Consegui salvar; a reprodução de sentar e levantar também funcionou normalmente”**. Isso foi registrado como validação em equipamento real para esta funcionalidade.

## Limites da entrega e da reversão

O arquivo-fonte congelado, o manifesto de versões e hashes e a cópia do relatório de validação estão em `artifacts/web-posture-recording-20261025/release/`. A entrega não inclui senhas pessoais, chaves SSH, Wi-Fi doméstico, pareamentos nem arquivos de estado. Não houve reconstrução da imagem, ativação do `updaterd` ou publicação pública nesta rodada. Um pacote ou imagem futuro deve ser validado usando a mesma origem congelada.

Se a troca de um único dispositivo falhar, o script restaura os arquivos anteriores de execução e reinicia somente o Studio. A troca atual foi concluída com sucesso, portanto não houve injeção de falha real para testar a reversão. Para reverter manualmente, primeiro pare a política e confirme que não há sessão de servo; pare o Studio, restaure os arquivos conforme o manifesto e remova apenas os módulos novos marcados como inexistentes antes da troca. Depois, inicie o Studio e valide a Web. Os movimentos salvos posteriormente devem ser preservados; não substitua o estado atual diretamente pelo backup antigo. Código que só suporte v1 ignorará gravações v2; isso não é motivo para excluir os arquivos nem tratá-los como corrompidos. Ao restaurar o código novo, eles voltarão a ser legíveis.
