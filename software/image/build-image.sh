#!/bin/sh
# 在 WSL / Linux 里以 root 运行：复制底图、挂载 p1、应用改动、缩容、压缩。
set -eu
LC_ALL=C
export LC_ALL

STEP=初始化
ERROR_PRINTED=0
LOOP=
PART=
MNT=
MOUNTED=0
WORK_IMG=
OUT=

usage() {
    echo "用法：sudo sh build-image.sh BASE_IMG PAYLOAD_TGZ STUDIO_DIR OUT_DIR" >&2
    echo "      sh build-image.sh --selftest   （不需要 root，只测分区行改写）" >&2
}

fail() {
    ERROR_PRINTED=1
    echo "错误：卡在「$STEP」：$1" >&2
    if [ "$#" -ge 2 ]; then
        echo "怎么办：$2" >&2
    fi
    exit 1
}

cleanup() {
    rc=$?
    trap '' 0
    if [ "$MOUNTED" -eq 1 ] && [ -n "$MNT" ]; then
        umount "$MNT" 2>/dev/null || echo "警告：umount $MNT 失败，请手工检查。" >&2
    fi
    if [ -n "$LOOP" ]; then
        losetup -d "$LOOP" 2>/dev/null || echo "警告：losetup -d $LOOP 失败，请手工检查。" >&2
    fi
    if [ -n "$MNT" ] && [ -d "$MNT" ]; then
        rmdir "$MNT" 2>/dev/null || true
    fi
    if [ "$rc" -ne 0 ] && [ "$ERROR_PRINTED" -eq 0 ]; then
        echo "错误：脚本在「$STEP」这一步意外停止（退出码 $rc）。" >&2
        echo "怎么办：看上面的命令报错。work.img 保留在 ${WORK_IMG:-OUT_DIR}，方便检查。" >&2
    fi
    if [ "$rc" -ne 0 ] && [ -n "$WORK_IMG" ]; then
        echo "失败现场：$WORK_IMG（未删除）" >&2
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

# sfdisk -d 的输出 → 改写 p1 size 的那一行。GPT / MBR 通用。
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
        echo "分区自检失败：GPT 样例没有解析出 p1" >&2
        exit 1
    }
    if [ "$gpt_got" != "$gpt_want" ]; then
        echo "分区自检失败：GPT 改写结果不对" >&2
        echo "  期望：$gpt_want" >&2
        echo "  实际：$gpt_got" >&2
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
        echo "分区自检失败：MBR 样例没有解析出 p1" >&2
        exit 1
    }
    if [ "$mbr_got" != "$mbr_want" ]; then
        echo "分区自检失败：MBR 改写结果不对" >&2
        echo "  期望：$mbr_want" >&2
        echo "  实际：$mbr_got" >&2
        exit 1
    fi
    echo "分区行改写自检通过（GPT / MBR）。"
}

if [ "${1:-}" = "--selftest" ]; then
    selftest_partition
    exit 0
fi

[ "$#" -eq 4 ] || { usage; exit 2; }
[ "$(id -u)" -eq 0 ] || fail "需要 root" "请用：sudo sh build-image.sh ..."

BASE_ARG=$1
PAYLOAD_ARG=$2
STUDIO_ARG=$3
OUT_ARG=$4

STEP="检查工具和环境"
echo "==> [1/7] 检查工具和环境"
MISSING=
for tool in cp losetup mount umount e2fsck resize2fs truncate xz sha256sum dumpe2fs sync awk sed date mkdir rm rmdir dirname basename id grep openssl; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if ! command -v sfdisk >/dev/null 2>&1; then
    MISSING="$MISSING sfdisk"
elif ! sfdisk --help 2>&1 | grep -q -- '--relocate'; then
    MISSING="$MISSING sfdisk(--relocate 需要 util-linux 2.33+)"
fi
    [ -z "$MISSING" ] || fail "缺少这些命令：$MISSING" "运行：apt install fdisk e2fsprogs xz-utils openssl"
PYTHON=$(find_python) || fail "找不到带 tomllib 的 python3（需要 3.11+）" "在构建机安装 python3.11 或设置 PATH 后重试。"
echo "    python：$PYTHON"

