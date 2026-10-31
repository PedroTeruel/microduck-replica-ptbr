#!/bin/bash
# Cria um cartão Armbian para Radxa Zero 3W (V1.12, Wi-Fi AIC8800), pronto para iniciar, conectar ao Wi-Fi e aceitar SSH.
#   sudo bash build-armbian-card.sh <Armbian_26.2.1_Radxa-zero3_trixie_vendor_6.1.115_minimal.img.xz> [card.conf]
# O que o script faz (todos os itens já foram testados na prática):
#   1. Substitui o bootloader: nos testes locais anteriores da V1.12, o U-Boot principal do Armbian não inicializou o sistema.
#      Usa idbloader.img + u-boot.itb do pacote u-boot-rk2410 da Radxa (setores 64 / 16384).
#   2. Usa extlinux com o U-Boot da Radxa: grava /boot/extlinux/extlinux.conf e ativa os overlays uart2-m0 (serial dos servos /dev/ttyS2)
#      e dwc3-peripheral (a porta OTG conectada ao computador aparece como serial); o console do kernel fica em tty1.
#   3. Define usuário, senha, locale e fuso horário para o primeiro login. Primeiro entra como root / 1234;
#      o usuário comum só é criado após o assistente do Armbian. wpa_supplicant autentica no Wi-Fi,
#      e a configuração wlan0 do systemd-networkd obtém o IPv4 via DHCP.
#   4. Ativa o console serial USB: g_serial + serial-getty@ttyGS0 adiciona uma porta COM ao conectar a placa ao computador.
#   5. Remove o console de login da serial dos servos: mascara serial-getty@ttyS2 / ttyFIQ0.
set -euo pipefail
export LC_ALL=C.UTF-8
XZ="${1:?Uso: sudo bash $0 <Armbian_xxx.img.xz> [card.conf]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
CONF="${2:-$HERE/card.conf}"
[ "$(id -u)" = 0 ] || { echo "É necessário ser root: sudo bash $0 ..."; exit 1; }
[ -f "$XZ" ] || { echo "Arquivo não encontrado: $XZ"; exit 1; }
[ -f "$CONF" ] || { echo "Arquivo não encontrado: $CONF"; exit 1; }
# shellcheck disable=SC1090
. <(tr -d '\r' < "$CONF")
# WIFI_SSID vazio = imagem pública: não grava credenciais Wi-Fi e mantém a configuração DHCP do wlan0.
PUBLIC=0
if [ -z "${WIFI_SSID:-}" ]; then
  PUBLIC=1
  echo "Modo de imagem pública: sem credenciais Wi-Fi; conecte-se após iniciar pela serial USB (porta COM)."
elif [ "${WIFI_SSID}" = "ALTERE_PARA_O_NOME_DA_REDE" ]; then
  echo "Altere o nome e a senha do Wi-Fi em card.conf ou deixe a linha vazia para criar uma imagem pública"; exit 1
fi

UBOOT_DEB_URL=https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/u-boot-rk2410_2017.09-64-39cd993_arm64.deb
UBOOT_DEB_SHA=fb319203ab7d568aac77505504c05698385aea8a0e8f895c226c6bc557a1bce7
OUT="${XZ%.img.xz}-cartao-microduck.img"
WORK=$(mktemp -d /root/mkcard.XXXX); trap 'umount -q "$WORK/m" 2>/dev/null; rm -rf "$WORK"' EXIT

echo "[1/6] Bootloader Radxa"
DEB="$HERE/$(basename "$UBOOT_DEB_URL")"
[ -f "$DEB" ] || curl -fL --retry 3 -o "$DEB" "$UBOOT_DEB_URL"
echo "$UBOOT_DEB_SHA  $DEB" | sha256sum -c - >/dev/null || { echo "Falha na verificação do pacote u-boot"; exit 1; }
mkdir -p "$WORK/deb"; dpkg-deb -x "$DEB" "$WORK/deb"
UB="$WORK/deb/usr/lib/u-boot/radxa-zero3"; ls "$UB/idbloader.img" "$UB/u-boot.itb" >/dev/null

echo "[2/6] Extraindo o Armbian (use um disco local; não é possível montar loop em /mnt)"
xz -dkc "$XZ" > "$WORK/card.img"

echo "[3/6] Gravando o bootloader (idbloader @64, u-boot.itb @16384)"
dd if="$UB/idbloader.img" of="$WORK/card.img" bs=512 seek=64 conv=notrunc status=none
dd if="$UB/u-boot.itb"   of="$WORK/card.img" bs=512 seek=16384 conv=notrunc status=none

