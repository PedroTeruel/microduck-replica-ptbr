#!/bin/sh
# Execute as root on the source Microduck. Reads source files only and creates a verifiable payload archive.
set -eu
LC_ALL=C
export LC_ALL

STEP=Inicialização
ERROR_PRINTED=0
TMP=
OUT=
PYTHON=

usage() {
    echo "Uso: sudo sh capture-payload.sh /tmp/microduck-payload.tgz" >&2
    echo "     sh capture-payload.sh --clean-toml IN.toml OUT.toml   (testa a função de limpeza separadamente no computador)" >&2
}

fail() {
    ERROR_PRINTED=1
    echo "Erro: falha em '$STEP': $1" >&2
    if [ "$#" -ge 2 ]; then
        echo "Como corrigir: $2" >&2
    fi
    exit 1
}

on_exit() {
    rc=$?
    trap '' 0
    if [ "$rc" -ne 0 ] && [ "$ERROR_PRINTED" -eq 0 ]; then
        echo "Erro: o script parou inesperadamente em '$STEP' (código de saída $rc)." >&2
        echo "Como corrigir: consulte o erro acima; os arquivos de origem não foram alterados. Corrija o problema e execute novamente." >&2
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
    [ -n "$PYTHON" ] || fail "Não foi encontrado python3 com tomllib (é necessário 3.11 ou superior)" "Instale python3 e tente novamente, ou valide em outra máquina."
    "$PYTHON" - "$file" <<'PY' || fail "Não foi possível ler o TOML após a limpeza: $file" "Preserve o arquivo e verifique se alguma chave removida estava escrita em várias linhas."
import sys
import tomllib
with open(sys.argv[1], 'rb') as fh:
    tomllib.load(fh)
PY
}

# Standalone TOML cleanup: remove only calibration/IMU mounting keys that are unambiguously identified.
# Record keys whose names look related but whose meaning is unclear; do not remove them.
# Section names may be quoted (["bus"]); remove quotes before comparison. Process multiline values (arrays and inline tables) together.
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
                    print "Linha " FNR ": continuação removida da chave " delkey ": " raw >> report
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
                    print "Linha " FNR ": seção inteira removida [" name "]: " raw >> report
                    next
                }
                drop = 0
                section = name
                print raw
                next
            }
            if (drop) {
                print "Linha " FNR ": removida da seção trunk_imu: " raw >> report
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
                print "Linha " FNR ": audio.bank substituída pelo pacote oficial de sons: " raw >> report
                print "\"bank\" = \"/var/lib/robot/sounds\""
                keep = bracket_delta(rest)
                if (keep > 0) { cont = keep; delcont = 1; delkey = key }
                next
            }

            if (is_certain_key(key, section)) {
                print "Linha " FNR ": chave removida " key ": " raw >> report
                d = bracket_delta(rest)
                if (d > 0) { cont = d; delcont = 1; delkey = key }
                next
            }
            if (looks_calibration_related(key)) {
                print "Linha " FNR ": chave mantida " key " (significado incerto): " raw >> report
            }
            print raw
            d = bracket_delta(rest)
            if (d > 0) cont = d
        }
    ' "$src" > "$dst"
}

if [ "${1:-}" = "--clean-toml" ]; then
    [ "$#" -eq 3 ] || { usage; exit 2; }
    [ -f "$2" ] || fail "O arquivo TOML de entrada não existe: $2" "Verifique o caminho."
    PYTHON=$(find_python) || PYTHON=
    TMP=$(mktemp -d "${TMPDIR:-/tmp}/microduck-clean.XXXXXX") || fail "Não foi possível criar o diretório temporário" "Verifique /tmp."
    REPORT=$TMP/report.txt
    : > "$REPORT"
    sanitize_robotd_toml "$2" "$3" "$REPORT"
    if [ -s "$REPORT" ]; then
        sed 's/^/  /' "$REPORT"
    fi
    validate_toml "$3"
    echo "Limpeza concluída: $3"
    exit 0
