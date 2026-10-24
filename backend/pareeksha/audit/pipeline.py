"""The ``auditor`` consumer's work: ``audit.requested`` -> turns -> ``call.completed`` (TRD 8).

    recording (blob path or https URL)
      -> decode to 16 kHz mono (stereo may carry one speaker per channel)
      -> batch STT: diarization + denoise + the agent's bias words (speech provider, Gnani default)
      -> speaker labels -> roles (first speaker, then an LLM check)
      -> ``turns`` (+ PII-masked copy for the judge), ``calls`` completed
      -> ``call.completed`` (the ``evaluator`` judges it with the same rubric as a simulation)

Everything database-related runs in ``ctx.tx`` (the transaction the consumer framework opened and
will commit together with the ``processed_events`` row). Faults split three ways:

* the recording itself is unusable (corrupt, no speech, 4xx from the vendor, unsafe URL): the call
  becomes ``status='error'`` with the reason and the event is done (nothing to retry);
* transient trouble (vendor 5xx/429/timeouts, download errors): ``RetryableError`` so the
  framework retries; on the last attempt the call is marked ``error`` instead of staying
  ``transcribing`` forever;
* operator trouble (no vendor key, a provider without diarization): ``PermanentError`` -> DLQ.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.audit.ingest import AudioError, DecodedAudio, decode_audio
from pareeksha.audit.roles import RoleDecision, detect_roles
from pareeksha.audit.turns import (
    BuiltTurn,
    LabelledSegment,
    build_turns,
    label_channels,
    label_segments,
)
from pareeksha.evaluation.pii import mask_pii
from pareeksha.events.consumer import Ctx, Outgoing, PermanentError, RetryableError
from pareeksha.events.schemas import AuditRequested, CallCompleted, Envelope
from pareeksha.events.topics import MAX_ATTEMPTS
from pareeksha.llm.base import LLMRetryableError
from pareeksha.llm.client import LLMClient
from pareeksha.speech.base import (
    SpeechConfigError,
    SpeechPermanentError,
    SpeechRetryableError,
    STTProvider,
    Transcript,
    UnsupportedCapabilityError,
)
from pareeksha.storage.blob import BlobNotFoundError, BlobStore

log = logging.getLogger(__name__)

#: Downloads an imported recording (https URL) -> bytes. Raises :class:`RecordingFetchError`.
Fetcher = Callable[[str], Awaitable[bytes]]


class RecordingFetchError(Exception):
    """An imported recording could not be downloaded. ``retryable`` = worth another attempt."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def blob_prefix(source: str, call_id: uuid.UUID) -> str:
    return f"{'uploads' if source == 'upload' else 'imports'}/{call_id}"


def stt_blob_key(source: str, call_id: uuid.UUID) -> str:
    """The labelled segments of the call (what a speaker-map override re-reads)."""
    return f"{blob_prefix(source, call_id)}/stt.json"


def primary_language(language: str) -> str:
    """``"kn-IN,en-IN"`` -> ``"kn-IN"``: the first tag is the one the recogniser is told."""
    return language.split(",")[0].strip()


def bias_words(bias_list: Sequence[str] | None) -> list[str] | None:
    """``agents.bias_list`` as the single words the vendor accepts (Gnani rejects phrases such as
    "Shakti Finance" with 400 INVALID_CONFIG), without duplicates, in the original order."""
    words = dict.fromkeys(w for entry in bias_list or [] for w in entry.split())
    return list(words) or None


def _event(kind: str, **fields: object) -> dict[str, object]:
    return {"event": kind, "at": datetime.now(UTC).isoformat(), **fields}


@dataclass
class AuditDeps:
    blobs: BlobStore
    stt_factory: Callable[[], STTProvider]
    llm: LLMClient | None
    fetch: Fetcher


class _Unusable(Exception):
    """The recording cannot be transcribed; the message becomes ``calls.error``."""


