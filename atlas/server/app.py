"""ATLAS core HTTP/WS server (L3).

Serves the dark HUD (atlas/interface/web) and the API the dashboard + voice loop
consume. Both front-ends hit this same core, so conversation state is shared.

Run:  python -m atlas.server     (or ./atlas/run.sh)
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from .. import settings as cfg
from ..connectors.loader import ConnectorRegistry
from ..evaluation.logger import metrics_today
from ..memory.store import VaultStore
from ..orchestration.router import Router

WEB_DIR = cfg.ATLAS_DIR / "interface" / "web"
_START = time.monotonic()

app = FastAPI(title="ATLAS", version=__version__)

# Singletons (shared core state across voice + chat).
router = Router()
vault = VaultStore()
registry = ConnectorRegistry()


class ChatIn(BaseModel):
    text: str
    confirmed: bool = False
    session: str = "s_web"
    turn: int = 1


def _uptime() -> str:
    s = int(time.monotonic() - _START)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _ram() -> tuple[float, float]:
    """(used_gb, total_gb). Reads /proc/meminfo on Linux; falls back gracefully."""
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k.strip()] = int(v.strip().split()[0])  # kB
        total = info["MemTotal"] / 1024 / 1024
        avail = info.get("MemAvailable", info.get("MemFree", 0)) / 1024 / 1024
        return round(total - avail, 1), round(total, 1)
    except Exception:
        return 6.2, 24.0


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/status")
def status() -> dict[str, Any]:
    v = cfg.version()
    used, total = _ram()
    return {
        "version": v.get("version", __version__),
        "backend": router.backend,
        "uptime": _uptime(),
        "ram_used_gb": used,
        "ram_total_gb": total,
        "phase": v.get("phase", 1),
        "cycle": v.get("cycle", 0),
    }


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    return metrics_today()


@app.get("/api/memory/recent")
def memory_recent() -> list[dict[str, str]]:
    return vault.recent_activity()


@app.get("/api/upgrade")
def upgrade() -> dict[str, Any]:
    v = cfg.version()
    changes = v.get("status", "bootstrap")
    return {
        "last_cycle": f"Cycle {v.get('cycle', 0)}",
        "last_change": "Bootstrap complete — all 7 layers initialized."
        if v.get("cycle", 0) == 0 else changes,
        "next_cycle": v.get("next_scheduled_cycle", "nightly 03:00"),
        "approval": cfg.settings()["upgrade"].get("approval_level", "PATCH_only"),
    }


@app.get("/api/connectors")
def connectors() -> dict[str, Any]:
    return {"installed": list(registry.installed_ids()),
            "proposed": [c["id"] for c in registry.proposed()]}


@app.post("/api/chat")
def chat(body: ChatIn) -> dict[str, Any]:
    return router.chat(body.text, session=body.session, turn=body.turn,
                       confirmed=body.confirmed)


@app.post("/api/consolidate")
def consolidate() -> dict[str, Any]:
    return vault.consolidate()


# --------------------------------------------------------------------------- #
# WebSocket — live voice-pipeline state for the orb (text chat also works here)
# --------------------------------------------------------------------------- #
@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    await sock.send_json({"type": "state", "value": "idle"})
    try:
        while True:
            msg = await sock.receive_json()
            if msg.get("type") == "chat":
                await sock.send_json({"type": "state", "value": "thinking"})
                out = router.chat(msg.get("text", ""), channel="voice")
                await sock.send_json({"type": "reply", "value": out["reply"]})
                await sock.send_json({"type": "state", "value": "idle"})
            elif msg.get("type") == "state":
                await sock.send_json({"type": "state", "value": msg.get("value", "idle")})
    except WebSocketDisconnect:
        return


# --------------------------------------------------------------------------- #
# Static HUD (mounted last so /api/* wins)
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


@app.exception_handler(404)
def not_found(_req, _exc):  # noqa: ANN001
    return JSONResponse({"error": "not found"}, status_code=404)
