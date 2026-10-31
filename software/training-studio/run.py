"""Start with: python run.py --demo --port 8093 (Python 3.12, stdlib only)."""
import argparse
import os
import signal
import sys
import threading
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from training_studio.config import StudioError  # noqa: E402
from training_studio.server import create_server  # noqa: E402
from training_studio.service import StudioService  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Microduck Training Studio · treinamento visual local")
    parser.add_argument("--demo", action="store_true", help="Demonstra processos filhos, curvas sintéticas e checkpoints de texto; não precisa de GPU")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--state-dir", type=Path, default=HERE / "state")
    parser.add_argument("--training-root", type=Path, default=HERE.parent / "training")
    parser.add_argument("--token", default=os.environ.get("STUDIO_ACCESS_TOKEN"), help="Obrigatório para escutar fora do loopback; a API usa X-Studio-Token")
    parser.add_argument("--open", action="store_true", help="Abre a interface no navegador")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("A porta precisa estar entre 0 e 65535")
    service = None
    server = None
    try:
        service = StudioService(args.state_dir, args.training_root, demo=args.demo)
        server = create_server(service, args.host, args.port, token=args.token)
        url_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        url = f"http://{url_host}:{server.server_address[1]}"
        print(f"Microduck Training Studio · {'DEMO: demonstração sintética' if args.demo else 'treinamento real'} · {url}", flush=True)
        print("Fechar o navegador não encerra o treinamento; fechar este serviço para os processos filhos que ele iniciou e mantém os checkpoints salvos.", flush=True)
        if args.token:
            print("Token de acesso habilitado; informe-o na interface (fica salvo na sessão atual do navegador).", flush=True)
        if args.open:
            webbrowser.open(url)

        def shutdown(_signum, _frame):
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)
        server.serve_forever(poll_interval=0.25)
    except StudioError as exc:
        parser.exit(2, f"{exc.error}\n")
    except OSError as exc:
        parser.exit(2, f"Falha ao iniciar o serviço: {exc}\n")
    finally:
        if server:
            server.server_close()
        if service:
            service.shutdown()


if __name__ == "__main__":
    main()
