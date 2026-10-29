# Sem HAT · substitua por módulos de ¥70 e fios

**Chinês simplificado**

> O HAT oficial é uma placa de quatro camadas, com componentes nos dois lados e 110 componentes. Fazer um protótipo e montá-lo custa mais de mil yuans, o que muita gente considera caro demais.
> Esta é uma alternativa: um módulo conversor de tensão, uma placa adaptadora half-duplex e o restante com fios. **As únicas funções perdidas são o áudio integrado e o sinal de detecção de desligamento.**

Leia primeiro a [introdução ao hardware](Hardware入门.md), que explica a função do HAT; depois, este guia mostra como usá-lo sem a placa.

[![Diagrama de fiação sem HAT](../assets/hw/不打HAT-Fiação图.png)](不打HAT-Fiação图.html)

> **O arquivo-fonte do diagrama é [`不打HAT-接线图.html`](不打HAT-接线图.html)** — contém SVG embutido; abra-o no navegador para ampliar, selecionar texto e imprimir em A3.
> Altere esse arquivo para trocar o módulo ou os pinos. A imagem PNG acima é apenas uma prévia no GitHub.

**Objetivo**: alimentar a placa principal pela bateria, comunicar-se com o barramento de servos através da placa adaptadora e ligar o ToF ao I²C da placa principal — **sem montar o HAT**. Módulos de ¥70 substituem um protótipo que custaria mais de mil yuans.

> ⚠️ **Este guia é um plano ainda não executado.** A fiação vem das especificações e dos esquemas oficiais; o software foi analisado a partir do código oficial `setup-board.sh`.
> Corrija aqui qualquer etapa que não funcionar durante a montagem. Depois de validar, remova a seção “Ainda não testado; precisa validar”.

## Lista de compras

Links de lojas podem expirar; **termos de busca e especificações tendem a durar**. Pesquise cada item e use os critérios de seleção. Depois de escolher, inclua o link na [lista de compras do controle eletrônico](电控Lista de compras.md).

| Item | Termo de busca | O que conferir antes de comprar | Preço aproximado |
|---|---|---|---:|
| **Conversor de tensão** | “UBEC 5V 3A 2S” | **Limite inferior de entrada ≤6 V** (muitos módulos anunciados para 2–6S só regulam a partir de 7 V; a bateria 2S quase descarregada cai abaixo disso) · saída de pelo menos 2 A contínuos · conversor síncrono; **não compre LM2596** | ¥10–15 |
| **Adaptador half-duplex** | “placa controladora servo de barramento serial ST SC” | Versão TTL ou USB. **A alimentação lógica deve aceitar 3,3 V** (se aceitar apenas 5 V, não conecte à placa principal) · lado dos servos deve suportar até 8,4 V. **Se já tiver uma FE-URT-2, ela é a versão USB e pode dispensar esta compra** (veja a etapa 4) | ¥22 |
| Barra de pinos 2×20 | “barra de pinos colorida Raspberry Pi 2x20” | 2,54 mm · vertical · cores ajudam a contar os pinos | ¥1 |
| 2 cartões microSD de alta resistência | “SanDisk High Endurance 64G” ou “Hikvision PLUS 64G” | **Loja oficial JD** · rótulo High Endurance / uso em câmeras · **não** modelos comuns Ultra / EVO | ¥90 cada |
| Leitor de cartões | “leitor TF USB 3.0” | USB 3.0 | ¥15 |
| Fio de silicone | “fio de silicone 18AWG vermelho preto” | 18 ou 20 AWG · capa de silicone (flexível e resistente ao calor) · 1 m de cada cor | ¥10 |
| Porta-fusível e fusível | “porta-fusível 5x20 com fios” + “fusível 5A 5x20” | Porta-fusível com fios facilita a solda · fusível rápido de 5 A | ¥5 |
| Interruptor de alimentação | “interruptor basculante KCD1” | Corrente nominal ≥6 A · simples, de um polo | ¥3 |
| 5 cabos PH2.0 de 3 pinos | “cabo PH2.0 3P ponta única” | Passo de 2,0 mm · 3 pinos · fios em apenas uma ponta e fios desencapados na outra | ¥5 |
| Fios Dupont | “fios Dupont fêmea-fêmea 20cm” | fêmea-fêmea · 20 cm · fileira de 40 fios | ¥5 |
| Capacitor eletrolítico de 470 µF | “capacitor eletrolítico 470uF 16V” | 16 V ou mais · 105 °C | ¥1 |
| *(Opcional) placa de som USB* | “placa de som USB plug and play 3,5 mm” | **Sem driver** (Linux reconhece o padrão UAC) · entrada para microfone | ¥15 |
| *(Opcional) alto-falante pequeno* | “alto-falante 3W 4 ohm” | 4 Ω, 3 W · para usar a saída de 3,5 mm da placa de som, é preciso amplificador; alternativamente, compre uma caixa USB com amplificador | ¥5 |

