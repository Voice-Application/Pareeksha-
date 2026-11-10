# 05 — Database Design · v0.2

PostgreSQL 16 is the **system of record**; Kafka only moves work between stages. The models are in `backend/pareeksha/db/models.py` (41 tables); the schema is built by Alembic `0001`–`0007`. [`schema.sql`](schema.sql) is the v0.2 baseline (29 tables = `0001_initial`); the 12 later tables (`users`, `llm_settings`, `prompt_versions`, the seven RAG-lab tables, `price_overrides`, `quick_tests`) come from migrations `0002`–`0006` (see §6).

**v0.2 changes:** removed `jobs` (Kafka replaces it); added `outbox_events`, `processed_events`, `dead_letters`, `integrations`, `integration_deliveries`, `external_refs`, `api_keys`, `scenario_drafts`; `agents.connection_type` → `agents.adapter` (+ adapter config/secrets); `calls.source` gains `import` and `calls.metadata`; `test_runs.active_calls`.

**After v0.2** (migrations `0002`–`0007`): `users` (web sign-in), `llm_settings`, `prompt_versions` + `agents.adapter = 'prompt'` (prompt-based agents), the RAG lab (`knowledge_bases`, `kb_documents`, `kb_indexes`, `kb_chunks`, `retrievals`, `rag_metrics`, `rag_matrices`), `price_overrides`, `quick_tests`, `scenarios.rag_expectation`, and the `no_unexpected_tool` check type.

---

## 1. Entity-relationship diagram

```mermaid
erDiagram
    projects ||--o{ agents : has
    projects ||--o{ scenarios : has
    projects ||--o{ personas : has
    projects ||--o{ noise_profiles : has
    projects ||--o{ test_runs : has
    projects ||--o{ dialect_datasets : has

    agents ||--o{ test_runs : "tested in"
    agents ||--o{ calls : "spoke in"
    agents ||--o{ regression_tests : owns

    test_runs ||--o{ run_items : expands_to
    rubric_versions ||--o{ test_runs : "scored with"
    scenarios ||--o{ run_items : ""
    personas ||--o{ run_items : ""
    noise_profiles ||--o{ run_items : ""
    run_items ||--o| calls : produces

    calls ||--o{ turns : contains
    calls ||--o{ tool_calls : "glass-box"
    calls ||--o| call_metrics : measured_by
    calls ||--o{ deterministic_checks : checked_by
    calls ||--o{ evaluations : judged_by
    rubric_versions ||--o{ evaluations : ""
    evaluations ||--o{ human_reviews : reviewed_by

    calls ||--o{ scenarios : "promoted into"
    scenarios ||--o{ regression_tests : ""
    regression_tests ||--o{ run_items : "re-run as"

    dialect_datasets ||--o{ dialect_samples : contains
    dialect_samples ||--o{ asr_results : transcribed_as
    noise_profiles ||--o{ asr_results : "condition"
    dialect_datasets ||--o{ dialect_reports : summarised_in

    test_runs ||--o{ api_usage : costs
    calls ||--o{ api_usage : costs

    agents ||--o{ scenario_drafts : "generated for"
    projects ||--o{ integrations : has
    integrations ||--o{ integration_deliveries : logs
    integrations ||--o{ external_refs : dedupes
    external_refs }o--|| calls : "imported as"
    projects ||--o{ api_keys : has

    projects ||--o{ knowledge_bases : has
    knowledge_bases ||--o{ kb_documents : holds
    knowledge_bases ||--o{ kb_indexes : "built as"
    kb_indexes ||--o{ kb_chunks : contains
    kb_documents ||--o{ kb_chunks : "chunked into"
    calls ||--o{ retrievals : "retrieved for"
    calls ||--o| rag_metrics : "scored by"
    agents ||--o{ prompt_versions : versions
    agents ||--o{ rag_matrices : compared_in
    agents ||--o{ quick_tests : tried_in
    test_runs ||--o{ quick_tests : "executed as"
    projects ||--o| llm_settings : configures
    projects ||--o{ price_overrides : has
```

`outbox_events`, `processed_events` and `dead_letters` are Kafka plumbing and reference entities only through their JSON envelopes. `users` is global (no `project_id`).

