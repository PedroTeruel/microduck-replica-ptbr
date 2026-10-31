# Microduck Studio

Painel de controle web instalado no robô. Abra `http://<IP do robô>:8000/` no navegador do computador ou celular para ver o estado atual, aliviar o torque com um toque, colocar o robô em pé ou fazê-lo andar, parear um controle Bluetooth (usando o comando oficial `robotctl pad pair`), calibrar os servos e a orientação da IMU, gravar esses dados no programa principal e seguir a lista de primeiros passos. Enquanto o robô estiver com o ponto de acesso ativo aguardando a configuração da rede, também é possível escolher o Wi-Fi da casa e informar a senha pelo celular.

## O que o Studio faz e o que não faz

- A comunicação normal com o programa principal `robotd` usa `/run/robotd.sock` (protocolo v40). Para controlar os servos diretamente na página correspondente, o `robotd` precisa liberar o barramento; ao terminar, o Studio o devolve.
- Todo estado exibido pela página vem de uma leitura de retorno do `robotd`. Por exemplo, “torque aliviado ✓” só aparece depois que `busStatus` confirma que o torque está desligado; clicar no botão não basta.
- Encerrar o Studio não afeta o robô. Encerrar o `robotd` **não** alivia o torque: os servos mantêm o último comando, e a página informa essa condição.
- **Encerrar o Studio não alivia o torque.** Se o Studio for encerrado, reiniciado ou atualizado enquanto a sessão do barramento estiver aberta, ele fecha apenas a porta serial; os servos continuam mantendo o torque. Ao abrir o barramento, o Studio grava `servo-session.json` no diretório de estado, com a porta serial, o horário de início e quem abriu a sessão. O arquivo só é removido depois que “Devolver ao programa principal” termina com sucesso. Se o Studio iniciar e encontrar esse arquivo, mas o `robotd` não estiver ativo, ele retoma o barramento em modo somente leitura, sem alterar o torque, e mantém o aviso no topo das páginas. O aviso explica que ainda pode haver servos mantendo torque da sessão anterior e orienta a retomar o controle na página Servo antes de aliviar o torque; o botão de alívio também leva a essa página. Se o `robotd` já estiver ativo, ele já terá liberado todos os servos, então o marcador é removido.
- Durante uma sessão com os servos, o Studio verifica a cada 5 segundos o socket do `robotd`. Se alguém iniciar o serviço manualmente, ele libera os servos e disputa a porta serial; o Studio registra o conflito, fecha o barramento sem enviar comandos aos servos e exibe um aviso vermelho. Para devolver o controle ao programa principal, use “Devolver ao programa principal”; não execute `systemctl start robotd` manualmente.

## Diretório

```
run.py              Inicialização (`python3 -I run.py …`): adiciona `deps/` ao caminho de busca e inicia o Studio
run_tests.py        Executa todos os testes
studio/
  log.py            Registros: categorias, níveis, horário em milissegundos, deduplicação, ocultação de dados sensíveis e rotação diária; comandos registram envio, resposta e duração
  auth.py           Senha de administrador (scrypt), sessão de login, espera progressiva após falhas e validação de Host/Origin
  rpc.py            Conexão JSON-RPC com `robotd` e `configd` (uma solicitação por conexão)
  robotd.py         Conexões persistentes separadas para consulta periódica, fluxo de estado, comandos e `configd`; o alívio de torque abre uma conexão nova para evitar conexões obsoletas após reiniciar o `robotd`
  estop.py          Máquina de estados do alívio de torque: `ready` → `pending` → `confirmed` / `unavailable`; aceita apenas leituras solicitadas depois da resposta ao comando de alívio
  state.py          Converte dados brutos no estado enviado à página: postura, bateria, servos, IMU, controle, tarefas pendentes e rede
  models.py         Biblioteca de modelos, restauração do padrão, confirmação da troca efetiva e remapeamento dos botões do controle
  model_package.py  Leitura de pacotes de implantação de modelos e verificação prévia do `robotd` sem hardware
  sensors.py        Configuração da origem da câmera e snapshots sob demanda do ToF, independentes do controle de movimento
  net.py            Configuração de rede: lê o `net.json` do netcheck e usa `net.status`, `scan`, `connect` e `forget` do configd para gerenciar redes e o ponto de acesso
  app.py            Servidor web: arquivos estáticos, login, registros, pacote de diagnóstico e WebSocket
web/                Interface (Preact + htm; renderiza o robô 3D com three.js; arquivos locais, sem CDN; `wifi.js` implementa o cartão e as configurações de Wi-Fi;
                    `probe.svg` é usado para localizar o novo endereço do robô depois da conexão ao Wi-Fi)
deps/               Dependências Python com versões fixas (starlette, uvicorn etc.; consulte `deps/VERSIONS.txt`)
dev/
  record_robotd.py  Grava somente leitura respostas reais do `robotd` no robô, para uso com o `fake_robotd` e nos testes
  fake_robotd.py    Simula `robotd` e `configd`, reproduzindo os dados gravados para executar no computador sem o robô
tests/              Testes unitários e dados gravados no robô em `fixtures/now-20261018.jsonl`
```

## Executar no computador (sem conectar o robô)

É necessário ter Python 3.13, a mesma versão usada na placa. No Windows, use `py -3.13`.

```bash
py -3.13 -I dev/fake_robotd.py --fixture tests/fixtures/now-20261018.jsonl \
    --net-mode hotspot --net-state-file ./state-dev/net.json   # robotd e ponto de acesso simulados; escuta nas portas 17001/17002
py -3.13 -I run.py --listen 127.0.0.1:18080 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002 \
    --net-state ./state-dev/net.json --dev-autologin --state-dir ./state-dev --log-dir ./logs-dev
```

Abra `http://127.0.0.1:18080/` no navegador. `--dev-autologin` aceita apenas solicitações locais e só pode ser usado com `127.0.0.1`; serve para testes de captura de tela e não deve ser ativado no robô.
No `fake_robotd`, `--mode commissioning|motion` seleciona o modo do programa principal (para simular a configuração de fábrica, use `--mode commissioning --calib factory`), e `--posture limp|policy|commissioning|starting` altera a postura. `--net-mode hotspot|wifi|none` grava um `net.json` simulado.
O modo de calibração simula o comportamento real do fork: primeiro retorna o relatório de inicialização (`phase=configuring_bus`) e, após a primeira leitura bem-sucedida, passa a retornar snapshots de estado em tempo real. `--commissioning-stuck-status` simula versões antigas do fork, que nunca limpam o relatório e deixam o Studio indicar “iniciando” continuamente.
Sem `--net-state`, o programa lê `/run/microduck/net.json`; se o arquivo não existir (por exemplo, no computador ou em uma imagem antiga), a seção Wi-Fi não será exibida. Sem `--duck-label`, a interface usa o nome do host (no robô, `duck-xxxx`).

O Python no Windows não oferece sockets Unix; por isso, informe o endereço como `tcp:host:porta`. No robô, o padrão é `unix:/run/robotd.sock`.

## Câmera e ToF

Depois de “Controle”, na barra lateral esquerda, há páginas independentes para “Câmera” e “ToF”; no celular, elas também aparecem na barra inferior.

