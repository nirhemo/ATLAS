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


def _stop_playback() -> None:
    """Interrupt any in-progress native playback (barge-in / user Stop)."""
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:
        pass


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
        aec: Any = None,                      # EchoCanceller (Phase 3) or None
        ref_provider: Callable[[], Any] = None,   # -> current far-end (TTS) frame, or None
        full_duplex: bool = False,            # listen while speaking (needs aec + ref)
        async_turn: bool = True,              # run the LLM+TTS turn off the mic thread
    ) -> None:
        self.router = router
        self.publish = publish
        self.wake_fn = wake_fn
        self.stt_fn = stt_fn
        self.synth_fn = synth_fn
        self.play_fn = play_fn
        self.vad_silence_ms = vad_silence_ms
        self.session = session
        self.aec = aec
        self.ref_provider = ref_provider
        self.full_duplex = bool(full_duplex and aec is not None)
        self.async_turn = async_turn

        self.state = "idle"
        self._utter: list = []
        self._silence_frames = 0
        self._abort = threading.Event()
        self._barge = False
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
        """Process one 80 ms int16 frame. During 'speaking', half-duplex ignores
        the mic; full-duplex runs AEC + wake on the cleaned signal for barge-in."""
        if self.state == "speaking":
            if self.full_duplex:
                self._maybe_barge(frame)
            return
        if self.state in ("transcribing", "thinking"):
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
                self._start_turn()

    def _maybe_barge(self, frame) -> bool:
        """AEC-clean the mic against the far-end (TTS) frame, then run wake on the
        residual — so 'Hey Jarvis' interrupts mid-sentence without self-triggering.
        Sets the abort + barge flags; the turn thread then switches to listening."""
        try:
            ref = self.ref_provider() if self.ref_provider else None
            cleaned = self.aec.process(frame, ref) if (self.aec and ref is not None) else frame
            if self.wake_fn(cleaned):
                self._barge = True
                self._abort.set()
                _stop_playback()
                self.publish({"type": "wake"})
                return True
        except Exception:
            pass
        return False

    def _start_turn(self) -> None:
        import numpy as np
        self._set_state("transcribing")
        frames = self._utter
        self._utter = []
        audio = (np.concatenate([np.asarray(f, dtype=np.int16) for f in frames])
                 if frames else np.zeros(0, dtype=np.int16))
        if self.async_turn:
            threading.Thread(target=self._run_turn, args=(audio,), daemon=True).start()
        else:
            self._run_turn(audio)

    def _run_turn(self, audio) -> None:
        """STT → Router → speak. Runs off the mic thread (async) so the mic loop
        stays live for barge-in while ATLAS thinks and speaks."""
        try:
            text = (self.stt_fn(audio.astype("float32") / 32768.0) or "").strip()
        except Exception:
            text = ""
        if not text:
            self._set_state("idle")
            return
        self.publish({"type": "final", "text": text})
        self._abort.clear()
        self._barge = False
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
        # barge-in → go straight to listening for the interrupting command; else idle.
        if self._barge:
            self._barge = False
            self._utter = []
            self._silence_frames = 0
            self._set_state("listening")
        else:
            self._set_state("idle")

    # ----- external commands (from /voice/ws) ----------------------------- #
    def command(self, cmd: str) -> None:
        if cmd == "abort":
            self._barge = False        # explicit stop → go quiet, not into listening
            self._abort.set()
            _stop_playback()
            if self.state in ("speaking", "listening"):
                self._utter = []
                self._set_state("idle")
        elif cmd == "start" and self.state == "idle":
            self._utter = []
            self._silence_frames = 0
            self._set_state("listening")


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
        from collections import deque
        from .aec import make_aec

        # Full-duplex AEC (Phase 3): the far-end (Kokoro) frames are queued into a
        # reference buffer as they play; the mic loop pops them so the canceller
        # sees what's coming out of the speaker. Timing here is best-effort and
        # wants on-device delay calibration; the macOS VoiceProcessingIO backend
        # (aec_backend="os", native bridge) avoids this plumbing entirely.
        aec_backend = str(vcfg.get("aec_backend", "os"))
        aec = make_aec(aec_backend) if aec_backend not in ("none", "off") else None
        ref_q: deque = deque(maxlen=64)

        def ref_provider():
            return ref_q.popleft() if ref_q else None

        def _resample_16k(samples, sr):
            if sr == SAMPLE_RATE:
                return samples
            import numpy as np
            n = int(len(samples) * SAMPLE_RATE / sr)
            return np.interp(np.linspace(0, len(samples), n, endpoint=False),
                             np.arange(len(samples)), samples).astype(np.float32)

        def synth_fn(text: str):
            return tts_engine.synth_pcm(text, voice=voice_id, speed=speed)

        def play_fn(samples, sr):
            # Queue the far-end frames for the AEC reference, then play.
            r = _resample_16k(np.asarray(samples, dtype=np.float32), sr)
            pcm16 = np.clip(r * 32768.0, -32768, 32767).astype(np.int16)
            for i in range(0, len(pcm16), FRAME):
                ref_q.append(pcm16[i:i + FRAME])
            sd.play(samples, sr); sd.wait()

        self.service = AudioService(
            router=self.router, publish=self.hub.publish,
            wake_fn=wake, stt_fn=stt, synth_fn=synth_fn, play_fn=play_fn,
            vad_silence_ms=int(vcfg.get("vad_silence_ms", 700)),
            aec=aec, ref_provider=ref_provider, full_duplex=(aec is not None),
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
