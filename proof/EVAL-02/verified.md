# EVAL-02 verified

- Date: 2026-10-23
- SHA verified: 140079175b5e0d1c7537c2d202801976c8832428 (task/EVAL-02), clean worktree, fresh venv (Python 3.13.17; pytest, pytest-cov, rapidfuzz, ruff)
- Re-run: `cd backend && python -m pytest tests/evaluation -q --cov=pareeksha/evaluation -rsx` -> 108 passed, 0 skipped, 0 xfail. Output: proof/EVAL-02/verifier/pytest.out
- Coverage on evaluation/: 97% (SCOPE requires >= 70%)
- `ruff check .` -> All checks passed; `ruff format --check .` -> 11 files already formatted. (No type checker is configured in the repo.)
- Spot checks (own script): naal-ku saavira / 4,000 / four thousand / चार हज़ार / ನಾಲ್ಕು ಸಾವಿರ / 4k all -> 4000; 2.5 lakh -> 250000; PII masks phone/Aadhaar/PAN; "EMI 40000" vs expected 4000 -> amount_confirmed failed ("Expected 4000; agent confirmed 40000").
- Stub scan of changed non-test files: no STUB(, TODO, FIXME, NotImplementedError, skips/xfail, noqa, type-ignore, or secrets.
- Rubric (docs/08 section 6) conformance: latency, first greeting, barge-in, agent stop time, silence gaps, talk ratio, WER match formulas. Documented deviations (module docstrings, acceptable): negative-latency pairs excluded and counted separately; repeated-utterance metric ignores agent turns under 3 words; barge-in with no agent speech to interrupt counts as honoured; no_loop check fails at 3+ near-identical agent turns.
- Note: SCOPE.md and the base branch moved after the builder's merge-base (49c6392); SCOPE criteria were read from claude/amazing-einstein-agkccc. Builder's branch diff vs base shows unrelated deletions only because the base advanced; the EVAL-02 changes themselves are confined to backend/pareeksha/evaluation, backend/tests/evaluation, proof/EVAL-02 (plus small STATUS.md/NOTES.md edits).
