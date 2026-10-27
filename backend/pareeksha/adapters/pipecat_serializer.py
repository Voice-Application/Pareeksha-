"""``PareekshaFrameSerializer``: Pipecat <-> ``pareeksha-audio-v1`` (docs/10-integrations §4).

A bot team adds it to the transport they already run (about five lines)::

    transport = FastAPIWebsocketTransport(
        websocket=ws,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True,
            serializer=PareekshaFrameSerializer(),
            fixed_audio_packet_size=AUDIO_FRAME_BYTES,   # whole 20 ms frames
        ),
    )

and puts a ``GlassBoxProcessor()`` after the STT service (what the bot heard) and another after
the LLM, before TTS (what it says and the tools it runs); glass box is optional.

Wire (platform <-> bot): binary frames are PCM s16le mono 16 kHz; text frames are JSON
``start`` / ``stop`` (platform to bot) and ``transcript`` / ``tool_call`` / ``call_end`` (bot to
platform). Pipecat's websocket output transport only hands the serializer audio, interruption,
end/cancel and transport-message frames, so glass-box events travel as
``OutputTransportMessageFrame`` produced by ``GlassBoxProcessor``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    FunctionCallResultFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    StartFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.base_serializer import FrameSerializer

from pareeksha.adapters.base import (
    AUDIO_SAMPLE_RATE,
    CallEndMessage,
    StartMessage,
    StopMessage,
)

#: Glass-box message types the bot may publish through transport messages.
GLASS_BOX_TYPES = frozenset({"transcript", "tool_call", "call_end"})


class PareekshaFrameSerializer(FrameSerializer):
    """Maps ``pareeksha-audio-v1`` frames to Pipecat frames and back."""

    def __init__(self, params: FrameSerializer.InputParams | None = None, **kwargs: Any) -> None:
        super().__init__(params, **kwargs)
        self._in_resampler = create_stream_resampler()
        self._out_resampler = create_stream_resampler()
        #: Set by the platform's ``start`` message (call_id, language_hint, metadata).
        self.start_message: StartMessage | None = None

    @property
    def language(self) -> str:
        """BCP-47 language of the call, from the platform's ``start`` message."""
        start = self.start_message
        return start.language_hint if start and start.language_hint else "en-IN"

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputAudioRawFrame):
            pcm = await self._out_resampler.resample(
                frame.audio, frame.sample_rate, AUDIO_SAMPLE_RATE
            )
            return pcm or None
        if isinstance(frame, EndFrame):
            return CallEndMessage(reason="completed").model_dump_json()
        if isinstance(frame, CancelFrame):
            return CallEndMessage(reason="cancelled").model_dump_json()
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            message = frame.message
            if isinstance(message, dict) and message.get("type") in GLASS_BOX_TYPES:
                return json.dumps(message, ensure_ascii=False)
        # InterruptionFrame needs no wire message: the platform hears the audio stop.
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, bytes):
            if not data:
                return None
            return InputAudioRawFrame(audio=data, sample_rate=AUDIO_SAMPLE_RATE, num_channels=1)
        try:
            decoded = json.loads(data)
        except ValueError:
            return None
        kind = decoded.get("type") if isinstance(decoded, dict) else None
        if kind == "start":
            self.start_message = StartMessage.model_validate(decoded)
            return None
        if kind == "stop":
            reason = StopMessage.model_validate(decoded).reason
            return EndFrame(reason=reason)
        return None


class GlassBoxProcessor(FrameProcessor):
    """Publishes the bot's own view of the call: what it heard, said and which tools it ran.

    Place one after the STT service and one after the LLM service (before TTS). It turns
    ``TranscriptionFrame`` (user speech),
    the LLM's streamed text (one ``agent`` transcript per response) and ``FunctionCallResultFrame``
    into ``OutputTransportMessageUrgentFrame`` frames that ``PareekshaFrameSerializer`` sends on.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._t0 = time.monotonic()
        self._agent_text: list[str] = []

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self._t0 = time.monotonic()
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            await self._publish(
                {"type": "transcript", "role": "user", "text": frame.text, "t_ms": self._now_ms()}
            )
        elif isinstance(frame, LLMTextFrame):
            self._agent_text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            text = "".join(self._agent_text).strip()
            self._agent_text.clear()
            if text:
                await self._publish(
                    {"type": "transcript", "role": "agent", "text": text, "t_ms": self._now_ms()}
                )
        elif isinstance(frame, FunctionCallResultFrame):
            result = frame.result if isinstance(frame.result, dict) else {"value": frame.result}
            await self._publish(
                {
                    "type": "tool_call",
                    "name": frame.function_name,
                    "arguments": frame.arguments if isinstance(frame.arguments, dict) else {},
                    "result": result,
                    "t_ms": self._now_ms(),
                }
            )
        elif isinstance(frame, InterruptionFrame):
            self._agent_text.clear()
        await self.push_frame(frame, direction)

    async def _publish(self, message: dict[str, Any]) -> None:
        # Urgent (system) frames skip the TTS queue, so the text reaches the platform when the
        # LLM finishes rather than after the audio has played.
        await self.push_frame(OutputTransportMessageUrgentFrame(message=message))
