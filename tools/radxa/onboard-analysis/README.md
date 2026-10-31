# Scripts de análise no robô

Scripts usados para investigar problemas na primeira inicialização do robô, na noite de 12/10/2026; o serviço de gravação foi atualizado na noite de 13/10. A análise da marcha é executada no computador; consulte [`tools/gait-analysis/`](../../gait-analysis/). Os scripts são **somente leitura**: assinam o estado do robotd e leem logs, sem enviar comandos de controle. A exceção é `webpad_probe.py`, que envia apenas quadros vazios com todos os botões soltos e os eixos no centro.

A investigação passo a passo da causa do “avanço brusco assim que assume o controle” está no [registro de análise no robô da noite de 12/10](../../../docs/HD1910-20261012-夜-IMU校准 e 首次迈步.md).

Os scripts pressupõem R17 do kissqy em execução na placa, socket do robotd em `/run/robotd.sock`, gravações em `/home/duck/r17/rec/` e scripts em `/home/duck/tools/`.

## Primeiro, grave os dados

| Arquivo | Onde executar | Finalidade |
|---|---|---|
| `duck_rec.py` | Placa principal | Assina `robot.subscribe` do robotd e registra a 50 Hz ângulos e alvos das articulações, velocidade articular, IMU, segurança, comandos do joystick e estado da política em JSONL. Uso: `python3 duck_rec.py segundos arquivo-de-saida`. Acrescenta ao arquivo e grava em disco a cada segundo; se o robotd reiniciar, registra `rec_error` e reconecta automaticamente. |
| `duck_health_log.py` | Placa principal | A cada 0,5 s registra `robotctl health --json` em CSV: tensão dos servos, servo mais quente, temperatura e frequência da CPU, Wi-Fi e Bluetooth. |
| `duck-rec.service` | Placa principal | Executa os dois scripts como serviços independentes na inicialização, sem depender do robotd; os nomes dos arquivos incluem o identificador de boot. Instale em `/etc/systemd/system/` e habilite com `systemctl enable --now duck-rec`. |
| `duck_journal.py`, `duck-journal.service` | Placa principal | Copia continuamente os logs de sistema da sessão de boot para o cartão, gravando a cada segundo. Os logs do Armbian ficam em memória e se perdem se houver queda de energia. Ignora o excesso de mensagens da fase de estabilização da IMU na inicialização do robotd. |

Os dois arquivos de serviço usam o usuário `duck` e caminhos `/home/duck/...`, correspondentes ao cartão personalizado deste projeto. A imagem de instalação rápida de kissqy usa o usuário `radxa`; ajuste os caminhos para `/home/radxa/...` antes de instalar.

As gravações ocupam cerca de 3 MB por minuto. O nome segue `run-data-hora-bprimeiros6caracteresDoBoot.jsonl`. Como a placa não tem RTC e o relógio volta ao iniciar, localize os arquivos pelo ID de boot: `cut -c1-6 /proc/sys/kernel/random/boot_id`. Os dados são gravados a cada segundo, então uma queda abrupta pode perder no máximo o último segundo. Os scripts abaixo ignoram linhas inválidas.

## Investigar uma falha

| Arquivo | Pergunta que ajuda a responder |
|---|---|
| `walk_now.py` | Durante o trecho mais recente em que a política assumiu (`policy=walk`), qual era a inclinação do corpo, a velocidade angular, o desvio dos alvos das pernas em relação a HOME, o erro de acompanhamento e os comandos do joystick? |
| `walk_report.py` | Quantas vezes o joystick foi acionado nos últimos N minutos? As pernas alternaram corretamente? Mede amplitude da diferença entre os joelhos e número de trocas e informa se houve queda. |
| `failure_onset.py` | Qual foi a transição entre estabilidade e perda de controle? Examina quadro a quadro inclinação, gravidade, velocidade angular e a primeira articulação a saturar antes/depois de um alvo da perna se desviar mais de 15° de HOME. |
| `imu_consistency.py` | O giroscópio da IMU e a direção da gravidade são coerentes (`dg/dt = −ω×g`)? Uma concordância próxima de 1 sugere eixos e sinais corretos; valor perto de −1 ou melhor concordância com outra combinação de eixos pode indicar montagem invertida. |
| `vel_consistency.py` | Compara, para cada articulação, a derivada do ângulo (velocidade medida) com a velocidade informada pelo robotd; ajuda a conferir sinal e escala. |
| `imu_fault_ctx.py` | O que o robô fazia quando a IMU desconectou (parado, retornando a HOME ou andando) e qual era a tensão? Ajuda a distinguir mau contato, queda de alimentação e temporização do driver. |
| `webpad_probe.py` | Testa na própria placa o caminho do controle web: tempo de inicialização do webpad e se o padd reconhece o controle virtual. |
| `crash_scan.py` | Mostra a linha do tempo de estados, comandos do joystick e últimos quadros de segurança de cada gravação. Com o CSV de health correspondente, também mostra tensão e temperatura antes de uma possível queda completa de alimentação. |
| `judge_block.py` | **Executar no computador.** Avalia a regra de parada usada com fusão do giroscópio BNO085: durante a caminhada ereta, detecta quando a postura percebida pelo modelo salta mais de 5° sem rotação indicada pelo giroscópio. Classifica os eventos de fusão como rígidos, leves ou isentos e compara a fusão ao chip quando parado em HOME. No modo chip, informa também os saltos do canal do chip como linha de base. Usa apenas a biblioteca padrão. Contexto no [registro de 15/10](../../../docs/HD1910-20261015-IMU乱跳根因与陀螺融合上机.md), seção 5.5. |
| `ab_blocks.py` | **Executar no computador.** Compara várias gravações: quedas (bordas de subida de `safety.fallen`; alternâncias dentro de 3 s contam como uma), tempo com joystick acionado, quedas por minuto de comando, saltos do chip e tremor do corpo. Soma as gravações rotuladas como `chip` e `gyro` e calcula razão, intervalo de 95% e valor p. Identifica o modo efetivo da gravação e avisa se o rótulo estiver invertido. |

