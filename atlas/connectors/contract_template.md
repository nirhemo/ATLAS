---
layer: L7
artifact: connector_contract_template
version: 1.0.0
---

# Connector Contract Template

Every connector is an **MCP server**. ATLAS's core speaks one protocol; the
connector adapts a service to it. Reuse an existing MCP server wherever one
exists (R8) — Gmail, Slack, Google Calendar, Drive all have them. Copy this
template into a new note when proposing or installing a connector.

```yaml
id:            short_slug              # e.g. calendar
name:          Human Name
mcp_server:    package-or-url          # the existing MCP server reused
rationale:     why ATLAS needs this (ideally from a usage pattern in the logs)

capabilities:                          # what it exposes to the core
  - list_events
  - create_event

auth:
  method:            oauth | api_key | none
  credential_store:  macos_keychain    # NEVER in config or prompts (Section 8)

risk_classes:                          # per capability
  list_events:   READ                  # auto-allowed
  create_event:  WRITE                 # allowed per settings, confirm after
  delete_event:  DESTRUCTIVE           # ALWAYS verbal confirmation first

health_check:  endpoint_or_call        # surfaced on the dashboard

offline_behavior: >
  On failure, degrade gracefully — ATLAS says the service is unreachable and
  continues; it never hangs or bricks (Mycroft lesson).

status: proposed | awaiting_owner_approval | installed | disabled
```

## Rules
- **Risk gating is enforced by the core**, not the connector: READ auto-allowed,
  WRITE per `settings.json`, DESTRUCTIVE always needs explicit verbal confirmation.
- **Install = MINOR upgrade → Owner approval.** The AGE may *propose* connectors
  from usage patterns ("you ask about email daily but have no email connector"),
  but never self-installs one.
- **Secrets live in the macOS Keychain.** The registry stores a *reference*, never
  a credential.
- **Graceful degradation is mandatory.** A dead connector must not take ATLAS down.
