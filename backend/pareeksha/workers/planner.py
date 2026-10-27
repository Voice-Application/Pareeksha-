"""``python -m pareeksha.workers.planner``: ``run.requested`` -> run items -> ``call.requested``.

For a matrix / dry-run run the planner expands scenario x persona x noise profile x repeats, for a
regression run it resolves the project's regression tests by status. It inserts one ``run_items``
row per call (idempotent: the table's unique key plus ``ON CONFLICT DO NOTHING``) and emits one
``call.requested`` per still-queued item, keyed by ``run_item_id`` so a run spreads over the
partitions, plus an ``item.status`` progress event for the live view.

Every output event gets the item id as its ``Outgoing.discriminator``, so ids are
``uuid5(run.requested.event_id, "call.requested:<run_item_id>")``: deterministic, so a crash after
the commit and before the produce re-produces exactly the same events (``reproduce=``), which the
simulators deduplicate.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from pareeksha.events.consumer import Ctx, Outgoing, PermanentError, consumer, run_worker
from pareeksha.events.schemas import (
    CallRequested,
    Envelope,
    ProgressEvent,
    RunCompleted,
    RunCompletedSummary,
    RunRequested,
)
from pareeksha.events.topics import Topics
from pareeksha.runs.matrix import Cell, expand_matrix, item_seed

log = logging.getLogger(__name__)

GROUP = "planner"
#: Runs in these states are not planned (cancelled before the planner got to them, or finished).
_DONE = ("cancelled", "completed", "partial", "failed")


async def _regression_cells(
    conn: psycopg.AsyncConnection[Any], run: RunRequested, project_id: uuid.UUID, run_seed: int
) -> list[Cell]:
    """One cell per regression test of the agent whose status is selected.

    A test without a persona or noise profile (``regression_tests`` allows null) falls back to the
    project's oldest persona / noise profile, so the call is still made.
    """
    cur = await conn.execute(
        "SELECT id, scenario_id, persona_id, noise_profile_id FROM regression_tests "
        "WHERE agent_id = %s AND project_id = %s AND status = ANY(%s) ORDER BY created_at, id",
        (run.agent_id, project_id, list(run.regression_statuses)),
    )
    tests = await cur.fetchall()
    default_persona = default_profile = None
    if any(t[2] is None or t[3] is None for t in tests):
        cur = await conn.execute(
            "SELECT id FROM personas WHERE project_id = %s ORDER BY created_at, id LIMIT 1",
            (project_id,),
        )
        row = await cur.fetchone()
        default_persona = row[0] if row else None
        cur = await conn.execute(
            "SELECT id FROM noise_profiles WHERE project_id = %s ORDER BY created_at, id LIMIT 1",
            (project_id,),
        )
        row = await cur.fetchone()
        default_profile = row[0] if row else None
    cells: list[Cell] = []
    for test_id, scenario_id, persona_id, profile_id in tests:
        persona_id = persona_id or default_persona
        profile_id = profile_id or default_profile
        if persona_id is None or profile_id is None:
            raise PermanentError(
                f"regression test {test_id} has no persona or noise profile and the project has "
                "no default to use"
            )
        seed = item_seed(run_seed, scenario_id, persona_id, profile_id, 0, salt=str(test_id))
        cells.append(Cell(scenario_id, persona_id, profile_id, seed, regression_test_id=test_id))
    return cells


async def _insert_items(
    conn: psycopg.AsyncConnection[Any], run_id: uuid.UUID, cells: Sequence[Cell]
) -> None:
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO run_items (run_id, scenario_id, persona_id, noise_profile_id, "
            "regression_test_id, seed) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, scenario_id, persona_id, noise_profile_id, seed) DO NOTHING",
            [
                (
                    run_id,
                    c.scenario_id,
                    c.persona_id,
                    c.noise_profile_id,
                    c.regression_test_id,
                    c.seed,
                )
                for c in cells
            ],
        )


async def _queued_outputs(
    conn: psycopg.AsyncConnection[Any], run_id: uuid.UUID, agent_id: uuid.UUID
) -> list[Outgoing]:
    """``call.requested`` + ``item.status`` for every item that is still waiting to start."""
    cur = await conn.execute(
        "SELECT i.id, i.scenario_id, i.persona_id, i.noise_profile_id, i.seed, "
        "i.regression_test_id, s.title, p.name "
        "FROM run_items i JOIN scenarios s ON s.id = i.scenario_id "
        "JOIN personas p ON p.id = i.persona_id "
        "WHERE i.run_id = %s AND i.status = 'queued' ORDER BY i.created_at, i.id",
        (run_id,),
    )
    outputs: list[Outgoing] = []
    for (
        item_id,
        scenario_id,
        persona_id,
        profile_id,
        seed,
        test_id,
        title,
        persona,
    ) in await cur.fetchall():
        outputs.append(
            Outgoing(
                CallRequested(
                    run_id=run_id,
                    run_item_id=item_id,
                    agent_id=agent_id,
                    scenario_id=scenario_id,
                    persona_id=persona_id,
                    noise_profile_id=profile_id,
                    seed=seed,
                    regression_test_id=test_id,
                ),
                discriminator=str(item_id),
            )
        )
        outputs.append(
            Outgoing(
                ProgressEvent(
                    kind="item.status",
                    run_id=run_id,
                    run_item_id=item_id,
                    status="queued",
                    scenario=title,
                    persona=persona,
                ),
                discriminator=str(item_id),
            )
        )
    return outputs


async def plan(env: Envelope[RunRequested], ctx: Ctx) -> list[Outgoing]:
    """Create the run's items and the events that start them (one DB transaction)."""
    run = env.payload
    cur = await ctx.tx.execute(
        "SELECT status, project_id FROM test_runs WHERE id = %s FOR UPDATE", (run.run_id,)
    )
    row = await cur.fetchone()
    if row is None:
        raise PermanentError(f"run {run.run_id} does not exist")
    status, project_id = row
    if status in _DONE:
        log.info("run %s is %s; nothing to plan", run.run_id, status)
        return []

    if run.kind == "regression":
        cells = await _regression_cells(ctx.tx, run, project_id, run.seed)
    else:
        cells = list(
            expand_matrix(
                run_seed=run.seed,
                scenario_ids=run.scenario_ids,
                persona_ids=run.persona_ids,
                noise_profile_ids=run.noise_profile_ids,
                repeats=run.repeats,
            )
        )
    await _insert_items(ctx.tx, run.run_id, cells)
    await ctx.tx.execute(
        "UPDATE test_runs SET config = config || jsonb_build_object('item_count', %s::int) "
        "WHERE id = %s",
        (len(cells), run.run_id),
    )
    log.info("planned run %s: %d item(s)", run.run_id, len(cells))
    if not cells:
        # An empty regression suite: nothing to call, so the run is finished right away.
        await ctx.tx.execute(
            "UPDATE test_runs SET status = 'completed', finished_at = now(), "
            "started_at = COALESCE(started_at, now()) WHERE id = %s",
            (run.run_id,),
        )
        return [
            Outgoing(
                RunCompleted(
                    run_id=run.run_id,
                    agent_id=run.agent_id,
                    kind=run.kind,
                    status="completed",
                    summary=RunCompletedSummary(
                        item_count=0,
                        evaluated_count=0,
                        error_count=0,
                        suite_passed=True if run.kind == "regression" else None,
                    ),
                )
            ),
            Outgoing(ProgressEvent(kind="run.completed", run_id=run.run_id)),
        ]
    return await _queued_outputs(ctx.tx, run.run_id, run.agent_id)


async def reproduce(env: Envelope[RunRequested], ctx: Ctx) -> list[Outgoing]:
    """A redelivered ``run.requested``: rebuild the events from the items already in the DB."""
    run = env.payload
    cur = await ctx.tx.execute("SELECT status FROM test_runs WHERE id = %s", (run.run_id,))
    row = await cur.fetchone()
    if row is None or row[0] in _DONE:
        return []
    return await _queued_outputs(ctx.tx, run.run_id, run.agent_id)


consumer(group=GROUP, topic=Topics.RUN_REQUESTED, reproduce=reproduce)(plan)


async def main() -> None:
    await run_worker(GROUP)


if __name__ == "__main__":
    asyncio.run(main())
