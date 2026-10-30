# Gravação, reprodução e movimentos expressivos na Web: implementação e validação da implantação em um dispositivo

Data: 25/10/2026 (horário de Tóquio; logs do dispositivo em UTC+8). O usuário autorizou: “Pode começar… movimentos expressivos… faça primeiro na versão Web” e depois escolheu explicitamente o endereço de controle existente do pato.

## Resultado e escopo desta rodada

Commit do código de execução: `c18783c9a2b2e2635124c6c4d53007e3fefb3ba6`, integrado por avanço rápido em `studio-dev`. As anotações existentes, ainda não commitadas, sobre o roteiro e a voz foram preservadas; o workspace não foi redefinido e o código de voz não foi alterado.

Na área de controle remoto existente, foram adicionados gravação, pausa/retomada, encerramento e salvamento com nome, descarte de rascunho, reprodução 1/3/5 vezes, pausa/retomada/parada, renomeação e exclusão. O estilo expressivo antigo da página de servos agora envia intenções por `robot.head`/`robot.mouth`; pode ser ativado separadamente ou durante uma gravação. Os alvos gerados são registrados, então a reprodução não os sorteia novamente.

A primeira versão limita cada gravação a 60 segundos, 6.000 eventos e 1 MiB, com até 20 gravações. Os dados ficam em `motion-recordings/` no estado do Studio e sobrevivem à atualização da página e à reinicialização. A gravação contém somente movimentos Web aceitos, intenções de cabeça/corpo/boca e sons conhecidos; não inclui áudio do microfone, vídeo da câmera, sentar/levantar, habilitação de torque, configurações ou habilidades do modelo. Como não há confirmação confiável de conclusão das habilidades, chutes, cambalhotas, coleta de objetos e outras habilidades são recusados antes do envio. Parar de enviar comandos não é tratado como prova de que uma habilidade física parou.

A gravação, os movimentos expressivos e a reprodução exigem que a política existente esteja pronta, que o estado seja recente e que não haja conflito com um controle físico; não levantam o robô nem habilitam torque automaticamente. Cada sessão tem um token próprio, heartbeat a cada 100 ms e expiração após 500 ms. Sair da área de controle, ir para segundo plano ou perder foco, desconectar, assumir o controle, conectar um controle físico, aliviar torque ou mudar o estado interrompe a sessão; reconectar não retoma a reprodução. Pausar limpa os alvos contínuos; retomar recupera as intenções de cabeça/corpo/boca, enquanto a velocidade aguarda o próximo quadro válido. Alvos atrasados são agrupados, sem rajadas para tentar recuperar movimentos vencidos. Uma gravação é recusada quando a impressão digital do conteúdo/configuração do modelo não corresponde.

## Validação do software

Foram aprovadas **351 verificações de software**: 203 verificações de backend de movimento/controle original (44 + 159), 140 regressões de HTTP/controle virtual original/visão geral/sensores, 7 testes Node do heartbeat e 1 teste de ponta a ponta do novo fluxo no navegador. Os problemas encontrados nas revisões independentes de requisitos e de código foram reproduzidos com testes e corrigidos; a revisão final não encontrou pendências.

Execute em `software/studio` (Windows, Python 3.13, dependências de execução existentes em `deps/`):

```powershell
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio','tests.test_pad'])"
node --test tests/motion_heartbeat.test.mjs
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_http','tests.test_vpad_e2e','tests.test_overview_e2e','tests.test_sensors_ui','tests.test_sensors_http'])"
py -3.13 -X utf8 -I -c "import sys;sys.path[:0]=['deps','.'];import unittest;unittest.main(module=None,argv=['x','tests.test_motion_studio_e2e'])"
```

O teste de navegador usou o Studio real, um `robotd` falso e o Edge. O fluxo completo de gravação expressiva, pausa/retomada, salvamento com nome, pausa/retomada/parada da reprodução, três ciclos limitados, renomeação, persistência após atualizar, parada ao trocar de página e exclusão foi concluído. Quadros de movimento válidos enviados: 30 na gravação, 18 em uma reprodução comum e 82 em três ciclos; os ciclos observados foram `[1,2,3]`, sem erros no console (`[]`). A reprodução agrupa quadros contínuos atrasados, portanto não tenta reenviar cada amostra vencida. As capturas de tela em desktop de 1440 px e celular de 390/320 px foram conferidas manualmente. Após a integração em `studio-dev`, outras 44 verificações de movimento passaram.

As evidências estão em `artifacts/web-motion-20261025/`: `backend-final.log`, `regression.log`, `browser-final2/browser.json` e `browser-final2/shots/`. As 203 e as 140 verificações finais foram aprovadas. Em uma rodada anterior, um teste existente de pareamento encontrou um arquivo de log temporário ainda em uso ao removê-lo no Windows. As asserções foram concluídas; o teste isolado passou cinco vezes seguidas e a suíte completa também passou. Esse problema preexistente de concorrência no encerramento não é apresentado como uma correção nova de pareamento.

