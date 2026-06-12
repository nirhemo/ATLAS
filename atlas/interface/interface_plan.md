---
layer: L3
artifact: interface_plan
version: 0.1.0
created: 2026-06-12
---

# L3 · Interface Plan

Two front-ends, one core. Voice is primary; the web dashboard is the window.

## A. Voice pipeline (always-listening, all local pre-API)

Proven on Apple Silicon; sub-1.5s full loops are realistic on Mac Mini-class HW.
See `voice/pipeline.md` for the detailed contract and `settings.json` for tunables.

```
 mic ─▶ Wake word ─▶ VAD ─▶ STT ─▶ [ LLM via L6 ] ─▶ TTS ─▶ speaker
        openWakeWord  silero  whisper.cpp   Claude/local   Kokoro/Piper
        "Hey Atlas"   -vad    (Metal)                      (streaming)
        (≤200MB,      end-of- base/small                   speak 1st
         resident)    speech                               sentence early
```

- **Wake word:** openWakeWord. Day-one interim model `hey_jarvis` (off-the-shelf,
  works immediately) while a custom **"Hey Atlas"** model is trained from
  synthetic speech. Per-room threshold tuning. (Porcupine custom keyword is the
  fallback option.)
- **VAD:** silero-vad detects end-of-speech — no robotic fixed recording windows.
- **STT:** whisper.cpp with Metal acceleration. `base`/`small` for commands,
  upgradeable per accuracy needs.
- **TTS:** Kokoro ONNX (quality) or Piper (speed), both CPU-friendly.
- **Streaming TTS:** start speaking the first complete sentence while the LLM is
  still generating the rest — the single biggest perceived-latency win.
- **Privacy:** nothing leaves the device before the wake word fires; post-wake
  audio→STT is also local. Only **text** goes to the model (Phase 1).
- **State machine:** `idle → wake_detected → transcribing → thinking → speaking →
  idle`. The current state is published to the dashboard orb (below) and logged.

### Minimal Viable Voice Loop (ship this first)
1. `hey_jarvis` wake → silero VAD → whisper.cpp `base.en` → Claude (L6) → Piper.
2. No streaming yet, no custom wake word yet — prove the round trip end-to-end and
   log `latency_ms` (wake-to-first-word). Target < 1500ms.
3. Then layer in: streaming TTS → Kokoro voice → custom "Hey Atlas" model.

## B. Chat + Dashboard (local web app)

- **Stack:** FastAPI backend (serves the core + a small JSON/WebSocket API) + a
  static dark-mode frontend (`web/`). Both front-ends hit the **same core**;
  conversation state is shared between voice and chat.
- **Aesthetic:** futuristic, dark-first — near-black background, glowing cyan /
  electric-blue accents, subtle glass panels, monospaced data readouts, smooth
  micro-animations. Stark workshop HUD, not a generic chat app.
- **Dashboard-by-default** (not just a chat box). Panels:
  - **System status** — version, model backend, uptime, RAM use.
  - **Live metrics** — today's latency / accuracy / interaction count vs 7-day trend.
  - **Memory activity feed** — vault notes created/updated in last 24h.
  - **Last upgrade cycle** — what changed + next scheduled cycle.
  - **State indicator** — idle / wake / transcribing / thinking / speaking.
  - **Voice orb** — animated waveform/orb reacting while ATLAS listens & speaks.
- **Settings panel** — first-class; every control maps to `atlas/config/settings.json`
  (single source of truth shared by Owner and the AGE). Full list in that file.

## Scaffold delivered at Cycle Zero
- `web/index.html` · `web/styles.css` · `web/app.js` — a working static dashboard
  shell wired to **mock data** that reads the real `settings.json` / `VERSION.json`
  shapes. Drop in the FastAPI WebSocket feed to make it live (`app.js` marks the
  one integration point). No build step, no framework — opens in a browser.
