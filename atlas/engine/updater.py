"""L5 self-updater — pull new ATLAS code from git, safely.

Best practice, in order: target the tracked release branch · require a clean
*tracked* tree · back up the owner's (gitignored) state · apply atomically with
`git reset --hard origin/<branch>` (a ref move, not a merge) · reinstall deps only
if requirements changed · health-gate with the test suite · auto-roll-back on
failure.

DATA SAFETY: this NEVER runs `git clean`, and all per-user state is gitignored
(settings.json, registry.json, owner.md, episodic, vault notes, TTS models,
keychain). git reset/checkout never touch gitignored or untracked files, so an
update changes ONLY code/capabilities — the owner's data and settings are
untouched. A pre-update backup is taken regardless, so rollback can restore both.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import settings as cfg
from ..evaluation.logger import log_event

ROOT = cfg.REPO_ROOT

# Gitignored per-user state backed up before an update (rollback can restore it).
_USER_STATE = [
    "atlas/config/settings.json",
    "atlas/connectors/registry.json",
    "atlas/memory/vault",
    "atlas/memory/episodic",
]


def _git(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True, timeout=timeout)


def _is_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree").returncode == 0


def _branch() -> str:
    b = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return b if b and b != "HEAD" else "main"


def _version() -> str:
    try:
        return json.loads(cfg.VERSION_PATH.read_text(encoding="utf-8")).get("version", "?")
    except Exception:
        return "?"


def check() -> dict[str, Any]:
    """How far behind the remote we are, with a changelog. No side effects beyond fetch."""
    if not _is_repo():
        return {"ok": False, "git": False,
                "detail": "Not a git checkout — clone ATLAS from GitHub to enable updates.",
                "current_version": _version()}
    if _git("fetch", "--tags", "--quiet").returncode != 0:
        return {"ok": False, "detail": "git fetch failed (offline?).", "current_version": _version()}
    branch = _branch()
    behind = int(_git("rev-list", "--count", f"HEAD..origin/{branch}").stdout.strip() or "0")
    changelog = [ln for ln in _git("log", "--oneline", "--no-decorate", "-12",
                                   f"HEAD..origin/{branch}").stdout.splitlines() if ln]
    return {
        "ok": True, "git": True, "branch": branch,
        "current_version": _version(),
        "current_commit": _git("rev-parse", "HEAD").stdout.strip()[:9],
        "behind": behind, "update_available": behind > 0,
        "changelog": changelog,
    }


def _backup_user_state() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = ROOT / "atlas" / "snapshots" / f"pre-update-{ts}"
    for rel in _USER_STATE:
        src = ROOT / rel
        if not src.exists():
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, out, dirs_exist_ok=True)
        else:
            shutil.copy2(src, out)
    return dest


def _health_check() -> tuple[bool, str]:
    """Run the test suite against the freshly-updated code."""
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "atlas/tests"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    except Exception as exc:
        return False, f"could not run tests: {type(exc).__name__}"
    line = next((l for l in reversed((r.stdout or r.stderr).splitlines()) if l.strip()), "")
    return r.returncode == 0, line.strip()


def apply(confirm: bool = False) -> dict[str, Any]:
    """Apply the update with full safety. Requires confirm=True."""
    if not confirm:
        return {"ok": False, "detail": "confirmation required"}
    info = check()
    if not info.get("ok"):
        return info
    if not info.get("update_available"):
        return {"ok": True, "applied": False, "detail": "Already up to date.", **info}

    branch = info["branch"]
    # Guard: tracked tree must be clean (gitignored/untracked are fine and preserved).
    dirty = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if dirty:
        return {"ok": False, "detail": "Local edits to tracked files — commit or stash before updating.",
                "dirty": dirty.splitlines()[:5]}

    rollback_point = _git("rev-parse", "HEAD").stdout.strip()
    backup = _backup_user_state()
    log_event("update_start", {"from_version": _version(), "behind": info["behind"], "backup": str(backup)})

    # Apply atomically — reset tracked files to the remote. NEVER `git clean`
    # (that would delete untracked user vault notes). Gitignored state untouched.
    reset = _git("reset", "--hard", f"origin/{branch}")
    if reset.returncode != 0:
        return {"ok": False, "detail": "git reset failed: " + reset.stderr.strip()}

    # Reinstall deps only if requirements changed.
    if "requirements.txt" in _git("diff", "--name-only", f"{rollback_point}..HEAD").stdout:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                       cwd=str(ROOT), capture_output=True, timeout=600)

    ok, detail = _health_check()
    if not ok:
        _git("reset", "--hard", rollback_point)   # roll back code; user data was never touched
        log_event("update_rolled_back", {"reason": detail, "restored_to": rollback_point[:9]})
        return {"ok": False, "applied": False, "rolled_back": True,
                "detail": f"Health check failed ({detail or 'tests failed'}) — rolled back, nothing lost."}

    new_commit = _git("rev-parse", "HEAD").stdout.strip()[:9]
    log_event("update_applied", {"to_version": _version(), "to_commit": new_commit, "backup": str(backup)})
    return {"ok": True, "applied": True, "needs_restart": True,
            "to_version": _version(), "to_commit": new_commit,
            "detail": "Update applied. Restart ATLAS to load the new code."}
