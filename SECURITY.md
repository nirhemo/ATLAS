# Security

## How ATLAS handles secrets & data

- **API keys** are stored in the **macOS Keychain**, never in the repo, in
  `settings.json`, or in logs. The code references them by name
  (`keychain:atlas-…`) and reads them at runtime.
- **Per-user state stays local & gitignored**: `settings.json`,
  `connectors/registry.json`, `memory/vault/people/owner.md`, episodic
  transcripts, the memory index, and the TTS model files. The self-updater never
  touches them (it only updates tracked code).
- **The server binds to localhost** (`127.0.0.1:8765`) and has **no
  authentication** — it's designed to run on the owner's own machine for a single
  user. Do **not** expose it to a public network or bind it to `0.0.0.0` without
  adding authentication and TLS in front of it.
- Conversations are saved locally; a scheduled job auto-deletes transcripts older
  than the configured retention (default 90 days).

## Reporting a vulnerability

Please open a private report via GitHub Security Advisories on this repository,
or open an issue marked **[security]** if private reporting isn't available.
Include steps to reproduce and the impact. Please don't disclose publicly until
a fix is available.
