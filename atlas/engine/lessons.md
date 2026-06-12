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

### Cycle 0 — Post-bootstrap review (VERIFY step, Section 3 #7)

Ran a high-effort code review (7 finder angles + verification) and a strict
Section 9 completion audit before declaring the cycle done. The audit: items
1–7 fully DONE; **item 8 PARTIAL** — VERSION.json + changelog shipped, but 3 of
the 10 identity canaries are placeholders because the Owner interview was
deferred (the engine's standing decision, recorded in VERSION.json
`owner_approval_pending`). Honest status, not silent over-claim. The review
caught real bugs the test suite missed — most usefully a `remember` handler that
sliced raw text with offsets computed on a stripped/lowercased copy (leading
whitespace garbled the stored fact), and a frontmatter parser that treated any
`---`-prefixed line as the closing delimiter. Lesson worth keeping: **green
tests are necessary but not sufficient — an adversarial read of just-written
code finds the off-by-context bugs that happy-path tests sail past.** Both are
now regression-tested (16 tests green). Also fixed: vault re-tokenized on every
query (added an mtime-cache, since this sits on the latency path), duplicated
metric extraction in L4, a throwaway second Router built at startup, and dead
code. Net: the VERIFY step paid for itself in the very first cycle — keep it
mandatory, never rubber-stamp a bootstrap because it "ran."
