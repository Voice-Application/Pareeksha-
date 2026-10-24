"""API-key authentication dependency: ``Authorization: Bearer pk_live_...`` with scopes.

Scopes: ``read``, ``runs:write``, ``audits:write``, ``admin`` (``admin`` implies all). Routes
declare the scope they need with ``scoped("runs:write")``; FastAPI publishes it in the OpenAPI
``security`` requirement of the operation. ``/health`` and ``/webhooks/inbound/{id}`` need no key.

Only the SHA-256 of a key is stored (``api_keys.key_hash``); the full key is shown once, when
``generate_api_key`` output is returned from ``POST /api-keys``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes
from sqlalchemy import select, update
from sqlalchemy.sql import func

from pareeksha.api.errors import ApiError
from pareeksha.db.models import ApiKeys
from pareeksha.db.session import SessionFactory, get_session_factory
from pareeksha.schemas.common import Scope

KEY_PREFIX = "pk_live_"
#: Length of ``api_keys.prefix`` (``pk_live_`` + 8 chars, e.g. pk_live_ab12cd34).
DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 8

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKey",
    bearerFormat="pk_live_...",
    description="API key from POST /api-keys (shown once). Scopes: read, runs:write, "
    "audits:write, admin (admin implies all).",
)


@dataclass(frozen=True)
class Principal:
    """The authenticated key: what a route may learn about its caller."""

    key_id: UUID
    project_id: UUID
    scopes: frozenset[str]


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return ``(full_key, display_prefix, key_hash)`` for a new key (256 bits of entropy)."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[:DISPLAY_PREFIX_LEN], hash_api_key(key)


def has_scope(granted: frozenset[str] | set[str] | list[str], required: list[str]) -> bool:
    """True when ``admin`` is granted or any of ``required`` is (no requirement: any valid key)."""
    return not required or "admin" in granted or any(s in granted for s in required)


def _unauthorized(message: str) -> ApiError:
    return ApiError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


async def authenticate(
    security_scopes: SecurityScopes,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Principal:
    """401 for a missing/unknown/revoked key, 403 when it lacks the route's scope."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing API key: send 'Authorization: Bearer pk_live_...'")
    key_hash = hash_api_key(credentials.credentials)
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ApiKeys.id, ApiKeys.project_id, ApiKeys.scopes).where(
                    ApiKeys.key_hash == key_hash, ApiKeys.revoked_at.is_(None)
                )
            )
        ).one_or_none()
        if row is None:
            raise _unauthorized("Invalid or revoked API key")
        if not has_scope(row.scopes, security_scopes.scopes):
            raise ApiError(
                403,
                "forbidden",
                "API key lacks the required scope",
                details={"required": security_scopes.scopes, "granted": list(row.scopes)},
            )
        await session.execute(
            update(ApiKeys).where(ApiKeys.id == row.id).values(last_used_at=func.now())
        )
        await session.commit()
    return Principal(key_id=row.id, project_id=row.project_id, scopes=frozenset(row.scopes))


def scoped(scope: Scope) -> Any:
    """Dependency marker for a route that needs ``scope``: ``dependencies=[scoped("read")]``."""
    return Security(authenticate, scopes=[scope])
