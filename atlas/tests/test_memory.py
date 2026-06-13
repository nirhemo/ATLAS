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


def test_context_block_surfaces_owner_and_preferences(tmp_path):
    # The context block is what gets injected into the system prompt each turn.
    store = _seed(tmp_path)
    # a just-stated reminder must be honored IMMEDIATELY (before consolidation)
    store.remember("Use metric units (km, °C, kg)", entity="units")
    block = store.context_block()
    assert "Owner" in block
    assert "voice-friendly" in block               # owner.md profile bullets
    assert "metric" in block.lower()               # pending reminder, pre-consolidation
    # ...and it still surfaces after it's consolidated into a durable note
    store.consolidate()
    assert "metric" in store.context_block().lower()


def test_context_block_empty_vault_is_blank(tmp_path):
    store = VaultStore(vault=tmp_path / "v", episodic=tmp_path / "e")
    assert store.context_block() == ""


def test_history_messages_returns_session_turns_in_order(tmp_path):
    store = _seed(tmp_path)
    store.log_turn(user="my name is Nir", reply="Nice to meet you, Nir.",
                   backend="x", session="s1", turn=1)
    store.log_turn(user="what's the weather like?", reply="Sunny, 22°C.",
                   backend="x", session="s1", turn=2)
    store.log_turn(user="different chat", reply="ok", backend="x", session="s2", turn=1)
    msgs = store.history_messages("s1")
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "my name is Nir"           # oldest first
    assert all("different chat" not in m["content"] for m in msgs)  # other session excluded


def test_history_messages_respects_limit(tmp_path):
    store = _seed(tmp_path)
    for i in range(10):
        store.log_turn(user=f"u{i}", reply=f"a{i}", backend="x", session="s1", turn=i)
    msgs = store.history_messages("s1", limit=3)
    assert len(msgs) == 6                  # last 3 turns × (user + assistant)
    assert msgs[0]["content"] == "u7"      # the oldest of the last three


def test_history_messages_blank_without_session(tmp_path):
    store = _seed(tmp_path)
    store.log_turn(user="hi", reply="hello", backend="x", session="s1", turn=1)
    assert store.history_messages("") == []


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


def test_memory_writing_paused_blocks_writes(tmp_path, monkeypatch):
    from atlas.memory import store as store_mod
    store = _seed(tmp_path)
    monkeypatch.setattr(store_mod.cfg, "settings",
                        lambda: {"memory": {"memory_writing_paused": True}})
    assert "paused" in store.remember("secret", entity="x").lower()
    assert store._pending_remembers() == []          # nothing was queued
    assert store.consolidate()["status"] == "paused"


def test_forget_removes_consolidated_fact(tmp_path):
    store = _seed(tmp_path)
    store.remember("Allergic to peanuts", entity="health")
    store.consolidate()
    note = tmp_path / "vault" / "preferences" / "health.md"
    assert note.exists() and "peanuts" in note.read_text(encoding="utf-8").lower()
    assert "forgotten" in store.forget(entity="health").lower()
    assert not note.exists()                          # last fact gone → note removed


def test_consolidate_dedups_repeated_fact(tmp_path):
    store = _seed(tmp_path)
    store.remember("Likes window seats", entity="travel"); store.consolidate()
    store.remember("Likes window seats", entity="travel"); store.consolidate()
    note = (tmp_path / "vault" / "preferences" / "travel.md").read_text(encoding="utf-8")
    assert note.lower().count("window seats") == 1    # no duplicate bullet


def test_context_block_includes_prose_and_other_notes(tmp_path):
    store = _seed(tmp_path)
    proj = tmp_path / "vault" / "projects"; proj.mkdir(parents=True)
    (proj / "trip.md").write_text(
        "---\ntype: project\n---\n\n# Italy Trip\n\nFlying to Rome on 12 July.\n",
        encoding="utf-8")
    block = store.context_block()
    assert "Italy Trip" in block                      # non-preference note surfaced
    assert "Rome" in block                            # prose fact captured (not a bullet)


def test_example_jsonl_never_consolidated(tmp_path):
    store = _seed(tmp_path)
    (tmp_path / "epis" / "example.jsonl").write_text(
        '{"action":"remember","fact":"SAMPLE ignore me","entity":"demo"}\n', encoding="utf-8")
    assert store._pending_remembers() == []           # date-named glob excludes example.jsonl
    assert store.consolidate()["lines_processed"] == 0


def test_decay_stale_lowers_confidence(tmp_path):
    store = _seed(tmp_path)
    prefs = tmp_path / "vault" / "preferences"; prefs.mkdir(parents=True)
    (prefs / "old.md").write_text(
        "---\ntype: preference\nupdated: 2020-01-01\nconfidence: 0.7\n"
        "owner_edited: false\n---\n\n# Old\n\n- stale fact\n", encoding="utf-8")
    assert store._decay_stale() == 1
    meta, _ = _parse_frontmatter((prefs / "old.md").read_text(encoding="utf-8"))
    assert meta["confidence"] < 0.7
