"""LLM access for API routes: the client builder (tests replace it) and the usage sink."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from pareeksha.db.models import ApiUsage
from pareeksha.db.session import SessionFactory
from pareeksha.llm.client import LLMClient, UsageRecord, UsageSink
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.factory import build_client

#: ``(settings, usage_sink) -> LLMClient``; the default builds the configured provider.
ClientBuilder = Callable[[LLMSettings, UsageSink | None], LLMClient]


def _default_builder(settings: LLMSettings, usage_sink: UsageSink | None) -> LLMClient:
    return build_client(settings, usage_sink=usage_sink)


def get_client_builder() -> ClientBuilder:
    return _default_builder


LlmBuilder = Annotated[ClientBuilder, Depends(get_client_builder)]


def usage_sink(factory: SessionFactory, project_id: uuid.UUID) -> UsageSink:
    """Records each provider call as an ``api_usage`` row in a session and transaction of its own.

    The request's transaction is rolled back when the route fails (502), but the provider has
    already billed, so the row must be committed regardless.
    """

    async def sink(record: UsageRecord) -> None:
        async with factory() as session:
            session.add(
                ApiUsage(
                    provider=record.provider.value,
                    operation=f"llm_{record.purpose.value}",
                    units=record.input_tokens + record.output_tokens,
                    unit_type="tokens",
                    cached=record.cache_hit,
                    est_cost=record.est_cost,
                    project_id=project_id,
                )
            )
            await session.commit()

    return sink
