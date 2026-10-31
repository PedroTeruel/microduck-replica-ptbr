#!/bin/sh
# Execute as root on WSL / Linux: copy the base image, mount p1, apply changes, shrink, and compress.
set -eu
LC_ALL=C
export LC_ALL

STEP=Inicialização
ERROR_PRINTED=0
LOOP=
PART=
MNT=
MOUNTED=0
WORK_IMG=
OUT=

usage() {
    echo "Uso: sudo sh build-image.sh BASE_IMG PAYLOAD_TGZ STUDIO_DIR OUT_DIR" >&2
    echo "     sh build-image.sh --selftest   (não requer root; testa apenas a edição da linha da partição)" >&2
}

fail() {
    ERROR_PRINTED=1
    echo "Erro: falha em '$STEP': $1" >&2
    if [ "$#" -ge 2 ]; then
        echo "Como corrigir: $2" >&2
    fi
    exit 1
}

cleanup() {
    rc=$?
    trap '' 0
    if [ "$MOUNTED" -eq 1 ] && [ -n "$MNT" ]; then
        umount "$MNT" 2>/dev/null || echo "Aviso: umount $MNT falhou; verifique manualmente." >&2
    fi
    if [ -n "$LOOP" ]; then
        losetup -d "$LOOP" 2>/dev/null || echo "Aviso: losetup -d $LOOP falhou; verifique manualmente." >&2
    fi
    if [ -n "$MNT" ] && [ -d "$MNT" ]; then
        rmdir "$MNT" 2>/dev/null || true
    fi
    if [ "$rc" -ne 0 ] && [ "$ERROR_PRINTED" -eq 0 ]; then
        echo "Erro: o script parou inesperadamente em '$STEP' (código de saída $rc)." >&2
        echo "Como corrigir: consulte o erro do comando acima. work.img foi mantido em ${WORK_IMG:-OUT_DIR} para inspeção." >&2
    fi
    if [ "$rc" -ne 0 ] && [ -n "$WORK_IMG" ]; then
        echo "Arquivo preservado após a falha: $WORK_IMG (não foi removido)" >&2
    fi
    exit "$rc"
}
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap cleanup 0

find_python() {
    for c in python3 python3.13 python3.12 python3.11 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import tomllib' >/dev/null 2>&1; then
            printf '%s' "$c"
            return 0
        fi
    done
    return 1
}

run_e2fsck() {
    set +e
    e2fsck -f -y "$@"
    rc=$?
    set -e
    case "$rc" in
        0|1) return 0 ;;
    esac
    return "$rc"
}

# Saída de sfdisk -d → reescreve a linha de tamanho de p1. Compatível com GPT e MBR.
new_p1_line() {
    dump=$1
    size=$2
    printf '%s\n' "$dump" | awk -v size="$size" '
        !done && index($0, "start=") > 0 && $0 ~ /^[^:]+1[ \t]*:/ {
            line = $0
            if (!sub(/size=[ \t]*[0-9]+/, "size=" size, line)) exit 1
            print line
            done = 1
            exit
        }
        END {
            if (!done) exit 1
        }
    '
}

selftest_partition() {
    gpt='label: gpt
label-id: 34D3C17E-5271-473F-ACB6-7F5D55B3BB28
device: /tmp/work.img
unit: sectors
first-lba: 2048
last-lba: 768511
sector-size: 512

/tmp/work.img1 : start=2048, size=766464, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=34D3C17E-5271-473F-ACB6-7F5D55B3BB28, name="rootfs"'
    gpt_want='/tmp/work.img1 : start=2048, size=100000, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, uuid=34D3C17E-5271-473F-ACB6-7F5D55B3BB28, name="rootfs"'
    gpt_got=$(new_p1_line "$gpt" 100000) || {
        echo "Autoverificação da partição falhou: não foi possível analisar p1 no exemplo GPT." >&2
        exit 1
    }
    if [ "$gpt_got" != "$gpt_want" ]; then
        echo "Autoverificação da partição falhou: o resultado da edição GPT está incorreto." >&2
        echo "  Esperado: $gpt_want" >&2
        echo "  Obtido:   $gpt_got" >&2
        exit 1
    fi

    mbr='label: dos
label-id: 0x12345678
device: /tmp/work.img
unit: sectors
sector-size: 512

/tmp/work.img1 : start=2048, size=766464, type=83, bootable'
    mbr_want='/tmp/work.img1 : start=2048, size=100000, type=83, bootable'
    mbr_got=$(new_p1_line "$mbr" 100000) || {
        echo "Autoverificação da partição falhou: não foi possível analisar p1 no exemplo MBR." >&2
        exit 1
    }
    if [ "$mbr_got" != "$mbr_want" ]; then
        echo "Autoverificação da partição falhou: o resultado da edição MBR está incorreto." >&2
        echo "  Esperado: $mbr_want" >&2
        echo "  Obtido:   $mbr_got" >&2
        exit 1
    fi
    echo "Autoverificação da edição de linha de partição aprovada (GPT / MBR)."
}

