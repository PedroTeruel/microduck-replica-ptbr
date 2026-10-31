> **Esta versão foi removida em 21/10/2026** por estar desatualizada. Para obter um cartão pronto, use a [imagem da réplica](https://github.com/fanhao375/microduck-replica/releases/latest). As notas abaixo registram a publicação original.

> **Correção da primeira autenticação (29/09/2026):** entre primeiro com `root` / `1234`. A imagem pública ainda não tinha o usuário `duck`; ele só é criado como `duck` / `duck1234 depois de concluir o assistente de primeiro acesso do Armbian, que também altera a senha do root para `duck1234`. Essa informação foi confirmada por uma inspeção somente leitura do banco de contas da imagem e do script de primeiro acesso. A instrução anterior, que dizia para entrar inicialmente como `duck` e informava a mesma senha para root, estava errada. Troque as duas senhas padrão imediatamente após concluir o assistente.
>
> **Correção de rede (28/09/2026):** os scripts antigos de criação do cartão não incluíam a configuração DHCP para `wlan0`. Mesmo com o nome e a senha do Wi-Fi corretos, a placa podia ficar sem um endereço IPv4, impedindo o acesso por SSH. Os scripts do repositório já foram corrigidos; cartões gravados anteriormente podem receber a correção descrita adiante, sem regravação.
>
> **O arquivo `.img.xz` desta publicação e `sha256.txt` continuam sendo os originais de 20 de setembro e não incluem essas correções.** A atualização abrange somente as notas, o guia fornecido com a publicação e os scripts de criação do cartão no repositório. O arquivo antigo `/root/先连WiFi.txt` que está no cartão também não foi atualizado; siga o guia revisado. A imagem pessoal corrigida foi testada nesta unidade, que obteve DHCP e aceitou o login SSH; `networkctl` confirmou a configuração nova. Isso valida somente uma unidade, não significa que a imagem pública tenha sido substituída nem que todos os problemas de conexão estejam resolvidos.

Esta imagem comunitária foi criada para resolver um problema de compatibilidade de inicialização observado na Radxa Zero 3W V1.12 com Wi-Fi AIC8800. Ela usa o kernel e os pacotes de sistema minimal Armbian 26.2.1 Trixie vendor 6.1.115, substitui o carregador de inicialização pelo da Radxa e ajusta as configurações de inicialização, login e rede. Lotes diferentes de placas precisam de validação separada.

Há também uma imagem candidata independente `20260929`, com a correção de DHCP e sem substituir os arquivos antigos desta publicação. A candidata passou somente por verificações offline; não foi gravada em um cartão para teste. A inspeção offline também encontrou chaves de host SSH pré-geradas na versão antiga. Em cartões já gravados, gere novas chaves por um terminal local conforme o [guia de uso revisado](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/镜像使用说明.md#cartao-antigo-recriar-as-chaves-de-host-ssh), sem regravar.

**Duas piscadas do LED verde podem ser o `heartbeat` normal; não conclua, somente pelas luzes, que a inicialização falhou ou que a imagem está danificada.** A imagem-base também não contém o software completo do robô. Rede, câmera e controle dos servos precisam de validações próprias.

### Arquivos para baixar

| Arquivo | Descrição |
|---|---|
| `armbian-26.2.1-zero3w-v1.12-bootfix-20260920.img.xz` | Imagem pública original, sem nome nem senha de Wi-Fi; depois de gravar, é necessário configurar o Wi-Fi e adicionar DHCP. Grave com Rufus, balenaEtcher ou Armbian Imager. |
| `sha256.txt` | SHA-256 da imagem original acima; permanece inalterado. |
| `radxa-zero3w-image-guide-zh.md` | Guia atualizado em 29/09: primeiro login root, contas criadas ao concluir o assistente, correção DHCP em cartões antigos, troca de Wi-Fi e instruções sobre portas USB e alimentação. Sincronizado com o [guia do repositório](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/镜像使用说明.md). |

SHA-256 do arquivo `.img.xz` original:

```text
4de8a355d3d9180e465af486c409e9b3e4ac82c0e241dc73d4fc0f0db7a67579
```

### Gravar e iniciar pela primeira vez

1. Verifique a imagem e grave-a em um cartão de pelo menos 8 GB.
2. Use um **cabo USB com transferência de dados** para conectar a porta **`5V IN / USB_OTG` (USB 2.0)** à placa; alimente-a somente pelo USB. A outra porta, **USB 3.0 Host**, é para periféricos e não permite que o computador acesse a serial USB integrada.
3. Aguarde cerca de 2 a 3 minutos na primeira inicialização. Depois que o sistema carregar o dispositivo USB, o computador deverá mostrar uma porta COM. Configure o terminal serial como **115200 8N1**, pressione Enter e autentique-se como **`root` / `1234`**. Conclua o assistente do Armbian (é possível escolher `bash` como shell); somente então são criados `duck` / `duck1234` e a senha root muda para `duck1234`. Ainda no terminal root, execute `passwd` e `passwd duck` para trocar as duas senhas; depois, use `duck` no dia a dia. Se o assistente tiver sido interrompido, o estado das contas pode estar incompleto. Autentique-se com a senha root já definida e conclua o assistente, sem regravar o cartão. Se a porta COM não aparecer, verifique primeiro a conexão, o cabo de dados e a alimentação; o LED verde, sozinho, não é um diagnóstico.
4. A imagem pública não contém uma configuração Wi-Fi. Siga a seção “Primeiro uso ou troca de rede Wi-Fi” da [seção 4 do guia](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/镜像使用说明.md#4-conectar-ao-wi-fi) para configurar autenticação sem fio e DHCP. A imagem-base não instala NetworkManager; não use `nmtui`.

**Aviso sobre a alimentação pela HAT:** os pinos de 5 V do conector de 40 pinos e o VBUS de `USB_OTG` estão ligados à mesma linha de alimentação. Não alimente a placa pela HAT e por um cabo USB comum conectado ao computador ao mesmo tempo. Para usar a serial USB, desligue o sistema normalmente, desconecte a entrada de alimentação da HAT e então alimente a placa somente pelo USB. Para depurar a HAT enquanto ela alimenta a placa, prefira Wi-Fi e SSH.

### Cartões antigos com Wi-Fi configurado: adicionar somente DHCP

Estas instruções se aplicam à imagem-base deste projeto, que usa `wpa_supplicant` e `systemd-networkd`. Se o sistema tiver sido migrado para NetworkManager, confira a conexão e a obtenção automática de IPv4 por ele. Não ative dois gerenciadores de rede sem fio simultaneamente.

Entre pelo USB serial ou por um terminal local. Preserve o nome e a senha Wi-Fi já configurados e execute:

```bash
sudo mkdir -p /etc/systemd/network
sudo tee /etc/systemd/network/25-wlan0.network >/dev/null <<'NETWORK'
[Match]
Name=wlan0

[Network]
DHCP=ipv4
NETWORK
sudo chmod 644 /etc/systemd/network/25-wlan0.network
sudo systemctl enable --now systemd-networkd wpa_supplicant@wlan0
sudo networkctl reload
sudo networkctl reconfigure wlan0
```

Aguarde cerca de 30 segundos e confira:

```bash
sudo wpa_cli -i wlan0 status   # deve mostrar wpa_state=COMPLETED
ip -4 a show wlan0            # deve mostrar o endereço IPv4 atribuído pelo roteador
ip -4 route                   # deve mostrar a rota padrão
networkctl status wlan0       # confira a configuração correspondente e o estado do DHCP
```

O netplan padrão configura somente interfaces cabeadas. O `wpa_supplicant` faz a autenticação Wi-Fi; o arquivo `25-wlan0.network` permite ao `systemd-networkd` solicitar um endereço IPv4 para a interface sem fio. **Informar a senha Wi-Fi não configura DHCP automaticamente.**

Se ainda não funcionar, verifique nesta ordem: existência de `wlan0`; conclusão da autenticação; obtenção de IPv4 e rota padrão; conectividade entre o computador e a placa na mesma rede local. Se a autenticação não terminar, confira o nome da rede, a senha, o sinal e o modo do roteador. Esta correção de DHCP não substitui essas verificações. Consulte o guia fornecido para os comandos detalhados de diagnóstico.

### Trocar de computador ou de rede Wi-Fi

- **Não é necessário regravar para trocar de computador.** Basta que o computador e a placa estejam na mesma rede local e possam se comunicar; entre com `ssh duck@IP-da-placa`. Uma rede de visitantes ou o isolamento de clientes do ponto de acesso pode impedir a comunicação.
- **Ao trocar de rede Wi-Fi, configure o novo nome e a nova senha; não regrave o cartão.** Pelo USB serial ou terminal local, siga novamente a seção 4 do guia. Reiniciar o serviço sem fio desconecta uma sessão SSH que use o Wi-Fi.
- O DHCP pode atribuir outro endereço. Consulte `ip -4 a show wlan0` na placa ou a lista de dispositivos do roteador; não presuma que o endereço anterior continua válido.
- Para pré-configurar seu Wi-Fi antes de gravar, use os [scripts e as instruções de criação do cartão](https://github.com/fanhao375/microduck-replica/tree/master/tools/radxa), depois de corrigidos. Uma imagem que contenha sua senha é para uso pessoal; não a publique.

As credenciais sem fio desta imagem não estão no netplan. **Não siga diretamente o fluxo upstream `migrate-network.sh` → reiniciar.** Mantenha a conexão atual até adaptar a importação das credenciais, a desativação dos serviços antigos e a recuperação em caso de desconexão; do contrário, a placa pode ficar inacessível por disputa entre gerenciadores de rede ou ausência da senha importada.

### Inicialização, periféricos e revisões da placa

A imagem substitui o carregador original pelo `u-boot-rk2410` da Radxa e inicializa por `extlinux.conf`. Configura os overlays `uart2-m0` e `dwc3-peripheral` e move o console de login da serial dos servos para o USB gadget. Eles habilitam, respectivamente, `/dev/ttyS2` para o barramento dos servos e a serial USB para login; isso não significa que o software de controle esteja instalado ou que o hardware tenha sido validado.

Em 28/09/2026, foi testada comunicação somente leitura com a HAT e, em seguida, corrigido o agrupamento das respostas de leitura síncrona por ID. A bancada web 0.15.4 foi implantada e manteve a postura existente por cerca de 64 segundos. Quatorze servos apresentaram estado válido 3000/3000, sem erros durante o intervalo; a meta era 50 Hz e a taxa observada foi de aproximadamente 46,87 Hz. Ainda ocorreram respostas ausentes em outros períodos. As proteções, o movimento e o ciclo completo de controle não foram validados. Essa bancada, instalada separadamente, não está incluída nesta imagem. Consulte o [resumo das 3000 leituras](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/50Hz%E4%BF%9D%E6%8C%81%E5%A7%BF%E5%8A%BF%E8%AF%BB%E7%8A%B6%E6%80%81-20260928.md).

Um membro da comunidade relatou que sua placa V1.12J/AIC8800DS2 iniciou com a combinação **carregador B1 + DTB B1 + kernel Armbian 6.1.115 + sistema Trixie**. Este projeto ainda não validou essa combinação de forma independente. Kernels com a mesma versão 6.1 não garantem que o DTB seja compatível; depois de trocar o DTB, confira novamente as sobreposições de serial e USB. Consulte a seção 6 do guia para os relatos e cuidados de operação.

O teste da câmera de 28/09 foi feito na **Radxa B1 oficial**. Depois de ajustar a orientação e o contato do cabo, a placa reconheceu a IMX219 e capturou 40 quadros em um teste curto. A repetição na imagem Armbian deste projeto ainda não foi concluída. Veja o [diagrama de conexão e registro de depuração](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/摄像头调试记录-20260928.md).

### Origem e licenças

- Imagem-base: [imagem oficial Radxa Zero da Armbian](https://www.armbian.com/radxa-zero-3/), 26.2.1 Trixie vendor 6.1.115 minimal, sob GPL e as licenças próprias dos componentes.
- Carregador: [`u-boot-rk2410`](https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/) da Radxa, versão `2017.09-64-39cd993`, sob GPL-2.0.
- A criação do cartão está documentada em [`build-armbian-card.sh`](https://github.com/fanhao375/microduck-replica/blob/master/tools/radxa/build-armbian-card.sh). O script atual inclui correções de DHCP, instruções de primeiro login e tratamento das chaves de host SSH; sua imagem gerada não será idêntica, byte a byte, à imagem antiga mantida nesta publicação.

Imagem comunitária, sem publicação ou endosso da Armbian ou da Radxa. Ao relatar um problema, informe a revisão da placa e anexe registros sem dados pessoais; abra uma [issue](https://github.com/fanhao375/microduck-replica/issues) neste repositório.