As páginas Visão geral e Controle mostram, nesta ordem, os estados da bateria, dos servos, da IMU, da câmera, do ToF, do controle e da placa principal. Para a câmera, o Studio verifica se o serviço está ativo por meio de uma mensagem `hello` somente leitura no socket local do `mediad`; um arquivo de configuração ou uma imagem de teste não confirma a conexão de uma câmera real. Abra a página da câmera para ver o vídeo. O ToF é considerado ativo quando chega um novo quadro; dados `fake`/`sim` são identificados como simulados. A barra verifica os serviços a cada 10 segundos e cancela a verificação ao trocar de página ou enviar o app para segundo plano. Estados vencidos são limpos. Essa verificação não solicita quadros, não estabelece WebRTC e não inicia serviços do sistema.

As imagens atuais ainda não têm uma política unificada que detecte câmera e ToF na inicialização e ative ou desative os serviços conforme o resultado. A detecção automática do `firstboot` é voltada à IMU. A imagem usa `media.source="test"` por padrão para evitar falhas repetidas quando não há câmera, mas o serviço de mídia ainda pode estar ativo. Uma falha de conexão na página pode indicar um problema de rede ou de serviço; ela não confirma a ausência do hardware e não deve levar ao desligamento do serviço.

Na Visão geral, role até a área do controle: a prévia da câmera fica abaixo do robô 3D, à esquerda, e os controles permanecem à direita. Em telas de computador, a coluna esquerda fica fixa no topo e distribui a postura e o vídeo conforme o espaço disponível; se faltar espaço, a página rola. No celular, os elementos aparecem nesta ordem: imagem do controle, robô 3D, câmera e controle remoto. O vídeo WebRTC existente só se conecta automaticamente quando o cartão de prévia está visível, a Visão geral está aberta, a verificação somente leitura informa que a origem configurada é uma câmera e o serviço de vídeo está ativo. Para a origem de teste, origem desconhecida ou serviço indisponível, aparece um espaço reservado; a verificação se repete a cada 10 segundos, sem reproduzir automaticamente o padrão de teste. Trocar de página, tirar o cartão da tela ou enviar o app para segundo plano cancela a leitura e libera a conexão de vídeo. A página independente da câmera ainda permite iniciar a reprodução da origem de teste. O layout reutiliza o mesmo cliente de vídeo, não inicia serviços do sistema e não implementa detecção e configuração automáticas quando a câmera é conectada ou desconectada fisicamente.

**Câmera:** conecta ao vídeo WebRTC local da rede fornecido pelo `mediad` (porta de sinalização padrão 8443). É possível iniciar, parar e restabelecer a conexão. A página só indica reprodução depois que os quadros reais começam a chegar; trocar de página ou enviar o app para segundo plano libera a conexão. O Studio apenas lê o vídeo e seus metadados: não ativa a câmera do computador ou celular e não envia comandos de movimento. A imagem é exibida com o ângulo de instalação informado pelo sistema que executa o vídeo.

**Identificação da origem:** `[media] source="test"` na imagem indica um padrão de teste; conseguir reproduzi-lo não comprova que uma câmera real esteja conectada. Quando a origem configurada é `camera`, a página informa “configuração: câmera”, mas o arquivo de configuração não comprova o estado atual. Se o serviço de vídeo indicar um dispositivo simulado, isso será informado separadamente. A versão atual ignora a opção antiga `media.camera`; o Studio não a usa para inferir a origem real.

**ToF:** recebe a grade de distâncias 8×8 de `tof.stream` pelo socket `/run/tofd/tof.sock`. Mostra a quantidade de células válidas, as distâncias válidas mínima e máxima em milímetros e o estado bruto de cada célula. Só entram nas estatísticas células com estado 5/9 e distância positiva. “Sem alvo” (255) e falha de medição são exibidos separadamente. Há mensagens distintas para serviço desconectado, sensor ausente, espera pelo primeiro quadro, formato inválido e dados vencidos. Dados `fake`/`sim` são identificados como simulados.

A leitura dos sensores é independente da conexão de movimento do `robotd` e só ocorre enquanto a página correspondente está visível. Não há desvio automático de obstáculos, navegação nem gravação em segundo plano; a configuração dos serviços do sistema não é alterada.

Em instalações avançadas, use `--tof unix:/run/tofd/tof.sock`, `--camera-socket unix:/run/mediad/media.sock` e `--camera-signaling-port 8443` para indicar os serviços locais. `--tof none` ou `--camera-socket none` desativa explicitamente a verificação somente leitura correspondente. Em testes de desenvolvimento, o socket pode apontar para um endpoint TCP controlado, como `tcp:127.0.0.1:porta`. A página não aceita endereços arbitrários de socket ou servidor de vídeo. A sinalização da câmera usa o nome de host de onde o Studio foi aberto; um túnel SSH remoto que encaminhe somente a porta 8000 não encaminha automaticamente o fluxo de vídeo.

O teste local `tests/test_sensors_e2e.py` usa um ToF simulado explicitamente identificado e uma implementação RTC de teste no navegador para verificar a reprodução na página, a navegação, os erros e a liberação de recursos. Esses testes de software não substituem a validação do hardware da câmera, do codificador e do ToF.

## Gravação e reprodução de movimentos pela Web

Na área de controle remoto, há a função “Gravar e reproduzir movimentos”. Siga o procedimento habitual para deixar o robô firme e pronto para andar; desligue o controle físico, toque em “Iniciar gravação” e use o joystick web, os controles da cabeça, do corpo e da boca, os sons ou os botões “Sentar/Levantar” (também disponíveis na cruz de direção web). É possível salvar uma gravação contendo apenas a transição de sentado para em pé. Durante essa transição, aguarde a confirmação do estado antes de executar a etapa seguinte. Também é possível ativar “Movimento expressivo”, que gera movimentos aleatórios e leves da cabeça e da boca; esse recurso é interrompido antes de iniciar uma transição entre sentado e em pé. O tempo em pausa não entra na duração da gravação. Ao terminar, informe um nome para salvá-la.

Selecione uma gravação na lista e reproduza-a 1, 3 ou 5 vezes. É possível pausar, continuar, parar, renomear e excluir; o conteúdo salvo permanece após atualizar a página ou reiniciar o Studio. “Movimento expressivo” também pode ser ativado separadamente. O `robotd` continua executando os movimentos; a interface Web não assume o barramento dos servos, não coloca o robô em pé nem alivia o torque ao ativar esse recurso.

Uma gravação guarda os comandos de controle aceitos e seus intervalos, mas não garante a repetição do mesmo trajeto no espaço. Ela não inclui vídeo da câmera, áudio do microfone, comandos para aplicar ou aliviar torque, início ou parada da estratégia de movimento nem alterações de configuração. Sentar e levantar são salvos como etapas com objetivo explícito. Na reprodução, o Studio lê a postura atual e não repete cegamente o botão de alternância; só executa a etapa seguinte depois de confirmar uma fase de estratégia recente e leituras consecutivas das posições reais e desejadas das articulações. Enquanto aguarda, a linha do tempo fica pausada. Gravações que incluem sentar e levantar são salvas no formato v2; gravações antigas v1 continuam legíveis. Uma versão do programa que só aceite v1 ignora as gravações v2; depois de restaurar a versão nova, elas voltam a ser lidas. Não exclua os arquivos originais.

Uma gravação que termina com o robô sentado pode ser reproduzida uma vez. Para repeti-la várias vezes, a última sequência precisa terminar com o robô em pé; caso contrário, a página explica o motivo e não acrescenta uma etapa automática para levantá-lo. Pausar, parar ou sair da interface cancela as etapas seguintes e limpa os comandos contínuos, mas uma transição entre sentado e em pé já enviada ao programa principal ainda será concluída. Para aliviar o torque imediatamente, use a parada de emergência existente. Se a fase ou a leitura da postura não estiver clara, a espera exceder 15 segundos ou a resposta se perder, as etapas seguintes são interrompidas e o motivo é informado; a alternância não é repetida automaticamente.

