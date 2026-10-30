# Voz local e reprodução de música no pato

Na versão atual, o padrão é clicar no botão R3 do controle para começar a escutar; o pato emite um grasnado curto. Fale depois de soltar o botão e clique novamente para parar, quando ele emite um som baixo. O controle web usa os mesmos avisos, somente quando o estado realmente muda. Select, desconexão e encerramento do serviço cancelam o modo silenciosamente.

O padrão de ECHO_REPLY_MODE é duck: com o controle por voz ativo, executa comandos explícitos para sentar ou levantar; no modo de música, responde a perguntas claras sobre a música. Falas comuns ou não reconhecidas não recebem resposta. O sistema não repete a voz do usuário nem oferece conversa livre. Ao desativar, cancela o reconhecimento pendente, para a gravação e a repetição e, em seguida, reproduz o aviso de desligamento.

Os avisos sonoros usam a duração do arquivo WAV da biblioteca instalada, mais 100 ms de margem de inicialização e 350 ms de cauda; a captura fica pausada nesse intervalo. Depois do aviso, há uma breve pausa antes de falar. A cada inicialização do serviço, a escuta e o modo de música começam desligados.

A reprodução da gravação continua disponível pelo comando separado record; ainda não está associada ao novo botão. Para solicitar explicitamente o comportamento antigo de repetição, defina ECHO_REPLY_MODE=echo ou passe --reply-mode echo. Nesse modo, o tom e a velocidade padrão aumentam para 1,25×; definir 1,0 restaura a voz original.

O painel web de voz e música desta rodada foi instalado na placa por SSH e os problemas de reconhecimento de frases foram corrigidos após nova verificação por uma pessoa. O áudio de música no alto-falante e os efeitos dos movimentos ainda precisam de aceitação humana; testes de software não substituem essas duas verificações. Consulte [a validação desta rodada](../../docs/superpowers/verification/2026-10-25-audio-interaction.md). A aceitação histórica da primeira versão refere-se ao modo antigo, em que era necessário manter o botão pressionado para falar.

Este é um serviço independente, instalado por SSH. Usa a interface existente do programa principal para sentar e levantar; não reinstala nem reinicia robotd ou padd. Apenas acompanha o controle físico e não toma posse exclusiva do dispositivo de entrada. O áudio fica na memória; gravações de conversa não são armazenadas em arquivos.

**Aceitação histórica da primeira versão:** implantada por SSH em 2026-10-25 no duck-0de6 (192.168.0.102) e configurada para iniciar com o sistema. Captura pelo microfone real, reprodução com alteração de voz e acionamento de R3 no controle físico (pressionar e soltar) funcionaram. Os 45 testes de software passaram. Depois, o usuário confirmou que os comandos de voz reais “levantar” e “sentar” funcionaram.

O controle físico usado foi um Nintendo Switch Pro Controller; dispositivo de entrada /dev/input/event4. Antes e depois da instalação, os PIDs de robotd (1090) e padd (1128) e o horário de inicialização não mudaram; o ciclo de controle permaneceu em 50 Hz. O serviço foi habilitado sem reiniciar todo o sistema. Depois que o controle foi pareado e reconectado após a inicialização, o serviço detectou sua presença automaticamente.

Hardware compatível: Linux de 64 bits, HAT TLV320AIC3104, saída de alto-falante já funcional e controle físico compatível com BTN_THUMBR. A captura usa o canal direito Mic3R configurado pelo script de inicialização do projeto. O R3 de um controle web simulado não é compatível.

## Música e perguntas explícitas (instalado na placa; som e movimento ainda aguardam aceitação)

O painel web pode controlar separadamente a escuta e o modo de música. Ativar a música também ativa o microfone; desligar a escuta desativa ambos. R3 e a leitura do painel web refletem o mesmo estado real da escuta. Com o controle físico desligado, ainda é possível iniciar a captura pela web; desconexão real do controle, Select, estouro de entrada e saída do serviço cancelam a entrada atual.

O modo de música reutiliza o mesmo fluxo do microfone. Estima ritmo e sensação geral usando energia de curto prazo e evidências de repetição do envelope. “Animada”, “suave” e “balançada” são apenas respostas sobre o ritmo, não identificação precisa de gênero ou emoção. A música não é enviada ao reconhecedor de repetição comum nem ao reconhecedor de comandos para sentar/levantar.

Quando a pessoa faz uma pergunta explícita, como “o que você acha?” ou “gosta dessa música?”, um reconhecedor local separado, em fluxo contínuo, reutiliza o modelo Vosk existente. Conforme o ritmo recente e confiável, seleciona os sons nativos chirp, coo ou greet; sem ritmo confiável, usa inquire. A confiança de cada palavra da pergunta completa precisa ser de pelo menos 0,8. Um trecho parcial estável, mantido por 0,5 s, pode receber resposta enquanto a música continua; o intervalo mínimo entre respostas é de 4 s. A captura da própria voz é suprimida durante o aviso e sua cauda.

