"""FastAPI application: ``uvicorn pareeksha.api.main:app``.

Every route of docs/06-api-spec.md is declared here under ``/api/v1`` with its final path, method,
typed request/response models and status codes, so ``GET /openapi.json`` is the complete contract
for the web app's generated client and the SDK.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute

from pareeksha.api.errors import install_error_handlers
from pareeksha.api.routers import (
    agents,
    api_keys,
    audits,
    calls,
    dialect,
    dlq,
    integrations,
    noise_profiles,
    personas,
    regression,
    runs,
    scenarios,
    system,
    webhooks,
)
from pareeksha.schemas.runs import SSE_EVENT_MODELS

API_PREFIX = "/api/v1"
API_VERSION = "0.2.0"

_DESCRIPTION = (
    "Pareeksha crash-tests voice agents with simulated Indian-language callers and scores the "
    "calls with evidence. Auth: `Authorization: Bearer pk_live_...` (scopes: read, runs:write, "
    "audits:write, admin), except `/health` and `/webhooks/inbound/{integration_id}` (HMAC). "
    'Errors: `{ "error": { "code", "message", "details" } }`.'
)

ROUTERS = (
    agents.router,
    scenarios.router,
    personas.router,
    noise_profiles.router,
    runs.router,
    regression.router,
    calls.router,
    audits.router,
    dialect.router,
    integrations.router,
    webhooks.router,
    dlq.router,
    api_keys.router,
    system.router,
    system.authed,
)


def _operation_id(route: APIRoute) -> str:
    """Stable operation ids (the handler name) for generated clients."""
    return route.name


def _strip_default_validation_errors(schema: dict[str, Any]) -> None:
    """FastAPI adds a 422 HTTPValidationError to every operation with inputs.

    Pareeksha reports validation failures as 400 ``validation_error`` in the standard envelope
    (422 is reserved for ``unsupported_audio`` / ``unsafe_url``), so the default is removed.
    """
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            body = responses.get("422", {}).get("content", {}).get("application/json", {})
            if body.get("schema", {}).get("$ref", "").endswith("/HTTPValidationError"):
                del responses["422"]
    components = schema.get("components", {}).get("schemas", {})
    components.pop("HTTPValidationError", None)
    components.pop("ValidationError", None)


def _add_sse_schemas(schema: dict[str, Any]) -> None:
    """Publish the SSE `data:` payload models so generated clients get types for them."""
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for model in SSE_EVENT_MODELS:
        model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, definition in model_schema.pop("$defs", {}).items():
            components.setdefault(name, definition)
        components[model.__name__] = model_schema


class PareekshaApp(FastAPI):
    """FastAPI app whose OpenAPI document follows the Pareeksha conventions."""

    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            schema = get_openapi(
                title=self.title,
                version=self.version,
                description=self.description,
                routes=self.routes,
            )
            _strip_default_validation_errors(schema)
            _add_sse_schemas(schema)
            self.openapi_schema = schema
        return self.openapi_schema


def create_app() -> FastAPI:
    app = PareekshaApp(
        title="Pareeksha API",
        version=API_VERSION,
        description=_DESCRIPTION,
        generate_unique_id_function=_operation_id,
    )
    install_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)

    # Docker Compose's healthcheck uses the unprefixed path; the documented route is /api/v1/health.
    app.add_api_route(
        "/health", system.health, methods=["GET"], include_in_schema=False, name="health_root"
    )
    return app


app = create_app()
