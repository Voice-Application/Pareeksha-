"""Agents (docs/06-api-spec.md section 1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.adapters.base import AgentTarget
from pareeksha.adapters.connection_check import check_connection
from pareeksha.agent_llm import AgentLLMError, AgentMessage, build_chat_provider
from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import ACTIVE_VERSION_KEY, active_version, flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.routers.integrations import _secret_box
from pareeksha.db.models import Agents
from pareeksha.integrations.crypto import SecretDecryptError
from pareeksha.schemas.agents import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    TestConnectionResult,
)
from pareeksha.schemas.common import Page
from pareeksha.schemas.prompts import ProviderName

router = APIRouter(tags=["agents"], responses=AUTH_ERRORS)

_DUPLICATE = "An agent with this name already exists"


def _out(row: Agents) -> AgentOut:
    out = AgentOut.model_validate(row, from_attributes=True)
    out.has_adapter_secrets = bool(row.adapter_secrets_encrypted)
    return out


def _client_config(config: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Client-supplied ``adapter_config`` minus the server-owned ``active_version_id``, which is
    kept from ``current`` (only prompt-version endpoints may point an agent at a version)."""
    out = {k: v for k, v in config.items() if k != ACTIVE_VERSION_KEY}
    if current and current.get(ACTIVE_VERSION_KEY):
        out[ACTIVE_VERSION_KEY] = current[ACTIVE_VERSION_KEY]
    return out


def _encrypt(secrets: dict[str, str]) -> bytes | None:
    """Fernet token for the write-only provider secrets; ``{}`` clears them."""
    return _secret_box().encrypt(secrets).encode() if secrets else None


@router.post(
    "/agents",
    status_code=201,
    responses=errors(409),
    summary="Register an agent under test",
)
async def create_agent(body: AgentCreate, key: WriteKey, session: Db) -> AgentOut:
    agent_id = uuid.uuid4()
    data = body.model_dump(mode="json")
    data["adapter_config"] = _client_config(data["adapter_config"])
    if body.adapter == "prompt":
        data["endpoint_url"] = f"prompt://{agent_id}"
    row = Agents(
        id=agent_id,
        project_id=key.project_id,
        adapter_secrets_encrypted=_encrypt(body.adapter_secrets or {}),
        **data,
    )
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.get("/agents", summary="List agents")
async def list_agents(
    key: ReadKey, session: Db, page: Pagination, include_archived: bool = False
) -> Page[AgentOut]:
    conditions = [Agents.project_id == key.project_id]
    if not include_archived:
        conditions.append(Agents.archived.is_(False))
    rows, next_cursor = await paginate(session, Agents, conditions, page)
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/agents/{agent_id}", responses=errors(404), summary="Get an agent")
async def get_agent(agent_id: UUID, key: ReadKey, session: Db) -> AgentOut:
    return _out(await get_or_404(session, Agents, agent_id, key.project_id, "Agent"))


@router.patch("/agents/{agent_id}", responses=errors(404, 409), summary="Update an agent")
async def update_agent(agent_id: UUID, body: AgentUpdate, key: WriteKey, session: Db) -> AgentOut:
    row = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    data = body.model_dump(mode="json", exclude_none=True)
    if "adapter_config" in data:
        data["adapter_config"] = _client_config(data["adapter_config"], row.adapter_config)
    if data.get("adapter", row.adapter) == "prompt":  # no endpoint of its own
        data["endpoint_url"] = f"prompt://{row.id}"
    elif row.adapter == "prompt" and "endpoint_url" not in data:  # leaving prompt needs one
        raise ApiError(422, "endpoint_url_required", "endpoint_url is required for this adapter")
    for field, value in data.items():
        setattr(row, field, value)
    if body.adapter_secrets is not None:
        row.adapter_secrets_encrypted = _encrypt(body.adapter_secrets)
    row.updated_at = datetime.now(UTC)
    await flush(session, _DUPLICATE)
    return _out(row)


@router.post("/agents/{agent_id}/archive", responses=errors(404), summary="Archive an agent")
async def archive_agent(agent_id: UUID, key: WriteKey, session: Db) -> AgentOut:
    row = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    if not row.archived:
        row.archived = True
        row.updated_at = datetime.now(UTC)
        await flush(session, _DUPLICATE)
    return _out(row)


@router.post(
    "/agents/{agent_id}/test-connection",
    responses=errors(404),
    summary="Open the socket, send 1 s of silence, wait up to 10 s for agent audio",
)
async def test_agent_connection(agent_id: UUID, key: WriteKey, session: Db) -> TestConnectionResult:
    row = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    if row.adapter == "prompt":
        return await _check_prompt_agent(session, row)
    target = AgentTarget(
        agent_id=row.id,
        adapter=row.adapter,
        endpoint_url=row.endpoint_url,
        adapter_config=dict(row.adapter_config or {}),
        languages=list(row.languages or []),
        glass_box=row.glass_box,
    )
    return await check_connection(target)


async def _check_prompt_agent(session: AsyncSession, row: Agents) -> TestConnectionResult:
    """One plain chat call ("Hello", no tools) with the active version's model and key."""
    version = await active_version(session, row)
    if version is None:
        return TestConnectionResult(
            ok=False, error="no_active_version", detail="Create a prompt version first"
        )
    try:
        secrets = (
            _secret_box().decrypt(row.adapter_secrets_encrypted.decode())
            if row.adapter_secrets_encrypted
            else {}
        )
    except SecretDecryptError as exc:
        raise ApiError(500, "internal_error", str(exc)) from exc
    try:
        provider = build_chat_provider(
            cast(ProviderName, version.provider),
            api_key=secrets.get("api_key"),
            base_url=version.base_url,
        )
        reply = await provider.chat(
            [
                AgentMessage(role="system", content=version.system_prompt),
                AgentMessage(role="user", content="Hello"),
            ],
            [],
            model=version.model,
            temperature=version.temperature,
            timeout_s=10.0,
        )
    except (AgentLLMError, ValueError) as exc:  # messages never carry the API key
        return TestConnectionResult(ok=False, error="provider_error", detail=str(exc))
    return TestConnectionResult(ok=True, first_audio_ms=reply.latency_ms, protocol=version.provider)
