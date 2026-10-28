# INT-04 proof

Built: `sdk/python/` (package `pareeksha-sdk`, import name `pareeksha_sdk`): sync `Pareeksha` and async `AsyncPareeksha` clients (agents, scenarios, personas, noise profiles, runs create/wait/items/cancel/regression, audits, DLQ, health), pydantic response models, retry on 5xx and transport errors (POST only on 502/503/504 so a retry cannot create a second run); `pareeksha.yaml` loader + idempotent `apply` by name; Typer CLI `login, apply, run, regress, audit, dlq list|replay, doctor`; Markdown job summary; `action/action.yml` composite GitHub Action (installs SDK, `apply`, `run --suite ... --wait`, optional `regress`; the CLI appends the summary to `$GITHUB_STEP_SUMMARY` and exits 1 on failure). Exit codes: 0 ok, 1 failed threshold/suite/run, 2 tool or API error.

Reproduce (from `sdk/python/`): `pip install -e ".[dev]"; python -m pytest -q --cov; python -m mypy; ruff check .; ruff format --check .; python ../../proof/INT-04/demo.py`
Actual: `pytest.txt` 50 passed, 0 failed, 0 skipped, 99% coverage; mypy strict and ruff clean. `demo_output.txt` drives the real `pareeksha` executable (subprocesses, real HTTP): first apply = 5 writes, second apply = "0 change(s)", writes stay 5; `run --fail-under 101` exits 1; `regress` with a failing suite exits 1; the summary blocks that the Action publishes are shown at the end.

Acceptance mapping: sync+async = test_client.py (both use real HTTP); non-zero on failure = test_cli.py (exit 1 / 2 cases); `apply` twice changes nothing = test_cli.py::test_apply_twice_changes_nothing (asserts zero server writes); Action summary + fail on regression = test_run_passes_and_writes_github_step_summary, test_regress_exit_codes, action/action.yml.

Limits stated plainly:
- The backend run/agent/audit/DLQ routes are still 501 stubs (API-02/03/04, EVAL-04), so everything ran against `sdk/python/tests/fake_platform.py`, an in-memory server written from docs/06-api-spec.md. It has not been run against the real API; wire-format drift is the risk until those tasks land.
- `action/action.yml` was parsed as YAML but not executed on a GitHub runner.
- `doctor` checks API, db and Kafka through `/health`; Gnani and Gemini are reported "n/a" because the API has no probe for them.
- The SDK models are hand-written (extra fields kept), not generated with datamodel-code-generator.
- The import name is `pareeksha_sdk`, not `pareeksha` as docs/10 section 3.1 shows, because the backend already owns the `pareeksha` package.

Code commit: 2551340 (branch task/INT-04)
