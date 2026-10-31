# Uso do servo-web como estação Web no host

A estação Web servo-web no RK3566 permite visualizar em tempo real a postura do IMU e o estado dos servos pelo navegador do computador.

---

## 1. Pré-requisitos

| Item | Requisito |
|---|---|
| Firmware da placa IMU | Firmware de protocolo Feetech FT-SCS v1.0.0 gravado (ID=200, 1 Mbps) |
| RK3566 | servo-web clonado em `/gitclone/microduck-replica/tools/servo-web/` |
| Porta serial do barramento | `/dev/ttyS2` (serial integrada à placa RK3566, conectada diretamente ao barramento do IMU) |
| Rede | RK3566 e computador na mesma rede local (IP de wlan0, por exemplo, `<IP do Duck>`) |
| Navegador | Chrome / Edge / Firefox (com suporte a WebSocket e ES Module) |

## 2. Inicialização do serviço

### 2.1 Acesse o RK3566 por SSH ou serial

```bash
# Via SSH (é necessário já ter configurado o SSH)
ssh root@<IP do Duck>

# Ou pelo console serial USB (COM8 @ 1500000 baud)
# Conecte com um terminal serial ou Python pyserial e entre como root
```

### 2.2 Pare serviços que possam conflitar

servo-web e robotd disputam o acesso a `/dev/ttyS2`; pare o robotd antes de iniciar:

```bash
systemctl stop robotd
```

### 2.3 Inicie `server.py`

```bash
cd /gitclone/microduck-replica/tools/servo-web
nohup python3 server.py \
  --port /dev/ttyS2 \
  --imu-bus \
  --host 0.0.0.0 \
  --http-port 8080 \
  > /tmp/servo-web.log 2>&1 &
```

Descrição dos parâmetros:

| Parâmetro | Significado |
|---|---|
| `--port /dev/ttyS2` | Dispositivo da porta serial do barramento |
| `--imu-bus` | Habilita o modo de barramento do IMU (ID 200 é lido junto dos servos na mesma chamada sync_read) |
| `--host 0.0.0.0` | Escuta em todas as interfaces de rede (permite acesso externo) |
| `--http-port 8080` | Porta HTTP/WebSocket |
| `> /tmp/servo-web.log 2>&1 &` | Executa em segundo plano e grava os logs em `/tmp/servo-web.log` |

### 2.4 Confirme que o serviço iniciou

```bash
# Confira o processo
ps aux | grep server.py

# Confira os logs (devem indicar que o barramento foi aberto e o IMU habilitado)
tail -20 /tmp/servo-web.log
```

Exemplo de log normal:

```
[Bus] Aberto /dev/ttyS2 @ 1000000 8N1
[IMU] IMU do barramento habilitado: ID 200 lido com os servos na mesma sync_read (a leitura ocorre quando há uma página conectada)
```

## 3. Acesso pela Web

### 3.1 Abra a página

No navegador do computador, acesse:

```
http://<IP do Duck>:8080/
```

> Use o IP real de wlan0 do RK3566. Consulte-o com `ip addr show wlan0`.

### 3.2 Estrutura da página

O título da página é “Estação de depuração de servos do Duck”. De cima para baixo:

1. **Estado da conexão:** ponto verde no canto superior esquerdo = WebSocket conectado.
2. **Área de busca de servos:** clique em “Buscar” para procurar dispositivos no barramento.
3. **Área de controle de servos:** botão de torque e controles deslizantes para posição e velocidade-alvo.
4. **Painel de postura do IMU** (`Postura do tronco · IMU`):
   - Etiqueta de modo: `Barramento · ID 200`.
   - Etiqueta de estado: `Aguardando dados` → `Acompanhamento em tempo real` (fica verde após receber dados válidos).
   - Ângulos de rolagem, inclinação e guinada (graus).
   - Contagem de amostras, frequência de leitura (Hz) e tensão de referência (V).
   - Aceleração em g (três eixos) e velocidade angular em °/s (três eixos).
   - Contadores de erros: IMU / SPI / FIFO.
   - Botões: “Zerar postura exibida” e “Postura original”.
   - Menu suspenso para direção de instalação (permite selecionar diferentes orientações).
