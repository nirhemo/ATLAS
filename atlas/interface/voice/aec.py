"""Acoustic echo cancellation (L3, Phase 3) — remove the far-end (Kokoro TTS)
signal from the mic so ATLAS can listen WHILE it speaks without hearing itself.

Backends (voice.aec_backend):
  "os"    — macOS VoiceProcessingIO (best; the OS owns mic+speaker and cancels
            echo for free). Needs a native audio-unit bridge; when unavailable we
            fall back to the software filter and say so.
  "webrtc"— WebRTC AEC3 via webrtc-audio-processing (needs a C++ build).
  "nlms"  — a pure-numpy frequency-domain adaptive filter (FDAF). No build deps,
            deterministic, unit-testable. Handles linear echo; not as strong as
            the OS/WebRTC cancellers on nonlinear echo, but always available.
  "none"  — passthrough (Phase 2 half-duplex).

The reference (far-end) frame is the exact Kokoro PCM being played, handed in
time-aligned by the audio service — that's what makes real cancellation possible.
"""
from __future__ import annotations

import numpy as np

FRAME = 1280        # 80 ms @ 16 kHz


class EchoCanceller:
    """Constrained frequency-domain adaptive filter (overlap-save FDAF), single
    partition of `block` samples. process(mic, ref) → near-end (echo removed)."""

    def __init__(self, block: int = FRAME, mu: float = 0.3, eps: float = 1e-3) -> None:
        self.N = block
        self.mu = float(mu)
        self.eps = float(eps)
        # Constrained overlap-save FDAF, single partition. Full complex FFT of size
        # 2N; the filter W and smoothed power P live in that 2N frequency domain.
        self._W = np.zeros(2 * block, dtype=np.complex128)
        self._x_prev = np.zeros(block, dtype=np.float64)     # previous ref block
        self._P = np.ones(2 * block, dtype=np.float64)       # smoothed ref power

    def process(self, mic_i16, ref_i16):
        N = self.N
        d = np.asarray(mic_i16, dtype=np.float64)[:N] / 32768.0
        x_cur = np.asarray(ref_i16, dtype=np.float64)[:N] / 32768.0
        if d.size < N:
            d = np.pad(d, (0, N - d.size))
        if x_cur.size < N:
            x_cur = np.pad(x_cur, (0, N - x_cur.size))

        x = np.concatenate([self._x_prev, x_cur])            # 2N overlap-save block
        X = np.fft.fft(x)                                    # 2N complex
        y = np.real(np.fft.ifft(self._W * X))[N:]            # linear-conv echo estimate
        e = d - y                                            # near-end estimate

        E = np.fft.fft(np.concatenate([np.zeros(N), e]))     # 2N
        self._P = 0.9 * self._P + 0.1 * (np.abs(X) ** 2)
        G = np.conj(X) * E / (self._P + self.eps)            # per-bin normalized grad
        g = np.real(np.fft.ifft(G))
        g[N:] = 0                                            # gradient constraint (first N taps)
        self._W += self.mu * np.fft.fft(g)

        self._x_prev = x_cur
        return np.clip(e * 32768.0, -32768, 32767).astype(np.int16)


class _Passthrough:
    backend = "none"

    def process(self, mic_i16, ref_i16):
        return np.asarray(mic_i16, dtype=np.int16)


class _Software:
    backend = "nlms"

    def __init__(self):
        self._ec = EchoCanceller()

    def process(self, mic_i16, ref_i16):
        return self._ec.process(mic_i16, ref_i16)


def _os_backend():
    """macOS VoiceProcessingIO. Requires a native audio-unit bridge (PyObjC/ctypes
    or a small Rust helper) that we don't build here yet — returns None so the
    caller falls back to the software filter. The hook is intentional: wiring the
    VPIO unit is the on-device upgrade for best-in-class AEC."""
    return None


def make_aec(backend: str = "os"):
    """Build an echo canceller for the requested backend, falling back gracefully.
    Returns an object with .process(mic_i16, ref_i16) and a .backend label."""
    backend = (backend or "os").lower()
    if backend in ("none", "off"):
        return _Passthrough()
    if backend == "os":
        vpio = _os_backend()
        if vpio is not None:
            return vpio
        sw = _Software()                 # VPIO bridge not built → software fallback
        sw.backend = "nlms(os-unavailable)"
        return sw
    if backend == "webrtc":
        try:
            import webrtc_audio_processing  # noqa: F401
            # (wiring left for the C++-built environment; software fallback here)
        except Exception:
            pass
        sw = _Software()
        sw.backend = "nlms(webrtc-unavailable)"
        return sw
    return _Software()
