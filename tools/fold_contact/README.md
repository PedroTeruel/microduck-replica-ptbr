# fold_contact · pontos de contato das juntas das pernas

Uma possibilidade para calibrar o zero é usar a postura encolhida como referência mecânica. Porém, se o robô ficar suspenso e for alinhado à mão, um erro de apenas um ou dois graus pode fazê-lo cair. Antes, é preciso saber quais peças limitam cada junta nessa postura e em que ângulo o contato ocorre. Este script calcula esses pontos usando o modelo oficial de simulação.

**Procedimento definido:** use como referência a pose “Oficial dobrada (cabeça e pescoço alinhados)” da bancada [`tools/servo-web`](../servo-web/), disponível desde a versão 0.14.0. Coloque as pernas na pose FOLD oficial e flexione os joelhos até os tornozelos encostarem nos servos das coxas (ponto de contato da segunda linha da tabela). Use um esquadro para deixar o pitch dos quadris na vertical. Deixe quadril yaw/roll, tornozelos, cabeça e pescoço alinhados (0°), com a boca fechada. Calibre as 15 juntas juntas; o zero continua sendo o valor oficial 2048.

```bash
pip install mujoco python-fcl numpy
python fold_contact.py --mjcf <microduck_rl>/src/mjlab_microduck/robot/microduck/robot_walk.xml [--json resultado.json]
```

- O MuJoCo calcula somente a cinemática direta (posição de cada peça). Para determinar o contato, **o FCL calcula a interseção exata das malhas triangulares originais**. O cálculo de colisão próprio do MuJoCo trata as malhas como cascos convexos, que são mais espessos que as peças reais e antecipam o contato.
- Na pose zero, com as pernas estendidas, já existem 20 pares de geometrias sobrepostos por causa da montagem (por exemplo, servos dentro dos suportes e rolamentos dentro dos alojamentos). Esses pares são excluídos da varredura.
- A varredura avança em passos de 0,25°; depois de detectar contato, uma busca binária refina o resultado até 0,05°.

## Resultados · geometria original XL330 (simulação oficial, 2026-09-22, microduck_rl `d424a0c`)

O modelo define a convenção dos ângulos. A tabela abaixo mostra a perna esquerda. Os valores dos joelhos e tornozelos da perna direita têm a mesma magnitude e sinal oposto; o pitch do quadril é assimétrico porque as carcaças esquerda e direita diferem, então os dois lados são apresentados.

| Junta e condição | Ângulo de contato | Superfícies em contato |
|---|---:|---|
| Joelho no sentido de flexão, quadril 0° e tornozelo 0° | **±70,7°** | Pé contra suporte de roll do quadril |
| Joelho no sentido de flexão, quadril ±90° (quadril da pose FOLD oficial) e tornozelo 0° | **±89,6°** | Tornozelo contra servo da coxa |
| Pitch do quadril no sentido de flexão, joelho totalmente flexionado | Esquerda **+126,0°**, direita **−122,9°** | Tornozelo contra carcaça do tronco |
| Tornozelo depois de flexionar totalmente joelho e quadril | Apenas o intervalo de **+0,4° a −19,8°** continua livre | Em uma extremidade, carcaça; na outra, coxa |
| Pitch do pescoço na direção da pose FOLD oficial, pernas flexionadas | **+66,6°** (igual com pitch da cabeça em 0° ou 57°) | Servo superior do pescoço contra carcaça do tronco |

As três poses oficiais são keyframes de `scene.xml`:

| Pose | Há contato entre as peças? |
|---|---|
| STAND (em pé) | Não |
| SIT (sentado) | Não |
| FOLD (dobrada, quadril e joelhos ±90°) | **Sim:** o tornozelo entra em contato com o servo da coxa cerca de 0,36° antes. A pose oficial usa joelho 1,57 rad = 89,95°; o contato ocorre em 89,59°. A pose dobrada da bancada limita o joelho a 88°. |

Na pose FOLD oficial, o pitch do pescoço e da cabeça é 57° (1 rad), mas isso não corresponde ao ponto de contato. O pescoço só encosta em outra peça a **66,6°**; em 57°, há folga dos dois lados, e alinhar a peça apenas visualmente não é preciso. Por isso, ao usar a pose dobrada como referência de calibração na bancada, alinhe a cabeça e o pescoço em 0°.

O alvo do joelho durante a calibração é calculado com o valor oficial de 1,57 rad. A posição física chega ao ponto de contato de 89,59°, deixando uma diferença de cerca de 0,36° (quatro passos) no zero, que pode ser ignorada.

## O que isso significa ao usar a postura encolhida como referência

1. **Os contatos das juntas são determinados pelos pés e tornozelos contra outras peças**, não pelos limites internos das próprias juntas. A posição final de cada uma depende dos ângulos das outras. Por exemplo, o joelho para em 70,7° com o quadril a 0° e em 89,6° com o quadril a 90°.
2. **O tornozelo fica livre na postura encolhida**, com cerca de 20° de movimento restante; não é possível calibrá-lo usando essa postura. Quadril yaw/roll e cabeça também não ficam restringidos.
3. Para calibrar o quadril e os joelhos nessa postura, é preciso **padronizar como ela é montada**: primeiro posicione o quadril no ângulo definido, pressione o tornozelo na direção indicada e então flexione o joelho. Os ângulos de referência só valem para esse procedimento reproduzível.
4. **Esses resultados descrevem a geometria original XL330.** A versão Feetech alterou oito peças de encaixe do horn, o que pode mudar os ângulos de contato. Exporte cada link do conjunto Feetech como STL na pose zero e refaça a análise, ou meça as mesmas poses no SolidWorks.
5. O método mais consistente é usar **um gabarito de calibração**: imprima placas que fixem as juntas entre coxa, perna e pé em ângulos definidos (por exemplo, perna estendida no zero e sola perpendicular). Isso é mais preciso e reproduzível do que flexionar até o contato, e fornece a mesma referência para os lados esquerdo e direito.

A bancada (`tools/servo-web`, desde a versão 0.13.0) pode sobrepor poses oficiais no modelo 3D e listar, para cada junta, a diferença “real − oficial”, ajudando a estimar o erro do zero. Desde a versão 0.15.0, também pode mostrar a pose “dobrada para calibração”: pernas na pose FOLD oficial, com a cabeça e o pescoço alinhados como descrito acima.
