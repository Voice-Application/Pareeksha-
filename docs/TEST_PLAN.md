# Test Plan (QA-01)

Version 1.0, 24 Oct 2026. Owner: QA. Sources: `docs/02-requirements.md`, `docs/SCOPE.md`, `docs/01-PRD.md` section 8, `docs/orchestration/GOAL.md`.

Owner decision applied: the default LLM (caller brain, judge, scenario generator, mock agent) is **DeepSeek**; **Gemini is optional**. Requirement text that says "Gemini" is read as "the configured LLM provider". Tests go through the single `llm/` module and are parametrised on the provider; acceptance runs use DeepSeek. A Gemini smoke test sits behind the `gemini_optional` pytest marker and is deselected (not skipped) in `make verify`.

## 1. Rules for every test

- Test owner = the task that writes the test and keeps it green. Feature task = the task that builds the code under test. QA reviews every builder test and never verifies its own work.
- Levels: `unit` (no network), `integration` (API + real Postgres), `kafka` (real Kafka via Compose or Testcontainers), `connectors` (respx mocks allowed, plus one live HubSpot test), `judge` (LLM schema and scoring; live DeepSeek in acceptance), `contract` (OpenAPI, event schemas, bundle scan, secret scan), `e2e` (live Gnani, DeepSeek, Kafka, Postgres, HubSpot; no mocks), `playwright` (UI with real data and screenshots), `manual` (verifier follows a guide, log kept).
- Mocks of Gnani, DeepSeek, Gemini, HubSpot or Kafka are allowed only in `unit`, `connectors` and `integration` tests. Nothing that `make verify` cites as acceptance evidence may use them.
- Zero skipped, zero xfail, zero failed. ruff, eslint and tsc are never disabled. Coverage >= 70% on `audio/` and `evaluation/` (NFR-12).
- Test locations are planned paths from `docs/07-file-structure.md` (`backend/tests/{unit,contract,kafka,connectors,judge,e2e,integration}`, `web/tests`, `sdk/python/tests`, `scripts/verify`). "(built)" marks tests that already exist from EVAL-02 and VOICE-02 under their current paths. A builder who places a test elsewhere updates this table in the same change.
- FR-DI-5, FR-DX-8 and FR-DX-9 are Could/Should items with no scheduled acceptance criterion in SCOPE.md. They stay mapped so no ID is orphaned and are reported "not built" (not failed) if cut with Preetham's written approval (AGENTS section 10).

## 2. Requirement to test map (99 IDs: 81 FR, 18 NFR)

