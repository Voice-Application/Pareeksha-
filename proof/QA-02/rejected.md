# QA-02: REJECTED (independent)

Verifier: independent session (built nothing). Date 2026-10-27. Tree verified: b26ff54 (origin/integrate/RC), fresh clone, private compose project `pqa`, ports 1xxxx.
Re-run on this tree (outputs in proof/QA-RC/verifier/): backend `pytest tests` with coverage 1286 passed / 0 failed / 0 skipped / 0 xfail, 96% line+branch coverage (pytest_backend_summary.txt, pytest_backend_tail.txt); `ruff check`, `ruff format --check`, `mypy --strict pareeksha` clean (lint_mypy_ruff_firstrun.txt; mypy needs types-PyYAML, see QA-04); sdk `pytest` 50 passed; web `eslint`, `tsc --noEmit` clean; Playwright mock suite 186 passed (playwright_mock_tail.txt); secret scan (key patterns + literal values of GNANI/DEEPSEEK env keys) over repo and proof/: 0 hits; R3 grep outside tests/examples: only `STUB(FE-03)` in web/app/runs/compare/page.tsx and 3 single-rule `# type: ignore[...]` on third-party gaps (documented in proof/RC/suppressions.md).
Live: one DeepSeek JSON call and one Gnani kn-IN TTS->STT round trip through the project providers succeeded (live_smoke.txt, live_deepseek.txt).

## Findings
SCOPE says 'Kafka suite ... green in CI'. On b26ff54 the `kafka-suite` workflow (run 40528331890) and the three earlier RC pushes ended in FAILURE (step 'Kafka suite', ~10 min); the failing assertion could not be extracted from the log. Locally the suite is green (tests/kafka 9 passed inside my 1286-pass run). Also the CI `ci` backend job cannot even collect tests (see QA-04). To pass: a green kafka-suite run link on the RC head.

CI evidence: proof/QA-RC/verifier/ci_status.md
