//! main.rs — entrada de linha de comando: analisa argumentos e chama o driver para testar os servos
//!
//! [Conceito de Rust: o binário usa a biblioteca do mesmo pacote]
//! Este crate contém src/lib.rs (a biblioteca feetech_servo) e este arquivo (o binário).
//! O binário importa os módulos da biblioteca como um consumidor externo com `use feetech_servo::...`.
//! A implementação do protocolo, da tabela de memória e do driver fica na biblioteca; a CLI mantém apenas a interação pela linha de comando.

use std::thread;
use std::time::Duration;

use clap::{Parser, Subcommand, ValueEnum};
use indicatif::{ProgressBar, ProgressStyle};

use feetech_servo::error::{Result, ServoError};
use feetech_servo::protocol;
use feetech_servo::registers::{self, find_register, Access, Area, REGISTERS, BAUD_RATES};
use feetech_servo::servo::Servo;

// =============================================================================
// Definição da linha de comando.
// =============================================================================

/// Interface de linha de comando principal: opções globais e um subcomando.
///
/// global = true permite informar as opções antes ou depois do subcomando,
/// por exemplo, `feetech-HD1910M-tester dump -i 2` ou `feetech-HD1910M-tester -i 2 dump`.
#[derive(Parser)]
#[command(
    name = "feetech-HD1910M-tester",
    version,
    about = "Ferramenta de teste serial para servos Feetech HD1910M (protocolo FT-SCS)",
    long_about = "Ferramenta de teste para todos os registradores legíveis e graváveis da tabela de memória oficial.\n\
                  Padrões de fábrica: ID=1, taxa=1000000, serial=/dev/ttyUSB0.\n\
                  Informe registradores pelo nome em inglês (por exemplo, pos-p), endereço decimal (21) ou hexadecimal (0x15)."
)]
struct Cli {
    /// Caminho do dispositivo serial.
    #[arg(short, long, default_value = "/dev/ttyUSB0", global = true)]
    port: String,

    /// Taxa de comunicação (padrão de fábrica: 1000000).
    #[arg(short, long, default_value_t = 1_000_000, global = true)]
    baud: u32,

    /// ID do servo (padrão de fábrica: 1).
    #[arg(short, long, default_value_t = 1, global = true)]
    id: u8,

    /// Timeout de transmissão/recepção serial (ms). Reduza durante a varredura para acelerar a operação.
    #[arg(short = 't', long, default_value_t = 50, global = true)]
    timeout: u64,

    /// Exibe os pacotes brutos enviados e recebidos (ative para estudar o protocolo FT-SCS).
    #[arg(short, long, global = true)]
    verbose: bool,

    /// Ative para ligações simples com TX/RX em curto; descarta o eco dos próprios dados enviados.
    #[arg(long, global = true)]
    echo: bool,

    #[command(subcommand)]
    cmd: Cmd,
}

/// Todos os subcomandos.
///
/// [Conceito de Rust: enum com dados e Subcommand]
/// Cada variante carrega sua própria estrutura de argumentos, que clap mapeia para um subcomando.
/// A função run() distribui todos os comandos com match; o compilador verifica se todas as variantes
/// foram tratadas e falha se alguma for esquecida durante uma refatoração.
#[derive(Subcommand)]
enum Cmd {
    /// Varre o barramento: envia PING aos IDs de 0 a 253 e lista os servos online.
    Scan {
        /// ID inicial.
        #[arg(long, default_value_t = 0)]
        from: u8,
        /// ID final.
        #[arg(long, default_value_t = 253)]
        to: u8,
    },

    /// Lê e exibe toda a tabela de memória, agrupada por área e com descrições e unidades em português.
    Dump,

    /// Lê um registrador: get pos-p / get 21 / get 0x15.
    Get {
        /// Registrador: nome em inglês, endereço decimal ou endereço hexadecimal 0x.
        reg: String,
    },

    /// Grava em um registrador (por padrão altera apenas a memória; use --save para persistir valores da área EPROM).
    Set {
        /// Registrador: nome em inglês ou endereço.
        reg: String,
        /// Valor a gravar (valores negativos também são aceitos; por exemplo, pos-offset permite -4095).
        value: i64,
        /// Persiste ao desligar (desbloqueia a EPROM, grava e bloqueia novamente).
        #[arg(long)]
        save: bool,
        /// Escrita registrada: armazena primeiro e executa com o comando action (para sincronizar vários servos).
        #[arg(long)]
        defer: bool,
    },

    /// Executa por broadcast todo o conteúdo armazenado por escritas REG WRITE.
    Action,

    /// Escrita sincronizada: grava o mesmo registrador em vários servos com um pacote (por exemplo: "1,2,3" goal-pos 2048).
    Swrite {
        /// Lista de IDs de destino, separados por vírgula.
        ids: String,
        /// Registrador: nome em inglês ou endereço.
        reg: String,
        /// Valor a gravar.
        value: i64,
    },

    /// Define o ID do servo (desbloqueia, grava, bloqueia novamente e persiste o valor).
    SetId {
        /// Novo ID (0 a 253).
        new_id: u8,
    },

    /// Define a taxa de comunicação (persiste ao desligar; reconecte usando a nova taxa).
    SetBaud {
        /// Índice da taxa, de 0 a 7: 0=1M 1=500k 2=250k 3=128k 4=115200 5=76800 6=57600 7=38400.
        index: u8,
    },

    /// Bloqueio de gravação da EPROM: on=bloqueia (padrão; não persiste ao desligar) / off=desbloqueia (persiste).
    Lock {
        #[arg(value_enum)]
        state: LockState,
    },

    /// Restaura as configurações de fábrica (restaura todos os valores da EPROM; use com cuidado).
    FactoryReset,

    /// Reinicia o servo (0x08; equivale a desligar e ligar, recarrega a SRAM da EPROM e pode validar gravações na EPROM).
    Reboot,

    /// Define o modo de operação: 0 posição, 1 velocidade constante, 2 corrente constante, 3 controle PWM em malha aberta, 4 PD de posição.
    Mode { mode: u8 },

