-- Pareeksha database schema v0.2 (PostgreSQL 16)
-- v0.2: Kafka is the event backbone, so the v0.1 `jobs` table is gone. Added: outbox_events,
-- processed_events, dead_letters (Kafka plumbing), integrations, integration_deliveries,
-- external_refs (CRM connectors), api_keys (SDK / CLI / CI / webhooks), test_runs.active_calls.
-- Apply: psql "$DATABASE_URL" -f schema.sql
-- In the real repo this becomes the first Alembic migration.

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Tenancy (single project in v1, kept for future multi-user)
-- ---------------------------------------------------------------------------
CREATE TABLE projects (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Configuration: agents, scenarios, personas, noise profiles, rubrics
-- ---------------------------------------------------------------------------
CREATE TABLE agents (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id            uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                  text NOT NULL,
    description           text NOT NULL DEFAULT '',          -- what the agent does / system prompt text
    adapter               text NOT NULL DEFAULT 'audio_v1'
                          CHECK (adapter IN ('audio_v1', 'pipecat', 'livekit', 'vapi')),
    endpoint_url          text NOT NULL,                      -- WS URL, or LiveKit token URL, or Vapi assistant ref
    adapter_config        jsonb NOT NULL DEFAULT '{}',        -- adapter-specific, non-secret
    adapter_secrets_encrypted bytea,                          -- e.g. Vapi API key (Fernet)
    languages             text[] NOT NULL DEFAULT '{}',       -- e.g. {kn-IN,hi-IN,en-IN}
    glass_box             boolean NOT NULL DEFAULT false,
    mandatory_disclosures jsonb NOT NULL DEFAULT '[]',        -- [{id, text, regex?, within_turns}]
    forbidden_phrases     jsonb NOT NULL DEFAULT '[]',        -- [{id, text, regex?}]
    expected_tools        jsonb NOT NULL DEFAULT '[]',        -- [{name, description, args_schema}]
    bias_list             text[] NOT NULL DEFAULT '{}',       -- domain words for STT boosting
    max_call_seconds      integer NOT NULL DEFAULT 300 CHECK (max_call_seconds BETWEEN 10 AND 1800),
    archived              boolean NOT NULL DEFAULT false,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE scenarios (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id         uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id           uuid REFERENCES agents(id) ON DELETE SET NULL,  -- null = reusable across agents
    title              text NOT NULL,
    caller_goal        text NOT NULL,
    fixtures           jsonb NOT NULL DEFAULT '{}',   -- synthetic facts: {name, loan_id, emi_amount, due_date, ...}
    reveal_rules       text NOT NULL DEFAULT '',      -- when caller reveals which facts
    success_criteria   text NOT NULL,
    must_say           jsonb NOT NULL DEFAULT '[]',   -- scenario-specific required agent behaviours
    must_not_say       jsonb NOT NULL DEFAULT '[]',
    expected_tool_calls jsonb NOT NULL DEFAULT '[]',  -- [{name, args, order}]
    caller_speaks_first boolean NOT NULL DEFAULT false,
    max_turns          integer NOT NULL DEFAULT 15 CHECK (max_turns BETWEEN 1 AND 60),
    tags               text[] NOT NULL DEFAULT '{}',
    source             text NOT NULL DEFAULT 'manual'
                       CHECK (source IN ('manual', 'generated', 'promoted')),
    source_call_id     uuid,                           -- FK added after calls table
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- LLM-generated scenarios waiting for the user's review (generator consumer writes here)
CREATE TABLE scenario_drafts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'ready', 'failed')),
    request     jsonb NOT NULL,                  -- {count, mix}
    drafts      jsonb NOT NULL DEFAULT '[]',
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE personas (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                text NOT NULL,
    language            text NOT NULL,                 -- BCP-47, e.g. kn-IN
    code_mix_style      text NOT NULL DEFAULT 'none'
                        CHECK (code_mix_style IN ('none', 'light', 'heavy')),
    dialect_label       text NOT NULL DEFAULT '',      -- descriptive only for synthetic voices
    tts_model           text NOT NULL DEFAULT 'timbre-v3.0',
    voice_id            text NOT NULL,
    speed               numeric(3,2) NOT NULL DEFAULT 1.00 CHECK (speed BETWEEN 0.5 AND 2.0),
    emotion             text NOT NULL DEFAULT 'neutral'
                        CHECK (emotion IN ('neutral','frustrated','angry','confused','anxious','polite','rushed')),
    patience_turns      integer NOT NULL DEFAULT 8 CHECK (patience_turns BETWEEN 1 AND 60),
    interruption_level  smallint NOT NULL DEFAULT 0 CHECK (interruption_level BETWEEN 0 AND 3),
    silence_habit       text NOT NULL DEFAULT 'normal'
                        CHECK (silence_habit IN ('normal', 'long_pauses', 'goes_silent')),
    behaviour_notes     text NOT NULL DEFAULT '',
    is_seed             boolean NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE noise_profiles (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                text NOT NULL,                 -- e.g. pstn_market_5db
    sample_rate         integer NOT NULL DEFAULT 16000 CHECK (sample_rate IN (8000, 16000)),
    codec               text NOT NULL DEFAULT 'none' CHECK (codec IN ('none', 'mulaw', 'alaw')),
    pstn_bandpass       boolean NOT NULL DEFAULT false,
    background_category text,                           -- null = no background noise
    snr_db              numeric(4,1),                   -- required when background_category set
    packet_loss_pct     numeric(4,2) NOT NULL DEFAULT 0 CHECK (packet_loss_pct BETWEEN 0 AND 20),
    clipping            boolean NOT NULL DEFAULT false,
    description         text NOT NULL DEFAULT '',
    created_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name),
    CHECK (background_category IS NULL OR snr_db IS NOT NULL)
);

CREATE TABLE rubric_versions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version       text NOT NULL UNIQUE,              -- e.g. rubric-2026-10-v1
    dimensions    jsonb NOT NULL,                    -- [{key, weight, description, anchors}]
    pass_threshold numeric(5,2) NOT NULL DEFAULT 80,
    prompt_hash   text NOT NULL,
    is_active     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);
