"""/settings/llm against the real app and real Postgres (encrypted key, tenant scope, resolver)."""

from __future__ import annotations

import os
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.integrations.crypto import SecretBox
from pareeksha.llm.project_settings import effective_llm_settings
from tests.conftest import Tenant

KEY = "sk-live-abcdef123456"


@pytest.fixture(autouse=True)
def _secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())


async def _put(api: AsyncClient, tenant: Tenant, **body: Any) -> Any:
    return await api.put("/api/v1/settings/llm", json=body, headers=tenant.admin)


async def test_environment_until_a_row_exists(api: AsyncClient, tenant: Tenant) -> None:
    body = (await api.get("/api/v1/settings/llm", headers=tenant.read)).json()
    assert body["source"] == "environment"


async def test_put_get_delete_round_trip_and_the_key_is_encrypted_at_rest(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    put = await _put(api, tenant, provider="deepseek", judge_model="my-judge", api_key=KEY)
    assert put.status_code == 200, put.text
    assert put.json()["api_key_last4"] == "3456" and KEY not in put.text
    got = await api.get("/api/v1/settings/llm", headers=tenant.read)
    assert got.json() == put.json() and KEY not in got.text

    async with session_factory() as session:
        stored = (
            await session.execute(
                text(
                    "SELECT api_key_encrypted, updated_at FROM llm_settings WHERE project_id = :p"
                ),
                {"p": tenant.project_id},
            )
        ).one()
        assert KEY not in stored.api_key_encrypted
        assert SecretBox(os.environ["SECRET_KEY"]).decrypt(stored.api_key_encrypted) == {
            "api_key": KEY
        }
        effective = await effective_llm_settings(session, tenant.project_id)
        assert effective.api_key == KEY and effective.judge_model == "my-judge"

    # a second PUT without a key keeps it and moves updated_at (the workers' cache fingerprint)
    again = await _put(api, tenant, provider="deepseek", caller_model="c2")
    assert again.json()["api_key_last4"] == "3456"
    async with session_factory() as session:
        later = (
            await session.execute(
                text("SELECT updated_at FROM llm_settings WHERE project_id = :p"),
                {"p": tenant.project_id},
            )
        ).scalar_one()
        assert later > stored.updated_at

    assert (await api.delete("/api/v1/settings/llm", headers=tenant.admin)).status_code == 204
    shown = (await api.get("/api/v1/settings/llm", headers=tenant.read)).json()
    assert shown["source"] == "environment"


async def test_settings_are_per_project(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    await _put(api, tenant, provider="deepseek", api_key=KEY)
    other = (await api.get("/api/v1/settings/llm", headers=other_tenant.read)).json()
    assert other["source"] == "environment" and other["api_key_last4"] is None


async def test_scopes_and_validation(api: AsyncClient, tenant: Tenant) -> None:
    denied = await api.put(
        "/api/v1/settings/llm",
        json={"provider": "deepseek", "api_key": KEY},
        headers=tenant.read,
    )
    assert denied.status_code == 403
    assert (await api.delete("/api/v1/settings/llm", headers=tenant.read)).status_code == 403
    assert (await api.post("/api/v1/settings/llm/test", headers=tenant.read)).status_code == 403
    private = await _put(
        api,
        tenant,
        provider="openai_compatible",
        base_url="https://10.0.0.5/v1",
        judge_model="j",
        caller_model="c",
        api_key=KEY,
    )
    assert private.status_code == 422 and private.json()["error"]["code"] == "unsafe_url"
