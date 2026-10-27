# QA-03: REJECTED (independent)

Verifier: independent session (built nothing). Date 2026-10-27. Tree verified: b26ff54 (origin/integrate/RC), fresh clone, private compose project `pqa`, ports 1xxxx.
Re-run on this tree (outputs in proof/QA-RC/verifier/): backend `pytest tests` with coverage 1286 passed / 0 failed / 0 skipped / 0 xfail, 96% line+branch coverage (pytest_backend_summary.txt, pytest_backend_tail.txt); `ruff check`, `ruff format --check`, `mypy --strict pareeksha` clean (lint_mypy_ruff_firstrun.txt; mypy needs types-PyYAML, see QA-04); sdk `pytest` 50 passed; web `eslint`, `tsc --noEmit` clean; Playwright mock suite 186 passed (playwright_mock_tail.txt); secret scan (key patterns + literal values of GNANI/DEEPSEEK env keys) over repo and proof/: 0 hits; R3 grep outside tests/examples: only `STUB(FE-03)` in web/app/runs/compare/page.tsx and 3 single-rule `# type: ignore[...]` on third-party gaps (documented in proof/RC/suppressions.md).
Live: one DeepSeek JSON call and one Gnani kn-IN TTS->STT round trip through the project providers succeeded (live_smoke.txt, live_deepseek.txt).

## Findings
Done-when: 'with bugs off the pass rate is high'. Builder's own evidence shows the clean 40-call run (run 8422cb13) has pass_rate 0.0 with 29 critical failures, clean-b and clean-c personas fail 0/2, and the post-fix clean control (FIX-01) passed 1 of 2. Only cooperative personas pass. The >=4/5 bug catch half is verified: catch_report.json shows 4 of 5 with cited turns, the 40-call run is 38 evaluated + 1 error + 1 judge_error = 39/40 (97.5%) free of infra errors, lag 0 (inspected, not re-spent). To pass: a bugs-off run showing a high pass rate on the demo matrix, or a written scope change.

CI evidence: proof/QA-RC/verifier/ci_status.md
