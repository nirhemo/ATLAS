# ATLAS Changelog

All notable changes. Versioning per Section 2: MAJOR.MINOR.PATCH.

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

### Pending Owner approval
- Identity personality sign-off; real canary answers; first 3 connector installs.

### Rollback
- Snapshot point: `atlas/snapshots/` · revert by checking out the previous tag.
