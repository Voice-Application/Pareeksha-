"""API-key authentication dependency: ``Authorization: Bearer pk_live_...`` with scopes.

Scopes: ``read``, ``runs:write``, ``audits:write``, ``admin`` (``admin`` implies all). Routes
declare the scope they need with ``scoped("runs:write")``; FastAPI publishes it in the OpenAPI
``security`` requirement of the operation. ``/health`` and ``/webhooks/inbound/{id}`` need no key.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, SecurityScopes

from pareeksha.api.errors import ApiError
from pareeksha.schemas.common import Scope

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKey",
    bearerFormat="pk_live_...",
    description="API key from POST /api-keys (shown once). Scopes: read, runs:write, "
    "audits:write, admin (admin implies all).",
)


async def authenticate(
    security_scopes: SecurityScopes,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> None:
    """Reject requests without a bearer key (401)."""
    if credentials is None or not credentials.credentials:
        raise ApiError(
            401,
            "unauthorized",
            "Missing API key: send 'Authorization: Bearer pk_live_...'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # STUB(API-01): hash the key, look it up in api_keys (not revoked), update last_used_at and
    # return 403 forbidden when none of security_scopes.scopes (or admin) is granted.


def scoped(scope: Scope) -> Any:
    """Dependency marker for a route that needs ``scope``: ``dependencies=[scoped("read")]``."""
    return Security(authenticate, scopes=[scope])