A captura contínua solicita períodos de 20 ms e buffer de 80 ms. O tempo do ritmo avança conforme as amostras, evitando distorções causadas por lotes de áudio entregues de uma só vez. A estimativa de repetição mantém apenas um envelope numérico limitado, calcula no máximo cinco vezes por segundo e reutiliza dados em cache na consulta de estado. Música suave pode exigir vários segundos de evidências repetidas; sem repetição clara, quando o som para ou a captura fica desatualizada, nenhum ritmo é informado. Uma leitura estável ainda representa somente uma estimativa do período do envelope de volume: acentos, andamento dobrado ou ritmos mistos podem ser ambíguos. Se as evidências forem conflitantes, prevalece a evidência mais forte; não há garantia de identificar um único ritmo.

Somente no modo toggle é criado o socket privado /run/duck-echo/control.sock (diretório com permissões 0700 e socket com 0600). Cada conexão aceita uma linha JSON UTF-8, com até 8192 bytes, e somente os métodos {"method":"status"} ou {"method":"set","listening":true,"music":true}; os campos booleanos devem ser true/false JSON. A resposta informa estado da escuta, música, ritmo e falhas breves; não fornece áudio gravado, transcrição ou comandos arbitrários para o robô. O serviço reinicia com tudo desligado. O modo hold mantém o comportamento antigo, de falar enquanto mantém o botão pressionado, e não oferece controle web de música pelo socket.

O reconhecimento local para perguntas sobre música precisa do modelo já instalado. Se o modelo não estiver pronto, o estado informa uma falha de reconhecimento musical; gravação/reprodução separada e modo echo explícito continuam disponíveis. Testes de software com ALSA falso e sockets UNIX não equivalem à validação de música no alto-falante real, reverberação ou reconhecimento de perguntas.

## Modo de comandos por voz

No modo de voz local, comandos curtos e claros como “sentar”, “senta aí”, “levantar” e “fique em pé” acionam a ação correspondente. Falas comuns não são reproduzidas por padrão. Frases como “não sente”, várias ações misturadas na mesma frase e reconhecimentos de baixa confiança não acionam movimentos. Select, desconexão do controle ou estouro de entrada cancelam comandos antigos ainda não executados e desligam a escuta contínua.

Na CPU do pato foram executados 14 testes com vozes sintéticas: comandos afirmativos, negações, citações, ações misturadas e fala comum. O reconhecimento levou aproximadamente 0,26–0,51 s e o pico de memória foi cerca de 144 MB. Foi usada uma lista pequena de palavras, incluindo fala desconhecida e negações, para evitar os 6–7 s de latência de uma transcrição completa. Em seguida, o usuário testou com microfone real e R3 e confirmou que levantar e sentar funcionaram.

Após a aceitação, houve um período em que SSH e web ficaram inacessíveis. A conectividade foi recuperada por configuração via Bluetooth; o pato foi fixado à rede TP-LINK_5G_6494 (5240 MHz), a conexão automática às outras redes salvas foi desativada e a economia de energia Wi-Fi foi desligada. Vinte acessos web consecutivos funcionaram. Em testes Bluetooth de aproximadamente 160 s com voz desligada e 180 s com voz ligada, não houve desconexões; o intervalo máximo entre dados do controle ficou abaixo de 49 ms. Durante a sessão, foram concluídos repetição de voz real, sentar e levantar, com dois registros de ação accepted=true. O usuário confirmou que repetição e joystick funcionaram; em outra ocasião, a luz piscou, mas a ação também funcionou e o registro não mostrou desconexão correspondente. Já houve desconexões reais antes, cuja causa ainda não foi determinada. Um teste curto não comprova que o problema intermitente de longa duração foi eliminado. Consulte docs/network-20261025.md e os artefatos locais artifacts/duck-network-20261025/final-verification.json.

Usa Vosk small-cn-0.22, com o modelo e as dependências locais em /opt/duck-echo; o áudio não é enviado para a internet. A gravação completa não é salva em arquivo. Os logs registram somente categoria do comando, confiança e resposta da ação; não registram o texto de conversa comum. Antes de cada movimento, o serviço consulta o estado atual de sentado/em pé. Repetir “sentar” não faz o pato levantar. Se o programa principal rejeitar uma solicitação de postura, o serviço não tenta contornar essa rejeição. Após sentar e liberar o torque, a recuperação continua sujeita aos requisitos existentes do firmware.

O modo de clique único processa uma frase após uma pausa na fala, com duração máxima de 10 s; resultados de reconhecimento com mais de 6 s não são executados. A captura fica suprimida durante a repetição da própria voz e os avisos de ação, e retoma após a cauda do som. A segmentação automática comum funciona melhor em ambiente silencioso; com música tocando continuamente, ative o modo de música.

Para restaurar o comportamento antigo de manter o botão pressionado, defina ECHO_TRIGGER_MODE=hold em /etc/default/duck-echo e reinicie somente o serviço duck-echo. No modo hold, a frase ainda é processada ao soltar o R3; se o modo de voz gravar por 10 s, essa frase é cancelada.