if [ "${1:-}" = "--selftest" ]; then
    selftest_partition
    exit 0
fi

[ "$#" -eq 4 ] || { usage; exit 2; }
[ "$(id -u)" -eq 0 ] || fail "é necessário ter privilégios de root" "Execute: sudo sh build-image.sh ..."

BASE_ARG=$1
PAYLOAD_ARG=$2
STUDIO_ARG=$3
OUT_ARG=$4

STEP="Verificação das ferramentas e do ambiente"
echo "==> [1/7] Verificação das ferramentas e do ambiente"
MISSING=
for tool in cp losetup mount umount e2fsck resize2fs truncate xz sha256sum dumpe2fs sync awk sed date mkdir rm rmdir dirname basename id grep openssl; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if ! command -v sfdisk >/dev/null 2>&1; then
    MISSING="$MISSING sfdisk"
elif ! sfdisk --help 2>&1 | grep -q -- '--relocate'; then
    MISSING="$MISSING sfdisk(--relocate requer util-linux 2.33 ou superior)"
fi
    [ -z "$MISSING" ] || fail "Estes comandos estão ausentes:$MISSING" "Execute: apt install fdisk e2fsprogs xz-utils openssl"
PYTHON=$(find_python) || fail "Não foi encontrado um python3 com tomllib (é necessário 3.11 ou superior)" "Instale python3.11 na máquina de build ou ajuste PATH e tente novamente."
echo "    Python: $PYTHON"

[ -f "$BASE_ARG" ] || fail "A imagem base não existe: $BASE_ARG" "Verifique o caminho da imagem R1."
[ -f "$PAYLOAD_ARG" ] || fail "O payload não existe: $PAYLOAD_ARG" "Execute primeiro capture-payload.sh no MicroDuck de origem."
[ -d "$STUDIO_ARG" ] || fail "STUDIO_DIR não existe: $STUDIO_ARG" "Aponte para software/studio."
[ -d "$OUT_ARG" ] || mkdir -p "$OUT_ARG" || fail "Não foi possível criar OUT_DIR: $OUT_ARG" "Escolha outro diretório com permissão de escrita."
BASE_IMG=$(cd "$(dirname "$BASE_ARG")" && pwd -P)/$(basename "$BASE_ARG")
PAYLOAD=$(cd "$(dirname "$PAYLOAD_ARG")" && pwd -P)/$(basename "$PAYLOAD_ARG")
STUDIO=$(cd "$STUDIO_ARG" && pwd -P)
OUT=$(cd "$OUT_ARG" && pwd -P)
HERE=$(cd "$(dirname "$0")" && pwd -P)
APPLY=$HERE/apply-rootfs.sh
OVERLAY=$HERE/overlay
WORK_IMG=$OUT/work.img

if [ -z "${IMAGE_VERSION:-}" ]; then
    if command -v git >/dev/null 2>&1 && IMAGE_VERSION=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null); then
        if [ -n "$(git -C "$HERE" status --porcelain -- . 2>/dev/null)" ]; then
            IMAGE_VERSION="$IMAGE_VERSION-dirty"
        fi
    else
        IMAGE_VERSION=desconhecido
    fi
fi
BASE_IMG_NAME=$(basename "$BASE_IMG")
BASE_IMG_SHA256=$(sha256sum "$BASE_IMG" | awk '{print $1}') || fail "Não foi possível calcular o SHA-256 da imagem base: $BASE_IMG" "Verifique as permissões do arquivo e o espaço em disco."
PAYLOAD_SHA256=$(sha256sum "$PAYLOAD" | awk '{print $1}') || fail "Não foi possível calcular o SHA-256 do payload: $PAYLOAD" "Verifique as permissões do arquivo e o espaço em disco."
export IMAGE_VERSION BASE_IMG_NAME BASE_IMG_SHA256 PAYLOAD_SHA256
echo "    Versão do script de imagem: $IMAGE_VERSION"

