"""Local neural TTS (L3) — Kokoro via kokoro-onnx.

A clean, natural voice that runs entirely on-device (no cloud, no key). The model
is loaded once and reused. If kokoro-onnx or the model files aren't present, synth
returns None and the browser falls back to the OS Web Speech voice — ATLAS never
loses its voice, it just sounds less polished.

Model files (gitignored, ~335MB) live in ./models/:
  kokoro-v1.0.onnx, voices-v1.0.bin
  from https://github.com/thewh1teagle/kokoro-onnx/releases (model-files-v1.0)
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "models"
_ONNX = _DIR / "kokoro-v1.0.onnx"
_VOICES = _DIR / "voices-v1.0.bin"

_LOCK = threading.Lock()      # MLX/ORT inference: serialize across request threads
_ENGINE = None
_TRIED = False


_DOWNLOADING = False

# Voice catalog for the onboarding/settings picker (bm_* = British, am_/af_ = US).
VOICES = [
    {"id": "bm_george", "label": "George (British male) — Jarvis-like"},
    {"id": "bm_lewis", "label": "Lewis (British male)"},
    {"id": "am_michael", "label": "Michael (US male)"},
    {"id": "af_heart", "label": "Heart (US female)"},
    {"id": "bf_emma", "label": "Emma (British female)"},
]

_MODEL_URLS = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


def models_present() -> bool:
    return _ONNX.exists() and _VOICES.exists()


def downloading() -> bool:
    return _DOWNLOADING


def lib_present() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        return True
    except Exception:
        return False


def available() -> bool:
    """True if the model files and kokoro-onnx are both present."""
    return models_present() and lib_present()


def download() -> None:
    """Fetch the Kokoro model files (~335MB) into ./models/. Blocking — run in a
    thread. Idempotent and best-effort."""
    global _DOWNLOADING
    if _DOWNLOADING or models_present():
        return
    _DOWNLOADING = True
    try:
        import urllib.request
        _DIR.mkdir(parents=True, exist_ok=True)
        for name, url in _MODEL_URLS.items():
            dest = _DIR / name
            if not dest.exists():
                tmp = dest.with_suffix(dest.suffix + ".part")
                urllib.request.urlretrieve(url, tmp)
                tmp.rename(dest)
    except Exception:
        pass
    finally:
        _DOWNLOADING = False


def _engine():
    global _ENGINE, _TRIED
    if _ENGINE is None and not _TRIED:
        _TRIED = True
        try:
            from kokoro_onnx import Kokoro
            _ENGINE = Kokoro(str(_ONNX), str(_VOICES))
        except Exception:
            _ENGINE = None
    return _ENGINE


def synth(text: str, voice: str = "bm_george", speed: float = 1.0) -> bytes | None:
    """Return WAV bytes for `text`, or None if local TTS is unavailable/failed.
    Voices starting with 'b' are British English; otherwise American."""
    text = (text or "").strip()
    if not text:
        return None
    eng = _engine()
    if eng is None:
        return None
    lang = "en-gb" if voice[:1] == "b" else "en-us"
    try:
        import soundfile as sf
        with _LOCK:
            samples, sr = eng.create(text, voice=voice, speed=speed, lang=lang)
        buf = io.BytesIO()
        sf.write(buf, samples, sr, format="WAV")
        return buf.getvalue()
    except Exception:
        return None


def synth_pcm(text: str, voice: str = "bm_george", speed: float = 1.0):
    """Return (float32 mono samples, sample_rate) for NATIVE playback by the audio
    service, or None. Same engine as synth(), no WAV wrapping."""
    text = (text or "").strip()
    if not text:
        return None
    eng = _engine()
    if eng is None:
        return None
    lang = "en-gb" if voice[:1] == "b" else "en-us"
    try:
        import numpy as np
        with _LOCK:
            samples, sr = eng.create(text, voice=voice, speed=speed, lang=lang)
        return np.asarray(samples, dtype=np.float32), int(sr)
    except Exception:
        return None
