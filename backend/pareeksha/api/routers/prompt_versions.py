"""Prompt-agent versions: immutable definitions, one active per agent."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.agent_llm import allow_private_urls, check_base_url
from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import ACTIVE_VERSION_KEY, active_version, flush, get_or_404
from pareeksha.api.deps import AUTH_ERRORS, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.db.models import Agents, PromptVersions
from pareeksha.schemas.prompts import PromptVersionCreate, PromptVersionOut, content_hash

router = APIRouter(tags=["prompt-versions"], responses=AUTH_ERRORS)

_CONFLICT = "Prompt version conflict, retry"


def _out(row: PromptVersions) -> PromptVersionOut:
    return PromptVersionOut.model_validate(row, from_attributes=True)


async def _prompt_agent(session: AsyncSession, agent_id: UUID, project_id: UUID) -> Agents:
    agent: Agents = await get_or_404(session, Agents, agent_id, project_id, "Agent")
    if agent.adapter != "prompt":
        raise ApiError(409, "not_a_prompt_agent", "This agent is not a prompt agent")
    return agent


async def _check_url(base_url: str | None) -> None:
    if not base_url:
        return
    try:  # getaddrinfo blocks
        await asyncio.to_thread(check_base_url, base_url, allow_private=allow_private_urls())
    except ValueError as exc:
        raise ApiError(422, "base_url_not_allowed", str(exc)) from exc


def _activate(agent: Agents, version: PromptVersions) -> None:
    """Point the agent at ``version`` and mirror its tools into ``expected_tools``."""
    agent.adapter_config = {
        **cast(dict[str, Any], agent.adapter_config),
        ACTIVE_VERSION_KEY: str(version.id),
    }
    agent.expected_tools = [
        {"name": t["name"], "description": t.get("description", ""), "args_schema": t["parameters"]}
        for t in version.tools
    ]
    agent.updated_at = datetime.now(UTC)


@router.post(
    "/agents/{agent_id}/prompt-versions",
    status_code=201,
    responses={
        **errors(404, 409, 422),
        200: {"model": PromptVersionOut, "description": "identical to the active version"},
    },
    summary="Create a prompt version and make it active",
)
async def create_prompt_version(
    agent_id: UUID, body: PromptVersionCreate, key: WriteKey, session: Db, response: Response
) -> PromptVersionOut:
    agent = await _prompt_agent(session, agent_id, key.project_id)
    await _check_url(body.base_url)
    await session.refresh(agent, with_for_update=True)  # serialise concurrent version numbering
    digest = content_hash(body)
    current = await active_version(session, agent)
    if current is not None and current.content_hash == digest:
        response.status_code = 200
        return _out(current)
    latest = await session.scalar(
        select(func.max(PromptVersions.version)).where(PromptVersions.agent_id == agent_id)
    )
    row = PromptVersions(
        id=uuid.uuid4(),
        project_id=key.project_id,
        agent_id=agent_id,
        version=(latest or 0) + 1,
        content_hash=digest,
        **body.model_dump(mode="json"),
    )
    session.add(row)
    await flush(session, _CONFLICT, refresh=row)
    _activate(agent, row)
    await flush(session, _CONFLICT)
    return _out(row)


@router.get(
    "/agents/{agent_id}/prompt-versions",
    responses=errors(404, 409),
    summary="List prompt versions, newest first",
)
async def list_prompt_versions(agent_id: UUID, key: ReadKey, session: Db) -> list[PromptVersionOut]:
    await _prompt_agent(session, agent_id, key.project_id)
    stmt = (
        select(PromptVersions)
        .where(PromptVersions.agent_id == agent_id)
        .order_by(PromptVersions.version.desc())
    )
    return [_out(r) for r in (await session.scalars(stmt)).all()]


async def _version(session: AsyncSession, agent_id: UUID, version: int) -> PromptVersions:
    row = (
        await session.scalars(
            select(PromptVersions).where(
                PromptVersions.agent_id == agent_id, PromptVersions.version == version
            )
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Prompt version not found", {"version": version})
    return row


@router.get(
    "/agents/{agent_id}/prompt-versions/{version}",
    responses=errors(404, 409),
    summary="Get one prompt version",
)
async def get_prompt_version(
    agent_id: UUID, version: int, key: ReadKey, session: Db
) -> PromptVersionOut:
    await _prompt_agent(session, agent_id, key.project_id)
    return _out(await _version(session, agent_id, version))


@router.post(
    "/agents/{agent_id}/prompt-versions/{version}/activate",
    responses=errors(404, 409, 422),
    summary="Make an existing prompt version the active one",
)
async def activate_prompt_version(
    agent_id: UUID, version: int, key: WriteKey, session: Db
) -> PromptVersionOut:
    agent = await _prompt_agent(session, agent_id, key.project_id)
    row = await _version(session, agent_id, version)
    await _check_url(row.base_url)
    _activate(agent, row)
    await flush(session, _CONFLICT)
    return _out(row)