START=$(python3 - "$WORK/card.img" <<'PY'
import struct,sys
f=open(sys.argv[1],'rb'); f.seek(512); h=f.read(512)
elba=struct.unpack('<Q',h[72:80])[0]; esz=struct.unpack('<I',h[84:88])[0]
f.seek(elba*512); e=f.read(esz); print(struct.unpack('<Q',e[32:40])[0])
PY
)
UUID=$(python3 - "$WORK/card.img" "$START" <<'PY'
import sys,uuid
f=open(sys.argv[1],'rb'); f.seek(int(sys.argv[2])*512+1024); sb=f.read(1024); print(uuid.UUID(bytes=sb[104:120]))
PY
)
echo "      Setor inicial da partição raiz: $START; UUID: $UUID"
mkdir -p "$WORK/m"; mount -o loop,offset=$((START*512)) "$WORK/card.img" "$WORK/m"; R="$WORK/m"
KVER=$(ls "$R/lib/modules" | head -1)

echo "[4/6] extlinux (o U-Boot da Radxa reconhece este arquivo, não boot.scr)"
mkdir -p "$R/boot/extlinux"
cat > "$R/boot/extlinux/extlinux.conf" <<CONF
default armbian
timeout 3
menu title Armbian (Radxa U-Boot)

label armbian
  linux /boot/vmlinuz-$KVER
  initrd /boot/initrd.img-$KVER
  fdt /boot/dtb/rockchip/rk3566-radxa-zero3.dtb
  fdtoverlays /boot/dtb/rockchip/overlay/rk3568-uart2-m0.dtbo /boot/dtb/rockchip/overlay/rk3568-dwc3-peripheral.dtbo
  append root=UUID=$UUID rootwait rw console=tty1 consoleblank=0 cma=256M
CONF
# Também atualiza armbianEnv, usado pelo setup-board.sh oficial; o arquivo efetivo é o extlinux acima.
sed -i 's/^overlay_prefix=.*/overlay_prefix=rk3568/; s/^console=.*/console=display/' "$R/boot/armbianEnv.txt"
grep -q '^overlays=' "$R/boot/armbianEnv.txt" && sed -i 's/^overlays=.*/overlays=uart2-m0 dwc3-peripheral/' "$R/boot/armbianEnv.txt" || echo 'overlays=uart2-m0 dwc3-peripheral' >> "$R/boot/armbianEnv.txt"

echo "[5/6] Configuração inicial de login e Wi-Fi"
# Define apenas as respostas do assistente inicial do Armbian; não altera /etc/shadow nem cria duck antecipadamente.
# Confirmado para a imagem base 26.2.1: primeiro login root / 1234; as senhas abaixo passam a valer após o assistente.
cat > "$R/root/.not_logged_in_yet" <<PRESET
PRESET_NET_CHANGE_DEFAULTS=0
PRESET_CONNECT_WIRELESS=n
PRESET_ROOT_PASSWORD='${ROOT_PASSWORD:-duck1234}'
PRESET_USER_NAME='${USER_NAME:-duck}'
PRESET_USER_PASSWORD='${USER_PASSWORD:-duck1234}'
PRESET_DEFAULT_REALNAME='Duck'
PRESET_LOCALE='en_US.UTF-8'
PRESET_TIMEZONE='Asia/Shanghai'
PRESET
chmod 600 "$R/root/.not_logged_in_yet"
# A imagem base oficial contém chaves de host SSH pré-geradas. Cada cartão deve gerar suas próprias chaves na primeira inicialização.
# O machine-id desta imagem está vazio; sshd-keygen.service está habilitado para executar ssh-keygen -A no primeiro boot.
[ ! -s "$R/etc/machine-id" ] || { echo "A imagem base já tem machine-id; use uma imagem oficial que ainda não foi inicializada"; exit 1; }
[ -L "$R/etc/systemd/system/ssh.service.wants/sshd-keygen.service" ] || { echo "A imagem base não inclui o serviço de geração de chaves SSH no primeiro boot"; exit 1; }
rm -f "$R/etc/ssh/ssh_host_"*
# O 10-dhcp-all-interfaces.yaml padrão corresponde apenas a interfaces cabeadas, não ao wlan0.
# A imagem pública também pré-configura DHCP; após inserir as credenciais Wi-Fi, o endereço será obtido automaticamente.
mkdir -p "$R/etc/systemd/network"
cat > "$R/etc/systemd/network/25-wlan0.network" <<'NETWORK'
[Match]
Name=wlan0

[Network]
DHCP=ipv4
NETWORK
chmod 644 "$R/etc/systemd/network/25-wlan0.network"
if [ "$PUBLIC" = 1 ]; then
cat > "$R/root/Conecte-WiFi-primeiro.txt" <<'NOTE'
Esta imagem pública não contém credenciais Wi-Fi. Como a placa não tem porta Ethernet, configure a rede após fazer login:

No primeiro login, use root / 1234. Conclua o assistente do Armbian (quando aparecer a opção de shell, pode escolher bash).
O assistente cria o usuário comum e altera a senha do root conforme as opções; por padrão, ao terminar: duck / duck1234 e root / duck1234.
Se você alterou o usuário ou as senhas em card.conf, use esses valores. Troque as senhas padrão antes de configurar o Wi-Fi.

