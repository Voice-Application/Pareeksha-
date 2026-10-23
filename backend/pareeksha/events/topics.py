"""Kafka topic catalogue. FROZEN CONTRACT (docs/03-TRD.md section 10.2, AGENTS.md section 6.1).

Topic names end in ``.v1``. Changing a name, key, partition count or retention is a contract
change: it needs Tech Lead approval and a CHANGELOG.md entry. ``infra/kafka/create-topics.sh``
must mirror this module (a contract test compares them).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

DAY_MS = 24 * 60 * 60 * 1000

#: Default retention for work topics (7 days).
RETENTION_DEFAULT_MS = 7 * DAY_MS
#: ``pareeksha.progress.v1`` only feeds live UI streams.
RETENTION_PROGRESS_MS = 1 * DAY_MS
#: Dead letters stay for 30 days.
RETENTION_DLQ_MS = 30 * DAY_MS

#: Partitions for work topics (ceiling on parallel consumers per group).
PARTITIONS_WORK = 6
#: Partitions for low-volume topics.
PARTITIONS_SMALL = 3

#: A message is attempted at most this many times, then goes to the DLQ.
MAX_ATTEMPTS = 3
#: Delay before a retry-topic message is re-delivered: attempt 2 uses retry.30s, attempt 3 retry.5m.
RETRY_DELAY_SECONDS: dict[int, int] = {2: 30, 3: 300}

# Kafka header names carried by retry / DLQ copies (TRD 10.3).
HEADER_TARGET_TOPIC = "x-target-topic"
HEADER_NOT_BEFORE = "x-not-before"  # RFC 3339 UTC timestamp; retrier waits until then
HEADER_ERROR = "x-error"
HEADER_REASON = "x-reason"  # "throttled" re-queues without consuming an attempt
REASON_THROTTLED = "throttled"


class Topics(StrEnum):
    """Every Kafka topic Pareeksha uses."""

    RUN_REQUESTED = "pareeksha.run.requested.v1"
    CALL_REQUESTED = "pareeksha.call.requested.v1"
    AUDIT_REQUESTED = "pareeksha.audit.requested.v1"
    CALL_COMPLETED = "pareeksha.call.completed.v1"
    EVALUATION_COMPLETED = "pareeksha.evaluation.completed.v1"
    RUN_COMPLETED = "pareeksha.run.completed.v1"
    PROGRESS = "pareeksha.progress.v1"
    SCENARIO_GENERATE_REQUESTED = "pareeksha.scenario.generate.requested.v1"
    DIALECT_CLIP_REQUESTED = "pareeksha.dialect.clip.requested.v1"
    RETRY_30S = "pareeksha.retry.30s.v1"
    RETRY_5M = "pareeksha.retry.5m.v1"
    DLQ = "pareeksha.dlq.v1"


class ConsumerGroups(StrEnum):
    """Consumer group ids (one per worker process; TRD section 2)."""

    PLANNER = "planner"
    SIMULATOR = "simulator"
    AUDITOR = "auditor"
    EVALUATOR = "evaluator"
    FINALIZER = "finalizer"
    INTEGRATIONS = "integrations"
    DIALECT = "dialect"
    GENERATOR = "generator"
    RETRIER = "retrier"
    DLQ_RECORDER = "dlq-recorder"


@dataclass(frozen=True, slots=True)
class TopicSpec:
    """Static description of one topic."""

    topic: Topics
    key: str  # what the message key is, for documentation and tests
    partitions: int
    retention_ms: int
    producers: tuple[str, ...]
    consumer_groups: tuple[str, ...]


TOPIC_SPECS: dict[Topics, TopicSpec] = {
    spec.topic: spec
    for spec in (
        TopicSpec(
            Topics.RUN_REQUESTED,
            "run_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("api (outbox)",),
            (ConsumerGroups.PLANNER,),
        ),
        # Keyed by run_item_id (NOT run_id) so one run spreads across partitions and simulators.
        TopicSpec(
            Topics.CALL_REQUESTED,
            "run_item_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("planner", "api (regression re-runs)"),
            (ConsumerGroups.SIMULATOR,),
        ),
        TopicSpec(
            Topics.AUDIT_REQUESTED,
            "call_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("api (outbox)", "source connectors"),
            (ConsumerGroups.AUDITOR,),
        ),
        TopicSpec(
            Topics.CALL_COMPLETED,
            "call_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("simulator", "auditor"),
            (ConsumerGroups.EVALUATOR,),
        ),
        TopicSpec(
            Topics.EVALUATION_COMPLETED,
            "call_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("evaluator",),
            (ConsumerGroups.FINALIZER, ConsumerGroups.INTEGRATIONS),
        ),
        TopicSpec(
            Topics.RUN_COMPLETED,
            "run_id",
            PARTITIONS_SMALL,
            RETENTION_DEFAULT_MS,
            ("finalizer",),
            (ConsumerGroups.INTEGRATIONS,),
        ),
        TopicSpec(
            Topics.PROGRESS,
            "run_id or call_id",
            PARTITIONS_SMALL,
            RETENTION_PROGRESS_MS,
            ("all workers",),
            ("api SSE (unique group per API instance, offset reset latest)",),
        ),
        TopicSpec(
            Topics.SCENARIO_GENERATE_REQUESTED,
            "agent_id",
            PARTITIONS_SMALL,
            RETENTION_DEFAULT_MS,
            ("api (outbox)",),
            (ConsumerGroups.GENERATOR,),
        ),
        TopicSpec(
            Topics.DIALECT_CLIP_REQUESTED,
            "sample_id",
            PARTITIONS_WORK,
            RETENTION_DEFAULT_MS,
            ("api (outbox)",),
            (ConsumerGroups.DIALECT,),
        ),
        TopicSpec(
            Topics.RETRY_30S,
            "original key",
            PARTITIONS_SMALL,
            RETENTION_DEFAULT_MS,
            ("any consumer",),
            (ConsumerGroups.RETRIER,),
        ),
        TopicSpec(
            Topics.RETRY_5M,
            "original key",
            PARTITIONS_SMALL,
            RETENTION_DEFAULT_MS,
            ("any consumer",),
            (ConsumerGroups.RETRIER,),
        ),
        TopicSpec(
            Topics.DLQ,
            "original key",
            PARTITIONS_SMALL,
            RETENTION_DLQ_MS,
            ("any consumer",),
            (ConsumerGroups.DLQ_RECORDER,),
        ),
    )
}

#: Topics that carry domain events (an Envelope with a typed payload).
EVENT_TOPICS: tuple[Topics, ...] = (
    Topics.RUN_REQUESTED,
    Topics.CALL_REQUESTED,
    Topics.AUDIT_REQUESTED,
    Topics.CALL_COMPLETED,
    Topics.EVALUATION_COMPLETED,
    Topics.RUN_COMPLETED,
    Topics.PROGRESS,
    Topics.SCENARIO_GENERATE_REQUESTED,
    Topics.DIALECT_CLIP_REQUESTED,
)

#: Topics that carry copies of messages from the topics above (envelope unchanged except attempt).
FAILURE_TOPICS: tuple[Topics, ...] = (Topics.RETRY_30S, Topics.RETRY_5M, Topics.DLQ)


def retry_topic_for_attempt(next_attempt: int) -> Topics:
    """Retry topic for a message about to be attempted for the ``next_attempt``-th time.

    attempt 2 -> retry.30s, attempt 3 -> retry.5m. Attempts above ``MAX_ATTEMPTS`` go to the DLQ,
    which is not a retry topic, so this raises ``ValueError`` for them.
    """
    if next_attempt == 2:
        return Topics.RETRY_30S
    if next_attempt == MAX_ATTEMPTS:
        return Topics.RETRY_5M
    raise ValueError(
        f"no retry topic for attempt {next_attempt}; attempts above {MAX_ATTEMPTS} go to the DLQ"
    )