5. **Área de gerenciamento de posturas:** salva, carrega e envia posturas predefinidas.
6. **Área de visualização 3D:** postura do tronco (derivada do quaternion do IMU) e postura das articulações (derivada das posições dos servos).
7. **Área de logs:** logs atualizados em tempo real na parte inferior.

### 3.3 Comece a visualizar os dados do IMU

**Depois de conectar à página Web, a leitura dos dados do IMU começa automaticamente; não é necessária nenhuma configuração adicional.**

Após estabelecer a conexão WebSocket, o loop de consulta de `server.py` inicia automaticamente e inclui o ID 200 em cada quadro sync_read. O painel do IMU muda de “Aguardando dados” para “Acompanhamento em tempo real”, e os ângulos e dados de amostragem passam a ser atualizados continuamente.

### 3.4 Confira se os dados do IMU estão normais

Verifique no painel do IMU:

| Campo | Valor normal | Diagnóstico se estiver anormal |
|---|---|---|
| Etiqueta de estado | `Acompanhamento em tempo real` (verde) | Se mostrar “Aguardando dados”/“Dados inválidos”, confira a alimentação da placa IMU e se o firmware foi gravado |
| Etiqueta de modo | `Barramento · ID 200` | Se o painel não aparecer, confirme que `server.py` foi iniciado com `--imu-bus` |
| Rolagem/inclinação/guinada | Muda quando a placa é girada | Se os valores não mudarem, confira o cabeamento do barramento e se `/dev/ttyS2` está ocupado |
| Contagem de amostras | Aumenta continuamente | Se não aumentar, não há resposta do barramento; confira se a placa IMU está energizada |
| Hz de leitura | 30–60 Hz | Se for zero ou muito baixo, confira se outro processo está usando o barramento |
| Aceleração/velocidade angular | Valores nos três eixos | Se todos mostrarem `—`, `validPacket` não passou; confira os campos `ready/configured` |

### 3.5 Operação dos servos (opcional)

1. Clique em “Buscar” e aguarde a conclusão (cerca de 2 segundos).
2. Os servos encontrados aparecem na lista de dispositivos online.
3. Clique em “Ligar torque” para habilitar o torque dos servos.
4. Arraste os controles para definir as posições-alvo ou clique em um botão de postura predefinida.
5. Ao terminar, clique em “Desligar torque”.

> **Segurança:** com o torque ligado, os servos exercem força de retenção. Antes de começar, confira se nada interfere no curso das alavancas dos servos.

## 4. Etapas de teste

### 4.1 Teste básico de conexão

1. Confirme que a placa IMU está energizada e conectada a `/dev/ttyS2`.
2. Pare o robotd: `systemctl stop robotd`.
3. Inicie `server.py` (consulte a seção 2.3).
4. Confira se os logs não mostram erros: `tail -20 /tmp/servo-web.log`.
5. Abra `http://<IP do Duck>:8080/` no navegador do computador.
6. O ponto verde no canto superior esquerdo indica que a conexão WebSocket foi estabelecida.
7. O painel do IMU aparece e mostra “Acompanhamento em tempo real”.

### 4.2 Validação dos dados do IMU

1. Deixe a placa IMU parada e confira se os ângulos permanecem estáveis (rolagem/inclinação próximas de 0°).
2. Incline a placa devagar; os ângulos de rolagem/inclinação devem acompanhar o movimento.
3. Gire a placa horizontalmente; o ângulo de guinada deve mudar. **Atenção:** a guinada de um IMU de seis eixos sofre deriva, o que é normal.
4. Confirme que a contagem de amostras aumenta e a frequência de leitura fica entre 30 e 60 Hz.
5. Os contadores de erro (IMU/SPI/FIFO) devem permanecer em 0.

### 4.3 Zerar e restaurar a postura original

1. Coloque a placa na postura desejada como “posição zero”.
2. Clique em “Zerar postura exibida”: a postura atual passa a 0° (afeta somente a exibição da página; não grava no hardware).
3. Gire a placa e observe os ângulos em relação à posição zero.
4. Clique em “Postura original” para voltar a exibir a postura original, incluindo a direção de instalação.

### 4.4 Teste conjunto com os servos

