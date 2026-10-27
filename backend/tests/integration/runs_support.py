"""Fixtures for the run tests: an agent, scenarios, personas and noise profiles via the API.

Everything goes through the real app and the Alembic-migrated Postgres of ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg
from httpx import AsyncClient

from pareeksha.events.consumer import Ctx, Outgoing
from pareeksha.events.schemas import RunRequested, parse_envelope
from pareeksha.events.settings import EventSettings, libpq_url
from pareeksha.events.topics import Topics
from pareeksha.workers.planner import plan
from tests.conftest import Tenant
from tests.integration.support import BOOTSTRAP

API = "/api/v1"


def settings_for(database_url: str) -> EventSettings:
    """Workers pointed at the migrated test database and the test broker."""
    return EventSettings(bootstrap_servers=BOOTSTRAP, database_url=libpq_url(database_url))


@dataclass
class Fixture:
    """The ids a run is built from."""

    agent_id: str
    scenario_ids: list[str] = field(default_factory=list)
    persona_ids: list[str] = field(default_factory=list)
    noise_profile_ids: list[str] = field(default_factory=list)

    def body(self, **overrides: Any) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": "baseline",
            "scenario_ids": self.scenario_ids,
            "persona_ids": self.persona_ids,
            "noise_profile_ids": self.noise_profile_ids,
            **overrides,
        }


async def _post(api: AsyncClient, tenant: Tenant, path: str, body: dict[str, Any]) -> str:
    response = await api.post(f"{API}{path}", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def make_fixture(
    api: AsyncClient,
    tenant: Tenant,
    scenarios: int = 2,
    personas: int = 2,
    profiles: int = 2,
    *,
    max_turns: int = 10,
) -> Fixture:
    tag = uuid.uuid4().hex[:6]
    fx = Fixture(
        agent_id=await _post(
            api,
            tenant,
            "/agents",
            {"name": f"EMI bot {tag}", "endpoint_url": "ws://mock-agent:8765/ws"},
        )
    )
    for i in range(scenarios):
        fx.scenario_ids.append(
            await _post(
                api,
                tenant,
                "/scenarios",
                {
                    "title": f"Scenario {i} {tag}",
                    "caller_goal": "Say you already paid.",
                    "success_criteria": "Agent accepts the UTR.",
                    "max_turns": max_turns,
                    "agent_id": fx.agent_id,
                },
            )
        )
    for i in range(personas):
        fx.persona_ids.append(
            await _post(
                api,
                tenant,
                "/personas",
                {
                    "name": f"Persona {i} {tag}",
                    "language": "kn-IN",
                    "code_mix_style": "heavy",
                    "tts_model": "timbre-v3.0",
                    "voice_id": "Prakash",
                },
            )
        )
    for i in range(profiles):
        fx.noise_profile_ids.append(
            await _post(
                api,
                tenant,
                "/noise-profiles",
                {
                    "name": f"profile_{i}_{tag}",
                    "sample_rate": 8000,
                    "codec": "alaw",
                    "pstn_bandpass": True,
                    "background_category": "market_crowd",
                    "snr_db": 5,
                },
            )
        )
    return fx


async def plan_in_db(database_url: str, run_id: str) -> list[Outgoing]:
    """Run the planner's handler on the run's own ``run.requested`` outbox row (no Kafka)."""
    url = libpq_url(database_url)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        cur = await conn.execute(
            "SELECT envelope FROM outbox_events WHERE topic = %s AND key = %s",
            (Topics.RUN_REQUESTED.value, run_id),
        )
        row = await cur.fetchone()
        assert row is not None, "no run.requested outbox row"
        env = parse_envelope(row[0])
        assert isinstance(env.payload, RunRequested)
        async with conn.transaction():
            ctx = Ctx(
                tx=conn,
                group="planner",
                topic=Topics.RUN_REQUESTED.value,
                partition=0,
                offset=0,
                attempt=1,
            )
            return await plan(env, ctx)  # type: ignore[arg-type]
