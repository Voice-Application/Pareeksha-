"""SQLAlchemy models mirroring docs/schema.sql v0.2 (Alembic revision 0001).

Generated with sqlacodegen from a database built from schema.sql, then ruff-formatted; the
migration test compares these tables and columns with the live schema.
"""

import datetime
import decimal
import uuid
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Calls(Base):
    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(
            "end_reason = ANY (ARRAY['goal_achieved'::text, 'gave_up'::text, 'agent_hangup'::text, 'max_turns'::text, 'timeout'::text, 'agent_silent'::text, 'connect_failed'::text, 'cancelled'::text, 'infra_error'::text, 'upload'::text, 'import'::text])",
            name="calls_end_reason_check",
        ),
        CheckConstraint(
            "source = ANY (ARRAY['simulation'::text, 'upload'::text, 'import'::text])",
            name="calls_source_check",
        ),
        CheckConstraint(
            "status = ANY (ARRAY['in_progress'::text, 'transcribing'::text, 'completed'::text, 'error'::text])",
            name="calls_status_check",
        ),
        ForeignKeyConstraint(["agent_id"], ["agents.id"], name="calls_agent_id_fkey"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="calls_project_id_fkey"
        ),
        ForeignKeyConstraint(
            ["run_item_id"], ["run_items.id"], ondelete="SET NULL", name="calls_run_item_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="calls_pkey"),
        UniqueConstraint("run_item_id", name="calls_run_item_id_key"),
        Index("calls_agent_started", "agent_id", "started_at"),
        Index("calls_source", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'in_progress'::text")
    )
    metadata_: Mapped[object] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    event_log: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    run_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    language: Mapped[str | None] = mapped_column(Text)
    end_reason: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    recording_caller: Mapped[str | None] = mapped_column(Text)
    recording_agent: Mapped[str | None] = mapped_column(Text)
    recording_mixed: Mapped[str | None] = mapped_column(Text)
    recording_original: Mapped[str | None] = mapped_column(Text)
    speaker_map: Mapped[object | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    ended_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))

    agent: Mapped[Optional["Agents"]] = relationship("Agents", back_populates="calls")
    project: Mapped["Projects"] = relationship("Projects", back_populates="calls")
    run_item: Mapped[Optional["RunItems"]] = relationship("RunItems", back_populates="calls")
    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="source_call"
    )
    scenarios: Mapped[list["Scenarios"]] = relationship("Scenarios", back_populates="source_call")
    deterministic_checks: Mapped[list["DeterministicChecks"]] = relationship(
        "DeterministicChecks", back_populates="call"
    )
    evaluations: Mapped[list["Evaluations"]] = relationship("Evaluations", back_populates="call")
    tool_calls: Mapped[list["ToolCalls"]] = relationship("ToolCalls", back_populates="call")
    turns: Mapped[list["Turns"]] = relationship("Turns", back_populates="call")
    external_refs: Mapped[list["ExternalRefs"]] = relationship(
        "ExternalRefs", back_populates="call"
    )
    api_usage: Mapped[list["ApiUsage"]] = relationship("ApiUsage", back_populates="call")