    /// Modo de posição: move até a posição desejada (ativa automaticamente o torque).
    Goto {
        /// Posição de destino: 0 a 4095 corresponde a 0 a 360° (centro em 2048; o modo multivoltas aceita valores negativos ou acima de 4095).
        target: i64,
        /// Opcional: define também a velocidade de operação (0,732 RPM/unidade).
        #[arg(long)]
        speed: Option<i64>,
        /// Opcional: define também a aceleração (8,7 graus/s² por unidade; 0 = máximo).
        #[arg(long)]
        acc: Option<i64>,
    },

    /// Controle por ângulo: move até o ângulo informado; 0° é o centro (2048). Aceita sincronização de vários servos.
    Angle {
        /// Ângulo de destino (graus por padrão; use --rad para radianos), faixa de ±180°.
        angle: f64,
        /// Interpreta a entrada em radianos (por exemplo, 0,1745 ≈ 10°).
        #[arg(long)]
        rad: bool,
        /// Lista de IDs de destino separados por vírgula (padrão: perna direita 11,12).
        #[arg(long, default_value = "11,12")]
        ids: String,
        /// Opcional: define também a velocidade de operação (0,732 RPM/unidade).
        #[arg(long)]
        speed: Option<i64>,
    },

    /// Teste de oscilação da perna direita: balança os servos em pequenos movimentos senoidais ao redor do centro e retorna ao centro no final.
    Swing {
        /// Lista de IDs de destino separados por vírgula (padrão: perna direita 11,12).
        #[arg(long, default_value = "11,12")]
        ids: String,
        /// Amplitude da oscilação em graus (limite de 30° para evitar interferência mecânica).
        #[arg(long, default_value_t = 10.0)]
        amplitude: f64,
        /// Número de ciclos completos.
        #[arg(long, default_value_t = 3)]
        cycles: u32,
        /// Duração de cada ciclo em milissegundos; valores maiores deixam o movimento mais suave.
        #[arg(long, default_value_t = 2000)]
        period: u64,
        /// Opcional: limita a velocidade de operação (0,732 RPM/unidade).
        #[arg(long)]
        speed: Option<i64>,
    },

    /// Torque: on=ativa a saída, off=desativa (servo livre), damp=modo de amortecimento.
    Torque {
        #[arg(value_enum)]
        state: TorqueState,
    },

    /// Define o limite de torque (endereço 48, de 0 a 1000, unidade 0,1%): limita o torque de bloqueio.
    TorqueLimit { value: i64 },

    /// Define a corrente desejada (endereço 44, de -2047 a 2047, unidade 6,5 mA): controle principal de força.
    GoalCurrent { value: i64 },

    /// Define a velocidade de operação (endereço 46; BIT15 indica a direção no modo de velocidade constante).
    Speed { value: i64 },

    /// Define os parâmetros PID: malha de posição, velocidade ou corrente.
    Pid {
        /// Malha: position (PID de posição), velocity (PI de velocidade) ou current (PI de corrente).
        #[arg(value_enum)]
        pid_loop: PidLoop,
        #[arg(long)]
        kp: Option<i64>,
        #[arg(long)]
        kd: Option<i64>,
        #[arg(long)]
        ki: Option<i64>,
        /// Grava na área de operação (endereços 50 a 52, efeito imediato e volátil); por padrão, grava na área de configuração EPROM.
        #[arg(long)]
        ram: bool,
        /// Persiste ao desligar quando gravar na EPROM.
        #[arg(long)]
        save: bool,
    },

    /// Monitoramento em tempo real: exibe continuamente posição, velocidade, carga, tensão, temperatura e corrente (Ctrl+C para parar).
    Monitor {
        /// Intervalo de atualização em milissegundos.
        #[arg(long, default_value_t = 100)]
        interval: u64,
        /// Número de leituras a exibir (omite para exibir continuamente).
        #[arg(long)]
        count: Option<u32>,
    },

    /// Parâmetros de proteção: temperatura, sobretensão, subtensão, sobrecorrente, condições de alívio e alerta LED.
    Protect {
        /// Limite máximo de temperatura em °C (endereço 13).
        #[arg(long)]
        max_temp: Option<i64>,
        /// Tensão máxima de entrada em unidades de 0,1 V (endereço 14; por exemplo, 100 = 10,0 V).
        #[arg(long)]
        max_voltage: Option<i64>,
        /// Tensão mínima de entrada em unidades de 0,1 V (endereço 15; por exemplo, 40 = 4,0 V).
        #[arg(long)]
        min_voltage: Option<i64>,
        /// Duração até acionar a proteção contra sobrecorrente, em unidades de 10 ms (endereço 38; por exemplo, 200 = 2 s).
        #[arg(long)]
        overcur_time: Option<i64>,
        /// Máscara de bits das condições de alívio (endereço 19): BIT0 tensão, BIT1 codificador magnético, BIT2 superaquecimento, BIT3 sobrecorrente.
        #[arg(long)]
        unload: Option<i64>,
        /// Máscara de bits do alerta LED (endereço 20), com a mesma definição acima.
        #[arg(long)]
        led: Option<i64>,
        /// Persiste ao desligar.
        #[arg(long)]
        save: bool,
    },

    /// Define os limites de ângulo (endereços 9 e 11; use --save para persistir; no modo multivoltas, ambos devem ser 0).
    Limits {
        /// Limite mínimo de ângulo (unidade bruta de 0 a 4094 por padrão; use --deg para informar graus).
        min: f64,
        /// Limite máximo de ângulo (unidade bruta de 1 a 4095 por padrão; use --deg para informar graus).
        max: f64,
        /// Interpreta min/max como graus: 0 a 360° corresponde aos valores brutos de 0 a 4095.
        #[arg(long)]
        deg: bool,
        /// Persiste ao desligar (grava os dois registradores em um único ciclo de desbloqueio).
        #[arg(long)]
        save: bool,
    },

