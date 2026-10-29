# Radxa Zero 3W · Criar um cartão Armbian que inicializa diretamente

> **2026-10-21: as duas imagens-base de setembro (20260920 e 20260929) foram removidas de Releases** porque ficaram antigas. Para um cartão pronto, use a [imagem da réplica](https://github.com/fanhao375/microduck-replica/releases/latest): basta gravar; ela inclui o programa principal, o modelo de caminhada e o Studio. Os scripts deste diretório foram mantidos e continuam disponíveis para quem quiser criar o próprio cartão; as referências às duas Releases abaixo são históricas.

Usado com a [etapa 1 de “Sem HAT”](../../docs/不打HAT.md#第-1-步--主控点亮什么都别接).
A imagem original do Armbian testada anteriormente não inicializava nesta placa V1.12 (Wi-Fi AIC8800); o problema foi resolvido após comparar e substituir o carregador de inicialização. Consulte a instrução de uso da imagem para diferenças entre lotes. **A luz piscando duas vezes não é, por si só, um código de erro**: em 2026-09-28, a placa oficial B1 também usava o padrão `heartbeat` enquanto estava conectada e coletava dados normalmente.
A investigação apontou incompatibilidade entre o U-Boot principal / firmware de inicialização de memória usado pelo Armbian e esta placa; com o carregador da Radxa, ela inicializou.
Os scripts deste diretório integram na imagem a troca do carregador, configuração Wi-Fi e DHCP, ativação da serial e console de controle USB para permitir a conexão de rede no primeiro uso.

Em 2026-09-28, foi corrigida a ausência da configuração DHCP de `wlan0` nos scripts de criação do cartão. A imagem e os hashes da Release de 20 de setembro continuam sendo os arquivos antigos e não incluem a correção. Quem já gravou a imagem antiga pode adicionar a configuração conforme as [instruções de rede](镜像使用说明.md#4-连-wifi); não precisa regravar o cartão só por isso. A imagem pessoal corrigida foi testada nesta placa: obteve endereço DHCP e aceitou login SSH. Isso não significa que todos os modelos de placa e roteadores tenham sido verificados; veja o [registro de testes](联网与HAT调试记录-20260928.md).

**Não quer criar o cartão?** Use a [imagem da réplica](https://github.com/fanhao375/microduck-replica/releases/latest), pronta para gravar e com programa principal e Studio. O parágrafo seguinte descreve historicamente a imagem-base do fim de setembro, sem Wi-Fi configurado (conexão inicial pelo USB serial). Para a configuração inicial e diferenças entre lotes, veja as [instruções da imagem](镜像使用说明.md). Trocar de computador não altera o sistema; ao mudar de rede Wi-Fi, informe novamente as credenciais, sem regravar o cartão.

**Correção do primeiro login (2026-09-29): `root / 1234`.** O usuário `duck / duck1234` só é criado e a senha root alterada depois de concluir o assistente do Armbian. O usuário e a senha em `card.conf` são valores predefinidos para o assistente, não as credenciais da primeira autenticação. Troque as senhas padrão logo depois. A imagem candidata 20260929 inclui DHCP pré-configurado, instruções atualizadas no cartão e remoção das chaves de host SSH pré-geradas; passou por verificação offline, mas ainda não foi testada após gravação. Não é necessário regravar cartões antigos: corrija o DHCP e gere novamente as chaves SSH conforme o guia.

| Arquivo | Função |
|---|---|
| `card.conf` | Edite o nome e a senha do Wi-Fi; no primeiro login, `root / 1234`, o assistente cria por padrão `duck / duck1234`. Para instalar software oficial a partir da China, informe o proxy HTTP. **Deixar vazios os dois campos de Wi-Fi ativa o modo de imagem pública**: nenhuma credencial é gravada, mas o DHCP continua pré-configurado. |
| `镜像使用说明.md` | Guia da imagem publicada: gravação, login pelo USB serial, conexão ao Wi-Fi e recuperação de outros lotes da placa com outro carregador. |
| [Registro de depuração da câmera 20260928](摄像头调试记录-20260928.md) | Referência visual da conexão do cabo, comparação com a Radxa B1 oficial, reconhecimento de IMX219 e captura limitada de quadros; novo teste com o Armbian original ainda pendente. |
| [Registro de rede e HAT 20260928](联网与HAT调试记录-20260928.md) | Resultados do login na placa e comunicação somente leitura com os servos no HAT após corrigir o DHCP, além de itens pendentes de diagnóstico. |
| `1-做卡.ps1` | No Windows, clique com o botão direito e selecione “Executar com PowerShell”; escolha o arquivo `.img.xz` baixado para criar `xxx-鸭子卡.img` e grave-o com Rufus. |
| `build-armbian-card.sh` | Script principal; no Linux / WSL, execute `sudo bash build-armbian-card.sh xxx.img.xz card.conf`. |
| `kissqy-r1-v112.sh` | Troca o carregador da imagem de instalação única R1 do kissqy pelo carregador Radxa e configura extlinux para permitir a inicialização da placa V1.12. Preserva o firmware, os modelos e a configuração de rede iniciais do kissqy. Opções: `--no-camera`, `--no-tof` e `--overlay i2c4-m0`. Uso: `sudo bash kissqy-r1-v112.sh microduck-zero3w-0.15.1-R1.img.xz [opções]`. Veja a [análise da imagem kissqy R1](../../docs/HD1910-20261012-kissqy镜像R1分析.md) para a motivação e os resultados offline; **ainda não foi testada no robô**. |

Os dois scripts procuram primeiro, no mesmo diretório, o pacote de inicialização Radxa `u-boot-rk2410_2017.09-64-39cd993_arm64.deb`; se não existir, baixam-no de radxa-repo.github.io. Às vezes o curl no WSL perde a conexão SSL com esse site. Nesse caso, baixe o pacote no Windows e coloque-o no diretório do script; o hash será verificado. Apague o `.deb` depois de usar e não o envie ao repositório.

A imagem usa **Armbian 26.2.1 trixie, kernel vendor 6.1.115, minimal** (versão indicada pela documentação oficial da Pollen; os espelhos chineses só mantêm 26.8.1; 26.2.1 está em `https://fi.mirror.armbian.de/archive/radxa-zero3/archive/`). O carregador Radxa é baixado automaticamente do pacote `u-boot-rk2410` em `radxa-repo.github.io`; o script fixa sua versão e SHA256.

O script faz cinco coisas:

1. Grava `idbloader.img` no setor 64 e `u-boot.itb` no setor 16384 (Radxa u-boot-rk2410 2017.09-64, DDR v1.25, BL31 v1.46).
2. Configura `/boot/extlinux/extlinux.conf`: o U-Boot Radxa reconhece extlinux, mas não o `boot.scr` do Armbian; inclui os overlays `uart2-m0` (serial dos servos `/dev/ttyS2`) e `dwc3-peripheral` (porta OTG como USB serial) e deixa o console do kernel em tty1.
3. Pré-configura `/root/.not_logged_in_yet` para o assistente inicial (usuário, senha, fuso e locale), aplicado depois da autenticação; configura Wi-Fi em `wpa_supplicant-wlan0.conf` e DHCP sem fio em `/etc/systemd/network/25-wlan0.network`; remove as chaves SSH de host pré-geradas da imagem-base e mantém o serviço original que cria novas chaves na primeira inicialização.
4. Ativa `g_serial` e `serial-getty@ttyGS0`: ao conectar a placa ao computador aparece uma porta COM em 115200, com login root.
5. Bloqueia `serial-getty@ttyS2` / `ttyFIQ0`, para que o console de login não ocupe a serial dos servos.

Depois de concluir o primeiro login e configurar a rede, localize `radxa-zero3` no roteador e conecte-se com `ssh duck@IP`. A imagem-base não inclui o ambiente completo de controle do robô; ter rede não significa que o painel web ou os servos já estejam prontos para uso.

Para instalar componentes depois, consulte o [install-dev.md oficial da Pollen](https://github.com/pollen-robotics/microduck/blob/main/docs/robot/install-dev.md), mas **não copie diretamente o fluxo `migrate-network.sh` → reiniciar nesta imagem**. O script upstream verificado importa credenciais sem fio do netplan; não lê `wpa_supplicant-wlan0.conf` desta imagem nem desativa automaticamente os serviços independentes `wpa_supplicant@wlan0` / `25-wlan0.network`. Mantenha primeiro o método de rede atual e só migre depois de adaptar a importação das credenciais, a saída dos serviços antigos e a recuperação de conexão, para evitar perder o acesso após reiniciar.

Também é necessário conferir se as alterações do instalador em `armbianEnv.txt` chegam ao arquivo realmente usado na inicialização, `extlinux.conf`; não conclua que o hardware está configurado apenas porque as verificações do script passaram.

## Scripts de análise na placa

[`onboard-analysis/`](onboard-analysis/) reúne scripts usados na noite de 2026-10-12 para investigar o avanço brusco do modelo, todos somente leitura: gravação a 50 Hz por serviço iniciado na inicialização, registro de tensão e temperatura, consistência da IMU, testes em quatro direções, **calibração do zero da IMU** (parado em HOME → inclinação esperada pela simulação → novo quaternion de montagem), pontos de mudança antes da perda de controle, estatísticas de passos com joystick e análise de desconexões da IMU.
