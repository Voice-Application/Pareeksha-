# FIX-03 proof: mypy clean and pinned; silent caller is silence, not infra_error

Base: main @6ebe99b. Branch: task/FIX-03. Commit: see the last line.

## 1. mypy / ruff (fresh venv, as .github/workflows/ci.yml installs)

```
python3.12 -m venv v && . v/bin/activate
pip install -r requirements.txt -r backend/requirements-dev.txt && pip install --no-deps -e backend
cd backend && mypy        # unpinned install resolved mypy 2.4.1, ruff 0.17.3
```
Before: 5 errors, `mock_agent/policy.py:469,499,509` (dict-item) and `tests/unit/speech/test_deepgram.py:229,254` (index).
CI and `make lint` ran `mypy pareeksha`, which skips `tests` and `../mock_agent` (`files` in pyproject.toml), so they never saw these.

Fix in code, no `type: ignore`: `tool: ToolCall = (...)` on the first assignment in each function; `next(iter(server.sockets))`.
Makefile and CI now run bare `mypy`. Pinned: mypy==2.4.1, ruff==0.17.3, types-PyYAML==6.0.12.20261030, types-jsonschema==4.26.0.20261006 (requirements-dev.txt and pyproject.toml).

After (`proof/FIX-03/lint.log`, `ruff check . ; ruff format --check . ; mypy`):
```
All checks passed!
340 files already formatted
Success: no issues found in 344 source files
```
The web half of `make lint` (npm lint, tsc) was not run.

## 2. Silent caller

Cause: the persona's line is punctuation only ("…"). Gnani returns HTTP 500 "No audio generated during synthesis"; that is a 5xx, so it was retried until the 25 s caller-TTS timeout, then infra_error.

Change:
- `simulation/processors.py`: `CallerTTS` does not call the provider for text without a letter, digit or Indic mark (`speech/text.py: has_speakable_text`). It plays `SimulationSettings.silent_turn_s` (5.0 s, my choice; the spec gives no duration) of zero PCM, logs `caller_silence`. A punctuation-only trailing part of a spoken line is dropped.
- `speech/base.py`: `SpeechNoAudioError(SpeechPermanentError)`, raised for "no audio generated" in `speech/http.py` (all HTTP providers) and in `gnani/clients.py is_retryable` / `providers/gnani.py _map_error`. Not retried.

Unit tests: `tests/unit/speech/test_core.py` (permanent, one request; other 500s still retry; speakable cases), `test_gnani_adapter.py`, `gnani/test_clients.py` (one attempt), `simulation/test_call_runner.py` (a "..." line: no TTS call, 1.5 s silent turn, not infra_error; trailing "..." dropped).

Full suite (`proof/FIX-03/pytest.log`): `cd backend && python -m pytest tests/unit tests/evaluation tests/judge tests/contract -q -p no:cacheprovider --cov=pareeksha`
```

86 files skipped due to complete coverage.
995 passed, 4 warnings in 361.34s (0:06:01)
```
Coverage of the touched modules:
```
pareeksha/gnani/clients.py                        167      1     30      1    99%   96
pareeksha/simulation/processors.py                341      9     98      6    97%   96-97, 101, 165->141, 168-
```

## 3. One live call (real Gnani + DeepSeek, mock agent)

No Docker or Postgres in this sandbox, so it runs in-process: `PYTHONPATH=.:backend python proof/FIX-03/live_silent_call.py proof/FIX-03/live_call.json`
(CallRunner + real STT/TTS + caller brain, then `evaluate_call`, the code the evaluator worker runs.)

- Scenario "Caller goes silent", persona "The Silent One", call id **3c391613-6813-4647-8e3e-3c0ec56b6550**
- end_reason `agent_hangup`, error none, 180 s
- 4 silent caller turns (text "…", 5.0 s each, `caller_silence` events), each followed by the nudge "हैलो, क्या आप सुन रहे हैं?" and the agent's answer; the agent finally transfers to a human
- Evaluation (`live_call.json`):
```
{
  "status": "ok",
  "overall_score": 97.5,
  "passed": true,
  "critical_failure": false,
  "failure_types": [],
  "summary": "Agent handled silent caller well: checked presence, avoided loops, and transferred to human. All mandatory disclosures and facts correct. Minor: could have acknowledged caller's frustration more explicitly.",
  "judge_model": "deepseek-v4-pro"
}
```
The judge transcript lists the silent turns as caller turns "…" with start/end ms, so the silence handling is visible to it. Full turns, events and dimension scores: `live_call.json`; run output: `live_call.log`.

## Honest status
- DONE: items 1 and 2 as above. One live call only, as asked; a single sample, not a pass rate.
- The call is not through the full stack (see above).
- The first full run had the schema contract test failing because `npm ci` had not been run in web/ (same on main); after `npm ci` it passes.
