#!/usr/bin/env bash
# Launch the ATLAS core (L3 server + L6 router). Run from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

# Optional virtualenv
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# ANTHROPIC_API_KEY is optional — without it, ATLAS runs in offline mode.
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo "ℹ  ANTHROPIC_API_KEY not set — starting in offline/degraded mode."
fi

exec python -m atlas.server