Habilidades de modelos, como chutar, rolar e pegar objetos, não são gravadas; o controle manual dessas habilidades continua funcionando. Depois de executar uma habilidade de modelo, pare a estratégia manualmente, reinicie a caminhada e aguarde leituras recentes que confirmem que o robô está pronto antes de começar uma gravação ou ativar “Movimento expressivo”. Não estime a conclusão da habilidade pelo tempo decorrido.

Só pode haver uma sessão de página por vez. Uma intervenção manual nos botões ou no joystick interrompe primeiro a reprodução automática. A conexão de um controle físico, a saída da área de controle remoto, o envio do app para segundo plano, a perda de foco ou de conexão, a parada de emergência ou um estado anormal também interrompem os comandos automáticos; reconectar não retoma a reprodução. A pausa limpa os alvos de velocidade, cabeça, corpo e boca. Ao continuar, restaura a postura mantida no ponto da pausa e aguarda novos comandos de velocidade. Se o modelo ou as configurações de controle mudarem, o trecho antigo não será reproduzido. Ao final de cada ciclo, o robô volta a emitir som, libera a postura mantida do corpo e fecha a boca. Comandos contínuos atrasados são agrupados para evitar o envio de uma sequência de movimentos obsoletos.

Cada gravação pode ter no máximo 60 segundos, 6.000 eventos e 1 MiB; são permitidas até 20 gravações, com nomes de até 32 caracteres. Os arquivos JSON versionados ficam em `motion-recordings/`, no diretório de estado do Studio, e são gravados atomicamente. Gravações danificadas são ignoradas e sinalizadas na página, sem afetar os controles nem os demais arquivos válidos. Preserve esse diretório de dados do usuário ao desinstalar ou atualizar o Studio.

A implementação está dividida entre `studio/motion_store.py` (validação e salvamento de arquivos), `studio/motion_studio.py` (sessões, linha do tempo e movimento expressivo), `studio/motion_posture.py` (objetivos de postura e validação das leituras), `web/motion-studio.js` (interface) e `web/motion-heartbeat.js` (atividade da página). O recurso usa o comando existente `pad.op` com `op=motion`; o nome do estado `pad.motion` permanece inalterado. Os registros atuais de desenvolvimento e validação estão no [plano de movimentos pela Web](../../docs/superpowers/plans/2026-10-25-web-motion-studio.md) e no [plano de extensão para sentar e levantar](../../docs/superpowers/plans/2026-10-25-web-posture-recording.md); a simulação local e a validação no robô são documentadas separadamente.

2026-10-25: a versão `c18783c` foi implantada no robô atual pelo endereço de controle já utilizado; somente o Studio foi reiniciado. As 351 verificações de software passaram, e foram confirmadas as identidades do serviço de controle, dos recursos estáticos e dos dados do usuário. O dispositivo exige login na Web; não se ignorou essa proteção para conferir snapshots, portanto o efeito real dos movimentos ainda aguarda confirmação do usuário. O pacote congelado do código-fonte, o backup e o escopo da reversão estão registrados na [validação da implantação](../../docs/superpowers/verification/2026-10-25-web-motion-studio.md). A imagem não foi atualizada pelo mecanismo geral de atualização remota.

No mesmo dia, após a confirmação do acesso por uma captura de tela do usuário, foi identificado que a barreira de recuperação após parar uma habilidade aguardava incorretamente o desligamento de uma opção de configuração estática. A versão `db970dd` corrigiu o fluxo com base no estado de execução de `bus.policy_enabled` e passou a orientar o usuário a confirmar a parada antes de tocar em “Começar a andar”. As 205 verificações de backend e o fluxo completo de recuperação, gravação e reprodução no navegador passaram. A correção foi instalada no robô original, com reinicialização somente do Studio. O efeito real dos movimentos da cabeça e da boca ainda aguarda confirmação; consulte a atualização correspondente no mesmo registro de validação.

Uma atualização posterior do mesmo dia, `aa825fc`, acrescentou sentar e levantar às gravações. As 389 verificações de software e uma revisão independente passaram, e a atualização foi implantada. O usuário confirmou que conseguiu salvar e que a reprodução das transições entre sentado e em pé funcionou. O escopo da validação no robô, as esperas por estado e a compatibilidade reversa do formato v2 estão descritos na [validação de sentar e levantar](../../docs/superpowers/verification/2026-10-25-web-posture-recording.md).

## Modo de bancada: controlar os servos pelo computador com a placa de depuração Feetech, sem gravar o controlador principal

Conecte a placa de depuração Feetech (ou um adaptador USB para TTL) ao computador e ligue os servos à alimentação. Em seguida, execute:

```bash
py -3.13 -I run.py --bench
```

Esse modo não se conecta ao programa principal e abre automaticamente a página “Servo” no navegador. Selecione a porta COM no menu “Porta serial”, no topo da página, e toque em “Conectar” para controlar os servos, como no `servo-web`.
Para conhecer a interface sem conectar o hardware, escolha “Demonstração (sem servos)” no menu da porta serial. O Studio simulará 15 servos.

## Instalar no robô

1. **Copie os arquivos:** copie o diretório inteiro `software/studio` para `/home/radxa/studio-dev` no robô. Você pode usar `scp -r` ou extrair um pacote de uma unidade USB.
2. **Faça a verificação inicial:** no robô, execute `python3 -I run.py --selfcheck`. Essa verificação somente leitura mostra as versões e consulta uma vez cada serviço: `robotd`, `configd` e `padd`.
3. **Instale o auxiliar com privilégios de root:** execute `cd deploy && sudo sh install.sh radxa`. A versão 0.7.2 do auxiliar faz a transferência do barramento dos servos, o pareamento do controle, o controle do ponto de acesso, os comandos `calib-read` e `calib-commit` (gravação da calibração no programa principal e troca para o modo de movimento), `ssh-status` e `ssh-password` (controle de SSH na página “Mais”) e `imu-recalibrate` (nova validação da orientação de instalação salva da IMU). Antes de desligar o ponto de acesso, o auxiliar grava `/run/microduck/studio-connecting.json` para que o netcheck não interfira durante a conexão. Ao devolver o controle pela página Servo, um snapshot em tempo real do modo de calibração também confirma que o programa principal iniciou. A versão 0.5.1 só reconhecia `control` no modo de movimento e, no modo de calibração, aguardava 30 segundos até declarar falha. Consulte `deploy/INSTALL.md` para ver as etapas, a desinstalação e as verificações no robô.
4. **Configure o serviço na inicialização:** siga o comando no cabeçalho de `deploy/microduck-studio.service` para instalá-lo:

   ```bash
   sudo install -m 644 microduck-studio.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now microduck-studio
   ```

   Para remover o serviço:

   ```bash
   sudo systemctl disable --now microduck-studio && sudo rm /etc/systemd/system/microduck-studio.service && sudo systemctl daemon-reload
   ```

5. Abra `http://<IP do robô>:8000/` e siga a lista de primeiros passos da página.

