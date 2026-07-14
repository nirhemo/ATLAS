"""L3/L6 smoke: the core boots, serves the HUD + API, and chats in offline mode."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

# Force offline mode so the suite never makes a network call — independent of
# the owner's live settings.json (which may select api/local mode).
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["ATLAS_FORCE_OFFLINE"] = "1"
# Don't spawn the scheduler thread during tests.
os.environ["ATLAS_NO_SCHEDULER"] = "1"

from atlas.server.app import app  # noqa: E402

client = TestClient(app)


def test_status_ok():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    assert body["backend"] == "offline"        # no API key in CI
    assert body["ram_total_gb"] > 0


def test_version_prefers_git_tags_with_fallback():
    # The displayed version is git-tag derived when available, else VERSION.json.
    from atlas import settings as cfg
    v = cfg.version()
    assert isinstance(v.get("version"), str) and v["version"]   # always non-empty
    gv = cfg.git_version()
    assert gv is None or isinstance(gv, str)                    # describe string or fallback
    if gv:
        assert v["version"] == gv.lstrip("v")


def test_metrics_shape():
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert "latency_ms" in r.json()


def test_hud_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "ATLAS" in r.text


def test_chat_offline_time():
    r = client.post("/api/chat", json={"text": "what time is it?"})
    assert r.status_code == 200
    body = r.json()
    assert body["backend"] == "offline"
    assert "get_time" in body["tools_used"]


def test_chat_offline_recall(tmp_path):
    # The seeded vault has an Owner note; offline recall should find it.
    r = client.post("/api/chat", json={"text": "what is my name?"})
    assert r.status_code == 200
    assert r.json()["reply"]


def test_chat_remember_preserves_fact_with_leading_space():
    # Regression: leading whitespace used to desync the match offset and garble
    # the remembered fact. The reply should confirm, not crash or truncate.
    # Fixture is deliberately non-sensitive — never use real personal data here.
    r = client.post("/api/chat", json={"text": "  remember that I prefer tea over coffee"})
    assert r.status_code == 200
    assert "remember" in r.json()["tools_used"]


def test_connectors_endpoint():
    r = client.get("/api/connectors")
    assert r.status_code == 200
    assert "web" in r.json()["installed"]   # connector approvals are per-user; web ships installed by default


def test_scheduler_endpoint_lists_jobs():
    r = client.get("/api/scheduler")
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()}
    assert {"consolidate", "health_report", "episodic_purge", "upgrade_cycle"} <= ids


def test_scheduler_run_unknown_job_404():
    r = client.post("/api/scheduler/run/ghost")
    assert r.status_code == 404


def test_voice_ws_handshake_reports_no_native_audio():
    # Phase 1 seam: /voice/ws exists and handshakes, but advertises audio=False so
    # the HUD keeps its browser Web Speech provider until the native service lands.
    with client.websocket_connect("/voice/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        caps = ws.receive_json()
        assert caps["type"] == "capabilities" and caps["audio"] is False
        assert ws.receive_json() == {"type": "ready", "audio": False}
        assert ws.receive_json() == {"type": "state", "value": "idle"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_voice_ws_native_path_forwards_commands(monkeypatch):
    # When the native runner is active, /voice/ws reports audio=True and routes
    # start/stop/abort to it (verified with a fake runner — no mic needed).
    from atlas.server import app as appmod

    class FakeRunner:
        def __init__(self):
            self.cmds = []

        def command(self, c):
            self.cmds.append(c)

    fake = FakeRunner()
    monkeypatch.setattr(appmod, "audio_runner", fake)
    with client.websocket_connect("/voice/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        assert ws.receive_json()["audio"] is True          # capabilities
        assert ws.receive_json() == {"type": "ready", "audio": True}
        assert ws.receive_json() == {"type": "state", "value": "idle"}
        ws.send_json({"type": "abort"})
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    assert "abort" in fake.cmds


def test_voice_native_status_endpoint():
    r = client.get("/api/voice/native")
    assert r.status_code == 200
    b = r.json()
    assert "available" in b and "running" in b and "capabilities" in b
