# Protocolo de comunicação do servo SCS

# 1. Visão geral do protocolo de comunicação
&emsp;&emsp;A comunicação utiliza níveis TTL, compatíveis com comunicação de alta velocidade, e o método RS-485, com maior imunidade a interferências. A comunicação é assíncrona e full-duplex; transmissão e recepção são processadas de forma assíncrona.
&emsp;&emsp;O controlador e o servo se comunicam no formato pergunta-resposta: o controlador envia um quadro de comando e o servo retorna um quadro de resposta.
&emsp;&emsp;Uma rede de barramento pode conter vários servos; por isso, cada servo recebe um ID exclusivo nessa rede. Os comandos do controlador contêm o ID, e somente o servo cujo ID corresponda pode receber o comando e retornar uma resposta.
A comunicação é serial assíncrona. Cada quadro contém 1 bit de início, 8 bits de dados e 1 bit de parada, sem bit de paridade, totalizando 10 bits.
&emsp;&emsp;Para alguns parâmetros de dois bytes na tabela de memória, a ordem dos bytes depende do modelo do servo. Servos com potenciômetro usam formato big-endian (byte mais significativo primeiro); servos com encoder magnético usam little-endian (byte menos significativo primeiro). Como as funções variam um pouco entre modelos, consulte a tabela de controle de memória do modelo específico durante a operação.

# 2. Quadro de comando
| Cabeçalho | ID | Comprimento dos dados | Instrução | Parâmetros | Soma de verificação |
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|Instruction|Parameter1 ...Parameter N|Check Sum|

- **Cabeçalho:** a recepção de dois bytes `0xFF` consecutivos indica a chegada de um pacote de dados.
**ID:** cada servo tem um ID. A faixa é de 0 a 253, ou `0x00` a `0xFD` em hexadecimal.
- **ID de broadcast:** o ID 254 é reservado para broadcast. Quando o controlador envia o ID 254 (`0xFE`), todos os servos recebem o comando. Exceto para PING, os demais comandos não geram resposta. Não use PING por broadcast quando vários servos estiverem conectados ao barramento.
- **Comprimento dos dados:** número de parâmetros a enviar, N, mais 2; isto é, `N+2`.
- **Instrução:** código da operação do pacote de dados. Consulte os tipos de instrução na seção 4.
- **Parâmetros:** informações de controle adicionais à instrução. Suporta no máximo um valor de memória representado por dois bytes; para a ordem dos bytes, consulte a tabela de controle de memória do manual do servo (ela varia conforme o modelo).
- **Soma de verificação:** calculada assim:
`Check Sum = ~ (ID + Length + Instruction + Parameter1 + ... + Parameter N)`. Se a soma dentro dos parênteses exceder 255, use somente o byte menos significativo. `~` significa inversão dos bits.

# 3. Quadro de resposta
| Cabeçalho | ID | Comprimento dos dados | Código de estado | Parâmetros | Soma de verificação |
|-|-|-|-|-|-|
|0xFF 0xFF|ID|Length|ERROR|Parameter1 ...Parameter N|Check Sum|

O quadro de resposta contém o estado atual do servo no campo ERROR. Se o servo não estiver funcionando normalmente, esse byte indica a condição (consulte os significados na tabela de controle de memória do manual). Se ERROR for 0, não há erro informado.

