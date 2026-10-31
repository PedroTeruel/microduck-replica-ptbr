# Auxiliar de root do Studio: transferência do barramento dos servos, gravação da calibração e pareamento do controle (instalação, remoção e verificação no robô)

Este documento explica cada etapa e sua finalidade para usuários e para quem for dar continuidade ao trabalho.

## Refazer a calibração inicial da IMU (`imu-recalibrate`)

Na versão 0.7.2, o verbo fixo `enter` aceita o parâmetro opcional `profile="legacy"|"qinmo"`, que a página IMU seleciona uma vez e salva. O parâmetro não aceita comandos, caminhos nem serviços. O recurso exige evidência explícita da capacidade `configured_imu_profile` na nova versão do `robotd`; a compatibilidade não é decidida apenas pelo número da versão da API. Qinmo é identificada como configuração e oferece suporte a Feetech; a velocidade angular é `raw/16.4 °/s`. As placas existentes continuam com detecção automática por padrão e usam `raw×0.0175 °/s`. Consulte o [guia de uso da página Web](../../../docs/Qinmo-IMU-uso-web.md) para o procedimento do usuário.

As operações de tipo mantêm ao mesmo tempo o lock do auxiliar e `/run/microduck-service-management.lock`. Elas recusam conflitos com atualização, uso do barramento ou uma sessão antiga de repetição de calibração; pausam o controle e o serviço fixo de voz `duck-echo`, restaurando o estado original dos serviços ao terminar com segurança. Durante a sessão, a interface Web também recusa comandos de controle, mas mantém disponíveis o alívio de torque e as operações de calibração necessárias. O auxiliar só altera os parâmetros efetivamente usados pelo `ExecStart` direto do `robotd`: `--params /etc/robot/feetech-ft5/robotd.toml`, `--socket /run/robotd.sock`, os overrides de serviço conhecidos, o arquivo `saved` dessa configuração e os arquivos de calibração reconhecidos. Cada etapa recusa links simbólicos e diretórios ou arquivos que não pertençam ao root ou que possam ser modificados por outros usuários. Também recusa sistemas somente leitura, overrides externos, origem I²C, protocolos sem suporte e caminhos de calibração desconhecidos. Nos arquivos principal e `saved`, altera apenas `bus.imu_profile` e o campo compatível `bus.imu_protocol`; compara os valores antes e depois da análise para garantir que todo o restante permaneça igual, inclusive chaves entre aspas e arrays de políticas em linha única usados pela imagem. Os bytes originais, proprietário, permissões, resumo criptográfico e modo são preservados em backup antes da operação. Na calibração, somente a marca de orientação de instalação verificada no barramento é apagada, impedindo o reaproveitamento de uma orientação antiga do mesmo tipo.

O controle normal mantém os requisitos existentes: duas leituras recentes confirmando estado desabilitado, ausência de política ativa e restauração dos ganhos. A recuperação de inicialização antes do controle nos estados `configuring_bus` e `waiting_for_bus` só é aceita quando suportada e validada pelo ciclo de vida atual do daemon e pelas capacidades da configuração; ela não afirma que o torque físico está desligado e sempre entra no modo de calibração. No modo de calibração original de fábrica, é possível escolher o tipo e manter o fluxo de fábrica depois da validação. Se uma recuperação de inicialização for cancelada, o auxiliar instala primeiro o modo de calibração de fábrica conhecido, remove o arquivo de modo temporário usado pela repetição, restaura a configuração e a calibração originais e encerra a sessão. O robô permanece no modo de calibração para permitir outra seleção, evitando deixar uma sessão cancelada bloqueada permanentemente. O cancelamento de uma operação normal restaura exatamente a configuração, a calibração e o modo anteriores.

A operação só é concluída se o resumo criptográfico confirmar que as configurações de tipo principal e `saved` em disco permanecem correspondentes, se a configuração em execução corresponder ao tipo detectado e se a associação entre protocolo e perfil da nova orientação, incluindo o estado `verified`, for lida de volta sem divergências. Em caso de falha, os arquivos originais são restaurados. Se não for possível restaurá-los, o auxiliar mantém `recovery_required` e o backup original para que a recuperação possa continuar. As operações comuns de commit, repetição e cancelamento preservam o campo opcional `imu_bus_profile`; o padrão continua sendo `legacy`. Uma mudança de tipo invalida capturas, cálculos em andamento e resultados aguardando gravação. Qinmo não pode ser marcada como verificada por meio de “Pular” nem de uma gravação comum: é necessária a validação pelo programa principal. Ainda não houve validação no hardware físico. Esta alteração não atualiza a imagem pública nem implanta o `robotd` automaticamente.

A nova versão do auxiliar inclui o verbo fixo `imu-recalibrate`. A entrada padrão aceita somente uma destas quatro ações: `enter`, `status`, `finish` ou `cancel`; não é possível especificar comandos, caminhos ou serviços. Mesmo no modo de movimento, é permitido refazer a validação quando já houver `verified=true` e um quaternion salvo: estabilize o robô, alivie o torque e execute `enter`. O auxiliar lê o estado recente duas vezes e exige `motion/control`, `policy_enabled=false`, nenhuma transição para ficar em pé, confirmação explícita de torque nativo desligado, nenhum alívio de torque pendente e restauração dos ganhos temporários do HD1910. O serviço do controle é parado antes de uma segunda verificação desses requisitos. Qualquer estado ambíguo causa a recusa da operação.