## Conferência da implantação em duck-0de6

O destino foi `http://duck-0de6:8000/#/pad`, escolhido pelo usuário. Antes da troca, os arquivos do dispositivo foram comparados com os bytes do Git congelado; as versões das dependências foram conferidas, os caminhos de instalação não ultrapassavam os limites nem usavam links simbólicos e o Python compilava. A troca só ocorreu após a leitura imediata de `motion/control`, `policy_enabled=false` e a confirmação de que não havia sessão de servo.

Foram atualizados 12 arquivos:

```text
studio/motion_store.py       studio/motion_studio.py
studio/pad.py                studio/pad_drive.py
web/app.js                  web/pad.js
web/pad.css                 web/sensors.js
web/sensors.css              web/motion-heartbeat.js
web/motion-studio.js         web/motion-studio.css
```

Os recursos correspondentes de `app`, `sensors` e `pad` incluem versões locais anteriores com a integração da câmera e a recuperação do pareamento; isso evitou substituir apenas o arquivo de entrada e deixar dependências incompletas. A câmera real não foi ativada. Rede, modelo, programa principal, `padd`, Bluetooth e serviço de voz não foram alterados.

Somente `microduck-studio` foi parado e iniciado novamente; o PID mudou de 980 para 15333, e o serviço está ativo. Antes e depois da implantação, `robotd=1105`, `padd=1138` e `duck-echo=1110` mantiveram os mesmos horários monotônicos de início. Os três serviços continuaram ativos e a voz permaneceu habilitada. Os hashes SHA-256 dos 12 arquivos instalados coincidiram com o manifesto.

`/`, `/healthz`, `/pad.js` e os três novos arquivos estáticos retornaram HTTP 200; os hashes dos bytes JS/CSS servidos coincidiram com os arquivos instalados, e os recursos estáticos tinham `Cache-Control: no-cache`. Os logs mostraram que o Studio se conectou normalmente ao programa principal pela interface v40, sem erros nesta inicialização. Os 11 arquivos de dados do usuário existentes permaneceram byte a byte iguais aos do backup feito ao parar o serviço.

O dispositivo mantém a proteção de login Web existente; sem autenticação, `/api/session` retorna 401. A autenticação não foi alterada nem contornada para obter snapshots de movimento. O pedido para abrir a página de controle ficou na fila (`queued`) e a janela Edge estava minimizada; portanto, não se afirma que a entrada tenha sido vista na página autenticada real nem que o movimento tenha sido testado. O usuário foi informado para atualizar a página, entrar e experimentar os movimentos expressivos. **O efeito dos movimentos no robô real ainda aguarda confirmação do usuário.** Nesta rodada, nenhum comando de levantar, caminhar, executar movimentos expressivos ou reproduzir foi enviado ao pato real.

Backup privado: `/home/radxa/.microduck-backups/web-motion-20261025-e6610b5e21`, com permissões 0700, contendo os arquivos de execução anteriores à atualização, o estado do usuário, o manifesto e o recibo de sucesso. Os programas anteriores estão em `artifacts/web-motion-20261025/device-before/full-runtime/`; `deployment-manifest.json`, `deployment-result.json` e `device-verification.json` registram as conferências completas. Esses arquivos não fazem parte do pacote público.

Se a instalação ou a verificação de saúde do serviço falhar, o script de troca do dispositivo restaura os arquivos antigos e reinicia o Studio. Não houve falha que acionasse a reversão nesta rodada; o caminho automático não foi exercitado injetando uma falha real no dispositivo, portanto não se afirma que a reversão genérica de OTA tenha sido validada. Para restaurar manualmente, primeiro confirme que o pato está parado e sem sessão de servo; pare o Studio, restaure os arquivos conforme o manifesto de backup, remova somente arquivos novos que o manifesto indique como inexistentes antes da atualização, reinicie o Studio e valide o HTTP. O estado original foi preservado. O estado de usuário no backup serve apenas para recuperação em caso de corrupção e não deve substituir gravações salvas posteriormente.

## Entrega congelada e próximos passos

Diretório de entrega local: `artifacts/web-motion-20261025/release/`, com um arquivo-fonte do Studio gerado a partir do commit Git, manifesto de versões e hashes e uma cópia deste relatório. O pacote não contém o estado do dispositivo, senhas pessoais, chaves SSH, Wi-Fi doméstico, dados de pareamento ou gravações; é uma origem rastreável para manutenção e uma futura publicação de componentes, ainda não um atualizador Web de um clique.

