"""``pipecat`` adapter (VOICE-06): reach a bot whose transport uses ``PareekshaFrameSerializer``.

On the wire this is ``pareeksha-audio-v1`` (the serializer maps protocol frames to Pipecat frames
on the bot side), so the platform side reuses the ``audio_v1`` client. The one difference is audio
framing: a Pipecat transport sends whatever chunk size its audio pipeline produces, so this session
re-frames the agent's PCM into the 20 ms frames the simulator expects.
"""

from __future__ import annotations

from typing import ClassVar

from pareeksha.adapters.audio_v1 import AudioV1Adapter, AudioV1Session
from pareeksha.adapters.base import AUDIO_FRAME_BYTES, AdapterName, AgentAudio, AgentEvent


class PipecatSession(AudioV1Session):
    """``audio_v1`` session that delivers agent audio as whole 20 ms frames."""

    _pcm_tail: bytes = b""

    def _on_binary(self, data: bytes) -> list[AgentEvent]:
        buffered = self._pcm_tail + data
        usable = len(buffered) - len(buffered) % AUDIO_FRAME_BYTES
        self._pcm_tail = buffered[usable:]
        return [
            AgentAudio(buffered[i : i + AUDIO_FRAME_BYTES])
            for i in range(0, usable, AUDIO_FRAME_BYTES)
        ]


class PipecatAdapter(AudioV1Adapter):
    name: ClassVar[AdapterName] = "pipecat"
    session_class: ClassVar[type[AudioV1Session]] = PipecatSession
