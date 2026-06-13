"""L4 logging + metrics. Events are appended as JSONL to atlas/logs/YYYY-MM-DD.jsonl
following atlas/logs/schema.md."""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .. import settings as cfg


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_file(day: str | None = None) -> Path:
    d = day or date.today().isoformat()
    p = cfg.logs_dir() / f"{d}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log_event(event_type: str, data: dict[str, Any], *, session: str = "s_000",
              turn: int = 0, channel: str = "chat") -> None:
    """Append one structured event. Best-effort; never raises into the request path."""
    rec = {
        "ts": _now_iso(), "type": event_type, "session": session,
        "turn": turn, "channel": channel, "data": data,
    }
    try:
        with _log_file().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _read_day(day: str) -> list[dict[str, Any]]:
    p = _log_file(day)
    if not p.exists():
        return []
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def _series(day: str) -> tuple[list, list, list, int]:
    """Extract (latency, accuracy, memory_hit) series + interaction count for a day.
    Single source for both the dashboard metrics and the daily health report."""
    events = [e for e in _read_day(day) if e.get("type") == "interaction"]
    lat = [e["data"]["latency_ms"] for e in events
           if e.get("data", {}).get("latency_ms") is not None]
    acc = [e["data"]["accuracy"] for e in events
           if e.get("data", {}).get("accuracy") is not None]
    hit = [e["data"]["memory_hit"] for e in events
           if e.get("data", {}).get("memory_hit") is not None]
    return lat, acc, hit, len(events)


def metrics_today() -> dict[str, Any]:
    """Aggregate today's interaction events for the dashboard."""
    lat, acc, hit, count = _series(date.today().isoformat())
    return {
        "latency_ms": round(statistics.median(lat)) if lat else 0,
        "latency_trend": 0,
        "accuracy": round(statistics.mean(acc), 3) if acc else 1.0,
        "accuracy_trend": 0,
        "interactions": count,
        "interactions_trend": 0,
        "memory_hit": round(statistics.mean(hit), 3) if hit else 1.0,
        "memhit_trend": 0,
    }


def recent_events(limit: int = 200) -> list[dict[str, Any]]:
    """Most recent `limit` log events for the Logs drawer, oldest→newest.
    Reads today and spills into prior days only as far as needed."""
    out: list[dict[str, Any]] = []
    d = date.today()
    # Walk back day-by-day until we have enough (cap at 7 days to bound work).
    for _ in range(7):
        day_events = _read_day(d.isoformat())
        out = day_events + out
        if len(out) >= limit:
            break
        d = date.fromordinal(d.toordinal() - 1)
    return out[-limit:]


def health_report(day: str | None = None) -> dict[str, Any]:
    """Compute the daily health report (Section 4) and log it."""
    d = day or date.today().isoformat()
    lat, acc, hit, count = _series(d)
    report = {
        "date": d,
        "interactions": count,
        "latency_p50_ms": round(statistics.median(lat)) if lat else 0,
        "latency_p95_ms": round(sorted(lat)[int(len(lat) * 0.95)]) if lat else 0,
        "accuracy": round(statistics.mean(acc), 3) if acc else None,
        "memory_hit_rate": round(statistics.mean(hit), 3) if hit else None,
        "regressions": [],
    }
    log_event("health_report", report)
    return report
