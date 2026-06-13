"""ATLAS core HTTP/WS server (L3).

Serves the dark HUD (atlas/interface/web) and the API the dashboard + voice loop
consume. Both front-ends hit this same core, so conversation state is shared.

Run:  python -m atlas.server     (or ./atlas/run.sh)
"""
from __future__ import annotations

import os
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from .. import settings as cfg
from ..connectors.loader import ConnectorRegistry
from ..evaluation.logger import log_event, metrics_today, recent_events
from ..memory.store import VaultStore
from ..orchestration.router import Router, keychain_secret
from ..scheduler import Scheduler

WEB_DIR = cfg.ATLAS_DIR / "interface" / "web"
_START = time.monotonic()

# Selectable Claude API models for the Settings dropdown (id -> label).
CLAUDE_MODELS = [
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8 (most capable)"},
    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6 (balanced)"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (fast)"},
    {"id": "claude-fable-5", "label": "Claude Fable 5"},
]

# Popular OpenRouter model ids — datalist suggestions only. The ↻ button live-
# fetches the authoritative list from the gateway (/api/openrouter/models).
OPENROUTER_MODELS = [
    "openai/gpt-5", "openai/gpt-5-mini", "anthropic/claude-sonnet-4.6",
    "anthropic/claude-opus-4.8", "google/gemini-2.5-pro", "google/gemini-2.5-flash",
    "deepseek/deepseek-chat", "meta-llama/llama-4-maverick",
]


def _scheduler_enabled() -> bool:
    # ATLAS_NO_SCHEDULER lets tests import the app without spawning the thread.
    return bool(cfg.settings().get("scheduler", {}).get("enabled")) and not os.environ.get("ATLAS_NO_SCHEDULER")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if _scheduler_enabled():
        scheduler.start()
    log_event("startup", {"mode": cfg.settings()["model"].get("mode", "api"),
                          "backend": router.backend,
                          "scheduler": _scheduler_enabled()})
    yield
    log_event("shutdown", {})
    scheduler.stop()


app = FastAPI(title="ATLAS", version=__version__, lifespan=lifespan)

# Singletons (shared core state across voice + chat).
router = Router()
vault = VaultStore()
registry = ConnectorRegistry()
scheduler = Scheduler()


class ChatIn(BaseModel):
    text: str
    confirmed: bool = False
    session: str = "s_web"
    turn: int = 1


