"""L2 Memory — MemVault: read/write Markdown notes, keyword retrieval, and the
nightly consolidation pass.

Source of truth is the markdown vault. Retrieval here uses a transparent,
zero-dependency keyword scorer so ATLAS runs with NO model downloads. The
documented upgrade path (vector_store.config.json) swaps in local embeddings +
sqlite-vec without changing this module's interface — `search()` stays the same.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .. import settings as cfg

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or", "in",
    "on", "for", "with", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "me", "do", "does", "what", "whats", "who", "how", "that", "this",
}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Minimal YAML-frontmatter parser (handles the subset the vault uses:
# scalars, booleans, numbers, and inline [a, b] lists). Zero dependencies.
# --------------------------------------------------------------------------- #
def _parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if close is None:
        return {}, raw
    fm_block = "\n".join(lines[1:close])
    body = "\n".join(lines[close + 1:]).lstrip("\n")
    meta: dict[str, Any] = {}
    for line in fm_block.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = _coerce(val.strip())
    return meta, body


def _coerce(val: str) -> Any:
    if val == "" :
        return None
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        return [v.strip() for v in inner.split(",")] if inner else []
    low = val.lower()
    if low in ("true", "false"):
        return low == "true"
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    if re.fullmatch(r"-?\d*\.\d+", val):
        return float(val)
    return val


@dataclass
class Note:
    path: Path
    rel: str
    title: str
    type: str
    body: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def confidence(self) -> float:
        return float(self.meta.get("confidence", 0.8))

    @property
    def owner_edited(self) -> bool:
        return bool(self.meta.get("owner_edited", False))

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"

    def to_context(self) -> str:
        return f"[[{self.title}]] ({self.rel})\n{self.body.strip()}"


class VaultStore:
    def __init__(self, vault: Path | None = None, episodic: Path | None = None):
        self.vault = vault or cfg.vault_dir()
        self.episodic = episodic or cfg.episodic_dir()
        self.vault.mkdir(parents=True, exist_ok=True)
        self.episodic.mkdir(parents=True, exist_ok=True)
        self._notes_cache: list[Note] | None = None
        self._notes_sig: tuple = ()

    # ----- read --------------------------------------------------------- #
    def _vault_signature(self) -> tuple:
        """Cheap fingerprint of the vault (paths + mtimes) to invalidate the cache."""
        return tuple((str(p), p.stat().st_mtime_ns)
                     for p in sorted(self.vault.rglob("*.md")))

    def load_notes(self) -> list[Note]:
        sig = self._vault_signature()
        if self._notes_cache is not None and self._notes_sig == sig:
            return self._notes_cache
        notes: list[Note] = []
        for p in sorted(self.vault.rglob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            raw = p.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            title = m.group(1).strip() if m else p.stem
            notes.append(Note(
                path=p, rel=str(p.relative_to(self.vault)), title=title,
                type=str(meta.get("type", "topic")), body=body, meta=meta,
            ))
        self._notes_cache = notes
        self._notes_sig = sig
        return notes

    def search(self, query: str, top_k: int | None = None) -> list[tuple[Note, float]]:
        """Keyword TF-IDF-ish retrieval. Returns (note, score) above threshold."""
        top_k = top_k or cfg.settings()["memory"].get("retrieval_top_k", 6)
        notes = self.load_notes()
        if not notes:
            return []
        q = set(_tokens(query))
        if not q:
            return []
        # document frequency for idf
        df: dict[str, int] = {}
        doc_tokens: list[list[str]] = []
        for n in notes:
            toks = _tokens(n.text)
            doc_tokens.append(toks)
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        N = len(notes)
        scored: list[tuple[Note, float]] = []
        for n, toks in zip(notes, doc_tokens):
            if not toks:
                continue
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for t in q:
                if t in tf:
                    idf = math.log((N + 1) / (df.get(t, 0) + 1)) + 1.0
                    score += (tf[t] / len(toks)) * idf
            # small boost: title hits and confidence
            title_hits = len(q & set(_tokens(n.title)))
            score = (score + 0.25 * title_hits) * (0.5 + 0.5 * n.confidence)
            if score > 0:
                scored.append((n, round(score, 4)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ----- write -------------------------------------------------------- #
    def remember(self, fact: str, entity: str | None = None) -> str:
        """Queue a fact for tonight's consolidation (append to episodic).

        Per the consolidation spec, ATLAS does not scribble speculation straight
        into long-term memory mid-conversation. The fact is logged; the nightly
        (or manual) consolidate() pass verifies + writes it to the vault.
        """
        line = {
            "ts": _now_iso(), "role": "system", "action": "remember",
            "fact": fact, "entity": entity or "general",
        }
        f = self.episodic / f"{date.today().isoformat()}.jsonl"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        return f"Noted — I'll remember that ({entity or 'general'})."

    def log_turn(self, *, user: str, reply: str, backend: str,
                 tools: list[str] | None = None, session: str = "s_web",
                 turn: int = 1) -> None:
        """Append one conversation turn to today's episodic transcript so EVERY
        conversation is saved. Consolidation ignores these (action != 'remember').
        Best-effort — never raises into the chat path."""
        rec = {
            "ts": _now_iso(), "action": "turn", "session": session, "turn": turn,
            "backend": backend, "tools": tools or [], "user": user, "assistant": reply,
        }
        f = self.episodic / f"{date.today().isoformat()}.jsonl"
        try:
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def seed_owner(self, name: str) -> None:
        """Personalize people/owner.md with the Owner's name during onboarding,
        marked owner_edited so consolidation never overwrites it."""
        name = (name or "Owner").strip() or "Owner"
        p = self.vault / "people" / "owner.md"
        today = date.today().isoformat()
        body = (
            f"---\ntype: person\ncreated: {today}\nupdated: {today}\n"
            f"confidence: 1.0\nowner_edited: true\naliases: [Owner]\n---\n\n"
            f"# {name}\n\nThe **Owner** of ATLAS.\n\n## Facts\n"
            f"- Wake word for ATLAS is **\"Hey Atlas\"**.\n"
            f"- Prefers concise, voice-friendly answers.\n"
        )
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        except OSError:
            pass

    def recent_turns(self, limit: int = 30) -> list[dict[str, Any]]:
        """Most recent conversation turns across date-named episodic files,
        oldest→newest — powers persistent chat history."""
        turns: list[dict[str, Any]] = []
        for f in sorted(self.episodic.glob("[0-9]*.jsonl")):
            for ln in f.read_text(encoding="utf-8").splitlines():
                try:
                    o = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if o.get("action") == "turn":
                    turns.append(o)
        return turns[-limit:]

    def _pending_remembers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in sorted(self.episodic.glob("*.jsonl")):
            for ln in f.read_text(encoding="utf-8").splitlines():
                try:
                    obj = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if obj.get("action") == "remember" and not obj.get("consolidated"):
                    obj["_file"] = str(f)
                    out.append(obj)
        return out

    def consolidate(self) -> dict[str, Any]:
        """Distill queued 'remember' facts into vault notes. Create/update,
        respect owner_edited, then git-commit the vault."""
        pending = self._pending_remembers()
        created = updated = 0
        prefs_dir = self.vault / "preferences"
        prefs_dir.mkdir(parents=True, exist_ok=True)
        for item in pending:
            entity = item.get("entity", "general")
            fact = item["fact"]
            slug = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-") or "general"
            note_path = prefs_dir / f"{slug}.md"
            if note_path.exists():
                meta, body = _parse_frontmatter(note_path.read_text(encoding="utf-8"))
                if meta.get("owner_edited"):
                    # Never overwrite an Owner edit — append a marked suggestion.
                    body += f"\n\n> ATLAS suggestion ({_now_iso()}): {fact}\n"
                else:
                    body = body.rstrip() + f"\n- {fact}\n"
                # The file changed either way → record it so the activity feed shows it.
                meta["updated"] = date.today().isoformat()
                note_path.write_text(_render_note(meta, body), encoding="utf-8")
                updated += 1
            else:
                meta = {
                    "type": "preference", "created": date.today().isoformat(),
                    "updated": date.today().isoformat(), "confidence": 0.7,
                    "owner_edited": False, "source": item.get("_file", "episodic"),
                }
                body = f"# {entity.title()}\n\n- {fact}\n"
                note_path.write_text(_render_note(meta, body), encoding="utf-8")
                created += 1
        commit = self._git_commit(f"consolidation {date.today().isoformat()}")
        # mark consolidated
        self._mark_consolidated()
        return {
            "notes_created": created, "notes_updated": updated,
            "lines_processed": len(pending), "git_commit": commit,
            "status": "ok",
        }

    def _mark_consolidated(self) -> None:
        for f in sorted(self.episodic.glob("*.jsonl")):
            lines = f.read_text(encoding="utf-8").splitlines()
            changed = False
            out = []
            for ln in lines:
                try:
                    obj = json.loads(ln)
                except json.JSONDecodeError:
                    out.append(ln)
                    continue
                if obj.get("action") == "remember" and not obj.get("consolidated"):
                    obj["consolidated"] = True
                    changed = True
                out.append(json.dumps(obj, ensure_ascii=False))
            if changed:
                f.write_text("\n".join(out) + "\n", encoding="utf-8")

    def init_git(self) -> bool:
        """Make the vault a standalone git repo (deployment step, run once).

        Not called in the monorepo bootstrap — there the vault shares the product
        repo and consolidation skips committing. On the Mac, run this once so
        nightly consolidation gets its own `git diff` / `git revert` history.
        """
        try:
            top = subprocess.run(
                ["git", "-C", str(self.vault), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True)
            if top.returncode == 0 and Path(top.stdout.strip()).resolve() == self.vault.resolve():
                return True  # already its own repo
            subprocess.run(["git", "init", str(self.vault)], check=True, capture_output=True)
            self._git_commit("init vault")
            return True
        except Exception:
            return False

    def _git_commit(self, msg: str) -> str | None:
        """Auto-commit the vault iff the vault is its OWN git repo root.

        In production the vault is a standalone git repo (`git init` in the vault)
        so `git diff`/`git revert` work per Section 2. If the vault merely lives
        inside some parent repo (as in this monorepo bootstrap), we must NOT commit
        — that would pollute the parent's history. In that case we skip silently.
        """
        try:
            top = subprocess.run(
                ["git", "-C", str(self.vault), "rev-parse", "--show-toplevel"],
                capture_output=True, text=True)
            if top.returncode != 0:
                return None  # not a git repo at all
            if Path(top.stdout.strip()).resolve() != self.vault.resolve():
                return None  # vault is not its own repo root — don't touch parent
            subprocess.run(["git", "-C", str(self.vault), "add", "-A"],
                           check=True, capture_output=True)
            r = subprocess.run(["git", "-C", str(self.vault), "commit", "-m", msg],
                               capture_output=True, text=True)
            if r.returncode != 0:
                return None
            h = subprocess.run(["git", "-C", str(self.vault), "rev-parse", "HEAD"],
                               capture_output=True, text=True)
            return h.stdout.strip()[:10] or None
        except Exception:
            return None

    # ----- dashboard ---------------------------------------------------- #
    def recent_activity(self, limit: int = 8) -> list[dict[str, str]]:
        items = []
        for n in self.load_notes():
            updated = str(n.meta.get("updated", n.meta.get("created", "")))
            created = str(n.meta.get("created", ""))
            kind = "updated" if updated and updated != created else "created"
            items.append({"kind": kind, "title": n.title, "ago": updated or "—"})
        items.sort(key=lambda x: x["ago"], reverse=True)
        return items[:limit]


def _render_note(meta: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, list):
            v = "[" + ", ".join(map(str, v)) + "]"
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")
