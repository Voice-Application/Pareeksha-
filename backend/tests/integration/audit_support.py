"""Helpers for the EVAL-04 audit tests: real Postgres, scripted speech and LLM providers."""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
import psycopg
import soundfile as sf
from httpx import AsyncClient
from psycopg.rows import dict_row

from pareeksha.audit.pipeline import AuditDeps, Auditor, RecordingFetchError
from pareeksha.events.consumer import Ctx
from pareeksha.events.schemas import AnyEnvelope, AuditRequested, Envelope, parse_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.speech.base import (
    SpeechProviderName,
    SpeechUsage,
    STTCapabilities,
    STTProvider,
    Transcript,
    TranscriptSegment,
)
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant
from tests.unit.evaluation.fakes import ScriptedProvider, client_for


def tone_wav(seconds: float = 2.0, rate: int = 16000, channels: int = 1) -> bytes:
    t = np.arange(int(seconds * rate)) / rate
    mono = (0.3 * np.sin(2 * np.pi * 300 * t)).astype("float32")
    data = mono if channels == 1 else np.stack([mono, np.roll(mono, 7)], axis=1)
    buf = io.BytesIO()
    sf.write(buf, data, rate, format="WAV")
    return buf.getvalue()


def seg(text: str, start: float, end: float, speaker: str | None) -> TranscriptSegment:
    return TranscriptSegment(text=text, start_s=start, end_s=end, speaker=speaker)


#: A short synthetic EMI-reminder call (all data invented). Provider speaker "1" speaks first.
CALL_SEGMENTS = [
    seg("Namaste, this is Shree Finance, this call is recorded.", 0.0, 3.0, "1"),
    seg("Your EMI of four thousand two hundred rupees is due on Friday.", 3.2, 6.0, "1"),
    seg("Haan, my number is 9876543210, I will pay on Friday.", 6.8, 9.0, "2"),
    seg("Thank you, I have noted the promise to pay.", 9.5, 11.5, "1"),
]


class FakeSTT(STTProvider):
    """Scripted speech-to-text: returns queued transcripts (or raises queued errors)."""

    name = SpeechProviderName.GNANI
    capabilities = STTCapabilities(
        streaming=False, word_timings=False, word_confidence=False, diarization=True, denoise=True
    )

    def __init__(self, *replies: list[TranscriptSegment] | Exception) -> None:
        self.replies = list(replies) or [CALL_SEGMENTS]
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
        denoise: bool = False,
    ) -> Transcript:
        self.calls.append(
            {
                "language": language,
                "diarize": diarize,
                "num_speakers": num_speakers,
                "bias_words": bias_words,
                "denoise": denoise,
                "wav_bytes": len(wav),
            }
        )
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return Transcript(
            provider=self.name,
            model="fake-batch",
            text=" ".join(s.text for s in reply),
            language=language,
            duration_s=12.0,
            segments=reply,
            usage=SpeechUsage(
                provider=self.name, operation="stt_batch", audio_seconds=12.0, est_cost=0.5
            ),
        )

    async def aclose(self) -> None:
        self.closed += 1


class NoDiarizeSTT(FakeSTT):
    capabilities = STTCapabilities(
        streaming=False, word_timings=False, word_confidence=False, diarization=False
    )


def role_reply(roles: dict[str, str], confidence: str = "high") -> str:
    import json

    return json.dumps({"speaker_roles": roles, "confidence": confidence, "reason": "greeting"})


def make_auditor(
    blobs: LocalBlobStore,
    stt: STTProvider | None = None,
    llm_replies: list[str | Exception] | None = None,
    fetch: Any = None,
) -> tuple[Auditor, STTProvider, ScriptedProvider | None]:
    stt = stt or FakeSTT()
    provider = None if llm_replies is None else ScriptedProvider(llm_replies)

    async def no_fetch(url: str) -> bytes:
        raise RecordingFetchError("fetch not expected", retryable=False)

    auditor = Auditor(
        AuditDeps(
            blobs=blobs,
            stt_factory=lambda: stt,
            llm=None if provider is None else client_for(provider),
            fetch=fetch or no_fetch,
        )
    )
    return auditor, stt, provider


@asynccontextmanager
async def transaction(database_url: str) -> AsyncIterator[Ctx]:
    """A consumer-style transaction on the migrated test database."""
    async with (
        await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as conn,
        conn.transaction(),
    ):
        yield Ctx(
            tx=conn, group="test", topic="t", partition=0, offset=0, attempt=1, duplicate=False
        )


async def fetch_rows(database_url: str, sql: str, *args: Any) -> list[dict[str, Any]]:
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), row_factory=dict_row
    ) as conn:
        cur = await conn.execute(sql, args)
        return await cur.fetchall()


async def outbox_envelopes(database_url: str, call_id: str, topic: str) -> list[AnyEnvelope]:
    rows = await fetch_rows(
        database_url,
        "SELECT envelope FROM outbox_events WHERE topic = %s "
        "AND envelope->'payload'->>'call_id' = %s ORDER BY created_at",
        topic,
        call_id,
    )
    import json

    return [parse_envelope(json.dumps(r["envelope"]).encode()) for r in rows]


async def create_agent(api: AsyncClient, tenant: Tenant, **overrides: Any) -> str:
    body = {
        "name": f"EMI bot {uuid.uuid4().hex[:6]}",
        "description": "Calls borrowers about an EMI due date and records a promise to pay.",
        "adapter": "audio_v1",
        "endpoint_url": "ws://mock-agent:8765/ws",
        "languages": ["kn-IN", "en-IN"],
        "mandatory_disclosures": [
            {"id": "recording", "text": "recorded", "regex": "record", "within_turns": 2}
        ],
        "bias_list": ["EMI", "Shree Finance"],
        **overrides,
    }
    response = await api.post("/api/v1/agents", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def upload(
    api: AsyncClient,
    tenant: Tenant,
    agent_id: str,
    *,
    audio: bytes | None = None,
    language: str = "kn-IN,en-IN",
    filename: str = "call.wav",
    content_type: str = "audio/wav",
    stereo: bool | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    data = {"agent_id": agent_id, "language": language}
    if stereo is not None:
        data["stereo_channels_are_speakers"] = "true" if stereo else "false"
    return await api.post(
        "/api/v1/audits",
        data=data,
        files={"file": (filename, audio if audio is not None else tone_wav(), content_type)},
        headers=tenant.admin if headers is None else headers,
    )


async def audit_envelope(database_url: str, call_id: str) -> Envelope[AuditRequested]:
    found = await outbox_envelopes(database_url, call_id, "pareeksha.audit.requested.v1")
    assert len(found) == 1
    return found[0]  # type: ignore[return-value]


RUBRIC_SQL = (
    "INSERT INTO rubric_versions (version, dimensions, prompt_hash) "
    "VALUES (%s, '[]'::jsonb, 'sha256:test') ON CONFLICT (version) DO NOTHING"
)
