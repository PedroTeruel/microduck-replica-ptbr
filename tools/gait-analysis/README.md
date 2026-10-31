# Scripts de análise da marcha (execução no computador)

Esses scripts foram usados na noite de 13/10 até a madrugada de 14/10 para investigar tremores durante a caminhada e raspagem dos pés. Todos são **somente leitura**: leem arquivos de registro e não se conectam ao robô.

O processo para chegar às conclusões está no [registro da placa principal da noite de 13/10](../../docs/HD1910-20261013-夜-掉电-ServoD e 蹭地.md).

**Entrada:** arquivo JSONL de 50 Hz gravado na placa principal pelo [`duck_rec.py`](../radxa/onboard-analysis/duck_rec.py), com ângulos e alvos das juntas, gravidade e giroscópio da IMU, comandos do joystick e estado da política. Copie o arquivo para o computador antes de analisá-lo.

**Dependências:** Python 3.10 ou superior, `numpy` e `scipy`. Scripts que recebem parâmetros `MJCF` também precisam de `mujoco` e do arquivo `src/mjlab_microduck/robot/microduck/scene_backlash.xml`, do repositório oficial `microduck_rl`, para calcular a cinemática direta.

`foot_clear.py`, `toe_decomp.py`, `stance_*.py` e `roll_pitch_coupling.py` analisam **somente os quadros em que a política controla o robô enquanto o joystick pede movimento** (`policy=walk` e velocidade de comando > 0,02 m/s); quadros parado na pose HOME servem para autoverificação. `gait_quality.py` separa automaticamente os períodos em HOME, parado e caminhando. `walk_transfer.py` usa trechos contínuos de `policy=walk` com pelo menos 3 segundos. Se o `robotd` reiniciar durante a gravação, esses scripts encerram o trecho naquele ponto. `home_roll.py` usa períodos contínuos mantendo HOME (`policy=held`, torque ativo) e analisa os últimos 150 quadros de cada período.

| Script | Pergunta respondida | Uso |
|---|---|---|
| `gait_quality.py` | A marcha treme ou oscila? Analisa oscilação dos alvos e proporção acima de 4 Hz, erro e atraso de acompanhamento, RMS e frequência dominante do giroscópio do tronco e frequência dos passos. | `python gait_quality.py registro.jsonl` |
| `walk_transfer.py` | Os servos acompanham os comandos? Compara por junta a razão de amplitude, o atraso e a coerência entre alvo e posição real (espectro cruzado de Welch); permite comparar registros reais e simulados. | `python walk_transfer.py nome=registro.jsonl ...` |
| `foot_clear.py` | Qual é a altura de elevação do pé durante o passo? Depois de corrigir a orientação pela IMU, compara o ponto mais baixo do pé em movimento com o ponto mais baixo do pé de apoio; identifica se, no ponto mais alto, o elemento inferior é a ponta ou o calcanhar; separa a intenção do modelo, o acompanhamento da perna em movimento e a sustentação da perna de apoio. | `python foot_clear.py MJCF nome=registro.jsonl[@início_wall[@fim_wall]] ...` |
| `toe_decomp.py` | No ponto mais alto do passo, a ponta do pé aponta para baixo ou para cima? Separa os efeitos das juntas e da inclinação do tronco. | `python toe_decomp.py MJCF nome=registro.jsonl ...` |
| `stance_pitch.py` | Quanto o tronco se inclina para a frente durante o apoio? Mostra as posições reais do quadril, joelho e tornozelo da perna de apoio e as posições solicitadas pelo modelo. | Mesmo formato acima |
| `stance_height.py` | Qual é a altura do tronco sustentado pela perna de apoio e quanto ele cede em relação ao solicitado pelo modelo? | Mesmo formato acima |
| `home_roll.py` | Qual é a diferença lateral entre as solas na postura HOME, qual junta a causa e que lado fica mais baixo quando o tronco é alinhado? A comparação é com a HOME simulada; leitura e alvo compartilham o mesmo zero, então um erro de zero não aparece. | `python home_roll.py MJCF nome=registro.jsonl ...` |
| `roll_pitch_coupling.py` | Roll e pitch estão acoplados? Acoplamento em todas as frequências sugere que a IMU está girada em torno do eixo vertical; acoplamento somente perto da frequência dos passos sugere movimento real de inclinação do tronco. | `python roll_pitch_coupling.py nome=registro.jsonl ...` |

**Observações:**

- A sintaxe com `@` seleciona um trecho pelos valores `wall` (horário Unix) do registro. Use-a quando uma mesma gravação incluir mudanças de parâmetros.
- `foot_clear.py` e os demais scripts com IMU usam a direção da gravidade para alinhar o tronco. Um erro de 1° no zero da IMU produz uma diferença calculada de aproximadamente 2 mm entre os pés (distância entre eles de cerca de 98 mm). Calibre o zero antes de comparar os lados, seguindo o [procedimento de calibração da IMU](../radxa/onboard-analysis/README.md#imu-校准今晚手动做的流程). A linha de autoverificação em HOME deve ficar dentro de ±1 mm.
- Também é possível fornecer gravações da simulação, desde que usem os mesmos campos, para comparar os resultados.
