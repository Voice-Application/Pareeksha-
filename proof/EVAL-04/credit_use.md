# EVAL-04 usage (one synthetic two-speaker recording, real Gnani + DeepSeek)

Per-call ledger: `usage.jsonl` (written by `run_acceptance.py`). Synthetic speech only: invented lender
"Shakti Finance", TTS voices Shivani and Shubham, no human voices.

| Vendor | Operation | Calls | Quantity |
|---|---|---|---|
| Gnani Timbre v3.0 TTS | build the recording (3 turns) | 3 | 210 characters, 15.36 s generated |
| Gnani Prisma batch STT | diarized + denoised transcription | 1 job | 17.46 s audio |
| DeepSeek `deepseek-v4-pro` | speaker role check | 1 | 754 in / 73 out tokens |
| DeepSeek `deepseek-v4-pro` | judge, original roles | 1 | 2133 in / 393 out |
| DeepSeek `deepseek-v4-pro` | judge, after the speaker-map swap | 1 | 2140 in / 385 out |
| **DeepSeek total** | | 3 | 5027 in / 851 out, about USD 0.0100 at list price (1.32 in / 3.96 out per 1M) |

Notes
- The first attempt (`acceptance_run_1_bias_phrase_400.log`) made the 3 TTS calls and one STT job request that Gnani
  rejected with `400 INVALID_CONFIG` before processing any audio (bias entries must be single words). That job is
  not in the ledger; the fix is `bias_words()` in `backend/pareeksha/audit/pipeline.py`. The re-run reused the
  recording (`synthetic_call.wav`), so there was no second TTS spend.
- The Gnani batch client retried one status poll after a 429 (visible in `acceptance_run.log`); that is a poll, not a new job.
- `COST_*` rates for Gnani are not set in this environment, so `est_cost` is empty for TTS/STT; quantities above are exact.
- Gemini: 0 calls. Other speech vendors: 0 calls.
