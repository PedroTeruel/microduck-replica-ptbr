//! registers.rs — definição completa e estruturada da tabela de memória do servo HD1910M
//!
//! A tabela de memória funciona como um cadastro interno de parâmetros do servo: cada endereço armazena uma configuração.
//! Esta tabela vem da documentação oficial da Feetech (tabela HLS_2 em doc.feetech.cn) e está dividida em cinco áreas:
//!
//!   Endereços 0 a 4    Informações de versão   (somente leitura: versões de firmware etc.)
//!   Endereços 5 a 39   Configuração EPROM       (leitura e escrita; persistente com a flag de bloqueio)
//!   Endereços 40 a 55  Controle SRAM            (leitura e escrita; controle em tempo real, volátil)
//!   Endereços 56 a 75  Feedback SRAM            (somente leitura: posição, velocidade, tensão, temperatura, corrente...)
//!   Endereços 77 a 86  Parâmetros de fábrica    (somente leitura: valores de calibração de fábrica)
//!
//! [Conceito de Rust: transformar uma tabela de documentação em constantes de compilação]
//! A tabela inteira é declarada como um array constante `&'static [Register]`.
//! O tempo de vida 'static indica que os dados existem durante toda a execução do programa,
//! sem ocupar heap nem adicionar custo de acesso. A ferramenta de linha de comando consulta esta tabela para validar parâmetros e exibir descrições;
//! para adicionar um registrador, basta incluir uma linha.

/// Permissões de leitura e escrita do registrador.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Access {
    /// Somente leitura (feedback, versão e valores de calibração de fábrica).
    ReadOnly,
    /// Leitura e escrita (configurações e controles).
    ReadWrite,
}

impl Access {
    pub fn as_str(&self) -> &'static str {
        match self {
            Access::ReadOnly => "Somente leitura",
            Access::ReadWrite => "Leitura/escrita",
        }
    }
}

/// Área da tabela de memória.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Area {
    Version,      // Informações de versão
    Eprom,        // Configuração EPROM (persistente)
    SramControl,  // Controle em tempo real da SRAM
    SramFeedback, // Feedback em tempo real da SRAM
    Factory,      // Parâmetros de calibração de fábrica
}

impl Area {
    pub fn as_str(&self) -> &'static str {
        match self {
            Area::Version => "Informações de versão",
            Area::Eprom => "Configuração EPROM",
            Area::SramControl => "Controle SRAM",
            Area::SramFeedback => "Feedback SRAM",
            Area::Factory => "Parâmetros de fábrica",
        }
    }
}

/// Definição de um registrador (corresponde a uma linha da tabela de memória oficial).
///
/// [Conceito de Rust: &'static str]
/// Literais de string (por exemplo, "Posição desejada") são compilados diretamente no executável,
/// têm duração 'static (a mesma do programa) e não exigem alocação no heap dentro da struct.
pub struct Register {
    /// Endereço inicial (decimal, conforme a documentação oficial).
    pub addr: u8,
    /// Chave em inglês usada na linha de comando (por exemplo, "pos-p"), sempre em minúsculas.
    pub key: &'static str,
    /// Nome localizado em português.
    pub cn: &'static str,
    /// Número de bytes ocupados: 1 ou 2 (em valores de dois bytes, o byte menos significativo vem primeiro: little-endian).
    pub size: u8,
    pub access: Access,
    pub area: Area,
    /// Unidade física (valor representado por cada LSB), por exemplo, "0.1V" ou "6.5mA".
    pub unit: &'static str,
    /// Faixa de valores permitidos (validada antes da gravação para evitar configurações inválidas do servo).
    pub min: i64,
    pub max: i64,
    /// Posição do bit de sinal na codificação sinal-magnitude:
    ///   None     — valor sem sinal
    ///   Some(15) — BIT15 indica a direção (posição, velocidade, corrente etc.)
    ///   Some(10) — BIT10 indica a direção (carga atual)
    /// O protocolo Feetech representa números negativos com bit de sinal e magnitude, não com complemento de dois.
    pub sign_bit: Option<u8>,
    /// Descrição adicional.
    pub desc: &'static str,
}

