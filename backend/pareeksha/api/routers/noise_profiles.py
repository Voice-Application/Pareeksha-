"""Noise profiles (docs/06-api-spec.md section 2)."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import delete_row, flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, binary_response, errors
from pareeksha.api.errors import ApiError
from pareeksha.audio import preview
from pareeksha.audio.noise import CATEGORIES
from pareeksha.audio.profiles import LineProfile
from pareeksha.db.models import NoiseProfiles
from pareeksha.schemas.common import Page
from pareeksha.schemas.personas import NoiseProfileCreate, NoiseProfileOut, NoiseProfileUpdate

router = APIRouter(tags=["noise-profiles"], responses=AUTH_ERRORS)

_DUPLICATE = "A noise profile with this name already exists"
_IN_USE = "Noise profile is referenced by a run and cannot be deleted"
#: Columns that may be set back to null by PATCH; every other column is NOT NULL.
_NULLABLE = {"background_category", "snr_db"}


def _out(row: NoiseProfiles) -> NoiseProfileOut:
    return NoiseProfileOut.model_validate(row, from_attributes=True)


def _check_category(category: str | None) -> None:
    if category is not None and category not in CATEGORIES:
        raise ApiError(
            400,
            "validation_error",
            f"background_category must be one of {list(CATEGORIES)}",
            {"background_category": category},
        )


def line_profile(row: NoiseProfiles) -> LineProfile:
    """The DSP definition of a stored noise profile."""
    return LineProfile(
        name=row.name,
        sample_rate=row.sample_rate,
        codec=row.codec,
        pstn_bandpass=row.pstn_bandpass,
        background=row.background_category,
        snr_db=None if row.snr_db is None else float(row.snr_db),
        packet_loss_pct=float(row.packet_loss_pct),
        clipping=row.clipping,
    )


@router.post("/noise-profiles", status_code=201, responses=errors(409))
async def create_noise_profile(
    body: NoiseProfileCreate, key: WriteKey, session: Db
) -> NoiseProfileOut:
    _check_category(body.background_category)
    row = NoiseProfiles(project_id=key.project_id, **body.model_dump())
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.get("/noise-profiles")
async def list_noise_profiles(key: ReadKey, session: Db, page: Pagination) -> Page[NoiseProfileOut]:
    rows, next_cursor = await paginate(
        session, NoiseProfiles, [NoiseProfiles.project_id == key.project_id], page
    )
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/noise-profiles/{noise_profile_id}", responses=errors(404))
async def get_noise_profile(noise_profile_id: UUID, key: ReadKey, session: Db) -> NoiseProfileOut:
    row = await get_or_404(
        session, NoiseProfiles, noise_profile_id, key.project_id, "Noise profile"
    )
    return _out(row)


@router.patch("/noise-profiles/{noise_profile_id}", responses=errors(404, 409))
async def update_noise_profile(
    noise_profile_id: UUID, body: NoiseProfileUpdate, key: WriteKey, session: Db
) -> NoiseProfileOut:
    row = await get_or_404(
        session, NoiseProfiles, noise_profile_id, key.project_id, "Noise profile"
    )
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k in _NULLABLE
    }
    _check_category(changes.get("background_category"))
    for field, value in changes.items():
        setattr(row, field, value)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.delete(
    "/noise-profiles/{noise_profile_id}",
    status_code=204,
    responses=errors(404, 409),
    summary="Delete a noise profile (409 if referenced by a run)",
)
async def delete_noise_profile(noise_profile_id: UUID, key: WriteKey, session: Db) -> Response:
    row = await get_or_404(
        session, NoiseProfiles, noise_profile_id, key.project_id, "Noise profile"
    )
    await delete_row(session, NoiseProfiles, row.id, _IN_USE)
    return Response(status_code=204)


@router.post(
    "/noise-profiles/{noise_profile_id}/preview",
    response_class=Response,
    responses={
        **binary_response("audio/wav", "Degraded sample, or the uploaded clip degraded"),
        **errors(404, 413, 422),
    },
    summary="Degrade a built-in sample or your own clip (multipart file, optional)",
)
async def preview_noise_profile(
    noise_profile_id: UUID,
    key: ReadKey,
    session: Db,
    file: Annotated[UploadFile | None, File(description="optional clip to degrade")] = None,
) -> Response:
    row = await get_or_404(
        session, NoiseProfiles, noise_profile_id, key.project_id, "Noise profile"
    )
    if file is None or not file.filename:
        clip = preview.builtin_sample()
    else:
        data = await file.read(preview.MAX_UPLOAD_BYTES + 1)
        if len(data) > preview.MAX_UPLOAD_BYTES:
            raise ApiError(
                413,
                "file_too_large",
                f"Clip is larger than {preview.MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        try:
            clip = preview.decode_wav(data)
        except preview.UnsupportedAudioError as exc:
            raise ApiError(422, "unsupported_audio", str(exc)) from exc
    profile = line_profile(row)
    degraded = await asyncio.to_thread(preview.degrade, profile, clip)
    return Response(content=preview.encode_wav(degraded), media_type="audio/wav")
