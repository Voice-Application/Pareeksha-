"""``python -m pareeksha.workers.auditor``: audit.requested -> batch STT -> turns -> call.completed.

Dependencies (speech provider, LLM client, blob store) are built from the environment on first
use, so importing this module needs no keys. The work itself is in ``pareeksha.audit.pipeline``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import cache
from typing import Any

from pareeksha.audit.fetch import fetch_recording
from pareeksha.audit.pipeline import AuditDeps, Auditor
from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import AuditRequested, Envelope
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.factory import build_client
from pareeksha.llm.project_settings import ProjectLLMClients
from pareeksha.speech.registry import get_stt_provider
from pareeksha.storage.blob import blob_store_from_env

GROUP = ConsumerGroups.AUDITOR.value


def _llm_or_none() -> LLMClient | None:
    """The role-detection LLM, or ``None`` when its key is not configured (heuristic only)."""
    try:
        settings = LLMSettings()
        if not settings.api_key:  # the property raises LLMConfigError when the key is missing
            return None
        return build_client(settings)
    except LLMConfigError:
        return None


_project_llms = ProjectLLMClients()


async def _llm_for_project(conn: Any, project_id: Any) -> LLMClient | None:
    """The project's own role-detection client, or ``None`` (use the environment's)."""
    if project_id is None:
        return None
    resolved = await _project_llms.resolve(conn, project_id)
    return None if resolved is None else resolved.client()


@cache
def get_auditor() -> Auditor:
    return Auditor(
        AuditDeps(
            blobs=blob_store_from_env(),
            stt_factory=get_stt_provider,
            llm=_llm_or_none(),
            fetch=fetch_recording,
            llm_for=_llm_for_project,
        )
    )


async def _reproduce(env: Envelope[AuditRequested], ctx: Ctx) -> Sequence[Outgoing]:
    return await get_auditor().reproduce(env, ctx)


@consumer(
    group=GROUP,
    topic=Topics.AUDIT_REQUESTED,
    reproduce=_reproduce,
    # a batch transcription takes a while (Gnani polls a job, 10 s minimum)
    max_poll_interval_ms=900_000,
)
async def handle_audit_requested(env: Envelope[AuditRequested], ctx: Ctx) -> Sequence[Outgoing]:
    return await get_auditor().handle(env, ctx)


async def main() -> None:
    try:
        await run_worker(GROUP)
    finally:
        await _project_llms.aclose()


if __name__ == "__main__":
    asyncio.run(main())
