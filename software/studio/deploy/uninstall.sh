#!/bin/sh
# Remove o assistente root do Studio, o drop-in de proteção do robotd e a regra correspondente do sudoers.
# Uso: sudo sh uninstall.sh [--purge] (com --purge, também remove os registros em /var/lib/microduck-helper).
# A remoção é recusada enquanto o Studio estiver usando o barramento dos servos; devolva o controle pelo Studio ou reinicie.
set -eu
[ "$(id -u)" -eq 0 ] || { echo "É necessário ser root: sudo sh uninstall.sh" >&2; exit 1; }
if [ -e /run/microduck-helper/bus-held ]; then
    echo "O Studio está usando o barramento dos servos (/run/microduck-helper/bus-held existe); devolva o controle ao programa principal pelo Studio antes de remover" >&2
    exit 1
fi
if [ -e /etc/systemd/system/robotd.service.d/zzzzzz-studio-imu-recalibrate.conf ]; then
    echo "A sessão de repetição da calibração inicial da IMU ainda está ativa; conclua ou cancele no Studio antes de remover (a sessão e o backup serão preservados)" >&2
    exit 1
fi
if [ -e /var/lib/microduck-helper/imu-recalibrate/manifest.json ]; then
    /usr/bin/python3 -IS -c 'import json,sys;sys.exit(1 if json.load(open("/var/lib/microduck-helper/imu-recalibrate/manifest.json"))["active"] else 0)' || {
        echo "A sessão de calibração inicial da IMU não foi concluída ou não pode ser lida; restaure a sessão antes de remover" >&2
        exit 1
    }
fi
rm -f /etc/sudoers.d/microduck-studio
rm -f /etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf
systemctl daemon-reload
rm -f /usr/local/sbin/microduck-helper
systemctl stop microduck-bus-hold 2>/dev/null || true
rm -rf /run/microduck-helper /run/microduck-handover
if [ "${1:-}" = "--purge" ]; then rm -rf /var/lib/microduck-helper; fi
echo "Remoção concluída. O robotd não foi reiniciado; zzzz-studio-bus.conf não deve mais aparecer em systemctl show robotd -p DropInPaths."