1. Clique em “Buscar” e confirme que os servos aparecem online.
2. Clique em “Ligar torque”.
3. Arraste o controle de posição; o servo deve se mover.
4. Observe ao mesmo tempo se os dados do painel IMU continuam chegando (IMU e servos são lidos no mesmo quadro).
5. Ao terminar, clique em “Desligar torque”.

### 4.5 Validação de leitura simultânea de vários dispositivos

1. Conecte a placa IMU e um ou dois servos Feetech ao barramento.
2. Inicie `server.py` e abra a página Web.
3. Confirme que a busca encontra o IMU (ID 200) e os servos.
4. Confira se “Acompanhamento em tempo real” do IMU e as posições dos servos são atualizados simultaneamente.
5. A frequência de leitura deve permanecer estável, sem queda perceptível por causa dos dispositivos adicionais.
6. Os logs não devem mostrar erros `ck_err`/timeout.

## 5. Como parar o serviço

```bash
# Localize o PID
ps aux | grep server.py

# Pare o processo
kill <PID>

# Ou encerre com um único comando
pkill -f 'python3 server.py'

# Reinicie o robotd, se necessário
systemctl start robotd
```

## 6. Problemas comuns

| Sintoma | O que verificar |
|---|---|
| O navegador não abre a página | Confira se o RK3566 está ligado, se o IP está correto e se o firewall permite a porta 8080 |
| Ponto cinza no canto superior esquerdo (sem conexão) | Confira se `server.py` está em execução; use `ps aux \| grep server.py` para verificar o processo |
| Painel do IMU não aparece | Confira se `server.py` recebeu `--imu-bus` e se os logs dizem “IMU habilitado” |
| Estado “Aguardando dados” | Confira a alimentação da placa IMU, o cabeamento do barramento e se o robotd está usando `/dev/ttyS2` |
| Todos os ângulos mostram `—` | `validPacket` não passou: confirme se o quadro live de `imu_bus.py` contém `ready=1, configured=1` |
| Contagem de amostras não aumenta | Sem resposta do barramento: confira se o firmware da placa IMU é a versão com protocolo Feetech e se a alimentação está normal |
| Frequência de leitura igual a 0 | Não há página Web conectada (a consulta só inicia com um cliente WebSocket) ou o sistema está calibrando |
| Busca não encontra servos | Confira a alimentação dos servos (`VDD_BUS`), se os IDs estão na faixa de busca e o cabeamento do barramento |
| Servo não se move | Depois da busca, confira se clicou em “Ligar torque” e se os registradores de modo/velocidade estão corretos |
| Log mostra `ck_err`/timeout | Interferência no barramento, cabos longos ou falta de terminação; confira se o ID 200 está no fim da lista SYNC READ |
| `/dev/ttyS2` está ocupado | Consulte o processo com `fuser /dev/ttyS2` e encerre-o ou execute `systemctl stop robotd` |

---

## 7. Protocolo Feetech FT-SCS

### 7.1 Formato dos quadros

A placa IMU usa o protocolo de barramento half-duplex Feetech FT-SCS (Feetech Servo Communication Serial) e opera na mesma linha que os servos Feetech SCS/STS. Todos os quadros têm o mesmo formato:

```
Quadro de solicitação: FF FF  ID  LEN  INST  P1..Pn  CK
Quadro de resposta:    FF FF  ID  LEN  ERR   D1..Dd  CK
```

| Campo | Descrição |
|---|---|
| `FF FF` | Cabeçalho (2 bytes fixos: 0xFF 0xFF) |
| `ID` | Endereço do dispositivo (1 byte; 0xFE=broadcast, 1~252=unicast) |
| `LEN` | Comprimento (1 byte; = 2 + quantidade de bytes de parâmetros/dados) |
| `INST`/`ERR` | Código de instrução (solicitação) / código de erro (resposta) |
| `P1..Pn`/`D1..Dd` | Parâmetros (solicitação) / dados (resposta) |
| `CK` | Checksum (1 byte) |

Comprimento total do quadro = 4 + LEN bytes.

### 7.2 Algoritmo de checksum

```
CK = ~(ID + LEN + INST/ERR + sum(P1..Pn/D1..Dd)) & 0xFF
```

