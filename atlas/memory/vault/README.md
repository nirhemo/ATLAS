# ATLAS Memory Vault

This directory **is** ATLAS's long-term memory — the source of truth (L2).
It is an **Obsidian-compatible** markdown vault: open it in Obsidian and you are
browsing ATLAS's brain directly.

## Layout
- `people/` — one note per person.
- `projects/` — one note per project or ongoing effort.
- `preferences/` — the Owner's standing preferences and defaults.
- `decisions/` — decisions made, with rationale and date.
- `topics/` — general knowledge notes.

## Note format
Every note is a markdown file with **YAML frontmatter** and uses `[[wiki-links]]`
to connect to other notes, forming a knowledge graph.

```markdown
---
type: person            # person | project | preference | decision | topic
created: 2026-06-12
updated: 2026-06-12
confidence: 0.9         # 0.0–1.0, decayed over time, never hard-deleted
owner_edited: false     # set true if you edit by hand — ATLAS will never overwrite
source: episodic/2026-06-12.jsonl#L42   # back-pointer to where this was learned
---

# Note Title

Body in plain markdown. Link related notes like [[Project Atlas]].
```

## Rules for humans
- **Your edits are law.** Set `owner_edited: true` (or just edit — the
  consolidation job detects manual changes) and ATLAS will never overwrite you.
- This folder is a **git repo**. ATLAS auto-commits after each nightly
  consolidation; run `git log` / `git diff` to see what he learned, `git revert`
  to undo a bad night.

## Rules for ATLAS
- Only the nightly consolidation job writes here (verified facts only).
- Never write speculation. Decay stale notes' confidence; do not delete.

> The files alongside this README (`people/owner.example.md`, `projects/atlas.md`) are
> **seed examples** created at Cycle Zero to demonstrate the format. Replace or
> correct them during the Owner interview.
