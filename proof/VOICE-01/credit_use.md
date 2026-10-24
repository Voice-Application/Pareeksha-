# VOICE-01 Gnani usage (all synthetic TTS speech, no human voices)

| Kind | Calls | Audio seconds |
|---|---|---|
| TTS REST (timbre-v3.0, 273 chars) | 5 | 23.28 s generated |
| STT REST (`/stt/v3`) | 8 | 38.08 s |
| STT WebSocket stream | 2 | 8.96 s |
| STT batch (diarization, 2 speakers) | 2 jobs | 20.0 s |
| **Total** | **17** | 23.28 s TTS + 67.04 s STT |

Two runs of `scripts/smoke_gnani.py`. Run 1 made all 5 TTS calls; its usage ledger over-reported
audio seconds because Gnani's WAV header has 0xFFFFFFFF size fields (fixed by `normalize_wav`; the buggy
ledger is kept in `run1/`). Run 2 reused the TTS disk cache (0 TTS calls) and repeated every STT call.
Hand-computed per-clip TTS durations: 4.24 + 4.96 + 4.88 + 4.72 + 4.48 s. Per-call detail for run 2:
`smoke_report.json`. A credit balance endpoint is not exposed by the SDK, so spend is reported as
calls and audio seconds rather than money.
