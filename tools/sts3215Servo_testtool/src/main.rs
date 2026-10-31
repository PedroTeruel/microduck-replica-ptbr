//! sts3215Servo_testtool — ferramenta de teste dos servos STS3215
//!
//! Uso:
//!   sts3215Servo_testtool scan [--from 0 --to 253]     busca servos no barramento (com barra de progresso)
//!   sts3215Servo_testtool info <id>                    lê o estado do servo (posição/tensão/temperatura/corrente/carga)
//!   sts3215Servo_testtool read <id> <addr> <len>       lê qualquer registrador (saída hexadecimal)
//!   sts3215Servo_testtool set-id <id-antigo> <id-novo> altera o ID do servo (conecte somente um servo ao barramento!)
//!   sts3215Servo_testtool move <id> <pos> [--speed N] [--time ms]   move até a posição especificada (0~4095)
//!   sts3215Servo_testtool test <id>                    executa um teste completo em um servo
//!   sts3215Servo_testtool test-all                     busca e testa todos os servos
//!   sts3215Servo_testtool raw [id]                     diagnóstico de baixo nível: imprime bytes brutos enviados/recebidos
//!   Opções globais: --port <caminho> (padrão /dev/ttyUSB0)  --baud <taxa> (padrão 1000000)

mod sts;

use std::io;
use std::thread;
use std::time::{Duration, Instant};
use sts::{reg, StsBus};

const TEST_POSITIONS: [u16; 4] = [2048, 1024, 3072, 2048]; // Centro → baixo → alto → centro.
const POS_TOLERANCE: u16 = 20; // Tolerância de posição (passos).

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cfg = match parse_args(&args) {
        Ok(c) => c,
        Err(msg) => {
            eprintln!("Erro nos argumentos: {msg}\n");
            print_usage();
            std::process::exit(2);
        }
    };

    let mut bus = match StsBus::open(&cfg.port, cfg.baud) {
        Ok(b) => b,
        Err(e) => {
            eprintln!("Não foi possível abrir a porta serial {}: {e}", cfg.port);
            eprintln!("Verifique se o adaptador dos servos está conectado, se o caminho do dispositivo está correto e se o usuário pertence ao grupo dialout.");
            std::process::exit(1);
        }
    };

    // Alguns adaptadores usam RTS/DTR para controlar a direção ou habilitar a transmissão; ajuste conforme necessário.
    if let Some(on) = cfg.rts {
        let _ = bus.set_rts(on);
    }
    if let Some(on) = cfg.dtr {
        let _ = bus.set_dtr(on);
    }

    let code = match cfg.cmd.as_str() {
        "scan" => cmd_scan(&mut bus, cfg.from, cfg.to),
        "raw" => cmd_raw(&mut bus, cfg.id.unwrap_or(1)),
        "read" => cmd_read(&mut bus, cfg.id.expect("read exige id"), cfg.pos.expect("read exige addr") as u8, cfg.len.unwrap_or(1)),
        "info" => cmd_info(&mut bus, cfg.id.expect("info exige id")),
        "set-id" => cmd_set_id(&mut bus, cfg.id.expect("set-id exige o ID antigo"), cfg.pos.expect("set-id exige o ID novo") as u8),
        "move" => cmd_move(&mut bus, cfg.id.expect("move exige id"), cfg.pos.unwrap_or(2048), cfg.speed, cfg.time_ms),
        "test" => cmd_test(&mut bus, cfg.id.expect("test exige id")),
        "test-all" => cmd_test_all(&mut bus, cfg.from, cfg.to),
        _ => {
            print_usage();
            2
        }
    };
    std::process::exit(code);
}

struct Config {
    port: String,
    baud: u32,
    cmd: String,
    id: Option<u8>,
    pos: Option<u16>,
    speed: u16,
    time_ms: u16,
    from: u8,
    to: u8,
    rts: Option<bool>,
    dtr: Option<bool>,
    len: Option<u8>,
}