class DeadLetters(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        CheckConstraint(
            "status = ANY (ARRAY['open'::text, 'replayed'::text, 'discarded'::text])",
            name="dead_letters_status_check",
        ),
        PrimaryKeyConstraint("id", name="dead_letters_pkey"),
        UniqueConstraint(
            "event_id", "consumer_group", name="dead_letters_event_id_consumer_group_key"
        ),
        Index("dead_letters_open", "failed_at", postgresql_where="(status = 'open'::text)"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    original_topic: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    consumer_group: Mapped[str] = mapped_column(Text, nullable=False)
    envelope: Mapped[object] = mapped_column(JSONB, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'open'::text"))
    failed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    replayed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))


class OutboxEvents(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="outbox_events_pkey"),
        Index("outbox_unpublished", "created_at", postgresql_where="(published_at IS NULL)"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    envelope: Mapped[object] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedEvents(Base):
    __tablename__ = "processed_events"
    __table_args__ = (
        PrimaryKeyConstraint("consumer_group", "event_id", name="processed_events_pkey"),
    )

    consumer_group: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    processed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )


class Projects(Base):
    __tablename__ = "projects"
    __table_args__ = (PrimaryKeyConstraint("id", name="projects_pkey"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    calls: Mapped[list["Calls"]] = relationship("Calls", back_populates="project")
    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="project"
    )
    scenarios: Mapped[list["Scenarios"]] = relationship("Scenarios", back_populates="project")
    agents: Mapped[list["Agents"]] = relationship("Agents", back_populates="project")
    api_keys: Mapped[list["ApiKeys"]] = relationship("ApiKeys", back_populates="project")
    dialect_datasets: Mapped[list["DialectDatasets"]] = relationship(
        "DialectDatasets", back_populates="project"
    )
    integrations: Mapped[list["Integrations"]] = relationship(
        "Integrations", back_populates="project"
    )
    noise_profiles: Mapped[list["NoiseProfiles"]] = relationship(
        "NoiseProfiles", back_populates="project"
    )
    personas: Mapped[list["Personas"]] = relationship("Personas", back_populates="project")
    test_runs: Mapped[list["TestRuns"]] = relationship("TestRuns", back_populates="project")


class RegressionTests(Base):
    __tablename__ = "regression_tests"
    __table_args__ = (
        CheckConstraint(
            "status = ANY (ARRAY['blocking'::text, 'scheduled'::text, 'manual'::text, 'retired'::text])",
            name="regression_tests_status_check",
        ),
        ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE", name="regression_tests_agent_id_fkey"
        ),
        ForeignKeyConstraint(
            ["noise_profile_id"],
            ["noise_profiles.id"],
            name="regression_tests_noise_profile_id_fkey",
        ),
        ForeignKeyConstraint(
            ["persona_id"], ["personas.id"], name="regression_tests_persona_id_fkey"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="regression_tests_project_id_fkey",
        ),
        ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            ondelete="CASCADE",
            name="regression_tests_scenario_id_fkey",
        ),
        ForeignKeyConstraint(
            ["source_call_id"],
            ["calls.id"],
            ondelete="SET NULL",
            name="regression_tests_source_call_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="regression_tests_pkey"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    scenario_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    failure_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'::text"))
    baseline_score: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("80")
    )
    tolerance: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("5")
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    noise_profile_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    agent: Mapped["Agents"] = relationship("Agents", back_populates="regression_tests")
    noise_profile: Mapped[Optional["NoiseProfiles"]] = relationship(
        "NoiseProfiles", back_populates="regression_tests"
    )
    persona: Mapped[Optional["Personas"]] = relationship(
        "Personas", back_populates="regression_tests"
    )
    project: Mapped["Projects"] = relationship("Projects", back_populates="regression_tests")
    scenario: Mapped["Scenarios"] = relationship("Scenarios", back_populates="regression_tests")
    source_call: Mapped[Optional["Calls"]] = relationship(
        "Calls", back_populates="regression_tests"
    )
    run_items: Mapped[list["RunItems"]] = relationship("RunItems", back_populates="regression_test")


class RubricVersions(Base):
    __tablename__ = "rubric_versions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="rubric_versions_pkey"),
        UniqueConstraint("version", name="rubric_versions_version_key"),
        Index("one_active_rubric", "is_active", postgresql_where="is_active", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[object] = mapped_column(JSONB, nullable=False)
    pass_threshold: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, server_default=text("80")
    )
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    evaluations: Mapped[list["Evaluations"]] = relationship(
        "Evaluations", back_populates="rubric_version"
    )
    test_runs: Mapped[list["TestRuns"]] = relationship("TestRuns", back_populates="rubric_version")


