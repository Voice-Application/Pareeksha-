# VOICE-05 credit use (2026-10-27)

Real Gnani + DeepSeek, counted from `api_usage` (caller side, `db_query_output.txt`) and the mock
agent's own cumulative log line. `COST_*` rates are unset, so `est_cost` is 0; units are shown.

| Item | Units |
|---|---|
| Gnani STT, caller side (REST, 42 calls) | 265.3 audio-seconds |
| Gnani TTS, caller side (57 calls) | 3,858 characters |
| Gnani STT, mock agent side (50 calls) | 274.5 audio-seconds |
| Gnani TTS, mock agent side | cached/short fixed lines, a handful of calls (not metered by the agent) |
| DeepSeek caller brain (28 calls) | 22,547 tokens |
| DeepSeek judge (12 calls, `deepseek-v4-pro`) | 36,826 tokens |

One aborted first attempt (agent endpoint still the compose hostname, every call `connect_failed`
before any speech) cost nothing. Earlier in the session the VOICE-04 real calls are in
`proof/VOICE-04/credit_use.md`.

Gnani answered HTTP 429 ("only 1 active request") 92 times across the 3 simulators and the mock agent;
every one was absorbed by the jittered retry (see below), 0 calls failed.
