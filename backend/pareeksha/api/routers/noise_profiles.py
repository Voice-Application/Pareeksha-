"""Noise profiles (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Response, UploadFile

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, binary_response, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.personas import NoiseProfileCreate, NoiseProfileOut, NoiseProfileUpdate

router = APIRouter(tags=["noise-profiles"], responses=AUTH_ERRORS)


@router.post(
    "/noise-profiles", status_code=201, dependencies=[scoped("runs:write")], responses=errors(409)
)
async def create_noise_profile(body: NoiseProfileCreate) -> NoiseProfileOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/noise-profiles", dependencies=[scoped("read")])
async def list_noise_profiles(page: Pagination) -> Page[NoiseProfileOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.get(
    "/noise-profiles/{noise_profile_id}", dependencies=[scoped("read")], responses=errors(404)
)
async def get_noise_profile(noise_profile_id: UUID) -> NoiseProfileOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.patch(
    "/noise-profiles/{noise_profile_id}",
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
)
async def update_noise_profile(noise_profile_id: UUID, body: NoiseProfileUpdate) -> NoiseProfileOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.delete(
    "/noise-profiles/{noise_profile_id}",
    status_code=204,
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Delete a noise profile (409 if referenced by a run)",
)
async def delete_noise_profile(noise_profile_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/noise-profiles/{noise_profile_id}/preview",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={
        **binary_response("audio/wav", "Degraded sample, or the uploaded clip degraded"),
        **errors(404, 413, 422),
    },
    summary="Degrade a built-in sample or your own clip (multipart file, optional)",
)
async def preview_noise_profile(
    noise_profile_id: UUID,
    file: Annotated[UploadFile | None, File(description="optional clip to degrade")] = None,
) -> Response:
    # STUB(API-02)
    not_implemented("API-02")
