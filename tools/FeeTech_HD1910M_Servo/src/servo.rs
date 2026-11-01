//! servo.rs — camada de driver do servo: envia pacotes de protocolo pela serial e analisa as respostas
//!
//! [Revisão da arquitetura em camadas]
//!   protocol.rs  dados puros: monta/analisa pacotes (sem hardware, testável)
//!   registers.rs dados puros: define a tabela de memória (sem hardware, testável)
//!   servo.rs     esta camada: abre a serial, envia/recebe bytes e trata timeouts e erros
//!   main.rs      camada externa: analisa a linha de comando e chama esta camada para executar as operações solicitadas
//!
//! [Conceito de Rust: objeto trait Box<dyn SerialPort>]
//! A biblioteca serialport usa tipos diferentes para implementar a serial em cada sistema operacional.
//! `Box<dyn SerialPort>` representa algum tipo no heap que implementa o trait SerialPort.
//! Não precisamos saber qual é o tipo concreto, desde que ofereça read/write. Isso é
//! despacho dinâmico em Rust, semelhante a uma referência de interface em Java, com a abstração escolhida sob demanda.

use std::io::{Read, Write};
use std::time::Duration;

use serialport::SerialPort;

use crate::error::{Result, ServoError};
use crate::protocol::{self, Instruction, StatusPacket, BROADCAST_ID};
use crate::registers::{self, Register};

/// Driver do servo, que possui um handle exclusivo da porta serial.
///
/// [Conceito de Rust: ownership garante acesso exclusivo]
/// A porta serial é um recurso exclusivo: somente um lugar pode transmitir ou receber por vez.
/// O sistema de ownership do Rust garante isso em tempo de compilação: Servo possui o handle,
/// e o acesso ao servo exige `&mut self` (empréstimo mutável), do qual só pode existir um ao mesmo tempo.
/// Assim, a linguagem impede que duas threads leiam e escrevam simultaneamente e corrompam os pacotes.
pub struct Servo {
    port: Box<dyn SerialPort>,
    /// Em uma ligação simples com TX e RX conectados diretamente, os dados enviados retornam ao próprio dispositivo.
    /// Se true, descarta esse eco depois de cada envio antes de ler a resposta.
    discard_echo: bool,
    /// Indica se os pacotes brutos enviados e recebidos devem ser exibidos (útil para estudar o protocolo).
    verbose: bool,
}

/// Dados de feedback em tempo real do servo (lidos de uma vez dos endereços 56 a 69 da tabela de memória).
///
/// [Conceito de Rust: derivar Debug para uma struct]
/// #[derive(Debug)] permite imprimir a struct inteira com `println!("{fb:?}")`, o que facilita a depuração.
#[derive(Debug)]
pub struct Feedback {
    /// Posição atual (0,087 grau/unidade, com bit de direção; inclui o número de voltas no modo multivoltas).
    pub pos: i64,
    /// Velocidade atual (0,732 RPM/unidade, com bit de direção).
    pub vel: i64,
    /// Carga/duty cycle atual (0,1%/unidade, BIT10 indica a direção).
    pub load: i64,
    /// Tensão atual em V, convertida para ponto flutuante.
    pub voltage: f64,
    /// Temperatura atual (°C).
    pub temp: i64,
    /// Status do servo (0 = normal; falhas codificadas por bits).
    pub status: u8,
    /// Indicador de movimento.
    pub moving: u8,
    /// Corrente atual em mA, convertida para ponto flutuante e com direção.
    pub current: f64,
}

