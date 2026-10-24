"""``python -m pareeksha.workers.outbox_relay``: publish unpublished ``outbox_events`` rows.

Kafka being down never stops the API (it only writes rows); the relay backs off and drains the
backlog once the broker is back (TRD sections 10.4 and 14).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from pareeksha.events.outbox import BATCH_SIZE, prune_published, relay_once
from pareeksha.events.producer import EventProducer
from pareeksha.events.runtime import (
    Database,
    configure_logging,
    install_stop_signals,
)
from pareeksha.events.settings import EventSettings

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
MAX_BACKOFF_S = 10.0
PRUNE_EVERY_S = 3600.0


class OutboxRelay:
    def __init__(
        self,
        settings: EventSettings,
        *,
        poll_interval: float = POLL_INTERVAL_S,
        batch_size: int = BATCH_SIZE,
        request_timeout_ms: int = 10_000,
    ) -> None:
        self._db = Database(settings)
        self._producer = EventProducer(
            settings.bootstrap_servers,
            client_id="outbox-relay",
            request_timeout_ms=request_timeout_ms,
        )
        self._poll = poll_interval
        self._batch = batch_size
        self.stop_event = asyncio.Event()
        self.published_total = 0

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_event.wait(), seconds)

    async def run(self) -> None:
        backoff = 0.0
        last_prune = 0.0
        try:
            while not self.stop_event.is_set():
                try:
                    await self._producer.start()
                    conn = await self._db.connection()
                    result = await relay_once(conn, self._producer, batch_size=self._batch)
                    if time.monotonic() - last_prune > PRUNE_EVERY_S:
                        last_prune = time.monotonic()
                        pruned = await prune_published(conn)
                        if pruned:
                            log.info("pruned %d published outbox rows", pruned)
                except Exception:
                    # Kafka or Postgres unavailable: keep the loop alive and retry
                    result = None
                    log.warning("outbox relay cycle failed; backing off", exc_info=True)
                if result is not None and result.failed == 0:
                    backoff = 0.0
                    self.published_total += result.published
                    if result.published:
                        log.info("outbox published %d event(s)", result.published)
                    if result.published >= self._batch:
                        continue  # more waiting
                    await self._sleep(self._poll)
                else:
                    if result is not None:
                        self.published_total += result.published
                    backoff = min(max(backoff * 2, 1.0), MAX_BACKOFF_S)
                    await self._sleep(backoff)
        finally:
            await self._producer.stop()
            await self._db.close()


async def main() -> None:
    configure_logging()
    relay = OutboxRelay(EventSettings.from_env())
    install_stop_signals(relay.stop_event)
    await relay.run()


if __name__ == "__main__":
    asyncio.run(main())