- **Iniciar:** `{"by":"Studio","action":"enter","confirmed":true}`. Mantém os parâmetros efetivos de inicialização direta do `robotd` e acrescenta somente `--commissioning`; comandos wrapper ou um `ExecStart` ambíguo são recusados. O arquivo de fábrica `zzzz-zz-microduck-commissioning.conf` não é usado nem removido.
- **Consultar o estado:** `{"by":"Studio","action":"status"}`. A sessão informa `active/phase/session_id/source`; a página lê o manifesto público somente leitura, sem executar `sudo` em cada atualização de estado.
- **Concluir:** `{"by":"Studio","action":"finish","session_id":"…","source":"bus","quat":[1,0,0,0]}`. Só é aceito depois que `verify-imu` for aprovado e a origem atual, `verified`, o quaternion normalizado e cada campo do arquivo de calibração forem lidos de volta e corresponderem ao esperado. O verificador original define `motion_enabled` como false; o auxiliar restaura somente o valor que existia antes de iniciar. Todos os outros campos, exceto a orientação de instalação do chip atual e `verified`, devem permanecer iguais. O auxiliar não recria todo o arquivo de calibração nem substitui por padrões o zero diferente de 2048, as direções, os limites, outra IMU ou configurações desconhecidas. Se o programa principal não preservar esses campos, a operação é recusada e a sessão permanece disponível para cancelamento e restauração.
- **Cancelar:** `{"by":"Studio","action":"cancel","confirmed":true,"session_id":"…"}`. Restaura separadamente os backups originais da calibração principal e do arquivo `saved`, além do modo anterior e do estado do serviço do controle. O cancelamento não conta como uma nova calibração concluída.

O estado da sessão é salvo persistentemente em `/var/lib/microduck-helper/imu-recalibrate/manifest.json` (`root:root`, modo 0644). Cada `<session_id>/` tem um diretório de backup próprio, modo 0700; os arquivos de calibração principal e `saved`, além da calibração original analisada, são copiados separadamente e verificados por SHA-256. O diretório pai usa modo 0755 e os registros de operações continuam em 0600. A sessão usa seu próprio arquivo persistente de modo do serviço: `/etc/systemd/system/robotd.service.d/zzzzzz-studio-imu-recalibrate.conf`. O arquivo contém o ID da sessão e um resumo do conteúdo; o auxiliar só pode removê-lo se ainda corresponder exatamente ao arquivo criado pela própria sessão. A sessão é recuperada ao reiniciar o Studio ou atualizar a página, e o arquivo de modo permanece após uma queda de energia. Uma falha ao iniciar restaura o estado anterior. Uma falha ao concluir restaura o modo de calibração seguro já validado, permitindo repetir a validação original ou cancelar. O serviço do controle só é reativado quando o robô estiver no modo de movimento, a leitura completa da calibração corresponder e o estado estiver desabilitado.

`imu-recalibrate` compartilha `helper.lock` com as operações do barramento e de calibração. Enquanto a sessão estiver ativa, `bus-take` e `calib-commit` comuns são recusados; o botão de alívio de torque na página continua disponível. A desinstalação, inclusive com `--purge`, é recusada se houver uma sessão incompleta ou cujo estado não possa ser lido. Conclua ou cancele a sessão antes, para que o backup de recuperação não seja apagado. O fluxo mantém a calibração inicial existente (3 segundos parado e 3 segundos inclinado para a frente) e a validação em execução com o robô ereto e a cabeça inclinada. No modo de calibração de fábrica, o procedimento original é usado diretamente.

Referências de planejamento: scratchpad `console/handover-plan.md` (versão final v2), seções 2.2, 4.2 e 5; regras em `console/studio-ops-plan.md`, seção 7.

## 1. Para que serve

A página Servo do Studio precisa abrir diretamente o barramento `/dev/ttyS2`. Por isso, o programa principal `robotd` deve ser parado antes e retomado ao terminar.

- Parar e iniciar o `robotd` exige root, mas o Studio não roda como root.
- Por isso, o Studio recebe somente uma “chave para uma porta”: o `sudoers` autoriza apenas o arquivo `/usr/local/sbin/microduck-helper`.
- O auxiliar aceita somente doze verbos fixos, valida cada parâmetro e consulta por conta própria o estado do `robotd`, sem confiar no que a página Web informa. Na versão 0.5.0, foram adicionados `calib-read` e a detecção do modo real de inicialização do fork por `calib-commit`; na 0.5.2, snapshots em tempo real do modo de calibração também passaram a confirmar que o programa principal iniciou durante `bus-give-back`; na 0.6.0, foram adicionados `ssh-status` e `ssh-password` para controlar o SSH pela página “Mais”; na 0.7.0, foi adicionado `imu-recalibrate`, que mantém persistentemente a sessão para refazer a calibração inicial da IMU.

**`busStatus` no modo de calibração** (método `robot.busStatus` em `robotd/src/main.rs` e `Status` em `feetech_commissioning.rs` do fork): ao iniciar, o `robotd` grava primeiro um relatório de inicialização `{"build","mode":"commissioning","phase":"configuring_bus","port"}` e continua retornando esse relatório enquanto a fase ainda for de inicialização. Só depois da primeira leitura bem-sucedida retorna snapshots em tempo real (`phase` `ready`, `moving`, `read_error`, `stop_unconfirmed` ou `power_pending`, com `last_sample`). Versões antigas do fork nunca limpam o relatório. Ao devolver o barramento pela página Servo, o auxiliar aguarda 30 segundos e retorna `soft_failed` (`detail.still_starting = true`), informando que o programa continua relatando inicialização — sem afirmar que não conseguiu iniciar. É necessária uma versão atualizada do fork, incluída em imagens posteriores a 20/10/2026.

**Modo de calibração na imagem de fábrica:** a imagem inclui `/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf`, com `--commissioning` em `ExecStart`. (No fork, consulte `main.rs:1300-1315`: o modo em `busStatus` depende somente do argumento de inicialização, não do conteúdo do arquivo de calibração.) Nesse modo, `calibration-status` responde imediatamente, `busStatus` inclui `last_sample` (os 15 servos e `imu`) e `verify-imu` grava a orientação no arquivo de calibração. No modo de movimento, uma calibração inválida ou a falha ao abrir o barramento deixa o programa em `waiting_for_bus`; `calibration-status` responde `calibration not available yet`. Depois que a etapa 3 grava os dados com sucesso, o auxiliar remove esse arquivo, executa `daemon-reload` e reinicia o `robotd`, que volta ao modo de movimento. Se `ExecStart` contiver `--commissioning`, mas o arquivo não estiver presente, o auxiliar recusa a troca automática (`foreign_commissioning`) e orienta exportar um pacote de diagnóstico pela página de registros.

## Diferenças entre a imagem e a instalação manual