Não foi criada uma nova imagem, ativado o `updaterd` nem publicado conteúdo remoto. A imagem existente continua na mesma versão. O próximo passo é concluir o teste de movimentos do usuário e, depois, organizar voz e Studio em um componente de versão unificada, definir instalação/migração/reversão genéricas e validar tanto cartões novos quanto sistemas existentes. Vincular controle e voz às reproduções salvas continua sendo um requisito futuro.

## Correção da avaliação de estado após a captura de tela do usuário

Em seguida, o usuário enviou uma captura da Web real, confirmando que as entradas “Gravação e reprodução de movimentos” e “Movimentos expressivos” já apareciam. Os botões estavam desabilitados e a postura mostrava “em pé (mantendo a posição)”, mas a página ainda dizia: “Uma habilidade do modelo ainda não tem estado de conclusão validável; pare a política manualmente primeiro”. Os logs mostraram que o usuário já havia executado sentar/levantar e “parar a política (permanecer em pé)”.

Uma leitura somente de consulta encontrou `robot.policies.enabled=true`, `homed=true`, `sitting=false`, enquanto `robot.busStatus.policy_enabled=false`, `mode=motion`, `phase=control` e `homed=true`. O código do programa principal confirma que o primeiro campo vem da configuração de inicialização `[policy] enabled`; não é o interruptor de execução. A primeira versão de `policy_feed` exigia incorretamente que tanto a configuração quanto o interruptor de execução fossem falsos. Assim, mesmo depois de a máquina real parar a política, não era possível registrar essa transição. O teste original colocava os dois interruptores em `false` e não cobria a configuração real que permanece `true`.

Correção no commit `db970dd470f7cc1586b1ce3a4ed6a2792b1f71ce`. Agora, uma leitura recente `bus.policy_enabled=false` confirma que a política realmente parou. Depois disso, o sistema ainda observa o interruptor de execução ativo, a permissão de configuração, `homed` nos dois lados e as condições de prontidão existentes; um recibo RPC de sucesso, por si só, não libera o bloqueio. Após confirmar a parada, a instrução passou a ser “Clique em ‘Começar a caminhar’ acima e aguarde a leitura recente confirmar ‘Pronto para caminhar’”. A barreira de habilidades não foi removida e os requisitos de estado para o comando normal de início não foram relaxados.

Foram adicionadas duas regressões de backend: com a configuração habilitada continuamente, parar → reativar → obter uma leitura recente de prontidão recupera a gravação e os movimentos expressivos; deixar a configuração desabilitada enquanto o interruptor de execução continua ligado não substitui a evidência de parada. O teste primeiro reproduziu a falha e passou após a correção. Ao final, **205 verificações de movimento/backend do controle original passaram**; a revisão independente repetiu as mesmas 205, sem pendências. O navegador também percorreu “habilidade do modelo → parar e permanecer em pé → botão desabilitado com instrução para começar a caminhar → começar a caminhar → botão habilitado” e, em seguida, o fluxo completo de gravação, reprodução, salvamento e troca de página. O teste de navegador passou: `skill_gate_recovered=true`, erros no console `[]` e layouts de 1440/390/320 px aprovados. As 140 regressões restantes e os 7 testes Node da primeira rodada não foram repetidos após esta correção específica; não são apresentados como uma nova validação completa da versão.

O commit db970dd foi implantado por SSH, atualizando somente `studio/motion_studio.py` e reiniciando somente o Studio (15333→21540). Os processos originais do robô, controle e voz continuaram com PIDs 1105/1138/1110 e os mesmos horários de início. Os quatro serviços estavam ativos e a voz habilitada. O SHA-256 do arquivo instalado foi `966c16c1f833baef6d314af899a0ad166a9c0ef8bda0ea2f60b9a015dd4f676b`; as verificações HTTP e de recursos estáticos passaram, e os 12 arquivos de dados do usuário permaneceram byte a byte iguais.

O backup privado desta troca está em `/home/radxa/.microduck-backups/web-motion-20261025-8ac5417e9b` (0700). A evidência lida do dispositivo está em `artifacts/web-motion-20261025/live-skill-gate-readback.json`; a evidência do navegador, em `skill-gate-browser/`. O manifesto de atualização do dispositivo, o recibo de sucesso, as leituras dos serviços/arquivos e o novo pacote de código-fonte congelado estão em `artifacts/web-motion-20261025-skill-gate/`; o registro da primeira rodada foi mantido.

O usuário foi orientado a atualizar a página, clicar em “Começar a caminhar”, esperar “Pronto para caminhar” e então ativar “Movimentos expressivos”. A captura do usuário confirmou que a entrada Web está visível. Ainda falta a resposta do usuário sobre os efeitos reais de cabeça e boca após a correção. Nenhum comando de movimento foi enviado pelo script desta rodada; a imagem não foi atualizada e o atualizador online genérico não foi ativado.