case "$OUT" in
    /mnt|/mnt/*)
        fail "OUT_DIR não pode ficar em /mnt: $OUT" "No WSL, operações loop no disco do Windows são lentas e têm problemas de permissão; use ~/microduck-out."
        ;;
esac

if [ "$BASE_IMG" = "$WORK_IMG" ]; then
    fail "BASE_IMG aponta para OUT_DIR/work.img: $BASE_IMG" "A imagem base seria sobrescrita; escolha outro OUT_DIR (por exemplo, ~/microduck-out)."
fi
[ -f "$APPLY" ] || fail "apply-rootfs.sh não foi encontrado: $APPLY" "Confirme se build-image.sh e apply-rootfs.sh estão no mesmo diretório."
[ -d "$OVERLAY" ] || fail "O diretório overlay não foi encontrado: $OVERLAY" "Confirme se software/image/overlay está completo no repositório."

if [ -n "${STUDIO_VERSION:-}" ]; then
    :
elif command -v git >/dev/null 2>&1 && git -C "$STUDIO" rev-parse --short HEAD >/dev/null 2>&1; then
    STUDIO_VERSION=$(git -C "$STUDIO" rev-parse --short HEAD)
    if [ -n "$(git -C "$STUDIO" status --porcelain -- . 2>/dev/null)" ]; then
        STUDIO_VERSION="$STUDIO_VERSION-dirty"
    fi
else
    STUDIO_VERSION=desconhecido
fi
export STUDIO_VERSION
echo "    Versão do Studio: $STUDIO_VERSION"

STEP="Cópia da imagem base e montagem de p1"
echo "==> [2/7] Cópia da imagem base e montagem de p1"
if [ -e "$WORK_IMG" ]; then
    echo "    Removendo $WORK_IMG deixado pela execução anterior"
    rm -f "$WORK_IMG" || fail "Não foi possível remover o work.img antigo" "Remova-o manualmente e tente novamente."
fi
if ! cp --reflink=auto --sparse=always "$BASE_IMG" "$WORK_IMG" 2>/dev/null; then
    cp "$BASE_IMG" "$WORK_IMG"
fi
LOOP=$(losetup -f --show -P "$WORK_IMG") || fail "losetup falhou" "Confirme que o WSL habilitou dispositivos loop e que você tem privilégios de root."
PART=$LOOP"p1"
if command -v udevadm >/dev/null 2>&1; then
    udevadm settle >/dev/null 2>&1 || true
fi
tries=0
while [ ! -b "$PART" ] && [ "$tries" -lt 50 ]; do
    sleep 0.1
    tries=$((tries + 1))
done
[ -b "$PART" ] || fail "A partição $PART não apareceu em até 5 segundos após losetup -P" "Confirme que a imagem base é ext4, tem uma única partição p1 para rootfs, ou inspecione com losetup -P."
echo "    $WORK_IMG -> $LOOP, p1 = $PART"

set +e
e2fsck -f -n "$PART"
RC=$?
set -e
[ "$RC" -eq 0 ] || fail "A verificação do sistema de arquivos da p1 da imagem base falhou (código de saída de e2fsck -fn: $RC)" "Uma versão antiga de e2fsprogs pode não reconhecer os recursos usados; atualize e2fsprogs ou troque a imagem base."

MNT=$(mktemp -d "${TMPDIR:-/tmp}/microduck-mnt.XXXXXX") || fail "Não foi possível criar o ponto de montagem" "Verifique /tmp e as permissões."
mount -o rw "$PART" "$MNT" || fail "Falha ao montar $PART em $MNT" "Confirme que a imagem não está montada como somente leitura e que o dispositivo loop está disponível."
MOUNTED=1
[ -d "$MNT/etc" ] || fail "A partição p1 não contém etc/" "A partição montada pode estar incorreta ou a imagem base pode ser inválida."
echo "    p1 foi montada em $MNT"

STEP="Aplicação do payload, Studio, overlay e limpeza"
echo "==> [3/7] Aplicação do payload, Studio, overlay e limpeza"
sh "$APPLY" "$MNT" "$PAYLOAD" "$STUDIO" "$OVERLAY" || fail "apply-rootfs.sh falhou" "Corrija o problema indicado acima; work.img será preservado."
[ -f "$MNT/usr/share/doc/microduck/镜像清单.txt" ] || fail "apply-rootfs.sh não gerou o manifesto da imagem" "Verifique as permissões de /usr/share/doc/microduck."
cp -f "$MNT/usr/share/doc/microduck/镜像清单.txt" "$OUT/镜像清单.txt" || fail "Falha ao copiar o manifesto da imagem para OUT_DIR" "Verifique as permissões de OUT_DIR."
echo "    Manifesto da imagem copiado para $OUT/镜像清单.txt"
for doc in 开源许可.txt 第三方.txt 模型说明.txt; do
    cp -f "$MNT/usr/share/doc/microduck/$doc" "$OUT/$doc" || fail "Falha ao copiar $doc para OUT_DIR" "Verifique as permissões de OUT_DIR."
done
echo "    Licenças e descrição dos modelos copiadas para $OUT"

STEP="Desmontagem, limpeza dos blocos livres e redução do sistema de arquivos"
echo "==> [4/7] Desmontagem, limpeza dos blocos livres e redução do sistema de arquivos"
sync
umount "$MNT" || fail "umount falhou" "Confirme que nenhum processo está usando o ponto de montagem."
MOUNTED=0
rmdir "$MNT" 2>/dev/null || true
MNT=
run_e2fsck -E discard "$PART" || fail "e2fsck -fy -E discard falhou" "work.img será preservado; repare o sistema de arquivos ou troque a imagem base."
resize2fs -M "$PART" || fail "resize2fs -M falhou" "Confirme que rootfs usa ext4; work.img será preservado."
BLOCKS=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block count:/ {gsub(/[ \t]/,"",$2); print $2; exit}')
BSIZE=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block size:/ {gsub(/[ \t]/,"",$2); print $2; exit}')
[ -n "$BLOCKS" ] && [ -n "$BSIZE" ] || fail "Não foi possível ler o tamanho do ext4" "Inspecione $PART manualmente com dumpe2fs."
FS_BYTES=$((BLOCKS * BSIZE))
echo "    Tamanho mínimo do sistema de arquivos: $FS_BYTES bytes"

STEP="Decisão sobre reduzir a partição"
echo "==> [5/7] Decisão sobre reduzir a partição"
DUMP=$(sfdisk -d "$WORK_IMG") || fail "sfdisk -d falhou" "work.img será preservado; inspecione a tabela de partições manualmente."
LABEL=$(printf '%s\n' "$DUMP" | awk -F': ' '$1 == "label" { print $2; exit }')
P1_LINE=$(printf '%s\n' "$DUMP" | awk 'index($0, "start=") > 0 && $0 ~ /^[^:]+1[ \t]*:/ { print; exit }')
[ -n "$P1_LINE" ] || fail "Não foi possível analisar a linha da partição p1" "Inspecione work.img manualmente com sfdisk -d."
START=$(printf '%s\n' "$P1_LINE" | sed -n 's/.*start=[[:space:]]*\([0-9][0-9]*\).*/\1/p')
ORIG_SECTORS=$(printf '%s\n' "$P1_LINE" | sed -n 's/.*size=[[:space:]]*\([0-9][0-9]*\).*/\1/p')
[ -n "$START" ] && [ -n "$ORIG_SECTORS" ] || fail "Não foi possível analisar start/size de p1" "Inspecione work.img manualmente com sfdisk -d."
ORIG_PART_BYTES=$((ORIG_SECTORS * 512))

