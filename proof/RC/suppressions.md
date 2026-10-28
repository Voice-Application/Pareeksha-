# Remaining lint/type suppressions outside tests/ and examples/

The 20 single-rule suppressions listed in proof/QA-05 were removed by fixing the code (casts and typed locals in
`seed/runner.py`, `routers/regression.py`, `routers/integrations.py`, `speech/config.py`; an explicit key check in
`workers/auditor.py`; a `useLatest` ref hook replaces the five `react-hooks/exhaustive-deps` disables in `web/`).
Inert `noqa`/`type: ignore` comments in `scripts/` and `proof/` (not covered by ruff or mypy) were deleted too.
`backend/pareeksha/api/stubs.py` was deleted (no handler used it).

Kept, with reason (3 type-ignores, all untyped third-party calls; mypy runs `strict`):

| File | Suppression | Why unavoidable |
|---|---|---|
| backend/pareeksha/speech/providers/google.py:59 | `type: ignore[no-untyped-call]` | `google.oauth2.service_account.Credentials.from_service_account_info` is untyped in google-auth |
| backend/pareeksha/simulation/processors.py:115 | `type: ignore[no-untyped-call]` | pipecat `FrameProcessor.cleanup` is untyped |
| backend/pareeksha/simulation/vad.py:107 | `type: ignore[no-untyped-call]` | pipecat `VADAnalyzer.cleanup` is untyped |

Coverage pragmas (`# pragma: no cover`, not lint or type checks): `llm/_retry.py:38`, `db/queries.py:10,19`,
`workers/generator.py:84`, `sdk/.../cli.py:266`; each marks a branch that cannot run in the test environment.
