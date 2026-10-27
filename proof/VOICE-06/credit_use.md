# VOICE-06 credit use (2026-10-27)

Two real calls through the `pipecat` adapter against `examples/pipecat-bot` (the first, with the
glass-box text arriving after the audio, was discarded; the kept one is `calls/00_pipecat_clean`).
Counted from `usage.json` (caller side) and `bot.log` (bot side). No balance endpoint exists.

| Call | Caller Gnani TTS | Caller Gnani STT | Bot Gnani STT/TTS | DeepSeek (caller brain) | DeepSeek (bot) |
|---|---|---|---|---|---|
| discarded run (90 s) | ~5 calls | ~5 calls | ~4 / ~3 calls | ~3 calls | ~4 calls |
| `00_pipecat_clean` (100 s) | 5 calls, 23.4 s audio, 331 chars | 5 calls, 36.9 s | ~5 / ~5 calls | 4 calls, 3.3k in / 0.2k out tokens | 7 calls |

Gnani answers one concurrent request per key; `bot.log` shows 8 HTTP 429s that the provider retry
absorbed (caller and bot share one key here). `COST_*` rates are unset, so `est_cost` is empty.
