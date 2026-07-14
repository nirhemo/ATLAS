"""L3 native audio service: the full state machine (idle→listening→transcribing→
thinking→speaking→idle) driven by injected fakes — no microphone or models."""
from __future__ import annotations

import numpy as np

from atlas.interface.voice import audio_service as A


class _Router:
    def __init__(self):
        self.calls = []

    def chat(self, text, **kw):
        self.calls.append((text, kw))
        return {"reply": "Hello there. Nice to meet you.", "media": None}


def _svc(**over):
    events = []
    played = []
    wake_on = {"v": False}

    defaults = dict(
        router=_Router(),
        publish=events.append,
        wake_fn=lambda frame: wake_on["v"],
        stt_fn=lambda samples: "what time is it",
        synth_fn=lambda text: (np.zeros(4, dtype=np.float32), 16000),
        play_fn=lambda samples, sr: played.append((len(samples), sr)),
        vad_silence_ms=160,          # 2 frames of silence ends the utterance
        async_turn=False,            # run the turn inline so tests are deterministic
    )
    defaults.update(over)
    svc = A.AudioService(**defaults)
    return svc, events, played, wake_on


def _silence():
    return np.zeros(A.FRAME, dtype=np.int16)


def _loud():
    return (np.ones(A.FRAME, dtype=np.int16) * 8000)


def test_speech_clean_strips_markup_and_urls():
    out = A.speech_clean("**Bold** see [link](https://x.com) and `code`")
    assert "*" not in out and "https" not in out and "`" not in out
    assert "Bold" in out and "link" in out


def test_split_sentences():
    assert A.split_sentences("One. Two! Three?") == ["One.", "Two!", "Three?"]


def test_wake_transitions_idle_to_listening():
    svc, events, _, wake = _svc()
    svc.feed(_silence())
    assert svc.state == "idle"                       # no wake yet
    wake["v"] = True
    svc.feed(_loud())
    assert svc.state == "listening"
    assert {"type": "wake"} in events


def test_full_turn_records_transcribes_responds_and_speaks():
    svc, events, played, wake = _svc()
    wake["v"] = True
    svc.feed(_loud())                                # wake → listening
    wake["v"] = False
    svc.feed(_loud())                                # speech frame
    svc.feed(_silence()); svc.feed(_silence())       # 2 silent frames → end utterance
    assert svc.state == "idle"                        # returned to idle after speaking
    types = [e.get("type") for e in events]
    assert "final" in types and "reply" in types
    # tts start → stop bracket the speech, and Kokoro played at least one sentence
    tts_states = [e["state"] for e in events if e.get("type") == "tts"]
    assert tts_states[0] == "start" and tts_states[-1] == "stop"
    assert played, "expected native playback of at least one sentence"
    # states passed through transcribing → thinking → speaking
    seen = [e["value"] for e in events if e.get("type") == "state"]
    assert "transcribing" in seen and "thinking" in seen and "speaking" in seen


def test_empty_transcript_returns_to_idle_without_responding():
    router = _Router()
    svc, events, _, wake = _svc(router=router, stt_fn=lambda s: "   ")
    wake["v"] = True
    svc.feed(_loud()); wake["v"] = False
    svc.feed(_silence()); svc.feed(_silence())
    assert svc.state == "idle"
    assert router.calls == []                         # nothing heard → no Router call
    assert "reply" not in [e.get("type") for e in events]


def test_abort_stops_speaking():
    # A synth that aborts mid-way: after the first sentence, flip the abort flag.
    svc, events, played, wake = _svc()

    def synth(text):
        svc.command("abort")                          # user says stop during playback
        return (np.zeros(2, dtype=np.float32), 16000)

    svc.synth_fn = synth
    wake["v"] = True
    svc.feed(_loud()); wake["v"] = False
    svc.feed(_silence()); svc.feed(_silence())
    assert svc.state == "idle"
    assert {"type": "tts", "state": "stop"} in events  # always brackets to stop


def test_hub_publish_without_loop_is_safe():
    hub = A.VoiceHub()
    hub.publish({"type": "state", "value": "idle"})    # no loop bound → no crash