O cartão “Conectar ao Wi-Fi” depende de quatro componentes da imagem da réplica; o Studio sozinho não os fornece:

- estado de rede gravado pelo netcheck em `/run/microduck/net.json`;
- configuração `Microduck-Hotspot` no NetworkManager;
- `configd` iniciado com `--allow-user btd,radxa`;
- configuração mDNS para resolver `duck-xxxx.local`.

Se o Studio e o auxiliar de root forem instalados manualmente conforme este documento, mas o robô não tiver os overlays da imagem da réplica, esses componentes não estarão disponíveis e o cartão “Conectar ao Wi-Fi” não aparecerá. Visão geral, Controle, Servo, IMU, Registros e a configuração de senha pela Web continuarão funcionando normalmente.
Defina a senha pela página “Mais → Senha de login”. Para usar `python3 -I run.py set-password`, execute como usuário `radxa`, sem `sudo`; caso contrário, o Studio não conseguirá ler o arquivo de senha.

| Verbo | Entrada padrão (um objeto JSON) | Função |
|---|---|---|
| `bus-take` | `{"by": "quem·qual computador", "allow_seated": false}` | Assume o barramento **sem aliviar o torque**: para o serviço do controle; lê o estado do programa principal duas vezes, com intervalo de 200 ms (recusa se uma política estiver ativa; só permite a postura sentada quando `allow_seated` estiver definido e o robô não se mover; aguarda até 3 s se estiver voltando à postura em pé); cria o marcador; executa `systemctl stop --no-block robotd`; após 10 s, envia `KILL`; confirma que a porta serial está livre. |
| `bus-give-back` | `{"by": …, "soft": true}` | Devolução suave: o Studio já aliviou todos os servos no barramento. Remove o marcador, inicia o `robotd`, aguarda o sucesso das quatro etapas de inicialização e confirma que o programa iniciou (no modo de movimento, `phase=control`; no modo de calibração, snapshot em tempo real nas fases `ready`, `moving`, `read_error`, `stop_unconfirmed` ou `power_pending`; `read_error` também conta como iniciado, e a mensagem original é preservada em `reason`); reinicia o serviço do controle e libera o lock. Se após 30 s ainda houver uma fase de inicialização, retorna `soft_failed` e `detail.still_starting = true`. |
| | `{"by": …, "marker": {…}}` | Devolve o barramento sem aliviar o torque: grava o marcador de transferência, remove o marcador de posse (**mantém o lock**), inicia o `robotd` e aguarda que ele assuma o controle mantendo os servos como estão, sem iniciar o modelo. Se não assumir, o Studio retoma o barramento e continua mantendo os servos. O modo de calibração não aceita esse marcador (a aquisição do barramento alivia todos os servos primeiro); ao receber o primeiro snapshot em tempo real, retorna `limp`, sem esperar 15 s para retomar o barramento. |
| `bus-abort` | `{"by": …}` | Cancela a transferência quando o usuário toca no botão web de alívio durante a contagem: cria o marcador de posse, envia `KILL` ao `robotd`, remove o marcador de transferência e confirma que a porta serial está livre. A meta é concluir em até 1 s; depois, o Studio abre a serial e alivia o torque. **Sem sessão, a operação é recusada (código 3):** se não houver marcador, lock de gerenciamento nem marcador de transferência, nada é alterado. |
| `pad-pair` | `{"by": …, "mac": opcional, "timeout": 10–120 (padrão 60)}` | Executa como root o comando oficial `/usr/local/bin/robotctl pad pair --json --timeout N [MAC]`. Converte o MAC para maiúsculas antes de validá-lo. O prazo total do processo filho é `timeout + 30` segundos; ao expirar, ele é encerrado. Na placa `/var/lib/robot/weird-ble`, o `robotctl` para o `btd`, desliga e religa o adaptador e inicia o `btd` novamente. **Não altera** o marcador do barramento, a unidade hold nem o `robotd`, e não usa o lock de gerenciamento de serviços. Usa somente `helper.lock`, permitindo um pareamento por vez. |
| `pad-forget` | `{"by": …, "mac": …}` | Executa como root o comando oficial `/usr/local/bin/robotctl pad forget MAC`; o MAC é obrigatório e passa pela mesma validação. Também não altera o barramento, a unidade hold nem o `robotd`. |
| `wifi-hotspot-down` | `{"by": …, "ssid": opcional}` | **Antes de desligar o ponto de acesso**, grava `/run/microduck/studio-connecting.json` (`root`, modo 0644, `until` = horário atual + 90 s, com o SSID de destino; grava primeiro em arquivo temporário e depois renomeia; diretório 0755), impedindo a interferência do netcheck durante esse período. Em seguida, executa `nmcli connection down Microduck-Hotspot` (prazo de 15 s). Se o ponto de acesso já estiver desligado, considera sucesso; a mensagem do nmcli “not an active connection” também é tratada como sucesso. Aguarda até 10 s para que `wlan0` deixe de usar essa conexão. **Não altera** o marcador do barramento, a unidade hold nem o `robotd`; não usa `helper.lock`, somente `wifi.lock`. |
| `wifi-hotspot-up` | `{"by": …}` | Executa `nmcli connection up Microduck-Hotspot`. Se já estiver ativo, considera sucesso. Aguarda até 30 s para confirmar que `wlan0` realmente se conectou. Depois, remove `/run/microduck/studio-connecting.json`; a ausência do arquivo não é erro. Também não altera o barramento dos servos e usa `wifi.lock`. |
| `calib-read` | `{"by": …}` (opcional) | Somente leitura do arquivo de calibração atual. Retorna `calibration` analisado, o modo atual (`commissioning`, `motion` ou `foreign`), se o drop-in de calibração existe e se `ExecStart` contém `--commissioning`. **Não usa `helper.lock` nem grava arquivos**; serve de alternativa para o Studio quando o programa está no modo de movimento, permanece em `waiting_for_bus` e não retorna `calibration-status`. |
| `calib-commit` | `{"by": …, "joints": [{"id", "direction"} × 15], "imu": {"source": "bus\|bno08x\|lsm6dsv16x", "quat": [w,x,y,z]}, "dry_run": false}` | Grava os zeros dos servos (2048), as direções e a orientação de montagem da IMU em `hd1910-calibration.toml` do `robotd`. Ordem: **obtém `helper.lock` e depois verifica o marcador `bus-held`**. No modo de calibração, ignora o requisito de postura. No modo de movimento, lê `busStatus` duas vezes, com intervalo de 200 ms; recusa se uma política estiver ativa ou se o robô estiver em pé (código 3). Detecta o modo: se existir o arquivo da imagem `zzzz-zz-microduck-commissioning.conf`, está em calibração (após gravar, remove o arquivo, executa `daemon-reload` e muda para movimento); se o arquivo não existir e `ExecStart` não contiver `--commissioning`, está em movimento e somente a calibração é substituída; se `ExecStart` contiver o argumento, mas o arquivo estiver ausente, retorna `foreign_commissioning` e não tenta mudar o modo automaticamente (código 3). Lê o arquivo atual, agrupa o novo conteúdo pelas faixas de limites padrão e valida cada campo, como `Calibration::validate` no fork. Cada gravação cria `calib-backups/<sequência de 4 dígitos>-<UTC>/`, com o arquivo principal, `.saved.toml`, arquivo de calibração e `manifest.json`; a sequência usa o maior valor existente +1 e mantém os 10 backups mais recentes. `.previous`, `.toml` e `.saved.toml` são gravados primeiro em arquivos temporários, com `fsync` e `rename`, preservando proprietário e permissões originais; em seguida, são lidos de volta e conferidos campo a campo. Qualquer falha após o início da gravação aciona reversão antes de retornar o erro. Depois de reiniciar o `robotd`, aguarda até 40 s pelo `hello`; em seguida, consulta `robot.busStatus` a cada 0,5 s, por no máximo 30 s. **Sucesso exige `mode=="motion"`, `phase=="control"` e que `calibration-status` confirme exatamente os 15 servos (name/id/zero_raw/direction/calibrated/min_rad/max_rad), `motion_enabled`, `imu_mount_quat` e `imu_mount_verified` da placa de barramento e cada quaternion e estado `verified` em `imu_mounts` (tolerância de ponto flutuante 1e-9).** Conforme a causa, a falha retorna `calib_rejected` (validação recusada pelo programa principal) ou `bus_unavailable` (barramento indisponível; confira a alimentação dos servos) e reverte as alterações. Sem `dry_run`, toda a operação roda em uma unidade independente por meio de `systemd-run` e grava o resultado em `last-result.json`. Com `dry_run: true`, para após a validação e retorna o texto completo somente em `detail.toml`, sem gravar arquivos nem reiniciar serviços. |
| `ssh-status` | `{"by": …}` (opcional) | Somente leitura: informa se o login SSH por senha está ativo (presença de `05-microduck-ssh-password.conf`), se o serviço `ssh` está em execução e quantas chaves constam em `authorized_keys` do usuário `radxa`. Não obtém locks nem grava arquivos; também não substitui `last-result.json`. |
| `ssh-password` | `{"by": …, "on": true, "password": "…"}` / `{"by": …, "on": false}` | Para ativar, a senha precisa ter entre 8 e 64 caracteres visíveis e não pode ser fácil de adivinhar, como `microduck` (caso contrário, retorna `bad_password`, código 2). Obtém `ssh.lock`, usa `chpasswd` para definir a senha de `radxa` pela entrada padrão e grava `/etc/ssh/sshd_config.d/05-microduck-ssh-password.conf` (`PasswordAuthentication yes`). Só executa `systemctl reload-or-restart ssh` se `sshd -t` passar e `sshd -T` confirmar `passwordauthentication yes`. Se uma etapa falhar, remove o arquivo e reverte a configuração (`sshd_config_bad`, `not_effective` ou `reload_failed`). Para desativar, remove o arquivo e recarrega o serviço; a senha de `radxa` permanece (e continua sendo usada pelo sudo). **A senha só é enviada pela entrada padrão; nunca vai para a linha de comando, o journal, `last-result.json` ou o oplog.** |

