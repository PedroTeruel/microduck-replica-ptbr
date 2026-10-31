# Origem dos parâmetros do 1910 M6

O arquivo `1910_m6.json` deste diretório **usa os parâmetros do 1910 BAM M6 publicados pela LuwuDynamics**. Eles não foram identificados nem medidos de forma independente por este projeto. Agradecemos à LuwuDynamics por disponibilizar os dados. Se esses parâmetros forem usados posteriormente para treinar uma política de caminhada, a origem ainda deve ser indicada na documentação dos parâmetros do modelo de servo.

## Origem fixada

- Projeto: [LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)
- Revisão: `326d77a1122870bdefa2c36403937502c958e69c`
- [Arquivo de parâmetros original](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck/params/1910_m6.json)
- [Configuração de treinamento correspondente](https://github.com/LuwuDynamics/xgoduck_rl/blob/326d77a1122870bdefa2c36403937502c958e69c/src/mjlab_microduck/robot/xgoduck_constants.py)
- SHA-256 do arquivo original: `ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`
- Obtido em 2026-09-24; o JSON foi salvo sem alteração dos parâmetros.
- Licença: **Apache-2.0** no repositório upstream; uma cópia está em `LICENSE` neste diretório.

O projeto upstream chama o servo de HLS1910. O campo `actuator: "sts3215"` no JSON seleciona a implementação de controle Feetech no BAM; ele não transforma os parâmetros em um modelo de fábrica do STS3215. O mantenedor do projeto de réplica confirmou que ele usa o mesmo modelo 1910; essa confirmação não significa que tenhamos reproduzido os experimentos de identificação do upstream.

## Uso atual

`Mjlab-Velocity-{Flat,Rough}-MicroDuck-HD1910` usa esses parâmetros e mantém as configurações de treinamento upstream: `kp_fw=5`, `vin_range=(7.4, 8.0)`, `vin_min=7.0`, ganho de queda de tensão sob carga `(0.0, 0.2)` e atraso de comando entre 3 e 6 passos de simulação. A geometria local do Microduck e a convenção das juntas são preservadas.

O valor `max_velocity=100` é uma configuração upstream para aproximar a remoção do limite de velocidade de variação da posição-alvo; **não** afirma que a velocidade sem carga do servo seja 100 rad/s. A velocidade do modelo continua limitada pela alimentação e pela força contraeletromotriz. `q_offset` é um viés de identificação no arquivo de parâmetros; não o copie para a tabela de zeros individuais dos servos reais.

O valor de origem de `command_delay` permanece no JSON. O atraso da fila de comandos do mjlab é controlado pela configuração de lag indicada acima; não some esses valores para declarar um atraso total do hardware real.

Os dados originais de identificação, a tensão de teste e a versão do firmware não foram fornecidos com o registro de consulta dos parâmetros. O treinamento upstream usa P=5, enquanto a execução Arduino mantém temporariamente os ganhos P=6 e D=20. Esses valores não devem ser tratados como uma configuração validada no robô real. Esta documentação não altera nenhum registrador de servo.

## Projetos upstream

- **LuwuDynamics:** parâmetros do 1910 e configuração correspondente ao XgoDuck, sob Apache-2.0.
- **[Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl):** o framework de treinamento local e o código das tarefas usam Apache-2.0; os modelos 3D e as malhas do Microduck preservam a licença upstream CC BY-NC-SA (o README upstream a descreve como BY-SA-NC).
- **[Rhoban / BAM](https://github.com/Rhoban/bam):** modelo de atuadores e framework de identificação, sob Apache-2.0.

`1910_m6.json` é redistribuído sem alterações de LuwuDynamics/xgoduck_rl, na revisão acima, sob Apache-2.0. Não é um modelo identificado de forma independente por este projeto de réplica. As alterações locais de integração são a configuração da tarefa HD1910 e esta documentação; a atribuição original foi preservada.
