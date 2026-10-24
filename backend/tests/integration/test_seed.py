"""The seed script on an empty, migrated Postgres: contents, idempotence, demo key (FR-PE-2)."""

from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.auth import hash_api_key
from pareeksha.api.main import app
from pareeksha.audio.profiles import BUILTIN_PROFILES
from pareeksha.db.models import (
    Agents,
    ApiKeys,
    NoiseProfiles,
    Personas,
    Projects,
    RubricVersions,
    Scenarios,
)
from pareeksha.db.session import get_session_factory
from pareeksha.seed.runner import (
    NOISE_DESCRIPTIONS,
    PROJECT_NAME,
    SeedResult,
    rubric_prompt_hash,
    seed_database,
)
from tests.conftest import BACKEND, bearer

Factory = async_sessionmaker[AsyncSession]


@pytest.fixture(autouse=True)
def _no_pinned_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAREEKSHA_API_KEY", raising=False)


async def _count(factory: Factory, model: type) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_20_personas_and_idempotent(fresh_session_factory: Factory) -> None:
    first = await seed_database(fresh_session_factory)
    assert first.created["personas"] == 20 and not first.existing.get("personas")
    second = await seed_database(fresh_session_factory)
    assert second.created == {} and second.existing["personas"] == 20
    assert second.demo_key is None  # the key is only ever shown by the run that made it
    assert await _count(fresh_session_factory, Personas) == 20
    assert await _count(fresh_session_factory, Projects) == 1

    async with fresh_session_factory() as session:
        personas = list(await session.scalars(select(Personas)))
    by_language = collections.Counter(p.language for p in personas)
    assert by_language["kn-IN"] >= 6 and by_language["hi-IN"] >= 6 and by_language["en-IN"] >= 4
    assert all(p.is_seed for p in personas)
    assert all(p.tts_model == "timbre-v3.0" for p in personas)
    voices = collections.Counter((p.language, p.voice_id) for p in personas)
    assert max(voices.values()) == 1  # no two personas of a language share a voice
    code_mix = {p.name: p.code_mix_style for p in personas}
    assert code_mix["Manju — auto driver"] == "heavy" and code_mix["Priya — careful"] == "none"
    silent = next(p for p in personas if p.name == "The Silent One")
    assert silent.patience_turns == 3 and silent.silence_habit == "goes_silent"


async def test_noise_profiles_are_the_eight_dsp_definitions(fresh_session_factory: Factory) -> None:
    await seed_database(fresh_session_factory)
    async with fresh_session_factory() as session:
        rows = {p.name: p for p in await session.scalars(select(NoiseProfiles))}
    assert set(rows) == set(BUILTIN_PROFILES) and len(rows) == 8
    assert set(NOISE_DESCRIPTIONS) == set(BUILTIN_PROFILES)
    for name, line in BUILTIN_PROFILES.items():
        row = rows[name]
        assert row.sample_rate == line.sample_rate and row.codec == line.codec
        assert row.pstn_bandpass == line.pstn_bandpass and row.clipping == line.clipping
        assert row.background_category == line.background
        assert (None if row.snr_db is None else float(row.snr_db)) == line.snr_db
        assert float(row.packet_loss_pct) == line.packet_loss_pct
        assert row.description == NOISE_DESCRIPTIONS[name]
    assert rows["mobile_bus_5db"].background_category == "bus_interior"
    assert (
        float(rows["mobile_weak_signal"].packet_loss_pct) == 5
        and rows["mobile_weak_signal"].clipping
    )


async def test_rubric_v1_is_active_and_weights_sum_to_100(fresh_session_factory: Factory) -> None:
    await seed_database(fresh_session_factory)
    async with fresh_session_factory() as session:
        rubric = (await session.scalars(select(RubricVersions))).one()
    assert rubric.version == "rubric-2026-10-v1" and rubric.is_active
    assert float(rubric.pass_threshold) == 80
    dims = rubric.dimensions
    assert isinstance(dims, list)
    assert [d["key"] for d in dims] == [
        "task_completion",
        "policy_compliance",
        "factual_accuracy",
        "language_handling",
        "conversation_flow",
        "empathy_tone",
        "escalation",
    ]
    assert sum(d["weight"] for d in dims) == 100
    assert all(set(d["anchors"]) >= {"4", "2", "1"} for d in dims)
    assert rubric.prompt_hash == rubric_prompt_hash(rubric.version, 80, dims)
    assert rubric.prompt_hash != rubric_prompt_hash(rubric.version, 70, dims)


async def test_an_existing_active_rubric_is_not_replaced(fresh_session_factory: Factory) -> None:
    async with fresh_session_factory() as session, session.begin():
        session.add(
            RubricVersions(version="custom", dimensions=[], prompt_hash="x", is_active=True)
        )
    await seed_database(fresh_session_factory)
    async with fresh_session_factory() as session:
        active = list(
            await session.scalars(select(RubricVersions.version).where(RubricVersions.is_active))
        )
    assert active == ["custom"]
    assert await _count(fresh_session_factory, RubricVersions) == 2


