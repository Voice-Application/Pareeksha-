"""``python -m pareeksha.workers.generator``: the ``generator`` consumer group (API-05).

``scenario.generate.requested`` -> ask the LLM for the drafts -> store them on ``scenario_drafts``
(``ready``, or ``failed`` with the reason). The API polls the row; drafts are reviewed by a human
and saved with ``POST /scenarios:bulk``, never automatically.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.agent_llm.context import prompt_context
from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import Envelope, ScenarioGenerateRequested
from pareeksha.events.topics import MAX_ATTEMPTS, Topics
from pareeksha.llm.base import LLMError, LLMRetryableError
from pareeksha.llm.client import JSONGenerationError, LLMClient, UsageRecord
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.factory import build_provider
from pareeksha.rag.guard import platform_llm_may_see_kb
from pareeksha.rag.questions import (
    generate_questions,
    locate_quote,
    question_scenario,
    sample_passages,
    split_counts,
)
from pareeksha.scenario_gen.generator import AgentBrief, generate_scenarios
from pareeksha.schemas.rag import RagExpectation

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


async def _fail(conn: psycopg.AsyncConnection[Any], draft_id: uuid.UUID, reason: str) -> list[Any]:
    await _finish(conn, draft_id, "failed", [], reason[:MAX_ERROR_CHARS])
    return []


async def _generate_rag(
    conn: psycopg.AsyncConnection[Any],
    p: ScenarioGenerateRequested,
    request: dict[str, Any],
    client: LLMClient,
    attempt: int,
) -> list[Any]:
    """Ground-truth questions from a knowledge base (``request.kind == "rag"``)."""
    kb = await _one(
        conn,
        "SELECT kb.name, kb.description, kb.local_only FROM knowledge_bases kb "
        "JOIN agents a ON a.project_id = kb.project_id WHERE kb.id = %s AND a.id = %s",
        (request["kb_id"], p.agent_id),
    )
    if kb is None:
        return await _fail(conn, p.draft_id, "knowledge base no longer exists")
    if not platform_llm_may_see_kb(kb[2]):  # re-checked: it may have been switched since the POST
        return await _fail(conn, p.draft_id, "local_only: the platform LLM cannot read this KB")
    cur = await conn.execute(
        "SELECT id, filename, text FROM kb_documents WHERE kb_id = %s AND deleted_at IS NULL "
        "ORDER BY created_at, id",
        (request["kb_id"],),
    )
    docs = {d[0]: (d[0], d[1], d[2]) for d in await cur.fetchall()}
    n_answerable, n_unanswerable = split_counts(p.count, float(request["unanswerable_share"]))
    passages = sample_passages(list(docs.values()), n_answerable, random.Random(p.draft_id.int))
    if not passages:
        return await _fail(conn, p.draft_id, "the knowledge base has no text to ask about")
    n_answerable = len(passages)
    try:
        batch = await generate_questions(
            client, kb[0], kb[1], passages, n_answerable, n_unanswerable
        )
    except (JSONGenerationError, LLMConfigError) as exc:
        return await _fail(conn, p.draft_id, str(exc))
    except LLMRetryableError as exc:
        if attempt >= MAX_ATTEMPTS:
            return await _fail(conn, p.draft_id, f"LLM unavailable: {exc}")
        raise
    except LLMError as exc:
        return await _fail(conn, p.draft_id, str(exc))
    drafts: list[dict[str, Any]] = []
    unmatched = 0
    for q in batch.questions:
        question = q.question.strip()
        if not question:
            unmatched += 1
            continue
        if q.answerable:
            assert q.passage is not None  # semantic_check guarantees it
            doc_id = passages[q.passage - 1].document_id
            span = locate_quote(docs[doc_id][2], q.quote)
            if span is None:  # never store a wrong span
                unmatched += 1
                continue
            expectation = RagExpectation(
                source_document_id=doc_id, source_span=span, reference_answer=q.reference_answer
            )
        else:
            expectation = RagExpectation(answerable=False)
        scenario = question_scenario(p.agent_id, question, q.reference_answer, expectation)
        drafts.append(scenario.model_dump(mode="json"))
    await conn.execute(
        "UPDATE scenario_drafts SET request = request || %s WHERE id = %s",
        (Jsonb({"unmatched": unmatched}), p.draft_id),
    )
    await _finish(conn, p.draft_id, "ready", drafts, None)
    return []


async def handle_generate_requested(
    env: Envelope[ScenarioGenerateRequested],
    ctx: Ctx,
    llm_for: Callable[[Callable[[UsageRecord], Any]], LLMClient] = default_llm,
) -> Sequence[Outgoing]:
    p = env.payload
    conn = ctx.tx
    draft = await _one(
        conn, "SELECT status, request FROM scenario_drafts WHERE id = %s FOR UPDATE", (p.draft_id,)
    )
    if draft is None:
        log.warning("draft %s no longer exists", p.draft_id)
        return []
    if draft[0] != "pending":  # a redelivered or replayed request: the answer is already stored
        return []
    agent = await _one(
        conn,
        "SELECT name, description, languages, expected_tools, mandatory_disclosures, "
        "forbidden_phrases, adapter, adapter_config FROM agents WHERE id = %s",
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
            "INSERT INTO api_usage (provider, operation, units, unit_type, cached, est_cost, "
            "project_id) VALUES (%s, 'llm_scenario_gen', %s, 'tokens', %s, %s, "
            "(SELECT project_id FROM agents WHERE id = %s))",
            (
                record.provider.value,
                record.input_tokens + record.output_tokens,
                record.cache_hit,
                record.est_cost,
                p.agent_id,
            ),
        )

    if (draft[1] or {}).get("kind") == "rag":
        return await _generate_rag(conn, p, draft[1], llm_for(sink), ctx.attempt)
    name, description, languages, tools, disclosures, forbidden, adapter, adapter_config = agent
    if adapter == "prompt":  # the ACTIVE version: scenarios are written for what runs next
        version_id = (adapter_config or {}).get("active_version_id")
        row = await _one(
            conn,
            "SELECT system_prompt FROM prompt_versions WHERE id = %s AND agent_id = %s",
            (version_id, p.agent_id),
        )
        description = prompt_context(
            description or "", {"system_prompt": row[0]} if row is not None else None
        )
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
