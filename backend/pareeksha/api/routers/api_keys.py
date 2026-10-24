"""API keys (docs/06-api-spec.md section 10)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.system import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(tags=["api-keys"], responses=AUTH_ERRORS)


@router.post(
    "/api-keys",
    status_code=201,
    dependencies=[scoped("admin")],
    summary="Create a key; the full key is returned once",
)
async def create_api_key(body: ApiKeyCreate) -> ApiKeyCreated:
    # STUB(API-02)
    not_implemented("API-02")


@router.get(
    "/api-keys", dependencies=[scoped("admin")], summary="List keys (prefix, scopes, last use)"
)
async def list_api_keys(page: Pagination) -> Page[ApiKeyOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.delete(
    "/api-keys/{api_key_id}",
    status_code=204,
    dependencies=[scoped("admin")],
    responses=errors(404),
    summary="Revoke a key",
)
async def revoke_api_key(api_key_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")
