# INT-03 credit use

One real run of `run_e2e.py` (`e2e_run.log`, `e2e_result.json`). No TTS: the two-speaker TTS clip was generated and paid for in EVAL-04 and is reused (`synthetic_call.wav`, 17.5 s, hi-IN, invented lender, synthetic voices only).

| Vendor | Call | Units | Est. cost (USD) |
|---|---|---|---|
| Gnani | batch STT (diarize + denoise) | 17.46 audio s | n/a (no per-second price configured; one short job) |
| DeepSeek | role check (deepseek-v4-pro) | 827 tokens | 0.0013 |
| DeepSeek | judge (deepseek-v4-pro) | 2529 tokens | 0.0044 |

Total estimated paid API spend: about USD 0.006 plus one 17 s STT job. Earlier attempts: none (the first run passed). Docker images were already cached; no Gemini, no HubSpot calls.
