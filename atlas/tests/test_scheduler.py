"""L8 scheduler: schedule math, due detection, run/persist, missed-slot rollover,
and graceful failure isolation."""
from __future__ import annotations

from datetime import datetime, timedelta

from atlas.scheduler.jobs import Job, compute_next, local_now
from atlas.scheduler.scheduler import Scheduler


def _now(h, m):
    return local_now().replace(hour=h, minute=m, second=0, microsecond=0)


def test_compute_next_daily_today_vs_tomorrow():
    base = _now(10, 0)
    # 23:00 is later today
    nxt = compute_next({"type": "daily", "at": "23:00"}, base)
    assert nxt.hour == 23 and nxt.date() == base.date()
    # 03:00 already passed -> tomorrow
    nxt2 = compute_next({"type": "daily", "at": "03:00"}, base)
    assert nxt2.hour == 3 and nxt2.date() == base.date() + timedelta(days=1)


def test_compute_next_interval():
    base = _now(10, 0)
    nxt = compute_next({"type": "interval", "every_minutes": 15}, base)
    assert nxt == base + timedelta(minutes=15)


def _sched(tmp_path, handlers, jobs):
    s = Scheduler(handlers=handlers, state_path=tmp_path / "state.json")
    s.jobs = jobs
    s._ensure_next_runs()
    return s


def test_due_and_run_persist(tmp_path):
    calls = []
    s = _sched(tmp_path, {"j": lambda: calls.append(1) or {"ok": True}},
               [Job(id="j", handler="j", schedule={"type": "interval", "every_minutes": 5})])
    # force it due
    past = (local_now() - timedelta(minutes=1)).isoformat()
    s.state["j"]["next_run"] = past
    ran = s.run_due()
    assert ran == ["j"]
    assert calls == [1]
    assert s.state["j"]["last_status"] == "ok"
    # next_run was advanced into the future
    assert datetime.fromisoformat(s.state["j"]["next_run"]) > local_now()


def test_missed_slot_rolls_forward_not_runs(tmp_path):
    # A job whose next_run is in the past at startup, catch_up=False, must be
    # rescheduled forward (no surprise run on restart).
    calls = []
    job = Job(id="j", handler="j", schedule={"type": "daily", "at": "03:00"},
              catch_up=False)
    s = Scheduler(handlers={"j": lambda: calls.append(1)},
                  state_path=tmp_path / "state.json")
    s.jobs = [job]
    s.state = {"j": {"next_run": (local_now() - timedelta(days=2)).isoformat()}}
    s._ensure_next_runs()
    assert datetime.fromisoformat(s.state["j"]["next_run"]) > local_now()
    assert s.run_due() == []          # nothing fires
    assert calls == []


def test_failing_job_is_isolated(tmp_path):
    def boom():
        raise RuntimeError("nope")
    s = _sched(tmp_path, {"bad": boom},
               [Job(id="bad", handler="bad", schedule={"type": "interval", "every_minutes": 5})])
    s.state["bad"]["next_run"] = (local_now() - timedelta(minutes=1)).isoformat()
    s.run_due()                        # must not raise
    assert s.state["bad"]["last_status"] == "error"
    assert "nope" in s.state["bad"]["last_result"]


def test_run_now_unknown_job(tmp_path):
    s = _sched(tmp_path, {}, [])
    try:
        s.run_now("ghost")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_purge_episodic_respects_retention(tmp_path, monkeypatch):
    import atlas.scheduler.jobs as J
    from atlas import settings as cfg

    epis = tmp_path / "epis"
    epis.mkdir()
    (epis / "2000-01-01.jsonl").write_text("{}\n")      # ancient -> purge
    (epis / "example.jsonl").write_text("{}\n")          # never purged
    recent = local_now().date().isoformat()
    (epis / f"{recent}.jsonl").write_text("{}\n")        # today -> keep

    monkeypatch.setattr(cfg, "episodic_dir", lambda: epis)
    out = J.purge_episodic()
    assert "2000-01-01.jsonl" in out["removed"]
    assert (epis / "example.jsonl").exists()
    assert (epis / f"{recent}.jsonl").exists()
