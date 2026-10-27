# RC integration proof (branch integrate/RC)

- Base 66a8f5f (QA-05); DOC-02, EVAL-04b, VOICE-06 were already contained. V10 now reads `proof/DOC-02/guides/N.log` (result: PENDING, guide 5 needs the HubSpot key).
- Suppressions: see `suppressions.md` (3 third-party typing gaps remain). `api/stubs.py` deleted; `STUB(FE-03)` in `web/app/runs/compare/page.tsx` left as instructed.
- Suites (private compose project `prc`, workers stopped for the Kafka/integration tests):
  - backend `pytest tests` (incl. e2e): **1286 passed, 0 failed, 0 skipped** (`pytest_backend_full.txt`); earlier runs with 1 failure kept in `pytest_backend_run*`, `pytest_integration_then_kafka*`: the Kafka-down outbox test shared an outbox with earlier tests; fixed (test clears stale rows; `EventProducer.stop` flush bounded to 15 s).
  - ruff check, ruff format --check, mypy strict: clean. SDK: 50 passed (`pytest_sdk.txt`).
  - web: eslint and `tsc` clean, `next build` ok (`web_build.txt`), Playwright 186 passed (`playwright.txt`).
- V2: PASS, 450 s (`V2.md`, `V2.demo.log`). Base images were pre-pulled from mirror.gcr.io (Docker Hub 429), not counted in the clock; image builds were.
- V6: PASS (`V6.md`, `V6.sink_hits.log`, `V6.kafka_suite.txt`): Kafka suite 9 passed; one evaluation.completed replayed twice plus SIGKILL of the integrations worker gave 1 evaluation and 1 webhook-sink delivery. Note: the extra 1-call run made during V6 ended `error`, so the replayed call was the earlier delivered one.
- V3 skipped as instructed.
