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
    parser = argparse.ArgumentParser(description="Microduck Training Studio · 本地可视化训练")
    parser.add_argument("--demo", action="store_true", help="演示子进程、合成曲线与文本检查点，无需 GPU")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8093)
    parser.add_argument("--state-dir", type=Path, default=HERE / "state")
    parser.add_argument("--training-root", type=Path, default=HERE.parent / "training")
    parser.add_argument("--token", default=os.environ.get("STUDIO_ACCESS_TOKEN"), help="非回环监听必填；API 使用 X-Studio-Token")
    parser.add_argument("--open", action="store_true", help="在浏览器中打开界面")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("端口必须在 0–65535 之间")
    service = None
    server = None
    try:
        service = StudioService(args.state_dir, args.training_root, demo=args.demo)
        server = create_server(service, args.host, args.port, token=args.token)
        url_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        url = f"http://{url_host}:{server.server_address[1]}"
        print(f"Microduck Training Studio · {'DEMO 合成演示' if args.demo else '真实训练'} · {url}", flush=True)
        print("关闭浏览器不会结束训练；关闭本服务会停止其拥有的子进程并保留已保存检查点。", flush=True)
        if args.token:
            print("已启用访问令牌；请在界面中输入令牌（保存在当前浏览器会话）。", flush=True)
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
        parser.exit(2, f"服务启动失败：{exc}\n")
    finally:
        if server:
            server.server_close()
        if service:
            service.shutdown()


if __name__ == "__main__":
    main()
