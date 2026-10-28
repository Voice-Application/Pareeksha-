# Guide 4 · Send recordings in with the webhook source

Goal: have your telephony system, CRM or a cron job `POST` a finished call recording to Pareeksha, which transcribes it, works out who is the agent and who is the caller, and judges it with the same rubric as simulated calls.

**Prerequisite:** the stack from [Guide 1](01-quickstart.md), seeded, and `pareeksha login` done. An agent with the name you will send (`EMI Reminder Bot` is seeded).

## 1. Create a webhook integration

```bash
API=http://localhost:${API_HOST_PORT:-8000}/api/v1
AGENT_ID=$(curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" "$API/agents" \
  | python3 -c "import sys,json; print(next(a['id'] for a in json.load(sys.stdin)['items'] if a['name']=='EMI Reminder Bot'))")
curl -s -X POST "$API/integrations" -H "Authorization: Bearer $PAREEKSHA_API_KEY" -H "Content-Type: application/json" \
  -d "{\"connector\":\"webhook\",\"name\":\"Telephony recordings\",
       \"config\":{\"url\":\"https://example.com/pareeksha-results\",\"events\":[\"evaluation.completed\"],\"default_agent_id\":\"$AGENT_ID\"},
       \"secrets\":{\"signing_secret\":\"$(openssl rand -hex 24)\"}}" | tee /tmp/integration.json
```

The response has `id` and `signing_secret` (shown **once**, store it). It also has an `inbound_url`, which points at the **API** (`PUBLIC_API_URL`, default `http://localhost:${API_HOST_PORT:-8000}`): post recordings to `<inbound_url>`, i.e. `$API/webhooks/inbound/<id>`. `config.url` is the outbound sink address (https only); the same integration is both directions. `default_agent_id` is used when a payload's `agent_name` matches no agent.

## 2. Send a signed call

The body:

```json
{
  "external_id": "exotel-CA123",
  "recording_url": "https://recordings.example.com/CA123.mp3",
  "agent_name": "EMI Reminder Bot",
  "language": "kn-IN",
  "metadata": {"phone": "+919800000000", "crm_contact_id": "1234"}
}
```

Sign it Stripe-style: `X-Pareeksha-Timestamp` = unix seconds, `X-Pareeksha-Signature: v1=<hex(hmac_sha256(secret, f"{timestamp}.{raw_body}"))>`. Receivers reject timestamps older than 5 minutes (HTTP 408). A small sender:

```python
# send_call.py  ·  usage: python send_call.py <api_inbound_url> <signing_secret> <recording_url> <external_id>
import hashlib, hmac, json, sys, time, urllib.request
url, secret, rec, ext = sys.argv[1:5]
body = json.dumps({"external_id": ext, "recording_url": rec, "agent_name": "EMI Reminder Bot",
                   "language": "kn-IN", "metadata": {"phone": "+919800000000"}}).encode()
ts = str(int(time.time()))
sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
req = urllib.request.Request(url, body, {"Content-Type": "application/json",
    "X-Pareeksha-Timestamp": ts, "X-Pareeksha-Signature": f"v1={sig}"})
print(urllib.request.urlopen(req).read().decode())     # {"call_id":"...","duplicate":false}
```

Answers: `202 {"call_id":"...","duplicate":false}`; sending the same `external_id` again returns `duplicate:true` with the same `call_id` and creates nothing. `401 invalid_signature`, `408 timestamp_out_of_window`, `422 unsafe_url` / `unknown_agent`.

**Recording URL rules (SSRF guard):** `https` only, no credentials in the URL, the hostname must resolve to a public address (loopback, private and link-local are refused), at most 10 MB, `Content-Type: audio/*`, WAV or MP3.

## 3. Watch it being judged

```bash
CALL_ID=<call_id from the answer>
curl -s -H "Authorization: Bearer $PAREEKSHA_API_KEY" "$API/calls/$CALL_ID" | python3 -m json.tool | head -30
```

`status` moves `transcribing` to `completed`; then `evaluation.overall_score` and the verdict appear, and the call shows up under Audits in the web app. If the agent/caller roles were guessed wrong, `POST /calls/{id}/speaker-map` with `{"spk_0":"caller","spk_1":"agent"}` re-judges without re-transcribing.

## 4. Local testing without a public recording host

Local receivers on `localhost` are blocked on purpose. For development only, switch the guard to allow private addresses and let the containers trust your self-signed certificate:

```bash
# serve ./rec/call.wav over https with a self-signed cert on the host (port 8443)
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 1 -subj "/CN=host.docker.internal" \
  -addext "subjectAltName=DNS:host.docker.internal"
cat > docker-compose.dev-webhook.yml <<'YAML'
services:
  api:                                  # checks the recording URL when the webhook arrives
    environment: { PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS: "1" }
  auditor:                              # downloads the recording
    environment: { PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS: "1", SSL_CERT_FILE: /dev-cert.pem }
    volumes: ["./cert.pem:/dev-cert.pem:ro"]
YAML
docker compose -f docker-compose.yml -f docker-compose.dev-webhook.yml --profile workers up -d api auditor
```

Then use `https://host.docker.internal:8443/call.wav` as `recording_url` (any WAV or MP3 served from `./rec`, for example `python3 -m http.server`-style over TLS; `backend/tests/fixtures/agent_greeting_5s.wav` works for a smoke test). `SSL_CERT_FILE` replaces the system trust store inside that container, which is fine for the auditor's local download. **Never set `PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS` in production**: it disables the private-address check (https, no-credentials and IP pinning still apply). The same switch relaxes the outbound webhook sink target check.

## 5. Receive the results (sink side)

When the call is judged, the integration POSTs `evaluation.completed` to `config.url`, signed with the same scheme (verify the signature and the 5-minute window on your side, constant-time compare). Payload: `event_id`, `type`, `occurred_at`, and `data` with `call_id`, `agent`, `overall_score`, `passed`, `critical_failure`, `failure_types`, `summary`, `link`, `metadata`. No transcript or audio is sent. Deliveries (status, HTTP code, response excerpt) are listed by `GET /integrations/{id}/deliveries`; failures retry, then land in the DLQ ([Guide 8](08-operating-kafka.md)).