-- Only one active rubric at a time
CREATE UNIQUE INDEX one_active_rubric ON rubric_versions (is_active) WHERE is_active;

-- ---------------------------------------------------------------------------
-- Runs and calls
-- ---------------------------------------------------------------------------
CREATE TABLE test_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id        uuid NOT NULL REFERENCES agents(id),
    name            text NOT NULL DEFAULT '',
    kind            text NOT NULL DEFAULT 'matrix' CHECK (kind IN ('matrix', 'regression', 'dry_run')),
    status          text NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('draft','queued','running','completed','partial','cancelled','failed')),
    config          jsonb NOT NULL DEFAULT '{}',     -- {max_concurrency, seed, judge_model, caller_model, ...}
    agent_snapshot  jsonb NOT NULL DEFAULT '{}',     -- agent config at run time (for before/after comparisons)
    rubric_version_id uuid REFERENCES rubric_versions(id),
    estimated_cost  numeric(12,2),
    active_calls    integer NOT NULL DEFAULT 0 CHECK (active_calls >= 0),  -- per-run concurrency slot counter
    summary         jsonb NOT NULL DEFAULT '{}',     -- filled by run_finalize: pass_rate, p95 latency, ...
    created_at      timestamptz NOT NULL DEFAULT now(),
    started_at      timestamptz,
    finished_at     timestamptz
);
CREATE INDEX test_runs_agent_created ON test_runs (agent_id, created_at DESC);

CREATE TABLE run_items (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           uuid NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    scenario_id      uuid NOT NULL REFERENCES scenarios(id),
    persona_id       uuid NOT NULL REFERENCES personas(id),
    noise_profile_id uuid NOT NULL REFERENCES noise_profiles(id),
    regression_test_id uuid,                         -- FK added below
    seed             bigint NOT NULL,
    status           text NOT NULL DEFAULT 'queued'
                     CHECK (status IN ('queued','connecting','in_progress','completed','evaluating',
                                       'evaluated','judge_error','error','cancelled','skipped_budget')),
    attempts         smallint NOT NULL DEFAULT 0,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, scenario_id, persona_id, noise_profile_id, seed)
);
CREATE INDEX run_items_run_status ON run_items (run_id, status);

CREATE TABLE calls (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id         uuid REFERENCES agents(id),
    run_item_id      uuid UNIQUE REFERENCES run_items(id) ON DELETE SET NULL,  -- null for uploads
    source           text NOT NULL CHECK (source IN ('simulation', 'upload', 'import')),  -- import = via a source connector
    language         text,                          -- primary language (persona or upload selection)
    status           text NOT NULL DEFAULT 'in_progress'
                     CHECK (status IN ('in_progress','transcribing','completed','error')),
    end_reason       text CHECK (end_reason IN ('goal_achieved','gave_up','agent_hangup','max_turns',
                                                'timeout','agent_silent','connect_failed','cancelled',
                                                'infra_error','upload','import')),
    duration_ms      integer,
    recording_caller text,                          -- blob paths
    recording_agent  text,
    recording_mixed  text,
    recording_original text,                        -- uploads
    speaker_map      jsonb,                         -- uploads: {"spk_0":"agent","spk_1":"caller"}
    metadata         jsonb NOT NULL DEFAULT '{}',   -- customer refs for CRM matching (phone/email/external_id); never sent to the judge
    event_log        jsonb NOT NULL DEFAULT '[]',   -- timeline events (see TRD §13)
    error            text,
    started_at       timestamptz NOT NULL DEFAULT now(),
    ended_at         timestamptz
);
CREATE INDEX calls_agent_started ON calls (agent_id, started_at DESC);
CREATE INDEX calls_source ON calls (source);

