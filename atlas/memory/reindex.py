"""Rebuild the retrieval index over the vault.

In Cycle 0 retrieval is a transparent in-memory keyword scorer (store.search),
so there is no persistent index to build — this command validates the vault and
reports note counts. When embeddings are adopted (vector_store.config.json), this
is where the sqlite-vec table gets populated. The interface stays the same.

Usage:
    python -m atlas.memory.reindex            # validate + summary
    python -m atlas.memory.reindex --full     # (future) full embedding rebuild
"""
from __future__ import annotations

import argparse

from .store import VaultStore


def main() -> None:
    ap = argparse.ArgumentParser(description="Reindex the ATLAS memory vault.")
    ap.add_argument("--full", action="store_true", help="full rebuild (embeddings)")
    args = ap.parse_args()

    store = VaultStore()
    notes = store.load_notes()
    by_type: dict[str, int] = {}
    for n in notes:
        by_type[n.type] = by_type.get(n.type, 0) + 1

    print(f"Vault: {store.vault}")
    print(f"Notes: {len(notes)}")
    for t, c in sorted(by_type.items()):
        print(f"  {t:12} {c}")
    if args.full:
        print("\n[--full] Embedding rebuild is the documented Cycle 1 upgrade "
              "(bge-small + sqlite-vec). Keyword retrieval active until then.")
    else:
        print("\nKeyword retrieval active (zero model downloads). OK.")


if __name__ == "__main__":
    main()
