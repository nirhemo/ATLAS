"""Web search connector (L7). READ-only — current facts the model can cite.

Default provider is **DuckDuckGo** (no API key, works out of the box). Tavily or
Brave can be selected in settings for higher quality; their key is read from the
env or the macOS Keychain (never stored in settings.json). All failures degrade
to an honest message rather than raising into the chat path.
"""
from __future__ import annotations

import os
from typing import Any

from .. import settings as cfg


def _web_cfg() -> dict[str, Any]:
    return cfg.settings().get("web") or {}


def _key(web: dict[str, Any], env_name: str) -> str | None:
    """API key from env first, then macOS Keychain via the configured ref."""
    if os.environ.get(env_name):
        return os.environ[env_name]
    from ..orchestration.router import keychain_secret  # lazy: avoid import cycle
    return keychain_secret(web.get("api_key_ref"))


def _format(rows: list[tuple[str, str, str]], query: str) -> str:
    if not rows:
        return f"No web results for '{query}'."
    out = [f"Web results for '{query}':"]
    for i, (title, body, url) in enumerate(rows, 1):
        out.append(f"{i}. {title}\n   {body}\n   {url}")
    out.append("\n(Cite the sources by URL when you use them.)")
    return "\n".join(out)


def search(query: str, *, max_results: int | None = None) -> str:
    query = (query or "").strip()
    if not query:
        return "No search query provided."
    web = _web_cfg()
    n = max_results or web.get("max_results", 5)
    provider = (web.get("provider") or "duckduckgo").lower()
    try:
        if provider == "duckduckgo":
            return _ddg(query, n)
        if provider == "tavily":
            return _tavily(query, n, _key(web, "TAVILY_API_KEY"))
        if provider == "brave":
            return _brave(query, n, _key(web, "BRAVE_API_KEY"))
        return f"Unknown search provider '{provider}'. Use duckduckgo, tavily, or brave."
    except Exception as exc:  # network / parse / rate-limit — stay graceful
        return f"Web search failed ({type(exc).__name__}). Try again shortly."


def _ddg(query: str, n: int) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        return "Web search needs the 'ddgs' package (pip install ddgs)."
    with DDGS() as d:
        res = list(d.text(query, max_results=n))
    return _format([(r.get("title", ""), r.get("body", ""), r.get("href", "")) for r in res], query)


def _tavily(query: str, n: int, key: str | None) -> str:
    if not key:
        return "Tavily selected but no key found. Add TAVILY_API_KEY (env or Keychain)."
    import httpx
    r = httpx.post("https://api.tavily.com/search", json={
        "api_key": key, "query": query, "max_results": n, "include_answer": False,
    }, timeout=15.0)
    r.raise_for_status()
    data = r.json()
    rows = [(x.get("title", ""), x.get("content", ""), x.get("url", "")) for x in data.get("results", [])]
    return _format(rows, query)


def _brave(query: str, n: int, key: str | None) -> str:
    if not key:
        return "Brave selected but no key found. Add BRAVE_API_KEY (env or Keychain)."
    import httpx
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                  params={"q": query, "count": n},
                  headers={"X-Subscription-Token": key, "Accept": "application/json"},
                  timeout=15.0)
    r.raise_for_status()
    rows = [(x.get("title", ""), x.get("description", ""), x.get("url", ""))
            for x in r.json().get("web", {}).get("results", [])]
    return _format(rows, query)
