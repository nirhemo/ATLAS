# ATLAS native app (Tauri) — build & status

ATLAS ships as a native desktop app that wraps the existing FastAPI HUD. The Python
core is unchanged: it runs as a **sidecar** (a PyInstaller-frozen binary) and the
Tauri shell points a webview at it. The localhost web HUD still works exactly as
before — Tauri is just a better front door.

## Build (macOS)
Prereqs (once): Rust (`rustup`), Tauri CLI (`cargo install tauri-cli --version ^2`),
PyInstaller (`pip install pyinstaller`), and app icons
(`cd src-tauri && cargo tauri icon ../path/to/atlas-logo.png`).

```bash
./deploy/build-app.sh     # freeze sidecar → build .app + .dmg
```

Output: `src-tauri/target/release/bundle/`.

## Signing / release
`.github/workflows/build-app.yml` builds macOS + Windows on a `v*` tag. macOS
signing + notarization activate when these repo secrets are set (never commit them):
`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`,
`APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`. Entitlements (mic + hardened runtime)
are in `src-tauri/Entitlements.plist`; the mic prompt string is in `src-tauri/Info.plist`.

## What's verified vs. needs your machine
- ✅ **Verified here:** the sidecar contract (`--port 0` → free port + `ATLAS_READY`),
  and the **frozen binary serving the API + HUD with no Python installed**.
- 🖥️ **Your on-device step:** `cargo tauri build` (long Rust compile), launching the
  GUI, granting the mic permission, and the interactive voice test.

## Windows follow-ons (Phase 5)
The shell, `/voice/ws` contract, HUD, settings, Router, and Kokoro are all
platform-agnostic and reused verbatim. Windows-specific work, staged:
- **Signing:** Azure Key Vault (HSM cert) to beat SmartScreen — add to the CI job.
- **AEC reference:** feed the WebRTC canceller a **WASAPI loopback** capture of the
  render endpoint (never RAW capture — it strips AEC). Hook in `aec.py` /
  `audio_service.py` (`aec_backend="webrtc"`).
- **Secrets:** `keychain_secret` already falls back to the OS keyring (Windows
  Credential Manager) when the macOS `security` CLI isn't present.
- **STT:** whisper.cpp on CUDA (NVIDIA) or CPU instead of Metal.
