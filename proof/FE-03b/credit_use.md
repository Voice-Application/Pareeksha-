# FE-03b real-service use (two 4-call runs through the full pipeline)

Source: `api_usage` table of the private compose project `fe03b` (written by the simulator and evaluator workers), queried after both runs:
`select provider, operation, count(*), sum(units) from api_usage group by 1,2`.

| Provider | Operation | Rows | Units |
|---|---|---|---|
| Gnani | TTS (timbre-v3.0, synthetic persona voices) | 59 | 3239 characters |
| Gnani | STT REST | 44 | 236.5 audio seconds |
| DeepSeek | caller brain (deepseek-flash) | 32 | 34,046 tokens |
| DeepSeek | judge (deepseek-v4-pro) | 8 | 33,034 tokens |

Runs: `Prompt v2 baseline` (4 calls, clean mock agent, 465 s) and `Prompt v3 candidate (planted bugs)` (4 calls, mock agent with `no_amount_confirm,no_disclosure`, 210 s); one request at a time (`max_concurrency: 1`). Gemini: 0 calls. `est_cost` is empty (COST_* rates are unset in this environment); DeepSeek list-price estimate for ~67k tokens is under USD 0.10. No human voices.
