"""Job definitions, schedule math, and the default handlers (L8).

A job is data (id + schedule + risk + enabled). The handler is a plain callable
looked up by name, so the scheduler stays decoupled from what the jobs *do* and
handlers can be injected in tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .. import settings as cfg
from ..evaluation.logger import health_report, log_event
from ..memory.store import VaultStore


def local_now() -> datetime:
    """Timezone-aware wall-clock now (schedules are wall-clock, e.g. '03:00')."""
    return datetime.now().astimezone()


@dataclass
class Job:
    id: str
    handler: str
    schedule: dict[str, Any]
    enabled: bool = True
    risk: str = "READ"
    catch_up: bool = False          # run a missed slot on startup, or skip it?
    meta: dict[str, Any] = field(default_factory=dict)


def compute_next(schedule: dict[str, Any], after: datetime) -> datetime:
    """Next fire time strictly after `after`.

    Supported schedules:
      {"type": "daily",    "at": "HH:MM"}
      {"type": "interval", "every_minutes": N}
    Unknown types are parked far in the future (never auto-fire).
    """
    kind = schedule.get("type")
    if kind == "daily":
        hh, mm = (int(x) for x in str(schedule.get("at", "03:00")).split(":"))
        cand = after.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= after:
            cand += timedelta(days=1)
        return cand
    if kind == "interval":
        every = max(1, int(schedule.get("every_minutes", 60)))
        return after + timedelta(minutes=every)
    return after + timedelta(days=3650)


def load_jobs() -> list[Job]:
    """Build Job objects from settings.json → scheduler.jobs."""
    sched = cfg.settings().get("scheduler", {})
    jobs: list[Job] = []
    for job_id, spec in sched.get("jobs", {}).items():
        spec = dict(spec)
        schedule = {k: spec[k] for k in ("type", "at", "every_minutes") if k in spec}
        # Single source of truth: the consolidate job's time mirrors the memory
        # layer's consolidation_time so the two settings can never drift.
        if job_id == "consolidate":
            schedule["at"] = cfg.settings()["memory"].get("consolidation_time",
                                                          schedule.get("at", "03:00"))
        jobs.append(Job(
            id=job_id,
            handler=spec.get("handler", job_id),
            schedule=schedule,
            enabled=bool(spec.get("enabled", True)),
            risk=spec.get("risk", "READ"),
            catch_up=bool(spec.get("catch_up", False)),
        ))
    return jobs


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def purge_episodic() -> dict[str, Any]:
    """Privacy retention (Section 8): drop date-named episodic transcripts older
    than privacy.episodic_retention_days. Semantic facts already live in the
    vault via consolidation; only raw transcripts are purged. The committed
    example.jsonl (not date-named) is never touched.

    Note: this is classed DESTRUCTIVE, but the Owner's retention window in
    settings.json is the standing authorization — a 4am purge can't ask for
    verbal confirmation, so the policy itself is the consent.
    """
    days = int(cfg.settings()["privacy"].get("episodic_retention_days", 90))
    cutoff = date.today() - timedelta(days=days)
    removed: list[str] = []
    for p in cfg.episodic_dir().glob("*.jsonl"):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.jsonl", p.name)
        if not m:
            continue
        if date.fromisoformat(m.group(1)) < cutoff:
            p.unlink()
            removed.append(p.name)
    return {"removed": removed, "cutoff": cutoff.isoformat(), "retention_days": days}


def run_upgrade_cycle() -> dict[str, Any]:
    """Nightly cycle (Section 3): check git for new ATLAS code and record whether
    an update is available. Applying is owner-gated (the HUD's Update button) —
    we never auto-apply unattended."""
    from ..engine.updater import check
    info = check()
    log_event("upgrade", {
        "status": "checked",
        "update_available": info.get("update_available", False),
        "behind": info.get("behind", 0),
        "current_version": info.get("current_version"),
    })
    return {"status": "checked", "update_available": info.get("update_available", False),
            "behind": info.get("behind", 0)}


def default_handlers() -> dict[str, Callable[[], Any]]:
    return {
        "consolidate": lambda: VaultStore().consolidate(),
        "health_report": health_report,
        "episodic_purge": purge_episodic,
        "upgrade_cycle": run_upgrade_cycle,
    }
