"""The scheduler runtime (L8).

Two ways to drive it, both backed by the same persisted state:
  1. In-process background thread (started by the server) — `start()` / `stop()`.
  2. External trigger (system cron / launchd) — `python -m atlas.scheduler run-due`.

State (last_run / next_run / status per job) is persisted to
atlas/scheduler/state.json so schedules survive restarts and the dashboard can
show them. The state file is runtime-only (gitignored).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .. import settings as cfg
from ..evaluation.logger import log_event
from .jobs import Job, compute_next, default_handlers, load_jobs, local_now

STATE_PATH = cfg.ATLAS_DIR / "scheduler" / "state.json"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _summarize(result: Any) -> str:
    s = json.dumps(result, default=str) if not isinstance(result, str) else result
    return s[:240]


class Scheduler:
    def __init__(self, handlers: dict[str, Callable[[], Any]] | None = None,
                 state_path: Path | None = None):
        self.handlers = handlers or default_handlers()
        self.state_path = state_path or STATE_PATH
        self.jobs: list[Job] = load_jobs()
        self.state = self._read()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._ensure_next_runs()

    # ----- persistence -------------------------------------------------- #
    def _read(self) -> dict[str, Any]:
        if self.state_path == STATE_PATH:
            return _load_state()
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self) -> None:
        if self.state_path == STATE_PATH:
            _save_state(self.state)
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    # ----- scheduling --------------------------------------------------- #
    def _ensure_next_runs(self) -> None:
        """Make sure every job has a future next_run. A slot missed while the
        process was down is rolled forward (unless the job opts into catch_up),
        so restarts never trigger a surprise consolidation/purge."""
        now = local_now()
        for job in self.jobs:
            st = self.state.setdefault(job.id, {})
            nxt = st.get("next_run")
            if not nxt:
                st["next_run"] = compute_next(job.schedule, now).isoformat()
            elif datetime.fromisoformat(nxt) <= now and not job.catch_up:
                st["next_run"] = compute_next(job.schedule, now).isoformat()
        self._write()

    def due_jobs(self, now: datetime | None = None) -> list[Job]:
        now = now or local_now()
        due = []
        for job in self.jobs:
            if not job.enabled:
                continue
            nxt = self.state.get(job.id, {}).get("next_run")
            if nxt and datetime.fromisoformat(nxt) <= now:
                due.append(job)
        return due

    def run_job(self, job: Job, now: datetime | None = None) -> dict[str, Any]:
        now = now or local_now()
        st = self.state.setdefault(job.id, {})
        try:
            result = self.handlers[job.handler]()
            st["last_status"] = "ok"
            st["last_result"] = _summarize(result)
        except Exception as exc:  # a bad job must not take the scheduler down
            st["last_status"] = "error"
            st["last_result"] = f"{type(exc).__name__}: {exc}"
        st["last_run"] = now.isoformat()
        st["next_run"] = compute_next(job.schedule, now).isoformat()
        self._write()
        log_event("scheduler", {"job": job.id, "status": st["last_status"],
                                "next_run": st["next_run"]})
        return st

    def run_due(self, now: datetime | None = None) -> list[str]:
        with self._lock:
            ran = []
            for job in self.due_jobs(now):
                self.run_job(job, now)
                ran.append(job.id)
            return ran

    def run_now(self, job_id: str) -> dict[str, Any]:
        """Manually trigger one job regardless of schedule (dashboard button / CLI)."""
        job = next((j for j in self.jobs if j.id == job_id), None)
        if job is None:
            raise KeyError(job_id)
        with self._lock:
            return self.run_job(job)

    # ----- background thread ------------------------------------------- #
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="atlas-scheduler",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        interval = int(cfg.settings().get("scheduler", {}).get("check_interval_seconds", 60))
        while not self._stop.wait(interval):
            try:
                self.run_due()
            except Exception:  # never let the loop die
                continue

    # ----- introspection ----------------------------------------------- #
    def status(self) -> list[dict[str, Any]]:
        out = []
        for job in self.jobs:
            st = self.state.get(job.id, {})
            out.append({
                "id": job.id, "handler": job.handler, "schedule": job.schedule,
                "enabled": job.enabled, "risk": job.risk,
                "next_run": st.get("next_run"), "last_run": st.get("last_run"),
                "last_status": st.get("last_status"),
            })
        out.sort(key=lambda j: j.get("next_run") or "")
        return out
