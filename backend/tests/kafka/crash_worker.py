"""An evaluator-like consumer process that the Kafka suite kills with SIGKILL.

    python -m tests.kafka.crash_worker <group> <mode>      (env: QA_DATABASE_URL)

Modes:
  normal                process messages; SIGTERM -> graceful shutdown (exit code 0)
  crash_in_handler      INSERT the evaluation, then SIGKILL before the transaction commits
  crash_before_produce  the handler commits, then SIGKILL as the framework is about to produce the
                        output event (after the DB commit, before the offset commit)

Prints ``READY`` once partitions are assigned and ``HANDLER <event_id>`` on every handler call.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Sequence
from typing import Any

from pareeksha.events.consumer import ConsumerRunner, Ctx, Outgoing
from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import configure_logging, install_stop_signals
from pareeksha.events.schemas import AnyEnvelope
from pareeksha.events.topics import Topics
from tests.kafka.kit import evaluate, evaluate_again, settings_for, spec_for

GROUP = sys.argv[1]
MODE = sys.argv[2]


def _kill_self() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


async def handle(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    print(f"HANDLER {env.event_id}", flush=True)
    outputs = await evaluate(env, ctx)
    if MODE == "crash_in_handler":
        _kill_self()
    return outputs


async def reproduce(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    print(f"REPRODUCE {env.event_id}", flush=True)
    return await evaluate_again(env, ctx)


class CrashingProducer(EventProducer):
    async def publish(self, envelope: AnyEnvelope) -> None:
        print("ABOUT_TO_PRODUCE", flush=True)
        _kill_self()


async def main() -> None:
    configure_logging()
    settings = settings_for(os.environ["QA_DATABASE_URL"])
    spec = spec_for(GROUP, Topics.CALL_COMPLETED, handle, reproduce)
    producer_cls = CrashingProducer if MODE == "crash_before_produce" else EventProducer
    producer = producer_cls(settings.bootstrap_servers, client_id=f"{GROUP}-producer")
    await producer.start()
    runner = ConsumerRunner(spec, settings, producer=producer)
    install_stop_signals(runner.stop_event)
    task = asyncio.create_task(runner.run())
    await runner.wait_ready()
    print("READY", flush=True)
    await task
    await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
