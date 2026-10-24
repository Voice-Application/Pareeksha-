# M1-INTEGRATION fix proof
Branch task/M1-fix (from integrate/M1 765b14d). Run from backend/ (needs `pip install gnani-vachana`).
- pytest: 540 passed, 0 skipped (pytest.txt)
- ruff check: clean (ruff_check.txt)
- ruff format --check: 76 files formatted (ruff_format.txt)
- mypy strict: no issues in 76 files (mypy.txt)
Changes: ruff format (14 files, whitespace only); E731 lambda -> def; full annotations in tests/unit/gnani/test_clients.py (cache_key test rewritten with typed kwargs, same 8 distinct keys asserted; asyncio imported directly in test, same module object); `float(...)` in wav_duration_s (no-op); narrow mypy override `gnani.tts` ignore_missing_imports in pyproject.toml. No globals disabled, no type: ignore.