    /// Calibração de zero (instrução 0x0B): define a posição mecânica atual como centro 2048, equivalente a “Definir zero” no software Feetech FD.
    ///
    /// Uso: torque off para liberar o servo → posicione a junta manualmente no zero → execute este comando → torque on.
    /// O servo altera e persiste automaticamente o registrador de deslocamento de posição 31 e confirma lendo o valor de volta.
    Zero {
        /// Leitura de destino da calibração (padrão: 2048 = centro; faixa de 0 a 4095). Só é relevante no modo de posição de volta única.
        #[arg(long)]
        to: Option<i64>,
    },

    /// Define o deslocamento de posição (endereço 31, de -4095 a 4095) para corrigir o zero manualmente; prefira o comando zero para calibrar automaticamente.
    Offset {
        value: i64,
        /// Persiste ao desligar.
        #[arg(long)]
        save: bool,
    },
}

/// Valores do bloqueio (clap restringe a entrada a on/off).
#[derive(Clone, Copy, ValueEnum)]
enum LockState {
    /// Bloqueado: gravações EPROM não persistem ao desligar (padrão de fábrica).
    On,
    /// Desbloqueado: gravações EPROM persistem ao desligar.
    Off,
}

/// Valores do controle de torque.
#[derive(Clone, Copy, ValueEnum)]
enum TorqueState {
    /// Ativa a saída de torque.
    On,
    /// Desativa a saída de torque (o servo pode ser movido manualmente).
    Off,
    /// Saída de amortecimento (oferece resistência ao movimento manual; usada com frequência para ensino de movimentos).
    Damp,
}

/// Seleção da malha PID.
#[derive(Clone, Copy, ValueEnum)]
enum PidLoop {
    /// Malha de posição: P=endereço 21, D=22, I=23 (área de operação 50/51/52).
    Position,
    /// Malha de velocidade: P=endereço 37, I=39 (área de operação 50/52).
    Velocity,
    /// Malha de corrente: P=endereço 34, I=35 (somente na área EPROM).
    Current,
}

// =============================================================================
// Ponto de entrada do programa.
// =============================================================================

/// [Conceito de Rust: fn main() -> Result]
/// main também pode retornar Result: Err encerra o programa com código diferente de zero e exibe o erro,
/// permitindo usar `?` diretamente em main.
fn main() -> Result<()> {
    let cli = Cli::parse();

    // O comando de varredura não precisa conectar a um servo específico, mas ainda precisa da porta serial.
    let mut servo = Servo::connect(&cli.port, cli.baud, cli.timeout, cli.echo, cli.verbose)?;
    if cli.verbose {
        eprintln!("Porta aberta: {} @ {} bps, ID de destino = {}", cli.port, cli.baud, cli.id);
    }

    // [Conceito de Rust: verificação de exaustividade do match]
    // O compilador exige tratar todas as variantes de Cmd; um novo subcomando sem tratamento causa erro de compilação.
    match cli.cmd {
        Cmd::Scan { from, to } => cmd_scan(&mut servo, from, to),
        Cmd::Dump => cmd_dump(&mut servo, cli.id),
        Cmd::Get { reg } => cmd_get(&mut servo, cli.id, &reg),
        Cmd::Set { reg, value, save, defer } => cmd_set(&mut servo, cli.id, &reg, value, save, defer),
        Cmd::Action => {
            servo.action()?;
            println!("ACTION transmitido por broadcast; todas as escritas registradas foram executadas.");
            Ok(())
        }
        Cmd::Swrite { ids, reg, value } => {
            let reg = find_register(&reg).ok_or_else(|| {
                ServoError::InvalidParam(format!("registrador desconhecido \"{reg}\""))
            })?;
            // Analisa a lista de IDs separados por vírgula: "1,2,3" → vec![1, 2, 3].
            let ids: std::result::Result<Vec<u8>, _> =
                ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
            let ids = ids.map_err(|_| ServoError::InvalidParam("formato da lista de IDs: 1,2,3".into()))?;
            servo.sync_write(&ids, reg, value)?;
            println!("Escrita sincronizada em {:?}: {} ({}) = {value}", ids, reg.key, reg.cn);
            Ok(())
        }
        Cmd::SetId { new_id } => cmd_set_id(&mut servo, cli.id, new_id),
        Cmd::SetBaud { index } => cmd_set_baud(&mut servo, cli.id, index),
        Cmd::Lock { state } => {
            let v = match state {
                LockState::On => 1,
                LockState::Off => 0,
            };
            servo.write_reg(cli.id, find_register("lock").unwrap(), v)?;
            println!("Flag de bloqueio definida como {v} ({})", if v == 0 { "desbloqueada: gravações EPROM serão persistidas" } else { "bloqueada: gravações EPROM não serão persistidas" });
            Ok(())
        }
        Cmd::FactoryReset => {
            servo.factory_reset(cli.id)?;
            println!("Instrução de restauração de fábrica enviada. Reinicie o servo (o ID volta a 1 e a taxa a 1 Mbps).");
            Ok(())
        }
        Cmd::Reboot => {
            // Alguns firmwares não respondem antes de reiniciar; timeout não é considerado falha.
            match servo.reboot(cli.id) {
                Ok(()) => println!("Instrução de reinicialização enviada e confirmada."),
                Err(ServoError::Timeout) => println!("Instrução de reinicialização enviada (o servo não respondeu; pode ter reiniciado imediatamente)."),
                Err(e) => return Err(e),
            }
            println!("Aguarde cerca de 1 segundo para o servo reiniciar antes de se comunicar novamente.");
            Ok(())
        }
        Cmd::Mode { mode } => {
            let reg = find_register("mode").unwrap();
            servo.write_reg(cli.id, reg, mode as i64)?;
            const MODES: [&str; 5] = [
                "0: modo de posição (posição + limite de corrente)",
                "1: modo de velocidade constante (velocidade + limite de corrente)",
                "2: modo de corrente constante (limite de corrente)",
                "3: modo de controle de velocidade PWM em malha aberta",
                "4: modo PD de posição pura (Sim2Real, padrão de fábrica)",
            ];
            println!("Modo de operação definido como {mode} = {}", MODES[mode as usize]);
            println!("Dica: o modo fica na EPROM. Use --verbose para ver os pacotes; para persistir ao desligar, execute set mode {mode} --save.");
            Ok(())
        }
        Cmd::Goto { target, speed, acc } => cmd_goto(&mut servo, cli.id, target, speed, acc),
        Cmd::Angle { angle, rad, ids, speed } => {
            cmd_angle(&mut servo, &ids, angle, rad, speed)
        }
        Cmd::Swing { ids, amplitude, cycles, period, speed } => {
            cmd_swing(&mut servo, &ids, amplitude, cycles, period, speed)
        }
        Cmd::Torque { state } => {
            let v = match state {
                TorqueState::On => 1,
                TorqueState::Off => 0,
                TorqueState::Damp => 2,
            };
            servo.write_reg(cli.id, find_register("torque-switch").unwrap(), v)?;
            let desc = match state {
                TorqueState::On => "saída de torque ativada",
                TorqueState::Off => "saída de torque desativada (servo livre, pode ser movido manualmente)",
                TorqueState::Damp => "saída de amortecimento ativada (oferece resistência ao movimento manual; pode ser usada para ensinar movimentos)",
            };
            println!("{desc}");
            Ok(())
        }
        Cmd::TorqueLimit { value } => {
            servo.write_reg(cli.id, find_register("torque-limit").unwrap(), value)?;
            println!("Limite de torque definido como {value} (= {:.1}%)", value as f64 / 10.0);
            Ok(())
        }
        Cmd::GoalCurrent { value } => {
            servo.write_reg(cli.id, find_register("goal-current").unwrap(), value)?;
            println!("Corrente desejada definida como {value} (≈ {:.0} mA)", value as f64 * 6.5);
            Ok(())
        }
        Cmd::Speed { value } => {
            servo.write_reg(cli.id, find_register("speed").unwrap(), value)?;
            println!("Velocidade de operação definida como {value} (≈ {:.1} RPM)", value as f64 * 0.732);
            Ok(())
        }
        Cmd::Pid { pid_loop, kp, kd, ki, ram, save } => {
            cmd_pid(&mut servo, cli.id, pid_loop, kp, kd, ki, ram, save)
        }
        Cmd::Monitor { interval, count } => cmd_monitor(&mut servo, cli.id, interval, count),
        Cmd::Protect { max_temp, max_voltage, min_voltage, overcur_time, unload, led, save } => cmd_protect(
            &mut servo, cli.id, max_temp, max_voltage, min_voltage, overcur_time, unload, led, save,
        ),
        Cmd::Limits { min, max, deg, save } => cmd_limits(&mut servo, cli.id, min, max, deg, save),
        Cmd::Zero { to } => cmd_zero(&mut servo, cli.id, to),
        Cmd::Offset { value, save } => {
            cmd_write_eprom(&mut servo, cli.id, "pos-offset", value, save)?;
            println!("Deslocamento de posição definido como {value}{}", if save { " (persistido)" } else { "" });
            Ok(())
        }
    }
}

