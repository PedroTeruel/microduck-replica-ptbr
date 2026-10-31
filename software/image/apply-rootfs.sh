#!/bin/sh
# Instala payload, Studio e overlay em um diretório rootfs já montado e faz a limpeza.
# Executa somente operações com arquivos: não usa dispositivos loop nem chroot.
set -eu
LC_ALL=C
export LC_ALL

STEP=Inicialização
ERROR_PRINTED=0
WORK=
ROOT=
DEL_LOG=
ADD_LOG=
SSH_WARN=
PYTHON=
STUDIO_DEST=
SYSTEMD=
DELETE_LIST=
PAYLOAD_META=
STUDIO_VERSION=${STUDIO_VERSION:-}
BASE_IMG_NAME=${BASE_IMG_NAME:-desconhecido}
BASE_IMG_SHA256=${BASE_IMG_SHA256:-desconhecido}
PAYLOAD_SHA256=${PAYLOAD_SHA256:-}
IMAGE_VERSION=${IMAGE_VERSION:-}
ALLOW_UNCONFIRMED=${ALLOW_UNCONFIRMED:-0}

usage() {
    echo "Uso: sh apply-rootfs.sh ROOT PAYLOAD_TGZ STUDIO_DIR OVERLAY_DIR" >&2
}

fail() {
    ERROR_PRINTED=1
    echo "Erro na etapa '$STEP': $1" >&2
    if [ "$#" -ge 2 ]; then
        echo "Como resolver: $2" >&2
    fi
    exit 1
}

on_exit() {
    rc=$?
    trap '' 0
    if [ "$rc" -ne 0 ] && [ "$ERROR_PRINTED" -eq 0 ]; then
        echo "Erro: o script parou inesperadamente na etapa '$STEP' (código de saída $rc)." >&2
        echo "Como resolver: confira o erro acima, corrija-o e execute novamente. Alguns arquivos em ROOT podem ter sido parcialmente alterados." >&2
    fi
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then
        rm -rf "$WORK" || true
    fi
    exit "$rc"
}
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap on_exit 0

rel_path() {
    p=$1
    case "$p" in
        "$ROOT"/*) p=${p#"$ROOT"/} ;;
    esac
    printf '%s' "$p"
}

add_del() {
    printf '%s\n' "$(rel_path "$1")" >> "$DEL_LOG"
}

add_add() {
    printf '%s\n' "$(rel_path "$1")" >> "$ADD_LOG"
}

assert_parent_in_root() {
    p=$1
    parent=$(dirname "$p")
    [ -d "$parent" ] || fail "O diretório pai do destino não existe: $parent" "Confirme se a estrutura de ROOT está completa ou monte a imagem novamente."
    real=$(cd "$parent" && pwd -P)
    case "$real" in
        "$ROOT"|"$ROOT"/*) ;;
        *) fail "Operação recusada fora de ROOT: $p (diretório pai real: $real)" "Verifique se há links simbólicos em ROOT apontando para o sistema hospedeiro." ;;
    esac
}

# Cria diretórios, inclusive os pais ausentes, sempre com permissão 0755. Se algum caminho
# existente ou a ser criado resolver para fora de ROOT, falha imediatamente; nunca grava antes de verificar.
safe_dir() {
    dir=$1
    case "$dir" in
        "$ROOT"|"$ROOT"/*) ;;
        *) fail "Criação de diretório recusada fora de ROOT: $dir" "Erro interno; interrompa e confira os argumentos." ;;
    esac
    probe=$dir
    while [ ! -e "$probe" ] && [ ! -L "$probe" ]; do
        parent=$(dirname "$probe")
        [ "$parent" != "$probe" ] || break
        probe=$parent
    done
    [ -d "$probe" ] || fail "O caminho contém um item que não é diretório: $probe" "Confira a estrutura de arquivos em ROOT."
    real=$(cd "$probe" && pwd -P) || fail "Não foi possível resolver o diretório: $probe" "Confira as permissões."
    case "$real" in
        "$ROOT"|"$ROOT"/*) ;;
        *) fail "Gravação recusada fora de ROOT: o pai $probe de $dir resolve para $real" "Há um link simbólico em ROOT apontando para fora da imagem; remova-o e tente novamente." ;;
    esac
    : > "$WORK/absent-dirs.txt"
    probe=$dir
    while [ ! -d "$probe" ] && [ "$probe" != "$ROOT" ] && [ "$probe" != "/" ]; do
        printf '%s\n' "$probe" >> "$WORK/absent-dirs.txt"
        probe=$(dirname "$probe")
    done
    mkdir -p "$dir" || fail "Não foi possível criar o diretório: $dir" "Confira se ROOT permite gravação e se há espaço em disco suficiente."
    if [ -s "$WORK/absent-dirs.txt" ]; then
        while IFS= read -r d; do
            [ -n "$d" ] || continue
            chmod 0755 "$d" || fail "Não foi possível definir as permissões do diretório: $d" "Confira se ROOT permite gravação."
        done < "$WORK/absent-dirs.txt"
    fi
    real=$(cd "$dir" && pwd -P) || fail "Não foi possível acessar o diretório: $dir" "Confira as permissões."
    case "$real" in
        "$ROOT"|"$ROOT"/*) ;;
        *) fail "Gravação recusada fora de ROOT: $dir resolve para $real" "Há um link simbólico em ROOT apontando para fora da imagem; remova-o e tente novamente." ;;
    esac
}

# Se o destino for um link simbólico, remove primeiro apenas o link e então permite a gravação; o diretório pai passa por safe_dir.
safe_file() {
    file=$1
    case "$file" in
        "$ROOT"/*) ;;
        *) fail "Gravação recusada fora de ROOT: $file" "Erro interno; interrompa e confira os argumentos." ;;
    esac
    if [ "$file" = "$ROOT" ]; then
        fail "Gravação recusada na própria ROOT" "O script grava somente arquivos específicos dentro de ROOT."
    fi
    safe_dir "$(dirname "$file")"
    if [ -L "$file" ]; then
        echo "  Removendo link simbólico (para evitar gravar no destino do link): $file"
        add_del "$file"
        rm -f "$file" || fail "Não foi possível remover o link simbólico: $file" "Confira as permissões."
    fi
    if [ -d "$file" ]; then
        fail "O destino é um diretório, não pode ser gravado como arquivo: $file" "Confira a estrutura de ROOT."
    fi
}

remove_path() {
    p=$1
    if [ ! -e "$p" ] && [ ! -L "$p" ]; then
        return 0
    fi
    case "$p" in
        "$ROOT"/*) ;;
        *) fail "Remoção recusada fora de ROOT: $p" "Erro interno; interrompa e confira os argumentos." ;;
    esac
    if [ "$p" = "$ROOT" ]; then
        fail "Remoção recusada da própria ROOT" "O script remove somente caminhos específicos dentro de ROOT."
    fi
    assert_parent_in_root "$p"
    echo "  Removendo $p"
    add_del "$p"
    rm -rf "$p" || fail "Falha ao remover: $p" "Confira as permissões; ROOT pode estar somente para leitura."
}

truncate_regular_file() {
    p=$1
    safe_file "$p"
    : > "$p" || fail "Não foi possível esvaziar o arquivo: $p" "Confira as permissões."
}

print_list() {
    label=$1
    file=$2
    if [ -s "$file" ]; then
        echo "    $label ($(wc -l < "$file" | tr -d '[:space:]') itens):"
        sed 's/^/      - /' "$file"
    fi
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

sha256_of() {
    sha256sum "$1" | awk '{print $1}'
}

size_of() {
    wc -c < "$1" | tr -d '[:space:]'
}

# No Windows, grep/awk podem remover CR; por isso Python lê os arquivos em modo binário.
# Ignora arquivos com NUL ou extensões binárias comuns (PNG etc. podem conter 0x0d).
check_crlf_paths() {
    "$PYTHON" - "$WORK/crlf.txt" "$OVERLAY" "$STUDIO/deploy" "$STUDIO/run.py" <<'PY' || fail "Falha na verificação de quebras de linha" "Confira se os diretórios overlay e Studio podem ser lidos."
import sys
from pathlib import Path

out = Path(sys.argv[1])
found = []
binary_suffixes = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".tif", ".tiff",
    ".pdf", ".zip", ".gz", ".xz", ".tgz", ".bz2", ".7z", ".so", ".bin", ".pyc",
    ".ttf", ".otf", ".woff", ".woff2", ".mp3", ".wav", ".ogg", ".mp4", ".webm",
}
for raw in sys.argv[2:]:
    path = Path(raw)
    files = [path] if path.is_file() else (list(path.rglob("*")) if path.is_dir() else [])
    for item in files:
        if not item.is_file():
            continue
        if item.suffix.lower() in binary_suffixes:
            continue
        try:
            data = item.read_bytes()
        except OSError:
            continue
        if b"\x00" in data:
            continue
        if b"\r" in data:
            found.append(str(item))
out.write_text("".join(line + "\n" for line in sorted(found)), encoding="utf-8")
PY
}

rewrite_radxa_gecos() {
    file=$1
    [ -e "$file" ] || [ -L "$file" ] || fail "Arquivo de contas ausente: $file" "Confirme se a imagem base contém etc/passwd e etc/passwd-."
    safe_file "$file"
    [ -f "$file" ] || fail "O arquivo de contas não é um arquivo regular: $file" "Confira a estrutura de ROOT/etc."
    "$PYTHON" - "$file" "$WORK/passwd.new" <<'PY' || fail "Não foi possível alterar somente o nome completo de radxa: $file" "Confirme se o arquivo segue o formato passwd padrão (7 campos separados por dois-pontos)."
import sys
from pathlib import Path

src, dst = sys.argv[1], sys.argv[2]
raw = Path(src).read_bytes()
lines = raw.split(b'\n')
seen = 0
for index, line in enumerate(lines):
    cr = b''
    if line.endswith(b'\r'):
        line = line[:-1]
        cr = b'\r'
    fields = line.split(b':')
    if fields and fields[0] == b'radxa':
        seen += 1
        if len(fields) != 7:
            raise SystemExit('A linha de radxa não tem 7 campos')
        fields[4] = b'Microduck'
        lines[index] = b':'.join(fields) + cr
if seen != 1:
    raise SystemExit(f'Esperada exatamente uma linha de radxa; encontradas {seen}')
Path(dst).write_bytes(b'\n'.join(lines))
PY
    cat "$WORK/passwd.new" > "$file" || fail "Não foi possível gravar o arquivo de contas: $file" "Confira as permissões."
    echo "  Nome completo de radxa alterado em $(rel_path "$file"): Microduck"
    add_add "$file"
}

# Altera somente o segundo campo (hash da senha) da linha de radxa; os demais campos, linhas e atributos do arquivo ficam intactos.
set_radxa_password_hash() {
    file=$1
    hash=$2
    [ -e "$file" ] || fail "Arquivo de contas ausente: $file" "Confirme se a imagem base contém etc/shadow (verifique também shadow-, se existir)."
    safe_file "$file"
    [ -f "$file" ] || fail "O arquivo de contas não é um arquivo regular: $file" "Confira a estrutura de ROOT/etc."
    "$PYTHON" - "$file" "$WORK/shadow.new" "$hash" <<'PY' || fail "Não foi possível alterar somente o hash da senha de radxa: $file" "Confirme o formato shadow padrão (9 campos separados por dois-pontos) e uma única linha de radxa."
import sys
from pathlib import Path

src, dst, new_hash = sys.argv[1], sys.argv[2], sys.argv[3].encode("ascii")
raw = Path(src).read_bytes()
lines = raw.split(b"\n")
seen = 0
for index, line in enumerate(lines):
    cr = b""
    if line.endswith(b"\r"):
        line = line[:-1]
        cr = b"\r"
    fields = line.split(b":")
    if fields and fields[0] == b"radxa":
        seen += 1
        if len(fields) != 9:
            raise SystemExit("A linha de radxa não tem 9 campos")
        fields[1] = new_hash
        lines[index] = b":".join(fields) + cr
if seen != 1:
    raise SystemExit(f"Esperada exatamente uma linha de radxa; encontradas {seen}")
Path(dst).write_bytes(b"\n".join(lines))
PY
    cat "$WORK/shadow.new" > "$file" || fail "Não foi possível gravar o arquivo de contas: $file" "Confira as permissões."
    echo "  Hash de senha padrão de radxa definido em $(rel_path "$file")"
    add_add "$file"
}

set_updater_dev_keys_false() {
    file=$1
    [ -e "$file" ] || [ -L "$file" ] || fail "Configuração do atualizador ausente: $file" "Confirme se a imagem base contém etc/robot/updater.toml."
    safe_file "$file"
    [ -f "$file" ] || fail "A configuração do atualizador não é um arquivo regular: $file" "Confira a estrutura de ROOT/etc/robot."
    "$PYTHON" - "$file" "$WORK/updater.toml.new" <<'PY' || fail "Não foi possível alterar somente o valor de allow_dev_keys: $file" "Confirme se há apenas uma linha allow_dev_keys no arquivo de configuração."
import re
import sys
from pathlib import Path

src, dst = sys.argv[1], sys.argv[2]
raw = Path(src).read_bytes()
lines = raw.split(b'\n')
pattern = re.compile(rb'^([ \t]*allow_dev_keys[ \t]*=[ \t]*)(true|false)([ \t]*(?:#.*)?)$')
matches = []
for index, line in enumerate(lines):
    cr = b''
    if line.endswith(b'\r'):
        line = line[:-1]
        cr = b'\r'
    match = pattern.match(line)
    if match:
        matches.append((index, match, cr))
if len(matches) != 1:
    raise SystemExit(f'Esperada exatamente uma linha allow_dev_keys; encontradas {len(matches)}')
index, match, cr = matches[0]
lines[index] = match.group(1) + b'false' + match.group(3) + cr
Path(dst).write_bytes(b'\n'.join(lines))
PY
    if cmp -s "$file" "$WORK/updater.toml.new"; then
        echo "  $(rel_path "$file") já está com allow_dev_keys = false"
    else
        cat "$WORK/updater.toml.new" > "$file" || fail "Não foi possível gravar a configuração do atualizador: $file" "Confira as permissões."
        echo "  Alterado $(rel_path "$file"): allow_dev_keys = false"
        add_add "$file"
    fi
}

prune_dev_keys() {
    dir=$1
    [ -d "$dir" ] || fail "Diretório de chaves públicas do atualizador ausente: $dir" "Confirme se a imagem base contém etc/robot/trusted_keys."
    dev_keys=$WORK/dev-keys.txt
    find "$dir" -mindepth 1 -maxdepth 1 -name '*.dev.pub' -print | LC_ALL=C sort > "$dev_keys" \
        || fail "Não foi possível listar as chaves públicas de assinatura de desenvolvimento: $dir" "Confira as permissões do diretório."
    print_list "Chaves públicas de desenvolvimento a remover" "$dev_keys"
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        remove_path "$p"
    done < "$dev_keys"
    release_keys=$WORK/release-keys.txt
    find "$dir" -mindepth 1 -maxdepth 1 -type f -name 'release-*.pub' -print | LC_ALL=C sort > "$release_keys" \
        || fail "Não foi possível listar as chaves públicas oficiais de assinatura: $dir" "Confira as permissões do diretório."
    if [ ! -s "$release_keys" ]; then
        fail "Nenhuma release-*.pub encontrada no diretório de confiança: $dir" "O atualizador não inicia com o diretório de confiança vazio; restaure as chaves públicas oficiais de release e tente novamente."
    fi
    echo "    Chaves públicas oficiais de assinatura mantidas:"
    sed 's/^/      - /' "$release_keys"
}

manifest_to_tsv() {
    manifest=$1
    out=$2
    : > "$out"
    if [ -n "$PYTHON" ]; then
        if "$PYTHON" - "$manifest" > "$WORK/manifest.raw" 2>/dev/null <<'PY'
import json
import sys
with open(sys.argv[1], encoding='utf-8') as fh:
    data = json.load(fh)
files = data.get('files')
if not isinstance(files, list):
    raise SystemExit('payload.json não contém o vetor files')
for item in files:
    path = item['path']
    digest = item['sha256']
    size = int(item['size'])
    if '\t' in path or '\n' in path:
        raise SystemExit('O caminho no payload contém tabulação ou quebra de linha')
    print(f'{path}\t{digest}\t{size}')
PY
        then
            tr -d '\r' < "$WORK/manifest.raw" > "$out"
        fi
    fi
    if [ ! -s "$out" ]; then
        echo "    Aviso: falha ao analisar payload.json com Python; usando awk como alternativa." >&2
        awk '
            {
                line = $0
                if (match(line, /"path"[ \t]*:[ \t]*"[^"]*"/)) {
                    p = substr(line, RSTART, RLENGTH)
                    sub(/^"path"[ \t]*:[ \t]*"/, "", p)
                    sub(/"$/, "", p)
                    rest = substr(line, RSTART + RLENGTH)
                    h = ""
                    s = ""
                    if (match(rest, /"sha256"[ \t]*:[ \t]*"[0-9a-fA-F]+"/)) {
                        h = substr(rest, RSTART, RLENGTH)
                        sub(/^"sha256"[ \t]*:[ \t]*"/, "", h)
                        sub(/"$/, "", h)
                    }
                    if (match(line, /"size"[ \t]*:[ \t]*[0-9]+/)) {
                        s = substr(line, RSTART, RLENGTH)
                        sub(/^"size"[ \t]*:[ \t]*/, "", s)
                    }
                    if (h != "" && s != "") print p "\t" h "\t" s
                }
            }
        ' "$manifest" > "$out"
    fi
    [ -s "$out" ] || fail "Não foi possível analisar payload.json" "Gere novamente com capture-payload.sh ou instale python3 e tente outra vez."
}