O fluxo principal para parear o controle usa o auxiliar de root, que chama o comando oficial `/usr/local/bin/robotctl pad pair --json`. Na placa `/var/lib/robot/weird-ble`, o comando para primeiro o `btd`, desliga e religa o adaptador Bluetooth e reinicia o `btd` depois do pareamento. Se o auxiliar não estiver instalado ou for de uma versão antiga, o Studio tenta usar `configd` e `bluetoothctl`. Esse método alternativo pode falhar nessa placa; nesse caso, o assistente orienta reinstalar o auxiliar ou executar `sudo robotctl pad pair` no robô.

Um resultado de pareamento bem-sucedido não significa que os botões já estejam funcionando. Depois que o auxiliar ou o `configd` informa que o controle foi vinculado, o assistente pode solicitar até duas vezes que o controle selecionado se conecte enquanto aguarda a conexão e os dados de entrada do `padd`. Cada tentativa dura no máximo 5 segundos e respeita o limite de espera atual; o pareamento não é apagado e o Bluetooth não é reiniciado. A prontidão só é confirmada quando a entrada do `padd` informa o mesmo endereço MAC; a conexão de outro controle não conta. Se o serviço demorar para atualizar o estado ou a entrada chegar no limite do tempo, vale a entrada efetivamente recebida. Se o mesmo controle voltar a funcionar depois, o aviso antigo de “desconectado/não foi possível ler os botões” também é removido. Se o usuário cancelar, o `padd` não estiver ativo ou a caminhada começar, o Studio não faz novas tentativas. Em versões antigas sem acesso direto às entradas, a orientação informa que não foi possível confirmar o funcionamento.

Essa reconexão é específica do fluxo de pareamento pela Web. Se o controle já estiver pareado, mas suspenso, pressione brevemente o botão Home/Xbox para despertá-lo; não é necessário removê-lo e pareá-lo de novo. Essa correção não cria tentativas ilimitadas de reconexão em segundo plano nem confirma que todos os modelos reconectem após uma queda de energia.

A imagem de fábrica executa o `robotd` no modo de calibração: `ExecStart` inclui `--commissioning` no arquivo `/etc/systemd/system/robotd.service.d/zzzz-zz-microduck-commissioning.conf`. Assim, `calibration-status` e `busStatus.last_sample` ficam disponíveis imediatamente, permitindo fazer a calibração inicial da IMU e centralizar os servos. Depois que a etapa 3 da lista de primeiros passos grava os dados com sucesso, o auxiliar remove esse arquivo, executa `daemon-reload` e reinicia o `robotd`, que volta ao modo de movimento. Se `systemctl show robotd -p ExecStart` mostrar `--commissioning`, mas o arquivo não existir, o auxiliar recusa a troca automática (`foreign_commissioning`); exporte um pacote de diagnóstico pela página de registros.

A página IMU mantém disponível a seção “Orientação de instalação da IMU” mesmo depois de salvar e validar o quaternion de instalação; use “Recalibrar orientação” para refazer a calibração. Segure o robô e alivie o torque. Depois da segunda confirmação, o auxiliar de root atualizado muda temporariamente do modo de movimento para o modo de calibração; se o robô já estiver nesse modo, a captura pode recomeçar diretamente. O procedimento continua igual: mantenha o robô imóvel por 3 segundos, incline todo o tronco para a frente entre 15° e 30° e capture por mais 3 segundos; então a orientação é calculada e validada pelo programa principal. **Antes de tocar em “Enviar para validação pelo programa principal”, coloque o robô novamente na posição vertical e aguarde até que fique parado**; depois, incline-o para a frente conforme as instruções. A sessão de recuperação da recalibração pelo auxiliar mantém o torque aliviado. O modo de calibração de fábrica também permite a captura na postura em pé; o procedimento de ajuste fino nessa postura não mudou.

O programa principal detecta automaticamente na inicialização a IMU no barramento de ID 200. Há suporte para FT6 e IMU-to-DXL (Feetech), além de SFLP 124/12 (Dynamixel 2.0). A página IMU mostra o protocolo e o tipo de placa detectados, tanto no modo de calibração quanto no modo de movimento. O nome da placa descreve o layout de registradores detectado e não comprova o fabricante. Para especificar o protocolo manualmente, altere a configuração do programa principal para `bus.imu_protocol = "auto"`, `"feetech"` ou `"dxl2"`; a interface Web não permite trocar o protocolo durante a execução. Os procedimentos para BNO085 e LSM6DSV16X via I²C permanecem iguais.

Consulte o [guia de uso](../../docs/Qinmo-IMU-uso-web.md) para a seleção única da Qinmo na interface Web, a reconexão controlada e a validação obrigatória da orientação de instalação. O tipo configurado e a conexão efetiva são exibidos separadamente. Qinmo é identificada explicitamente como configuração; nem o ID 200 nem o layout de registradores servem para confirmar automaticamente o fabricante. O auxiliar 0.7.2 também preserva `imu_bus_profile` (padrão `legacy`); uma mudança no tipo de dispositivo, mesmo entre dispositivos Feetech, invalida a orientação antiga e o resultado pendente de gravação. A validação local de software não equivale à validação no hardware; a imagem publicada não foi implantada nem atualizada.

O programa principal grava `imu_bus_protocol` depois de validar a orientação de instalação do barramento. Calibrações antigas sem esse campo só são compatíveis com Feetech. Se o protocolo detectado não corresponder, a página orienta recalibrar; pular a etapa 2 não faz com que a orientação antiga seja considerada validada. O programa principal mantém a opção de refazer a calibração quando os motores estão desabilitados no modo de movimento. A etapa 3 e o auxiliar 0.7.1 preservam e leem esse campo. Depois de recalibrar, a nova associação pode ser usada; se a operação for cancelada, o arquivo original é restaurado. Uma alteração no protocolo, no layout da placa ou nos bytes brutos de identificação invalida a captura atual, qualquer cálculo em andamento e a antiga calibração de postura em pé. As placas DXL2 não fornecem número de sequência da amostra, bits de estado ou idade da leitura do sensor. O programa principal verifica a atualidade do dado recebido pelo host e se os bytes brutos permanecem estáveis; a página não inventa esses valores de diagnóstico.

Na primeira calibração da orientação de instalação pelo modo de calibração de fábrica, também é possível tocar manualmente em “Ativar postura em pé”. Aguarde a postura HOME estabilizar (erro ≤5°), segure o tronco com as duas mãos, capture os dados com o robô parado e inclinado para a frente, volte à posição vertical e envie os dados para validação pelo programa principal. São aceitos os estados de torque aliviado ou de postura em pé confirmada. O procedimento é recusado se o robô estiver se levantando, se o torque for desconhecido, se estiver em movimento ou se o alívio do torque ainda não tiver sido confirmado. Quando o auxiliar coloca o robô no modo de calibração a partir do modo de movimento para uma sessão de recuperação da recalibração, o torque precisa permanecer aliviado durante todo o procedimento; assim, a reinicialização do programa principal ao restaurar o modo não altera a postura em pé. A captura não alivia o torque nem inicia movimentos automaticamente.

A sessão de recalibração preserva a calibração original e as configurações iniciais. É possível continuá-la depois de atualizar a página ou reiniciar o Studio, ou escolher “Cancelar e restaurar os parâmetros originais”. Após a validação pelo programa principal, cada item é lido de volta para confirmar o sensor atual e a nova orientação. Só são restaurados o modo de movimento e as permissões que estavam ativos originalmente. Os zeros dos servos (inclusive os diferentes de 2048), as direções, os limites, outras IMUs e as configurações desconhecidas são preservados. Mesmo após uma restauração bem-sucedida, o torque continua aliviado. Em caso de falha, a opção de restauração permanece disponível e uma orientação que não tenha sido lida de volta não é informada como concluída. Esse fluxo exige atualizar o Studio, o auxiliar de root e o `sudoers`; ele não usa a etapa 3 da lista de primeiros passos para regravar a calibração dos servos.