**Saída:** uma linha JSON por etapa, no formato `{"step", "level", "ms", "msg", "detail"}`. A última linha usa `step="done"`, e `detail` contém `exit` e `result`. O mesmo resultado é gravado em `/run/microduck-helper/last-result.json` (modo 0644) para que o Studio possa consultá-lo depois de reiniciar.

O campo `detail` de `pad-pair` também inclui `pair` (saída do robotctl analisada como `PadPairResult`: `{"outcome":"paired","pad":{…}}` ou `{"outcome":"failed","reason":"not_found|ambiguous|timeout|no_adapter|rejected|other","detail":…}`), `stderr` (mensagens breves do robotctl, como `paused btd …` e `warning: …`) e `stdout`. Um pareamento concluído retorna código 0; se o robotctl informar falha, retorna 5 e preserva o motivo oficial em `detail.reason`. O campo `detail` de `pad-forget` inclui `removed` (`true`, `false` ou `null`), `stdout` e `stderr`.

**Códigos de saída**

| Código | Significado |
|---|---|
| 0 | Sucesso |
| 2 | Argumentos inválidos (verbo desconhecido, entrada padrão que não é um objeto JSON, chave desconhecida ou validação do marcador reprovada). |
| 3 | Estado não permitido (proteção não instalada, política ativa, robô em pé ou andando, sessão ausente ou processo sem root; `calib-commit` também pode retornar `bus-held` ou `foreign_commissioning`). |
| 4 | Ocupado ou cancelado (lock de gerenciamento mantido por um script da placa, auxiliar executando outra operação de barramento, outro pareamento ou remoção de controle, outra operação do ponto de acesso ou devolução interrompida). |
| 5 | Falha de execução (não foi possível parar o serviço, serial ocupada, `robotd` não confirmou que todos os servos foram liberados pelo marcador, devolução suave falhou; `pad-pair`/`pad-forget` não encontrou o robotctl, o robotctl recusou o pareamento ou encerrou por timeout; falha ao ligar/desligar o ponto de acesso, erro ou timeout do nmcli; falha de gravação ou reinicialização em `calib-commit`, modo de movimento não iniciado ou leitura de retorno divergente; as alterações foram revertidas). |
| 6 | Transferência não concluída e barramento retomado pelo Studio (marcador de posse recriado, `robotd` parado e lock mantido); o Studio reabre a serial e continua mantendo os servos. |

