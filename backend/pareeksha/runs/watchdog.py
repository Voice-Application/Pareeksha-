"""Run items nothing will move on any more: give them up so their run can finish (TRD 10.6).

Two passes, run by ``pareeksha.workers.reconciler`` every minute before the slot counter is
recomputed. Both end an item through ``store.give_up_item`` (the simulator's own path: one
transaction, conditional on the item's current status, slot released once, an ``infra_error``
call, an ``item.status`` progress event in the outbox); the run is then finished by the
completion reconciler like any run whose last item errored. Running a pass twice, or on two
replicas, is harmless: the second ``give_up_item`` finds the item terminal and does nothing.

* ``give_up_dead_lettered``: an open ``dead_letters`` row for a run item's ``call.requested``
  (or its ``call.completed``) means no consumer will process that item again unless an operator
  replays it. This covers what the simulator could not give up itself: an unparseable message,
  a database fault while giving up, an evaluation that was dead-lettered.
* ``sweep_stale``: the safety net for items that hold a slot while no message for them is alive
  anywhere (a message lost, a dead letter discarded, a worker crash-looping on the same message:
  the attempt counter never grows then). Nothing advances while a call runs, so an item's clock
  is its call's ``started_at``, which a redelivery keeps (``open_call`` is ``ON CONFLICT DO
  NOTHING``); an item still ``connecting`` without a call row is timed from when this process
  first saw it so.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg

from pareeksha.events.topics import MAX_ATTEMPTS, RETRY_DELAY_SECONDS, Topics
from pareeksha.simulation import store

log = logging.getLogger(__name__)

#: ``max_poll_interval_ms`` of the simulator consumer: a delivery still running after this is
#: taken from its worker by Kafka and redelivered, so it bounds one live attempt.
SIMULATOR_MAX_DELIVERY_S = 2_400
#: Longest healthy life of a slot-holding item from its call's start: every attempt at its
#: longest plus the retry waits (3 x 40 min + 30 s + 5 min, about 2 h 6 min). The default
#: threshold doubles it to leave room for a backlog of calls ahead of a retried message on its
#: partition. Override with ``RUN_ITEM_STALE_AFTER_S``.
HEALTHY_ITEM_LIFETIME_S = MAX_ATTEMPTS * SIMULATOR_MAX_DELIVERY_S + sum(
    RETRY_DELAY_SECONDS.values()
)
DEFAULT_STALE_AFTER_S = 2 * HEALTHY_ITEM_LIFETIME_S  # 15 060 s, about 4 h 11 min
#: Items given up per pass (each in its own short transaction).
BATCH = 100

_UUID_RE = "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

# Literal 'open' so the partial index dead_letters_open applies; the regex guard keeps a
# malformed payload from failing the cast (and the whole pass).
_DEAD_LETTERED_SQL = f"""
SELECT ri.id, dl.original_topic, dl.error
  FROM dead_letters dl
  JOIN run_items ri ON ri.id = CASE
       WHEN dl.envelope->'payload'->>'run_item_id' ~ '{_UUID_RE}'
       THEN (dl.envelope->'payload'->>'run_item_id')::uuid END
 WHERE dl.status = 'open'
   AND ((dl.original_topic = %(requested)s
         AND ri.status IN ('queued', 'connecting', 'in_progress'))
     OR (dl.original_topic = %(completed)s AND ri.status IN ('completed', 'evaluating')))
 ORDER BY dl.failed_at
 LIMIT %(limit)s
"""

# Driven from the runs that can hold slots so run_items_run_status serves the item lookup.
_ACTIVE_ITEMS_SQL = """
SELECT ri.id, c.started_at, now()
  FROM test_runs r
  JOIN run_items ri ON ri.run_id = r.id AND ri.status IN ('connecting', 'in_progress')
  LEFT JOIN calls c ON c.run_item_id = ri.id
 WHERE r.status IN ('running', 'cancelled')
"""


@dataclass(frozen=True, slots=True)
class GivenUp:
    run_item_id: uuid.UUID
    status: str
    reason: str


async def give_up_dead_lettered(
    conn: psycopg.AsyncConnection[Any], *, limit: int = BATCH
) -> list[GivenUp]:
    """Give up items whose ``call.requested`` / ``call.completed`` sits open in the DLQ."""
    cur = await conn.execute(
        _DEAD_LETTERED_SQL,
        {
            "requested": Topics.CALL_REQUESTED.value,
            "completed": Topics.CALL_COMPLETED.value,
            "limit": limit,
        },
    )
    done: list[GivenUp] = []
    for item_id, topic, error in await cur.fetchall():
        if topic == Topics.CALL_REQUESTED.value:
            reason = f"infra: dead-lettered: {error}"
            statuses = frozenset({"queued", *store.SLOT_STATUSES})
        else:
            reason = f"judge: dead-lettered: {error}"
            statuses = frozenset({"completed", "evaluating"})
        status = await store.give_up_item(conn, item_id, reason, statuses=statuses)
        if status is not None:
            done.append(GivenUp(item_id, status, reason))
    _log(done, "gave up dead-lettered run item")
    return done


@dataclass
class StaleSweep:
    """``sweep_stale`` with the memory it needs for items that have no call row yet."""

    stale_after_s: float = DEFAULT_STALE_AFTER_S
    limit: int = BATCH
    #: ``connecting`` items without a call, and when this sweep first saw each of them so.
    first_seen: dict[uuid.UUID, datetime] = field(default_factory=dict)

    async def run(
        self, conn: psycopg.AsyncConnection[Any], *, now: datetime | None = None
    ) -> list[GivenUp]:
        """Give up slot-holding items older than ``stale_after_s``; ``now`` is for tests."""
        cur = await conn.execute(_ACTIVE_ITEMS_SQL)
        rows = await cur.fetchall()
        if not rows:
            self.first_seen = {}
            return []
        if now is None:
            now = rows[0][2]
        cutoff = now - timedelta(seconds=self.stale_after_s)
        seen: dict[uuid.UUID, datetime] = {}
        stale: list[tuple[datetime, uuid.UUID]] = []
        for item_id, started_at, _ in rows:
            if started_at is None:
                started_at = seen[item_id] = self.first_seen.get(item_id, now)
            if started_at < cutoff:
                stale.append((started_at, item_id))
        self.first_seen = seen
        minutes = round(self.stale_after_s / 60)
        reason = f"infra: stale: no progress for {minutes} minutes"
        done: list[GivenUp] = []
        for _, item_id in sorted(stale)[: self.limit]:
            status = await store.give_up_item(conn, item_id, reason, stale_before=cutoff)
            if status is not None:
                done.append(GivenUp(item_id, status, reason))
                self.first_seen.pop(item_id, None)
        _log(done, "gave up stale run item")
        return done


def _log(done: list[GivenUp], message: str) -> None:
    for g in done:
        log.warning(
            message,
            extra={"run_item_id": str(g.run_item_id), "status": g.status, "reason": g.reason},
        )
