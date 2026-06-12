---
layer: L3
artifact: voice_pipeline_contract
version: 0.1.0
created: 2026-06-12
---

# Voice Pipeline Contract

Component contract for the always-listening loop. Every stage is **local** and
swappable (R3 model-agnostic, R8 adopt-before-build). Memory budgets per Section 7.

| Stage      | Default                    | Alt            | Budget   | Tunable (settings.json)                 |
|------------|----------------------------|----------------|----------|-----------------------------------------|
| Wake word  | openWakeWord `hey_jarvis`* | Porcupine      | ≤200MB   | `voice.wake_word_enabled`, `…sensitivity` |
| VAD        | silero-vad                 | webrtcvad      | ~50MB    | `voice.vad_silence_ms`                  |
| STT        | whisper.cpp `base.en` (Metal) | `small`/`medium` | ≤2GB | `voice.stt_model`                       |
| LLM        | via L6 orchestrator        | local Gemma    | ≤14GB(local) | `model.backend`                     |
| TTS        | Kokoro ONNX                | Piper          | ≤1GB     | `voice.tts_voice`, `voice.speech_rate`  |

\* Interim. Custom **"Hey Atlas"** openWakeWord model trained from synthetic speech
replaces `hey_jarvis` once ready; threshold re-tuned per room.

## State machine
```
idle ──wake──▶ wake_detected ──speech──▶ transcribing ──text──▶ thinking
  ▲                                                                 │
  └──────────────── speaking ◀────tts──── (LLM streaming) ◀─────────┘
```
- Each transition is published to the dashboard (`state_indicator`) and logged to
  `atlas/logs/` as a `state_change` event.
- **Barge-in:** wake word stays hot during `speaking`; a new wake interrupts TTS.

## Latency contract
- Metric: `latency_ms` = wake-to-first-spoken-word. **Target < 1500ms.**
- **Streaming TTS is mandatory for the target:** synthesize + start speaking on the
  first complete sentence while the LLM keeps generating.

## Privacy invariants (Section 8 — non-negotiable)
- Mic audio is processed on-device; **nothing leaves the machine before wake**.
- Post-wake audio → STT is also local; **only text** is sent to the model (Phase 1).
- No raw audio is persisted. Episodic logs store post-STT text only.
- `voice.mic_mute` hard-stops capture at the source.

## Graceful degradation (Mycroft lesson)
- TTS down → fall back to on-screen text in the dashboard.
- Model/network down → L6 degraded offline mode; ATLAS says what it can't do and
  still serves local tasks (timers, memory recall). It **never hangs or bricks**.
