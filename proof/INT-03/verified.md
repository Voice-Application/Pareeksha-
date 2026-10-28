# INT-03: VERIFIED (independent)

Verifier: independent session (built nothing). Date 2026-10-27. Tree verified: b26ff54 (origin/integrate/RC), fresh clone, private compose project `pqa`, ports 1xxxx.
Re-run on this tree (outputs in proof/QA-RC/verifier/): backend `pytest tests` with coverage 1286 passed / 0 failed / 0 skipped / 0 xfail, 96% line+branch coverage (pytest_backend_summary.txt, pytest_backend_tail.txt); `ruff check`, `ruff format --check`, `mypy --strict pareeksha` clean (lint_mypy_ruff_firstrun.txt; mypy needs types-PyYAML, see QA-04); sdk `pytest` 50 passed; web `eslint`, `tsc --noEmit` clean; Playwright mock suite 186 passed (playwright_mock_tail.txt); secret scan (key patterns + literal values of GNANI/DEEPSEEK env keys) over repo and proof/: 0 hits; R3 grep outside tests/examples: only `STUB(FE-03)` in web/app/runs/compare/page.tsx and 3 single-rule `# type: ignore[...]` on third-party gaps (documented in proof/RC/suppressions.md).
Live: one DeepSeek JSON call and one Gnani kn-IN TTS->STT round trip through the project providers succeeded (live_smoke.txt, live_deepseek.txt).

## Task-specific
Tests covering this task on the RC tree (all passed in the full run): tests/integration/test_inbound_webhook.py (15), unit/audit/test_fetch.py (11)
Checks against AGENTS.md section 7 / SCOPE.md done-when: Signed import webhook -> call + audit.requested, bad signature/replay rejected, unsafe URLs refused.
R3 scan of the task's files: clean (no TODO/FIXME/NotImplementedError/skip/xfail/eslint-disable/ts-ignore; no secrets).
Evidence pointer: proof/QA-RC/verifier/ and proof/INT-03/proof.md.

## Pending or not built (listed explicitly, NOT counted as passed)
- HubSpot note from a real webhook-imported recording (V5) PENDING owner token.
