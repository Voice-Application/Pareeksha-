GitHub Actions on b26ff54 (integrate/RC), checked via GitHub API 2026-10-27:
- ci run 40528331456: FAILURE. web job success. sdk job FAIL (27 errors: RuntimeError python-multipart not installed; `pip install sdk/python[dev]` does not pull it).
  build-fail-grep FAIL: `web/app/runs/compare/page.tsx:1: STUB(FE-03)`.
  backend job FAIL: pytest collection error in tests/contract/test_event_schemas.py (jsonschema not in backend/requirements-dev.txt; also types-PyYAML only passed on the CLI line).
- kafka-suite run 40528331890: FAILURE (step "Kafka suite", 10 min; failing assertion not extracted from the log).
Reproduced locally: ModuleNotFoundError jsonschema and mypy "stubs not installed for yaml" with requirements-dev.txt only.
