"""The ``integrations`` consumer end to end: real Kafka, real Postgres, a real HTTPS receiver.

The worker is the real process (``python -m pareeksha.workers.integrations``), the receiver is a
local HTTPS server that verifies the HMAC signature, and the database is a throwaway Postgres
migrated by Alembic. Nothing is mocked. The receiver trusts only its own self-signed certificate
(``SSL_CERT_FILE``) and the sender runs with ``PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1`` because
the receiver lives on loopback; every other SSRF rule (https, no credentials, IP pinning) stays on.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import EvaluationCompleted, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import ConsumerGroups, Topics
from tests.conftest import Tenant
from tests.integration.support import BOOTSTRAP, group_lag, prime_group, wait_for
from tests.integration.webhook_receiver import ReceiverServer

BACKEND_DIR = Path(__file__).resolve().parents[2]
SIGNING_SECRET = "whsec_" + "a1b2c3d4" * 4
GROUP = ConsumerGroups.INTEGRATIONS.value
EVAL_TOPIC = Topics.EVALUATION_COMPLETED


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", key)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pareeksha.example.com")
    return key


@pytest.fixture
def receiver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ReceiverServer]:
    server = ReceiverServer(tmp_path, SIGNING_SECRET).start()
    monkeypatch.setenv("SSL_CERT_FILE", str(server.cert))
    monkeypatch.setenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", "1")
    yield server
    server.stop()


# ----------------------------------------------------------------------------------- helpers
def _db(url: str) -> psycopg.Connection[Any]:
    return psycopg.connect(libpq_url(url), autocommit=True)


def seed_evaluation(
    url: str, project_id: uuid.UUID, *, passed: bool = False, score: float = 42.0
) -> dict[str, uuid.UUID]:
    """An agent, a call (with CRM metadata) and its evaluation, as the evaluator leaves them."""
    with _db(url) as conn:
        agent = conn.execute(
            "INSERT INTO agents (project_id, name, endpoint_url) VALUES (%s, %s, 'wss://x') "
            "RETURNING id",
            (project_id, f"EMI Reminder Bot {uuid.uuid4().hex[:6]}"),
        ).fetchone()
        rubric = conn.execute(
            "INSERT INTO rubric_versions (version, dimensions, prompt_hash) "
            "VALUES (%s, '[]', 'h') RETURNING id",
            (f"rubric-{uuid.uuid4().hex[:8]}",),
        ).fetchone()
        assert agent is not None and rubric is not None
        call = conn.execute(
            "INSERT INTO calls (project_id, agent_id, source, language, status, end_reason, "
            "duration_ms, metadata) VALUES (%s, %s, 'simulation', 'kn-IN', 'completed', "
            "'goal_achieved', 61000, %s) RETURNING id",
            (project_id, agent[0], psycopg.types.json.Jsonb({"phone": "+91XXXXXXXX00"})),
        ).fetchone()
        assert call is not None
        evaluation = conn.execute(
            "INSERT INTO evaluations (call_id, rubric_version_id, judge_model, prompt_hash, "
            "dimensions, overall_score, passed, failure_types, summary) "
            "VALUES (%s, %s, 'judge-x', 'h', %s, %s, %s, %s, 'Agent skipped the disclosure.') "
            "RETURNING id",
            (
                call[0],
                rubric[0],
                psycopg.types.json.Jsonb(
                    {
                        "disclosure": {"score": 0, "evidence_turns": [1], "reason": "not stated"},
                        "tone": {"score": 4, "evidence_turns": [], "reason": "polite"},
                    }
                ),
                score,
                passed,
                ["missing_disclosure"],
            ),
        ).fetchone()
        assert evaluation is not None
    return {"agent": agent[0], "call": call[0], "evaluation": evaluation[0]}


def evaluation_event(
    ids: dict[str, uuid.UUID], *, passed: bool = False, score: float = 42.0
) -> Any:
    payload = EvaluationCompleted(
        call_id=ids["call"],
        evaluation_id=ids["evaluation"],
        agent_id=ids["agent"],
        overall_score=score,
        passed=passed,
        failure_types=["missing_disclosure"],
    )
    return make_envelope(payload, producer="test@host", correlation_id=str(ids["call"]))


async def publish(*envelopes: Any) -> None:
    producer = EventProducer(BOOTSTRAP, client_id="int01b-test")
    await producer.start()
    try:
        for env in envelopes:
            await producer.publish(env)
    finally:
        await producer.stop()


async def create_integration(
    api: AsyncClient, tenant: Tenant, url: str, **overrides: Any
) -> dict[str, Any]:
    body = {
        "connector": "webhook",
        "name": f"receiver-{uuid.uuid4().hex[:6]}",
        "config": {"url": url, "events": ["evaluation.completed"]},
        "secrets": {"signing_secret": SIGNING_SECRET},
        **overrides,
    }
    response = await api.post("/api/v1/integrations", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def delivery_rows(url: str, integration_id: str) -> list[dict[str, Any]]:
    with _db(url) as conn:
        cur = conn.execute(
            "SELECT status, attempts, http_status, direction, event_id, request_summary "
            "FROM integration_deliveries WHERE integration_id = %s ORDER BY created_at",
            (uuid.UUID(integration_id),),
        )
        names = [d.name for d in cur.description or []]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


class Worker:
    """The real ``integrations`` worker process."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc

    @classmethod
    async def spawn(cls, database_url: str, receiver: ReceiverServer) -> Worker:
        env = {
            **os.environ,
            "DATABASE_URL": database_url,
            "KAFKA_BOOTSTRAP_SERVERS": BOOTSTRAP,
            "SSL_CERT_FILE": str(receiver.cert),
            "PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS": "1",
            "PYTHONUNBUFFERED": "1",
        }
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pareeksha.workers.integrations",
            cwd=BACKEND_DIR,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return cls(proc)

    async def stop(self) -> None:
        if self.proc.returncode is None:
            self.proc.send_signal(signal.SIGTERM)
            assert await asyncio.wait_for(self.proc.wait(), 30) == 0, "SIGTERM must exit cleanly"

    async def kill(self) -> None:
        self.proc.send_signal(signal.SIGKILL)
        assert await asyncio.wait_for(self.proc.wait(), 30) == -signal.SIGKILL