// =============================================================================
// Implementações dos subcomandos.
// =============================================================================

/// Varre o barramento (com barra de progresso).
///
/// [Conceito de Rust: uso do crate de terceiros indicatif]
/// Depois de adicionar a dependência ao Cargo.toml, ela pode ser usada com `use indicatif::...`.
/// ProgressBar atualiza uma linha da barra de progresso no terminal:
///   - ProgressStyle::with_template define o modelo visual ({bar}, {pos}, {msg} etc.)
///   - progress_chars personaliza os caracteres de preenchimento
///   - enable_steady_tick mantém a animação girando durante a espera
///   - pb.println imprime acima da barra sem corromper sua exibição
fn cmd_scan(servo: &mut Servo, from: u8, to: u8) -> Result<()> {
    let total = (to - from + 1) as u64;
    let pb = ProgressBar::new(total);
    pb.set_style(
        ProgressStyle::with_template(
            "{spinner:.green} [{elapsed_precise}] [{bar:40.cyan/blue}] {pos}/{len} ({percent}%) {msg}",
        )
        .unwrap() // O modelo é uma string fixa e válida em tempo de compilação; unwrap é seguro aqui.
        .progress_chars("█▉▊▋▌▍▎▏  "),
    );
    // Atualiza o spinner a cada 100 ms para que a tela não pareça congelada durante o timeout.
    pb.enable_steady_tick(Duration::from_millis(100));

    let mut found = Vec::new();
    for id in from..=to {
        pb.set_message(format!("PING ID {id}"));
        if servo.ping(id)? {
            found.push(id);
            pb.println(format!("  ✔ Servo encontrado, ID = {id}"));
        }
        pb.inc(1); // Avança o progresso em 1.
    }

    // Finaliza a barra de progresso e exibe o resultado.
    pb.finish_and_clear();
    if found.is_empty() {
        println!("Varredura concluída (IDs {from} a {to}): nenhum servo encontrado. Verifique a fiação, alimentação, taxa (-b) e porta serial (-p).");
    } else {
        // [Conceito de Rust: map e collect de iteradores para montar uma string]
        let list: Vec<String> = found.iter().map(|id| id.to_string()).collect();
        println!("Varredura concluída: {} servo(s) encontrado(s), IDs: {}", found.len(), list.join(", "));
    }
    Ok(())
}

