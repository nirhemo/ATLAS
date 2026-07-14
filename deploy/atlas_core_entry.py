"""PyInstaller entry point for the frozen sidecar. Uses an ABSOLUTE import so the
`atlas` package context is intact (running atlas/server/__main__.py directly would
break its `from .. import ...` relative imports)."""
from atlas.server.__main__ import main

if __name__ == "__main__":
    main()
