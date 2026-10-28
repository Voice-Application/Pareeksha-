"""``python -m pareeksha.workers.reconciler``: heal leaked run slots every minute (TRD 10.6).

``test_runs.active_calls`` is a counter, so a bug, a manual SQL change or a restore can leave it
different from the number of items that really hold a slot. A run stuck at its cap stops making
progress, so this loop recomputes the counter from ``run_items`` and logs every repair.
The consumer groups own no timers, hence a small worker of its own (the TRD places it in the
finalizer process; it only needs Postgres and can run beside any worker).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from pareeksha.events.runtime import Database, configure_logging, install_stop_signals
from pareeksha.events.settings import EventSettings
from pareeksha.runs.slots import reconcile_slots

log = logging.getLogger(__name__)

INTERVAL_S = 60.0


class Reconciler:
    def __init__(self, settings: EventSettings, *, interval: float = INTERVAL_S) -> None:
        self._db = Database(settings)
        self._interval = interval
        self.stop_event = asyncio.Event()
        self.repaired_total = 0

    async def run_once(self) -> int:
        """One pass; returns the number of runs repaired. Raises if Postgres is unreachable."""
        repairs = await reconcile_slots(await self._db.connection())
        self.repaired_total += len(repairs)
        return len(repairs)

    async def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    await self.run_once()
                except Exception:
                    log.warning("slot reconciliation failed; will retry", exc_info=True)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), self._interval)
        finally:
            await self._db.close()


async def main() -> None:
    configure_logging()
    reconciler = Reconciler(EventSettings.from_env())
    install_stop_signals(reconciler.stop_event)
    await reconciler.run()


if __name__ == "__main__":
    asyncio.run(main())
