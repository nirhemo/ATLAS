"""Settings + path resolution. settings.json is the single source of truth (L3)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

# Repo root = parent of the `atlas` package directory.
REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_DIR = REPO_ROOT / "atlas"

SETTINGS_PATH = ATLAS_DIR / "config" / "settings.json"
VERSION_PATH = ATLAS_DIR / "VERSION.json"
ORCH_CONFIG_PATH = ATLAS_DIR / "orchestration" / "config.json"
REGISTRY_PATH = ATLAS_DIR / "connectors" / "registry.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def settings() -> dict[str, Any]:
    return _load_json(SETTINGS_PATH)


def reload_settings() -> dict[str, Any]:
    settings.cache_clear()
    return settings()


def version() -> dict[str, Any]:
    return _load_json(VERSION_PATH)


def orchestration_config() -> dict[str, Any]:
    return _load_json(ORCH_CONFIG_PATH)


def registry() -> dict[str, Any]:
    return _load_json(REGISTRY_PATH)


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