ALTER TABLE scenarios
    ADD CONSTRAINT scenarios_source_call_fk FOREIGN KEY (source_call_id) REFERENCES calls(id) ON DELETE SET NULL;

CREATE TABLE turns (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id            uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    idx                integer NOT NULL,              -- 0-based order in the call
    speaker            text NOT NULL CHECK (speaker IN ('caller', 'agent')),
    text               text NOT NULL DEFAULT '',      -- what the platform heard (Prisma STT); masked copy below
    text_masked        text NOT NULL DEFAULT '',      -- PII-masked, sent to judge
    ground_truth_text  text,                          -- caller turns in simulation: text before TTS
    agent_heard_text   text,                          -- glass-box: what the agent's own STT produced
    language_detected  text,
    start_ms           integer NOT NULL,
    end_ms             integer NOT NULL,
    stt_confidence     numeric(4,3),
    is_barge_in        boolean NOT NULL DEFAULT false,
    UNIQUE (call_id, idx),
    CHECK (end_ms >= start_ms)
);

CREATE TABLE tool_calls (                              -- glass-box only
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id     uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    turn_idx    integer,
    seq         integer NOT NULL,
    name        text NOT NULL,
    arguments   jsonb NOT NULL DEFAULT '{}',
    result      jsonb,
    at_ms       integer NOT NULL,
    UNIQUE (call_id, seq)
);

-- ---------------------------------------------------------------------------
-- Evaluation
-- ---------------------------------------------------------------------------
CREATE TABLE call_metrics (
    call_id                 uuid PRIMARY KEY REFERENCES calls(id) ON DELETE CASCADE,
    first_greeting_ms       integer,
    response_latency_p50_ms integer,
    response_latency_p90_ms integer,
    response_latency_p95_ms integer,
    response_latency_max_ms integer,
    barge_in_attempts       integer NOT NULL DEFAULT 0,
    barge_in_honoured       integer NOT NULL DEFAULT 0,
    agent_stop_time_p50_ms  integer,
    silence_gaps_over_2s    integer NOT NULL DEFAULT 0,
    turn_count              integer NOT NULL DEFAULT 0,
    agent_talk_ratio        numeric(4,3),
    repeated_utterances     integer NOT NULL DEFAULT 0,
    caller_asr_wer          numeric(6,4),           -- glass-box: agent_heard vs ground_truth
    latency_is_approximate  boolean NOT NULL DEFAULT false,  -- true for uploads
    extra                   jsonb NOT NULL DEFAULT '{}',
    computed_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE deterministic_checks (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id       uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    check_type    text NOT NULL CHECK (check_type IN ('disclosure_present','forbidden_absent','language_match',
                                                       'tool_calls_expected','no_loop','amount_confirmed')),
    check_key     text NOT NULL,                  -- e.g. disclosure id
    must_pass     boolean NOT NULL DEFAULT true,
    passed        boolean,                         -- null = not applicable
    evidence_turns integer[] NOT NULL DEFAULT '{}',
    detail        text NOT NULL DEFAULT '',
    UNIQUE (call_id, check_type, check_key)
);

CREATE TABLE evaluations (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    call_id            uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    rubric_version_id  uuid NOT NULL REFERENCES rubric_versions(id),
    status             text NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'judge_error')),
    judge_model        text NOT NULL,
    temperature        numeric(3,2) NOT NULL DEFAULT 0,
    prompt_hash        text NOT NULL,
    dimensions         jsonb NOT NULL DEFAULT '{}', -- {key: {score, evidence_turns, reason}}
    overall_score      numeric(5,2),                 -- computed in code
    passed             boolean,
    critical_failure   boolean NOT NULL DEFAULT false,
    needs_human_review boolean NOT NULL DEFAULT false,
    review_reasons     text[] NOT NULL DEFAULT '{}',
    failure_types      text[] NOT NULL DEFAULT '{}',
    summary            text NOT NULL DEFAULT '',
    confidence         text CHECK (confidence IN ('high', 'medium', 'low')),
    raw_response       jsonb,
    input_tokens       integer,
    output_tokens      integer,
    latency_ms         integer,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (call_id, rubric_version_id)            -- idempotent re-evaluation
);
CREATE INDEX evaluations_review ON evaluations (needs_human_review) WHERE needs_human_review;

