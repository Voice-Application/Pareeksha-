"""``python -m pareeksha.workers.simulator``: call.requested -> a real call -> call.completed.

Registered with the INFRA-02 consumer framework as group ``simulator``. Per message:

1. ``start_item`` (API-03) takes one of the run's concurrency slots and marks the item
   ``connecting`` on a connection of its own, so the slot is visible to the other simulator
   instances at once and not only when this message's transaction ends. At the cap it raises
   ``Throttled`` (retry in 30 s, attempt unchanged); a cancelled / finished item is skipped; a
   redelivery of an item that already holds its slot resumes it.
2. The call itself runs outside any transaction: Pipecat pipeline, Gnani STT/TTS, the caller
   brain, the agent over ``pareeksha-audio-v1`` (``pareeksha.simulation.runner``).
3. Recordings go to the blob store; then, in the framework's transaction, the call row, turns,
   tool calls and usage are saved, the item is marked ``completed`` and ``release_slot`` gives the
   slot back, so all of it commits (or none of it does) together with the ``processed_events``
   row. ``call.completed`` is produced for the evaluator.

A duplicate delivery finds its ``processed_events`` row and re-produces the same
``call.completed`` without calling the agent again. A call that ends ``infra_error`` /
``connect_failed`` is saved with status ``error``, the item becomes ``error`` and nothing is
sent to the evaluator (there is nothing to judge).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from functools import cache
from typing import Any

from pareeksha.events.consumer import Ctx, Outgoing, PermanentError, Throttled, consumer, run_worker
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, Envelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import ConsumerGroups, Topics
from pareeksha.llm.caller import CallerBrain
from pareeksha.llm.factory import build_client
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.runs.slots import StartResult, start_item
from pareeksha.simulation import store
from pareeksha.simulation.models import CallResult, CallSpec
from pareeksha.simulation.runner import CallRunner, quiet_pipecat_logs
from pareeksha.simulation.runtime import BrainCallerSource
from pareeksha.speech.registry import get_stt_provider, get_tts_provider
from pareeksha.storage.blob import BlobStore, blob_store_from_env

log = logging.getLogger(__name__)

GROUP = ConsumerGroups.SIMULATOR.value
PRODUCER = "simulator"

_db: Database | None = None
_usage: ApiUsageSink | None = None
_runner: CallRunner | None = None
_providers: list[Any] = []
_blobs: BlobStore | None = None


def configure(
    *,
    db: Database | None = None,
    usage: ApiUsageSink | None = None,
    runner: CallRunner | None = None,
    blobs: BlobStore | None = None,
) -> None:
    """Install collaborators (tests, crash worker); ``None`` rebuilds from the environment."""
    global _db, _usage, _runner, _blobs
    _db, _usage, _runner, _blobs = db, usage, runner, blobs


def _database() -> Database:
    global _db
    if _db is None:
        _db = Database(EventSettings.from_env())
    return _db


def _blob_store() -> BlobStore:
    global _blobs
    if _blobs is None:
        _blobs = blob_store_from_env()
    return _blobs


@cache
def _usage_sink() -> ApiUsageSink:
    return ApiUsageSink(EventSettings.from_env())


def _call_runner() -> CallRunner:
    global _runner
    if _runner is None:
        quiet_pipecat_logs()
        sink = _usage if _usage is not None else _usage_sink()
        brain = CallerBrain(build_client(usage_sink=sink))
        stt, tts = get_stt_provider(), get_tts_provider()
        _providers.extend([stt, tts, brain])
        _runner = CallRunner(stt=stt, tts=tts, caller=BrainCallerSource(brain))
    return _runner


def _completed(req: CallRequested, spec: CallSpec, result: CallResult) -> Outgoing:
    return Outgoing(
        CallCompleted(
            call_id=spec.call_id,
            source="simulation",
            agent_id=req.agent_id,
            run_id=req.run_id,
            run_item_id=req.run_item_id,
            end_reason=result.end_reason,
        ),
        correlation_id=str(req.run_id),
    )


async def _reproduce(env: Envelope[CallRequested], ctx: Ctx) -> Sequence[Outgoing]:
    """Duplicate delivery: the call is already saved; say so again, do not call the agent."""
    req = env.payload
    cur = await ctx.tx.execute(
        "SELECT end_reason, status FROM calls WHERE id = %s", (store.call_id_for(req.run_item_id),)
    )
    row = await cur.fetchone()
    if row is None or row[1] == "error":
        return []
    return [
        Outgoing(
            CallCompleted(
                call_id=store.call_id_for(req.run_item_id),
                source="simulation",
                agent_id=req.agent_id,
                run_id=req.run_id,
                run_item_id=req.run_item_id,
                end_reason=row[0],
            ),
            correlation_id=str(req.run_id),
        )
    ]


async def _run_call(spec: CallSpec) -> tuple[CallResult, dict[str, bytes]]:
    """Run the call; an unexpected crash of the pipeline becomes an ``infra_error`` result."""
    try:
        outcome = await _call_runner().run(spec)
    except Exception as exc:
        log.exception("call %s crashed", spec.call_id)
        return (
            CallResult(
                call_id=spec.call_id, end_reason="infra_error", duration_ms=0, error=repr(exc)[:500]
            ),
            {},
        )
    audio: dict[str, bytes] = {}
    if outcome.recordings is not None:
        audio = {
            "caller": outcome.recordings.caller_wav,
            "agent": outcome.recordings.agent_wav,
            "mixed": outcome.recordings.mixed_wav,
        }
    return outcome.result, audio


@consumer(
    group=GROUP,
    topic=Topics.CALL_REQUESTED,
    reproduce=_reproduce,
    # a call is up to max_call_seconds (agent default 300 s, cap 1800 s) plus STT/TTS latency
    max_poll_interval_ms=2_400_000,
)
async def on_call_requested(env: Envelope[CallRequested], ctx: Ctx) -> Sequence[Outgoing]:
    req = env.payload
    conn = await _database().connection()
    started = await start_item(conn, req.run_id, req.run_item_id)
    if started is StartResult.THROTTLED:
        raise Throttled(f"run {req.run_id} is at its concurrency cap")
    if started is StartResult.SKIPPED:
        log.info("skipping run item %s (cancelled, finished or unknown)", req.run_item_id)
        return []
    try:
        spec, project_id = await store.read_spec(conn, req)
    except store.SpecNotFoundError as exc:
        await store.fail_item(conn, req.run_id, req.run_item_id, str(exc))
        raise PermanentError(str(exc)) from exc
    await store.open_call(conn, req=req, project_id=project_id, spec=spec)
    await store.mark_in_progress(conn, req.run_item_id)

    sink = _usage if _usage is not None else _usage_sink()
    with sink.scope(run_id=req.run_id, call_id=spec.call_id):
        result, audio = await _run_call(spec)

    keys: dict[str, str] | None = None
    if audio:
        prefix = store.blob_prefix(spec.call_id)
        keys = {name: f"{prefix}/{name}.wav" for name in audio}
        for name, data in audio.items():
            await _blob_store().put(keys[name], data)
    await store.save_call(
        ctx.tx, req=req, project_id=project_id, spec=spec, result=result, recording_keys=keys
    )
    if result.end_reason in ("infra_error", "connect_failed"):
        return []
    return [_completed(req, spec, result)]


async def main() -> None:
    try:
        await run_worker(GROUP)
    finally:
        for provider in _providers[:2]:
            await provider.aclose()
        if _usage is not None:
            await _usage.close()
        elif _usage_sink.cache_info().currsize:
            await _usage_sink().close()
        if _db is not None:
            await _db.close()


if __name__ == "__main__":
    asyncio.run(main())