[ -f "$BASE_ARG" ] || fail "底图不存在：$BASE_ARG" "检查 R1 镜像路径。"
[ -f "$PAYLOAD_ARG" ] || fail "payload 不存在：$PAYLOAD_ARG" "先在二号鸭上运行 capture-payload.sh。"
[ -d "$STUDIO_ARG" ] || fail "STUDIO_DIR 不存在：$STUDIO_ARG" "指向 software/studio。"
[ -d "$OUT_ARG" ] || mkdir -p "$OUT_ARG" || fail "无法创建 OUT_DIR：$OUT_ARG" "换一个可写目录。"
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
        IMAGE_VERSION=未知
    fi
fi
BASE_IMG_NAME=$(basename "$BASE_IMG")
BASE_IMG_SHA256=$(sha256sum "$BASE_IMG" | awk '{print $1}') || fail "无法计算底图 sha256：$BASE_IMG" "检查文件权限和磁盘。"
PAYLOAD_SHA256=$(sha256sum "$PAYLOAD" | awk '{print $1}') || fail "无法计算 payload sha256：$PAYLOAD" "检查文件权限和磁盘。"
export IMAGE_VERSION BASE_IMG_NAME BASE_IMG_SHA256 PAYLOAD_SHA256
echo "    镜像脚本版本：$IMAGE_VERSION"

