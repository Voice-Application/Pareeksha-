"""Run-completion reconciler (runs inside the ``finalizer`` worker, every minute).

Finds runs whose items are all terminal but that have no ``finished_at`` (the
``evaluation.completed`` that would have finished them was lost, or the finalizer died between
its claim and the produce of a run whose claim never committed) and completes them: claim +
``run.completed`` into the outbox in ONE transaction. It uses the same atomic claim and the same
per-run event id as the consumer, so a racing finalizer and any number of reconcilers produce
``run.completed`` exactly once. (Run-slot repair, ``active_calls``, is API-03's reconciler.)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import psycopg

from pareeksha.evaluation.handlers import (
    final_status,
    run_completed_outputs,
    run_is_complete,
    summarize_run,
)
from pareeksha.evaluation.pg_stores import PgFinalizerStore, find_completable_runs
from pareeksha.events.outbox import enqueue
from pareeksha.events.runtime import Database
from pareeksha.events.settings import EventSettings

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 60.0
PRODUCER = "finalizer-reconciler"


async def reconcile_once(conn: psycopg.AsyncConnection[Any]) -> list[uuid.UUID]:
    """Complete every completable run; returns the run ids this call completed."""
    done: list[uuid.UUID] = []
    for run_id in await find_completable_runs(conn):
        async with conn.transaction():
            store = PgFinalizerStore(conn)
            state = await store.load_run_state(run_id)
            if state is None or not run_is_complete(state):
                continue
            status, summary = final_status(state), summarize_run(state)
            if not await store.claim_run_completion(run_id, status, summary):
                continue  # the finalizer (or another reconciler) got there first
            for envelope in run_completed_outputs(
                None, run_id, state.agent_id, state.kind, status, summary, producer=PRODUCER
            ):
                await enqueue(conn, envelope)
            done.append(run_id)
    return done


async def run_reconciler(
    settings: EventSettings, stop: asyncio.Event, *, interval: float = INTERVAL_SECONDS
) -> None:
    """Loop until ``stop``; survives database outages (logs and tries again next tick)."""
    db = Database(settings)
    try:
        while not stop.is_set():
            try:
                done = await reconcile_once(await db.connection())
                if done:
                    log.info("reconciler completed %d run(s): %s", len(done), done)
            except Exception:
                log.exception("completion reconciler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)
    finally:
        await db.close()
