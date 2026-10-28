"""``python -m pareeksha.workers.generator``: the ``generator`` consumer group (API-05).

``scenario.generate.requested`` -> ask the LLM for the drafts -> store them on ``scenario_drafts``
(``ready``, or ``failed`` with the reason). The API polls the row; drafts are reviewed by a human
and saved with ``POST /scenarios:bulk``, never automatically.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import Envelope, ScenarioGenerateRequested
from pareeksha.events.topics import MAX_ATTEMPTS, Topics
from pareeksha.llm.base import LLMError, LLMRetryableError
from pareeksha.llm.client import JSONGenerationError, LLMClient, UsageRecord
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.factory import build_provider
from pareeksha.scenario_gen.generator import AgentBrief, generate_scenarios

log = logging.getLogger(__name__)
GROUP = "generator"
MAX_ERROR_CHARS = 500


@lru_cache(maxsize=1)
def _llm_parts() -> tuple[Any, LLMSettings]:
    settings = LLMSettings()
    return build_provider(settings), settings


def default_llm(sink: Callable[[UsageRecord], Any]) -> LLMClient:
    provider, settings = _llm_parts()
    return LLMClient(provider, settings, usage_sink=sink)


async def _one(conn: psycopg.AsyncConnection[Any], sql: str, params: tuple[Any, ...]) -> Any:
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def _finish(
    conn: psycopg.AsyncConnection[Any],
    draft_id: uuid.UUID,
    status: str,
    drafts: list[dict[str, Any]],
    error: str | None,
) -> None:
    await conn.execute(
        "UPDATE scenario_drafts SET status = %s, drafts = %s, error = %s WHERE id = %s",
        (status, Jsonb(drafts), error, draft_id),
    )


async def handle_generate_requested(
    env: Envelope[ScenarioGenerateRequested],
    ctx: Ctx,
    llm_for: Callable[[Callable[[UsageRecord], Any]], LLMClient] = default_llm,
) -> Sequence[Outgoing]:
    p = env.payload
    conn = ctx.tx
    draft = await _one(
        conn, "SELECT status FROM scenario_drafts WHERE id = %s FOR UPDATE", (p.draft_id,)
    )
    if draft is None:
        log.warning("draft %s no longer exists", p.draft_id)
        return []
    if draft[0] != "pending":  # a redelivered or replayed request: the answer is already stored
        return []
    agent = await _one(
        conn,
        "SELECT name, description, languages, expected_tools, mandatory_disclosures, "
        "forbidden_phrases FROM agents WHERE id = %s",
        (p.agent_id,),
    )
    if agent is None:  # pragma: no cover - the FK cascade removes the draft with its agent
        await _finish(conn, p.draft_id, "failed", [], "agent no longer exists")
        return []
    cur = await conn.execute(
        "SELECT title FROM scenarios WHERE agent_id = %s OR agent_id IS NULL ORDER BY created_at "
        "DESC LIMIT 60",
        (p.agent_id,),
    )
    titles = [t for (t,) in await cur.fetchall()]

    async def sink(record: UsageRecord) -> None:
        await conn.execute(
            "INSERT INTO api_usage (provider, operation, units, unit_type, cached, est_cost) "
            "VALUES (%s, 'llm_scenario_gen', %s, 'tokens', %s, %s)",
            (
                record.provider.value,
                record.input_tokens + record.output_tokens,
                record.cache_hit,
                record.est_cost,
            ),
        )

    name, description, languages, tools, disclosures, forbidden = agent
    brief = AgentBrief(
        name=name,
        description=description,
        languages=languages,
        tools=tools,
        disclosures=disclosures,
        forbidden=forbidden,
    )
    try:
        generated = await generate_scenarios(llm_for(sink), brief, p.count, p.mix, titles)
    except (JSONGenerationError, LLMConfigError) as exc:
        # retrying cannot fix an answer the model keeps getting wrong or a missing key
        await _finish(conn, p.draft_id, "failed", [], str(exc)[:MAX_ERROR_CHARS])
        return []
    except LLMRetryableError as exc:
        if ctx.attempt >= MAX_ATTEMPTS:  # the framework would dead-letter it next
            await _finish(
                conn, p.draft_id, "failed", [], f"LLM unavailable: {exc}"[:MAX_ERROR_CHARS]
            )
            return []
        raise
    except LLMError as exc:
        await _finish(conn, p.draft_id, "failed", [], str(exc)[:MAX_ERROR_CHARS])
        return []
    drafts = [s.model_dump(mode="json") for s in generated.scenarios]
    await _finish(conn, p.draft_id, "ready", drafts, None)
    return []


@consumer(group=GROUP, topic=Topics.SCENARIO_GENERATE_REQUESTED)
async def handle(env: Envelope[ScenarioGenerateRequested], ctx: Ctx) -> Sequence[Outgoing]:
    return await handle_generate_requested(env, ctx)


async def main() -> None:
    await run_worker(GROUP)


if __name__ == "__main__":
    asyncio.run(main())
