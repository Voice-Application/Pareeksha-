"""The real ``evaluator`` consumer (registered handler, Postgres stores) in a killable process.

    python -m tests.integration.evaluator_crash_worker <group> <database_url> <mode>

The judge is a scripted provider (the exactly-once tests must not spend DeepSeek credit and need
to know how often the judge was called); everything else is the production code path.

Modes:
  normal                SIGTERM -> graceful shutdown (exit code 0)
  crash_in_judge        SIGKILL while the judge is being called (before any DB commit)
  crash_before_produce  handler and DB transaction commit, then SIGKILL when the framework is
                        about to produce ``evaluation.completed`` (before the offset commit)

Prints ``READY``, ``JUDGE_CALL`` on every judge call and ``REPRODUCE <event_id>`` when the
framework takes the duplicate path.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import signal
import sys
from typing import Any

from pareeksha.events.consumer import REGISTRY, ConsumerRunner, Ctx, Outgoing
from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import configure_logging, install_stop_signals
from pareeksha.events.schemas import AnyEnvelope
from pareeksha.events.settings import EventSettings
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.workers import evaluator
from tests.integration.support import BOOTSTRAP
from tests.unit.evaluation.fakes import judge_json

GROUP, DB_URL, MODE = sys.argv[1], sys.argv[2], sys.argv[3]


def _kill_self() -> None:
    os.kill(os.getpid(), signal.SIGKILL)


class CountingJudge(LLMProvider):
    name = LLMProviderName.DEEPSEEK

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        print("JUDGE_CALL", flush=True)
        if MODE == "crash_in_judge":
            _kill_self()
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=judge_json(),
            usage=LLMUsage(input_tokens=1000, output_tokens=200),
            latency_ms=5,
        )

    async def aclose(self) -> None:
        return None


class CrashingProducer(EventProducer):
    async def publish(self, envelope: AnyEnvelope) -> None:
        print("ABOUT_TO_PRODUCE", flush=True)
        _kill_self()


async def main() -> None:
    configure_logging()
    settings = EventSettings(bootstrap_servers=BOOTSTRAP, database_url=DB_URL)
    usage = ApiUsageSink(settings)
    llm_settings = LLMSettings(
        _env_file=None,
        deepseek_api_key="scripted",
        cost_deepseek_per_1k_input_tokens=0.001,
        cost_deepseek_per_1k_output_tokens=0.004,
    )
    evaluator.set_client(LLMClient(CountingJudge(), llm_settings, usage_sink=usage), usage)

    base = REGISTRY[str(evaluator.GROUP)]

    async def reproduce(env: Any, ctx: Ctx) -> list[Outgoing]:
        print(f"REPRODUCE {env.event_id}", flush=True)
        return await evaluator.reproduce(env, ctx)

    spec = dataclasses.replace(base, group=GROUP, reproduce=reproduce)
    producer_cls = CrashingProducer if MODE == "crash_before_produce" else EventProducer
    producer = producer_cls(BOOTSTRAP, client_id=f"{GROUP}-producer")
    await producer.start()
    runner = ConsumerRunner(spec, settings, producer=producer)
    install_stop_signals(runner.stop_event)
    task = asyncio.create_task(runner.run())
    await runner.wait_ready()
    print("READY", flush=True)
    await task
    await producer.stop()
    await usage.close()


if __name__ == "__main__":
    asyncio.run(main())
