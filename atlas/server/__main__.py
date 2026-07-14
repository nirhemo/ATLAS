"""Entry point: `python -m atlas.server` (and the frozen Tauri sidecar).

Sidecar contract (Phase 0): accepts `--port N` (or `--port 0`/none → pick a free
port), binds 127.0.0.1 only, and prints `ATLAS_READY <port>` on stdout once uvicorn
is serving. The Tauri shell reads that line, then points its webview at the port.
"""
from __future__ import annotations

import argparse
import os
import socket
import threading

import uvicorn

from .. import settings as cfg


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _announce_when_ready(server: "uvicorn.Server", port: int) -> None:
    """Print the readiness line once the server is actually accepting requests, so
    a supervisor (Tauri) can gate the webview on it instead of racing startup."""
    import time
    for _ in range(600):                    # up to ~60s
        if getattr(server, "started", False):
            print(f"ATLAS_READY {port}", flush=True)
            return
        time.sleep(0.1)


def main() -> None:
    ap = argparse.ArgumentParser(prog="atlas.server", add_help=True)
    ap.add_argument("--port", type=int, default=None,
                    help="port to bind (0 or omitted → a free port, printed on stdout)")
    ap.add_argument("--host", default="127.0.0.1")
    args, _ = ap.parse_known_args()

    if args.port is None:                       # omitted → settings port (or a free one)
        port = int(cfg.settings().get("ui", {}).get("port", 8765) or 0) or _free_port()
    elif args.port == 0:                        # explicit 0 → pick a free port
        port = _free_port()
    else:
        port = args.port

    key_env = cfg.settings()["model"].get("api_key_env", "ANTHROPIC_API_KEY")
    mode = "claude" if os.environ.get(key_env) else "offline/degraded"
    print(f"ATLAS core -> http://{args.host}:{port}  (mode: {mode})", flush=True)

    config = uvicorn.Config("atlas.server.app:app", host=args.host, port=port, reload=False)
    server = uvicorn.Server(config)
    threading.Thread(target=_announce_when_ready, args=(server, port), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
