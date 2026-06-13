#!/usr/bin/env bash
# Launch the ATLAS core (L3 server + L6 router). Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

# Optional virtualenv
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Pre-flight: ATLAS needs Python >= 3.10 (the codebase uses 3.10+ syntax).
if ! python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  PYV="$(python -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo unknown)"
  echo "✗ ATLAS requires Python 3.10+ (found ${PYV})."
  echo "  Create a venv with a newer Python, e.g.:  python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# Dependencies present?
if ! python -c 'import fastapi, uvicorn, pydantic' 2>/dev/null; then
  echo "✗ Dependencies missing. Run:  pip install -r requirements.txt"
  exit 1
fi

echo "✓ ATLAS starting → http://localhost:8765   (first run shows the setup wizard)"
exec python -m atlas.server
