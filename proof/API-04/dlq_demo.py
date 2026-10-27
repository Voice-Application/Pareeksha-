"""Run inside the backend image: put a message on the bus that its consumer cannot handle.

    python dlq_demo.py

Writes a ``run.requested`` event for a run that does not exist to the outbox. The outbox relay
publishes it, the planner raises a permanent error (the run is unknown), the framework sends it to
``pareeksha.dlq.v1`` and the DLQ recorder copies it into ``dead_letters``: the row GET /dlq lists.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import psycopg

from pareeksha.events.outbox import enqueue
from pareeksha.events.schemas import RunRequested, make_envelope
from pareeksha.events.settings import libpq_url


async def main() -> None:
    payload = RunRequested(
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind="matrix",
        scenario_ids=[uuid.uuid4()],
        persona_ids=[uuid.uuid4()],
        noise_profile_ids=[uuid.uuid4()],
        repeats=1,
        seed=1,
    )
    envelope = make_envelope(payload, producer="proof-api04", correlation_id=str(payload.run_id))
    async with await psycopg.AsyncConnection.connect(libpq_url(os.environ["DATABASE_URL"])) as conn:
        await enqueue(conn, envelope)
        await conn.commit()
    print(f"enqueued run.requested for unknown run {payload.run_id} (event {envelope.event_id})")


asyncio.run(main())