MARGIN=$((256 * 1024 * 1024))
ALIGN=$((1024 * 1024))
WANT=$((FS_BYTES + MARGIN))
WANT=$(( (WANT + ALIGN - 1) / ALIGN * ALIGN ))

if [ "$WANT" -ge "$ORIG_PART_BYTES" ]; then
    echo "    Sistema de arquivos mínimo + 256 MB = $WANT bytes, maior ou igual aos $ORIG_PART_BYTES bytes da p1 original"
    echo "    A partição não será reduzida; a compressão xz diminuirá o arquivo após limpar os blocos livres."
    resize2fs "$PART" || fail "Não foi possível expandir o sistema de arquivos de volta ao tamanho da partição original" "work.img será preservado; inspecione manualmente."
else
    SECTORS=$((WANT / 512))
    END=$((START + SECTORS - 1))
    NEW_LINE=$(new_p1_line "$DUMP" "$SECTORS") || fail "Não foi possível gerar a nova linha da partição p1" "Inspecione work.img manualmente com sfdisk -d."
    echo "    p1 original: start=$START, size=$ORIG_SECTORS setores ($ORIG_PART_BYTES bytes)"
    echo "    Nova p1: start=$START, size=$SECTORS setores ($WANT bytes)"

    losetup -d "$LOOP" || fail "Não foi possível desanexar $LOOP" "Execute losetup -d manualmente e tente novamente."
    LOOP=
    PART=
    printf '%s\n' "$NEW_LINE" | sfdisk --wipe-partitions never --no-reread -N 1 "$WORK_IMG" \
        || fail "sfdisk falhou ao modificar p1" "work.img será preservado; inspecione a tabela de partições manualmente."
    IMAGE_BYTES=$(( (END + 1) * 512 + ALIGN ))
    truncate -s "$IMAGE_BYTES" "$WORK_IMG" || fail "truncate falhou" "Verifique o espaço em disco e as permissões."
    if [ "$LABEL" = "gpt" ]; then
        sfdisk --relocate gpt-bak-std "$WORK_IMG" || fail "sfdisk --relocate falhou" "work.img será preservado; verifique o cabeçalho GPT de backup."
        sfdisk --verify "$WORK_IMG" || fail "sfdisk --verify falhou" "work.img será preservado; verifique a tabela de partições."
    fi
    echo "    A imagem foi truncada para $IMAGE_BYTES bytes"

    LOOP=$(losetup -f --show -P "$WORK_IMG") || fail "Falha ao executar losetup novamente" "Verifique o dispositivo loop."
    PART=$LOOP"p1"
    if command -v udevadm >/dev/null 2>&1; then
        udevadm settle >/dev/null 2>&1 || true
    fi
    tries=0
    while [ ! -b "$PART" ] && [ "$tries" -lt 50 ]; do
        sleep 0.1
        tries=$((tries + 1))
    done
    [ -b "$PART" ] || fail "$PART não apareceu em até 5 segundos após a nova montagem" "Verifique as alterações na tabela de partições."
    resize2fs "$PART" || fail "Não foi possível expandir o sistema de arquivos até o limite da nova partição" "work.img será preservado; inspecione manualmente."
    run_e2fsck -E discard "$PART" || fail "e2fsck -fy -E discard falhou após a redução" "work.img será preservado; o sistema de arquivos precisa de reparo manual."
