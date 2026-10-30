# Repetição pelo microfone do pato (2026-10-25)

O usuário autorizou escolher a interação, implantar por SSH e validar sem regravar a imagem. Implementação como serviço Python 3 independente, instalado em /opt/duck-echo. Não modifica nem reinicia robotd/padd e não envia comandos de movimento.

## Interação e escopo

Escolhemos manter pressionado R3 (botão do joystick direito; Linux BTN_THUMBR=318) para gravar e soltar para reproduzir. Duração máxima de 10 s; um pressionamento curto demais não gera reprodução. Por padrão, o canal direito capturado é reproduzido a 1,25× da taxa de amostragem, causando uma pequena alteração de tom. O modo de voz original pode ser configurado como 1,0. Ao iniciar uma nova gravação enquanto a anterior toca, interrompe-se a reprodução anterior. Se o controle desconectar ou o serviço parar, o trecho em gravação é descartado.

Também há os comandos probe (gravação limitada e medição do nível), record --seconds 4 (grava por um período definido e reproduz) e devices (lista os controles disponíveis). O áudio fica na memória; não salva conversas nem acessa a nuvem.

Alternativas consideradas: manter o botão pressionado é fácil de controlar e evita gravar o próprio alto-falante; apertar para iniciar e apertar novamente para encerrar facilita esquecer a gravação ligada; detecção automática de fala exigiria gate de ruído e cancelamento de eco adicionais. Esta implementação usa a primeira opção.

## Áudio e entrada

O ALSA captura com arecord -t raw -f S16_LE -c 2 -r 48000; uma thread de leitura coleta no máximo 10 s de áudio. Mic3R é o canal direito escolhido pelo script existente de inicialização da HAT. A reprodução seleciona o canal direito, copia-o para os dois canais e usa aplay. Falhas do processo de captura, placa de som ocupada ou gravação silenciosa devem ser informadas claramente; não se deve declarar sucesso de áudio sem evidência. O PCM bruto e o processo de reprodução têm limites explícitos de tamanho e duração.

Um listener evdev somente lê o controle físico, sem executar EVIOCGRAB e sem tomar posse do padd. Se um botão já estiver pressionado durante a inicialização, é preciso soltá-lo antes do próximo pressionamento aceito. Repetições do evento de tecla não iniciam múltiplas gravações; estouro do buffer de entrada ou desconexão cancela a gravação. Sem controle conectado, o serviço verifica periodicamente se houve conexão a quente.

## Plano de instalação e aceitação

- [x] Primeiro escrever testes de canal PCM, níveis, máquina de estados e eventos evdev; confirmar que falham por falta de implementação.
- [x] Implementar processamento PCM, gravação/reprodução limitadas, máquina de estados de R3, detecção de conexão a quente e interface de comandos.
- [x] Fornecer unidade systemd, preparação do caminho do microfone e scripts de instalação/desinstalação; a desinstalação restaura as configurações de captura anteriores.
- [x] Executar todos os testes unitários e a ajuda dos comandos localmente; verificar sintaxe Python e finais de linha dos scripts.
- [x] Depois de obter conexão SSH, conferir hostname, placa de som, serviço e dispositivo de controle, registrando o estado original.
- [x] Enviar o diretório independente, executar probe do microfone e confirmar nível diferente de zero; fazer gravação/reprodução limitada antes de habilitar o serviço R3.
- [x] Conferir os logs do novo serviço e verificar novamente processos/estado de execução de robotd/padd. A fala real e a audição do acionamento físico precisam ser validadas no hardware; testes offline não substituem essa verificação.

## Diagnóstico inicial da conexão

Na primeira varredura de 2026-10-25, a porta TCP 22 não foi encontrada e a lista Wi-Fi não mostrava o ponto de acesso Microduck. Depois que o usuário confirmou a inicialização, o duck-0de6 foi encontrado em 192.168.0.102. A chave de host foi conferida com o histórico e a conexão foi feita usando os dados de acesso atuais fornecidos pelo usuário. A senha de login não foi gravada nos arquivos do projeto.

## Validação offline e revisão

- Ubuntu 22.04 / Python 3.10: 25 testes aprovados, incluindo reprodução simulada dirigida por subprocessos reais, duração limitada, desconexão, dispositivo de áudio ocupado, dois nomes de controles de microfone, ciclo de vida dos backups e recuperação de falha de atualização.
- systemd-analyze verify foi executado em um arquivo temporário de serviço com permissões 0644; código de saída 0.
- O arquivo microduck/deploy/audio/aic3104-i2c3.dts do projeto escolhe explicitamente o compatible genérico aic3x e o controle Mic3R; a ramificação específica AIC3104 do driver do codec usa Mic2R. A instalação reconhece o nome pela lista real de controles, em vez de tentar adivinhá-lo.
- A revisão encontrou dois defeitos: uma reinstalação com erro reutilizava incorretamente o backup da primeira instalação; uma falha de instalação não restaurava as configurações de captura. Ambos foram reproduzidos com testes que falhavam, corrigidos e validados.
- O texto acima descreve a validação offline; a validação física está abaixo.

## Aceitação em hardware real

- Dispositivo duck-0de6, aarch64, placa de som aic3104 e controle Mic3R disponível.
- Probe do microfone concluído; uma gravação limitada produziu cerca de 2,876 s de áudio válido, RMS 1233,255 e -28,5 dBFS. O processo de reprodução com alteração de tom terminou com código 0.
- /opt/duck-echo instalado; duck-echo.service active/running e enabled; usuário do serviço radxa; sem reinicializações automáticas do serviço.
- O Pro Controller já pareado reconectou com sucesso. O serviço identificou Nintendo Switch Pro Controller em /dev/input/event4 e evento R3 de número 318.
- Os logs registraram várias sessões reais de gravação/reprodução por R3, com trechos de aproximadamente 0,75–2,125 s, todas reproduzidas integralmente. O usuário confirmou ter ouvido o pato repetir a fala.
- Antes e depois da instalação, robotd (PID 1090) e padd (PID 1128) e os respectivos horários de inicialização permaneceram iguais; estado saudável, ciclo de controle de 50 Hz, bus ok e imu ready.
- O serviço foi habilitado para iniciar com o sistema; não reiniciamos o dispositivo para validar. Foram mantidos o tom/velocidade padrão de 1,25× e o limite de gravação de 10 s.
- Evidências no workspace em artifacts/duck-echo-20261025: hardware-preflight.json, hardware-install.json e hardware-service.json. Não contêm senha de acesso nem áudio de conversa.