| Req ID | Pri | Test ID | Level | Planned test location | Test owner task | Feature task(s) | What the test proves |
|---|---|---|---|---|---|---|---|
| FR-AG-1 | M | T-FR-AG-1 | integration | `backend/tests/integration/test_agents_api.py::test_crud_archive` | API-02 | API-02, FE-02 | CRUD via API; archived agent rejected by POST /runs |
| FR-AG-2 | M | T-FR-AG-2 | contract | `backend/tests/contract/test_agent_fields.py` | API-02 | API-02 | all fields round-trip via GET /agents/{id} |
| FR-AG-3 | M | T-FR-AG-3 | e2e | `backend/tests/e2e/test_agent_test_connection.py` | QA-05 | API-02, VOICE-03 | ok + first-audio latency vs mock agent; error cases DNS/refused/timeout/protocol |
| FR-AG-4 | S | T-FR-AG-4 | integration | `backend/tests/integration/test_glass_box_store.py` | VOICE-04 | VOICE-04, VOICE-03 | glass_box agent => agent transcript + tool calls stored per turn |
| FR-SC-1 | M | T-FR-SC-1 | integration | `backend/tests/integration/test_scenarios_api.py` | API-02 | API-02, FE-02 | create/edit with all fields |
| FR-SC-2 | M | T-FR-SC-2 | judge | `backend/tests/judge/test_scenario_generator.py` | API-05 | API-05 | 10 drafts schema-valid; live DeepSeek run (Gemini optional) |
| FR-SC-3 | M | T-FR-SC-3 | e2e | `backend/tests/e2e/test_scenario_two_languages.py` | QA-05 | API-02, VOICE-05 | same scenario, Kannada and Hindi persona, no edits |
| FR-SC-4 | M | T-FR-SC-4 | integration | `backend/tests/integration/test_scenario_source.py` | API-05 | API-02, API-05 | promoted scenario links its source call |
| FR-PE-1 | M | T-FR-PE-1 | unit | `backend/tests/unit/test_persona_schema.py` | API-02 | API-02 | schema validation accepts/rejects |
| FR-PE-2 | M | T-FR-PE-2 | integration | `backend/tests/integration/test_seed.py::test_20_personas_and_idempotent` | API-02 | API-02 | 20 personas (>=6 kn, >=6 hi, >=4 en-IN, extras); seed twice, no dupes |
| FR-PE-3 | S | T-FR-PE-3 | e2e | `backend/tests/e2e/test_persona_preview.py` | FE-02 | API-02, FE-02 | preview returns playable audio (live Gnani) |
| FR-NP-1 | M | T-FR-NP-1 | unit | `backend/tests/unit/test_noise_profile_schema.py` | API-02 | API-02 | schema validation |
| FR-NP-2 | M | T-FR-NP-2 | unit | `backend/tests/unit/audio/test_profiles_distinct.py` | VOICE-02 | VOICE-02 | 8 profiles render audible, mutually distinct (built; proof/VOICE-02) |
| FR-NP-3 | M | T-FR-NP-3 | unit | `backend/tests/unit/audio/test_snr.py` | VOICE-02 | VOICE-02 | SNR within +-0.5 dB (built) |
| FR-NP-4 | M | T-FR-NP-4 | unit | `backend/tests/unit/audio/test_determinism.py` | VOICE-02 | VOICE-02 | same seed byte-identical; chunked equals whole (built) |
| FR-RN-1 | M | T-FR-RN-1 | integration | `backend/tests/integration/test_matrix_expand.py` | API-03 | API-03 | 3x2x2 gives 12 run items |
| FR-RN-2 | S | T-FR-RN-2 | integration | `backend/tests/integration/test_cost_estimate.py` | API-03 | API-03, FE-03 | over-budget run gets 402-style error with estimate |
| FR-RN-3 | M | T-FR-RN-3 | kafka | `backend/tests/kafka/test_run_cap_and_outbox.py` | QA-02 | API-03, VOICE-05 | run + outbox row atomic; active calls never exceed cap; leaked slot reconciled |
| FR-RN-4 | M | T-FR-RN-4 | e2e | `backend/tests/e2e/test_single_call.py` | QA-05 | VOICE-04, EVAL-01 | call vs mock agent has >=4 turns (live Gnani + DeepSeek) |
| FR-RN-5 | M | T-FR-RN-5 | integration | `backend/tests/integration/test_end_reasons.py` | VOICE-04 | VOICE-04 | each end condition yields a recorded end_reason |
| FR-RN-6 | M | T-FR-RN-6 | unit | `backend/tests/unit/simulation/test_barge_in.py` | VOICE-04 | VOICE-04 | barge-in start 0.8-2.5 s, seeded, logged |
| FR-RN-7 | M | T-FR-RN-7 | integration | `backend/tests/integration/test_recordings.py` | VOICE-04 | VOICE-04 | 3 files, mono 16 kHz tracks + stereo mix, durations within 100 ms |
| FR-RN-8 | M | T-FR-RN-8 | integration | `backend/tests/integration/test_turns_table.py` | VOICE-04 | VOICE-04 | per-turn fields populated |
| FR-RN-9 | M | T-FR-RN-9 | kafka | `backend/tests/kafka/test_retry_dlq_throttle.py` | QA-02 | INFRA-02 | 3 failures -> retry.30s, retry.5m, one DLQ row; throttle never reaches DLQ |
| FR-RN-10 | S | T-FR-RN-10 | e2e | `backend/tests/e2e/test_cancel_run.py` | QA-05 | API-03, VOICE-05 | cancel in <10 s, calls hang up |
| FR-RN-11 | S | T-FR-RN-11 | integration | `backend/tests/integration/test_dry_run_zero_cost.py` | VOICE-05 | VOICE-05 | 20-item dry run writes zero Gnani api_usage rows |
| FR-EV-1 | M | T-FR-EV-1 | unit | `backend/tests/evaluation/test_metrics.py` | EVAL-02 | EVAL-02 | latency p50/90/95, gaps, talk ratio etc. (built) |
| FR-EV-2 | M | T-FR-EV-2 | unit | `backend/tests/evaluation/test_checks.py` | EVAL-02 | EVAL-02 | disclosure, forbidden, tools, language match (built) |
| FR-EV-3 | M | T-FR-EV-3 | judge | `backend/tests/judge/test_judge_schema_repair.py` | EVAL-03 | EVAL-03 | schema-valid output, one repair retry then judge_error; DeepSeek default |
| FR-EV-4 | M | T-FR-EV-4 | unit | `backend/tests/evaluation/test_scoring_formula.py` | EVAL-03 | EVAL-03 | weighted 0-100; pass = >=80, no critical, must-pass checks |
| FR-EV-5 | M | T-FR-EV-5 | integration | `backend/tests/integration/test_eval_audit_fields.py` | EVAL-03 | EVAL-03 | rubric version, prompt hash, model id, temp, tokens, latency non-null |
| FR-EV-6 | M | T-FR-EV-6 | judge | `backend/tests/judge/test_needs_human_review_rule.py` | EVAL-03 | EVAL-03 | rule enforced in code regardless of judge output |
| FR-EV-7 | S | T-FR-EV-7 | integration | `backend/tests/integration/test_human_review.py` | API-05 | API-05, FE-04 | per-dimension human scores stored |
| FR-EV-8 | S | T-FR-EV-8 | unit | `backend/tests/unit/test_calibration.py` | API-05 | API-05 | Cohen kappa and Spearman equal hand-computed values |
| FR-EV-9 | M | T-FR-EV-9 | unit | `backend/tests/evaluation/test_pii.py` | EVAL-02 | EVAL-02 | phone/Aadhaar/PAN masked (built) |
| FR-AU-1 | M | T-FR-AU-1 | integration | `backend/tests/integration/test_audit_upload.py` | EVAL-04 | EVAL-04 | WAV/MP3 <=10 MB stored, source=upload; >10 MB rejected |
| FR-AU-2 | M | T-FR-AU-2 | e2e | `backend/tests/e2e/test_audit_batch_stt.py` | QA-05 | EVAL-04 | diarized turns with speaker labels (live Prisma) |
| FR-AU-3 | M | T-FR-AU-3 | integration | `backend/tests/integration/test_agent_role_swap.py` | EVAL-04 | EVAL-04 | speaker_role assigned; swap re-runs evaluation |
| FR-AU-4 | M | T-FR-AU-4 | integration | `backend/tests/integration/test_audit_same_rubric.py` | EVAL-04 | EVAL-04 | audit evaluation uses same rubric version |
| FR-AU-5 | S | T-FR-AU-5 | integration | `backend/tests/integration/test_promote_to_regression.py` | API-05 | API-05, FE-04 | scenario + regression test linked to source call, baseline set |
| FR-DI-1 | M | T-FR-DI-1 | unit | `backend/tests/unit/dialect/test_manifest_consent.py` | EVAL-05 | EVAL-05 | rows without consent=true rejected |
| FR-DI-2 | M | T-FR-DI-2 | integration | `backend/tests/integration/test_asr_results_rows.py` | EVAL-05 | EVAL-05 | one asr_result per clip x condition |
| FR-DI-3 | M | T-FR-DI-3 | unit | `backend/tests/unit/dialect/test_asr_metrics.py` | EVAL-05 | EVAL-05 | normalised WER/CER/entity accuracy on known pairs |
| FR-DI-4 | M | T-FR-DI-4 | unit | `backend/tests/unit/dialect/test_bootstrap_ci.py` | EVAL-05 | EVAL-05 | speaker-grouped bootstrap CI; HTML report renders |
| FR-DI-5 | C | T-FR-DI-5 | unit | `backend/tests/unit/dialect/test_comparator_column.py` | EVAL-05 | EVAL-05 | Could, unscheduled: reported "not built" unless built |
| FR-DI-6 | S | T-FR-DI-6 | unit | `backend/tests/unit/dialect/test_bias_list.py` | EVAL-05 | EVAL-05 | bias_list suggestions in report |
| FR-RG-1 | S | T-FR-RG-1 | integration | `backend/tests/integration/test_regression_fields.py` | API-05 | API-05 | status, failure type, baseline stored |
| FR-RG-2 | S | T-FR-RG-2 | integration | `backend/tests/integration/test_regression_suite.py` | API-05 | API-05 | fails on score < baseline - tolerance(5) or critical failure |
| FR-RG-3 | S | T-FR-RG-3 | integration | `backend/tests/integration/test_run_compare.py` | API-04 | API-04, FE-03 | per-cell delta, regressions first |
| FR-RG-4 | C | T-FR-RG-4 | integration | `sdk/python/tests/test_cli_exit_codes.py` | INT-04 | INT-04 | exit 1 on suite failure |
| FR-DB-1 | M | T-FR-DB-1 | playwright | `web/tests/smoke.spec.ts` | QA-04 | FE-02, FE-03, FE-04, FE-05 | every page reachable from sidebar; screenshot with real data |
| FR-DB-2 | M | T-FR-DB-2 | playwright | `web/tests/run_detail.spec.ts` | QA-04 | FE-03 | 40-call run renders <3 s; new evaluated call appears <2 s without reload |
| FR-DB-3 | M | T-FR-DB-3 | playwright | `web/tests/call_detail.spec.ts` | QA-04 | FE-04 | evidence turn click seeks audio |
| FR-DB-4 | M | T-FR-DB-4 | playwright | `web/tests/dialect.spec.ts` | QA-04 | FE-05 | heatmap, metric selector, drill-down |
| FR-DB-5 | M | T-FR-DB-5 | contract | `web/tests/bundle_scan.spec.ts` | QA-04 | FE-01, FE-02 | no API key in client bundles or responses |
| FR-DB-6 | M | T-FR-DB-6 | contract | `backend/tests/contract/test_schema_dts_fresh.py` | QA-04 | FE-01 | regenerated schema.d.ts equals committed; CI fails if stale |
| FR-MK-1 | M | T-FR-MK-1 | e2e | `backend/tests/e2e/test_mock_agent_connect.py` | VOICE-03 | VOICE-03 | responds to test-connection |
| FR-MK-2 | M | T-FR-MK-2 | integration | `backend/tests/integration/test_mock_agent_glass_box.py` | VOICE-03 | VOICE-03 | control messages received |
| FR-MK-3 | M | T-FR-MK-3 | e2e | `backend/tests/e2e/test_planted_bugs.py` | QA-03 | VOICE-03, EVAL-03 | each bug toggles independently; run flags >=4/5 with cited turns |
| FR-CO-1 | S | T-FR-CO-1 | integration | `backend/tests/integration/test_api_usage_rows.py` | VOICE-01 | VOICE-01, EVAL-01 | api_usage rows per external call |
| FR-CO-2 | S | T-FR-CO-2 | unit | `backend/tests/unit/test_tts_cache.py` | VOICE-01 | VOICE-01 | second identical request served from cache |
| FR-IN-1 | M | T-FR-IN-1 | connectors | `backend/tests/connectors/test_entry_point_discovery.py` | INT-01 | INT-01 | external pip package connector listed |
| FR-IN-2 | M | T-FR-IN-2 | connectors | `backend/tests/connectors/test_secrets_encrypted.py` | INT-01 | INT-01, API-02 | secrets_set true; DB column ciphertext; never returned |
| FR-IN-3 | M | T-FR-IN-3 | connectors | `backend/tests/connectors/test_integration_test_endpoint.py` | INT-02 | INT-02 | bad HubSpot token gives ok:false with reason |
| FR-IN-4 | M | T-FR-IN-4 | connectors | `backend/tests/connectors/test_sink_filters.py` | INT-01 | INT-01 | filters by event, agent, only-failed, threshold |
| FR-IN-5 | M | T-FR-IN-5 | kafka | `backend/tests/kafka/test_outbound_idempotent.py` | QA-02 | INT-01, INT-02 | replay yields one note / one POST |
| FR-IN-6 | M | T-FR-IN-6 | connectors | `backend/tests/connectors/test_webhook_sink_signature.py` | INT-01 | INT-01 | receiver verifies HMAC; no transcript by default |
| FR-IN-7 | M | T-FR-IN-7 | connectors | `backend/tests/connectors/test_webhook_source.py` | INT-03 | INT-03 | bad sig 401, duplicate external_id one call, private IP 422, stale timestamp rejected |
| FR-IN-8 | M | T-FR-IN-8 | connectors | `backend/tests/connectors/test_hubspot_sink.py` | INT-02 | INT-02 | respx: note body has score, pass/fail, failure types, link; no match skipped |
| FR-IN-9 | S | T-FR-IN-9 | playwright | `web/tests/integrations.spec.ts` | QA-04 | API-04, FE-05 | delivery log + redeliver |
| FR-IN-10 | S | T-FR-IN-10 | kafka | `backend/tests/kafka/test_dlq_replay.py` | QA-02 | API-04, FE-05 | replay republishes attempt=1, status replayed |
| FR-DX-1 | M | T-FR-DX-1 | e2e | `scripts/verify/step2_demo_timed.sh` | QA-05 | INFRA-01, DOC-02 | fresh clone, compose up + make demo, evaluated call < 20 min (timed log) |
| FR-DX-2 | M | T-FR-DX-2 | integration | `backend/tests/integration/test_api_key_scopes.py` | API-01 | API-01 | wrong scope 403; hashed; shown once |
| FR-DX-3 | M | T-FR-DX-3 | integration | `sdk/python/tests/test_sdk_sync_async.py` | INT-04 | INT-04 | README SDK example runs against demo stack |
| FR-DX-4 | M | T-FR-DX-4 | integration | `sdk/python/tests/test_cli.py::test_fail_under` | INT-04 | INT-04 | pareeksha run --fail-under 101 exits 1 |
| FR-DX-5 | S | T-FR-DX-5 | integration | `sdk/python/tests/test_apply_idempotent.py` | INT-04 | INT-04 | apply twice changes nothing |
| FR-DX-6 | S | T-FR-DX-6 | e2e | `scripts/verify/step8_github_action.sh` | QA-05 | INT-04 | two PR check links: fail with bug, pass after fix |
| FR-DX-7 | M | T-FR-DX-7 | contract | `backend/tests/contract/test_adapter_contract.py` | VOICE-06 | VOICE-04, VOICE-06 | audio_v1 and Pipecat examples pass contract test |
| FR-DX-8 | S | T-FR-DX-8 | contract | `backend/tests/contract/test_livekit_example.py` | VOICE-06 | VOICE-06 | Should, cut first; no acceptance criterion defined |
| FR-DX-9 | C | T-FR-DX-9 | contract | `backend/tests/contract/test_vapi_adapter.py` | VOICE-06 | VOICE-06 | Could, unscheduled; reported "not built" unless built |
| FR-DX-10 | M | T-FR-DX-10 | manual | `proof/QA-05/adopter_guides/<guide>.log` | QA-05 | DOC-02 | verifier follows each of 8 guides from a clean clone |
| NFR-1 | M | T-NFR-1 | e2e | `scripts/verify/step3_perf_20call.sh` | QA-05 | VOICE-05 | 20 calls, concurrency 4, < 15 min |
| NFR-2 | M | T-NFR-2 | integration | `backend/tests/integration/test_loopback_overhead.py` | VOICE-04 | VOICE-04 | echo agent, overhead <= 50 ms |
| NFR-3 | M | T-NFR-3 | e2e | `scripts/verify/step3_kafka_40call.sh` | QA-05 | VOICE-05 | >= 95% calls free of infra errors (SQL query + run_id) |
| NFR-4 | M | T-NFR-4 | kafka | `backend/tests/kafka/test_duplicate_and_crash.py` | QA-02 | INFRA-02 | duplicate and crash mid-handler => one evaluation/call/note |
| NFR-4b | M | T-NFR-4b | kafka | `backend/tests/kafka/test_kafka_down_outbox.py` | QA-02 | API-03, INFRA-02 | API accepts while Kafka down; outbox drains in per-key order |
| NFR-4c | M | T-NFR-4c | kafka | `backend/tests/kafka/test_scale_consumers.py` | QA-02 | INFRA-02 | 2 instances share partitions, no config change |
| NFR-5 | M | T-NFR-5 | unit | `backend/tests/unit/test_first_utterance_seed.py` | EVAL-01 | EVAL-01, VOICE-02 | same seed gives same first utterance and noise |
| NFR-6 | M | T-NFR-6 | judge | `backend/tests/judge/test_judge_pinned.py` | EVAL-03 | EVAL-03 | temperature 0, pinned model id (DeepSeek), versioned rubric |
| NFR-7 | M | T-NFR-7 | integration | `backend/tests/integration/test_score_traceability.py` | EVAL-03 | EVAL-03 | snapshot + version + hash + model stored |
| NFR-8 | M | T-NFR-8 | contract | `backend/tests/contract/test_secret_scan_and_logs.py` | QA-04 | ALL | gitleaks clean; keys absent from logs and browser |
| NFR-9 | M | T-NFR-9 | unit | `backend/tests/unit/test_privacy.py` | EVAL-02 | EVAL-02, EVAL-05 | PII masked before judge; consent enforced; retention setting honoured |
| NFR-10 | M | T-NFR-10 | integration | `backend/tests/integration/test_structured_logs.py` | API-03 | API-03, INFRA-02 | JSON logs carry run_id, call_id, job_id; event timeline stored |
| NFR-11 | M | T-NFR-11 | e2e | `scripts/verify/step2_demo_timed.sh` | QA-05 | INFRA-01 | compose up healthy; managed-Kafka config-only override test |
| NFR-12 | S | T-NFR-12 | unit | `backend/tests/unit/test_single_client_modules.py` | QA-04 | VOICE-01, EVAL-01 | Gnani and LLM calls only via gnani/ and llm/; coverage >= 70% on audio/ and evaluation/ |
| NFR-13 | S | T-NFR-13 | unit | `backend/tests/unit/test_new_language_config.py` | EVAL-02 | EVAL-02 | new language via data only, no core change |
| NFR-14 | S | T-NFR-14 | manual | `proof/QA-05/adopter_guides/quickstart.log` | QA-05 | DOC-02 | clean clone to first evaluated call < 20 min |
| NFR-15 | M | T-NFR-15 | connectors | `backend/tests/connectors/test_security_primitives.py` | INT-01 | INT-01, API-01 | HMAC both ways + timestamp, SSRF block, Fernet, hashed keys |
| NFR-16 | S | T-NFR-16 | integration | `backend/tests/integration/test_metrics_summary.py` | API-04 | API-04, FE-05 | lag, outbox backlog, DLQ count at /metrics/summary |