**O modo de calibração exige uma versão atualizada do fork.** Ao iniciar, o `robotd` do fork grava um relatório de inicialização (`{"mode":"commissioning","phase":"configuring_bus",...}`). `robot.busStatus` continua retornando esse relatório enquanto a fase indicar inicialização. Depois da primeira leitura bem-sucedida, passa a retornar snapshots em tempo real do modo de calibração, com `last_sample` e uma destas fases: `ready`, `moving`, `read_error`, `stop_unconfirmed` ou `power_pending`. Versões antigas do fork nunca limpavam o relatório, então o Studio mostrava “iniciando” indefinidamente e não recebia `last_sample` (como ocorreu na validação no robô em 20/10). O fork foi corrigido para limpar o relatório depois da primeira leitura bem-sucedida; use uma imagem posterior a 20/10/2026 ou reinstale aquele `robotd`. No Studio, todas as fases dos snapshots em tempo real indicam que o programa principal iniciou. `read_error` significa que ele iniciou, mas houve um erro na leitura dos servos; a mensagem original do programa principal é mantida. Se o programa continuar informando uma fase de inicialização por mais de 30 segundos após a conexão, a Visão geral informa que ele continua “iniciando” e oferece um atalho para a página de registros. O cabeçalho, as tarefas pendentes e a lista de primeiros passos também deixam de dizer que a inicialização “normalmente leva 10 segundos”.

Quando o robô estiver alimentado por uma fonte de bancada, selecione “Fonte de bancada” em “Configurações → Bateria”. O Studio exibirá a tensão, sem calcular nem informar o nível de carga.
Por padrão, o Studio não tem senha e qualquer pessoa na mesma rede pode abri-lo. Defina uma senha em “Mais → Senha de login”. Depois disso, será necessário fazer login para alterá-la; também é possível removê-la. O comando `python3 -I run.py set-password` continua disponível, mas deve ser executado como usuário `radxa`, sem `sudo` (o Studio não consegue ler um arquivo de senha criado pelo root).

## Lista de primeiros passos: fazer, marcar como concluído ou pular

Cada item sempre tem três botões (solicitação do usuário em 20/10: permitir refazer uma etapa já feita e permitir ignorar uma etapa):

- **Fazer:** abre a página daquela etapa. Se a verificação encontrar um problema, o item oferece a opção “Fazer novamente”.
- **Marcar como concluído:** indica que a etapa já foi feita, por exemplo, que o zero dos servos do segundo robô foi ajustado na página Servo do Studio. O item recebe uma marca ✓ e registra “Você marcou como concluído” com a data e a hora. Essa opção substitui a antiga confirmação de que a calibração já tinha sido feita e só precisava ser conferida.
- **Pular:** deixa a etapa para depois e marca o item com ↷.

Um item marcado oferece as opções “Fazer novamente” e “Cancelar” (para um item pulado, “Cancelar pulo”). A marca é associada à impressão digital daquela etapa — zero dos servos, orientação da IMU, calibração, controle e assim por diante. Se essa impressão digital mudar, a marca deixa de valer e o item volta ao estado “Pendente”. Se não for possível ler a impressão digital quando o item for marcado, ela será associada assim que estiver disponível.

Mesmo em situações antes bloqueadas — o programa principal informar que a etapa não foi concluída, não ser possível ler o estado, haver uma falha de medição, uma parada de emergência ou um ajuste dos servos em andamento — os botões continuam disponíveis. Porém, “Marcar como concluído” e “Pular” exigem dois toques. O segundo botão descreve a consequência, por exemplo: “Tem certeza de que deseja pular? O programa principal informa que a calibração está incompleta; o robô poderá não conseguir ficar em pé”. O backend também recusa a ação se não receber a confirmação.

Se a etapa 1 for marcada como concluída ou pulada, o requisito “zero dos servos” será considerado atendido na etapa 3, “Gravar no programa principal”. Isso só é adequado quando o zero dos 15 servos em 2048 está correto, ou seja, quando ele já foi ajustado na página Servo do Studio.

Se a etapa 2 for marcada como concluída ou pulada, mas a orientação da IMU em uso no programa principal não estiver confirmada e a página IMU não tiver uma calibração em pé pendente (arquivo `imu-pending.json` ausente), a etapa 3 **grava a orientação padrão de montagem da IMU e a marca como confirmada**. Na validação no robô em 21/10, o fork exigia que a orientação estivesse confirmada para entrar no modo de movimento; ao pular todas as etapas, o robô permanecia no modo de calibração. Os valores padrão são:

* Placa do barramento (`bus`): o valor existente de `imu_mount_quat` no arquivo; a montagem oficial de fábrica é `[0.7071067811865476, 0, 0.7071067811865476, 0]`.
* BNO085 (`bno08x`): `[0.5, 0.5, 0.5, 0.5]`, valor `BNO08X_DEFAULT_MOUNT` em `duck-control/src/trunk_imu.rs` do fork.
* LSM6DSV16X (`lsm6dsv16x`): `[0.7071067811865476, 0, 0.7071067811865476, 0]`, montagem recomendada para a réplica, com o eixo x do módulo voltado para baixo e o eixo z para a frente; verificada no segundo robô em 17/10. O padrão definido pelo próprio fork é o quaternion identidade, com a observação de que a placa não tem uma orientação para cima estabelecida; esse padrão não é usado.

Na preparação, a página informa: “Você marcou a etapa 2 como concluída: será gravada a montagem padrão da IMU (sensor: montagem correspondente). Se a montagem física for diferente, o robô poderá pender para um lado ao ficar em pé. Depois de gravar, calibre a IMU em pé na página correspondente e grave novamente no programa principal”. O segundo toque em “Gravar no programa principal” pede confirmação explícita de que a montagem padrão será gravada. Se a página IMU tiver uma calibração em pé pendente (`imu-pending.json`), ela continua sendo usada. Se o programa principal já confirmar a orientação, esse valor também continua sendo usado. Se a página IMU tiver dados de outro sensor ou o programa principal ainda não identificar qual sensor está em uso, o Studio não tenta adivinhar e bloqueia a operação como antes. O auxiliar `calib-commit` continua aceitando somente `imu: {source, quat}`. Assim, o fluxo **pular as etapas 1 e 2 → gravar na etapa 3 → entrar no modo de movimento** pode ser concluído.

## Escolher o endereço para abrir o Studio

Em um computador Windows com o proxy do sistema Clash ativado, `duck-xxxx.local` pode não abrir porque a solicitação passa pelo proxy e resulta em erro 502. O endereço `duck-xxxx`, sem o ponto, pode funcionar: o Windows localiza o robô por LLMNR e o proxy ignora nomes incluídos em `<local>`. Use o endereço adequado ao dispositivo:

- **Computador Windows:** `http://duck-xxxx:8000/` (também pode funcionar com o proxy ativado).
- **iPhone ou Mac:** `http://duck-xxxx.local:8000/`.
- **Celular Android ou falha nos outros endereços:** encontre `duck-xxxx` na lista de dispositivos do roteador e use o endereço IP.
- **Computador com o modo TUN do Clash ativado:** se ainda não abrir, configure a rede local (`192.168.0.0/16`) como conexão direta no Clash.

