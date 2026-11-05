"""Energy VAD over 20 ms PCM16 frames, with a hangover so short pauses do not end an utterance.

A frame is speech when it is above ``threshold`` and well above the line's own noise, so steady noise
at 5 or 10 dB SNR (which is above ``threshold``) is neither heard as the caller nor hides them.
"""

from __future__ import annotations

import array
import math
from collections import deque
from dataclasses import dataclass, field

FRAME_MS = 20
#: The noise floor is the 20th percentile of the last 10 s of frame levels: a caller would have to
#: talk through 80% of that window to move it.
NOISE_WINDOW_FRAMES = 500
#: 1.2 s of line before the floor is trusted. Speech that fills 80% of this (a caller talking within
#: 240 ms of connecting, and for over a second) reads as noise and loses its start.
NOISE_WARMUP_FRAMES = 60


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
    noise_ratio: float = 2.0
    end_silence_ms: int = 700
    min_speech_ms: int = 200
    speaking: bool = False
    voiced: bool = False
    speech_ms: int = 0
    silence_ms: int = 0
    _buf: bytearray = field(default_factory=bytearray)
    _levels: deque[float] = field(default_factory=lambda: deque(maxlen=NOISE_WINDOW_FRAMES))

    def measure(self, frame: bytes) -> float:
        """Add a frame to the noise floor; the only part that runs while the VAD itself is off."""
        level = rms(frame)
        self._levels.append(level)
        return level

    @property
    def noise_known(self) -> bool:
        return len(self._levels) >= NOISE_WARMUP_FRAMES

    def feed(self, frame: bytes) -> bytes | None:
        level = self.measure(frame)
        cut = self.threshold
        if self.noise_known:
            floor = sorted(self._levels)[len(self._levels) // 5]
            cut = max(self.threshold, self.noise_ratio * floor)
            if len(self._levels) == NOISE_WARMUP_FRAMES and cut > self.threshold:
                self.reset()  # what the warm-up took for speech was the line
        self.voiced = level >= cut
        if self.voiced:
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            if not self.speaking and self.speech_ms >= FRAME_MS * 3:
                self.speaking = True
        else:
            self.silence_ms += FRAME_MS
        if self.speaking or self.voiced:
            self._buf += frame
        if self.speaking and self.silence_ms >= self.end_silence_ms:
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
        self.speaking = False
        self.speech_ms = 0
        self.silence_ms = 0
        self._buf = bytearray()
