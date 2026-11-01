//! protocol.rs — protocolo serial personalizado FT-SCS (protocolo proprietário dos servos Feetech)
//!
//! [Formato do quadro do protocolo — pacote enviado pelo host]
//! ```text
//!   Índice do byte: 0     1     2      3         4          5..N+4    N+5
//!   Conteúdo:      0xFF  0xFF   ID   Length   Instruction   params... Checksum
//! ```
//!   - Cabeçalho: dois bytes 0xFF fixos, usados pelo receptor para localizar o início do quadro;
//!   - ID: endereço do servo de destino, 0 a 253; 0xFE (254) é o endereço de broadcast (todos recebem, nenhum responde);
//!   - Length = número de parâmetros N + 2 (1 byte de instrução + 1 byte de checksum);
//!   - Checksum = soma de ID + Length + Instruction + todos os parâmetros,
//!     complemento de um (~), mantendo apenas os 8 bits inferiores. O receptor recalcula e descarta o quadro se houver divergência.
//!
//! [Pacote de resposta do servo] O formato é quase igual, mas o quarto byte é o status de erro em vez da instrução:
//! ```text
//!   0xFF  0xFF   ID   Length   Error   params... Checksum
//! ```
//!
//! [Conceito de Rust: por que esta camada não acessa a porta serial?]
//! Esta camada apenas converte dados entre arrays de bytes e structs; ela não conhece a porta serial.
//! Assim, é possível executar testes unitários sem hardware (veja o módulo #[cfg(test)] no fim do arquivo),
//! uma prática típica de arquitetura em camadas.

use crate::error::{Result, ServoError};

/// Cabeçalho: o protocolo FT-SCS usa dois bytes 0xFF como marcador fixo de início do quadro.
pub const HEADER: [u8; 2] = [0xFF, 0xFF];

/// ID de broadcast: todos os servos no barramento executam a instrução, mas nenhum envia uma resposta.
/// Usado com frequência para escrever em vários servos ao mesmo tempo. Nunca o use para detectar servos durante uma varredura.
pub const BROADCAST_ID: u8 = 0xFE;

/// Conjunto de instruções do protocolo (inclui as instruções mencionadas nas linhas 7 e 19 da documentação da tabela de memória).
///
/// [Conceito de Rust: #[repr(u8)]]
/// Por padrão, o layout de memória de um enum Rust não é garantido; #[repr(u8)]
/// força cada variante a ocupar um byte, com o valor numérico especificado,
/// permitindo obter com segurança o byte de protocolo 0x01 por meio de `Instruction::Ping as u8`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Instruction {
    /// 0x01 Consulta se o servo está online (handshake); um servo funcional deve responder.
    Ping = 0x01,
    /// 0x02 Lê a tabela de memória: parâmetros = [endereço inicial, número de bytes a ler]
    Read = 0x02,
    /// 0x03 Escreve na tabela de memória: parâmetros = [endereço inicial, dados...]; efeito imediato.
    Write = 0x03,
    /// 0x04 Escrita registrada (REG WRITE): mesmos parâmetros da instrução de escrita, mas armazena sem executar;
    /// executa quando recebe ACTION (usada para sincronizar movimentos de vários servos).
    RegWrite = 0x04,
    /// 0x05 Executa o conteúdo armazenado anteriormente por REG WRITE.
    Action = 0x05,
    /// 0x06 Restaura as configurações de fábrica (todos os valores da EPROM voltam ao padrão).
    Reset = 0x06,
    /// 0x08 Reinicia o servo: equivale a desligar e ligar, recarregando a SRAM a partir da EPROM.
    /// Pode verificar se uma gravação na EPROM foi realmente persistida, sem desligar fisicamente.
    Reboot = 0x08,
    /// 0x0A Redefine o status (reinicia a contagem de voltas no modo multivoltas).
    ResetTurns = 0x0A,
    /// 0x0B Calibra a posição: sem parâmetros, define a posição atual como centro (2048);
    /// com dois bytes de parâmetro (little-endian), calibra para a leitura especificada.
    /// Ao receber a instrução, o servo calcula e altera automaticamente o registrador de deslocamento de posição 31.
    /// Esta é a instrução correspondente ao botão “Definir zero” do software de diagnóstico Feetech FD.
    /// Atenção: o HD-1910 (firmware da série HLS >= 3.43) não aceita o método antigo de calibração “escrever 128 no torque switch”; use esta instrução.
    /// Uma resposta de sucesso não garante que a alteração foi aplicada; sempre leia o valor de volta para confirmar.
    Calibrate = 0x0B,
    /// 0x83 Escrita sincronizada: uma instrução grava no mesmo endereço de vários servos ao mesmo tempo.
    SyncWrite = 0x83,
}