async def test_mock_agent_and_scenarios(fresh_session_factory: Factory) -> None:
    result = await seed_database(fresh_session_factory)
    assert result.created["agents"] == 1 and result.created["scenarios"] == 8
    async with fresh_session_factory() as session:
        agent = (await session.scalars(select(Agents))).one()
        scenarios = list(await session.scalars(select(Scenarios)))
    assert agent.name == "EMI Reminder Bot" and agent.adapter == "audio_v1"
    assert agent.endpoint_url == "ws://mock-agent:8765/ws" and agent.glass_box
    assert agent.languages == ["kn-IN", "hi-IN", "en-IN"]
    assert {s.agent_id for s in scenarios} == {agent.id}
    assert len({s.title for s in scenarios}) == 8
    tags = {t for s in scenarios for t in s.tags}
    assert {"happy_path", "edge_case", "adversarial"} <= tags
    # a user's edit to a seeded row survives re-seeding
    async with fresh_session_factory() as session, session.begin():
        await session.execute(update(Scenarios).values(max_turns=7))
        await session.execute(update(Personas).values(speed=1.5))
    again = await seed_database(fresh_session_factory)
    assert again.created == {}
    async with fresh_session_factory() as session:
        assert set(await session.scalars(select(Scenarios.max_turns))) == {7}


async def test_demo_key_is_created_once_and_authenticates(
    fresh_session_factory: Factory,
) -> None:
    first = await seed_database(fresh_session_factory)
    assert first.demo_key is not None and first.demo_key.startswith("pk_live_")
    async with fresh_session_factory() as session:
        row = (await session.scalars(select(ApiKeys))).one()
    assert row.name == "demo" and row.scopes == ["admin"]
    assert row.key_hash == hash_api_key(first.demo_key) and str(row.project_id) == first.project_id

    app.dependency_overrides[get_session_factory] = lambda: fresh_session_factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            headers = bearer(first.demo_key)
            personas = await api.get("/api/v1/personas?limit=200", headers=headers)
            assert personas.status_code == 200 and len(personas.json()["items"]) == 20
            profiles = await api.get("/api/v1/noise-profiles", headers=headers)
            assert len(profiles.json()["items"]) == 8
            assert (await api.get("/api/v1/api-keys", headers=headers)).status_code == 200
    finally:
        app.dependency_overrides.pop(get_session_factory, None)

    second = await seed_database(fresh_session_factory)
    assert second.demo_key is None and await _count(fresh_session_factory, ApiKeys) == 1


async def test_a_revoked_demo_key_is_replaced(fresh_session_factory: Factory) -> None:
    await seed_database(fresh_session_factory)
    async with fresh_session_factory() as session, session.begin():
        await session.execute(update(ApiKeys).values(revoked_at=func.now()))
    again = await seed_database(fresh_session_factory)
    assert again.demo_key is not None and await _count(fresh_session_factory, ApiKeys) == 2


async def test_pinned_demo_key_from_the_environment(
    fresh_session_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = "pk_live_pinned-demo-key-for-tests-0123456789"
    monkeypatch.setenv("PAREEKSHA_API_KEY", pinned)
    first = await seed_database(fresh_session_factory)
    assert first.demo_key is None and first.created["api_keys"] == 1  # the caller already has it
    async with fresh_session_factory() as session:
        row = (await session.scalars(select(ApiKeys))).one()
    assert row.key_hash == hash_api_key(pinned) and row.prefix == pinned[:16]
    again = await seed_database(fresh_session_factory)
    assert again.existing["api_keys"] == 1 and await _count(fresh_session_factory, ApiKeys) == 1

    monkeypatch.setenv("PAREEKSHA_API_KEY", "not-a-key")
    with pytest.raises(ValueError, match="pk_live_"):
        await seed_database(fresh_session_factory)


async def test_a_second_project_is_not_created(fresh_session_factory: Factory) -> None:
    await seed_database(fresh_session_factory)
    await seed_database(fresh_session_factory)
    async with fresh_session_factory() as session:
        names = list(await session.scalars(select(Projects.name)))
    assert names == [PROJECT_NAME]


def test_seed_module_runs_from_the_command_line(database_url: str) -> None:
    """`python -m pareeksha.seed` against a migrated database prints the summary and the key."""
    import os

    env = {k: v for k, v in os.environ.items() if k != "PAREEKSHA_API_KEY"}
    env.update(DATABASE_URL=database_url, PYTHONPATH=str(BACKEND))

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pareeksha.seed"],
            cwd=Path(BACKEND),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    first = run().stdout
    summary = json.loads(first[: first.rindex("}") + 1])
    assert "created" in summary and "existing" in summary
    assert "Demo API key" in first or summary["existing"].get("api_keys")
    second = run().stdout
    assert json.loads(second)["created"] == {} and "Demo API key" not in second


async def test_main_seeds_the_database_named_by_database_url(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pareeksha.seed.__main__ import _run

    monkeypatch.setenv("DATABASE_URL", database_url)
    assert await _run() == 0
    out = capsys.readouterr().out
    assert '"created"' in out and '"existing"' in out


def test_seed_result_counts() -> None:
    result = SeedResult()
    result.count("x", True)
    result.count("x", False)
    assert result.created == {"x": 1} and result.existing == {"x": 1}