class RunItems(Base):
    __tablename__ = "run_items"
    __table_args__ = (
        CheckConstraint(
            "status = ANY (ARRAY['queued'::text, 'connecting'::text, 'in_progress'::text, 'completed'::text, 'evaluating'::text, 'evaluated'::text, 'judge_error'::text, 'error'::text, 'cancelled'::text, 'skipped_budget'::text])",
            name="run_items_status_check",
        ),
        ForeignKeyConstraint(
            ["noise_profile_id"], ["noise_profiles.id"], name="run_items_noise_profile_id_fkey"
        ),
        ForeignKeyConstraint(["persona_id"], ["personas.id"], name="run_items_persona_id_fkey"),
        ForeignKeyConstraint(
            ["regression_test_id"],
            ["regression_tests.id"],
            ondelete="SET NULL",
            name="run_items_regression_fk",
        ),
        ForeignKeyConstraint(
            ["run_id"], ["test_runs.id"], ondelete="CASCADE", name="run_items_run_id_fkey"
        ),
        ForeignKeyConstraint(["scenario_id"], ["scenarios.id"], name="run_items_scenario_id_fkey"),
        PrimaryKeyConstraint("id", name="run_items_pkey"),
        UniqueConstraint(
            "run_id",
            "scenario_id",
            "persona_id",
            "noise_profile_id",
            "seed",
            name="run_items_run_id_scenario_id_persona_id_noise_profile_id_se_key",
        ),
        Index("run_items_run_status", "run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    scenario_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    persona_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    noise_profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'::text"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    regression_test_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_error: Mapped[str | None] = mapped_column(Text)

    calls: Mapped[Optional["Calls"]] = relationship(
        "Calls", uselist=False, back_populates="run_item"
    )
    noise_profile: Mapped["NoiseProfiles"] = relationship(
        "NoiseProfiles", back_populates="run_items"
    )
    persona: Mapped["Personas"] = relationship("Personas", back_populates="run_items")
    regression_test: Mapped[Optional["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="run_items"
    )
    run: Mapped["TestRuns"] = relationship("TestRuns", back_populates="run_items")
    scenario: Mapped["Scenarios"] = relationship("Scenarios", back_populates="run_items")


class Scenarios(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        CheckConstraint("max_turns >= 1 AND max_turns <= 60", name="scenarios_max_turns_check"),
        CheckConstraint(
            "source = ANY (ARRAY['manual'::text, 'generated'::text, 'promoted'::text])",
            name="scenarios_source_check",
        ),
        ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="SET NULL", name="scenarios_agent_id_fkey"
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="scenarios_project_id_fkey"
        ),
        ForeignKeyConstraint(
            ["source_call_id"], ["calls.id"], ondelete="SET NULL", name="scenarios_source_call_fk"
        ),
        PrimaryKeyConstraint("id", name="scenarios_pkey"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    caller_goal: Mapped[str] = mapped_column(Text, nullable=False)
    fixtures: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    reveal_rules: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    must_say: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    must_not_say: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expected_tool_calls: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    caller_speaks_first: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("15"))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'manual'::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="scenario"
    )
    run_items: Mapped[list["RunItems"]] = relationship("RunItems", back_populates="scenario")
    agent: Mapped[Optional["Agents"]] = relationship("Agents", back_populates="scenarios")
    project: Mapped["Projects"] = relationship("Projects", back_populates="scenarios")
    source_call: Mapped[Optional["Calls"]] = relationship("Calls", back_populates="scenarios")


class Agents(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            "adapter = ANY (ARRAY['audio_v1'::text, 'pipecat'::text, 'livekit'::text, 'vapi'::text])",
            name="agents_adapter_check",
        ),
        CheckConstraint(
            "max_call_seconds >= 10 AND max_call_seconds <= 1800",
            name="agents_max_call_seconds_check",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="agents_project_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="agents_pkey"),
        UniqueConstraint("project_id", "name", name="agents_project_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    adapter: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'audio_v1'::text")
    )
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_config: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    glass_box: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    mandatory_disclosures: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    forbidden_phrases: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    expected_tools: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    bias_list: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    max_call_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("300")
    )
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    adapter_secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)

    calls: Mapped[list["Calls"]] = relationship("Calls", back_populates="agent")
    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="agent"
    )
    scenarios: Mapped[list["Scenarios"]] = relationship("Scenarios", back_populates="agent")
    project: Mapped["Projects"] = relationship("Projects", back_populates="agents")
    scenario_drafts: Mapped[list["ScenarioDrafts"]] = relationship(
        "ScenarioDrafts", back_populates="agent"
    )
    test_runs: Mapped[list["TestRuns"]] = relationship("TestRuns", back_populates="agent")


class ApiKeys(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="api_keys_project_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="api_keys_pkey"),
        UniqueConstraint("prefix", name="api_keys_prefix_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{read}'::text[]")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))

    project: Mapped["Projects"] = relationship("Projects", back_populates="api_keys")


