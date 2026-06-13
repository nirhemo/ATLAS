---
type: project
created: 2026-06-12
updated: 2026-06-12
confidence: 0.95
owner_edited: false
source: atlasmetaprompt.md
---

# Project Atlas

Building **ATLAS** — Automated Task & Logic Assistant System — a persistent,
voice-first, general-purpose AI assistant that lives on a Mac Mini M4 (24GB) and
is *upgraded forever, never rebuilt*.

## Architecture (7 layers)
- L1 Core Identity · L2 Memory (this vault) · L3 Interface (voice + dashboard)
- L4 Evaluation · L5 Upgrade Engine (the AGE) · L6 Orchestration · L7 Connectors

## Phase
- **Phase 1 (now):** Claude API is the brain; wake word, STT, TTS, memory, UI all
  local. → Phase 2 hybrid local Gemma. → Phase 3 local-first.

## Key decisions
- See [[Memory is MemVault, a Markdown vault]] and [[Voice stack choice]].

## Owner
- [[Owner]]
