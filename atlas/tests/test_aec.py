"""L3 Phase 3: echo cancellation (FDAF) reduces far-end echo, and the audio
service's full-duplex barge-in decision fires on a wake during speech."""
from __future__ import annotations

import numpy as np

from atlas.interface.voice import aec as AEC
from atlas.interface.voice import audio_service as A


def _i16(x):
    return np.clip(x * 32768.0, -32768, 32767).astype(np.int16)


def test_fdaf_reduces_echo_energy():
    rng = np.random.RandomState(0)
    ec = AEC.EchoCanceller(block=A.FRAME, mu=0.3)
    room = np.array([0.0, 0.6, 0.0, -0.3, 0.15], dtype=np.float64)  # short echo path
    tail = np.zeros(len(room) - 1)

    def step(measure):
        nonlocal tail, mic_energy, out_energy
        ref = rng.randn(A.FRAME) * 0.3                      # far-end (TTS) signal
        full = np.concatenate([tail, ref])
        echo = np.convolve(full, room, mode="valid")        # echo the mic picks up
        tail = ref[-(len(room) - 1):]
        out = ec.process(_i16(echo), _i16(ref)).astype(np.float64) / 32768.0
        if measure:
            mic_energy += float(np.sum(echo ** 2))
            out_energy += float(np.sum(out ** 2))

    mic_energy = out_energy = 0.0
    for _ in range(80):                                     # warm up the adaptive filter
        step(measure=False)
    for _ in range(40):                                     # measure steady-state residual
        step(measure=True)
    # once adapted, residual echo should be << the raw mic echo (~>6 dB reduction)
    assert out_energy < 0.25 * mic_energy, (out_energy, mic_energy)


def test_make_aec_backends_fall_back_gracefully():
    assert AEC.make_aec("none").process(_i16(np.zeros(A.FRAME)), _i16(np.zeros(A.FRAME))) is not None
    # os / webrtc have no native build here → software fallback, still functional
    assert "nlms" in AEC.make_aec("os").backend
    assert "nlms" in AEC.make_aec("webrtc").backend


def test_full_duplex_barge_in_fires_on_wake_during_speech():
    events = []
    wake = {"v": False}

    class _R:
        def chat(self, text, **kw):
            return {"reply": "ok", "media": None}

    svc = A.AudioService(
        router=_R(), publish=events.append,
        wake_fn=lambda f: wake["v"], stt_fn=lambda s: "hi",
        synth_fn=lambda t: (np.zeros(2, dtype=np.float32), 16000),
        play_fn=lambda s, sr: None,
        aec=AEC.make_aec("none"), ref_provider=lambda: np.zeros(A.FRAME, dtype=np.int16),
        full_duplex=True,
    )
    svc.state = "speaking"                                  # pretend ATLAS is mid-sentence
    wake["v"] = True
    barged = svc._maybe_barge(np.zeros(A.FRAME, dtype=np.int16))
    assert barged is True
    assert svc._abort.is_set() and svc._barge is True       # abort + queued to listen
    assert {"type": "wake"} in events


def test_full_duplex_no_barge_without_wake():
    svc = A.AudioService(
        router=object(), publish=lambda e: None,
        wake_fn=lambda f: False, stt_fn=lambda s: "",
        synth_fn=lambda t: None, play_fn=lambda s, sr: None,
        aec=AEC.make_aec("none"), ref_provider=lambda: None, full_duplex=True,
    )
    svc.state = "speaking"
    assert svc._maybe_barge(np.zeros(A.FRAME, dtype=np.int16)) is False
    assert not svc._abort.is_set()
