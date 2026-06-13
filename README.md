# ATLAS — Automated Task & Logic Assistant System

A **persistent, voice-first, local-first** personal assistant that lives on your
Mac. Talk to it ("Hey Atlas"), and it answers in a clean neural voice, remembers
what matters, searches the web for live facts, and upgrades itself — **forever,
never rebuilt**. Bring your own model: a **free local model**, **OpenRouter**, or
the **Claude API**.

> **Status:** v0.2.0 · runs offline-degraded out of the box; add a model in the
> first-run wizard for full reasoning. **Free & open source** under the
> [GNU AGPL-3.0](LICENSE). **Commercial licenses** — to build closed-source or
> hosted products without AGPL's source-sharing terms — are available from Nir Hemo.

---
<img width="1707" height="1289" alt="image" src="https://github.com/user-attachments/assets/db914c3a-34fc-489b-a5b5-58220f7ff73b" />

## Highlights

- 🟦 **Voice-first HUD** — a dark, futuristic dashboard with a central voice orb,
  wake-word listening, a fluent back-and-forth conversation loop, a floating chat,
  a live logs drawer, and a working settings panel.
- 🗣️ **Clean neural voice** — on-device **Kokoro** TTS (no cloud, no key), with a
  graceful fall back to the browser voice. Speaks like a person, not a document.
- 🧠 **Bring-your-own-model + task routing** — Local (MLX), OpenRouter, or Claude
  API. Optional **smart routing** sends *code* → a strong model, *complex* tasks →
  a balanced one, *daily* questions → a cheap/free one — per turn, no extra latency.
- 🔎 **Grounded answers** — every factual question goes through **web search** (or
  memory) and is cited; ATLAS never answers from stale model memory.
- 💾 **Real memory** — **MemVault**, a local Markdown memory vault (linked notes
  + YAML frontmatter), plus saved conversation history and nightly consolidation.
- 🔁 **Self-updater** — pulls new code from GitHub safely: backup → atomic apply →
  health-check → auto-rollback. **Your data and settings are never touched** — only
  capabilities update.
- 🔒 **Private by design** — keys in the macOS Keychain, conversations on-device,
  per-user state never committed.

## Quick start

```bash
git clone https://github.com/nirhemo/ATLAS.git && cd ATLAS
python3.12 -m venv .venv && source .venv/bin/activate     # Python 3.10+ required
pip install -r requirements.txt

./atlas/run.sh            # → http://localhost:8765
```

Open **http://localhost:8765** and the **first-run setup wizard** walks you
through everything: your name, picking a model brain, connecting a key (stored in
Keychain), voice setup, connector approvals, and a privacy review. Re-run it
anytime from **Settings → ↻ Setup**.

> Works in Chrome/Edge for voice (Web Speech). Text chat works everywhere.

## Choosing a model

The wizard (or **Settings → Model**) lets you pick:

| Backend | What | Cost |
|---|---|---|
| 🖥️ **Local (MLX)** | A model on your Mac via an OpenAI-compatible server (e.g. `mlx_lm.server`) | Free, private |
| 🌐 **OpenRouter** | One key → many models (free + frontier) | Free tiers + pay-as-you-go |
| ☁️ **Claude API** | Anthropic key | Pay-per-token |

**Task routing** (optional) maps intents to tiers — e.g. Code → Opus, Complex →
Sonnet, Daily → a free model — so most turns are cheap/free and you only pay for
the hard ones.

## Privacy & data

API keys live in the **macOS Keychain**. Conversations, your profile, connector
approvals, and settings stay **on your machine** and are **gitignored** (templates
ship instead). A scheduled job auto-deletes old transcripts. See [SECURITY.md](SECURITY.md).

## Run as a service (auto-restart)

Install ATLAS as a macOS LaunchAgent so it starts on login, restarts on crash, and
restarts cleanly after an update:

```bash
./deploy/install-service.sh     # uninstall: ./deploy/uninstall-service.sh
```

## Architecture (8 layers)

| Layer | What | Where |
|---|---|---|
| **L1** Core Identity | the ATLAS system prompt | `atlas/core/identity.md` |
| **L2** Memory | vault + retrieval + saved conversations + consolidation | `atlas/memory/` |
| **L3** Interface | voice pipeline, neural TTS, dark HUD, FastAPI core, onboarding | `atlas/interface/`, `atlas/server/` |
| **L4** Evaluation | JSONL event logs + health report | `atlas/evaluation/`, `atlas/logs/` |
| **L5** Upgrade Engine | versioning, snapshots, **self-updater** | `atlas/engine/`, `atlas/VERSION.json` |
| **L6** Orchestration | model router (api/openrouter/local) + task routing + tools | `atlas/orchestration/` |
| **L7** Connectors | web search + MCP integrations + risk gating | `atlas/connectors/` |
| **L8** Scheduler | cron jobs (consolidate, health, purge, update check) | `atlas/scheduler/` |

Full design rationale: [`atlas/ARCHITECTURE.md`](atlas/ARCHITECTURE.md).

## Tests

```bash
pytest -q     # 25 tests, fully offline (ATLAS_FORCE_OFFLINE)
```

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Keep tests green and offline,
and never commit per-user state or secrets.

## License

ATLAS is **free and open source** under the
[GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later) —
use, study, modify, and self-host it freely. Because it's AGPL, if you run a
**modified** ATLAS as a network service you must offer your users the
corresponding source.

**Commercial license:** to build a **closed-source product** or a **hosted/SaaS
offering** on ATLAS *without* AGPL's source-disclosure obligations, a separate
commercial license is available — contact **Nir Hemo**.

---

*Built with love by **Nir Hemo**, with contributions from **[RepoWise.ai](https://repowise.ai)**.*