Sem o HAT, perde-se: **o sinal de detecção de desligamento** (LM5050-1 IO_06), o BMI088 integrado (o software oficial já não o usa) e **o áudio integrado** — é possível substituí-lo por uma placa de som USB, veja a etapa 8.
Sem o sinal de desligamento e usando microSD, o corte abrupto de energia pode danificar o cartão: **desligue o software antes de cortar a alimentação**.

## Etapa 1 · Ligue a placa principal, sem conectar mais nada

> ⚠️ **Os Radxa Zero 3W comprados a partir de novembro de 2024 são da versão V1.12 (módulo Wi-Fi AIC8800), que não inicia com a imagem oficial do Armbian gravada diretamente**:
> os LEDs piscam em pares, o sistema nunca inicia e a placa não aparece na rede. A causa é o U-Boot principal incluído pelo Armbian (firmware de inicialização da memória v1.21 de 2024-01), que não suporta a placa nova. Use o carregador de inicialização da própria Radxa. O sistema oficial Radxa inicia, enquanto o Armbian não.
> Foram necessários dois dias e nove gravações de cartões para descobrir isso; veja [problemas encontrados](../Problemas encontrados.md). O script de preparação abaixo já resolve esse e outros problemas.

**Imagem**: Armbian **26.2.1 · Debian 13 (trixie) · minimal · kernel do fabricante 6.1.115**, versão indicada pela documentação oficial da Pollen.
Os espelhos chineses só mantêm a 26.8.1; a imagem 26.2.1 (376 MB) está aqui:

```
https://fi.mirror.armbian.de/archive/radxa-zero3/archive/Armbian_26.2.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz
```

Não escolha `current_6.18` (kernel principal, incompatível com o runtime oficial) nem a versão desktop.

**1a · Prepare o cartão** (inclui Wi-Fi, senhas, carregador de inicialização e serial na imagem; depois de gravar, basta inserir e conectar por SSH)

Copie os três arquivos de [`tools/radxa/`](../tools/radxa/) para qualquer pasta local. No computador, é necessário ter WSL2 (se não tiver, execute `wsl --install` no PowerShell como administrador e reinicie uma vez):

1. Abra `card.conf` no Bloco de Notas e altere o nome e a senha do Wi-Fi. O usuário e senha padrão são `duck` / `duck1234`. Para instalar software oficial na China, configure `HTTP_PROXY=` com o endereço do proxy no computador (por exemplo, ative “Permitir acesso pela rede local” no Clash e informe `http://IP-do-computador:7890`).
2. Clique com o botão direito em `1-做卡.ps1` → “Executar com PowerShell” e selecione o arquivo `.img.xz` baixado. O script extrai a imagem no WSL, troca o carregador e grava as configurações. Em cerca de um minuto, cria um arquivo `xxx-鸭子卡.img` (2,2 GB).
3. Solde primeiro dois pinos diagonais da barra: vire a placa para conferir se está perpendicular e, em seguida, solde os outros 38.

**1b · Grave o cartão** (Rufus portátil, 2 MB, sem instalação)

