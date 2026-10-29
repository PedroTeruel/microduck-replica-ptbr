# Plano de correção do acompanhamento musical local

> **Para agentes de trabalho:** sub-habilidade obrigatória: desenvolvimento orientado por subagentes. Execute as tarefas na ordem abaixo; para cada item, primeiro crie uma regressão que falhe, depois implemente e revise.

**Objetivo:** corrigir o problema de a música captada pelo microfone não produzir batidas estáveis para conduzir a cabeça/o corpo, deixar explícitos os estados de espera e movimento real e validar os limites de tomada de controle pelo controle físico.

**Arquitetura:** manter um único microfone, as interfaces atuais robot.head/robot.pose e a política de movimento. Solicitar captura em períodos de 20 ms; detectar o ritmo por envelope de volume finito atualizado conforme as amostras e evidências periódicas; não gerar movimento para entradas instáveis. A Web mantém as proteções existentes de gravação/reprodução; só permite que a música use um controle ocioso quando houver evidências suficientes, sem remover proteções gerais.

**Tecnologias:** biblioteca padrão do Python, ALSA arecord, Studio Python/Preact, RPC Unix existente e dados paralelos do controle.

## Evidências obtidas

Em 26/10/2026, durante a reprodução de música, o usuário fez duas captações de 8 s salvando somente valores numéricos: período padrão de 6000 quadros/125 ms; após solicitar `--period-time=20000 --buffer-time=80000`, período real de 960 quadros/20 ms. Ambas terminaram normalmente. O detector antigo não encontrou snapshots estáveis na música real com período curto; o envelope de volume do mesmo trecho mostrou repetição com atraso de cerca de 0,6 s. Portanto, não se deve localizar batidas apenas por um aumento de 1,65× entre quadros adjacentes. Evidências em artifacts/music-local-fix-20261026/capture-ab.json; o PCM não foi salvo.

## Tarefa 1: eixo temporal da captação e ritmo da música real

Arquivos: `software/duck-echo/continuous_audio.py`, `music_feel.py`, `test_music_feel.py`, `test_alsa_linux.py`; se forem necessários testes adicionais, criar `test_music_timing.py` no mesmo diretório.

- [ ] Criar primeiro uma regressão que falhe: o mesmo PCM fixo, fornecido uniformemente a cada 20 ms ou em blocos de 125 ms, deve produzir BPM semelhantes e um last_beat válido, que não esteja no futuro; as fronteiras dos blocos não podem alterar a linha temporal da energia.
- [ ] Adicionar uma regressão com o envelope numérico da música real (um trecho de período curto de capture-ab); o BPM deve vir de evidências repetidas, não de um valor fixo como 100/120. Preservar os casos existentes de batidas fortes repetidas a 75/125 BPM, balanço, volume constante, silêncio/dados expirados e mudança de velocidade.
- [ ] Solicitar captação com período de 20 ms e buffer de 80 ms; validar que separação de frases, avisos sonoros e cancelamento de voz não regridem. A estimativa periódica em janela finita deve permanecer unknown sem ritmo confiável e liberar a batida antiga quando o som parar.
- [ ] Comandos de teste de referência: `python -X utf8 -m unittest test_music_feel test_music_timing test_continuous_audio`; suíte completa: `python -X utf8 -m unittest discover -p 'test_*.py'`. Executar todos os testes no Linux do dispositivo antes da implantação.
- [ ] Fazer commit do código da tarefa; realizar uma revisão independente da especificação e, depois, uma revisão de qualidade. Corrigir problemas importantes.

## Tarefa 2: cadeia de movimento e estados visíveis

Arquivos: `software/duck-echo/continuous_audio.py`, `music_feel.py`, `test_music_feel.py`, `test_alsa_linux.py`; se forem necessários testes adicionais, criar `test_music_timing.py` no mesmo diretório.

- [ ] Rastrear a autoridade de controle real e o caminho de envio; conferir postura, BPM, sessão de movimento e leitura de retorno de robot.pose. Localizar a causa antes de alterar o código.
- [ ] Exibir claramente o estado “aguardando ritmo estável”, evitando mostrar apenas “movendo-se com a música” sem haver movimento. Validar o retorno da cabeça/pose inactive quando o estado expirar, o som silenciar ou a reprodução parar.
- [ ] Distinguir conexão do controle de entrada ativa; primeiro verificar se o modo ocioso do padd nativo continua escrevendo head/pose. Só permitir execução musical se for possível confirmar que não há disputa de escrita e que o fluxo paralelo está atualizado; qualquer operação real cancela a música atual. Preservar a parada de emergência e as regras atuais de gravação/reprodução. Se não houver evidência do modo, documentar a lacuna do protocolo; não remover a proteção indiscriminadamente só por causa do estado da conexão.
- [ ] Executar os testes Node e do backend do Studio afetado. Se somente o Studio for atualizado, primeiro confirmar que o dispositivo está parado; salvar o estado do usuário e a identidade dos processos.
- [ ] Fazer commit e executar revisões da especificação e da qualidade.

## Tarefa 3: implantação no dispositivo, nova verificação e registro

- [ ] Implantar o componente de voz usando commit e hash fixos; executar os testes Linux no dispositivo, salvar backup para reversão e reiniciar somente o serviço necessário.
- [ ] Ler novamente o período ALSA real, a atualidade do ritmo, BPM e confiança; se necessário, repetir a medição enquanto o usuário estiver tocando música, sem tratar um resultado de microfone simulado como captação real.
- [ ] Validar na Web os estados de espera/movimento/parada e a saída real da cabeça e do corpo. O usuário confirma o movimento físico; a existência de arquivos não substitui a aceitação.
- [ ] Atualizar os itens F24/F25 do inventário de funcionalidades do software e o registro de validação, distinguindo código corrigido, implantação concluída, validação física e itens ainda pendentes.
