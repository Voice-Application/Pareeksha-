# Guide 3 · Connect any bot with `pareeksha-audio-v1`

Goal: expose a WebSocket endpoint from any voice stack (your own server, Twilio-style media bridge, a prototype) that Pareeksha can call.

**Prerequisite:** the stack from [Guide 1](01-quickstart.md), seeded.

## The protocol in one screen

Pareeksha is the WebSocket **client**; your bot is the **server**. One socket per call.

- **Binary frames, both directions:** raw PCM, signed 16-bit little-endian, mono, 16 000 Hz, 20 ms per frame (640 bytes), at real-time pace.
- **Platform to bot (text):** `{"type":"start","protocol":"pareeksha-audio-v1","call_id":"...","sample_rate":16000,"language_hint":"kn-IN","metadata":{}}` first, and `{"type":"stop","reason":"caller_hangup"}` at the end.
- **Bot to platform (text, all optional, enables glass-box metrics):**
  `{"type":"transcript","role":"user","text":"...","is_final":true,"t_ms":9450}` (what your STT heard),
  `{"type":"transcript","role":"agent","text":"..."}` (what you are about to say),
  `{"type":"tool_call","name":"record_promise_to_pay","arguments":{},"result":{}}`,
  `{"type":"call_end","reason":"completed"}`.
- The bot normally speaks first. Either side may close the socket.
- `GET /health` over plain HTTP on the same port is used by the "Test connection" button if it answers 200 (optional).

Full spec: `docs/06-api-spec.md` section 7.

## A minimal server (Python, `websockets`)

Save as `echo_bot.py`. It greets, then echoes back whatever audio it hears, which is enough to prove the plumbing.

```python
import asyncio, json
from websockets.asyncio.server import serve

FRAME = b"\x00\x00" * 320            # 20 ms of silence at 16 kHz

async def handler(ws):
    start = json.loads(await ws.recv())            # the "start" message
    assert start["protocol"] == "pareeksha-audio-v1"
    await ws.send(json.dumps({"type": "transcript", "role": "agent", "text": "Namaskara, this is a test bot."}))
    for _ in range(50):                            # one second of (silent) greeting
        await ws.send(FRAME)
        await asyncio.sleep(0.02)
    async for msg in ws:
        if isinstance(msg, bytes):
            await ws.send(msg)                     # echo the caller's audio back
        elif json.loads(msg)["type"] == "stop":
            break
    await ws.send(json.dumps({"type": "call_end", "reason": "completed"}))

async def main():
    async with serve(handler, "0.0.0.0", 8770):
        await asyncio.Future()

asyncio.run(main())
```

```bash
pip install websockets
python echo_bot.py &
```

## Register and test

```bash
pareeksha login --url http://localhost:${API_HOST_PORT:-8000} --key "$PAREEKSHA_API_KEY"
cat > pareeksha.yaml <<'YAML'
version: 1
agent:
  name: Echo Bot
  adapter: audio_v1
  endpoint_url: ws://host.docker.internal:8770/ws
  languages: [en-IN]
  glass_box: true
YAML
pareeksha apply -f pareeksha.yaml
```

Test the connection (replace `<id>` with the agent id from `curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" http://localhost:8000/api/v1/agents`):

```bash
curl -s -X POST -H "Authorization: Bearer $PAREEKSHA_API_KEY" http://localhost:${API_HOST_PORT:-8000}/api/v1/agents/<id>/test-connection
# {"ok":true,"first_audio_ms":...,"protocol":"pareeksha-audio-v1","glass_box_messages_seen":true}
```

An `ok:false` answer carries `error` (`timeout`, `connect_failed`, ...) and `detail`.

## Tips

- From the simulator container, `localhost` is the container itself. Use `host.docker.internal` (mapped in this repo's compose), a compose service name, or a public hostname.
- Send audio at real-time pace; bursts confuse barge-in timing metrics.
- Declare `mandatory_disclosures`, `forbidden_phrases` and `expected_tools` on the agent (see `sdk/python/pareeksha.example.yaml`) so the deterministic checks can score your bot.
- The reference implementation is `mock_agent/server.py` (scripted EMI bot with five planted bugs).