verify_manifest() {
    base=$1
    label=$2
    while IFS=$(printf '\t') read -r rel expected size; do
        case "$rel" in
            ""|/*|*".."*) fail "Caminho inseguro no manifesto do payload: $rel" "Gere o payload novamente." ;;
        esac
        target=$base/$rel
        if [ ! -e "$target" ] && [ ! -L "$target" ]; then
            fail "Arquivo ausente em $label: $rel" "Execute capture-payload.sh novamente ou confira se o tgz está completo."
        fi
        if [ -L "$target" ]; then
            fail "Link simbólico em $label: $rel" "O payload não permite links simbólicos; gere-o novamente."
        fi
        actual=$(sha256_of "$target")
        if [ "$actual" != "$expected" ]; then
            fail "SHA-256 divergente em $label: $rel (esperado $expected, obtido $actual)" "Não continue: baixe o payload novamente e confira se a transferência não foi corrompida."
        fi
        actual_size=$(size_of "$target")
        if [ "$actual_size" != "$size" ]; then
            fail "Tamanho divergente em $label: $rel (esperado $size, obtido $actual_size)" "Baixe o payload novamente."
        fi
    done < "$WORK/files.tsv"
}

put_file() {
    src=$1
    dst=$2
    mode=$3
    [ -f "$src" ] || fail "Arquivo de origem ausente: $src" "Confira se STUDIO_DIR/deploy está completo."
    safe_file "$dst"
    if [ "$(id -u)" -eq 0 ]; then
        install -D -m "$mode" -o 0 -g 0 "$src" "$dst" || fail "Falha ao instalar o arquivo: $dst" "Confira se ROOT permite gravação e se há espaço em disco suficiente."
    else
        install -D -m "$mode" "$src" "$dst" || fail "Falha ao instalar o arquivo: $dst" "Confira se ROOT permite gravação e se há espaço em disco suficiente."
    fi
    add_add "$dst"
}

# Na imagem de fábrica, inicia o programa principal em modo de calibração. O assistente remove este arquivo após concluir a etapa 3 do guia inicial.
# O conteúdo e os comentários do arquivo fazem parte do contrato com o assistente e não podem ser alterados.
write_commissioning_dropin() {
    src=$STAGE/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf
    dst=$SYSTEMD/robotd.service.d/zzzz-zz-microduck-commissioning.conf
    [ -f "$src" ] || fail "Drop-in do robotd ausente no payload: etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf" "Execute capture-payload.sh novamente; o payload está incompleto."
    "$PYTHON" - "$src" "$WORK/commissioning.conf" <<'PY' || fail "Não foi possível gerar o drop-in de calibração de fábrica a partir de zzzz-r17-0151.conf do payload" "Confira o drop-in: deve haver exatamente uma linha ExecStart= não vazia e ela ainda não pode conter --commissioning."
import re
import sys
from pathlib import Path

src, dst = sys.argv[1], sys.argv[2]
exec_lines = []
for raw in Path(src).read_text(encoding="utf-8", errors="strict").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        continue
    if line.startswith("ExecStart="):
        value = line[len("ExecStart="):].strip()
        if value:
            exec_lines.append(value)
if len(exec_lines) != 1:
    raise SystemExit("zzzz-r17-0151.conf deve conter exatamente uma linha ExecStart= não vazia; encontradas %d" % len(exec_lines))
command = exec_lines[0]
if re.search(r"(^|\s)--commissioning(\s|$)", command):
    raise SystemExit("zzzz-r17-0151.conf já contém --commissioning; payload inválido")
text = (
    "# Imagem réplica do Microduck: inicia o programa principal no modo de calibração (--commissioning).\n"
    "# Após concluir a etapa 3 do guia inicial (gravar o programa principal), o assistente root remove este arquivo e o programa volta ao modo de movimento.\n"
    "[Service]\n"
    "ExecStart=\n"
    "ExecStart=" + command + " --commissioning\n"
)
Path(dst).write_text(text, encoding="utf-8", newline="\n")
PY
    safe_file "$dst"
    cp -f "$WORK/commissioning.conf" "$dst" || fail "Não foi possível gravar o drop-in do modo de calibração de fábrica: $dst" "Confira se ROOT permite gravação e se há espaço em disco suficiente."
    chmod 0644 "$dst" || fail "Não foi possível definir as permissões: $dst" "Confira as permissões do sistema de arquivos de ROOT."
    if [ "$(id -u)" -eq 0 ]; then
        chown 0:0 "$dst" || fail "Não foi possível definir o proprietário: $dst (root:root)" "Confira se o sistema de arquivos de ROOT permite chown."
    fi
    add_add "$dst"
    echo "    Drop-in do modo de calibração de fábrica gravado: $(rel_path "$dst")"
}

make_enable_link() {
    target=$1
    link=$2
    safe_file "$link"
    if ! ln -s "$target" "$link" 2>/dev/null; then
        source_file=$ROOT$target
        [ -f "$source_file" ] || fail "Arquivo da unidade ausente; não é possível criar o link de habilitação: $target" "Confira OVERLAY_DIR ou o caminho da unidade systemd."
        cp -f "$source_file" "$link" || fail "Não foi possível criar o link: $link" "Confira as permissões."
        echo "  Aviso: este sistema não cria links simbólicos; no ambiente de teste, copiando o arquivo da unidade: $link"
    fi
    echo "  Link criado: $link -> $target"
    add_add "$link"
}

queue_delete() {
    p=$1
    if [ -e "$p" ] || [ -L "$p" ]; then
        printf '%s\n' "$p" >> "$DELETE_LIST"
    fi
}

queue_unit_links() {
    name=$1
    find "$ROOT" \( -type d -name '*.wants' -o -type d -name '*.requires' \) -print > "$WORK/unit-dirs.txt" 2>/dev/null || true
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        queue_delete "$d/$name"
    done < "$WORK/unit-dirs.txt"
}

purge_unit() {
    name=$1
    queue_delete "$SYSTEMD/$name"
    queue_delete "$SYSTEMD/$name.d"
    queue_unit_links "$name"
}

ssh_file_records() {
    file=$1
    label=$2
    awk -v label="$label" '
        {
            raw=$0
            line=raw
            sub(/^[ \t]+/, "", line)
            if (line == "" || line ~ /^#/) next
            n=split(line, a, /[ \t=]+/)
            key=tolower(a[1])
            if (key == "include") next
            val=tolower(a[2])
            if (key=="passwordauthentication" || key=="permitrootlogin" || key=="kbdinteractiveauthentication" || key=="challengeresponseauthentication")
                print key "\t" val "\t" label ":" FNR ": " raw
        }
    ' "$file" >> "$WORK/ssh-records.txt"
}

ssh_audit() {
    main=$ROOT/etc/ssh/sshd_config
    : > "$WORK/ssh-records.txt"
    : > "$SSH_WARN"
    if [ ! -f "$main" ]; then
        echo "  Aviso: a configuração principal do sshd não existe em ROOT: $main (confirme manualmente a política SSH)"
        return 0
    fi
    include_line=$(awk '
        {
            line=$0
            sub(/^[ \t]+/, "", line)
            if (line ~ /^#/) next
            if (tolower(line) ~ /^include[ \t]+/ && index(line, "/etc/ssh/sshd_config.d/") > 0) {
                print NR
                exit
            }
        }
    ' "$main")
    if [ -n "$include_line" ]; then
        awk -v upto="$include_line" 'NR < upto' "$main" > "$WORK/ssh-main-before"
        awk -v from="$include_line" 'NR > from' "$main" > "$WORK/ssh-main-after"
    else
        cp "$main" "$WORK/ssh-main-before"
        : > "$WORK/ssh-main-after"
    fi
    ssh_file_records "$WORK/ssh-main-before" "sshd_config (antes de Include)"
    if [ -d "$ROOT/etc/ssh/sshd_config.d" ]; then
        find "$ROOT/etc/ssh/sshd_config.d" -maxdepth 1 -type f -name '*.conf' -print | sort > "$WORK/ssh-dropins.txt" || true
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            ssh_file_records "$f" "sshd_config.d/$(basename "$f")"
        done < "$WORK/ssh-dropins.txt"
    fi
    ssh_file_records "$WORK/ssh-main-after" "sshd_config (depois de Include)"
    # O sshd usa o primeiro valor encontrado para cada opção; somente drop-ins anteriores a 10-microduck.conf podem alterá-lo.
    awk -F'\t' '!seen[$1]++ && $2 != "no" { print $3 }' "$WORK/ssh-records.txt" > "$SSH_WARN"
}

clean_log_dir() {
    dir=$1
    [ -d "$dir" ] || return 0
    if [ -d "$dir/journal" ]; then
        find "$dir/journal" -mindepth 1 -maxdepth 1 -print > "$WORK/journal.txt" || true
        if [ -s "$WORK/journal.txt" ]; then
            echo "    Conteúdo a remover de $dir/journal:"
            sed 's/^/      - /' "$WORK/journal.txt"
            while IFS= read -r p; do
                remove_path "$p"
            done < "$WORK/journal.txt"
        fi
    fi
    find "$dir" -type f ! -path "$dir/journal/*" -print > "$WORK/log-files.txt" || true
    if [ -s "$WORK/log-files.txt" ]; then
        echo "    Esvaziando $(wc -l < "$WORK/log-files.txt" | tr -d '[:space:]') arquivos de log (mantendo a estrutura de diretórios): $dir"
        while IFS= read -r p; do
            truncate_regular_file "$p"
        done < "$WORK/log-files.txt"
    fi
}

[ "$#" -eq 4 ] || { usage; exit 2; }
ROOT_ARG=$1
PAYLOAD_ARG=$2
STUDIO_ARG=$3
OVERLAY_ARG=$4

[ -n "$ROOT_ARG" ] || fail "ROOT não pode estar vazio" "Informe o diretório rootfs já montado."
[ "$ROOT_ARG" != "/" ] || fail "ROOT não pode ser /" "Nunca opere na raiz da máquina que está executando o script."
[ -d "$ROOT_ARG" ] || fail "ROOT não é um diretório: $ROOT_ARG" "Monte primeiro a partição p1 da imagem."
ROOT=$(cd "$ROOT_ARG" && pwd -P)
case "$ROOT" in
    /|//|///) fail "ROOT resolve para o diretório raiz: $ROOT" "Use um diretório de montagem separado." ;;
esac

[ -f "$PAYLOAD_ARG" ] || fail "Arquivo payload não encontrado: $PAYLOAD_ARG" "Execute capture-payload.sh primeiro e confirme o caminho."
PAYLOAD=$(cd "$(dirname "$PAYLOAD_ARG")" && pwd -P)/$(basename "$PAYLOAD_ARG")
[ -d "$STUDIO_ARG" ] || fail "STUDIO_DIR não existe: $STUDIO_ARG" "Aponte para o diretório software/studio."
STUDIO=$(cd "$STUDIO_ARG" && pwd -P)
[ -d "$OVERLAY_ARG" ] || fail "OVERLAY_DIR não existe: $OVERLAY_ARG" "Aponte para o diretório overlay deste projeto."
OVERLAY=$(cd "$OVERLAY_ARG" && pwd -P)
HERE=$(cd "$(dirname "$0")" && pwd -P)
SOFTWARE_COMPONENTS_REQUESTED=0
if [ -n "${SOFTWARE_UPDATE_PACKAGE:-}${SOFTWARE_UPDATE_PUBLIC_KEY:-}${SOFTWARE_UPDATE_ENGINE:-}${VOICE_RESOURCES_DIR:-}" ]; then
    SOFTWARE_COMPONENTS_REQUESTED=1
    [ -f "${SOFTWARE_UPDATE_PACKAGE:-}" ] && [ -f "${SOFTWARE_UPDATE_PUBLIC_KEY:-}" ] && \
        [ -f "${SOFTWARE_UPDATE_ENGINE:-}" ] && [ -f "${VOICE_RESOURCES_DIR:-}/resources-manifest.json" ] || \
        fail "Entradas incompletas para os componentes de atualização de software" "Informe SOFTWARE_UPDATE_PACKAGE, SOFTWARE_UPDATE_PUBLIC_KEY, SOFTWARE_UPDATE_ENGINE e VOICE_RESOURCES_DIR; todos os arquivos devem existir."
    [ -f "$HERE/software_components.py" ] && [ -f "$HERE/../updater/bootstrap.py" ] || \
        fail "Falta o instalador compartilhado para os componentes de atualização de software" "Use o código-fonte congelado completo, incluindo software/updater e software/image."
fi
CAL_SRC=$HERE/calib/hd1910-calibration.option-a.toml

if [ -z "$IMAGE_VERSION" ]; then
    if command -v git >/dev/null 2>&1 && IMAGE_VERSION=$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null); then
        if [ -n "$(git -C "$HERE" status --porcelain -- . 2>/dev/null)" ]; then
            IMAGE_VERSION="$IMAGE_VERSION-dirty"
        fi
    else
        IMAGE_VERSION=desconhecido
    fi
fi

STEP="Verificação de argumentos e limites de ROOT"
echo "==> [0/9] Verificando argumentos e limites de ROOT"
MISSING_TOOLS=
for tool in tar sha256sum awk sed find grep cmp cp mkdir chmod chown install ln dirname basename readlink date mktemp rm mv sort tr wc stat openssl; do
    command -v "$tool" >/dev/null 2>&1 || MISSING_TOOLS="$MISSING_TOOLS $tool"
done
    [ -z "$MISSING_TOOLS" ] || fail "Comandos ausentes:$MISSING_TOOLS" "Instale coreutils, tar, grep e openssl no WSL/Debian e tente novamente."
PYTHON=$(find_python) || PYTHON=
[ -n "$PYTHON" ] || fail "Não foi encontrado python3 com tomllib (é necessário 3.11 ou superior)" "Instale python3 (>=3.11) e tente novamente."

[ -e "$ROOT/etc" ] || fail "ROOT não parece ser um rootfs: falta etc/" "Confirme se a partição p1 da R1 está montada."
[ -e "$ROOT/etc/systemd/system/basic.target.wants/armbian-resize-filesystem.service" ] || [ -L "$ROOT/etc/systemd/system/basic.target.wants/armbian-resize-filesystem.service" ] || fail "Falta basic.target.wants/armbian-resize-filesystem.service" "O sistema não expandirá automaticamente para o cartão inteiro no primeiro boot; confirme se a imagem base é Armbian R1."
[ ! -e "$ROOT/root/.no_rootfs_resize" ] || fail "Existe root/.no_rootfs_resize" "Esse marcador impede a expansão automática no primeiro boot; remova-o e tente novamente."

# Se um diretório de nível superior apontar para fora de ROOT, as cópias seguintes podem danificar /etc e outros diretórios do sistema hospedeiro.
for d in etc opt var home usr root tmp boot; do
    if [ -d "$ROOT/$d" ]; then
        real_d=$(cd "$ROOT/$d" && pwd -P)
        case "$real_d" in
            "$ROOT"|"$ROOT"/*) ;;
            *) fail "ROOT/$d aponta para fora de ROOT: $real_d" "Confira os links simbólicos da imagem e não continue." ;;
        esac
    fi
done

if [ -n "${STUDIO_VERSION:-}" ]; then
    :
else
    STUDIO_VERSION=
    VERSION_FILE=$STUDIO/studio/__init__.py
    if [ -f "$VERSION_FILE" ]; then
        parsed=$(awk -F'"' '/^[ \t]*__version__[ \t]*=/ {k=$1; sub(/[ \t]*=.*$/,"",k); gsub(/[ \t]/,"",k); if (k=="__version__") {print $2; exit}}' "$VERSION_FILE")
        if [ -n "$parsed" ]; then
            STUDIO_VERSION=$parsed
        fi
    fi
    if [ -z "$STUDIO_VERSION" ]; then
        STUDIO_VERSION="desconhecido"
    fi
fi

WORK=$(mktemp -d "${TMPDIR:-/tmp}/microduck-apply.XXXXXX") || fail "Não foi possível criar o diretório temporário" "Confira TMPDIR e o espaço em disco."
DEL_LOG=$WORK/deleted.txt
ADD_LOG=$WORK/added.txt
SSH_WARN=$WORK/ssh-warnings.txt
DELETE_LIST=$WORK/delete.list
: > "$DEL_LOG"
: > "$ADD_LOG"
: > "$SSH_WARN"
: > "$DELETE_LIST"
SYSTEMD=$ROOT/etc/systemd/system
STAGE=$WORK/payload
mkdir -p "$STAGE"

STEP="Verificação das quebras de linha em overlay e Studio"
echo "    Verificando se overlay, Studio/deploy e run.py contêm CR (quebras de linha do Windows)"
: > "$WORK/crlf.txt"
check_crlf_paths
if [ -s "$WORK/crlf.txt" ]; then
    echo "    Estes arquivos contêm CR (quebras de linha do Windows); os scripts podem não funcionar após a instalação na imagem:"
    sed 's/^/      - /' "$WORK/crlf.txt"
    fail "Há arquivos de texto com quebras CRLF em overlay ou Studio" "Clone novamente com git config core.autocrlf false ou execute dos2unix nesses arquivos."
fi

if [ -z "$PAYLOAD_SHA256" ]; then
    PAYLOAD_SHA256=$(sha256_of "$PAYLOAD") || fail "Não foi possível calcular o SHA-256 do payload: $PAYLOAD" "Confira as permissões do arquivo e o disco."
fi

STEP="Extração do payload e verificação individual de SHA-256"
echo "==> [1/9] Extraindo o payload e verificando cada SHA-256"
PAYLOAD_META=$WORK/payload-meta.tsv
: > "$PAYLOAD_META"
for rel in etc/robot/feetech-ft5/robotd.toml etc/robot/feetech-ft5/robotd.saved.toml; do
    if [ -f "$ROOT/$rel" ]; then
        meta=$(stat -c '%u %g %a' "$ROOT/$rel") || fail "Falha ao ler os atributos do arquivo da imagem base: $ROOT/$rel" "Confira se ROOT pode ser lido."
    else
        meta='0 0 644'
    fi
    printf '%s\t%s\n' "$rel" "$meta" >> "$PAYLOAD_META"
done

tar -xzf "$PAYLOAD" -C "$STAGE" --numeric-owner || fail "Falha ao extrair o payload" "Confira se o tgz está completo e se há espaço em disco suficiente."
[ -f "$STAGE/payload.json" ] || fail "payload.json não foi encontrado no payload" "Gere-o novamente com capture-payload.sh."
manifest_to_tsv "$STAGE/payload.json" "$WORK/files.tsv"
verify_manifest "$STAGE" "extração temporária"

if find "$STAGE" -type l -print | grep -q .; then
    echo "    Links simbólicos encontrados no payload:"
    find "$STAGE" -type l -print | sed 's/^/      - /'
    fail "Há links simbólicos no payload" "Gere o payload novamente; a imagem não aceita links simbólicos."
fi
if find "$STAGE" ! -type d ! -type f ! -path "$STAGE" -print | grep -q .; then
    echo "    Arquivos não regulares encontrados no payload:"
    find "$STAGE" ! -type d ! -type f ! -path "$STAGE" -print | sed 's/^/      - /'
    fail "Há arquivos não regulares no payload" "Gere o payload novamente."
fi
(
    cd "$STAGE"
    find . -type f ! -name payload.json | sed 's|^\./||' | sort
) > "$WORK/stage-files.txt"
awk -F'\t' '{print $1}' "$WORK/files.tsv" | sort -u > "$WORK/manifest-files.txt"
comm -13 "$WORK/manifest-files.txt" "$WORK/stage-files.txt" > "$WORK/extra-files.txt" || true
if [ -s "$WORK/extra-files.txt" ]; then
    echo "    Arquivos no payload que não constam no manifesto:"
    sed 's/^/      - /' "$WORK/extra-files.txt"
    fail "Há arquivos no payload que não constam no manifesto" "Não adicione arquivos manualmente ao tgz; gere-o novamente com capture-payload.sh."
fi

while IFS=$(printf '\t') read -r rel _expected _size; do
    [ -n "$rel" ] || continue
    safe_dir "$ROOT/$(dirname "$rel")"
done < "$WORK/files.tsv"

tar -cf "$WORK/payload.tar" -C "$STAGE" --numeric-owner --exclude='./payload.json' . || fail "Falha ao reempacotar o payload" "Confira o espaço disponível no diretório temporário."
( cd "$ROOT" && find . -type d ) | sort > "$WORK/dirs-before.txt"
tar -C "$ROOT" --no-overwrite-dir --numeric-owner -xpf "$WORK/payload.tar" || fail "Falha ao extrair o payload em ROOT" "Confira se ROOT permite gravação e se há espaço em disco suficiente."
( cd "$ROOT" && find . -type d ) | sort > "$WORK/dirs-after.txt"
comm -13 "$WORK/dirs-before.txt" "$WORK/dirs-after.txt" > "$WORK/dirs-new.txt" || true
while IFS= read -r d; do
    [ -n "$d" ] || continue
    chmod 0755 "$ROOT/$d" || fail "Não foi possível definir as permissões do novo diretório: $ROOT/$d" "Confira se ROOT permite gravação."
done < "$WORK/dirs-new.txt"
while IFS=$(printf '\t') read -r rel meta; do
    [ -n "$rel" ] || continue
    set -- $meta
    [ "$#" -eq 3 ] || fail "Formato incorreto dos atributos do arquivo da imagem base: $rel ($meta)" "Confira a saída de stat."
    uid=$1 gid=$2 mode=$3
    dst=$ROOT/$rel
    [ -f "$dst" ] || fail "Arquivo ausente após instalar o payload: $dst" "Confira se o payload está completo."
    chown "$uid:$gid" "$dst" || fail "Não foi possível definir o proprietário: $dst ($uid:$gid)" "Confira se o sistema de arquivos de ROOT permite chown."
    chmod "$mode" "$dst" || fail "Não foi possível definir as permissões: $dst ($mode)" "Confira as permissões do sistema de arquivos de ROOT."
done < "$PAYLOAD_META"
verify_manifest "$ROOT" "ROOT"
STEP="Geração do drop-in do modo de calibração de fábrica"
write_commissioning_dropin
STEP="Extração do payload e verificação individual de SHA-256"
cp -f "$STAGE/payload.json" "$WORK/payload.json"
ROBOTD_SHA=$(awk -F'"' '/"robotd_sha256"/ {for (i=1;i<=NF;i++) if ($i=="robotd_sha256") {print $(i+2); exit}}' "$WORK/payload.json")
if [ -z "$ROBOTD_SHA" ] && [ -f "$ROOT/opt/robot/feetech-ft5-r5/robotd" ]; then
    ROBOTD_SHA=$(sha256_of "$ROOT/opt/robot/feetech-ft5-r5/robotd")
fi
echo "    Arquivos do payload instalados em ROOT; todos os SHA-256 conferem."

STEP="Remoção dos serviços e identificadores do outro autor"
echo "==> [2/9] Removendo serviços e identificadores do outro autor"
purge_unit microduck-setup.service
queue_delete "$SYSTEMD/microduck-setup.service.wants"
queue_delete "$ROOT/usr/local/libexec/microduck-setup-portal.py"
queue_delete "$ROOT/usr/local/libexec/__pycache__"
queue_delete "$ROOT/usr/local/sbin/microduck-public-image"
queue_delete "$ROOT/etc/NetworkManager/system-connections/Microduck-Setup.nmconnection"

purge_unit gamesir-xboxd.service
queue_delete "$ROOT/usr/local/sbin/gamesir-xboxd"
queue_delete "$ROOT/usr/local/sbin/gamesir-xbox-status"
queue_delete "$ROOT/etc/udev/rules.d/70-gamesir-xbox-bridge.rules"
queue_delete "$ROOT/etc/modules-load.d/gamesir-xbox.conf"

queue_delete "$ROOT/etc/systemd/system/alsa-restore.service.d/microduck-audio.conf"
queue_delete "$ROOT/etc/systemd/system/alsa-state.service.d/microduck-audio.conf"
queue_delete "$ROOT/etc/sudoers.d/microduck-alsa-volume"
ASOUND_STATE=$ROOT/var/lib/alsa/asound.state
if [ -e "$ASOUND_STATE" ] || [ -L "$ASOUND_STATE" ]; then
    echo "    Estado de mixagem ALSA deixado pela imagem base (alsa-restore o usaria no boot para substituir o volume definido por aic3104-init): $(rel_path "$ASOUND_STATE")"
    cat "$ASOUND_STATE" 2>/dev/null | sed 's/^/      /' || true
    remove_path "$ASOUND_STATE"
fi

queue_delete "$ROOT/etc/microduck-v112-image.txt"
queue_delete "$ROOT/home/radxa/microduck-public-image.sh"
queue_delete "$ROOT/home/radxa/microduck-public-image-R5.sh"

STEP="Restrição da confiança do atualizador"
echo "    Restringindo a confiança do atualizador (somente assinaturas oficiais de release)"
set_updater_dev_keys_false "$ROOT/etc/robot/updater.toml"
prune_dev_keys "$ROOT/etc/robot/trusted_keys"
STEP="Remoção dos serviços e identificadores do outro autor"

if [ -d "$SYSTEMD/padd.service.d" ]; then
    find "$SYSTEMD/padd.service.d" -mindepth 1 -maxdepth 1 -print > "$WORK/padd-dropins.txt" || true
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        base=$(basename "$p")
        case "$base" in
            zzzz-replica-padd.conf|zzzz-replica-netpad.conf) ;;
            *) printf '%s\n' "$p" >> "$DELETE_LIST" ;;
        esac
    done < "$WORK/padd-dropins.txt"
fi

# Arquivos do outro autor deixados no diretório opt, exceto os itens permitidos pela lista de confiança.
OPT=$ROOT/opt/robot/feetech-ft5-r5
if [ -d "$OPT" ]; then
    for entry in "$OPT"/* "$OPT"/.[!.]* "$OPT"/..?*; do
        if [ ! -e "$entry" ] && [ ! -L "$entry" ]; then
            continue
        fi
        base=$(basename "$entry")
        case "$base" in
            robotd|padd|mediad|onnxruntime|models|roller|padd.service|padd-sysusers.conf|LICENSE)
                ;;
            *) printf '%s\n' "$entry" >> "$DELETE_LIST" ;;
        esac
    done
    # O payload é a referência para models/, roller/ e onnxruntime/: remove itens extras da imagem base (arquivos de treinamento e modelos antigos não usados).
    LC_ALL=C sort -u "$WORK/manifest-files.txt" > "$WORK/manifest-files.C.txt"
    for sub in models roller onnxruntime; do
        [ -d "$OPT/$sub" ] || continue
        ( cd "$ROOT" && find "opt/robot/feetech-ft5-r5/$sub" ! -type d -print ) | LC_ALL=C sort -u > "$WORK/opt-$sub.txt"
        LC_ALL=C comm -23 "$WORK/opt-$sub.txt" "$WORK/manifest-files.C.txt" | sed "s|^|$ROOT/|" >> "$DELETE_LIST"
    done
    # O 使用说明.md gerado pela ferramenta de exportação do autor do modelo não corresponde à imagem; remove mesmo se estiver no payload.
    for sub in models roller; do
        [ -d "$OPT/$sub" ] || continue
        find "$OPT/$sub" -type f -name '使用说明.md' -print >> "$DELETE_LIST" || true
    done
fi

sort -u "$DELETE_LIST" -o "$DELETE_LIST"
if [ -s "$DELETE_LIST" ]; then
    echo "    Os itens a seguir serão removidos ($(wc -l < "$DELETE_LIST" | tr -d '[:space:]')):"
    sed 's/^/      - /' "$DELETE_LIST"
    while IFS= read -r p; do
        remove_path "$p"
    done < "$DELETE_LIST"
else
    echo "    Nenhum serviço antigo ou arquivo para remover foi encontrado."
fi
for sub in models roller onnxruntime; do
    [ -d "$OPT/$sub" ] || continue
    # Remove diretórios vazios subindo na hierarquia até não restar nenhum.
    while :; do
        find "$OPT/$sub" -mindepth 1 -type d -empty -print > "$WORK/opt-empty.txt" || true
        [ -s "$WORK/opt-empty.txt" ] || break
        while IFS= read -r d; do
            [ -n "$d" ] || continue
            echo "  Removendo diretório vazio $d"
            add_del "$d"
            rmdir "$d" || fail "Falha ao remover o diretório vazio: $d" "Confira as permissões; ROOT pode estar somente para leitura."
        done < "$WORK/opt-empty.txt"
    done
done
for d in "$SYSTEMD/alsa-restore.service.d" "$SYSTEMD/alsa-state.service.d"; do
    if [ -d "$d" ] && [ -z "$(ls -A "$d" 2>/dev/null)" ]; then
            echo "  Removendo diretório vazio $d"
        add_del "$d"
        rmdir "$d" || true
    fi
done

EXTLINUX=$ROOT/boot/extlinux/extlinux.conf
if [ -f "$EXTLINUX" ]; then
    if grep -q '^menu title' "$EXTLINUX"; then
        safe_file "$EXTLINUX"
        awk 'BEGIN { done=0 }
             /^menu title/ && !done { print "menu title Microduck (Radxa U-Boot)"; done=1; next }
             { print }' "$EXTLINUX" > "$WORK/extlinux.new"
        cat "$WORK/extlinux.new" > "$EXTLINUX" || fail "Não foi possível regravar extlinux.conf" "Confira as permissões."
        echo "  Título do menu de extlinux.conf alterado para: Microduck (Radxa U-Boot)"
        add_add "$EXTLINUX"
    else
        echo "  Aviso: extlinux.conf não contém uma linha iniciada por menu title; o título do menu não foi alterado."
    fi
fi

STEP="Instalação do Studio e do assistente root"
echo "==> [3/9] Instalando o Studio e o assistente root"
RADXA_LINE=$(awk -F: '$1=="radxa" {print $3 ":" $4; exit}' "$ROOT/etc/passwd")
[ -n "$RADXA_LINE" ] || fail "O usuário radxa não consta em ROOT/etc/passwd" "Confirme se a imagem base é R1; o Studio precisa do UID/GID de radxa."
rewrite_radxa_gecos "$ROOT/etc/passwd"
rewrite_radxa_gecos "$ROOT/etc/passwd-"

STEP="Configuração da senha padrão de radxa"
SALT=$(openssl rand -hex 8) || fail "Não foi possível gerar o salt da senha de radxa" "Confira se openssl está disponível."
[ "${#SALT}" -eq 16 ] || fail "Comprimento incorreto do salt gerado: $SALT" "Confira a saída de openssl rand."
RADXA_HASH=$(openssl passwd -6 -salt "$SALT" microduck) || fail "Não foi possível gerar o hash da senha de radxa" "Confira se a versão do openssl aceita passwd -6."
case "$RADXA_HASH" in
    '$6$'*) ;;
    *) fail "O hash da senha de radxa não está no formato SHA-512 crypt: $RADXA_HASH" "Confira a saída de openssl passwd -6." ;;
esac
set_radxa_password_hash "$ROOT/etc/shadow" "$RADXA_HASH"
if [ -e "$ROOT/etc/shadow-" ] || [ -L "$ROOT/etc/shadow-" ]; then
    set_radxa_password_hash "$ROOT/etc/shadow-" "$RADXA_HASH"
else
    echo "    Aviso: a imagem base não contém etc/shadow-; somente etc/shadow foi alterado."
fi
STEP="Instalação do Studio e do assistente root"

STUDIO_DEST=$ROOT/home/radxa/studio-dev
if [ -e "$STUDIO_DEST" ] || [ -L "$STUDIO_DEST" ]; then
    echo "    Esvaziando o diretório existente $STUDIO_DEST"
    remove_path "$STUDIO_DEST"
fi
safe_dir "$STUDIO_DEST"
STUDIO_TAR=$WORK/studio.tar
STUDIO_MEMBERS=
for rel in run.py README.md LICENSE studio web deps deploy; do
    if [ -e "$STUDIO/$rel" ] || [ -L "$STUDIO/$rel" ]; then
        STUDIO_MEMBERS="$STUDIO_MEMBERS $rel"
    fi
done
[ -f "$STUDIO/run.py" ] || fail "run.py ausente em STUDIO_DIR: $STUDIO" "Confirme se aponta para software/studio."
[ -d "$STUDIO/deploy" ] || fail "deploy/ ausente em STUDIO_DIR: $STUDIO" "Confirme se os arquivos necessários para executar o Studio estão completos."
(
    cd "$STUDIO"
    # Não inclui cache de compilação na imagem: arquivos .pyc antigos podem ter sido gerados antes da tradução e seriam detectados pela verificação.
    tar -cf "$STUDIO_TAR" --numeric-owner --anchored \
        --exclude='*/__pycache__' --exclude='*.pyc' $STUDIO_MEMBERS
) || fail "Falha ao empacotar STUDIO_DIR" "Confira se STUDIO_DIR pode ser lido."
tar -xpf "$STUDIO_TAR" -C "$STUDIO_DEST" --numeric-owner || fail "Falha ao extrair o Studio" "Confira o espaço disponível em ROOT."
find "$STUDIO_DEST" -type d -exec chmod 0755 {} \; || fail "Não foi possível definir as permissões dos diretórios do Studio" "Confira se ROOT permite gravação."
find "$STUDIO_DEST" -type f -exec chmod 0644 {} \; || fail "Não foi possível definir as permissões dos arquivos do Studio" "Confira se ROOT permite gravação."
if ! chown -R "$RADXA_LINE" "$STUDIO_DEST" 2>/dev/null; then
    if [ "$(id -u)" -eq 0 ]; then
        fail "Não foi possível alterar o proprietário do Studio para radxa ($RADXA_LINE)" "Confirme se o rootfs montado aceita chown."
    fi
    echo "    Aviso: o processo não é root; o proprietário do Studio não foi definido (pode ser ignorado em testes; a compilação final definirá radxa)."
