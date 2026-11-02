"""Energy VAD over 20 ms PCM16 frames, with a hangover so short pauses do not end an utterance.

A frame is speech when it is above the absolute ``threshold`` AND ``speech_ratio`` times above the
noise floor (EVAL-07, ISSUE-1). The floor is a low percentile of the frame levels of the last few
seconds, so a steady noise bed (street, office babble) becomes the floor within ``floor_window_ms``
and no longer reads as endless speech, while speech (which has pauses between syllables and words)
does not lift it.
``max_utterance_ms`` closes an utterance that never meets the end silence, so the agent always
gets a turn to answer.
"""

from __future__ import annotations

import array
import math
from collections import deque
from dataclasses import dataclass, field

FRAME_MS = 20


def rms(frame: bytes) -> float:
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class UtteranceDetector:
    """Feed frames; ``feed`` returns the utterance PCM once speech is followed by silence."""

    threshold: float = 500.0
    end_silence_ms: int = 700
    min_speech_ms: int = 200
    #: A frame must be this many times the noise floor to count as speech (2.5 = +8 dB).
    speech_ratio: float = 2.5
    #: The noise floor is this percentile of the frame levels in the last ``floor_window_ms``.
    floor_percentile: float = 0.10
    floor_window_ms: int = 5000
    #: An utterance this long is closed even without end silence.
    max_utterance_ms: int = 12000
    _levels: deque[float] = field(default_factory=deque)
    utterance_ms: int = 0
    speaking: bool = False
    speech_ms: int = 0
    silence_ms: int = 0
    _buf: bytearray = field(default_factory=bytearray)

    @property
    def noise_floor(self) -> float | None:
        """Low percentile of recent frame levels; None until half a second has been heard."""
        if len(self._levels) < 500 // FRAME_MS:
            return None
        ordered = sorted(self._levels)
        return ordered[int(self.floor_percentile * (len(ordered) - 1))]

    def _track_floor(self, level: float) -> None:
        self._levels.append(level)
        if len(self._levels) > self.floor_window_ms // FRAME_MS:
            self._levels.popleft()

    def feed(self, frame: bytes) -> bytes | None:
        level = rms(frame)
        floor = self.noise_floor
        # No speech is detected in the first half second, while the floor is still unknown.
        voiced = floor is not None and level >= max(self.threshold, floor * self.speech_ratio)
        self._track_floor(level)
        if voiced:
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            if not self.speaking and self.speech_ms >= FRAME_MS * 3:
                self.speaking = True
        else:
            self.silence_ms += FRAME_MS
        if self.speaking or voiced:
            self._buf += frame
        if self.speaking:
            self.utterance_ms += FRAME_MS
        if self.speaking and (
            self.silence_ms >= self.end_silence_ms or self.utterance_ms >= self.max_utterance_ms
        ):
            utterance = bytes(self._buf) if self.speech_ms >= self.min_speech_ms else None
            self.reset()
            return utterance
        if not self.speaking and self.silence_ms >= self.end_silence_ms:
            self.reset()
        return None

    @property
    def speech_started(self) -> bool:
        return self.speaking

    def reset(self) -> None:
        """End the current utterance; the noise floor is kept (it describes the line, not a turn)."""
        self.utterance_ms = 0
        self.speaking = False
        self.speech_ms = 0
        self.silence_ms = 0
        self._buf = bytearray()