CREATE TABLE human_reviews (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    evaluation_id  uuid NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
    reviewer       text NOT NULL,
    dimensions     jsonb NOT NULL DEFAULT '{}',     -- same shape as evaluations.dimensions
    overall_score  numeric(5,2),
    passed         boolean NOT NULL,
    critical_failure boolean NOT NULL DEFAULT false,
    notes          text NOT NULL DEFAULT '',
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (evaluation_id, reviewer)
);

-- ---------------------------------------------------------------------------
-- Regression
-- ---------------------------------------------------------------------------
CREATE TABLE regression_tests (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id        uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    scenario_id     uuid NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    persona_id      uuid REFERENCES personas(id),
    noise_profile_id uuid REFERENCES noise_profiles(id),
    source_call_id  uuid REFERENCES calls(id) ON DELETE SET NULL,
    failure_type    text NOT NULL,
    status          text NOT NULL DEFAULT 'manual' CHECK (status IN ('blocking', 'scheduled', 'manual', 'retired')),
    baseline_score  numeric(5,2) NOT NULL DEFAULT 80,
    tolerance       numeric(5,2) NOT NULL DEFAULT 5,
    notes           text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE run_items
    ADD CONSTRAINT run_items_regression_fk FOREIGN KEY (regression_test_id) REFERENCES regression_tests(id) ON DELETE SET NULL;

-- ---------------------------------------------------------------------------
-- Dialect / ASR gap report
-- ---------------------------------------------------------------------------
CREATE TABLE dialect_datasets (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        text NOT NULL,
    description text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE dialect_samples (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id      uuid NOT NULL REFERENCES dialect_datasets(id) ON DELETE CASCADE,
    audio_path      text NOT NULL,
    reference_text  text NOT NULL,
    language        text NOT NULL,                  -- kn-IN, hi-IN, en-IN
    dialect_label   text NOT NULL,                  -- e.g. kn-mysuru, kn-north, kn-coastal, hi-delhi, kn-en-mix
    speaker_id      text NOT NULL,                  -- pseudonymous
    duration_ms     integer NOT NULL,
    consent         boolean NOT NULL CHECK (consent),  -- rows without consent are rejected
    domain_terms    text[] NOT NULL DEFAULT '{}',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dialect_samples_dataset_dialect ON dialect_samples (dataset_id, dialect_label);

CREATE TABLE asr_results (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sample_id          uuid NOT NULL REFERENCES dialect_samples(id) ON DELETE CASCADE,
    noise_profile_id   uuid NOT NULL REFERENCES noise_profiles(id),
    engine             text NOT NULL,              -- gnani-prisma, whisper-large-v3, ...
    engine_model       text NOT NULL,
    hypothesis_text    text NOT NULL,
    ref_normalised     text NOT NULL,
    hyp_normalised     text NOT NULL,
    wer                numeric(6,4) NOT NULL,
    cer                numeric(6,4) NOT NULL,
    entity_total       integer NOT NULL DEFAULT 0,
    entity_correct     integer NOT NULL DEFAULT 0,
    intent_preserved   boolean,
    substitutions      jsonb NOT NULL DEFAULT '[]', -- [[ref_word, hyp_word], ...]
    latency_ms         integer,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sample_id, noise_profile_id, engine, engine_model)
);

CREATE TABLE dialect_reports (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id    uuid NOT NULL REFERENCES dialect_datasets(id) ON DELETE CASCADE,
    conditions    uuid[] NOT NULL,                 -- noise_profile ids
    engines       text[] NOT NULL,
    aggregates    jsonb NOT NULL,                  -- {dialect: {condition: {engine: {wer, wer_ci, cer, entity_acc, n}}}}
    top_errors    jsonb NOT NULL DEFAULT '[]',
    bias_suggestions text[] NOT NULL DEFAULT '{}',
    html_path     text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Infrastructure: Kafka plumbing, API usage
-- ---------------------------------------------------------------------------
-- Kafka plumbing ------------------------------------------------------------
-- Transactional outbox: the API writes domain rows and their events in ONE transaction;
-- the outbox relay publishes unpublished rows to Kafka and stamps published_at.
CREATE TABLE outbox_events (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),   -- = envelope.event_id
    topic         text NOT NULL,
    key           text NOT NULL,
    envelope      jsonb NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    published_at  timestamptz,
    attempts      smallint NOT NULL DEFAULT 0,
    last_error    text
);
CREATE INDEX outbox_unpublished ON outbox_events (created_at) WHERE published_at IS NULL;

-- Consumer idempotency: insert (group, event_id) in the SAME transaction as the side effect.
-- A duplicate insert means "already processed" -> skip and commit the offset.
CREATE TABLE processed_events (
    consumer_group text NOT NULL,
    event_id       uuid NOT NULL,
    processed_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consumer_group, event_id)
);

-- Copy of every message that reached pareeksha.dlq.v1, for the DLQ viewer and replay.
CREATE TABLE dead_letters (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id       uuid NOT NULL,
    original_topic text NOT NULL,
    key            text NOT NULL,
    consumer_group text NOT NULL,
    envelope       jsonb NOT NULL,
    error          text NOT NULL,
    attempts       smallint NOT NULL,
    status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replayed', 'discarded')),
    failed_at      timestamptz NOT NULL DEFAULT now(),
    replayed_at    timestamptz,
    UNIQUE (event_id, consumer_group)
);
CREATE INDEX dead_letters_open ON dead_letters (failed_at DESC) WHERE status = 'open';

-- ---------------------------------------------------------------------------
-- Integrations (CRM / webhook connectors) and API keys
-- ---------------------------------------------------------------------------
CREATE TABLE integrations (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    connector         text NOT NULL,                  -- registry name: webhook, hubspot, (salesforce, zoho, exotel, slack ...)
    name              text NOT NULL,
    direction         text NOT NULL CHECK (direction IN ('source', 'sink', 'both')),
    enabled           boolean NOT NULL DEFAULT true,
    config            jsonb NOT NULL DEFAULT '{}',    -- non-secret settings, validated by the connector's config_schema
    secrets_encrypted bytea,                          -- Fernet-encrypted JSON (tokens, signing secrets)
    event_filter      jsonb NOT NULL DEFAULT '{}',    -- e.g. {"events":["evaluation.completed"],"only_failed":true,"agent_ids":[...]}
    last_test_at      timestamptz,
    last_test_ok      boolean,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

-- One row per (integration, event, direction): makes outbound pushes idempotent and gives the delivery log.
CREATE TABLE integration_deliveries (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id   uuid NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    event_id         uuid NOT NULL,
    direction        text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    status           text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','succeeded','failed','skipped')),
    attempts         smallint NOT NULL DEFAULT 0,
    http_status      integer,
    external_id      text,                           -- e.g. HubSpot note id
    request_summary  jsonb NOT NULL DEFAULT '{}',     -- no secrets, no transcript
    response_excerpt text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (integration_id, event_id, direction)
);
CREATE INDEX integration_deliveries_recent ON integration_deliveries (integration_id, created_at DESC);

-- Dedupe inbound recordings: the same external call id imported twice maps to one call.
CREATE TABLE external_refs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    integration_id  uuid NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
    external_id     text NOT NULL,
    call_id         uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (integration_id, external_id)
);

-- API keys for the SDK, CLI, GitHub Action and the web app's server side. Only a hash is stored.
CREATE TABLE api_keys (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name          text NOT NULL,
    prefix        text NOT NULL UNIQUE,              -- first 8 chars shown in UI, e.g. pk_live_ab12cd34
    key_hash      text NOT NULL,                     -- sha256 of the full key
    scopes        text[] NOT NULL DEFAULT '{read}',  -- read, runs:write, audits:write, admin
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_used_at  timestamptz,
    revoked_at    timestamptz
);

CREATE TABLE api_usage (
    id          bigserial PRIMARY KEY,
    provider    text NOT NULL CHECK (provider IN ('gnani', 'gemini', 'other')),
    operation   text NOT NULL,                   -- tts, stt_stream, stt_rest, stt_batch, llm_judge, llm_caller, ...
    units       numeric(14,3) NOT NULL,           -- seconds of audio, characters, or tokens
    unit_type   text NOT NULL CHECK (unit_type IN ('audio_seconds', 'characters', 'tokens')),
    est_cost    numeric(12,4),
    cached      boolean NOT NULL DEFAULT false,
    run_id      uuid REFERENCES test_runs(id) ON DELETE SET NULL,
    call_id     uuid REFERENCES calls(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX api_usage_created ON api_usage (created_at);
CREATE INDEX api_usage_run ON api_usage (run_id);