impl Servo {
    /// Abre a porta serial e cria o driver.
    ///
    /// [Conceito de Rust: operador ?]
    /// `serialport::new(...).open()?` converte a falha em ServoError e retorna imediatamente
    /// (a conversão é feita automaticamente por #[from] em error.rs); em caso de sucesso, continua.
    /// Isso mantém o tratamento de erros rigoroso e conciso.
    pub fn connect(path: &str, baud: u32, timeout_ms: u64, discard_echo: bool, verbose: bool) -> Result<Self> {
        let port = serialport::new(path, baud)
            .timeout(Duration::from_millis(timeout_ms)) // Tempo máximo de espera de cada read.
            .data_bits(serialport::DataBits::Eight)     // 8 bits de dados.
            .parity(serialport::Parity::None)           // Sem paridade.
            .stop_bits(serialport::StopBits::One)       // 1 bit de parada — especificação 7-2: 8 bits, 1 parada, sem paridade.
            .open()?;
        Ok(Servo { port, discard_echo, verbose })
    }

    // =========================================================================
    // Comunicação de baixo nível.
    // =========================================================================

    /// Envia uma instrução, aguarda a resposta e retorna o pacote analisado.
    /// Este é o canal comum para todas as instruções.
    fn transact(&mut self, id: u8, inst: Instruction, params: &[u8], expect_reply: bool) -> Result<StatusPacket> {
        let pkt = protocol::build_packet(id, inst, params);

        // Limpa bytes residuais no buffer de entrada (fim da comunicação anterior, ruído etc.),
        // evitando que dados antigos sejam confundidos com a resposta atual.
        let _ = self.port.clear(serialport::ClearBuffer::Input);

        if self.verbose {
            eprintln!("  >> Enviado: {:02X?}", pkt);
        }

        // [Conceito de Rust: passagem de &mut self]
        // write_all exige um empréstimo mutável da serial. Como transact já emprestou &mut self,
        // o compilador garante que ninguém mais acessará esta porta durante a operação.
        self.port.write_all(&pkt)?;
        self.port.flush()?;

        // Em uma ligação simples (TX/RX em curto), primeiro chegam de volta os bytes enviados; descarte a mesma quantidade.
        if self.discard_echo {
            let mut echo = vec![0u8; pkt.len()];
            let _ = self.port.read_exact(&mut echo);
        }

        // O endereço de broadcast não responde; com nível de resposta 0, instruções de escrita também não respondem.
        if !expect_reply || id == BROADCAST_ID {
            return Ok(StatusPacket { id, error: 0, params: Vec::new() });
        }

        let raw = self.recv_packet()?;
        if self.verbose {
            eprintln!("  << Recebido: {:02X?}", raw);
        }
        let status = protocol::parse_status(&raw)?;
        // Confere se o ID do servo que respondeu é o mesmo solicitado.
        // Pode haver vários servos no barramento; receber uma resposta de outro indica um problema de temporização.
        if status.id != id {
            return Err(ServoError::Malformed("o ID do pacote de resposta não corresponde ao solicitado".into()));
        }
        if status.error != 0 {
            return Err(ServoError::ServoStatus(
                status.error,
                protocol::describe_status(status.error),
            ));
        }
        Ok(status)
    }

