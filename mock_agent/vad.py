"""Energy VAD over 20 ms PCM16 frames, with a hangover so short pauses do not end an utterance."""

from __future__ import annotations

import array
import math
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
    speaking: bool = False
    speech_ms: int = 0
    silence_ms: int = 0
    _buf: bytearray = field(default_factory=bytearray)

    def feed(self, frame: bytes) -> bytes | None:
        voiced = rms(frame) >= self.threshold
        if voiced:
            self.speech_ms += FRAME_MS
            self.silence_ms = 0
            if not self.speaking and self.speech_ms >= FRAME_MS * 3:
                self.speaking = True
        else:
            self.silence_ms += FRAME_MS
        if self.speaking or voiced:
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
