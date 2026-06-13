#!/usr/bin/env bash
# Install ATLAS as a macOS LaunchAgent: starts on login, auto-restarts on crash,
# and lets the self-updater restart cleanly after an update. Run once.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "✗ No Python found. Create a venv: python3.12 -m venv .venv && pip install -r requirements.txt"; exit 1; }

LABEL="com.atlas.assistant"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$REPO/atlas/logs"

sed -e "s#__REPO__#$REPO#g" -e "s#__PYTHON__#$PY#g" \
    "$REPO/deploy/com.atlas.assistant.plist" > "$PLIST"

# Reload if already installed.
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✓ ATLAS installed as a LaunchAgent and started."
echo "  → http://localhost:8765"
echo "  python:  $PY"
echo "  plist:   $PLIST"
echo "  logs:    $REPO/atlas/logs/launchd.{out,err}.log"
echo "  stop:    launchctl unload \"$PLIST\"   (or deploy/uninstall-service.sh)"
echo
echo "Note: if you already have ATLAS running manually, stop it first (the port 8765 must be free)."
