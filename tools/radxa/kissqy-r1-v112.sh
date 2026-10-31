#!/bin/bash
# Adapta a imagem de instalação única R1 do kissqy para inicializar também na placa V1.12.
#   sudo bash kissqy-r1-v112.sh <microduck-zero3w-0.15.1-R1.img.xz> [--no-camera] [--no-tof] [--overlay i2c4-m0 ...]
#
# Motivo: a R1 usa o U-Boot principal do Armbian 2025.10 e firmware v1.21 de inicialização da memória.
# A placa V1.12 (Wi-Fi AIC8800) não inicia com esse bootloader; é necessário usar o bootloader da Radxa (veja o README e os registros de problemas).
#
# Modifica apenas os itens abaixo. Mantém os demais componentes como estão (firmware, modelos, configuração inicial por hotspot, bloqueio de contas e geração de chaves SSH no primeiro boot):
#   1. Grava idbloader.img / u-boot.itb do u-boot-rk2410 da Radxa nos setores 64 / 16384 (mesma versão e SHA-256 de build-armbian-card.sh).
#   2. Grava /boot/extlinux/extlinux.conf: o U-Boot da Radxa reconhece extlinux, não boot.scr. Overlays, FDT e parâmetros do kernel
#      são copiados do armbianEnv.txt da imagem, mantendo o áudio HAT, a câmera e o NPU originais.
#   3. Opcionalmente, --overlay NAME adiciona um overlay, por exemplo i2c4-m0 (I²C4 nos pinos 27/28 do conector de 40 pinos, onde pode ser ligado o módulo IMU).
#   4. --no-camera / --no-tof desativa a inicialização automática de mediad / tofd. Sem câmera ou ToF, eles podem reiniciar repetidamente;
#      mediad verifica os plugins GStreamer a cada reinício, podendo ocupar um núcleo e reduzir a frequência da placa.
#
# Atenção: após trocar o bootloader pelo da Radxa, alterações em armbianEnv.txt deixam de valer; novos overlays devem ser incluídos em extlinux.conf.
# Este script altera apenas o bootloader e a configuração de inicialização. Não faz o programa reconhecer o módulo IMU (a R1 aceita somente a placa IMU ID 200 no barramento).
set -euo pipefail
export LC_ALL=C.UTF-8

R1_SHA=75da978b5d56acd9e4146256431732381de84523bb683e4ab7ac9f0580a7bce5   # Hash publicado pelo kissqy.
UBOOT_DEB_URL=https://radxa-repo.github.io/bookworm/pool/main/u/u-boot-rk2410/u-boot-rk2410_2017.09-64-39cd993_arm64.deb
UBOOT_DEB_SHA=fb319203ab7d568aac77505504c05698385aea8a0e8f895c226c6bc557a1bce7

XZ="${1:?Uso: sudo bash $0 <microduck-zero3w-0.15.1-R1.img.xz> [--no-camera] [--no-tof] [--overlay NAME ...]}"
shift
NO_CAMERA=0; NO_TOF=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-camera) NO_CAMERA=1 ;;
    --no-tof) NO_TOF=1 ;;
    --overlay) EXTRA+=("${2:?--overlay exige um nome, por exemplo i2c4-m0}"); shift ;;
    *) echo "Opção desconhecida: $1"; exit 1 ;;
  esac
  shift
done
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" = 0 ] || { echo "É necessário ser root: sudo bash $0 ..."; exit 1; }
[ -f "$XZ" ] || { echo "Arquivo não encontrado: $XZ"; exit 1; }

echo "[1/7] Verificando o hash do pacote R1 original"
GOT=$(sha256sum "$XZ" | cut -d' ' -f1)
[ "$GOT" = "$R1_SHA" ] || { echo "Hash incorreto: $GOT (esperado: $R1_SHA). Confira outras versões antes de alterar o script."; exit 1; }

OUT="${XZ%.img.xz}-V112.img"
WORK=$(mktemp -d /root/r1v112.XXXX); trap 'umount -q "$WORK/m" 2>/dev/null; rm -rf "$WORK"' EXIT

echo "[2/7] Bootloader Radxa"
DEB="$HERE/$(basename "$UBOOT_DEB_URL")"
[ -f "$DEB" ] || curl -fL --retry 3 -o "$DEB" "$UBOOT_DEB_URL"
echo "$UBOOT_DEB_SHA  $DEB" | sha256sum -c - >/dev/null || { echo "Falha na verificação do pacote u-boot"; exit 1; }
mkdir -p "$WORK/deb"; dpkg-deb -x "$DEB" "$WORK/deb"
UB="$WORK/deb/usr/lib/u-boot/radxa-zero3"; ls "$UB/idbloader.img" "$UB/u-boot.itb" >/dev/null

