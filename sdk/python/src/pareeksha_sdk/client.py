"""Sync and async clients. Thin and typed; retries on 5xx and transport errors.

    pk = Pareeksha(base_url="http://localhost:8000", api_key="pk_live_...")
    agent = pk.agents.get_by_name("EMI Reminder Bot")
    run = pk.runs.create(agent.id, scenario_ids, persona_ids, noise_profile_ids)
    result = pk.runs.wait(run.id, timeout_s=1800)

Retry policy: idempotent calls (GET/PATCH) retry any 5xx; POSTs retry only gateway errors
(502/503/504) and connection failures, so a retry cannot create a second run.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import httpx

from pareeksha_sdk import _calls as c
from pareeksha_sdk.errors import ApiError, NotFoundError, PareekshaError, WaitTimeoutError
from pareeksha_sdk.models import Agent, Call, CallRef, DeadLetter, Health, Named, Run, RunItem
from pareeksha_sdk.models import RunCreated as RunCreatedModel

LibraryKind = Literal["scenarios", "personas", "noise-profiles"]
GATEWAY_ERRORS = frozenset({502, 503, 504})
Progress = Callable[[Run], None]


def normalise_base_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/api/v1") else url + "/api/v1"


def _error_from(response: httpx.Response) -> ApiError:
    try:
        err = response.json()["error"]
        return ApiError(
            response.status_code,
            str(err.get("code", "error")),
            str(err.get("message", response.reason_phrase)),
            err.get("details") or {},
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return ApiError(response.status_code, "http_error", response.text[:300] or "no body")


def _should_retry(call: c.Call_, status: int) -> bool:
    if status in GATEWAY_ERRORS:
        return True
    return call.idempotent and status >= 500


def _unwrap(call: c.Call_, response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise _error_from(response)
    if response.status_code == 204 or not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise PareekshaError(f"{call.method} {call.path}: response is not JSON") from exc


def _find_by_name(items: list[Named], name: str, kind: str) -> Named:
    for item in items:
        if name in (item.name, item.title):
            return item
    raise NotFoundError(f"{kind} {name!r} not found")


def _run_body(
    agent_id: UUID | str,
    scenario_ids: list[UUID | str],
    persona_ids: list[UUID | str],
    noise_profile_ids: list[UUID | str],
    name: str,
    repeats: int,
    max_concurrency: int | None,
    seed: int | None,
    dry_run: bool,
    confirm_over_budget: bool,
) -> dict[str, Any]:
    config: dict[str, Any] = {"dry_run": dry_run}
    if max_concurrency is not None:
        config["max_concurrency"] = max_concurrency
    if seed is not None:
        config["seed"] = seed
    return {
        "agent_id": str(agent_id),
        "name": name,
        "kind": "dry_run" if dry_run else "matrix",
        "scenario_ids": [str(i) for i in scenario_ids],
        "persona_ids": [str(i) for i in persona_ids],
        "noise_profile_ids": [str(i) for i in noise_profile_ids],
        "repeats": repeats,
        "config": config,
        "confirm_over_budget": confirm_over_budget,
    }


# ===========================================================================================
# Sync
# ===========================================================================================


class _SyncCore:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=normalise_base_url(base_url),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def _send(self, call: c.Call_, params: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            try:
                if call.file is not None:
                    with call.file.open("rb") as handle:
                        response = self._http.request(
                            call.method,
                            call.path,
                            params=params,
                            data=call.data,
                            files={"file": (call.file.name, handle)},
                        )
                else:
                    response = self._http.request(
                        call.method, call.path, params=params, json=call.json, data=call.data
                    )
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
            else:
                if not _should_retry(call, response.status_code) or attempt >= self._max_retries:
                    return response
            attempt += 1
            self._sleep(self._backoff_s * 2 ** (attempt - 1))

    def call(self, call: c.Call_) -> Any:
        if not call.paged:
            return _unwrap(call, self._send(call, dict(call.params)))
        items: list[Any] = []
        cursor: str | None = None
        while True:
            params = {**call.params, "limit": 200, **({"cursor": cursor} if cursor else {})}
            page = _unwrap(call, self._send(call, params))
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items


class _Agents:
    def __init__(self, core: _SyncCore) -> None:
        self._core = core

    def list(self, include_archived: bool = False) -> list[Agent]:
        return c.parse_agents(self._core.call(c.agents_list(include_archived)))

    def get(self, agent_id: UUID | str) -> Agent:
        return c.parse_agent(self._core.call(c.agent_get(agent_id)))

    def get_by_name(self, name: str) -> Agent:
        for agent in self.list():
            if agent.name == name:
                return agent
        raise NotFoundError(f"agent {name!r} not found")

    def create(self, body: dict[str, Any]) -> Agent:
        return c.parse_agent(self._core.call(c.agent_create(body)))

    def update(self, agent_id: UUID | str, body: dict[str, Any]) -> Agent:
        return c.parse_agent(self._core.call(c.agent_update(agent_id, body)))


class _Library:
    """Scenarios, personas or noise profiles."""

    def __init__(self, core: _SyncCore, kind: LibraryKind) -> None:
        self._core = core
        self._kind = kind

    def list(self, **filters: Any) -> list[Named]:
        return c.parse_named_list(self._core.call(c.library_list(self._kind, **filters)))

    def get_by_name(self, name: str, **filters: Any) -> Named:
        return _find_by_name(self.list(**filters), name, self._kind)

    def create(self, body: dict[str, Any]) -> Named:
        return c.parse_named(self._core.call(c.library_create(self._kind, body)))

    def update(self, item_id: UUID | str, body: dict[str, Any]) -> Named:
        return c.parse_named(self._core.call(c.library_update(self._kind, item_id, body)))


class _Runs:
    def __init__(self, core: _SyncCore) -> None:
        self._core = core

    def create(
        self,
        agent_id: UUID | str,
        scenario_ids: list[UUID | str],
        persona_ids: list[UUID | str],
        noise_profile_ids: list[UUID | str],
        *,
        name: str = "",
        repeats: int = 1,
        max_concurrency: int | None = None,
        seed: int | None = None,
        dry_run: bool = False,
        confirm_over_budget: bool = False,
    ) -> RunCreatedModel:
        body = _run_body(
            agent_id,
            scenario_ids,
            persona_ids,
            noise_profile_ids,
            name,
            repeats,
            max_concurrency,
            seed,
            dry_run,
            confirm_over_budget,
        )
        return c.parse_run_created(self._core.call(c.run_create(body)))

    def create_regression(
        self, agent_id: UUID | str, *, statuses: list[str] | None = None, name: str = ""
    ) -> RunCreatedModel:
        body = {"agent_id": str(agent_id), "name": name, "statuses": statuses or ["blocking"]}
        return c.parse_run_created(self._core.call(c.regression_run_create(body)))

    def get(self, run_id: UUID | str) -> Run:
        return c.parse_run(self._core.call(c.run_get(run_id)))

    def items(self, run_id: UUID | str) -> list[RunItem]:
        return c.parse_items(self._core.call(c.run_items(run_id)))

    def cancel(self, run_id: UUID | str) -> None:
        self._core.call(c.run_cancel(run_id))

    def wait(
        self,
        run_id: UUID | str,
        *,
        timeout_s: float = 1800,
        poll_s: float = 3.0,
        on_progress: Progress | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Run:
        deadline = clock() + timeout_s
        while True:
            run = self.get(run_id)
            if on_progress is not None:
                on_progress(run)
            if run.is_final:
                return run
            if clock() >= deadline:
                raise WaitTimeoutError(f"run {run_id} still {run.status} after {timeout_s}s")
            sleep(poll_s)


class _Audits:
    def __init__(self, core: _SyncCore) -> None:
        self._core = core

    def create(
        self,
        file: str | Path,
        agent_id: UUID | str,
        language: str,
        *,
        stereo_channels_are_speakers: bool = False,
    ) -> CallRef:
        path = Path(file)
        call = c.audit_create(path, agent_id, language, stereo_channels_are_speakers)
        return c.parse_call_ref(self._core.call(call))

    def wait(
        self,
        call_id: UUID | str,
        *,
        timeout_s: float = 600,
        poll_s: float = 3.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Call:
        deadline = clock() + timeout_s
        while True:
            call = c.parse_call(self._core.call(c.call_get(call_id)))
            if call.status in ("completed", "error"):
                return call
            if clock() >= deadline:
                raise WaitTimeoutError(f"call {call_id} still {call.status} after {timeout_s}s")
            sleep(poll_s)


class _Dlq:
    def __init__(self, core: _SyncCore) -> None:
        self._core = core

    def list(self, status: str | None = "open") -> list[DeadLetter]:
        return c.parse_dlq(self._core.call(c.dlq_list(status)))

    def replay(self, dead_letter_id: UUID | str) -> None:
        self._core.call(c.dlq_replay(dead_letter_id))

    def discard(self, dead_letter_id: UUID | str) -> None:
        self._core.call(c.dlq_discard(dead_letter_id))


class Pareeksha:
    """Synchronous client."""

    def __init__(self, base_url: str, api_key: str, **options: Any) -> None:
        self._core = _SyncCore(base_url, api_key, **options)
        self.agents = _Agents(self._core)
        self.scenarios = _Library(self._core, "scenarios")
        self.personas = _Library(self._core, "personas")
        self.noise_profiles = _Library(self._core, "noise-profiles")
        self.runs = _Runs(self._core)
        self.audits = _Audits(self._core)
        self.dlq = _Dlq(self._core)

    def health(self) -> Health:
        return c.parse_health(self._core.call(c.health()))

    def metrics_summary(self) -> dict[str, Any]:
        result: dict[str, Any] = self._core.call(c.metrics_summary())
        return result

    def close(self) -> None:
        self._core.close()

    def __enter__(self) -> Pareeksha:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


# ===========================================================================================
# Async
# ===========================================================================================


class _AsyncCore:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_s: float = 0.5,
        sleep: Callable[[float], Any] = asyncio.sleep,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=normalise_base_url(base_url),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    async def close(self) -> None:
        await self._http.aclose()

    async def _send(self, call: c.Call_, params: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            try:
                if call.file is not None:
                    files = {"file": (call.file.name, call.file.read_bytes())}
                    response = await self._http.request(
                        call.method, call.path, params=params, data=call.data, files=files
                    )
                else:
                    response = await self._http.request(
                        call.method, call.path, params=params, json=call.json, data=call.data
                    )
            except httpx.TransportError:
                if attempt >= self._max_retries:
                    raise
            else:
                if not _should_retry(call, response.status_code) or attempt >= self._max_retries:
                    return response
            attempt += 1
            await self._sleep(self._backoff_s * 2 ** (attempt - 1))

    async def call(self, call: c.Call_) -> Any:
        if not call.paged:
            return _unwrap(call, await self._send(call, dict(call.params)))
        items: list[Any] = []
        cursor: str | None = None
        while True:
            params = {**call.params, "limit": 200, **({"cursor": cursor} if cursor else {})}
            page = _unwrap(call, await self._send(call, params))
            items.extend(page["items"])
            cursor = page.get("next_cursor")
            if not cursor:
                return items


class _AsyncAgents:
    def __init__(self, core: _AsyncCore) -> None:
        self._core = core

    async def list(self, include_archived: bool = False) -> list[Agent]:
        return c.parse_agents(await self._core.call(c.agents_list(include_archived)))

    async def get(self, agent_id: UUID | str) -> Agent:
        return c.parse_agent(await self._core.call(c.agent_get(agent_id)))

    async def get_by_name(self, name: str) -> Agent:
        for agent in await self.list():
            if agent.name == name:
                return agent
        raise NotFoundError(f"agent {name!r} not found")

    async def create(self, body: dict[str, Any]) -> Agent:
        return c.parse_agent(await self._core.call(c.agent_create(body)))

    async def update(self, agent_id: UUID | str, body: dict[str, Any]) -> Agent:
        return c.parse_agent(await self._core.call(c.agent_update(agent_id, body)))


class _AsyncLibrary:
    def __init__(self, core: _AsyncCore, kind: LibraryKind) -> None:
        self._core = core
        self._kind = kind

    async def list(self, **filters: Any) -> list[Named]:
        return c.parse_named_list(await self._core.call(c.library_list(self._kind, **filters)))

    async def get_by_name(self, name: str, **filters: Any) -> Named:
        return _find_by_name(await self.list(**filters), name, self._kind)

    async def create(self, body: dict[str, Any]) -> Named:
        return c.parse_named(await self._core.call(c.library_create(self._kind, body)))

    async def update(self, item_id: UUID | str, body: dict[str, Any]) -> Named:
        return c.parse_named(await self._core.call(c.library_update(self._kind, item_id, body)))


class _AsyncRuns:
    def __init__(self, core: _AsyncCore) -> None:
        self._core = core

    async def create(
        self,
        agent_id: UUID | str,
        scenario_ids: list[UUID | str],
        persona_ids: list[UUID | str],
        noise_profile_ids: list[UUID | str],
        *,
        name: str = "",
        repeats: int = 1,
        max_concurrency: int | None = None,
        seed: int | None = None,
        dry_run: bool = False,
        confirm_over_budget: bool = False,
    ) -> RunCreatedModel:
        body = _run_body(
            agent_id,
            scenario_ids,
            persona_ids,
            noise_profile_ids,
            name,
            repeats,
            max_concurrency,
            seed,
            dry_run,
            confirm_over_budget,
        )
        return c.parse_run_created(await self._core.call(c.run_create(body)))

    async def create_regression(
        self, agent_id: UUID | str, *, statuses: list[str] | None = None, name: str = ""
    ) -> RunCreatedModel:
        body = {"agent_id": str(agent_id), "name": name, "statuses": statuses or ["blocking"]}
        return c.parse_run_created(await self._core.call(c.regression_run_create(body)))

    async def get(self, run_id: UUID | str) -> Run:
        return c.parse_run(await self._core.call(c.run_get(run_id)))

    async def items(self, run_id: UUID | str) -> list[RunItem]:
        return c.parse_items(await self._core.call(c.run_items(run_id)))

    async def cancel(self, run_id: UUID | str) -> None:
        await self._core.call(c.run_cancel(run_id))

    async def wait(
        self,
        run_id: UUID | str,
        *,
        timeout_s: float = 1800,
        poll_s: float = 3.0,
        on_progress: Progress | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Run:
        deadline = clock() + timeout_s
        while True:
            run = await self.get(run_id)
            if on_progress is not None:
                on_progress(run)
            if run.is_final:
                return run
            if clock() >= deadline:
                raise WaitTimeoutError(f"run {run_id} still {run.status} after {timeout_s}s")
            await sleep(poll_s)


class _AsyncAudits:
    def __init__(self, core: _AsyncCore) -> None:
        self._core = core

    async def create(
        self,
        file: str | Path,
        agent_id: UUID | str,
        language: str,
        *,
        stereo_channels_are_speakers: bool = False,
    ) -> CallRef:
        call = c.audit_create(Path(file), agent_id, language, stereo_channels_are_speakers)
        return c.parse_call_ref(await self._core.call(call))

    async def wait(
        self,
        call_id: UUID | str,
        *,
        timeout_s: float = 600,
        poll_s: float = 3.0,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> Call:
        deadline = clock() + timeout_s
        while True:
            call = c.parse_call(await self._core.call(c.call_get(call_id)))
            if call.status in ("completed", "error"):
                return call
            if clock() >= deadline:
                raise WaitTimeoutError(f"call {call_id} still {call.status} after {timeout_s}s")
            await sleep(poll_s)


class _AsyncDlq:
    def __init__(self, core: _AsyncCore) -> None:
        self._core = core

    async def list(self, status: str | None = "open") -> list[DeadLetter]:
        return c.parse_dlq(await self._core.call(c.dlq_list(status)))

    async def replay(self, dead_letter_id: UUID | str) -> None:
        await self._core.call(c.dlq_replay(dead_letter_id))

    async def discard(self, dead_letter_id: UUID | str) -> None:
        await self._core.call(c.dlq_discard(dead_letter_id))


class AsyncPareeksha:
    """Asynchronous client with the same surface as ``Pareeksha``."""

    def __init__(self, base_url: str, api_key: str, **options: Any) -> None:
        self._core = _AsyncCore(base_url, api_key, **options)
        self.agents = _AsyncAgents(self._core)
        self.scenarios = _AsyncLibrary(self._core, "scenarios")
        self.personas = _AsyncLibrary(self._core, "personas")
        self.noise_profiles = _AsyncLibrary(self._core, "noise-profiles")
        self.runs = _AsyncRuns(self._core)
        self.audits = _AsyncAudits(self._core)
        self.dlq = _AsyncDlq(self._core)

    async def health(self) -> Health:
        return c.parse_health(await self._core.call(c.health()))

    async def metrics_summary(self) -> dict[str, Any]:
        result: dict[str, Any] = await self._core.call(c.metrics_summary())
        return result

    async def aclose(self) -> None:
        await self._core.close()

    async def __aenter__(self) -> AsyncPareeksha:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
