"""Post-call audits (docs/06-api-spec.md section 4)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import CallRef

router = APIRouter(tags=["audits"], responses=AUTH_ERRORS)


@router.post(
    "/audits",
    status_code=202,
    dependencies=[scoped("audits:write")],
    responses=errors(404, 413, 422),
    summary="Upload a recording (WAV/MP3, up to 10 MB) for transcription and evaluation",
)
async def create_audit(
    file: Annotated[UploadFile, File(description="WAV or MP3, at most 10 MB")],
    agent_id: Annotated[UUID, Form(description="rubric context")],
    language: Annotated[str, Form(description="e.g. kn-IN or kn-IN,en-IN")],
    stereo_channels_are_speakers: Annotated[bool, Form()] = False,
) -> CallRef:
    # STUB(EVAL-04)
    not_implemented("EVAL-04")