# 4. Tipos de instrução
| Instrução | Função | Valor | Comprimento dos parâmetros |
|-|-|-|-|
| PING (consulta) | Consultar estado de funcionamento | 0x01 | 0 |
| READ DATA (leitura) | Consultar dados da tabela de controle | 0x02 | 2 |
| WRITE DATA (gravação) | Gravar dados na tabela de controle | 0x03 | Pelo menos 2 |
| REGWRITE DATA (gravação assíncrona) | Semelhante a WRITE DATA, mas os dados preparados não entram em ação até a chegada de ACTION | 0x04 | Pelo menos 4 |
| ACTION (executar gravação assíncrona) | Acionar a gravação REG WRITE | 0x05 | 0 |
| SYNC READ DATA (leitura síncrona) | Consultar vários servos ao mesmo tempo | 0x82 | Pelo menos 3 |
| SYNC WRITE DATA (gravação síncrona) | Controlar vários servos ao mesmo tempo | 0x83 | Pelo menos 2 |
| RESET (redefinição de estado) | Redefinir o estado do servo (zerar a contagem de voltas) | 0x0A | 0 |
| Calibração de posição | Recalibrar a posição atual para o valor de comando | 0x0B | 0 |
| Comando para restaurar parâmetros | Restaurar os parâmetros do servo, exceto o ID | 0x06 | 0 |
| Comando para fazer backup dos parâmetros | Salvar os parâmetros atuais para uso pelo comando de restauração | 0x09 | 0 |
| Comando de reinicialização | Reiniciar o servo | 0x08 | 0 |

## 4.1 Instrução PING para consultar o estado
- **Função:** ler o estado de funcionamento do servo.
- **Comprimento:** `0x02`.
- **Instrução:** `0x01`.
- **Parâmetros:** nenhum.
- A instrução PING pode usar o endereço de broadcast; nesse caso, os servos também retornam respostas.

**Exemplo 1: ler o estado de funcionamento do servo de ID 1.**
Quadro de comando: `FF FF 01 02 01 FB` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 02
Instrução: 01
Soma de verificação: FB
```

Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 02
Estado: 00
Soma de verificação: FC
```

## 4.2 Instrução READ DATA
- **Função:** ler dados da tabela de controle da memória do servo.
- **Comprimento:** `0x04`.
- **Instrução:** `0x02`.
- **Parâmetro 1:** endereço inicial do trecho de dados a ler.
- **Parâmetro 2:** comprimento dos dados a ler.

**Exemplo 2: ler a posição atual do servo de ID 1 (byte menos significativo primeiro, depois o mais significativo). O endereço da posição na tabela de memória é `0x38`; são dois bytes consecutivos.**

Quadro de comando: `FF FF 01 04 02 38 02 BE` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 04
Instrução: 02
Parâmetros: 38 02 (endereço da posição atual, comprimento dos dados a ler)
Soma de verificação: BE
```

Quadro de resposta: `FF FF 01 04 00 18 05 DD` (exibido em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 04
Estado: 00
Parâmetros: 18 05
Soma de verificação: DD
```
Os dois bytes lidos estão em formato little-endian: byte menos significativo L = `0x18`, byte mais significativo H = `0x05`. Juntos formam o valor de 16 bits `0x0518`; em decimal, a posição atual é 1304.

## 4.3 Instrução WRITE DATA
- **Função:** gravar dados na tabela de controle da memória do servo.
- **Comprimento:** `N+2` (N é o comprimento dos parâmetros).
- **Instrução:** `0x03`.
- **Parâmetro 1:** endereço inicial do trecho onde os dados serão gravados.
- **Parâmetro 2:** primeiro dado a gravar.
- **Parâmetro 3:** segundo dado a gravar.
…
- **Parâmetro N:** enésimo dado a gravar; `N=n+1`.

**Exemplo 3: usar o ID de broadcast (`0xFE`) para definir como 1 o ID de qualquer servo. O endereço do ID na tabela de memória é 5.**
Quadro de comando: `FF FF FE 04 03 05 01 F4` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: FE
Comprimento: 04
Instrução: 03
Parâmetros: 05 01 (endereço do ID, novo valor de ID)
Soma de verificação: F4
```

Como o comando usa o ID de broadcast, não haverá retorno de dados. A memória EPROM tem um bloqueio de proteção; antes de alterar o ID, é necessário desativá-lo (definir como 0), caso contrário o novo ID do exemplo não será salvo após desligar. Consulte a tabela de memória ou o manual de operação do modelo específico para obter instruções detalhadas.

**Exemplo 4: controlar o servo de ID 1 para girar até a posição 2048 à velocidade de 1000 passos por segundo. O endereço inicial da posição-alvo na tabela de memória é `0x2A`; portanto, grave seis bytes consecutivos a partir do endereço `0x2A`.**

- Posição: `0x0800` (2048)
- Reservado: `0x0000` (0)
- Velocidade: `0x03E8` (1000)

Quadro de comando: `FF FF 01 09 03 2A 00 08 00 00 E8 03 D5` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 09
Instrução: 03
Parâmetros:
2A (endereço inicial)
00 08 (posição)
00 00 (reservado)
E8 03 (velocidade)
Soma de verificação: D5
```

Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```language
Cabeçalho: FF FF
ID: FE
Comprimento: 02
Estado: 00
Soma de verificação: FC
```
O estado de funcionamento retornado é 0, o que indica que o servo recebeu o comando corretamente, sem erros, e começou a executá-lo. Como o comando foi enviado a um ID que não é o de broadcast (`0xFE`), o servo retorna um quadro de estado após receber o pacote.

