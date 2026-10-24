"""``python -m pareeksha.workers.evaluator``: call.completed -> judge -> evaluation.completed.

Wires the framework-independent handler of EVAL-03 (``evaluation.handlers``) to the consumer
framework with the Postgres store. Uploaded, imported and simulated calls take the same path, so an
audit is judged by the same rubric version as a simulation (FR-AU-4).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import cache

from pareeksha.evaluation.handlers import handle_call_completed
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.evaluation.store import PgEvaluatorStore
from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import CallCompleted, Envelope, EvaluationCompleted, ProgressEvent
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.llm.client import LLMClient
from pareeksha.llm.factory import build_client

GROUP = ConsumerGroups.EVALUATOR.value


@cache
def get_client() -> LLMClient:
    return build_client()


async def evaluate(
    env: Envelope[CallCompleted], ctx: Ctx, client: LLMClient | None = None
) -> list[Outgoing]:
    """Judge the call inside ``ctx.tx`` and return the events to produce."""
    envelopes = await handle_call_completed(
        env, PgEvaluatorStore(ctx.tx), client or get_client(), producer=GROUP
    )
    return [Outgoing(e.payload, correlation_id=e.correlation_id) for e in envelopes]


async def reproduce(env: Envelope[CallCompleted], ctx: Ctx) -> list[Outgoing]:
    """Duplicate delivery: the evaluation is already stored; produce its events again."""
    cur = await ctx.tx.execute(
        "SELECT e.id, e.status, e.overall_score, e.passed, e.critical_failure, "
        "e.needs_human_review, e.failure_types, c.agent_id, ri.run_id, c.run_item_id "
        "FROM evaluations e JOIN rubric_versions rv ON rv.id = e.rubric_version_id "
        "JOIN calls c ON c.id = e.call_id LEFT JOIN run_items ri ON ri.id = c.run_item_id "
        "WHERE e.call_id = %s AND rv.version = %s",
        (env.payload.call_id, RUBRIC_VERSION),
    )
    row = await cur.fetchone()
    if row is None:
        return []
    (eid, status, score, passed, critical, review, failure_types, agent_id, run_id, item_id) = row
    done = EvaluationCompleted(
        call_id=env.payload.call_id,
        evaluation_id=eid,
        status="ok" if status == "ok" else "judge_error",
        agent_id=agent_id,
        run_id=run_id,
        run_item_id=item_id,
        overall_score=None if score is None else float(score),
        passed=passed,
        critical_failure=critical,
        needs_human_review=review,
        failure_types=list(failure_types),
    )
    out = [Outgoing(done, correlation_id=env.correlation_id)]
    if status == "ok" and score is not None and passed is not None:
        progress = ProgressEvent(
            kind="call.evaluated",
            run_id=run_id,
            call_id=env.payload.call_id,
            run_item_id=item_id,
            overall_score=float(score),
            passed=passed,
            critical_failure=critical,
        )
        out.append(Outgoing(progress, correlation_id=env.correlation_id))
    return out


@consumer(
    group=GROUP,
    topic=Topics.CALL_COMPLETED,
    reproduce=reproduce,
    # a judge call plus its repair retry can take a few minutes
    max_poll_interval_ms=600_000,
)
async def handle_call_completed_event(env: Envelope[CallCompleted], ctx: Ctx) -> Sequence[Outgoing]:
    return await evaluate(env, ctx)


async def main() -> None:
    await run_worker(GROUP)


if __name__ == "__main__":
    asyncio.run(main())
