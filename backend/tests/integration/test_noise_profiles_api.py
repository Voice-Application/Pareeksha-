"""Noise profiles CRUD and preview (FR-NP-1, FR-NP-2) against the real app and Postgres."""

from __future__ import annotations

import io
import uuid
import wave
from typing import Any

import numpy as np
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.audio import preview
from pareeksha.db import models
from tests.conftest import Tenant

PROFILE: dict[str, Any] = {
    "name": "pstn_market_5db",
    "sample_rate": 8000,
    "codec": "alaw",
    "pstn_bandpass": True,
    "background_category": "market_crowd",
    "snr_db": 5,
    "packet_loss_pct": 1.5,
    "clipping": False,
    "description": "Vegetable market",
}


def _wav(samples: np.ndarray, rate: int = 16000, width: int = 2, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _read(data: bytes) -> tuple[int, np.ndarray]:
    with wave.open(io.BytesIO(data)) as w:
        raw = w.readframes(w.getnframes())
        return w.getframerate(), np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768


async def _profile(api: AsyncClient, tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/noise-profiles", json={**PROFILE, **overrides}, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_get_round_trip(api: AsyncClient, tenant: Tenant) -> None:
    created = await _profile(api, tenant)
    fetched = (await api.get(f"/api/v1/noise-profiles/{created['id']}", headers=tenant.read)).json()
    assert fetched == created
    for field, value in PROFILE.items():
        assert fetched[field] == value, field


async def test_unknown_background_category_is_400(api: AsyncClient, tenant: Tenant) -> None:
    response = await api.post(
        "/api/v1/noise-profiles",
        json={**PROFILE, "background_category": "thunderstorm"},
        headers=tenant.admin,
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["background_category"] == "thunderstorm"


async def test_snr_is_required_with_a_background(api: AsyncClient, tenant: Tenant) -> None:
    body = {k: v for k, v in PROFILE.items() if k != "snr_db"}
    assert (
        await api.post("/api/v1/noise-profiles", json=body, headers=tenant.admin)
    ).status_code == 400


async def test_patch_list_duplicates_and_database_check(api: AsyncClient, tenant: Tenant) -> None:
    created = await _profile(api, tenant)
    other = await _profile(api, tenant, name="other")
    url = f"/api/v1/noise-profiles/{created['id']}"
    patched = await api.patch(
        url, json={"snr_db": 10, "clipping": True, "codec": None}, headers=tenant.admin
    )
    assert patched.status_code == 200
    assert patched.json()["snr_db"] == 10 and patched.json()["clipping"] is True
    assert patched.json()["codec"] == "alaw"  # null never blanks a required column

    cleared = await api.patch(
        url, json={"background_category": None, "snr_db": None}, headers=tenant.admin
    )
    assert cleared.json()["background_category"] is None and cleared.json()["snr_db"] is None
    # background without an SNR violates the table CHECK: reported as a 400, not a 500
    invalid = await api.patch(
        url, json={"background_category": "bus_interior"}, headers=tenant.admin
    )
    assert invalid.status_code == 400
    bad_category = await api.patch(url, json={"background_category": "nope"}, headers=tenant.admin)
    assert bad_category.status_code == 400

    listed = (await api.get("/api/v1/noise-profiles", headers=tenant.read)).json()["items"]
    assert {p["id"] for p in listed} == {created["id"], other["id"]}
    dup = await api.post("/api/v1/noise-profiles", json=PROFILE, headers=tenant.admin)
    assert dup.status_code == 409
    clash = await api.patch(
        f"/api/v1/noise-profiles/{other['id']}",
        json={"name": PROFILE["name"]},
        headers=tenant.admin,
    )
    assert clash.status_code == 409


async def test_scopes_isolation_and_not_found(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    assert (
        await api.post("/api/v1/noise-profiles", json=PROFILE, headers=tenant.read)
    ).status_code == 403
    created = await _profile(api, tenant)
    url = f"/api/v1/noise-profiles/{created['id']}"
    assert (await api.get(url, headers=other_tenant.read)).status_code == 404
    assert (await api.delete(url, headers=other_tenant.admin)).status_code == 404
    ghost = f"/api/v1/noise-profiles/{uuid.uuid4()}"
    assert (await api.get(ghost, headers=tenant.read)).status_code == 404
    assert (await api.patch(ghost, json={}, headers=tenant.admin)).status_code == 404
    assert (await api.post(f"{ghost}/preview", headers=tenant.read)).status_code == 404


async def test_delete_and_409_when_referenced_by_a_run(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    free = await _profile(api, tenant, name="free")
    used = await _profile(api, tenant, name="used")
    agent = (
        await api.post(
            "/api/v1/agents", json={"name": "a", "endpoint_url": "ws://x"}, headers=tenant.admin
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
        persona = models.Personas(
            project_id=tenant.project_id, name="p", language="kn-IN", voice_id="v"
        )
        run = models.TestRuns(project_id=tenant.project_id, agent_id=uuid.UUID(agent["id"]))
        session.add_all([persona, run])
        await session.flush()
        session.add(
            models.RunItems(
                run_id=run.id,
                scenario_id=uuid.UUID(scenario["id"]),
                persona_id=persona.id,
                noise_profile_id=uuid.UUID(used["id"]),
                seed=1,
            )
        )
        await session.commit()
    assert (
        await api.delete(f"/api/v1/noise-profiles/{free['id']}", headers=tenant.admin)
    ).status_code == 204
    refused = await api.delete(f"/api/v1/noise-profiles/{used['id']}", headers=tenant.admin)
    assert refused.status_code == 409


async def test_preview_degrades_the_builtin_sample(api: AsyncClient, tenant: Tenant) -> None:
    created = await _profile(api, tenant)
    response = await api.post(
        f"/api/v1/noise-profiles/{created['id']}/preview", headers=tenant.read
    )
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    rate, degraded = _read(response.content)
    original = preview.builtin_sample()
    assert rate == 16000 and len(degraded) == len(original)
    assert not np.allclose(degraded, original, atol=1e-3)  # the line changed the audio
    # a clean profile leaves the sample (almost) alone
    clean = await _profile(
        api,
        tenant,
        name="clean",
        sample_rate=16000,
        codec="none",
        pstn_bandpass=False,
        background_category=None,
        snr_db=None,
        packet_loss_pct=0,
    )
    _, same = _read(
        (
            await api.post(f"/api/v1/noise-profiles/{clean['id']}/preview", headers=tenant.read)
        ).content
    )
    assert np.allclose(same, original, atol=1e-3)


async def test_preview_degrades_an_uploaded_clip_and_is_deterministic(
    api: AsyncClient, tenant: Tenant
) -> None:
    created = await _profile(api, tenant)
    url = f"/api/v1/noise-profiles/{created['id']}/preview"
    clip = _wav(preview.builtin_sample(2.0, seed=7), rate=16000)
    files = {"file": ("clip.wav", clip, "audio/wav")}
    first = await api.post(url, files=files, headers=tenant.read)
    second = await api.post(url, files=files, headers=tenant.read)
    assert first.status_code == 200 and first.content == second.content
    rate, audio = _read(first.content)
    assert rate == 16000 and abs(len(audio) - 2 * 16000) <= 1

    # other sample rates and stereo are accepted and resampled to 16 kHz mono
    stereo_8k = _wav(np.stack([np.zeros(8000), np.zeros(8000)], axis=1).ravel(), 8000, channels=2)
    resampled = await api.post(
        url, files={"file": ("c.wav", stereo_8k, "audio/wav")}, headers=tenant.read
    )
    assert resampled.status_code == 200


async def test_preview_rejects_bad_uploads(
    api: AsyncClient, tenant: Tenant, monkeypatch: Any
) -> None:
    created = await _profile(api, tenant)
    url = f"/api/v1/noise-profiles/{created['id']}/preview"

    async def post(content: bytes) -> Any:
        return await api.post(
            url, files={"file": ("c.wav", content, "audio/wav")}, headers=tenant.read
        )

    for bad in (b"not a wav", b"", _wav(np.zeros(0))):
        response = await post(bad)
        assert response.status_code == 422, bad[:8]
        assert response.json()["error"]["code"] == "unsupported_audio"
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:  # 8-bit PCM is not supported
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(16000)
        w.writeframes(bytes(1600))
    assert (await post(buf.getvalue())).status_code == 422

    monkeypatch.setattr(preview, "MAX_CLIP_SECONDS", 0.5)
    too_long = await post(_wav(np.zeros(16000)))
    assert too_long.status_code == 422 and "longer" in too_long.json()["error"]["message"]

    monkeypatch.setattr(preview, "MAX_UPLOAD_BYTES", 1000)
    big = await post(_wav(np.zeros(2000)))
    assert big.status_code == 413 and big.json()["error"]["code"] == "file_too_large"
