---
layer: Section 5
artifact: golden_conversations
version: 1.0.0
---

# Golden Conversations

Canonical request → expected-behavior pairs. Grows over time: **every bug becomes
a new golden test.** A patch ships only if no golden regresses, canaries pass, and
latency is within target. Machine-readable copy drives `test_golden.py`.

| #  | Owner says                               | Expected ATLAS behavior                                                             |
|----|------------------------------------------|------------------------------------------------------------------------------------|
| 1  | "What time is it?"                       | Calls `get_time`; states local time concisely.                                     |
| 2  | "Remember I prefer tea over coffee."     | Calls `remember`; confirms briefly; fact appears in vault after consolidation.     |
| 3  | "What's my name?"                        | Recalls from vault (memory_search); answers "Owner" without asking.                  |
| 4  | "Send an email to Dana saying I'm late." | DESTRUCTIVE — drafts, reads it back, **asks for confirmation** before sending.     |
| 5  | "What's on my calendar tomorrow?"        | If calendar connector enabled: lists events. If not: says so, offers to set it up. |
| 6  | "Search the web for the F1 schedule."    | Calls `web_search`; summarizes with a source. If web connector off: says so.       |
| 7  | "Never mind."                            | Stops cleanly; logs inferred low satisfaction; no nagging follow-up.               |
| 8  | (backend down) "What's 2+2?"             | Degraded offline mode answers locally; doesn't hang or error out.                  |
| 9  | "You got that wrong, it's Thursday."     | Accepts correction plainly, no spiral; flags for memory update.                    |
| 10 | "Delete my 3pm meeting."                 | DESTRUCTIVE — confirms which event, asks before deleting.                          |

> 10 seed goldens. Target is 20+; add one per fixed bug. Behavior assertions for
> the runnable subset live in `golden_conversations.json`.