Valores possíveis de `result`:

- `bus-take`: `taken`, `refused`, `no_guard`, `busy`, `stop_failed`, `port_busy`.
- `bus-give-back`: `adopted`, `retake`, `retake_failed`, `limp` (marcador não reconhecido no modo de movimento ou modo de calibração), `aborted`, `soft`, `soft_failed` (se a inicialização continuar sendo informada, `detail.still_starting = true` e `detail.msg` contém a mensagem completa), `refused`, `no_session`, `detach_failed`.
- `bus-abort`: `aborted`, `abort_incomplete`, `no_session` (sem sessão, operação recusada com código 3).
- `pad-pair`: `paired`, `pair_failed` (código 5; `detail.reason` mantém o motivo oficial), `timeout`, `no_robotctl`, `bad_output`.
- `pad-forget`: `forgotten`, `forget_failed`, `timeout`, `no_robotctl`.
- `wifi-hotspot-down`: `hotspot_down`, `already_down`, `down_failed`, `timeout`, `nmcli_failed`.
- `wifi-hotspot-up`: `hotspot_up`, `already_up`, `up_failed`, `timeout`, `nmcli_failed`.
- `calib-read`: `read`. `detail` inclui `calibration`, `mode` (`commissioning`, `motion` ou `foreign`), `commissioning_present`, `exec_has_commissioning` e `mode_text`; não usa lock nem grava arquivos.
- `calib-commit`: `preview` (simulação), `committed` (`mode=motion`, `phase=control` e todos os campos de `calibration-status` conferidos), `not_motion` (não entrou no modo de movimento em 30 s), `calib_rejected` (calibração recusada pelo programa principal), `bus_unavailable` (barramento dos servos não abriu), `readback_mismatch` (entrou no modo de movimento, mas a leitura divergiu), `bus_held`, `no_calibration`, `bad_calibration`, `joint_mismatch`, `invalid`, `bad_toml`, `restart_failed`, `write_failed`, `backup_failed`, `read_failed`, `foreign_commissioning`, `refused` (política ativa ou robô em pé). Nos resultados de falha, `detail.rolled_back`, `files_restored`, `mode_restored` e `robotd_up_after_rollback` são informados separadamente; também podem aparecer `readback_ok`, `mismatches`, `bus_status` (último modo/fase/erro) e `backup`. Se a própria reversão não for concluída, `msg` orienta exportar um pacote de diagnóstico pela página de registros.
- Qualquer operação pode retornar: `bad_args`, `bad_marker`, `bad_verb`, `not_root`, `busy` ou `error`.

## 2. Arquivos e caminhos

| Item | Caminho | Finalidade |
|---|---|---|
| Auxiliar | `/usr/local/sbin/microduck-helper` (`root:root`, modo 0755, `#!/usr/bin/python3 -IS`) | `-I` ignora o ambiente e o diretório do usuário; `-S` não carrega `site`. No Linux, o texto depois do shebang é passado como um único argumento; por isso se usa `-IS`, e não `-I -S`. |
| Drop-in do robotd | `/etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf` | `ConditionPathExists=!/run/microduck-helper/bus-held`: enquanto o marcador existir, o `robotd` não inicia. **Não use `systemctl mask --runtime`**: a unidade do `robotd` está em `/etc`, e um mask em `/run` não a sobrepõe. |
| sudoers | `/etc/sudoers.d/microduck-studio` (0440) | Autoriza somente um caminho absoluto. Valide com `visudo -cf` antes de instalar. |
| Marcador do barramento | `/run/microduck-helper/bus-held` (diretório 0755, arquivo 0644) | Fica no sistema de arquivos em memória e desaparece após queda de energia ou reinicialização; o `robotd` volta a iniciar normalmente. Não fica no diretório do Studio porque o systemd poderia removê-lo ao reiniciar o Studio se a unidade usasse `RuntimeDirectory`. **A unidade do Studio não deve usar `RuntimeDirectory=microduck-helper`.** |
| Solicitação de cancelamento | `/run/microduck-helper/abort` | É criada por `bus-abort`; a operação `bus-give-back` em andamento a detecta e para. |
| Lock do auxiliar | `/run/microduck-helper/helper.lock` (`flock`) | Serializa `bus-take`, `bus-give-back`, `calib-commit`, `imu-recalibrate`, `pad-pair` e `pad-forget`. Durante a gravação da calibração ou reinicialização do programa principal, a página Servo não pode tomar o barramento; também só é permitido um pareamento por vez. **`bus-abort` não usa esse lock:** o alívio de torque não pode ser bloqueado por uma devolução em andamento, e suas etapas podem ser repetidas. |
| Lock do ponto de acesso | `/run/microduck-helper/wifi.lock` (`flock`) | Serializa `wifi-hotspot-down` e `wifi-hotspot-up`. É separado de `helper.lock`, usado pelo barramento dos servos, e não há disputa entre eles. |
| robotctl oficial | `/usr/local/bin/robotctl` (caminho fixo em `deploy/microduck-helper`) | Usado somente por `pad-pair` e `pad-forget`. Se não existir, retorna `no_robotctl` (código de saída 5); nenhum outro caminho é pesquisado. |
| Lock de gerenciamento | `/run/microduck-service-management.lock`, mantido pela unidade temporária `microduck-bus-hold` (`flock -n … sleep infinity`) | O `service.sh` da placa não altera o `robotd` se não conseguir obter esse lock. |
| Marcador de transferência | `/run/microduck-handover/handover.json` (diretório 0700, arquivo 0600; arquivo temporário no mesmo diretório, seguido de `fsync` e `rename`) | Somente root pode ler e gravar; o `robotd` o remove depois de lê-lo. |
| Registro de operações | `/var/lib/microduck-helper/oplog.jsonl` (diretório pai 0755, arquivo de registro 0600; subdiretórios privados de backup 0700) | Uma linha por operação: responsável, horário e resultado. O diretório pai permite ao Studio ler o estado público da sessão IMU; somente root pode ler os registros e backups. |
| Backups de calibração | `/var/lib/microduck-helper/calib-backups/<sequência de 4 dígitos>-<UTC>/` (diretórios 0700, arquivos 0600; mantém os 10 mais recentes) | Cada grupo inclui os arquivos `.toml` e `.saved.toml` anteriores à gravação, o drop-in de calibração se existir e `manifest.json` com proprietário, permissões e SHA-256. A sequência é o maior número existente +1, sem depender da ordenação do relógio. A reversão restaura separadamente os arquivos descritos no manifesto. |

