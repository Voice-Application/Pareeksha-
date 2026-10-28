"""API keys (docs/06-api-spec.md section 10)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import AdminKey, generate_api_key
from pareeksha.api.crud import flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.db.models import ApiKeys
from pareeksha.schemas.common import Page
from pareeksha.schemas.system import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(tags=["api-keys"], responses=AUTH_ERRORS)


def _out(row: ApiKeys) -> ApiKeyOut:
    return ApiKeyOut.model_validate(row, from_attributes=True)


@router.post(
    "/api-keys",
    status_code=201,
    summary="Create a key; the full key is returned once",
)
async def create_api_key(body: ApiKeyCreate, key: AdminKey, session: Db) -> ApiKeyCreated:
    full_key, prefix, key_hash = generate_api_key()
    scopes = list(dict.fromkeys(body.scopes))  # drop duplicates, keep order
    row = ApiKeys(
        project_id=key.project_id,
        name=body.name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
    )
    session.add(row)
    await flush(session, "Could not create the key, try again", refresh=row)
    return ApiKeyCreated(**_out(row).model_dump(), key=full_key)


@router.get("/api-keys", summary="List keys (prefix, scopes, last use)")
async def list_api_keys(key: AdminKey, session: Db, page: Pagination) -> Page[ApiKeyOut]:
    rows, next_cursor = await paginate(
        session, ApiKeys, [ApiKeys.project_id == key.project_id], page
    )
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.delete(
    "/api-keys/{api_key_id}",
    status_code=204,
    responses=errors(404),
    summary="Revoke a key",
)
async def revoke_api_key(api_key_id: UUID, key: AdminKey, session: Db) -> Response:
    row = await get_or_404(session, ApiKeys, api_key_id, key.project_id, "API key")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await flush(session, "Could not revoke the key")
    return Response(status_code=204)
