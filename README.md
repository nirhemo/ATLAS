# ATLAS — Automated Task & Logic Assistant System

A persistent, voice-first, general-purpose AI assistant that lives on a Mac Mini
M4 (24GB) and is **upgraded forever, never rebuilt**. Built by the ATLAS Genesis
Engine (AGE) from the meta-prompt in `atlasmetaprompt.md`.

> **Status:** Cycle 0 bootstrap complete — a runnable core across all 7 layers.
> Runs **offline with zero model downloads**; add an API key for full reasoning.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the core (HUD + chat + memory). No key needed — offline/degraded mode.
./atlas/run.sh                 # or: python -m atlas.server
# open http://localhost:8765

# Full reasoning (Phase 1): connect Claude
export ANTHROPIC_API_KEY=sk-ant-...
python -m atlas.server

# Tests
pip install pytest httpx && pytest -q

# Memory: distill queued facts into the vault, validate the index
python -m atlas.memory.reindex

# Scheduler (L8): list jobs / run what's due (cron entry) / force one
python -m atlas.scheduler list
python -m atlas.scheduler run-due        # put this in launchd/cron each minute
python -m atlas.scheduler run consolidate
```

What works right now, on real hardware or here:
- **Dark futuristic HUD** at `/` — system status, live metrics, memory feed,
  upgrade panel, voice orb, and a working chat box.
- **Chat** via Claude (with a tool loop) **or** an honest offline fallback
  (time, memory recall, "remember this") that never hangs or bricks.
- **Memory** — read/write the Obsidian-style vault, keyword retrieval,
  `remember` → nightly/manual `consolidate` with git auto-commit, and
  **Owner edits are never overwritten**.
- **Risk gating** — READ auto, WRITE per settings, DESTRUCTIVE needs confirmation;
  uninstalled connectors degrade gracefully.
- **JSONL evaluation logging** + daily health report.
- **Scheduler (L8)** — recurring jobs (consolidation, health report, retention
  purge, upgrade cycle) with a HUD panel, run-now buttons, and a cron CLI; a
  failing job is isolated and the loop never dies.

The voice loop (wake word → STT → TTS) ships as a documented, swappable pipeline
contract; it needs a mic + speakers, so it activates on the Mac, not in CI.

## Architecture (7 layers)

| Layer | What | Where |
|---|---|---|
| **L1** Core Identity | the ATLAS system prompt | `atlas/core/identity.md` |
| **L2** Memory | Obsidian-style vault + retrieval + consolidation | `atlas/memory/` |
| **L3** Interface | voice pipeline + dark HUD + FastAPI core | `atlas/interface/`, `atlas/server/` |
| **L4** Evaluation | JSONL logs + health report | `atlas/evaluation/`, `atlas/logs/` |
| **L5** Upgrade Engine | versioning, canaries, lessons | `atlas/VERSION.json`, `atlas/engine/`, `atlas/tests/` |
| **L6** Orchestration | model router + fallback + tools | `atlas/orchestration/` |
| **L7** Connectors | MCP integrations + risk classes | `atlas/connectors/` |
| **L8** Scheduler | cron system for recurring jobs | `atlas/scheduler/` |

Single source of truth for settings: **`atlas/config/settings.json`** (shared by
the Owner UI and the engine). Full design rationale: `atlas/ARCHITECTURE.md`.

## Phase

Phase 1 (now): Claude is the brain; wake word, STT, TTS, memory, UI run local.
→ Phase 2 hybrid local Gemma · → Phase 3 local-first. Identity, memory, and tools
are backend-independent — switching models never changes who ATLAS is.

## Owner to-do (Cycle 0 placeholders)

- Sign off the L1 personality (`core/identity.md`).
- Replace placeholder identity canaries with real facts (`tests/identity_canaries.*`).
- Approve the first 3 connectors — calendar, email, web (`connectors/registry.json`).
