---
layer: L5 / Section 2
artifact: identity_canaries
version: 1.0.0
rotated: 2026-06-12
status: PLACEHOLDERS — replace answers in the Owner interview
---

# Identity Canaries

10 memory questions ATLAS must answer correctly after **every** upgrade to prove
continuity ("ATLAS is still ATLAS"). Any failure → automatic rollback (Section 2).
Rotated monthly. Answers are checked against the memory vault.

> ⚠️ These are **Cycle Zero placeholders**. During the Owner interview, replace the
> `expected` answers with real facts and mark the corresponding vault notes
> `owner_edited: true`. Machine-readable copy: `identity_canaries.json`.

| #  | Question                                              | Expected (placeholder)            | Vault source              |
|----|------------------------------------------------------|-----------------------------------|---------------------------|
| 1  | What is my name?                                     | Owner                               | people/nir.md             |
| 2  | What's the wake word for you?                        | "Hey Atlas"                       | people/nir.md             |
| 3  | What project are we building together?              | ATLAS                             | projects/atlas.md         |
| 4  | What hardware do you run on?                         | Mac Mini M4, 24GB                  | projects/atlas.md         |
| 5  | How do I like my answers — long or short?           | Short, voice-friendly             | people/nir.md             |
| 6  | What's your default model backend right now?        | Claude (Sonnet), Phase 1          | projects/atlas.md         |
| 7  | Which email connector do I use?                     | _to capture in interview_         | preferences/ (tbd)        |
| 8  | What are my working hours?                          | _to capture in interview_         | preferences/ (tbd)        |
| 9  | What's a standing preference you should always honor?| _to capture in interview_         | preferences/ (tbd)        |
| 10 | Name one decision we made about your memory design. | Obsidian-style markdown vault     | decisions/ (tbd)          |

## How the test runs
1. For each question, ATLAS answers using only memory retrieval (no web).
2. A grader (string/semantic match against `expected`) marks pass/fail.
3. **All 10 must pass** or the upgrade auto-rolls-back to the snapshot.
