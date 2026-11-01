//! error.rs — definição centralizada dos tipos de erro possíveis neste projeto
//!
//! [Conceito de Rust: tratamento de erros]
//! Rust não usa exceções try/catch como Java ou Python; a possibilidade de falha
//! é declarada explicitamente na assinatura: `Result<T, E>` retorna T em caso de sucesso ou E em caso de falha.
//! O chamador precisa tratar o Result com match, if let ou o operador `?` para propagar o erro;
//! caso contrário, o compilador acusa a falha. É assim que o Rust ajuda a escrever código robusto.
//!
//! [Conceito de Rust: enum]
//! Enums do Rust são mais flexíveis que os de C: cada variante pode carregar dados de tipos diferentes,
//! como em um tipo algébrico. Cada variante de erro abaixo contém informações contextuais relevantes.

use thiserror::Error;

/// Tipo de erro unificado da ferramenta de servo.
///
/// `#[derive(Error, Debug)]` é uma macro derivada: a biblioteca thiserror implementa automaticamente
/// o trait padrão `std::error::Error` para este enum.
/// Os marcadores `{0}` e `{1}` em `#[error("...")]` referenciam os dados da variante.
#[derive(Error, Debug)]
pub enum ServoError {
    /// Falha ao abrir, ler ou gravar na porta serial. `#[from]` permite que `?` converta
    /// automaticamente erros de serialport para este tipo, sem código de conversão manual.
    #[error("Erro serial: {0}")]
    Serial(#[from] serialport::Error),

    /// Erro de E/S padrão (por exemplo, erro de baixo nível ao ler a porta serial).
    #[error("Erro de E/S: {0}")]
    Io(#[from] std::io::Error),

    /// Timeout ao aguardar a resposta do servo — geralmente causado por fiação incorreta, ID ou taxa errados.
    #[error("Tempo esgotado: o servo não respondeu (verifique a fiação, o ID e a taxa de transmissão)")]
    Timeout,

    /// Checksum da resposta inválido; pode haver interferência na linha ou truncamento dos dados.
    #[error("Checksum inválido na resposta")]
    Checksum,

    /// Resposta fora do formato do protocolo (cabeçalho ou tamanho incorretos etc.).
    #[error("Formato de resposta inválido: {0}")]
    Malformed(String),

    /// O servo retornou um status de erro (falha de tensão, temperatura, corrente ou codificador).
    /// O primeiro campo é o byte de status bruto; o segundo contém sua descrição em português.
    #[error("Falha informada pelo servo (status 0x{0:02X}): {1}")]
    ServoStatus(u8, String),

    /// Parâmetro de entrada inválido (fora da faixa, registrador somente leitura etc.).
    #[error("Parâmetro inválido: {0}")]
    InvalidParam(String),
}

/// [Conceito de Rust: alias de tipo]
/// Um alias dá um nome curto a um tipo longo e recorrente. Neste projeto,
/// `Result<T, ServoError>` é abreviado uniformemente como `Result<T>`.
/// Ele oculta o Result da biblioteca padrão, uma prática comum na comunidade Rust.
pub type Result<T> = std::result::Result<T, ServoError>;