echo "[3/7] Extraindo a imagem (use um disco local; não é possível montar loop em /mnt)"
xz -dkc "$XZ" > "$WORK/card.img"

START=$(python3 - "$WORK/card.img" <<'PY'
import struct,sys
f=open(sys.argv[1],'rb'); f.seek(512); h=f.read(512)
elba=struct.unpack('<Q',h[72:80])[0]; esz=struct.unpack('<I',h[84:88])[0]
f.seek(elba*512); e=f.read(esz); print(struct.unpack('<Q',e[32:40])[0])
PY
)
# O bootloader ocupa os setores 64..32767; a partição deve começar no setor 32768 ou depois.
[ "$START" -ge 32768 ] || { echo "A partição raiz começa no setor $START; não há espaço para o bootloader Radxa. Interrompendo."; exit 1; }

echo "[4/7] Gravando o bootloader (idbloader @64, u-boot.itb @16384)"
dd if="$UB/idbloader.img" of="$WORK/card.img" bs=512 seek=64 conv=notrunc status=none
dd if="$UB/u-boot.itb"   of="$WORK/card.img" bs=512 seek=16384 conv=notrunc status=none

UUID=$(python3 - "$WORK/card.img" "$START" <<'PY'
import sys,uuid
f=open(sys.argv[1],'rb'); f.seek(int(sys.argv[2])*512+1024); sb=f.read(1024); print(uuid.UUID(bytes=sb[104:120]))
PY
)
echo "      Setor inicial da partição raiz: $START; UUID: $UUID"
mkdir -p "$WORK/m"; mount -o loop,offset=$((START*512)) "$WORK/card.img" "$WORK/m"; R="$WORK/m"
KVER=$(ls "$R/lib/modules" | head -1)
ENV="$R/boot/armbianEnv.txt"
val(){ sed -n "s/^$1=//p" "$ENV" | tr -d '\r' | tail -1; }
PREFIX=$(val overlay_prefix); FDT=$(val fdtfile); ARGS=$(val extraargs)
read -r -a OVERLAYS <<< "$(val overlays)"
for o in "${EXTRA[@]}"; do [[ " ${OVERLAYS[*]} " == *" $o "* ]] || OVERLAYS+=("$o"); done

echo "[5/7] extlinux (o U-Boot da Radxa reconhece este arquivo, não boot.scr)"
FILES=()
for o in "${OVERLAYS[@]}"; do
  f="/boot/dtb/rockchip/overlay/${PREFIX}-${o}.dtbo"
  [ -f "$R$f" ] || { echo "Arquivo de overlay ausente na imagem: $f. Interrompendo."; exit 1; }
  FILES+=("$f")
done
[ -f "$R/boot/vmlinuz-$KVER" ] && [ -f "$R/boot/initrd.img-$KVER" ] && [ -f "$R/boot/dtb/$FDT" ] \
  || { echo "Kernel, initrd ou $FDT ausente. Interrompendo."; exit 1; }
mkdir -p "$R/boot/extlinux"
cat > "$R/boot/extlinux/extlinux.conf" <<CONF
default armbian
timeout 3
menu title kissqy R1 (Radxa U-Boot)

label armbian
  linux /boot/vmlinuz-$KVER
  initrd /boot/initrd.img-$KVER
  fdt /boot/dtb/$FDT
  fdtoverlays ${FILES[*]}
  append root=UUID=$UUID rootwait rw console=tty1 consoleblank=0 ${ARGS}
CONF
# Sincroniza a lista de overlays em armbianEnv para referência de scripts futuros; extlinux é a configuração efetiva.
sed -i "s/^overlays=.*/overlays=${OVERLAYS[*]}/" "$ENV"

echo "[6/7] Serviços"
off(){ rm -f "$R/etc/systemd/system/multi-user.target.wants/$1.service"; echo "      $1 não iniciará mais automaticamente (para reativar: sudo systemctl enable --now $1)"; }
[ "$NO_CAMERA" = 1 ] && off mediad
[ "$NO_TOF" = 1 ] && off tofd
cat > "$R/etc/microduck-v112-image.txt" <<NOTE
Este cartão foi adaptado da kissqy Public Image R1 pelo microduck-replica tools/radxa/kissqy-r1-v112.sh em $(date -u +%F).
SHA-256 do pacote original: $R1_SHA
Alterações: bootloader Radxa u-boot-rk2410 2017.09-64; /boot/extlinux/extlinux.conf; overlays=${OVERLAYS[*]}; no-camera=$NO_CAMERA no-tof=$NO_TOF
Após trocar o bootloader, altere os overlays em extlinux.conf; armbianEnv.txt não terá efeito.
NOTE

echo "[7/7] Finalização"
umount "$WORK/m"
mv "$WORK/card.img" "$OUT"
echo "Imagem pronta: $OUT"
sha256sum "$OUT"
