"""``python -m pareeksha.workers.integrations``: the ``integrations`` consumer group.

Consumes ``evaluation.completed`` and ``run.completed`` (the finalizer reads the same topics in its
own group) and pushes each event to the project's matching sink integrations (webhook, HubSpot, ...)
through the connector framework. Delivery rows live on a separate autocommit connection, so:

* a duplicate Kafka message is skipped by ``processed_events``; a replay that slips past it finds
  the terminal ``integration_deliveries`` row and sends nothing;
* a crash between the HTTP call and the row update re-runs only that integration on redelivery
  (the receiver sees the same ``X-Pareeksha-Event-Id``; HubSpot finds its note marker);
* a retryable failure of one integration retries the event through ``retry.30s`` / ``retry.5m``;
  integrations that already finished are terminal and skipped on the retry. After the last
  attempt the row is recorded as ``failed`` and the event goes to the DLQ.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from typing import Any

from pareeksha.events.consumer import (
    Ctx,
    Outgoing,
    RetryableError,
    consumer,
    run_worker,
)
from pareeksha.events.runtime import Database
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import MAX_ATTEMPTS, ConsumerGroups, Topics
from pareeksha.integrations.crypto import SecretBox
from pareeksha.integrations.dispatch import DeliveryRetry, deliver_to_sinks
from pareeksha.integrations.registry import get_registry
from pareeksha.integrations.sql_store import PsycopgDeliveryStore

GROUP = ConsumerGroups.INTEGRATIONS.value

_state: dict[str, Any] = {}


def _secret_box() -> SecretBox:
    key = os.environ.get("SECRET_KEY")
    if not key:
        raise SystemExit(
            "SECRET_KEY is not set: the integrations worker cannot decrypt connector secrets. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" and put it in .env (`make demo` does this)."
        )
    return SecretBox(key)


async def _store() -> PsycopgDeliveryStore:
    """A store on its own autocommit connection (not the consumer's transaction)."""
    if "db" not in _state:
        _state["db"] = Database(EventSettings.from_env())
    conn = await _state["db"].connection()
    return PsycopgDeliveryStore(conn)


async def _nothing_to_reproduce(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    """A duplicate message produces no output events, so there is nothing to re-produce."""
    return []


@consumer(
    group=GROUP,
    topic=[Topics.EVALUATION_COMPLETED, Topics.RUN_COMPLETED],
    reproduce=_nothing_to_reproduce,
)
async def handle(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
    try:
        await deliver_to_sinks(
            ctx.tx,
            await _store(),
            _secret_box(),
            get_registry(),
            env,
            final_attempt=ctx.attempt >= MAX_ATTEMPTS,
        )
    except DeliveryRetry as exc:
        raise RetryableError(str(exc)) from exc
    return []


if __name__ == "__main__":
    _secret_box()  # fail fast at startup, not as a dead-letter per event
    asyncio.run(run_worker(GROUP))
