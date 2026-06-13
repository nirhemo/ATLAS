"""L2 memory: retrieval, remember-queue, consolidation, owner-edit protection."""
from __future__ import annotations

from atlas.memory.store import VaultStore, _parse_frontmatter, _render_note


def _seed(tmp_path):
    vault = tmp_path / "vault"
    epis = tmp_path / "epis"
    (vault / "people").mkdir(parents=True)
    (vault / "people" / "owner.md").write_text(
        "---\ntype: person\nconfidence: 0.9\nowner_edited: false\n---\n\n"
        "# Owner\n\n- The Owner of ATLAS.\n- Prefers short, voice-friendly answers.\n",
        encoding="utf-8",
    )
    return VaultStore(vault=vault, episodic=epis)


def test_frontmatter_roundtrip():
    meta, body = _parse_frontmatter("---\ntype: person\nconfidence: 0.9\n"
                                    "owner_edited: true\naliases: [a, b]\n---\n\n# T\nhi")
    assert meta["type"] == "person"
    assert meta["confidence"] == 0.9
    assert meta["owner_edited"] is True
    assert meta["aliases"] == ["a", "b"]
    assert body.startswith("# T")
    rendered = _render_note(meta, body)
    assert "owner_edited: true" in rendered


def test_search_finds_relevant_note(tmp_path):
    store = _seed(tmp_path)
    hits = store.search("who is the owner")
    assert hits, "expected at least one hit"
    assert hits[0][0].title == "Owner"


def test_remember_then_consolidate_creates_note(tmp_path):
    store = _seed(tmp_path)
    store.remember("Drinks tea, not coffee", entity="beverages")
    result = store.consolidate()
    assert result["notes_created"] == 1
    note = tmp_path / "vault" / "preferences" / "beverages.md"
    assert note.exists()
    assert "tea" in note.read_text(encoding="utf-8").lower()


def test_consolidate_is_idempotent(tmp_path):
    store = _seed(tmp_path)
    store.remember("Likes window seats", entity="travel")
    store.consolidate()
    second = store.consolidate()  # already-consolidated lines are skipped
    assert second["lines_processed"] == 0


def test_frontmatter_ignores_dash_lines_in_body(tmp_path):
    # A body that contains a '----' rule or a '---xyz' line must not be mistaken
    # for the closing frontmatter delimiter.
    meta, body = _parse_frontmatter(
        "---\ntype: topic\nconfidence: 0.9\n---\n\n# T\n\nintro\n\n----\n\nmore")
    assert meta["type"] == "topic"
    assert meta["confidence"] == 0.9
    assert "more" in body


def test_owner_edit_never_overwritten(tmp_path):
    store = _seed(tmp_path)
    prefs = tmp_path / "vault" / "preferences"
    prefs.mkdir(parents=True)
    (prefs / "beverages.md").write_text(
        "---\ntype: preference\nowner_edited: true\n---\n\n# Beverages\n\n"
        "- Owner-authored truth.\n", encoding="utf-8",
    )
    store.remember("Some machine guess", entity="beverages")
    store.consolidate()
    text = (prefs / "beverages.md").read_text(encoding="utf-8")
    assert "Owner-authored truth." in text          # not overwritten
    assert "ATLAS suggestion" in text                # appended as a suggestion
