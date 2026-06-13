"""L7 risk gating: READ auto, WRITE allowed, DESTRUCTIVE blocked w/o confirm,
uninstalled connectors degrade gracefully."""
from __future__ import annotations

from atlas.connectors.loader import ConnectorRegistry, RiskClass


def test_read_tool_is_auto_allowed():
    reg = ConnectorRegistry()
    allowed, _ = reg.gate("get_time")
    assert allowed is True
    assert reg.tool_risk("get_time") is RiskClass.READ


def test_destructive_blocked_without_confirmation():
    reg = ConnectorRegistry()
    # email_send is DESTRUCTIVE; even ignoring the connector, confirmation gates it.
    assert reg.tool_risk("email_send") is RiskClass.DESTRUCTIVE
    allowed, reason = reg.gate("email_send", confirmed=False)
    assert allowed is False
    assert "connector" in reason.lower() or "confirm" in reason.lower()


def test_uninstalled_connector_degrades_gracefully():
    reg = ConnectorRegistry()
    # Connector approvals are per-user (registry.json is gitignored), so force a
    # known "nothing installed" state to test the gate deterministically.
    reg.registry = {"installed": [], "proposed": [{"id": "calendar"}]}
    allowed, reason = reg.gate("calendar_list_events")
    assert allowed is False                     # not installed
    assert "calendar" in reason.lower()
