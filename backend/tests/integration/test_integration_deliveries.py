"""SQL delivery store, dispatch and the delivery routes (real Postgres, real HTTPS receiver)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from pareeksha.events.settings import libpq_url
from pareeksha.integrations.crypto import SecretBox
from pareeksha.integrations.delivery import DeliveryRecord
from pareeksha.integrations.dispatch import DeliveryRetry, deliver_to_sinks
from pareeksha.integrations.registry import get_registry
from pareeksha.integrations.sql_store import PsycopgDeliveryStore
from tests.conftest import Tenant
from tests.integration.test_integrations_worker import (
    SIGNING_SECRET,
    _db,
    create_integration,
    delivery_rows,
    evaluation_event,
    seed_evaluation,
)
from tests.integration.webhook_receiver import ReceiverServer


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch, database_url: str) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", key)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pareeksha.example.com")
    monkeypatch.setenv("DATABASE_URL", database_url)
    return key


@pytest.fixture
def receiver(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ReceiverServer]:
    server = ReceiverServer(tmp_path, SIGNING_SECRET).start()
    monkeypatch.setenv("SSL_CERT_FILE", str(server.cert))
    monkeypatch.setenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", "1")
    yield server
    server.stop()


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as connection:
        yield connection


# ------------------------------------------------------------------------------- SQL store
async def test_store_claim_is_unique_per_integration_event_direction(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, conn: psycopg.AsyncConnection[Any]
) -> None:
    integration = uuid.UUID((await create_integration(api, tenant, receiver.url))["id"])
    store = PsycopgDeliveryStore(conn)
    event_id = uuid.uuid4()
    first, created = await store.claim(integration, event_id, "outbound")
    again, created_again = await store.claim(integration, event_id, "outbound")
    inbound, created_inbound = await store.claim(integration, event_id, "inbound")
    assert (created, created_again, created_inbound) == (True, False, True)
    assert again.id == first.id != inbound.id
    assert first.status == "pending" and first.attempts == 0

    first.status, first.attempts, first.http_status = "succeeded", 1, 200
    first.external_id, first.response_excerpt = "note-7", "ok"
    first.request_summary = {"event_type": "evaluation.completed"}
    await store.save(first)
    loaded = await store.get(first.id)
    assert loaded is not None
    assert (loaded.status, loaded.attempts, loaded.http_status, loaded.external_id) == (
        "succeeded",
        1,
        200,
        "note-7",
    )
    assert loaded.request_summary == {"event_type": "evaluation.completed"}
    assert [r.id for r in await store.recent(integration)] == [inbound.id, first.id]
    assert await store.get(uuid.uuid4()) is None


async def test_concurrent_claims_create_one_row(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer, database_url: str
) -> None:
    integration = uuid.UUID((await create_integration(api, tenant, receiver.url))["id"])
    event_id = uuid.uuid4()

    async def claim() -> tuple[DeliveryRecord, bool]:
        async with await psycopg.AsyncConnection.connect(
            libpq_url(database_url), autocommit=True
        ) as c:
            return await PsycopgDeliveryStore(c).claim(integration, event_id, "outbound")

    results = await asyncio.gather(*[claim() for _ in range(8)])
    assert sum(1 for _, created in results if created) == 1
    assert len({r.id for r, _ in results}) == 1


async def test_store_refuses_a_transactional_connection(database_url: str) -> None:
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url)) as c:
        with pytest.raises(ValueError, match="autocommit"):
            PsycopgDeliveryStore(c)


async def test_claim_for_an_unknown_integration_violates_the_foreign_key(
    conn: psycopg.AsyncConnection[Any],
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await PsycopgDeliveryStore(conn).claim(uuid.uuid4(), uuid.uuid4(), "outbound")


# ---------------------------------------------------------------------------------- dispatch
async def _dispatch(
    conn: psycopg.AsyncConnection[Any], secret_key: str, event: Any, *, final_attempt: bool = False
) -> list[DeliveryRecord]:
    return await deliver_to_sinks(
        conn,
        PsycopgDeliveryStore(conn),
        SecretBox(secret_key),
        get_registry(),
        event,
        final_attempt=final_attempt,
    )


async def test_retryable_failure_keeps_the_row_pending_then_failed_on_the_last_attempt(
    api: AsyncClient,
    tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    ids = seed_evaluation(database_url, tenant.project_id)
    event = evaluation_event(ids)
    receiver.state.statuses = [503, 503]

    with pytest.raises(DeliveryRetry, match="503"):
        await _dispatch(conn, environment, event)
    [row] = delivery_rows(database_url, integration["id"])
    assert (row["status"], row["attempts"]) == ("pending", 1)

    done = await _dispatch(conn, environment, event, final_attempt=True)  # no retry left
    assert [d.status for d in done] == []  # retryable on the last attempt is not "delivered"
    [row] = delivery_rows(database_url, integration["id"])
    assert (row["status"], row["attempts"]) == ("failed", 2)

    # a later healthy attempt for a failed row is allowed (redeliver does exactly this)
    again = await _dispatch(conn, environment, event)
    assert [d.status for d in again] == ["succeeded"]
    [row] = delivery_rows(database_url, integration["id"])
    assert (row["status"], row["attempts"], row["http_status"]) == ("succeeded", 3, 200)

    # terminal rows are never sent again
    await _dispatch(conn, environment, event)
    assert len(receiver.state.requests) == 3


async def test_permanent_failure_is_logged_failed_without_retry(
    api: AsyncClient,
    tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    receiver.state.statuses = [404]
    event = evaluation_event(seed_evaluation(database_url, tenant.project_id))
    [done] = await _dispatch(conn, environment, event)
    assert done.status == "failed" and "404" in (done.response_excerpt or "")
    [row] = delivery_rows(database_url, integration["id"])
    assert (row["status"], row["http_status"]) == ("failed", None)


async def test_one_failing_integration_does_not_block_the_others(
    api: AsyncClient,
    tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    first = await create_integration(api, tenant, receiver.url)
    second = await create_integration(api, tenant, receiver.url)
    receiver.state.statuses = [500]  # the first request fails, the second succeeds
    event = evaluation_event(seed_evaluation(database_url, tenant.project_id))
    with pytest.raises(DeliveryRetry):
        await _dispatch(conn, environment, event)
    statuses = {delivery_rows(database_url, i["id"])[0]["status"] for i in (first, second)}
    assert statuses == {"pending", "succeeded"}

    await _dispatch(conn, environment, event)  # the retry only re-sends the pending one
    assert len(receiver.state.requests) == 3
    assert all(
        delivery_rows(database_url, i["id"])[0]["status"] == "succeeded" for i in (first, second)
    )


async def test_missing_evaluation_and_other_projects_are_not_delivered(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    mine = await create_integration(api, tenant, receiver.url)
    theirs = await create_integration(api, other_tenant, receiver.url)
    ids = seed_evaluation(database_url, tenant.project_id)
    await _dispatch(conn, environment, evaluation_event(ids))
    assert len(delivery_rows(database_url, mine["id"])) == 1
    assert delivery_rows(database_url, theirs["id"]) == []

    ghost = dict(ids, evaluation=uuid.uuid4())
    with pytest.raises(LookupError, match="not found"):
        await _dispatch(conn, environment, evaluation_event(ghost))


# --------------------------------------------------------------------------------- the routes
async def test_connectors_route_lists_webhook_and_hubspot(api: AsyncClient, tenant: Tenant) -> None:
    response = await api.get("/api/v1/integrations/connectors", headers=tenant.read)
    assert response.status_code == 200
    assert {c["name"] for c in response.json()} >= {"webhook", "hubspot"}


async def test_test_route_runs_the_connector_and_stores_the_result(
    api: AsyncClient, tenant: Tenant, receiver: ReceiverServer
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    url = f"/api/v1/integrations/{integration['id']}/test"

    ok = await api.post(url, headers=tenant.admin)
    assert ok.status_code == 200 and ok.json() == {"ok": True, "detail": "HTTP 200"}
    assert receiver.state.requests[-1].signature_ok
    fetched = (
        await api.get(f"/api/v1/integrations/{integration['id']}", headers=tenant.read)
    ).json()
    assert fetched["last_test_ok"] is True and fetched["last_test_at"] is not None

    receiver.state.statuses = [500]
    failing = await api.post(url, headers=tenant.admin)
    assert failing.json() == {"ok": False, "detail": "HTTP 500"}
    fetched = (
        await api.get(f"/api/v1/integrations/{integration['id']}", headers=tenant.read)
    ).json()
    assert fetched["last_test_ok"] is False

    assert (await api.post(url, headers=tenant.read)).status_code == 403
    missing = await api.post(f"/api/v1/integrations/{uuid.uuid4()}/test", headers=tenant.admin)
    assert missing.status_code == 404


async def test_test_route_reports_bad_configuration_and_unknown_connectors(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    bad = await create_integration(
        api, tenant, "https://ci.example.com/hook", secrets={"signing_secret": "short"}
    )
    result = await api.post(f"/api/v1/integrations/{bad['id']}/test", headers=tenant.admin)
    assert result.status_code == 200
    body = result.json()
    assert (
        body["ok"] is False and "signing_secret" in body["detail"] and "short" not in body["detail"]
    )

    with _db(database_url) as c:
        c.execute(
            "UPDATE integrations SET connector = 'gone' WHERE id = %s", (uuid.UUID(bad["id"]),)
        )
    gone = await api.post(f"/api/v1/integrations/{bad['id']}/test", headers=tenant.admin)
    assert gone.json() == {"ok": False, "detail": "Connector 'gone' is not installed"}


async def test_ssrf_guard_applies_to_the_test_route(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", raising=False)
    integration = await create_integration(api, tenant, "https://127.0.0.1:9/hook")
    result = await api.post(f"/api/v1/integrations/{integration['id']}/test", headers=tenant.admin)
    assert result.json()["ok"] is False and "non-public" in result.json()["detail"]


async def test_deliveries_route_filters_paginates_and_is_project_scoped(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    receiver.state.statuses = [404]  # the first event fails permanently
    for _ in range(3):
        event = evaluation_event(seed_evaluation(database_url, tenant.project_id))
        await _dispatch(conn, environment, event)

    base = f"/api/v1/integrations/{integration['id']}/deliveries"
    everything = (await api.get(base, headers=tenant.read)).json()
    assert len(everything["items"]) == 3 and everything["next_cursor"] is None

    failed = (await api.get(base, params={"status": "failed"}, headers=tenant.read)).json()
    assert [d["status"] for d in failed["items"]] == ["failed"]
    succeeded = (await api.get(base, params={"status": "succeeded"}, headers=tenant.read)).json()
    assert len(succeeded["items"]) == 2

    first = (await api.get(base, params={"limit": 2}, headers=tenant.read)).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    rest = (
        await api.get(
            base, params={"limit": 2, "cursor": first["next_cursor"]}, headers=tenant.read
        )
    ).json()
    assert len(rest["items"]) == 1
    assert {d["id"] for d in first["items"] + rest["items"]} == {
        d["id"] for d in everything["items"]
    }

    assert (await api.get(base, headers=other_tenant.read)).status_code == 404
    assert (await api.get(base, params={"status": "bogus"}, headers=tenant.read)).status_code == 400


async def test_redeliver_sends_the_logged_event_again_under_the_same_event_id(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    receiver.state.statuses = [404]
    event = evaluation_event(seed_evaluation(database_url, tenant.project_id))
    await _dispatch(conn, environment, event)
    [failed] = delivery_rows(database_url, integration["id"])
    assert failed["status"] == "failed"
    listed = (
        await api.get(f"/api/v1/integrations/{integration['id']}/deliveries", headers=tenant.read)
    ).json()
    delivery_id = listed["items"][0]["id"]
    url = f"/api/v1/integrations/{integration['id']}/deliveries/{delivery_id}/redeliver"

    response = await api.post(url, headers=tenant.admin)
    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["id"], body["status"], body["http_status"], body["attempts"]) == (
        delivery_id,
        "succeeded",
        200,
        2,
    )
    assert [r.event_id for r in receiver.state.requests] == [str(event.event_id)] * 2
    assert all(r.signature_ok for r in receiver.state.requests)
    [row] = delivery_rows(database_url, integration["id"])
    assert (row["status"], row["attempts"]) == ("succeeded", 2)

    assert (await api.post(url, headers=tenant.read)).status_code == 403
    assert (await api.post(url, headers=other_tenant.admin)).status_code == 404
    unknown = await api.post(
        f"/api/v1/integrations/{integration['id']}/deliveries/{uuid.uuid4()}/redeliver",
        headers=tenant.admin,
    )
    assert unknown.status_code == 404

    # a row written before events were captured cannot be replayed
    with _db(database_url) as c:
        c.execute(
            "UPDATE integration_deliveries SET request_summary = '{}' WHERE id = %s",
            (uuid.UUID(delivery_id),),
        )
    assert (await api.post(url, headers=tenant.admin)).status_code == 409


async def test_redeliver_records_a_failing_receiver_as_failed(
    api: AsyncClient,
    tenant: Tenant,
    receiver: ReceiverServer,
    conn: psycopg.AsyncConnection[Any],
    database_url: str,
    environment: str,
) -> None:
    integration = await create_integration(api, tenant, receiver.url)
    event = evaluation_event(seed_evaluation(database_url, tenant.project_id))
    await _dispatch(conn, environment, event)
    delivery_id = delivery_rows(database_url, integration["id"])[0]
    with _db(database_url) as c:
        row = c.execute(
            "SELECT id FROM integration_deliveries WHERE integration_id = %s",
            (uuid.UUID(integration["id"]),),
        ).fetchone()
    assert row is not None and delivery_id["status"] == "succeeded"
    receiver.state.statuses = [503]
    response = await api.post(
        f"/api/v1/integrations/{integration['id']}/deliveries/{row[0]}/redeliver",
        headers=tenant.admin,
    )
    assert response.status_code == 202 and response.json()["status"] == "failed"