def _uptime() -> str:
    s = int(time.monotonic() - _START)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _ram() -> tuple[float, float]:
    """(used_gb, total_gb) — LIVE, cross-platform via psutil (works on macOS).
    'used' = total − available (the standard pressure gauge), so it tracks real
    usage including the local model when loaded."""
    try:
        import psutil
        m = psutil.virtual_memory()
        return round((m.total - m.available) / 1024**3, 1), round(m.total / 1024**3, 1)
    except Exception:
        try:  # last-resort: total from sysconf, used unknown
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3
            return round(total * 0.5, 1), round(total, 1)
        except Exception:
            return 0.0, 0.0


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/status")
def status() -> dict[str, Any]:
    v = cfg.version()
    used, total = _ram()
    return {
        "version": v.get("version", __version__),
        "backend": router.status_label(),
        "routing": router.routing_enabled,
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


@app.get("/api/scheduler")
def scheduler_status() -> list[dict[str, Any]]:
    return scheduler.status()


@app.post("/api/scheduler/run/{job_id}")
def scheduler_run(job_id: str) -> dict[str, Any]:
    try:
        return scheduler.run_now(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no such job: {job_id}")


def _rebuild_core() -> None:
    """Rebuild the core singletons from the current settings/registry. Used by
    both /api/reload and a settings save, so a model-backend switch or newly
    approved connector applies without restarting the process."""
    global router, vault, registry, scheduler
    router = Router()
    vault = VaultStore()
    registry = ConnectorRegistry()
    scheduler.stop()
    scheduler = Scheduler()
    if _scheduler_enabled():
        scheduler.start()
    log_event("core_rebuilt", {"mode": cfg.settings()["model"].get("mode", "api"),
                               "backend": router.backend})


@app.post("/api/reload")
def reload_config() -> dict[str, Any]:
    """Re-read settings/registry and rebuild the core singletons."""
    cfg.reload_settings()
    _rebuild_core()
    log_event("reload", {"backend": router.backend})
    return {"reloaded": True, "backend": router.backend,
            "connectors_installed": list(registry.installed_ids())}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    """The live settings the Owner UI edits (settings.json, or the bundled
    example on a fresh clone)."""
    return cfg.settings()


def _dig(d: Any, *path: str) -> Any:
    for k in path:
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d


@app.put("/api/settings")
def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    """Persist the full settings object, then rebuild the core so it takes
    effect immediately. Writes settings.json (gitignored owner config).
    Logs exactly which model/mode fields changed so every change is trackable."""
    old = cfg.settings()
    try:
        cfg.save_settings(body)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _rebuild_core()
    tracked = {
        "mode": ("model", "mode"), "api_model": ("model", "backend"),
        "escalation_model": ("model", "escalation_model"),
        "openrouter_model": ("model", "openrouter", "model"),
        "local_model": ("model", "local", "model"),
        "max_tokens": ("model", "max_tokens"), "temperature": ("model", "temperature"),
        "owner_name": ("general", "owner_name"),
    }
    changes = {k: {"from": _dig(old, *p), "to": _dig(body, *p)}
               for k, p in tracked.items() if _dig(old, *p) != _dig(body, *p)}
    if changes:
        log_event("config_change", {"changes": changes, "backend": router.backend})
    return {"saved": True, "backend": router.backend, "changed": list(changes)}


@app.get("/api/conversation")
def conversation(limit: int = 30) -> list[dict[str, Any]]:
    """Recent saved conversation turns (oldest→newest) — powers chat history."""
    return vault.recent_turns(max(1, min(limit, 200)))


@app.get("/api/credits")
def credits() -> dict[str, Any]:
    """OpenRouter credit balance (remaining = granted − used). {available:false}
    if no key or unreachable."""
    import httpx
    orc = cfg.settings()["model"].get("openrouter") or {}
    key = os.environ.get(orc.get("api_key_env", "OPENROUTER_API_KEY")) \
        or keychain_secret(orc.get("api_key_ref"))
    if not key:
        return {"available": False}
    try:
        r = httpx.get("https://openrouter.ai/api/v1/credits",
                      headers={"Authorization": f"Bearer {key}"}, timeout=5.0)
        r.raise_for_status()
        d = r.json().get("data", {})
        total, usage = d.get("total_credits") or 0, d.get("total_usage") or 0
        return {"available": True, "remaining": round(total - usage, 2),
                "total": total, "usage": round(usage, 4)}
    except Exception:
        return {"available": False}


class OnboardIn(BaseModel):
    owner_name: str | None = None
    identity_approved: bool = False
    privacy_acknowledged: bool = False


@app.get("/api/onboarding/status")
def onboarding_status() -> dict[str, Any]:
    """First-run state + pre-flight info the wizard needs (python, backend, voice)."""
    import sys
    from ..interface.voice import tts as tts_engine
    s = cfg.settings()
    ob = s.get("onboarding") or {}
    return {
        "completed": bool(ob.get("completed")),
        "identity_approved": bool(ob.get("identity_approved")),
        "privacy_acknowledged": bool(ob.get("privacy_acknowledged")),
        "owner_name": (s.get("general") or {}).get("owner_name", "Owner"),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok": sys.version_info >= (3, 10),
        "has_backend": router.routing_enabled or router.backend != "offline",
        "voice": {"models_present": tts_engine.models_present(),
                  "lib": tts_engine.lib_present(), "downloading": tts_engine.downloading()},
    }


@app.post("/api/onboarding/complete")
def onboarding_complete(body: OnboardIn) -> dict[str, Any]:
    """Finalize first-run: persist consent flags, personalize owner.md, mark done."""
    s = cfg.settings()
    if body.owner_name:
        s.setdefault("general", {})["owner_name"] = body.owner_name.strip()
        vault.seed_owner(body.owner_name.strip())
    s["onboarding"] = {"completed": True,
                       "identity_approved": bool(body.identity_approved),
                       "privacy_acknowledged": bool(body.privacy_acknowledged)}
    cfg.save_settings(s)
    _rebuild_core()
    log_event("onboarding_complete", {"identity_approved": body.identity_approved,
                                      "privacy_acknowledged": body.privacy_acknowledged})
    return {"completed": True}


class ApproveIn(BaseModel):
    id: str


@app.post("/api/connectors/approve")
def approve_connector(body: ApproveIn) -> dict[str, Any]:
    """Move a proposed L7 connector to 'installed' in the registry."""
    import json as _json
    reg = cfg.registry()
    proposed = reg.get("proposed", [])
    found = next((c for c in proposed if c.get("id") == body.id), None)
    if not found:
        raise HTTPException(status_code=404, detail=f"no proposed connector '{body.id}'")
    reg["proposed"] = [c for c in proposed if c.get("id") != body.id]
    reg.setdefault("installed", []).append({**found, "status": "installed"})
    with cfg.REGISTRY_PATH.open("w", encoding="utf-8") as fh:
        _json.dump(reg, fh, indent=2)
        fh.write("\n")
    _rebuild_core()
    log_event("connector_approved", {"id": body.id})
    return {"approved": body.id, "installed": [c["id"] for c in reg["installed"]]}


@app.get("/api/update/check")
def update_check() -> dict[str, Any]:
    """How far behind GitHub the running code is, with a changelog."""
    from ..engine.updater import check
    d = check()
    d["supervised"] = bool(os.environ.get("ATLAS_SUPERVISED"))  # can we auto-restart?
    return d


@app.post("/api/update/apply")
def update_apply(confirm: bool = False) -> dict[str, Any]:
    """Apply the update (confirm=true). Backs up user state, applies atomically,
    health-checks, and auto-rolls-back on failure. Owner data is never touched."""
    from ..engine.updater import apply
    return apply(confirm=confirm)


@app.post("/api/restart")
def restart() -> dict[str, Any]:
    """Exit so the launchd supervisor respawns ATLAS with fresh code. Only works
    when supervised (ATLAS_SUPERVISED set by the LaunchAgent); otherwise the
    owner must restart manually."""
    import threading
    import time
    if not os.environ.get("ATLAS_SUPERVISED"):
        raise HTTPException(status_code=409,
                            detail="Not supervised — restart ATLAS manually (or install deploy/install-service.sh).")
    log_event("restart_requested", {})

    def _exit_soon():
        time.sleep(1.0)   # let this response flush first
        os._exit(0)       # KeepAlive=true → launchd restarts us with the new code

    threading.Thread(target=_exit_soon, daemon=True).start()
    return {"restarting": True}


@app.get("/api/voice/status")
def voice_status() -> dict[str, Any]:
    from ..interface.voice import tts as tts_engine
    return {"available": tts_engine.available(), "models_present": tts_engine.models_present(),
            "lib": tts_engine.lib_present(), "downloading": tts_engine.downloading(),
            "voices": tts_engine.VOICES}


@app.post("/api/tts/download")
def tts_download() -> dict[str, Any]:
    """Kick off a background download of the local-voice model files (~335MB)."""
    import threading
    from ..interface.voice import tts as tts_engine
    if tts_engine.models_present():
        return {"status": "present"}
    if tts_engine.downloading():
        return {"status": "downloading"}
    threading.Thread(target=tts_engine.download, daemon=True).start()
    return {"status": "started"}


class TTSIn(BaseModel):
    text: str
    voice: str | None = None


@app.post("/api/tts")
def tts(body: TTSIn) -> Response:
    """Synthesize speech locally (Kokoro). Returns WAV; 503 if the local voice
    isn't installed (the browser then falls back to its OS Web Speech voice)."""
    from ..interface.voice import tts as tts_engine
    cfg_voice = (cfg.settings().get("voice", {}) or {}).get("tts_voice", "kokoro:bm_george")
    voice = body.voice or (cfg_voice.split(":", 1)[1] if ":" in cfg_voice else "bm_george")
    wav = tts_engine.synth(body.text, voice=voice)
    if not wav:
        raise HTTPException(status_code=503, detail="local TTS unavailable")
    return Response(content=wav, media_type="audio/wav")


@app.get("/api/logs")
def logs(limit: int = 200) -> list[dict[str, Any]]:
    """Recent structured events for the Logs drawer (oldest→newest)."""
    return recent_events(max(1, min(limit, 1000)))


def _err_detail(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return {401: "Auth failed (401) — check your API key.",
            402: "Out of credits (402) — top up the account.",
            403: "Forbidden (403) — key lacks access to this model.",
            404: "Model not found (404) — pick another model.",
            429: "Rate limited (429) — try again shortly."}.get(
        status, f"{type(exc).__name__} — connection or model error.")


def _test_provider(provider: str) -> dict[str, Any]:
    import httpx
    m = cfg.settings()["model"]
    if provider == "api":
        key = os.environ.get(m.get("api_key_env", "ANTHROPIC_API_KEY")) or keychain_secret(m.get("api_key_ref"))
        if not key:
            return {"ok": False, "detail": "No Anthropic key — add one and retry."}
        if router._client is None:
            return {"ok": False, "detail": "Anthropic SDK unavailable (pip install anthropic) or key invalid."}
        try:
            router._client.messages.create(model=m.get("backend", "claude-sonnet-4-6"),
                                            max_tokens=1, messages=[{"role": "user", "content": "ping"}])
            return {"ok": True, "detail": "Claude reachable — full reasoning is live."}
        except Exception as exc:
            return {"ok": False, "detail": _err_detail(exc)}
    if provider == "openrouter":
        orc = m.get("openrouter") or {}
        key = os.environ.get(orc.get("api_key_env", "OPENROUTER_API_KEY")) or keychain_secret(orc.get("api_key_ref"))
        if not key:
            return {"ok": False, "detail": "No OpenRouter key — add one and retry."}
        try:
            r = httpx.get("https://openrouter.ai/api/v1/credits",
                          headers={"Authorization": f"Bearer {key}"}, timeout=6.0)
            if r.status_code == 401:
                return {"ok": False, "detail": "OpenRouter key rejected (401)."}
            r.raise_for_status()
            d = r.json().get("data", {})
            rem = round((d.get("total_credits") or 0) - (d.get("total_usage") or 0), 2)
            return {"ok": True, "detail": f"OpenRouter reachable — ${rem} credits."}
        except Exception as exc:
            return {"ok": False, "detail": _err_detail(exc)}
    if provider == "local":
        ep = ((m.get("local") or {}).get("endpoint") or "http://localhost:8080/v1").rstrip("/")
        try:
            r = httpx.get(f"{ep}/models", timeout=3.0)
            r.raise_for_status()
            return {"ok": True, "detail": f"Local server up — {len(r.json().get('data', []))} model(s) at {ep}."}
        except Exception:
            return {"ok": False, "detail": f"No local server at {ep} — start it with mlx_lm.server."}
    return {"ok": False, "detail": "Offline mode — no backend to test."}


@app.post("/api/backend/test")
def backend_test(provider: str | None = None) -> dict[str, Any]:
    """Test the backend is reachable, with a distinct error (auth / credits /
    model / network). Tests `provider` if given, else the active mode (or the
    routing 'daily' tier when routing is on)."""
    m = cfg.settings()["model"]
    if provider is None:
        provider = (((m.get("routing") or {}).get("tiers") or {}).get("daily", {}).get("provider", "openrouter")
                    if router.routing_enabled else m.get("mode", "api"))
    out = _test_provider(provider)
    out["backend"] = router.status_label()
    return out


@app.get("/api/models")
def models() -> dict[str, Any]:
    """Everything the Settings model picker needs: the selectable API models +
    whether a key is present, and a LIVE probe of the configured local server
    (its /v1/models is the 'fetch the local model that's running')."""
    import httpx
    m = cfg.settings()["model"]
    key_env = m.get("api_key_env", "ANTHROPIC_API_KEY")
    key_present = bool(os.environ.get(key_env) or keychain_secret(m.get("api_key_ref")))

    local_cfg = m.get("local") or {}
    endpoint = (local_cfg.get("endpoint") or "http://localhost:8080/v1").rstrip("/")
    running, local_models = False, []
    try:
        r = httpx.get(f"{endpoint}/models", timeout=1.5)
        if r.status_code == 200:
            running = True
            local_models = [d.get("id") for d in r.json().get("data", []) if d.get("id")]
    except Exception:
        pass

    orc = m.get("openrouter") or {}
    or_key_present = bool(os.environ.get(orc.get("api_key_env", "OPENROUTER_API_KEY"))
                          or keychain_secret(orc.get("api_key_ref")))

    return {
        "mode": m.get("mode", "api"),
        "api": {"models": CLAUDE_MODELS, "active": m.get("backend"),
                "escalation": m.get("escalation_model"), "key_present": key_present,
                "key_env": key_env},
        "openrouter": {"endpoint": orc.get("endpoint", "https://openrouter.ai/api/v1"),
                       "active": orc.get("model"), "key_present": or_key_present,
                       "key_env": orc.get("api_key_env", "OPENROUTER_API_KEY"),
                       "models": OPENROUTER_MODELS},
        "local": {"endpoint": endpoint, "active": local_cfg.get("model"),
                  "running": running, "models": local_models},
    }


@app.get("/api/openrouter/models")
def openrouter_models() -> dict[str, Any]:
    """Live-fetch the authoritative model list from the OpenRouter gateway
    (no key needed for the catalog) to populate the Settings suggestions."""
    import httpx
    orc = cfg.settings()["model"].get("openrouter") or {}
    ep = (orc.get("endpoint") or "https://openrouter.ai/api/v1").rstrip("/")
    try:
        r = httpx.get(f"{ep}/models", timeout=8.0)
        r.raise_for_status()
        ids = sorted(d.get("id") for d in r.json().get("data", []) if d.get("id"))
        return {"ok": True, "count": len(ids), "models": ids}
    except Exception as exc:
        return {"ok": False, "models": [], "detail": type(exc).__name__}


class SecretIn(BaseModel):
    key: str


def _secret_target(provider: str) -> tuple[str, str]:
    """(keychain_ref, env_var) for a provider's API key, from settings."""
    m = cfg.settings()["model"]
    if provider == "anthropic":
        return (m.get("api_key_ref", "keychain:atlas-anthropic-api-key"),
                m.get("api_key_env", "ANTHROPIC_API_KEY"))
    if provider == "openrouter":
        orc = m.get("openrouter") or {}
        return (orc.get("api_key_ref", "keychain:atlas-openrouter-api-key"),
                orc.get("api_key_env", "OPENROUTER_API_KEY"))
    raise HTTPException(status_code=404, detail=f"unknown secret provider: {provider}")


@app.post("/api/secret/{provider}")
def set_secret(provider: str, body: SecretIn) -> dict[str, Any]:
    """Store a provider's API key in the macOS Keychain (never in settings.json
    or git) AND activate it for this process, then rebuild the core so the
    backend comes online without a restart. provider ∈ {anthropic, openrouter}."""
    key = body.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="empty key")
    ref, env = _secret_target(provider)
    name = ref.split(":", 1)[1] if ref.startswith("keychain:") else f"atlas-{provider}-api-key"
    try:
        subprocess.run(["security", "add-generic-password", "-U", "-s", name,
                        "-a", "atlas", "-w", key], check=True, capture_output=True, timeout=10)
        stored = True
    except (OSError, subprocess.SubprocessError):
        stored = False  # off-macOS or no Keychain — still activate via env below
    os.environ[env] = key
    _rebuild_core()
    log_event("secret_set", {"provider": provider, "stored_in_keychain": stored})
    return {"stored_in_keychain": stored, "backend": router.backend}


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
