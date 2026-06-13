"""L6 Router — picks a backend, runs the tool loop, falls back gracefully.

Fallback chain (orchestration/config.json): claude-api -> local-gemma -> offline.
If the Anthropic SDK isn't installed or no API key is present, the router runs in
DEGRADED OFFLINE mode: it answers from local tools + memory and is honest about
what needs connectivity. It never hangs or bricks (Mycroft lesson, R: L6/Section 8).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
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


def keychain_secret(ref: str | None) -> str | None:
    """Read a secret from the macOS Keychain given a 'keychain:<name>' ref.
    Lets the Owner store the API key securely (never in settings.json or git)
    and have ATLAS pick it up without an env var. Returns None off-macOS or
    if the item is absent."""
    if not ref or not ref.startswith("keychain:"):
        return None
    name = ref.split(":", 1)[1]
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", name, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


# Models that reject the `temperature` sampling param (Anthropic 4.7+ / Fable).
_NO_TEMPERATURE = ("opus-4-8", "opus-4-7", "fable", "mythos")

# Cheap, no-LLM intent classifier for the task router. code > complex > daily.
_CODE_RE = re.compile(
    r"```"
    r"|\bwrite (me )?(a |an )?(script|program|function|class|regex|query)\b"
    r"|\bfix (this|the|my) (bug|code|error|function|script)\b"
    r"|\b(function|refactor|debug|compile|traceback|stack ?trace|syntax error|"
    r"regex|pytest|unit tests?|docker|kubernetes|terraform|"
    r"python|javascript|typescript|golang|rust)\b"
    r"|\bdef \b|\bnpm \b|\bpip install\b|\bgit (commit|push|clone|rebase|merge)\b",
    re.I)
_COMPLEX_RE = re.compile(
    r"\b(analy|compar|evaluat|summar|strateg|architect|research|brainstorm|optimiz)"  # stems
    r"|\b(design|draft|essay|report|proposal|breakdown|outline|plan|assess|forecast)\b"
    r"|\b(deep dive|in depth|step by step|pros and cons|trade[- ]?offs?)\b",
    re.I)


def classify_tier(text: str) -> str:
    """Route a turn by intent — no extra LLM call (keeps voice snappy).
    code → coding/debugging; complex → analysis/long/multi-part; daily → the rest."""
    t = text or ""
    if _CODE_RE.search(t):
        return "code"
    if _COMPLEX_RE.search(t) or len(t) > 280 or t.count("?") >= 2:
        return "complex"
    return "daily"


class Router:
    def __init__(self) -> None:
        self.settings = cfg.settings()
        self.vault = VaultStore()
        self.tools = ToolBox(vault=self.vault)
        self._client = None
        self._mode = "offline"          # api | local | offline
        self._backend = "offline"
        self._last_routed: str | None = None   # last model picked by the task router
        self._init_backend()

    @property
    def routing_enabled(self) -> bool:
        if os.environ.get("ATLAS_FORCE_OFFLINE"):   # hermetic tests never route/network
            return False
        return bool((self.settings.get("model", {}).get("routing") or {}).get("enabled"))

    def status_label(self) -> str:
        """What the System panel shows. With routing on, the last model that ran
        (or a ready hint); otherwise the static backend."""
        if self.routing_enabled:
            return self._last_routed or "router (ready)"
        return self.backend

    # ----- backend selection ------------------------------------------- #
    def _init_backend(self) -> None:
        # Hermetic escape hatch: tests (and CI) set ATLAS_FORCE_OFFLINE so the
        # backend is deterministic regardless of the owner's live settings.json
        # (which may be in local/api mode) and never makes a network call.
        if os.environ.get("ATLAS_FORCE_OFFLINE"):
            return
        m = self.settings["model"]
        mode = m.get("mode", "api")
        if mode == "local":
            # Local OpenAI-compatible server (mlx-lm, LM Studio, Ollama…).
            # Reachability is checked lazily on chat() so a stopped server
            # degrades gracefully instead of bricking startup.
            self._mode = "local"
            self._backend = (m.get("local") or {}).get("model") or "local"
            return
        if mode == "openrouter":
            # OpenRouter: OpenAI-compatible cloud gateway to many models.
            self._mode = "openrouter"
            self._backend = (m.get("openrouter") or {}).get("model") or "openrouter"
            return
        # API mode — key from env, else macOS Keychain.
        key_env = m.get("api_key_env", "ANTHROPIC_API_KEY")
        api_key = os.environ.get(key_env) or keychain_secret(m.get("api_key_ref"))
        if not api_key:
            return
        try:
            import anthropic  # noqa: WPS433
            self._client = anthropic.Anthropic(api_key=api_key)
            self._mode = "api"
            self._backend = m.get("backend", "claude-sonnet-4-6")
        except Exception:
            self._client = None
            self._mode = "offline"
            self._backend = "offline"

    @property
    def backend(self) -> str:
        return "offline" if self._mode == "offline" else self._backend

    def _system_prompt(self) -> str:
        """Identity + a live snapshot of what ATLAS knows about its owner, so saved
        preferences (units, language, tone, …) actually shape every reply. Without
        this, memory is write-only and the owner has to repeat themselves."""
        base = _identity_prompt()
        try:
            mem = self.vault.context_block()
        except Exception:
            mem = ""
        if not mem:
            return base
        return (base
                + "\n\n# What you know about your owner\n"
                + "Apply these standing facts and preferences in every reply "
                  "(e.g. units, language, tone, formatting). When the owner states a "
                  "new standing preference or asks you to remember something, call "
                  "the `remember` tool so it persists. When they change or retract "
                  "one, call `forget` for the old fact, then `remember` the new.\n\n"
                + mem)

    def _history(self, session: str) -> list[dict[str, Any]]:
        """Recent (user, assistant) message pairs for this session — ATLAS's
        short-term conversational memory, so it remembers what was just said.
        Bounded by memory.history_turns (default 8) to keep the prompt cheap."""
        if not session:
            return []
        n = (self.settings.get("memory") or {}).get("history_turns", 8)
        try:
            return self.vault.history_messages(session, limit=n)
        except Exception:
            return []

    # ----- public API --------------------------------------------------- #
    def chat(self, text: str, *, session: str = "s_000", turn: int = 1,
             channel: str = "chat", confirmed: bool = False) -> dict[str, Any]:
        t0 = time.monotonic()
        tier = None
        if self.routing_enabled:
            tier = classify_tier(text)
            tiers = (self.settings["model"].get("routing") or {}).get("tiers") or {}
            tcfg = tiers.get(tier) or tiers.get("daily") or {}
            model = tcfg.get("model")
            if model:
                reply, used, mem_hit = self._chat_routed(
                    text, provider=tcfg.get("provider", "openrouter"), model=model,
                    confirmed=confirmed, session=session)
                backend = model
                self._last_routed = model
            else:  # misconfigured tier → fall back to the single mode
                tier = None
                reply, used, mem_hit = self._dispatch_mode(text, confirmed=confirmed, session=session)
                backend = self.backend
        else:
            reply, used, mem_hit = self._dispatch_mode(text, confirmed=confirmed, session=session)
            backend = self.backend

        latency_ms = round((time.monotonic() - t0) * 1000)
        log_event("interaction", {
            "latency_ms": latency_ms, "accuracy": None, "satisfaction": None,
            "memory_hit": mem_hit, "tools_used": used, "backend": backend,
            "tier": tier, "routed": tier is not None,
        }, session=session, turn=turn, channel=channel)
        # Persist the conversation turn to episodic memory (every conversation is saved).
        self.vault.log_turn(user=text, reply=reply,
                            backend=(f"{tier}:{backend}" if tier else backend),
                            tools=used, session=session, turn=turn)
        return {"reply": reply, "backend": backend, "tier": tier,
                "latency_ms": latency_ms, "tools_used": used}

    def _dispatch_mode(self, text: str, *, confirmed: bool,
                       session: str = "") -> tuple[str, list[str], int | None]:
        """Single-backend dispatch (when routing is off)."""
        if self._mode == "api" and self._client is not None:
            return self._chat_claude(text, confirmed=confirmed, session=session)
        if self._mode == "openrouter":
            return self._chat_openrouter(text, confirmed=confirmed, session=session)
        if self._mode == "local":
            return self._chat_local(text, confirmed=confirmed, session=session)
        return self._chat_offline(text, confirmed=confirmed)

    def _chat_routed(self, text: str, *, provider: str, model: str,
                     confirmed: bool, session: str = "") -> tuple[str, list[str], int | None]:
        """Dispatch one turn to a specific (provider, model) chosen by the router."""
        m = self.settings["model"]
        if provider == "openrouter":
            orc = m.get("openrouter") or {}
            key = os.environ.get(orc.get("api_key_env", "OPENROUTER_API_KEY")) \
                or keychain_secret(orc.get("api_key_ref"))
            return self._chat_openai_compatible(
                text, confirmed=confirmed, session=session,
                endpoint=orc.get("endpoint", "https://openrouter.ai/api/v1"),
                model=model, auth_key=key,
                extra_headers={"HTTP-Referer": "https://github.com/nirhemo/ATLAS", "X-Title": "ATLAS"},
                offline_note="OpenRouter isn't reachable — check your API key. Answering offline meanwhile.")
        if provider == "local":
            local = m.get("local") or {}
            return self._chat_openai_compatible(
                text, confirmed=confirmed, session=session,
                endpoint=local.get("endpoint", "http://localhost:8080/v1"), model=model,
                offline_note="Local model server isn't reachable. Answering offline meanwhile.")
        if provider == "api" and self._client is not None:
            return self._chat_claude(text, confirmed=confirmed, model_override=model, session=session)
        reply, used, mh = self._chat_offline(text, confirmed=confirmed)
        return (f"(The '{provider}' backend for this task tier isn't available — "
                "answering offline.)\n\n" + reply), used, mh

    # ----- Claude path -------------------------------------------------- #
    def _chat_claude(self, text: str, *, confirmed: bool, model_override: str | None = None,
                     session: str = "") -> tuple[str, list[str], int | None]:
        model = model_override or self.settings["model"].get("backend", "claude-sonnet-4-6")
        max_tokens = self.settings["model"].get("max_tokens", 1024)
        # Opus 4.7+/Fable reject `temperature` (HTTP 400) — only send it when allowed.
        extra: dict[str, Any] = ({} if any(t in model for t in _NO_TEMPERATURE)
                                 else {"temperature": self.settings["model"].get("temperature", 0.4)})
        # Prepend recent session turns so ATLAS remembers the conversation so far.
        sys_prompt = self._system_prompt()   # computed once, reused across the loop
        messages: list[dict[str, Any]] = [*self._history(session),
                                          {"role": "user", "content": text}]
        used: list[str] = []
        mem_hit: int | None = None

        for _ in range(5):  # bounded tool loop
            resp = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=sys_prompt,
                tools=anthropic_tools(), messages=messages, **extra,
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

    # ----- OpenAI-compatible paths (local MLX + OpenRouter) ------------- #
    def _chat_local(self, text: str, *, confirmed: bool,
                    session: str = "") -> tuple[str, list[str], int | None]:
        """Local OpenAI-compatible server (mlx-lm / LM Studio / Ollama)."""
        local = self.settings["model"].get("local") or {}
        return self._chat_openai_compatible(
            text, confirmed=confirmed, session=session,
            endpoint=local.get("endpoint", "http://localhost:8080/v1"),
            model=local.get("model"),
            offline_note="My local model server isn't reachable — start it with "
                         "`mlx_lm.server`. Answering in offline mode meanwhile.")

    def _chat_openrouter(self, text: str, *, confirmed: bool,
                         session: str = "") -> tuple[str, list[str], int | None]:
        """OpenRouter — OpenAI-compatible cloud gateway (Bearer key)."""
        orc = self.settings["model"].get("openrouter") or {}
        key = os.environ.get(orc.get("api_key_env", "OPENROUTER_API_KEY")) \
            or keychain_secret(orc.get("api_key_ref"))
        return self._chat_openai_compatible(
            text, confirmed=confirmed, session=session,
            endpoint=orc.get("endpoint", "https://openrouter.ai/api/v1"),
            model=orc.get("model"),
            auth_key=key,
            # OpenRouter likes these for attribution; harmless if ignored.
            extra_headers={"HTTP-Referer": "https://github.com/nirhemo/ATLAS", "X-Title": "ATLAS"},
            offline_note="OpenRouter isn't reachable — check your API key and "
                         "connection. Answering in offline mode meanwhile.")

    def _chat_openai_compatible(self, text: str, *, confirmed: bool, endpoint: str,
                                model: str | None, auth_key: str | None = None,
                                extra_headers: dict[str, str] | None = None,
                                offline_note: str = "Backend unreachable.",
                                session: str = "",
                                ) -> tuple[str, list[str], int | None]:
        """Shared OpenAI-compatible chat with a bounded tool loop — same tools as
        the Claude path (get_time, memory_search, remember, web_search). On any
        failure (server down, bad key) it degrades to the honest offline path."""
        import httpx
        from .tools import openai_tools

        endpoint = (endpoint or "").rstrip("/")
        tools = openai_tools(self.tools.registry)
        headers: dict[str, str] = {}
        if auth_key:
            headers["Authorization"] = f"Bearer {auth_key}"
        if extra_headers:
            headers.update(extra_headers)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            *self._history(session),
            {"role": "user", "content": text},
        ]
        used: list[str] = []
        mem_hit: int | None = None

        try:
            for _ in range(5):  # bounded tool loop
                r = httpx.post(
                    f"{endpoint}/chat/completions",
                    headers=headers,
                    json={
                        "model": model, "messages": messages, "tools": tools,
                        "max_tokens": self.settings["model"].get("max_tokens", 1024),
                        "temperature": self.settings["model"].get("temperature", 0.4),
                        "stream": False,
                    },
                    timeout=180.0,
                )
                r.raise_for_status()
                msg = r.json()["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                if not calls:
                    # Reasoning models emit 'reasoning' then 'content'; prefer content.
                    reply = (msg.get("content") or "").strip() or (msg.get("reasoning") or "").strip()
                    return reply or "(no reply)", used, mem_hit

                messages.append({"role": "assistant", "content": msg.get("content") or "",
                                 "tool_calls": calls})
                for tc in calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    raw = fn.get("arguments")
                    try:
                        a = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    except (ValueError, TypeError):
                        a = {}
                    used.append(name)
                    out = self.tools.dispatch(name, a, confirmed=confirmed)
                    if name == "memory_search":
                        mem_hit = 0 if out.startswith("No matching") else 1
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                     "content": out})
            return "I got stuck in a tool loop — let me stop there.", used, mem_hit
        except Exception:
            reply, off_used, off_hit = self._chat_offline(text, confirmed=confirmed)
            return f"({offline_note})\n\n" + reply, used + off_used, mem_hit if mem_hit is not None else off_hit

    # ----- offline degraded path --------------------------------------- #
    def _chat_offline(self, text: str, *, confirmed: bool) -> tuple[str, list[str], int | None]:
        stripped = text.strip()
        low = stripped.lower()

        if re.search(r"\b(time|date|what day)\b", low):
            return self.tools.dispatch("get_time", {}), ["get_time"], None

        # Match on the stripped ORIGINAL text so the captured fact keeps its
        # casing and offsets line up (don't slice raw text with stripped offsets).
        m = re.match(r"(?:remember|note)\s+(?:that\s+)?(.+)", stripped,
                     re.IGNORECASE | re.DOTALL)
        if m:
            fact = m.group(1).strip()
            return self.tools.dispatch("remember", {"fact": fact}), ["remember"], None

        m = re.match(r"(?:forget|delete)\s+(?:that\s+|about\s+)?(.+)", stripped,
                     re.IGNORECASE | re.DOTALL)
        if m:
            return self.tools.dispatch("forget", {"fact": m.group(1).strip()}), ["forget"], None

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
