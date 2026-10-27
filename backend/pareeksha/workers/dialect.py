"""``python -m pareeksha.workers.dialect``: the ``dialect`` consumer group (EVAL-05).

Reads ``dialect.clip.requested`` (key = sample_id, so clips spread over partitions and several
instances share a report) and runs ``pareeksha.dialect.pipeline.handle_clip_requested``.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from pareeksha.dialect.pipeline import DialectDeps, handle_clip_requested
from pareeksha.events.consumer import Ctx, Outgoing, consumer, run_worker
from pareeksha.events.schemas import DialectClipRequested, Envelope
from pareeksha.events.topics import Topics
from pareeksha.llm.client import LLMClient, UsageRecord
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.factory import build_provider
from pareeksha.speech.base import SpeechProviderName, STTProvider
from pareeksha.speech.registry import get_stt_provider

GROUP = "dialect"


@lru_cache(maxsize=8)
def _stt(name: SpeechProviderName) -> STTProvider:
    return get_stt_provider(name)


@lru_cache(maxsize=1)
def _llm_parts() -> tuple[Any, LLMSettings] | None:
    """The shared LLM provider, or ``None`` when no key is configured (intent flag stays null)."""
    settings = LLMSettings()
    try:
        return build_provider(settings), settings
    except LLMConfigError:
        return None


def _llm_for(sink: Callable[[UsageRecord], Any]) -> LLMClient | None:
    parts = _llm_parts()
    if parts is None:
        return None
    provider, settings = parts
    return LLMClient(provider, settings, usage_sink=sink)


def make_deps() -> DialectDeps:
    return DialectDeps(
        data_dir=Path(os.environ.get("DATA_DIR", "/data")), stt_for=_stt, llm_for=_llm_for
    )


@consumer(group=GROUP, topic=Topics.DIALECT_CLIP_REQUESTED)
async def handle(env: Envelope[DialectClipRequested], ctx: Ctx) -> Sequence[Outgoing]:
    return await handle_clip_requested(env, ctx, make_deps())


async def main() -> None:
    await run_worker(GROUP)


if __name__ == "__main__":
    asyncio.run(main())
