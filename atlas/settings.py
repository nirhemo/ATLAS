"""Settings + path resolution. settings.json is the single source of truth (L3)."""
from __future__ import annotations

import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

# Repo root = parent of the `atlas` package directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_DIR = REPO_ROOT / "atlas"

SETTINGS_PATH = ATLAS_DIR / "config" / "settings.json"
SETTINGS_EXAMPLE_PATH = ATLAS_DIR / "config" / "settings.example.json"
VERSION_PATH = ATLAS_DIR / "VERSION.json"
ORCH_CONFIG_PATH = ATLAS_DIR / "orchestration" / "config.json"
REGISTRY_PATH = ATLAS_DIR / "connectors" / "registry.json"
REGISTRY_EXAMPLE_PATH = ATLAS_DIR / "connectors" / "registry.example.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    # settings.json is gitignored (holds owner config). On a fresh clone it
    # won't exist yet — fall back to the committed template so ATLAS still runs.
    path = SETTINGS_PATH if SETTINGS_PATH.exists() else SETTINGS_EXAMPLE_PATH
    return _load_json(path)


def reload_settings() -> dict[str, Any]:
    settings.cache_clear()
    return settings()


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Persist the owner's settings to settings.json (creating it on first save,
    even on a fresh clone that was running off settings.example.json) and refresh
    the in-process cache. Written pretty-printed so it stays human-editable."""
    if not isinstance(data, dict):
        raise ValueError("settings payload must be a JSON object")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SETTINGS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return reload_settings()


@lru_cache(maxsize=1)
def git_version() -> str | None:
    """Version straight from git tags — the source of truth. Returns e.g. 'v0.2.1'
    on a release tag or 'v0.2.1-3-g1a2b3c4' a few commits later, so it advances
    automatically on every merge (CI tags each merge to main). None when this isn't
    a git checkout or has no tags yet (then VERSION.json's value is used)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "describe", "--tags", "--dirty"],
            capture_output=True, text=True, timeout=5)
        return (r.stdout.strip() or None) if r.returncode == 0 else None
    except Exception:
        return None


def version() -> dict[str, Any]:
    """Version metadata. The displayed `version` prefers git tags (so it tracks
    every merge automatically); VERSION.json's value is the fallback for non-git
    (tarball) installs and also carries the cycle/phase/layer metadata."""
    data = _load_json(VERSION_PATH)
    gv = git_version()
    if gv:
        data["version"] = gv.lstrip("v")
        data["git_version"] = gv
    return data


def orchestration_config() -> dict[str, Any]:
    return _load_json(ORCH_CONFIG_PATH)


def registry() -> dict[str, Any]:
    # registry.json holds the owner's per-user connector approvals (gitignored).
    # On a fresh clone it won't exist yet — fall back to the committed template.
    return _load_json(REGISTRY_PATH if REGISTRY_PATH.exists() else REGISTRY_EXAMPLE_PATH)


def resolve(rel: str) -> Path:
    """Resolve a settings path (relative to repo root) to an absolute Path."""
    p = Path(rel)
    return p if p.is_absolute() else REPO_ROOT / p


def vault_dir() -> Path:
    return resolve(settings()["memory"]["vault_path"])


def episodic_dir() -> Path:
    return resolve(settings()["memory"]["episodic_path"])


def logs_dir() -> Path:
    return ATLAS_DIR / "logs"
