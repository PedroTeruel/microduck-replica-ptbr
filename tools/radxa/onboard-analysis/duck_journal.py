"""Copia em tempo real o log do sistema desta inicialização para o cartão e sincroniza
em disco a cada segundo (o /var/log do Armbian fica na memória e se perde se a energia
for cortada). Ignora a enxurrada de mensagens de estabilização da IMU, emitidas pelo
robotd a cada 20 ms durante a inicialização. Uso: python3 duck_journal.py arquivo_de_saida"""
import os, subprocess, sys, threading, time
out = sys.argv[1]
p = subprocess.Popen(['journalctl', '-b', '-f', '-n', 'all', '-o', 'short-precise', '--no-pager'],
                     stdout=subprocess.PIPE, text=True, errors='replace')
f = open(out, 'a'); lock = threading.Lock()
def syncer():
    while True:
        time.sleep(1)
        with lock:
            f.flush(); os.fsync(f.fileno())
threading.Thread(target=syncer, daemon=True).start()
for line in p.stdout:
    if 'settling' in line:
        continue
    with lock:
        f.write(line)
