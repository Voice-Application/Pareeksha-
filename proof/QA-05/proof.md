# QA-05-verify proof: `make demo`, `make verify`, CI workflows (STATUS: partly done, honest)

Branch `task/QA-05-verify` (from `task/QA-04`). No PR opened, repo not made public.

## Built
- `Makefile`: `demo`, `verify`, `verify-step N=4`, `lint`, `test`. `scripts/demo.sh`: creates `.env`, generates `SECRET_KEY` / `PAREEKSHA_API_KEY` when empty, requires the Gnani and DeepSeek keys, `compose up --build`, health wait, seed, 10-call demo run (`scripts/verify/vapi.py demo`).
- `scripts/verify/`: `run_all.sh` (V1..V11, writes `proof/FINAL_REPORT.md`, exit 1 unless all PASS; PENDING = needs owner input, counts as not passed), one script per step (`v01_proofs.sh`, `step2_demo_timed.sh`, `v03_kafka_run.sh` + `step3_perf_20call.sh` + `step3_kafka_40call.sh`, `v04_planted_bugs.sh/.py`, `v05_webhook_hubspot.sh`, `v06_duplicates.sh`, `v07_dialect.sh`, `step8_github_action.sh`, `v09_calibration.sh`, `v10_adopter_guides.sh`, `v11_release.sh`), `vapi.py` helper, `lib.sh`.
- `.github/workflows/ci.yml` (ruff, mypy, unit/evaluation/judge/contract tests, web lint/tsc/Playwright, SDK tests, build-fail grep) and `.github/workflows/pareeksha-regression.yml` (starts the stack on the runner, applies `examples/ci/pareeksha.yaml`, runs `./action` with the bugs listed in `.github/mock-agent-bugs`; a PR adding a bug there should fail it). Neither has run on GitHub: the regression one needs repo secrets `GNANI_API_KEY` / `DEEPSEEK_API_KEY`.

## Run here (evidence in `proof/verify/V<n>.md`)
| Step | Result here | Note |
|---|---|---|
| V1 | FAIL | 33 of 43 tasks lack a signed verified.md on this branch; build-fail grep hits: `STUB(FE-03)` in `web/app/runs/compare/page.tsx` and a docstring in `api/stubs.py`; 20 single-rule suppressions are listed, not failed |
| V4 | PASS | 4/5 bugs caught with valid cited turns (disclosure, amount, language, waiver... see `V4.catch_report.json`); bugs-off control 1/2 passed (clean-call noise, see FIX-01 proof) |
| V5, V7, V8, V9 | PENDING | need the HubSpot token + consented recording + test contact; consented dialect clips (H-02); the two Action run URLs; 30 human labels |
| V10 | FAIL | no adopter-guide logs exist |
| V11 | FAIL | tag `v1.0.0` missing; repo visibility not readable here (no `gh`) |
| V2, V3, V6 | not run end to end | V2 would rebuild the stack from scratch; V3 spends ~60 calls (the 40-call run was done in QA-03); V6's live replay part untested. Scripts only syntax-checked |

## Suites
- Kafka + integration (`tests/kafka tests/integration`), against the private stack with its own workers stopped: **314 passed, 0 failed, 0 skipped** (`pytest_kafka_integration.txt`). The first run (workers of the stack still consuming the same topics) had 12 failures, all duplicate-DLQ/consumer interference; the failing outbox test the orchestrator mentioned did not reproduce in isolation.
- Unit/evaluation/judge/contract: 954 passed + 1 failure caused by FIX-01 (a test scripting one repair attempt), fixed in `1c408ff`; audit tests rerun: 57 passed. Not rerun as a whole after the fix.
- `mypy`, `ruff check`, `ruff format --check`: clean.

## Bugs found while building V4
`compose run -d` returns before the mock agent listens, so early calls ended `connect_failed` (2/5 caught); stale bug agents pointed at removed containers. Both fixed in `v04_planted_bugs.py`.
