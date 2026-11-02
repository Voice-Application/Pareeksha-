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
#: 20 ms of 16 kHz PCM16 mono (the pareeksha-audio-v1 frame).
FRAME_BYTES = 640


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

    def _bar(self, floor: float | None) -> float:
        """Level a frame must reach to count as speech."""
        return self.threshold if floor is None else max(self.threshold, floor * self.speech_ratio)

    def _real_speech(self) -> bool:
        """Does the buffered utterance still hold ``min_speech_ms`` of speech against the current
        floor? Drops an "utterance" that was only line noise heard before the floor was known."""
        bar = self._bar(self.noise_floor)
        frames = (self._buf[i : i + FRAME_BYTES] for i in range(0, len(self._buf), FRAME_BYTES))
        voiced = sum(1 for f in frames if rms(f) >= bar)
        return voiced * FRAME_MS >= self.min_speech_ms

    @property
    def floor_known(self) -> bool:
        """True once the noise floor is measured (barge-in only counts from then on)."""
        return self.noise_floor is not None

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
        # In the first half second the floor is unknown: the absolute threshold alone decides, and
        # the utterance is checked against the floor when it closes (see _real_speech).
        voiced = level >= self._bar(floor)
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
            utterance = (
                bytes(self._buf)
                if self.speech_ms >= self.min_speech_ms and self._real_speech()
                else None
            )
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
