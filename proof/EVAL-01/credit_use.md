# EVAL-01 LLM usage (real DeepSeek calls from run_acceptance.py)

| Model | Calls | Input tok | Output tok | Est. cost USD |
|---|---|---|---|---|
| deepseek-v4-pro | 3 | 436 | 45 | 0.000185 |
| deepseek-flash | 4 | 2697 | 197 | 0.001045 |

Total: 7 billed calls (2 cache hits, 0 tokens), est. **$0.00123**. Estimated with the flash list price (0.30/1.20 per 1M tokens) for every model, so the v4-pro calls are under-estimated (list 1.32/3.96); still well under $0.01.
Gemini: 0 calls, GEMINI_API_KEY is empty in this environment. Raw per-call ledger: `usage.jsonl`.
