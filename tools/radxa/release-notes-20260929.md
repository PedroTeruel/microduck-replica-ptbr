> **Esta versão foi removida em 21/10/2026** por estar desatualizada. Para cartões disponíveis, use a [imagem de réplica](https://github.com/fanhao375/microduck-replica/releases/latest). As informações abaixo ficam registradas como nota histórica.

> **Imagem candidata (pré-lançamento): a verificação offline foi concluída, mas esta nova imagem ainda não foi gravada em cartão, inicializada nem testada na rede.** Foi criada a partir da imagem pública 20260920, acrescentando apenas a correção do DHCP sem fio, a revisão das instruções de login/rede do cartão e a remoção das chaves de host SSH pré-geradas. Os arquivos da versão antiga continuam na publicação original. Cartões antigos podem ser corrigidos seguindo o guia; não é necessário regravá-los apenas por causa desta atualização.

Base compatível: Radxa Zero 3W V1.12/AIC8800, Armbian 26.2.1 Trixie vendor 6.1.115 minimal + u-boot-rk2410 da Radxa. Outros lotes de placa, câmeras e roteadores precisam de validação própria.

**Este é um sistema-base; não inclui o runtime do robô, painel web de depuração, configuração dos servos, configuração da IMU nem política de caminhada. Não contém Wi-Fi pessoal, proxy nem chaves de login.** Uma imagem pessoal diferente foi testada na rede em 28/09; esse resultado não prova que esta imagem candidata tenha sido gravada ou testada em cartão.

### Arquivos anexos

| Arquivo | Finalidade |
|---|---|
| armbian-26.2.1-zero3w-v1.12-dhcpfix-20260929.img.xz | Imagem candidata para gravação com Rufus, balenaEtcher ou Armbian Imager em cartão de pelo menos 8 GB |
| sha256.txt | Hash de verificação da imagem compactada desta versão; não use o hash da versão anterior |
| radxa-zero3w-image-guide-zh.md | Guia de primeiro login, rede, troca de Wi-Fi, reparo de cartões antigos, alimentação e lotes da placa |
| image-verification-20260929.json | Verificação offline, origem, SHA256 da imagem bruta e compactada, diferenças arquivo a arquivo e indicação de que não houve teste físico |

Tamanho da imagem compactada: 419.157.756 bytes. SHA256:

    d7a4dc60a0c622786ae3eb03ebea2d5316d4cff44373945f4a61f44ac7019f63

### Primeiro login e conexão de rede

1. Depois de verificar o arquivo baixado, grave o cartão. Para a serial USB, use a porta da placa marcada **5V IN / USB_OTG** (USB 2.0), conecte o cabo de dados ao computador e alimente somente por USB. Não combine essa alimentação com a entrada da HAT. A porta USB 3.0 Host é para periféricos.
2. Aguarde o boot e a aparição da porta COM; abra-a a **115200 8N1**. **A conta inicial é root / 1234**, não duck.
3. Conclua o assistente de primeiro login do Armbian (shell bash pode ser escolhido). Só então o assistente cria duck / duck1234 e define duck1234 como senha de root. Ainda no terminal root, troque imediatamente as duas senhas padrão com passwd e passwd duck. Se o assistente for interrompido, o sistema pode ficar em um estado intermediário; continue a inicialização com a senha de root já definida.
4. Configure seu Wi-Fi conforme a seção 4 do guia anexo. wpa_supplicant faz a autenticação; o arquivo /etc/systemd/network/25-wlan0.network incluído nesta versão solicita um endereço IPv4 ao systemd-networkd. A imagem-base não tem NetworkManager nem nmtui.
5. Depois de conferir wpa_state=COMPLETED, o endereço IPv4 e a rota padrão, conecte-se por ssh duck@IP-da-placa a partir de um dispositivo da mesma rede local. Na primeira conexão SSH, confira a impressão digital do host mostrada localmente pela placa.

### Verificações desta versão

- A origem foi somente a imagem pública .img.xz, SHA256 4de8a355d3d9180e465af486c409e9b3e4ac82c0e241dc73d4fc0f0db7a67579; não foi usada uma imagem com Wi-Fi pessoal.
- A partição raiz GPT começa no setor 32768. Os primeiros 16 MiB da área de boot são idênticos byte a byte; kernel, DTB, overlays e bibliotecas de usuários não foram alterados.
- A verificação somente leitura e2fsck -f -n da partição raiz passou; a inspeção final foi feita com ro,noload. Conteúdo, permissões, proprietário e links simbólicos foram comparados com a versão original; as mudanças se limitam às três categorias listadas acima.
- A senha inicial de root corresponde a 1234, não a duck1234. A conta duck não existe inicialmente; permanecem o assistente e o fluxo originais de primeiro login do Armbian.
- A imagem candidata não contém chaves de host SSH. Um machine-id vazio e o serviço sshd-keygen.service habilitado fazem o sistema original executar ssh-keygen -A no primeiro boot. O mecanismo estático do serviço foi conferido; a primeira inicialização real ainda precisa ser testada.
- Não há arquivo de autenticação Wi-Fi, proxy pessoal, authorized_keys, conteúdo de diretórios de usuários nem histórico de shell. As chaves privadas SSH da imagem-base antiga também não foram encontradas na nova imagem bruta. A sintaxe Bash do comando de conexão à rede no cartão foi verificada.

Consulte o relatório de verificação anexo para todos os dados. Verificação offline não substitui gravar o cartão, inicializar, gerar chaves SSH, conectar-se à rede sem fio nem validar o hardware.

### Andamento do projeto e origem

O painel de depuração 0.15.4 foi instalado separadamente na placa principal. Em uma janela de aproximadamente 64 segundos, mantendo a pose, leu 3.000/3.000 estados válidos de cada um dos 14 servos; a meta era 50 Hz, a frequência real foi cerca de 46,87 Hz e não houve erros de timeout, checksum ou ID nessa janela. Em outros períodos ainda houve falhas ocasionais de resposta. Isso não valida o ciclo completo de controle, a IMU, movimentos com carga nem a marcha. A câmera só foi confirmada no sistema oficial B1. Consulte o [resumo do teste](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/50Hz%E4%BF%9D%E6%8C%81%E5%A7%BF%E5%8A%BF%E8%AF%BB%E7%8A%B6%E6%80%81-20260928.md).

A imagem-base vem do [Armbian](https://www.armbian.com/radxa-zero-3/); o bootloader vem do [u-boot-rk2410 da Radxa](https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/). Aplicam-se a GPL e as licenças de cada software. Esta é uma versão modificada pela comunidade, não uma publicação oficial do Armbian nem da Radxa. [Scripts de gravação e guias](https://github.com/fanhao375/microduck-replica/tree/master/tools/radxa).