fi

[ "$#" -eq 1 ] || { usage; exit 2; }
[ "$(id -u)" -eq 0 ] || fail "É necessário ter privilégios de root para ler todos os arquivos" "Execute: sudo sh capture-payload.sh /tmp/microduck-payload.tgz"

OUT_ARG=$1
OUT_PARENT=$(dirname "$OUT_ARG")
[ -d "$OUT_PARENT" ] || fail "O diretório de saída não existe: $OUT_PARENT" "Crie o diretório ou escolha um caminho existente."
OUT=$(cd "$OUT_PARENT" && pwd -P)/$(basename "$OUT_ARG")
[ -d "$OUT" ] && fail "O caminho de saída é um diretório: $OUT" "Informe o nome de um arquivo .tgz."

STEP="Verificação das ferramentas e dos arquivos de origem"
echo "==> [1/6] Verificação das ferramentas e dos arquivos de origem"
for tool in tar sha256sum awk sed find cp mkdir date uname mktemp rm sort tr wc basename dirname id; do
    command -v "$tool" >/dev/null 2>&1 || fail "Comando ausente: $tool" "Instale coreutils / tar no Microduck de origem e tente novamente."
done
PYTHON=$(find_python) || fail "Não foi encontrado python3 com tomllib (é necessário 3.11 ou superior)" "Confirme se o Microduck de origem tem python3 >= 3.11."

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
[ -z "$MISSING" ] || fail "Estes caminhos obrigatórios estão ausentes:$MISSING" "Confirme que este é o Microduck de origem e que feetech-ft5-r5 está instalado; não use diretórios incompletos de uma imagem."

STEP="Criação do diretório temporário e cópia dos arquivos permitidos"
echo "==> [2/6] Criação do diretório temporário e cópia dos arquivos permitidos"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/microduck-payload.XXXXXX") || fail "Não foi possível criar o diretório temporário" "Verifique se /tmp permite gravação e se há espaço em disco."
mkdir -p "$TMP/stage"

copy_file() {
    src=$1
    rel=$2
    mkdir -p "$TMP/stage/$(dirname "$rel")"
    cp -pL "$src" "$TMP/stage/$rel" || fail "Falha ao copiar: $src" "Verifique as permissões e o espaço em disco; o arquivo de origem não será alterado."
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
        echo "    Artefatos de treinamento ignorados (não serão incluídos na imagem):"
        sed "s|^\./|      - $rel/|" "$TMP/skipped.txt"
    fi
    tar -C "$src" --numeric-owner \
        --exclude='export-data.zip' --exclude='training-*.json' --exclude='upstream-params' \
        --exclude='*.pt' --exclude='*.ckpt' --exclude='使用说明.md' \
        -cf - . | tar -C "$dest" --numeric-owner -xf - \
        || fail "Falha ao copiar o diretório de modelos: $src" "Verifique as permissões e o espaço em disco; os arquivos de origem não serão alterados."
}

copy_models "$PREFIX/models" opt/robot/feetech-ft5-r5/models
copy_models "$PREFIX/roller" opt/robot/feetech-ft5-r5/roller
mkdir -p "$TMP/stage/opt/robot/feetech-ft5-r5/onnxruntime"
tar -C "$PREFIX/onnxruntime" --numeric-owner -cf - . | tar -C "$TMP/stage/opt/robot/feetech-ft5-r5/onnxruntime" --numeric-owner -xf - \
    || fail "Falha ao copiar onnxruntime" "Verifique as permissões e o espaço em disco."

for f in robotd padd mediad padd.service padd-sysusers.conf LICENSE; do
    copy_file "$PREFIX/$f" "opt/robot/feetech-ft5-r5/$f"
done
copy_file "$DROPIN" etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf
if [ -f "$NETPAD" ]; then
    copy_file "$NETPAD" etc/systemd/system/padd.service.d/zzzz-replica-netpad.conf
else
    echo "    Aviso: $NETPAD não existe no Microduck de origem; o controle UDP na imagem pode ficar sem permissões de rede. Verifique manualmente."