---

## 2. Table groups

### 2.1 Configuration — *what to test*

| Table | Purpose | Key columns |
|---|---|---|
| `projects` | Tenant boundary. One row in v1. Exists so multi-user later doesn't need a migration of every table. | `name` |
| `agents` | The voice bot under test. Holds everything needed to call it and to judge it. | `adapter` (audio_v1/pipecat/livekit/vapi/prompt), `endpoint_url`, `adapter_config`, `adapter_secrets_encrypted`, `languages[]`, `glass_box`, `mandatory_disclosures` (JSONB), `forbidden_phrases`, `expected_tools`, `bias_list[]` |
| `scenario_drafts` | LLM-generated scenarios awaiting review (written by the `generator` consumer). | `status` (pending/ready/failed), `drafts`, `error` |
| `scenarios` | What the caller wants and how success is defined. Language-independent. | `caller_goal`, `fixtures` (synthetic facts), `success_criteria`, `must_say`/`must_not_say`, `expected_tool_calls`, `rag_expectation`, `source` (manual/generated/promoted), `source_call_id` |
| `personas` | Who the caller is. | `language`, `code_mix_style`, `voice_id`, `speed`, `emotion`, `patience_turns`, `interruption_level` |
| `noise_profiles` | Line/background condition. Also reused as "conditions" in the dialect report. | `sample_rate`, `codec`, `pstn_bandpass`, `background_category`, `snr_db`, `packet_loss_pct` |
| `rubric_versions` | Frozen judge rubrics. Only one active (partial unique index). | `version`, `dimensions`, `pass_threshold`, `prompt_hash`, `is_active` |

### 2.2 Execution — *what happened*