/// Lê e exibe toda a tabela de memória.
///
/// [Otimização: leitura em blocos] Alguns endereços da tabela de memória são lacunas (como 10, 12 e 29).
/// Ler cada registrador individualmente exigiria dezenas de instruções; em vez disso, lê cinco blocos contíguos por área
/// e busca os valores no buffer por endereço, o que é muito mais rápido.
fn cmd_dump(servo: &mut Servo, id: u8) -> Result<()> {
    // (endereço inicial, tamanho da leitura): cobre 0 a 4, 5 a 39, 40 a 55, 56 a 75 e 77 a 86.
    let blocks = [(0u8, 5u8), (5, 35), (40, 16), (56, 20), (77, 10)];
    let mut image = [0u8; 128]; // Cópia da tabela de memória; o índice corresponde ao endereço.
    for (start, len) in blocks {
        let data = servo.read(id, start, len)?;
        if data.len() < len as usize {
            return Err(ServoError::Malformed("bloco lido muito curto".into()));
        }
        // Copia para o buffer da tabela.
        image[start as usize..(start + len) as usize].copy_from_slice(&data[..len as usize]);
    }

    println!("====== Tabela de memória HD1910M (ID={id}) ======");
    let mut last_area: Option<Area> = None;
    for reg in REGISTERS {
        // Exibe o título da área quando ela muda.
        if last_area != Some(reg.area) {
            println!("\n----- {} -----", reg.area.as_str());
            last_area = Some(reg.area);
        }
        let raw = if reg.size == 1 {
            image[reg.addr as usize] as u16
        } else {
            u16::from_le_bytes([image[reg.addr as usize], image[reg.addr as usize + 1]])
        };
        let val = registers::decode_value(raw, reg.sign_bit);
        println!(
            "  [{:>2}/0x{:02X}] {:<12} {:<10} = {:>6} {:<8} [{}] {}",
            reg.addr, reg.addr, reg.key, reg.cn, val, reg.unit,
            reg.access.as_str(), reg.desc
        );
    }
    Ok(())
}

/// Lê um registrador e exibe o resultado de forma legível.
fn cmd_get(servo: &mut Servo, id: u8, name: &str) -> Result<()> {
    let reg = find_register(name).ok_or_else(|| {
        ServoError::InvalidParam(format!("registrador desconhecido \"{name}\"; use o comando dump para listar todos os nomes"))
    })?;
    let val = servo.read_reg(id, reg)?;
    println!(
        "[{}/0x{:02X}] {}（{}）= {} {}",
        reg.addr, reg.addr, reg.key, reg.cn, val, reg.unit
    );
    // Exibe uma explicação dos bits para registradores que usam máscaras de bits.
    match reg.key {
        "status" => println!("  Status: {}", protocol::describe_status(val as u8)),
        "unload-cond" | "led-alarm" => println!("  Significado dos bits: {}", describe_protect_bits(val as u8)),
        _ => {}
    }
    Ok(())
}

/// Grava em um registrador.
fn cmd_set(servo: &mut Servo, id: u8, name: &str, value: i64, save: bool, defer: bool) -> Result<()> {
    let reg = find_register(name).ok_or_else(|| {
        ServoError::InvalidParam(format!("registrador desconhecido \"{name}\"; use o comando dump para listar todos os nomes"))
    })?;
    if reg.access == Access::ReadOnly {
        return Err(ServoError::InvalidParam(format!(
            "{} ({}) é somente leitura e não pode ser gravado", reg.key, reg.cn
        )));
    }
    if defer {
        // A escrita registrada também valida a faixa antes de enviar (sem isso, valores fora da faixa seriam codificados e enviados).
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let bytes = if reg.size == 1 { vec![val as u8] } else { val.to_le_bytes().to_vec() };
        servo.reg_write(id, reg.addr, &bytes)?;
        println!("Escrita registrada de {} ({}) = {value}; terá efeito após executar o comando action.", reg.key, reg.cn);
        return Ok(());
    }
    if save {
        servo.save_reg(id, reg, value)?;
        println!("{} ({}) = {value} (gravado na EPROM e persistido)", reg.key, reg.cn);
    } else {
        servo.write_reg(id, reg, value)?;
        let tip = if reg.area == Area::Eprom { " (válido apenas até desligar; use --save para persistir)" } else { "" };
        println!("{}（{}）= {value}{tip}", reg.key, reg.cn);
    }
    Ok(())
}

/// Função auxiliar para gravar em um registrador EPROM (usada pelo comando offset).
fn cmd_write_eprom(servo: &mut Servo, id: u8, key: &str, value: i64, save: bool) -> Result<()> {
    let reg = find_register(key).unwrap();
    if save {
        servo.save_reg(id, reg, value)
    } else {
        servo.write_reg(id, reg, value)
    }
}

/// Define a faixa ativa (limites de ângulo): ângulo mínimo no endereço 9 e máximo no endereço 11.
///
/// Corresponde aos limites de ângulo do software Feetech FD e aceita valores brutos ou graus (--deg).
/// Com --save, os dois registradores compartilham um único ciclo de desbloqueio/bloqueio, reduzindo pela metade o acesso à EPROM.
/// Depois da gravação, lê os valores para confirmar: a Feetech pode responder “sucesso” mesmo quando a gravação não é suportada ou não teve efeito.
fn cmd_limits(servo: &mut Servo, id: u8, min: f64, max: f64, deg: bool, save: bool) -> Result<()> {
    // Graus → valor bruto de posição; entradas brutas são arredondadas diretamente.
    let (min, max) = if deg {
        ((min / DEG_PER_COUNT).round() as i64, (max / DEG_PER_COUNT).round() as i64)
    } else {
        (min as i64, max as i64)
    };

    // Valida a faixa. No modo multivoltas, ambos devem ser 0, embora o limite nominal inferior de max-angle seja 1;
    // por isso, a combinação 0/0 é tratada separadamente (a documentação oficial indica 0 no controle absoluto multivoltas).
    let multico = min == 0 && max == 0;
    if !(0..=4094).contains(&min) {
        return Err(ServoError::InvalidParam(format!("limite mínimo de ângulo {min} fora da faixa 0 a 4094")));
    }
    if !multico && !(1..=4095).contains(&max) {
        return Err(ServoError::InvalidParam(format!("limite máximo de ângulo {max} fora da faixa 1 a 4095")));
    }
    if !multico && min >= max {
        return Err(ServoError::InvalidParam(format!(
            "o limite mínimo de ângulo {min} deve ser menor que o limite máximo {max} (no modo multivoltas, defina ambos como 0)"
        )));
    }

    let min_reg = find_register("min-angle").unwrap();
    let max_reg = find_register("max-angle").unwrap();
    if save {
        // Grava os dois registradores em um ciclo de desbloqueio; bloqueia novamente mesmo se uma etapa falhar.
        let lock = find_register("lock").unwrap();
        servo.write_reg(id, lock, 0)?;
        let r1 = servo.write_reg(id, min_reg, min);
        let r2 = servo.write_reg(id, max_reg, max);
        let relock = servo.write_reg(id, lock, 1);
        r1.and(r2).and(relock)?;
    } else {
        servo.write_reg(id, min_reg, min)?;
        servo.write_reg(id, max_reg, max)?;
    }

    // Lê os valores de volta para confirmar.
    let rb_min = servo.read_reg(id, min_reg)?;
    let rb_max = servo.read_reg(id, max_reg)?;
    println!(
        "Limites de ângulo lidos de volta = {rb_min} a {rb_max} (aprox. {:.1}° a {:.1}°){}",
        rb_min as f64 * DEG_PER_COUNT,
        rb_max as f64 * DEG_PER_COUNT,
        if save { " (persistidos)" } else { " (válidos apenas até desligar; use --save para persistir)" }
    );
    Ok(())
}

