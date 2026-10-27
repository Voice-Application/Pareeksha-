# QA-03 credit use (2026-10-27)

Real Gnani + DeepSeek via the private compose stack `pk-m3`; totals from `api_usage` (`usage_totals.txt`),
covering all runs on the stack (smoke 4 failed calls, clean/bug runs 26 calls, 40-call run). `COST_*`
rates are unset so `est_cost` is 0; units shown.

| Item | Units |
|---|---|
| Gnani STT (REST, caller side, 177 requests) | 1,102.7 audio-seconds |
| Gnani TTS (231 requests) | 11,407 characters |
| DeepSeek caller brain (121 calls) | 109,827 tokens |
| DeepSeek judge (66 calls) | 208,204 tokens |

Not metered here: the mock agent's own Gnani STT/TTS (separate containers). 70 calls total in the DB.