fi
add_add "$STUDIO_DEST"

put_file "$STUDIO/deploy/microduck-helper" "$ROOT/usr/local/sbin/microduck-helper" 0755
put_file "$STUDIO/deploy/zzzz-studio-bus.conf" "$SYSTEMD/robotd.service.d/zzzz-studio-bus.conf" 0644
put_file "$STUDIO/deploy/sudoers-microduck-studio" "$ROOT/etc/sudoers.d/microduck-studio" 0440
put_file "$STUDIO/deploy/microduck-studio.service" "$SYSTEMD/microduck-studio.service" 0644

if command -v visudo >/dev/null 2>&1; then
    if visudo -cf "$ROOT/etc/sudoers.d/microduck-studio" >/dev/null 2>&1; then
        echo "    O arquivo sudoers passou pela validação visudo -cf."
    else
        remove_path "$ROOT/etc/sudoers.d/microduck-studio"
        fail "Falha na validação do sudoers: $ROOT/etc/sudoers.d/microduck-studio" "Confira o conteúdo e as permissões de deploy/sudoers-microduck-studio."
    fi
else
    echo "    Aviso: visudo não está instalado nesta máquina; o sudoers não foi validado. Para a compilação final, instale sudo no WSL/Debian e execute novamente."
fi

make_enable_link /etc/systemd/system/microduck-studio.service \
    "$SYSTEMD/multi-user.target.wants/microduck-studio.service"

