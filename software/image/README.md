# Imagem de réplica do Microduck: script de construção

> Para quem vai usar a imagem: consulte [Gravação da imagem e primeiro uso](烧录和第一次使用.md). Este documento explica como construir a imagem.

> Se o ponto de acesso não aparecer, confirme primeiro se a placa principal é uma **Zero 3W** ou uma **3E sem Wi-Fi integrado**. O ponto de acesso não depende do ID dos servos. A compatibilidade com a 3E ainda não foi validada nesta imagem. Consulte [Verificação do ponto de acesso e do modelo da placa principal](../../docs/热点与主板型号排查.md).

> **Lançamento de 2026-10-27:** a [imagem 20261027](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) e o [pacote de software 2026.10.27](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) foram publicados. Incluem atualização e reversão assinadas pela web, o auxiliar compatível e comandos locais de voz no R3 para sentar e levantar, além do modelo chinês de reconhecimento de fala e das dependências ARM64. O código em execução vem de `e382f074`; o pacote assinado e a imagem usam o mesmo instalador. O tamanho e os hashes de todos os anexos do servidor e os links públicos de download foram verificados. O robô está desligado e a imagem ainda não foi gravada nem testada no robô; a validação física desta versão está pendente. Consulte [hashes e limites da verificação](../../docs/superpowers/verification/2026-10-27-web-updates.md) e [atualização de software e uso de voz](../../docs/软件更新与语音使用说明-20261027.md). As notas de 25 de outubro abaixo descrevem o estado histórico.

> **Nota de 2026-10-25:** o [inventário de recursos e atualizações de software](../../docs/软件功能与升级总账.md) registra diferenças entre o código-fonte, o robô atual e a imagem, além do plano de atualização posterior pelo pacote de componentes. Naquele dia, o serviço de voz independente e a manutenção da faixa selecionada ainda não faziam parte da construção geral da imagem; a atualização online ainda não estava implementada.

> **Atualização posterior, no mesmo dia:** a gravação e reprodução de movimentos pela web e o modo de movimentos espontâneos foram implementados em `c18783c` e instalados no robô atual via SSH. A prévia da câmera interna e a recuperação da entrada pareada também foram sincronizadas com a versão compatível. A imagem existente não foi reconstruída. O pacote de código congelado e a instalação em um único robô não equivalem a uma atualização online geral. Consulte a [verificação desta rodada](../../docs/superpowers/verification/2026-10-25-web-motion-studio.md).

> **Atualização:** `aa825fc` também adicionou a gravação de sentar e levantar. O recurso foi instalado, e o usuário confirmou que salvar e reproduzir os movimentos funciona. A versão 2 registra a compatibilidade e os limites de reversão na [verificação de sentar e levantar](../../docs/superpowers/verification/2026-10-25-web-posture-recording.md). Esta versão ainda não foi incorporada a uma nova imagem.

A imagem de réplica é um cartão SD que pode ser gravado e usado. Ela já inclui o programa principal do nosso fork, os modelos de marcha e de movimentos, o Microduck Studio, os recursos de primeira inicialização (nome do robô, identificação da IMU e criação do ponto de acesso) e a configuração da rede (se não encontrar Wi-Fi, o robô abre um ponto de acesso).

Este diretório contém os scripts que preparam o cartão: eles copiam em modo somente leitura o programa principal e os modelos de um robô configurado, instalam-nos sobre a imagem-base, removem a identidade da máquina, os registros e os dados deixados por outras pessoas e, por fim, reduzem e compactam a imagem.

A imagem é gratuita e destinada apenas a réplicas pessoais e não comerciais. **Não a distribua com produtos pagos.** Os modelos incluídos seguem a licença pessoal e não comercial dos autores. Consulte [`overlay/usr/share/doc/microduck/模型说明.txt`](overlay/usr/share/doc/microduck/模型说明.txt).

## Conteúdo da imagem

