"""``read_spec`` for a prompt agent: the run's pinned version and the decrypted secrets."""

from __future__ import annotations

import json
import uuid

import psycopg
from cryptography.fernet import Fernet
from httpx import AsyncClient
from pytest import MonkeyPatch

from pareeksha.events.schemas import CallRequested
from pareeksha.events.settings import libpq_url
from pareeksha.integrations.crypto import SecretBox
from pareeksha.simulation import store
from tests.conftest import Tenant
from tests.integration.runs_support import API, make_fixture, plan_in_db


async def test_read_spec_loads_pinned_version_and_secrets(
    api: AsyncClient, tenant: Tenant, database_url: str, monkeypatch: MonkeyPatch
) -> None:
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SECRET_KEY", key)
    fx = await make_fixture(api, tenant, 1, 1, 1)
    created = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    req = next(
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    )
    pinned, newer = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as conn:
        cur = await conn.execute("SELECT project_id FROM agents WHERE id = %s", (fx.agent_id,))
        row = await cur.fetchone()
        assert row is not None
        project_id = row[0]
        for vid, n in ((pinned, 1), (newer, 2)):
            await conn.execute(
                "INSERT INTO prompt_versions (id, project_id, agent_id, version, system_prompt, "
                "provider, model, temperature, tools, content_hash) "
                "VALUES (%s, %s, %s, %s, %s, 'openai', 'gpt-x', 0.2, '[]', %s)",
                (vid, project_id, fx.agent_id, n, f"prompt v{n}", f"h{n}"),
            )
        await conn.execute(
            "UPDATE agents SET adapter = 'prompt', adapter_secrets_encrypted = %s, "
            "adapter_config = %s WHERE id = %s",
            (
                SecretBox(key).encrypt({"api_key": "sk-test"}).encode(),
                json.dumps({"active_version_id": str(newer)}),
                fx.agent_id,
            ),
        )
        await conn.execute(
            "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
            (json.dumps({"adapter_config": {"active_version_id": str(pinned)}}), run_id),
        )
        spec, _ = await store.read_spec(conn, req)

    assert spec.agent.adapter_config["prompt_version"]["id"] == str(pinned)
    assert spec.agent.adapter_config["prompt_version"]["system_prompt"] == "prompt v1"
    assert spec.agent.adapter_secrets == {"api_key": "sk-test"}
