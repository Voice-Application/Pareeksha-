"""``CallRunner``: run one simulated call end to end (the unit the ``simulator`` consumer calls).

connect through the agent's adapter -> build the Pipecat pipeline -> wait for an end condition ->
tear down -> render the recordings and return the ``CallResult``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from loguru import logger as _loguru
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner

from pareeksha.adapters.base import (
    AUDIO_SAMPLE_RATE,
    Adapter,
    AdapterError,
    AgentConnectError,
    AudioSession,
    CallContext,
)
from pareeksha.adapters.registry import get_adapter
from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.schemas.calls import EndReason
from pareeksha.simulation.barge_in import BargeInScheduler
from pareeksha.simulation.director import CallerDirector
from pareeksha.simulation.models import (
    CallClock,
    CallResult,
    CallSpec,
    RecordingFiles,
    SimulationSettings,
)
from pareeksha.simulation.processors import (
    AgentSource,
    AgentSTT,
    AgentTurnDetector,
    CallerMic,
    CallerTTS,
    CallTap,
)
from pareeksha.simulation.recorder import Recordings
from pareeksha.simulation.runtime import CallerSource, CallRuntime
from pareeksha.speech.base import STTProvider, TTSProvider

log = logging.getLogger(__name__)

VadFactory = Callable[[SimulationSettings], VADAnalyzer]
TEARDOWN_TIMEOUT_S = 5.0


def silero_vad(settings: SimulationSettings) -> VADAnalyzer:
    return SileroVADAnalyzer(
        sample_rate=AUDIO_SAMPLE_RATE,
        params=VADParams(
            confidence=settings.vad_confidence,
            start_secs=settings.vad_start_s,
            stop_secs=settings.end_of_turn_s,
            min_volume=0.3,
        ),
    )


def quiet_pipecat_logs(level: str | None = None) -> None:
    """Pipecat logs every frame link at DEBUG through loguru; keep warnings and errors only."""
    chosen = level or os.environ.get("PIPECAT_LOG_LEVEL", "WARNING")
    _loguru.remove()
    _loguru.add(sys.stderr, level=chosen)


@dataclass
class CallOutcome:
    result: CallResult
    recordings: Recordings | None

    def save(self, directory: Path) -> CallResult:
        """Write ``caller.wav``, ``agent.wav``, ``mixed.wav`` and ``transcript.json``."""
        directory.mkdir(parents=True, exist_ok=True)
        if self.recordings is not None:
            self.recordings.save(directory)
            self.result.recordings = RecordingFiles(
                caller=str(directory / "caller.wav"),
                agent=str(directory / "agent.wav"),
                mixed=str(directory / "mixed.wav"),
                duration_ms=self.recordings.duration_ms,
            )
        (directory / "transcript.json").write_text(
            json.dumps(self.result.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.result


class CallRunner:
    def __init__(
        self,
        *,
        stt: STTProvider,
        tts: TTSProvider,
        caller: CallerSource,
        settings: SimulationSettings | None = None,
        vad_factory: VadFactory = silero_vad,
        adapter: Adapter | None = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._caller = caller
        self._settings = settings or SimulationSettings()
        self._vad_factory = vad_factory
        self._adapter = adapter

    async def run(self, spec: CallSpec, *, cancel: asyncio.Event | None = None) -> CallOutcome:
        """Run the call. ``cancel`` ends it early with ``end_reason`` ``cancelled``."""
        quiet_pipecat_logs()
        clock = CallClock()
        rt = CallRuntime(spec, self._settings, clock)
        try:
            adapter = self._adapter or get_adapter(spec.agent.adapter)
            session = await adapter.connect(
                spec.agent,
                CallContext(
                    call_id=spec.call_id,
                    language_hint=spec.language,
                    metadata=spec.metadata,
                    connect_timeout_s=spec.connect_timeout_s,
                ),
            )
        except AdapterError as exc:
            reason: EndReason = (
                "connect_failed" if isinstance(exc, AgentConnectError) else "infra_error"
            )
            return CallOutcome(self._result(rt, reason, str(exc)), None)
        clock.reset()
        rt.log("call_start", language=spec.language, profile=spec.profile.name, seed=spec.seed)
        try:
            await self._run_pipeline(rt, session, cancel)
        finally:
            with contextlib.suppress(Exception):
                await session.close()
        if rt.hop_ms:
            ordered = sorted(rt.hop_ms)
            rt.log(
                "pipeline_overhead",
                frames=len(ordered),
                p50_ms=round(ordered[len(ordered) // 2], 3),
                p95_ms=round(ordered[int(len(ordered) * 0.95)], 3),
                max_ms=round(ordered[-1], 3),
            )
        recordings = rt.recorder.finalize(rt.ended_ms)
        return CallOutcome(self._result(rt, rt.end_reason or "infra_error", rt.error), recordings)

    async def _run_pipeline(
        self, rt: CallRuntime, session: AudioSession, cancel: asyncio.Event | None
    ) -> None:
        spec = rt.spec
        line = LineSimulator(spec.profile, seed=spec.seed)
        director = CallerDirector(
            rt,
            self._caller,
            BargeInScheduler(
                spec.persona.interruption_level,
                spec.seed,
                min_s=self._settings.barge_in_min_s,
                max_s=self._settings.barge_in_max_s,
            ),
        )
        pipeline = Pipeline(
            [
                AgentSource(rt, session),
                CallTap(rt),
                AgentTurnDetector(rt, self._vad_factory(self._settings)),
                AgentSTT(rt, self._stt),
                director,
                CallerTTS(rt, self._tts),
                CallerMic(rt, session, line),
            ]
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=AUDIO_SAMPLE_RATE, audio_out_sample_rate=AUDIO_SAMPLE_RATE
            ),
            idle_timeout_secs=None,
            cancel_on_idle_timeout=False,
            enable_turn_tracking=False,
            enable_rtvi=False,
            check_dangling_tasks=False,
        )
        runner = WorkerRunner(handle_sigint=False, handle_sigterm=False, check_dangling_tasks=False)
        await runner.add_workers(worker)
        runner_task = asyncio.create_task(runner.run(), name=f"call-{spec.call_id}")
        watchers = [asyncio.create_task(rt.finished.wait())]
        if cancel is not None:
            watchers.append(asyncio.create_task(cancel.wait()))
        try:
            done, _ = await asyncio.wait(
                [*watchers, runner_task], return_when=asyncio.FIRST_COMPLETED
            )
            if runner_task in done and not rt.finished.is_set():
                rt.finish("infra_error", "caller pipeline stopped unexpectedly")
            if cancel is not None and cancel.is_set():
                rt.finish("cancelled")
        finally:
            for w in watchers:
                w.cancel()
            with contextlib.suppress(Exception):
                await session.close()  # unblocks AgentSource before the pipeline is cancelled
            if not runner_task.done():
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(worker.cancel(), timeout=TEARDOWN_TIMEOUT_S)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(runner_task, timeout=TEARDOWN_TIMEOUT_S)
            if not runner_task.done():
                runner_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await runner_task

    @staticmethod
    def _result(rt: CallRuntime, reason: EndReason, error: str | None) -> CallResult:
        turns, tool_calls = rt.tracker.build()
        return CallResult(
            call_id=rt.spec.call_id,
            end_reason=reason,
            duration_ms=rt.ended_ms if rt.ended_ms is not None else rt.clock.now_ms(),
            turns=turns,
            tool_calls=tool_calls,
            events=sorted(rt.events, key=lambda e: e.t_ms),
            barge_in_attempts=rt.barge_attempts,
            usage=rt.usage,
            error=error,
            glass_box=rt.tracker.glass_box_seen,
        )
