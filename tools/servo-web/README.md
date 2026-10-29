# servo-web · Bancada web de depuração Feetech

> O modelo 3D da página serve para visualização durante a depuração e ainda usa a geometria de simulação upstream. **Não o exporte como se fosse o modelo mais recente das peças imprimíveis Feetech.** Os modelos estruturais e de montagem ficam no repositório [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).

Conecte a porta serial e arraste os controles no navegador para mover os servos e ver o pato 3D acompanhar. A ferramenta serve para montagem, ajuste do zero e validação de bancada; também é usada nos itens 0–8 da lista de bancada da [arquitetura de adaptação Feetech](../../software/飞特适配架构.md).

![Interface](../../assets/servo-web.png)

- Há 15 controles deslizantes, agrupados por perna esquerda, cabeça e pescoço, e perna direita. A linha amarela indica a posição real do servo; cada um tem um controle de torque. **Antes de ativar o torque, alinhe o alvo com a posição atual**: se a junta foi movida à mão, recebeu uma pose ou foi calibrada enquanto o torque estava desligado, o registrador de alvo ainda conserva o valor antigo. Sem alinhar, o servo pode avançar bruscamente ao ativar o torque. O torque não pode ser ativado se a posição não puder ser lida.
- Leitura de retorno em tempo real: posição, tensão, temperatura, carga, corrente e bits de estado (sobrecorrente, superaquecimento e sobrecarga ficam em vermelho).
- O modelo 3D acompanha as posições reais (usa o modelo MuJoCo do [microduck_rl](https://github.com/apirrone/microduck_rl), Apache-2.0). O sinal ± ao lado de cada junta representa sua direção; fica em `directions.json`, compartilhado por todas as páginas. O 3D, a pose em pé, as sequências e as animações usam esse mapeamento, sem mover o servo. “Copiar tabela de direções do robotd” gera a linha necessária no `robotd.toml`. A direção dos 15 servos foi conferida na unidade real: todos estavam invertidos (a direção de aumento das leituras do HD-1910 é oposta à do XL330, e a montagem copiou a orientação do XL330).
- **Poses**: salve as posições atuais como uma pose e envie-as novamente com um clique. Arquivos JSON com `steps` representam sequências, incluindo a sequência de três passos “levantar”. Poses, postura em pé e posição zero fazem uma transição linear a partir da posição atual durante o tempo configurado; é possível interrompê-la a qualquer momento.
- **Calibração com um clique** (somente Feetech; o XL330 não tem este recurso): coloque o pato na pose de referência e ajuste a leitura de posição “atual” do servo selecionado para o valor de referência. Há três referências:
  - **Zero 2048**: com torque ativado, use o controle deslizante para estender as pernas, deixar as solas verticais, a cabeça olhando para frente e a boca fechada. Apoie o robô antes de calibrar. As poses salvas são convertidas automaticamente para o novo zero.
  - **Dobrada oficial (cabeça e pescoço alinhados)** (recomendado): dobre e apoie o pato, sem segurá-lo suspenso. Flexione os joelhos até os tornozelos encostarem nos servos das coxas (contato mecânico repetível); use um esquadro para deixar o pitch do quadril perpendicular ao tronco; alinhe yaw / roll do quadril, tornozelos, pescoço, cabeça e boca. Valores-alvo: ângulos FOLD oficiais das pernas convertidos pelo sinal ± (com todos os sinais em −1, 22/23 = 1025 e 12/13 = 3071); os demais ficam em 2048. Depois, o zero corresponde ao 2048 oficial e as poses salvas são convertidas automaticamente; os 15 servos são calibrados juntos. Não use os 57° FOLD oficiais para cabeça e pescoço: esse valor não é um ponto de contato e não pode ser ajustado com precisão a olho (veja [`tools/fold_contact`](../fold_contact/)). O alvo dos joelhos é calculado a partir do 1,57 rad (90,0°) oficial; na geometria oficial, o tornozelo encosta no servo da coxa a 89,6°, então a diferença do zero é cerca de 0,36° (4 passos). É possível posicionar as juntas à mão com o torque desligado; ele continuará desligado após a calibração. Ao escolher esta referência, o 3D sobrepõe automaticamente a “dobra para calibração” como guia.
  - **Pose salva** (por exemplo, “encolhido”): deixe o pato encolhido e estável; o contato mecânico posiciona as peças sem precisar segurá-las. O zero continua sendo o 2048 oficial, sem adicionar offset ao código ou à política oficial; poses diferentes usam a mesma leitura de referência e não são deslocadas.

  Ao clicar, aparece uma confirmação com cada servo listado como “agora → novo valor, diferença em graus” (calculada no backend, igual à calibração real). **Diferenças de 30° ou mais pedem uma segunda confirmação, mas não bloqueiam a operação**: um braço do servo montado meia volta fora produz diferença de 180°, que a calibração deve corrigir; porém, uma direção ± invertida também produz 180° de diferença entre esquerda e direita (juntas a ±90° na dobra). Nesse caso, o valor calibrado seria incorreto. Confira primeiro o sinal ±: com torque desligado, mova a junta um pouco à mão e veja se o modelo 3D se move na mesma direção. Depois, o log destaca os servos com diferenças grandes.

  A calibração usa o comando de posição 0x0B (o HD-1910 não reconhece a escrita 128 no controle de torque; veja abaixo). Para cada servo: desbloqueia → lê posição → desliga torque → envia 0x0B → lê de volta → só ajusta o alvo se a leitura conferiu → restaura o torque → bloqueia. O torque fica desligado por apenas alguns milissegundos, sem deixar a junta ceder à gravidade ou saltar. Se a leitura não conferir, não move a junta e informa falha; se houver erro no meio, volta a bloquear. O offset anterior é guardado em `calib/` e pode ser restaurado (somente para as poses deslocadas naquela operação). Ao finalizar, libera apenas os limites de velocidade e aceleração (41, 46), sem reescrever o alvo 42.
- **Operações por servo**: selecione-o em uma lista suspensa com o nome da junta e indicação de offline; exporte todos os registradores 0–86 (JSON / tabela Markdown) para o **inventário de registradores**; reinicie com 0x08; calibre o zero; altere o ID (IDs antigos mostram apenas os online; os novos mostram 15 posições padrão e indicam conflitos); grave registradores por uma lista com nomes, desbloqueando automaticamente a área EEPROM e conferindo a leitura após a gravação.
- Toda a comunicação serial bruta é gravada em log (hexadecimal, nome do registrador e resposta do servo). Isso ajuda a diagnosticar operações Feetech que respondem “sucesso” sem terem sido executadas.
- Os logs são separados por sistema, barramento, movimento, calibração, registradores, poses, direções, IMU e página. Avisos e erros são coloridos e contabilizados; é possível filtrar por categoria, mostrar somente avisos / erros e copiar tudo. Cada evento também é salvo em `logs/servo-web-data.log`; erros incluem traceback. Na calibração, há uma linha por servo com leituras, offsets e respostas de cada etapa. Envie esse arquivo para investigar um problema.
- **Teste de temporização `sync_read`**: lê os 15 servos em conjunto 200 vezes e informa min / média / p99 / máximo e número de falhas.
- **Diagnóstico de servos** (linha de comando, **somente leitura**): `python servo_report.py --port COM5` lê os protetores (condição de descarga 19), bits de estado, temperatura, tensão, corrente, offset e limites angulares. Classifica alertas conforme a etapa 5 do “Registro de depuração” e salva `logs/diagnostico-data.md` e um `.json` correspondente com os valores brutos 0–86. Para uma única unidade, use `--ids 21`; se não souber o ID, use `--scan-all`. A porta serial não pode estar sendo usada pela bancada ou pelo FD ao mesmo tempo.
- **Diagnóstico remoto**: [`远程排查交接.md`](远程排查交接.md) descreve um fluxo para Claude Code em outro computador (diagnóstico → inspeção individual → ativar proteção → calibração dobrada). Na outra máquina, peça: “Leia `tools/servo-web/远程排查交接.md` e me guie pelo procedimento”.
- **Autoteste**: `python selftest.py`, sem servos conectados. [`sim_bus.py`](sim_bus.py) é um simulador de protocolo HD-1910 que transmite pacotes Feetech byte a byte e simula bloqueio, torque, 0x0B, a recusa do HD-1910 à escrita 128, offsets e desconexões. Ele permite que o `feetech.py` e o `server.py` reais executem calibração, reversão, alteração de ID, gravação e exportação. Ao alterar código que controla servos, rode-o antes de testar no robô.
- O backend não depende do SDK Feetech. [`feetech.py`](feetech.py), com pouco mais de cem linhas, constrói os pacotes conforme o manual de protocolo de 2026 (em [`docs/飞特资料/`](../../docs/飞特资料/)).
## Como executar

```bash
pip install -r requirements.txt
python server.py --port COM5                 # Windows + URT-2; confira a porta no Gerenciador de Dispositivos
python server.py --port /dev/ttyUSB0         # na placa, com URT-2 na porta USB
python server.py --port /dev/ttyS2           # UART2 pelo conector de 40 pinos (requer adaptador half-duplex; veja abaixo)
python server.py --fake                      # sem servos: modo de simulação
```

**Modo de simulação** (sem porta serial): os servos virtuais seguem curvas trapezoidais conforme os registradores de velocidade e aceleração reais. Poses, controles, sequências, animações e posturas oficiais movem o 3D na mesma velocidade do hardware real. O torque começa ativado, sem gravidade. No painel “Simulação”, no alto à direita, escolha uma IMU: nenhuma; uma placa virtual no ID 200 do barramento simulado (mesmo caminho de `--imu-bus`); ou uma placa virtual desconectada, para observar como a bancada remove o ID 200 da leitura conjunta, faz PING separado e o adiciona de volta. Conecte o USB, escolha a porta serial na barra superior e clique em “Conectar” para usar os servos reais; o painel de simulação some e a placa de IMU virtual é desconectada.

A simulação também permite ensaiar a calibração em um clique e a reversão: ela altera apenas os servos virtuais e guarda a cópia de segurança no diretório temporário do sistema, **sem tocar em `calib/` ou `poses/`**. Se um offset virtual fosse parar em `calib/`, clicar em “Reverter” com servos reais conectados o gravaria neles. Salvar uma pose ou mudar o sinal ± continua sendo uma operação explícita e grava arquivos normalmente.

Se não conseguir abrir a porta serial, a aplicação não cai: a página abre com o barramento simulado. A barra superior mostra um seletor serial; conecte o USB, escolha a porta e clique em “Conectar” para alternar sem reiniciar.

Abra `http://127.0.0.1:8080` no navegador. Se a aplicação estiver rodando na placa, use o IP dela; o celular também pode acessar. Os IDs padrão são `20-24,30-34,10-14`; informe outros com `--ids`. Os arquivos do modelo 3D estão prontos em `model/`. Para gerá-los novamente:

```bash
python build_model.py --src <microduck_rl>/src/mjlab_microduck/robot/microduck
```

### Depurar pela rede Wi-Fi com placa principal + HAT

Confirme que a placa obteve um endereço Wi-Fi e aceita login SSH; siga as [instruções da imagem da placa](../radxa/镜像使用说明.md#4-连-wifi). Copie este diretório e as dependências para a placa. Confirme que programas como `robotd` não estão usando `/dev/ttyS2` e execute:

```bash
python server.py --port /dev/ttyS2 --ids 20-24,30-33,10-14 --host 0.0.0.0 --http-port 8080
```

Conecte o computador ou celular à mesma rede local e abra `http://IP-da-placa:8080`. O exemplo exclui a boca; ajuste os IDs se quiser incluí-la. A página pode controlar os servos físicos: use apenas em uma rede confiável. Desde a versão 0.15.2, iniciar ou conectar a serial apenas faz a varredura e lê a fase; não remove mais automaticamente os limites de velocidade e aceleração. Os botões de movimento e calibração ainda enviam comandos reais.

Desde a versão 0.15.4, a frequência-alvo de leitura do estado dos servos reais e de envio à web é **50 Hz** (antes, 10 Hz); o modo de simulação continua em 30 Hz. “Atualização”, na barra superior, indica a frequência com que a web realmente recebe o estado e depende do tempo serial, timeouts, escalonamento do sistema e rede. Aumentar a frequência de leitura não altera poses, habilitação ou cadência dos comandos e não significa que o ciclo completo de controle a 50 Hz, incluindo IMU, inferência da política e gravação dos comandos, tenha sido validado.

Os controles deslizantes escrevem apenas a posição-alvo e preservam as configurações atuais de velocidade / aceleração do servo. Se a fase definir velocidade 0 como parada e o valor atual for 0, arrastar o controle pode não mover a junta. Antes de mover, confirme as proteções, o apoio e o espaço mecânico; use a função explícita de transição suave com velocidade definida.

Para comparar com uma conexão direta do adaptador USB-serial ao computador, primeiro pare o programa de depuração da placa; depois desligue o sistema normalmente, corte a alimentação e troque os cabos. Com a alimentação restabelecida, no computador execute `python server.py --port COM<número-real> --ids 23` para comparar o mesmo servo. Não deixe o controlador HAT e o adaptador USB-serial enviarem comandos simultaneamente ao mesmo barramento. O relatório somente leitura também pode ser gerado com `python servo_report.py --port COM<número-real> --ids 23`.

## Poses oficiais: mover até a pose e comparar com sobreposição 3D

A aba “Poses oficiais” contém quatro keyframes do `scene.xml` do microduck_rl: **zero** (todos em 2048), **em pé** (STAND), **sentado** (SIT) e **dobrado** (FOLD).

- **“Mover”** converte os ângulos oficiais em leituras, aplicando o sinal ± de cada servo e o zero atual, e faz a transição pelo tempo configurado. **Ao enviar a pose dobrada, os joelhos flexionam apenas 88°**: pela malha exata, na geometria oficial o tornozelo encosta no servo da coxa quando o quadril está a 90°, o tornozelo a 0° e o joelho a 89,6°. Os 90° oficiais pressionariam o servo contra a peça (veja [`tools/fold_contact`](../fold_contact/)).
- **“Sobreposição 3D”** desenha um segundo pato azul semitransparente na pose oficial e lista, abaixo, a diferença angular por junta entre “real − oficial” (amarelo acima de 2°, vermelho acima de 5°). Quando o robô está nessa pose, a diferença mostra o erro do zero.

## Opcional: orientação do tronco pela IMU (barramento de servos / ST-Link / DAPLink / J-Link)

A bancada pode combinar duas fontes no **mesmo modelo**: os ângulos das juntas dos servos continuam movimentando as articulações e o quaternion da IMU controla a orientação do tronco. Reutiliza o serviço, `/ws`, os arquivos de modelo e o CDN; não inicia outro serviço web. Sem parâmetros de IMU, essa área fica oculta e a função serial existente continua normal.

Compatível com a placa já validada **STM32G031F8P6 + LSM6DSV16X**. O modo J-Link requer Windows x64, Python 3.11 ou superior, driver USB SEGGER J-Link instalado à parte e `JLink_x64.dll`. O firmware da placa e as instruções de gravação estão em [`hardware/imu_to_dxl/firmware/`](../../hardware/imu_to_dxl/firmware/); esquemas e conexões, no [índice de hardware](../../hardware/imu_to_dxl/). J3.1 vai a GND, J3.2 a SWCLK, J3.3 a SWDIO e **J3.6 a VTref**; J3.4/5 são seriais e não devem ser usados como referência de alimentação.

1. Copie `imu-jlink.example.json` para `imu-jlink.json` e preencha `dll` e `probe_serial`. O arquivo está ignorado pelo Git.
2. Feche o modo de depuração do Keil, J-Link Commander e similares para liberar a sonda; o firmware HEX correspondente já deve estar executando na placa.
3. Em `tools/servo-web/`, execute um dos comandos abaixo; o navegador continua em `http://127.0.0.1:8080`:

```bash
python server.py --port COM5 --imu-jlink imu-jlink.json  # serial dos servos + IMU real
python server.py --fake --imu-jlink imu-jlink.json       # somente placa IMU; juntas demonstrativas
python server.py --fake --imu-demo                       # ambas as fontes são simuladas
```

Os caminhos do JSON são relativos ao próprio arquivo. `dll` pode conter um caminho completo como `E:/SEGGER/JLink/JLink_x64.dll`, mas deve apontar para a instalação real. `firmware` é opcional; por padrão, usa `hardware/imu_to_dxl/firmware/Build/imu_to_dxl.hex` do repositório. `hz` aceita 1–20; `resume` é `false` por padrão. Defina `resume: true` apenas se precisar explicitamente retomar a CPU pausada e depois de validar o firmware. Não há número de série padrão e a sonda não é selecionada automaticamente.

Ao receber a primeira orientação válida, a referência visual zero é definida automaticamente; também é possível apoiar a placa e clicar em “Zerar”. A montagem padrão aplica rotação de +90° em Y (`DEFAULT_MOUNT`); ajuste conforme a montagem física e zere novamente. Essas ações afetam apenas a página: não gravam nada na IMU, nos servos ou na Flash. A tela zerada mostra orientação relativa; “orientação bruta” também é relativa à referência da inicialização da IMU.

### Mais simples: `--imu-bus`, leitura direta do barramento de servos

Com a placa pequena conectada ao barramento de servos (desde o firmware 0.2.0, protocolo Feetech), **não é necessário nenhum depurador**: o URT-2 lê servos e IMU pela mesma conexão.

```bash
python server.py --port COM5 --imu-bus      # barramento real: 15 servos + ID 200
python server.py --fake --imu-bus           # sem hardware: uma placa falsa no barramento simulado
```

- Envia a mesma chamada `sync_read` do controlador principal a cada ciclo: endereço 56, tamanho 15, **ID 200 primeiro**, seguido pelos servos. A resposta dos servos é decodificada como antes; o bloco 200 usa os critérios do controlador (quaternion totalmente zero = fusão ainda sem saída; rejeita norm² > 1,02; 25 quadros consecutivos sem alteração nos 12 bytes = congelado; bytes reservados precisam ser zero; bits BIT1/BIT2 indicam falhas reportadas pela própria placa), iguais aos de `tools/imu200`.
- A especificação diz que, se a placa não responder, as respostas dos servos posteriores na mesma chamada sync_read também podem se perder. Por isso, após **5 quadros consecutivos sem resposta do 200**, ele é removido da leitura conjunta; os servos são lidos sozinhos e o ID 200 recebe um PING separado a cada 2 s. Quando responder, é reintegrado. A bancada continua útil sem a placa e o log da categoria IMU explica a falha.
- Compatível com a placa `imu_to_dxl` no protocolo DXL 2.0 original: altere o protocolo na página ou use `--imu-bus-protocol dxl2`; o padrão continua Feetech. O modo DXL2 lê ID 200, endereço 124, tamanho 12.
- A leitura contínua ocorre apenas enquanto a interface web está conectada, no mesmo ciclo de atualização do estado dos servos; é pausada durante calibração. Na bancada, é possível conectar somente a placa IMU: mesmo que a varredura não encontre servos, o ID 200 ainda é lido.
- Com taxa-alvo de 50 Hz no barramento real, o firmware de 120 Hz normalmente atualiza 2–3 vezes entre leituras. Se o ciclo real ficar mais lento, o BIT3 (“leitura muito lenta”) ainda pode aparecer. Até a versão 0.15.3, a leitura era 10 Hz e havia cerca de 12 atualizações entre leituras. A bancada não trata BIT3 isoladamente como alarme; preserva os bits originais no quadro (`status_bits`).
- Uma placa com firmware 0.1.0 (Dynamixel 2.0) não responde no modo Feetech padrão. Mantenha o firmware e escolha o modo compatível DXL2, ou grave o 0.2.0 indicado em [`firmware/`](../../hardware/imu_to_dxl/firmware/) e use o modo Feetech padrão. No DXL2, a IMU e os servos Feetech são lidos em duas transações seriais; no modo Feetech, continua sendo usada a leitura conjunta descrita acima.

### Sem J-Link: `--imu-swd` (ST-Link / DAPLink via pyOCD)

O processo é o mesmo: verifica a tensão-alvo, compara byte a byte a Flash da placa e lê o mesmo snapshot da RAM. Não grava firmware nem memória. Usa [pyOCD](https://pyocd.io/); **funciona com ST-Link e CMSIS-DAP (DAPLink)** sem arquivo de configuração. **Para J-Link, use `--imu-jlink`**: conectar o J-Link via pyOCD pode aplicar 5 V pelo pino 19 e atualizar silenciosamente o firmware da sonda, contornando as proteções daquele caminho; por isso `--imu-swd` rejeita J-Link.

```bash
pip install pyocd
python server.py --fake --imu-swd                           # com uma sonda, seleciona automaticamente
python server.py --fake --imu-swd 301612179216303030303032  # com várias, indique o UID (consulte com pyocd list)
python server.py --port COM5 --imu-swd                      # serial dos servos + IMU real
```

- A fiação é igual à anterior: J3.1 GND, J3.2 SWCLK, J3.3 SWDIO, J3.6 ao **VTref / TVCC** da sonda (somente medição de tensão; não alimenta a placa). A placa recebe alimentação pelo barramento. Se o depurador tiver uma saída de 3,3 V (o pino 19 de alguns ST-LINK/V2, por exemplo), **não a conecte junto à alimentação do barramento**.
- O conector de 20 pinos ST-LINK/V2 varia conforme a versão: pinos 4/6/8/10 podem ser GND; outros podem ser UART, BOOT0 ou SWIM. **Use apenas os pinos 12/18/20 para GND.**
- Conecta em modo `attach`: não reinicia nem pausa a CPU e não envia Go ao desconectar. Não carrega `pyocd.yaml` nem scripts do usuário no diretório atual. Ainda grava registradores de depuração (DHCSR.C_DEBUGEN etc.) e deixa C_DEBUGEN ligado após desconectar; portanto, não tem impacto absolutamente nulo. Na medição de 2026-09-22, com ST-LINK/V2 V2J43S7 a 100 kHz, três conexões consecutivas mantiveram o temporizador do chip sincronizado com o relógio e **não reiniciaram a placa**; atualização em cerca de 20 Hz e idade dos dados de 6–11 ms.
- Antes de conectar ao chip, verifica a tensão-alvo. Apenas ST-Link consegue medi-la: fora de 3,0–3,5 V, a conexão é recusada (próximo de 0 V, avisa para conferir VTref/TVCC ou a alimentação da placa). O DAPLink não informa tensão; a página mostra “—” e não bloqueia. As mensagens distinguem “não foi possível abrir o depurador” (ocupado pelo Keil / CubeProgrammer ou firmware ST-Link antigo) de “não foi possível conectar ao chip” (fiação ou alimentação).
- Para voltar ao Keil ou CubeProgrammer, pare este serviço para liberar o depurador.

Conexões, erros, mudanças de estado e calibração visual são gravados em `logs/servo-web-data.log`, na categoria **IMU**; não são registrados todos os quadros. Ao parar o serviço, a sonda J-Link / ST-Link / DAPLink é liberada. Para usar o Keil, primeiro pare o serviço; fechar apenas a aba do navegador não libera a sonda. A interface ainda não permite reconectar ou reiniciar a sonda pela web; após resolver uma falha, reinicie o serviço.

### Verificação do firmware e escopo da validação

- Envie somente um arquivo `.hex`; não é necessário baixar `.bin` ou `.map`. Os backends SWD / J-Link verificam os registros Intel HEX e a imagem contínua da Flash. Após decodificação, o firmware 0.2.0 tem **10.724 bytes**, SHA-256 `66bc7c532f5a1ad87e3dfff71a4b51f8c4f20840a8f62436874fa5b7c665938e` e layout de RAM `sample=0x2000006C`, `tick=0x20000A34`. Apenas essa imagem usa o layout de RAM revisado; após conectar, o conteúdo real da Flash também é comparado byte a byte. Firmware diferente não permite ler a orientação nem retomar a CPU.
- Ao mudar o firmware, confira primeiro a estrutura, os endereços e os tamanhos no novo MAP; depois atualize o hash e o layout validados. Não remova apenas a verificação do hash. Esta ferramenta não grava firmware.
- Leituras anteriores em placa real com J-Link 9.78 e SWD a 100 kHz chegaram a cerca de 20 Hz; uma sessão SDK chegou a reiniciar a placa e não pode ser considerada observação sem perturbação. A versão integrada passou por autotestes sem hardware, mas **a operação simultânea com servo real e IMU real ainda não foi validada**; precisa ser conferida no robô quanto aos eixos e à estabilidade prolongada.
- **O firmware 0.2.0 incluído já usa o protocolo Feetech** (ID 200, bloco de 15 bytes no endereço 56). O código do protocolo real passou em `imu200.py check` com barramento simulado, mas **o barramento físico ainda não foi testado**. Uma imagem SWD normal não comprova a validação do barramento real nem do `FeetechIo`. Antes de integrar ao robô, execute `imu200.py check --port`.
- O rumo da IMU de seis eixos deriva com o tempo. A página não mede translação nem confirma contato físico dos pés. O centro de massa e a área de apoio continuam estimativas da geometria do modelo; não comprovam que o robô completo consegue ficar em pé ou caminhar de forma estável. Em caso de perda do fluxo, a última orientação é preservada e marcada como inválida.

### Regressão sem hardware

```bash
pip install -r requirements-test.txt
python selftest.py
python -m pytest test_feetech_sync.py test_imu_bridge.py test_imu_server.py test_imu_swd.py test_imu_bus.py test_dxl2.py test_sim.py test_servo_report.py
node --test test_imu_attitude.cjs
```

Node.js é usado apenas nos testes matemáticos da interface; não é necessário para usar normalmente a bancada. Os testes de host do firmware e registros de testes em placa real estão em [VALIDATION.md](../../hardware/imu_to_dxl/firmware/VALIDATION.md).

## Atenção

- **Conecte o USB do URT-2 antes de alimentar os servos.** Se fizer o contrário, o nível do barramento pode ficar preso em 2,1 V; a varredura não encontra nenhum servo e só recebe alguns zeros em broadcast. Veja [problemas encontrados](../../踩坑记录.md#工具).
- **Antes de usar `ttyS2` na placa, execute `sudo systemctl stop robotd`**. O daemon oficial abre essa porta a cada segundo para procurar servos; se os dois programas transmitirem ao mesmo tempo, os pacotes colidem. Usar URT-2 em `ttyUSB0` evita esse conflito.
- **Não ligue `ttyS2` diretamente aos fios do servo esperando resposta.** A UART da Radxa é full-duplex, com dois fios de 3,3 V; o barramento Feetech é half-duplex e de fio único. É necessário um buffer tri-state (como no HAT oficial) ou um circuito adaptador baseado no chip do URT-2. Depois de montar o adaptador, use o teste de temporização da página para verificar eco: um eco faz todos os servos parecerem “sem resposta”.
- Calibrar o zero e alterar IDs grava a EEPROM; a página pede confirmação. Ao trocar um ID, deixe somente aquele servo conectado ao barramento.
- **HD-1910 (firmware 3.46) não reconhece o valor 128 para ativar / desativar torque.** Embora a tabela de memória diga que esse valor calibra o zero, em quatro rodadas com 15 servos cada, desbloquear, desligar torque e gravar 128 retornou “sucesso”, mas não alterou nenhum offset. A tabela 4.9 do manual de protocolo também informa que HLS ≥3.43 não oferece suporte. Use sempre 0x0B para calibrar.
- “Todos para 2048” move imediatamente qualquer servo cujo torque esteja ligado. Nos servos montados nas pernas, desligue o torque primeiro ou opere um de cada vez.
- A página carrega three.js pelo jsdelivr; o computador precisa de acesso à internet para abrir a página. O backend não precisa.
- O modelo não inclui a junta da boca (ID 34); o controle ainda move o servo, mas ele não aparece no 3D.

## Versão

A versão aparece ao lado do título da página. Se a versão da página e a do serviço forem diferentes, a página fica vermelha e pede para reiniciar `server.py` e usar Ctrl+F5; normalmente o navegador ainda está usando arquivos antigos. Ao alterar o código, atualize juntos `VERSION` em `server.py` e `PAGE_VERSION` em `index.html`.

| Versão | Data | Alterações |
|---|---|---|
| 0.15.6 | 2026-10-23 | Corrigida a gravação contínua de logs brutos durante a leitura normal da IMU DXL 2.0; mantida a configuração `trace_skip` do barramento e preservados os pedidos com falha e logs de diagnóstico manual. |
| 0.15.5 | 2026-10-17 | Adicionado modo compatível com a placa `imu_to_dxl` DXL 2.0 original e seleção de protocolo pela página; Feetech continua como padrão. |
| 0.15.4 | 2026-09-28 | Frequência-alvo de leitura do estado real dos servos e envio à web aumentada de 10 para 50 Hz; simulação permanece em 30 Hz e a lógica de movimento / habilitação não mudou. |
| 0.15.3 | 2026-09-28 | Leitura conjunta passou a associar respostas pelo ID real do pacote; corrigido o caso em que a ausência de um pacote fazia respostas seguintes normais serem marcadas como falha. Leituras realmente perdidas continuam visíveis, sem escondê-las com tentativas extras; adicionados testes de regressão do fluxo de bytes do protocolo. |
| 0.15.2 | 2026-09-28 | Na inicialização / conexão serial, apenas a fase é lida; não são mais gravados automaticamente registradores de velocidade e aceleração. Acrescentado o método de comparação entre depuração por Wi-Fi com placa + HAT e conexão USB-serial. |
| 0.15.1 | 2026-09-22 | Adicionado `servo_report.py`, diagnóstico somente leitura (validado no simulador de protocolo, sem emitir comandos de gravação), e `远程排查交接.md`. A confirmação da calibração esclarece que a sola fica perpendicular à perna; “alinhada” podia ser entendido de outra forma. |
| 0.15.0 | 2026-09-22 | Revisões corrigiram a ativação de torque: alinhar o alvo à posição atual antes de ligar o torque (calibrar sem torque e abrir a junta à mão podia fazê-la voltar bruscamente à posição dobrada); ao finalizar a calibração, não reescrever o alvo 42 com a leitura 67; a calibração e reversão simuladas não tocam `calib/` nem `poses/`; offsets do barramento simulado usam codificação sinal-magnitude; ao conectar a serial real, desconectar a IMU virtual e propagar conexão / desconexão a todas as páginas. A confirmação lista “agora → novo valor, diferença em graus”; pede nova confirmação para diferenças ≥30°, sem bloquear. Sobreposição 3D da dobra de calibração e aviso para não selecionar “dobrado” antes de calibrar o zero. |
| 0.14.0 | 2026-09-22 | Simulação com servos virtuais seguindo curvas trapezoidais de velocidade / aceleração (antes havia apenas acompanhamento de primeira ordem com torque ligado), torque ligado por padrão e estado a 30 Hz; opção de conectar / desconectar uma IMU virtual. O 3D só redesenha quando há alterações (antes, mais de 400 mil triângulos eram renderizados a 60 fps e atrasavam a confirmação dos botões). A calibração em um clique ganhou a referência “dobra oficial”: alvos calculados pelos ângulos FOLD oficiais × sinal ±, zero final em 2048 oficial e conversão das poses salvas; pernas dobradas e cabeça / pescoço alinhados, os 15 servos calibrados juntos. |
| 0.13.0 | 2026-09-22 | Aba “Poses oficiais”: quatro botões para zero / em pé / sentado / dobrado (keyframes oficiais convertidos pelo sinal ±; joelhos flexionam 2° a menos na dobra para não encostar nas peças). Sobreposição 3D semitransparente e diferença angular por junta para visualizar erro do zero. |
| 0.12.0 | 2026-09-22 | Opção `--imu-bus`: leitura da placa de IMU diretamente pelo barramento, com o mesmo `sync_read` do controlador (endereço 56, tamanho 15, ID 200 primeiro), usando os critérios principais (não pronta, rejeição, congelamento, bytes reservados e bits de falha). Após 5 quadros sem resposta, remove 200 da leitura conjunta e faz PING separado a cada 2 s; os servos continuam funcionando sem a placa. `--fake --imu-bus` demonstra uma placa simulada. Firmware 0.2.0 Feetech; atualizado o hash HEX e os endereços RAM do observador SWD/J-Link. |
| 0.11.0 | 2026-09-22 | Opção `--imu-swd`: leitura da IMU via ST-Link / DAPLink usando pyOCD, sem DLL nem configuração J-Link (J-Link continua em `--imu-jlink`, e `--imu-swd` o rejeita). Proteções iguais ao caminho J-Link: verificar tensão antes de conectar, comparar a Flash, ler somente RAM e não retomar a CPU automaticamente. Modo attach testado sem reinicialização da placa. Seleção automática com uma sonda ou UID explícito com várias; ST-Link exibe a tensão-alvo; avisos pyOCD registrados no log da IMU; a aba mostra o nome real do depurador. |
| 0.10.0 | 2026-09-21 | Opção `--imu-jlink`: combinação dos ângulos dos servos e orientação do tronco da IMU na mesma interface WebSocket, log e modelo 3D; mantém montagem e zeragem visual, oferece `--imu-demo` sem hardware e preserva a interface original quando a IMU não é ativada. Firmware e materiais de hardware reunidos; só o HEX fica no repositório. |
| 0.9.1 | 2026-09-20 | Comunicação serial bruta passa a ser gravada com bytes hexadecimais, nomes de registradores e respostas dos servos. Como operações Feetech sem suporte podem responder “sucesso” sem agir, os bytes permitem conferir o resultado real. Polling de estado a 10 Hz fica fora do log para evitar excesso de dados. |
| 0.9.0 | 2026-09-20 | Calibração reescrita após revisão de código: verificar se o registrador de offset mudou, e não apenas se a leitura corresponde ao alvo, pois comandos não suportados podem responder “sucesso”. Compensação da queda por gravidade durante o intervalo sem torque (pescoço medido a 0,62 passo/ms, ida e volta serial USB de 1–16 ms); leitura de confirmação após desligar o torque; gravar sempre a leitura atual como alvo; restaurar alvo, torque e bloqueio mesmo em caso de erro; barramento exclusivo e velocidade / aceleração reduzidas durante a calibração; sentido do offset detectado uma vez na inicialização (±1 passo); registradores 31/42/46 passam a usar sinal-magnitude em vez de complemento de dois; faixa de offset limitada a ±2047; reversão também desloca poses salvas depois da calibração; cópia de segurança atômica antes de mover as poses. O simulador passou a modelar gravidade e latência do barramento. |
| 0.8.1 | 2026-09-20 | Se a porta serial não abrir (USB desconectado, número alterado ou porta ocupada), a página ainda inicia no barramento simulado e lista as portas disponíveis. Seletor serial e botão “Conectar” na barra superior permitem assumir uma porta USB sem reiniciar o serviço. |
| 0.8.0 | 2026-09-20 | Calibração mudou da gravação de 128 para o comando 0x0B (HD-1910 não reconhece 128; o “sucesso” da versão 0.7.x ocorria porque a leitura já estava perto de 2048); sucesso requer leitura realmente igual ao alvo; opção de usar uma pose salva como referência; torque desligado por poucos milissegundos; reversão desloca apenas poses movidas naquela operação; nomes de cópia de segurança incluem milissegundos; calibração individual segue a referência. |
| 0.7.3 | 2026-09-20 | Corrigida falha de calibração de todos os 15 servos na versão 0.7.1 (`'_thread.lock' object is not callable`: `self.lock` escondia o método `lock()` da EEPROM); exportação termina no registrador 86 (90 causava `short read` na placa real); erros no meio da calibração também bloqueiam o servo, sem restaurar torque automaticamente; logs categorizados, em arquivo, com filtros e cópia; operações individuais em lista; simulador de protocolo e autoteste. |
| 0.7.2 | 2026-09-20 | Poses podem ser excluídas com o botão ×, movendo-as para `poses/.trash/` para recuperação; botões de poses homônimas mostram a data. |
| 0.7.1 | 2026-09-20 | Corrigida a calibração de zero: a versão 0.7.0 gravava 128 com torque ligado e servo bloqueado; ele respondia “sucesso” sem calibrar e a gravação posterior de 2048 puxava a junta de volta ao zero antigo. Novo fluxo: desbloquear → desligar torque → gravar 128 → confirmar leitura → atualizar alvo → restaurar torque → bloquear; se a calibração não for confirmada, não mover. |
| 0.7.0 | 2026-09-20 | Calibração de zero com um clique (todos ou IDs selecionados) e reversão; contagem online, frequência de atualização e tensão média no topo; ângulos das juntas por servo; direção invertida nos 15 servos. |
| 0.6.0 | 2026-09-20 | Direções das juntas salvas em `directions.json` e compartilhadas entre páginas; conferidos os sentidos invertidos nos IDs 23, 13 e 30–34; botão para copiar a tabela do `robotd`; cache do navegador desativado e número de versão adicionado. |
| 0.5.0 | 2026-09-19 | Animação de cabeça “灵动”; movimento suave sem bloquear o backend; corrigido o registrador de velocidade igual a zero quando BIT3=0, que significa parada. |
| 0.4.0 | 2026-09-18 | Projeção do centro de massa e área de apoio no 3D; movimento suave com trajetória trapezoidal no servo; leitura de confirmação da posição-alvo e reenvio quando não alcançada. |
| 0.3.0 | 2026-09-18 | Salvar e carregar poses, botões “encolher” e “em pé”, sequências para levantar / voltar a encolher e duração da transição. |
| 0.2.0 | 2026-09-17 | Dobradiça da boca, aviso quando torque está desligado, botão de postura oficial e porta padrão alterada para 8080. |
| 0.1.0 | 2026-09-17 | Primeira versão: controles deslizantes, leitura em tempo real, acompanhamento 3D, exportação de registradores, teste de temporização, alteração de ID e calibração de zero. |

## Arquivos

| Arquivo | Função |
|---|---|
| `server.py` | Serviço HTTP + WebSocket com starlette + uvicorn |
| `feetech.py` | Protocolo Feetech: PING / READ / WRITE / SYNC_READ / SYNC_WRITE / REBOOT e nomes dos registradores |
| `sim_bus.py` / `selftest.py` | Simulador de servo no nível do protocolo / autoteste do backend |
| `servo_report.py` / `test_servo_report.py` | Diagnóstico somente leitura / teste com `sim_bus` |
| `远程排查交接.md` | Fluxo de diagnóstico e calibração para um assistente de IA em outro computador |
| `logs/` `calib/` | Logs de execução e cópias dos offsets anteriores à calibração; dados locais, não incluídos no repositório |
| `index.html` | Interface de arquivo único; carrega three.js de um CDN |
| `imu_bridge.py` / `test_imu_bridge.py` | Leitura J-Link / pyOCD, validação de firmware, decodificação de amostras e testes sem hardware |
| `test_imu_swd.py` | Teste do leitor `--imu-swd` (pyOCD) com módulo simulado, sem sonda |
| `imu_bus.py` / `dxl2.py` | Leitura de IMU pelo barramento `--imu-bus` e adaptação compatível com DXL2 |
| `imu_attitude.js` / `test_imu_attitude.cjs` | Conversão de quaternion, montagem da IMU e referência visual; testes de regressão |
| `imu-jlink.example.json` / `test_imu_server.py` | Modelo de configuração pessoal / teste de integração da IMU no serviço |
| `build_model.py` | MuJoCo XML + STL → `model/model.json` + `model/meshes.bin` (vértices quantizados int16; 21 MB reduzidos para 2,9 MB) |
| `model/` | Modelo gerado, com 14 juntas |
