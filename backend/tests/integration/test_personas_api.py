"""Personas CRUD and preview (FR-PE-1, FR-PE-3) against the real app and Postgres.

The preview route is tested with a recording synthesizer injected through the
``get_synthesizer`` dependency; the live Gnani call is captured in ``proof/API-02``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.main import app
from pareeksha.api.speech import GnaniSynthesizer, get_synthesizer
from pareeksha.db import models
from tests.conftest import Tenant

PERSONA: dict[str, Any] = {
    "name": "Manju — frustrated Kanglish auto driver",
    "language": "kn-IN",
    "code_mix_style": "heavy",
    "dialect_label": "Bengaluru urban (synthetic)",
    "tts_model": "timbre-v3.0",
    "voice_id": "Prakash",
    "speed": 1.1,
    "emotion": "frustrated",
    "patience_turns": 6,
    "interruption_level": 2,
    "silence_habit": "normal",
    "behaviour_notes": "Short sentences.",
}


class RecordingSynthesizer:
    def __init__(self, audio: bytes = b"RIFFfakewav", fail: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.audio = audio
        self.fail = fail

    def synthesize_wav(
        self, text: str, voice: str, language: str, *, speed: float, model: str
    ) -> bytes:
        self.calls.append(
            {"text": text, "voice": voice, "language": language, "speed": speed, "model": model}
        )
        if self.fail:
            raise self.fail
        return self.audio


@pytest.fixture
def synthesizer() -> Iterator[RecordingSynthesizer]:
    fake = RecordingSynthesizer()
    app.dependency_overrides[get_synthesizer] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_synthesizer, None)


async def _persona(api: AsyncClient, tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/personas", json={**PERSONA, **overrides}, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_get_round_trip(api: AsyncClient, tenant: Tenant) -> None:
    created = await _persona(api, tenant)
    assert created["is_seed"] is False and created["speed"] == 1.1
    fetched = (await api.get(f"/api/v1/personas/{created['id']}", headers=tenant.read)).json()
    assert fetched == created
    for field, value in PERSONA.items():
        assert fetched[field] == value, field


async def test_defaults_apply(api: AsyncClient, tenant: Tenant) -> None:
    minimal = {"name": "Min", "language": "hi-IN", "voice_id": "Shivani"}
    response = await api.post("/api/v1/personas", json=minimal, headers=tenant.admin)
    body = response.json()
    assert body["code_mix_style"] == "none" and body["speed"] == 1.0
    assert body["tts_model"] == "timbre-v3.0" and body["patience_turns"] == 8


async def test_patch_list_filter_and_duplicate(api: AsyncClient, tenant: Tenant) -> None:
    kn = await _persona(api, tenant)
    hi = await _persona(api, tenant, name="Rohit", language="hi-IN", voice_id="Shubham")
    patched = await api.patch(
        f"/api/v1/personas/{kn['id']}",
        json={"speed": 0.9, "emotion": "angry", "behaviour_notes": None},
        headers=tenant.admin,
    )
    assert patched.status_code == 200
    assert patched.json()["speed"] == 0.9 and patched.json()["emotion"] == "angry"
    assert patched.json()["behaviour_notes"] == PERSONA["behaviour_notes"]

    everyone = (await api.get("/api/v1/personas", headers=tenant.read)).json()["items"]
    assert {p["id"] for p in everyone} == {kn["id"], hi["id"]}
    only_hi = (await api.get("/api/v1/personas?language=hi-IN", headers=tenant.read)).json()
    assert [p["id"] for p in only_hi["items"]] == [hi["id"]]

    dup = await api.post("/api/v1/personas", json=PERSONA, headers=tenant.admin)
    assert dup.status_code == 409
    clash = await api.patch(
        f"/api/v1/personas/{hi['id']}", json={"name": PERSONA["name"]}, headers=tenant.admin
    )
    assert clash.status_code == 409


async def test_validation_and_scopes_and_isolation(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    bad = await api.post("/api/v1/personas", json={**PERSONA, "speed": 5}, headers=tenant.admin)
    assert bad.status_code == 400
    assert (
        await api.post("/api/v1/personas", json=PERSONA, headers=tenant.read)
    ).status_code == 403
    created = await _persona(api, tenant)
    url = f"/api/v1/personas/{created['id']}"
    assert (await api.get(url, headers=other_tenant.read)).status_code == 404
    assert (await api.delete(url, headers=other_tenant.admin)).status_code == 404
    ghost = f"/api/v1/personas/{uuid.uuid4()}"
    assert (await api.get(ghost, headers=tenant.read)).status_code == 404
    assert (await api.patch(ghost, json={}, headers=tenant.admin)).status_code == 404


async def test_delete_and_409_when_referenced_by_a_run(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    free = await _persona(api, tenant, name="free")
    used = await _persona(api, tenant, name="used")
    agent = (
        await api.post(
            "/api/v1/agents",
            json={"name": "a", "endpoint_url": "ws://x"},
            headers=tenant.admin,
        )
    ).json()
    scenario = (
        await api.post(
            "/api/v1/scenarios",
            json={"title": "t", "caller_goal": "g", "success_criteria": "s"},
            headers=tenant.admin,
        )
    ).json()
    async with session_factory() as session:
        noise = models.NoiseProfiles(project_id=tenant.project_id, name="n")
        run = models.TestRuns(project_id=tenant.project_id, agent_id=uuid.UUID(agent["id"]))
        session.add_all([noise, run])
        await session.flush()
        session.add(
            models.RunItems(
                run_id=run.id,
                scenario_id=uuid.UUID(scenario["id"]),
                persona_id=uuid.UUID(used["id"]),
                noise_profile_id=noise.id,
                seed=1,
            )
        )
        await session.commit()
    assert (
        await api.delete(f"/api/v1/personas/{free['id']}", headers=tenant.admin)
    ).status_code == 204
    refused = await api.delete(f"/api/v1/personas/{used['id']}", headers=tenant.admin)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "conflict"


async def test_preview_synthesises_one_line_in_the_persona_voice(
    api: AsyncClient, tenant: Tenant, synthesizer: RecordingSynthesizer
) -> None:
    created = await _persona(api, tenant)
    response = await api.post(f"/api/v1/personas/{created['id']}/preview", headers=tenant.read)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav" and response.content == b"RIFFfakewav"
    (call,) = synthesizer.calls
    assert call["voice"] == "Prakash" and call["language"] == "kn-IN"
    assert call["speed"] == 1.1 and call["model"] == "timbre-v3.0"
    assert any("ಀ" <= ch <= "೿" for ch in call["text"])  # a Kannada sample line

    hindi = await _persona(api, tenant, name="hi", language="hi-IN")
    await api.post(f"/api/v1/personas/{hindi['id']}/preview", headers=tenant.read)
    assert any("ऀ" <= ch <= "ॿ" for ch in synthesizer.calls[-1]["text"])
    tamil = await _persona(api, tenant, name="ta", language="ta-IN")
    await api.post(f"/api/v1/personas/{tamil['id']}/preview", headers=tenant.read)
    assert synthesizer.calls[-1]["text"].startswith("Hello")  # other languages use English


async def test_preview_404_and_upstream_failure_is_502(
    api: AsyncClient, tenant: Tenant, synthesizer: RecordingSynthesizer
) -> None:
    missing = await api.post(f"/api/v1/personas/{uuid.uuid4()}/preview", headers=tenant.read)
    assert missing.status_code == 404
    created = await _persona(api, tenant)
    synthesizer.fail = RuntimeError("503 from upstream")
    failed = await api.post(f"/api/v1/personas/{created['id']}/preview", headers=tenant.read)
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "upstream_error"
    assert "503 from upstream" in failed.json()["error"]["message"]


async def test_preview_without_a_gnani_key_is_502(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GNANI_API_KEY", raising=False)
    created = await _persona(api, tenant)
    response = await api.post(f"/api/v1/personas/{created['id']}/preview", headers=tenant.read)
    assert response.status_code == 502
    assert "GNANI_API_KEY" in response.json()["error"]["message"]


def test_default_synthesizer_reads_key_and_cache_dir_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("GNANI_API_KEY", "k")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    synth = get_synthesizer()
    assert isinstance(synth, GnaniSynthesizer)
    assert synth._api_key == "k" and synth._cache_dir == tmp_path / "tts_cache"
    monkeypatch.delenv("DATA_DIR")
    assert isinstance(get_synthesizer(), GnaniSynthesizer)
