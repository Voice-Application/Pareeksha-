"""``python -m pareeksha.workers.judge``: judge finished quick-test calls without a client polling.

A quick test's rule verdicts are normally filled lazily, a batch at a time, when its result page is
read (see ``quicktest.service.check_finished_calls``). A finished test that nobody opens would never
get judged. This small loop drives the same ``check_finished_calls`` across every quick test that
still has finished-but-unchecked calls, so verdicts land whether or not a client is watching.

It owns no timers of the consumer framework (like the reconciler, TRD 10.6), so it is a worker of
its own that only needs Postgres and the configured LLM provider. Each tick:

* picks candidate test ids under ``FOR UPDATE OF quick_tests SKIP LOCKED`` so two judge workers (or
  a reader and a worker) never claim the same test at once;
* for each candidate, builds the project's effective judge client and calls ``check_finished_calls``
  (which re-locks the row with its own skip-locked lock, the real guard against double-judging,
  and caps the work at ``JUDGE_BATCH`` calls), committing per test so progress is durable;
* swallows and logs a per-test failure, leaving its calls unchecked for a later tick, exactly as a
  failed lazy read does today.

Enable it with ``JUDGE_WORKER_ENABLED=1``; ``JUDGE_WORKER_INTERVAL_S`` sets the poll cadence.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid

from sqlalchemy import Boolean, Text, cast, exists, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.llm_deps import ClientBuilder, _default_builder
from pareeksha.db.models import Calls, QuickTests, RunItems
from pareeksha.db.session import SessionFactory, get_session_factory
from pareeksha.events.runtime import configure_logging, install_stop_signals
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMConfigError
from pareeksha.llm.project_settings import effective_llm_settings
from pareeksha.quicktest import service
from pareeksha.quicktest.service import NO_CONVERSATION

log = logging.getLogger(__name__)

#: How often the loop looks for tests to judge, in seconds (``JUDGE_WORKER_INTERVAL_S``).
INTERVAL_S = 10.0
#: Tests claimed per tick; each is judged ``JUDGE_BATCH`` calls at a time, so the rest follow.
MAX_PER_TICK = 20


def interval_s() -> float:
    """The poll cadence from ``JUDGE_WORKER_INTERVAL_S`` (default ``INTERVAL_S``)."""
    try:
        return max(0.5, float(os.environ.get("JUDGE_WORKER_INTERVAL_S", INTERVAL_S)))
    except ValueError:
        return INTERVAL_S


def enabled() -> bool:
    """Whether ``JUDGE_WORKER_ENABLED`` is a truthy value (``1``/``true``/``yes``/``on``)."""
    return os.environ.get("JUDGE_WORKER_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


async def _candidates(session: AsyncSession, limit: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """``(project_id, test_id)`` of tests with a finished, unchecked call, claimed skip-locked.

    A call is checkable when it completed with a conversation (``NO_CONVERSATION`` end reasons have
    nothing to judge); it is unchecked when its id is not yet a key of ``quick_tests.verdicts``.
    ``FOR UPDATE OF quick_tests SKIP LOCKED`` claims the test rows so a second worker skips them,
    mirroring ``check_finished_calls``' own lock; the lock is released at the end of the tick's
    read transaction, before any judging, and ``check_finished_calls`` re-acquires it per test.
    """
    # ``verdicts ? '<call_id>'`` is the JSONB "has this top-level key" test; the call id is cast to
    # text because its keys are the call ids stored as strings.
    unchecked = not_(QuickTests.verdicts.op("?", return_type=Boolean)(cast(Calls.id, Text)))
    has_finished_unchecked = exists(
        select(Calls.id)
        .select_from(Calls)
        .join(RunItems, RunItems.id == Calls.run_item_id)
        .where(
            RunItems.run_id == QuickTests.run_id,
            Calls.status == "completed",
            Calls.end_reason.notin_(NO_CONVERSATION),
            unchecked,
        )
    )
    stmt = (
        select(QuickTests.project_id, QuickTests.id)
        .where(has_finished_unchecked)
        .order_by(QuickTests.created_at)
        .limit(limit)
        .with_for_update(of=QuickTests, skip_locked=True)
    )
    rows = (await session.execute(stmt)).all()
    return [(p, t) for p, t in rows]


class JudgeWorker:
    """Polls for finished-but-unchecked quick tests and drives ``check_finished_calls``."""

    def __init__(
        self,
        factory: SessionFactory,
        *,
        build: ClientBuilder = _default_builder,
        interval: float | None = None,
        limit: int = MAX_PER_TICK,
    ) -> None:
        """Keep the session factory, the judge-client builder and the poll cadence/batch size."""
        self._factory = factory
        self._build = build
        self._interval = interval if interval is not None else interval_s()
        self._limit = limit
        self.stop_event = asyncio.Event()
        self.judged_tests = 0

    async def _judge_one(self, project_id: uuid.UUID, test_id: uuid.UUID) -> None:
        """Build the project's judge client and check one test's finished calls, in its own tx."""
        async with self._factory() as session:
            try:
                settings = await effective_llm_settings(session, project_id)
                client: LLMClient = self._build(settings, None)
            except LLMConfigError:
                log.warning("quick test %s: no usable judge client; skipping", test_id)
                return
            try:
                await service.check_finished_calls(session, project_id, test_id, client)
                await session.commit()
                self.judged_tests += 1
            finally:
                await client.aclose()

    async def run_once(self) -> int:
        """One pass: claim candidates, judge each. Returns how many tests were attempted."""
        async with self._factory() as session:
            candidates = await _candidates(session, self._limit)
            # release the claim locks before judging; check_finished_calls re-locks per test
            await session.rollback()
        for project_id, test_id in candidates:
            try:
                await self._judge_one(project_id, test_id)
            except Exception:
                log.warning("quick test %s: judging failed; will retry", test_id, exc_info=True)
        return len(candidates)

    async def run(self) -> None:
        """Loop until stopped, logging and swallowing a tick's own failures."""
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except Exception:
                log.warning("judge tick failed; will retry", exc_info=True)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop_event.wait(), self._interval)


async def main() -> None:
    """Run the loop when ``JUDGE_WORKER_ENABLED`` is set; otherwise exit at once."""
    configure_logging()
    if not enabled():
        log.info("judge worker disabled (set JUDGE_WORKER_ENABLED=1 to run it)")
        return
    worker = JudgeWorker(get_session_factory())
    install_stop_signals(worker.stop_event)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
