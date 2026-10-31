# Auxiliar de root do Studio: transferência do barramento dos servos, gravação da calibração e pareamento do controle (instalação, remoção e verificação no robô)

Este documento explica cada etapa e sua finalidade para usuários e para quem for dar continuidade ao trabalho.

## Refazer a calibração inicial da IMU (`imu-recalibrate`)

Na versão 0.7.2, o verbo fixo `enter` aceita o parâmetro opcional `profile="legacy"|"qinmo"`, que a página IMU seleciona uma vez e salva. O parâmetro não aceita comandos, caminhos nem serviços. O recurso exige evidência explícita da capacidade `configured_imu_profile` na nova versão do `robotd`; a compatibilidade não é decidida apenas pelo número da versão da API. Qinmo é identificada como configuração e oferece suporte a Feetech; a velocidade angular é `raw/16.4 °/s`. As placas existentes continuam com detecção automática por padrão e usam `raw×0.0175 °/s`. Consulte o [guia de uso da página Web](../../../docs/Qinmo-IMU-网页使用.md) para o procedimento do usuário.

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

| 动词 | stdin（一个 JSON 对象） | 做什么 |
|---|---|---|
| `bus-take` | `{"by": "谁·哪台电脑", "allow_seated": false}` | 接管，**不卸力**：先停手柄服务 → 隔 200 ms 读两次主程序状态（策略在跑就拒绝；坐姿只有 `allow_seated` 并且不动才放行；正在回站姿最多等 3 秒）→ 立旗 → `systemctl stop --no-block robotd`，10 秒没停就 KILL → 确认串口没人占 |
| `bus-give-back` | `{"by": …, "soft": true}` | 软交还：Studio 已经在总线上全卸了。撤旗 → 起 robotd → 等启动 4 步都 success、而且主程序起来了（运动模式 `phase=control`，或者标定模式的实时快照 `ready` / `moving` / `read_error` / `stop_unconfirmed` / `power_pending`；`read_error` 照样算成，原话写进 reason）→ 拉回手柄服务 → 放锁。30 秒还一直报启动阶段：`soft_failed`、`detail.still_starting = true` |
| | `{"by": …, "marker": {…}}` | 不卸力交还：写交接标记 → 撤旗（**锁不放**）→ 起 robotd → 等 robotd 接手（接手保持、不开模型）。没接手就把总线拿回来，交给 Studio 接着保持。标定模式不认标记（开总线先全部卸力）：实时快照一来就回 `limp`，不等 15 秒再拿回总线 |
| `bus-abort` | `{"by": …}` | 中止交接（交接倒数期间按了网页卸力）：立旗 → KILL robotd → 删标记 → 确认串口空出来。目标 1 秒以内，之后 Studio 自己开串口卸力。**没有会话时拒绝（退出 3）**：旗、管理锁、交接标记都不在就什么都不碰 |
| `pad-pair` | `{"by": …, "mac": 可选, "timeout": 10–120（默认 60）}` | 以 root 跑官方 `/usr/local/bin/robotctl pad pair --json --timeout N [MAC]`。MAC 先转大写再校验。子进程总超时 = `timeout + 30` 秒（超时就杀掉）。robotctl 在 `/var/lib/robot/weird-ble` 板上会先停 btd、给适配器断电再开，最后把 btd 起回来。**不碰**总线旗子、hold 单元、robotd，也不拿服务管理锁；只拿 `helper.lock`，一次只跑一个配对 |
| `pad-forget` | `{"by": …, "mac": …}` | 以 root 跑官方 `/usr/local/bin/robotctl pad forget MAC`（MAC 必填，校验同上）。同样不碰总线、hold 单元、robotd |
| `wifi-hotspot-down` | `{"by": …, "ssid": 可选}` | 关热点**之前**写 `/run/microduck/studio-connecting.json`（root 0644，`until` = 现在 + 90 秒，带目标 SSID；先写临时文件再 rename，目录 0755），netcheck 在这段时间里不插手。然后 `nmcli connection down Microduck-Hotspot`（命令超时 15 秒）。热点本来就没开算成功（nmcli 说「不是活动连接」也当成功）；最多等 10 秒，等 wlan0 不再是这个连接。**不碰**总线旗子、hold 单元、robotd，也不拿 `helper.lock`，用 `wifi.lock` |
| `wifi-hotspot-up` | `{"by": …}` | `nmcli connection up Microduck-Hotspot`。本来就开着算成功；从 up 开始最多等 30 秒，等 wlan0 真的挂上这个连接。开起来以后删掉 `/run/microduck/studio-connecting.json`（文件本来不在不算错）。同样不碰舵机总线，用 `wifi.lock` |
| `calib-read` | `{"by": …}`（可省） | 只读当前标定文件：回解析后的 `calibration`、现在是哪种模式（`commissioning` / `motion` / `foreign`）、commissioning drop-in 在不在、`ExecStart` 里有没有 `--commissioning`。**不拿 `helper.lock`、不写任何文件**，给 Studio 在运动模式卡 `waiting_for_bus`、读不到 `calibration-status` 时兜底。 |
| `calib-commit` | `{"by": …, "joints": [{"id", "direction"} × 15], "imu": {"source": "bus\|bno08x\|lsm6dsv16x", "quat": [w,x,y,z]}, "dry_run": false}` | 把舵机零位（2048）、方向、IMU 安装方向写进 robotd 的 `hd1910-calibration.toml`。顺序：**先拿 `helper.lock`，再查 bus-held 旗**；标定模式跳过着势门槛，运动模式隔 200 ms 读两次 busStatus（策略在跑 / 站着就拒绝，退出 3）；认模式：镜像的 `zzzz-zz-microduck-commissioning.conf` 在 = 标定模式（写完删掉、`daemon-reload` 切运动模式），不在且 `ExecStart` 没有 `--commissioning` = 运动模式（只换标定），`ExecStart` 有但文件不在 = `foreign_commissioning`（不敢自动切，退出 3）。读现在的文件、按标准限位组新内容、逐条校验（跟 fork 的 `Calibration::validate` 一样）。每次写一组 `calib-backups/<4 位序号>-<UTC>/`（主文件、`.saved.toml`、commissioning 文件、`manifest.json`，序号取已有最大值 +1，保留 10 组）；`.previous`、`.toml`、`.saved.toml` 都先写临时文件、fsync、rename，保留原属主和权限；写完读回来逐项校验。从第一次写开始，任何异常都先回滚再报错。重启 robotd 后最多等 40 秒 hello；再每 0.5 秒读一次 `robot.busStatus`、最多 30 秒：**成功 = `mode=="motion"` 且 `phase=="control"`，并且 `calibration-status` 读回的 15 颗（name / id / zero_raw / direction / calibrated / min_rad / max_rad）、`motion_enabled`、总线小板 `imu_mount_quat` / `imu_mount_verified`、`imu_mounts` 每一格的 quat / verified 跟写进去的一致（浮点 1e-9）**。失败按原因回 `calib_rejected`（标定没通过主程序的检查）或 `bus_unavailable`（主程序打不开舵机总线，先看舵机电源），并回滚。非 dry_run 的整段用 `systemd-run` 跑在独立单元里，结果写 `last-result.json`；`dry_run: true` 到校验完就停，只在 `detail.toml` 回全文，不写文件、不重启。 |
| `ssh-status` | `{"by": …}`（可省） | 只读：SSH 密码登录开没开（看 `05-microduck-ssh-password.conf` 在不在）、`ssh` 服务在不在跑、radxa 的 `authorized_keys` 登记了几把钥匙。不拿锁、不写任何文件（也不覆盖 `last-result.json`）。 |
| `ssh-password` | `{"by": …, "on": true, "password": "…"}` / `{"by": …, "on": false}` | 打开：密码 8–64 个可见字符、不能是 `microduck` 这类大家都猜得到的（不合格回 `bad_password`，退出 2）；拿 `ssh.lock`，`chpasswd` 从 stdin 设 radxa 的密码，写 `/etc/ssh/sshd_config.d/05-microduck-ssh-password.conf`（`PasswordAuthentication yes`），`sshd -t` 过了、`sshd -T` 读回 `passwordauthentication yes` 才 `systemctl reload-or-restart ssh`；哪一步不对就删掉这个文件退回去（`sshd_config_bad` / `not_effective` / `reload_failed`）。关掉：删文件、reload，radxa 的密码不动（sudo 还用它）。**密码只在 stdin 里，不进命令行、journal、`last-result.json`、oplog。** |

