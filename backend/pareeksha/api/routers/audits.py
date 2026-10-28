"""Post-call audits (docs/06-api-spec.md section 4)."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from pareeksha.api.auth import WriteAuditKey
from pareeksha.api.crud import get_or_404
from pareeksha.api.deps import AUTH_ERRORS, Blobs, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.audit.ingest import (
    MAX_UPLOAD_BYTES,
    AudioError,
    AudioTooLargeError,
    decode_audio,
)
from pareeksha.audit.pipeline import blob_prefix
from pareeksha.db.models import Agents, Calls
from pareeksha.events.outbox import enqueue_session
from pareeksha.events.schemas import AuditRequested, make_envelope
from pareeksha.schemas.common import CallRef

router = APIRouter(tags=["audits"], responses=AUTH_ERRORS)

#: ``kn-IN`` or ``kn-IN,en-IN`` (BCP-47 language-region tags, comma separated).
_LANGUAGES = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*(,[a-z]{2,3}(-[A-Za-z0-9]{2,8})*)*$")
_MAX_NAME = 200


def _clean_languages(value: str) -> str:
    cleaned = ",".join(part.strip() for part in value.split(","))
    if not _LANGUAGES.fullmatch(cleaned):
        raise ApiError(
            400,
            "validation_error",
            "language must be a BCP-47 tag or a comma-separated list, e.g. kn-IN or kn-IN,en-IN",
            {"language": value},
        )
    return cleaned


@router.post(
    "/audits",
    status_code=202,
    responses=errors(404, 413, 422),
    summary="Upload a recording (WAV/MP3, up to 10 MB) for transcription and evaluation",
)
async def create_audit(
    key: WriteAuditKey,
    session: Db,
    blobs: Blobs,
    file: Annotated[UploadFile, File(description="WAV or MP3, at most 10 MB")],
    agent_id: Annotated[UUID, Form(description="rubric context")],
    language: Annotated[str, Form(description="e.g. kn-IN or kn-IN,en-IN")],
    stereo_channels_are_speakers: Annotated[bool, Form()] = False,
) -> CallRef:
    languages = _clean_languages(language)
    await get_or_404(session, Agents, agent_id, key.project_id, "Agent")

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        audio = await asyncio.to_thread(decode_audio, data)  # size, format and decodability
    except AudioTooLargeError as exc:
        raise ApiError(413, "file_too_large", str(exc), {"max_bytes": MAX_UPLOAD_BYTES}) from exc
    except AudioError as exc:
        raise ApiError(422, "unsupported_audio", str(exc)) from exc

    call_id = uuid.uuid4()
    original = f"{blob_prefix('upload', call_id)}/original.{audio.format}"
    session.add(
        Calls(
            id=call_id,
            project_id=key.project_id,
            agent_id=agent_id,
            source="upload",
            language=languages,
            status="transcribing",
            recording_original=original,
            metadata_={
                "filename": (file.filename or "")[:_MAX_NAME],
                "size_bytes": len(data),
                "stereo_channels_are_speakers": stereo_channels_are_speakers,
            },
        )
    )
    await session.flush()
    await blobs.put(original, data)
    enqueue_session(
        session,
        make_envelope(
            AuditRequested(
                call_id=call_id,
                source="upload",
                agent_id=agent_id,
                language=languages,
                recording_ref=original,
                stereo_channels_are_speakers=stereo_channels_are_speakers,
            ),
            producer="api",
            correlation_id=str(call_id),
        ),
    )
    return CallRef(call_id=call_id)
