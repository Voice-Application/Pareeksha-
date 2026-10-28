# Pipecat bot example (EMI reminder)

A complete Pipecat bot that Pareeksha can call: Gnani STT -> DeepSeek -> Gnani TTS over a
`FastAPIWebsocketTransport`. It is an ordinary Pipecat pipeline plus the three Pareeksha pieces
below. Docs: `docs/10-integrations-and-dx.md` section 4.

## Add Pareeksha to your own Pipecat bot (about five lines)

```python
from pareeksha.adapters.base import AUDIO_FRAME_BYTES
from pareeksha.adapters.pipecat_serializer import GlassBoxProcessor, PareekshaFrameSerializer

serializer = PareekshaFrameSerializer()
transport = FastAPIWebsocketTransport(websocket=ws, params=FastAPIWebsocketParams(
    audio_in_enabled=True, audio_out_enabled=True,
    audio_in_sample_rate=16000, audio_out_sample_rate=16000,
    fixed_audio_packet_size=AUDIO_FRAME_BYTES,          # whole 20 ms frames
    serializer=serializer))
# optional glass box: one processor after STT (what the bot heard), one after the LLM (what it
# says + tool calls), both before TTS:
Pipeline([transport.input(), stt, GlassBoxProcessor(), user_agg, llm, GlassBoxProcessor(), tts,
          transport.output(), assistant_agg])
```

`serializer.start_message` holds the platform's `start` message (call id, `language_hint`,
metadata); `serializer.language` is the language to speak. The serializer is a single file
(`backend/pareeksha/adapters/pipecat_serializer.py`); copy it if you do not want to install the
`pareeksha` package. Wire format: `docs/06-api-spec.md` section 7 (`pareeksha-audio-v1`).

## Run this example

```
pip install -r requirements.txt
GNANI_API_KEY=... DEEPSEEK_API_KEY=... PYTHONPATH=../../backend:. python bot.py   # ws://localhost:8766/ws
```

Register an agent in Pareeksha with adapter `pipecat` and endpoint `ws://<host>:8766/ws`.
`speech_services.py` wraps `pareeksha.speech` providers because `pipecat-gnani` 0.5.12 does not
import against `gnani-vachana` 0.8.2; swap in your own STT/TTS services freely.

Contract test (scripted STT/LLM/TTS, real transport and serializer):
`cd backend && pytest tests/contract/test_adapter_contract.py`.
