# Ações por voz com R3 (2026-10-25)

O usuário escolheu manter o botão do controle pressionado enquanto fala e executar a ação ao soltá-lo, atualizando pelo fluxo SSH existente. A repetição atual do R3 foi preservada: quando reconhece explicitamente “sentar” ou “levantar”, executa a ação correspondente; as demais falas continuam sendo repetidas.

## Projeto

- Usar localmente o modelo em chinês Vosk small-cn-0.22 (cerca de 42 MB na página oficial), sem enviar gravações. O modelo fica carregado em uma thread de reconhecimento em segundo plano; uma gravação limitada só é processada depois de soltar R3.
- Usar um vocabulário pequeno, preservando fala desconhecida, negações e citações. A transcrição completa leva 6–7 s na placa; o vocabulário pequeno levou cerca de 0,26–0,51 s em 14 frases sintéticas na mesma placa.
- Lista permitida: somente “sentar”, “levantar” e poucas variantes explícitas. Remover espaços e pontuação do resultado completo e exigir correspondência exata. “Não sente”, “sente e depois levante” e resultados de baixa confiança não acionam movimento; não usar correspondência aproximada.
- Fala comum, o prefixo explícito “repete” e gravações sem comando reconhecido seguem para a repetição. Cancelar comandos antigos ainda não executados quando começar outra gravação, o controle desconectar ou o serviço sair. Resultados de reconhecimento com mais de 6 s não são executados. Se a gravação atingir o limite de 10 s, cancelar a frase sem executá-la automaticamente.
- Antes de cada ação, ler robot.policies e robot.busStatus. Se já estiver sentado, repetir “sentar” não envia uma alternância; se já estiver em pé, repetir “levantar” também não alterna. Para levantar de um estado de repouso, usar robot.init; para levantar de sentado enquanto a política está normal, usar sit_toggle.
- Para sentar a partir do estado em pé e sustentado: confirmar HOME e torque, zerar a velocidade, ativar a política por robot.enable, aguardar a leitura de retorno e então solicitar sit_toggle. Se o programa principal rejeitar qualquer etapa, parar. Não alterar firmware, configuração de movimento, calibração nem proteções de segurança.
- Se estiver sentado e o torque já tiver sido liberado, não forçar inicialização nem contornar as regras de postura do programa principal. Verificar separadamente o recibo da ação e o estado desejado sentado/em pé.
- Modificar somente /opt/duck-echo e seu serviço. É possível desligar o modo de voz e retornar à repetição simples. Instalar modelo e dependências isoladamente; não reiniciar serviços de movimento.

## Arquivos e sequência de validação

1. voice_commands.py: análise dos comandos, JSON-RPC limitado e ações de postura. Primeiro escrever testes para negação, baixa confiança, idempotência sentado/em pé e rejeição de estado desconhecido.
2. speech_control.py: reconhecimento Vosk, fila limitada, cancelamento e expiração. Verificar o reconhecimento com o modelo real e fala sintetizada do sistema; usar testes unitários para confirmar que resultados atrasados não executam ações.
3. duck_echo.py: conectar o processador somente quando a voz estiver habilitada; preservar o comportamento original quando estiver desligada; cobrir fallback para frases comuns, cancelamento por timeout e por desconexão.
4. Script de instalação e serviço: instalar os dois módulos, isolar dependências e caminho do modelo, reservar memória para o modo de voz e atualizar pelo mecanismo de rollback existente.
5. Depois de concluir testes Linux, teste com modelo real e validação da configuração do serviço, instalar na placa. Conferir CPU/memória, estado da ação somente leitura e carregamento do modelo; primeiro observar o reconhecimento, depois validar sentar e levantar com comandos reais pelo R3. Confirmar que os processos de movimento originais não reiniciaram.

## Fontes

- https://alphacephei.com/vosk/models
- https://alphacephei.com/vosk/install
- https://github.com/alphacep/vosk-api/blob/master/python/example/test_simple.py
- Lógica de sentado/em pé em studio/pad_drive.py e RPC NDJSON em studio/rpc.py deste projeto.

## Validação e implantação concluídas

- Os 45 testes de software passaram (processos ALSA simulados reais no Linux, máquina de estados, comandos, cancelamento concorrente, rollback da instalação e extração offline das dependências).
- O modelo real foi validado no Windows e na placa ARM64 com frases afirmativas, negativas, citações e fala comum. Na placa, as 14 frases sintéticas produziram as ações esperadas ou foram rejeitadas; pico de memória de 144 MB.
- O Python 3.13 da placa não tinha pip. Foram usados wheels ARM64/cp313 distribuídos pelo PyPI oficial, extraídos offline em /opt/duck-echo/asr-deps, sem modificar os pacotes Python do sistema.
- O modelo foi instalado em /opt/duck-echo/models; ECHO_VOICE_MODE=actions está habilitado, o serviço está ativo, a thread de voz está pronta e o consumo residente é de aproximadamente 123 MB.
- Os PIDs dos serviços de movimento robotd (1090) e padd (1128), bem como os respectivos horários de inicialização, não mudaram; ciclo de controle em torno de 50 Hz.
- O estado inicial era sem HOME, torque desligado e sitting=false. Dizer “levantar” primeiro usava robot.init nativo; depois de levantar normalmente, foi possível testar “sentar”.
- A revisão descobriu a estrutura real robot.policies slots[] e um problema de cancelamento em caso de estouro de entrada; ambos foram reproduzidos primeiro com testes que falhavam e depois corrigidos.
- O usuário confirmou explicitamente “levantar e sentar funcionaram”; a validação de voz real com R3 e as ações de postura foi concluída. Essa conclusão se baseia no relato do usuário.
- Depois da validação, a verificação SSH expirou. A varredura pela interface cabeada não encontrou o host SSH, então não foram obtidos novos logs correspondentes a essas ações humanas. Os logs de reconhecimento e implantação anteriores foram preservados; a instabilidade de rede ainda não foi descartada. A investigação da rede não alterou o comportamento de voz ou movimento.
