"""``python -m pareeksha.workers.finalizer``: ``evaluation.completed`` -> ``run.completed`` once.

Registered with the INFRA-02 consumer framework as group ``finalizer``. When the evaluation that
just finished was the run's last open item, ``PgFinalizerStore.claim_run_completion`` (one atomic
``UPDATE ... WHERE finished_at IS NULL ... RETURNING``) lets exactly one handler call emit
``run.completed``, whatever the number of finalizer instances or redeliveries. The event id is
``uuid5(run_id, "run.completed")``, so even a re-emission after a crash is a duplicate downstream.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pareeksha.evaluation.handlers import (
    handle_evaluation_completed,
    reproduce_run_completed,
)
from pareeksha.evaluation.pg_stores import PgFinalizerStore
from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.workers._outgoing import to_outgoing

GROUP = ConsumerGroups.FINALIZER


async def reproduce(env: Any, ctx: Ctx) -> list[Outgoing]:
    """Duplicate delivery: re-emit ``run.completed`` if the run is already finished."""
    return to_outgoing(await reproduce_run_completed(env, PgFinalizerStore(ctx.tx)))


@consumer(group=GROUP, topic=Topics.EVALUATION_COMPLETED, reproduce=reproduce)
async def on_evaluation_completed(env: Any, ctx: Ctx) -> list[Outgoing]:
    return to_outgoing(await handle_evaluation_completed(env, PgFinalizerStore(ctx.tx)))


async def main() -> None:
    await run_worker(str(GROUP))


if __name__ == "__main__":
    asyncio.run(main())
