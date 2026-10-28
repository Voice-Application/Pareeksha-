"""Event filters, the dev-only private-target switch, and "no INT-01 stub left"."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from pareeksha.events.schemas import (
    EvaluationCompleted,
    RunCompleted,
    RunCompletedSummary,
    make_envelope,
)
from pareeksha.integrations.dispatch import DEFAULT_EVENTS, filter_matches
from pareeksha.integrations.ssrf import DEV_ALLOW_PRIVATE_ENV, SSRFError, resolve_public
from pareeksha.integrations.webhook import WebhookConnector

PACKAGE = Path(__file__).resolve().parents[3] / "pareeksha"


def evaluation(*, passed: bool, score: float, agent: uuid.UUID | None = None) -> Any:
    payload = EvaluationCompleted(
        call_id=uuid.uuid4(),
        evaluation_id=uuid.uuid4(),
        agent_id=agent,
        overall_score=score,
        passed=passed,
    )
    return make_envelope(payload, producer="t", correlation_id="c")


def run_completed(agent: uuid.UUID) -> Any:
    payload = RunCompleted(
        run_id=uuid.uuid4(),
        agent_id=agent,
        kind="matrix",
        status="completed",
        summary=RunCompletedSummary(item_count=1, evaluated_count=1, error_count=0),
    )
    return make_envelope(payload, producer="t", correlation_id="c")


def test_default_filter_wants_evaluation_completed_only() -> None:
    assert DEFAULT_EVENTS == ["evaluation.completed"]
    assert filter_matches({}, evaluation(passed=True, score=90))
    assert not filter_matches({}, run_completed(uuid.uuid4()))
    assert filter_matches({"events": ["run.completed"]}, run_completed(uuid.uuid4()))


def test_only_failed_min_score_and_agent_filters() -> None:
    agent = uuid.uuid4()
    passing = evaluation(passed=True, score=95, agent=agent)
    failing = evaluation(passed=False, score=40, agent=agent)
    assert not filter_matches({"only_failed": True}, passing)
    assert filter_matches({"only_failed": True}, failing)
    assert filter_matches({"min_score_below": 60}, failing)
    assert not filter_matches({"min_score_below": 60}, passing)
    assert filter_matches({"agent_ids": [str(agent)]}, failing)
    assert not filter_matches({"agent_ids": [str(uuid.uuid4())]}, failing)
    wanted = {"events": ["run.completed"], "agent_ids": [str(agent)]}
    assert filter_matches(wanted, run_completed(agent))
    assert not filter_matches(wanted, run_completed(uuid.uuid4()))


async def test_private_addresses_are_refused_unless_the_dev_switch_is_given() -> None:
    with pytest.raises(SSRFError, match="non-public"):
        await resolve_public("https://127.0.0.1:8443/hook")
    host, ip, port = await resolve_public("https://127.0.0.1:8443/hook", allow_private=True)
    assert (host, ip, port) == ("127.0.0.1", "127.0.0.1", 8443)
    with pytest.raises(SSRFError, match="only https"):  # the other rules stay on
        await resolve_public("http://127.0.0.1/hook", allow_private=True)


def test_connector_reads_the_dev_switch_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(DEV_ALLOW_PRIVATE_ENV, raising=False)
    assert WebhookConnector()._allow_private is False
    monkeypatch.setenv(DEV_ALLOW_PRIVATE_ENV, "1")
    with caplog.at_level("WARNING"):
        assert WebhookConnector()._allow_private is True
    assert DEV_ALLOW_PRIVATE_ENV in caplog.text
    monkeypatch.setenv(DEV_ALLOW_PRIVATE_ENV, "true")
    assert WebhookConnector()._allow_private is False  # only the literal "1" turns it on


def test_no_int01_stub_marker_remains() -> None:
    offenders = [
        str(p.relative_to(PACKAGE))
        for p in PACKAGE.rglob("*.py")
        if "STUB(INT-01)" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
