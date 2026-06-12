"""Connector registry + risk gating (L7).

Risk classes (Section 8 / connector contract):
  READ        -> auto-allowed
  WRITE       -> allowed per settings, confirm briefly after
  DESTRUCTIVE -> ALWAYS requires explicit verbal confirmation before execution
"""
from __future__ import annotations

import enum
from typing import Any

from .. import settings as cfg


class RiskClass(str, enum.Enum):
    READ = "READ"
    WRITE = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class ConnectorRegistry:
    def __init__(self) -> None:
        self.registry = cfg.registry()
        self.orch = cfg.orchestration_config()

    def installed_ids(self) -> set[str]:
        return {c["id"] for c in self.registry.get("installed", [])}

    def is_installed(self, connector_id: str) -> bool:
        return connector_id in self.installed_ids()

    def proposed(self) -> list[dict[str, Any]]:
        return self.registry.get("proposed", [])

    def tool_risk(self, tool_name: str) -> RiskClass:
        for t in self.orch.get("tool_schema", []):
            if t["name"] == tool_name:
                return RiskClass(t.get("risk", "READ"))
        return RiskClass.READ

    def tool_connector(self, tool_name: str) -> str | None:
        for t in self.orch.get("tool_schema", []):
            if t["name"] == tool_name:
                return t.get("connector")
        return None

    def gate(self, tool_name: str, *, confirmed: bool = False) -> tuple[bool, str]:
        """Decide whether a tool call may proceed.

        Returns (allowed, reason). DESTRUCTIVE without confirmation is blocked.
        A tool whose connector isn't installed is blocked gracefully.
        """
        connector = self.tool_connector(tool_name)
        if connector and not self.is_installed(connector):
            return False, (f"The {connector} connector isn't installed yet. "
                           f"It's proposed and awaiting your approval.")
        risk = self.tool_risk(tool_name)
        if risk is RiskClass.DESTRUCTIVE and not confirmed:
            return False, ("This is a destructive action and needs your explicit "
                           "confirmation first.")
        return True, "ok"