fn parse_args(args: &[String]) -> Result<Config, String> {
    let mut cfg = Config {
        port: "/dev/ttyUSB0".into(),
        baud: 1_000_000,
        cmd: String::new(),
        id: None,
        pos: None,
        speed: 1000,
        time_ms: 0,
        from: 0,
        to: 253,
        rts: None,
        dtr: None,
        len: None,
    };
    let mut positional: Vec<&str> = Vec::new();
    let mut i = 0;
    while i < args.len() {
        let take = |i: &mut usize| -> Result<&str, String> {
            *i += 1;
            args.get(*i)
                .map(|s| s.as_str())
                .ok_or_else(|| format!("Falta o valor da opção {}", args[*i - 1]))
        };
        let onoff = |s: &str| -> Result<bool, String> {
            match s {
                "on" | "1" => Ok(true),
                "off" | "0" => Ok(false),
                _ => Err("O valor deve ser on/off".into()),
            }
        };
        match args[i].as_str() {
            "--port" | "-p" => cfg.port = take(&mut i)?.to_string(),
            "--baud" | "-b" => cfg.baud = take(&mut i)?.parse().map_err(|_| "A taxa baud deve ser numérica")?,
            "--speed" => cfg.speed = take(&mut i)?.parse().map_err(|_| "speed deve ser numérico")?,
            "--time" => cfg.time_ms = take(&mut i)?.parse().map_err(|_| "time deve ser numérico")?,
            "--from" => cfg.from = take(&mut i)?.parse().map_err(|_| "from deve ser numérico")?,
            "--to" => cfg.to = take(&mut i)?.parse().map_err(|_| "to deve ser numérico")?,
            "--rts" => cfg.rts = Some(onoff(take(&mut i)?)?),
            "--dtr" => cfg.dtr = Some(onoff(take(&mut i)?)?),
            "-h" | "--help" => return Err("".into()),
            s if s.starts_with('-') => return Err(format!("Opção desconhecida: {s}")),
            s => positional.push(s),
        }
        i += 1;
    }
    cfg.cmd = positional.first().copied().unwrap_or("").to_string();
    if let Some(v) = positional.get(1) {
        cfg.id = Some(v.parse().map_err(|_| "id deve ser um número de 0 a 253")?);
    }
    if let Some(v) = positional.get(2) {
        cfg.pos = Some(v.parse().map_err(|_| "pos/addr deve ser um número")?);
    }
    if let Some(v) = positional.get(3) {
        cfg.len = Some(v.parse().map_err(|_| "len deve ser um número")?);
    }
    Ok(cfg)
}

fn print_usage() {
    let doc: Vec<&str> = include_str!("main.rs")
        .lines()
        .take_while(|l| l.starts_with("//!"))
        .map(|l| l.trim_start_matches("//!").trim_start())
        .collect();
    eprintln!("{}", doc.join("\n"));
}

/// Diagnóstico: envia ping ao servo e imprime os bytes brutos recebidos em hexadecimal.
///   Nenhum byte       -> servo não respondeu (alimentação/fiação/modo)
///   Igual ao enviado  -> adaptador ecoou, mas o servo não respondeu
///   Muitos caracteres inválidos -> taxa baud incompatível
///   FF FF id 02 00 CS -> resposta normal do servo!
fn cmd_raw(bus: &mut StsBus, id: u8) -> i32 {
    let show = |label: &str, r: io::Result<(Vec<u8>, Vec<u8>)>| match r {
        Ok((sent, recv)) => {
            let h = |v: &[u8]| v.iter().map(|b| format!("{b:02X}")).collect::<Vec<_>>().join(" ");
            println!("{label}");
            println!("  Enviado: {}", h(&sent));
            println!("  Recebido: {}", if recv.is_empty() { "(nenhum byte)".into() } else { h(&recv) });
            0
        }
        Err(e) => {
            eprintln!("{label} falhou: {e}");
            1
        }
    };
    let mut code = 0;
    code |= show("PING:", bus.raw_exchange(id, sts::INST_PING, &[]));
    code |= show("READ modelo (endereço 3, 2 bytes):", bus.raw_exchange(id, sts::INST_READ, &[3, 2]));
    code |= show("READ estado (endereço 56, 15 bytes):", bus.raw_exchange(id, sts::INST_READ, &[56, 15]));
    code
}

/// Leitura genérica de registrador: read <id> <addr> <len>, com saída hexadecimal.
fn cmd_read(bus: &mut StsBus, id: u8, addr: u8, len: u8) -> i32 {
    match bus.read(id, addr, len) {
        Ok(data) => {
            let hex: Vec<String> = data.iter().map(|b| format!("{b:02X}")).collect();
            println!("Servo {id}, {} bytes a partir do endereço {addr}: {}", data.len(), hex.join(" "));
            0
        }
        Err(e) => {
            eprintln!("Falha na leitura: {e}");
            1
        }
    }
}

