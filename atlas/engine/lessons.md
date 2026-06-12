# AGE Lessons

The ATLAS Genesis Engine appends one paragraph per cycle — what it learned about
upgrading ATLAS. This file is how the engine improves itself without changing its
prompt. Newest at the bottom.

---

## Cycle 0 — Bootstrap (2026-06-12)

First light. Built ATLAS from the meta-prompt as a *running* system, not just
specs: seven layers laid down with real, loadable artifacts (identity, vault,
schema, configs, logging, orchestration, connectors) and a working FastAPI core
that serves the dark HUD, talks to Claude with an offline fallback, reads/writes
the Obsidian-style vault, and logs every interaction as JSONL. Two lessons worth
keeping. First — **make the source-of-truth files real and machine-loadable from
day one** (settings.json, registry.json, the canaries as JSON), so the Owner UI
and the engine genuinely share one source rather than drifting docs. Second —
**the offline path is not an afterthought**: wiring the degraded fallback at
bootstrap (no API key → local echo + memory recall instead of a crash) bakes in
the Mycroft lesson before there's anything to brick. Open items deferred to
Cycle 1: real embeddings for retrieval (currently a transparent keyword scorer so
the system runs with zero model downloads), the live voice loop on real hardware,
and replacing every Owner placeholder (canaries, connector auth) via the
interview. Next cycle should also start honoring R7 — research before the first
MINOR patch — now that there's a baseline to measure against.
