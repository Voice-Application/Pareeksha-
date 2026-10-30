# FIX-03 verified (2026-10-30, SHA 9330f69)
Clean worktree, fresh python3.12 venv, ci.yml install recipe. Outputs in proof/FIX-03/verifier/.
- Lint: mypy 2.4.1, ruff 0.17.3 (pinned): `ruff check`, `ruff format --check` (340 files), bare `mypy` (344 files) all clean (`lint.txt`). Web half of `make lint` not run.
- pytest with --cov (tests/unit evaluation judge contract): 994 passed, 1 failed, 0 skipped, coverage 75% total (`pytest.txt`). The one failure is `test_committed_schema_dts_matches_the_backend_openapi`: "run `npm ci` in web/ first". ci.yml runs `npm ci` before pytest and I had not. After `npm ci`, tests/contract: 127 passed (`pytest_contract_after_npm_ci.txt`). So 995 passed, 0 failed, 0 skipped with the CI sequence.
- One live silent-caller call (real Gnani + DeepSeek, in-process as the proof does; `live_call.json/log`): call 199ecedb-cbe8-4746-9f4b-943cb9a0b8e3, end_reason agent_hangup, error None, 10 silence events, evaluation status ok, score 88.75, passed, judge deepseek-v4-pro. Evaluated, not infra_error.
- Diff 6ebe99b..9330f69 outside tests/ and proof/: no STUB/TODO/FIXME/NotImplementedError, no skips/xfail, no type: ignore or noqa, no hardcoded results. Tests added/changed contain no skip/xfail/ignore either.
Caveat: silent-turn length (5.0 s) is the builder's choice; the live call is in-process, not through the full stack.