- Soma todos os bytes de ID até o último byte de dados e mantém os 8 bits inferiores.
- Inverte os bits e mantém os 8 bits inferiores.
- O cabeçalho FF FF não participa do cálculo do checksum.

Implementação no firmware (`protocol.c`):

```c
uint8_t proto_checksum(const uint8_t *bytes, uint16_t length) {
    uint16_t sum = 0;
    for (uint16_t i = 0; i < length; ++i)
        sum += bytes[i];
    return ~(uint8_t)(sum & 0xFF);
}
```

### 7.3 Conjunto de instruções

| Código | Nome | Descrição |
|---|---|---|
| 0x01 | PING | Responde um quadro de estado vazio em unicast; PING em broadcast não recebe resposta |
| 0x02 | READ | Lê registradores (addr u8, count u8); unicast |
| 0x03 | WRITE | Grava registradores (addr u8, data...); ACK em unicast, silêncio em broadcast |
| 0x82 | SYNC READ | Leitura em broadcast (addr, count, id...); cada ID responde em sequência conforme a lista |
| 0x83 | SYNC WRITE | Gravação em broadcast (addr, dlen, [id, data]...); sem resposta |

Os registradores de identidade da placa IMU (endereços 0~9) são somente para leitura; WRITE é recusado com ERR_ACCESS(7). O endereço 85 (`user_marker`) aceita gravação de 1 byte; escrever 0xA5 no endereço 240 solicita a reinicialização do IMU.

### 7.4 Códigos de erro

| Código | Nome | Significado |
|---|---|---|
| 0 | OK | Sucesso |
| 1 | RESULT | Erro de resultado |
| 2 | INSTRUCTION | Instrução inválida |
| 3 | CRC | Erro de checksum |
| 4 | RANGE | Endereço fora da faixa |
| 5 | LENGTH | Comprimento inválido |
| 6 | LIMIT | Limite excedido |
| 7 | ACCESS | Acesso negado (gravação em área somente leitura ou de identidade etc.) |

### 7.5 Regra de respostas SYNC READ em ordem

SYNC READ é uma instrução de broadcast; vários dispositivos respondem em sequência de acordo com a lista de IDs. A resposta da placa IMU (ID=200) funciona assim (`protocol.c`):

1. **ID 200 em primeiro lugar** (`i == 2`): responde diretamente, mas os servos Feetech podem começar antes e causar colisão (somente 3/30 sucessos observados). **Não use essa ordem.**
2. **ID 200 no fim da lista:** aguarda a resposta do ID anterior no barramento e então responde (30/30 sucessos observados).
3. **Predecessor sem resposta ou com checksum inválido:** a placa IMU ignora esta rodada para evitar colisão.
4. **Proteção de timeout:** se a espera pelo predecessor exceder 25 ms (`PROTO_TRANSACTION_TIMEOUT_US`), a transação é cancelada automaticamente.

> **O host deve colocar o ID 200 depois dos servos** (`[IDs dos servos..., 200]`) ou em um grupo separado (`[200]`).

---

## 8. Definição dos registradores

### 8.1 Área de identidade (endereços 0~9, somente leitura)

| Endereço | Campo | Valor | Descrição |
|---|---|---|---|
| 0 | Versão principal do firmware | 1 | |
| 1 | Versão secundária do firmware | 0 | |
| 2 | Ordem dos bytes | 0 | 0=little-endian |
| 3-4 | Modelo | 0x4D44 | Byte menos significativo primeiro (3=0x44, 4=0x4D) |
| 5 | ID do dispositivo | 200 | Fixo, não pode ser alterado |
| 6 | Código de baud rate | 0 | 0 = 1.000.000 bit/s |
| 7 | Reservado | 0 | |
| 8 | Nível de estado | 1 | Retorna código de erro (quando diferente de 0) |
| 9 | Reservado | 0 | |

### 8.2 Bloco rápido (endereços 56~70, 15 bytes)

O bloco ocupa os mesmos endereços do estado dos servos Feetech (56). Uma chamada SYNC READ 56/15 lê a placa IMU e todos os servos ao mesmo tempo.

