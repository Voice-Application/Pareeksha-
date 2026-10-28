# VOICE-04 credit use (this session, 2026-10-27)

Real Gnani + DeepSeek calls, counted from each call's `usage.json` and the mock agent's own log
(`calls/*/mock_agent.log`, "gnani usage" line). No balance endpoint exists, so spend is units used.

| Call | Gnani TTS (caller) | Gnani STT (caller side, REST) | Mock agent Gnani (STT / TTS) | DeepSeek (caller brain) |
|---|---|---|---|---|
| exploratory run (63 s, not kept) | 4 calls | 4 calls | ~4 / ~4 calls | 2 calls |
| `00_clean` (33 s) | 2 calls, 11.9 s audio, 163 chars | 2 calls, 12.7 s | 3 STT calls, 12.5 s | 1 call, 725 in / 51 out tokens |
| `01_false_waiver` (102 s) | 14 calls, 50.6 s audio, 780 chars | 8 calls, 33.0 s | 9 STT calls, 48.0 s; 1 TTS call, 4.3 s, 66 chars | 7 calls, 5877 in / 352 out tokens |

Totals kept in proof: ~16 caller TTS calls (62.5 s audio, 943 chars), ~10 caller-side STT calls (45.7 s),
12 agent-side STT calls (60.5 s), 1 agent-side TTS call, 8 DeepSeek calls (6.6k in / 0.4k out tokens).
`COST_*` rates are unset in the environment, so `est_cost` is 0 in `usage.json`.