1. Baixe `rufus-x.xxp.exe` em [rufus.ie](https://rufus.ie/zh/). Conecte o leitor ao computador e **deixe conectado apenas esse dispositivo USB**, depois abra o Rufus. Se perguntar se deve verificar atualizações pela internet, selecione **Não**:

   <img src="../assets/flash/烧卡-1-Rufus问Atualização-点否.png" width="420">

2. O leitor aparecerá selecionado em “Dispositivo”. Clique em **Selecionar** e escolha o arquivo `xxx-鸭子卡.img` criado acima:

   <img src="../assets/flash/烧卡-2-设备自动选 em -点选择.png" width="380">

3. Clique em **Iniciar**. Quando avisar que os dados do cartão serão apagados, confirme. A gravação leva cerca de dois minutos:

   <img src="../assets/flash/烧卡-3-正在Gravação.png" width="380">

4. Quando a barra de estado voltar a “Pronto”, terminou. Feche o Rufus e remova o cartão. **O Windows pode perguntar várias vezes se deseja formatar o disco; clique em Cancelar em todas**, pois não reconhece as partições Linux.

   <img src="../assets/flash/烧卡-4-Concluído-准备就绪.png" width="380">

**1c · Inicie a placa, encontre o IP e conecte por SSH**

Insira o cartão na Radxa. Conecte uma fonte USB de 5 V (pode ser um carregador Apple de 20 W; não use carregador Huawei de carga rápida) à porta **`5V IN / USB_OTG`** (identificada no verso da placa, perto do cartão TF).
Aguarde de 2 a 3 minutos para ela conectar ao Wi-Fi. Os LEDs devem piscar em pares por alguns segundos, continuar piscando assim por cerca de dois minutos e depois ficar acesos continuamente. Se continuarem piscando sem parar, a inicialização falhou.
No roteador, encontre o dispositivo `radxa-zero3` e copie o IP. No Windows, use o SSH incluído:

```
ssh duck@IP-da-placa        # a senha está em card.conf
```

**Uma forma extra de acesso: o cabo USB também transmite a serial.** Conecte a porta `5V IN` da placa a uma porta USB do computador (que fornecerá energia). O Gerenciador de Dispositivos mostrará “Dispositivo serial USB (COMx)”. Abra um terminal serial a 115200 baud para ver o prompt de login; a senha do root está em `card.conf`. Se o Wi-Fi ou o SSH não funcionar, use esse acesso para investigar.

Só avance quando a placa ligar e aceitar SSH. **Não misture problemas de inicialização com problemas de fiação.**

## Etapa 2 · Fazer `/dev/ttyS2` aparecer

O script de preparação já habilita a porta: adiciona o overlay `uart2-m0` ao extlinux, mantém o console do kernel em `tty1` e desativa (`mask`) `serial-getty@ttyS2` e `ttyFIQ0`. Conecte por SSH e confirme:

```bash
ls -l /dev/ttyS2            # deve existir
sudo fuser -v /dev/ttyS2    # nenhum processo deve estar usando
cat /proc/cmdline           # não deve conter console=ttyS2 nem ttyFIQ0
```

O `setup-board.sh` oficial tenta alterar `overlay_prefix`, `overlays` e `console` em `/boot/armbianEnv.txt`, mas isso não funciona neste cartão: o U-Boot da Radxa usa extlinux e não lê `boot.scr`. As verificações do script ainda passam, então pode executá-lo normalmente. **Se `apt upgrade` atualizar o pacote do kernel, o nome dos arquivos em `extlinux.conf` precisa ser atualizado**; confira `/boot/extlinux/extlinux.conf` antes de atualizar.

Da mesma forma, para acrescentar outro overlay (por exemplo, o da câmera `rk3568-radxa-zero3-rpi-camera-v2.dtbo`, que `setup-board.sh` copia com esse nome), acrescente o caminho ao fim da linha `fdtoverlays` em `extlinux.conf` e reinicie. Sem câmera conectada, `mediad` reiniciará continuamente; os outros itens de `robotctl health` não são afetados.

## Etapa 3 · Alimentação: meça a cada conexão

```
NP-F550 ──► interruptor ──► fusível 5 A ──┬──► conversor ──► 5 V ──► pino 2 (ou 4) da Radxa
                                          │        │
                                          │        └── capacitor de 470 µF na entrada
                                          │
                                          └──► VDD do barramento dos servos (tensão original, fio 18 AWG)
Terra comum: negativo da bateria · terra da saída do conversor · pino 6 da Radxa · GND do barramento
```

```
1. Conecte o interruptor e o fusível; meça: com o interruptor fechado, deve haver continuidade nos terminais do fusível.
2. Conecte o conversor, ainda sem a Radxa. Meça a saída: 5,0 V ±0,2 e polaridade correta.
3. ⚠️ Confira a polaridade antes de conectar a Radxa: os pinos 2/4 não têm proteção; inverter a ligação queima a placa.
4. Desconecte o USB-C da Radxa e ligue-a pelos 5 V no pino 2; confirme que o SSH funciona.
5. Só então conecte o VDD do barramento dos servos.
```

## Etapa 4 · Conectar o barramento dos servos à placa principal

```
Pinos 40 vias da Radxa          Lado MCU da placa adaptadora
pino 1   3,3 V    ──────────►   VCC       ⚠️ somente 3,3 V; com 5 V, o TX pode danificar o RX da placa principal
pino 8   UART2_TX ──────────►   RX        ← cruzado
pino 10  UART2_RX ◄──────────   TX        ← cruzado
pino 6   GND      ──────────►   GND

Lado dos servos na placa adaptadora
DATA  ──► S do barramento dos servos
V     ◄── VDD do barramento (tensão original da bateria, conectada na etapa 3)
G     ──► terra comum
```

**Placa adaptadora USB**: não conecte os pinos 1/8/10; ligue a placa a uma porta USB da Radxa. A serial aparecerá como `/dev/ttyUSB0` ou `/dev/ttyACM0`; altere `port` em `robotd.toml` para corresponder. É mais simples, mas o overlay `uart2-m0` da etapa 2 fica sem uso (o `agetty` continuará desativado, sem causar problema).

> 💡 **A placa de depuração Feetech FE-URT-2 já é uma placa adaptadora USB** — depois de configurar os IDs, transfira-a para o robô: USB-C na porta host da Radxa, pino TTL S no barramento e G no terra do barramento.
> **A tensão original da bateria deve ir diretamente ao barramento dos servos, nunca ao terminal V1 da URT-2** — na V1, a alimentação pode estar conectada diretamente aos 5 V do USB; aplicar 7,4 V pode devolver corrente à Radxa.
> As chaves na placa selecionam o nível lógico (3,3/5 V); selecione 5 V. Nesse caso, pode dispensar a placa adaptadora separada.
> Primeiro verifique se a Radxa reconhece o CH343: execute `dmesg | tail` e procure `ttyACM0`; se não aparecer, o site da WCH oferece o código-fonte do driver Linux.
> É sua única placa de depuração: depois de instalá-la no robô, não poderá configurar os servos pelo computador. **Configure os IDs dos 15 servos antes de transferi-la.**

**Derivações do barramento** — cabeça, perna esquerda e perna direita se ramificam no tronco. O barramento half-duplex de fio único é **paralelo**, não em série: estrela e árvore funcionam; o encadeamento é apenas uma forma conveniente de passar os fios.

```
TTL da placa adaptadora ──┬──► cabeça e pescoço  30 → 31 → 32 → 33 → 34
                          ├──► perna esquerda   20 → 21 → 22 → 23 → 24
                          └──► perna direita    10 → 11 → 12 → 13 → 14
                              (imu_to_dxl 200 em qualquer derivação no tronco)
```

Opções: usar as duas saídas TTL da URT-2 e derivar a terceira a partir de um servo; comprar uma “placa divisora de barramento servo 3P” com uma entrada e quatro saídas (¥5); ou soldar três fios juntos.
**Passe V e G em fios 18 AWG separados até as três derivações**; o fio S pode seguir qualquer percurso. ⚠️ **Não passe toda a corrente das três derivações pela placa `imu_to_dxl`** — os quatro conectores são paralelos, mas as trilhas de cobre da placa de duas camadas não foram dimensionadas para vários ampères e podem queimar. Instale-a no meio ou no fim de apenas uma derivação.

## Etapa 5 · Verificar a comunicação com um único servo

Conecte **apenas um servo**, com o ID já configurado (por exemplo, o joelho esquerdo, ID 23). Na placa principal:

```bash
# Use a ferramenta de referência do barramento incluída no runtime oficial (disponível após a etapa 7), ou faça um ping rápido em Python:
pip install feetech-servo-sdk    # ou scservo_sdk
# 1 Mbps; faça ping ao ID 23 — se responder, a comunicação funciona
```

Se não funcionar, verifique nesta ordem: se `/dev/ttyS2` existe (`ls /dev/ttyS2`) → se algum processo ocupa a porta (`fuser`) → se TX e RX estão cruzados → se VCC da placa adaptadora é 3,3 V → contato do fio S.

## Etapa 6 · ToF

```
VL53L8CX          Pinos 40 vias da Radxa
SDA      ◄──►    pino 3
SCL      ◄──►    pino 5
3V3      ◄───    pino 17     (o pino 1 já alimenta a placa adaptadora; use uma saída separada)
GND      ────►   pino 6
```

A placa já tem resistores pull-up nos pinos 3 e 5; não é preciso instalar outros.

⚠️ **O I²C também precisa de um overlay.** A configuração oficial remultiplexa `i2c3` para M0 (os pinos 3/5), mas isso desativa a negociação USB-C PD.
O overlay oficial está em `deploy/audio/i2c3-pihat.dts` e foi feito para o HAT. **Ainda precisa ser verificado se funciona sem o HAT.**

## Etapa 7 · Instalar e executar o runtime oficial

```bash
curl -fsSL https://raw.githubusercontent.com/pollen-robotics/microduck/main/scripts/provision.sh -o /tmp/provision.sh
sudo sh /tmp/provision.sh
# Executa setup-board.sh → migrate-network.sh → reinicialização → install.sh, tudo automaticamente
robotctl health
```

O `robotd.toml` fica em `/etc/robot/`; a porta serial padrão é `/dev/ttyS2`. Com uma placa adaptadora USB, altere-a para `/dev/ttyUSB0`.

## Etapa 8 · Adicionar som (opcional)

Sem o HAT não há codec: os sons oficiais, a detecção por toque na cabeça, o teclado musical do ToF e o coro de vários patos não funcionam. **A caminhada continua funcionando normalmente**; segundo um comentário do código oficial, “sem a placa de codec, a caminhada é exatamente igual; apenas não há som”.

Para recuperar o áudio, conecte uma **placa de som USB** sem necessidade de driver (reconhecida diretamente pelo Linux):

```bash
aplay -l                          # encontre o nome da placa USB, por exemplo, card 1: Device
sudo nano /etc/robot/robotd.toml
```

```toml
[audio]
enabled = true
device = "plughw:CARD=Device"     # substitua pelo nome mostrado por aplay -l; o padrão oficial é plughw:aic3104
```

```bash
sudo systemctl restart robotd
```

Conecte o alto-falante à saída de 3,5 mm da placa de som (um alto-falante pequeno precisa de amplificador; a opção mais simples é uma caixa USB com amplificador integrado) e o microfone à entrada de microfone.

⚠️ **Ainda não verificado**: os programas oficiais `sounds` e `pet_detect` usam taxa de amostragem e número de canais específicos do aic3104; uma placa USB pode não corresponder. Quando funcionar, atualize esta nota.

## Ainda não testado; precisa validar

| Item | Dúvida | Como verificar |
|---|---|---|
| Placa adaptadora de terceiros a 1 Mbps | O circuito de direção do HAT oficial usa `1G08+1G125+1G126`; a comutação de direção da placa de ¥22 será rápida o bastante? | Concluir a etapa 5 e confirmar que `bench_dynamixel_bus` registra zero erros |
| Overlay `i2c3-pihat.dts` sem o HAT | O overlay foi feito para o HAT | Na etapa 6, `i2cdetect -y 3` deve encontrar 0x29 |
| Capacidade do conversor durante a queda de tensão na partida dos servos | Ao se moverem simultaneamente, os 15 servos podem derrubar a tensão da bateria | Caminhar sem reiniciar a placa principal; se falhar, aumentar o capacitor de entrada |
| Imagem Armbian exata | A documentação oficial informa 26.2.x, mas não especifica minimal ou desktop | Basta conseguir conexão SSH na etapa 1 |
| Placa de som USB como substituta do aic3104 | O código de áudio oficial espera taxas de amostragem próprias do codec | Na etapa 8, `robotctl health` não deve relatar erro de áudio e deve haver som durante a inicialização |

Veja o diagrama no início do documento; o arquivo-fonte está em `不打HAT-接线图.html`, neste mesmo diretório.
