# FE-03 / FE-04 real-service use (one 12-call run, one audit clip)

| Service | Calls | Units |
|---|---|---|
| Gnani TTS (timbre-v3.0, synthetic voices only) | 43 | 245 s audio, 3009 characters |
| Gnani STT REST | 38 | 141 s audio |
| DeepSeek judge (deepseek-v4-pro) | 18 ledger rows (12 calls + judge repair retries) | ~46k input / ~8k output tokens, about USD 0.09 at list price |

Ledger: `usage.jsonl` (written by `proof/FE-04/real_calls.py`). TTS results are cached on disk, so re-runs of the harness cost nothing for text already voiced; 429 rate-limit retries (Gnani allows one active request) are not billed. Gemini: 0 calls. No human voices: every clip is synthetic TTS.