/// Busca com barra de progresso.
fn scan_with_progress(bus: &mut StsBus, from: u8, to: u8) -> Vec<u8> {
    use std::io::Write as _;
    let total = (to - from + 1) as usize;
    let mut found = Vec::new();
    for (i, id) in (from..=to).enumerate() {
        const WIDTH: usize = 30;
        let done = (i + 1) * WIDTH / total;
        eprint!(
            "\rBuscando [{}{}] {:>3}/{total}  encontrados: {}",
            "#".repeat(done),
            "-".repeat(WIDTH - done),
            i + 1,
            found.len()
        );
        let _ = std::io::stderr().flush();
        if bus.ping(id).unwrap_or(false) {
            found.push(id);
        }
    }
    eprintln!(); // Quebra de linha após a barra de progresso.
    found
}

/// Busca no barramento e imprime os servos encontrados e seus modelos.
fn cmd_scan(bus: &mut StsBus, from: u8, to: u8) -> i32 {
    let ids = scan_with_progress(bus, from, to);
    if ids.is_empty() {
        println!("Nenhum servo encontrado. Verifique a fiação, a alimentação (7,4 V/12 V) e a taxa baud (--baud). ");
        return 1;
    }
    for id in &ids {
        let model = bus.read_u16(*id, reg::MODEL_NUMBER).unwrap_or(0);
        let t_max = bus.read_u8(*id, reg::MAX_TEMPERATURE).unwrap_or(0);
        let v_max = bus.read_u8(*id, reg::MAX_VOLTAGE).map(|v| v as f32 * 0.1).unwrap_or(0.0);
        let v_min = bus.read_u8(*id, reg::MIN_VOLTAGE).map(|v| v as f32 * 0.1).unwrap_or(0.0);
        let volt = bus.read_u8(*id, reg::PRESENT_VOLTAGE).map(|v| v as f32 * 0.1).unwrap_or(0.0);
        println!("  ID {id:>3}  Online  Modelo={model}  Tensão={volt:.1} V (faixa {v_min:.1}~{v_max:.1} V)  Proteção térmica={t_max} °C");
    }
    println!("Total de servos encontrados: {}.", ids.len());
    0
}

/// Imprime o estado completo de um servo.
fn cmd_info(bus: &mut StsBus, id: u8) -> i32 {
    match bus.read_status(id) {
        Ok(s) => {
            println!("Servo ID {id}:");
            println!("  Posição  : {:>4} / 4095   ({:.1}°)", s.position, s.angle_deg());
            println!("  Velocidade: {:>4} passos/s", s.speed);
            println!("  Carga    : {:>4.1} %", s.load as f32 * 0.1);
            println!("  Tensão   : {:>4.1} V", s.voltage);
            println!("  Temperatura: {:>4} °C", s.temperature);
            println!("  Corrente : {:>4.0} mA", s.current_ma);
            println!("  Em movimento: {}", if s.moving { "sim" } else { "não" });
            if s.servo_status != 0 {
                println!("  ⚠ Alarme : código de estado 0x{:02X}", s.servo_status);
            }
            0
        }
        Err(e) => {
            eprintln!("Falha ao ler o servo {id}: {e}");
            1
        }
    }
}

