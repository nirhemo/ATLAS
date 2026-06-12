"""Entry point: `python -m atlas.server`."""
from __future__ import annotations

import uvicorn

from .. import settings as cfg


def main() -> None:
    port = int(cfg.settings().get("ui", {}).get("port", 8765))
    print(f"ATLAS core starting on http://localhost:{port}  (backend: ", end="")
    from ..orchestration.router import Router
    print(f"{Router().backend})")
    uvicorn.run("atlas.server.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