impl Register {
    /// Valida a faixa do valor antes da gravação; retorna Err para valores fora do intervalo e bloqueia o envio.
    /// Todas as operações de escrita (write_reg, sync_write, set --defer etc.) usam esta mesma validação.
    pub fn check_value(&self, value: i64) -> crate::error::Result<()> {
        if value < self.min || value > self.max {
            return Err(crate::error::ServoError::InvalidParam(format!(
                "O valor {value} está fora do intervalo permitido de {} ({}) {} a {}",
                self.key, self.cn, self.min, self.max
            )));
        }
        Ok(())
    }
}

/// Tabela de memória completa (corresponde linha a linha à documentação oficial HLS_2).
///
/// [Conceito de Rust: arrays constantes]
/// A declaração const define todo o conteúdo durante a compilação; a iteração é igual à de um array comum.
pub const REGISTERS: &[Register] = &[
    // ---------------- 2.1 Informações de versão (somente leitura) ----------------
    Register { addr: 0,  key: "fw-major",    cn: "Versão principal do firmware", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "Versão principal do firmware" },
    Register { addr: 1,  key: "fw-minor",    cn: "Versão secundária do firmware", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "Versão secundária do firmware" },
    Register { addr: 2,  key: "endian",      cn: "END",         size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "0 indica estrutura de armazenamento little-endian" },
    Register { addr: 3,  key: "servo-major", cn: "Versão principal do servo", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "Versão principal do servo" },
    Register { addr: 4,  key: "servo-minor", cn: "Versão secundária do servo", size: 1, access: Access::ReadOnly,  area: Area::Version, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "Versão secundária do servo" },

    // ---------------- 2.2 Configuração EPROM (leitura/escrita, persistente) ----------------
    Register { addr: 5,  key: "id",              cn: "ID principal",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",     min: 0, max: 253,   sign_bit: None, desc: "ID principal exclusivo no barramento (padrão de fábrica: 1); gravá-lo também altera o ID secundário." },
    Register { addr: 6,  key: "baud",            cn: "Taxa de transmissão",         size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 7,     sign_bit: None, desc: "0 a 7 = 1000000/500000/250000/128000/115200/76800/57600/38400" },
    Register { addr: 7,  key: "id2",             cn: "ID secundário",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",     min: 0, max: 253,   sign_bit: None, desc: "Identificador secundário, usado pelas instruções de escrita, escrita registrada, execução registrada e escrita sincronizada." },
    Register { addr: 8,  key: "resp-level",      cn: "Nível de resposta",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 1,     sign_bit: None, desc: "0: não responde, exceto a leitura e PING; 1: responde a todas as instruções." },
    Register { addr: 9,  key: "min-angle",       cn: "Limite mínimo de ângulo",   size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0,087 grau", min: 0, max: 4094,  sign_bit: None, desc: "Este valor é 0 no controle de posição absoluta multivoltas." },
    Register { addr: 11, key: "max-angle",       cn: "Limite máximo de ângulo",   size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0,087 grau", min: 1, max: 4095,  sign_bit: None, desc: "Este valor é 0 no controle de posição absoluta multivoltas." },
    Register { addr: 13, key: "max-temp",        cn: "Temperatura máxima",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "°C",    min: 0, max: 100,   sign_bit: None, desc: "Acima desta temperatura, a saída de torque é desligada (proteção ativada por padrão a 70 °C)." },
    Register { addr: 14, key: "max-voltage",     cn: "Tensão máxima de entrada",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0,1 V",  min: 0, max: 254,   sign_bit: None, desc: "Acima desta tensão, a proteção contra sobretensão é ativada." },
    Register { addr: 15, key: "min-voltage",     cn: "Tensão mínima de entrada",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0,1 V",  min: 0, max: 254,   sign_bit: None, desc: "Abaixo desta tensão, a proteção contra subtensão é ativada (padrão de fábrica: 4,0 V)." },
    Register { addr: 16, key: "max-torque",      cn: "Torque máximo",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0,1%",  min: 0, max: 1000,  sign_bit: None, desc: "Na inicialização, é atribuído ao limite de torque do endereço 48." },
    Register { addr: 18, key: "phase",           cn: "Fase",           size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Byte de função especial (direção, codificador, frequência PWM etc.); altere somente se necessário." },
    Register { addr: 19, key: "unload-cond",     cn: "Condições de alívio",       size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Bits: BIT0 tensão, BIT1 codificador magnético, BIT2 superaquecimento, BIT3 sobrecorrente; 1 ativa a proteção." },
    Register { addr: 20, key: "led-alarm",       cn: "Condições do alerta LED",    size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Bits: BIT0 tensão, BIT1 codificador magnético, BIT2 superaquecimento, BIT3 sobrecorrente; 1 ativa o alerta intermitente." },
    Register { addr: 21, key: "pos-p",           cn: "Ganho P da posição", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Na inicialização, é atribuído ao Kp do endereço 50 (proporcional da malha de posição, 1/8)." },
    Register { addr: 22, key: "pos-d",           cn: "Ganho D da posição", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Na inicialização, é atribuído ao Kd do endereço 51 (derivativo da malha de posição, 1/4)." },
    Register { addr: 23, key: "pos-i",           cn: "Ganho I da posição", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Na inicialização, é atribuído ao Ki do endereço 52." },
    Register { addr: 24, key: "min-start-force", cn: "Força mínima de partida",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0,1%",  min: 0, max: 254,   sign_bit: None, desc: "Torque mínimo de saída para iniciar o movimento do servo." },
    Register { addr: 25, key: "integral-limit",  cn: "Limite integral",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "O valor integral máximo é este valor × 4; 0 desativa o limite. Aplicável aos modos 0 e 4." },
    Register { addr: 26, key: "deadband-cw",     cn: "Zona morta positiva",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0,087 grau", min: 0, max: 16,    sign_bit: None, desc: "A unidade mínima equivale à menor resolução angular." },
    Register { addr: 27, key: "deadband-ccw",    cn: "Zona morta negativa",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "0,087 grau", min: 0, max: 16,    sign_bit: None, desc: "A unidade mínima equivale à menor resolução angular." },
    Register { addr: 28, key: "protect-current", cn: "Corrente de proteção",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "6,5 mA", min: 0, max: 2047,  sign_bit: None, desc: "Na inicialização, é atribuída à corrente desejada do endereço 44." },
    Register { addr: 30, key: "angle-resolution",cn: "Resolução angular",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 1, max: 128,   sign_bit: None, desc: "Fator de ampliação da menor resolução angular do sensor." },
    Register { addr: 31, key: "pos-offset",      cn: "Deslocamento de posição",       size: 2, access: Access::ReadWrite, area: Area::Eprom, unit: "0,087 grau", min: -4095, max: 4095, sign_bit: Some(15), desc: "BIT15 indica a direção e é usado para corrigir o zero mecânico." },
    Register { addr: 33, key: "mode",            cn: "Modo de operação",       size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 4,     sign_bit: None, desc: "0 servo de posição (posição + limite de corrente); 1 velocidade constante; 2 corrente constante; 3 controle PWM em malha aberta; 4 PD de posição pura (Sim2Real)." },
    Register { addr: 34, key: "cur-p",           cn: "Ganho P de corrente", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Ganho proporcional da malha de corrente (parâmetro central do controle de força)." },
    Register { addr: 35, key: "cur-i",           cn: "Ganho I de corrente", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 254,   sign_bit: None, desc: "Ganho integral da malha de corrente (parâmetro central do controle de força)." },
    Register { addr: 36, key: "reserved-36",     cn: "Sem definição (36)",     size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",      min: 0, max: 255,   sign_bit: None, desc: "Não definido na documentação oficial; altere com cuidado." },
    Register { addr: 37, key: "vel-p",           cn: "Ganho P de velocidade", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",   min: 0, max: 254,   sign_bit: None, desc: "Ganho proporcional da malha de velocidade no modo 1; na inicialização, é atribuído ao Kp do endereço 50." },
    Register { addr: 38, key: "overcur-time",    cn: "Tempo de proteção contra sobrecorrente",   size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "10 ms",  min: 0, max: 254,   sign_bit: None, desc: "Aciona a proteção contra sobrecorrente após este tempo acima do limite." },
    Register { addr: 39, key: "vel-i",           cn: "Ganho I de velocidade", size: 1, access: Access::ReadWrite, area: Area::Eprom, unit: "",   min: 0, max: 254,   sign_bit: None, desc: "Ganho integral da malha de velocidade no modo 1; na inicialização, é atribuído ao Ki do endereço 52." },

    // ---------------- 2.3 Controle SRAM (leitura/escrita, volátil) ----------------
    Register { addr: 40, key: "torque-switch", cn: "Controle de torque",   size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 2,     sign_bit: None, desc: "0: saída de torque desativada; 1: ativada; 2: amortecimento." },
    Register { addr: 41, key: "acc",           cn: "Aceleração",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "8,7 graus/s²", min: 0, max: 254, sign_bit: None, desc: "Aceleração/desaceleração de operação; 0 representa aceleração máxima." },
    Register { addr: 42, key: "goal-pos",      cn: "Posição desejada",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0,087 grau", min: -32767, max: 32767, sign_bit: Some(15), desc: "Controle de posição absoluta; BIT15 indica a direção. No modo multivoltas, pode exceder 4095." },
    Register { addr: 44, key: "goal-current",  cn: "Corrente desejada",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "6,5 mA", min: -2047, max: 2047, sign_bit: Some(15), desc: "Controla a corrente máxima do motor, exceto no modo 3. No modo de corrente constante, BIT15 indica a direção; no modo PWM, a faixa é -1000 a 1000 e BIT10 indica a direção." },
    Register { addr: 46, key: "speed",         cn: "Velocidade de operação",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0,732 RPM", min: -32767, max: 32767, sign_bit: Some(15), desc: "Velocidade máxima do motor; 0 = parado. No modo de velocidade constante, BIT15 indica a direção." },
    Register { addr: 48, key: "torque-limit",  cn: "Limite de torque",   size: 2, access: Access::ReadWrite, area: Area::SramControl, unit: "0,1%",  min: 0, max: 1000,  sign_bit: None, desc: "Controla a saída de torque de bloqueio (na inicialização, recebe o torque máximo do endereço 16)." },
    Register { addr: 50, key: "kp",            cn: "Kp de operação",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "Servo de posição: P da malha de posição (1/8); velocidade constante: P da malha de velocidade (efeito em tempo real)." },
    Register { addr: 51, key: "kd",            cn: "Kd de operação",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "Servo de posição: D da malha de posição (1/4); sem efeito no modo de velocidade constante." },
    Register { addr: 52, key: "ki",            cn: "Ki de operação",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 254,   sign_bit: None, desc: "Sem efeito no servo de posição; I da malha de velocidade no modo de velocidade constante." },
    Register { addr: 53, key: "reserved-53",   cn: "Sem definição (53)", size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 255,   sign_bit: None, desc: "Não definido na documentação oficial; altere com cuidado." },
    Register { addr: 54, key: "reserved-54",   cn: "Sem definição (54)", size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 255,   sign_bit: None, desc: "Não definido na documentação oficial; altere com cuidado." },
    Register { addr: 55, key: "lock",          cn: "Flag de bloqueio",     size: 1, access: Access::ReadWrite, area: Area::SramControl, unit: "",     min: 0, max: 1,     sign_bit: None, desc: "0: desbloqueia a gravação e persiste valores EPROM; 1: bloqueia a gravação e não persiste ao desligar (padrão)." },

    // ---------------- 2.4 Feedback SRAM (somente leitura) ----------------
    Register { addr: 56, key: "pos",            cn: "Posição atual",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0,087 grau",  min: -32767, max: 32767, sign_bit: Some(15), desc: "Posição absoluta atual; BIT15 indica a direção (inclui voltas no modo multivoltas)." },
    Register { addr: 58, key: "vel",            cn: "Velocidade atual",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0,732 RPM", min: -32767, max: 32767, sign_bit: Some(15), desc: "Velocidade de rotação atual do motor; BIT15 indica a direção." },
    Register { addr: 60, key: "load",           cn: "Carga atual",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0,1%",     min: -1000, max: 1000,   sign_bit: Some(10), desc: "Duty cycle da tensão aplicada ao motor; BIT10 indica a direção." },
    Register { addr: 62, key: "voltage",        cn: "Tensão atual",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0,1 V",    min: 0, max: 255,   sign_bit: None, desc: "Tensão de operação atual do servo." },
    Register { addr: 63, key: "temp",           cn: "Temperatura atual",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "°C",     min: 0, max: 255,   sign_bit: None, desc: "Temperatura interna de operação atual do servo." },
    Register { addr: 64, key: "async-flag",     cn: "Flag de escrita registrada", size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "Flag usada com instruções de escrita registrada." },
    Register { addr: 65, key: "status",         cn: "Status do servo",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "BIT0 tensão, BIT1 codificador magnético, BIT2 temperatura, BIT3 corrente; 1 indica falha." },
    Register { addr: 66, key: "moving",         cn: "Indicador de movimento",   size: 1, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 255,   sign_bit: None, desc: "BIT0 = 1 durante o movimento; BIT1 = 1 em movimento e 0 quando parado na posição de destino." },
    Register { addr: 67, key: "goal-pos-fb",    cn: "Feedback da posição desejada", size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "0,087 grau", min: 0, max: 65535, sign_bit: None, desc: "Posição de destino atual." },
    Register { addr: 69, key: "current",        cn: "Corrente atual",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "6,5 mA",   min: -32767, max: 32767, sign_bit: Some(15), desc: "Corrente de fase atual do motor; BIT15 indica a direção." },
    Register { addr: 71, key: "reserved-71",    cn: "Sem definição (71)", size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 65535, sign_bit: None, desc: "Não definido na documentação oficial." },
    Register { addr: 73, key: "current-offset", cn: "Deslocamento de corrente",   size: 2, access: Access::ReadOnly, area: Area::SramFeedback, unit: "",       min: 0, max: 65535, sign_bit: None, desc: "Deslocamento do zero de corrente." },

    // ---------------- 2.5 Parâmetros de fábrica (somente leitura, calibração de fábrica) ----------------
    Register { addr: 77, key: "v-fk",            cn: "vFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 78, key: "v-kgi",           cn: "vKgI",         size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 79, key: "p-fk",            cn: "pFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 80, key: "move-speed-th",   cn: "Limite de velocidade de movimento", size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Limite de velocidade usado para determinar se o servo está em movimento." },
    Register { addr: 81, key: "dts",             cn: "DTs (ms)",      size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 82, key: "e-fk",            cn: "eFk(*10)",     size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 83, key: "vk",              cn: "Vk (ms)",       size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 84, key: "max-speed-limit", cn: "Limite máximo de velocidade", size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 85, key: "acc-limit",       cn: "Limite de aceleração",   size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
    Register { addr: 86, key: "acc-multi",       cn: "Multiplicador de aceleração",   size: 1, access: Access::ReadOnly, area: Area::Factory, unit: "", min: 0, max: 255, sign_bit: None, desc: "Parâmetro de calibração de fábrica." },
];

/// Índice da taxa de transmissão: os valores de 0 a 7 no endereço 6 da tabela correspondem às taxas reais.
pub const BAUD_RATES: [u32; 8] = [
    1_000_000, 500_000, 250_000, 128_000, 115_200, 76_800, 57_600, 38_400,
];

/// Localiza um registrador pela chave em inglês ou pelo endereço.
///
/// Formatos aceitos (adequados para uso na linha de comando):
///   - Chave: "pos-p", "id", "torque-limit" (sem distinção entre maiúsculas e minúsculas)
///   - Endereço decimal: "21"
///   - Endereço hexadecimal: "0x15"
///
/// [Conceito de Rust: Option<T>]
/// A possibilidade de não encontrar um valor é representada por `Option`: Some(registrador) ou None.
/// Esta é a alternativa do Rust a null; o compilador exige que o caso ausente seja tratado,
/// eliminando erros de ponteiro nulo pela raiz.
///
/// [Conceito de Rust: encadeamento de iteradores]
/// `.iter().find(...)` usa um estilo funcional: percorre o array e retorna o primeiro elemento que satisfaz a condição.
pub fn find_register(name_or_addr: &str) -> Option<&'static Register> {
    let key = name_or_addr.to_lowercase();

    // Primeiro tenta interpretar como endereço: "0x15" (hexadecimal) ou "21" (decimal).
    let addr: Option<u8> = if let Some(hex) = key.strip_prefix("0x") {
        u8::from_str_radix(hex, 16).ok() // .ok() converte Result em Option.
    } else {
        key.parse::<u8>().ok()
    };
    if let Some(a) = addr {
        return REGISTERS.iter().find(|r| r.addr == a);
    }

    // Depois tenta localizar pela chave.
    REGISTERS.iter().find(|r| r.key == key)
}

/// Decodificação sinal-magnitude: converte o u16 bruto do protocolo em um inteiro com sinal.
///
/// Números negativos no protocolo Feetech não usam complemento de dois; usam bit de sinal e magnitude:
///   bit de sinal igual a 1 indica negativo; os demais bits armazenam o valor absoluto.
///   Por exemplo, a posição -100 é codificada como 0x8000 | 100 = 0x8064.
pub fn decode_value(raw: u16, sign_bit: Option<u8>) -> i64 {
    match sign_bit {
        Some(bit) => {
            let sign_mask = 1u16 << bit;        // Máscara do bit de sinal, por exemplo, 0x8000.
            let mag_mask = sign_mask - 1;       // Máscara da magnitude, por exemplo, 0x7FFF.
            let mag = (raw & mag_mask) as i64;
            if raw & sign_mask != 0 { -mag } else { mag }
        }
        None => raw as i64,
    }
}

/// Codificação sinal-magnitude: empacota um inteiro com sinal no formato u16 exigido pelo protocolo.
pub fn encode_value(value: i64, sign_bit: Option<u8>) -> u16 {
    match sign_bit {
        Some(bit) => {
            let sign_mask = 1u16 << bit;
            let mag = value.unsigned_abs() as u16; // unsigned_abs obtém diretamente |v| como valor sem sinal.
            if value < 0 { mag | sign_mask } else { mag }
        }
        None => value as u16,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_by_key_and_addr() {
        assert_eq!(find_register("pos-p").unwrap().addr, 21);
        assert_eq!(find_register("POS-P").unwrap().addr, 21); // Não diferencia maiúsculas e minúsculas.
        assert_eq!(find_register("21").unwrap().key, "pos-p");
        assert_eq!(find_register("0x15").unwrap().key, "pos-p");
        assert!(find_register("not-exist").is_none());
    }

    #[test]
    fn test_sign_magnitude_roundtrip() {
        // A posição -100 deve ser codificada como 0x8064 e decodificada de volta.
        let raw = encode_value(-100, Some(15));
        assert_eq!(raw, 0x8064);
        assert_eq!(decode_value(raw, Some(15)), -100);
        // Registradores sem sinal não são afetados.
        assert_eq!(decode_value(1000, None), 1000);
        // A carga usa BIT10 como bit de sinal: -500 → 0x0400 | 500.
        let raw = encode_value(-500, Some(10));
        assert_eq!(decode_value(raw, Some(10)), -500);
    }

    #[test]
    fn test_check_value() {
        let reg = find_register("pos-p").unwrap(); // Faixa: 0 a 254.
        assert!(reg.check_value(254).is_ok());
        assert!(reg.check_value(255).is_err());
        assert!(reg.check_value(-1).is_err());
        let offset = find_register("pos-offset").unwrap(); // Faixa: -4095 a 4095.
        assert!(offset.check_value(-4095).is_ok());
        assert!(offset.check_value(-4096).is_err());
    }
}