## 4.4 Instrução de gravação assíncrona REG WRITE
A instrução REG WRITE é semelhante a WRITE DATA, mas o momento de execução é diferente. Ao receber um quadro REG WRITE, os dados são armazenados temporariamente no buffer e o registrador de gravação assíncrona é definido como 1. Quando chega a instrução ACTION, os dados armazenados são finalmente aplicados.
- **Comprimento:** `N+2` (N é o comprimento dos parâmetros).
- **Instrução:** `0x04`.
- **Parâmetro 1:** endereço inicial do trecho onde os dados serão gravados.
- **Parâmetro 2:** primeiro dado a gravar.
- **Parâmetro 3:** segundo dado a gravar.
- **Parâmetro N:** enésimo dado a gravar; `N=n+1`.

**Exemplo 5: comandar os servos de ID 1 a ID 10 para girar até a posição 2048 à velocidade de 1000 passos por segundo.**

```language
ID 1 — quadro REG WRITE: FF FF 01 09 04 2A 00 08 00 00 E8 03 D4
ID 1 — resposta: FF FF 01 02 00 FC
ID 2 — quadro REG WRITE: FF FF 02 09 04 2A 00 08 00 00 E8 03 D3
ID 2 — resposta: FF FF 02 02 00 FB
ID 3 — quadro REG WRITE: FF FF 03 09 04 2A 00 08 00 00 E8 03 D2
ID 3 — resposta: FF FF 03 02 00 FA
ID 4 — quadro REG WRITE: FF FF 04 09 04 2A 00 08 00 00 E8 03 D1
ID 4 — resposta: FF FF 04 02 00 F9
ID 5 — quadro REG WRITE: FF FF 05 09 04 2A 00 08 00 00 E8 03 D0
ID 5 — resposta: FF FF 05 02 00 F8
ID 6 — quadro REG WRITE: FF FF 06 09 04 2A 00 08 00 00 E8 03 CF
ID 6 — resposta: FF FF 06 02 00 F7
ID 7 — quadro REG WRITE: FF FF 07 09 04 2A 00 08 00 00 E8 03 CE
ID 7 — resposta: FF FF 07 02 00 F6
ID 8 — quadro REG WRITE: FF FF 08 09 04 2A 00 08 00 00 E8 03 CD
ID 8 — resposta: FF FF 08 02 00 F5
ID 9 — quadro REG WRITE: FF FF 09 09 04 2A 00 08 00 00 E8 03 CC
ID 9 — resposta: FF FF 09 02 00 F4
ID 10 — quadro REG WRITE: FF FF 0A 09 04 2A 00 08 00 00 E8 03 CB
ID 10 — resposta: FF FF 0A 02 00 F3
```

## 4.5 Instrução ACTION para executar a gravação assíncrona
- **Função:** acionar a instrução REG WRITE.
- **Comprimento:** `0x02`.
- **Instrução:** `0x05`.
- **Parâmetros:** nenhum.

1. A instrução ACTION é muito útil ao controlar vários servos ao mesmo tempo.
2. Ao controlar vários servos, ACTION permite que o primeiro e o último servo executem suas respectivas ações simultaneamente, sem atraso entre eles.
3. Para enviar ACTION a vários servos, use o ID de broadcast (`0xFE`); por isso, essa instrução não retorna um quadro de dados.