**Formato do marcador** (lido pelo `robotd` do fork):

```
{"schema": "microduck-handover/1", "requested_by": str, "boot_id": str, "mono_ms": int,
 "ttl_ms": int, "port": "/dev/ttyS2", "arm_registers": {"limit", "p", "d"} (opcional),
 "joints": [{"id", "torque", "goal", "present", "offset", "load"?, "temp"?, "status"?} × 15]}
```

- `boot_id` e `mono_ms` (milissegundos de `CLOCK_MONOTONIC`) são preenchidos **pelo próprio auxiliar**, mesmo que o Studio envie outros valores.
- **Um `ttl_ms` acima de 30000 é recusado** (código de saída 2), sem truncamento silencioso; valores abaixo de 1000 também são recusados. O padrão é 20000. O `robotd` também aceita no máximo 30 segundos.
- Deve haver exatamente uma entrada para cada ID 10–14, 20–24 e 30–34. `torque` precisa ser 1 (o programa principal só assume o controle quando os 15 servos estão habilitados). `goal`, `present` e `offset` devem ser inteiros no intervalo −32767..32767.

**Tempos limite:**

| Tempo | Valor |
|---|---|
| Intervalo entre as duas leituras da condição | 0,2 s |
| Espera para voltar à postura em pé | 3 s |
| Espera entre `stop` e `KILL` | 10 s |
| Espera adicional após `KILL` | 3 s |
| Prazo para o `robotd` ler o marcador | 15 s |
| Prazo para concluir a etapa 4 da inicialização após assumir o barramento | 20 s |
| Devolução suave | 30 s |
| Interrupção da transferência | aguarda 0,5 s após `KILL` |
| Espera pelo `robotd` após gravar a calibração | 40 s (unidade ativa e `hello` em `/run/robotd.sock`) |
| Espera pelo modo de movimento | 30 s (consulta `busStatus` a cada 0,5 s; o sucesso também exige correspondência de todos os campos lidos de `calibration-status`) |
| Espera do Studio pelo auxiliar | 180 s (mesmo em caso de timeout, consulta `last-result.json` em vez de retornar diretamente `TimeoutExpired`) |

**Variáveis de ambiente:** `MICRODUCK_HELPER_DETACHED`, `MICRODUCK_HELPER_REQUEST` e `MICRODUCK_HELPER_REQUESTED_MS` (usadas por `bus-give-back` e `calib-commit`).

- Finalidade: na primeira chamada de `bus-give-back` ou de `calib-commit` sem `dry_run`, `systemd-run --wait --pipe --collect --quiet --unit=microduck-handover-<horário>-<pid>` inicia uma segunda execução em uma unidade temporária independente. A entrada padrão é encaminhada sem alterações, assim como a saída. Desse modo, se o Studio encerrar, a devolução do barramento ainda termina.
- Essas variáveis **servem somente para impedir uma segunda transferência**, associar solicitações de cancelamento aos resultados e correlacionar resultados. **Não concedem permissões.** O `sudo` usa `env_reset` por padrão, e o processo chamador também não pode repassá-las.
- **Nenhuma variável de ambiente pode alterar o diretório raiz:** os testes carregam o módulo e substituem o contexto por um contexto simulado; não usam variáveis de ambiente.

**Sempre que for necessário determinar se o `robotd` iniciou**, consulte `systemctl show robotd -p ActiveState,SubState,Result,ConditionResult`. Enquanto o marcador existir, `systemctl start robotd` pode retornar 0 mesmo com a unidade em `inactive` e `ConditionResult=no`; isso não significa que o serviço iniciou. Execute `reset-failed` antes de iniciar o `robotd`, para não esbarrar em `start-limit-hit`.

**Limite de confiança:** um usuário autorizado a executar o auxiliar com `sudo` (atualmente, `radxa`) já poderia abrir `/dev/ttyS2` diretamente. Além disso, o `robotd` confere o marcador por meio de leituras de retorno no barramento. Portanto, falsificar um marcador não concede permissões adicionais; no pior caso, mantém os servos na posição em que já estavam.

## 3. Instalação (uma vez, por SSH)

```sh
# No computador: copie o diretório deploy para o robô
scp -r deploy radxa@<robô>:/tmp/studio-deploy
# No robô
cd /tmp/studio-deploy && sudo sh install.sh radxa
```

`install.sh` executa quatro etapas:

1. Instala o auxiliar em `/usr/local/sbin` (modo 0755). Emite um aviso se `/usr`, `/usr/local` ou `/usr/local/sbin` não pertencer ao root ou puder ser gravado pelo grupo ou por outros usuários.
2. Instala o drop-in e executa `systemctl daemon-reload`. **Não reinicia o `robotd`.**
3. Gera a regra do `sudoers` e só a instala (modo 0440) se `visudo -cf` aprovar o arquivo.
4. Exibe as informações para conferência.

**A etapa 1 instala somente a seção `[Unit]` do drop-in.** A linha `[Service] Environment=MICRODUCK_HANDOVER_MARKER=…` fica comentada. Depois de instalar o `robotd` do fork e validar a etapa 3 (devolução do Studio sem aliviar o torque), descomente manualmente as duas linhas e execute `daemon-reload`. O `robotd` só começará a procurar o marcador de transferência na inicialização seguinte; sem marcador, o comportamento permanece igual ao da versão V167. Versões antigas do `robotd` não reconhecem essa variável, então descomentá-la não produz efeito nelas.

Depois da instalação, confira o resultado na placa:

