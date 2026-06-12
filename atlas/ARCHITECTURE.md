# ATLAS Architecture

How the runnable system maps to the 7-layer design. Read alongside
`atlasmetaprompt.md` (the spec) and `VERSION.json` (the manifest).

## Runtime flow

```
                          ┌──────────────────────────────────────────┐
   Browser / Voice ──────▶│  L3 server (atlas/server/app.py, FastAPI) │
   (HUD, /api/chat, /ws)  └───────────────┬──────────────────────────┘
                                          │
                              ┌───────────▼────────────┐
                              │  L6 Router (router.py) │  picks backend,
                              │  claude → offline       │  runs bounded tool loop
                              └─────┬─────────────┬─────┘
                    ┌───────────────┘             └───────────────┐
          ┌─────────▼─────────┐            ┌──────────────────────▼─────────┐
          │ L1 identity.md    │            │ L6 tools.py / L7 loader.py     │
          │ (system prompt)   │            │ risk gating READ/WRITE/DESTRUCT│
          └───────────────────┘            └───────────┬────────────────────┘
                                                       │
                          ┌────────────────────────────▼───────────────┐
                          │ L2 VaultStore (memory/store.py)             │
                          │ search · remember · consolidate · git commit│
                          └────────────────────────────┬───────────────┘
                                                       │
                          ┌────────────────────────────▼───────────────┐
                          │ L4 logger.py → atlas/logs/YYYY-MM-DD.jsonl  │
                          └─────────────────────────────────────────────┘
```

Every chat turn: Router → (Claude tool loop | offline intents) → tools may hit
the vault or connectors → L4 logs an `interaction` event with latency + memory_hit.

## Layer-by-layer

- **L1 Identity** — `core/identity.md` is loaded verbatim as the system prompt on
  every turn, regardless of backend (R3). Editing it is a MAJOR change.
- **L2 Memory** — markdown vault is source of truth; `store.py` parses frontmatter,
  scores notes (keyword TF-IDF now, embeddings later — same `search()` interface),
  queues `remember` to episodic, and `consolidate()` distills + git-commits.
  Owner-edited notes are appended to, never overwritten.
- **L3 Interface** — `server/app.py` serves the HUD and the JSON/WS API; the voice
  pipeline contract lives in `interface/voice/pipeline.md` (hardware-gated).
- **L4 Evaluation** — `logger.py` writes the JSONL schema in `logs/schema.md` and
  computes `metrics_today()` / `health_report()`.
- **L5 Upgrade Engine** — `VERSION.json`, `snapshots/`, `engine/lessons.md`,
  and the `tests/` canaries + goldens are the machinery the AGE drives each cycle.
- **L6 Orchestration** — `config.json` defines routing, the fallback chain, and the
  one tool schema; `router.py` + `tools.py` execute it with graceful degradation.
- **L7 Connectors** — `registry.json` (installed/proposed) + `loader.py` enforce
  risk classes. Cycle 0 ships zero installed connectors; calendar/email/web are
  proposed and await Owner approval (installing = MINOR).

## Design decisions worth knowing

1. **Offline-first from bootstrap.** No API key ⇒ degraded mode (time, recall,
   remember), not a crash. The Mycroft "don't brick" lesson is wired in on day one.
2. **Zero model downloads to run.** Retrieval is a transparent keyword scorer;
   embeddings are the documented Cycle 1 upgrade behind the same interface.
3. **One source of truth.** `config/settings.json`, `connectors/registry.json`,
   and the canaries are real machine-loadable files the UI and engine both edit —
   no doc/runtime drift.
4. **Reversibility everywhere (R2).** Vault is git (revert a bad night); snapshots
   gate MAJOR/MINOR; canaries auto-rollback an identity regression.

## Not yet wired (next cycles)

- Live voice loop on hardware (openWakeWord/silero/whisper.cpp/Kokoro).
- Real MCP connector clients (calendar/email/web) behind the existing gate.
- sqlite-vec embeddings + the nightly cron scheduler.
- The AGE's automated cycle runner (currently the loop is run by an operator).
