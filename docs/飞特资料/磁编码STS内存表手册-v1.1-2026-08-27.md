# Tabela de memória do servo STS com encoder magnético

# 1. Protocolo de comunicação do servo
O servo usa o protocolo personalizado FT-SCS. A porta serial vem configurada de fábrica; o STS usa taxa padrão de 1 Mbps e comunicação TTL de barramento único, com 8 bits de dados, sem paridade e 1 bit de parada. A taxa pode ser configurada de 38400 a 1 Mbps. O endereço de comunicação (ID da estação) padrão é 1.
[Protocolo personalizado FT-SCS](http://doc.feetech.cn/#/tiaozhunlujingft?srcType=FT-SCS-Protocol-41ad23fe8a244712ba160b93)

# 2. Definição da tabela de memória do servo
Para funções com endereços de dados de dois bytes, o byte menos significativo vem no endereço inferior e o mais significativo no endereço seguinte.
## 2.1 Informações da versão
|Endereço DEC|Endereço HEX|Nome da função|Bytes|Valor inicial|Permissão|Faixa de valores|Unidade|Instruções|
|-|-|-|-|-|-|-|-|-|
|0|0x00|Versão principal do firmware|1|--|Somente leitura||||
|1|0x01|Versão secundária do firmware|1|--|Somente leitura|||
|2|0x02|END|1|0|Somente leitura|||0 indica armazenamento little-endian|
|3|0x03|Versão principal do servo|1|--|Somente leitura||||
|4|0x04|Versão secundária do servo|1|--|Somente leitura||||

## 2.2 Configuração da EPROM
|Endereço DEC|Endereço HEX|Nome da função|Bytes|Valor inicial|Permissão|Faixa de valores|Unidade|Instruções|
|-|-|-|-|-|-|-|-|-|
|5|0x05|ID do servo|1|1|Leitura/escrita|0 ~ 253|ID|Identificador de ID principal, único no barramento|
|6|0x06|Taxa de transmissão|1|0|Leitura/escrita|0 ~ 7|Nenhum|Os valores 0–7 correspondem às taxas: 1000000 (0), 500000 (1), 250000 (2), 128000 (3), 115200 (4), 76800 (5), 57600 (6), 38400 (7)|
|7|0x07|Endereço reservado|1|--|Leitura/escrita|--|--||
|8|0x08|Nível de resposta|1|1|Leitura/escrita|0 ~ 1|Nenhum|0: não responde a instruções, exceto READ e PING; 1: responde a todas as instruções|
|9|0x09|Limite mínimo de ângulo|2|0|Leitura/escrita|0 ~ 4094|0,087°|Defina como 0 para controle de posição absoluta multivoltas|
|11|0x0B|Limite máximo de ângulo|2|4095|Leitura/escrita|1 ~ 4095|0,087°|Defina como 0 para controle de posição absoluta multivoltas|
|13|0x0D|Limite superior de temperatura|1|70|Leitura/escrita|0 ~ 100|°C||
|14|0x0E|Tensão máxima de entrada|1|--|Leitura/escrita|0 ~ 254|0.1V||
|15|0x0F|Tensão mínima de entrada|1|40|Leitura/escrita|0 ~ 254|0.1V||
|16|0x10|Torque máximo|2|1000|Leitura/escrita|0 ~ 1000|0.1%|O valor de torque é aplicado ao limite de torque no endereço 48|
|18|0x12|Fase|1|--|Leitura/escrita|0 ~ 254|Nenhum|Byte de função especial; não altere sem necessidade específica|
|19|0x13|Condição de desligamento de torque|1|--|Leitura/escrita|0 ~ 254|Nenhum|Defina o bit correspondente como 1 para ativar a proteção ou 0 para desativá-la|
|20|0x14|Condição de alerta do LED|1|--|Leitura/escrita|0 ~ 254|Nenhum|Defina o bit correspondente como 1 para ativar o alerta piscante ou 0 para desativá-lo|
|21|0x15|Ganho proporcional P do controle de posição|1|--|Leitura/escrita|0 ~ 254|Nenhum|Ganho proporcional do controle do motor (1/4)|
|22|0x16|Ganho derivativo D do controle de posição|1|--|Leitura/escrita|0 ~ 254|Nenhum|Ganho derivativo do controle do motor (1/8)|
|23|0x17|Ganho integral I do controle de posição|1|0|Leitura/escrita|0 ~ 254|Nenhum|Ganho integral do controle do motor|
|24|0x18|Torque inicial mínimo|1|--|Leitura/escrita|0 ~ 254|0.1%|Define o torque de inicialização mínimo de saída do servo|
|25|0x19|Limite integral|1|0|Leitura/escrita|0 ~ 254|Nenhum|Valor integral máximo = limite integral × 4; 0 desativa o limite. Aplicável aos modos de posição 0 e 4|
|26|0x1A|Zona morta positiva|1|1|Leitura/escrita|0 ~ 16|0,087°|A unidade mínima é um incremento da resolução angular mínima|
|27|0x1B|Zona morta negativa|1|1|Leitura/escrita|0 ~ 16|0,087°|A unidade mínima é um incremento da resolução angular mínima|
|28|0x1C|Corrente de proteção|2|511|Leitura/escrita|0 ~ 2047|6.5mA|Corrente máxima configurável: 500 × 6,5 mA = 3250 mA|
|30|0x1E|Resolução angular|1|1|Leitura/escrita|1 ~ 128|Nenhum|Fator de ampliação da resolução angular mínima do sensor|
|31|0x1F|Deslocamento de posição|2|0|Leitura/escrita|0 ~ 8191|0,087°|0–2047 representa 0–2047; 2048–4095 representa 0 a −2047; 4096–6143 representa 2048–4095; 6144–8191 representa −2048 a −4095 (deslocamento de −4095 a 4095)|
|33|0x21|Modo de operação|1|0|Leitura/escrita|0 ~ 3|Nenhum|0: servo de posição; 1: velocidade constante do motor; 2: controle de velocidade PWM em malha aberta; 3: modo de passos|
|34|0x22|Torque mantido|1|20|Leitura/escrita|0 ~ 254|1%|Torque de saída após entrar na proteção contra sobrecarga; 20 significa 20% do torque máximo|
|35|0x23|Tempo de proteção|1|200|Leitura/escrita|0 ~ 254|10ms|Tempo durante o qual a carga atual deve exceder o torque de sobrecarga para iniciar a proteção; 200 significa 2 s, máximo de 2,5 s|
|36|0x24|Torque de sobrecarga|1|80|Leitura/escrita|0 ~ 254|1%|Limite de torque máximo que inicia a contagem da proteção contra sobrecarga; 80 significa 80% do torque máximo|
|37|0x25|Ganho proporcional P do controle de velocidade|1|--|Leitura/escrita|0 ~ 254|Nenhum|Ganho proporcional do controle de velocidade no modo de velocidade constante do motor (modo 1)|
|38|0x26|Tempo de proteção contra sobrecorrente|1|200|Leitura/escrita|0 ~ 254|10ms|Máximo configurável: 254 × 10 ms = 2540 ms|
|39|0x27|Ganho integral I do controle de velocidade|1|--|Leitura/escrita|0 ~ 254|Nenhum|Ganho integral do controle de velocidade no modo de velocidade constante do motor (modo 1)|

## 2.3 Controle da SRAM
Endereço DEC|Endereço HEX|Nome da função|Bytes|Valor inicial|Permissão|Faixa de valores|Unidade|Instruções|
|-|-|-|-|-|-|-|-|-|
|40|0x28|Chave de torque|1|0|Leitura/escrita|0 ~ 2|Nenhum|Gravar 0: desativa a saída de torque; gravar 1: ativa a saída; gravar 2: ativa a saída de amortecimento (o limite de torque, endereço 48, controla sua intensidade); gravar 128: calibra qualquer posição atual como 2048|
|41|0x29|Aceleração|1|0|Leitura/escrita|0 ~ 254|8,7°/s²|Aceleração/desaceleração do servo; 0 significa aceleração máxima|
|42|0x2A|Posição-alvo|2|0|Leitura/escrita|-32767 ~ 32767|0,087°|No controle de posição absoluta, o máximo corresponde ao maior ângulo válido; BIT15 indica a direção|
|44|0x2C|Velocidade PWM em malha aberta|2|1000|Leitura/escrita|0~1000|0.1%|Aplicável ao modo PWM de velocidade em malha aberta; BIT10 indica a direção|
|46|0x2E|Velocidade de operação|2|Velocidade máxima padrão de fábrica do servo|Leitura/escrita|-32767 ~ 32767|0.732RPM/0.0146RPM|Controla a velocidade máxima do motor; BIT15 indica a direção. Por padrão, velocidade 0 significa velocidade máxima; pela configuração de fase, 0 também pode significar parado. A fase seleciona a unidade: 0,732 RPM ou 0,0146 RPM. Mesmo ao selecionar 0,0146 RPM, a precisão continua sendo 0,732 RPM.|
|48|0x30|Limite de torque|2|Torque máximo (16), padrão 1000|Leitura/escrita|0 ~ 1000|0.1%|O usuário pode alterar este valor no programa para controlar o torque de saída em caso de travamento|
|50~54|0x32~0x36|Não definido|1|--|Leitura/escrita|--|--||
|55|0x37|Flag de bloqueio|1|1|Leitura/escrita|0 ~ 1|Nenhum|Gravar 0 desbloqueia a escrita e salva os valores da EPROM após desligar; gravar 1 bloqueia a escrita e não salva alterações da EPROM após desligar|

## 2.4 Feedback da SRAM
|Endereço DEC|Endereço HEX|Nome da função|Bytes|Valor inicial|Permissão|Faixa de valores|Unidade|Instruções|
|-|-|-|-|-|-|-|-|-|
|56|0x38|Posição atual|2|--|Somente leitura|--|0,087°|Retorna a posição absoluta atual do servo; BIT15 indica a direção. No modo de passos 3, retorna a diferença em passos entre a posição atual e a posição-alvo; BIT15 indica a direção|
|58|0x3A|Velocidade atual|2|--|Somente leitura|--|0.732RPM/0.0146RPM|Retorna a velocidade atual do motor; a unidade depende da configuração de fase; BIT15 indica a direção|
|60|0x3C|Carga atual|2|--|Somente leitura|--|0.1%|Ciclo de trabalho da tensão de saída de controle que aciona o motor; BIT10 indica a direção|
|62|0x3E|Tensão atual|1|--|Somente leitura|--|0.1V|Tensão de operação atual do servo|
|63|0x3F|Temperatura atual|1|--|Somente leitura|--|°C|Temperatura interna atual do servo|
|64|0x40|Flag de gravação assíncrona|1|0|Somente leitura|--|Nenhum|Flag usada com a instrução de gravação assíncrona|
|65|0x41|Estado do servo|1|0|Somente leitura|--|Nenhum|Um bit correspondente em 1 indica o erro correspondente|
|66|0x42|Flag de movimento|1|0|Somente leitura|--|Nenhum|1 enquanto o servo está em movimento; 0 quando atinge o alvo e para. Sem atualização da posição-alvo, permanece em 0|
|67|0x43|Posição-alvo|2|0|Somente leitura|--|0,087°|Posição-alvo atual|
|69|0x45|Corrente atual|2|--|Somente leitura|--|6.5mA|Retorna a corrente de fase atual do motor|
|71|0x47|Não definido|2|--|Somente leitura|--|--||

## 3.5 Parâmetros de fábrica
|Endereço DEC|Endereço HEX|Nome da função|Bytes|Valor inicial|Permissão|Faixa de valores|Unidade|Instruções|
|-|-|-|-|-|-|-|-|-|
|80|0x50|Limite de velocidade de movimento|1|--|Somente leitura|--|--|--|
|81|0x51|DTs(ms)|1|--|Somente leitura|--|--|--|
|82|0x52|Fator da unidade de velocidade|1|--|Somente leitura|--|--|--|
|83|0x53|Limite mínimo de velocidade|1|--|Somente leitura|--|--|Unidade: 0,732 rpm|
|84|0x54|Limite máximo de velocidade|1|--|Somente leitura|--|--|Unidade: 0,732 rpm|
|85|0x55|Limite de aceleração|1|--|Somente leitura|--|--|--|
|86|0x56|Multiplicador de aceleração|1|--|Somente leitura|--|--|O multiplicador de aceleração é usado quando a aceleração é 0. Se o multiplicador e a aceleração forem ambos 0, o servo responde na velocidade máxima|

# 3. Interpretação de bytes especiais
## 3.1 Fase do servo
- **Número do bit / peso do bit:**
- BIT0 (1): fase da direção de acionamento — (0) direta, (1) reversa
- BIT1 (2): modo da ponte de acionamento — (0) sem escovas, (1) com escovas; aplicado após reinicialização
- BIT2 (4): unidade de velocidade — (0) 0,732 RPM, (1) 0,0146 RPM
- BIT3 (8): modo de velocidade — (0) velocidade 0 significa parado, (1) velocidade 0 significa velocidade máxima
- BIT4 (16): modo de feedback angular — (0) ângulo de uma volta, (1) ângulo total
- BIT5 (32): configuração da ponte de acionamento — (0) ponte H independente, (1) ponte H integrada/sem feedback de corrente
- BIT6 (64): frequência PWM — (0) 24 kHz, (1) 16 kHz
- BIT7 (128): fase da direção de feedback de posição — (0) direta, (1) reversa
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">Ao definir vários bits, o valor da fase do servo é a soma dos respectivos pesos. Exemplo: se a fase original for 0 e o servo operar no sentido inverso, o valor será 128+1=129.
</div> 

## 3.2 Estado do servo
**Estado do servo: 0 = normal; 1 = anormal**
- **Número do bit / peso do bit:**
- BIT0 (1): estado da tensão
- BIT1 (2): estado do encoder magnético
- BIT2 (4): estado da temperatura
- BIT3 (8): estado da corrente
- BIT4 (16): —
- BIT5 (32): estado da carga
- BIT6 (64): —
- BIT7 (128): —
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">Quando há vários estados, o valor do estado do servo é a soma dos pesos dos bits. Exemplo: sobretensão/subtensão e superaquecimento do servo resultam em 4+1=5.
</div> 

## 3.3 Condições de desligamento de torque
**Condição de desligamento de torque: 0 = desativada; 1 = ativada**
- **Número do bit / peso do bit:**
- BIT0 (1): proteção de tensão
- BIT1 (2): proteção do encoder magnético
- BIT2 (4): proteção contra superaquecimento
- BIT3 (8): proteção contra sobrecorrente
- BIT4 (16): —
- BIT5 (32): sobrecarga
- BIT6 (64): —
- BIT7 (128): —
- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">Ao definir vários bits, o valor da condição de desligamento do servo é a soma dos pesos. Exemplo: proteção de tensão e proteção térmica ativadas resultam em 4+1=5.
</div>

## 3.4 Condições de alerta do LED
**Condição de alerta do LED: 0 = desativada; 1 = ativada**
- **Número do bit / peso do bit:**
- BIT0 (1): alerta de tensão
- BIT1 (2): alerta do encoder magnético
- BIT2 (4): alerta de superaquecimento
- BIT3 (8): alerta de sobrecorrente
- BIT4 (16): —
- BIT5 (32): alerta de sobrecarga
- BIT6 (64): —
- BIT7 (128): —

- <div style="padding: 8px 16px;background-color: #fff9e9;border-radius: 4px;border-left: 5px solid #fbc302;margin: 20px 0;">Ao definir vários bits, o valor da condição de alerta do LED do servo é a soma dos pesos. Exemplo: alertas de tensão e superaquecimento ativados resultam em 4+1=5;
</div>
