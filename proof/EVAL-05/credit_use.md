# EVAL-05 external usage (all audio is synthetic Gnani TTS; no human recordings)

Two executions of `live_run.py` (the first before spelling-variant entries were added to
`loanwords.yaml`, the second is the committed proof). Tests use doubles and cost nothing.

| Provider | Operation | Calls | Units |
|---|---|---|---|
| Gnani | TTS (timbre-v3.0), 12 sentences, run 1 only (disk cache hit in run 2) | 12 | 408 characters, 30.72 s of audio |
| Gnani | STT REST `/stt/v3`, 12 clips x 3 conditions, per run | 36 + 36 | 92.16 s + 92.16 s of audio |
| DeepSeek | `llm_asr_intent` (only clips whose normalised text differs from the reference) | 13 (run 1) + 7 (run 2) | 4,360 + 2,384 tokens (input + output) |

Run 2 (committed `usage.json`, from the `api_usage` table): Gnani 36 calls / 92.16 s,
DeepSeek 7 calls / 2,384 tokens. `COST_*` rates are not set in this environment, so `est_cost`
is NULL and spend is reported in units, not money. Total across both runs: 12 TTS + 72 STT calls
(184.32 s STT audio), 20 DeepSeek calls (6,744 tokens).