/// Calibração de zero (instrução 0x0B): calibra a posição mecânica atual para target (centro 2048 por padrão).
///
/// [Etapas principais] Desbloqueia a EPROM antes de calibrar para persistir o deslocamento;
/// depois, lê a posição atual e o deslocamento para confirmar. A resposta “sucesso” da Feetech não é confiável:
/// testes mostraram que o HD-1910 também confirma com sucesso a calibração antiga por gravação de 128, que não é suportada.
fn cmd_zero(servo: &mut Servo, id: u8, to: Option<i64>) -> Result<()> {
    let target = to.unwrap_or(CENTER_POS);
    if !(0..=4095).contains(&target) {
        return Err(ServoError::InvalidParam(format!(
            "destino de calibração {target} fora da faixa 0 a 4095 (só é relevante no modo de posição de volta única)"
        )));
    }

    // Lê antes da calibração para exibir a leitura original desta posição.
    let before = servo.read_reg(id, find_register("pos").unwrap())?;
    println!(
        "Antes da calibração: posição atual = {before} ({:+.1}° em relação ao centro); será calibrada para {target}",
        (before - CENTER_POS) as f64 * DEG_PER_COUNT
    );

    // Desbloqueia → calibra → bloqueia: persiste o deslocamento de posição do endereço 31 na EPROM.
    let lock = find_register("lock").unwrap();
    servo.write_reg(id, lock, 0)?;
    let result = servo.calibrate(id, Some(target as u16));
    let relock = servo.write_reg(id, lock, 1);
    result.and(relock)?;

    // O servo precisa de um tempo para calcular e gravar o deslocamento internamente.
    thread::sleep(Duration::from_millis(100));

    // Confirma lendo de volta: a posição deve ser target e o servo deve ter alterado o registrador de deslocamento.
    let after = servo.read_reg(id, find_register("pos").unwrap())?;
    let offset = servo.read_reg(id, find_register("pos-offset").unwrap())?;
    println!("Após a calibração: posição atual = {after}, deslocamento de posição (endereço 31) = {offset} (persistido)");
    if (after - target).abs() > 4 {
        return Err(ServoError::Malformed(format!(
            "a calibração pode não ter sido aplicada: a posição lida {after} difere do destino {target} em mais de 4 unidades;\
             tente novamente com -v e confira se o firmware aceita a instrução 0x0B"
        )));
    }
    println!("Calibração de zero concluída: a posição mecânica atual corresponde à leitura {target} ({:+.1}° em relação ao centro)",
        (target - CENTER_POS) as f64 * DEG_PER_COUNT);
    println!("Dica: se moveu a junta manualmente com torque off, execute goto {target} antes de torque on para evitar que ela volte ao zero antigo.");
    Ok(())
}

/// Define o ID do servo — uma configuração importante que precisa ser persistida.
///
/// [Ponto de atenção] Depois de gravar o registrador ID, o servo passa **imediatamente** a responder pelo novo ID.
/// Portanto, a última etapa (bloquear novamente) precisa usar o novo ID; enviar ao antigo causa timeout,
/// embora a alteração já tenha sido concluída.
fn cmd_set_id(servo: &mut Servo, old_id: u8, new_id: u8) -> Result<()> {
    if new_id > 253 {
        return Err(ServoError::InvalidParam("o ID deve estar entre 0 e 253".into()));
    }
    if new_id == old_id {
        println!("O novo ID é igual ao ID atual ({old_id}); nenhuma alteração necessária.");
        return Ok(());
    }
    println!("Alterando o ID do servo de {old_id} para {new_id} (desbloquear → gravar → bloquear)...");
    let lock = find_register("lock").unwrap();
    let id_reg = find_register("id").unwrap();

    // 1) Desbloqueia a EPROM para persistir gravações (envia ao ID antigo).
    servo.write_reg(old_id, lock, 0)?;
    // 2) Grava o novo ID (envia ao ID antigo; após responder, o servo passa a aceitar somente o novo ID).
    servo.write_reg(old_id, id_reg, new_id as i64)?;
    // 3) Bloqueia novamente: precisa enviar ao **novo ID**.
    servo.write_reg(new_id, lock, 1)?;

    println!("Concluído! Use -i {new_id} para conectar a este servo. Exemplo: feetech-HD1910M-tester -i {new_id} dump");
    println!("Atenção: outro servo com ID={new_id} no barramento causará conflito; conecte-se apenas a este servo antes de alterar o ID.");
    Ok(())
}

/// Define a taxa de transmissão.
fn cmd_set_baud(servo: &mut Servo, id: u8, index: u8) -> Result<()> {
    if index > 7 {
        return Err(ServoError::InvalidParam("o índice da taxa de transmissão deve estar entre 0 e 7".into()));
    }
    let baud = BAUD_RATES[index as usize];
    let reg = find_register("baud").unwrap();
    servo.save_reg(id, reg, index as i64)?;
    println!("Taxa de transmissão definida no índice {index} ({baud} bps) e persistida.");
    println!("A alteração terá efeito após reiniciar o servo; conecte-se usando -b {baud}.");
    Ok(())
}

