# Guide 2 · Connect your Pipecat bot

Goal: let Pareeksha call a bot you built with [Pipecat](https://github.com/pipecat-ai/pipecat) over its `FastAPIWebsocketTransport`, with glass-box events (what the bot heard, what it will say, tool calls). About five lines change in your bot.

**Prerequisite:** the stack from [Guide 1](01-quickstart.md) is running and seeded, and `pareeksha login` is done.

## 1. Add the serializer to your transport

`PareekshaFrameSerializer` maps the `pareeksha-audio-v1` wire format (PCM s16le, 16 kHz, 20 ms frames, JSON control messages) to Pipecat frames. It is one file, `backend/pareeksha/adapters/pipecat_serializer.py`; either install the package (`pip install -e ./backend --no-deps` in an environment that already has Pipecat) or copy the file into your repo.

```python
from pareeksha.adapters.base import AUDIO_FRAME_BYTES
from pareeksha.adapters.pipecat_serializer import GlassBoxProcessor, PareekshaFrameSerializer

serializer = PareekshaFrameSerializer()
transport = FastAPIWebsocketTransport(websocket=ws, params=FastAPIWebsocketParams(
    audio_in_enabled=True, audio_out_enabled=True,
    audio_in_sample_rate=16000, audio_out_sample_rate=16000,
    fixed_audio_packet_size=AUDIO_FRAME_BYTES,      # whole 20 ms frames
    serializer=serializer))

# optional glass box: one processor after STT (what the bot heard), one after the LLM
# (what it will say + tool calls), both before TTS
Pipeline([transport.input(), stt, GlassBoxProcessor(), user_agg, llm, GlassBoxProcessor(), tts,
          transport.output(), assistant_agg])
```

`serializer.start_message` holds the platform's `start` message (call id, `language_hint`, metadata); `serializer.language` is the language the caller is using, so pick your STT/TTS language from it.

## 2. Try the bundled example first

`examples/pipecat-bot/` is a complete EMI-reminder bot (Gnani STT, DeepSeek, Gnani TTS) wired exactly as above.

```bash
python3 -m venv .venv-bot && . .venv-bot/bin/activate
pip install -r examples/pipecat-bot/requirements.txt      # Pipecat + the few libraries the speech wrapper needs
pip install -e ./backend --no-deps                     # the pareeksha package (serializer, speech providers)
set -a; . ./.env; set +a
cd examples/pipecat-bot && PYTHONPATH=.:../../backend python bot.py      # ws://0.0.0.0:8766/ws
```

Check it: `curl -s http://localhost:8766/health`.

## 3. Register it as an agent

The simulator runs inside Docker, so the endpoint must be reachable from the container. On Docker Desktop and with this repo's compose file `host.docker.internal` resolves to the host:

```bash
pareeksha login --url http://localhost:${API_HOST_PORT:-8000} --key "$PAREEKSHA_API_KEY"   # once
cat > pareeksha.yaml <<'YAML'
version: 1
agent:
  name: Pipecat EMI Bot
  adapter: pipecat
  endpoint_url: ws://host.docker.internal:8766/ws
  languages: [en-IN, hi-IN]
  glass_box: true
scenarios:
  - title: Already paid, wants confirmation
    caller_goal: Say the EMI was paid yesterday and ask for confirmation.
    success_criteria: Agent verifies the payment instead of demanding it again.
    tags: [payment_dispute]
suites:
  smoke:
    scenarios: {tags: [payment_dispute]}
    personas: ["Rohit — millennial"]
    noise_profiles: [clean_16k]
    fail_under: 50
YAML
pareeksha apply -f pareeksha.yaml
```

(Or use the web app: Agents, New agent, adapter `pipecat`.) Then test the connection. It opens a socket, sends `start`, and waits for the first audio:

```bash
curl -s -X POST -H "Authorization: Bearer $PAREEKSHA_API_KEY" \
  http://localhost:${API_HOST_PORT:-8000}/api/v1/agents/$(curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" \
  "http://localhost:${API_HOST_PORT:-8000}/api/v1/agents" | python3 -c "import sys,json; d=json.load(sys.stdin); print(next(a['id'] for a in d['items'] if a['name']=='Pipecat EMI Bot'))")/test-connection
# {"ok":true,"first_audio_ms":...,"protocol":"pareeksha-audio-v1","glass_box_messages_seen":true}
```

## 4. Run a call

```bash
pareeksha run --suite smoke --wait
```

The transcript in the web app shows glass-box rows (what your bot heard versus what the caller said), which feeds the ASR-error metrics.

## Notes

- Glass-box text must travel as `OutputTransportMessageUrgentFrame`; `GlassBoxProcessor` does this for you. Ordinary message frames arrive only after the audio has played.
- `pipecat-gnani` 0.5.12 does not import against `gnani-vachana` 0.8.2, so the example wraps `pareeksha.speech` providers (`speech_services.py`). Use your own STT/TTS services freely.
- Contract test of the serializer against a scripted pipeline: `cd backend && pytest tests/contract/test_adapter_contract.py`.