STEP="Instalação do OVERLAY e processamento de enable.list"
echo "==> [4/9] Instalando OVERLAY e processando enable.list"
if find "$OVERLAY" -type l -print | grep -q .; then
    find "$OVERLAY" -type l -print | sed 's/^/      - /'
    fail "Há links simbólicos em OVERLAY_DIR" "O overlay deve conter somente arquivos regulares; remova os links e tente novamente."
fi
: > "$WORK/overlay-modes.tsv"
if [ -f "$OVERLAY/modes.list" ]; then
    awk 'NF >= 2 && $1 !~ /^#/ { p=$1; sub(/^\.\//, "", p); print p "\t" $2 }' "$OVERLAY/modes.list" > "$WORK/overlay-modes.tsv"
    while IFS=$(printf '\t') read -r p m; do
        [ -n "$p" ] || continue
        case "$m" in
            [0-7][0-7][0-7]|[0-7][0-7][0-7][0-7]) ;;
            *) fail "Modo inválido em modes.list: $p $m" "Use três ou quatro dígitos octais, por exemplo 0755." ;;
        esac
    done < "$WORK/overlay-modes.tsv"
fi
(
    cd "$OVERLAY"
    find . -type f ! -path './enable.list' ! -path './modes.list' | sed 's|^\./||' | sort
) > "$WORK/overlay-files.txt"
while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    mode=$(awk -F'\t' -v r="$rel" '$1==r {print $2; exit}' "$WORK/overlay-modes.tsv")
    [ -n "$mode" ] || mode=0644
    dst=$ROOT/$rel
    safe_file "$dst"
    if [ "$(id -u)" -eq 0 ]; then
        install -D -m "$mode" -o 0 -g 0 "$OVERLAY/$rel" "$dst" || fail "Falha ao instalar o arquivo de overlay: $dst" "Confira as permissões e o espaço disponível."
    else
        install -D -m "$mode" "$OVERLAY/$rel" "$dst" || fail "Falha ao instalar o arquivo de overlay: $dst" "Confira as permissões e o espaço disponível."
    fi
    add_add "$dst"