/// Movimento no modo de posição.
fn cmd_goto(servo: &mut Servo, id: u8, target: i64, speed: Option<i64>, acc: Option<i64>) -> Result<()> {
    // As opções só são gravadas quando informadas; caso contrário, preserva a configuração atual do servo.
    if let Some(a) = acc {
        servo.write_reg(id, find_register("acc").unwrap(), a)?;
    }
    if let Some(s) = speed {
        servo.write_reg(id, find_register("speed").unwrap(), s)?;
    }
    // Ativa o torque para que o servo mantenha a posição.
    servo.write_reg(id, find_register("torque-switch").unwrap(), 1)?;
    servo.write_reg(id, find_register("goal-pos").unwrap(), target)?;
    let deg = target as f64 * 0.0879; // 0,087 grau/unidade (valor nominal; 360°/4096 ≈ 0,0879).
    println!("Posição desejada = {target} (aprox. {deg:.1}°); servo em movimento... use o comando monitor para acompanhar.");
    Ok(())
}

// =============================================================================
// Teste da perna direita (ângulo/oscilação): centro 2048 equivale a 0°; controle por ângulo em vez do valor bruto da posição.
// =============================================================================

/// Valor bruto do centro da posição (0 a 4095 mapeado para 0 a 360°).
const CENTER_POS: i64 = 2048;
/// Ângulo em graus por unidade de posição: 360° / 4096.
const DEG_PER_COUNT: f64 = 360.0 / 4096.0;
/// Amplitude máxima permitida em graus no teste de oscilação. A perna direita tem peças próximas; amplitudes excessivas causam interferência mecânica.
const MAX_SWING_AMPLITUDE_DEG: f64 = 30.0;

/// Converte ângulo em graus relativo ao centro no valor bruto de posição do servo.
fn deg_to_pos(deg: f64) -> i64 {
    CENTER_POS + (deg / DEG_PER_COUNT).round() as i64
}

/// Analisa uma lista de IDs separados por vírgula: "11,12" → vec![11, 12].
fn parse_ids(ids: &str) -> Result<Vec<u8>> {
    let ids: std::result::Result<Vec<u8>, _> =
        ids.split(',').map(|s| s.trim().parse::<u8>()).collect();
    ids.map_err(|_| ServoError::InvalidParam("formato da lista de IDs: 11,12".into()))
}

/// Controle por ângulo: move o servo o número de graus (ou radianos) informado em relação ao centro.
/// Para vários IDs, envia uma única escrita sincronizada (SYNC WRITE) para manter os servos alinhados.
fn cmd_angle(servo: &mut Servo, ids: &str, angle: f64, rad: bool, speed: Option<i64>) -> Result<()> {
    let ids = parse_ids(ids)?;
    // Converte tudo para graus: radianos × 180/π.
    let deg = if rad { angle.to_degrees() } else { angle };
    // No modo de posição de volta única, somente valores entre ±180° têm significado; rejeita valores fora da faixa.
    if !(-180.0..=180.0).contains(&deg) {
        return Err(ServoError::InvalidParam(format!(
            "o ângulo {deg}° excede a faixa de ±180° em relação ao centro"
        )));
    }
    let target = deg_to_pos(deg);
    // Ativa o torque, aplica o limite de velocidade opcional e envia a posição de destino sincronizada.
    servo.sync_write(&ids, find_register("torque-switch").unwrap(), 1)?;
    if let Some(s) = speed {
        servo.sync_write(&ids, find_register("speed").unwrap(), s)?;
    }
    servo.sync_write(&ids, find_register("goal-pos").unwrap(), target)?;
    println!(
        "Ângulo de destino = {:.2}° (posição bruta {target}, centro {CENTER_POS}), enviado de forma sincronizada para {:?}",
        deg, ids
    );
    Ok(())
}

/// Teste de oscilação: movimento senoidal suave ao redor do centro, com amplitude pequena e velocidade baixa para evitar interferência na perna.
///
/// [Implementação] Divide cada ciclo em pequenos passos (50 ms cada),
/// calcula a posição como centro + amplitude × sin(fase) e envia cada alvo com escrita sincronizada.
/// Assim, os dois servos seguem a mesma curva suave e se movem juntos.
fn cmd_swing(
    servo: &mut Servo,
    ids: &str,
    amplitude: f64,
    cycles: u32,
    period: u64,
    speed: Option<i64>,
) -> Result<()> {
    let ids = parse_ids(ids)?;
    if amplitude <= 0.0 || amplitude > MAX_SWING_AMPLITUDE_DEG {
        return Err(ServoError::InvalidParam(format!(
            "a amplitude deve estar entre 0 e {MAX_SWING_AMPLITUDE_DEG}° para evitar interferência mecânica na perna"
        )));
    }
    if period < 400 {
        return Err(ServoError::InvalidParam("o período é muito curto (<400 ms) e o movimento ficará brusco; aumente --period".into()));
    }

    let goal_pos = find_register("goal-pos").unwrap();
    // Ativa o torque e aplica o limite de velocidade opcional (velocidade menor = movimento mais suave).
    servo.sync_write(&ids, find_register("torque-switch").unwrap(), 1)?;
    if let Some(s) = speed {
        servo.sync_write(&ids, find_register("speed").unwrap(), s)?;
    }

    // Retorna ao centro e aguarda a parada antes de começar.
    println!("Retornando ao centro {CENTER_POS} (0°)...");
    servo.sync_write(&ids, goal_pos, CENTER_POS)?;
    thread::sleep(Duration::from_millis(800));

    println!(
        "Iniciando oscilação: amplitude ±{amplitude}°, {cycles} ciclo(s), período de {period} ms (Ctrl+C interrompe a qualquer momento)"
    );
    const STEP_MS: u64 = 50; // Passos de 50 ms produzem uma curva senoidal suave.
    let steps_per_cycle = (period / STEP_MS).max(1);
    for cycle in 1..=cycles {
        for step in 0..steps_per_cycle {
            // A fase vai de 0 a 2π, completando um ciclo.
            let phase = 2.0 * std::f64::consts::PI * step as f64 / steps_per_cycle as f64;
            let target = deg_to_pos(amplitude * phase.sin());
            servo.sync_write(&ids, goal_pos, target)?;
            thread::sleep(Duration::from_millis(STEP_MS));
        }
        println!("  Ciclo {cycle}/{cycles} concluído");
    }

    // Finalização: retorna ao centro e lê as posições reais para conferência.
    servo.sync_write(&ids, goal_pos, CENTER_POS)?;
    thread::sleep(Duration::from_millis(500));
    println!("Oscilação concluída; posição central restaurada. Feedback atual:");
    for &id in &ids {
        let fb = servo.read_feedback(id)?;
        let deg = (fb.pos - CENTER_POS) as f64 * DEG_PER_COUNT;
        println!("  ID {id}: posição {} ({deg:+.2}° em relação ao centro), tensão {:.1} V, temperatura {} °C", fb.pos, fb.voltage, fb.temp);
    }
    Ok(())
}

