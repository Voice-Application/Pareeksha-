# VOICE-07 Gnani usage (one smoke round trip, synthetic speech only)

| Kind | Calls | Detail |
|---|---|---|
| TTS REST (timbre-v3.0, voice Shivani, hi-IN) | 1 | 29 characters, 2.56 s generated |
| STT REST (`/stt/v3`) | 1 | 2.56 s |
| **Total** | **2** | 2.56 s TTS + 2.56 s STT |

Run with `python scripts/smoke_speech_gnani.py proof/VOICE-07` through the provider abstraction
(`get_tts_provider()` / `get_stt_provider()`, default `gnani`). Output: `gnani_adapter_roundtrip.json`
and `gnani_adapter_roundtrip.wav`. The STT transcript equals the reference text exactly.
The four other vendors made zero real calls (no keys).