/// Altera o ID do servo na EEPROM: desbloqueia (LOCK=0) → grava o ID → bloqueia (LOCK=1).
/// ⚠ Conecte somente o servo que será alterado ao barramento! Caso contrário, todos os servos com o mesmo ID serão modificados.
fn cmd_set_id(bus: &mut StsBus, old_id: u8, new_id: u8) -> i32 {
    if new_id > 253 {
        eprintln!("O novo ID deve estar entre 0 e 253 (254 é o endereço de broadcast)");
        return 2;
    }
    match bus.ping(old_id) {
        Ok(true) => println!("ID {old_id} online; preparando alteração para {new_id}..."),
        Ok(false) => {
            eprintln!("O ID {old_id} não respondeu; nenhuma alteração foi feita.");
            return 1;
        }
        Err(e) => {
            eprintln!("Falha no ping: {e}");
            return 1;
        }
    }
    // A última etapa, de bloqueio, deve ser enviada ao **novo ID**: assim que o ID é gravado, o servo
    // passa a reconhecer apenas o novo. Se a instrução for enviada ao ID antigo, ninguém a receberá
    // e a EEPROM ficará desbloqueada (55=0); qualquer gravação acidental posterior será permanente.
    // O SDK oficial da Feetech também usa LockEprom(novo ID).
    let steps = [
        (old_id, reg::LOCK, 0u8),  // Desbloqueia a EEPROM.
        (old_id, reg::ID, new_id), // Grava o novo ID; após aplicar, o servo passa a usar esse ID.
        (new_id, reg::LOCK, 1),    // Bloqueia novamente, enviando para o novo ID.
    ];
    for (id, addr, val) in steps {
        if let Err(e) = bus.write_u8(id, addr, val) {
            eprintln!("Falha ao gravar no registrador {addr}: {e}");
            return 1;
        }
        thread::sleep(Duration::from_millis(50)); // Aguarda a gravação da EEPROM terminar.
    }
    // Verifica o novo ID e lê novamente o sinalizador de bloqueio para confirmar que foi aplicado.
    match bus.ping(new_id) {
        Ok(true) => {
            let locked = bus.read_u8(new_id, reg::LOCK).unwrap_or(0);
            println!("✅ ID alterado: {old_id} -> {new_id} (continua válido após desligar e ligar)");
            if locked != 1 {
                eprintln!("⚠ O sinalizador de bloqueio retornou {locked}; a EEPROM continua desbloqueada. Bloqueie manualmente e verifique novamente após set-id.");
                return 1;
            }
            0
        }
        _ => {
            eprintln!("❌ O novo ID {new_id} não respondeu; a alteração pode ter falhado. Faça uma nova busca para confirmar.");
            1
        }
    }
}

/// Move o servo para a posição especificada e lê novamente para confirmar.
fn cmd_move(bus: &mut StsBus, id: u8, pos: u16, speed: u16, time_ms: u16) -> i32 {
    if pos > 4095 {
        eprintln!("pos fora do intervalo 0~4095");
        return 2;
    }
    if let Err(e) = bus.move_to(id, pos, speed, time_ms) {
        eprintln!("Falha ao enviar a instrução de movimento: {e}");
        return 1;
    }
    println!("Servo {id} -> alvo {pos}; aguardando chegar à posição...");
    match wait_until_arrived(bus, id, pos, Duration::from_secs(5)) {
        Ok((final_pos, _elapsed)) => {
            println!("Posição atingida: {final_pos} ({:.1}°)", final_pos as f32 * 360.0 / 4096.0);
            0
        }
        Err(e) => {
            eprintln!("Tempo esgotado ou falha ao aguardar a posição: {e}");
            1
        }
    }
}

/// Consulta até o servo atingir a posição-alvo (ou ocorrer timeout) e retorna a posição final e a duração.
fn wait_until_arrived(bus: &mut StsBus, id: u8, target: u16, timeout: Duration) -> io::Result<(u16, Duration)> {
    let start = Instant::now();
    thread::sleep(Duration::from_millis(50)); // Aguarda o servo iniciar o movimento.
    loop {
        let s = bus.read_status(id)?;
        let err = s.position.abs_diff(target);
        if !s.moving && err <= POS_TOLERANCE {
            return Ok((s.position, start.elapsed()));
        }
        if start.elapsed() > timeout {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                format!("Timeout antes de atingir a posição: alvo {target}, atual {}, diferença {err}", s.position),
            ));
        }
        thread::sleep(Duration::from_millis(20));
    }
}

/// Relatório do teste completo de um servo.
struct TestReport {
    id: u8,
    model: u16,
    voltage: f32,
    temperature: u8,
    max_current_ma: f32,
    max_load_pct: f32,
    max_pos_err: u16,
    pass: bool,
    notes: Vec<String>,
}

/// Executa um teste completo em um servo: leitura de referência → varredura de posição → amostragem de corrente/carga → retorno ao centro.
fn cmd_test(bus: &mut StsBus, id: u8) -> i32 {
    match test_one(bus, id) {
        Ok(r) => {
            print_report(&r);
            if r.pass {
                0
            } else {
                1
            }
        }
        Err(e) => {
            eprintln!("Falha no teste do servo {id}: {e}");
            1
        }
    }
}