/// Define PID selecionando os registradores pela malha.
fn cmd_pid(
    servo: &mut Servo,
    id: u8,
    pid_loop: PidLoop,
    kp: Option<i64>,
    kd: Option<i64>,
    ki: Option<i64>,
    ram: bool,
    save: bool,
) -> Result<()> {
    // Escolhe as chaves dos registradores conforme a malha e a área de gravação.
    // Na documentação, a área operacional 50/51/52 representa PID de posição no modo de posição e PI de velocidade no modo de velocidade constante.
    let (k_p, k_d, k_i): (&str, Option<&str>, Option<&str>) = match (pid_loop, ram) {
        (PidLoop::Position, false) => ("pos-p", Some("pos-d"), Some("pos-i")),
        (PidLoop::Position, true) => ("kp", Some("kd"), Some("ki")),
        (PidLoop::Velocity, false) => ("vel-p", None, Some("vel-i")),
        (PidLoop::Velocity, true) => ("kp", None, Some("ki")),
        (PidLoop::Current, false) => ("cur-p", None, Some("cur-i")),
        (PidLoop::Current, true) => {
            return Err(ServoError::InvalidParam("a malha de corrente não tem mapeamento na área operacional; remova --ram".into()))
        }
    };

    // Associa cada valor de parâmetro à chave do registrador correspondente e grava os valores informados.
    let pairs: [(Option<i64>, &str); 3] = [
        (kp, k_p),
        (kd, k_d.unwrap_or("")),
        (ki, k_i.unwrap_or("")),
    ];
    let mut wrote_any = false;
    for (value, key) in pairs {
        if let (Some(v), false) = (value, key.is_empty()) {
            let reg = find_register(key).unwrap();
            if save { servo.save_reg(id, reg, v)?; } else { servo.write_reg(id, reg, v)?; }
            println!("  {} ({}) = {v}", reg.key, reg.cn);
            wrote_any = true;
        }
    }
    if !wrote_any {
        return Err(ServoError::InvalidParam(
            "informe pelo menos um parâmetro, por exemplo: pid position --kp 40 --kd 8".into(),
        ));
    }
    match (ram, save) {
        (true, _) => println!("Gravado na área operacional (efeito imediato, volátil) — adequado para experimentar ajustes."),
        (false, true) => println!("Gravado na EPROM e persistido."),
        (false, false) => println!("Gravado na configuração EPROM (válido até desligar; use --save para persistir após ajustar)."),
    }
    Ok(())
}

/// Monitora o feedback em tempo real.
fn cmd_monitor(servo: &mut Servo, id: u8, interval: u64, count: Option<u32>) -> Result<()> {
    println!("Posição   Velocidade Carga%  TensãoV Temperatura°C Corrente mA Movimento Status");
    let mut n = 0u32;
    loop {
        let fb = servo.read_feedback(id)?;
        println!(
            "{:<9} {:<9} {:<8.1} {:<7.1} {:<7} {:<8.0} {:<5} {}",
            fb.pos, fb.vel, fb.load as f64 / 10.0, fb.voltage, fb.temp,
            fb.current, fb.moving, protocol::describe_status(fb.status),
        );
        n += 1;
        // [Conceito de Rust: pattern matching em Option]
        // count é Option<u32>; Some(n) indica que o usuário especificou o número de leituras.
        if let Some(max) = count {
            if n >= max {
                break;
            }
        }
        thread::sleep(Duration::from_millis(interval));
    }
    Ok(())
}

/// Define os parâmetros de proteção.
#[allow(clippy::too_many_arguments)]
fn cmd_protect(
    servo: &mut Servo,
    id: u8,
    max_temp: Option<i64>,
    max_voltage: Option<i64>,
    min_voltage: Option<i64>,
    overcur_time: Option<i64>,
    unload: Option<i64>,
    led: Option<i64>,
    save: bool,
) -> Result<()> {
    let pairs: [(Option<i64>, &str); 6] = [
        (max_temp, "max-temp"),
        (max_voltage, "max-voltage"),
        (min_voltage, "min-voltage"),
        (overcur_time, "overcur-time"),
        (unload, "unload-cond"),
        (led, "led-alarm"),
    ];
    let mut wrote_any = false;
    for (value, key) in pairs {
        if let Some(v) = value {
            let reg = find_register(key).unwrap();
            if save { servo.save_reg(id, reg, v)?; } else { servo.write_reg(id, reg, v)?; }
            println!("  {} ({}) = {v}", reg.key, reg.cn);
            wrote_any = true;
        }
    }
    if !wrote_any {
        return Err(ServoError::InvalidParam(
            "informe pelo menos um parâmetro, por exemplo: protect --max-temp 80 --unload 12 --led 12".into(),
        ));
    }
    if save {
        println!("Todas as alterações foram persistidas.");
    } else {
        println!(" (válido apenas até desligar; use --save para persistir)");
    }
    Ok(())
}

/// Converte as máscaras de bits das condições de alívio e do alerta LED em descrições (consulte as seções 3.3 e 3.4 da documentação).
fn describe_protect_bits(v: u8) -> String {
    if v == 0 {
        return "Tudo desativado".to_string();
    }
    let bits = [
        (1u8, "Tensão"),
        (2, "Codificador magnético"),
        (4, "Superaquecimento"),
        (8, "Sobrecorrente"),
    ];
    let mut names = Vec::new();
    for (bit, name) in bits {
        if v & bit != 0 {
            names.push(name);
        }
    }
    names.join("+")
}