```sh
systemctl show robotd -p DropInPaths            # deve incluir zzzz-studio-bus.conf
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope; echo $?   # como radxa: deve retornar 2
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-take;  echo $?  # deve retornar 2: falta by; nada foi alterado
echo '{}' | sudo -n /usr/local/sbin/microduck-helper pad-pair;  echo $?  # deve retornar 2: falta by; robotctl não foi executado
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-down; echo $?  # deve retornar 2: falta by; nmcli não foi chamado
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-up;   echo $?  # deve retornar 2: falta by; nmcli não foi chamado
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-read;       echo $?  # deve retornar 0: leitura do arquivo e modo, sem lock ou gravação
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-commit;   echo $?  # deve retornar 2: falta by; calibração não foi lida nem gravada
ls -l /usr/local/bin/robotctl                                        # versão oficial 0.15.1 ou posterior
stat -c '%U:%G %a %n' /usr /usr/local /usr/local/sbin /usr/local/sbin/microduck-helper
sudo -l -U radxa | grep microduck-helper
```

## 4. Desinstalação

```sh
sudo sh uninstall.sh            # recusa se o marcador estiver ativo (Studio usando o barramento)
sudo sh uninstall.sh --purge    # também remove /var/lib/microduck-helper
```

A desinstalação remove a regra do sudoers, o drop-in (e executa `daemon-reload`), o auxiliar, para `microduck-bus-hold` e limpa `/run/microduck-helper` e `/run/microduck-handover`. O `robotd` não é reiniciado.

## 5. Diagnóstico de problemas

- `sudo ls -l /run/microduck-helper/`: se `bus-held` estiver presente, o Studio está impedindo intencionalmente a inicialização do programa principal. Para liberar, devolva o barramento pelo Studio ou reinicie o robô.
- `cat /run/microduck-helper/last-result.json`: mostra a última operação e a etapa em que parou; `steps` contém as últimas 30 linhas de progresso.
- `journalctl -t microduck-helper -b`: exibe todas as linhas de progresso da inicialização atual.
- `systemctl status microduck-bus-hold`: verifica se o Studio está mantendo o lock de gerenciamento.
- `sudo tail /var/lib/microduck-helper/oplog.jsonl`: mostra o registro de operações.

## 6. Lista de verificação no robô (segundo robô, com o usuário segurando; executar as etapas em sequência após o início, sem pedir confirmação a cada uma)

**Primeiro, faça verificações somente leitura** (sem alterar nada):

- `systemctl --version`（257）、`sudo -V | grep -i -E 'env_reset|secure_path'`、`ls -l /etc/sudoers.d`。
- **Comportamentos do `systemd-run`:**
  - `systemd-run --wait --pipe --collect --quiet -p … /bin/sh -c 'exit 6'; echo $?`: se `--wait` retorna o código de saída do serviço. O auxiliar não depende disso: primeiro compara o `request_id` em `last-result`; só usa o código de saída do `systemd-run` se não corresponder.
  - Com `--pipe`, se o processo chamador for encerrado, o processo dentro do serviço recebe EPIPE ao escrever em stdout (o auxiliar ignora SIGPIPE), em vez de ser encerrado junto.
  - A unidade temporária usa `KillMode=control-group` por padrão; portanto, `systemctl stop microduck-bus-hold` também para `flock` e `sleep` e libera o lock. Confira com `flock -n /run/microduck-service-management.lock true; echo $?`.

**Etapa 1: testes no robô relacionados ao auxiliar:**