| Deslocamento | Endereço | Campo | Tipo | Descrição |
|---|---|---|---|---|
| 0-1 | 56-57 | Giroscópio X | i16 LE | Faixa ±500 dps, 17,5 mdps/LSB |
| 2-3 | 58-59 | Giroscópio Y | i16 LE | Igual ao anterior |
| 4-5 | 60-61 | Giroscópio Z | i16 LE | Igual ao anterior |
| 6-7 | 62-63 | Quaternion X | fp16 (binary16) | Formato SFLP, componente x |
| 8-9 | 64-65 | Quaternion Y | fp16 | Formato SFLP, componente y |
| 10-11 | 66-67 | Quaternion Z | fp16 | Formato SFLP, componente z |
| 12 | 68 | Contador de amostras | u8 | 8 bits inferiores do contador de registros SFLP; aumenta de 1 a 4 por quadro |
| 13 | 69 | Bits de estado | u8 bitfield | Consulte a seção 8.3 |
| 14 | 70 | Reservado | u8 | Fixo em 0; `server.py` valida esse valor |

O componente w do quaternion não é transmitido no barramento; o host o reconstrói:

```python
norm2 = x*x + y*y + z*z
w = sqrt(max(0, 1 - norm2))    # se norm2 > 1, normaliza xyz
```

Conversão do giroscópio:

```python
gyro_dps = raw_i16 * 0.0175    # 17,5 mdps/LSB → dps
```

### 8.3 Definição dos bits de estado (endereço 69)

| Bit | Nome | Valor | Significado |
|---|---|---|---|
| BIT0 | FUSION_NOT_READY | 0x01 | Fusão não pronta (quaternion zerado ou logo após ligar) |
| BIT1 | IMU_COMM_FAIL | 0x02 | Falha de comunicação do IMU (SPI/reset/configuração/FIFO/dados obsoletos/quaternion) |
| BIT2 | SELF_TEST_FAIL | 0x04 | Falha no autoteste (`WHO_AM_I` diferente de 0x70) |
| BIT3 | READER_TOO_SLOW | 0x08 | Host lê devagar demais (pelo menos 5 atualizações SFLP entre duas leituras) |

Lógica de definição no firmware (`control_table.c`):

```c
if (!s->ready || quat_fp16_all_zero)  bits |= BIT0;  // fusão ainda não produziu dados
if (error in SPI/RESET/CONFIG/STALE/FIFO/QUAT) bits |= BIT1;  // falha de comunicação
if (error == ID)                      bits |= BIT2;  // falha no autoteste
if (sample_count_delta >= 5)          bits |= BIT3;  // leitura lenta demais
```

Comportamento de `server.py` para cada estado:

| Estado | Comportamento de `server.py` |
|---|---|
| BIT0 ativo | O quadro recebe `status="stale"` (a fusão ainda não produziu dados; cerca de 0,5 s após ligar é normal) |
| BIT1 ativo | O quadro recebe `status="error"` (falha de comunicação; confira soldas/cabeamento) |
| BIT2 ativo | O quadro recebe `status="error"` (falha no autoteste; confira a solda do chip IMU) |
| BIT3 ativo | O quadro live recebe um aviso de leitura lenta; a validade dos dados não muda |
| byte 14 ≠ 0 | O quadro recebe `status="error"` (byte reservado diferente de 0; firmware incompatível com o protocolo) |

### 8.4 Área de expansão (endereços 71~85)

| Endereço | Campo | Tipo | Descrição |
|---|---|---|---|
| 71-76 | Aceleração X/Y/Z | i16 × 3 LE | Faixa ±4 g, 0,122 mg/LSB |
| 77 | WHO_AM_I | u8 | LSM6DSV16X = 0x70 (112) |
| 78 | Código de erro | u8 | Valor do enum `imu_error_t` |
| 79 | Estado do clock | u8 | |
| 80 | Watchdog habilitado | u8 | |
| 81-84 | Contador de amostras | u32 LE | Total de registros SFLP (32 bits) |
| 85 | Marcador do usuário | u8 | Gravável, fica na RAM (perdido quando a alimentação é desligada) |

### 8.5 Área de diagnóstico (endereços 90~185, 96 bytes)

24 palavras u32 little-endian, na seguinte ordem:

