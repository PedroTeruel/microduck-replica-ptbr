#!/bin/sh
# Instala o assistente root do Studio (incluindo o comando fixo de sessão imu-recalibrate), o drop-in de proteção do robotd e uma regra do sudoers.
# Uso (no Microduck, dentro do diretório deploy): sudo sh install.sh [usuário que executa o Studio; padrão: radxa]
# Não reinicia o robotd nem altera /dev/ttyS2. Consulte INSTALL.md.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
user=${1:-radxa}

[ "$(id -u)" -eq 0 ] || { echo "É necessário ser root: sudo sh install.sh [usuário]" >&2; exit 1; }
case $user in
    *[!a-z0-9_-]*|"") echo "O nome de usuário só pode conter letras minúsculas, números, _ e -: $user" >&2; exit 1 ;;
esac
id "$user" >/dev/null 2>&1 || { echo "O usuário $user não existe" >&2; exit 1; }
[ -f /etc/systemd/system/robotd.service ] || echo "Aviso: /etc/systemd/system/robotd.service não existe; o drop-in não terá uma unidade para configurar" >&2

# 1. Assistente: root:root 0755; somente root pode gravar em cada nível do caminho.
install -o root -g root -m 0755 "$here/microduck-helper" /usr/local/sbin/microduck-helper
install -d -o root -g root -m 0755 /var/lib/microduck-helper /var/lib/microduck-helper/imu-recalibrate
for d in /usr /usr/local /usr/local/sbin; do
    if [ "$(stat -c %u "$d")" != 0 ]; then
        echo "Aviso: $d não pertence ao root; o assistente pode ser substituído" >&2
    fi
    if [ -n "$(find "$d" -maxdepth 0 -perm /022 2>/dev/null)" ]; then
        echo "Aviso: o grupo ou outros usuários podem gravar em $d; o assistente pode ser substituído" >&2
    fi
done

# 2. Drop-in de proteção do robotd (na etapa 1, somente a condição fica ativa; habilite Environment manualmente após validar a etapa 3).
install -d -o root -g root -m 0755 /etc/systemd/system/robotd.service.d
install -o root -g root -m 0644 "$here/zzzz-studio-bus.conf" /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf
systemctl daemon-reload

# 3. sudoers: autorize somente o caminho completo do assistente; valide com visudo -cf antes de instalar.
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
{
    echo "# Criado por Microduck Studio deploy/install.sh; autoriza somente o assistente root. Consulte deploy/INSTALL.md."
    echo "$user ALL=(root) NOPASSWD: /usr/local/sbin/microduck-helper"
} >"$tmp"
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/microduck-studio

# 4. Conferência
echo "--- Conferência ---"
systemctl show robotd -p DropInPaths
ls -l /usr/local/sbin/microduck-helper /etc/sudoers.d/microduck-studio /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf
echo "Teste como $user: echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope ; echo \$?   (o resultado deve ser 2: comando desconhecido)"
echo "Instalação concluída. O robotd não foi reiniciado."