| Componente | Localização na imagem | Origem | Licença |
|---|---|---|---|
| Base do sistema | `/` | Armbian 26.2.1 (Debian 13), kernel 6.1.115-vendor-rk35xx e U-Boot da Radxa | A licença de cada pacote está em `/usr/share/doc/<pacote>/copyright` |
| Runtime oficial 0.15.1 | `/opt/robot/daemon/`, `/usr/local/bin/robotctl` | Pollen Robotics, commit `1fa8438`, já incluído na imagem-base | Apache-2.0 |
| Programas principais `robotd`, `padd` e `mediad` | `/opt/robot/feetech-ft5-r5/` | Nosso fork do runtime oficial 0.15.1, com barramento Feetech, módulo IMU I²C, fusão do giroscópio e controle UDP; copiados de um robô configurado | Apache-2.0 |
| ONNX Runtime 1.28.0 | `/opt/robot/feetech-ft5-r5/onnxruntime/` | Microsoft, sem modificações | MIT |
| Dez modelos de marcha e movimentos | `/opt/robot/feetech-ft5-r5/models/` e `roller/` | Treinados por autores da comunidade e copiados de um robô configurado; os arquivos de treinamento foram removidos | Pessoal e não comercial |
| Microduck Studio | Desde 20261027: `/opt/microduck/software/current/studio/`, serviço `microduck-studio`, porta 8000; em imagens antigas: `/home/radxa/studio-dev/` | [`../studio/`](../studio/), arquivo de execução assinado | Apache-2.0 |
| Voz local para sentar e levantar | `/opt/microduck/software/current/duck-echo/`; recursos em `/opt/microduck/resources/`; por padrão, um clique no R3 alterna a escuta e o robô confirma com um som | [`../duck-echo/`](../duck-echo/), Vosk small-cn0.22 e dependências ARM64/cp313 | Apache-2.0 e licenças próprias das dependências |
| Executor de atualização de software | `/usr/local/lib/microduck-updater/`, serviço root independente; versões em `/opt/microduck/software/releases/` | [`../updater/`](../updater/), derivado do updaterd 0.15.1 para ARM; inclui sua própria chave pública de lançamento; aplicação automática desativada | Apache-2.0 |
| Primeira inicialização, configuração de rede e auxiliar root | `/usr/local/sbin/microduck-firstboot`, `microduck-netcheck` e `microduck-helper` | [`overlay/`](overlay/) e `deploy/` do Studio | Apache-2.0 |
| Calibração de fábrica | `/etc/robot/feetech-ft5/hd1910-calibration.toml` | [`calib/hd1910-calibration.option-a.toml`](calib/hd1910-calibration.option-a.toml): todos os 15 servos estão em 2048 / −1 / não calibrado | — |

Os textos completos das licenças estão em `/usr/share/doc/microduck/` na imagem. Durante a construção, eles também são copiados para o diretório de saída e acompanham o lançamento.

As principais diferenças em relação ao segundo robô de referência são:

- **O programa principal inicia no modo de calibração** (`robotd.service.d/zzzz-zz-microduck-commissioning.conf` acrescenta `--commissioning`). Um robô sem calibração só consegue ler a IMU, fazer a calibração básica e mostrar a calibração dos 15 servos nesse modo. Depois que a terceira etapa da lista de primeiro uso, **Gravar no programa principal**, termina com sucesso, o auxiliar root remove esse arquivo e o programa principal volta ao modo de movimento.
- **A câmera usa uma imagem de teste por padrão** (a configuração oficial `/etc/robot/robotd.toml` define `[media] source = "test"`). Assim, `mediad` não entra em ciclo de falhas quando o robô está sem câmera.
- **A senha padrão de `radxa` é `microduck`**. O usuário root fica bloqueado e o SSH aceita somente chaves.
- Os controles e parâmetros de caminhada seguem o `robotd.toml` do segundo robô: amplitude de movimento 0.7, sem alívio de torque automático após quedas e sem desligamento automático quando a bateria acaba.

## Insumos para a construção

### 1. Imagem-base

