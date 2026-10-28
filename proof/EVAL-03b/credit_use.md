# EVAL-03b LLM usage (real DeepSeek judge calls)

| Phase | Model | Calls | Input tok | Output tok | Est. cost USD |
|---|---|---|---|---|---|
| Acceptance run (`acceptance.txt`) | deepseek-v4-pro | 1 | 2230 | 491 | 0.00489 |
| pytest (exactly-once, crash, finalizer tests) | scripted provider (no network) | 0 | 0 | 0 | 0 |
| **Total** | | **1** | **2230** | **491** | **0.00489** |

Rates: v4-pro list price $1.32 in / $3.96 out per 1M tokens (cache miss, peak), passed to the
containers as `COST_DEEPSEEK_PER_1K_INPUT_TOKENS=0.00132` / `..._OUTPUT_TOKENS=0.00396`.
The single call is also the single `api_usage` row of the run (`provider=deepseek, operation=llm_judge,
units=2721 tokens, est_cost=0.0049`, see `acceptance.txt`). The call.completed event was delivered twice;
the duplicate did not reach the judge. A first attempt of the acceptance run failed before any request left
the container (sandbox proxy CA missing, `CERTIFICATE_VERIFY_FAILED`), so it cost nothing. Gemini: 0 calls.