**输出**：一行一个 JSON：`{"step", "level", "ms", "msg", "detail"}`，最后一行 `step="done"`，`detail` 里有 `exit` 和 `result`。同一份结果写进 `/run/microduck-helper/last-result.json`（0644），Studio 重启以后读它。

`pad-pair` 的 `detail` 还有：`pair`（robotctl 的 stdout，按 `PadPairResult` 解析：`{"outcome":"paired","pad":{…}}` 或 `{"outcome":"failed","reason":"not_found|ambiguous|timeout|no_adapter|rejected|other","detail":…}`）、`stderr`（robotctl 的几行提示，如 `paused btd …`、`warning: …`）和 `stdout`。配上了退出 0；robotctl 说失败退出 5，`detail.reason` 保留官方原因。`pad-forget` 的 `detail` 有 `removed`（true / false / null）、`stdout`、`stderr`。

**退出码**

| 码 | 意思 |
|---|---|
| 0 | Sucesso |
| 2 | Parâmetros错（动词不认识、stdin 不是 JSON 对象、有不认识 de 键、标记校验没过） |
| 3 | 状态不允许（没装保护、策略在跑、鸭子站着 / 在走、没有会话、不是 root；`calib-commit` 还可能是 bus-held、`foreign_commissioning`） |
| 4 | 忙或 em 止（管理锁被板端脚本占着、小助手正在跑别 de 总线操作 / 另一个配对或忘掉、另一个 WiFi Ponto de acesso操作、交还被 em 止） |
| 5 | 执行失败（停不下来、串口被占、robotd 没认标记已经全卸、软交还起不来；或者 `pad-pair` / `pad-forget` 找不到 robotctl、robotctl 说配对失败、超时被杀；热点关 / 开没成、nmcli 出错、等超时；`calib-commit` 写失败 / 重启失败 / 主程序没进运动模式 / 读回不一致，已经回滚） |
| 6 | 交接没成，总线已拿回（旗重新立好、robotd 停了、锁还在），Studio 重开串口接着保持 |

