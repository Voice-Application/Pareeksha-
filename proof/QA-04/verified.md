# QA-04: VERIFIED (independent, qa/RC2)

Date 2026-10-27. Tree verified: 9b1ffbc (origin/task/FIX-02), fresh clone, fresh venv. Verifier built nothing. Supersedes proof/QA-04/rejected.md (kept in git history).

Re-run from fresh venv (`pip install -r requirements.txt -r backend/requirements-dev.txt` + `pip install --no-deps -e backend`): `ruff check .` clean, `ruff format --check .` clean (339 files), `mypy pareeksha` clean (184 files). CI's pytest set (unit, evaluation, judge, contract): 974 passed; the only failure, test_schema_dts_fresh, needs `npm ci` in web/ as ci.yml does; after `npm ci` contract tests **127 passed**. No green Actions run link observed.
