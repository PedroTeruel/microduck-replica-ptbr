# sts3215Servo_testtool — ferramenta Rust de teste para servos STS3215

Projeto de aprendizado/teste que controla servos de barramento Feetech (FEETECH) em Rust por meio de um adaptador USB–TTL. Implementa uma versão mínima própria do protocolo serial STS/SCS. O código está dividido em dois arquivos:

- `src/sts.rs` — biblioteca de protocolo: montagem e checksum de quadros, ping, leitura/gravação de registradores e interpretação de estado (`ServoStatus`).
- `src/main.rs` — ferramenta de linha de comando: varredura, leitura de informações, movimento, teste individual e teste em lote.

## Fiação do hardware

```text
Adaptador USB (por exemplo, Feetech URT-1 / Waveshare Bus Servo Adapter) --TTL--> servo STS3215
O servo precisa de alimentação independente (versão 7,4 V: use 7,4 V; versão 12 V: use 12 V). Não o alimente pela USB!
```

Porta serial padrão: /dev/ttyUSB0. Baud rate padrão: 1.000.000 (valor de fábrica do STS3215).

## Comandos comuns

```bash
source ~/.cargo/env          # carregue o ambiente cargo na primeira utilização
cargo build --release        # compilar
cargo run -- scan                       # varrer os servos do barramento (com barra de progresso)
cargo run -- info 1                     # ler posição/tensão/temperatura/corrente/carga do servo ID=1
cargo run -- read 1 42 2                # ler registradores arbitrários: ID=1, endereço 42, 2 bytes (hexadecimal)
cargo run -- move 1 2048                # mover o servo ID=1 para o ponto central 2048
cargo run -- move 1 3072 --speed 800    # mover na velocidade especificada
cargo run -- test 1                     # teste completo do ID=1: varredura de posição + amostragem de corrente/carga
cargo run -- test-all                   # varrer e testar todos os servos em lote; gerar tabela-resumo
cargo run -- raw 1                      # diagnóstico de baixo nível: imprimir bytes brutos enviados/recebidos
cargo run -- set-id 1 2                 # alterar ID=1 para ID=2 (conecte somente este servo ao barramento!)
cargo run -- --port /dev/ttyUSB1 scan   # especificar a porta serial
cargo run -- --baud 115200 scan         # especificar o baud rate
```

## Exemplos de comandos e resultados reais

Os exemplos abaixo foram medidos em um Raspberry Pi 5, com adaptador oficial Feetech (CH340) e STS3215 de 7,4 V no ID=1.

### scan — varrer o barramento

```bash
$ cargo run -- scan
Varrendo [##############################] 254/254  1 encontrado
  ID   1  online  modelo=777  tensão=7,4 V (faixa 4,0–8,0 V)  proteção térmica=70 °C
Total de servos encontrados: 1.
```

Se a tensão estiver fora da faixa (por exemplo, se conectar 9 V por engano), o comando de movimento acionará o alarme de sobretensão/subtensão e o LED do servo piscará.

### info — ler o estado atual

```bash
$ cargo run -- info 1
Servo ID 1:
  posição   : 2049 / 4095   (180,1°)
  velocidade:    0 passos/s
  carga     :  0,0 %
  tensão    :  7,4 V
  temperatura: 30 °C
  corrente  :    0 mA
  em movimento: não
```

Quando há um alarme, aparece uma linha adicional `⚠ alarme: código de estado 0x01` (bit0 = erro de tensão). Conversão de posição: 4096 passos = 360°.

### move — mover para uma posição especificada

```bash
$ cargo run -- move 1 2048 --speed 1000
Servo 1 → posição-alvo 2048; aguardando...
Posição alcançada: posição atual 2049 (180,1°)
```

- `pos`: posição-alvo de 0 a 4095 (2048 é o ponto central).
- `--speed`: passos por segundo; quanto maior, mais rápido. `--time ms`: duração desejada; 0 significa sem limite.
- Precisão observada: desvio ≤1 passo (aproximadamente 0,09°).

### test — teste completo de um servo

```bash
$ cargo run -- test 1
== Teste do servo ID 1 ==
  modelo=777  tensão=7,4 V  temperatura=30 °C  posição=2049
  alvo 2048 → medido 2049  desvio 1  OK
  alvo 1024 → medido 1025  desvio 1  OK
  alvo 3072 → medido 3072  desvio 0  OK
  alvo 2048 → medido 2049  desvio 1  OK
-- Relatório: servo 1 --
  modelo=777  tensão=7,4 V  temperatura=30 °C
  corrente de pico=84 mA  carga de pico=38,8 %  maior desvio de posição=1
  resultado: ✅ PASS
```

### test-all — teste em lote (vários servos)

