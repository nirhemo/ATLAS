"""Web search connector (L7). READ-only — current facts the model can cite, plus
RICH results (related images + the top article) for the visual HUD, and an article
reader so ATLAS can summarize / TLDR / read a page aloud on request.

Default provider is DuckDuckGo (no key). Tavily/Brave selectable in settings; keys
come from env or the macOS Keychain. All failures degrade to an honest message
rather than raising into the chat path.
"""
from __future__ import annotations

import os
from typing import Any

from .. import settings as cfg

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125 Safari/537.36")


def _web_cfg() -> dict[str, Any]:
    return cfg.settings().get("web") or {}


def _key(web: dict[str, Any], env_name: str) -> str | None:
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


# ----- provider row-getters → (title, body, url) ------------------------- #
def _ddg_rows(query: str, n: int) -> list[tuple[str, str, str]]:
    from ddgs import DDGS
    with DDGS() as d:
        res = list(d.text(query, max_results=n))
    return [(r.get("title", ""), r.get("body", ""), r.get("href", "")) for r in res]


def _tavily_rows(query: str, n: int, key: str) -> list[tuple[str, str, str]]:
    import httpx
    r = httpx.post("https://api.tavily.com/search", json={
        "api_key": key, "query": query, "max_results": n, "include_answer": False}, timeout=15.0)
    r.raise_for_status()
    return [(x.get("title", ""), x.get("content", ""), x.get("url", "")) for x in r.json().get("results", [])]


def _brave_rows(query: str, n: int, key: str) -> list[tuple[str, str, str]]:
    import httpx
    r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                  params={"q": query, "count": n},
                  headers={"X-Subscription-Token": key, "Accept": "application/json"}, timeout=15.0)
    r.raise_for_status()
    return [(x.get("title", ""), x.get("description", ""), x.get("url", ""))
            for x in r.json().get("web", {}).get("results", [])]


def _rows(query: str, n: int, web: dict[str, Any]) -> list[tuple[str, str, str]]:
    provider = (web.get("provider") or "duckduckgo").lower()
    if provider == "duckduckgo":
        try:
            import ddgs  # noqa: F401
        except ImportError:
            raise RuntimeError("ddgs-missing")
        return _ddg_rows(query, n)
    if provider == "tavily":
        key = _key(web, "TAVILY_API_KEY")
        if not key:
            raise RuntimeError("no-tavily-key")
        return _tavily_rows(query, n, key)
    if provider == "brave":
        key = _key(web, "BRAVE_API_KEY")
        if not key:
            raise RuntimeError("no-brave-key")
        return _brave_rows(query, n, key)
    raise RuntimeError(f"unknown-provider:{provider}")


def search(query: str, *, max_results: int | None = None) -> str:
    """Plain-text results for the model (with source URLs to cite)."""
    query = (query or "").strip()
    if not query:
        return "No search query provided."
    web = _web_cfg()
    n = max_results or web.get("max_results", 5)
    try:
        return _format(_rows(query, n, web), query)
    except RuntimeError as exc:
        m = str(exc)
        if m == "ddgs-missing":
            return "Web search needs the 'ddgs' package (pip install ddgs)."
        if m.startswith("no-"):
            return f"Search provider needs an API key ({m})."
        return f"Web search unavailable ({m})."
    except Exception as exc:  # network / parse / rate-limit — stay graceful
        return f"Web search failed ({type(exc).__name__}). Try again shortly."


# ----- images (for the floating photos on the HUD) ----------------------- #
def _images(query: str, n: int = 6) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS
        with DDGS() as d:
            res = list(d.images(query, max_results=n))
    except Exception:
        return []
    out: list[dict[str, str]] = []
    for r in res:
        img = r.get("image")
        if not img:
            continue
        out.append({"image": img, "thumbnail": r.get("thumbnail") or img,
                    "source": r.get("url") or img, "title": r.get("title", "")})
    return out


def rich(query: str, *, max_results: int | None = None) -> dict[str, Any]:
    """Text (for the model) + related images + the top article (for the HUD)."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "text": "No search query provided.", "images": [], "article": None}
    web = _web_cfg()
    n = max_results or web.get("max_results", 5)
    try:
        rows = _rows(query, n, web)
        text = _format(rows, query)
    except Exception as exc:
        rows, text = [], f"Web search failed ({type(exc).__name__})."
    images = _images(query, max(n + 1, 6))
    article = None
    if rows:
        title, body, url = rows[0]
        article = {"title": title, "url": url, "summary": body,
                   "image": images[0]["image"] if images else None}
    return {"query": query, "text": text, "images": images, "article": article}


# ----- article reader (fetch + extract main text) ------------------------ #
def read_article(url: str) -> str:
    """Fetch a page and return its readable main text so the model can summarize,
    TLDR, or read it aloud. Truncated so it fits the context window."""
    url = (url or "").strip()
    if not url.startswith("http"):
        return "There's no article URL to read yet — search for something first."
    try:
        import httpx
        r = httpx.get(url, timeout=15.0, follow_redirects=True, headers={"User-Agent": _UA})
        r.raise_for_status()
        html = r.text
    except Exception as exc:
        return f"Couldn't fetch the article ({type(exc).__name__})."
    text = _extract_text(html)
    if not text:
        return "Couldn't extract readable text from that page (it may be paywalled or JS-only)."
    return text[:6000]


def _extract_text(html: str) -> str:
    try:
        from lxml import html as lhtml
    except ImportError:
        return ""
    try:
        doc = lhtml.fromstring(html)
    except Exception:
        return ""
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//aside|//form"):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    title = (doc.findtext(".//title") or "").strip()
    nodes = doc.xpath("//article//p") or doc.xpath("//main//p") or doc.xpath("//p")
    paras = [" ".join(p.text_content().split()).strip() for p in nodes]
    paras = [p for p in paras if len(p) > 40]
    if not paras:
        return ""
    body = "\n\n".join(paras)
    return (f"{title}\n\n{body}" if title else body).strip()
