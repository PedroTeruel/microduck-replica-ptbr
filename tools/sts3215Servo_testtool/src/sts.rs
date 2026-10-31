//! Implementação mínima do protocolo de comunicação serial FEETECH STS/SCS para servos STS3215.
//!
//! Formato do quadro (bytes enviados via UART, padrão de 1.000.000 baud, 8N1):
//!   [0xFF, 0xFF, ID, LENGTH, INSTRUCTION, PARAM1..PARAMn, CHECKSUM]
//!   - LENGTH    = número de bytes de parâmetros + 2 (byte de instrução + byte de checksum)
//!   - CHECKSUM  = 8 bits inferiores de ~(ID + LENGTH + INSTRUCTION + todos os parâmetros)
//!
//! O quadro de resposta do servo usa o mesmo formato, mas substitui INSTRUCTION pelo byte de estado ERROR.

use serialport::SerialPort;
use std::io::{self, ErrorKind};
use std::time::{Duration, Instant};

// ---- Códigos de instrução ----
pub const INST_PING: u8 = 0x01;
pub const INST_READ: u8 = 0x02;
pub const INST_WRITE: u8 = 0x03;

/// Mapa de memória do STS3215 (endereços de registradores comuns).
/// Conferido com o SDK oficial da Feetech `sms_sts.py` (FTServo_Python).
#[allow(dead_code)] // Mantém a tabela completa de registradores como referência.
pub mod reg {
    // ---- EPROM somente leitura ----
    pub const FIRMWARE: u8 = 0; // 3 bytes, versão do firmware.
    pub const MODEL_NUMBER: u8 = 3; // u16, modelo.
    // ---- EPROM leitura/escrita (desbloqueie com LOCK=0 antes de alterar) ----
    pub const ID: u8 = 5; // u8, ID do servo.
    pub const BAUD_RATE: u8 = 6; // u8, índice da taxa baud: 0=1M, 4=115200...
    pub const MIN_POSITION: u8 = 9; // u16, limite mínimo do ângulo.
    pub const MAX_POSITION: u8 = 11; // u16, limite máximo do ângulo.
    pub const MAX_TEMPERATURE: u8 = 13; // u8, proteção de temperatura máxima.
    pub const MAX_VOLTAGE: u8 = 14; // u8, tensão máxima, unidade 0,1 V.
    pub const MIN_VOLTAGE: u8 = 15; // u8, tensão mínima, unidade 0,1 V.
    pub const MODE: u8 = 33; // u8, 0=modo posição, 1=modo roda.
    // ---- SRAM leitura/escrita ----
    pub const TORQUE_ENABLE: u8 = 40; // u8, torque: 1=travado, 0=liberado.
    pub const ACCELERATION: u8 = 41; // u8, aceleração.
    pub const GOAL_POSITION: u8 = 42; // u16, posição-alvo 0~4095.
    pub const GOAL_TIME: u8 = 44; // u16, tempo de movimento em ms.
    pub const GOAL_SPEED: u8 = 46; // u16, velocidade de movimento em passos/s.
    pub const TORQUE_LIMIT: u8 = 48; // u16, limite de torque.
    pub const LOCK: u8 = 55; // u8, bloqueio da EEPROM: 0=desbloqueada, 1=bloqueada.
    // ---- SRAM somente leitura ----
    pub const PRESENT_POSITION: u8 = 56; // u16, posição atual 0~4095.
    pub const PRESENT_SPEED: u8 = 58; // u16, velocidade atual.
    pub const PRESENT_LOAD: u8 = 60; // u16, bits 0~9=valor, bit 10=sentido, unidade 0,1%.
    pub const PRESENT_VOLTAGE: u8 = 62; // u8, tensão atual, unidade 0,1 V.
    pub const PRESENT_TEMPERATURE: u8 = 63; // u8, temperatura atual em °C.
    pub const SERVO_STATUS: u8 = 65; // u8, estado do servo (bits de alarme).
    pub const MOVING: u8 = 66; // u8, indica se está em movimento.
    pub const PRESENT_CURRENT: u8 = 69; // u16, corrente atual, aproximadamente 6,5 mA por unidade.
}

