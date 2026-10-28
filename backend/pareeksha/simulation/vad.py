"""Voice activity on the agent's audio, using Pipecat's VAD analyzers (Silero by default).

``SpeechGate`` feeds 20 ms frames to a ``pipecat.audio.vad.vad_analyzer.VADAnalyzer`` and turns its
QUIET / STARTING / SPEAKING / STOPPING states into start and end events stamped on the call clock:

- ``start_ms`` is the arrival time of the first frame of the analysis window that began the speech
  (the analyzer needs ``vad_start_s`` of speech to confirm it, so the event is raised late but
  stamped early);
- ``end_ms`` is the last frame that still counted as speech, ``stop_secs`` before the analyzer
  declared silence.

Latency (FR-EV-1) is measured from these stamps, so they never include the VAD hangover.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass
from typing import Literal

from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams, VADState

from pareeksha.adapters.base import AUDIO_FRAME_MS, AUDIO_SAMPLE_RATE


def frame_rms(frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class EnergyVADAnalyzer(VADAnalyzer):
    """Loudness-threshold analyzer: deterministic, model-free (tests and a fallback)."""

    def __init__(
        self,
        *,
        threshold: float = 500.0,
        sample_rate: int | None = AUDIO_SAMPLE_RATE,
        params: VADParams | None = None,
    ) -> None:
        super().__init__(
            sample_rate=sample_rate, params=params or VADParams(confidence=0.5, min_volume=0.0)
        )
        self._threshold = threshold

    def num_frames_required(self) -> int:
        return AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS // 1000

    def voice_confidence(self, buffer: bytes) -> float:
        return 1.0 if frame_rms(buffer) >= self._threshold else 0.0


@dataclass(frozen=True)
class SpeechEdge:
    kind: Literal["start", "end"]
    #: Call-clock milliseconds of the speech edge itself (see module docstring).
    t_ms: int
    #: Call-clock milliseconds at which the gate noticed it.
    detected_ms: int


class SpeechGate:
    def __init__(self, analyzer: VADAnalyzer) -> None:
        self._analyzer = analyzer
        self._analyzer.set_sample_rate(AUDIO_SAMPLE_RATE)
        #: Audio the analyzer classifies at a time (Silero: 512 samples = 32 ms).
        self._window_ms = analyzer.num_frames_required() * 1000 // AUDIO_SAMPLE_RATE
        self._state = VADState.QUIET
        self._candidate_ms = 0
        self._last_voiced_ms = 0
        self._speaking = False

    @property
    def speaking(self) -> bool:
        return self._speaking

    async def feed(self, frame: bytes, arrived_ms: int) -> list[SpeechEdge]:
        """``arrived_ms`` = call-clock time at which ``frame`` (the newest audio) arrived."""
        previous = self._state
        state = await self._analyzer.analyze_audio(frame)
        self._state = state
        edges: list[SpeechEdge] = []
        if state is VADState.STARTING and previous is VADState.QUIET:
            self._candidate_ms = max(0, arrived_ms + AUDIO_FRAME_MS - self._window_ms)
        if state in (VADState.SPEAKING, VADState.STARTING):
            self._last_voiced_ms = arrived_ms
        if state is VADState.SPEAKING and not self._speaking:
            self._speaking = True
            edges.append(SpeechEdge("start", self._candidate_ms, arrived_ms))
        elif state is VADState.QUIET and self._speaking:
            self._speaking = False
            edges.append(SpeechEdge("end", self._last_voiced_ms, arrived_ms))
        return edges

    def flush(self, now_ms: int) -> SpeechEdge | None:
        """Close speech that is still open (the stream ended)."""
        if not self._speaking:
            return None
        self._speaking = False
        return SpeechEdge("end", self._last_voiced_ms, now_ms)

    async def cleanup(self) -> None:
        await self._analyzer.cleanup()  # type: ignore[no-untyped-call]
