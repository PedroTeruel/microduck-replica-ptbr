# Ferramenta de servos HD1910M — tutorial prático de Rust

> Leia este tutorial junto com o código-fonte. O objetivo é aprender conceitos centrais de Rust por meio de um projeto que controla hardware de verdade e, ao mesmo tempo, entender o protocolo serial FT-SCS da Feetech.
>
> **Hardware:** servo HD1910M (6 V, 12 kg·cm, codificador magnético de 360°, serial TTL half-duplex, com controle de força).
> **Software:** Rust 1.98 ou superior, Raspberry Pi e adaptador USB-serial CH340.

---

## Índice

1. [Conexão do hardware](#1-conexão-do-hardware)
2. [Primeiros passos em cinco minutos](#2-primeiros-passos-em-cinco-minutos)
3. [Detalhes do protocolo de comunicação FT-SCS](#3-detalhes-do-protocolo-de-comunicação-ft-scs)
4. [Mapa de memória](#4-mapa-de-memória)
5. [Estrutura e camadas do projeto](#5-estrutura-e-camadas-do-projeto)
6. [Conceitos de Rust em detalhe](#6-conceitos-de-rust-em-detalhe)
7. [Referência completa dos comandos](#7-referência-completa-dos-comandos)
8. [Experimentos práticos](#8-experimentos-práticos)
9. [Cuidados de segurança](#9-cuidados-de-segurança)
10. [Solução de problemas](#10-solução-de-problemas)

---

## 1. Conexão do hardware

O cabo do servo usa um conector AMP 2.0 de três pinos:

| Pino | Cor do fio | Função | Conexão |
|---|---|---|---|
| 1 | Preto | Sinal serial TTL | TX e RX do CH340 unidos (half-duplex; detalhes abaixo) |
| 2 | Preto | Vcc (4–8,4 V; normalmente 6 V/7,4 V) | **Positivo de uma fonte externa**; não alimente pela USB |
| 3 | Preto | GND | Negativo da fonte externa; **deve compartilhar o terra com o CH340** |

Pontos importantes:

- **Half-duplex:** o servo tem um único fio de sinal para enviar e receber. O CH340 é full-duplex, com TX e RX separados. Uma ligação simples une TX e RX do CH340 e conecta ambos ao fio de sinal do servo. Nesse arranjo, os dados enviados retornam como eco; execute a ferramenta com `--echo` para descartá-los. A opção mais adequada é usar um adaptador half-duplex oficial da Feetech, como URT-1; nesse caso, não use `--echo`.
- **Terra comum:** GND do servo, da fonte e do CH340 precisam estar conectados entre si; sem isso, a comunicação pode ficar instável.
- **Alimentação:** a corrente de bloqueio pode chegar a 1,6 A a 6 V. Uma porta USB não fornece corrente suficiente; use uma fonte separada.
- No Raspberry Pi, o CH340 geralmente aparece como `/dev/ttyUSB0`, que é a porta padrão da ferramenta.

---

## 2. Primeiros passos em cinco minutos

```bash
# Compilar (na primeira vez, baixa as dependências e compila para target/debug/)
cargo build

# Nas próximas execuções, cargo run recompila e executa; argumentos após -- vão para o programa
cargo run -- scan

# Também é possível executar diretamente o binário compilado
./target/debug/feetech-HD1910M-tester scan

# 1. Procurar servos no barramento, com barra de progresso
./target/debug/feetech-HD1910M-tester scan

# 2. Ler todo o mapa de memória
./target/debug/feetech-HD1910M-tester dump

# 3. Monitorar posição/velocidade/tensão/temperatura/corrente (Ctrl+C encerra)
./target/debug/feetech-HD1910M-tester monitor

# 4. Ir para 90° (1024 ≈ 90°; o centro corresponde a 2048)
./target/debug/feetech-HD1910M-tester goto 1024

# 5. Consultar todos os comandos e a ajuda de um subcomando
./target/debug/feetech-HD1910M-tester --help
./target/debug/feetech-HD1910M-tester pid --help
```

Opções globais (podem aparecer antes ou depois do subcomando):

```text
-p / --port      Caminho da porta serial; padrão /dev/ttyUSB0
-b / --baud      Baud rate; padrão 1000000
-i / --id        ID do servo; padrão 1
-t / --timeout   Timeout em ms; padrão 50 (em varreduras, 20 pode acelerar)
-v / --verbose   Exibe os pacotes brutos enviados e recebidos; útil para aprender o protocolo
    --echo       Descartar eco quando TX e RX estiverem unidos
```

---

## 3. Detalhes do protocolo de comunicação FT-SCS

Código correspondente: `src/protocol.rs`.

A configuração serial de fábrica do servo é **1 Mbps, 8 bits de dados, sem paridade e 1 bit de parada** (seção 7-2 da especificação). O protocolo segue o padrão mestre-escravo de pergunta e resposta: o mestre (Raspberry Pi) envia um pacote de instrução e o servo responde.

### 3.1 Pacote enviado pelo mestre

```text
 Byte:    0     1     2      3         4          5..N+4    N+5
 Campo:  0xFF  0xFF   ID   Length  Instruction   parâmetros Checksum
```

- **Cabeçalho** `0xFF 0xFF`: dois bytes fixos que marcam o início do quadro.
- **ID:** endereço do servo, de 0 a 253. `0xFE` é broadcast: todos os servos executam, mas nenhum responde.
- **Length** = quantidade de parâmetros N + 2 (1 byte de instrução + 1 byte de checksum).
- **Checksum** = byte inferior de `~(ID + Length + Instruction + todos os parâmetros)`. O receptor recalcula e descarta o pacote se o valor não coincidir.

### 3.2 Pacote de resposta do servo

O formato é quase igual ao pacote enviado, mas o quarto byte contém o **estado de erro** em vez da instrução:

```text
0xFF  0xFF   ID   Length   Error   parâmetros...   Checksum
```

Error igual a zero indica sucesso. Valores diferentes de zero são interpretados bit a bit: BIT0 tensão, BIT1 codificador magnético, BIT2 temperatura e BIT3 corrente.

### 3.3 Conjunto de instruções

| Instrução | Valor | Finalidade |
|---|---:|---|
| PING | 0x01 | Handshake; verificar se o servo está online |
| READ | 0x02 | Ler o mapa de memória; parâmetros `[endereço inicial, quantidade de bytes]` |
| WRITE | 0x03 | Gravar no mapa de memória; parâmetros `[endereço inicial, dados...]`; efeito imediato |
| REG WRITE | 0x04 | Gravação assíncrona: armazena a instrução sem executá-la ainda |
| ACTION | 0x05 | Executar as gravações assíncronas armazenadas; permite sincronizar vários servos |
| RESET | 0x06 | Restaurar as configurações de fábrica |
| SYNC WRITE | 0x83 | Gravar o mesmo endereço em vários servos com um único pacote |

### 3.4 Exemplo real

Com `-v`, é possível observar os pacotes enviados e recebidos. Exemplo: `goto 911 --speed 500`.

```text
>> Enviado:  [FF, FF, 01, 05, 03, 2E, F4, 01, D3]   # WRITE: endereço 46 (velocidade) = 0x01F4 = 500
<< Recebido: [FF, FF, 01, 02, 00, FC]               # Resposta: Error=0, sem erro
>> Enviado:  [FF, FF, 01, 04, 03, 28, 01, CE]       # WRITE: endereço 40 (torque) = 1
>> Enviado:  [FF, FF, 01, 05, 03, 2A, 8F, 03, 3A]   # WRITE: endereço 42 (posição alvo) = 0x038F = 911
```

Confira o checksum manualmente: `0x01+0x05 = 0x06`; `+0x03 = 0x09`; `+0x2E = 0x37`; `+0xF4 = 0x12B`; `+0x01 = 0x12C`. Mantendo somente o byte inferior, temos `0x2C`; o complemento bit a bit é `!0x2C = 0xD3`, igual ao último byte do pacote.

> **Exercício:** veja os testes unitários no fim de `src/protocol.rs` (`cargo test`). Eles incluem uma comparação completa do pacote PING. Tente calcular o checksum à mão.

---

## 4. Mapa de memória

Código correspondente: `src/registers.rs`.

O mapa de memória é a tabela de parâmetros interna do servo; cada endereço armazena um parâmetro. **Valores de dois bytes usam little-endian, com o byte menos significativo primeiro.**

### 4.1 Cinco regiões

| Endereços | Região | Acesso | Conteúdo |
|---|---|---|---|
| 0–4 | Informações de versão | Somente leitura | Firmware/modelo do servo e indicador de ordem de bytes |
| 5–39 | Configuração EPROM | Leitura e gravação | ID, baud, PID e proteções; **persistem sem alimentação** |
| 40–55 | Controle SRAM | Leitura e gravação | Torque, posição/velocidade/corrente alvo; efeito imediato, perdido ao desligar |
| 56–75 | Feedback SRAM | Somente leitura | Posição, velocidade, carga, tensão, temperatura e corrente atuais |
| 77–86 | Parâmetros de fábrica | Somente leitura | Valores de calibração de fábrica; não altere |

### 4.2 Sinalizador de bloqueio (endereço 55): persistência da EPROM

Este mecanismo é uma fonte comum de problemas:

- Bloqueio = **1** (padrão de fábrica): gravações na região EPROM, endereços 5–39, alteram somente a cópia em memória; **os valores originais retornam após desligar**.
- Bloqueio = **0**: gravações na região EPROM são persistidas e **continuam após desligar**.

Portanto, o procedimento padrão para persistir uma configuração é **desbloquear → gravar → bloquear novamente**. `set <registrador> <valor> --save`, `set-id` e `set-baud` fazem isso automaticamente (veja `save_reg` em `src/servo.rs`).

> Não mantenha o bloqueio desativado: a EPROM tem vida útil de gravação limitada (cerca de 100 mil ciclos). Bloqueá-la novamente evita que um bug provoque gravações repetidas e danifique o servo.

### 4.3 Codificação sinal-magnitude: números negativos não usam complemento de dois

No protocolo Feetech, valores com direção (posição, velocidade, corrente, carga e deslocamento de posição) **não** usam o complemento de dois habitual. Usam sinal mais magnitude:

- Na maioria dos valores, **BIT15 é o sinal** e os 15 bits inferiores são a magnitude. Por exemplo, `-100` é codificado como `0x8000 | 100 = 0x8064`.
- A carga atual (endereço 60) é uma exceção: **BIT10 é o sinal** e os 10 bits inferiores são a magnitude.

Interpretar `0x8064` como complemento de dois produz -32668, em vez de -100, e está errado. `decode_value`/`encode_value` em `src/registers.rs` tratam essa codificação; o campo `sign_bit` de cada registrador identifica o bit usado como sinal.

### 4.4 Modos de operação (endereço 33)

| Valor | Modo | Descrição |
|---:|---|---|
| 0 | Servo de posição | Malha fechada de posição com limite de corrente alvo (controle de força disponível) |
| 1 | Motor de velocidade constante | Malha fechada de velocidade; a velocidade não cai quando a carga aumenta; usado em rodas |
| 2 | Motor de corrente constante | Malha fechada de corrente, com torque constante |
| 3 | Controle de velocidade PWM em malha aberta | Ajusta a tensão pelo ciclo de trabalho, sem malha fechada; a velocidade varia com a carga |
| 4 | Modo PD de posição pura | Malha fechada proporcional-derivativa; modo padrão de fábrica deste projeto para Sim2Real |

### 4.5 Dois conjuntos de parâmetros PID

O mapa de memória contém dois conjuntos de parâmetros:

- **Configuração EPROM:** P/D/I da posição nos endereços 21/22/23, P/I da velocidade em 37/39 e P/I da corrente em 34/35. São os valores padrão copiados para a região de operação ao ligar.
- **Região de operação SRAM:** Kp/Kd/Ki nos endereços 50/51/52. São os valores realmente usados durante a operação; uma alteração tem efeito imediato e se perde ao desligar.

Para ajustar corretamente, experimente primeiro na região de operação, por exemplo `pid position --kp 40 --ram`. Quando estiver satisfeito, use `pid position --kp 40 --save` para persistir na EPROM.

**A função dos endereços 50/51/52 depende do modo:** em servo de posição, representam PID de posição; no modo de velocidade constante (modo 1), passam a representar PI de velocidade e Kd não é usado.

### 4.6 Registradores de proteção

- Endereço 13: limite máximo de temperatura (80 °C por padrão; torque é desligado ao exceder).
- Endereços 14/15: tensão máxima/mínima de entrada, em unidades de 0,1 V.
- Endereço 28: limite de corrente de proteção, em unidades de 6,5 mA; endereço 38: duração da proteção contra sobrecorrente, em unidades de 10 ms. Se a corrente exceder o limite durante esse período, a proteção é ativada. Um novo comando de posição pode limpar o estado.
- Endereços 19/20: condições de descarga e de alerta do LED, codificadas em máscara de bits. BIT0 (1)=tensão, BIT1 (2)=codificador magnético, BIT2 (4)=superaquecimento, BIT3 (8)=sobrecorrente; valor 1 habilita a condição. Por exemplo, tensão mais superaquecimento corresponde a `1+4=5`.

---

## 5. Estrutura e camadas do projeto

```text
FT-HD1901M_Servo/
├── Cargo.toml          # Manifesto: nome do pacote, versão e dependências
├── src/
│   ├── main.rs         # Camada 4: definição e despacho da CLI (clap)
│   ├── servo.rs        # Camada 3: driver serial (abertura, comunicação, timeout)
│   ├── protocol.rs     # Camada 2: montagem e análise de pacotes (dados puros, sem hardware)
│   ├── registers.rs    # Camada 2: mapa de memória (dados puros, sem hardware)
│   └── error.rs        # Tipo de erro unificado usado em todas as camadas
└── TUTORIAL.md         # Este manual
```

**Por que separar em camadas:** as duas camadas inferiores (`protocol` e `registers`) fazem apenas conversões de dados e não acessam a porta serial. Por isso, seus testes unitários (`cargo test`) podem ser executados sem hardware. Se todo o código estivesse junto, testar o protocolo exigiria conectar um servo real. Essa separação é chamada de “separação de responsabilidades”.

As dependências seguem uma única direção: `main.rs → servo.rs → protocol.rs / registers.rs`; todas as camadas usam `error.rs`. Uma camada inferior nunca depende de uma camada superior.

---

## 6. Conceitos de Rust em detalhe

Os conceitos aparecem na ordem em que são encontrados no código. Cada seção indica os arquivos correspondentes.

### 6.1 Cargo e sistema de módulos — `Cargo.toml`, início de `src/main.rs`

- `Cargo.toml` declara as dependências. Durante a compilação, elas são baixadas do crates.io e suas versões são fixadas em `Cargo.lock`.
- `mod error;` declara um módulo; `use crate::error::Result;` importa um nome desse módulo.
- `crate::` significa “a partir da raiz do projeto”, como um caminho absoluto.

### 6.2 Tratamento de erros: `Result` e `?` — `src/error.rs`

Rust não usa exceções. Funções que podem falhar retornam `Result<T, E>`:

```rust
// Forma explícita
let port = match serialport::new(path, baud).open() {
    Ok(p) => p,
    Err(e) => return Err(ServoError::Serial(e)),
};

// Forma equivalente, usando o operador ?
let port = serialport::new(path, baud).open()?;
```

`?` significa: **se ocorrer um erro, converta-o e retorne imediatamente; se der certo, extraia o valor e continue**. O atributo `#[from]`, fornecido por thiserror, converte automaticamente `serialport::Error` no tipo `ServoError` do projeto; por isso, basta usar `?`.

**Por que criar uma enumeração de erro própria?** A camada superior recebe um único tipo de erro e pode distinguir os casos com `match`: timeout (talvez não exista servo nesse ID, algo normal durante uma busca) e erro de checksum (possível problema na conexão). Veja `ping()` em `servo.rs`.

### 6.3 Enumerações: um dos recursos centrais de Rust — `src/error.rs`, `src/protocol.rs`

```rust
pub enum ServoError {
    Timeout,                        // sem dados associados
    Checksum,
    Malformed(&'static str),        // contém uma string
    ServoStatus(u8, String),        // contém dois valores
}
```

Cada variante pode conter tipos e quantidades diferentes de dados. Com a verificação de **exaustividade** de `match`, o compilador detecta uma variante não tratada e torna refatorações mais seguras:

```rust
match self.transact(id, Instruction::Ping, &[], true) {
    Ok(_) => Ok(true),
    Err(ServoError::Timeout) => Ok(false),  // timeout = ID não encontrado; não é falha da varredura
    Err(e) => Err(e),                        // propaga os demais erros
}
```

### 6.4 `Option`: sem ponteiros nulos — `find_register` em `src/registers.rs`

Uma busca que pode não encontrar resultado retorna `Option<&Register>` (`Some(x)` ou `None`), não um ponteiro nulo. O chamador precisa tratar explicitamente `None`, e o compilador exige isso:

```rust
let reg = find_register(name).ok_or_else(|| {
    ServoError::InvalidParam(format!("Registrador desconhecido: \"{name}\""))
})?;  // transforma None em Err e retorna
```

Argumentos opcionais da CLI, como `goto --speed`, também usam `Option<i64>`: `Some(valor)` quando informado e `None` quando ausente; podem ser tratados com `if let Some(s) = speed { ... }`.

### 6.5 Ownership e empréstimo: exclusividade da porta serial garantida pela linguagem — `src/servo.rs`

Regras centrais de Rust:

1. Cada valor tem exatamente um **proprietário** (`owner`); quando ele sai do escopo, o valor é liberado automaticamente.
2. Pode haver vários empréstimos imutáveis (`&T`) ou um único empréstimo mutável (`&mut T`), nunca os dois tipos ao mesmo tempo.
3. Um empréstimo não pode durar mais que o proprietário.

A estrutura `Servo` é proprietária do handle serial e todos os métodos de operação exigem `&mut self`. Assim, o compilador garante que somente um trecho do código possa usar a porta serial por vez. **Erros comuns em C, como várias threads intercalarem pacotes na porta, são rejeitados pelo compilador Rust.**

### 6.6 Estruturas e `impl` — `src/servo.rs`

```rust
pub struct Servo {          // dados
    port: Box<dyn SerialPort>,
    discard_echo: bool,     // campo privado; não pode ser alterado diretamente de fora
    verbose: bool,
}

impl Servo {                // comportamento (métodos)
    pub fn connect(...) -> Result<Self> { ... }  // função associada, semelhante a construtor/método estático
    pub fn ping(&mut self, id: u8) -> Result<bool> { ... }  // &mut self permite alterar o próprio objeto
}
```

Os três tipos de receptor — `&self` (empréstimo somente leitura), `&mut self` (empréstimo mutável) e `self` (consome a propriedade) — deixam explícito na assinatura se o método pode alterar o objeto.

### 6.7 Traits e objetos trait — `Box<dyn SerialPort>`

Um trait é semelhante a uma interface de Java ou Go. A biblioteca `serialport` usa tipos diferentes para portas seriais em Linux, Windows e macOS, mas todos implementam o trait `SerialPort`. `Box<dyn SerialPort>` representa um valor alocado no heap que implementa esse trait; o restante do código usa apenas os métodos definidos pelo trait. Isso permite suportar várias plataformas sem depender de um tipo concreto.

### 6.8 Iteradores e closures — usados em vários pontos

```rust
// protocol.rs: soma acumulada; a closure |acc, &b| ... recebe o contexto
let sum = bytes.iter().fold(0u8, |acc, &b| acc.wrapping_add(b));

// main.rs: map + collect transforma Vec<u8> em Vec<String>, depois join
let list: Vec<String> = found.iter().map(|id| id.to_string()).collect();

// main.rs: converte uma lista de IDs separada por vírgulas em Vec<u8>
let ids: Result<Vec<u8>, _> = ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
```

Iteradores são uma **abstração sem custo adicional**: após a compilação, equivalem a um loop `for` escrito manualmente.

### 6.9 Macros `derive` e clap — `src/main.rs`

```rust
#[derive(Parser)]                    // clap implementa a análise de argumentos automaticamente
struct Cli {
    /// Este comentário aparece automaticamente na ajuda --help!
    #[arg(short, long, default_value_t = 1)]
    id: u8,
}
```

`#[derive(...)]` é uma macro derivada que gera código durante a compilação. Neste projeto, `Debug` gera formatação de depuração; `Clone/Copy` implementa cópia; `Error` implementa o trait de erro via thiserror; `Parser/Subcommand/ValueEnum` são fornecidos por clap.

### 6.10 Testes unitários — `#[cfg(test)] mod tests` no fim dos arquivos

```rust
#[cfg(test)]           // compilado somente em cargo test; ausente na versão publicada
mod tests {
    use super::*;      // super indica o módulo pai
    #[test]
    fn test_build_ping_packet() {
        assert_eq!(build_packet(1, Instruction::Ping, &[]),
                   vec![0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB]);
    }
}
```

Execute `cargo test`. Testes das camadas puras de lógica (protocolo e mapa de memória) não precisam de hardware.

### 6.11 Referência rápida de recursos comuns

| Construção | Significado | Arquivo |
|---|---|---|
| `wrapping_add` | Soma com retorno ao início em caso de overflow; checksum usa módulo 256 | protocol.rs |
| `u16::from_le_bytes([a, b])` | Combina dois bytes little-endian em um u16 | servo.rs |
| `to_le_bytes()` | Divide u16 em bytes little-endian | servo.rs |
| `Vec::with_capacity(n)` | Reserva capacidade para evitar realocações repetidas | protocol.rs |
| `{value}` em `format!` / `println!` | Interpolação de strings do Rust 2021 | vários |
| `.expect("...")` | Extrai um valor quando a falha é considerada impossível; em erro, gera panic com mensagem | servo.rs |
| `matches!(x, Err(...))` | Verifica se um valor corresponde a um padrão | testes de protocol.rs |
| `&[u8]` vs `Vec<u8>` | Empréstimo de slice vs vetor que possui seus dados | assinaturas de funções |

---

## 7. Referência completa dos comandos

> Por padrão, as gravações **alteram apenas a memória e são perdidas ao desligar**. Para persistir um registrador EPROM, acrescente `--save`; o comando desbloqueia, grava e bloqueia novamente. Isso ajuda a preservar a vida útil da EPROM.

### Consultas

```bash
feetech-HD1910M-tester scan                          # Procura IDs de 0 a 253, com barra de progresso
feetech-HD1910M-tester scan --from 1 --to 10         # Restringe a busca
feetech-HD1910M-tester dump                          # Exibe o mapa inteiro, dividido em 5 regiões e com unidades
feetech-HD1910M-tester get pos-p                     # Lê um registrador pelo nome em inglês
feetech-HD1910M-tester get 21                        # Também aceita endereço decimal
feetech-HD1910M-tester get 0x15                      # Ou endereço hexadecimal
feetech-HD1910M-tester get status                    # Decodifica automaticamente os bits de estado
feetech-HD1910M-tester monitor                       # Monitoramento em tempo real (Ctrl+C encerra)
feetech-HD1910M-tester monitor --interval 50 --count 100
```

### Gravação genérica (qualquer registrador gravável do mapa)

```bash
feetech-HD1910M-tester set <registrador> <valor>             # Grava na memória; efeito imediato, perdido ao desligar
feetech-HD1910M-tester set <registrador> <valor> --save      # Grava na EPROM e persiste sem alimentação
feetech-HD1910M-tester set <registrador> <valor> --defer     # Gravação assíncrona; deixa o comando em cache
feetech-HD1910M-tester action                                # Broadcast para executar as gravações em cache
feetech-HD1910M-tester swrite 1,2,3 goal-pos 2048            # Grava o mesmo registrador em vários servos
```

Exemplos: `set deadband-cw 3`, `set integral-limit 10 --save`, `set min-start-force 20`.

### ID, baud, bloqueio e restauração de fábrica

```bash
feetech-HD1910M-tester set-id 2              # Altera o ID atual para 2; salva automaticamente; conecte com -i 2 depois
feetech-HD1910M-tester set-baud 4            # Índice de baud 0–7; aqui define 115200; salva e passa a valer após reiniciar
feetech-HD1910M-tester lock on               # Bloqueia: gravações EPROM não persistem; padrão de fábrica
feetech-HD1910M-tester lock off              # Desbloqueia: gravações EPROM persistem
feetech-HD1910M-tester factory-reset         # Restaura a fábrica; use com cuidado: ID volta a 1 e baud a 1M
```

### Controle de movimento

```bash
feetech-HD1910M-tester mode 0                        # Modo servo de posição (0–4; consulte a seção 4.4)
feetech-HD1910M-tester goto 2048                     # Vai ao centro; ativa o torque automaticamente
feetech-HD1910M-tester goto 1024 --speed 500 --acc 50
feetech-HD1910M-tester torque on / off / damp        # Ativa, libera o eixo ou aplica amortecimento para ensino manual
feetech-HD1910M-tester speed 1000                    # Velocidade; em modo constante, BIT15 indica a direção
```

### Torque e controle de força

```bash
feetech-HD1910M-tester torque-limit 500               # Limite de torque de 50% (0–1000 equivale a 0–100%)
feetech-HD1910M-tester goal-current 100                # Corrente alvo de cerca de 650 mA (unidade de 6,5 mA)
feetech-HD1910M-tester set max-torque 800 --save       # Torque máximo de 80%; EPROM copia para o endereço 48 ao ligar
feetech-HD1910M-tester set protect-current 300 --save  # Corrente de proteção de cerca de 1,95 A; EPROM
feetech-HD1910M-tester set min-start-force 20 --save   # Força mínima de partida de 2%
```

### Ajuste de PID (três malhas)

```bash
feetech-HD1910M-tester pid position --kp 40 --kd 8             # Malha de posição; atualiza a configuração EPROM e vale nesta sessão
feetech-HD1910M-tester pid position --kp 40 --kd 8 --ram       # Grava na região ativa; efeito imediato, recomendado para ajuste
feetech-HD1910M-tester pid position --kp 40 --kd 8 --save      # Persiste na EPROM após concluir o ajuste
feetech-HD1910M-tester pid velocity --kp 60 --ki 20            # Malha de velocidade, usada no modo de velocidade constante
feetech-HD1910M-tester pid current --kp 200 --ki 50            # Malha de corrente, central no controle de força
```

### Proteções e limites

```bash
feetech-HD1910M-tester protect --max-temp 80                          # Limite de temperatura: 80 °C
feetech-HD1910M-tester protect --min-voltage 40 --max-voltage 100     # Faixa de tensão: 4,0–10,0 V
feetech-HD1910M-tester protect --overcur-time 200                     # Protege após 2 s de sobrecorrente
feetech-HD1910M-tester protect --unload 12 --led 12                   # Libera torque e pisca em caso de superaquecimento/sobrecorrente
feetech-HD1910M-tester limits 0 4095 --save                           # Limita ângulo; no modo multivoltas use 0 0
feetech-HD1910M-tester limits 90 270 --deg --save                     # Também aceita ângulos de 0 a 360°
feetech-HD1910M-tester offset -100 --save                             # Deslocamento de posição para ajuste manual do zero
feetech-HD1910M-tester zero                                           # Calibra a posição atual como centro 2048
feetech-HD1910M-tester zero --to 1024                                 # Usa outra leitura alvo e confirma pela leitura de retorno
```

---

## 8. Experimentos práticos

Siga a ordem e observe os resultados de cada experimento. Recomenda-se usar `-v` para ver os pacotes.

### Experimento 1: handshake e observação do protocolo

```bash
feetech-HD1910M-tester -v get pos
```

Observe o pacote enviado `FF FF 01 04 02 38 02 ...`: `02` é READ, `38` é o endereço inicial 56 e o último `02` solicita dois bytes. A resposta contém a posição atual em little-endian. Confira o checksum manualmente.

### Experimento 2: leitura do mapa de memória

```bash
feetech-HD1910M-tester dump
feetech-HD1910M-tester get mode        # Consulta o modo atual; padrão de fábrica = 4, PD de posição pura
feetech-HD1910M-tester get status      # Decodifica os bits de estado
```

### Experimento 3: torque e demonstração manual

```bash
feetech-HD1910M-tester torque off      # Libere o eixo e gire o servo à mão
feetech-HD1910M-tester monitor         # Em outro terminal, veja a posição mudar e a carga ficar perto de zero
feetech-HD1910M-tester torque damp     # Modo amortecido: gire à mão e sinta a resistência
feetech-HD1910M-tester torque on       # Reative o torque
```

### Experimento 3.5: calibração do zero mecânico para o centro

Após montar o mecanismo, o zero mecânico pode não coincidir com o centro 2048 do servo. Use a calibração de zero, equivalente a “definir zero” no software Feetech FD:

```bash
feetech-HD1910M-tester torque off      # 1. Libere o eixo
# 2. Posicione a articulação no zero desejado; não espere, pois a gravidade pode deslocá-la
feetech-HD1910M-tester zero            # 3. Calibre imediatamente a posição atual como 2048 e persista
feetech-HD1910M-tester torque on       # 4. Reative o torque; a leitura atual já será 2048 e não haverá salto
```

O comando confirma o resultado lendo a posição atual e o deslocamento do endereço 31. **HD-1910 com firmware HLS não aceita o método antigo de calibrar escrevendo 128 no controle de torque**: pode responder sucesso sem aplicar a alteração. Use a instrução de calibração 0x0B do comando `zero`. Não calibre no modo multivoltas.

### Experimento 4: movimento de posição e feedback

```bash
feetech-HD1910M-tester monitor --count 100 &          # monitore em segundo plano ou em outro terminal
feetech-HD1910M-tester goto 1024 --speed 300
feetech-HD1910M-tester goto 3072 --speed 1000
```

Observe `moving` mudar para 1 durante o movimento. A velocidade aumenta e depois diminui (perfil trapezoidal); ao chegar, a posição estabiliza dentro de ±1 unidade do alvo, considerando a zona morta.

### Experimento 5: ajuste de PID na região de operação, reversível

```bash
# Reduza Kp: movimento mais suave e chegada mais lenta
feetech-HD1910M-tester pid position --kp 8 --ram
feetech-HD1910M-tester goto 1024

# Aumente Kp: resposta mais rápida, com possibilidade de oscilação ou zumbido
feetech-HD1910M-tester pid position --kp 80 --ram
feetech-HD1910M-tester goto 3072

# Restaure os valores de fábrica do dump (pos-p=32) ou desligue e ligue novamente
feetech-HD1910M-tester pid position --kp 32 --kd 40 --ram
```

### Experimento 6: controle de força pelo limite da corrente alvo

```bash
feetech-HD1910M-tester mode 0                 # Servo de posição com limite de corrente
feetech-HD1910M-tester goal-current 30        # Corrente alvo ≈195 mA; força reduzida
feetech-HD1910M-tester goto 2048
# Bloqueie o servo suavemente com a mão: ele não deve vencer a resistência; observe a corrente no monitor
feetech-HD1910M-tester goal-current 500       # Restaura o limite (≈3,25 A)
```

### Experimento 7: proteção

```bash
feetech-HD1910M-tester protect --max-temp 40  # Reduz o limite de temperatura para 40 °C
# Aqueça o servo com cuidado ou aguarde; acima de 40 °C o torque é desligado e status indica superaquecimento
feetech-HD1910M-tester protect --max-temp 80  # Restaure ao terminar
```

### Experimento 8: validar o bloqueio da EPROM

```bash
feetech-HD1910M-tester set resp-level 1       # Sem --save: altera somente a memória
feetech-HD1910M-tester get lock               # Verifica o bloqueio atual (padrão 1)
feetech-HD1910M-tester set min-angle 10       # Altera um valor
# Desligue e ligue o servo; dump mostrará min-angle de volta a 0, pois lock=1 não persistiu a gravação
feetech-HD1910M-tester set min-angle 10 --save
# Desligue e ligue novamente: desta vez o valor permanece
feetech-HD1910M-tester set min-angle 0 --save # Restaure após o experimento
```

### Experimento 9: alterar ID (primeiro passo para vários servos)

```bash
feetech-HD1910M-tester set-id 2               # Altera o ID atual para 2
feetech-HD1910M-tester -i 2 dump              # Conecta usando o novo ID
feetech-HD1910M-tester -i 2 set-id 1          # Restaura o ID 1 para o exercício com um servo
```

### Experimento 10: gravação assíncrona e sincronizada (requer pelo menos dois servos)

```bash
feetech-HD1910M-tester -i 1 set goal-pos 1024 --defer   # Armazena sem mover
feetech-HD1910M-tester -i 2 set goal-pos 3072 --defer   # Armazena sem mover
feetech-HD1910M-tester action                            # Broadcast: os dois iniciam juntos
```

---

## 9. Cuidados de segurança

1. **O bloqueio prolongado gera calor:** a corrente pode chegar a 1,6 A e a temperatura subir rapidamente. Em experimentos de controle de força, limite a saída com `torque-limit` ou `goal-current` e acompanhe a temperatura com `monitor`.
2. **Vida útil da EPROM:** cerca de 100 mil ciclos de gravação. Durante o ajuste, use `--ram` ou omita `--save`; persista somente depois de decidir os valores. Nunca use `--save` em um loop.
3. **Registrador de fase (endereço 18):** controla configurações de baixo nível, como a direção do motor e do codificador. Alterá-lo sem entender a seção 3 pode fazer o servo girar sem controle; não o modifique sem compreender o protocolo.
4. **Antes de alterar ID/baud:** confirme que conseguirá reconectar usando os novos parâmetros e anote-os. Se esquecê-los, use `factory-reset` ou procure o servo testando baud rates.
5. **Montagem mecânica:** não deixe o servo suspenso com carga durante os experimentos; evite que ele atinja suas mãos ou arremesse peças.

---

## 10. Solução de problemas

| Sintoma | Verificações |
|---|---|
| `Response timeout` | 1) O servo está alimentado? 2) Os GNDs estão unidos? 3) O baud está correto? O padrão é 1M; use `-b` se alterado. 4) O ID está correto? Use `scan`. 5) Se TX/RX estiverem unidos, use `--echo`. |
| `Serial error: Permission denied` | Adicione o usuário ao grupo dialout com `sudo usermod -aG dialout $USER` e entre novamente na sessão. |
| `Checksum error` | Verifique interferência ou mau contato nos fios; o baud também pode estar incompatível. |
| `scan` não encontra o servo, embora esteja online | Aumente o timeout com `-t 30` ou teste outros baud rates, por exemplo `-b 115200 scan`. |
| O servo informa “overcurrent” | Envie novamente um comando de posição para limpar o estado. Para evitar recorrência, reduza `protect-current` ou `torque-limit`. |
| Configuração desaparece após reiniciar | Gravações na EPROM precisam de `--save`; consulte o bloqueio na seção 4.2. |
| Leitura de posição mostra um número negativo muito grande | A ferramenta já trata a codificação; a causa típica é interpretar sinal-magnitude como complemento de dois (seção 4.3). |

---

## Apêndice: roteiro de estudo recomendado

1. Execute os experimentos 1–4 para entender o protocolo e o mapa de memória.
2. Leia `src/protocol.rs` (cerca de 200 linhas) para entender a montagem e análise de pacotes.
3. Leia `src/registers.rs` e veja como transformar a tabela da documentação em código.
4. Leia `src/servo.rs`, com atenção a `&mut self`, `Result` e ao encadeamento de `?`.
5. Leia `src/main.rs` para conhecer a CLI declarativa do clap e o despacho por `match`.
6. Pratique alterando o código: adicione a `dump` uma opção para exibir apenas registradores diferentes do padrão de fábrica ou crie o subcomando `wave` para mover o servo em uma onda senoidal e observar com `monitor`.

Bom aprendizado!
