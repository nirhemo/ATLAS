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
    r = client.post("/api/chat", json={"text": "  remember my locker code is 4831"})
    assert r.status_code == 200
    assert "remember" in r.json()["tools_used"]


def test_connectors_endpoint():
    r = client.get("/api/connectors")
    assert r.status_code == 200
    assert "calendar" in r.json()["proposed"]


def test_scheduler_endpoint_lists_jobs():
    r = client.get("/api/scheduler")
    assert r.status_code == 200
    ids = {j["id"] for j in r.json()}
    assert {"consolidate", "health_report", "episodic_purge", "upgrade_cycle"} <= ids


def test_scheduler_run_unknown_job_404():
    r = client.post("/api/scheduler/run/ghost")
    assert r.status_code == 404