/// Estado em tempo real do servo, decodificado a partir de 15 bytes lidos desde o endereço 56.
#[derive(Debug, Clone)]
pub struct ServoStatus {
    pub position: u16,    // 0~4095
    pub speed: i16,       // passos/s (com sentido).
    pub load: i16,        // 0,1% (com sentido).
    pub voltage: f32,     // V
    pub temperature: u8,  // °C
    pub servo_status: u8, // Diferente de zero indica alarme (sobretensão, sobrecorrente, superaquecimento etc.).
    pub moving: bool,
    pub current_ma: f32, // mA
}

impl ServoStatus {
    /// Converte a posição 0~4095 em ângulo (graus).
    pub fn angle_deg(&self) -> f32 {
        self.position as f32 * 360.0 / 4096.0
    }
}

/// Barramento aberto. Toda a comunicação com os servos passa por ele.
pub struct StsBus {
    port: Box<dyn SerialPort>,
    /// Tempo máximo de espera para uma leitura de pacote.
    timeout: Duration,
}

impl StsBus {
    /// Abre a porta serial, por exemplo StsBus::open("/dev/ttyUSB0", 1_000_000).
    pub fn open(path: &str, baud: u32) -> io::Result<Self> {
        let port = serialport::new(path, baud)
            .data_bits(serialport::DataBits::Eight)
            .stop_bits(serialport::StopBits::One)
            .parity(serialport::Parity::None)
            .flow_control(serialport::FlowControl::None)
            .timeout(Duration::from_millis(20))
            .open()?;
        Ok(Self {
            port,
            timeout: Duration::from_millis(150),
        })
    }

    fn checksum(bytes: &[u8]) -> u8 {
        !bytes.iter().fold(0u8, |acc, b| acc.wrapping_add(*b))
    }

    /// Envia um quadro de instrução.
    fn send_packet(&mut self, id: u8, inst: u8, params: &[u8]) -> io::Result<()> {
        let len = params.len() as u8 + 2;
        let mut pkt = Vec::with_capacity(6 + params.len());
        pkt.extend_from_slice(&[0xFF, 0xFF, id, len, inst]);
        pkt.extend_from_slice(params);
        pkt.push(Self::checksum(&pkt[2..]));
        self.port.write_all(&pkt)?;
        self.port.flush()
    }

    /// Lê n bytes antes do prazo limite.
    fn read_n(&mut self, n: usize, deadline: Instant) -> io::Result<Vec<u8>> {
        let mut buf = vec![0u8; n];
        let mut got = 0;
        while got < n {
            match self.port.read(&mut buf[got..]) {
                Ok(0) => {}
                Ok(k) => got += k,
                Err(e) if e.kind() == ErrorKind::TimedOut => {
                    if Instant::now() >= deadline {
                        return Err(io::Error::new(
                            ErrorKind::TimedOut,
                            "Tempo esgotado aguardando resposta do servo",
                        ));
                    }
                }
                Err(e) => return Err(e),
            }
        }
        Ok(buf)
    }