**Exemplo 6: depois de enviar as instruções de gravação assíncrona para comandar os servos de ID 1 a 10 até a posição 2048, a 1000 passos por segundo, execute a gravação assíncrona.**
```
Quadro de comando: `FF FF FE 02 05 FA`.
Resposta: nenhuma.
```

## 4.6 Instrução de gravação síncrona SYNC WRITE
- **Função:** controlar vários servos ao mesmo tempo.
- **ID:** `0xFE`.
- **Comprimento:** `(L+1)*n+4` (L: comprimento dos dados enviados a cada servo; n: número de servos).
- **Instrução:** `0x83`.
- **Parâmetro 1:** endereço inicial do trecho onde os dados serão gravados.
- **Parâmetro 2:** comprimento dos dados enviados a cada servo (L).
- **Parâmetro 3:** ID do primeiro servo.
- **Parâmetro 4:** primeiro dado a gravar no primeiro servo.
- **Parâmetro 5:** segundo dado a gravar no primeiro servo.
…
- **Parâmetro L+3:** enésimo dado a gravar no primeiro servo.
- **Parâmetro L+4:** ID do segundo servo.
- **Parâmetro L+5:** primeiro dado a gravar no segundo servo.
- **Parâmetro L+6:** segundo dado a gravar no segundo servo.
…
- **Parâmetro 2L+4:** enésimo dado a gravar no segundo servo.
…

Diferentemente de REG WRITE + ACTION, SYNC WRITE tem maior imediatismo: uma única instrução pode alterar de uma vez o conteúdo da tabela de controle de vários servos, enquanto REG WRITE + ACTION faz isso em etapas. Mesmo assim, todos os dados gravados por SYNC WRITE precisam ter o mesmo comprimento e o mesmo endereço inicial.

**Exemplo 7: gravar nos quatro servos de ID 1 a 4, começando no endereço `0x2A`, posição `0x0800`, tempo `0x0000` e velocidade `0x03E8` (byte menos significativo primeiro).**
Quadro de comando: `FF FF FE 20 83 2A 06 01 00 08 00 00 E8 03 02 00 08 00 00 E8 03 03 00 08 00 00 E8 03 04 00 08 00 00 E8 03 58` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: FE
Comprimento dos dados válidos: 20
Instrução: 83
Parâmetros:
2A 06 (endereço inicial, comprimento dos dados)
01 00 08 00 00 E8 03 (comando para o servo ID 1)
02 00 08 00 00 E8 03 (comando para o servo ID 2)
03 00 08 00 00 E8 03 (comando para o servo ID 3)
04 00 08 00 00 E8 03 (comando para o servo ID 4)
Soma de verificação: 58
```

## 4.7 Instrução de leitura síncrona SYNC READ
- **Função:** consultar vários servos ao mesmo tempo.
- **ID:** `0xFE`.
- **Comprimento:** `n+4` (n é o número de servos).
- **Instrução:** `0x82`.
- **Parâmetro 1:** endereço inicial dos dados a ler.
- **Parâmetro 2:** comprimento dos dados a ler.
- **Parâmetro 3:** ID do primeiro servo.
- **Parâmetro 4:** ID do segundo servo.
…
- **Parâmetro N:** ID do enésimo servo; `N=n+2`.

Uma única instrução SYNC READ consulta o conteúdo da tabela de controle de vários servos. A instrução especifica os IDs a consultar; as respostas são retornadas na mesma ordem dos IDs no comando. Todos os dados consultados precisam ter o mesmo comprimento e endereço inicial. Esta instrução está disponível em alguns servos de barramento serial.

**Exemplo 8: consultar posição, velocidade, carga, tensão e temperatura atuais dos servos de ID 1 e 2. O endereço inicial é `0x38`, total de 8 palavras de dados, com o byte menos significativo primeiro.**

Quadro de comando: `FF FF FE 06 82 38 08 01 02 36`.
```language
Cabeçalho: FF FF
ID: FE
Comprimento: 06
Instrução: 82
Parâmetros:
38 08 (endereço inicial dos dados, comprimento)
01 02 (IDs 01 e 02)
Soma de verificação: 36
```

Quadros de resposta:
```language
Servo ID 01: FF FF 01 0A 00 00 08 00 00 00 00 79 1E 55
Servo ID 02: FF FF 02 0A 00 FF 07 00 00 00 00 77 23 53
```
Os quadros de resposta podem ser decodificados conforme a instrução READ DATA.

## 4.8 Instrução RESET para redefinir o estado
- **Função:** redefinir o estado do servo (zerar a contagem de voltas).
- **Comprimento:** `0x02`.
- **Instrução:** `0x0A`.
- **Parâmetros:** nenhum.

**Exemplo 9: redefinir o servo de ID 01.**
```language
Quadro de comando: `FF FF 01 02 0A F2` (enviar em hexadecimal).
Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```

## 4.9 Instrução de calibração da posição
- **Função:** recalibrar a posição atual para o valor definido.
- **Comprimento:** `0x02`.
- **Instrução:** `0x0B`.
- **Parâmetros:** nenhum.

**Observação:** sem parâmetros, a instrução de calibração define a posição atual como zero. A calibração só é compatível com alguns modelos; consulte a tabela abaixo para verificar a compatibilidade.

**Exemplo 10: recalibrar a posição atual como zero.**
```language
Quadro de comando: `FF FF 01 02 0B F1` (enviar em hexadecimal).
Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```

**Exemplo 11: recalibrar a posição atual para 1024.**
Quadro de comando: `FF FF 01 04 0B 00 04 EB` (enviar em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 04
Instrução: 0B
Valor definido: 00 04 (1024)
Soma de verificação: EB
```

Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```language
Cabeçalho: FF FF
ID: 01
Comprimento: 02
Estado: 00
Soma de verificação: FC
```

