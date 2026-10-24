"""SDK: sync + async clients over real HTTP, plus retry behaviour with a scripted transport."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from pareeksha_sdk import (
    ApiError,
    AsyncPareeksha,
    NotFoundError,
    Pareeksha,
    PareekshaError,
    WaitTimeoutError,
)
from pareeksha_sdk.client import normalise_base_url
from tests.fake_platform import API_KEY, State, add_dead_letter

AGENT = {"name": "EMI Reminder Bot", "endpoint_url": "ws://x/ws"}


def seed(pk: Pareeksha) -> tuple[str, str, str, str]:
    agent = pk.agents.create(AGENT)
    scenario = pk.scenarios.create({"title": "S1", "caller_goal": "g", "agent_id": str(agent.id)})
    persona = pk.personas.create({"name": "P1"})
    noise = pk.noise_profiles.create({"name": "N1"})
    return str(agent.id), str(scenario.id), str(persona.id), str(noise.id)


def test_normalise_base_url() -> None:
    assert normalise_base_url("http://h:8000/") == "http://h:8000/api/v1"
    assert normalise_base_url("http://h:8000/api/v1") == "http://h:8000/api/v1"


def test_sync_roundtrip_agents_runs_wait(base_url: str, state: State) -> None:
    with Pareeksha(base_url, API_KEY) as pk:
        agent_id, s, p, n = seed(pk)
        assert pk.agents.get_by_name("EMI Reminder Bot").id == uuid.UUID(agent_id)
        assert pk.agents.get(agent_id).name == "EMI Reminder Bot"
        assert pk.agents.update(agent_id, {"glass_box": True}).model_extra == {
            "endpoint_url": "ws://x/ws",
            "glass_box": True,
        }
        assert pk.scenarios.get_by_name("S1").label == "S1"
        assert pk.personas.update(pk.personas.list()[0].id, {"speed": 1.1}).label == "P1"
        run = pk.runs.create(agent_id, [s], [p], [n], name="r", max_concurrency=2, seed=1)
        assert run.item_count == 1 and run.status == "queued"
        seen: list[str] = []
        done = pk.runs.wait(
            run.id, poll_s=0, on_progress=lambda r: seen.append(r.status), sleep=lambda _: None
        )
        assert seen == ["running", "completed"] and done.summary.pass_rate == 0.9
        assert pk.runs.items(run.id)[0].passed is True
        assert pk.health().db == "ok" and pk.metrics_summary()["dlq_open"] == 0


def test_not_found_and_api_error_envelope(base_url: str) -> None:
    pk = Pareeksha(base_url, API_KEY)
    with pytest.raises(NotFoundError):
        pk.agents.get_by_name("nope")
    with pytest.raises(NotFoundError):
        pk.personas.get_by_name("nope")
    with pytest.raises(ApiError) as info:
        pk.agents.get(uuid.uuid4())
    assert info.value.status_code == 404 and info.value.code == "error"
    pk.agents.create(AGENT)
    with pytest.raises(ApiError, match="409"):
        pk.agents.create(AGENT)
    with pytest.raises(ApiError) as bad:
        Pareeksha(base_url, "wrong").agents.list()
    assert bad.value.code == "unauthorized"


def test_pagination_follows_cursor(base_url: str, state: State) -> None:
    state.page_size = 2
    pk = Pareeksha(base_url, API_KEY)
    for i in range(5):
        pk.personas.create({"name": f"p{i}"})
    assert [p.name for p in pk.personas.list()] == [f"p{i}" for i in range(5)]


def test_wait_times_out(base_url: str, state: State) -> None:
    state.polls_until_done = 10_000
    pk = Pareeksha(base_url, API_KEY)
    agent_id, s, p, n = seed(pk)
    run = pk.runs.create(agent_id, [s], [p], [n])
    ticks = iter(range(0, 1000, 100))
    with pytest.raises(WaitTimeoutError):
        pk.runs.wait(run.id, timeout_s=250, sleep=lambda _: None, clock=lambda: float(next(ticks)))


def test_regression_audits_dlq(base_url: str, state: State, tmp_path: Path) -> None:
    pk = Pareeksha(base_url, API_KEY)
    agent_id, *_ = seed(pk)
    assert pk.runs.create_regression(agent_id).item_count == 2
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")
    ref = pk.audits.create(wav, agent_id, "kn-IN", stereo_channels_are_speakers=True)
    assert pk.audits.wait(ref.call_id, poll_s=0, sleep=lambda _: None).status == "completed"
    dl = add_dead_letter(state)
    assert [d.id for d in pk.dlq.list()] == [uuid.UUID(dl)]
    pk.dlq.replay(dl)
    assert pk.dlq.list() == []
    pk.dlq.discard(dl)
    assert state.dlq[dl]["status"] == "discarded"


def test_audit_wait_times_out(base_url: str, state: State, tmp_path: Path) -> None:
    pk = Pareeksha(base_url, API_KEY)
    agent_id, *_ = seed(pk)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")
    ref = pk.audits.create(wav, agent_id, "kn-IN")
    ticks = iter([0.0, 100.0])
    with pytest.raises(WaitTimeoutError):
        pk.audits.wait(ref.call_id, timeout_s=50, sleep=lambda _: None, clock=lambda: next(ticks))


# --- retries ---------------------------------------------------------------------------------


def scripted(statuses: list[int]) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status = queue.pop(0) if queue else 200
        if status == -1:
            raise httpx.ConnectError("refused")
        body = (
            {"items": [], "next_cursor": None}
            if request.method == "GET"
            else {"id": str(uuid.uuid4()), "status": "queued", "item_count": 0, "name": "x"}
        )
        if status >= 400:
            body = {"error": {"code": "boom", "message": "server broke", "details": {}}}
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler), seen


def test_get_retries_5xx_then_succeeds() -> None:
    transport, seen = scripted([500, 503, -1, 200])
    sleeps: list[float] = []
    pk = Pareeksha("http://x", "k", transport=transport, sleep=sleeps.append)
    assert pk.agents.list() == []
    assert len(seen) == 4 and sleeps == [0.5, 1.0, 2.0]


def test_get_gives_up_after_max_retries() -> None:
    transport, seen = scripted([500] * 10)
    pk = Pareeksha("http://x", "k", transport=transport, sleep=lambda _: None, max_retries=2)
    with pytest.raises(ApiError) as info:
        pk.agents.list()
    assert info.value.code == "boom" and len(seen) == 3
    transport, _ = scripted([-1] * 10)
    with pytest.raises(httpx.ConnectError):
        Pareeksha(
            "http://x", "k", transport=transport, sleep=lambda _: None, max_retries=1
        ).health()


def test_post_does_not_retry_plain_500_but_retries_gateway_errors() -> None:
    transport, seen = scripted([500])
    pk = Pareeksha("http://x", "k", transport=transport, sleep=lambda _: None)
    with pytest.raises(ApiError):
        pk.runs.create(uuid.uuid4(), [uuid.uuid4()], [uuid.uuid4()], [uuid.uuid4()])
    assert len(seen) == 1  # a retried POST could create a second run
    transport, seen = scripted([502, 503, 200])
    pk = Pareeksha("http://x", "k", transport=transport, sleep=lambda _: None)
    assert pk.agents.create(AGENT).id
    assert len(seen) == 3


def test_non_json_and_empty_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/health"):
            return httpx.Response(200, text="<html>")
        return httpx.Response(502, text="bad gateway")

    pk = Pareeksha("http://x", "k", transport=httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(PareekshaError, match="not JSON"):
        pk.health()
    with pytest.raises(ApiError) as info:
        pk.agents.list()
    assert info.value.code == "http_error" and "bad gateway" in info.value.message


def test_cancel_accepts_empty_202() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    pk = Pareeksha("http://x", "k", transport=httpx.MockTransport(handler))
    pk.runs.cancel(uuid.uuid4())  # a 202 without a body must not raise


# --- async -----------------------------------------------------------------------------------


async def test_async_client_full_flow(base_url: str, state: State, tmp_path: Path) -> None:
    async with AsyncPareeksha(base_url, API_KEY) as pk:
        agent = await pk.agents.create(AGENT)
        assert (await pk.agents.get_by_name("EMI Reminder Bot")).id == agent.id
        assert (await pk.agents.get(agent.id)).name == agent.name
        await pk.agents.update(agent.id, {"glass_box": True})
        s = await pk.scenarios.create({"title": "S1", "caller_goal": "g"})
        p = await pk.personas.create({"name": "P1"})
        n = await pk.noise_profiles.create({"name": "N1"})
        assert (await pk.scenarios.get_by_name("S1")).id == s.id
        await pk.personas.update(p.id, {"speed": 1.0})
        run = await pk.runs.create(agent.id, [s.id], [p.id], [n.id], dry_run=True)
        seen: list[str] = []

        async def no_sleep(_: float) -> None:
            return None

        done = await pk.runs.wait(
            run.id, on_progress=lambda r: seen.append(r.status), sleep=no_sleep
        )
        assert done.status == "completed" and seen == ["running", "completed"]
        assert len(await pk.runs.items(run.id)) == 1
        assert (await pk.runs.create_regression(agent.id)).item_count == 2
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"abc")
        ref = await pk.audits.create(wav, agent.id, "kn-IN")
        assert (await pk.audits.wait(ref.call_id, sleep=no_sleep)).status == "completed"
        dl = add_dead_letter(state)
        assert len(await pk.dlq.list()) == 1
        await pk.dlq.replay(dl)
        await pk.dlq.discard(dl)
        assert (await pk.health()).kafka == "ok"
        assert (await pk.metrics_summary())["outbox_backlog"] == 0
        with pytest.raises(NotFoundError):
            await pk.agents.get_by_name("nope")
        with pytest.raises(NotFoundError):
            await pk.personas.get_by_name("nope")
        with pytest.raises(ApiError):
            await pk.agents.get(uuid.uuid4())


async def test_async_timeouts_and_retries() -> None:
    transport, seen = scripted([503, 200])
    slept: list[float] = []

    async def fake_sleep(s: float) -> None:
        slept.append(s)

    pk = AsyncPareeksha("http://x", "k", transport=transport, sleep=fake_sleep)
    assert await pk.agents.list() == []
    assert slept == [0.5] and len(seen) == 2
    transport, _ = scripted([-1, -1])
    pk = AsyncPareeksha("http://x", "k", transport=transport, sleep=fake_sleep, max_retries=1)
    with pytest.raises(httpx.ConnectError):
        await pk.health()
    await pk.aclose()

    def pending(request: httpx.Request) -> httpx.Response:
        if "/runs/" in request.url.path:
            return httpx.Response(200, json={"id": str(uuid.uuid4()), "status": "running"})
        return httpx.Response(200, json={"id": str(uuid.uuid4()), "status": "transcribing"})

    pk = AsyncPareeksha("http://x", "k", transport=httpx.MockTransport(pending))
    ticks = iter([0.0, 100.0, 200.0, 300.0])

    async def no_sleep(_: float) -> None:
        return None

    with pytest.raises(WaitTimeoutError):
        await pk.runs.wait(uuid.uuid4(), timeout_s=50, sleep=no_sleep, clock=lambda: next(ticks))
    with pytest.raises(WaitTimeoutError):
        await pk.audits.wait(uuid.uuid4(), timeout_s=50, sleep=no_sleep, clock=lambda: next(ticks))
    await pk.runs.cancel(uuid.uuid4())