    /// Recebe um quadro de resposta e retorna (id, error, parâmetros).
    fn recv_packet(&mut self) -> io::Result<(u8, u8, Vec<u8>)> {
        let deadline = Instant::now() + self.timeout;
        // 1. Desliza byte a byte até encontrar o cabeçalho 0xFF 0xFF.
        let mut prev = self.read_n(1, deadline)?[0];
        loop {
            let cur = self.read_n(1, deadline)?[0];
            if prev == 0xFF && cur == 0xFF {
                break;
            }
            prev = cur;
        }
        // 2. id + length
        let head = self.read_n(2, deadline)?;
        let (id, len) = (head[0], head[1] as usize);
        // 3. error + parâmetros + checksum (length já inclui esses dois bytes).
        let body = self.read_n(len, deadline)?;
        let mut all = vec![id, len as u8];
        all.extend_from_slice(&body);
        if Self::checksum(&all) != 0x00 {
            let hex: Vec<String> = all.iter().map(|b| format!("{b:02X}")).collect();
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                format!("Checksum inválido; bytes recebidos: {}", hex.join(" ")),
            ));
        }
        let error = body[0];
        let params = body[1..body.len() - 1].to_vec();
        Ok((id, error, params))
    }

    /// Recebe um quadro de resposta. Alguns adaptadores ecoam no RX os bytes enviados; o quadro ecoado
    /// é idêntico ao enviado (o campo "error" coincide com o código de instrução). Porém, a resposta
    /// a ping de um servo em alarme (error=0x01) não pode ser distinguida do eco de ping apenas pelos
    /// bytes. Estratégia: se o primeiro quadro parecer um eco, aguarda um segundo; se não chegar,
    /// trata o primeiro como a resposta real.
    fn recv_non_echo(&mut self, sent_id: u8, sent_inst: u8, sent_params: &[u8]) -> io::Result<(u8, u8, Vec<u8>)> {
        let first = self.recv_packet()?;
        let looks_like_echo = first.0 == sent_id && first.1 == sent_inst && first.2 == sent_params;
        if !looks_like_echo {
            return Ok(first);
        }
        match self.recv_packet() {
            Ok(second) => Ok(second), // Se há um segundo quadro, o primeiro era o eco.
            Err(e) if e.kind() == ErrorKind::TimedOut => Ok(first), // Sem segundo quadro, o primeiro é a resposta.
            Err(e) => Err(e),
        }
    }

    /// Configura as linhas de controle RTS / DTR (alguns adaptadores as usam para direção ou habilitação da transmissão).
    pub fn set_rts(&mut self, on: bool) -> io::Result<()> {
        self.port
            .write_request_to_send(on)
            .map_err(|e| io::Error::new(ErrorKind::Other, e.to_string()))
    }
    pub fn set_dtr(&mut self, on: bool) -> io::Result<()> {
        self.port
            .write_data_terminal_ready(on)
            .map_err(|e| io::Error::new(ErrorKind::Other, e.to_string()))
    }

    /// Faz uma varredura do barramento e retorna os IDs dos servos que responderem.
    #[allow(dead_code)] // Mantido como API da biblioteca; a CLI usa a versão com barra de progresso.
    pub fn scan(&mut self, from: u8, to: u8) -> Vec<u8> {
        let mut found = Vec::new();
        for id in from..=to {
            if self.ping(id).unwrap_or(false) {
                found.push(id);
            }
        }
        found
    }

    /// Para diagnóstico: envia um quadro arbitrário e retorna os bytes brutos recebidos nos 500 ms seguintes.
    /// Retorna (bytes enviados, bytes recebidos).
    pub fn raw_exchange(&mut self, id: u8, inst: u8, params: &[u8]) -> io::Result<(Vec<u8>, Vec<u8>)> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        // Remonta o conteúdo enviado para exibição.
        let len = params.len() as u8 + 2;
        let mut sent = vec![0xFF, 0xFF, id, len, inst];
        sent.extend_from_slice(params);
        sent.push(Self::checksum(&sent[2..]));

        self.port.write_all(&sent)?;
        self.port.flush()?;

        let deadline = Instant::now() + Duration::from_millis(500);
        let mut out = Vec::new();
        let mut buf = [0u8; 64];
        while Instant::now() < deadline {
            match self.port.read(&mut buf) {
                Ok(n) if n > 0 => out.extend_from_slice(&buf[..n]),
                Ok(_) => {}
                Err(e) if e.kind() == ErrorKind::TimedOut => {}
                Err(e) => return Err(e),
            }
        }
        Ok((sent, out))
    }

    /// Verifica se há um servo online em determinado ID.
    /// O byte error da resposta representa o estado de alarme do servo (por exemplo, bit0=tensão anormal);
    /// mesmo com alarme, o servo é considerado online.
    pub fn ping(&mut self, id: u8) -> io::Result<bool> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        self.send_packet(id, INST_PING, &[])?;
        match self.recv_non_echo(id, INST_PING, &[]) {
            Ok((rid, _err, _)) => Ok(rid == id),
            Err(e) if e.kind() == ErrorKind::TimedOut => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Lê len bytes do servo (len <= 250).
    /// O byte error (estado de alarme) não é considerado falha; os dados são retornados normalmente.
    pub fn read(&mut self, id: u8, addr: u8, len: u8) -> io::Result<Vec<u8>> {
        self.port.clear(serialport::ClearBuffer::Input)?;
        self.send_packet(id, INST_READ, &[addr, len])?;
        let (rid, _err, params) = self.recv_non_echo(id, INST_READ, &[addr, len])?;
        if rid != id {
            return Err(io::Error::new(
                ErrorKind::InvalidData,
                format!("ID da resposta divergente: esperado {id}, recebido {rid}"),
            ));
        }
        Ok(params)
    }

    pub fn read_u8(&mut self, id: u8, addr: u8) -> io::Result<u8> {
        Ok(self.read(id, addr, 1)?[0])
    }

    /// u16 usa little-endian (byte menos significativo primeiro).
    pub fn read_u16(&mut self, id: u8, addr: u8) -> io::Result<u16> {
        let b = self.read(id, addr, 2)?;
        Ok(u16::from_le_bytes([b[0], b[1]]))
    }

    /// Grava bytes (em registradores SRAM; é normal o servo não responder).
    pub fn write(&mut self, id: u8, addr: u8, data: &[u8]) -> io::Result<()> {
        let mut params = vec![addr];
        params.extend_from_slice(data);
        self.send_packet(id, INST_WRITE, &params)?;
        // Descarta a resposta à instrução de gravação (se habilitada), sem bloquear.
        let _ = self.recv_packet();
        Ok(())
    }

    pub fn write_u8(&mut self, id: u8, addr: u8, v: u8) -> io::Result<()> {
        self.write(id, addr, &[v])
    }

    #[allow(dead_code)] // Mantido como API da biblioteca.
    pub fn write_u16(&mut self, id: u8, addr: u8, v: u16) -> io::Result<()> {
        self.write(id, addr, &v.to_le_bytes())
    }

    /// Controle de torque: true=travado (controlável), false=liberado (pode ser movido à mão).
    pub fn set_torque(&mut self, id: u8, enable: bool) -> io::Result<()> {
        self.write_u8(id, reg::TORQUE_ENABLE, enable as u8)
    }

    /// Move o servo para a posição-alvo (0~4095); speed em passos/s e time_ms como duração desejada.
    /// Segue o WritePosEx do SDK oficial: grava sete bytes de uma vez a partir de ACCELERATION(41).
    pub fn move_to(&mut self, id: u8, pos: u16, speed: u16, time_ms: u16) -> io::Result<()> {
        self.set_torque(id, true)?;
        let pos = pos.min(4095);
        let mut data = Vec::with_capacity(7);
        data.push(50); // Aceleração.
        data.extend_from_slice(&pos.to_le_bytes());
        data.extend_from_slice(&time_ms.to_le_bytes());
        data.extend_from_slice(&speed.to_le_bytes());
        self.write(id, reg::ACCELERATION, &data)
    }

    /// Lê de uma vez 15 bytes desde o endereço 56 e decodifica em ServoStatus.
    pub fn read_status(&mut self, id: u8) -> io::Result<ServoStatus> {
        let b = self.read(id, reg::PRESENT_POSITION, 15)?;
        // b[0..2] posição   b[2..4] velocidade  b[4..6] carga
        // b[6] tensão b[7] temperatura  b[8] indicador de gravação  b[9] estado
        // b[10] em movimento  b[11..13] reservado  b[13..15] corrente
        let position = u16::from_le_bytes([b[0], b[1]]);
        let speed = sts_signed(i16::from_le_bytes([b[2], b[3]]));
        let load_raw = u16::from_le_bytes([b[4], b[5]]);
        // Carga: bits 0~9 indicam o valor (0,1%); bit 10 indica o sentido.
        let load = if load_raw & 0x0400 != 0 {
            -((load_raw & 0x03FF) as i16)
        } else {
            (load_raw & 0x03FF) as i16
        };
        let current_raw = i16::from_le_bytes([b[13], b[14]]);
        let current_ma = sts_signed(current_raw) as f32 * 6.5;
        Ok(ServoStatus {
            position,
            speed,
            load,
            voltage: b[6] as f32 * 0.1,
            temperature: b[7],
            servo_status: b[9],
            moving: b[10] != 0,
            current_ma,
        })
    }
}

/// Inteiro com sinal de dois bytes no protocolo Feetech: bit15 é o sinal e os 15 bits inferiores são o valor.
fn sts_signed(v: i16) -> i16 {
    if v & (1 << 15) != 0 {
        -(v & !(1 << 15))
    } else {
        v
    }
}
