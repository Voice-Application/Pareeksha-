"""Three aligned recordings of a call (FR-RN-7): caller, agent (mono) and a stereo mix.

Both tracks are laid on one timeline by arrival time on the call clock, with silence in the gaps
(agents may omit silence frames). ``finalize`` pads both to the same length, so the three files
have exactly the same duration. The caller track is what left the platform *after* the line
simulator (degraded), the agent track is what arrived.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2


class _Track:
    def __init__(self) -> None:
        self._buf = bytearray()

    @property
    def samples(self) -> int:
        return len(self._buf) // BYTES_PER_SAMPLE

    def write(self, pcm: bytes, at_sample: int) -> None:
        """Append at ``at_sample``; earlier audio is never overwritten (no overlap in a track)."""
        gap = at_sample - self.samples
        if gap > 0:
            self._buf += bytes(gap * BYTES_PER_SAMPLE)
        self._buf += pcm[: len(pcm) // BYTES_PER_SAMPLE * BYTES_PER_SAMPLE]

    def padded(self, samples: int) -> bytes:
        if self.samples >= samples:
            return bytes(self._buf[: samples * BYTES_PER_SAMPLE])
        return bytes(self._buf) + bytes((samples - self.samples) * BYTES_PER_SAMPLE)


def _wav(pcm: bytes, channels: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(BYTES_PER_SAMPLE)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return out.getvalue()


@dataclass(frozen=True)
class Recordings:
    caller_wav: bytes
    agent_wav: bytes
    mixed_wav: bytes
    duration_ms: int

    def save(self, directory: Path) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        paths = {
            "caller": directory / "caller.wav",
            "agent": directory / "agent.wav",
            "mixed": directory / "mixed.wav",
        }
        paths["caller"].write_bytes(self.caller_wav)
        paths["agent"].write_bytes(self.agent_wav)
        paths["mixed"].write_bytes(self.mixed_wav)
        return paths


class AudioRecorder:
    """Collects both directions; ``finalize`` renders the WAV files."""

    def __init__(self) -> None:
        self._caller = _Track()
        self._agent = _Track()

    @staticmethod
    def _sample_at(t_ms: float) -> int:
        return max(0, round(t_ms * SAMPLE_RATE / 1000))

    def add_caller(self, pcm: bytes, t_ms: float) -> None:
        """``t_ms`` = when the frame started (call clock)."""
        self._caller.write(pcm, self._sample_at(t_ms))

    def add_agent(self, pcm: bytes, t_ms: float) -> None:
        """``t_ms`` = when the frame was received; contiguous frames queue back to back."""
        self._agent.write(pcm, self._sample_at(t_ms))

    @property
    def duration_ms(self) -> int:
        return int(max(self._caller.samples, self._agent.samples) * 1000 / SAMPLE_RATE)

    def finalize(self, duration_ms: int | None = None) -> Recordings:
        samples = max(self._caller.samples, self._agent.samples)
        if duration_ms is not None:
            samples = max(samples, self._sample_at(duration_ms))
        caller = self._caller.padded(samples)
        agent = self._agent.padded(samples)
        stereo = np.empty(samples * 2, dtype="<i2")
        stereo[0::2] = np.frombuffer(caller, dtype="<i2")  # left = caller
        stereo[1::2] = np.frombuffer(agent, dtype="<i2")  # right = agent
        return Recordings(
            caller_wav=_wav(caller, 1),
            agent_wav=_wav(agent, 1),
            mixed_wav=_wav(stereo.tobytes(), 2),
            duration_ms=int(samples * 1000 / SAMPLE_RATE),
        )