done < "$WORK/overlay-files.txt"

if [ -f "$OVERLAY/enable.list" ]; then
    while IFS= read -r raw || [ -n "$raw" ]; do
        line=$(printf '%s' "$raw" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
        case "$line" in
            ""|\#*) continue ;;
        esac
        unit=$line
        unit=${unit#/}
        unit=${unit#etc/systemd/system/}
        case "$unit" in
            */*)
                echo "    Aviso: esta linha de enable.list não é um nome de unidade; ignorando: $line"
                continue
                ;;
        esac
        if [ -f "$SYSTEMD/$unit" ]; then
            target=/etc/systemd/system/$unit
        elif [ -f "$ROOT/usr/lib/systemd/system/$unit" ]; then
            target=/usr/lib/systemd/system/$unit
        else
            fail "A unidade especificada em enable.list não existe: $unit" "Confira o caminho correspondente em OVERLAY_DIR."
        fi
        make_enable_link "$target" "$SYSTEMD/multi-user.target.wants/$unit"
        echo "    Unidade habilitada: $unit"
    done < "$OVERLAY/enable.list"
else
    echo "    OVERLAY não contém enable.list."
fi

# Alias de sshd: systemd usa o caminho absoluto dentro da imagem, sem escapar dela.
if [ -f "$ROOT/usr/lib/systemd/system/ssh.service" ]; then
    make_enable_link /usr/lib/systemd/system/ssh.service "$SYSTEMD/sshd.service"
fi

STEP="Verificação de opções de segurança do sshd"
echo "==> [5/9] Verificando se a configuração do sshd reativa opções restritas"
ssh_audit
if [ -s "$SSH_WARN" ]; then
    echo "    Aviso: as configurações abaixo podem reativar o login por senha ou como root; elas não foram removidas automaticamente:"
    sed 's/^/      /' "$SSH_WARN"
else
    echo "    Nenhuma configuração foi encontrada reativando PasswordAuthentication / PermitRootLogin / KbdInteractiveAuthentication."
fi

STEP="Limpeza da identidade da máquina, logs, históricos e arquivos temporários"
echo "==> [6/9] Limpando identidade da máquina, logs, históricos e arquivos temporários"
safe_file "$ROOT/etc/machine-id"
: > "$ROOT/etc/machine-id"
chmod 0644 "$ROOT/etc/machine-id"
echo "  Arquivo esvaziado: $ROOT/etc/machine-id"
add_add "$ROOT/etc/machine-id"
remove_path "$ROOT/var/lib/dbus/machine-id"

if [ -d "$ROOT/etc/ssh" ]; then
    find "$ROOT/etc/ssh" -maxdepth 1 -name 'ssh_host_*' -print > "$WORK/ssh-host-keys.txt" || true
    if [ -s "$WORK/ssh-host-keys.txt" ]; then
        echo "    Chaves de host SSH a remover:"
        sed 's/^/      - /' "$WORK/ssh-host-keys.txt"
        while IFS= read -r p; do
            remove_path "$p"
        done < "$WORK/ssh-host-keys.txt"
    fi
fi

for f in root/.ssh/authorized_keys root/.ssh/known_hosts home/radxa/.ssh/authorized_keys home/radxa/.ssh/known_hosts; do
    remove_path "$ROOT/$f"
done

# Use somente em um cartão de validação próprio: grava DEV_AUTHORIZED_KEY (uma chave pública SSH em uma linha) no authorized_keys de radxa,
# permitindo corrigir problemas remotamente sem regravar o cartão. Não defina para imagens publicadas: isso deixaria uma porta de acesso aberta para todos os usuários.
DEV_KEY_NOTE=
if [ -n "${DEV_AUTHORIZED_KEY:-}" ]; then
    case "$DEV_AUTHORIZED_KEY" in
        "ssh-ed25519 "*|"ssh-rsa "*|"ecdsa-sha2-"*) ;;
        *) fail "DEV_AUTHORIZED_KEY não parece conter uma chave pública SSH em uma linha" "Informe uma chave pública começando com ssh-ed25519 (conteúdo de um arquivo .pub)." ;;
    esac
    case "$DEV_AUTHORIZED_KEY" in
        *"
"*) fail "DEV_AUTHORIZED_KEY deve conter apenas uma linha" "Informe somente uma chave pública." ;;
    esac
    RADXA_IDS=$(awk -F: '$1=="radxa" {print $3":"$4; exit}' "$ROOT/etc/passwd")
    [ -n "$RADXA_IDS" ] || fail "radxa não consta em ROOT/etc/passwd" "Confira a imagem base."
    SSH_DIR=$ROOT/home/radxa/.ssh
    safe_dir "$SSH_DIR"
    safe_file "$SSH_DIR/authorized_keys"
    printf '%s\n' "$DEV_AUTHORIZED_KEY" > "$SSH_DIR/authorized_keys" || fail "Não foi possível gravar em $SSH_DIR/authorized_keys" "Confira as permissões."
    chmod 0700 "$SSH_DIR" && chmod 0600 "$SSH_DIR/authorized_keys" || fail "Não foi possível definir as permissões de .ssh" "Confira o sistema de arquivos de ROOT."
    if [ "$(id -u)" -eq 0 ]; then
        chown "$RADXA_IDS" "$SSH_DIR" "$SSH_DIR/authorized_keys" || fail "Não foi possível definir o proprietário de .ssh como $RADXA_IDS" "Confira o sistema de arquivos de ROOT."
    fi
    add_add "$SSH_DIR/authorized_keys"
    DEV_KEY_NOTE="Cartão de validação: radxa inclui uma chave pública SSH de desenvolvimento (${DEV_AUTHORIZED_KEY##* }); imagens publicadas não a incluem."
    echo "    $DEV_KEY_NOTE"
fi

: > "$WORK/official-install-residue.txt"
if [ -d "$ROOT/home/radxa" ]; then
    find "$ROOT/home/radxa" -mindepth 1 -maxdepth 1 \
        \( -name 'microduck-official-init' -o -name 'microduck-official-install-*' \) \
        -print | LC_ALL=C sort > "$WORK/official-install-residue.txt" || true
fi
print_list "Resíduos de instalação do serviço oficial a remover" "$WORK/official-install-residue.txt"
while IFS= read -r p; do
    [ -n "$p" ] || continue
    remove_path "$p"
done < "$WORK/official-install-residue.txt"

clean_log_dir "$ROOT/var/log"
clean_log_dir "$ROOT/var/log.hdd"

remove_path "$ROOT/var/lib/systemd/random-seed"
for d in "$ROOT/var/lib/bluetooth" "$ROOT/var/lib/NetworkManager"; do
    if [ -d "$d" ]; then
        find "$d" -mindepth 1 -maxdepth 1 -print > "$WORK/state-clean.txt" || true
        if [ -s "$WORK/state-clean.txt" ]; then
            echo "    Esvaziando $d:"
            sed 's/^/      - /' "$WORK/state-clean.txt"
            while IFS= read -r p; do
                remove_path "$p"
            done < "$WORK/state-clean.txt"
        fi
    fi
done

for home in "$ROOT/root" "$ROOT/home/radxa"; do
    [ -d "$home" ] || continue
    for rel in .python_history .viminfo .lesshst .wget-hsts .cache; do
        remove_path "$home/$rel"
    done
    for p in "$home/.local/share/recently-used"*; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            remove_path "$p"
        fi
    done
done

remove_path "$ROOT/root/.bash_history"
remove_path "$ROOT/home/radxa/.bash_history"
remove_path "$ROOT/var/lib/microduck-helper"
if [ -d "$STUDIO_DEST" ]; then
    for p in "$STUDIO_DEST"/state* "$STUDIO_DEST"/logs*; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            remove_path "$p"
        fi
    done
fi

NM_DIR=$ROOT/etc/NetworkManager/system-connections
if [ -d "$NM_DIR" ]; then
    find "$NM_DIR" -mindepth 1 -maxdepth 1 -print > "$WORK/nm.txt" || true
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        base=$(basename "$p")
        overlay_nm=$OVERLAY/etc/NetworkManager/system-connections/$base
        if [ -e "$overlay_nm" ] || [ -L "$overlay_nm" ]; then
            echo "    Mantendo a conexão do NetworkManager fornecida pelo OVERLAY: $base"
        else
            remove_path "$p"
        fi
    done < "$WORK/nm.txt"
fi

if [ -d "$ROOT/tmp" ]; then
    find "$ROOT/tmp" -mindepth 1 -maxdepth 1 -print > "$WORK/tmp.txt" || true
    if [ -s "$WORK/tmp.txt" ]; then
        echo "    Esvaziando $ROOT/tmp"
        while IFS= read -r p; do
            remove_path "$p"
        done < "$WORK/tmp.txt"
    fi
fi
if [ -d "$ROOT/var/cache/apt/archives" ]; then
    find "$ROOT/var/cache/apt/archives" -maxdepth 1 -type f -name '*.deb' -print > "$WORK/debs.txt" || true
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        remove_path "$p"
    done < "$WORK/debs.txt"
fi

HWCLOCK=$ROOT/etc/fake-hwclock.data
HWCLOCK_EPOCH=0
if [ -f "$HWCLOCK" ] && grep -qE '^[0-9]+$' "$HWCLOCK" 2>/dev/null; then
    HWCLOCK_EPOCH=1
fi
if [ "$HWCLOCK_EPOCH" -eq 1 ]; then
    BUILD_TIME=$(date -u '+%s')
else
    BUILD_TIME=$(date -u '+%Y-%m-%d %H:%M:%S')
fi
safe_file "$HWCLOCK"
printf '%s\n' "$BUILD_TIME" > "$HWCLOCK" || fail "Não foi possível gravar em etc/fake-hwclock.data" "Confira as permissões."
chmod 0644 "$HWCLOCK"
echo "  Hora da compilação gravada em etc/fake-hwclock.data (UTC): $BUILD_TIME"
add_add "$HWCLOCK"

STEP="Instalação da calibração de fábrica e remoção de calibrações antigas"
echo "==> [7/9] Instalando a calibração de fábrica e removendo calibrações antigas"
[ -f "$CAL_SRC" ] || fail "Arquivo de origem da calibração ausente: $CAL_SRC" "Confirme se software/image/calib/hd1910-calibration.option-a.toml existe."
CAL_DIR=$ROOT/etc/robot/feetech-ft5
CAL_ACTIVE=$CAL_DIR/hd1910-calibration.toml
safe_dir "$CAL_DIR"
find "$CAL_DIR" -maxdepth 1 \( -name 'hd1910-calibration.*.toml' -o -name '*.bak-*' -o -name '*.previous' -o -name '*.tmp.*' \) -print | sort > "$WORK/cal-stale.txt" || true
print_list "Arquivos de calibração antigos e backups a remover" "$WORK/cal-stale.txt"
while IFS= read -r p; do
    [ -n "$p" ] || continue
    remove_path "$p"
done < "$WORK/cal-stale.txt"

ROBOT_GID=$(awk -F: '$1=="robot" {print $3; exit}' "$ROOT/etc/group")
[ -n "$ROBOT_GID" ] || fail "O grupo robot não consta em ROOT/etc/group" "Confirme se a imagem base contém o grupo robot do robotd."

safe_file "$CAL_ACTIVE"
cp -f "$CAL_SRC" "$CAL_ACTIVE" || fail "Não foi possível gravar o arquivo de calibração: $CAL_ACTIVE" "Confira as permissões e o espaço disponível."
chmod 0644 "$CAL_ACTIVE"
if [ "$(id -u)" -eq 0 ]; then
    chown 0:"$ROBOT_GID" "$CAL_ACTIVE" || fail "Não foi possível definir o proprietário do arquivo de calibração como root:robot ($ROBOT_GID)" "Confira o rootfs montado."
fi
add_add "$CAL_ACTIVE"
echo "    Calibração de fábrica instalada: $CAL_ACTIVE (root:robot, 0644)"

CAL_COUNT=$(find "$CAL_DIR" -maxdepth 1 -name 'hd1910-calibration*.toml' -print | wc -l | tr -d '[:space:]')
[ "$CAL_COUNT" = "1" ] || fail "Restaram $CAL_COUNT arquivos hd1910-calibration*.toml no diretório de calibração" "Remova os arquivos antigos e tente novamente."

"$PYTHON" - "$CAL_ACTIVE" <<'PY' || fail "Falha na autoverificação do arquivo de calibração: $CAL_ACTIVE" "Não continue; confira calib/hd1910-calibration.option-a.toml."
import sys
import tomllib

path = sys.argv[1]
with open(path, 'rb') as fh:
    data = tomllib.load(fh)

expected = [
    ('left_hip_yaw', 20), ('left_hip_roll', 21), ('left_hip_pitch', 22),
    ('left_knee', 23), ('left_ankle', 24),
    ('neck_pitch', 30), ('head_pitch', 31), ('head_yaw', 32),
    ('head_roll', 33), ('mouth', 34),
    ('right_hip_yaw', 10), ('right_hip_roll', 11), ('right_hip_pitch', 12),
    ('right_knee', 13), ('right_ankle', 14),
]
errors = []
top = set(data)
want_top = {'motion_enabled', 'imu_mount_verified', 'imu_mount_quat',
            'units_verified', 'current_ma_per_count', 'joints'}
if top != want_top:
    errors.append(f'Chaves de nível superior incorretas: extras {sorted(top - want_top)}, ausentes {sorted(want_top - top)}')
if data.get('motion_enabled') is not False:
    errors.append('motion_enabled deve ser false')
if data.get('imu_mount_verified') is not False:
    errors.append('imu_mount_verified deve ser false')
if data.get('units_verified') is not False:
    errors.append('units_verified deve ser false')
if data.get('current_ma_per_count') != 0.0:
    errors.append('current_ma_per_count deve ser 0.0')
if data.get('imu_mount_quat') != [0.7071067811865476, 0.0, 0.7071067811865476, 0.0]:
    errors.append('imu_mount_quat deve ser o quaternion oficial de +90 graus em torno de Y')
joints = data.get('joints')
if not isinstance(joints, list) or len(joints) != 15:
    errors.append('joints deve conter 15 itens')
else:
    for index, (name, joint_id) in enumerate(expected):
        joint = joints[index]
        if set(joint) != {'name', 'id', 'zero_raw', 'direction', 'calibrated'}:
            errors.append(f'{name}: chaves incorretas {sorted(joint)}')
            continue
        if joint['name'] != name:
            errors.append(f'A junta {index + 1} se chama {joint["name"]}; esperado: {name}')
        if joint['id'] != joint_id:
            errors.append(f'{name}: id é {joint["id"]}; esperado: {joint_id}')
        if joint['zero_raw'] != 2048:
            errors.append(f'{name}: zero_raw deve ser 2048')
        if joint['direction'] != -1:
            errors.append(f'{name}: direction deve ser -1')
        if joint['calibrated'] is not False:
            errors.append(f'{name}: calibrated deve ser false')
if errors:
    print('Falha na validação do arquivo de calibração:')
    for item in errors:
        print('  - ' + item)
    raise SystemExit(1)
PY

# A configuração [media] da imagem base oficial usa a câmera por padrão; sem uma câmera conectada, mediad não inicia e reinicia a cada 5 segundos.
# A imagem passa a usar a tela de teste por padrão; quem tiver câmera conectada pode mudar para "camera" e reiniciar mediad.
MEDIA_TOML=$ROOT/etc/robot/robotd.toml
[ -f "$MEDIA_TOML" ] || fail "Configuração oficial ausente: $MEDIA_TOML" "Confirme se a imagem base é R1-V112."
safe_file "$MEDIA_TOML"
awk 'BEGIN { sec=""; done=0 }
     /^\[/ { sec=$0 }
     sec=="[media]" && /^#? *source *=/ && !done {
         print "source = \"test\"   # Padrão da imagem réplica: inicia mesmo sem câmera. Com câmera conectada, altere para \"camera\" e execute sudo systemctl restart mediad"
         done=1; next
     }
     { print }
     END { if (!done) exit 3 }' "$MEDIA_TOML" > "$WORK/robotd-media.new" \
    || fail "Não foi encontrada uma linha source na seção [media] da configuração oficial: $MEDIA_TOML" "A imagem base mudou? Confira primeiro a seção [media]."
# Substitui o conteúdo sem trocar o arquivo; mantém o proprietário e as permissões.
cat "$WORK/robotd-media.new" > "$MEDIA_TOML" || fail "Não foi possível gravar em $MEDIA_TOML" "Confira as permissões e o espaço disponível."
echo "    source da seção [media] oficial alterado para \"test\" (inicia mesmo sem câmera)"

STEP="Geração da documentação de modelos e do manifesto da imagem"
echo "==> [8/9] Gerando a documentação dos modelos e o manifesto da imagem"
DOC_DIR=$ROOT/usr/share/doc/microduck
safe_dir "$DOC_DIR"
safe_file "$DOC_DIR/payload.json"
cp -f "$WORK/payload.json" "$DOC_DIR/payload.json" || fail "Não foi possível copiar payload.json" "Confira as permissões."
chmod 0644 "$DOC_DIR/payload.json"
add_add "$DOC_DIR/payload.json"

MODEL_LIST=$WORK/models.txt
{
    printf '%-58s %s\n' 'Diretório do modelo (relativo a /opt/robot/feetech-ft5-r5)' 'SHA-256 de policy.onnx'
    printf '%-58s %s\n' '----------------------------------------------------------' '------------------------------------------------'
    found=0
    : > "$WORK/model-paths.txt"
    for base in models roller; do
        [ -d "$ROOT/opt/robot/feetech-ft5-r5/$base" ] || continue
        find "$ROOT/opt/robot/feetech-ft5-r5/$base" -type f -name policy.onnx -print >> "$WORK/model-paths.txt" 2>/dev/null || true
    done
    if [ -s "$WORK/model-paths.txt" ]; then
        sort "$WORK/model-paths.txt" -o "$WORK/model-paths.txt"
        while IFS= read -r p; do
            [ -n "$p" ] || continue
            found=1
            d=$(dirname "$p")
            rel=${d#"$ROOT"/opt/robot/feetech-ft5-r5/}
            hash=$(sha256_of "$p")
            printf '%-58s %s\n' "$rel" "$hash"
        done < "$WORK/model-paths.txt"
    fi
    if [ "$found" -eq 0 ]; then
        echo "(nenhum policy.onnx encontrado)"
    fi
} > "$MODEL_LIST"

MODEL_DOC=$DOC_DIR/模型说明.txt
safe_file "$MODEL_DOC"
if [ -f "$MODEL_DOC" ] && grep -qx '@@MODEL_LIST@@' "$MODEL_DOC"; then
    awk -v listfile="$MODEL_LIST" '
        $0 == "@@MODEL_LIST@@" {
            while ((getline line < listfile) > 0) print line
            close(listfile)
            next
        }
        { print }
    ' "$MODEL_DOC" > "$WORK/model-doc.new"
    cat "$WORK/model-doc.new" > "$MODEL_DOC" || fail "Não foi possível atualizar a documentação dos modelos" "Confira as permissões."
else
    {
        echo ""
        echo "Manifesto de arquivos de modelo (gerado durante a compilação):"
        cat "$MODEL_LIST"
    } >> "$MODEL_DOC"
fi
chmod 0644 "$MODEL_DOC"

MANIFEST=$DOC_DIR/镜像清单.txt
TO_CONFIRM=$WORK/to-confirm.txt
: > "$TO_CONFIRM"
CONFIRM_HAS_FILE=0
UNCONFIRMED_ALLOWED=0
for rel in var/lib/robot/config; do
    p=$ROOT/$rel
    if [ -L "$p" ]; then
        printf '%s  link simbólico -> %s (não seguido; não é arquivo regular)\n' "$rel" "$(readlink "$p")" >> "$TO_CONFIRM"
    elif [ -d "$p" ]; then
        find "$p" -type f -print | LC_ALL=C sort > "$WORK/confirm-files.txt" || true
        if [ -s "$WORK/confirm-files.txt" ]; then
            while IFS= read -r file; do
                [ -n "$file" ] || continue
                file_rel=${file#"$ROOT"/}
                printf '%s  tamanho=%s  SHA-256=%s\n' "$file_rel" "$(size_of "$file")" "$(sha256_of "$file")" >> "$TO_CONFIRM"
            done < "$WORK/confirm-files.txt"
            CONFIRM_HAS_FILE=1
        else
            printf '%s  diretório vazio\n' "$rel" >> "$TO_CONFIRM"
        fi
    elif [ -f "$p" ]; then
        printf '%s  tamanho=%s  SHA-256=%s\n' "$rel" "$(size_of "$p")" "$(sha256_of "$p")" >> "$TO_CONFIRM"
        CONFIRM_HAS_FILE=1
    elif [ -e "$p" ]; then
        printf '%s  (não é arquivo regular; SHA-256 não calculado; não requer confirmação)\n' "$rel" >> "$TO_CONFIRM"
    fi
done
if [ -s "$TO_CONFIRM" ]; then
    echo "    Itens que aguardam confirmação manual (não foram removidos):"
    sed 's/^/      - /' "$TO_CONFIRM"
fi
if [ "$CONFIRM_HAS_FILE" -eq 1 ]; then
    if [ "$ALLOW_UNCONFIRMED" = "1" ]; then
        UNCONFIRMED_ALLOWED=1
        echo "    Atenção: ainda há arquivos regulares aguardando confirmação; liberados por ALLOW_UNCONFIRMED=1."
    else
        fail "Ainda há arquivos regulares que aguardam confirmação manual (veja acima)" "Confirme se contêm dados pessoais; se devem ser mantidos, execute novamente com ALLOW_UNCONFIRMED=1."
    fi
fi

safe_file "$MANIFEST"
{
    echo "Manifesto da imagem réplica do Microduck"
    echo "================================"
    echo "Data da compilação (UTC): $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "Nome do arquivo da imagem base: $BASE_IMG_NAME"
    echo "SHA-256 da imagem base: $BASE_IMG_SHA256"
    echo "SHA-256 do payload: $PAYLOAD_SHA256"
    echo "Versão do script de imagem: $IMAGE_VERSION"
    echo "SHA-256 do robotd do payload: $ROBOTD_SHA"
    echo "Versão do Studio: $STUDIO_VERSION"
    echo "O Studio inclui somente arquivos de execução (sem tests/dev/docs)."
    echo "Senha padrão de radxa: microduck (uso local ou via sudo após login com chave; altere com passwd no primeiro acesso)."
    [ -z "$DEV_KEY_NOTE" ] || echo "$DEV_KEY_NOTE"
    echo ""
    echo "Removidos (caminhos relativos à raiz da imagem)"
    echo "--------------------------------"
    if [ -s "$DEL_LOG" ]; then
        sort -u "$DEL_LOG"
    else
        echo "(nenhum)"
    fi
    echo ""
    echo "Adicionados / instalados (caminhos relativos à raiz da imagem)"
    echo "--------------------------------"
    if [ -s "$ADD_LOG" ]; then
        sort -u "$ADD_LOG"
    else
        echo "(nenhum)"
    fi
    echo ""
    echo "Aguardando confirmação manual (não removido automaticamente; confirme se há dados pessoais)"
    echo "--------------------------------"
    if [ -s "$TO_CONFIRM" ]; then
        cat "$TO_CONFIRM"
    else
        echo "(nenhum)"
    fi
    if [ "$UNCONFIRMED_ALLOWED" -eq 1 ]; then
        echo "Atenção: esta compilação liberou os arquivos regulares acima usando ALLOW_UNCONFIRMED=1."
    fi
    echo ""
    echo "Avisos de configuração SSH (não removidos automaticamente)"
    echo "--------------------------------"
    if [ -s "$SSH_WARN" ]; then
        while IFS= read -r line; do
            case "$line" in
                "$ROOT"/*) line=${line#"$ROOT"/} ;;
            esac
            echo "  $line"
        done < "$SSH_WARN"
    else
        echo "(nenhum)"
    fi
    echo ""
    echo "Licenças e informações dos modelos: arquivos 开源许可.txt, 第三方.txt e 模型说明.txt no mesmo diretório."
} > "$MANIFEST" || fail "Não foi possível gravar o manifesto da imagem" "Confira as permissões."
chmod 0644 "$MANIFEST"
if [ "$(id -u)" -eq 0 ]; then
    chown 0:0 "$MANIFEST" || fail "Não foi possível definir o proprietário do manifesto da imagem" "Confira o rootfs montado."
fi

STEP="Verificação de resíduos"
NAME_SCAN='kis''sqy'
echo "==> [9/9] Verificando resíduos (nome do autor terceiro, links quebrados e referências a itens removidos)"
SCAN_START=$(date +%s)
: > "$WORK/name-leak.txt"
# Examina todos os arquivos regulares em ROOT, inclusive binários (-a), sem diferenciar maiúsculas/minúsculas nem usar -w.
find "$ROOT" -type f -exec grep -ailE "$NAME_SCAN" {} + >> "$WORK/name-leak.txt" 2>/dev/null || true
LC_ALL=C sort -u "$WORK/name-leak.txt" -o "$WORK/name-leak.txt"
if [ -s "$WORK/name-leak.txt" ]; then
    EXCEPT=$ROOT/usr/share/doc/microduck/模型说明.txt
    grep -v -x -F "$EXCEPT" "$WORK/name-leak.txt" > "$WORK/name-leak-left.txt" || true
    if [ -s "$WORK/name-leak-left.txt" ]; then
        echo "    Arquivos que ainda contêm o nome do autor terceiro:"
        sed 's/^/      - /' "$WORK/name-leak-left.txt"
        fail "Ainda há ocorrências do nome do autor terceiro na imagem" "Limpe os arquivos listados acima ou adicione uma regra de remoção em apply-rootfs.sh."
    fi
fi
SCAN_END=$(date +%s)
echo "    Duração da busca pelo nome do autor terceiro: $((SCAN_END - SCAN_START)) segundos"

: > "$WORK/dangling.txt"
: > "$WORK/link-dirs.txt"
: > "$WORK/link-list.txt"
for d in "$ROOT/etc/systemd/system" "$ROOT/etc/udev/rules.d"; do
    [ -d "$d" ] && printf '%s\n' "$d" >> "$WORK/link-dirs.txt"
done
for d in "$ROOT"/etc/cron*; do
    { [ -e "$d" ] || [ -L "$d" ]; } && printf '%s\n' "$d" >> "$WORK/link-dirs.txt"
done
while IFS= read -r d; do
    [ -n "$d" ] || continue
    find "$d" -type l -print >> "$WORK/link-list.txt" 2>/dev/null || true
done < "$WORK/link-dirs.txt"
if [ -s "$WORK/link-list.txt" ]; then
    while IFS= read -r l; do
        [ -n "$l" ] || continue
        t=$(readlink "$l") || continue
        case "$t" in
            # Links criados por systemctl mask: /dev/null não existe no rootfs montado, mas o link não está quebrado.
            /dev/null) continue ;;
            /*) target="$ROOT$t" ;;
            *) target="$(dirname "$l")/$t" ;;
        esac
        if [ ! -e "$target" ]; then
            printf '%s -> %s\n' "$l" "$t" >> "$WORK/dangling.txt"
        fi
    done < "$WORK/link-list.txt"
fi
if [ -s "$WORK/dangling.txt" ]; then
    echo "    Links quebrados (resolvidos em relação a ROOT):"
    sed 's/^/      - /' "$WORK/dangling.txt"
    fail "Há links quebrados apontando para destinos inexistentes" "Remova os links acima ou limpe-os junto com as unidades/regras removidas."
fi

: > "$WORK/deleted-refs.txt"
if [ -s "$DELETE_LIST" ]; then
    "$PYTHON" - "$ROOT" "$DELETE_LIST" "$WORK/deleted-refs.txt" <<'PY' || fail "Falha ao verificar referências após a remoção" "Confira o erro do Python acima, corrija-o e tente novamente."
import sys
from pathlib import Path

root, delete_list, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
deleted = {line.strip() for line in delete_list.read_text(encoding="utf-8").splitlines() if line.strip()}
# Procura pelo caminho completo dentro da imagem (/opt/.../robotctl removido não deve corresponder a uma menção em /usr/local/bin/robotctl);
# somente unidades systemd removidas também são verificadas pelo nome (After=xxx.service usa o nome, não um caminho).
UNIT_SUFFIXES = (".service", ".socket", ".timer", ".path", ".target", ".mount")
needles = set()
for p in deleted:
    path = Path(p)
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        continue
    needles.add("/" + rel)
    if path.name.endswith(UNIT_SUFFIXES):
        needles.add(path.name)
bases = needles
dirs = [root / "etc/systemd", root / "etc/udev", root / "etc/sudoers.d"]
dirs += sorted((root / "etc").glob("cron*")) if (root / "etc").is_dir() else []
rows = set()
for directory in dirs:
    if not directory.exists():
        continue
    items = [directory] if directory.is_file() else list(directory.rglob("*"))
    for item in items:
        if not item.is_file() or item.is_symlink():
            continue
        if str(item) in deleted:
            continue
        try:
            data = item.read_bytes()
        except OSError:
            continue
        for base in bases:
            if base.encode("utf-8") in data:
                rows.add("%s ainda referencia %s" % (item.relative_to(root).as_posix(), base))
out_path.write_text("".join(row + "\n" for row in sorted(rows)), encoding="utf-8")
PY
fi
if [ -s "$WORK/deleted-refs.txt" ]; then
    echo "    Os seguintes arquivos ativos ainda referenciam nomes de arquivos removidos:"
    sed 's/^/      - /' "$WORK/deleted-refs.txt"
    fail "Nomes de arquivos removidos ainda são referenciados por arquivos ativos" "Altere as unidades/regras listadas ou remova os arquivos correspondentes e tente novamente."
fi

STEP="Verificação de artefatos de treinamento em opt"
echo "    Verificando se opt/robot/feetech-ft5-r5 ainda contém arquivos de treinamento e instruções do modelo"
find "$ROOT/opt/robot/feetech-ft5-r5" \
    \( -name export-data.zip -o -name 'training-*.json' -o -name upstream-params \
       -o -name '*.pt' -o -name '*.ckpt' -o -name '使用说明.md' \) \
    -print | LC_ALL=C sort > "$WORK/training-left.txt" 2>/dev/null || true
if [ -s "$WORK/training-left.txt" ]; then
    echo "    Ainda restam estes artefatos de treinamento:"
    sed 's/^/      - /' "$WORK/training-left.txt"
    fail "O diretório opt ainda contém artefatos de treinamento ou instruções do autor do modelo" "Remova esses arquivos do payload ou adicione uma regra de remoção em apply-rootfs.sh."
fi

STEP="Verificação dos arquivos oficiais de inicialização de áudio"
echo "    Verificando se os arquivos oficiais de inicialização da placa de som estão completos"
AIC_UNIT=$ROOT/etc/systemd/system/aic3104-init.service
AIC_WANTS=$ROOT/etc/systemd/system/multi-user.target.wants/aic3104-init.service
AIC_SCRIPT=$ROOT/usr/local/bin/aic3104-init.sh
[ -f "$AIC_UNIT" ] || fail "Unidade oficial de inicialização de áudio ausente: $(rel_path "$AIC_UNIT")" "aic3104-init.service é um arquivo oficial e não deve ser removido."
[ -e "$AIC_WANTS" ] || [ -L "$AIC_WANTS" ] || fail "Link de habilitação da inicialização oficial de áudio ausente: $(rel_path "$AIC_WANTS")" "multi-user.target.wants/aic3104-init.service deve ser mantido."
[ -f "$AIC_SCRIPT" ] || fail "Script oficial de inicialização de áudio ausente: $(rel_path "$AIC_SCRIPT")" "aic3104-init.sh é um arquivo oficial e não deve ser removido."
AIC_MODE=$(stat -c '%a' "$AIC_SCRIPT") || fail "Não foi possível ler as permissões do script oficial de inicialização de áudio: $(rel_path "$AIC_SCRIPT")" "Confira se ROOT pode ser lido."
if [ "$AIC_MODE" != "755" ]; then
    if [ -n "${MSYS:-}${CYGWIN:-}" ]; then
        echo "    Aviso: Git Bash não preserva os bits de permissão Unix (stat informou $AIC_MODE); o teste ignora a verificação exata de 0755."
    else
        fail "As permissões de aic3104-init.sh não são 0755: $AIC_MODE" "Execute chmod 0755 $(rel_path "$AIC_SCRIPT") e tente novamente; o arquivo oficial deve ser executável."
    fi
fi
echo "    Arquivos oficiais de inicialização de áudio mantidos: aic3104-init.service, link multi-user.target.wants e aic3104-init.sh (0755)"

if [ "$SOFTWARE_COMPONENTS_REQUESTED" -eq 1 ]; then
    STEP="Instalação do pacote assinado e dos recursos de voz offline"
    echo "==> Instalando os mesmos componentes assinados usados na atualização online"
    "$PYTHON" "$HERE/software_components.py" --root "$ROOT" \
        --package "$SOFTWARE_UPDATE_PACKAGE" --public-key "$SOFTWARE_UPDATE_PUBLIC_KEY" \
        --engine "$SOFTWARE_UPDATE_ENGINE" --resources "$VOICE_RESOURCES_DIR" \
        --engine-command-json "${SOFTWARE_UPDATE_ENGINE_COMMAND_JSON:-[]}" || \
        fail "Falha ao instalar componentes de software assinados" "Confira os erros de assinatura, hash dos recursos ou instalação do atualizador compartilhado; não ignore a validação."
    printf '\nAtualização de software e voz local: instalador compartilhado de componentes assinados; detalhes em software-components.json.\n' >> "$MANIFEST"
    printf '%s\n' 'Reconhecimento local de fala em mandarim para os comandos sentar/levantar: Vosk small-cn-0.22 (Apache-2.0); origem: https://alphacephei.com/vosk/models .' \
        'Dependências ARM64/cp313 e licenças mantidas em /opt/microduck/resources/asr-deps; hashes em resources-manifest.json.' \
        'Controle padrão por clique no botão R3; a escuta começa desativada. Quando ativada, reconhece comandos explícitos para sentar/levantar em mandarim; não é uma conversa livre com IA.' > "$DOC_DIR/speech-resources.txt"
    chmod 0644 "$DOC_DIR/speech-resources.txt"
fi

STEP="Concluído"
echo "==> Concluído"
echo "    ROOT：$ROOT"
echo "    Manifesto da imagem: $MANIFEST"
echo "    Registros removidos: $(wc -l < "$DEL_LOG" | tr -d '[:space:]'); registros adicionados: $(wc -l < "$ADD_LOG" | tr -d '[:space:]')."
if [ -s "$SSH_WARN" ]; then
    echo "    Atenção: há $(wc -l < "$SSH_WARN" | tr -d '[:space:]') avisos de configuração SSH; revise-os manualmente."
fi
