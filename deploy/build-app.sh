#!/usr/bin/env bash
# Build the native ATLAS desktop app (Tauri shell + frozen FastAPI sidecar).
#
#   ./deploy/build-app.sh
#
# Produces src-tauri/target/release/bundle/ (.app + .dmg on macOS).
# Prereqs (installed once): Rust (rustup), Tauri CLI (`cargo install tauri-cli --version ^2`),
# PyInstaller (`pip install pyinstaller`). Signing/notarization is CI's job (see
# .github/workflows/build-app.yml) and needs the owner's Apple Developer cert.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f src-tauri/icons/icon.icns ]; then
  echo "✗ App icons missing. Generate them once from a square PNG logo:"
  echo "    ( cd src-tauri && cargo tauri icon ../path/to/atlas-logo.png )"
  exit 1
fi

echo "==> 1/3  Freezing the FastAPI core with PyInstaller"
pyinstaller --clean -y deploy/atlas-core.spec

echo "==> 2/3  Placing the sidecar with its target-triple suffix"
TRIPLE="$(rustc -vV | awk -F': ' '/host/{print $2}')"
mkdir -p src-tauri/binaries
cp "dist/atlas-core" "src-tauri/binaries/atlas-core-${TRIPLE}"
chmod +x "src-tauri/binaries/atlas-core-${TRIPLE}"
echo "    → src-tauri/binaries/atlas-core-${TRIPLE}"

echo "==> 3/3  Building the Tauri app"
( cd src-tauri && cargo tauri build )

echo "✓ Done. Bundle in src-tauri/target/release/bundle/"
