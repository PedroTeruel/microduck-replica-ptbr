"""Inicia o Studio usando run.py (que adiciona deps/ ao caminho de busca):

    No robô:  python3 -I run.py --listen 0.0.0.0:8000
    No computador:  py -3.13 -I run.py --listen 127.0.0.1:8000 --robotd tcp:127.0.0.1:17001 --configd tcp:127.0.0.1:17002
              (inicie primeiro o robotd simulado: py -3.13 -I dev/fake_robotd.py)
    Autodiagnóstico somente leitura: python3 -I run.py --selfcheck
    Definir senha:  na página “Mais → Senha de acesso” ou execute como usuário radxa: python3 -I run.py set-password
"""
import argparse
import asyncio
import getpass
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def camera_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("A porta de sinalização de vídeo deve estar entre 1 e 65535")
    return port


def default_state_dir():
    if sys.platform.startswith("linux") and os.path.isdir("/var/lib/microduck-studio"):
        return "/var/lib/microduck-studio"
    return str(ROOT / "state")


def parse(argv=None):
    ap = argparse.ArgumentParser(prog="studio", description="Microduck Studio")
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "set-password"])
    ap.add_argument("--listen", default=None, help="Endereço e porta de escuta (padrão no robô: 0.0.0.0:8000; modo de bancada: 127.0.0.1:18080)")
    ap.add_argument("--robotd", default=None, help="Padrão: unix:/run/robotd.sock; não conecta no modo de bancada")
    ap.add_argument("--configd", default=None, help="Padrão: unix:/run/configd.sock; não conecta no modo de bancada")
    ap.add_argument("--tof", default="unix:/run/tofd/tof.sock", help="Endereço do serviço ToF somente leitura; none significa não conectar")
    ap.add_argument("--camera-socket", default="unix:/run/mediad/media.sock", help="Endereço para detectar o serviço da câmera em modo somente leitura; none significa não conectar")
    ap.add_argument("--camera-signaling-port", type=camera_port, default=8443, help="Porta de sinalização de vídeo do mediad local (padrão: 8443)")
    ap.add_argument("--bench", action="store_true",
                    help="Modo de bancada: sem firmware no controlador principal; use a placa de depuração Feetech ou um adaptador USB para TTL conectado ao computador para ajustar os servos. Não conecta ao programa principal; abre automaticamente a página dos servos no navegador, onde você seleciona a porta COM.")
    ap.add_argument("--state-dir", default=None, help="Diretório de senhas e sessões (padrão: ./state)")
    ap.add_argument("--log-dir", default=None, help="Diretório de logs (padrão: ./logs)")
    ap.add_argument("--web-dir", default=str(ROOT / "web"))
    ap.add_argument("--name", action="append", default=[], help="Nomes de host adicionais permitidos (pode informar vários)")
    ap.add_argument("--duck-label", default=None, help="Nome exibido na interface; se omitido, usa o nome do host (no robô, duck-xxxx)")
    ap.add_argument("--net-state", default="/run/microduck/net.json",
                    help="Arquivo de estado da configuração de rede escrito pelo netcheck (padrão: /run/microduck/net.json; se não existir, toda a seção de Wi-Fi fica oculta)")
    ap.add_argument("--duck-color", default="#0F7C80", help="Cor de identificação")
    ap.add_argument("--servo-port", default="/dev/ttyS2" if sys.platform.startswith("linux") else None,
                    help="Porta serial do barramento dos servos (no robô: /dev/ttyS2; no computador, informe algo como COM5 para um adaptador USB-TTL)")
    ap.add_argument("--servo-sim", action="store_true", help="Desenvolvimento: usa servos simulados na página dos servos (sem hardware conectado; o software simula 15 servos)")
    ap.add_argument("--selfcheck", action="store_true", help="Autodiagnóstico somente leitura: exibe a versão, consulta cada socket uma vez e encerra")
    ap.add_argument("--dev-autologin", action="store_true",
                    help="Desenvolvimento: solicitações locais dispensam login (permitido somente com --listen 127.0.0.1; usado em testes de captura de tela)")
    ap.add_argument("--dev-duck-root", default=None,
                    help="Desenvolvimento: o cartão de ajustes lê a árvore de arquivos simulada neste diretório (criada por dev/duckfs.py), sem ler /etc nem /opt. Só pode ser usado com um robotd simulado (tcp:)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse(argv)
    # Define os valores padrão primeiro: Robotd e o autodiagnóstico precisam deles mais adiante
    if a.listen is None:
        a.listen = "127.0.0.1:18080" if a.bench else "0.0.0.0:8000"
    if a.robotd is None:
        a.robotd = "none" if a.bench else "unix:/run/robotd.sock"
    if a.configd is None:
        a.configd = "none" if a.bench else "unix:/run/configd.sock"
    state_dir = a.state_dir or default_state_dir()
    log_dir = a.log_dir or str(ROOT / "logs")

    from .auth import Auth
    from .log import setup

    if a.cmd == "set-password":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise SystemExit("Não use sudo: execute como usuário radxa, caso contrário o Studio não conseguirá ler o arquivo de senha")
        pw = getpass.getpass("Nova senha de administrador (mínimo de 6 caracteres):")
        if pw != getpass.getpass("Digite novamente:"):
            raise SystemExit("As senhas não coincidem; nenhuma alteração foi feita.")
        Auth(state_dir).set_password(pw)
        print("Senha definida; todas as sessões anteriores foram encerradas.")
        return

    log = setup(log_dir)
    import starlette
    import uvicorn

    from .app import VERSION, build_app, precompress
    from .robotd import Robotd

    log.info(f"Dependências: starlette {starlette.__version__} · uvicorn {uvicorn.__version__} · em {Path(starlette.__file__).parent.parent}",
             cat="Sistema", dedup=False)
    rd = Robotd(a.robotd, a.configd, log)

    if a.selfcheck:
        async def check():
            r = await rd.selfcheck()
            await rd.stop()
            return r
        print(f"Studio {VERSION} · Python {sys.version.split()[0]}")
        for k, v in asyncio.run(check()).items():
            print(f"  {k:12s} {v}")
        return

    auth = Auth(state_dir, log)
    if not auth.has_password():
        log.info("Nenhuma senha definida: qualquer pessoa na mesma rede pode abrir a página (para adicionar uma senha: Mais → Senha de acesso)", cat="Sistema",
                 hint=f"Defina pela página ou execute como usuário radxa: python3 -I {ROOT / 'run.py'} set-password (não use sudo)")
    host, _, port = a.listen.rpartition(":")
    if a.dev_autologin and host != "127.0.0.1":
        raise SystemExit("--dev-autologin só pode ser usado com --listen 127.0.0.1:PORTA")
    if a.dev_autologin and (os.path.exists("/run/robotd.sock") or a.robotd.startswith("unix:")):
        # No robô, solicitações encaminhadas localmente (proxy reverso, túnel SSH) também chegam como 127.0.0.1; habilitar esta opção daria acesso de administrador a qualquer pessoa
        raise SystemExit("--dev-autologin só pode ser usada no computador com um robotd simulado; não habilite no robô")
    # A imagem não fixa o nome: se --duck-label não for informado, usa o nome do host (em uma placa nova, duck-xxxx na primeira inicialização)
    label = a.duck_label or socket.gethostname()
    duck = {"label": label, "short": label.split(" ")[-1], "color": a.duck_color}
    names = list(a.name)
    precompress(a.web_dir)
    from .servo import ServoSession, load_directions
    # A página dos servos está sempre disponível: no robô, a porta padrão é /dev/ttyS2; no computador, se --servo-port não for informado, selecione a porta serial na página (como no servo-web)
    servo = ServoSession(log, port=a.servo_port, sim=a.servo_sim, directions=load_directions(state_dir),
                         state_dir=state_dir)
    from .imu import ImuBackend
    imu = ImuBackend(rd, log, state_dir, root=a.dev_duck_root or "/")
    from .pad import default_pad
    # O modo de bancada (--bench) não se conecta ao programa principal e, portanto, não tem o backend da página do controle
    pad = None if a.bench else default_pad(log, configd_addr=a.configd, robotd_addr=a.robotd, state_dir=state_dir)
    from .onboard import Onboarding
    # Lista de configuração inicial no painel (registrada em onboarding.json no diretório state); no modo de bancada, sem conexão ao programa principal, a lista apenas informa “não verificado”
    onboard = Onboarding(state_dir, log)
    from .commit import CommitService
    # Etapa 3 da lista inicial, “Gravar no programa”: preparação, pré-visualização e gravação pelo assistente root (no computador, sem o assistente, apenas exibe a prévia e recusa a gravação)
    commit = CommitService(rd, log, state_dir)
    from .battery_svc import BatteryService
    # Estimativa de bateria (consulta a tensão dos servos em uma tabela; apenas aviso): configurações em battery-settings.json no diretório state
    battery = BatteryService(rd, log, state_dir, servo=servo, onboard=onboard)
    from .net import Net
    # Estado da configuração da rede: durante o desenvolvimento no computador ou sem o assistente instalado, conectar ao Wi-Fi não desliga o hotspot (uma mensagem é registrada no log)
    net = Net(a.configd, a.net_state, state_dir, log, dev_mode=bool(a.dev_autologin), port=int(port))
    # Modelos exibidos em “Execução e ajustes” no painel e na página de configurações (planos de ajuste T1–T3, somente leitura). Não são disponibilizados no modo de bancada, que não se conecta ao programa principal
    tune = None
    models = None
    if not a.bench:
        from .tune import Tune
        if a.dev_duck_root and not a.robotd.startswith("tcp:"):
            raise SystemExit("--dev-duck-root só pode ser usado no computador com um robotd simulado (--robotd tcp:...)")
        tune = Tune(rd, log, state_dir, root=a.dev_duck_root or "/", duck=duck)
        from .models import Models
        models = Models(rd, log, state_dir, tune=tune, root=a.dev_duck_root or "/")
    from .sensors import Sensors
    sensors = Sensors(log=log, root=a.dev_duck_root or "/", tof_addr=a.tof,
                      camera_signaling_port=a.camera_signaling_port, camera_addr=a.camera_socket)
    app = build_app(auth=auth, robotd=rd, log=log, web_dir=a.web_dir, duck=duck, names=names, state_dir=state_dir,
                    dev_autologin=a.dev_autologin, servo=servo, imu=imu, pad=pad, onboard=onboard, battery=battery,
                    tune=tune, net=net, commit=commit, models=models, sensors=sensors)
    log.info(f"Endereço da interface: http://{host if host not in ('0.0.0.0', '') else '<IP do robô>'}:{port}/", cat="Sistema", dedup=False)
    if a.bench:
        import threading
        import webbrowser
        url = f"http://{host or '127.0.0.1'}:{port}/#/servos"
        log.info(f"Modo de bancada: sem conexão ao programa principal; abrindo {url} no navegador. Selecione a porta COM na página dos servos para conectar", cat="Sistema", dedup=False)
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    from .ws_protocol import MusicWebSocketProtocol
    uvicorn.run(app, host=host or "0.0.0.0", port=int(port), ws=MusicWebSocketProtocol, http="h11", lifespan="on",
                log_level="warning", server_header=False, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
