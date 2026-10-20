#!/bin/sh
# 在二号鸭上以 root 运行，只读源文件；输出一个可核验的 payload tgz。
set -eu
LC_ALL=C
export LC_ALL

STEP=初始化
ERROR_PRINTED=0
TMP=
OUT=
PYTHON=

usage() {
    echo "用法：sudo sh capture-payload.sh /tmp/microduck-payload.tgz" >&2
    echo "      sh capture-payload.sh --clean-toml IN.toml OUT.toml   （在电脑上单独测清理函数）" >&2
}

fail() {
    ERROR_PRINTED=1
    echo "错误：卡在「$STEP」：$1" >&2
    if [ "$#" -ge 2 ]; then
        echo "怎么办：$2" >&2
    fi
    exit 1
}

on_exit() {
    rc=$?
    trap '' 0
    if [ "$rc" -ne 0 ] && [ "$ERROR_PRINTED" -eq 0 ]; then
        echo "错误：脚本在「$STEP」这一步意外停止（退出码 $rc）。" >&2
        echo "怎么办：看上面的报错；源文件没有被改动，修好后重跑即可。" >&2
    fi
    if [ -n "$TMP" ] && [ -d "$TMP" ]; then
        rm -rf "$TMP" || true
    fi
    exit "$rc"
}
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap on_exit 0

