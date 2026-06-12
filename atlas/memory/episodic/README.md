# Episodic Cold Storage

Append-only **raw transcripts**, one JSONL file per day: `YYYY-MM-DD.jsonl`.

These are **not** memory notes — they are the raw record. The nightly
consolidation job (`../consolidation.md`) distills vault-worthy facts out of these
into the vault and keeps back-pointers (note → transcript line) for auditability.

## Line format (one JSON object per line)
```json
{"ts":"2026-06-12T23:14:56Z","role":"owner","text":"Hey Atlas, remind me to call the dentist tomorrow at 9.","session":"s_001","turn":1}
{"ts":"2026-06-12T23:14:58Z","role":"atlas","text":"Done — reminder set for 9am tomorrow.","session":"s_001","turn":1,"actions":["reminder.create"]}
```

| field     | meaning                                              |
|-----------|------------------------------------------------------|
| `ts`      | ISO-8601 UTC timestamp of the utterance              |
| `role`    | `owner` \| `atlas` \| `system`                       |
| `text`    | verbatim utterance / response text (no audio stored) |
| `session` | conversation session id                              |
| `turn`    | turn number within the session                       |
| `actions` | (optional) connector/tool actions taken this turn    |

## Retention (Section 8)
- Episodic logs containing third-party personal data are retained **90 days**,
  then distilled (semantic facts kept in the vault) and purged from cold storage.
- Retention window is configurable in `settings.json` → `privacy.episodic_retention_days`.
- No audio is ever written here — only post-STT text. Audio never leaves the device.

> `2026-06-12.jsonl` alongside this README is a seed example.