§BT§§BT§§BT§bash
# Atualize primeiro os arquivos de execução; depois instale as dependências e o modelo local de reconhecimento.
# Para uma instalação offline, podem ser fornecidos wheels ARM64/cp313.
sudo python3 /home/radxa/duck-echo/install.py
sudo python3 /opt/duck-echo/install_speech.py --mode actions \
  --archive /home/radxa/duck-echo/vosk-model-small-cn-0.22.zip \
  --wheels /home/radxa/duck-echo/arm64-wheels

# Observar o reconhecimento sem executar ações:
sudo python3 /opt/duck-echo/install_speech.py --mode shadow

# Desativar o reconhecimento de comandos (configure ECHO_REPLY_MODE=echo separadamente para habilitar repetição):
sudo python3 /opt/duck-echo/install_speech.py --mode off
§BT§§BT§§BT§

Fontes: [modelos oficiais do Vosk](https://alphacephei.com/vosk/models), [suporte de instalação ARM64](https://alphacephei.com/vosk/install).

## Instalação por SSH na placa

Envie esta pasta para /home/radxa/duck-echo no pato. Na placa, execute:

§BT§§BT§§BT§bash
cd /home/radxa/duck-echo
arecord -l
python3 duck_echo.py devices
sudo python3 install.py prepare-mic
python3 duck_echo.py probe --seconds 3
python3 duck_echo.py record --seconds 4
sudo python3 install.py
journalctl -u duck-echo -n 30 --no-pager
§BT§§BT§§BT§

Durante os 3 s de probe, fale perto do microfone; a saída inclui peak, rms e dbfs. Silêncio, amostra curta ou falha de captura resultam no código de saída 2. O comando record grava por 4 s e depois reproduz. A saída playback_ok: true só aparece se o processo de reprodução terminar com sucesso. Mesmo assim, é necessário ouvir para confirmar a qualidade real e o volume do alto-falante.

A instalação requer sudo; o serviço roda como usuário radxa, incluído nos grupos suplementares audio/input. Dependências: Python 3 do sistema, alsa-utils e systemd; não é necessário baixar pacotes Python.

## Voz original e configurações do dispositivo

§BT§§BT§§BT§bash
sudo nano /etc/default/duck-echo
# ECHO_PITCH=1.0 mantém a voz original; 1.25 deixa a voz mais aguda e rápida.
# ECHO_CHANNEL=1 seleciona o canal direito Mic3R; use 0 somente se o hardware realmente estiver ligado à entrada esquerda.
sudo systemctl restart duck-echo
§BT§§BT§§BT§

Somente o serviço de repetição será reiniciado. Se o nome da placa de som for diferente, ajuste ECHO_CAPTURE/ECHO_PLAYBACK. A configuração do microfone deste instalador foi feita especificamente para aic3104; outras placas de som exigem confirmação do caminho de captura correspondente ao hardware.

## Diagnóstico e reversão

- Sem controle, o serviço aguarda; após a conexão, encontra automaticamente um dispositivo evdev com suporte a R3. Se o R3 já estiver pressionado durante a inicialização, solte e tente novamente. Quando há vários controles, usa o primeiro. O log informa o nome do dispositivo e o caminho event reais.
- Sem áudio gravado: confira arecord -l, nível de sinal em probe e soldagem/fiação do Mic3R. O hardware desta unidade ainda não foi validado; não atribua o silêncio ao software ou à soldagem sem testar.
- Se a reprodução indicar Device busy, solte o gatilho de áudio existente e tente novamente. Os efeitos nativos e a repetição podem disputar a saída de áudio; esta versão informa o erro e não interrompe robotd nem altera globalmente a configuração ALSA.
- A alteração de tom também muda a velocidade da fala. Esta versão reconhece comandos curtos para sentar e levantar após o acionamento; não tem palavra de ativação contínua, conversa livre nem alteração de voz com velocidade preservada.

§BT§§BT§§BT§bash
sudo systemctl stop duck-echo
sudo python3 /opt/duck-echo/install.py uninstall
§BT§§BT§§BT§

A desinstalação para o serviço de repetição e restaura a configuração de captura do microfone anterior à instalação. O programa e os backups permanecem em /opt/duck-echo e /var/lib/duck-echo; o instalador não altera o volume do alto-falante. Se a instalação ou atualização falhar, o script tenta restaurar os arquivos, as configurações de captura e o estado anterior do serviço de repetição. Se a restauração também falhar, o erro é informado explicitamente.

## Validação offline

§BT§§BT§§BT§bash
python3 -m unittest discover -v
python3 duck_echo.py --help
§BT§§BT§§BT§

Os testes de integração Linux usam programas falsos temporários de arecord/aplay/amixer e executam processos-filho reais. Cobrem gravação/reprodução, limite de duração, desconexão, dispositivo de áudio ocupado e restauração das configurações do microfone. Não representam aceitação de áudio em hardware real.
'''
p.write_text(s.replace('§BT§',chr(96)))
PY
git diff --check
rg -n '[\p{Han}]' software/duck-echo/README.md | head -30