| Modelo de servo | Versão do firmware | Condição de funcionamento | Observação |
|-|-|-|-|
| Servo SMS | <=2.54 | Nenhuma | Compatível com calibração de zero ao gravar 128 no controle de torque |
| Servo STS | >=3.10 | Nenhuma | Compatível com instruções com e sem parâmetros; compatível com calibração de zero ao gravar 128 no controle de torque |
| Servo HLS | >=3.43 | Nenhuma | Compatível com instruções com e sem parâmetros; não é compatível com calibração de zero ao gravar 128 no controle de torque |

## 4.10 Instrução para restaurar parâmetros
- **Função:** restaurar os parâmetros do servo, exceto o ID.
- **Comprimento:** `0x02`.
- **Instrução:** `0x06`.
- **Parâmetros:** nenhum.

**Exemplo 11: restaurar os parâmetros do servo.**
```language
Quadro de comando: `FF FF 01 02 06 F6` (enviar em hexadecimal).
Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```
**Observação:** desbloqueie os parâmetros da EEPROM antes de restaurar os parâmetros do servo.

## 4.11 Instrução para fazer backup dos parâmetros
- **Função:** fazer backup dos parâmetros para uso pela instrução de restauração.
- **Comprimento:** `0x02`.
- **Instrução:** `0x09`.
- **Parâmetros:** nenhum.

**Exemplo 12: fazer backup dos parâmetros do servo.**
```language
Quadro de comando: `FF FF 01 02 09 F3` (enviar em hexadecimal).
Quadro de resposta: `FF FF 01 02 00 FC` (exibido em hexadecimal).
```
**Observação:** desbloqueie os parâmetros da EEPROM antes de fazer backup dos parâmetros do servo.

## 4.12 Instrução de reinicialização
- **Função:** reiniciar o servo.
- **Comprimento:** `0x02`.
- **Instrução:** `0x08`.
- **Parâmetros:** nenhum.

**Exemplo 13: reiniciar o servo.**
```language
Quadro de comando: `FF FF 01 02 08 F4` (enviar em hexadecimal).
Resposta: nenhuma.
```
**Observação:** desligue o controle de torque antes de reiniciar o servo.