`result` 的取值：

- bus-take：`taken`、`refused`、`no_guard`、`busy`、`stop_failed`、`port_busy`
- bus-give-back：`adopted`、`retake`、`retake_failed`、`limp`（运动模式没认标记，或者标定模式）、`aborted`、`soft`、`soft_failed`（主程序一直报启动阶段时 `detail.still_starting = true`、`detail.msg` 是整句）、`refused`、`no_session`、`detach_failed`
- bus-abort：`aborted`、`abort_incomplete`、`no_session`（没有会话时拒绝，退出 3）
- pad-pair：`paired`、`pair_failed`（退出 5，`detail.reason` 是官方原因）、`timeout`、`no_robotctl`、`bad_output`
- pad-forget：`forgotten`、`forget_failed`、`timeout`、`no_robotctl`
- wifi-hotspot-down：`hotspot_down`、`already_down`、`down_failed`、`timeout`、`nmcli_failed`
- wifi-hotspot-up：`hotspot_up`、`already_up`、`up_failed`、`timeout`、`nmcli_failed`
- calib-read：`read`。`detail` 有 `calibration`、`mode`（`commissioning` / `motion` / `foreign`）、`commissioning_present`、`exec_has_commissioning`、`mode_text`；不拿锁、不写文件
- calib-commit：`preview`（dry_run）、`committed`（`mode=motion` 且 `phase=control`，并且 `calibration-status` 读回逐项一致）、`not_motion`（30 秒还没进运动模式）、`calib_rejected`（主程序说标定没通过检查）、`bus_unavailable`（主程序打不开舵机总线）、`readback_mismatch`（进了运动模式但读回不一致）、`bus_held`、`no_calibration`、`bad_calibration`、`joint_mismatch`、`invalid`、`bad_toml`、`restart_failed`、`write_failed`、`backup_failed`、`read_failed`、`foreign_commissioning`、`refused`（策略在跑 / 站着）。失败结果里 `detail.rolled_back` / `files_restored` / `mode_restored` / `robotd_up_after_rollback` 分开报；`readback_ok`、`mismatches`、`bus_status`（最后一次的 mode / phase / error）和 `backup` 也在。若回滚自己没完全成功，`msg` 会写「去日志页导出诊断包」
- 都可能有：`bad_args`、`bad_marker`、`bad_verb`、`not_root`、`busy`、`error`

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
 "ttl_ms": int, "port": "/dev/ttyS2", "arm_registers": {"limit", "p", "d"}（可选）,
 "joints": [{"id", "torque", "goal", "present", "offset", "load"?, "temp"?, "status"?} × 15]}
