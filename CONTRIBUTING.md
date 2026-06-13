# Contributing to ATLAS

Thanks for your interest in improving ATLAS! It's a voice-first personal
assistant built across 8 layers (identity, memory, interface, evaluation,
upgrade engine, orchestration, connectors, scheduler) — see
[`atlas/ARCHITECTURE.md`](atlas/ARCHITECTURE.md).

## Dev setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Python 3.10+ required
pip install -r requirements.txt
pytest -q                 # 25 tests, fully offline (no API key needed)
./atlas/run.sh            # http://localhost:8765 — first run shows the setup wizard
```

Optional local voice (clean neural TTS): `pip install kokoro-onnx soundfile "misaki[en]"`
and download the model files into `atlas/interface/voice/models/` (see
[`atlas/interface/voice/tts.py`](atlas/interface/voice/tts.py)).

## Ground rules

- **Tests must stay green and offline.** `pytest` sets `ATLAS_FORCE_OFFLINE=1`,
  so the suite never makes a network call. Keep new tests hermetic.
- **Never commit per-user state or secrets.** `settings.json`, `registry.json`,
  `people/owner.md`, episodic transcripts, and the TTS model files are
  gitignored; templates (`*.example.*`) ship instead. API keys live only in the
  macOS Keychain. Stage files explicitly and check your diff before committing.
- **Identity & safety are MAJOR changes.** Edits to `atlas/core/identity.md` or
  the risk-gating in `atlas/connectors/` change who ATLAS is — flag them clearly.
- **Match the surrounding style** (comment density, naming, idiom).

## Pull requests

1. Branch off `main`, keep commits small and logically scoped.
2. Run `pytest -q` (and, for UI changes, sanity-check the HUD at `localhost:8765`).
3. Describe what changed and why; link any related issue.

## Licensing of contributions

ATLAS is **source-available** under the
[PolyForm Noncommercial License 1.0.0](LICENSE) — free to use, modify, and share
for non-commercial purposes. Commercial licenses are offered separately by the
maintainer, **Nir Hemo**.

By submitting a contribution, you agree that:

- your contribution is licensed to the project under the **PolyForm Noncommercial
  License**, and
- you grant the maintainer (**Nir Hemo**) a perpetual, worldwide, irrevocable,
  royalty-free right to use, reproduce, modify, and **relicense your contribution —
  including under commercial terms** — so ATLAS can be offered under commercial
  licenses alongside the noncommercial one.

(This is a lightweight inbound license grant, not legal advice. If you can't agree
to it, please open an issue to discuss before submitting code.)