fi
if [ -d "$MARKER" ]; then
    mkdir -p "$TMP/stage/var/lib/robot/weird-ble"
    tar -C "$MARKER" --numeric-owner -cf - . | tar -C "$TMP/stage/var/lib/robot/weird-ble" --numeric-owner -xf - \
        || fail "Falha ao copiar $MARKER" "Verifique as permissões."
else
    copy_file "$MARKER" var/lib/robot/weird-ble
fi

STEP="Limpeza dos dados de calibração e de montagem da IMU em robotd.toml"
echo "==> [3/6] Limpeza dos dados de calibração e de montagem da IMU em robotd.toml"
mkdir -p "$TMP/stage/etc/robot/feetech-ft5"
REPORT=$TMP/robotd-clean-report.txt
: > "$REPORT"
sanitize_robotd_toml "$ROBOTD_TOML" "$TMP/stage/etc/robot/feetech-ft5/robotd.toml" "$REPORT"
if [ -s "$REPORT" ]; then
    echo "    Registro da limpeza de robotd.toml:"
    sed 's/^/      /' "$REPORT"
else
    echo "    robotd.toml não contém chaves de calibração identificáveis com certeza; nada foi removido."
fi
validate_toml "$TMP/stage/etc/robot/feetech-ft5/robotd.toml"
cp -f "$TMP/stage/etc/robot/feetech-ft5/robotd.toml" "$TMP/stage/etc/robot/feetech-ft5/robotd.saved.toml"
echo "    Também foi criado robotd.saved.toml (com o mesmo conteúdo de robotd.toml após a limpeza)."

STEP="Geração do manifesto payload.json"
echo "==> [4/6] Geração do manifesto payload.json"
(
    cd "$TMP/stage"
    find . -type f ! -name payload.json | sed 's|^\./||' | sort
) > "$TMP/files.txt"
[ -s "$TMP/files.txt" ] || fail "Nenhum arquivo foi coletado" "Verifique se os caminhos permitidos estão vazios."

ROBOTD_SHA=$(sha256_of "$TMP/stage/opt/robot/feetech-ft5-r5/robotd")
CAPTURED_AT=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
KERNEL=$(uname -r)
{
    printf '{\n'
    printf '  "captured_at": "%s",\n' "$(json_escape "$CAPTURED_AT")"
    printf '  "uname_r": "%s",\n' "$(json_escape "$KERNEL")"
    printf '  "robotd_sha256": "%s",\n' "$ROBOTD_SHA"
    printf '  "notes": "As chaves de calibração e montagem da IMU identificadas com certeza foram removidas de robotd.toml, assim como a seção trunk_imu; audio.bank aponta para o pacote oficial de sons; chaves incertas foram mantidas e listadas linha por linha durante a captura.",\n'
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

# Validate the manifest itself so malformed JSON is caught before packaging.
"$PYTHON" -c 'import json,sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$TMP/stage/payload.json" \
    || fail "payload.json não contém JSON válido" "Preserve os arquivos e verifique se algum caminho contém caracteres inesperados."

STEP="Empacotamento e verificação da saída"
echo "==> [5/6] Empacotamento e verificação da saída"
tar -czf "$OUT" -C "$TMP/stage" --numeric-owner . || fail "Falha ao criar o pacote tar: $OUT" "Verifique o espaço disponível e as permissões do diretório de saída."
[ -s "$OUT" ] || fail "O arquivo de saída está vazio: $OUT" "Verifique o espaço em disco."

STEP="Concluído"
echo "==> [6/6] Concluído"
echo "    Payload: $OUT"
echo "    Tamanho: $(size_of "$OUT") bytes"
echo "    SHA-256 do robotd: $ROBOTD_SHA"
echo "    Data da captura: $CAPTURED_AT"
echo "    A cópia de robotd.toml foi limpa; consulte os detalhes acima. O arquivo original do Microduck de origem não foi alterado."
