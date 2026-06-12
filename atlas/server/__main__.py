"""Entry point: `python -m atlas.server`."""
from __future__ import annotations

import os

import uvicorn

from .. import settings as cfg


def main() -> None:
    port = int(cfg.settings().get("ui", {}).get("port", 8765))
    # Cheap mode check — the actual Router is built once inside the app module.
    key_env = cfg.settings()["model"].get("api_key_env", "ANTHROPIC_API_KEY")
    mode = "claude" if os.environ.get(key_env) else "offline/degraded"
    print(f"ATLAS core -> http://localhost:{port}  (mode: {mode})")
    uvicorn.run("atlas.server.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
