# VOICE-03 Gnani usage (all synthetic TTS speech, no human voices; DeepSeek/LLM: none, dialog is scripted)

SDK exposes no balance, so spend is calls and audio seconds (as in VOICE-01).

| Kind | Calls | Audio seconds |
|---|---|---|
| TTS REST timbre-v3.0, distinct texts (disk-cached, so every distinct line billed once) | 20 | 91.1 s generated (agent lines + 8 caller lines: 4 en, 4 kn) |
| STT REST `/stt/v3` (agent hearing the caller), 8 acceptance calls | 31 | 66.3 s |
| STT REST in 4 aborted debug runs of the demo script (caller bug, since fixed) | 1 | 7.0 s |

TTS figure = sum of cached WAV durations in the TTS cache (one real request per file). STT figure =
sum of the per-call "gnani usage" lines in `calls/*/server.log` (4+4+3+4+4+4+4+4 calls; 04b is its final rerun).
