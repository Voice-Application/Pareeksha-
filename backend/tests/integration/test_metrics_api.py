"""GET /metrics/summary and GET /usage (API-04, NFR-16). Real Postgres and a real Kafka broker."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiokafka import AIOKafkaConsumer
from httpx import AsyncClient

from pareeksha.api.main import app
from pareeksha.db import models
from pareeksha.events.producer import EventProducer
from pareeksha.events.settings import kafka_bootstrap
from pareeksha.events.topics import Topics
from tests.conftest import Tenant
from tests.integration.api04_support import Factory
from tests.integration.runs_support import API
from tests.integration.support import (
    BOOTSTRAP,
    audit_envelope,
    prime_group,
    unique_group,
)


@pytest.fixture(autouse=True)
def _broker() -> Iterator[None]:
    app.dependency_overrides[kafka_bootstrap] = lambda: BOOTSTRAP
    yield
    app.dependency_overrides.pop(kafka_bootstrap, None)


async def _catch_up(group: str) -> None:
    """Read and commit everything the group has not consumed yet."""
    consumer: Any = AIOKafkaConsumer(
        Topics.AUDIT_REQUESTED.value,
        bootstrap_servers=BOOTSTRAP,
        group_id=group,
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        while True:
            await consumer.getmany(timeout_ms=500)
            ends = await consumer.end_offsets(list(consumer.assignment()))
            if consumer.assignment() and all(
                [await consumer.position(tp) >= ends[tp] for tp in consumer.assignment()]
            ):
                break
        await consumer.commit()
    finally:
        await consumer.stop()


async def _summary(api: AsyncClient, tenant: Tenant) -> dict[str, object]:
    response = await api.get(f"{API}/metrics/summary", headers=tenant.read)
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_consumer_lag_is_end_offset_minus_committed_per_group(
    api: AsyncClient, tenant: Tenant
) -> None:
    group = unique_group("lag-probe")
    await prime_group(group, [Topics.AUDIT_REQUESTED])
    assert (await _summary(api, tenant))["consumer_lag"][group] == 0  # type: ignore[index]

    producer = EventProducer(BOOTSTRAP)
    await producer.start()
    try:
        for _ in range(7):
            await producer.publish(audit_envelope())
    finally:
        await producer.stop()
    lag = (await _summary(api, tenant))["consumer_lag"]
    assert lag[group] == 7  # type: ignore[index]

    await _catch_up(group)
    assert (await _summary(api, tenant))["consumer_lag"][group] == 0  # type: ignore[index]


async def test_outbox_backlog_dlq_open_and_credits_used_come_from_postgres(
    private_api: tuple[AsyncClient, Tenant, Factory],
) -> None:
    api, tenant, session_factory = private_api
    before = await _summary(api, tenant)
    env = audit_envelope()
    async with session_factory() as session:
        for published in (None, None, datetime.now(UTC)):
            e = audit_envelope()
            session.add(
                models.OutboxEvents(
                    id=e.event_id,
                    topic=e.topic.value,
                    key=e.partition_key(),
                    envelope=e.model_dump(mode="json"),
                    published_at=published,
                )
            )
        for status in ("open", "open", "replayed", "discarded"):
            session.add(
                models.DeadLetters(
                    event_id=uuid.uuid4(),
                    original_topic=env.topic.value,
                    key="k",
                    consumer_group="auditor",
                    envelope={},
                    error="x",
                    attempts=3,
                    status=status,
                )
            )
        session.add_all(
            [
                models.ApiUsage(
                    provider="gnani",
                    operation="tts",
                    units=100,
                    unit_type="characters",
                    est_cost=1.25,
                ),
                models.ApiUsage(
                    provider="deepseek",
                    operation="llm_judge",
                    units=900,
                    unit_type="tokens",
                    est_cost=0.5,
                ),
                models.ApiUsage(
                    provider="gnani",
                    operation="stt_batch",
                    units=30,
                    unit_type="audio_seconds",
                ),  # no cost recorded
            ]
        )
        await session.commit()
    after = await _summary(api, tenant)
    assert after["outbox_backlog"] == before["outbox_backlog"] + 2  # type: ignore[operator]
    assert after["dlq_open"] == before["dlq_open"] + 2  # type: ignore[operator]
    assert after["credits_used"] == pytest.approx(before["credits_used"] + 1.75)  # type: ignore[operator]
    assert set(after) == {"consumer_lag", "outbox_backlog", "dlq_open", "credits_used"}


async def test_summary_is_502_when_kafka_is_unreachable_and_needs_a_key(
    api: AsyncClient, tenant: Tenant
) -> None:
    app.dependency_overrides[kafka_bootstrap] = lambda: "127.0.0.1:1"
    response = await api.get(f"{API}/metrics/summary", headers=tenant.read)
    assert response.status_code == 502 and response.json()["error"]["code"] == "upstream_error"
    assert (await api.get(f"{API}/metrics/summary")).status_code == 401


async def test_usage_aggregates_a_time_window_and_reports_the_budget(
    private_api: tuple[AsyncClient, Tenant, Factory], monkeypatch: pytest.MonkeyPatch
) -> None:
    api, tenant, session_factory = private_api
    window_start = datetime(2001, 1, 1, tzinfo=UTC)
    inside = window_start + timedelta(days=1)
    async with session_factory() as session:
        session.add_all(
            models.ApiUsage(
                provider=provider,
                operation=operation,
                units=units,
                unit_type=unit_type,
                est_cost=cost,
                created_at=when,
            )
            for provider, operation, units, unit_type, cost, when in (
                ("gnani", "tts", 100, "characters", 1.0, inside),
                ("gnani", "tts", 50, "characters", 0.5, inside),
                ("gnani", "stt_batch", 60, "audio_seconds", 2.0, inside),
                ("deepseek", "llm_judge", 1000, "tokens", None, inside),
                ("gnani", "tts", 9999, "characters", 99.0, window_start + timedelta(days=30)),
            )
        )
        await session.commit()
    monkeypatch.setenv("BUDGET_CREDITS", "1000")
    params = {
        "from": window_start.isoformat(),
        "to": (window_start + timedelta(days=2)).isoformat(),
    }
    body = (await api.get(f"{API}/usage", params=params, headers=tenant.read)).json()
    assert body["items"] == [
        {
            "provider": "deepseek",
            "operation": "llm_judge",
            "unit_type": "tokens",
            "units": 1000.0,
            "est_cost": None,
        },
        {
            "provider": "gnani",
            "operation": "stt_batch",
            "unit_type": "audio_seconds",
            "units": 60.0,
            "est_cost": 2.0,
        },
        {
            "provider": "gnani",
            "operation": "tts",
            "unit_type": "characters",
            "units": 150.0,
            "est_cost": 1.5,
        },
    ]
    assert body["credits_used"] == 3.5
    assert body["budget_credits"] == 1000.0
    total = (await _summary(api, tenant))["credits_used"]
    assert body["remaining_budget"] == pytest.approx(1000.0 - total)  # type: ignore[operator]

    open_window = (
        await api.get(f"{API}/usage", params={"from": params["from"]}, headers=tenant.read)
    ).json()
    assert open_window["credits_used"] >= 102.5

    monkeypatch.delenv("BUDGET_CREDITS")
    no_budget = (await api.get(f"{API}/usage", params=params, headers=tenant.read)).json()
    assert no_budget["budget_credits"] is None and no_budget["remaining_budget"] is None
    assert (await api.get(f"{API}/usage")).status_code == 401
    assert (await api.get(f"{API}/usage?from=yesterday", headers=tenant.read)).status_code == 400