```

- `boot_id` e `mono_ms` (milissegundos de `CLOCK_MONOTONIC`) são preenchidos **pelo próprio auxiliar**, mesmo que o Studio envie outros valores.
- **Um `ttl_ms` acima de 30000 é recusado** (código de saída 2), sem truncamento silencioso; valores abaixo de 1000 também são recusados. O padrão é 20000. O `robotd` também aceita no máximo 30 segundos.
- Deve haver exatamente uma entrada para cada ID 10–14, 20–24 e 30–34. `torque` precisa ser 1 (o programa principal só assume o controle quando os 15 servos estão habilitados). `goal`, `present` e `offset` devem ser inteiros no intervalo −32767..32767.

**Tempos limite:**

| 时间 | 值 |
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
systemctl show robotd -p DropInPaths            # 要有 zzzz-studio-bus.conf
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope; echo $?   # 用 radxa：应该是 2
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-take;  echo $?  # 应该是 2：缺 by（什么都没动）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper pad-pair;  echo $?  # 应该是 2：缺 by（不跑 robotctl）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-down; echo $?  # 应该是 2：缺 by（不碰 nmcli）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper wifi-hotspot-up;   echo $?  # 应该是 2：缺 by（不碰 nmcli）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-read;       echo $?  # 应该是 0：读文件 + 模式（不拿锁、不写）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper calib-commit;   echo $?  # 应该是 2：缺 by（不读写标定）
ls -l /usr/local/bin/robotctl                                        # 官方 0.15.1 或更新
stat -c '%U:%G %a %n' /usr /usr/local /usr/local/sbin /usr/local/sbin/microduck-helper
sudo -l -U radxa | grep microduck-helper
```

## 4. 卸载

```sh
sudo sh uninstall.sh            # 旗在（Studio 正占着总线）时拒绝
sudo sh uninstall.sh --purge    # 连 /var/lib/microduck-helper 一起删
```

卸载会删掉 sudoers 那一行、drop-in（然后 daemon-reload）、小助手，停掉 `microduck-bus-hold`，清掉 `/run/microduck-helper` 和 `/run/microduck-handover`。robotd 不重启。

## 5. 出事时怎么看

- `sudo ls -l /run/microduck-helper/`：`bus-held` 在 = 主程序被 Studio 挡着，起不来是故意的。要放开：在 Studio 里交还，或者重启。
- `cat /run/microduck-helper/last-result.json`：上一次做了什么、卡在哪一步（`steps` 是最后 30 行进度）。
- `journalctl -t microduck-helper -b`：每一行进度都写在这里。
- `systemctl status microduck-bus-hold`：管理锁在不在 Studio 手里。
- `sudo tail /var/lib/microduck-helper/oplog.jsonl`：操作记录。

## 6. Superior机核对清单（二号鸭，Usuário扶着；他说开始就连着跑，不用每次问）

**先只读核对**（不动任何东西）：