json_escape() {
    printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

size_of() {
    wc -c < "$1" | tr -d '[:space:]'
}

find_python() {
    for c in python3 python3.13 python3.12 python3.11 python; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import tomllib' >/dev/null 2>&1; then
            printf '%s' "$c"
            return 0
        fi
    done
    return 1
}

validate_toml() {
    file=$1
    [ -n "$PYTHON" ] || fail "找不到带 tomllib 的 python3（需要 3.11+）" "安装 python3 后重试，或换一台机器校验。"
    "$PYTHON" - "$file" <<'PY' || fail "清理后的 TOML 读不了：$file" "保留现场，检查被删除的键是否跨行写坏了。"
import sys
import tomllib
with open(sys.argv[1], 'rb') as fh:
    tomllib.load(fh)
PY
}

# 独立的 TOML 清理函数：只删已经能确定的标定 / IMU 安装键。
# 对含义不确定、但名字看起来相关的键只记录，不删除。
# 段名可能带引号（["bus"]），比较前先去引号；跨行的值（数组、内联表）连续行一起处理。
sanitize_robotd_toml() {
    src=$1
    dst=$2
    report=$3
    awk -v report="$report" '
        function trim(s) {
            gsub(/^[ \t]+/, "", s)
            gsub(/[ \t]+$/, "", s)
            return s
        }
        function unquote(s,    q) {
            s = trim(s)
            if (length(s) >= 2) {
                q = substr(s, 1, 1)
                if ((q == "\"" || q == sprintf("%c", 39)) && substr(s, length(s), 1) == q) {
                    s = substr(s, 2, length(s) - 2)
                }
            }
            return s
        }
        function bracket_delta(s,    i, c, inq, esc, d) {
            inq = 0; esc = 0; d = 0
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (inq) {
                    if (esc) esc = 0
                    else if (c == "\\") esc = 1
                    else if (c == "\"") inq = 0
                    continue
                }
                if (c == "\"") { inq = 1; continue }
                if (c == "[") d++
                else if (c == "]") d--
                else if (c == "{") d++
                else if (c == "}") d--
            }
            return d
        }
        function is_calibration_section(name) {
            return name == "calibration" ||
                   name == "joints" ||
                   name ~ /(^|\.)calibration($|\.)/ ||
                   name ~ /(^|\.)joints($|\.)/
        }
        function is_certain_key(key, section) {
            return key == "imu_mount" ||
                   key == "imu_mount_quat" ||
                   key == "imu_mount_verified" ||
                   key == "imu_direction" ||
                   key == "mount" ||
                   key == "calibrated" ||
                   key == "calibration" ||
                   key == "zero" ||
                   key == "zero_raw" ||
                   key == "zero_offset" ||
                   key == "zero_rad" ||
                   key == "min_rad" ||
                   key == "max_rad" ||
                   key == "current_ma_per_count" ||
                   key == "units_verified" ||
                   key == "motion_enabled" ||
                   key == "joints" ||
                   key ~ /^imu_(mount|direction|zero|offset|verified)/ ||
                   key ~ /^(mount|zero)_/ ||
                   (section ~ /imu/ && key ~ /^(direction|mount|verified|zero|offset)/)
        }
        function looks_calibration_related(key) {
            return key ~ /imu|mount|calib|zero|direction|joint|verified/
        }
        {
            raw = $0
            line = trim(raw)

            if (cont > 0) {
                if (delcont) {
                    print "第 " FNR " 行，删除键 " delkey " 的续行：" raw >> report
                    cont += bracket_delta(raw)
                    if (cont <= 0) { cont = 0; delcont = 0 }
                    next
                }
                print raw
                cont += bracket_delta(raw)
                if (cont <= 0) cont = 0
                next
            }

            if (line ~ /^\[\[?/) {
                name = line
                sub(/^\[\[?/, "", name)
                sub(/\]\].*$/, "", name)
                sub(/\].*$/, "", name)
                name = unquote(name)
                gsub(/[ \t]/, "", name)
                if (name == "trunk_imu") {
                    drop = 1
                    print "第 " FNR " 行，整段删除 [" name "]：" raw >> report
                    next
                }
                drop = 0
                section = name
                print raw
                next
            }
            if (drop) {
                print "第 " FNR " 行，trunk_imu 段内删除：" raw >> report
                next
            }

            if (line == "" || line ~ /^#/) {
                print raw
                next
            }

            eq = index(line, "=")
            if (eq == 0) {
                print raw
                next
            }
            key = unquote(substr(line, 1, eq - 1))
            rest = substr(line, eq + 1)

            if (section == "audio" && key == "bank") {
                print "第 " FNR " 行，audio.bank 改成官方声音包：" raw >> report
                print "\"bank\" = \"/var/lib/robot/sounds\""
                keep = bracket_delta(rest)
                if (keep > 0) { cont = keep; delcont = 1; delkey = key }
                next
            }

            if (is_certain_key(key, section)) {
                print "第 " FNR " 行，删除键 " key "：" raw >> report
                d = bracket_delta(rest)
                if (d > 0) { cont = d; delcont = 1; delkey = key }
                next
            }
            if (looks_calibration_related(key)) {
                print "第 " FNR " 行，保留键 " key "（拿不准）：" raw >> report
            }
            print raw
            d = bracket_delta(rest)
            if (d > 0) cont = d
        }
    ' "$src" > "$dst"
}

if [ "${1:-}" = "--clean-toml" ]; then
    [ "$#" -eq 3 ] || { usage; exit 2; }
    [ -f "$2" ] || fail "输入 TOML 不存在：$2" "检查路径。"
    PYTHON=$(find_python) || PYTHON=
    TMP=$(mktemp -d "${TMPDIR:-/tmp}/microduck-clean.XXXXXX") || fail "无法创建临时目录" "检查 /tmp。"
    REPORT=$TMP/report.txt
    : > "$REPORT"
    sanitize_robotd_toml "$2" "$3" "$REPORT"
    if [ -s "$REPORT" ]; then
        sed 's/^/  /' "$REPORT"
    fi
    validate_toml "$3"
    echo "清理完成：$3"
    exit 0
fi

[ "$#" -eq 1 ] || { usage; exit 2; }
[ "$(id -u)" -eq 0 ] || fail "需要 root 才能读取完整文件" "请用：sudo sh capture-payload.sh /tmp/microduck-payload.tgz"

OUT_ARG=$1
OUT_PARENT=$(dirname "$OUT_ARG")
[ -d "$OUT_PARENT" ] || fail "输出目录不存在：$OUT_PARENT" "先建目录，或换一个存在的输出路径。"
OUT=$(cd "$OUT_PARENT" && pwd -P)/$(basename "$OUT_ARG")
[ -d "$OUT" ] && fail "输出路径是目录：$OUT" "请给一个 .tgz 文件名。"

STEP="检查工具和源文件"
echo "==> [1/6] 检查工具和源文件"
for tool in tar sha256sum awk sed find cp mkdir date uname mktemp rm sort tr wc basename dirname id; do
    command -v "$tool" >/dev/null 2>&1 || fail "缺少命令 $tool" "在二号鸭上安装 coreutils / tar 后重试。"
done
PYTHON=$(find_python) || fail "找不到带 tomllib 的 python3（需要 3.11+）" "确认二号鸭上有 python3 >= 3.11。"

PREFIX=/opt/robot/feetech-ft5-r5
ROBOTD_TOML=/etc/robot/feetech-ft5/robotd.toml
DROPIN=/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf
NETPAD=/etc/systemd/system/padd.service.d/zzzz-replica-netpad.conf
MARKER=/var/lib/robot/weird-ble

MISSING=
for p in \
    "$PREFIX/robotd" "$PREFIX/padd" "$PREFIX/mediad" \
    "$PREFIX/onnxruntime" "$PREFIX/models" "$PREFIX/roller" \
    "$PREFIX/padd.service" "$PREFIX/padd-sysusers.conf" \
    "$PREFIX/LICENSE" \
    "$ROBOTD_TOML" "$DROPIN" "$MARKER"
do
    if [ ! -e "$p" ]; then
        MISSING="$MISSING
  $p"
    fi
done
[ -z "$MISSING" ] || fail "缺少这些必需路径：$MISSING" "确认这是二号鸭，且 feetech-ft5-r5 已安装；不要用镜像里的半成品目录。"

STEP="建立临时目录并复制白名单文件"
echo "==> [2/6] 建立临时目录并复制白名单文件"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/microduck-payload.XXXXXX") || fail "无法创建临时目录" "检查 /tmp 是否可写、磁盘是否已满。"
mkdir -p "$TMP/stage"

copy_file() {
    src=$1
    rel=$2
    mkdir -p "$TMP/stage/$(dirname "$rel")"
    cp -pL "$src" "$TMP/stage/$rel" || fail "复制失败：$src" "检查权限和磁盘空间；源文件不会被修改。"
}

copy_models() {
    src=$1
    rel=$2
    dest=$TMP/stage/$rel
    mkdir -p "$dest"
    (
        cd "$src"
        find . -mindepth 1 \
            \( -name export-data.zip -o -name 'training-*.json' -o -name upstream-params \
               -o -name '*.pt' -o -name '*.ckpt' -o -name '使用说明.md' \) -prune -print
    ) > "$TMP/skipped.txt" || true
    if [ -s "$TMP/skipped.txt" ]; then
        echo "    跳过训练产物（不进镜像）："
        sed "s|^\./|      - $rel/|" "$TMP/skipped.txt"
    fi
    tar -C "$src" --numeric-owner \
        --exclude='export-data.zip' --exclude='training-*.json' --exclude='upstream-params' \
        --exclude='*.pt' --exclude='*.ckpt' --exclude='使用说明.md' \
        -cf - . | tar -C "$dest" --numeric-owner -xf - \
        || fail "复制模型目录失败：$src" "检查权限和磁盘空间；源文件不会被修改。"
}

copy_models "$PREFIX/models" opt/robot/feetech-ft5-r5/models
copy_models "$PREFIX/roller" opt/robot/feetech-ft5-r5/roller
mkdir -p "$TMP/stage/opt/robot/feetech-ft5-r5/onnxruntime"
tar -C "$PREFIX/onnxruntime" --numeric-owner -cf - . | tar -C "$TMP/stage/opt/robot/feetech-ft5-r5/onnxruntime" --numeric-owner -xf - \
    || fail "复制 onnxruntime 失败" "检查权限和磁盘空间。"

for f in robotd padd mediad padd.service padd-sysusers.conf LICENSE; do
    copy_file "$PREFIX/$f" "opt/robot/feetech-ft5-r5/$f"
done
copy_file "$DROPIN" etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf
if [ -f "$NETPAD" ]; then
    copy_file "$NETPAD" etc/systemd/system/padd.service.d/zzzz-replica-netpad.conf
else
    echo "    警告：二号鸭上没有 $NETPAD；镜像里的 UDP 手柄可能缺少网络权限，请人工确认。"
fi
if [ -d "$MARKER" ]; then
    mkdir -p "$TMP/stage/var/lib/robot/weird-ble"
    tar -C "$MARKER" --numeric-owner -cf - . | tar -C "$TMP/stage/var/lib/robot/weird-ble" --numeric-owner -xf - \
        || fail "复制 $MARKER 失败" "检查权限。"
else
    copy_file "$MARKER" var/lib/robot/weird-ble
fi

STEP="清理 robotd.toml 中的标定和 IMU 安装信息"
echo "==> [3/6] 清理 robotd.toml 中的标定和 IMU 安装信息"
mkdir -p "$TMP/stage/etc/robot/feetech-ft5"
REPORT=$TMP/robotd-clean-report.txt
: > "$REPORT"
sanitize_robotd_toml "$ROBOTD_TOML" "$TMP/stage/etc/robot/feetech-ft5/robotd.toml" "$REPORT"
if [ -s "$REPORT" ]; then
    echo "    robotd.toml 清理记录："
    sed 's/^/      /' "$REPORT"
else
    echo "    robotd.toml 没有可确定的标定键；没有删除。"
fi
validate_toml "$TMP/stage/etc/robot/feetech-ft5/robotd.toml"
cp -f "$TMP/stage/etc/robot/feetech-ft5/robotd.toml" "$TMP/stage/etc/robot/feetech-ft5/robotd.saved.toml"
echo "    同时生成 robotd.saved.toml（内容与清理后的 robotd.toml 相同）。"

STEP="生成 payload.json 清单"
echo "==> [4/6] 生成 payload.json 清单"
(
    cd "$TMP/stage"
    find . -type f ! -name payload.json | sed 's|^\./||' | sort
) > "$TMP/files.txt"
[ -s "$TMP/files.txt" ] || fail "没有收集到文件" "检查白名单路径是否为空。"

ROBOTD_SHA=$(sha256_of "$TMP/stage/opt/robot/feetech-ft5-r5/robotd")
CAPTURED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
KERNEL=$(uname -r)
{
    printf '{\n'
    printf '  "captured_at": "%s",\n' "$(json_escape "$CAPTURED_AT")"
    printf '  "uname_r": "%s",\n' "$(json_escape "$KERNEL")"
    printf '  "robotd_sha256": "%s",\n' "$ROBOTD_SHA"
    printf '  "notes": "robotd.toml 已去掉可确定的标定和 IMU 安装键，并删掉 trunk_imu 段；audio.bank 指向官方声音包；不确定的键留在文件里，逐行清单在捕获时打印。",\n'
    printf '  "files": [\n'
    first=1
    while IFS= read -r rel; do
        abs=$TMP/stage/$rel
        hash=$(sha256_of "$abs")
        bytes=$(size_of "$abs")
        if [ "$first" -eq 1 ]; then
            first=0
        else
            printf ',\n'
        fi
        printf '    {"path": "%s", "sha256": "%s", "size": %s}' \
            "$(json_escape "$rel")" "$hash" "$bytes"
    done < "$TMP/files.txt"
    printf '\n  ]\n}\n'
} > "$TMP/stage/payload.json"

# 清单自身也做一次可读性检查，避免包打好了才发现 JSON 坏了。
"$PYTHON" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TMP/stage/payload.json" \
    || fail "payload.json 不是合法 JSON" "保留现场并检查路径里是否有异常字符。"

STEP="打包并核对输出"
echo "==> [5/6] 打包并核对输出"
tar -czf "$OUT" -C "$TMP/stage" --numeric-owner . || fail "tar 打包失败：$OUT" "检查输出目录空间和权限。"
[ -s "$OUT" ] || fail "输出文件为空：$OUT" "检查磁盘空间。"

STEP="完成"
echo "==> [6/6] 完成"
echo "    payload：$OUT"
echo "    大小：$(size_of "$OUT") 字节"
echo "    robotd sha256：$ROBOTD_SHA"
echo "    拉取时间：$CAPTURED_AT"
echo "    robotd.toml 副本已清理，逐条记录见上方输出；二号鸭原文件未改动。"
