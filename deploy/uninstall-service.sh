#!/usr/bin/env bash
# Remove the ATLAS LaunchAgent (stops auto-start/auto-restart).
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/com.atlas.assistant.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✓ ATLAS LaunchAgent removed. (Run it manually with: ./atlas/run.sh)"
