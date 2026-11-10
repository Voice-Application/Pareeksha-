"""``python -m pareeksha.workers.reconciler``: heal stuck run items and leaked slots every minute
(TRD 10.6).

``test_runs.active_calls`` is a counter, so a bug, a manual SQL change or a restore can leave it
different from the number of items that really hold a slot. A run stuck at its cap stops making
progress, so this loop recomputes the counter from ``run_items`` and logs every repair.
Before that it gives up run items nothing will move on any more (``runs.watchdog``): items whose
message is open in the DLQ, and slot-holding items older than ``RUN_ITEM_STALE_AFTER_S``
(default ``watchdog.DEFAULT_STALE_AFTER_S``, about 4 h; see there for how it is derived).
The consumer groups own no timers, hence a small worker of its own (the TRD places it in the
finalizer process; it only needs Postgres and can run beside any worker).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from pareeksha.events.runtime import Database, configure_logging, install_stop_signals
from pareeksha.events.settings import EventSettings
from pareeksha.runs.slots import reconcile_slots
from pareeksha.runs.watchdog import DEFAULT_STALE_AFTER_S, StaleSweep, give_up_dead_lettered

log = logging.getLogger(__name__)

INTERVAL_S = 60.0


def stale_after_from_env() -> float:
    """``RUN_ITEM_STALE_AFTER_S`` (seconds, > 0), else the default."""
    value = float(os.environ.get("RUN_ITEM_STALE_AFTER_S") or DEFAULT_STALE_AFTER_S)
    if value <= 0:
        raise ValueError("RUN_ITEM_STALE_AFTER_S must be a positive number of seconds")
    return value


class Reconciler:
    def __init__(
        self,
        settings: EventSettings,
        *,
        interval: float = INTERVAL_S,
        stale_after_s: float | None = None,
    ) -> None:
        self._db = Database(settings)
        self._interval = interval
        self._sweep = StaleSweep(
            stale_after_s=stale_after_from_env() if stale_after_s is None else stale_after_s
        )
        self.stop_event = asyncio.Event()
        self.repaired_total = 0
        self.given_up_total = 0

    async def run_once(self) -> int:
        """One pass; returns the number of runs whose slot counter was repaired. Raises if
        Postgres is unreachable."""
        conn = await self._db.connection()
        given_up = await give_up_dead_lettered(conn)
        given_up += await self._sweep.run(conn)
        self.given_up_total += len(given_up)
        repairs = await reconcile_slots(conn)
        self.repaired_total += len(repairs)
        return len(repairs)

    async def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                try:
                    await self.run_once()
                except Exception:
                    log.warning("run reconciliation failed; will retry", exc_info=True)
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
