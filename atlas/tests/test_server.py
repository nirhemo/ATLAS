"""L3/L6 smoke: the core boots, serves the HUD + API, and chats in offline mode."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

# Force offline mode so the suite never makes a network call.
os.environ.pop("ANTHROPIC_API_KEY", None)

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
    # The seeded vault has a Owner note; offline recall should find it.
    r = client.post("/api/chat", json={"text": "what is my name?"})
    assert r.status_code == 200
    assert r.json()["reply"]


def test_connectors_endpoint():
    r = client.get("/api/connectors")
    assert r.status_code == 200
    assert "calendar" in r.json()["proposed"]
