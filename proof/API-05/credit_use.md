# API-05 external usage

Tests use scripted model answers and cost nothing. One live run of `live_run.py`:

| Provider | Operation | Calls | Units |
|---|---|---|---|
| DeepSeek (`LLM_PROVIDER=deepseek`, caller model from `DEEPSEEK_CALLER_MODEL`) | `llm_scenario_gen`: 10 scenario drafts, one batch, no repair retry | 1 | 3,477 tokens (input + output, from `api_usage`) |

No Gnani or Gemini calls. `COST_DEEPSEEK_*` rates are not set in this environment, so `est_cost`
is NULL; spend is reported in tokens.