@pytest.fixture
async def worker_env(database_url: str) -> AsyncIterator[str]:
    await prime_group(GROUP, [EVAL_TOPIC, Topics.RUN_COMPLETED])
    yield database_url


async def lag_is_zero() -> bool:
    return sum((await group_lag(GROUP, [EVAL_TOPIC, Topics.RUN_COMPLETED])).values()) == 0


# ------------------------------------------------------------------------------------- tests
async def test_evaluation_completed_is_delivered_signed_and_logged(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, worker_env: str
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    ids = seed_evaluation(worker_env, tenant.project_id)
    event = evaluation_event(ids)
    worker = await Worker.spawn(worker_env, receiver)
    try:
        await publish(event)

        async def logged() -> bool:
            rows = delivery_rows(worker_env, integration["id"])
            return bool(rows) and rows[0]["status"] == "succeeded"

        await wait_for(logged, timeout=60, what="delivery row succeeded")
        await wait_for(lag_is_zero, what="offset committed")
    finally:
        await worker.stop()

    [request] = receiver.state.requests
    assert request.signature_ok, "receiver could not verify the HMAC signature"
    assert request.headers["X-Pareeksha-Event-Id"] == str(event.event_id)
    import json

    body = json.loads(request.body)
    assert body["event_id"] == str(event.event_id) and body["type"] == "evaluation.completed"
    data = body["data"]
    assert data["passed"] is False and data["overall_score"] == 42.0
    assert data["agent"]["name"].startswith("EMI Reminder Bot")
    assert data["metadata"] == {"phone": "+91XXXXXXXX00"}
    assert data["link"] == f"https://pareeksha.example.com/calls/{ids['call']}"
    assert [d["dimension"] for d in data["top_failing_dimensions"]] == ["disclosure"]
    assert "transcript" not in request.body.decode()

    [row] = delivery_rows(worker_env, integration["id"])
    assert (row["status"], row["attempts"], row["http_status"], row["direction"]) == (
        "succeeded",
        1,
        200,
        "outbound",
    )
    assert row["event_id"] == event.event_id
    assert row["request_summary"]["event_type"] == "evaluation.completed"

    listed = await api.get(
        f"/api/v1/integrations/{integration['id']}/deliveries", headers=tenant.read
    )
    assert listed.status_code == 200
    [item] = listed.json()["items"]
    assert item["status"] == "succeeded" and item["event_id"] == str(event.event_id)


async def test_duplicate_kafka_delivery_gives_one_delivery(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, worker_env: str
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    ids = seed_evaluation(worker_env, tenant.project_id)
    event = evaluation_event(ids)
    worker = await Worker.spawn(worker_env, receiver)
    try:
        await publish(event, event, event)  # the same event id, three times
        await wait_for(lag_is_zero, timeout=60, what="all three messages consumed")
        await asyncio.sleep(1.0)  # a (wrong) second POST would have arrived by now
    finally:
        await worker.stop()

    assert len(receiver.state.requests) == 1
    assert len(delivery_rows(worker_env, integration["id"])) == 1
    with _db(worker_env) as conn:
        processed = conn.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
            (GROUP, event.event_id),
        ).fetchone()
    assert processed == (1,)


async def test_kill_9_during_the_http_call_still_gives_one_delivery(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, worker_env: str
) -> None:
    import threading

    integration = await create_integration(api, tenant, receiver.url)
    ids = seed_evaluation(worker_env, tenant.project_id)
    event = evaluation_event(ids)
    receiver.state.hold = threading.Event()  # the receiver holds its response: sender is mid-call

    victim = await Worker.spawn(worker_env, receiver)
    await publish(event)
    await wait_for(
        lambda: asyncio.sleep(0, result=receiver.state.arrived.is_set()),
        timeout=60,
        what="the receiver to see the first request",
    )
    # the claim row is already durable and still pending when the process dies
    [claimed] = delivery_rows(worker_env, integration["id"])
    assert claimed["status"] == "pending" and claimed["attempts"] == 1
    await victim.kill()
    assert not await lag_is_zero(), "the offset must not have been committed"

    receiver.state.hold.set()  # the receiver answers from now on
    survivor = await Worker.spawn(worker_env, receiver)
    try:

        async def finished() -> bool:
            rows = delivery_rows(worker_env, integration["id"])
            return len(rows) == 1 and rows[0]["status"] == "succeeded"

        await wait_for(finished, timeout=60, what="redelivered after the crash")
        await wait_for(lag_is_zero, what="offset committed after redelivery")
    finally:
        await survivor.stop()

    # at-least-once on the wire (the dead process's request plus the retry), exactly one logical
    # delivery: one event id at the receiver, one row, attempt 2 recorded
    assert receiver.state.unique_event_ids == {str(event.event_id)}
    assert all(r.signature_ok for r in receiver.state.requests)
    [row] = delivery_rows(worker_env, integration["id"])
    assert (row["status"], row["attempts"]) == ("succeeded", 2)


async def test_event_filter_and_disabled_integrations_are_respected(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, worker_env: str
) -> None:
    only_failed = await create_integration(
        api,
        tenant,
        receiver.url,
        event_filter={"events": ["evaluation.completed"], "only_failed": True},
    )
    disabled = await create_integration(api, tenant, receiver.url, enabled=False)
    ids = seed_evaluation(worker_env, tenant.project_id, passed=True, score=95.0)
    worker = await Worker.spawn(worker_env, receiver)
    try:
        await publish(evaluation_event(ids, passed=True, score=95.0))
        await wait_for(lag_is_zero, timeout=60, what="event consumed")
    finally:
        await worker.stop()
    assert delivery_rows(worker_env, only_failed["id"]) == []
    assert delivery_rows(worker_env, disabled["id"]) == []
    assert receiver.state.requests == []
