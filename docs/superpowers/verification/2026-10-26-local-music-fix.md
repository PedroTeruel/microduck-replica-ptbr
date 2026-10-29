# Correção da interação musical local e limitações reais

**Data:** 26/10/2026 (horário de Tóquio). Nesta rodada foi implantada uma correção de software, mas o usuário ainda relatou espera pelo ritmo e ausência de movimento da cabeça e do corpo. **A interação com música real ainda não foi validada.**

## Alterações implantadas

- Serviço de voz `2f24a6ae7b5a2b16d2b222eee507aa91b988c9fc`: período ALSA de 20 ms e buffer de 80 ms; eixo temporal do áudio avança conforme as amostras; detecção de ciclos de envelope contínuos; tratamento de interrupções curtas e deriva do relógio; liberação do ritmo antigo quando a música para, mesmo com ruído de fundo.
- Studio `6ca5459c781663d3872cf3a2b4697ee21a05c892`: estados “aguardando o ritmo” e “movimento ativo” aparecem separadamente. Desligar R3/o serviço encerra a sessão musical independente; reativar a escuta não retoma uma sessão antiga. A proteção de primeiro plano/heartbeat e do controle físico foi mantida.
- Backup do serviço de voz: `/var/lib/duck-echo/upgrades/20261026-012132-2f24a6ae7b`; PID 42568 durante a implantação. A comparação posterior de captação reiniciou somente o serviço de voz; 42568 não é mais o PID atual. Backup da Web: `/home/radxa/.microduck-backups/web-audio-20261025-cefb03d009`; PID em execução 43893.
- Antes da atualização Web, o usuário confirmou que o robô estava parado; a leitura de retorno foi standing/homed, `policy_enabled=false`. Nenhum comando de parada adicional foi enviado. Foram atualizados 5 arquivos do Studio; os hashes dos 12 arquivos originais de dados do usuário não mudaram. Os processos robotd 1099/padd 1132 e seus horários de início foram preservados.
- Oito recursos HTTP e verificações de saúde passaram; hashes dos recursos estáticos coincidiram e os arquivos congelados usavam no-cache. A captura real do WebSocket exige login; não houve tentativa de contornar a autenticação.

## Verificações de software e desempenho

- Serviço de voz no Windows: 150 verificações; 133 passaram e 17 foram ignoradas por dependerem de Linux. No pato WSL, passaram todas as 150. A versão final no pato levou 98,600 s.
- Backend do Studio: 257 verificações em Python 3.13 e 11 em Node; 88 verificações relacionadas passaram na revisão independente do backend.
- Fluxo completo local no Edge passou em 88,561 s: primeiro exibe “aguardando”, sem inventar movimento, e depois mostra o ritmo. O registro do robô simulado contém 22 quadros de cabeça e 21 de corpo. Gravação/reprodução de sentar/levantar e verificação de tela estreita foram preservadas. Isso não demonstra o resultado no robô real.
- Duas rodadas de revisão independente corrigiram evidência repetida causada por ataques fracos, timeout ao parar música lenta e acúmulo de desvio temporal em trocas rápidas de modo. Não restaram itens importantes conhecidos na revisão de software.
- Referência numérica offline em ARM (corpo de detecção 7fb0b86): processamento de envelope em 8 s usou cerca de 521,66 ms de CPU; quadro mais lento, 30,05 ms; média de snapshot em cache, cerca de 0,019 ms. Isso não é um teste prolongado de temperatura de toda a cadeia ASR/música.

## Captação real e resultado relatado pelo usuário