`microduck-zero3w-0.15.1-R1-V112.img` foi derivada da imagem R1 publicada pela comunidade com o script de conversão R1 em `tools/radxa/`. Os argumentos `--no-tof --overlay i2c4-m0` substituem o U-Boot e a árvore de dispositivos pelos da Radxa B1 e habilitam I²C4 (pinos 27 e 28) para o módulo IMU. A imagem-base já contém o runtime oficial 0.15.1. As imagens usadas em 20261020 e 20261021 tinham o mesmo SHA-256: `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`.

O plano é substituir essa base por uma instalação limpa do Armbian com o instalador oficial, eliminando a dependência de uma imagem de terceiros.

### 2. Payload (copiado de um robô configurado)

O robô de origem precisa ter o programa principal do nosso fork instalado e já conseguir caminhar. Ele deve conter:

- `robotd`, `padd`, `mediad`, `onnxruntime/`, `models/` e `roller/` em `/opt/robot/feetech-ft5-r5/`;
- `/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf` com os parâmetros de inicialização do programa principal, sem `--commissioning`;
- `/etc/robot/feetech-ft5/robotd.toml`. Durante a cópia, a configuração da fiação da IMU local é removida e o pacote de voz volta a apontar para a versão oficial.

A cópia usa uma lista permitida, é somente para leitura e não altera arquivos no robô de origem:

```sh
# No computador: copie o script para o robô
scp capture-payload.sh radxa@<IP-do-robo>:/tmp/
# No robô
sudo sh /tmp/capture-payload.sh /tmp/microduck-payload.tgz
# No computador: copie o arquivo de volta
scp radxa@<IP-do-robo>:/tmp/microduck-payload.tgz .
```

A versão de 20261020 foi copiada do segundo robô. O SHA-256 do payload começa com `9e1e64b8…`. O `robotd` dentro dele (SHA-256 começando com `9b734239…`) foi compilado em 15 de outubro no espaço de trabalho do fork, mas **não corresponde exatamente a um commit**; uma nota anterior o associava incorretamente a `a844db6`.

A versão de 20261021 usou o mesmo payload, trocando apenas o `robotd` pela versão ARM64 compilada do commit `f4bbe53` da branch `hd1910-v167-imu-autodetect` do fork. O SHA-256 do binário começa com `0a6a86b2…`; o endereço do fork está na seção Software da página inicial. O valor do `robotd` em `payload.json` foi atualizado e o novo SHA-256 do payload começa com `26252fbc…`. Desde então, cada `robotd` deve ser compilado a partir de um commit para que corresponda ao código-fonte.

