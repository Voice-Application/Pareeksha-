"""``python -m pareeksha.workers.indexer``: the ``indexer`` consumer group (RAG lab, Task 5).

``kb.index.requested`` -> chunk the snapshot documents, embed (reusing vectors), store the chunks
and mark the index ``ready``, or ``failed`` with a key-free reason.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import Envelope, KbIndexRequested
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.rag.indexing import EmbedderFor, build_index, default_embedder_for

GROUP = ConsumerGroups.INDEXER.value


async def handle_index_requested(
    env: Envelope[KbIndexRequested],
    ctx: Ctx,
    embedder_for: EmbedderFor = default_embedder_for,
) -> Sequence[Outgoing]:
    await build_index(ctx.tx, env.payload.index_id, embedder_for=embedder_for, attempt=ctx.attempt)
    return []


@consumer(group=GROUP, topic=Topics.KB_INDEX_REQUESTED)
async def handle(env: Envelope[KbIndexRequested], ctx: Ctx) -> Sequence[Outgoing]:
    return await handle_index_requested(env, ctx)


async def main() -> None:
    await run_worker(GROUP)


if __name__ == "__main__":
    asyncio.run(main())
