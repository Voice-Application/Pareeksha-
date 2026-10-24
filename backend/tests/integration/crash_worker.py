"""A consumer process the tests kill with SIGKILL (a real crash, not a simulated exception).

    python -m tests.integration.crash_worker <group> <mode>

Modes:
  normal                 process messages; SIGTERM -> graceful shutdown (exit code 0)
  crash_in_handler       insert the side effect, then SIGKILL itself before the transaction commits
  crash_before_produce   handler commits normally, then SIGKILL itself when the framework is about
                         to produce the output event (after the DB commit, before the offset commit)

Prints ``READY`` once partitions are assigned, and ``HANDLER <event_id>`` on every handler call.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Sequence
from typing import Any

from pareeksha.events.consumer import ConsumerRunner, ConsumerSpec, Ctx, Outgoing
from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import configure_logging, install_stop_signals
from pareeksha.events.schemas import AnyEnvelope
from pareeksha.events.topics import Topics
from tests.integration.support import SETTINGS, completed_payload

GROUP = sys.argv[1]
MODE = sys.argv[2]


def _kill_self() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def _outputs(env: Any) -> list[Outgoing]:
    return [Outgoing(completed_payload(env.payload.call_id))]


async def handle(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    print(f"HANDLER {env.event_id}", flush=True)
    await ctx.tx.execute(
        "INSERT INTO it_side_effects (grp, event_id, note) VALUES (%s, %s, %s)",
        (GROUP, env.event_id, f"pid={os.getpid()}"),
    )
    if MODE == "crash_in_handler":
        _kill_self()
    return _outputs(env)


async def reproduce(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    print(f"REPRODUCE {env.event_id}", flush=True)
    return _outputs(env)


class CrashingProducer(EventProducer):
    async def publish(self, envelope: AnyEnvelope) -> None:
        print("ABOUT_TO_PRODUCE", flush=True)
        _kill_self()


async def main() -> None:
    configure_logging()
    spec = ConsumerSpec(
        group=GROUP, topics=(Topics.AUDIT_REQUESTED,), handler=handle, reproduce=reproduce
    )
    producer_cls = CrashingProducer if MODE == "crash_before_produce" else EventProducer
    producer = producer_cls(SETTINGS.bootstrap_servers, client_id=f"{GROUP}-producer")
    await producer.start()
    runner = ConsumerRunner(spec, SETTINGS, producer=producer)
    install_stop_signals(runner.stop_event)
    task = asyncio.create_task(runner.run())
    await runner.wait_ready()
    print("READY", flush=True)
    await task
    await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
