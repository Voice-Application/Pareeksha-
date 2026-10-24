# EVAL-01 proof: LLM providers, client, caller_v1

## Built
- `pareeksha/llm/deepseek.py` (default, OpenAI-compatible JSON mode, schema in prompt, thinking off), `gemini.py` (REST generateContent, native `responseJsonSchema`), both behind the frozen `llm/base.py`; 3 retries with backoff (`_retry.py`), 429/5xx/timeout/empty content = retryable, other 4xx/safety = permanent (`_http.py`).
- `client.py`: `LLMClient.generate_json` = pydantic validation, one repair retry (also for a caller-supplied `semantic_check`), `UsageRecord` per provider call to a sink + log (tokens, cached tokens, est. cost, prompt hash), optional response cache (`InMemoryJSONCache`, `FileJSONCache`). `factory.py` selects by `LLM_PROVIDER`. `prompts.py` renders Jinja2 templates; `prompt_hash` = sha256 of the unrendered file.
- `prompts/caller_v1.j2` + `caller.py` (`CallerBrain.next_utterance`).
- `pyproject.toml`: added runtime deps httpx, jinja2 and packaged `prompts/*.j2`.

## Reproduce
```
cd backend && pip install -e ".[dev]" rapidfuzz gnani-vachana
python -m pytest -q --cov=pareeksha.llm          # see pytest_output.txt
ruff check . && ruff format --check . && python -m mypy
python ../proof/EVAL-01/run_acceptance.py        # needs DEEPSEEK_API_KEY; writes acceptance.json, usage.jsonl
```

## Real-API results (DeepSeek, `acceptance.json`)
- Schema-valid JSON from `deepseek-v4-pro` (temp 0, thinking off).
- Repair: first answer rejected by a semantic check, second real call produced the valid object (`repaired: true`, tokens summed).
- caller_v1, kn-IN elderly persona: opening line in Kannada script; hi-IN heavy code-mix persona: Devanagari with Latin English loanwords. Same seed twice gives the identical utterance (second is a cache hit, 0 tokens).
- Honest limit: with no cache, two temperature-0 calls with the same prompt were NOT identical (`kn_uncached_repeat_identical: false`; DeepSeek does not document a seed). Reproducibility per seed therefore comes from the seed-keyed response cache (`cache_salt=caller:<seed>:<turn>`), which VOICE-04/VOICE-05 must pass a persistent `FileJSONCache` to if they need it across processes.
- Gemini: ONE real smoke call is **blocked**: `GEMINI_API_KEY` is empty in this environment (needs H-01 key; pinned model IDs `GEMINI_*_MODEL` also unset; script defaults to `gemini-3.5-flash-lite` for the smoke). Provider is unit-tested against recorded-shape mock responses only; its request field names come from ai.google.dev/api/generate-content, `responseJsonSchema`/`thinkingConfig` were not verifiable live.
- Spend: `credit_use.md` (7 billed calls, about $0.001).

## Not done / dependencies
- "Caller brain wired into VOICE-04": VOICE-04 does not exist yet; `CallerBrain` is the integration surface (takes persona, scenario, history, seed).
- Usage sink writing `api_usage` rows needs the DB layer (not present); sink is a callback.
- Env note: python 3.13 lacks `audioop` (VOICE-02 tests import it); installed `audioop-lts` locally only. Project targets 3.11/3.12.