    /// Lê um pacote de resposta completo da serial (localiza o cabeçalho byte a byte, lê ID/Length e depois os bytes restantes).
    ///
    /// [Conceito de Rust: converter timeout de E/S em erro da aplicação]
    /// Um timeout de leitura serial aparece como io::ErrorKind::TimedOut; convertemos para
    /// ServoError::Timeout para que a camada superior receba um erro mais significativo.
    fn recv_packet(&mut self) -> Result<Vec<u8>> {
        // Etapa 1: percorre os bytes até encontrar o cabeçalho 0xFF 0xFF.
        // Pode haver ruído no barramento; não presuma que o primeiro byte recebido seja o cabeçalho.
        let mut window = [0u8; 2]; // Janela deslizante que guarda os dois bytes recebidos mais recentemente.
        let mut found = false;
        for _ in 0..64 {
            // Percorre no máximo 64 bytes; se não encontrar, desiste.
            let mut b = [0u8; 1];
            self.port.read_exact(&mut b).map_err(|e| match e.kind() {
                std::io::ErrorKind::TimedOut => ServoError::Timeout,
                _ => ServoError::Io(e),
            })?;
            window[0] = window[1];
            window[1] = b[0];
            if window == protocol::HEADER {
                found = true;
                break;
            }
        }
        if !found {
            return Err(ServoError::Malformed("não foi possível encontrar o cabeçalho 0xFF 0xFF".into()));
        }

        // Etapa 2: lê ID e Length.
        let mut head = [0u8; 2];
        self.port.read_exact(&mut head).map_err(|e| match e.kind() {
            std::io::ErrorKind::TimedOut => ServoError::Timeout,
            _ => ServoError::Io(e),
        })?;
        let length = head[1] as usize;

        // Etapa 3: lê os bytes restantes indicados por Length (Error + parâmetros + checksum).
        let mut rest = vec![0u8; length];
        self.port.read_exact(&mut rest).map_err(|e| match e.kind() {
            std::io::ErrorKind::TimedOut => ServoError::Timeout,
            _ => ServoError::Io(e),
        })?;

        // Monta o quadro completo e o entrega à camada de protocolo para análise.
        let mut full = Vec::with_capacity(4 + length);
        full.extend_from_slice(&protocol::HEADER);
        full.extend_from_slice(&head);
        full.extend_from_slice(&rest);
        Ok(full)
    }

    // =========================================================================
    // API de instruções (corresponde diretamente às instruções do protocolo).
    // =========================================================================