/// Calcula o checksum FT-SCS: soma todos os bytes, aplica complemento de um e mantém os 8 bits inferiores.
///
/// [Conceito de Rust: `impl IntoIterator` e genéricos]
/// O parâmetro usa genéricos e limites de traits para que a função aceite tanto `&[u8]` quanto `Vec<u8>`,
/// oferecendo flexibilidade ao chamador. `.iter()` cria um iterador e `.fold(0u8, ...)` acumula os valores.
/// `wrapping_add` soma com retorno ao início em caso de overflow — o checksum usa módulo 256.
/// Com `+` comum, o overflow pode causar panic em modo de depuração; aqui declaramos explicitamente que o retorno é intencional.
pub fn checksum(bytes: &[u8]) -> u8 {
    let sum = bytes
        .iter()
        .fold(0u8, |acc, &b| acc.wrapping_add(b));
    !sum // `!` é complemento bit a bit para inteiros e negação lógica para bool.
}

/// Monta um pacote completo para envio.
///
/// [Conceito de Rust: Vec e ownership]
/// A função cria um Vec<u8> e o retorna ao chamador, transferindo a propriedade.
/// Não há malloc/free nem coletor de lixo; o compilador determina em tempo de compilação quem libera a memória.
pub fn build_packet(id: u8, inst: Instruction, params: &[u8]) -> Vec<u8> {
    // Length = instrução (1) + número de parâmetros + checksum (1)
    let length = (params.len() + 2) as u8;

    // with_capacity pré-aloca memória suficiente e evita realocações repetidas durante push.
    let mut pkt = Vec::with_capacity(params.len() + 6);
    pkt.extend_from_slice(&HEADER);
    pkt.push(id);
    pkt.push(length);
    pkt.push(inst as u8);
    pkt.extend_from_slice(params);
    // O checksum abrange de ID até o último parâmetro (sem incluir o cabeçalho).
    pkt.push(checksum(&pkt[2..]));
    pkt
}

/// Pacote de resposta do servo após a análise.
pub struct StatusPacket {
    /// ID do servo que respondeu.
    pub id: u8,
    /// Status de erro: 0 indica operação normal; cada bit diferente de zero representa uma falha
    /// (BIT0 tensão / BIT1 codificador magnético / BIT2 temperatura / BIT3 corrente).
    pub error: u8,
    /// Dados da resposta (o retorno de uma instrução de leitura fica aqui).
    pub params: Vec<u8>,
}

/// Analisa os bytes recebidos em um StatusPacket e valida o pacote por completo.
///
/// [Conceito de Rust: Result para uma sequência de validações combináveis]
/// Cada validação retorna Err(...) imediatamente quando falha; o caminho de sucesso permanece linear,
/// sem blocos if/else profundamente aninhados (o estilo conhecido como cláusulas de guarda).
pub fn parse_status(buf: &[u8]) -> Result<StatusPacket> {
    // Um quadro tem pelo menos 6 bytes: cabeçalho 2 + ID + Length + Error + Checksum.
    if buf.len() < 6 {
        return Err(ServoError::Malformed("pacote de resposta muito curto: menos de 6 bytes".into()));
    }
    if buf[0] != HEADER[0] || buf[1] != HEADER[1] {
        return Err(ServoError::Malformed("o cabeçalho não é 0xFF 0xFF".into()));
    }
    let id = buf[2];
    let length = buf[3] as usize;
    // Comprimento total indicado pelo campo Length = cabeçalho 2 + ID + Length + valor de Length.
    if buf.len() != length + 4 {
        return Err(ServoError::Malformed("o tamanho do pacote não corresponde ao campo Length".into()));
    }
    // Recalcula o checksum (do ID até o byte anterior ao checksum).
    let expect = checksum(&buf[2..buf.len() - 1]);
    if expect != buf[buf.len() - 1] {
        return Err(ServoError::Checksum);
    }
    Ok(StatusPacket {
        id,
        error: buf[4],
        // A área de parâmetros fica entre o byte de erro e o checksum; pode estar vazia (por exemplo, na resposta a PING).
        params: buf[5..buf.len() - 1].to_vec(),
    })
}

