# Music Interaction Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development, with specification and code quality reviews before deployment.

**Objetivo:** quando houver música tocando em alto-falantes, o pato se mover suavemente no ritmo e responder com vocalizações conforme a sensação musical após ouvir uma pergunta explícita.

**Arquitetura:** reutilizar o fluxo PCM único de continuous_audio e extrair o ritmo com MusicFeel; usar reconhecimento local de perguntas por streaming, isolado, e processar áudio com exclusão mútua em relação ao reconhecimento comum de sentar/levantar. Um socket Unix privado fornece estado e alternância com limites; o Studio reutiliza a prioridade e o heartbeat da sessão de ações Web para enviar intenções de cabeça/corpo.

**Tecnologias:** biblioteca padrão, modelo Vosk existente, AF_UNIX, Python/JavaScript do Studio.

Correção posterior do usuário: ao ativar a escuta, tocar um grasnado curto; no modo diário, responder por padrão com vocalização nativa do pato, sem repetir literalmente a fala. Manter a repetição de gravações como função explícita e independente echo/record; não implementar um botão separado nesta rodada. Esta correção substitui o projeto de transição anterior, que previa repetir falas comuns.

### 1. Percepção e reconhecimento de perguntas

- [ ] `music_feel.py`/testes: detectar início de som por RMS a cada 20 ms, limitar a janela a 8 s/64 pontos, acompanhar BPM/atualidade da batida e classificar em animada, grave, balanço ou incerta; usar uma lista de perguntas explícitas permitidas. Ritmo rápido/lento não equivale a identificar corretamente o gênero musical. Cobrir separadamente simulações a 75/125 BPM, balanço, ruído constante, silêncio, mudança de velocidade e canal de áudio incorreto.
- [ ] `music_interaction.py`/testes: reutilizar o modelo Vosk e criar uma fila separada e limitada para perguntas reconhecidas por streaming. Responder a perguntas completas e estáveis mesmo com música ambiente tocando; confiança de pelo menos 0,8 para palavras parciais, pergunta completa da lista permitida estável por 0,5 s e intervalo de 4 s contra repetição. O modo música não pode tratar a faixa inteira como repetição comum nem como comando de sentar/levantar. Cada resposta deve suprimir o próprio áudio por ContinuousAudio e usar o ritmo recente confiável anterior à pergunta. Limpar a fila ou perder quadros deve redefinir o reconhecimento; não manter transcrições arbitrárias.

### 2. Serviço local de controle

- [ ] `audio_control.py`/testes: usar `/run/duck-echo/control.sock`, permissões 0600, uma solicitação JSON limitada; os únicos métodos são status e set. Permitir apenas alternar escuta e modo música, sem aceitar comandos arbitrários ao robô. O estado contém somente alternância, ritmo e falhas; não guarda PCM nem texto de conversas. Inicia desligado. As alterações por R3 e pela Web compartilham o mesmo estado active real; desligar/Select/desconexão cancela a sessão. A música pela Web pode ativar o microfone mesmo com o controle físico desligado.
- [ ] Integrar o daemon de modo que a thread principal continue processando o estado sem controle e a reconexão; encerrar corretamente o socket; usar RuntimeDirectory na unidade systemd e incluir todos os módulos no manifesto de instalação. Testar concorrência de alternâncias, entrada excessiva, campos inválidos e ausência de vocalização de uma pergunta antiga após desligar.

### 3. Web e movimento rítmico

- [ ] O cliente local do Studio consulta o estado em segundo plano; o snapshot não pode bloquear o loop de eventos. O endpoint pad.op autenticado fornece os controles de escuta e música.
- [ ] MotionStudio adiciona sessão musical e amostragem do ritmo, reutilizando preparação de movimento, heartbeat, perda de conexão, tomada de controle pelo controle físico e bloqueios de sentar/levantar. Envia somente intenções pequenas de cabeça/corpo; não habilita torque nem inicia a política automaticamente. Se o controle físico estiver conectado, o movimento Web pausa e explica o motivo; quando o usuário desligar o controle físico, pode ativar a escuta musical pela Web. Sem ritmo confiável, aguarda; com áudio/estado expirado, para a saída e limpa o bloqueio retido.
- [ ] Na página existente do controle, exibir ao lado do painel de gravação a alternância “voz/ouvir música”, o estado da escuta, BPM e uma estimativa aproximada da sensação musical. Parada, saída da página e parada de emergência continuam seguindo o fluxo atual.

### 4. Validação e publicação

- [ ] Testes unitários de Python, ALSA simulada no Linux, IPC com robô simulado, validação de frontend/navegador e alternância entre modos de validação com supressão de feedback.
- [ ] Congelar o pacote de componentes, hashes dos arquivos e backup dos arquivos originais do dispositivo; confirmar estado parado e reiniciar somente o serviço necessário. Verificar que os processos robotd/padd permaneceram inalterados, registrar carga/temperatura e as validações humanas ainda pendentes.
- [ ] Atualizar F16/F17 no inventário, criar identificadores para movimento rítmico e perguntas sobre música e especificar os limites entre validação de software e validação humana da reverberação/música real.