- `systemctl --version`（257）、`sudo -V | grep -i -E 'env_reset|secure_path'`、`ls -l /etc/sudoers.d`。
- **systemd-run 那几个行为**：
  - `systemd-run --wait --pipe --collect --quiet -p … /bin/sh -c 'exit 6'; echo $?`：`--wait` 会不会把服务的退出码带回来。小助手不靠这个，先读 last-result 里的 request_id 对号，对不上才用 systemd-run 的退出码；
  - `--pipe` 下把调用方杀掉，服务里面的进程写 stdout 会拿到 EPIPE（小助手忽略 SIGPIPE），而不是被一起杀掉；
  - 临时单元默认 `KillMode=control-group`，所以 `systemctl stop microduck-bus-hold` 会连 flock 和 sleep 一起停掉、锁跟着放掉。用 `flock -n /run/microduck-service-management.lock true; echo $?` 核对。

**第 1 步 de Superior机Teste（跟小助手有关 de ）**：

| 编号 | 做什么 | 看什么 |
|---|---|---|
| U1 | 卸力状态下 `bus-take` | 退出码 0；旗在；robotd inactive；Studio 开串口读 40 全是 0、位置不变 |
| U2 | 站姿保持（init 以后）`bus-take` | 0；Studio 读 40 全是 1，位置差 <1°，鸭子不往下沉 |
| U3 | 策略开着（手柄 Start 进保持）`bus-take` | 3，原因是「先按手柄 Start…」；padd 回来了；robotd 没被停。按 Start 2 秒回站姿以后再 take → 0，不软 |
| U4 | 旗在的时候 `sudo systemctl start robotd` | 退出码 0，但 `systemctl show robotd -p ActiveState,ConditionResult` 是 inactive / no；板上的 `service.sh status`（路径以板上实际为准）被锁拒：「已有服务管理操作正在执行」 |
| U4b | 旗在时 KILL 以后的自动重启 | **不要在用户拿着总线的时候拿 robotd 做。** 先用一个假单元验：建一个带同样 Condition 的临时服务，起来、立旗、`systemctl kill -s KILL`，看 2 秒后它有没有被拉起来。用户空下来以后，再在 robotd 上做一次 |
| U4c | 旗在时连着 `systemctl start robotd` 6 次 | 看 `Result` 会不会变成 start-limit-hit。然后撤旗（`bus-give-back {"soft":true}` 会先 reset-failed）确认能起来 |
| U5 | 会话中 `systemctl restart studio-trial` | 鸭子不软；旗、`microduck-bus-hold` 还在；Studio 起来以后 `bus-take` 返回 0，detail 里 `session_was_open=true` |
| U6 | 软交还 | 扶住；`bus-give-back {"soft":true}` 返回 0；robotd 四步 success；padd 回来；`microduck-bus-hold` 停了 |
| U7 | 离开Servo页 | 有保持就不交还（另一个子代理 de 部分，一起验） |
| V0（小助手部分） | 量 `bus-take` 和 `bus-abort` 各用多久 | 看 last-result 的 `ms`；abort 目标 ≤1 秒 |
| U8 | 在 Studio 里配一次手柄（雷神 G50 Pro，Switch Pro 模式，名字 `Pro Controller`） | 向导里「配对走的是」写小助手；`cat /run/microduck-helper/last-result.json` 的 `verb=pad-pair`、`result=paired`，`detail.stderr` 有 `paused btd …`；30 秒内 padd 认到并进按键测试。没有新版小助手时向导会提示先重装 |
| U9 | 热点开着时 `wifi-hotspot-down {"by":"核对","ssid":"Home"}` | 退出 0、`result=hotspot_down`；关之前已有 `/run/microduck/studio-connecting.json`（root 0644，`until` 约 90 秒后，`ssid=Home`）；`nmcli connection show --active` 里没有 `Microduck-Hotspot`；手机的热点连接断开。热点本来关着再调一次 → 0、`already_down`，且不写连接窗口 |
| U10 | 热点关着时 `wifi-hotspot-up {"by":"核对"}` | 退出 0、`result=hotspot_up`；`nmcli connection show --active` 里有 `Microduck-Hotspot`（wlan0）；手机能搜到热点；`studio-connecting.json` 已删掉。再调一次 → 0、`already_up`，文件不在也不报错 |
| U11 | 先只预览：`calib-commit {…, "dry_run": true}`（joints / imu 用 Studio 预览的同一份） | 退出 0、`result=preview`；`detail.toml` 里 15 颗 `calibrated = true`、`motion_enabled = true`、限位和四元数在；`detail.mode` 是 `commissioning`（出厂）或 `motion`；`hd1910-calibration.toml` 的 sha256 和 mtime 都没变，robotd 没重启 |
| U12 | 真写（扶好鸭子）：同上 `dry_run: false` | 退出 0、`result=committed`；`detail.mode_before=commissioning`、`detail.bus_status.mode=motion`、`phase=control`、`readback_ok=true`、`mismatches=[]`；`zzzz-zz-microduck-commissioning.conf` 没了、`daemon-reload` 跑过；`.saved.toml` 跟主文件一样、`.previous.toml` 是写之前的；`calib-backups/` 多一组（manifest 里三份都在）；`systemctl show robotd -p ActiveState` 是 active；Studio 清单第 3 步变完成、顶栏显示运动模式 |
| U12b | 回滚（标定被拒）：把正在用的 IMU 改成没 verified（或来源对不上），再跑一次 U12 | 退出 5、`result=calib_rejected`；`reason` 是「标定没通过主程序的检查：motion requires all 15 calibrated joints…」；`detail.bus_status` 是 `mode=motion`、`phase=waiting_for_bus`；`detail.files_restored` / `mode_restored` / `robotd_up_after_rollback` 都是 true，`detail.rolled_back` 也是 true；主文件、`.saved.toml` 跟 U12 之前一样，commissioning 文件放回去了，robotd 又起了一次（回到标定模式） |
| U12c | 回滚（舵机没上电）：关舵机电源，再跑一次 U12 | 退出 5、`result=bus_unavailable`；`reason` 是「主程序打不开舵机总线：torque readback…。舵机电源开了吗？」；`detail.bus_status.phase=waiting_for_bus`；文件和模式都换回 |
| U12d | 回滚（读回不一致）：临时把假主程序 / 测试桩的 calibration-status 改一颗 `zero_raw`，再跑一次 U12 | 退出 5、`result=readback_mismatch`、`detail.readback_ok=false`、`detail.mismatches` 里写明哪一项；文件和模式都换回 |
| U13 | 回滚：临时让 robotd 起不来（建一个 `robotd.service.d/zzzz-e2e-fail.conf`，写 `[Unit]` + `ConditionPathExists=/nonexistent-e2e`，`daemon-reload`），再跑一次 U12 | 退出 5、`result=restart_failed`、`detail.files_restored=true`、`detail.robotd_up_after_rollback=false`（真的等到 hello 才算 true）；主文件和 `.saved.toml` 跟 U12 之前一样；`detail.journal` 有 robotd 最后 30 行；`reason` 带「去日志页导出诊断包」。核对完删掉那个 drop-in、`daemon-reload`、`systemctl start robotd` |

