//! lib.rs — alvo de biblioteca: disponibiliza o driver de servo para reutilização por outros programas
//!
//! [Conceito de Rust: um crate pode ser programa e biblioteca]
//! Convenções do Cargo:
//!   - src/main.rs → compilado como executável (alvo binário)
//!   - src/lib.rs  → compilado como biblioteca (alvo que pode ser dependência de outro projeto)
//! Os dois podem coexistir no mesmo pacote. Assim:
//!   - a ferramenta CLI (main.rs) continua disponível;
//!   - um projeto GUI pode usar diretamente os módulos protocol, registers, servo e error
//!     por meio de uma dependência de caminho `path = "../FeeTech_HD1910M_Servo"`, sem duplicar código.
//!
//! Essa é uma vantagem da arquitetura em camadas: os módulos de baixo nível não dependem do código de CLI em main.rs
//! e podem ser reutilizados diretamente por outra interface, como uma GUI.
//!
//! O nome da biblioteca é definido como feetech_servo na seção [lib] de Cargo.toml
//! (identificadores Rust não aceitam `-`, então usamos sublinhado).

pub mod error;
pub mod protocol;
pub mod registers;
pub mod servo;
