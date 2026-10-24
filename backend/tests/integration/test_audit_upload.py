"""FR-AU-1: WAV/MP3 up to 10 MB is stored (source=upload); bigger or invalid files are refused."""

from __future__ import annotations

import io
import uuid

import numpy as np
import soundfile as sf
from httpx import AsyncClient

from pareeksha.audit.ingest import MAX_UPLOAD_BYTES
from pareeksha.events.schemas import AuditRequested
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant
from tests.integration.audit_support import (
    audit_envelope,
    create_agent,
    fetch_rows,
    outbox_envelopes,
    tone_wav,
    upload,
)


async def test_wav_upload_is_stored_and_queued(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    agent_id = await create_agent(api, tenant)
    audio = tone_wav(2.0)
    response = await upload(api, tenant, agent_id, audio=audio, language="kn-IN, en-IN")
    assert response.status_code == 202, response.text
    call_id = response.json()["call_id"]

    (call,) = await fetch_rows(database_url, "SELECT * FROM calls WHERE id = %s", call_id)
    assert call["source"] == "upload" and call["status"] == "transcribing"
    assert str(call["project_id"]) == str(tenant.project_id) and str(call["agent_id"]) == agent_id
    assert call["language"] == "kn-IN,en-IN"
    assert call["recording_original"] == f"uploads/{call_id}/original.wav"
    assert await blobs.get(call["recording_original"]) == audio
    assert call["metadata"]["filename"] == "call.wav" and call["metadata"]["size_bytes"] == len(
        audio
    )

    env = await audit_envelope(database_url, call_id)
    payload = env.payload
    assert isinstance(payload, AuditRequested)
    assert payload.source == "upload" and payload.recording_ref == call["recording_original"]
    assert payload.language == "kn-IN,en-IN" and payload.stereo_channels_are_speakers is False
    assert str(payload.agent_id) == agent_id and env.producer == "api"
    assert env.correlation_id == call_id


async def test_mp3_and_stereo_flag(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    agent_id = await create_agent(api, tenant)
    buf = io.BytesIO()
    sf.write(buf, np.zeros((16000, 2), dtype="float32") + 0.1, 16000, format="MP3")
    response = await upload(
        api, tenant, agent_id, audio=buf.getvalue(), filename="call.mp3", stereo=True
    )
    assert response.status_code == 202, response.text
    call_id = response.json()["call_id"]
    (call,) = await fetch_rows(
        database_url, "SELECT recording_original FROM calls WHERE id = %s", call_id
    )
    assert call["recording_original"].endswith("original.mp3")
    (env,) = await outbox_envelopes(database_url, call_id, "pareeksha.audit.requested.v1")
    assert isinstance(env.payload, AuditRequested) and env.payload.stereo_channels_are_speakers


async def test_more_than_ten_megabytes_is_refused(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    agent_id = await create_agent(api, tenant)
    big = tone_wav(2.0) + b"\x00" * MAX_UPLOAD_BYTES
    response = await upload(api, tenant, agent_id, audio=big)
    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "file_too_large" and error["details"]["max_bytes"] == MAX_UPLOAD_BYTES
    rows = await fetch_rows(
        database_url, "SELECT count(*) AS n FROM calls WHERE project_id = %s", tenant.project_id
    )
    assert rows[0]["n"] == 0


async def test_exactly_ten_megabytes_is_accepted(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore
) -> None:
    agent_id = await create_agent(api, tenant)
    # 8 kHz 16-bit mono WAV padded to the limit with silence inside the data chunk
    seconds = (MAX_UPLOAD_BYTES - 44) // 2 / 8000
    wav = tone_wav(seconds, rate=8000)
    assert len(wav) <= MAX_UPLOAD_BYTES
    response = await upload(api, tenant, agent_id, audio=wav)
    assert response.status_code == 202, response.text


async def test_not_audio_is_unsupported(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore
) -> None:
    agent_id = await create_agent(api, tenant)
    for audio, name in ((b"hello world, not audio", "notes.txt"), (b"", "empty.wav")):
        response = await upload(
            api, tenant, agent_id, audio=audio, filename=name, content_type="audio/wav"
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "unsupported_audio"
    corrupt = await upload(api, tenant, agent_id, audio=b"RIFF\x24\x00\x00\x00WAVEjunkjunkjunkjunk")
    assert corrupt.status_code == 422


async def test_validation_and_scoping(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, blobs: LocalBlobStore
) -> None:
    agent_id = await create_agent(api, tenant)
    assert (await upload(api, tenant, str(uuid.uuid4()))).status_code == 404
    # an agent of another project is not visible
    assert (await upload(api, other_tenant, agent_id)).status_code == 404
    bad = await upload(api, tenant, agent_id, language="Kannada!")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "validation_error"
    assert (await upload(api, tenant, agent_id, headers=tenant.read)).status_code == 403
    assert (await upload(api, tenant, agent_id, headers={})).status_code == 401
    missing_file = await api.post(
        "/api/v1/audits", data={"agent_id": agent_id, "language": "kn-IN"}, headers=tenant.admin
    )
    assert missing_file.status_code == 400
