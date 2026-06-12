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
