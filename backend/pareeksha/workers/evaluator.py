"""``python -m pareeksha.workers.evaluator``: consume ``call.completed`` -> judge -> evaluation.

Registered with the INFRA-02 consumer framework as group ``evaluator``. Per message the framework
opens a transaction, inserts ``(evaluator, event_id)`` into ``processed_events`` and calls the
handler with ``ctx.tx``; the evaluation rows are written in that same transaction, so:

* a duplicate delivery finds the ``processed_events`` row, skips the judge and re-produces the
  stored evaluation's events (same event ids);
* a crash before the commit leaves nothing behind and the redelivered message is judged once;
* a crash after the commit but before the offset commit takes the duplicate path above.

``evaluations`` also has ``UNIQUE (call_id, rubric_version_id)`` and a deterministic row id, so
even two different ``call.completed`` events for one call cannot create two rows.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pareeksha.evaluation.handlers import (
    CallNotFoundError,
    handle_call_completed,
    reproduce_call_completed,
)
from pareeksha.evaluation.pg_stores import PgEvaluatorStore, RubricNotFoundError, mark_evaluating
from pareeksha.events.consumer import (
    Ctx,
    Outgoing,
    PermanentError,
    RetryableError,
    consumer,
    run_worker,
)
from pareeksha.events.runtime import Database
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.llm.base import LLMPermanentError, LLMRetryableError
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMConfigError
from pareeksha.llm.factory import build_client
from pareeksha.llm.project_settings import ProjectLLMClients
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.workers._outgoing import to_outgoing

log = logging.getLogger(__name__)

GROUP = ConsumerGroups.EVALUATOR

_client: LLMClient | None = None
_usage: ApiUsageSink | None = None
_status_db: Database | None = None
_injected = False  # set_client was given a client: it wins over per-project settings
#: Providers of projects that override the environment's LLM settings (see get_client).
_project_llms = ProjectLLMClients()


def set_client(
    client: LLMClient | None,
    usage: ApiUsageSink | None = None,
    status_db: Database | None = None,
) -> None:
    """Install the judge client (tests and the crash worker inject a provider here)."""
    global _client, _usage, _status_db, _injected
    _client, _usage, _status_db = client, usage, status_db
    _injected = client is not None


async def _mark_evaluating(call_id: Any) -> None:
    """Best effort ``completed -> evaluating`` on its own connection (visible during the judge
    call); the evaluation commit moves the item on, so a failure here is only logged."""
    global _status_db
    try:
        if _status_db is None:
            _status_db = Database(EventSettings.from_env())
        await mark_evaluating(await _status_db.connection(), call_id)
    except Exception:
        log.warning("could not mark run item evaluating", exc_info=True)


def get_usage() -> ApiUsageSink:
    global _usage
    if _usage is None:
        _usage = ApiUsageSink(EventSettings.from_env())
    return _usage


async def _project_client(conn: Any, call_id: Any) -> LLMClient | None:
    """The judge client for a project with its own LLM settings (``PUT /settings/llm``), else
    ``None`` (use the process-wide environment client). Skipped when a client was injected."""
    if _injected:
        return None
    cur = await conn.execute("SELECT project_id FROM calls WHERE id = %s", (call_id,))
    found = await cur.fetchone()
    if found is None:
        return None
    resolved = await _project_llms.resolve(conn, found[0])
    return None if resolved is None else resolved.client(get_usage())


def get_client() -> tuple[LLMClient, ApiUsageSink]:
    """The process-wide judge client (provider from ``LLM_PROVIDER``, DeepSeek by default)."""
    global _client
    usage = get_usage()
    if _client is None:
        _client = build_client(usage_sink=usage)
    return _client, usage


async def reproduce(env: Any, ctx: Ctx) -> list[Outgoing]:
    """Duplicate delivery: read-only, no judge call."""
    return to_outgoing(await reproduce_call_completed(env, PgEvaluatorStore(ctx.tx)))


@consumer(group=GROUP, topic=Topics.CALL_COMPLETED, reproduce=reproduce)
async def on_call_completed(env: Any, ctx: Ctx) -> list[Outgoing]:
    try:
        project_client = await _project_client(ctx.tx, env.payload.call_id)
    except LLMConfigError as exc:  # the project's own settings are unusable: retrying cannot help
        raise PermanentError(f"judge: {exc}") from exc
    if project_client is None:
        client, usage = get_client()
    else:
        client, usage = project_client, get_usage()
    store = PgEvaluatorStore(ctx.tx)
    await _mark_evaluating(env.payload.call_id)
    try:
        with usage.scope(run_id=env.payload.run_id, call_id=env.payload.call_id):
            envelopes = await handle_call_completed(env, store, client)
    except CallNotFoundError as exc:
        raise PermanentError(str(exc)) from exc
    except RubricNotFoundError as exc:
        raise RetryableError(str(exc)) from exc
    except LLMPermanentError as exc:
        raise PermanentError(f"judge: {exc}") from exc
    except LLMRetryableError as exc:
        raise RetryableError(f"judge: {exc}") from exc
    return to_outgoing(envelopes)


async def main() -> None:
    try:
        await run_worker(str(GROUP))
    finally:
        if _client is not None:
            await _client.aclose()
        await _project_llms.aclose()
        if _usage is not None:
            await _usage.close()
        if _status_db is not None:
            await _status_db.close()


if __name__ == "__main__":
    asyncio.run(main())