case "$OUT" in
    /mnt|/mnt/*)
        fail "OUT_DIR 不能放在 /mnt 下：$OUT" "WSL 的 Windows 盘上 loop 很慢、权限也不对；换成 ~/microduck-out。"
        ;;
esac

if [ "$BASE_IMG" = "$WORK_IMG" ]; then
    fail "BASE_IMG 就是 OUT_DIR/work.img：$BASE_IMG" "底图会被覆盖；换一个 OUT_DIR（例如 ~/microduck-out）。"
fi
[ -f "$APPLY" ] || fail "缺少 apply-rootfs.sh：$APPLY" "确认 build-image.sh 和它在同一目录。"
[ -d "$OVERLAY" ] || fail "缺少 overlay 目录：$OVERLAY" "确认仓库里的 software/image/overlay 完整。"

if [ -n "${STUDIO_VERSION:-}" ]; then
    :
elif command -v git >/dev/null 2>&1 && git -C "$STUDIO" rev-parse --short HEAD >/dev/null 2>&1; then
    STUDIO_VERSION=$(git -C "$STUDIO" rev-parse --short HEAD)
    if [ -n "$(git -C "$STUDIO" status --porcelain -- . 2>/dev/null)" ]; then
        STUDIO_VERSION="$STUDIO_VERSION-dirty"
    fi
else
    STUDIO_VERSION=未知
fi
export STUDIO_VERSION
echo "    Studio 版本：$STUDIO_VERSION"

STEP="复制底图并挂载 p1"
echo "==> [2/7] 复制底图并挂载 p1"
if [ -e "$WORK_IMG" ]; then
    echo "    删除上次留下的 $WORK_IMG"
    rm -f "$WORK_IMG" || fail "无法删除旧 work.img" "手工删除后重试。"
fi
if ! cp --reflink=auto --sparse=always "$BASE_IMG" "$WORK_IMG" 2>/dev/null; then
    cp "$BASE_IMG" "$WORK_IMG"
fi
LOOP=$(losetup -f --show -P "$WORK_IMG") || fail "losetup 失败" "确认 WSL 已挂载 loop 设备并给了 root 权限。"
PART=$LOOP"p1"
if command -v udevadm >/dev/null 2>&1; then
    udevadm settle >/dev/null 2>&1 || true
fi
tries=0
while [ ! -b "$PART" ] && [ "$tries" -lt 50 ]; do
    sleep 0.1
    tries=$((tries + 1))
done
[ -b "$PART" ] || fail "losetup -P 后 5 秒内没有出现分区：$PART" "确认底图是 p1 为 rootfs 的单分区 ext4 镜像；或手工 losetup -P 检查。"
echo "    $WORK_IMG -> $LOOP，p1 = $PART"

set +e
e2fsck -f -n "$PART"
RC=$?
set -e
[ "$RC" -eq 0 ] || fail "底图 p1 的文件系统检查失败（e2fsck -fn 退出码 $RC）" "e2fsprogs 太旧认不出特性时会在这里报；升级 e2fsprogs 或换底图。"

MNT=$(mktemp -d "${TMPDIR:-/tmp}/microduck-mnt.XXXXXX") || fail "无法创建挂载点" "检查 /tmp 和权限。"
mount -o rw "$PART" "$MNT" || fail "挂载失败：$PART -> $MNT" "确认镜像没有只读挂载、loop 设备可用。"
MOUNTED=1
[ -d "$MNT/etc" ] || fail "p1 里没有 etc/" "挂错分区或底图不对。"
echo "    p1 已挂到 $MNT"

STEP="应用 payload、Studio、overlay 和清理"
echo "==> [3/7] 应用 payload、Studio、overlay 和清理"
sh "$APPLY" "$MNT" "$PAYLOAD" "$STUDIO" "$OVERLAY" || fail "apply-rootfs.sh 失败" "按上面输出的步骤修复；work.img 保留。"
[ -f "$MNT/usr/share/doc/microduck/镜像清单.txt" ] || fail "apply-rootfs.sh 没有生成镜像清单" "检查 /usr/share/doc/microduck 权限。"
cp -f "$MNT/usr/share/doc/microduck/镜像清单.txt" "$OUT/镜像清单.txt" || fail "复制镜像清单到 OUT_DIR 失败" "检查 OUT_DIR 权限。"
echo "    镜像清单已拷到 $OUT/镜像清单.txt"
for doc in 开源许可.txt 第三方.txt 模型说明.txt; do
    cp -f "$MNT/usr/share/doc/microduck/$doc" "$OUT/$doc" || fail "复制 $doc 到 OUT_DIR 失败" "检查 OUT_DIR 权限。"
done
echo "    许可和模型说明已拷到 $OUT"

STEP="卸载、清零空闲块并缩到最小文件系统"
echo "==> [4/7] 卸载、清零空闲块并缩到最小文件系统"
sync
umount "$MNT" || fail "umount 失败" "确认没有进程占用挂载点。"
MOUNTED=0
rmdir "$MNT" 2>/dev/null || true
MNT=
run_e2fsck -E discard "$PART" || fail "e2fsck -fy -E discard 失败" "work.img 保留，先修文件系统或换底图。"
resize2fs -M "$PART" || fail "resize2fs -M 失败" "确认 rootfs 是 ext4；work.img 保留。"
BLOCKS=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block count:/ {gsub(/[ \t]/,"",$2); print $2; exit}')
BSIZE=$(dumpe2fs -h "$PART" 2>/dev/null | awk -F: '/^Block size:/ {gsub(/[ \t]/,"",$2); print $2; exit}')
[ -n "$BLOCKS" ] && [ -n "$BSIZE" ] || fail "无法读取 ext4 大小" "用 dumpe2fs 手工检查 $PART。"
FS_BYTES=$((BLOCKS * BSIZE))
echo "    文件系统最小大小：$FS_BYTES 字节"

STEP="决定是否缩分区"
echo "==> [5/7] 决定是否缩分区"
DUMP=$(sfdisk -d "$WORK_IMG") || fail "sfdisk -d 失败" "work.img 保留；手工检查分区表。"
LABEL=$(printf '%s\n' "$DUMP" | awk -F': ' '$1 == "label" { print $2; exit }')
P1_LINE=$(printf '%s\n' "$DUMP" | awk 'index($0, "start=") > 0 && $0 ~ /^[^:]+1[ \t]*:/ { print; exit }')
[ -n "$P1_LINE" ] || fail "无法解析 p1 分区行" "用 sfdisk -d work.img 手工检查。"
START=$(printf '%s\n' "$P1_LINE" | sed -n 's/.*start=[[:space:]]*\([0-9][0-9]*\).*/\1/p')
ORIG_SECTORS=$(printf '%s\n' "$P1_LINE" | sed -n 's/.*size=[[:space:]]*\([0-9][0-9]*\).*/\1/p')
[ -n "$START" ] && [ -n "$ORIG_SECTORS" ] || fail "无法解析 p1 的 start/size" "用 sfdisk -d work.img 手工检查。"
ORIG_PART_BYTES=$((ORIG_SECTORS * 512))

MARGIN=$((256 * 1024 * 1024))
ALIGN=$((1024 * 1024))
WANT=$((FS_BYTES + MARGIN))
WANT=$(( (WANT + ALIGN - 1) / ALIGN * ALIGN ))