| Table | Purpose | Key columns |
|---|---|---|
| `test_runs` | One launch. Stores a **snapshot of the agent config** so before/after comparisons stay valid even after you edit the agent. | `kind` (matrix/regression/dry_run), `status` (draft/queued/running/completed/partial/cancelled/failed), `config`, `agent_snapshot`, `summary`, `estimated_cost`, `active_calls` (per-run concurrency slots) |
| `run_items` | One matrix cell = one call to make. Unique on (run, scenario, persona, profile, seed) so re-submits don't duplicate. | `seed`, `status` (queued … evaluated/judge_error/error/cancelled/skipped_budget), `attempts`, `last_error`, `regression_test_id` |
| `calls` | One conversation: simulated, uploaded, or imported through a source connector. `run_item_id` is unique → at most one call per item. | `source` (simulation/upload/import), `status` (in_progress/transcribing/completed/error), `end_reason`, recording paths, `speaker_map`, `event_log`, `metadata` (customer refs for CRM matching; never sent to the judge) |
| `turns` | Ordered utterances. Three text fields make ASR attribution possible. | `text` (platform STT), `text_masked` (sent to judge), `ground_truth_text` (caller's real words), `agent_heard_text` (glass-box) |
| `tool_calls` | Agent's tool calls (glass-box agents only). | `seq`, `name`, `arguments`, `result` |

### 2.3 Evaluation — *how good was it*

| Table | Purpose | Key columns |
|---|---|---|
| `call_metrics` | 1:1 with call. Deterministic numbers. | latency p50/p90/p95, barge-in counts, silence gaps, talk ratio, `caller_asr_wer` |
| `deterministic_checks` | Rule results with evidence turns. `passed = NULL` means "not applicable". | `check_type`, `check_key`, `must_pass`, `passed`, `evidence_turns[]` |
| `evaluations` | Judge output + computed score. Unique on (call, rubric version) → re-running is an upsert, never a duplicate. | `dimensions` (JSONB), `overall_score`, `passed`, `critical_failure`, `needs_human_review`, `failure_types[]`, `prompt_hash`, `judge_model` |
| `human_reviews` | Your own labels, for calibration. One per reviewer per evaluation. | `dimensions`, `passed`, `critical_failure`, `notes` |

### 2.4 Regression

| Table | Purpose |
|---|---|
| `regression_tests` | A scenario (usually promoted from a failed call) pinned to a persona + profile, with a baseline score and tolerance. `blocking` tests form the regression suite. |

### 2.5 Dialect report

| Table | Purpose |
|---|---|
| `dialect_datasets` | A named collection of clips. |
| `dialect_samples` | One real clip with reference transcript, dialect label and pseudonymous speaker ID. `CHECK (consent)` means a row without consent cannot exist. |
| `asr_results` | One transcription of one clip under one condition by one engine, with normalised texts and metrics. Unique per (sample, condition, engine, model). |
| `dialect_reports` | Frozen aggregate output (so the report you put in your README doesn't change when you add clips later). |

### 2.6 Kafka plumbing

| Table | Purpose |
|---|---|
| `outbox_events` | Transactional outbox. The API inserts domain rows and their event in one transaction; `outbox-relay` claims unpublished rows (`FOR UPDATE SKIP LOCKED`), publishes, sets `published_at`. |
| `processed_events` | Consumer idempotency: `(consumer_group, event_id)` inserted in the same transaction as the side effect. Conflict → already processed → skip. |
| `dead_letters` | Copy of every DLQ message (from `dlq-recorder`) for the DLQ page and replay. |
| `api_usage` | Every external call with units and estimated cost (`provider`: gnani/gemini/deepseek/google/azure/elevenlabs/deepgram/other). Feeds the budget guard and the "credits used" counter. |

### 2.7 Integrations & access

| Table | Purpose |
|---|---|
| `integrations` | One configured connector instance (e.g. "HubSpot – sales portal"). `config` is validated by the connector's schema; `secrets_encrypted` is Fernet ciphertext; `event_filter` decides which events reach a sink. |
| `integration_deliveries` | Delivery log + idempotency guard: `UNIQUE (integration_id, event_id, direction)` means a replayed event can't post twice. Stores HTTP status and the external id (e.g. HubSpot note id). |
| `external_refs` | Dedupes inbound recordings: the same `(integration, external_id)` always maps to one call. |
| `api_keys` | Programmatic access for SDK, CLI, GitHub Action and the web app's server side. Only a sha256 hash and a display prefix are stored; scopes control access. |
| `users` | Web sign-in accounts (migration `0002`): unique `email`, `name`, `password_hash`, `role` (`admin`/`member`), `disabled_at`, `last_login_at`. Sessions are signed cookies issued by the web app (see `web/proxy.ts`), so there is no session table. |

### 2.8 Settings & pricing (migrations 0003, 0005)

| Table | Purpose |
|---|---|
| `llm_settings` | Per-project LLM provider override; see §6. |
| `price_overrides` | Per-project price overrides for cost estimates: unique `(project_id, kind, provider, model)`, `kind` (llm/embedding/rerank), `input_per_m_inr`, `output_per_m_inr`. |

### 2.9 Prompt agents & quick tests (migrations 0004, 0006)

| Table | Purpose |
|---|---|
| `prompt_versions` | Versions of a prompt agent (`adapter = 'prompt'`): `system_prompt`, `provider`, `model`, `base_url`, `temperature`, `tools`, `max_tool_rounds`, `rag_config`, `note`, `content_hash`. Unique `(agent_id, version)`. |
| `quick_tests` | "Paste a prompt and test it": one row per test, pointing at an ordinary agent and `test_runs` row (`run_id`); holds `system_prompt`, `user_details`, `plan`, `verdicts`, `improvement`, optional `parent_id` (re-test chain) and `kb_id`. |

### 2.10 RAG lab (migration 0005)

| Table | Purpose |
|---|---|
| `knowledge_bases` | Named KB per project (unique name); `local_only` restricts to local embedding; `secrets_encrypted`. |
| `kb_documents` | Uploaded documents: `filename`, `mime`, `sha256`, extracted `text`, `blob_key`, soft-deleted via `deleted_at`. Unique `(kb_id, sha256)`. |
| `kb_indexes` | One built index per KB version: `index_key`, `chunking` and `embedding` configs (JSONB), `status` (pending/building/ready/failed), `document_ids`, `chunk_count`, `stats`. Unique `(kb_id, version)`. |
| `kb_chunks` | Chunks of an index with character offsets, `text_sha` and `embedding` (`REAL[]`; no pgvector). |
| `retrievals` | What was retrieved for a call turn: `turn_idx`, `rag_config`, `index_id`, `query`/`queries`, `results`, `timings`, `usage`. |
| `rag_metrics` | 1:1 with call: computed RAG `metrics` (or `skipped`). |
| `rag_matrices` | Saved RAG-lab comparison per agent / prompt version / KB: `request` and result `entries`. |

---

## 3. Important design choices

1. **UUID primary keys** (`gen_random_uuid()`): safe to generate anywhere, no ID guessing in URLs, easy merging later. Exceptions: `api_usage` uses `bigserial` (high-volume append-only log); `call_metrics` and `rag_metrics` (key = `call_id`), `llm_settings` (key = `project_id`) and `processed_events` (composite key) use natural keys.
2. **`text` + `CHECK` instead of Postgres `ENUM`s**: adding a value is a one-line constraint change instead of an `ALTER TYPE` dance. Python mirrors live as `Literal` types in `pareeksha/schemas/`.
3. **JSONB for flexible, read-mostly config** (disclosures, fixtures, dimensions). Anything you filter or aggregate on often is a real column (`overall_score`, `passed`, `critical_failure`, latencies).
4. **Snapshots for reproducibility**: `test_runs.agent_snapshot`, `evaluations.prompt_hash` + `judge_model` + `rubric_version_id`, `turns.text_masked`. A score is always traceable to exactly what the judge saw.
5. **Score computed in code, stored as a column**: `overall_score` is never taken from the LLM.
6. **Circular references** (scenario ↔ call, run_item ↔ regression_test) are resolved by adding those foreign keys with `ALTER TABLE` after both tables exist.
7. **Deletion behaviour**: deleting a project cascades everything; deleting a call keeps scenarios/regression tests promoted from it (`SET NULL`); deleting a run cascades its items, but calls survive with `run_item_id = NULL`.

---

## 4. Common queries

**Run summary (used by `run_finalize` and the dashboard)**
```sql
SELECT
  count(*)                                               AS calls,
  avg(e.passed::int)                                     AS pass_rate,
  sum(e.critical_failure::int)                           AS critical_failures,
  sum(e.needs_human_review::int)                         AS needs_review,
  percentile_cont(0.5)  WITHIN GROUP (ORDER BY m.response_latency_p50_ms) AS median_p50_ms,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY m.response_latency_p95_ms) AS p95_of_p95_ms
FROM run_items ri
JOIN calls c        ON c.run_item_id = ri.id
JOIN evaluations e  ON e.call_id = c.id
LEFT JOIN call_metrics m ON m.call_id = c.id
WHERE ri.run_id = :run_id;
```

**Matrix heatmap (scenario × persona)**
```sql
SELECT s.title, p.name AS persona, np.name AS profile, e.overall_score, e.passed
FROM run_items ri
JOIN scenarios s       ON s.id = ri.scenario_id
JOIN personas p        ON p.id = ri.persona_id
JOIN noise_profiles np ON np.id = ri.noise_profile_id
JOIN calls c           ON c.run_item_id = ri.id
JOIN evaluations e     ON e.call_id = c.id
WHERE ri.run_id = :run_id;
```

**Run-vs-run regressions**
```sql
WITH a AS (SELECT ri.scenario_id, ri.persona_id, ri.noise_profile_id, e.overall_score
           FROM run_items ri JOIN calls c ON c.run_item_id = ri.id JOIN evaluations e ON e.call_id = c.id
           WHERE ri.run_id = :old_run),
     b AS (SELECT ri.scenario_id, ri.persona_id, ri.noise_profile_id, e.overall_score
           FROM run_items ri JOIN calls c ON c.run_item_id = ri.id JOIN evaluations e ON e.call_id = c.id
           WHERE ri.run_id = :new_run)
SELECT b.*, a.overall_score AS old_score, b.overall_score - a.overall_score AS delta
FROM b JOIN a USING (scenario_id, persona_id, noise_profile_id)
ORDER BY delta ASC;
```

**Dialect heatmap**
```sql
SELECT ds.dialect_label, np.name AS condition, ar.engine,
       count(*) AS n, avg(ar.wer) AS wer, avg(ar.cer) AS cer,
       sum(ar.entity_correct)::float / nullif(sum(ar.entity_total), 0) AS entity_acc
FROM asr_results ar
JOIN dialect_samples ds ON ds.id = ar.sample_id
JOIN noise_profiles np  ON np.id = ar.noise_profile_id
WHERE ds.dataset_id = :dataset_id
GROUP BY 1, 2, 3;
```
(Confidence intervals are computed in Python with a speaker-grouped bootstrap, not SQL.)

**Per-run concurrency slot (simulator, before starting a call)**
```sql
UPDATE test_runs SET active_calls = active_calls + 1
WHERE id = :run_id AND active_calls < (config->>'max_concurrency')::int
RETURNING active_calls;          -- no row = run is at its cap → throttle (retry.30s, attempt unchanged)
```

**Outbox relay claim**
```sql
SELECT id, topic, key, envelope FROM outbox_events
WHERE published_at IS NULL ORDER BY created_at
FOR UPDATE SKIP LOCKED LIMIT 100;
```

**Consumer idempotency check (inside the handler's transaction)**
```sql
INSERT INTO processed_events (consumer_group, event_id) VALUES (:group, :event_id)
ON CONFLICT DO NOTHING RETURNING event_id;   -- no row = duplicate → skip
```

**Credits used this month**
```sql
SELECT provider, operation, sum(units) AS units, sum(est_cost) AS cost
FROM api_usage WHERE created_at >= date_trunc('month', now())
GROUP BY 1, 2 ORDER BY cost DESC NULLS LAST;
```

---

## 5. Seed data

`python -m pareeksha.seed` (`backend/pareeksha/seed/`, run by `make demo`; get-or-create) inserts:
- 1 project (`default`)
- Rubric versions `rubric-2026-10-v1`, `-v2` and `rubric-2026-11-v3` (`seed/data/`); the build's `RUBRIC_VERSION` is made active
- 8 noise profiles (rubric doc §7)
- 20 personas (rubric doc §8)
- The mock agent ("EMI Reminder Bot", adapter `audio_v1`, `ws://mock-agent:8765/ws`, glass-box on)
- One admin-scope API key (pinned by `PAREEKSHA_API_KEY` if set, else generated and returned once)
- Demo scenarios for the mock agent
- First-run demo data (`seed/demo.py`): a prompt agent with a v1-vs-v2 regression and a bilingual knowledge base with a finished RAG matrix, precomputed (no API keys needed)

## 6. Migrations

- Alembic (psycopg 3 driver; `backend/alembic/versions/`). `0001_initial` = `schema.sql`; `0002` users; `0003` llm_settings; `0004` prompt_versions, `prompt` adapter, `no_unexpected_tool` check; `0005` RAG lab + price_overrides; `0006` quick_tests; `0007` idempotent repair adding `api_usage.project_id` / `dead_letters.project_id` where an older 0001 left them out. The `migrate` compose service runs them.
- Rule: never edit an applied migration; add a new one.
- `rubric_versions` rows are data, not schema: a new rubric = insert a new row and flip `is_active`.

### `llm_settings` (revision 0003, not in `schema.sql` v0.2)

One row per project (`project_id` primary key, `ON DELETE CASCADE`): `provider` (`deepseek`, `gemini`, `openai_compatible`; no DB CHECK), `base_url`, `judge_model`, `caller_model`, `designer_model` (all nullable: null means the environment's value), `api_key_encrypted` (Fernet token, `SECRET_KEY`), `api_key_last4`, `updated_at` (part of the worker cache fingerprint). No row means the environment's settings apply.

## 7. Retention

Kafka topic retention is 7 days by default (progress 1 day, DLQ topics 30 days; `events/topics.py`). `outbox-relay` prunes published `outbox_events` older than 3 days, hourly (`events/outbox.py`). No other maintenance job exists in the repository: `processed_events` and `dead_letters` are not pruned, and there is no `make maintenance` target or `AUDIO_RETENTION_DAYS` setting, so recordings are kept. Transcripts, scores and delivery logs are kept.