class CallMetrics(Base):
    __tablename__ = "call_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="call_metrics_call_id_fkey"
        ),
        PrimaryKeyConstraint("call_id", name="call_metrics_pkey"),
    )

    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    barge_in_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    barge_in_honoured: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    silence_gaps_over_2s: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    repeated_utterances: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    latency_is_approximate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    extra: Mapped[object] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    first_greeting_ms: Mapped[int | None] = mapped_column(Integer)
    response_latency_p50_ms: Mapped[int | None] = mapped_column(Integer)
    response_latency_p90_ms: Mapped[int | None] = mapped_column(Integer)
    response_latency_p95_ms: Mapped[int | None] = mapped_column(Integer)
    response_latency_max_ms: Mapped[int | None] = mapped_column(Integer)
    agent_stop_time_p50_ms: Mapped[int | None] = mapped_column(Integer)
    agent_talk_ratio: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 3))
    caller_asr_wer: Mapped[decimal.Decimal | None] = mapped_column(Numeric(6, 4))


class DeterministicChecks(Base):
    __tablename__ = "deterministic_checks"
    __table_args__ = (
        CheckConstraint(
            "check_type = ANY (ARRAY['disclosure_present'::text, 'forbidden_absent'::text, 'language_match'::text, 'tool_calls_expected'::text, 'no_loop'::text, 'amount_confirmed'::text])",
            name="deterministic_checks_check_type_check",
        ),
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="deterministic_checks_call_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="deterministic_checks_pkey"),
        UniqueConstraint(
            "call_id",
            "check_type",
            "check_key",
            name="deterministic_checks_call_id_check_type_check_key_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    check_type: Mapped[str] = mapped_column(Text, nullable=False)
    check_key: Mapped[str] = mapped_column(Text, nullable=False)
    must_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    evidence_turns: Mapped[list[int]] = mapped_column(
        ARRAY(Integer()), nullable=False, server_default=text("'{}'::integer[]")
    )
    detail: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    passed: Mapped[bool | None] = mapped_column(Boolean)

    call: Mapped["Calls"] = relationship("Calls", back_populates="deterministic_checks")


class DialectDatasets(Base):
    __tablename__ = "dialect_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="dialect_datasets_project_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="dialect_datasets_pkey"),
        UniqueConstraint("project_id", "name", name="dialect_datasets_project_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    project: Mapped["Projects"] = relationship("Projects", back_populates="dialect_datasets")
    dialect_reports: Mapped[list["DialectReports"]] = relationship(
        "DialectReports", back_populates="dataset"
    )
    dialect_samples: Mapped[list["DialectSamples"]] = relationship(
        "DialectSamples", back_populates="dataset"
    )


class Evaluations(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(
            "confidence = ANY (ARRAY['high'::text, 'medium'::text, 'low'::text])",
            name="evaluations_confidence_check",
        ),
        CheckConstraint(
            "status = ANY (ARRAY['ok'::text, 'judge_error'::text])", name="evaluations_status_check"
        ),
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="evaluations_call_id_fkey"
        ),
        ForeignKeyConstraint(
            ["rubric_version_id"], ["rubric_versions.id"], name="evaluations_rubric_version_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="evaluations_pkey"),
        UniqueConstraint(
            "call_id", "rubric_version_id", name="evaluations_call_id_rubric_version_id_key"
        ),
        Index("evaluations_review", "needs_human_review", postgresql_where="needs_human_review"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rubric_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'ok'::text"))
    judge_model: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[decimal.Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default=text("0")
    )
    prompt_hash: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    critical_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    needs_human_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    review_reasons: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    failure_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    overall_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[str | None] = mapped_column(Text)
    raw_response: Mapped[object | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    call: Mapped["Calls"] = relationship("Calls", back_populates="evaluations")
    rubric_version: Mapped["RubricVersions"] = relationship(
        "RubricVersions", back_populates="evaluations"
    )
    human_reviews: Mapped[list["HumanReviews"]] = relationship(
        "HumanReviews", back_populates="evaluation"
    )


class Integrations(Base):
    __tablename__ = "integrations"
    __table_args__ = (
        CheckConstraint(
            "direction = ANY (ARRAY['source'::text, 'sink'::text, 'both'::text])",
            name="integrations_direction_check",
        ),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="integrations_project_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="integrations_pkey"),
        UniqueConstraint("project_id", "name", name="integrations_project_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    config: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    event_filter: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_test_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)

    project: Mapped["Projects"] = relationship("Projects", back_populates="integrations")
    external_refs: Mapped[list["ExternalRefs"]] = relationship(
        "ExternalRefs", back_populates="integration"
    )
    integration_deliveries: Mapped[list["IntegrationDeliveries"]] = relationship(
        "IntegrationDeliveries", back_populates="integration"
    )


class NoiseProfiles(Base):
    __tablename__ = "noise_profiles"
    __table_args__ = (
        CheckConstraint(
            "background_category IS NULL OR snr_db IS NOT NULL", name="noise_profiles_check"
        ),
        CheckConstraint(
            "codec = ANY (ARRAY['none'::text, 'mulaw'::text, 'alaw'::text])",
            name="noise_profiles_codec_check",
        ),
        CheckConstraint(
            "packet_loss_pct >= 0::numeric AND packet_loss_pct <= 20::numeric",
            name="noise_profiles_packet_loss_pct_check",
        ),
        CheckConstraint(
            "sample_rate = ANY (ARRAY[8000, 16000])", name="noise_profiles_sample_rate_check"
        ),
        ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="noise_profiles_project_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="noise_profiles_pkey"),
        UniqueConstraint("project_id", "name", name="noise_profiles_project_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("16000"))
    codec: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'::text"))
    pstn_bandpass: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    packet_loss_pct: Mapped[decimal.Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, server_default=text("0")
    )
    clipping: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    background_category: Mapped[str | None] = mapped_column(Text)
    snr_db: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 1))

    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="noise_profile"
    )
    run_items: Mapped[list["RunItems"]] = relationship("RunItems", back_populates="noise_profile")
    project: Mapped["Projects"] = relationship("Projects", back_populates="noise_profiles")
    asr_results: Mapped[list["AsrResults"]] = relationship(
        "AsrResults", back_populates="noise_profile"
    )


class Personas(Base):
    __tablename__ = "personas"
    __table_args__ = (
        CheckConstraint(
            "code_mix_style = ANY (ARRAY['none'::text, 'light'::text, 'heavy'::text])",
            name="personas_code_mix_style_check",
        ),
        CheckConstraint(
            "emotion = ANY (ARRAY['neutral'::text, 'frustrated'::text, 'angry'::text, 'confused'::text, 'anxious'::text, 'polite'::text, 'rushed'::text])",
            name="personas_emotion_check",
        ),
        CheckConstraint(
            "interruption_level >= 0 AND interruption_level <= 3",
            name="personas_interruption_level_check",
        ),
        CheckConstraint(
            "patience_turns >= 1 AND patience_turns <= 60", name="personas_patience_turns_check"
        ),
        CheckConstraint(
            "silence_habit = ANY (ARRAY['normal'::text, 'long_pauses'::text, 'goes_silent'::text])",
            name="personas_silence_habit_check",
        ),
        CheckConstraint("speed >= 0.5 AND speed <= 2.0", name="personas_speed_check"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="personas_project_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="personas_pkey"),
        UniqueConstraint("project_id", "name", name="personas_project_id_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    code_mix_style: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'none'::text")
    )
    dialect_label: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''::text")
    )
    tts_model: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'timbre-v3.0'::text")
    )
    voice_id: Mapped[str] = mapped_column(Text, nullable=False)
    speed: Mapped[decimal.Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default=text("1.00")
    )
    emotion: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'neutral'::text")
    )
    patience_turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("8"))
    interruption_level: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    silence_habit: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'normal'::text")
    )
    behaviour_notes: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("''::text")
    )
    is_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    regression_tests: Mapped[list["RegressionTests"]] = relationship(
        "RegressionTests", back_populates="persona"
    )
    run_items: Mapped[list["RunItems"]] = relationship("RunItems", back_populates="persona")
    project: Mapped["Projects"] = relationship("Projects", back_populates="personas")


class ToolCalls(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="tool_calls_call_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="tool_calls_pkey"),
        UniqueConstraint("call_id", "seq", name="tool_calls_call_id_seq_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_idx: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[object | None] = mapped_column(JSONB)

    call: Mapped["Calls"] = relationship("Calls", back_populates="tool_calls")


class Turns(Base):
    __tablename__ = "turns"
    __table_args__ = (
        CheckConstraint("end_ms >= start_ms", name="turns_check"),
        CheckConstraint(
            "speaker = ANY (ARRAY['caller'::text, 'agent'::text])", name="turns_speaker_check"
        ),
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="turns_call_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="turns_pkey"),
        UniqueConstraint("call_id", "idx", name="turns_call_id_idx_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(Text, nullable=False)
    text_: Mapped[str] = mapped_column(
        "text", Text, nullable=False, server_default=text("''::text")
    )
    text_masked: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    is_barge_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    ground_truth_text: Mapped[str | None] = mapped_column(Text)
    agent_heard_text: Mapped[str | None] = mapped_column(Text)
    language_detected: Mapped[str | None] = mapped_column(Text)
    stt_confidence: Mapped[decimal.Decimal | None] = mapped_column(Numeric(4, 3))

    call: Mapped["Calls"] = relationship("Calls", back_populates="turns")


class DialectReports(Base):
    __tablename__ = "dialect_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id"],
            ["dialect_datasets.id"],
            ondelete="CASCADE",
            name="dialect_reports_dataset_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="dialect_reports_pkey"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    conditions: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()), nullable=False)
    engines: Mapped[list[str]] = mapped_column(ARRAY(Text()), nullable=False)
    aggregates: Mapped[object] = mapped_column(JSONB, nullable=False)
    top_errors: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    bias_suggestions: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    html_path: Mapped[str | None] = mapped_column(Text)

    dataset: Mapped["DialectDatasets"] = relationship(
        "DialectDatasets", back_populates="dialect_reports"
    )


class DialectSamples(Base):
    __tablename__ = "dialect_samples"
    __table_args__ = (
        CheckConstraint("consent", name="dialect_samples_consent_check"),
        ForeignKeyConstraint(
            ["dataset_id"],
            ["dialect_datasets.id"],
            ondelete="CASCADE",
            name="dialect_samples_dataset_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="dialect_samples_pkey"),
        Index("dialect_samples_dataset_dialect", "dataset_id", "dialect_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    reference_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    dialect_label: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_id: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    domain_terms: Mapped[list[str]] = mapped_column(
        ARRAY(Text()), nullable=False, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    dataset: Mapped["DialectDatasets"] = relationship(
        "DialectDatasets", back_populates="dialect_samples"
    )
    asr_results: Mapped[list["AsrResults"]] = relationship("AsrResults", back_populates="sample")


class ExternalRefs(Base):
    __tablename__ = "external_refs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="CASCADE", name="external_refs_call_id_fkey"
        ),
        ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            ondelete="CASCADE",
            name="external_refs_integration_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="external_refs_pkey"),
        UniqueConstraint(
            "integration_id", "external_id", name="external_refs_integration_id_external_id_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )

    call: Mapped["Calls"] = relationship("Calls", back_populates="external_refs")
    integration: Mapped["Integrations"] = relationship(
        "Integrations", back_populates="external_refs"
    )


class HumanReviews(Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["evaluation_id"],
            ["evaluations.id"],
            ondelete="CASCADE",
            name="human_reviews_evaluation_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="human_reviews_pkey"),
        UniqueConstraint(
            "evaluation_id", "reviewer", name="human_reviews_evaluation_id_reviewer_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    reviewer: Mapped[str] = mapped_column(Text, nullable=False)
    dimensions: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    critical_failure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    overall_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))

    evaluation: Mapped["Evaluations"] = relationship("Evaluations", back_populates="human_reviews")


class IntegrationDeliveries(Base):
    __tablename__ = "integration_deliveries"
    __table_args__ = (
        CheckConstraint(
            "direction = ANY (ARRAY['inbound'::text, 'outbound'::text])",
            name="integration_deliveries_direction_check",
        ),
        CheckConstraint(
            "status = ANY (ARRAY['pending'::text, 'succeeded'::text, 'failed'::text, 'skipped'::text])",
            name="integration_deliveries_status_check",
        ),
        ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            ondelete="CASCADE",
            name="integration_deliveries_integration_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="integration_deliveries_pkey"),
        UniqueConstraint(
            "integration_id",
            "event_id",
            "direction",
            name="integration_deliveries_integration_id_event_id_direction_key",
        ),
        Index("integration_deliveries_recent", "integration_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    integration_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'::text")
    )
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    request_summary: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    http_status: Mapped[int | None] = mapped_column(Integer)
    external_id: Mapped[str | None] = mapped_column(Text)
    response_excerpt: Mapped[str | None] = mapped_column(Text)

    integration: Mapped["Integrations"] = relationship(
        "Integrations", back_populates="integration_deliveries"
    )


class ScenarioDrafts(Base):
    __tablename__ = "scenario_drafts"
    __table_args__ = (
        CheckConstraint(
            "status = ANY (ARRAY['pending'::text, 'ready'::text, 'failed'::text])",
            name="scenario_drafts_status_check",
        ),
        ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE", name="scenario_drafts_agent_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="scenario_drafts_pkey"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'::text")
    )
    request: Mapped[object] = mapped_column(JSONB, nullable=False)
    drafts: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    error: Mapped[str | None] = mapped_column(Text)

    agent: Mapped["Agents"] = relationship("Agents", back_populates="scenario_drafts")


class TestRuns(Base):
    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint("active_calls >= 0", name="test_runs_active_calls_check"),
        CheckConstraint(
            "kind = ANY (ARRAY['matrix'::text, 'regression'::text, 'dry_run'::text])",
            name="test_runs_kind_check",
        ),
        CheckConstraint(
            "status = ANY (ARRAY['draft'::text, 'queued'::text, 'running'::text, 'completed'::text, 'partial'::text, 'cancelled'::text, 'failed'::text])",
            name="test_runs_status_check",
        ),
        ForeignKeyConstraint(["agent_id"], ["agents.id"], name="test_runs_agent_id_fkey"),
        ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE", name="test_runs_project_id_fkey"
        ),
        ForeignKeyConstraint(
            ["rubric_version_id"], ["rubric_versions.id"], name="test_runs_rubric_version_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="test_runs_pkey"),
        Index("test_runs_agent_created", "agent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''::text"))
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'matrix'::text"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'::text"))
    config: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    agent_snapshot: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    active_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    summary: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    rubric_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    estimated_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))

    run_items: Mapped[list["RunItems"]] = relationship("RunItems", back_populates="run")
    agent: Mapped["Agents"] = relationship("Agents", back_populates="test_runs")
    project: Mapped["Projects"] = relationship("Projects", back_populates="test_runs")
    rubric_version: Mapped[Optional["RubricVersions"]] = relationship(
        "RubricVersions", back_populates="test_runs"
    )
    api_usage: Mapped[list["ApiUsage"]] = relationship("ApiUsage", back_populates="run")


class ApiUsage(Base):
    __tablename__ = "api_usage"
    __table_args__ = (
        CheckConstraint(
            "provider = ANY (ARRAY['gnani'::text, 'gemini'::text, 'deepseek'::text, 'google'::text, 'azure'::text, 'elevenlabs'::text, 'deepgram'::text, 'other'::text])",
            name="api_usage_provider_check",
        ),
        CheckConstraint(
            "unit_type = ANY (ARRAY['audio_seconds'::text, 'characters'::text, 'tokens'::text])",
            name="api_usage_unit_type_check",
        ),
        ForeignKeyConstraint(
            ["call_id"], ["calls.id"], ondelete="SET NULL", name="api_usage_call_id_fkey"
        ),
        ForeignKeyConstraint(
            ["run_id"], ["test_runs.id"], ondelete="SET NULL", name="api_usage_run_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="api_usage_pkey"),
        Index("api_usage_created", "created_at"),
        Index("api_usage_run", "run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    units: Mapped[decimal.Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit_type: Mapped[str] = mapped_column(Text, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    est_cost: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 4))
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    call: Mapped[Optional["Calls"]] = relationship("Calls", back_populates="api_usage")
    run: Mapped[Optional["TestRuns"]] = relationship("TestRuns", back_populates="api_usage")


class AsrResults(Base):
    __tablename__ = "asr_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["noise_profile_id"], ["noise_profiles.id"], name="asr_results_noise_profile_id_fkey"
        ),
        ForeignKeyConstraint(
            ["sample_id"],
            ["dialect_samples.id"],
            ondelete="CASCADE",
            name="asr_results_sample_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="asr_results_pkey"),
        UniqueConstraint(
            "sample_id",
            "noise_profile_id",
            "engine",
            "engine_model",
            name="asr_results_sample_id_noise_profile_id_engine_engine_model_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    noise_profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    engine_model: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_text: Mapped[str] = mapped_column(Text, nullable=False)
    ref_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    hyp_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    wer: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    cer: Mapped[decimal.Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    entity_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    entity_correct: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    substitutions: Mapped[object] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    intent_preserved: Mapped[bool | None] = mapped_column(Boolean)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    noise_profile: Mapped["NoiseProfiles"] = relationship(
        "NoiseProfiles", back_populates="asr_results"
    )
    sample: Mapped["DialectSamples"] = relationship("DialectSamples", back_populates="asr_results")
