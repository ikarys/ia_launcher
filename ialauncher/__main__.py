"""Entry point: python -m ialauncher (see run.sh)."""
import os
import signal
import threading

from . import config
from .app import build
from .web.server import serve


def main():
    app = build()
    server = serve(app, config.LISTEN_HOST, config.LISTEN_PORT)

    def stop(*_):
        app.supervisor.shutdown()
        os._exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    app.supervisor.poll()
    threading.Thread(target=app.supervisor.run_forever, args=(config.POLL_S,), daemon=True).start()
    print(f"IA Launcher: http://{config.LISTEN_HOST}:{config.LISTEN_PORT}   (Ctrl+C to stop)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