class Auditor:
    """Handler object for the ``auditor`` consumer group."""

    def __init__(self, deps: AuditDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------ consumer entry points

    async def handle(self, env: Envelope[AuditRequested], ctx: Ctx) -> list[Outgoing]:
        p = env.payload
        async with ctx.tx.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT c.id, c.source, c.status, c.agent_id, c.language, c.metadata, "
                "a.name AS agent_name, a.description AS agent_description, "
                "a.bias_list AS bias_list "
                "FROM calls c LEFT JOIN agents a ON a.id = c.agent_id "
                "WHERE c.id = %s FOR UPDATE OF c",
                (p.call_id,),
            )
            call = await cur.fetchone()
        if call is None:
            raise PermanentError(f"call {p.call_id} does not exist")
        if call["status"] == "completed":
            return [self._completed(p, call["agent_id"])]  # replayed event: already transcribed

        try:
            await self._transcribe_and_store(p, call, ctx)
        except _Unusable as exc:
            await self._mark_error(ctx, p.call_id, str(exc))
            log.warning("audit failed: %s", exc, extra={"call_id": str(p.call_id)})
            return []
        except RetryableError as exc:
            if ctx.attempt >= MAX_ATTEMPTS:
                await self._mark_error(
                    ctx, p.call_id, f"gave up after {ctx.attempt} attempts: {exc}"
                )
                return []
            raise
        return [self._completed(p, call["agent_id"])]

    async def reproduce(self, env: Envelope[AuditRequested], ctx: Ctx) -> list[Outgoing]:
        """Duplicate delivery: produce ``call.completed`` again if the audit finished."""
        cur = await ctx.tx.execute(
            "SELECT agent_id, status FROM calls WHERE id = %s", (env.payload.call_id,)
        )
        row = await cur.fetchone()
        if row is None or row[1] != "completed":
            return []
        return [self._completed(env.payload, row[0])]

    # ------------------------------------------------------------------ the pipeline

    @staticmethod
    def _completed(p: AuditRequested, agent_id: uuid.UUID | None) -> Outgoing:
        return Outgoing(
            CallCompleted(
                call_id=p.call_id,
                source=p.source,
                agent_id=p.agent_id or agent_id,
                end_reason=p.source,
            ),
            correlation_id=str(p.call_id),
        )

    async def _load_audio(self, p: AuditRequested, ctx: Ctx) -> bytes:
        if p.source == "upload":
            try:
                return await self.deps.blobs.get(p.recording_ref)
            except BlobNotFoundError as exc:
                raise _Unusable(f"uploaded recording is missing from storage: {exc}") from exc
        try:
            data = await self.deps.fetch(p.recording_ref)
        except RecordingFetchError as exc:
            if exc.retryable:
                raise RetryableError(f"download failed: {exc}") from exc
            raise _Unusable(f"recording could not be downloaded: {exc}") from exc
        key = f"{blob_prefix(p.source, p.call_id)}/original"
        await self.deps.blobs.put(key, data)
        await ctx.tx.execute(
            "UPDATE calls SET recording_original = %s WHERE id = %s", (key, p.call_id)
        )
        return data

    async def _transcribe(
        self, stt: STTProvider, audio: DecodedAudio, p: AuditRequested, call: dict[str, Any]
    ) -> tuple[list[LabelledSegment], list[Transcript], list[str]]:
        """Run the vendor; returns labelled segments, the raw transcripts and notes."""
        language = primary_language(p.language)
        bias = bias_words(call["bias_list"])
        denoise = stt.capabilities.denoise
        notes: list[str] = []
        stereo = p.stereo_channels_are_speakers and len(audio.channel_wavs) == 2
        if p.stereo_channels_are_speakers and not stereo:
            notes.append("stereo_channels_are_speakers ignored: the recording is mono")

        async def run(wav: bytes, speakers: int) -> Transcript:
            nonlocal bias
            try:
                return await stt.transcribe(
                    wav,
                    language,
                    diarize=True,
                    num_speakers=speakers,
                    bias_words=bias,
                    denoise=denoise,
                )
            except UnsupportedCapabilityError:
                if bias is None:
                    raise
                notes.append(f"{stt.name.value} has no bias words: transcribed without them")
                bias = None
                return await stt.transcribe(
                    wav, language, diarize=True, num_speakers=speakers, denoise=denoise
                )

        if stereo:
            transcripts = [await run(w, 1) for w in audio.channel_wavs]
            return label_channels([t.segments for t in transcripts]), transcripts, notes
        transcript = await run(audio.mixed_wav, 2)
        return label_segments(transcript.segments), [transcript], notes

    async def _transcribe_and_store(
        self, p: AuditRequested, call: dict[str, Any], ctx: Ctx
    ) -> None:
        raw = await self._load_audio(p, ctx)
        try:
            audio = decode_audio(raw)
        except AudioError as exc:
            raise _Unusable(str(exc)) from exc

        stt = self.deps.stt_factory()
        if not stt.capabilities.diarization:
            await stt.aclose()
            raise PermanentError(
                f"STT provider {stt.name.value} cannot diarize (needed for audits)"
            )
        try:
            segments, transcripts, notes = await self._transcribe(stt, audio, p, call)
        except SpeechConfigError as exc:
            raise PermanentError(str(exc)) from exc
        except SpeechRetryableError as exc:
            raise RetryableError(str(exc)) from exc
        except (SpeechPermanentError, UnsupportedCapabilityError) as exc:
            raise _Unusable(f"speech-to-text rejected the recording: {exc}") from exc
        finally:
            await stt.aclose()
        if not segments:
            raise _Unusable("no speech detected in the recording")

        try:
            decision = await detect_roles(
                segments,
                self.deps.llm,
                agent_name=call["agent_name"] or "voice agent",
                agent_description=call["agent_description"] or "",
                language=primary_language(p.language),
            )
        except LLMRetryableError as exc:
            raise RetryableError(f"role detection: {exc}") from exc

        turns = build_turns(segments, decision.roles)
        prefix = blob_prefix(p.source, p.call_id)
        await self.deps.blobs.put(
            f"{prefix}/stt.json",
            json.dumps(
                {
                    "provider": transcripts[0].provider.value,
                    "model": transcripts[0].model,
                    "language": primary_language(p.language),
                    "stereo_channels_are_speakers": len(transcripts) == 2,
                    "segments": [s.to_dict() for s in segments],
                },
                ensure_ascii=False,
            ).encode(),
        )
        await self.deps.blobs.put(f"{prefix}/mixed.wav", audio.mixed_wav)
        await self._persist(p, ctx, audio, transcripts, decision, turns, notes)

    async def _persist(
        self,
        p: AuditRequested,
        ctx: Ctx,
        audio: DecodedAudio,
        transcripts: Sequence[Transcript],
        decision: RoleDecision,
        turns: Sequence[BuiltTurn],
        notes: Sequence[str],
    ) -> None:
        tx = ctx.tx
        language = primary_language(p.language)
        await write_turns(tx, p.call_id, turns, language)
        first = transcripts[0]
        events = [
            _event(
                "stt",
                provider=first.provider.value,
                model=first.model,
                operation=first.usage.operation,
                audio_seconds=round(sum(t.usage.audio_seconds for t in transcripts), 2),
                channels=len(transcripts),
                notes=list(notes),
            ),
            {"at": datetime.now(UTC).isoformat(), **decision.to_event()},
        ]
        await tx.execute(
            "UPDATE calls SET status = 'completed', end_reason = %s, duration_ms = %s, "
            "recording_mixed = %s, speaker_map = %s, event_log = event_log || %s, "
            "error = NULL, ended_at = now() WHERE id = %s",
            (
                p.source,
                round(audio.duration_s * 1000),
                f"{blob_prefix(p.source, p.call_id)}/mixed.wav",
                Jsonb(decision.roles),
                Jsonb(events),
                p.call_id,
            ),
        )
        for t in transcripts:
            await tx.execute(
                "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost, call_id) "
                "VALUES (%s, %s, %s, 'audio_seconds', %s, %s)",
                (
                    t.provider.value,
                    t.usage.operation,
                    t.usage.audio_seconds,
                    t.usage.est_cost,
                    p.call_id,
                ),
            )
        if decision.llm_model is not None and self.deps.llm is not None:
            await tx.execute(
                "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost, call_id) "
                "VALUES (%s, 'llm_role_detect', %s, 'tokens', %s, %s)",
                (
                    self.deps.llm.provider.name.value,
                    decision.input_tokens + decision.output_tokens,
                    decision.est_cost,
                    p.call_id,
                ),
            )

    async def _mark_error(self, ctx: Ctx, call_id: uuid.UUID, message: str) -> None:
        await ctx.tx.execute(
            "UPDATE calls SET status = 'error', error = %s, ended_at = now(), "
            "event_log = event_log || %s WHERE id = %s",
            (message[:1000], Jsonb([_event("error", message=message[:1000])]), call_id),
        )


async def write_turns(
    tx: Any, call_id: uuid.UUID, turns: Sequence[BuiltTurn], language: str | None
) -> None:
    """Replace the call's turns. ``text_masked`` is what the judge sees (PII masked)."""
    await tx.execute("DELETE FROM turns WHERE call_id = %s", (call_id,))
    async with tx.cursor() as cur:
        await cur.executemany(
            "INSERT INTO turns (call_id, idx, speaker, text, text_masked, start_ms, end_ms, "
            "is_barge_in, language_detected) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    call_id,
                    t.idx,
                    t.speaker,
                    t.text,
                    mask_pii(t.text),
                    t.start_ms,
                    t.end_ms,
                    t.is_barge_in,
                    language,
                )
                for t in turns
            ],
        )