| Deslocamento | Endereço | Nome | Descrição |
|---|---|---|---|
| 0 | 90 | `gyro_count` | Total de amostras do giroscópio |
| 1 | 94 | `accel_count` | Total de amostras do acelerômetro |
| 2 | 98 | `uptime_ms` | Tempo de execução (ms) |
| 3 | 102 | `gyro_age_ms` | Milissegundos desde os últimos dados do giroscópio |
| 4 | 106 | `quat_age_ms` | Milissegundos desde o último quaternion |
| 5 | 110 | `spi_errors` | Quantidade de erros de comunicação SPI |
| 6 | 114 | `fifo_overflows` | Quantidade de overflows FIFO |
| 7 | 118 | `invalid_quaternions` | Quantidade de quaternions inválidos |
| 8 | 122 | `recovery_count` | Quantidade de recuperações do IMU |
| 9 | 126 | `rx_overflows` | Overflow da recepção UART RX |
| 10 | 130 | `uart_errors` | Erros UART |
| 11 | 134 | `checksum_errors` | Erros de checksum do protocolo |
| 12 | 138 | `malformed_packets` | Quantidade de pacotes malformados |
| 13 | 142 | `receive_timeouts` | Timeouts de recepção |
| 14 | 146 | `rx_packets` | Pacotes recebidos |
| 15 | 150 | `tx_packets` | Pacotes transmitidos |
| 16 | 154 | `cancelled_replies` | Respostas canceladas |
| 17 | 158 | `reset_flags` | Flags de reset |
| 18 | 162 | `clock_hz` | Frequência do clock |
| 19 | 166 | `tx_timeouts` | Timeouts de transmissão |
| 20 | 170 | `log_dropped` | Logs descartados |
| 21 | 174 | `diag_revision` | Versão da tabela de diagnóstico (=1) |
| 22 | 178 | `tx_busy_drops` | Transmissões descartadas porque o barramento estava ocupado |
| 23 | 182 | `reserved` | Reservado |

---

## 9. Lógica de validação

### 9.1 Validação no firmware (quadros de solicitação recebidos)

`proto_feed()` em `protocol.c` recebe os bytes um a um e faz as seguintes verificações:

1. **Busca do cabeçalho:** espera dois bytes 0xFF; aceita FF excedentes; reinicia se encontrar algo diferente de 0xFF.
2. **Validação de ID:** 0x00 e 0xFF são inválidos e reiniciam a busca.
3. **Validação de LEN:** descarta LEN < 2 ou > 132 (`PROTO_MAX_FRAME_LEN`).
4. **Validação do checksum:** `complete_packet()` calcula o checksum dos bytes de ID até o penúltimo; compara com o último byte. Se não corresponder, incrementa `checksum_errors++` e não executa a instrução.
5. **Validação da instrução:** verifica quantidade de parâmetros, faixa de endereços, unicidade da lista de IDs em SYNC READ etc.

### 9.2 Validação em `server.py` (bloco de 15 bytes analisado)

`feed()` em `imu_bus.py` valida item a item o bloco de 15 bytes retornado pelo ID 200:

| Verificação | Ação em caso de falha | Estado correspondente |
|---|---|---|
| Comprimento do bloco = 15 | Não deve ocorrer (sync_read tem comprimento fixo) | — |
| Byte reservado (offset 14) == 0 | `status="error"` | Firmware incompatível com o protocolo |
| BIT2 (falha no autoteste) ativo | `status="error"` | `WHO_AM_I` diferente do esperado |
| BIT1 (falha de comunicação) ativo | `status="error"` | SPI/reset/configuração/FIFO |
| BIT0 (não pronto) ativo ou quaternion todo zero | `status="stale"` | A fusão ainda não produziu dados |
| Os primeiros 12 bytes idênticos por pelo menos 8 quadros consecutivos | `status="stale"` | Dados congelados |
| Erro ao decodificar fp16 do quaternion | `status="error"` | Quaternion inválido |
| Todas as verificações anteriores passam | `status="live"` | Dados normais |

### 9.3 Validação no frontend (exibição dos dados)

`validPacket()` em `imu_attitude.js` exige que todas as condições abaixo sejam satisfeitas ao mesmo tempo:

| Condição | Descrição |
|---|---|
| `live === true` | Quadro marcado como live |
| `status === "live"` | Texto do estado corresponde |
| `ready === 1` | IMU pronto (flag ready do firmware) |
| `configured === 1` | IMU configurado (flag configured do firmware) |
| `connected === true` | Conexão do barramento normal |
| `quaternion_xyzw` Array(4) | Quaternion é um vetor de 4 elementos |
| Todos os 4 elementos são finitos | Nenhum `NaN`/`Infinity` |
| Módulo > 0,5 e < 1,5 | Verificação de plausibilidade do quaternion |
| `sample_count` é um inteiro seguro não negativo | Contagem de amostras válida |

Se qualquer condição falhar, ângulos/contagem/Hz aparecem como `—` na página e a etiqueta de estado fica amarela.

> Nota: `ready` e `configured` são definidos como 1 no quadro live por `imu_bus.py` em `server.py`. Se estiverem ausentes (por exemplo, em uma versão antiga de `imu_bus.py`), os dados são transmitidos, mas a página mostra `—`.

---

## 10. Fluxo de dados e mecanismo de consulta

### 10.1 Condições para iniciar a consulta

A lógica `stream_should_poll()` de `server.py` é:

```
há cliente WebSocket && (há servo online || imu_backend=="bus") && calibração não está bloqueada
```

Em outras palavras, **a consulta só acontece enquanto uma página está conectada**. Os dados do IMU são transmitidos pela coroutine independente `imu_stream`, sem bloquear o fluxo dos servos.

### 10.2 Ordem da lista `sync_read`

A lista de IDs de `sync_read` em `read_states_with_imu()` é construída assim:

```python
ids_sent = servo_ids + ([imu_bus.IMU_ID] if with_imu else [])
#          ^^^^^^^^^^                          ^^^^^^^^^^^^^^^^
#          servos primeiro                     IMU por último
```

**O IMU precisa ficar no final; não pode ficar no início.**
- No início: o IMU responde diretamente enquanto um servo Feetech também começa a transmitir → colisão no barramento → bytes desalinhados (0xFF aparece na área de dados) → erro de checksum.
- No final: o IMU aguarda a resposta do último servo e então transmite → sem colisão (30/30 sucessos).
- Em grupo isolado `[200]`: não há outros dispositivos → sem colisão.

> **Atenção:** quando `PRESENT` está vazio (nenhum servo encontrado), `ids_sent = [200]` e a leitura do IMU isolado não colide. Quando servos ficam online, `[200] + servo_ids` causa colisões — esse era o motivo dos dados do IMU aparecerem de forma intermitente.

### 10.3 Fluxo de dados

```
Servos Feetech (ID=2..) ──┐
                          ├──> /dev/ttyS2 ──> server.py sync_read ──> WebSocket ──> navegador
Placa IMU (ID=200) ───────┘    (responde por último)                    ↓             ↓
                                                                  imu_bus.py   imu_attitude.js
                                                                       ↓             ↓
                                                                    feed()      painel do IMU
                                                              (validação/decodificação)
```

### 10.4 Parâmetros de tempo

| Parâmetro | Valor | Descrição |
|---|---|---|
| Baud rate do barramento | 1.000.000 bit/s | 8N1 |
| Taxa de amostragem do IMU | 120 Hz | Frequência de fusão SFLP interna do chip |
| Frequência de consulta do host | ~30–60 Hz | Depende da quantidade de dispositivos no barramento e da atualização da Web |
| Timeout entre bytes | 1500 µs | Descarta o quadro se o intervalo entre bytes exceder esse valor |
| Timeout da transação | 25.000 µs | Cancela SYNC READ se exceder a espera pelo predecessor |
| Validade da resposta | 2.000 µs | Cancela a resposta pronta que não for transmitida dentro desse prazo |
| Expiração dos dados no host | 1.000 ms | Marca como stale um quadro publicado há mais tempo |
| Limite de dados congelados | 8 quadros | Marca congelado se os 12 primeiros bytes forem idênticos em 8 quadros seguidos |
| Limite de leitura lenta | 5 atualizações | Marca BIT3 se houver pelo menos 5 atualizações SFLP entre duas leituras |