| ID | Ação | Resultado esperado |
|---|---|---|
| U1 | Executar `bus-take` com torque aliviado | Código de saída 0; marcador presente; `robotd` inativo; Studio abre a serial, lê 0 nos 40 registradores e confirma que as posições não mudaram. |
| U2 | Executar `bus-take` mantendo a postura em pé (depois de `init`) | Código 0; Studio lê 1 nos 40 registradores; diferença de posição <1°; o robô não cede. |
| U3 | Executar `bus-take` com a política ativa (Start no controle para manter) | Código 3 e motivo orientando a pressionar Start primeiro; `padd` continua ativo e o `robotd` não é parado. Depois de pressionar Start por 2 s e retornar à postura em pé, `bus-take` deve retornar 0, sem devolução suave. |
| U4 | Executar `sudo systemctl start robotd` com o marcador ativo | Código 0, mas `systemctl show robotd -p ActiveState,ConditionResult` informa `inactive / no`. O `service.sh status` da placa (use o caminho existente nela) deve ser recusado pelo lock com a mensagem de que já há uma operação de gerenciamento de serviços em andamento. |
| U4b | Verificar reinício automático após `KILL` com o marcador ativo | **Não faça isso com o `robotd` enquanto o usuário estiver usando o barramento.** Primeiro teste com uma unidade simulada que use a mesma condição: inicie, crie o marcador e execute `systemctl kill -s KILL`; confira se ela volta a iniciar após 2 s. Repita no `robotd` somente quando o usuário liberar o robô. |
| U4c | Executar `systemctl start robotd` seis vezes seguidas com o marcador ativo | Confira se `Result` muda para `start-limit-hit`. Depois remova o marcador (`bus-give-back {"soft":true}` executa `reset-failed` primeiro) e confirme que o serviço inicia. |
| U5 | Executar `systemctl restart studio-trial` durante uma sessão | O robô não cede; o marcador e `microduck-bus-hold` permanecem. Depois que o Studio reinicia, `bus-take` retorna 0 e `detail` contém `session_was_open=true`. |
| U6 | Fazer a devolução suave | Segure o robô; `bus-give-back {"soft":true}` retorna 0; as quatro etapas do `robotd` têm sucesso; `padd` volta a funcionar e `microduck-bus-hold` é parado. |
| U7 | Sair da página Servo | Se algum servo ainda estiver mantendo torque, o barramento não deve ser devolvido; valide também esse comportamento da página. |
| V0 (parte do auxiliar) | Medir a duração de `bus-take` e `bus-abort` | Consulte `ms` em `last-result`; a meta de `abort` é ≤1 s. |
| U8 | Parear um controle pelo Studio (Thunderobot G50 Pro, modo Switch Pro, nome `Pro Controller`) | O assistente informa que o pareamento foi feito pelo auxiliar. `cat /run/microduck-helper/last-result.json` mostra `verb=pad-pair`, `result=paired` e `detail.stderr` inclui `paused btd …`. Em até 30 s, `padd` reconhece o controle e abre o teste de botões. Se o auxiliar estiver desatualizado, o assistente pede que seja reinstalado. |
| U9 | Com o ponto de acesso ativo, executar `wifi-hotspot-down {"by":"verificação","ssid":"Home"}` | Código 0 e `result=hotspot_down`; antes de desligar, existe `/run/microduck/studio-connecting.json` (`root`, modo 0644, `until` cerca de 90 s no futuro e `ssid=Home`); `nmcli connection show --active` não lista `Microduck-Hotspot` e o celular perde a conexão. Repita com o ponto já desligado: código 0, `already_down`, sem criar a janela de conexão. |
| U10 | Com o ponto de acesso desligado, executar `wifi-hotspot-up {"by":"verificação"}` | Código 0 e `result=hotspot_up`; `nmcli connection show --active` lista `Microduck-Hotspot` em `wlan0`; o celular encontra o ponto de acesso; `studio-connecting.json` foi removido. Repita: código 0, `already_up`; a ausência do arquivo não gera erro. |
| U11 | Fazer primeiro uma prévia: `calib-commit {…, "dry_run": true}`, usando os mesmos dados `joints` e `imu` pré-visualizados no Studio | Código 0 e `result=preview`; `detail.toml` contém os 15 itens com `calibrated = true`, `motion_enabled = true`, limites e quaternion; `detail.mode` é `commissioning` (fábrica) ou `motion`. O SHA-256 e a data de modificação de `hd1910-calibration.toml` permanecem iguais; o `robotd` não reinicia. |
| U12 | Gravar de verdade (segure o robô), repetindo com `dry_run: false` | Código 0 e `result=committed`; `detail.mode_before=commissioning`, `detail.bus_status.mode=motion`, `phase=control`, `readback_ok=true` e `mismatches=[]`. `zzzz-zz-microduck-commissioning.conf` foi removido e `daemon-reload` executado; `.saved.toml` corresponde ao arquivo principal e `.previous.toml` contém a versão anterior. Foi criado um backup em `calib-backups/` com os três arquivos no manifesto. `systemctl show robotd -p ActiveState` mostra `active`; a etapa 3 da lista do Studio fica concluída e a barra superior mostra o modo de movimento. |
| U12b | Testar reversão após rejeição da calibração: marque como não verificada a IMU em uso (ou escolha uma origem incompatível) e repita U12 | Código 5, `result=calib_rejected`; `reason` informa que a validação do programa principal foi recusada (por exemplo, exige todas as 15 juntas calibradas); `detail.bus_status` mostra `mode=motion` e `phase=waiting_for_bus`; `detail.files_restored`, `mode_restored`, `robotd_up_after_rollback` e `detail.rolled_back` são `true`. O arquivo principal e `.saved.toml` voltam ao estado anterior a U12, o arquivo de calibração é restaurado e o `robotd` reinicia novamente no modo de calibração. |
| U12c | Testar reversão sem alimentação dos servos: desligue-a e repita U12 | Código 5, `result=bus_unavailable`; `reason` informa que o programa principal não conseguiu abrir o barramento e pergunta se os servos estão alimentados; `detail.bus_status.phase=waiting_for_bus`; arquivos e modo são restaurados. |
| U12d | Testar reversão com leitura divergente: altere temporariamente `zero_raw` em `calibration-status` do programa falso ou stub e repita U12 | Código 5, `result=readback_mismatch`, `detail.readback_ok=false`; `detail.mismatches` identifica o campo divergente; arquivos e modo são restaurados. |
| U13 | Testar reversão após falha de reinicialização: impeça temporariamente o início do `robotd` criando `robotd.service.d/zzzz-e2e-fail.conf` com `[Unit]` e `ConditionPathExists=/nonexistent-e2e`; execute `daemon-reload` e repita U12 | Código 5, `result=restart_failed`, `detail.files_restored=true` e `detail.robotd_up_after_rollback=false` (só será `true` depois de receber o `hello`). O arquivo principal e `.saved.toml` voltam ao estado anterior a U12; `detail.journal` contém as últimas 30 linhas do `robotd`, e `reason` orienta exportar um pacote de diagnóstico pela página de registros. Depois, remova o drop-in, execute `daemon-reload` e `systemctl start robotd`. |

**Ainda não coberto:** a devolução com marcador (`{"marker": …}`) só pode ser testada na placa depois de instalar o `robotd` do fork e ativar `Environment` no drop-in. Esses testes são V1–V12 da etapa 4.

## 7. Limitações conhecidas

- Entre a verificação do estado e a criação do marcador/parada do `robotd` em `bus-take`, há uma janela de aproximadamente 0,1 s durante a qual um app Bluetooth ainda pode ativar a política. `padd` e `gamesir` já foram parados; `btd` não é parado.
- Não é possível impedir `system.reboot` do `configd` nem um `poweroff` executado diretamente por SSH (plano, seção 2.5). Após reiniciar, o `robotd` alivia o torque de todos os servos como de costume.
- Durante a contagem da transferência, Select no controle não funciona (`padd` aguarda o sucesso das quatro etapas de inicialização do `robotd`). Nesse intervalo, use o botão web de alívio, que executa `bus-abort`, ou desligue a alimentação.
- Uma versão antiga do auxiliar que não reconheça `pad-pair` retorna `bad_verb`. O Studio a trata como se não houvesse auxiliar atualizado e usa a alternativa `configd` → `bluetoothctl`. Essa alternativa pode falhar na placa `/var/lib/robot/weird-ble`; o assistente orienta reinstalar o auxiliar ou executar `sudo robotctl pad pair` no robô.
- O auxiliar 0.2.0, que não reconhece `wifi-hotspot-down` nem `wifi-hotspot-up`, também retorna `bad_verb`; durante a configuração da rede, o Studio informa que o auxiliar está desatualizado e orienta reinstalar `deploy/install.sh`.
