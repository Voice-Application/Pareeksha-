"""``api_usage`` rows for LLM calls (the ``usage_sink`` of ``LLMClient``).

Each provider call (the repair retry included) becomes one row: ``operation = llm_<purpose>``,
``units`` = input + output tokens, ``est_cost`` from the ``COST_*`` rates in the environment.

The row is written on its own autocommit connection, not in the handler's transaction: the money
is spent whether or not the handler later commits, so a rolled-back evaluation (crash, retry)
still leaves its usage row. A failure to write the row never fails the evaluation; it is logged
with the full record so the spend can be reconstructed.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from pareeksha.events.runtime import Database
from pareeksha.events.settings import EventSettings
from pareeksha.llm.client import UsageRecord

log = logging.getLogger("pareeksha.llm.usage")


@dataclass(frozen=True, slots=True)
class UsageScope:
    """What the calls made inside a ``scope()`` block are attributed to."""

    run_id: uuid.UUID | None = None
    call_id: uuid.UUID | None = None


_SCOPE: contextvars.ContextVar[UsageScope | None] = contextvars.ContextVar(
    "pareeksha_usage_scope", default=None
)

_INSERT = """
INSERT INTO api_usage (provider, operation, units, unit_type, est_cost, cached, run_id, call_id)
VALUES (%s, %s, %s, 'tokens', %s, %s, %s, %s)
"""


class ApiUsageSink:
    """Callable usable as ``usage_sink``; attribute calls with ``with sink.scope(...)``."""

    def __init__(self, settings: EventSettings) -> None:
        self._db = Database(settings)

    @contextlib.contextmanager
    def scope(
        self, *, run_id: uuid.UUID | None = None, call_id: uuid.UUID | None = None
    ) -> Iterator[None]:
        token = _SCOPE.set(UsageScope(run_id=run_id, call_id=call_id))
        try:
            yield
        finally:
            _SCOPE.reset(token)

    async def __call__(self, record: UsageRecord) -> None:
        scope = _SCOPE.get() or UsageScope()
        params = (
            record.provider.value,
            f"llm_{record.purpose.value}",
            record.input_tokens + record.output_tokens,
            record.est_cost,
            record.cache_hit,
            scope.run_id,
            scope.call_id,
        )
        try:
            conn = await self._db.connection()
            await conn.execute(_INSERT, params)
        except Exception:
            log.exception("api_usage insert failed; usage=%s", record.model_dump_json())

    async def close(self) -> None:
        await self._db.close()
