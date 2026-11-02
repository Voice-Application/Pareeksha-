# EVAL-06 rejected (verifier, 2026-11-02, verified inside aa07ff1, which contains 7d347ba)

**One blocker: `mypy` not clean.** `backend/tests/unit/test_calibration_import_labels.py` has 6 errors under the pinned
mypy 2.4.1 (lines 129, 233, 255, 323, 373, 382: bare `dict`, `round(float|None)`, untyped `cal`). See
`proof/EVAL-07/rejected.md` and `proof/EVAL-07/verifier/mypy.txt`.

Everything else passed: kappa v1 recomputed **0.1892 on n=30** with `compute_calibration` from the stored owner labels
and judge results; the DB dump holds 30 `human_reviews` (reviewer preetham, posted through `POST /calls/{id}/review`);
the importer stops when `GET /calibration` n differs from the labelled rows (`import_labels.py:776,782`); its 38 tests
pass; ruff clean; no STUB/TODO/skip in the diff.