- Com o usuário tocando música ao lado, duas captações A/B de 8 s confirmaram o período padrão de 6000 quadros = 125 ms. Após reduzir o período, a configuração real foi 960 quadros = 20 ms. O algoritmo antigo não produziu resultado estável em trechos de música com período curto; o novo extraiu um envelope numérico de cerca de 100 BPM. Foram salvos somente dados numéricos, sem PCM nem gravação de conversas.
- Após a implantação, o usuário informou: “fica esperando o ritmo; a cabeça e o corpo não se mexeram”. O recurso continua sendo tratado como não corrigido. A primeira observação dos motores, de 45 s, ocorreu antes de o usuário começar a operar: escuta/música estavam false e a política, desativada. Portanto, não cobriu a reprodução real do usuário e não valida o movimento.
- Numa leitura posterior de 6 s do serviço real, 60/60 itens eram válidos, com aproximadamente 65,2 BPM e confiança entre 0,667 e 0,815; numa nova leitura, voltou a unknown. O travamento do ritmo com música real continua instável: uma única amostra não comprova funcionamento geral com músicas reais.
- O cliente de áudio foi instalado e lido com sucesso usando o Python 3.13 real do Studio e UID 1000 da Radxa. A mesma rotina MusicRhythm aguarda corretamente quando o estado é unknown. Não se pode atribuir o problema à permissão do socket de controle nem afirmar que a diferença de relógio foi comprovada.

## Nova captação e comparação independente de algoritmos (ainda sem validação)

- A configuração real foi conferida com ALSA `cget`: microfone direito Mic3R ativado, demais entradas PGA desligadas, PGA Capture Switch em on,on, ganho 60,60 (30 dB), AGC desligado. Isso coincide com a captação do canal direito pelo serviço atual. A configuração correta, por si só, não prova que a música reproduzida esteja chegando claramente ao microfone.
- Em duas observações de cerca de 62 s, o estado do serviço não revelou ritmo confiável; após remover DC, o RMS do canal direito ficou aproximadamente entre 207 e 414. Ainda não foi confirmado o teste comparativo “Testar microfone”; portanto, esses dados não podem ser tratados como segmentos de fala ou de uma música específica já confirmados.
- Foi compilado no staging privado o núcleo DSP do aubio 0.4.9; SHA256 do código-fonte original: `d48282ae4dab83b3dc94c16cf011bcb63835c1c02b515490e1883049c3d1f3da`. Nenhum pacote do sistema foi instalado e o algoritmo de produção não foi alterado. Numa comparação de 12 s de áudio real, a saída tempo previu batidas, mas a confiança nativa permaneceu sempre em 0; specflux relatou um início de batida apenas uma vez, na inicialização. Não trate a contagem prevista como evidência confiável de ritmo.
- Na captação acústica de um tom curto, o RMS do canal direito antes/depois foi cerca de 302/294; durante os tons de 700 Hz e 1100 Hz, cerca de 28659/32049, com componentes de frequência correspondentes. O canal esquerdo permaneceu em 0. Isso confirma que o canal direito capta a saída local; houve clipping no último caso, portanto esse volume não deve ser reutilizado em testes. O resultado não substitui comparações com música reproduzida em alto-falante e fala a curta distância.
- Esse teste de tom interrompeu temporariamente o serviço de voz para obter acesso exclusivo à placa de som e, no bloco finally, restaurou os estados anteriores de escuta/música; nenhuma interface de movimento foi chamada. Após restaurar, os PIDs eram voz 53645, Studio 43893, robotd 1099 e padd 1132. O software em execução continuava sendo voz 2f24a6a/Studio 6ca5459.
- Foi iniciado um observador temporário de entrada numérica com prazo automático de 300 s; ele salva somente horário, RMS, BPM, confiança e estados dos controles, sem armazenar fala ou PCM. Ainda é necessária a confirmação sincronizada do usuário ao reproduzir música e falar, para localizar a diferença entre entrada de áudio e detecção.

## Principal descoberta sobre a capacidade corporal do modelo

Com o pato atual em pé e estável, política em execução, torque confirmado, feedback recente das articulações e controle físico desconectado, foram feitas comparações breves, de pequena amplitude e sem caminhada. Não houve comando automático de HOME, habilitação ou troca de modelo. Ao fim de cada sondagem, foram enviados head zero e pose inactive, ambos aceitos.

