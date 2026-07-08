"""L8 upgrade cycle: check-only vs auto-apply, gated by settings. Hermetic — the
updater and settings are monkeypatched, so nothing touches git or restarts."""
from __future__ import annotations

from atlas.engine import updater
from atlas.scheduler import jobs


def _settings(upgrade):
    return lambda: {"upgrade": upgrade}


def test_up_to_date_is_a_noop(monkeypatch):
    monkeypatch.setattr(jobs.cfg, "settings", _settings({"auto_apply": True}))
    monkeypatch.setattr(updater, "check", lambda: {"update_available": False, "current_version": "0.4.0"})
    r = jobs.run_upgrade_cycle()
    assert r["status"] == "up_to_date"


def test_checks_only_when_auto_apply_off(monkeypatch):
    monkeypatch.setattr(jobs.cfg, "settings", _settings({"auto_apply": False}))
    monkeypatch.setattr(updater, "check", lambda: {"update_available": True, "behind": 2, "current_version": "0.4.0"})
    applied = {"v": False}
    monkeypatch.setattr(updater, "apply", lambda confirm: applied.update(v=True))
    r = jobs.run_upgrade_cycle()
    assert r["status"] == "update_available"
    assert applied["v"] is False        # must NOT apply when the switch is off


def test_auto_applies_when_on(monkeypatch):
    monkeypatch.setattr(jobs.cfg, "settings", _settings({"auto_apply": True, "auto_restart": False}))
    monkeypatch.setattr(updater, "check", lambda: {"update_available": True, "behind": 1, "current_version": "0.4.0"})
    calls = {}

    def fake_apply(confirm):
        calls["confirm"] = confirm
        return {"applied": True, "to_version": "0.4.1"}

    monkeypatch.setattr(updater, "apply", fake_apply)
    r = jobs.run_upgrade_cycle()
    assert calls["confirm"] is True     # applied with confirm=True
    assert r["status"] == "applied"
    assert r["to_version"] == "0.4.1"
    assert r["restarting"] is False     # not supervised in tests → no restart
