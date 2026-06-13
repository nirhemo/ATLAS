"""Uniform tool layer (L6). Tools are defined once in orchestration/config.json
and dispatched here. READ/WRITE tools that need no connector run locally;
connector-backed tools degrade gracefully until their connector is installed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..connectors.loader import ConnectorRegistry
from ..memory.store import VaultStore


def anthropic_tools() -> list[dict[str, Any]]:
    """Build the Anthropic tool-use schema from orchestration/config.json."""
    from .. import settings as cfg
    out = []
    for t in cfg.orchestration_config().get("tool_schema", []):
        out.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t.get("input_schema", {"type": "object", "properties": {}}),
        })
    return out


def openai_tools(registry: "ConnectorRegistry | None" = None) -> list[dict[str, Any]]:
    """Same tool schema in OpenAI function-calling format, for local models
    (mlx-lm / LM Studio / Ollama). Tools whose connector isn't installed are
    omitted so a weaker local model isn't tempted to call something that can't
    run; native tools (get_time, memory_search, remember, web_search) stay."""
    from .. import settings as cfg
    reg = registry or ConnectorRegistry()
    installed = reg.installed_ids()
    out = []
    for t in cfg.orchestration_config().get("tool_schema", []):
        conn = t.get("connector")
        if conn and conn not in installed:
            continue
        out.append({"type": "function", "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
        }})
    return out


class ToolBox:
    def __init__(self, vault: VaultStore | None = None,
                 registry: ConnectorRegistry | None = None):
        self.vault = vault or VaultStore()
        self.registry = registry or ConnectorRegistry()

    def dispatch(self, name: str, args: dict[str, Any], *,
                 confirmed: bool = False) -> str:
        allowed, reason = self.registry.gate(name, confirmed=confirmed)
        if not allowed:
            return reason

        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            connector = self.registry.tool_connector(name)
            if connector:
                return (f"The {connector} connector isn't wired up in this build yet, "
                        f"so I can't run {name}.")
            return f"I don't have a tool called {name}."
        return handler(args)

    # ----- local tools -------------------------------------------------- #
    def _t_get_time(self, args: dict[str, Any]) -> str:
        return datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")

    def _t_memory_search(self, args: dict[str, Any]) -> str:
        query = args.get("query", "")
        hits = self.vault.search(query)
        if not hits:
            return "No matching notes in the vault."
        return "\n\n---\n\n".join(n.to_context() for n, _ in hits)

    def _t_remember(self, args: dict[str, Any]) -> str:
        return self.vault.remember(args.get("fact", ""), args.get("entity"))

    def _t_forget(self, args: dict[str, Any]) -> str:
        return self.vault.forget(args.get("fact"), args.get("entity"))

    def _t_web_search(self, args: dict[str, Any]) -> str:
        from ..connectors.web_search import search
        return search(args.get("query", ""))

    def _t_atlas_status(self, args: dict[str, Any]) -> str:
        """Introspect ATLAS's own layers/state so the model can answer questions
        about itself (jobs, connectors, model/routing, memory, version)."""
        from .. import settings as cfg
        area = (args.get("area") or "overview").lower()

        if area == "scheduler":
            from ..scheduler import Scheduler
            jobs = Scheduler().status()
            if not jobs:
                return "No scheduled jobs configured (L8 scheduler)."
            out = ["Scheduled jobs (L8 scheduler):"]
            for j in jobs:
                s = j.get("schedule", {})
                out.append(f"- {j['id']}: {s.get('type','')} at {s.get('at','')} · "
                           f"risk {j.get('risk')} · next {j.get('next_run')} · "
                           f"last {j.get('last_status') or 'never run'}")
            return "\n".join(out)

        if area == "connectors":
            inst = sorted(self.registry.installed_ids())
            prop = [c["id"] for c in self.registry.proposed()]
            return (f"Connectors (L7) — installed: {', '.join(inst) or 'none'}; "
                    f"proposed (awaiting your approval): {', '.join(prop) or 'none'}.")

        if area == "model":
            m = cfg.settings().get("model", {})
            r = m.get("routing") or {}
            if r.get("enabled"):
                tiers = "; ".join(f"{k}→{(v or {}).get('model')}"
                                  for k, v in (r.get("tiers") or {}).items())
                return f"Model (L6): task routing ON — {tiers}."
            return (f"Model (L6): mode={m.get('mode')}, "
                    f"active={m.get('backend') if m.get('mode')=='api' else (m.get(m.get('mode'),{}) or {}).get('model')}, "
                    f"routing OFF.")

        if area == "memory":
            vault = cfg.vault_dir()
            notes = len(list(vault.rglob("*.md"))) if vault.exists() else 0
            turns = len(self.vault.recent_turns(9999))
            return (f"Memory (L2): {notes} vault notes; {turns} saved conversation "
                    f"turns in recent episodic logs. Retrieval + nightly consolidation.")

        # overview
        v = cfg.version()
        m = cfg.settings().get("model", {})
        from ..scheduler import Scheduler
        njobs = len(Scheduler().status())
        inst = sorted(self.registry.installed_ids())
        routing = (m.get("routing") or {}).get("enabled")
        return (
            f"ATLAS v{v.get('version')} (Cycle {v.get('cycle')}, Phase {v.get('phase')}). "
            "Seven layers: L1 core identity, L2 memory, L3 interface/voice, "
            "L4 evaluation, L5 upgrade engine, L6 orchestration, L7 connectors, "
            "L8 scheduler. "
            f"Model: {'task-routing ON' if routing else m.get('mode')}. "
            f"{njobs} scheduled jobs. Connectors installed: {', '.join(inst) or 'none'}. "
            "Tools: time, web search, memory recall + remember, self-status. "
            "Ask for a specific area — scheduler, connectors, model, or memory — for detail."
        )
