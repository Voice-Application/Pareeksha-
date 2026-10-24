"""Enqueue N ``audit.requested`` events into the outbox, one transaction (INFRA-02 proof helper).

    PYTHONPATH=backend DATABASE_URL=postgresql+psycopg://...@localhost:55432/pareeksha \
    python proof/INFRA-02/enqueue_events.py 5
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import psycopg

from pareeksha.events.outbox import enqueue
from pareeksha.events.schemas import AuditRequested, make_envelope
from pareeksha.events.settings import EventSettings


async def main(count: int) -> None:
    settings = EventSettings.from_env()
    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        async with conn.transaction():
            for _ in range(count):
                call_id = uuid.uuid4()
                payload = AuditRequested(
                    call_id=call_id, source="upload", language="kn-IN", recording_ref="blob://demo"
                )
                env = make_envelope(payload, producer="demo@host", correlation_id=str(call_id))
                await enqueue(conn, env)
                print(f"enqueued event_id={env.event_id} key={call_id}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1])))