## 3. PRD section 8 product and portfolio metrics

| Metric | Target | Test / evidence | Owner | `make verify` step |
|---|---|---|---|---|
| 20-call run, concurrency 4 | < 15 min | `scripts/verify/step3_perf_20call.sh` timed log (NFR-1) | QA-05 | V3 |
| Calls without infra error | >= 95% | SQL over `run_items` of the 40-call run (NFR-3) | QA-05 | V3 |
| Judge kappa vs Preetham, 30 calls | >= 0.6 (target 0.7) | `/calibration` JSON + T-FR-EV-8 | EVAL-06 | V9 |
| Planted bugs detected | >= 4 of 5 | T-FR-MK-3 with cited turn indices | QA-03 | V4 |
| Dialect report coverage | >= 3 Kannada groups + Hindi + code-mixed, >= 20 clips each | dialect HTML + manifest counts query (H-02, EVAL-05) | EVAL-05 | V7 |
| Duplicate delivery / crash duplicates | 0 | T-NFR-4 + live replay with note count query | QA-02, QA-05 | V6 |
| Clean clone to first evaluated call | < 20 min | timed log (FR-DX-1, NFR-14) | QA-05 | V2 |
| Webhook import to HubSpot note | < 3 min | timestamps + note ID + screenshot (FR-IN-7, FR-IN-8) | QA-05 | V5 |
| Portfolio: demo video, README heatmap, launch post | published | links (PJM-01, DOC-03) | PJM-01 | V11 |

