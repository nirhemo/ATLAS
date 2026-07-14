"""L3 native audio service — mic → wake → VAD → STT → Router → Kokoro, streaming
state to the HUD over /voice/ws. Replaces the browser Web Speech loop with a
fully on-device, offline pipeline (openWakeWord + whisper.cpp + Kokoro).

Phase 2 is HALF-DUPLEX: the mic is ignored while ATLAS speaks (barge-in falls back
to the UI Stop). Phase 3 swaps in echo-cancelled full-duplex barge-in.

Every heavy dep (sounddevice, openwakeword, onnxruntime, pywhispercpp) is OPTIONAL:
if any is missing, available() is False, the service never starts, and the HUD
keeps its browser Web Speech fallback. The pipeline stages are INJECTABLE
(wake_fn / stt_fn / synth_fn / play_fn / publish), so the whole state machine is
unit-tested with fakes — no microphone or models required.
"""
from __future__ import annotations

import queue
import re
import threading
from typing import Any, Callable

SAMPLE_RATE = 16000        # openWakeWord + whisper both want 16 kHz mono
FRAME = 1280               # 80 ms @ 16 kHz — the openWakeWord frame size
_MAX_UTTERANCE_S = 15      # hard cap so a stuck VAD can't record forever


# --------------------------------------------------------------------------- #
# Dependency / model availability
# --------------------------------------------------------------------------- #
def deps_present() -> bool:
    try:
        import numpy, sounddevice, openwakeword, pywhispercpp  # noqa: F401
        return True
    except Exception:
        return False


def wake_model_path(name: str = "hey_jarvis") -> str | None:
    try:
        import glob
        import os
        import openwakeword
        d = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
        hits = glob.glob(os.path.join(d, f"{name}*.onnx"))
        return hits[0] if hits else None
    except Exception:
        return None


def available() -> bool:
    """True if the native pipeline can run (deps + a wake model present)."""
    return deps_present() and wake_model_path() is not None


