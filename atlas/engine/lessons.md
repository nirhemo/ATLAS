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
MemVault (the Markdown memory vault), and logs every interaction as JSONL. Two lessons worth
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

## Cycle 1 — L8 Scheduler (2026-06-13)

Added the first brand-new layer post-bootstrap: **L8, the cron system**. The
trigger was honest — the specs kept promising "nightly at 03:00" work (L2
consolidation, L4 health report, Section 8 retention purge, L5 upgrade cycle)
that nothing actually ran. R6 says a revealed need becomes its own layer, not a
bolt-on, so it went in as L8 with its own spec, not as a timer stapled to L2.
Design lessons worth keeping. First — **jobs are data, handlers are callables**:
the schedule lives in settings.json and the handler is looked up by name, which
made the whole layer injectable and gave me six fast unit tests with fake
handlers instead of waiting on wall-clock time. Second — **decide the
missed-slot policy explicitly**: a scheduler that runs everything it missed
while the machine was asleep would fire a surprise consolidation/purge on every
restart, so the default rolls past slots forward and only `catch_up: true` jobs
replay — a safer default than the obvious one. Third — **two drivers, one
state**: an in-process thread for the always-on Mac, plus a `run-due` CLI so
launchd/cron can drive the exact same jobs; the OS scheduler is more battle-
tested than my loop (R8), so I let it be an option rather than reinventing it.
Kept the Mycroft reflex: a throwing job is caught and the loop survives. One
debt carried forward: `upgrade_cycle` only records "due" — the AGE's automated
cycle runner is still the missing piece, and that's the natural next layer of
work now that something is poised to call it.