## Calibração da IMU (procedimento manual)

**Etapa 1: conferir a orientação** (na primeira montagem da IMU ou depois de removê-la e reinstalá-la)

Segure o pato na vertical e incline cerca de 20° para frente, para trás, para a esquerda do próprio pato e para a direita. Mantenha cada inclinação por três segundos e retorne à posição inicial. Depois, execute:

```text
python3 imu_tilt_check.py 120        # Últimos 120 s, uma linha a cada 0,5 s; marca com ← desvios acima de 8° da posição inicial
```

As quatro leituras devem aparecer na ordem: “inclinação para frente +”, “inclinação para trás −”, “inclinação para a direita − (esquerda +)” e “inclinação para a direita +”. A direção de rotação medida pelo giroscópio também deve coincidir. Um sinal invertido indica que os eixos da montagem estão configurados incorretamente.

**Etapa 2: calibrar o zero** (depois de uma queda forte, impacto na IMU ou troca do cabo)

Durante o treinamento do modelo, o pato fica na pose HOME oficial, com os pés apoiados e o corpo nivelado. O keyframe `STAND` do MJCF usa quaternion unitário, isto é, leitura de IMU de 0°. Portanto, com o robô real em HOME, a IMU também deve indicar aproximadamente 0°. A diferença mede a inclinação do módulo; o procedimento abaixo considera os ângulos reais das articulações, mesmo que os joelhos fiquem ligeiramente cedidos.

1. Coloque o pato em piso plano, pressione Start para assumir HOME, retire as mãos e aguarde três segundos parado.
2. Na placa principal, execute `python3 capture_home.py home-capture.json` para capturar a média dos ângulos das articulações e da gravidade nos últimos 100 quadros.
3. Copie o JSON para um computador com MuJoCo e o projeto oficial `microduck_rl`. Execute: `python sim_home_tilt.py <microduck_rl>/src/mjlab_microduck/robot/microduck/scene_backlash.xml home-capture.json`. A saída mostra a inclinação esperada do corpo com os ângulos reais das articulações e o desvio de montagem da IMU (medido menos esperado).
4. Calcule o novo quaternion de montagem: `python imu_mount_fix.py <desvio-de-inclinação-frontal> <desvio-de-inclinação-lateral> <quaternion-atual-w-x-y-z>`.
5. Depois de **liberar o torque**, faça backup de `/etc/robot/feetech-ft5/hd1910-calibration.toml`, substitua `"quat"` sob `[["imu_mounts"."bno08x"]]` pelo novo valor e execute `sudo systemctl restart robotd`.
6. Coloque o robô em HOME novamente e repita as etapas 2–3. O desvio deve ficar abaixo de 1°.

Na primeira unidade, em 12/10/2026, duas posturas indicaram inclinação frontal de 8,2°/8,9° e lateral à direita de 1,7°/1,8°. Depois de compensar 8,54°/1,78°, a medição de retorno foi −0,55°/−0,47°. O quaternion gravado foi `[0.454164155, 0.544101455, 0.527409117, 0.468538313]`; ele veio de um ajuste de mínimos quadrados em dois conjuntos de dados e diferiu menos de 0,01° do valor calculado por `imu_mount_fix.py 8.54 1.78`.

O próximo passo é transformar este procedimento em uma ferramenta manual com botões. Ela não deve alterar a configuração automaticamente e deve registrar cada calibração em log. Consulte “Próximas etapas” no [registro de análise no robô](../../../docs/HD1910-20261012-夜-IMU校准 e 首次迈步.md).