    /// Handshake PING: retorna Ok(true) se o servo estiver online, Ok(false) em caso de timeout e propaga os demais erros.
    ///
    /// [Conceito de Rust: tratar cada tipo de erro com match]
    /// Um timeout significa apenas que não há servo neste ID; os outros erros indicam falhas reais.
    pub fn ping(&mut self, id: u8) -> Result<bool> {
        match self.transact(id, Instruction::Ping, &[], true) {
            Ok(_) => Ok(true),
            Err(ServoError::Timeout) => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Lê len bytes da memória a partir de addr.
    pub fn read(&mut self, id: u8, addr: u8, len: u8) -> Result<Vec<u8>> {
        let resp = self.transact(id, Instruction::Read, &[addr, len], true)?;
        Ok(resp.params)
    }

    /// Escreve data na memória a partir de addr (efeito imediato).
    pub fn write(&mut self, id: u8, addr: u8, data: &[u8]) -> Result<()> {
        // Parâmetros = [endereço inicial, dados...], montados com um iterador.
        let mut params = Vec::with_capacity(data.len() + 1);
        params.push(addr);
        params.extend_from_slice(data);
        self.transact(id, Instruction::Write, &params, true)?;
        Ok(())
    }

    /// Escrita registrada (REG WRITE): armazena primeiro e executa quando action() é transmitido.
    /// Uso típico: registra a posição desejada em vários servos e envia um único ACTION de broadcast
    /// para que todos iniciem ao mesmo tempo — base da sincronização de vários eixos.
    pub fn reg_write(&mut self, id: u8, addr: u8, data: &[u8]) -> Result<()> {
        let mut params = Vec::with_capacity(data.len() + 1);
        params.push(addr);
        params.extend_from_slice(data);
        self.transact(id, Instruction::RegWrite, &params, true)?;
        Ok(())
    }

    /// ACTION de broadcast: executa o conteúdo REG_WRITE armazenado nos servos.
    pub fn action(&mut self) -> Result<()> {
        self.transact(BROADCAST_ID, Instruction::Action, &[], false)?;
        Ok(())
    }

    /// Escrita sincronizada (SYNC WRITE 0x83): um pacote grava o mesmo registrador em vários servos.
    ///
    /// Estrutura do pacote (ID de broadcast, sem resposta):
    ///   FF FF FE Length 0x83 endereço inicial tamanho dos dados [ID1 dados...] [ID2 dados...]... Checksum
    ///
    /// Exemplo: seis juntas de um braço robótico precisam receber a posição desejada “ao mesmo tempo”.
    /// Escritas individuais criariam dezenas de milissegundos de diferença; uma escrita sincronizada entrega tudo em um único pacote.
    pub fn sync_write(&mut self, ids: &[u8], reg: &Register, value: i64) -> Result<()> {
        if ids.is_empty() {
            return Err(ServoError::InvalidParam("a escrita sincronizada exige pelo menos um ID de destino".into()));
        }
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let data: Vec<u8> = if reg.size == 1 {
            vec![val as u8]
        } else {
            val.to_le_bytes().to_vec()
        };

        // Monta os parâmetros: endereço inicial + tamanho dos dados por servo + [ID, dados...] de cada servo.
        let mut params = Vec::with_capacity(2 + ids.len() * (1 + data.len()));
        params.push(reg.addr);
        params.push(data.len() as u8);
        for &id in ids {
            params.push(id);
            params.extend_from_slice(&data);
        }
        // A escrita sincronizada é uma instrução de broadcast; os servos não respondem.
        self.transact(BROADCAST_ID, Instruction::SyncWrite, &params, false)?;
        Ok(())
    }

    /// Restaura as configurações de fábrica (todos os valores EPROM dos endereços 5 a 39 voltam ao padrão).
    pub fn factory_reset(&mut self, id: u8) -> Result<()> {
        self.transact(id, Instruction::Reset, &[], true)?;
        Ok(())
    }

    /// Reinicia o servo (0x08): equivale a desligá-lo e ligá-lo, recarregando a SRAM da EPROM.
    /// Usado para verificar se a gravação na EPROM foi persistida (também usado pelo robotd ao trocar um servo).
    pub fn reboot(&mut self, id: u8) -> Result<()> {
        self.transact(id, Instruction::Reboot, &[], true)?;
        Ok(())
    }

    /// Calibração de posição (0x0B): define novamente a posição atual do servo para a leitura target.
    /// (None = posição central 2048, como no botão “Definir zero” do software de diagnóstico Feetech FD.)
    ///
    /// O servo calcula e altera automaticamente o registrador de deslocamento de posição 31.
    /// [Atenção] O HD-1910 (firmware HLS >= 3.43) não aceita o método antigo de calibração “gravar 128 no torque switch”; use esta instrução.
    /// A Feetech pode responder “sucesso” mesmo para operações não suportadas,
    /// portanto, após calibrar, leia a posição e o registrador de deslocamento para confirmar (consulte o comando zero).
    pub fn calibrate(&mut self, id: u8, target: Option<u16>) -> Result<()> {
        let params = match target {
            Some(t) => t.to_le_bytes().to_vec(), // Little-endian: o byte menos significativo vem primeiro.
            None => Vec::new(),
        };
        self.transact(id, Instruction::Calibrate, &params, true)?;
        Ok(())
    }

    // =========================================================================
    // API de registradores (usa a tabela de memória para tratar bytes múltiplos, bit de sinal e validação de faixa).
    // =========================================================================

    /// Lê um registrador e decodifica como inteiro com sinal (trata automaticamente little-endian e sinal-magnitude).
    pub fn read_reg(&mut self, id: u8, reg: &Register) -> Result<i64> {
        let raw = self.read(id, reg.addr, reg.size)?;
        if raw.len() < reg.size as usize {
            return Err(ServoError::Malformed("os dados lidos são muito curtos".into()));
        }
        // Montagem little-endian: o endereço mais baixo contém o byte menos significativo (seção 2 da documentação).
        let val = if reg.size == 1 {
            raw[0] as u16
        } else {
            u16::from_le_bytes([raw[0], raw[1]])
        };
        Ok(registers::decode_value(val, reg.sign_bit))
    }

    /// Escreve em um registrador (valida a faixa, codifica sinal-magnitude e separa em bytes little-endian).
    ///
    /// Atenção: esta função grava diretamente. Para persistir uma gravação na área EPROM após desligar, use save_reg().
    pub fn write_reg(&mut self, id: u8, reg: &Register, value: i64) -> Result<()> {
        // [Programação defensiva] Valida antes de gravar: rejeita registradores somente leitura e valores fora da faixa.
        // A tabela de memória é nosso schema; detectar erros antes do envio é melhor que provocar um comportamento inesperado do servo.
        if reg.access == registers::Access::ReadOnly {
            return Err(ServoError::InvalidParam(format!(
                "o registrador {} ({}) é somente leitura e não pode ser gravado",
                reg.key, reg.cn
            )));
        }
        reg.check_value(value)?;
        let val = registers::encode_value(value, reg.sign_bit);
        let bytes = if reg.size == 1 {
            vec![val as u8]
        } else {
            val.to_le_bytes().to_vec() // Little-endian: envia primeiro o byte menos significativo.
        };
        self.write(id, reg.addr, &bytes)
    }

    /// Grava um registrador EPROM e persiste o valor após desligar.
    ///
    /// [Mecanismo importante: flag de bloqueio (endereço 55)]
    ///   Bloqueio=1 (padrão): gravações na área EPROM alteram apenas a memória e não persistem após desligar;
    ///   Bloqueio=0: gravações na área EPROM são persistidas.
    /// Portanto, o fluxo é: desbloquear (gravar 0) → gravar o registrador desejado → bloquear novamente (gravar 1).
    ///
    /// [Por que não deixar sempre desbloqueado?] A EPROM tem vida útil de aproximadamente 100 mil ciclos de gravação.
    /// Mantê-la bloqueada evita que um bug cause gravações repetidas e danifique o servo.
    pub fn save_reg(&mut self, id: u8, reg: &Register, value: i64) -> Result<()> {
        if reg.area != registers::Area::Eprom {
            // A área SRAM já tem efeito imediato e perde os dados ao desligar; não precisa do fluxo de desbloqueio.
            return self.write_reg(id, reg, value);
        }
        let lock = registers::find_register("lock").expect("o registrador lock deve existir");
        self.write_reg(id, lock, 0)?; // Desbloqueia.
        let result = self.write_reg(id, reg, value);
        // Bloqueia novamente mesmo que a gravação falhe; guarda o resultado antes de usar `?` para não deixar o servo desbloqueado.
        let relock = self.write_reg(id, lock, 1);
        result.and(relock)
    }

    // =========================================================================
    // API de alto nível (métodos convenientes para cenários de teste).
    // =========================================================================

    /// Lê todo o feedback em tempo real de uma vez (15 bytes dos endereços 56 a 70; uma leitura é muito mais rápida que várias).
    pub fn read_feedback(&mut self, id: u8) -> Result<Feedback> {
        let raw = self.read(id, 56, 15)?;
        if raw.len() < 15 {
            return Err(ServoError::Malformed("os dados de feedback são muito curtos".into()));
        }
        // Closure auxiliar para obter um valor little-endian de dois bytes.
        let u16le = |i: usize| u16::from_le_bytes([raw[i], raw[i + 1]]);
        Ok(Feedback {
            pos: registers::decode_value(u16le(0), Some(15)),        // 56: posição atual.
            vel: registers::decode_value(u16le(2), Some(15)),        // 58: velocidade atual.
            load: registers::decode_value(u16le(4), Some(10)),       // 60: carga atual; BIT10 indica a direção.
            voltage: raw[6] as f64 / 10.0,                           // 62: tensão em unidades de 0,1 V.
            temp: raw[7] as i64,                                     // 63: temperatura em °C.
            status: raw[9],                                          // 65: status do servo.
            moving: raw[10],                                         // 66: indicador de movimento.
            current: registers::decode_value(u16le(13), Some(15)) as f64 * 6.5, // 69: corrente em unidades de 6,5 mA.
        })
    }
}
