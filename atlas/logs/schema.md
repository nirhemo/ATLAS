---
layer: L4
artifact: logging_schema
version: 1.0.0
created: 2026-06-12
---

# L4 · Logging Schema

Structured event logs, one JSONL file per day: `atlas/logs/YYYY-MM-DD.jsonl`.
The evaluation layer reads these to compute the daily health report and to feed
the upgrade engine (L5).

## Event envelope (one JSON object per line)
```json
{
  "ts": "2026-06-12T23:15:12Z",
  "type": "interaction",
  "session": "s_001",
  "turn": 3,
  "channel": "voice",
  "data": { }
}
```
| field     | meaning                                                        |
|-----------|----------------------------------------------------------------|
| `ts`      | ISO-8601 UTC                                                    |
| `type`    | `interaction` \| `state_change` \| `tool_call` \| `error` \| `health_report` \| `upgrade` |
| `session` | conversation session id                                        |
| `turn`    | turn number within the session                                 |
| `channel` | `voice` \| `chat`                                              |
| `data`    | type-specific payload (below)                                  |

## `interaction` payload — the metric framework (Section 4)
```json
{
  "latency_ms": 740,            // wake-to-first-word (voice) / send-to-first-token (chat)
  "accuracy": 1,               // 1 ok / 0 failed / null unknown
  "satisfaction": null,         // explicit rating, or inferred from corrections/repeats/"never mind"
  "memory_hit": 1,             // 1 if retrieval surfaced the right context; 0 if ATLAS asked what it should know
  "tools_used": ["memory_search"],
  "backend": "claude-sonnet-4-6",
  "tokens_in": 812, "tokens_out": 140
}
```
Targets: voice `latency_ms` < 1500, chat < 800.

## `state_change` payload (voice pipeline)
```json
{ "from": "thinking", "to": "speaking" }
```

## `tool_call` payload
```json
{ "name": "calendar_create_event", "risk": "WRITE", "ok": true, "ms": 210, "confirmed": true }
```

## `error` payload
```json
{ "where": "tts", "message": "engine timeout", "degraded_to": "text" }
```

## `health_report` payload (one per day, written by the evaluation pass)
```json
{
  "date": "2026-06-12",
  "interactions": 23,
  "latency_p50_ms": 690, "latency_p95_ms": 1320,
  "accuracy": 0.96, "memory_hit_rate": 0.91,
  "satisfaction_inferred": 0.9,
  "design_intent": 5,
  "regressions": [],
  "vs_7day_baseline": { "latency_ms": -8, "accuracy": 0.02 }
}
```

> Daily `YYYY-MM-DD.jsonl` files are runtime, machine-local artifacts (gitignored).
> The evaluation layer writes them as ATLAS runs.