/// Converte o status do servo (byte Error da resposta / endereço 65 da tabela de memória) em uma descrição em português.
///
/// [Conceito de Rust: operações de bits + Vec<String> + join]
/// O status é codificado por bits: BIT0(1)=tensão, BIT1(2)=codificador magnético, BIT2(4)=temperatura, BIT3(8)=corrente.
/// Quando há várias falhas, o valor é a soma dos bits; por isso, cada um é testado com `&`.
pub fn describe_status(status: u8) -> String {
    if status == 0 {
        return "Normal".to_string();
    }
    let mut problems: Vec<&str> = Vec::new();
    // [Conceito de Rust: teste de bits iterativo] Um loop simples sobre um array deixa a lógica clara.
    let bits = [
        (1 << 0, "Falha de tensão"),
        (1 << 1, "Falha do codificador magnético"),
        (1 << 2, "Superaquecimento"),
        (1 << 3, "Sobrecorrente"),
    ];
    for (bit, name) in bits {
        if status & bit != 0 {
            problems.push(name);
        }
    }
    problems.join(" + ")
}

// =============================================================================
// [Conceito de Rust: testes unitários]
// `#[cfg(test)]` indica que este módulo é compilado apenas por `cargo test`, não nas versões de lançamento.
// A camada de protocolo contém funções puras e não depende de hardware, sendo ideal para testes unitários.
// =============================================================================
#[cfg(test)]
mod tests {
    use super::*; // Importa tudo do módulo pai (super = módulo acima).

    #[test]
    fn test_build_ping_packet() {
        // Pacote PING clássico para ID=1: FF FF 01 02 01 FB.
        let pkt = build_packet(1, Instruction::Ping, &[]);
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x02, 0x01, 0xFB]);
    }

    #[test]
    fn test_checksum_wraps() {
        // 0xFF + 0xFF excede u8; wrapping_add deve retornar ao início sem causar panic.
        assert_eq!(checksum(&[0xFF, 0xFF]), !0xFEu8);
    }

    #[test]
    fn test_parse_status_roundtrip() {
        // Cria um pacote de resposta válido (leitura do endereço 56 retorna dois bytes) e analisa-o novamente.
        let raw = [0xFF, 0xFF, 0x01, 0x04, 0x00, 0x00, 0x08, 0xF2];
        let pkt = parse_status(&raw).expect("o pacote válido deve ser analisado com sucesso");
        assert_eq!(pkt.id, 1);
        assert_eq!(pkt.error, 0);
        assert_eq!(pkt.params, vec![0x00, 0x08]); // Little-endian: posição = 0x0800 = 2048.
    }

    #[test]
    fn test_parse_bad_checksum() {
        let raw = [0xFF, 0xFF, 0x01, 0x04, 0x00, 0x00, 0x08, 0x00]; // O byte de checksum está intencionalmente incorreto.
        assert!(matches!(parse_status(&raw), Err(ServoError::Checksum)));
    }

    #[test]
    fn test_build_calibrate_packet() {
        // Calibra a posição do ID=1 para 2048 (0x0800): FF FF 01 04 0B 00 08 E7.
        let pkt = build_packet(1, Instruction::Calibrate, &2048u16.to_le_bytes());
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x04, 0x0B, 0x00, 0x08, 0xE7]);
        // Sem parâmetros = calibra para o centro 2048: FF FF 01 02 0B F1.
        let pkt = build_packet(1, Instruction::Calibrate, &[]);
        assert_eq!(pkt, vec![0xFF, 0xFF, 0x01, 0x02, 0x0B, 0xF1]);
    }
}
