# Histórico de alterações

Este arquivo registra as mudanças importantes da ferramenta de teste de servos HD1910M.

## [0.2.0] - 03/10/2026

Autor: 漂移菌

Objetivo principal: **adicionar recursos de calibração de zero e limitação da faixa ativa equivalentes ao software de depuração Feetech FD** e concluir a validação no Microduck real, com 15 servos HD-1910 e firmware 3.46.

### Novos recursos

#### 1. Calibração de zero `zero` (instrução de calibração de posição 0x0B) — recurso principal

Equivale aos botões “Definir zero/calibração de posição” do software Feetech FD: define a leitura desejada para a posição mecânica atual do servo (padrão: ponto médio 2048). O servo calcula e altera automaticamente o registrador de deslocamento de posição 31.

> Por que não usar o método antigo: HD-1910 com firmware HLS versão 3.43 ou superior **não aceita** a calibração de zero escrevendo 128 no controle de torque (responde “sucesso”, mas o registrador de deslocamento não muda). A instrução 0x0B é o único método correto para este modelo.

Uso durante a montagem, servo por servo:

```bash
feetech-HD1910M-tester torque off      # 1. Libere o eixo
# 2. Posicione manualmente a articulação no zero mecânico e mantenha-a ali; não espere, pois a gravidade pode deslocá-la
feetech-HD1910M-tester zero            # 3. Calibre: posição atual -> 2048; grava automaticamente em memória não volátil
feetech-HD1910M-tester torque on       # 4. Reative o torque
feetech-HD1910M-tester zero --to 1024  # Também aceita qualquer leitura de destino (0~4095)
```

Fluxo interno do comando: lê a posição antes da calibração → desbloqueia EPROM → envia 0x0B → bloqueia novamente → aguarda → **confirma por duas leituras: posição atual e deslocamento de posição** (diferença superior a 4 unidades gera erro). Como a Feetech pode responder “sucesso” a operações não suportadas, o resultado da leitura é que determina o sucesso.

#### 2. Comando de reinicialização `reboot` (0x08)

Equivale a desligar e ligar: SRAM é carregada novamente da EPROM. Serve para **verificar sem cortar fisicamente a alimentação** se uma gravação na EPROM foi persistida; o processo de troca de servo do robotd também usa essa instrução.

```bash
feetech-HD1910M-tester reboot          # Após reiniciar, aguarde cerca de 1 s antes de comunicar
```

Uma forma de confirmar a recarga da EPROM: grave um valor de teste em SRAM, como `torque-limit 300`, execute `reboot` e leia o valor novamente. Se ele voltar ao padrão da EPROM (1000), a reinicialização ocorreu; a leitura dos itens de EPROM mostra os valores persistidos.

#### 3. Novas instruções na camada de protocolo

`Instruction::Reboot = 0x08`, `Instruction::ResetTurns = 0x0A` (zera o contador de voltas múltiplas) e `Instruction::Calibrate = 0x0B`, com testes unitários de montagem dos pacotes.

### Melhorias

#### Limites da faixa ativa `limits` (ângulos mínimo/máximo nos endereços 9/11)

- Adicionada a opção `--deg` para informar ângulos, por exemplo `limits 90 270 --deg --save` (0–360° corresponde a 0–4095).
- Adicionada validação cruzada: rejeita `min >= max`; o caso `0 0` no modo multivoltas é aceito explicitamente (antes era rejeitado incorretamente pelo limite inferior nominal do ângulo máximo).
- `--save` agora desbloqueia e bloqueia uma vez para gravar os dois registradores, reduzindo pela metade as operações na EPROM; qualquer falha garante novo bloqueio.
- Após gravar, lê de volta e exibe os valores em graus.

```bash
feetech-HD1910M-tester limits 1024 3072 --save   # Valores brutos: ponto médio ±90°
feetech-HD1910M-tester limits 90 270 --deg       # Graus: altera apenas a RAM, para depuração
```

### Correções

- `set --defer` ignorava a validação de faixa antes da gravação assíncrona, permitindo transmitir valores fora dos limites. Agora todos os caminhos (`write_reg`, `sync_write` e `set --defer`) usam `Register::check_value()`.

### Melhorias internas

- `Register::check_value()`: unificou em um só local a validação de faixa antes repetida em três trechos.
- `ServoError::Malformed` agora carrega `String` para informar erros dinâmicos.
- Simplificados ramos redundantes do comando `pid`.
- Adicionados testes unitários para montagem do pacote 0x0B e limites de `check_value()`; os oito testes passaram.

### Validação no robô real (Microduck, 15 HD-1910, firmware 3.46)

- **Calibração 0x0B medida:** posição 2958 (+80°) → exatamente 2048 após calibrar; o registrador de deslocamento gravou automaticamente 910 (= 2958−2048). A leitura confirmou a semântica do deslocamento: “valor retornado = valor original − deslocamento”. O valor permaneceu após desligar a alimentação.
- **Reinicialização 0x08 confirmada**; a pendência “aguarda teste de bancada” na documentação do projeto pode ser removida.
- **Validação dos 15 servos:** IDs 10–14/20–24/30–34; firmware 3.46; ordem de bytes 0; baud 1M; nível de resposta 1; modo 4; faixa de tensão 4,0–10,0 V; condição de descarga 13 (tensão, superaquecimento e sobrecorrente) — todos aprovados. Diferença entre leitura das articulações e a meta da postura em pé: no máximo 4 unidades.

---

## [0.1.0] - versão inicial

- Implementação completa do protocolo FT-SCS: PING / READ / WRITE / REG WRITE / ACTION / SYNC WRITE / restauração de fábrica.
- Comandos `dump`, `get` e `set` para todos os registradores da tabela HLS_2 oficial (aceitam nome, endereço decimal ou hexadecimal).
- Varredura do barramento com `scan` e monitoramento em tempo real com `monitor` (posição, velocidade, carga, tensão, temperatura e corrente).
- Controle de movimento `goto` / `angle` / `swing`; torque e controle de força com `torque` / `torque-limit` / `goal-current`.
- Ajuste de PID em três malhas (`pid`), parâmetros de proteção (`protect`) e configuração de ID/baud (`set-id` / `set-baud`).
- Mecanismo de bloqueio de EPROM (`lock` / `--save`): desbloquear → gravar → bloquear, para preservar a vida útil da EPROM.
