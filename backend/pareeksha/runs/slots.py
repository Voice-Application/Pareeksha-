"""Per-run concurrency slots (TRD section 10.6) and the reconciler that heals leaked ones.

``test_runs.active_calls`` counts the calls a run has in flight; ``config->>'max_concurrency'``
is the cap. A simulator calls ``start_item`` before it starts a call and ``release_slot`` in the
transaction that saves the finished call::

    result = await start_item(conn, run_id, run_item_id)
    if result is StartResult.THROTTLED:
        raise Throttled(...)          # consumer framework: retry.30s, attempt unchanged
    if result is StartResult.SKIPPED:
        return []                     # cancelled / already finished: nothing to do
    ...                               # simulate the call
    await release_slot(conn, run_id)  # same transaction as saving the call

``start_item`` takes the slot and marks the item ``connecting`` in ONE transaction, so the counter
and the items it counts cannot disagree after a crash; a redelivered message finds the item
already active and resumes it without taking a second slot (``StartResult.RESUMED``).
``reconcile_slots`` recomputes the counter from ``run_items`` for runs where they differ, which
repairs whatever a bug or a manual change left behind.

All functions take an open psycopg async connection. In a consumer handler that is
``ctx.tx`` (the framework commits); ``start_item`` and ``reconcile_slots`` open their own
transaction (a savepoint inside an open one) because they lock rows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psycopg

log = logging.getLogger(__name__)

#: Item statuses that hold a slot. ``completed`` (call saved) and later do not.
ACTIVE_ITEM_STATUSES = ("connecting", "in_progress")
#: TRD 10.6, atomic: no row back means the run is at its cap. A run whose config lacks
#: ``max_concurrency`` falls back to 3, the API default (``RunConfig``).
_TAKE_SLOT_SQL = (
    "UPDATE test_runs SET active_calls = active_calls + 1 "
    "WHERE id = %s AND active_calls < COALESCE((config->>'max_concurrency')::int, 3) "
    "RETURNING active_calls"
)


class StartResult(StrEnum):
    TAKEN = "taken"  # new slot taken, item is now `connecting`
    RESUMED = "resumed"  # redelivery: the item already holds its slot
    THROTTLED = "throttled"  # run is at its cap: retry later, attempt unchanged
    SKIPPED = "skipped"  # item cancelled / finished / unknown: do not simulate


async def take_slot(conn: psycopg.AsyncConnection[Any], run_id: uuid.UUID) -> bool:
    """TRD 10.6: increment ``active_calls`` unless the run is at its ``max_concurrency`` cap.

    One atomic statement, so concurrent simulators can never push the counter past the cap.
    """
    cur = await conn.execute(_TAKE_SLOT_SQL, (run_id,))
    return await cur.fetchone() is not None


async def release_slot(conn: psycopg.AsyncConnection[Any], run_id: uuid.UUID) -> None:
    """Give a slot back (never below zero). Call in the transaction that saves the call."""
    await conn.execute(
        "UPDATE test_runs SET active_calls = GREATEST(active_calls - 1, 0) WHERE id = %s",
        (run_id,),
    )


async def start_item(
    conn: psycopg.AsyncConnection[Any], run_id: uuid.UUID, run_item_id: uuid.UUID
) -> StartResult:
    """Take a slot for ``run_item_id`` and mark it ``connecting`` (one transaction).

    The run row is locked first, then the item, so ``start_item`` and ``reconcile_slots`` and
    other simulators serialize on the run in the same order (no deadlocks). The first start of a
    run also moves it ``queued -> running``.
    """
    async with conn.transaction():
        cur = await conn.execute(
            "SELECT status FROM test_runs WHERE id = %s FOR UPDATE",
            (run_id,),
        )
        run = await cur.fetchone()
        cur = await conn.execute(
            "SELECT status FROM run_items WHERE id = %s AND run_id = %s FOR UPDATE",
            (run_item_id, run_id),
        )
        item = await cur.fetchone()
        if run is None or item is None:
            return StartResult.SKIPPED
        if item[0] in ACTIVE_ITEM_STATUSES:
            return StartResult.RESUMED
        if item[0] != "queued" or run[0] in ("cancelled", "completed", "partial", "failed"):
            return StartResult.SKIPPED
        if not await take_slot(conn, run_id):
            return StartResult.THROTTLED
        await conn.execute(
            "UPDATE run_items SET status = 'connecting', attempts = attempts + 1 WHERE id = %s",
            (run_item_id,),
        )
        await conn.execute(
            "UPDATE test_runs SET status = 'running', started_at = COALESCE(started_at, now()) "
            "WHERE id = %s AND status = 'queued'",
            (run_id,),
        )
        return StartResult.TAKEN


@dataclass(frozen=True, slots=True)
class SlotRepair:
    run_id: uuid.UUID
    was: int
    now: int


async def reconcile_slots(conn: psycopg.AsyncConnection[Any]) -> list[SlotRepair]:
    """Set ``active_calls`` to the number of items that really hold a slot, where they differ.

    Each run is repaired in its own short transaction: lock the run row (the same lock
    ``take_slot`` needs), then count in a separate statement so the count sees every slot that
    committed before the lock was granted. Returns the repairs made.
    """
    cur = await conn.execute(
        "SELECT r.id FROM test_runs r WHERE r.active_calls <> ("
        "  SELECT count(*) FROM run_items i WHERE i.run_id = r.id AND i.status = ANY(%s))",
        (list(ACTIVE_ITEM_STATUSES),),
    )
    suspects = [row[0] for row in await cur.fetchall()]
    repairs: list[SlotRepair] = []
    for run_id in suspects:
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT active_calls FROM test_runs WHERE id = %s FOR UPDATE", (run_id,)
            )
            row = await cur.fetchone()
            if row is None:
                continue
            cur = await conn.execute(
                "SELECT count(*) FROM run_items WHERE run_id = %s AND status = ANY(%s)",
                (run_id, list(ACTIVE_ITEM_STATUSES)),
            )
            counted = await cur.fetchone()
            assert counted is not None
            actual = int(counted[0])
            if actual != row[0]:
                await conn.execute(
                    "UPDATE test_runs SET active_calls = %s WHERE id = %s", (actual, run_id)
                )
                repairs.append(SlotRepair(run_id, int(row[0]), actual))
    for repair in repairs:
        log.warning(
            "repaired run slot counter",
            extra={"run_id": str(repair.run_id), "was": repair.was, "now": repair.now},
        )
    return repairs
