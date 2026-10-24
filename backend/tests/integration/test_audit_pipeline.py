"""The auditor against real Postgres: upload -> diarized STT -> roles -> turns -> call.completed.

Speech-to-text and the LLM are scripted (the real-vendor run is proof/EVAL-04); the database, the
blob store, the API and the outbox are real.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.audit.pipeline import RecordingFetchError
from pareeksha.events.consumer import PermanentError, RetryableError
from pareeksha.events.schemas import AuditRequested, CallCompleted, Envelope, make_envelope
from pareeksha.speech.base import (
    SpeechConfigError,
    SpeechPermanentError,
    SpeechRetryableError,
)
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant
from tests.integration.audit_support import (
    CALL_SEGMENTS,
    FakeSTT,
    NoDiarizeSTT,
    audit_envelope,
    create_agent,
    fetch_rows,
    make_auditor,
    role_reply,
    seg,
    tone_wav,
    transaction,
    upload,
)


async def uploaded(
    api: AsyncClient, tenant: Tenant, database_url: str, **kwargs: Any
) -> tuple[str, Envelope[AuditRequested]]:
    agent_id = kwargs.pop("agent_id", None) or await create_agent(api, tenant)
    response = await upload(api, tenant, agent_id, **kwargs)
    assert response.status_code == 202, response.text
    call_id = response.json()["call_id"]
    return call_id, await audit_envelope(database_url, call_id)


async def call_row(database_url: str, call_id: str) -> dict[str, Any]:
    (row,) = await fetch_rows(database_url, "SELECT * FROM calls WHERE id = %s", call_id)
    return row


async def turn_rows(database_url: str, call_id: str) -> list[dict[str, Any]]:
    return await fetch_rows(
        database_url, "SELECT * FROM turns WHERE call_id = %s ORDER BY idx", call_id
    )


async def test_upload_becomes_labelled_turns_and_call_completed(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    auditor, stt, llm = make_auditor(
        blobs, llm_replies=[role_reply({"spk_0": "agent", "spk_1": "caller"})]
    )
    async with transaction(database_url) as ctx:
        out = await auditor.handle(env, ctx)

    (completed,) = out
    payload = completed.payload
    assert isinstance(payload, CallCompleted)
    assert str(payload.call_id) == call_id and payload.source == "upload"
    assert payload.end_reason == "upload" and payload.agent_id == env.payload.agent_id
    assert payload.run_id is None and completed.correlation_id == call_id

    # the vendor was asked for what the brief requires: diarization, denoise, bias words
    (request,) = stt.calls  # type: ignore[attr-defined]
    assert request["language"] == "kn-IN"  # first of "kn-IN,en-IN"
    assert request["diarize"] is True and request["num_speakers"] == 2
    assert request["denoise"] is True and request["bias_words"] == ["EMI", "Shree", "Finance"]
    assert stt.closed == 1  # type: ignore[attr-defined]

    call = await call_row(database_url, call_id)
    assert call["status"] == "completed" and call["end_reason"] == "upload"
    assert call["speaker_map"] == {"spk_0": "agent", "spk_1": "caller"}
    assert call["duration_ms"] == 2000 and call["error"] is None and call["ended_at"]
    assert await blobs.exists(call["recording_mixed"])
    assert [e["event"] for e in call["event_log"]] == ["stt", "role_detection"]
    assert call["event_log"][1]["method"] == "llm" and call["event_log"][1]["agrees_with_heuristic"]

    turns = await turn_rows(database_url, call_id)
    assert [(t["idx"], t["speaker"]) for t in turns] == [(0, "agent"), (1, "caller"), (2, "agent")]
    assert turns[0]["text"].endswith(
        "this call is recorded. Your EMI of four thousand two hundred rupees is due on Friday."
    )
    assert (turns[0]["start_ms"], turns[0]["end_ms"]) == (0, 6000)
    assert "9876543210" in turns[1]["text"] and "9876543210" not in turns[1]["text_masked"]
    assert all(t["language_detected"] == "kn-IN" for t in turns)

    usage = await fetch_rows(
        database_url,
        "SELECT provider, operation, unit_type, units, est_cost FROM api_usage "
        "WHERE call_id = %s ORDER BY id",
        call_id,
    )
    assert [(u["provider"], u["operation"], u["unit_type"]) for u in usage] == [
        ("gnani", "stt_batch", "audio_seconds"),
        ("deepseek", "llm_role_detect", "tokens"),
    ]
    assert llm is not None and len(llm.requests) == 1


async def test_llm_check_overrides_the_first_speaker_rule(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    """The customer spoke first ("hello?") so the heuristic is wrong; the LLM fixes it."""
    segments = [
        seg("Hello? Who is this?", 0.0, 1.5, "1"),
        seg(
            "Namaste, I am calling from Shree Finance about your EMI, this call is recorded.",
            2.0,
            6.0,
            "2",
        ),
        seg("Okay, tell me the amount.", 6.5, 8.0, "1"),
    ]
    call_id, env = await uploaded(api, tenant, database_url)
    auditor, _, _ = make_auditor(
        blobs,
        stt=FakeSTT(segments),
        llm_replies=[role_reply({"spk_0": "caller", "spk_1": "agent"})],
    )
    async with transaction(database_url) as ctx:
        await auditor.handle(env, ctx)
    call = await call_row(database_url, call_id)
    assert call["speaker_map"] == {"spk_0": "caller", "spk_1": "agent"}
    detection = call["event_log"][1]
    assert detection["method"] == "llm" and detection["agrees_with_heuristic"] is False
    assert "overrides" in detection["note"]
    turns = await turn_rows(database_url, call_id)
    assert [t["speaker"] for t in turns] == ["caller", "agent", "caller"]


async def test_without_an_llm_the_first_speaker_is_the_agent_and_the_log_says_so(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    auditor, _, _ = make_auditor(blobs, llm_replies=None)
    async with transaction(database_url) as ctx:
        out = await auditor.handle(env, ctx)
    assert len(out) == 1
    call = await call_row(database_url, call_id)
    assert call["event_log"][1]["method"] == "heuristic"
    assert "not configured" in call["event_log"][1]["note"]
    usage = await fetch_rows(
        database_url, "SELECT operation FROM api_usage WHERE call_id = %s", call_id
    )
    assert [u["operation"] for u in usage] == ["stt_batch"]


async def test_stereo_channels_are_transcribed_separately(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(
        api, tenant, database_url, audio=tone_wav(3.0, channels=2), stereo=True
    )
    stt = FakeSTT(
        [seg("Namaste, Shree Finance, this call is recorded.", 0.0, 2.0, "1")],
        [seg("Haan boliye.", 1.0, 2.5, "1")],
    )
    auditor, _, _ = make_auditor(blobs, stt=stt, llm_replies=None)
    async with transaction(database_url) as ctx:
        await auditor.handle(env, ctx)
    assert [c["num_speakers"] for c in stt.calls] == [1, 1]
    turns = await turn_rows(database_url, call_id)
    assert [(t["speaker"], t["is_barge_in"]) for t in turns] == [("agent", False), ("caller", True)]
    usage = await fetch_rows(database_url, "SELECT 1 FROM api_usage WHERE call_id = %s", call_id)
    assert len(usage) == 2  # one billed STT call per channel


async def test_stereo_flag_on_a_mono_recording_is_noted_and_ignored(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url, stereo=True)
    auditor, stt, _ = make_auditor(blobs, llm_replies=None)
    async with transaction(database_url) as ctx:
        await auditor.handle(env, ctx)
    assert [c["num_speakers"] for c in stt.calls] == [2]  # type: ignore[attr-defined]
    notes = (await call_row(database_url, call_id))["event_log"][0]["notes"]
    assert any("mono" in n for n in notes)


async def test_bias_words_are_dropped_when_the_provider_has_none(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    from pareeksha.speech.base import UnsupportedCapabilityError

    class NoBias(FakeSTT):
        async def transcribe(self, wav: bytes, language: str, **kw: Any):  # type: ignore[no-untyped-def]
            if kw.get("bias_words"):
                self.calls.append({"bias_words": kw["bias_words"]})
                raise UnsupportedCapabilityError("no bias words")
            return await super().transcribe(wav, language, **kw)

    call_id, env = await uploaded(api, tenant, database_url)
    stt = NoBias()
    auditor, _, _ = make_auditor(blobs, stt=stt, llm_replies=None)
    async with transaction(database_url) as ctx:
        await auditor.handle(env, ctx)
    assert (
        stt.calls[0]["bias_words"] == ["EMI", "Shree", "Finance"]
        and stt.calls[1]["bias_words"] is None
    )
    notes = (await call_row(database_url, call_id))["event_log"][0]["notes"]
    assert any("bias words" in n for n in notes)


async def test_replayed_event_does_not_pay_for_transcription_twice(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    auditor, stt, _ = make_auditor(blobs, llm_replies=None)
    async with transaction(database_url) as ctx:
        first = await auditor.handle(env, ctx)
    async with transaction(database_url) as ctx:
        again = await auditor.handle(env, ctx)  # e.g. a DLQ replay with a fresh event id
    async with transaction(database_url) as ctx:
        reproduced = await auditor.reproduce(env, ctx)
    assert len(stt.calls) == 1  # type: ignore[attr-defined]
    assert first[0].payload == again[0].payload == reproduced[0].payload
    assert len(await turn_rows(database_url, call_id)) == 3


async def test_reproduce_before_completion_produces_nothing(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    _, env = await uploaded(api, tenant, database_url)
    auditor, _, _ = make_auditor(blobs, llm_replies=None)
    async with transaction(database_url) as ctx:
        assert await auditor.reproduce(env, ctx) == []
    ghost = make_envelope(
        AuditRequested(
            call_id=uuid.uuid4(), source="upload", language="kn-IN", recording_ref="uploads/x/y.wav"
        ),
        producer="t",
        correlation_id="x",
    )
    async with transaction(database_url) as ctx:
        assert await auditor.reproduce(ghost, ctx) == []  # type: ignore[arg-type]


async def test_unknown_call_goes_to_the_dlq(blobs: LocalBlobStore, database_url: str) -> None:
    ghost = make_envelope(
        AuditRequested(
            call_id=uuid.uuid4(), source="upload", language="kn-IN", recording_ref="uploads/x/y.wav"
        ),
        producer="t",
        correlation_id="x",
    )
    auditor, _, _ = make_auditor(blobs)
    async with transaction(database_url) as ctx:
        with pytest.raises(PermanentError, match="does not exist"):
            await auditor.handle(ghost, ctx)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------- failures


async def failed_call(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    auditor_args: dict[str, Any],
    attempt: int = 1,
    corrupt: bool = False,
) -> tuple[dict[str, Any], list[Any]]:
    call_id, env = await uploaded(api, tenant, database_url)
    if corrupt:
        await blobs.put(env.payload.recording_ref, b"RIFF\x24\x00\x00\x00WAVEjunkjunkjunk")
    auditor, _, _ = make_auditor(blobs, **auditor_args)
    async with transaction(database_url) as ctx:
        ctx.attempt = attempt
        out = await auditor.handle(env, ctx)
    return await call_row(database_url, call_id), list(out)


async def test_corrupt_audio_marks_the_call_failed_without_retrying(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call, out = await failed_call(api, tenant, blobs, database_url, {}, corrupt=True)
    assert out == [] and call["status"] == "error" and "cannot decode" in call["error"]
    assert call["event_log"][-1]["event"] == "error"
    assert (
        await fetch_rows(database_url, "SELECT 1 FROM turns WHERE call_id = %s", call["id"]) == []
    )


async def test_missing_blob_marks_the_call_failed(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    other = LocalBlobStore(blobs.root.parent / "elsewhere")
    auditor, _, _ = make_auditor(other)
    async with transaction(database_url) as ctx:
        assert await auditor.handle(env, ctx) == []
    assert "missing from storage" in (await call_row(database_url, call_id))["error"]


async def test_no_speech_marks_the_call_failed(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    stt = FakeSTT([seg("   ", 0.0, 1.0, "1")])
    call, out = await failed_call(api, tenant, blobs, database_url, {"stt": stt})
    assert (
        out == []
        and call["status"] == "error"
        and call["error"] == "no speech detected in the recording"
    )


async def test_vendor_rejection_is_final(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    stt = FakeSTT(SpeechPermanentError("gnani: 400 unsupported language"))
    call, out = await failed_call(api, tenant, blobs, database_url, {"stt": stt})
    assert out == [] and call["status"] == "error" and "rejected the recording" in call["error"]
    assert stt.closed == 1


async def test_transient_vendor_error_is_retried_then_recorded_on_the_last_attempt(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    stt = FakeSTT(SpeechRetryableError("gnani: 503"))
    auditor, _, _ = make_auditor(blobs, stt=stt)
    async with transaction(database_url) as ctx:
        with pytest.raises(RetryableError, match="503"):
            await auditor.handle(env, ctx)
    async with transaction(database_url) as ctx:
        ctx.attempt = 3
        assert await auditor.handle(env, ctx) == []
    call = await call_row(database_url, call_id)
    assert call["status"] == "error" and "gave up after 3 attempts" in call["error"]


async def test_missing_vendor_key_is_an_operator_problem_not_a_bad_recording(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    call_id, env = await uploaded(api, tenant, database_url)
    auditor, _, _ = make_auditor(blobs, stt=FakeSTT(SpeechConfigError("gnani: set GNANI_API_KEY")))
    async with transaction(database_url) as ctx:
        with pytest.raises(PermanentError, match="GNANI_API_KEY"):
            await auditor.handle(env, ctx)
    # the call is left transcribing so that replaying the DLQ entry can finish it
    assert (await call_row(database_url, call_id))["status"] == "transcribing"


async def test_provider_without_diarization_is_refused(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    _, env = await uploaded(api, tenant, database_url)
    stt = NoDiarizeSTT()
    auditor, _, _ = make_auditor(blobs, stt=stt)
    async with transaction(database_url) as ctx:
        with pytest.raises(PermanentError, match="cannot diarize"):
            await auditor.handle(env, ctx)
    assert stt.closed == 1 and stt.calls == []


async def test_role_detection_outage_is_retried(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    from pareeksha.llm.base import LLMRetryableError

    _, env = await uploaded(api, tenant, database_url)
    auditor, _, _ = make_auditor(blobs, llm_replies=[LLMRetryableError("deepseek 503")])
    async with transaction(database_url) as ctx:
        with pytest.raises(RetryableError, match="role detection"):
            await auditor.handle(env, ctx)


# ---------------------------------------------------------------------------------- imports


async def imported(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: Any,
    url: str = "https://calls.example.com/1.wav",
) -> Envelope[AuditRequested]:
    from pareeksha.db.models import Calls

    agent_id = uuid.UUID(await create_agent(api, tenant))
    call_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            Calls(
                id=call_id,
                project_id=tenant.project_id,
                agent_id=agent_id,
                source="import",
                language="hi-IN",
                status="transcribing",
            )
        )
        await session.commit()
    return make_envelope(  # type: ignore[return-value]
        AuditRequested(
            call_id=call_id,
            source="import",
            agent_id=agent_id,
            language="hi-IN",
            recording_ref=url,
            integration_id=uuid.uuid4(),
            external_id="CA123",
        ),
        producer="integrations",
        correlation_id=str(call_id),
    )


async def test_imported_recording_is_downloaded_stored_and_transcribed(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str, session_factory: Any
) -> None:
    env = await imported(api, tenant, session_factory)
    fetched: list[str] = []

    async def fetch(url: str) -> bytes:
        fetched.append(url)
        return tone_wav(2.0)

    auditor, _, _ = make_auditor(blobs, llm_replies=None, fetch=fetch)
    async with transaction(database_url) as ctx:
        (out,) = await auditor.handle(env, ctx)
    call_id = str(env.payload.call_id)
    assert fetched == ["https://calls.example.com/1.wav"]
    assert isinstance(out.payload, CallCompleted) and out.payload.source == "import"
    assert out.payload.end_reason == "import"
    call = await call_row(database_url, call_id)
    assert call["status"] == "completed" and call["end_reason"] == "import"
    assert call["recording_original"] == f"imports/{call_id}/original"
    assert await blobs.exists(call["recording_original"])
    assert await blobs.exists(f"imports/{call_id}/stt.json")
    assert len(await turn_rows(database_url, call_id)) == 3


@pytest.mark.parametrize(("retryable", "expect"), [(False, "marked"), (True, "retry")])
async def test_download_failures(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    session_factory: Any,
    retryable: bool,
    expect: str,
) -> None:
    env = await imported(api, tenant, session_factory)

    async def fetch(url: str) -> bytes:
        raise RecordingFetchError("blocked: private address", retryable=retryable)

    auditor, _, _ = make_auditor(blobs, fetch=fetch)
    async with transaction(database_url) as ctx:
        if expect == "retry":
            with pytest.raises(RetryableError, match="download failed"):
                await auditor.handle(env, ctx)
        else:
            assert await auditor.handle(env, ctx) == []
    call = await call_row(database_url, str(env.payload.call_id))
    assert call["status"] == ("transcribing" if retryable else "error")
    if not retryable:
        assert "could not be downloaded" in call["error"]


def test_call_segments_fixture_is_what_the_tests_assume() -> None:
    assert [s.speaker for s in CALL_SEGMENTS] == ["1", "1", "2", "1"]