Na página “Mais”, a seção “Endereços deste robô” lista os endereços disponíveis: o IP atual (campo `ip4` de `net.status` do `configd`; no modo de ponto de acesso, `10.42.0.1`), `duck-xxxx` e `duck-xxxx.local`. Cada um pode ser copiado. Também é possível ver o IP ao passar o cursor sobre o nome do robô na barra superior da Visão geral. A lista de redes Wi-Fi omite o ponto de acesso do próprio robô, usando `hotspot_ssid` no `net.json`; se o campo não existir, omite redes salvas cujo nome comece com `Microduck-`.

**Redirecionamento automático depois de conectar ao Wi-Fi** (solicitação do usuário em 21/10, após precisar se reconectar três vezes): ao iniciar a conexão, a página guarda os endereços `http://duck-xxxx:8000/` e `http://duck-xxxx.local:8000/` que deverá localizar. O nome do host vem do `net.json`, e a porta corresponde a `--listen`.

Quando a conexão com o robô cai — porque o WebSocket foi desconectado ou não chegaram mensagens por 5 segundos —, o cartão informa que o robô está se conectando ao Wi-Fi da casa e pede que o computador ou celular também se conecte a essa rede. Ele lista os dois endereços clicáveis e orienta encontrar o IP de `duck-xxxx` na lista de dispositivos do roteador caso a busca falhe.

A cada 2 segundos, o Studio tenta carregar `<endereço>probe.svg?t=<horário>` com `new Image()`. O arquivo `web/probe.svg`, como os demais arquivos estáticos, não exige login e não é armazenado em cache; imagens entre origens diferentes podem ser carregadas sem CORS. O primeiro endereço a responder abre automaticamente. Cada tentativa aguarda no máximo 6 segundos e o mesmo endereço não é consultado novamente enquanto essa tentativa não terminar.

A busca dura no máximo 3 minutos. Se nenhum endereço responder, o Studio volta às instruções habituais de acesso para cada dispositivo. A busca é interrompida se a página se reconectar ao endereço original — por exemplo, se o ponto de acesso voltar — e a página mantém a informação sobre a falha.

## Diferenças entre a imagem do sistema e a instalação manual

O cartão “Conectar ao Wi-Fi” depende de componentes incluídos na imagem do sistema da réplica; eles não fazem parte do Studio:

- estado de configuração da rede gravado pelo netcheck em `/run/microduck/net.json`;
- configuração do ponto de acesso `Microduck-Hotspot` no NetworkManager;
- `configd` iniciado com `--allow-user btd,radxa`, que permite ao Studio executar `net.scan`, `net.connect` e `net.forget`;
- configuração mDNS, necessária para localizar o robô pelo endereço `duck-xxxx.local` no celular.

Se o Studio e o auxiliar de root forem instalados manualmente conforme `deploy/INSTALL.md`, mas os overlays da imagem da réplica estiverem ausentes, esses componentes não estarão disponíveis e o cartão “Conectar ao Wi-Fi” não será exibido. As páginas Visão geral, Controle, Servo, IMU e Registros continuam funcionando normalmente.

## Protocolo entre a página e o Studio (WebSocket `/ws`)

Durante a negociação da conexão, o Studio valida `Host` e `Origin`; se algum deles não corresponder, recusa a negociação (o navegador recebe somente o código 1006, e o motivo fica nos registros). Se o usuário ainda não tiver feito login, a conexão é aceita e encerrada em seguida com o código 4401; ao receber 4401, a página abre o login.

| Direção | Mensagem | Descrição |
|---|---|---|
| Studio → página | `{"t":"hello","version","duck"}` | Enviada uma vez ao conectar |
| | `{"t":"state", …}` | Estado enviado a 10 Hz quando a página está visível; campos documentados em `summarize` no arquivo `studio/state.py` |
| | `{"t":"hb"}` | Heartbeat a 1 Hz quando a página está em segundo plano; nessa situação, não há inscrição no estado em tempo real do `robotd`, reduzindo o uso da CPU |
| | `{"t":"log","entry":{…}}` | Novo registro |
| | `{"t":"result","id","ok","reason","data"}` | Resposta a um comando; dados como a lista de redes Wi-Fi encontradas ficam em `data` |
| | `{"t":"pad", …}` | Snapshot do controle: enviado a 10 Hz quando a área do controle está visível na tela e a 1 Hz quando não está, para atualizar o cartão do controle na Visão geral. Se listas longas não mudarem, a mensagem inclui `lists_same` e omite as listas |
| Página → Studio | `{"t":"hb","seq","visible","route","pad_visible"}` | Enviado uma vez por segundo e novamente assim que a área do controle aparece ou desaparece. `pad_visible` indica se a área está na tela; `#/pad` é apenas uma âncora na Visão geral |
| | `{"t":"cmd","id","name","args"}` | Comandos `relax`, `servo.*`, `imu.op`, `calib.op` (`preview`/`commit`, etapa 3 da lista), `pad.op`, `onboard.op` (`done` para marcar como concluído, `skip` para pular, `undone`/`unskip` para cancelar; `{step, confirmed}` exige dois toques, e o comando antigo `confirm_servo` continua aceito) e `net.op` (`scan`/`connect`/`forget`) |

Os campos de `state` relacionados à sessão dos servos são usados na faixa de aviso no topo das páginas: `servo_session` só aparece quando há uma sessão ativa e contém `holding` (quantos servos continuam mantendo torque), `unknown` (quantos tiveram o torque desconhecido) e `restored` (se o Studio retomou o controle depois de reiniciar); `servo_handback_s` fica ativo depois da devolução e até o programa principal se conectar; `servo_orphan` indica que o barramento estava aberto no encerramento anterior e ainda não foi retomado; `servo_conflict_s` informa que o `robotd` foi iniciado manualmente durante a sessão, dentro dos últimos 10 minutos. Ao sair da página Servo, `servo.close {if_idle:true}` só devolve o barramento quando uma leitura naquele instante confirmar torque 0 nos 15 servos, nenhuma outra página estiver usando a página Servo e não houver calibração nem movimento em andamento. O comando `servo.close {}` (botão “Devolver ao programa principal”) aguarda a conclusão das operações pendentes dos servos, alivia o torque e devolve o barramento.

`state.starting_s` e `state.starting_long` informam por quantos segundos o programa principal relatou continuamente uma fase de inicialização desde a conexão atual e se esse período ultrapassou 30 segundos. Esses campos são usados para atualizar a Visão geral, a barra superior e as tarefas pendentes com o aviso de inicialização prolongada.

`state.net` representa o estado da rede. `known=false` indica que não há `net.json` e oculta toda a seção de Wi-Fi. Caso contrário, inclui `mode` (`wifi`, `hotspot` ou `none`), `ssid`, `signal` e `ip4` atuais, `hostname`, `url_local` (`duck-xxxx.local`, na porta definida por `--listen`), `url_host` (`duck-xxxx`, sem ponto), `ip_now` (IP disponível no momento; no modo de ponto de acesso, o endereço desse ponto), `urls` (itens da seção “Endereços deste robô”, no formato `{kind: ip / host / local, url, note}`), `hotspot {ssid, ip, psk}` do ponto de acesso do robô, `last_try` com o resultado da última tentativa e `busy`. `net.op scan` remove da lista o ponto de acesso do próprio robô. `net.op connect` primeiro responde “Iniciando a troca”; a página usa `url_host` e `url_local` como endereços para localizar o robô depois. O desligamento do ponto de acesso e a solicitação ao `configd` ocorrem em segundo plano. O resultado é gravado em `net-last-try.json`, no diretório de estado, sem incluir a senha. A senha do Wi-Fi da casa é enviada uma única vez da página ao `configd` e não é incluída nos registros, no estado nem no pacote de diagnóstico.