if [ "$WANT" -ge "$ORIG_PART_BYTES" ]; then
    echo "    最小文件系统 + 256 MB = $WANT 字节，不小于原 p1 的 $ORIG_PART_BYTES 字节"
    echo "    不缩分区，靠清零 + xz 压小"
    resize2fs "$PART" || fail "把文件系统撑回原分区大小失败" "work.img 保留；手工检查。"
else
    SECTORS=$((WANT / 512))
    END=$((START + SECTORS - 1))
    NEW_LINE=$(new_p1_line "$DUMP" "$SECTORS") || fail "无法生成新的 p1 分区行" "用 sfdisk -d work.img 手工检查。"
    echo "    原 p1：start=$START size=$ORIG_SECTORS sectors（$ORIG_PART_BYTES 字节）"
    echo "    新 p1：start=$START size=$SECTORS sectors（$WANT 字节）"

    losetup -d "$LOOP" || fail "无法 detach $LOOP" "手工 losetup -d 后重试。"
    LOOP=
    PART=
    printf '%s\n' "$NEW_LINE" | sfdisk --wipe-partitions never --no-reread -N 1 "$WORK_IMG" \
        || fail "sfdisk 修改 p1 失败" "work.img 保留；手工检查分区表。"
    IMAGE_BYTES=$(( (END + 1) * 512 + ALIGN ))
    truncate -s "$IMAGE_BYTES" "$WORK_IMG" || fail "truncate 失败" "检查磁盘空间和权限。"
    if [ "$LABEL" = "gpt" ]; then
        sfdisk --relocate gpt-bak-std "$WORK_IMG" || fail "sfdisk --relocate 失败" "work.img 保留；检查 GPT 备份头。"
        sfdisk --verify "$WORK_IMG" || fail "sfdisk --verify 失败" "work.img 保留；检查分区表。"
    fi
    echo "    镜像已截到 $IMAGE_BYTES 字节"

    LOOP=$(losetup -f --show -P "$WORK_IMG") || fail "重新 losetup 失败" "检查 loop 设备。"
    PART=$LOOP"p1"
    if command -v udevadm >/dev/null 2>&1; then
        udevadm settle >/dev/null 2>&1 || true
    fi
    tries=0
    while [ ! -b "$PART" ] && [ "$tries" -lt 50 ]; do
        sleep 0.1
        tries=$((tries + 1))
    done
    [ -b "$PART" ] || fail "重新挂载后 5 秒内没出现 $PART" "检查分区表改动。"
    resize2fs "$PART" || fail "把文件系统撑满新分区失败" "work.img 保留；手工检查。"
    run_e2fsck -E discard "$PART" || fail "缩容后的 e2fsck -fy -E discard 失败" "work.img 保留，文件系统需要人工修复。"
fi

STEP="压缩并生成校验文件"
echo "==> [6/7] 压缩并生成校验文件"
if [ -n "$LOOP" ]; then
    losetup -d "$LOOP" || fail "无法 detach $LOOP" "手工 losetup -d 后重试。"
    LOOP=
fi
DATE=$(date +%Y%m%d)
# IMAGE_TAG：同一天出第二版时用（比如 20261021b），不给就是日期
case "${IMAGE_TAG:-}" in
    ''|*[!0-9a-z]*) [ -z "${IMAGE_TAG:-}" ] || fail "IMAGE_TAG 只能是数字和小写字母：$IMAGE_TAG" "比如 20261021b。" ;;
esac
XZ_NAME=microduck-replica-${IMAGE_TAG:-$DATE}.img.xz
xz -T0 -6 -c "$WORK_IMG" > "$OUT/$XZ_NAME" || fail "xz 压缩失败" "检查 OUT_DIR 空间。"
(
    cd "$OUT"
    sha256sum "$XZ_NAME" > "$XZ_NAME.sha256"
) || fail "生成 sha256 失败" "检查 OUT_DIR 权限。"

STEP="完成"
echo "==> [7/7] 完成"
echo "    镜像：$OUT/$XZ_NAME"
echo "    校验：$OUT/$XZ_NAME.sha256"
echo "    清单：$OUT/镜像清单.txt"
echo "    work.img 总是保留在 $WORK_IMG（确认无误后可手工删除）。"
