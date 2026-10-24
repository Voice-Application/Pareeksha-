"""Personas (docs/06-api-spec.md section 2)."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import delete_row, flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, binary_response, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.speech import Synthesizer, get_synthesizer, sample_line
from pareeksha.db.models import Personas
from pareeksha.schemas.common import Page
from pareeksha.schemas.personas import PersonaCreate, PersonaOut, PersonaUpdate

router = APIRouter(tags=["personas"], responses=AUTH_ERRORS)

_DUPLICATE = "A persona with this name already exists"
_IN_USE = "Persona is referenced by a run and cannot be deleted"


def _out(row: Personas) -> PersonaOut:
    return PersonaOut.model_validate(row, from_attributes=True)


@router.post("/personas", status_code=201, responses=errors(409))
async def create_persona(body: PersonaCreate, key: WriteKey, session: Db) -> PersonaOut:
    row = Personas(project_id=key.project_id, is_seed=False, **body.model_dump())
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.get("/personas")
async def list_personas(
    key: ReadKey, session: Db, page: Pagination, language: str | None = None
) -> Page[PersonaOut]:
    conditions = [Personas.project_id == key.project_id]
    if language is not None:
        conditions.append(Personas.language == language)
    rows, next_cursor = await paginate(session, Personas, conditions, page)
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/personas/{persona_id}", responses=errors(404))
async def get_persona(persona_id: UUID, key: ReadKey, session: Db) -> PersonaOut:
    return _out(await get_or_404(session, Personas, persona_id, key.project_id, "Persona"))


@router.patch("/personas/{persona_id}", responses=errors(404, 409))
async def update_persona(
    persona_id: UUID, body: PersonaUpdate, key: WriteKey, session: Db
) -> PersonaOut:
    row = await get_or_404(session, Personas, persona_id, key.project_id, "Persona")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.delete(
    "/personas/{persona_id}",
    status_code=204,
    responses=errors(404, 409),
    summary="Delete a persona (409 if referenced by a run)",
)
async def delete_persona(persona_id: UUID, key: WriteKey, session: Db) -> Response:
    row = await get_or_404(session, Personas, persona_id, key.project_id, "Persona")
    await delete_row(session, Personas, row.id, _IN_USE)
    return Response(status_code=204)


@router.post(
    "/personas/{persona_id}/preview",
    response_class=Response,
    responses={
        **binary_response("audio/wav", "One sample line in the persona's voice"),
        **errors(404, 502),
    },
    summary="Synthesise one sample line (audio/wav)",
)
async def preview_persona(
    persona_id: UUID,
    key: ReadKey,
    session: Db,
    synthesizer: Annotated[Synthesizer, Depends(get_synthesizer)],
) -> Response:
    row = await get_or_404(session, Personas, persona_id, key.project_id, "Persona")
    try:
        audio = await asyncio.to_thread(
            synthesizer.synthesize_wav,
            sample_line(row.language),
            row.voice_id,
            row.language,
            speed=float(row.speed),
            model=row.tts_model,
        )
    except Exception as exc:
        raise ApiError(502, "upstream_error", f"Gnani TTS failed: {exc}") from exc
    return Response(content=audio, media_type="audio/wav")
