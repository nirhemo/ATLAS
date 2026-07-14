"""Web search: rich results (images + article) + the article reader. Hermetic —
no network; extraction and wiring are tested with monkeypatched providers."""
from __future__ import annotations

from atlas.connectors import web_search as ws
from atlas.orchestration.tools import ToolBox


def test_extract_text_pulls_paragraphs_and_drops_chrome():
    html = ("<html><head><title>Hello World</title></head><body>"
            "<script>junk()</script><nav>menu</nav>"
            "<article><p>This is a sufficiently long paragraph about the topic at hand.</p>"
            "<p>short</p><p>Another long and meaningful paragraph with real content here.</p>"
            "</article></body></html>")
    out = ws._extract_text(html)
    assert "Hello World" in out
    assert "sufficiently long paragraph" in out
    assert "Another long and meaningful" in out
    assert "junk()" not in out and "menu" not in out     # script/nav stripped
    assert "short" not in out                            # <40 chars dropped


def test_read_article_rejects_non_url():
    assert "search for something" in ws.read_article("not a url").lower()


def test_rich_shapes_media(monkeypatch):
    monkeypatch.setattr(ws, "_rows", lambda q, n, web: [("Title A", "Body A", "https://a.example/post")])
    monkeypatch.setattr(ws, "_images", lambda q, n=6: [
        {"image": "https://img/1.jpg", "thumbnail": "https://img/1t.jpg",
         "source": "https://a.example", "title": "one"}])
    d = ws.rich("quantum computing")
    assert d["query"] == "quantum computing"
    assert d["images"][0]["image"].endswith("1.jpg")
    assert d["article"]["url"] == "https://a.example/post"
    assert d["article"]["image"] == "https://img/1.jpg"
    assert "Web results" in d["text"]


def test_rich_numbers_results_for_open_article_n(monkeypatch):
    rows = [("A", "sa", "https://a"), ("B", "sb", "https://b"), ("C", "sc", "https://c")]
    monkeypatch.setattr(ws, "_rows", lambda q, n, web: rows)
    monkeypatch.setattr(ws, "_images", lambda q, n=6: [
        {"image": f"https://img/{i}.jpg", "thumbnail": "", "source": "", "title": ""} for i in range(3)])
    d = ws.rich("news")
    assert [r["n"] for r in d["results"]] == [1, 2, 3]          # numbered for "open article N"
    assert d["results"][1]["url"] == "https://b"                # article 2 → second result
    assert d["results"][2]["image"] == "https://img/2.jpg"      # thumbnail zipped by index
    assert d["article"]["url"] == "https://a"                   # top result


def test_toolbox_web_search_sets_last_media(monkeypatch):
    monkeypatch.setattr(ws, "rich", lambda q: {
        "query": q, "text": "the text for the model",
        "images": [{"image": "x", "thumbnail": "x", "source": "s", "title": "t"}],
        "article": {"title": "T", "url": "https://u", "summary": "s", "image": "x"}})
    tb = ToolBox()
    out = tb._t_web_search({"query": "cats"})
    assert out == "the text for the model"                # model gets the text
    assert tb.last_media["type"] == "search"
    assert tb.last_media["article"]["url"] == "https://u"  # HUD gets the visuals
    assert len(tb.last_media["images"]) == 1


def test_toolbox_read_article_defaults_to_last_article(monkeypatch):
    captured = {}

    def fake_read(url):
        captured["url"] = url
        return "READ"

    monkeypatch.setattr(ws, "read_article", fake_read)
    tb = ToolBox()
    tb.last_media = {"article": {"url": "https://last-article"}}
    assert tb._t_read_article({}) == "READ"               # no url → uses last article
    assert captured["url"] == "https://last-article"
