"""L6 Router — picks a backend, runs the tool loop, falls back gracefully.

Fallback chain (orchestration/config.json): claude-api -> local-gemma -> offline.
If the Anthropic SDK isn't installed or no API key is present, the router runs in
DEGRADED OFFLINE mode: it answers from local tools + memory and is honest about
what needs connectivity. It never hangs or bricks (Mycroft lesson, R: L6/Section 8).
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

from .. import settings as cfg
from ..evaluation.logger import log_event
from ..memory.store import VaultStore
from .tools import ToolBox, anthropic_tools


def _identity_prompt() -> str:
    p = cfg.ATLAS_DIR / "core" / "identity.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "You are ATLAS, a calm, capable, concise voice-first assistant."


class Router:
    def __init__(self) -> None:
        self.settings = cfg.settings()
        self.vault = VaultStore()
        self.tools = ToolBox(vault=self.vault)
        self._client = None
        self._backend = "offline"
        self._init_backend()

    # ----- backend selection ------------------------------------------- #
    def _init_backend(self) -> None:
        key_env = self.settings["model"].get("api_key_env", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(key_env)
        if not api_key:
            return
        try:
            import anthropic  # noqa: WPS433
            self._client = anthropic.Anthropic(api_key=api_key)
            self._backend = self.settings["model"].get("backend", "claude-sonnet-4-6")
        except Exception:
            self._client = None
            self._backend = "offline"

    @property
    def backend(self) -> str:
        return self._backend if self._client else "offline"

    # ----- public API --------------------------------------------------- #
    def chat(self, text: str, *, session: str = "s_000", turn: int = 1,
             channel: str = "chat", confirmed: bool = False) -> dict[str, Any]:
        t0 = time.monotonic()
        if self._client is not None:
            reply, used, mem_hit = self._chat_claude(text, confirmed=confirmed)
        else:
            reply, used, mem_hit = self._chat_offline(text, confirmed=confirmed)
        latency_ms = round((time.monotonic() - t0) * 1000)
        log_event("interaction", {
            "latency_ms": latency_ms, "accuracy": None, "satisfaction": None,
            "memory_hit": mem_hit, "tools_used": used, "backend": self.backend,
        }, session=session, turn=turn, channel=channel)
        return {"reply": reply, "backend": self.backend,
                "latency_ms": latency_ms, "tools_used": used}

    # ----- Claude path -------------------------------------------------- #
    def _chat_claude(self, text: str, *, confirmed: bool) -> tuple[str, list[str], int | None]:
        model = self.settings["model"].get("backend", "claude-sonnet-4-6")
        max_tokens = self.settings["model"].get("max_tokens", 1024)
        temperature = self.settings["model"].get("temperature", 0.4)
        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        used: list[str] = []
        mem_hit: int | None = None

        for _ in range(5):  # bounded tool loop
            resp = self._client.messages.create(
                model=model, max_tokens=max_tokens, temperature=temperature,
                system=_identity_prompt(), tools=anthropic_tools(),
                messages=messages,
            )
            if resp.stop_reason != "tool_use":
                parts = [b.text for b in resp.content if b.type == "text"]
                return "".join(parts).strip() or "(no reply)", used, mem_hit

            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                used.append(block.name)
                if block.name == "memory_search":
                    out = self.tools.dispatch(block.name, block.input, confirmed=confirmed)
                    mem_hit = 0 if out.startswith("No matching") else 1
                else:
                    out = self.tools.dispatch(block.name, block.input, confirmed=confirmed)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": out})
            messages.append({"role": "user", "content": results})
        return "I got stuck in a tool loop — let me stop there.", used, mem_hit

    # ----- offline degraded path --------------------------------------- #
    def _chat_offline(self, text: str, *, confirmed: bool) -> tuple[str, list[str], int | None]:
        low = text.lower().strip()

        if re.search(r"\b(time|date|what day)\b", low):
            return self.tools.dispatch("get_time", {}), ["get_time"], None

        m = re.match(r"(remember|note) (that )?(.+)", low)
        if m:
            fact = text[m.start(3):].strip()
            return self.tools.dispatch("remember", {"fact": fact}), ["remember"], None

        # try memory recall for "what/who/where is my ..." style questions
        if re.search(r"\b(my|who|what|where|name|remember|know)\b", low):
            hits = self.vault.search(text)
            if hits:
                top = hits[0][0]
                summary = _first_fact(top.body) or top.to_context()
                return summary, ["memory_search"], 1

        return (
            "I'm running in offline mode right now (no model backend connected), "
            "so I can handle time, simple recall, and noting things to remember. "
            "Set ANTHROPIC_API_KEY and restart to bring my full reasoning online.",
            [], None,
        )


def _first_fact(body: str) -> str | None:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- ") and not line.startswith("- [["):
            return line[2:].strip()
    # else first non-heading, non-blockquote paragraph
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith(">"):
            return s
    return None
