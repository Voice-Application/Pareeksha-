"""The stale-item threshold stays above the longest healthy life of a run item."""

from __future__ import annotations

import pytest

from pareeksha.events.consumer import REGISTRY
from pareeksha.events.topics import MAX_ATTEMPTS, RETRY_DELAY_SECONDS, ConsumerGroups
from pareeksha.runs import watchdog
from pareeksha.workers import simulator
from pareeksha.workers.reconciler import stale_after_from_env


def test_the_bound_follows_the_simulator_consumer_and_the_retry_contract() -> None:
    spec = REGISTRY[ConsumerGroups.SIMULATOR.value]
    assert spec.handler is simulator.on_call_requested
    assert watchdog.SIMULATOR_MAX_DELIVERY_S * 1000 == spec.max_poll_interval_ms
    longest = MAX_ATTEMPTS * spec.max_poll_interval_ms / 1000 + sum(RETRY_DELAY_SECONDS.values())
    assert watchdog.HEALTHY_ITEM_LIFETIME_S == longest
    assert watchdog.DEFAULT_STALE_AFTER_S >= 2 * longest


def test_the_threshold_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUN_ITEM_STALE_AFTER_S", raising=False)
    assert stale_after_from_env() == watchdog.DEFAULT_STALE_AFTER_S
    monkeypatch.setenv("RUN_ITEM_STALE_AFTER_S", "")
    assert stale_after_from_env() == watchdog.DEFAULT_STALE_AFTER_S
    monkeypatch.setenv("RUN_ITEM_STALE_AFTER_S", "21600")
    assert stale_after_from_env() == 21600
    for bad in ("0", "-5", "soon"):
        monkeypatch.setenv("RUN_ITEM_STALE_AFTER_S", bad)
        with pytest.raises(ValueError):
            stale_after_from_env()
