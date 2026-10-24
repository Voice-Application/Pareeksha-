"""Integrations CRUD with write-only, Fernet-encrypted secrets (FR-IN-2) on real Postgres."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.connectors import connector_direction, installed_directions
from pareeksha.db.models import Integrations
from pareeksha.integrations.crypto import SecretBox
from tests.conftest import Tenant

HUBSPOT: dict[str, Any] = {
    "connector": "hubspot",
    "name": "HubSpot – collections portal",
    "config": {"match_by": "phone", "only_failed": False},
    "secrets": {"private_app_token": "pat-very-secret-token"},
    "event_filter": {"events": ["evaluation.completed"], "only_failed": True},
}
WEBHOOK: dict[str, Any] = {
    "connector": "webhook",
    "name": "CI webhook",
    "config": {"url": "https://ci.example.com/hook"},
}


@pytest.fixture(autouse=True)
def secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", key)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://pareeksha.example.com/")
    return key


async def _stored_secrets(
    factory: async_sessionmaker[AsyncSession], integration_id: str
) -> bytes | None:
    async with factory() as session:
        value = await session.scalar(
            text("SELECT secrets_encrypted FROM integrations WHERE id = :i"),
            {"i": uuid.UUID(integration_id)},
        )
    return None if value is None else bytes(value)


async def test_create_hides_secrets_and_stores_ciphertext(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    secret_key: str,
) -> None:
    response = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["secrets_set"] is True and body["direction"] == "sink" and body["enabled"] is True
    assert body["config"] == HUBSPOT["config"] and body["event_filter"]["only_failed"] is True
    assert body["inbound_url"] is None and body["signing_secret"] is None
    assert "pat-very-secret-token" not in response.text and "secrets" not in body

    stored = await _stored_secrets(session_factory, body["id"])
    assert stored is not None and b"pat-very-secret-token" not in stored
    assert SecretBox(secret_key).decrypt(stored.decode()) == HUBSPOT["secrets"]

    fetched = await api.get(f"/api/v1/integrations/{body['id']}", headers=tenant.read)
    assert fetched.status_code == 200 and "pat-very-secret-token" not in fetched.text
    assert fetched.json()["secrets_set"] is True
    listed = await api.get("/api/v1/integrations", headers=tenant.read)
    assert "pat-very-secret-token" not in listed.text


async def test_webhook_gets_inbound_url_and_a_signing_secret_shown_once(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    secret_key: str,
) -> None:
    created = (await api.post("/api/v1/integrations", json=WEBHOOK, headers=tenant.admin)).json()
    secret = created["signing_secret"]
    assert isinstance(secret, str) and len(secret) >= 32
    assert created["inbound_url"] == (
        f"https://pareeksha.example.com/api/v1/webhooks/inbound/{created['id']}"
    )
    stored = await _stored_secrets(session_factory, created["id"])
    assert stored is not None
    assert SecretBox(secret_key).decrypt(stored.decode()) == {"signing_secret": secret}

    again = (await api.get(f"/api/v1/integrations/{created['id']}", headers=tenant.read)).json()
    assert again["signing_secret"] is None and again["secrets_set"] is True
    assert again["inbound_url"] == created["inbound_url"]

    chosen = await api.post(
        "/api/v1/integrations",
        json={**WEBHOOK, "name": "own secret", "secrets": {"signing_secret": "x" * 20}},
        headers=tenant.admin,
    )
    assert chosen.json()["signing_secret"] == "x" * 20


async def test_patch_replaces_secrets_only_when_provided(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    secret_key: str,
) -> None:
    created = (await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)).json()
    url = f"/api/v1/integrations/{created['id']}"
    before = await _stored_secrets(session_factory, created["id"])

    renamed = await api.patch(
        url,
        json={"name": "Renamed", "enabled": False, "config": {"match_by": "email"}},
        headers=tenant.admin,
    )
    assert renamed.status_code == 200
    body = renamed.json()
    assert body["name"] == "Renamed" and body["enabled"] is False
    assert body["config"] == {"match_by": "email"} and body["secrets_set"] is True
    assert body["updated_at"] >= created["updated_at"]
    assert await _stored_secrets(session_factory, created["id"]) == before

    filtered = await api.patch(
        url, json={"event_filter": {"events": ["run.completed"]}}, headers=tenant.admin
    )
    assert filtered.json()["event_filter"]["events"] == ["run.completed"]

    rotated = await api.patch(
        url, json={"secrets": {"private_app_token": "pat-new"}}, headers=tenant.admin
    )
    assert rotated.json()["secrets_set"] is True
    after = await _stored_secrets(session_factory, created["id"])
    assert after is not None and after != before
    assert SecretBox(secret_key).decrypt(after.decode()) == {"private_app_token": "pat-new"}

    cleared = await api.patch(url, json={"secrets": {}}, headers=tenant.admin)
    assert cleared.json()["secrets_set"] is False
    assert await _stored_secrets(session_factory, created["id"]) is None


async def test_patching_a_webhook_keeps_its_signing_secret(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    secret_key: str,
) -> None:
    created = (await api.post("/api/v1/integrations", json=WEBHOOK, headers=tenant.admin)).json()
    url = f"/api/v1/integrations/{created['id']}"
    await api.patch(
        url, json={"secrets": {"previous_signing_secret": "p" * 20}}, headers=tenant.admin
    )
    stored = await _stored_secrets(session_factory, created["id"])
    assert stored is not None
    assert SecretBox(secret_key).decrypt(stored.decode()) == {
        "signing_secret": created["signing_secret"],
        "previous_signing_secret": "p" * 20,
    }
    await api.patch(url, json={"secrets": {"signing_secret": "n" * 20}}, headers=tenant.admin)
    stored = await _stored_secrets(session_factory, created["id"])
    assert stored is not None
    assert SecretBox(secret_key).decrypt(stored.decode()) == {"signing_secret": "n" * 20}


async def test_patching_a_webhook_row_that_has_no_stored_secrets(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        row = Integrations(
            project_id=tenant.project_id, connector="webhook", name="legacy", direction="sink"
        )
        session.add(row)
        await session.commit()
    response = await api.patch(
        f"/api/v1/integrations/{row.id}",
        json={"secrets": {"signing_secret": "s" * 20}},
        headers=tenant.admin,
    )
    assert response.status_code == 200 and response.json()["secrets_set"] is True


async def test_unknown_connector_duplicates_and_validation(
    api: AsyncClient, tenant: Tenant
) -> None:
    unknown = await api.post(
        "/api/v1/integrations", json={**HUBSPOT, "connector": "nope"}, headers=tenant.admin
    )
    assert unknown.status_code == 400 and unknown.json()["error"]["details"] == {
        "connector": "nope"
    }
    first = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)
    assert first.status_code == 201
    dup = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)
    assert dup.status_code == 409
    other = (
        await api.post(
            "/api/v1/integrations", json={**HUBSPOT, "name": "second"}, headers=tenant.admin
        )
    ).json()
    clash = await api.patch(
        f"/api/v1/integrations/{other['id']}", json={"name": HUBSPOT["name"]}, headers=tenant.admin
    )
    assert clash.status_code == 409
    bad = await api.post("/api/v1/integrations", json={**HUBSPOT, "name": ""}, headers=tenant.admin)
    assert bad.status_code == 400


async def test_admin_scope_for_writes_read_scope_for_reads_and_isolation(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    denied = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.read)
    assert denied.status_code == 403
    created = (await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)).json()
    url = f"/api/v1/integrations/{created['id']}"
    assert (await api.get(url, headers=tenant.read)).status_code == 200
    assert (await api.patch(url, json={"enabled": False}, headers=tenant.read)).status_code == 403
    assert (await api.delete(url, headers=tenant.read)).status_code == 403
    assert (await api.get(url, headers=other_tenant.read)).status_code == 404
    assert (await api.patch(url, json={}, headers=other_tenant.admin)).status_code == 404
    assert (await api.delete(url, headers=other_tenant.admin)).status_code == 404
    assert (await api.get("/api/v1/integrations", headers=other_tenant.read)).json()["items"] == []
    ghost = f"/api/v1/integrations/{uuid.uuid4()}"
    assert (await api.get(ghost, headers=tenant.read)).status_code == 404


async def test_delete_removes_the_integration(api: AsyncClient, tenant: Tenant) -> None:
    created = (await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)).json()
    url = f"/api/v1/integrations/{created['id']}"
    deleted = await api.delete(url, headers=tenant.admin)
    assert deleted.status_code == 204 and deleted.content == b""
    assert (await api.get(url, headers=tenant.read)).status_code == 404


async def test_missing_or_invalid_secret_key_is_a_500_not_a_leak(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SECRET_KEY")
    missing = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)
    assert missing.status_code == 500 and "SECRET_KEY" in missing.json()["error"]["message"]
    monkeypatch.setenv("SECRET_KEY", "not-a-fernet-key")
    invalid = await api.post("/api/v1/integrations", json=HUBSPOT, headers=tenant.admin)
    assert invalid.status_code == 500 and "Fernet" in invalid.json()["error"]["message"]
    # without secrets nothing needs the key
    plain = await api.post(
        "/api/v1/integrations",
        json={"connector": "hubspot", "name": "no secrets"},
        headers=tenant.admin,
    )
    assert plain.status_code == 201 and plain.json()["secrets_set"] is False


async def test_wrong_secret_key_when_patching_a_webhook_is_a_500(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = (await api.post("/api/v1/integrations", json=WEBHOOK, headers=tenant.admin)).json()
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    response = await api.patch(
        f"/api/v1/integrations/{created['id']}",
        json={"secrets": {"previous_signing_secret": "p" * 20}},
        headers=tenant.admin,
    )
    assert response.status_code == 500 and "SECRET_KEY" in response.json()["error"]["message"]
    assert json.dumps(response.json()).count(created["signing_secret"]) == 0


def test_connector_directions_include_shipped_and_entry_point_connectors() -> None:
    assert connector_direction("webhook") == "sink"
    assert connector_direction("hubspot") == "sink"
    assert connector_direction("does-not-exist") is None
    assert {"webhook", "hubspot"} <= set(installed_directions())


def test_a_broken_entry_point_plugin_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        name = "broken"

        def load(self) -> Any:
            raise ImportError("missing dependency")

    class Good:
        name = "zoho"

        def load(self) -> Any:
            class Zoho:
                name = "zoho"
                direction = "both"

            return Zoho

    monkeypatch.setattr("pareeksha.api.connectors.entry_points", lambda group: [Broken(), Good()])
    found = installed_directions()
    assert found["zoho"] == "both" and "broken" not in found and found["webhook"] == "sink"
