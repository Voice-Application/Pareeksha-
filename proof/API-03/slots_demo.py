"""Run inside the backend image: 12 simulators race for the slots of one run.

    python slots_demo.py <run_id>

Each "simulator" has its own Postgres connection and calls ``start_item`` for a different run
item, like 12 workers receiving 12 ``call.requested`` messages at once. With the run's
``max_concurrency`` of 3, exactly 3 take a slot and 9 are throttled.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from collections import Counter

import psycopg

from pareeksha.events.settings import libpq_url
from pareeksha.runs.slots import StartResult, start_item


async def main(run_id: uuid.UUID) -> None:
    dsn = libpq_url(os.environ["DATABASE_URL"])
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cur = await conn.execute(
            "SELECT id FROM run_items WHERE run_id = %s AND status = 'queued' ORDER BY id",
            (run_id,),
        )
        items = [row[0] for row in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT config->>'max_concurrency' FROM test_runs WHERE id = %s", (run_id,)
        )
        row = await cur.fetchone()
        assert row is not None
        print(f"run {run_id}: {len(items)} queued items, max_concurrency={row[0]}")

    async def simulator(item: uuid.UUID) -> StartResult:
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as c:
            return await start_item(c, run_id, item)

    results = await asyncio.gather(*[simulator(i) for i in items])
    print("start_item results:", dict(Counter(r.value for r in results)))
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cur = await conn.execute(
            "SELECT active_calls, status FROM test_runs WHERE id = %s", (run_id,)
        )
        print("test_runs (active_calls, status):", await cur.fetchone())
        cur = await conn.execute(
            "SELECT status, count(*) FROM run_items WHERE run_id = %s GROUP BY status ORDER BY 1",
            (run_id,),
        )
        print("run_items by status:", await cur.fetchall())


asyncio.run(main(uuid.UUID(sys.argv[1])))
