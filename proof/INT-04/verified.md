# INT-04: VERIFIED (independent, qa/RC2)

Date 2026-10-27. Tree verified: 9b1ffbc (origin/task/FIX-02), fresh clone, fresh venv. Verifier built nothing. Supersedes proof/INT-04/rejected.md (kept in git history).

Re-run: fresh venv, `pip install -e "sdk/python[dev]"`, `pytest -q sdk/python`: **50 passed** (python-multipart now in dev extras). No green GitHub Actions sdk job link was observed from this session; the failing cause (clean install) is reproduced fixed.
