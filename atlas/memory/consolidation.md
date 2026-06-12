---
layer: L2
artifact: consolidation_job_spec
version: 1.0.0
created: 2026-06-12
---

# L2 · Nightly Consolidation ("Sleep-Time" Pass)

ATLAS writes his own Zettelkasten. Each night, the day's raw episodic transcripts
are distilled into the human-readable vault. This is the job that turns
*conversation* into *memory*.

## When
- **Trigger:** nightly cron, default `03:00` local (configurable in `settings.json`
  → `memory.consolidation_time`). Also runnable on demand: "ATLAS, consolidate."
- Runs during idle time so it never competes with live interaction latency.

## Inputs
- `atlas/memory/episodic/YYYY-MM-DD.jsonl` — yesterday's append-only transcript.
- Rows in `episodic_index` where `consolidated = 0`.
- The existing vault (for dedupe / update vs. create decisions).

## Pipeline
1. **Select** unconsolidated episodic lines (`consolidated = 0`).
2. **Distill** — the model extracts durable, vault-worthy facts only. ~60–70% of
   raw conversation is noise (greetings, repair, chit-chat) and is dropped.
   Vault-worthy = people, projects, preferences, decisions, standing facts.
3. **Verify** — every candidate fact is checked **against the source transcript
   line** before it is written. Unverifiable or speculative thoughts are
   discarded. Working memory never leaks guesses into the vault.
4. **Route** — for each verified fact, decide:
   - *create* a new note (new entity/topic), or
   - *update* an existing note (new info about a known entity), or
   - *link* — add a `[[wiki-link]]` to connect related notes.
5. **Respect Owner edits** — if the target note has `owner_edited: true`, the job
   may append a clearly-marked suggestion block but **must never overwrite** the
   Owner's text. Owner edits are law.
6. **Back-pointer** — write a `backrefs` row: note → episodic source line. Every
   vault fact stays auditable to the exact utterance it came from.
7. **Decay, don't delete** — stale items (not referenced, aging past the decay
   window) have their `confidence` lowered rather than being removed. Nothing is
   silently forgotten.
8. **Dedupe** — merge near-duplicate notes; keep the higher-confidence wording.
9. **Reindex** — incrementally re-embed changed notes (see `vector_store.config.json`).
10. **Mark** processed lines `consolidated = 1`.

## Output & versioning
- The vault is a **git repo**. After a successful run the job auto-commits:
  `git -C atlas/memory/vault commit -am "consolidation YYYY-MM-DD"`.
- `git diff` shows exactly what ATLAS learned overnight; `git revert <hash>`
  cleanly undoes a bad consolidation. This is the L2 hook into Section 2 rollback.
- A `consolidation_runs` row records counts + the commit hash + status.

## Failure / rollback
- If verification fails for >25% of candidates, or the identity canaries regress
  after the run, the job marks the run `rolled_back`, `git revert`s the vault
  commit, and flags it in the next daily health report for Owner review.

## Guarantees
- **Traceable:** every note links back to a transcript line a human can open.
- **Auditable:** the Owner can browse the vault in Obsidian and correct anything.
- **Reversible:** git history is the undo button.
- **Non-destructive:** decay over delete; Owner edits are never overwritten.
