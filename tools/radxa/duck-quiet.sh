#!/bin/bash
# Resfriamento da placa: identifica as fontes de calor, registra a curva de temperatura e desativa serviços desnecessários durante a marcha (restauração em um comando).
#   sudo bash duck-quiet.sh status                 # temperatura, frequência, processos com maior uso de CPU e estado dos serviços
#   sudo bash duck-quiet.sh measure 120 ocioso     # registra a cada 5 s durante 120 s, com a etiqueta “ocioso”
#   sudo bash duck-quiet.sh quiet                  # desativa serviços da lista QUIET iniciados automaticamente e registra o estado original
#   sudo bash duck-quiet.sh restore                # restaura os serviços desativados conforme o registro
#
# Motivação: após montar o conjunto kissqy completo na primeira unidade em 2026-10-12, a placa atingiu 85–92 °C e a CPU ficou travada na frequência mínima de 408 MHz,
# atrasando a resposta do joystick web. Sem câmera conectada, mediad reiniciava continuamente após falhas, e a varredura do GStreamer ocupava um núcleo.
# Para caminhar, bastam robotd (controle), padd e controle web (joystick), SSH e rede.
# Registros: /var/log/duck-quiet/<data>.log (com categoria e nível); curva térmica: /var/log/duck-quiet/thermal-<hora>-<etiqueta>.csv
set -euo pipefail
export LC_ALL=C.UTF-8

# Serviços desnecessários durante a marcha. Bluetooth (bluetooth.service) não está na lista padrão: será necessário ao conectar um controle Bluetooth.
QUIET=(mediad tofd btd configd gamesir-xboxd updaterd robot-boot-check.timer)
STATE=/var/lib/duck-quiet/disabled.txt
LOGDIR=/var/log/duck-quiet
mkdir -p "$LOGDIR" "$(dirname "$STATE")"
LOG="$LOGDIR/$(date +%F).log"
log(){ printf '%s [%s][%s] %s\n' "$(date '+%F %T')" "$1" "$2" "$3" | tee -a "$LOG" >&2; }
[ "$(id -u)" = 0 ] || { echo "É necessário ser root: sudo bash $0 ..."; exit 1; }

temp_c(){ awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp; }
freq_mhz(){ awk '{printf "%d", $1/1000}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq; }
unit_name(){ case "$1" in *.*) echo "$1" ;; *) echo "$1.service" ;; esac; }

status(){
  log temperatura INFO "CPU $(temp_c)°C, frequência $(freq_mhz) MHz (408 = mínimo, sob limitação térmica)"
  log carga INFO "Carga em 1/5/15 minutos: $(cut -d' ' -f1-3 /proc/loadavg)"
  # Faz duas coletas e usa a segunda; a primeira representa a média desde a inicialização.
  top -b -n 2 -d 2 -o %CPU | awk '/^top/{n++} n==2' | sed -n '7,14p' | while read -r line; do log processo INFO "$line"; done
  for u in robotd padd microduck-webpad.socket "${QUIET[@]}" bluetooth; do
    n=$(unit_name "$u")
    # is-enabled também retorna código diferente de zero para disabled; evite fallback com ||, que acrescentaria “ausente” após “disabled”.
    en=$(systemctl is-enabled "$n" 2>/dev/null || true); [ -n "$en" ] || en=ausente
    log serviço INFO "$(printf '%-24s inicialização automática=%-8s estado atual=%s' "$n" "$en" "$(systemctl is-active "$n" 2>/dev/null || true)")"
  done
}

measure(){
  local secs="${1:-120}" label="${2:-sem-nome}" out
  out="$LOGDIR/thermal-$(date +%Y%m%d-%H%M%S)-${label}.csv"
  echo "segundos,temperatura_C,frequencia_MHz,carga_1_minuto" > "$out"
  log medição INFO "Início: $label, $secs s, amostra a cada 5 s → $out"
  local t=0
  while [ "$t" -le "$secs" ]; do
    echo "$t,$(temp_c),$(freq_mhz),$(cut -d' ' -f1 /proc/loadavg)" >> "$out"
    sleep 5; t=$((t + 5))
  done
  awk -F, 'NR>1 {n++; s+=$2; if($2>mx)mx=$2; if(mn==""||$2<mn)mn=$2; if($3<=408)low++}
           END {printf "Temperatura: mínima %.1f / média %.1f / máxima %.1f °C; %d/%d amostras a 408 MHz\n", mn, s/n, mx, low, n}' "$out" \
    | while read -r line; do log medição INFO "$label: $line"; done
}

quiet(){
  [ -f "$STATE" ] && { log serviço WARN "Já existe um registro de desativação em $STATE; execute restore antes de quiet para não sobrescrevê-lo"; exit 1; }
  : > "$STATE"
  for u in "${QUIET[@]}"; do
    n=$(unit_name "$u")
    if [ "$(systemctl is-enabled "$n" 2>/dev/null || true)" = enabled ]; then
      systemctl disable --now "$n" >/dev/null 2>&1 && { echo "$n" >> "$STATE"; log serviço INFO "Desativado: $n"; } \
        || log serviço ERROR "Falha ao desativar: $n"
    else
      systemctl stop "$n" >/dev/null 2>&1 || true
      log serviço INFO "Não iniciava automaticamente; apenas interrompido: $n"
    fi
  done
  log serviço INFO "Registro salvo em $STATE; para restaurar: sudo bash $0 restore"
}

restore(){
  [ -f "$STATE" ] || { log serviço WARN "Não há registro de desativação; nada precisa ser restaurado"; exit 0; }
  while read -r n; do
    [ -n "$n" ] || continue
    systemctl enable --now "$n" >/dev/null 2>&1 && log serviço INFO "Restaurado: $n" || log serviço ERROR "Falha ao restaurar: $n"
  done < "$STATE"
  mv "$STATE" "$STATE.restored-$(date +%Y%m%d-%H%M%S)"
}

case "${1:-status}" in
  status) status ;;
  measure) measure "${2:-120}" "${3:-sem-nome}" ;;
  quiet) quiet ;;
  restore) restore ;;
  *) echo "Uso: sudo bash $0 status | measure [segundos] [etiqueta] | quiet | restore"; exit 1 ;;
esac