Exemplo com vários servos conectados: cada servo gera primeiro seu próprio relatório completo; no final, é exibido o resumo.

```bash
$ cargo run -- test-all
Varrendo [##############################] 254/254  2 encontrados
Servos encontrados: 2: [1, 2]
... (um relatório de teste para cada servo) ...
==== Resumo dos testes em lote ====
ID   modelo   tensão V   temperatura °C  corrente pico mA   carga pico %   desvio posição   resultado
1    777      7,4        30              84                 38,8           1                PASS
2    777      7,4        29              79                 35,2           1                PASS
```

> Nota: o resultado mostrado para o ID=2 é ilustrativo; ao testar, considere as leituras reais do seu servo.

### read — ler registradores arbitrários (para estudar a tabela de memória)

```bash
$ cargo run -- read 1 14 2
Servo 1, dois bytes a partir do endereço 14: 50 28  # tensão máx. 0x50=80→8,0 V; mín. 0x28=40→4,0 V
$ cargo run -- read 1 3 2
Servo 1, dois bytes a partir do endereço 3: 09 03   # modelo = 0x0309 = 777 (little-endian)
```

### raw — diagnóstico de baixo nível (investigar problemas de comunicação)

```bash
$ cargo run -- raw 1
PING:
  enviado:  FF FF 01 02 01 FB
  recebido: FF FF 01 02 01 FB              # resposta normal (error=01 indica alarme de tensão)
READ da região de estado (endereço 56, 15 bytes):
  enviado:  FF FF 01 04 02 38 0F B1
  recebido: FF FF 01 11 01 EB 0F 00 00 ... # dados de estado brutos de 15 bytes
```

Campo “recebido” vazio significa que o servo não respondeu (verifique alimentação/fiação/baud rate). Se os dados recebidos forem idênticos aos enviados e não houver um segundo pacote, o adaptador está devolvendo o eco.

### set-id — alterar o ID do servo

```bash
$ cargo run -- set-id 1 2    # ⚠ conecte somente este servo ao barramento
ID 1 online; preparando a alteração para 2...
✅ ID alterado: 1 → 2 (continua válido após desligar e ligar)
```

## Vários servos: altere os IDs antes de conectá-los juntos ao barramento

Servos novos vêm todos com ID 1. Se vários servos com o mesmo ID forem ligados ao mesmo barramento, **responderão ao mesmo tempo e entrarão em conflito** (a varredura pode mostrar apenas um ou não encontrar nenhum). Procedimento correto:

1. Conecte **somente um servo** ao barramento.
2. Execute `cargo run -- set-id 1 2` para atribuir um novo ID (operação EEPROM: desbloqueia, grava e bloqueia automaticamente; o valor é mantido após desligar).
3. Desligue, conecte o próximo servo e repita, atribuindo IDs 3, 4 etc.
4. Depois de conectá-los todos, `cargo run -- scan` deve encontrar cada servo com um ID distinto.

> ⚠ Se houver vários servos com o mesmo ID durante `set-id`, todos serão alterados **juntos para o mesmo novo ID**.

## Resultados medidos

- Padrões de fábrica: ID=1, baud rate 1M, leitura do modelo 777.
- Use uma fonte adequada à versão: a versão 7,4 V (C001) tem limite superior de tensão em torno de 8,0 V; conectar 9 V dispara **alarme de sobretensão** (LED piscando e código de estado 0x01). A versão de 12 V (C018) usa 12 V.
- Precisão de posição medida: desvio de apenas 1 passo entre alvo e posição real (aproximadamente 0,09°).

## O que os testes (test / test-all) fazem

1. Verificam resposta a ping e leem o modelo.
2. Leem valores de referência: tensão, temperatura e posição.
3. Fazem uma varredura de posição: ponto central 2048 → 1024 → 3072 → 2048, amostrando o movimento a cada 20 ms.
4. Calculam corrente de pico (mA), carga de pico (%) e maior desvio de posição.
5. Classificam PASS/FAIL e indicam tensão anormal, bits de alarme, desvio fora do limite ou aumento excessivo de temperatura.

## Escrever um script de teste próprio

No arquivo `main.rs`, use `test_one()` como referência. API principal:

```rust
let mut bus = StsBus::open("/dev/ttyUSB0", 1_000_000)?;
bus.ping(1)?;                      // verificar se está online
bus.move_to(1, 2048, 1000, 0)?;    // mover: id, posição, velocidade, duração
let s = bus.read_status(1)?;       // ler todo o estado de uma vez
println!("{} V {} mA {} °C", s.voltage, s.current_ma, s.temperature);
bus.set_torque(1, false)?;         // liberar torque (pode ser movido manualmente)
```
