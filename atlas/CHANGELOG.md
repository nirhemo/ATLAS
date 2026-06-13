# ATLAS Changelog

All notable changes. Versioning per Section 2: MAJOR.MINOR.PATCH.

## [0.2.0] — 2026-06-13 · Cycle 1 · L8 Scheduler (MAJOR — new layer)

Added an **L8 Scheduler layer** (cron system). MAJOR-class change (new layer);
Owner-approved on request. Rollback point: git tag `v0.1.0` (commit aed71b6).

### Added
- **L8 Scheduler** — `atlas/scheduler/`: jobs-as-data + named handlers, schedule
  math (`daily`/`interval`), persisted state (`state.json`, gitignored), an
  in-process daemon thread **and** a `python -m atlas.scheduler run-due` CLI for
  system cron/launchd. Spec: `atlas/scheduler/README.md`.
- **Default jobs** wired to real work: `consolidate` (L2), `health_report` (L4),
  `episodic_purge` (90-day retention, Section 8), `upgrade_cycle` (L5, records
  "due" until the AGE runner is automated).
- **API:** `GET /api/scheduler`, `POST /api/scheduler/run/{job_id}`; HUD gains a
  "Scheduled jobs" panel with next-run times + run-now buttons.
- `settings.json → scheduler` (enabled, check interval, per-job schedule/risk).
  The `consolidate` time is sourced from `memory.consolidation_time` (no drift).

### Safety
- Failing jobs are isolated (marked `error`, loop survives — Mycroft lesson).
- Slots missed while offline roll forward on startup (no surprise consolidation).
- Migrated server lifecycle to FastAPI `lifespan` (no deprecation warnings).

### Tests
- +9 tests (25 total green): schedule math, due detection, run/persist,
  missed-slot rollover, failure isolation, retention purge, API endpoints.

---

## [0.1.0] — 2026-06-12 · Cycle 0 · Bootstrap

Cycle Zero. ATLAS initialized from the Genesis Engine meta-prompt as a runnable
system across all seven layers.

### Added
- **L1 Core Identity** — `core/identity.md` v1.0 (calm, capable, voice-first,
  general-purpose; safety + memory + continuity contracts). *Pending Owner sign-off.*
- **L2 Memory** — Obsidian-style markdown vault (`memory/vault/`) with seed notes,
  SQLite + sqlite-vec schema (`memory/schema.sql`), vector-store config, nightly
  consolidation spec, and append-only episodic cold storage.
- **L3 Interface** — voice pipeline contract (openWakeWord → silero-vad →
  whisper.cpp → LLM → Kokoro/Piper, streaming TTS) and a working dark-futuristic
  web dashboard (`interface/web/`) served by the core.
- **L4 Evaluation** — JSONL logging schema + runtime logger and daily health report.
- **L5 Upgrade Engine** — version manifest, snapshots dir, `engine/lessons.md`,
  identity canaries (md + json), golden conversations.
- **L6 Orchestration** — model router with Claude API + offline fallback chain and
  the uniform tool schema (`orchestration/config.json`, `router.py`, `tools.py`).
- **L7 Connectors** — registry v0 (empty installed; calendar/email/web proposed),
  contract template, and risk-gating (READ/WRITE/DESTRUCTIVE).
- **Runtime** — FastAPI core (`atlas/server/`), pytest suite, `requirements.txt`,
  `run.sh`. Runs offline with zero model downloads.

### Verify (post-bootstrap review)
- High-effort code review + strict Section 9 audit run before sign-off.
- Section 9 audit: items 1–7 DONE; item 8 PARTIAL (canaries 7/10 real, 3 awaiting
  the Owner interview — see VERSION.json `owner_approval_pending`).
- Fixed real bugs the happy-path tests missed: `remember` garbled facts on leading
  whitespace; frontmatter parser mis-detected `---`-prefixed body lines as the
  delimiter. Both now regression-tested (16 tests green).
- Cleanups: mtime-cache for vault retrieval (latency path); de-duplicated L4
  metric extraction; removed a redundant startup Router and dead code; added
  `POST /api/reload` so the Settings UI can apply config without a restart.

### Pending Owner approval
- Identity personality sign-off; real canary answers; first 3 connector installs.

### Rollback
- Snapshot point: `atlas/snapshots/` · revert by checking out the previous tag.