- Comparação de cabeça/corpo de 6 s a 1 Hz: 300 solicitações foram aceitas; a variação real de yaw da cabeça foi de 0,08897 rad, enquanto as articulações do corpo ficaram praticamente inalteradas.
- Roll estático lento de 0,04 rad durante 6 s: não houve mudança visível na posição do corpo. Adicionar um heartbeat de movimento zero também não ajudou, descartando essa hipótese.
- A assinatura simultânea dos alvos reais mostrou mudanças de apenas cerca de 0,002–0,010 rad nos alvos das articulações do corpo; as posições medidas quase não se moveram. Uma resposta RPC accepted não significa, por si só, que o pato executou a ação.
- Modelo atualmente em uso: `Mjlab-VelStand-Rough-Backlash-MicroDuck`; SHA256 `1cbf8730eadd75a5704332c9f3c10f60bfa9412135b907831c9dbd731ce1795f`. A captura de treinamento exportada integralmente do dispositivo confirma `body_pose_tracking.weight=0.0` e `head_pose_tracking.weight=2.0`; não existe etapa curricular posterior que habilite a recompensa de rastreamento corporal.
- Inferência contrafactual offline do ONNX local com o SHA correspondente: ao alterar roll de 0 para +0,04, as saídas de hip_roll esquerdo/direito mudaram apenas +0,000238/+0,000453 rad; a maior mudança de saída das pernas foi cerca de 0,00765 rad. É uma análise de sensibilidade de um passo, não uma simulação de rollout físico.
- O código nativo fixo 4734cbb mantém z/roll/pitch do corpo nas observações 57–59 e envia os valores ao modelo de caminhada mesmo quando o slot stand está vazio; portanto, a instrução corporal não é descartada por isso. A principal limitação está no objetivo de treinamento do modelo atual; atrito/zona morta podem contribuir, mas ainda não foram quantificados separadamente.

Assim, a hipótese inicial desta rodada — “se a interface aceita, o modelo existente pode produzir movimento corporal ao ritmo” — não se confirmou. Para acompanhar o ritmo com o corpo de forma confiável, é necessário validar separadamente um modelo com capacidade de rastreamento corporal. Não se deve alegar que o problema foi resolvido apenas conectando um modelo grande de voz, ampliando os comandos ou removendo proteções.

## Limites do modelo candidato e da autoridade de controle

O modelo local `firmware/policies/stand/policy.onnx`, restaurado do professor do HD1910 (SHA256 `a481d9f211f31d9476ab1a319fe362a21ef0879d9fa59442a122845af598268c`), possui um currículo de treinamento para rastreamento corporal; hardware, HOME, ordem e dimensões correspondem ao modelo atual, e a resposta offline à entrada corporal é clara. Porém, sua função é teacher_only, `deployment_verified=false`, e o README diz para não colocá-lo automaticamente no slot stand de velocidade zero. Esse slot afeta todas as posturas de baixa velocidade/parada. É apenas candidato para simulação; **não foi ativado nem substituído**.

A coexistência com um controle físico ocioso ainda exige propriedade nativa do canal e protocolo de tomada de controle: o raw tap atual não expõe o modo nativo cabeça/corpo/IMU, e a limpeza ao parar pode competir com a gravação do controle. A proteção foi mantida nesta rodada. A sessão musical Web da versão anterior 6ca5459 terminava ao sair do primeiro plano; depois, o usuário pediu explicitamente continuidade em segundo plano. Isso foi implementado no ciclo de vida independente da 29b9400 e implantado; consulte [Validação da execução em segundo plano](2026-10-26-background-music.md). Detecção sonora e capacidade do modelo corporal continuam sendo validadas separadamente, conforme as evidências desta página.

Próximos passos: primeiro, verificar se há detecção confiável do ritmo e resposta da cabeça/boca com música real; em seguida, avaliar separadamente um modelo corporal conforme a escolha do usuário, em simulação e no robô. Não houve conexão com Doubao/Jev, recriação da imagem nem publicação OTA.

Evidências numéricas e de implantação: diretório raiz de trabalho `artifacts/music-local-fix-20261026/`; verificações finais do Linux do serviço de voz em `artifacts/audio-interaction-20261025/linux-tests-2f24a6ae7b.json`.