## 4. GOAL.md FINAL acceptance items

`make verify` (fresh clone) runs steps V1..V11 in order, writes one section per step into `proof/FINAL_REPORT.md`, prints `PASS Vn` or `FAIL Vn` with the evidence path, and exits non-zero if any step fails. Step scripts live in `scripts/verify/` (written by QA-05; the Makefile target is wired by QA-05 and PJM-01). Step numbers equal GOAL.md item numbers.

| # | GOAL.md item | Test / evidence | Requirements covered | Evidence owner | `make verify` step: what it checks |
|---|---|---|---|---|---|
| 1 | Every section-7 task has proof/ and a signed verified.md | `proof/<TASK>/proof.md`, `verified.md` (date, SHA, verifier output) | all | each task; QA-05 aggregates | V1: for every task ID in `docs/AGENTS.md` section 7, both files exist and verified.md carries a date and a SHA that is an ancestor of HEAD; also runs the build-fail grep below |
| 2 | compose up + make demo gives an evaluated call in < 20 min | `scripts/verify/step2_demo_timed.sh` timestamped log | FR-DX-1, NFR-11, NFR-14 | QA-05 | V2: starts a clock, `docker compose up -d`, waits healthy, `make demo`, queries Postgres for an evaluation row with a score, asserts elapsed < 1200 s |
| 3 | 40-call Kafka run, >= 95% free of infra errors | run_id + SQL output; consumer offsets and lag; 20-call concurrency-4 timing | NFR-1, NFR-3, NFR-4c, FR-RN-3, FR-RN-9 | QA-05 | V3: creates the 5x4x2 run, waits for `run.completed`, asserts infra-error-free ratio >= 0.95, dumps lag per group (0 at end) and DLQ count |
| 4 | >= 4 of 5 planted bugs caught with cited turn indices | T-FR-MK-3 report JSON | FR-MK-1..3, FR-EV-3 | QA-03 | V4: one run per bug on; asserts the evaluation flags it with an evidence turn index that exists in the transcript; count >= 4; bugs-off control pass rate reported |
| 5 | Webhook-imported real recording audited, HubSpot note within 3 min | signed inbound POST timestamp, note ID, HubSpot screenshot, delivery-log rows | FR-IN-7, FR-IN-8, FR-AU-1..4, NFR-15 | QA-05 (needs INT-02 live test and a HubSpot token) | V5: posts a signed webhook with a consented real recording, polls the HubSpot API for the note, asserts note time minus POST time < 180 s, stores the note ID |
| 6 | Duplicate delivery and worker-crash tests give exactly one evaluation and one CRM note | T-NFR-4, T-FR-IN-5, live replay | NFR-4, FR-IN-5, FR-RN-9 | QA-02, QA-05 | V6: runs the Kafka suite, then re-publishes one `evaluation.completed` twice and kills a worker mid-handler on the live stack; asserts COUNT(evaluations)=1 and HubSpot notes for that call = 1 |
| 7 | Dialect report: >= 3 Kannada groups + Hindi + code-mixed, n + CIs (HTML) | `dialect_<id>.html` + manifest query | FR-DI-1..6, NFR-9 | EVAL-05, H-02 | V7: parses the HTML; asserts >= 5 groups, n >= 20 each, a CI on every cell, and no clip without consent=true in the DB |
| 8 | GitHub Action fails a PR enabling a mock bug, passes after fix | two Actions run URLs | FR-DX-6, FR-RG-4, FR-DX-4 | QA-05, INT-04 | V8: `gh run view` on both URLs; first conclusion=failure, second=success, same workflow, second commit descends from the first |
| 9 | Judge vs Preetham labels on 30 calls: Cohen's kappa | calibration JSON (kappa, Spearman, n) | FR-EV-7, FR-EV-8, NFR-6, NFR-7 | EVAL-06 | V9: fetches `/calibration`; asserts n=30 and kappa >= 0.6; recomputes kappa independently from exported labels |
| 10 | Each of 8 adopter guides followed from a clean clone by the verifier | `proof/QA-05/adopter_guides/<guide>.log` x 8 | FR-DX-10, NFR-14 | DOC-02, QA-05 | V10: asserts 8 logs exist (names from `docs/10-integrations-and-dx.md` section 7), each ends with its success marker and a recorded exit code 0 |
| 11 | Repo public, tagged v1.0.0, demo video + launch post published | links in `proof/PJM-01/release.md` | PRD section 8 portfolio | PJM-01 | V11: `gh repo view --json visibility` is PUBLIC, tag `v1.0.0` exists, both links return HTTP 200, secret scan (gitleaks) clean |

Build-fail grep (run in V1 and CI): outside `tests/` and `examples/` no `STUB(`, `TODO`, `FIXME`, `NotImplementedError`, `pass  # placeholder`, skip/xfail markers or disabled lint/type directives.

## 5. Per-task QA gates

Task-level acceptance is in `docs/SCOPE.md` section 2; QA re-runs each `proof/<TASK>/proof.md` command on a clean checkout. QA writes the suites for QA-02 (Kafka), QA-03 (planted bugs), QA-04 (Playwright, contract, bundle scan) and QA-05 (full acceptance and the `scripts/verify/` steps); every other test is written by the owner in the table and reviewed by QA.

## 6. Machine-checkable coverage

`python3 scripts/check_test_plan_coverage.py` exits 1 if: any FR/NFR ID in `docs/02-requirements.md` is missing from section 2 of this plan (or has no test, level, owner or feature task); an owner or feature task is not in `docs/AGENTS.md` section 7 (or `ALL`); a GOAL.md item 1..11 or a verify step V1..V11 is unmapped; or a PRD section 8 metric row is missing. Output is saved in `proof/QA-01/coverage.txt`.