Mesmo redes criptografadas já salvas exigem que a senha seja informada novamente: o `configd` oficial retorna `unsupported` quando recebe uma rede protegida sem senha. Se a senha estiver incorreta, o Studio remove com `net.forget` a configuração inválida criada pela tentativa e reativa imediatamente o ponto de acesso. Ele também reativa o ponto de acesso em caso de `timeout`, `other` ou de seu próprio tempo limite aguardando o `configd`. Uma espera de 60 segundos sem resposta do serviço de configuração da rede do robô é registrada separadamente como ausência de resposta; ela não é confundida com o `timeout` do `configd`.
Antes de desligar o ponto de acesso, o auxiliar grava `/run/microduck/studio-connecting.json` para impedir que o netcheck interfira durante 90 segundos. O marcador é removido depois que o ponto de acesso é ativado com sucesso.

A página determina se a conexão foi perdida pelo intervalo entre as mensagens recebidas (fica esmaecida após 1 segundo e exibe um alerta após 3 segundos). Os relógios dos dois dispositivos não são comparados, pois o relógio do robô pode estar configurado para 1970.

## Logs

Os registros ficam em `logs/studio-YYYY-MM-DD.log`, são mantidos por 14 dias e não excedem 50 MB no total. Cada linha registra uma ação:

```
2026-10-18T00:41:56.194+09:00 [comando] → liberar torque (computador 127.0.0.1) · etapa: robot.relax
2026-10-18T00:41:56.197+09:00 [comando] ← liberar torque: sucesso · 3 ms · enviado, aguardando confirmação de leitura · etapa: robot.relax · resposta original: {"accepted": true}
```

Em caso de erro, o registro informa “parou em: etapa · resposta original: … · sugestão: … · estado atual: {…}”. Senhas e tokens são ocultados automaticamente. Mensagens idênticas dentro de um minuto são registradas uma vez, com a quantidade de ocorrências agrupadas.

A página “Logs” mostra os 500 registros mais recentes e permite exportar um pacote de diagnóstico com logs, estado naquele momento, respostas originais do robotd, versões e logs de sistema do robotd. Use-o ao pedir ajuda nos grupos.

Cada comando registra envio e resposta, duração e estado atual. O código dessa funcionalidade é original deste projeto.

## Testes

```bash
py -3.13 -I run_tests.py               # computador
python3 -I run_tests.py                # robô
```

Regressão direcionada da integração do barramento com a IMU (inclui página Edge sem interface gráfica; os testes de navegador são ignorados se Edge não estiver disponível ou Node for anterior à versão 22):

```bash
py -3.13 -I -c "import sys;sys.path[:0]=['deps','.','dev'];import unittest;unittest.main(module=None,argv=['x','tests.test_imu_backend','tests.test_commit','tests.test_helper_calib','tests.test_helper_imu_redo','tests.test_imu_bus_ui','tests.test_imu_wizard_e2e'])"
```

Cobertura:

- Login: sessões, espera após cinco senhas incorretas, CSRF ao sair, matriz Host 421/Origin e fechamento com 4401 do WebSocket sem autenticação.
- Logs: formatação, ocultação de dados, deduplicação e limpeza por dia, mesmo com o relógio parado em 1970.
- JSON-RPC: linhas incompletas ou muito longas, JSON inválido ou que não seja objeto e reconexão após timeout.
- Liberação de torque: não fica bloqueada por consultas lentas; confirma pela leitura; a ausência do sinalizador HD1910 não conta como confirmação; cobre modo de calibração, sucesso na primeira tentativa após reinício do robotd e não reenvia automaticamente um comando de torque aplicado por outro processo após a confirmação.
- Polling: erro em um item não bloqueia os demais; assina o fluxo em tempo real somente enquanto há alguém observando; heartbeat ausente significa que não há observador; cobre queda e retorno do robotd.
- Detecção de postura com dados gravados no robô; ida e volta completa do comando de liberação pelo WebSocket.
- Pareamento do controle: valida argumentos do auxiliar `pad-pair`/`pad-forget`; interpreta sucesso, falha e timeout do robotctl; fluxo principal do assistente, fallback para o auxiliar antigo, nova tentativa após falha de registro do proxy bluetoothctl, espera de 30 s do padd, reconexão limitada após parear, entrada real antes do serviço de estado, limites de timeout e cancelamento e recuperação de estado quando chega tarde uma entrada do mesmo controle.
- Configuração de rede: verbos do ponto de acesso no auxiliar e arquivo de janela de conexão; net.json ausente, inválido ou em cada modo; cache de busca; ordem de conexão e causas de falha (bad_key remove a configuração antes de reativar o ponto de acesso); restauração do ponto de acesso; somente uma conexão por vez; senha ausente de logs, state, last-try e pacote de diagnóstico.
- Senha de login: configuração inicial pela página, alteração somente após login, remoção, manutenção da sessão atual após alterar a senha, recusa de `set-password` como root e orientação do cartão quando estiver no modo de ponto de acesso sem senha.
- Estado de calibração: fake robotd envia primeiro o relatório de inicialização com quatro campos e depois do primeiro read retorna o snapshot do fork; `--commissioning-stuck-status` mantém o relatório inicial. O snapshot real indica que o controlador iniciou (resumo, requisitos e entrega ao auxiliar); se um fork antigo continuar em `configuring_bus`, a entrega considera que ele não iniciou e explica o estado real. Depois de 30 s contínuos no estado inicial, a interface informa que continua mostrando “iniciando”.
- Os três botões da lista inicial: “concluído”/“pular” em todos os casos antes bloqueados, confirmação em duas etapas com texto correto e recusa do backend sem confirmação; registro e invalidação de conclusão; associação posterior da impressão digital quando não foi possível lê-la; item 1 concluído satisfaz a verificação do zero dos servos no item 3; item 2 concluído sem direção confirmada grava a orientação padrão da IMU (placa do barramento, BNO085 ou LSM6DSV16X), verifica quaternion do auxiliar e passa na validação do modo de movimento; usa `imu-pending.json` quando existe, usa a orientação confirmada pelo controlador e mantém o bloqueio quando o chip não corresponde.
- Botões “ativar postura”/“desativar” da página da IMU: no modo de calibração, solicita confirmação e envia `imu.op hold`; o controlador recebe 15 direções e 3000 ms em `hold-home`; depois de ficar em pé, a página informa “modo de calibração (em pé)”; desativar usa `relax`. No modo de movimento, o comando é igual a “levantar” no controle e a “liberar torque” no topo, verificado de ponta a ponta no navegador.
- Endereços nos modos de ponto de acesso/Wi-Fi, exclusão do ponto de acesso do robô dos resultados da busca e apresentação dos três tipos de endereço no aviso de troca de rede.
- Localização do robô após conectar ao Wi-Fi: `probe.svg` não exige login e não fica em cache; apresenta os dois nomes de host; lógica exercitada no código real de `web/wifi.js` com relógio falso, duas buscas a cada 2 s, redirecionamento pelo primeiro endereço disponível, desistência após 3 minutos, parada quando o ponto de acesso retorna e sem repetir uma sondagem pendente; teste do aviso de desconexão, retorno do ponto de acesso e redirecionamento no navegador.
- Gravação no controlador: `calib-read` do auxiliar é somente leitura e não adquire bloqueio; `calib-commit` adquire o bloqueio e verifica os sinalizadores; sai do modo de calibração removendo drop-in; só confirma após ler de volta `mode=motion`, `phase=control` e todos os campos de `calibration-status`; erros de `waiting_for_bus` e do barramento são separados; divergência de leitura, falha em `.saved.toml` e falha de reinício provocam rollback, com erros de arquivo e modo separados; recusa enquanto a política está ativa ou quando `ExecStart` contém `--commissioning` mas falta o drop-in; mantém os dez backups mais recentes em ordem. Testa o estado de prontidão nos dois modos, fallback para `calib-read`, leitura de `last-result.json` após timeout, atualização do item 3 quando pending/centered muda, remoção do registro ao desfazer calibração de centro e saída de código idêntica dos dois TOMLs de grupo.
- Comando “gravar no controlador”: o auxiliar `calib-read` é somente leitura e não obtém o lock; `calib-commit` obtém o lock antes de verificar os sinalizadores; remove o drop-in de calibração antes de trocar para modo de movimento; sucesso exige leitura de `mode=motion`, `phase=control` e igualdade campo a campo de `calibration-status`; distingue erro de calibração `waiting_for_bus` de erro do barramento; divergência de leitura, falha de gravação `.saved.toml` e falha de reinício causam rollback com mensagens separadas para arquivo e modo; recusa se a política estiver rodando ou se `ExecStart` tiver `--commissioning` sem drop-in; mantém dez backups numerados. O Studio testa prontidão nos dois modos, fallback de `calib-read`, consulta de `last-result.json` após timeout, alteração do item 3 quando pending/centered muda, remoção do registro ao desfazer calibração central e saída igual dos dois arquivos TOML de grupo.