O `robotd` de 20261023c veio da branch [`hd1910-v167-imu-dxl2` do fork do runtime](https://github.com/fanhao375/Microduck-kissqy/tree/hd1910-v167-imu-dxl2), commit `0791fcd44f71c705dc8bb0fbcde405593b52d19b`, identificação da compilação `4734cbb-feetech-imu-auto-control.44`. Foi compilado com Rust 1.99.0 e `cargo zigbuild --locked --release --target aarch64-unknown-linux-gnu.2.31 -p robotd --bin robotd`, usando `CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1`. O SHA-256 do `robotd` é `edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`.

Somente o `robotd` foi substituído no payload verificado, e `[bus] imu_protocol = "auto"` foi definido explicitamente na configuração de execução e na configuração salva. Os outros daemons, os modelos e o ONNX Runtime permaneceram iguais. Os tamanhos e hashes de cada arquivo são verificados novamente ao reempacotar. `payload.json` registra o commit de origem, os parâmetros da compilação e as fontes; o hash completo do payload consta no manifesto da imagem entregue. Consulte o [registro desta versão](../../docs/HD1910-20261023-总线IMU自动识别.md) para conhecer o escopo de compatibilidade, a comparação com falhas de testes antigos e os limites da validação no robô real.

### 3. Máquina de construção

Use Ubuntu 22.04 no WSL ou qualquer Linux. A construção precisa de permissões root para acessar dispositivos loop:

```sh
sudo apt install fdisk e2fsprogs xz-utils openssl python3.11
```

O script requer Python 3.11 ou superior por usar `tomllib`. O Ubuntu 22.04 vem com Python 3.10. Depois de instalar o Python 3.11, configure o comando `python3` para apontar para ele — por exemplo, criando um diretório com apenas esse link e colocando-o no início de `PATH`.

## Construção

A imagem completa de 20261027 precisa de quatro insumos fornecidos em conjunto. Se faltar qualquer um, o script interrompe antes de modificar o sistema de arquivos raiz. Primeiro, gere o pacote assinado a partir do commit congelado e use `voice_resources.py` para preparar e verificar o modelo oficial de voz em chinês e as dependências ARM64/cp313. Não inclua dependências Python da máquina de desenvolvimento, arquivos pessoais de voz nem chaves pessoais. A chave privada de lançamento serve apenas para assinar na máquina de construção e não é um insumo da imagem.

```sh
export SOFTWARE_UPDATE_PACKAGE=/path/to/2026.10.27.software-update.tar
export SOFTWARE_UPDATE_PUBLIC_KEY=/path/to/software/updater/release.pub
export SOFTWARE_UPDATE_ENGINE=/path/to/verified-arm64-updaterd
export VOICE_RESOURCES_DIR=/path/to/verified-resources
# Em uma máquina x86, também é necessário qemu-user e a raiz verificada de bibliotecas/loader ARM64.
# Em uma máquina ARM nativa, deixe esta variável vazia.
export SOFTWARE_UPDATE_ENGINE_COMMAND_JSON='["qemu-aarch64","-L","/path/to/arm64-libs"]'
```

Ao construir em um shell root, as variáveis de ambiente acima continuam disponíveis. Se executar com `sudo`, transmita explicitamente esses insumos fixos para evitar que o `sudo` limpe o ambiente e acione a construção antiga. Sem o conjunto completo de insumos, o script mantém o comportamento da imagem antiga e não inclui os novos componentes de atualização e voz. Na imagem final, confira `/usr/share/doc/microduck/software-components.json`, a descrição dos recursos de voz e os arquivos de versão efetivamente instalados.

```sh
sudo STUDIO_VERSION=<commit-do-Studio> IMAGE_VERSION=<commit-deste-diretorio> \
    sh build-image.sh /path/to/microduck-zero3w-0.15.1-R1-V112.img \
    /path/to/microduck-payload.tgz ../studio ~/microduck-out
```

- `OUT_DIR` não pode ficar em `/mnt`: a montagem loop na unidade Windows do WSL é lenta e tem problemas de permissões. Use, por exemplo, `~/microduck-out`.
- Para um cartão de validação pessoal, `DEV_AUTHORIZED_KEY="$(cat algum-arquivo.pub)"` instala a chave pública em `authorized_keys` do usuário `radxa`. Assim, você pode corrigir problemas remotamente sem gravar o cartão outra vez; o manifesto da imagem registra essa inclusão. **Nunca defina essa variável em um lançamento público:** isso deixaria uma porta de acesso nos robôs dos usuários.
- Se não informar as versões, o script tentará obtê-las com `git rev-parse`. Acrescentará `-dirty` se houver alterações sem commit e usará “desconhecido” se não conseguir ler o Git. O WSL frequentemente não consegue acessar um worktree Git em uma unidade Windows; informe as versões manualmente no lançamento.
- Por padrão, a imagem recebe o nome `microduck-replica-DATA.img.xz`. Para uma segunda versão no mesmo dia, passe um nome como `IMAGE_TAG=20261021b` (somente números e letras minúsculas).
- A construção leva cerca de 10 minutos. Os resultados são:
  - `microduck-replica-YYYYMMDD.img.xz` e seu arquivo `.sha256`;
  - `镜像清单.txt`, com o SHA-256 da imagem-base e do payload e a lista de itens removidos e adicionados;
  - `开源许可.txt`, `第三方.txt` e `模型说明.txt`;
  - `work.img`, mantido para inspeção. Apague-o manualmente depois de confirmar o resultado.

É possível executar verificações individuais sem permissões root:

```sh
sh build-image.sh --selftest                 # reescrita das linhas de partição GPT / MBR
sh capture-payload.sh --clean-toml IN OUT    # função de limpeza de robotd.toml
sh apply-rootfs.sh ROOT PAYLOAD ../studio ./overlay   # teste de instalação em uma árvore fictícia (ROOT não pode ser /)
```

## Testes

```sh
# Execute todos os testes como root no WSL; alguns verificam proprietário e permissões.
python3 -I -m unittest discover -s tests -v
sh -n apply-rootfs.sh && sh -n build-image.sh && sh -n capture-payload.sh
```

No Windows, também é possível executar `py -3.13 -I -m unittest discover -s tests -v` com o `sh` do Git Bash. O teste de permissões será ignorado.

## O que o script bloqueia automaticamente

Se qualquer uma das condições abaixo falhar, a construção para e informa a etapa e a ação necessária:

- o SHA-256 de um arquivo no payload não corresponde ao manifesto, há arquivo sem manifesto ou há link simbólico;
- os arquivos em `overlay/`, `Studio/deploy/` ou `run.py` usam finais de linha Windows (CR). Ao clonar no Windows com `core.autocrlf=true`, scripts sem extensão podem virar CRLF e falhar na inicialização. O `.gitattributes` do repositório define LF nesses diretórios;
- qualquer arquivo da imagem, inclusive binários, ainda contém o nome de um autor de modelos. A única exceção é `模型说明.txt`, que precisa creditar os autores conforme a licença;
- existe um link simbólico quebrado em `etc/systemd`, `udev` ou `cron`, ou algum desses diretórios ainda aponta para um arquivo removido;
- ainda há arquivos de treinamento em `opt/robot/feetech-ft5-r5`, como `export-data.zip`, `training-*.json`, `upstream-params` ou `*.pt`;
- a seção “A confirmar manualmente” ainda contém arquivos comuns. Antes de liberar com `ALLOW_UNCONFIRMED=1`, confirme que eles não contêm dados pessoais; o manifesto registrará a exceção;
- a inicialização oficial do codec de áudio (`aic3104-init`) está incompleta.

Além disso, as exclusões são listadas antes de ocorrer e todas as gravações passam por `safe_dir` ou `safe_file`. Se `ROOT` contiver um link simbólico apontando para fora, o script falhará em vez de modificar arquivos do computador. `apply-rootfs.sh` não acessa dispositivos loop nem executa `chroot`.

## Verificações antes do lançamento

1. Execute todos os testes no WSL como root.
2. Construa a imagem a partir de um commit. Informe os commits em `STUDIO_VERSION` e `IMAGE_VERSION` e confirme que o registro não liberou nenhum arquivo com `ALLOW_UNCONFIRMED`.
3. Descompacte e monte a imagem entregue em modo somente leitura. Confira pelo menos: hashes corretos; `e2fsck -fn` sem erros; hashes do programa principal e dos modelos iguais aos do payload; todos os modelos referenciados em `robotd.toml` presentes; arquivo auxiliar do modo de calibração instalado; `machine-id` vazio; nenhuma chave SSH de host; SSH aceitando somente chaves; somente `模型说明.txt` contendo nomes de autores de modelos.
4. Registre o escopo do teste físico de um cartão novo com [Gravação da imagem e primeiro uso](烧录和第一次使用.md): ponto de acesso → configuração da rede → seis etapas da lista de primeiro uso → levantar e caminhar. Se a validação não estiver concluída, declare isso nas instruções do lançamento; não reutilize resultados de testes físicos de versões anteriores. Em 20261027, o usuário autorizou publicar primeiro o software e a imagem verificados; o teste físico desta versão será feito depois da inicialização.
5. Confirme que o commit do fork do programa principal incluído na imagem foi enviado ao fork remoto.
6. No GitHub Releases, publique o `.img.xz`, o `.sha256`, `镜像清单.txt` e os três arquivos `.txt`. A primeira seção das instruções do lançamento deve dizer: “Gratuito, somente para réplicas pessoais e não comerciais; não distribuir com produtos pagos”.
