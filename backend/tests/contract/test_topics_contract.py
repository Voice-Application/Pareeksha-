"""events/topics.py must match the TRD table and the topic-creation script."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pareeksha.events.topics import (
    DAY_MS,
    EVENT_TOPICS,
    FAILURE_TOPICS,
    MAX_ATTEMPTS,
    TOPIC_SPECS,
    Topics,
    retry_topic_for_attempt,
)

REPO = Path(__file__).resolve().parents[3]
TRD = REPO / "docs" / "03-TRD.md"
SCRIPT_CANDIDATES = [
    REPO / "infra" / "kafka" / "create-topics.sh",
    REPO / "docs" / "starter" / "infra" / "kafka" / "create-topics.sh",
]


def test_twelve_versioned_topics() -> None:
    assert len(Topics) == 12
    assert set(TOPIC_SPECS) == set(Topics)
    assert all(t.value.startswith("pareeksha.") and t.value.endswith(".v1") for t in Topics)
    assert set(EVENT_TOPICS) | set(FAILURE_TOPICS) == set(Topics)


def test_call_requested_is_keyed_by_run_item_id() -> None:
    assert TOPIC_SPECS[Topics.CALL_REQUESTED].key == "run_item_id"


def test_trd_table_matches() -> None:
    """Rows of the TRD 10.2 table: topic, key, partitions."""
    rows = {}
    for line in TRD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(pareeksha\.[a-z0-9.]+\.v1)` \| (.+?) \|.*\| (\d+) \|\s*$", line)
        if m:
            rows[m.group(1)] = (
                m.group(2).replace("*", "").replace("`", "").strip(),
                int(m.group(3)),
            )
    assert set(rows) == {t.value for t in Topics}
    for topic, spec in TOPIC_SPECS.items():
        key, partitions = rows[topic.value]
        assert spec.partitions == partitions, topic
        assert spec.key.split(" ")[0] == key.split(" ")[0], topic


def test_create_topics_script_matches() -> None:
    script = next((p for p in SCRIPT_CANDIDATES if p.exists()), None)
    assert script is not None, "no create-topics.sh found"
    text = script.read_text(encoding="utf-8")
    created: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"^create (pareeksha\.\S+)\s+(\S+)\s+(\S+)", text, re.MULTILINE):
        created[m.group(1)] = (m.group(2), m.group(3))
    assert set(created) == {t.value for t in Topics}

    work, retention_default = 6, "$RETENTION_MS"
    for topic, spec in TOPIC_SPECS.items():
        partitions, retention = created[topic.value]
        expected_partitions = '"$PARTITIONS"' if spec.partitions == work else str(spec.partitions)
        assert partitions == expected_partitions, topic
        if spec.retention_ms == 7 * DAY_MS:
            assert retention == f'"{retention_default}"', topic
        elif spec.retention_ms == 1 * DAY_MS:
            assert retention == "86400000", topic
        else:
            assert spec.retention_ms == 30 * DAY_MS
            assert "30 * 86400000" in text.split(topic.value, 1)[1].splitlines()[0], topic


@pytest.mark.parametrize(("attempt", "topic"), [(2, Topics.RETRY_30S), (3, Topics.RETRY_5M)])
def test_retry_topic_for_attempt(attempt: int, topic: Topics) -> None:
    assert retry_topic_for_attempt(attempt) is topic


@pytest.mark.parametrize("attempt", [1, MAX_ATTEMPTS + 1])
def test_no_retry_topic_outside_2_and_3(attempt: int) -> None:
    with pytest.raises(ValueError):
        retry_topic_for_attempt(attempt)
