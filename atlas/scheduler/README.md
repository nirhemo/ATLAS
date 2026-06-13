---
layer: L8
artifact: scheduler_spec
version: 1.0.0
created: 2026-06-13
status: active
upgrade_class: MAJOR (new layer — Owner approved 2026-06-13)
---

# L8 · Scheduler Layer (cron system)

## Why this layer exists

The system already *assumed* recurring work — nightly consolidation at `03:00`,
the daily health report, 90-day episodic retention, the nightly upgrade cycle —
but nothing actually ran it. Per **R6** (a need the logs reveal becomes its own
layer, not a bolt-on) this is L8 rather than extra code stapled to L2 or L5.

## Contract

- **Source of truth:** `settings.json → scheduler` (the Owner + AGE edit one file).
- **Jobs are data, handlers are callables.** A job declares `type/at`, `enabled`,
  `risk`, `catch_up`; the handler is looked up by name (injectable for tests).
- **Persisted state:** `atlas/scheduler/state.json` (runtime, gitignored) records
  `last_run`, `next_run`, `last_status` per job — survives restarts, feeds the HUD.
- **Two drivers, one state:**
  1. in-process daemon thread started by the server (`Scheduler.start()`), or
  2. the OS (launchd/cron) calling `python -m atlas.scheduler run-due` each minute.
  Use whichever fits the deployment; never both for the same jobs.

## Schedules supported
| schedule | meaning |
|---|---|
| `{"type":"daily","at":"HH:MM"}` | once a day at wall-clock time |
| `{"type":"interval","every_minutes":N}` | every N minutes |

## Default jobs (Cycle 1)
| job | handler | when | risk | does |
|---|---|---|---|---|
| `consolidate` | L2 `VaultStore.consolidate` | `memory.consolidation_time` (03:00) | WRITE | distill episodic → vault, git-commit |
| `health_report` | L4 `health_report` | 23:55 | READ | write the daily health report |
| `episodic_purge` | retention | 04:00 | DESTRUCTIVE* | drop transcripts older than the retention window |
| `upgrade_cycle` | L5 AGE | 03:30 | WRITE | trigger the nightly upgrade cycle |

\* The `consolidate` time is read from `memory.consolidation_time` so it can never
drift from the L2 setting. \* `episodic_purge` is DESTRUCTIVE, but the Owner's
`privacy.episodic_retention_days` is the standing authorization — an unattended
4am purge can't ask for verbal confirmation, so the policy is the consent.

## Safety / graceful degradation
- A failing job is caught, marked `error`, and **never takes the loop down**
  (Mycroft lesson). The next slot is still scheduled.
- Slots missed while the process was down are rolled forward on startup (unless a
  job sets `catch_up: true`), so a restart never fires a surprise consolidation.
- `upgrade_cycle` honestly records "due" until the AGE automated runner exists —
  the scheduling is real even though the cycle is still run on demand.

## API / control
- `GET  /api/scheduler` — job list with next/last run + status (HUD panel).
- `POST /api/scheduler/run/{job_id}` — manual trigger.
- CLI: `list` · `run-due` · `run <job>` · `start` (see `__main__.py`).
- Toggle the whole layer with `settings.json → scheduler.enabled`.