**还没覆盖到的**：标记交还（`{"marker": …}`）要等 fork 的 robotd 装上、drop-in 打开 Environment 以后才能在板上测，那是第 4 步的 V1–V12。

## 7. 已知 de 限制

- bus-take 在「判完状态」到「立旗、停 robotd」之间，有大约 0.1 秒 de 窗口，这期间蓝牙 App 还能把策略打开。padd、gamesir 已经先停了，btd 没停。
- configd 的 `system.reboot`、SSH 里直接 `poweroff` 拦不住（方案 §2.5）。重启的话，robotd 起来时照老规矩全卸。
- 交接倒数期间手柄 Select 不起作用（padd 要等 robotd 四步都 success 才Inicialização）；那几秒用Web卸力（走 bus-abort）或关Alimentação。
- 旧版小助手（不认 `pad-pair`）会回 `bad_verb`；Studio 把它当没有新版小助手，退回 configd → bluetoothctl。这块板（`/var/lib/robot/weird-ble`）上后备路可能配不上，向导会提示重装小助手或在鸭子上运行 `sudo robotctl pad pair`。
- 旧版小助手（0.2.0，不认 `wifi-hotspot-down` / `wifi-hotspot-up`）也回 `bad_verb`；Studio 配网时会提示「小助手太旧，重装 deploy/install.sh」。