# --------------------------------------------------------------------------- #
# Pub-sub bridge: audio thread → async WebSocket clients
# --------------------------------------------------------------------------- #
class VoiceHub:
    """Thread-safe fan-out from the audio worker thread to /voice/ws clients.
    The FastAPI lifespan binds the running loop; publish() is called off-thread."""

    def __init__(self) -> None:
        self._loop = None
        self._queues: set = set()

    def bind_loop(self, loop) -> None:
        self._loop = loop

    def subscribe(self):
        import asyncio
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self._queues.discard(q)

    def publish(self, event: dict) -> None:
        loop = self._loop
        if loop is None:
            return
        for q in list(self._queues):
            try:
                loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Speech text cleanup (mirror of the HUD's speechClean, so TTS never reads markup)
# --------------------------------------------------------------------------- #
def speech_clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"```[\s\S]*?```", " code shown on screen ", s)
    s = re.sub(r"【[^】]*】", "", s)
    s = re.sub(r"\[\^?\d+\]", "", s)
    s = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"\bhttps?://\S+", "", s)
    s = re.sub(r"^\s{0,3}#{1,6}\s+", "", s, flags=re.M)
    s = re.sub(r"[*_#`>~|]", " ", s)
    s = re.sub(r"\s*&\s*", " and ", s)
    s = re.sub(r"\n{2,}", ". ", s).replace("\n", ", ")
    s = re.sub(r"\s+([.,!?;:])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


# --------------------------------------------------------------------------- #
# The service (state machine is injectable → unit-testable without hardware)
# --------------------------------------------------------------------------- #
class AudioService:
    """States: idle (await wake) → listening (record) → transcribing → thinking →
    speaking → idle. Frames are int16 [FRAME]. Inject the pipeline stages for
    tests; build_default() wires the real engines."""

    def __init__(
        self,
        *,
        router: Any,
        publish: Callable[[dict], None],
        wake_fn: Callable[[Any], bool],
        stt_fn: Callable[[Any], str],
        synth_fn: Callable[[str], Any],       # text -> (float32 samples, sr) | None
        play_fn: Callable[[Any, int], None],  # (samples, sr) -> plays, honors abort
        vad_silence_ms: int = 700,
        session: str = "s_voice",
    ) -> None:
        self.router = router
        self.publish = publish
        self.wake_fn = wake_fn
        self.stt_fn = stt_fn
        self.synth_fn = synth_fn
        self.play_fn = play_fn
        self.vad_silence_ms = vad_silence_ms
        self.session = session

        self.state = "idle"
        self._utter: list = []
        self._silence_frames = 0
        self._abort = threading.Event()
        self._turn = 0

    # ----- helpers -------------------------------------------------------- #
    def _set_state(self, value: str) -> None:
        self.state = value
        self.publish({"type": "state", "value": value})

    def _rms(self, frame) -> float:
        import numpy as np
        f = np.asarray(frame, dtype=np.float32) / 32768.0
        return float(np.sqrt(np.mean(f * f)) if f.size else 0.0)

    @property
    def _silence_limit_frames(self) -> int:
        return max(1, int(self.vad_silence_ms / 80))   # 80 ms per frame

    # ----- per-frame state machine (the testable core) -------------------- #
    def feed(self, frame) -> None:
        """Process one 80 ms int16 frame. No-op while speaking (half-duplex)."""
        if self.state in ("speaking", "transcribing", "thinking"):
            return
        if self.state == "idle":
            try:
                if self.wake_fn(frame):
                    self.publish({"type": "wake"})
                    self._utter = []
                    self._silence_frames = 0
                    self._set_state("listening")
            except Exception:
                pass
            return
        if self.state == "listening":
            self._utter.append(frame)
            if self._rms(frame) < 0.012:
                self._silence_frames += 1
            else:
                self._silence_frames = 0
            too_long = len(self._utter) > int(_MAX_UTTERANCE_S * SAMPLE_RATE / FRAME)
            if self._silence_frames >= self._silence_limit_frames or too_long:
                self._finish_utterance()

    def _finish_utterance(self) -> None:
        import numpy as np
        self._set_state("transcribing")
        frames = self._utter
        self._utter = []
        try:
            audio = np.concatenate([np.asarray(f, dtype=np.int16) for f in frames]) \
                if frames else np.zeros(0, dtype=np.int16)
            samples = audio.astype(np.float32) / 32768.0
            text = (self.stt_fn(samples) or "").strip()
        except Exception:
            text = ""
        if not text:
            self._set_state("idle")
            return
        self.publish({"type": "final", "text": text})
        self._respond(text)

    def _respond(self, text: str) -> None:
        self._abort.clear()
        self._turn += 1
        self._set_state("thinking")
        try:
            out = self.router.chat(text, channel="voice", session=self.session, turn=self._turn)
        except Exception as exc:
            out = {"reply": f"(voice error: {type(exc).__name__})", "media": None}
        reply = out.get("reply") or "(no reply)"
        self.publish({"type": "reply", "text": reply, "media": out.get("media")})
        self._speak(reply)

    def _speak(self, reply: str) -> None:
        spoken = speech_clean(reply)
        if not spoken:
            self._set_state("idle")
            return
        self._set_state("speaking")
        self.publish({"type": "tts", "state": "start"})
        for sentence in split_sentences(spoken):
            if self._abort.is_set():
                break
            self.publish({"type": "tts", "state": "sentence_start", "text": sentence})
            try:
                pcm = self.synth_fn(sentence)
                if pcm:
                    self.play_fn(pcm[0], pcm[1])
            except Exception:
                pass
        self.publish({"type": "tts", "state": "stop"})
        self._set_state("idle")

    # ----- external commands (from /voice/ws) ----------------------------- #
    def command(self, cmd: str) -> None:
        if cmd == "abort":
            self._abort.set()
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            if self.state in ("speaking", "listening"):
                self._utter = []
                self._set_state("idle")


# --------------------------------------------------------------------------- #
# Real-engine wiring + capture thread
# --------------------------------------------------------------------------- #
class NativeAudioRunner:
    """Owns the mic stream + worker thread and drives an AudioService with the real
    openWakeWord / whisper.cpp / Kokoro engines. start()/stop() from the lifespan."""

    def __init__(self, router: Any, hub: VoiceHub) -> None:
        self.router = router
        self.hub = hub
        self._q: queue.Queue = queue.Queue(maxsize=64)
        self._stream = None
        self._thread = None
        self._running = False
        self.service: AudioService | None = None

    def start(self) -> bool:
        if self._running or not available():
            return False
        from .. import voice  # noqa: F401
        from ... import settings as cfg
        import numpy as np
        import sounddevice as sd

        vcfg = (cfg.settings().get("voice") or {})
        wake = _build_wake(vcfg.get("wake_word_model", "hey_jarvis"),
                           float(vcfg.get("wake_word_sensitivity", 0.6)))
        stt = _build_stt(vcfg.get("stt_model", "base.en"))
        voice_id = str(vcfg.get("tts_voice", "kokoro:bm_george")).split(":")[-1]
        speed = float(vcfg.get("speech_rate", 1.0))

        from . import tts as tts_engine

        def synth_fn(text: str):
            return tts_engine.synth_pcm(text, voice=voice_id, speed=speed)

        def play_fn(samples, sr):
            sd.play(samples, sr); sd.wait()

        self.service = AudioService(
            router=self.router, publish=self.hub.publish,
            wake_fn=wake, stt_fn=stt, synth_fn=synth_fn, play_fn=play_fn,
            vad_silence_ms=int(vcfg.get("vad_silence_ms", 700)),
        )

        def _cb(indata, frames, time_info, status):
            try:
                self._q.put_nowait((indata[:, 0] * 32768.0).astype(np.int16))
            except queue.Full:
                pass

        try:
            self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                          blocksize=FRAME, dtype="float32", callback=_cb)
            self._stream.start()
        except Exception:
            self._stream = None
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        while self._running:
            try:
                frame = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            if self.service:
                self.service.feed(frame)

    def command(self, cmd: str) -> None:
        if self.service:
            self.service.command(cmd)

    def stop(self) -> None:
        self._running = False
        try:
            if self._stream:
                self._stream.stop(); self._stream.close()
        except Exception:
            pass
        self._stream = None


def _build_wake(name: str, threshold: float) -> Callable[[Any], bool]:
    from openwakeword.model import Model
    path = wake_model_path(name) or wake_model_path("hey_jarvis")
    model = Model(wakeword_models=[path], inference_framework="onnx")
    key = None

    def wake_fn(frame) -> bool:
        nonlocal key
        scores = model.predict(frame)
        if key is None:
            key = next(iter(scores), None)
        return key is not None and scores.get(key, 0.0) >= threshold

    return wake_fn


def _build_stt(model_name: str) -> Callable[[Any], str]:
    from pywhispercpp.model import Model
    model = Model(model_name, print_realtime=False, print_progress=False, print_timestamps=False)

    def stt_fn(samples) -> str:
        segs = model.transcribe(samples)
        text = " ".join(s.text for s in segs).strip()
        # whisper marks non-speech as [BLANK_AUDIO], (music), [ Silence ], etc. —
        # strip bracketed/parenthetical markers so silence isn't treated as a turn.
        text = re.sub(r"[\[(][^\])]*[\])]", "", text)
        return re.sub(r"\s{2,}", " ", text).strip()

    return stt_fn