Configure pela serial USB ou por um terminal local; alterar o Wi-Fi desconectará o SSH sem fio. Preencha country com o país onde está.
A configuração WPA2 abaixo foi testada na V1.12 + AIC8800 e usa o DHCP pré-configurado. A imagem corrigida foi testada em 2026-09-28; outras placas e redes ainda precisam ser verificadas.

sudo mkdir -p /etc/wpa_supplicant
sudo tee /etc/wpa_supplicant/wpa_supplicant-wlan0.conf >/dev/null <<'CONF'
ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=1
country=CN

network={
    ssid="NOME_DA_REDE_WIFI"
    psk="SENHA_DA_REDE_WIFI"
    key_mgmt=WPA-PSK
    pairwise=CCMP
    ieee80211w=0
    scan_ssid=1
    priority=10
}
CONF
sudo chmod 600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
sudo systemctl enable --now systemd-networkd
sudo systemctl enable wpa_supplicant@wlan0
sudo systemctl restart wpa_supplicant@wlan0
sudo networkctl reload
sudo networkctl reconfigure wlan0
ip -4 a show wlan0       # DHCP é fornecido por 25-wlan0.network, já configurado.

Após aguardar cerca de 30 segundos, verifique: sudo wpa_cli -i wlan0 status, ip -4 a show wlan0 e ip -4 route.
O resultado deve mostrar wpa_state=COMPLETED, um endereço IPv4 e uma rota padrão.
Esta configuração exige WPA2-PSK / AES no roteador; não funciona em redes exclusivamente WPA3 ou que exijam PMF.

NetworkManager/nmtui não está instalado na imagem base; use os comandos acima.

Para gravar o Wi-Fi antes de preparar o cartão, use tools/radxa/build-armbian-card.sh do repositório,
preencha o nome e a senha em card.conf e gere um cartão já configurado.
NOTE
chmod 644 "$R/root/Conecte-WiFi-primeiro.txt"
else
# Wi-Fi usa wpa_supplicant (configuração testada na V1.12 + AIC8800; o método com netplan não foi validado nesta placa).
# Mantém a configuração WPA2-PSK/CCMP testada; não serve para redes exclusivamente WPA3 ou que exijam PMF.
# DHCP é fornecido por /etc/systemd/network/25-wlan0.network, gravado acima.
mkdir -p "$R/etc/wpa_supplicant"
cat > "$R/etc/wpa_supplicant/wpa_supplicant-wlan0.conf" <<CONF
ctrl_interface=DIR=/run/wpa_supplicant GROUP=netdev
update_config=1
country=CN

network={
    ssid="$WIFI_SSID"
    psk="$WIFI_PASSWORD"
    key_mgmt=WPA-PSK
    pairwise=CCMP
    ieee80211w=0
    scan_ssid=1
    priority=10
}
CONF
chmod 600 "$R/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"
ln -sf /lib/systemd/system/wpa_supplicant@.service "$R/etc/systemd/system/multi-user.target.wants/wpa_supplicant@wlan0.service"
fi
if [ -n "${HTTP_PROXY:-}" ]; then
  printf 'http_proxy=%s\nhttps_proxy=%s\nHTTP_PROXY=%s\nHTTPS_PROXY=%s\nno_proxy=localhost,127.0.0.1,192.168.0.0/16\nNO_PROXY=localhost,127.0.0.1,192.168.0.0/16\n' "$HTTP_PROXY" "$HTTP_PROXY" "$HTTP_PROXY" "$HTTP_PROXY" >> "$R/etc/environment"
fi

echo "[6/6] Ativando console serial USB e desativando o console de login na serial dos servos"
echo g_serial > "$R/etc/modules-load.d/duck-usb-serial.conf"
ln -sf /lib/systemd/system/serial-getty@.service "$R/etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service"
ln -sf /dev/null "$R/etc/systemd/system/serial-getty@ttyS2.service"
ln -sf /dev/null "$R/etc/systemd/system/serial-getty@ttyFIQ0.service"
rm -f "$R/etc/systemd/system/getty.target.wants/serial-getty@ttyFIQ0.service"
sync; umount "$R"
cp "$WORK/card.img" "$OUT"
echo; echo "Concluído. Grave esta imagem com Rufus / Armbian Imager: $OUT"
if [ "$PUBLIC" = 1 ]; then
  echo "Imagem pública: sem Wi-Fi pré-configurado. Conecte o cabo USB_OTG ao computador, use a porta COM (115200 8N1), entre como root / 1234, conclua o assistente do Armbian e siga /root/Conecte-WiFi-primeiro.txt para conectar."
else
  echo "No primeiro acesso, use a serial USB_OTG (115200 8N1), entre como root / 1234 e conclua o assistente do Armbian."
fi
echo "O usuário ${USER_NAME:-duck} só existe após concluir o assistente; root e o usuário comum receberão as senhas definidas em card.conf. Troque as senhas padrão imediatamente e então conecte via ssh ${USER_NAME:-duck}@IP."