fi

STEP="Compactação e geração do arquivo de verificação"
echo "==> [6/7] Compactação e geração do arquivo de verificação"
if [ -n "$LOOP" ]; then
    losetup -d "$LOOP" || fail "Não foi possível desanexar $LOOP" "Execute losetup -d manualmente e tente novamente."
    LOOP=
fi
DATE=$(date +%Y%m%d)
# IMAGE_TAG: use this for a second release on the same day (for example, 20261021b); defaults to the date.
case "${IMAGE_TAG:-}" in
    ''|*[!0-9a-z]*) [ -z "${IMAGE_TAG:-}" ] || fail "IMAGE_TAG aceita apenas números e letras minúsculas: $IMAGE_TAG" "Por exemplo: 20261021b." ;;
esac
XZ_NAME=microduck-replica-${IMAGE_TAG:-$DATE}.img.xz
xz -T0 -6 -c "$WORK_IMG" > "$OUT/$XZ_NAME" || fail "A compactação xz falhou" "Verifique o espaço disponível em OUT_DIR."
(
    cd "$OUT"
    sha256sum "$XZ_NAME" > "$XZ_NAME.sha256"
) || fail "Falha ao gerar o SHA-256" "Verifique as permissões de OUT_DIR."

STEP="Concluído"
echo "==> [7/7] Concluído"
echo "    Imagem: $OUT/$XZ_NAME"
echo "    Verificação: $OUT/$XZ_NAME.sha256"
echo "    Manifesto: $OUT/镜像清单.txt"
echo "    work.img foi mantido em $WORK_IMG (remova-o manualmente depois de confirmar que está tudo correto)."
