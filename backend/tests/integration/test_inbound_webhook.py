"""FR-IN-7: the signed inbound webhook becomes an import call and ``audit.requested``."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from pareeksha.events.schemas import AuditRequested
from pareeksha.integrations.signing import sign_headers
from tests.conftest import Tenant
from tests.integration.audit_support import create_agent, fetch_rows, outbox_envelopes

SECRET = "s3cret-s3cret-s3cret-0001"
RECORDING = "https://8.8.8.8/recordings/CA123.mp3"  # an IP literal: public, no DNS in tests


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", raising=False)


async def _source(
    api: AsyncClient, tenant: Tenant, *, config: dict[str, Any] | None = None, **extra: Any
) -> str:
    response = await api.post(
        "/api/v1/integrations",
        json={
            "connector": "webhook",
            "name": f"crm-{uuid.uuid4().hex[:6]}",
            "config": {"url": "https://hooks.example.com/in", **(config or {})},
            "secrets": {"signing_secret": SECRET, **extra},
        },
        headers=tenant.admin,
    )
    assert response.status_code == 201, response.text
    assert response.json()["direction"] == "both"
    return str(response.json()["id"])


def _payload(agent_name: str | None, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "external_id": f"exotel-{uuid.uuid4().hex[:8]}",
        "recording_url": RECORDING,
        "language": "kn-IN",
        "metadata": {"phone": "+91XXXXXXXX00", "crm_contact_id": "1234"},
    }
    if agent_name is not None:
        body["agent_name"] = agent_name
    return {**body, **overrides}


async def _post(
    api: AsyncClient,
    integration_id: str,
    body: dict[str, Any],
    *,
    secret: str = SECRET,
    timestamp: int | None = None,
) -> Any:
    raw = json.dumps(body).encode()
    headers = {**sign_headers(secret, raw, timestamp=timestamp), "Content-Type": "application/json"}
    return await api.post(
        f"/api/v1/webhooks/inbound/{integration_id}", content=raw, headers=headers
    )


async def _agent_name(api: AsyncClient, tenant: Tenant) -> str:
    agent_id = await create_agent(api, tenant)
    response = await api.get(f"/api/v1/agents/{agent_id}", headers=tenant.admin)
    return str(response.json()["name"])


async def test_signed_delivery_becomes_an_import_call_and_audit_requested(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    body = _payload(name)
    response = await _post(api, integration, body)
    assert response.status_code == 202, response.text
    call_id = response.json()["call_id"]
    assert response.json()["duplicate"] is False

    (call,) = await fetch_rows(database_url, "SELECT * FROM calls WHERE id = %s", call_id)
    assert call["source"] == "import" and call["status"] == "transcribing"
    assert str(call["project_id"]) == str(tenant.project_id) and call["language"] == "kn-IN"
    assert call["metadata"] == body["metadata"]
    (ref,) = await fetch_rows(
        database_url, "SELECT * FROM external_refs WHERE call_id = %s", call_id
    )
    assert ref["external_id"] == body["external_id"] and str(ref["integration_id"]) == integration

    (env,) = await outbox_envelopes(database_url, call_id, "pareeksha.audit.requested.v1")
    payload = env.payload
    assert isinstance(payload, AuditRequested)
    assert payload.source == "import" and payload.recording_ref == RECORDING
    assert str(payload.integration_id) == integration and payload.external_id == body["external_id"]
    assert str(payload.agent_id) == str(call["agent_id"])


async def test_same_external_id_twice_is_one_call(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    body = _payload(name)
    first = await _post(api, integration, body)
    again = await _post(api, integration, body)  # same delivery replayed
    assert again.status_code == 202 and again.json() == {
        "call_id": first.json()["call_id"],
        "duplicate": True,
    }
    rows = await fetch_rows(
        database_url, "SELECT 1 FROM external_refs WHERE integration_id = %s", integration
    )
    assert len(rows) == 1
    assert (
        len(
            await outbox_envelopes(
                database_url, first.json()["call_id"], "pareeksha.audit.requested.v1"
            )
        )
        == 1
    )


async def test_default_agent_is_used_when_the_name_is_unknown(
    api: AsyncClient, tenant: Tenant
) -> None:
    agent_id = await create_agent(api, tenant)
    integration = await _source(api, tenant, config={"default_agent_id": agent_id})
    response = await _post(api, integration, _payload("Nobody Bot"))
    assert response.status_code == 202, response.text


async def test_unknown_agent_without_default_is_422(api: AsyncClient, tenant: Tenant) -> None:
    integration = await _source(api, tenant)
    response = await _post(api, integration, _payload("Nobody Bot"))
    assert response.status_code == 422 and response.json()["error"]["code"] == "unknown_agent"
    bad_default = await _source(api, tenant, config={"default_agent_id": "not-a-uuid"})
    response = await _post(api, bad_default, _payload(None))
    assert response.status_code == 422


async def test_bad_signature_is_401_and_creates_nothing(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    body = _payload(name)
    response = await _post(api, integration, body, secret="wrong-wrong-wrong-wrong")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_signature"
    tampered = await api.post(
        f"/api/v1/webhooks/inbound/{integration}",
        content=json.dumps(body).encode(),
        headers={**sign_headers(SECRET, b"{}"), "Content-Type": "application/json"},
    )
    assert tampered.status_code == 401
    rows = await fetch_rows(
        database_url, "SELECT 1 FROM external_refs WHERE integration_id = %s", integration
    )
    assert rows == []


async def test_stale_timestamp_is_408(api: AsyncClient, tenant: Tenant) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    response = await _post(api, integration, _payload(name), timestamp=int(time.time()) - 3600)
    assert response.status_code == 408


async def test_previous_secret_is_accepted_during_rotation(
    api: AsyncClient, tenant: Tenant
) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant, previous_signing_secret="older-older-older-0002")
    response = await _post(api, integration, _payload(name), secret="older-older-older-0002")
    assert response.status_code == 202


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/a.mp3",  # not https
        "https://127.0.0.1/a.mp3",  # loopback
        "https://10.0.0.5/a.mp3",  # private
        "https://169.254.169.254/latest/meta-data",  # link-local metadata service
        "https://user:pw@8.8.8.8/a.mp3",  # credentials in the URL
    ],
)
async def test_unsafe_recording_urls_are_refused(
    api: AsyncClient, tenant: Tenant, database_url: str, url: str
) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    response = await _post(api, integration, _payload(name, recording_url=url))
    assert response.status_code == 422 and response.json()["error"]["code"] == "unsafe_url"
    rows = await fetch_rows(
        database_url, "SELECT 1 FROM external_refs WHERE integration_id = %s", integration
    )
    assert rows == []


async def test_dev_switch_allows_a_private_recording_host(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", "1")
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    response = await _post(
        api, integration, _payload(name, recording_url="https://127.0.0.1/a.wav")
    )
    assert response.status_code == 202


async def test_invalid_language_is_400(api: AsyncClient, tenant: Tenant) -> None:
    name = await _agent_name(api, tenant)
    integration = await _source(api, tenant)
    response = await _post(api, integration, _payload(name, language="not a language"))
    assert response.status_code == 400


async def test_unknown_disabled_and_sink_only_integrations_are_404(
    api: AsyncClient, tenant: Tenant
) -> None:
    name = await _agent_name(api, tenant)
    assert (await _post(api, str(uuid.uuid4()), _payload(name))).status_code == 404
    integration = await _source(api, tenant)
    patched = await api.patch(
        f"/api/v1/integrations/{integration}", json={"enabled": False}, headers=tenant.admin
    )
    assert patched.status_code == 200
    assert (await _post(api, integration, _payload(name))).status_code == 404
    hubspot = await api.post(
        "/api/v1/integrations",
        json={
            "connector": "hubspot",
            "name": "crm",
            "config": {"match_by": "phone"},
            "secrets": {"private_app_token": "pat-token-0000"},
        },
        headers=tenant.admin,
    )
    assert (await _post(api, hubspot.json()["id"], _payload(name))).status_code == 404