fn test_one(bus: &mut StsBus, id: u8) -> io::Result<TestReport> {
    println!("== Testando o servo ID {id} ==");
    if !bus.ping(id)? {
        return Err(io::Error::new(io::ErrorKind::NotConnected, "O servo não respondeu"));
    }
    let model = bus.read_u16(id, reg::MODEL_NUMBER)?;
    let mut notes = Vec::new();

    // Estado de referência.
    let base = bus.read_status(id)?;
    println!("  Modelo={model}  Tensão={:.1} V  Temperatura={} °C  Posição={}", base.voltage, base.temperature, base.position);
    if base.voltage < 6.0 {
        notes.push(format!("Tensão baixa: {:.1} V; verifique a alimentação", base.voltage));
    }
    if base.servo_status != 0 {
        notes.push(format!("Alarme ativo: 0x{:02X}", base.servo_status));
    }

    // Varredura de posição e amostragem durante o movimento.
    let mut max_current = 0f32;
    let mut max_load = 0f32;
    let mut max_pos_err = 0u16;
    for &target in &TEST_POSITIONS {
        bus.move_to(id, target, 1500, 0)?;
        let start = Instant::now();
        let mut arrived = false;
        while start.elapsed() < Duration::from_secs(4) {
            let s = bus.read_status(id)?;
            max_current = max_current.max(s.current_ma.abs());
            max_load = max_load.max((s.load as f32 * 0.1).abs());
            if !s.moving && s.position.abs_diff(target) <= POS_TOLERANCE {
                arrived = true;
                break;
            }
            thread::sleep(Duration::from_millis(20));
        }
        let s = bus.read_status(id)?;
        let err = s.position.abs_diff(target);
        max_pos_err = max_pos_err.max(err);
        println!("  Alvo {target:>4} -> atual {:>4}  diferença {err:>3}  {}", s.position, if arrived { "OK" } else { "timeout" });
    }

    // Leitura final.
    let end = bus.read_status(id)?;
    if end.temperature > base.temperature + 15 {
        notes.push(format!("Aumento excessivo de temperatura: {} °C -> {} °C", base.temperature, end.temperature));
    }
    let pass = notes.is_empty() && max_pos_err <= POS_TOLERANCE;

    Ok(TestReport {
        id,
        model,
        voltage: base.voltage,
        temperature: end.temperature,
        max_current_ma: max_current,
        max_load_pct: max_load,
        max_pos_err,
        pass,
        notes,
    })
}

fn print_report(r: &TestReport) {
    println!("-- Relatório do servo {} --", r.id);
    println!("  Modelo={}  Tensão={:.1} V  Temperatura={} °C", r.model, r.voltage, r.temperature);
    println!("  Corrente máxima={:.0} mA  Carga máxima={:.1}%  Maior desvio de posição={}", r.max_current_ma, r.max_load_pct, r.max_pos_err);
    for n in &r.notes {
        println!("  ⚠ {n}");
    }
    println!("  Resultado: {}", if r.pass { "✅ PASSOU" } else { "❌ FALHOU" });
}

/// Busca todos os servos, testa cada um e exibe um resumo final.
fn cmd_test_all(bus: &mut StsBus, from: u8, to: u8) -> i32 {
    let ids = scan_with_progress(bus, from, to);
    if ids.is_empty() {
        println!("Nenhum servo encontrado.");
        return 1;
    }
    println!("Servos encontrados: {} — {:?}\n", ids.len(), ids);

    let mut reports = Vec::new();
    for &id in &ids {
        match test_one(bus, id) {
            Ok(r) => {
                print_report(&r);
                reports.push(r);
            }
            Err(e) => {
                eprintln!("Exceção durante o teste do servo {id}: {e}");
                reports.push(TestReport {
                    id, model: 0, voltage: 0.0, temperature: 0,
                    max_current_ma: 0.0, max_load_pct: 0.0, max_pos_err: u16::MAX,
                    pass: false, notes: vec![format!("Exceção no teste: {e}")],
                });
            }
        }
        println!();
    }

    // Tabela de resumo.
    println!("==== Resumo dos testes em lote ====");
    println!("{:<4} {:<8} {:<8} {:<6} {:<10} {:<10} {:<8} Resultado", "ID", "Modelo", "Tensão V", "Temp. °C", "Corrente máx. mA", "Carga máx. %", "Desvio posição");
    for r in &reports {
        println!(
            "{:<4} {:<8} {:<8.1} {:<6} {:<10.0} {:<10.1} {:<8} {}",
            r.id, r.model, r.voltage, r.temperature, r.max_current_ma, r.max_load_pct, r.max_pos_err,
            if r.pass { "PASS" } else { "FAIL" }
        );
    }
    if reports.iter().all(|r| r.pass) { 0 } else { 1 }
}