## Estado atual (primeira versão)

Disponível:

- **Visão geral:** estado em tempo real, pato 3D, bateria, temperatura da placa e liberação de torque em um toque (também pela barra de espaço).
- **Servos:** busca, calibração de zero individual ou de todos (grava diretamente nos servos), direção, postura, P/D e limite de torque.
- **IMU:** calibração inicial no modo de fábrica (segurar o robô alinhado e incliná-lo para a frente; o controlador valida com `verify-imu`) e calibração fina em pé quando possível. Os botões “ativar postura” e “desativar (liberar torque)” aparecem acima de “calibração em pé”, com indicação de postura atual, relaxada ou em processo de levantar. No modo de movimento, “ativar postura” usa o mesmo comando `pad.op stand` do controle remoto, com nova validação do estado pelo backend. No modo de calibração também é possível ficar em pé, conforme solicitação do usuário de 21/10: envia `imu.op hold` para o comando `hold-home` do fork; os 15 servos giram juntos da posição atual até HOME por 3 s e mantêm torque, enquanto a IMU continua sendo lida. A direção segue a usada no item 3 e o zero vem do arquivo do controlador (2048 de fábrica). No modo de calibração, o Studio consulta `busStatus` a cada 0,1 s; `last_sample.imu` alimenta a leitura em tempo real, a inclinação da área “agora” e a calibração em pé. Também é possível calibrar em pé antes de confirmar a direção, calculando a orientação completa nova que será gravada no item 3. A gravação no controlador fica bloqueada enquanto o robô está em pé, pois reiniciar o controlador faria o robô cair; se estiver relaxado, a calibração em pé orienta ativar a postura primeiro.
- **Acesso remoto por SSH** (página “Mais”, pedido em 21/10 para permitir reparos sem regravar o cartão): a imagem de fábrica aceita somente chaves e não contém chaves de usuários nem senha remota padrão. O usuário configura primeiro a senha da página (sem ela o backend recusa, para impedir que qualquer pessoa conectada ao ponto de acesso habilite SSH) e depois define uma senha SSH própria de 8–64 caracteres, que não seja fácil de adivinhar. `POST /api/ssh {action: on}` chama `ssh-password` no auxiliar: define a senha de radxa com `chpasswd` via stdin, grava `/etc/ssh/sshd_config.d/05-microduck-ssh-password.conf` antes de `10-microduck.conf`, valida com `sshd -t` e `sshd -T` se login por senha está realmente habilitado e só então recarrega o serviço. Se algo falhar, remove o arquivo e reverte. Desativar remove esse arquivo e recarrega o serviço. **A senha só passa pelo stdin do auxiliar; não aparece na linha de comando, nos logs nem nos arquivos de resultado**, conferido nos testes. O cartão mostra o comando `ssh radxa@<endereco-atual>`. Alternativa: cadastrar uma chave pela página usando `studio/sshkeys.py`. Como o Studio já roda como radxa, grava diretamente no próprio `~/.ssh/authorized_keys`, sem o auxiliar. Aceita uma chave pública completa de uma linha (ed25519/rsa/ecdsa/sk-*), verifica que o tipo em base64 corresponde ao prefixo e rejeita opções como `command=` e chaves privadas. Não duplica fingerprints SHA256; a remoção é por fingerprint. Recusa links simbólicos e aplica permissões 700 ao diretório e 600 ao arquivo. Assim como para senha SSH, exige primeiro definir a senha de login da página.
- **Gravar no controlador:** o item 3 da lista inicial grava de uma vez o zero dos servos, a direção e a orientação da IMU na calibração do robotd. A imagem de fábrica usa modo de calibração; após sucesso, o auxiliar remove o drop-in de commissioning e reinicia o controlador em modo de movimento. Não basta o reinício: também exige `mode=motion`, `phase=control` e leitura de volta igual campo a campo de `calibration-status`; caso contrário, restaura arquivos e modo. Após reiniciar o Studio, o resultado anterior é recuperado de `last-result.json` no cartão do item 3.
- **Controle:** pareamento pelo comando oficial `robotctl pad pair`, controle pelo navegador e teste de emergência.
- **Controle remoto:** levantar, iniciar caminhada, sentar, habilidades, ações e sequências.
- **Ajuste de movimento:** somente leitura. **Gerenciamento de modelos:** importar pacote de implantação, renomear, selecionar modelo, restaurar o integrado, configurar teclas de ação e remover modelos importados. Consulte [Importação de modelos](MODEL_IMPORT.md) para o formato.
- **Logs:** página de logs e pacote de diagnóstico; no celular, ambos também ficam acessíveis em “Mais”.
- **Conectar ao Wi-Fi:** quando o robô está em modo de ponto de acesso, o celular pode selecionar a rede doméstica e informar a senha. Depois da troca, a página localiza o novo endereço do robô e redireciona; as configurações também mostram a rede atual e permitem trocar de rede ou esquecer uma salva.
- **Senha de login:** configurar, alterar ou remover em “Mais → Senha de login”. No modo de ponto de acesso sem senha, o cartão de Wi-Fi na visão geral orienta configurá-la primeiro.

Ainda não disponível nesta versão:

- Alterar pela web os parâmetros de movimento (amplitude da caminhada, suavização, P/D e limites de torque).

## Referências

Este projeto se baseia no código aberto oficial do Microduck e considera ideias de vários projetos abertos da comunidade. O código foi escrito pelos autores deste repositório, com auxílio de ferramentas de IA durante o desenvolvimento.

## Licença

Apache-2.0, conforme o restante do repositório. Preact, htm e three.js em `web/vendor/` usam MIT; as licenças estão em `web/vendor/licenses/`. A origem dos modelos 3D está em `web/model/NOTICE.md`. As licenças dos pacotes em `deps/` estão nos respectivos diretórios `dist-info`.
