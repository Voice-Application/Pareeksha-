"""INT-03 end-to-end: webhook import -> audit -> evaluation -> sink note, through real Kafka.

    cd backend && PYTHONPATH=. python ../proof/INT-03/run_e2e.py ../proof/INT-03

Real: Postgres + Kafka (private compose stack), the HTTP API (uvicorn) and the workers
``outbox_relay``, ``auditor``, ``evaluator``, ``integrations`` as separate processes, Gnani batch STT
(diarize + denoise), DeepSeek (role check + judge), a local HTTPS receiver that serves the recording
(the imported URL) and receives the signed sink delivery. The recording is the two-speaker TTS clip
from EVAL-04 (no human voices, no new TTS spend). Needs GNANI_API_KEY and DEEPSEEK_API_KEY in the
environment; DATABASE_URL / KAFKA_BOOTSTRAP_SERVERS point at the private stack.

The HubSpot sink is NOT exercised: HUBSPOT_ACCESS_TOKEN is not set (see proof.md).
"""

from __future__ import annotations

import json
import os
import secrets
import ssl
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import psycopg
from alembic import command
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from pareeksha.integrations.signing import SignatureError, sign_headers, verify_signature
from tests.conftest import alembic_config
from tests.integration.webhook_receiver import make_certificate

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "../proof/INT-03").resolve()
SERVER = os.environ["DATABASE_URL"]
KAFKA = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
API_PORT = int(os.environ.get("INT03_API_PORT", "28000"))
RECEIVER_PORT = int(os.environ.get("INT03_RECEIVER_PORT", "28443"))
LANGUAGE = "hi-IN"
LIMIT_S = 180  # GOAL item 5: a note within 3 minutes
WORKERS = ["outbox_relay", "auditor", "evaluator", "integrations"]
SINK_SECRET = "int03-sink-secret-" + secrets.token_hex(8)

events: list[dict[str, Any]] = []


def log(msg: str) -> None:
    print(msg, flush=True)


def stamp(name: str, **extra: Any) -> float:
    now = time.time()
    events.append(
        {"event": name, "at": datetime.fromtimestamp(now, UTC).isoformat(timespec="milliseconds"), **extra}
    )
    log(f"[{events[-1]['at']}] {name} {extra if extra else ''}")
    return now


# ------------------------------------------------------------------------------ local receiver
class State:
    wav = b""
    notes: list[dict[str, Any]] = []
    recording_fetches = 0
    lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/recordings/CA-int03.wav":
            self.send_error(404)
            return
        with State.lock:
            State.recording_fetches += 1
        stamp("recording downloaded from the import URL", bytes=len(State.wav))
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(State.wav)))
        self.end_headers()
        self.wfile.write(State.wav)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        headers = dict(self.headers.items())
        try:
            verify_signature(headers, body, SINK_SECRET)
            ok = True
        except SignatureError:
            ok = False
        if ok and json.loads(body).get("type") == "ping":
            self._reply(200, {"pong": True})
            return
        with State.lock:
            State.notes.append({"received_at": time.time(), "signature_ok": ok, "body": json.loads(body)})
        if ok:
            stamp("sink delivery received (CRM-note stand-in)", signature_ok=ok)
        self._reply(200 if ok else 401, {"received": ok})

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:
        return


def start_receiver(cert: Path, key: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", RECEIVER_PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ------------------------------------------------------------------------------ processes
def start(module: str, env: dict[str, str], logs: Path, *args: str) -> subprocess.Popen[bytes]:
    fh = (logs / f"{module.rsplit('.', 1)[-1]}.log").open("wb")
    return subprocess.Popen([sys.executable, "-m", module, *args], env=env, stdout=fh, stderr=fh)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logs = OUT / "logs"
    logs.mkdir(exist_ok=True)
    State.wav = (OUT / "synthetic_call.wav").read_bytes()

    base = make_url(SERVER.replace("postgresql+psycopg://", "postgresql://"))
    name = f"int03_e2e_{secrets.token_hex(3)}"
    admin = base.set(drivername="postgresql").render_as_string(hide_password=False)
    url = base.set(database=name).render_as_string(hide_password=False)
    sa_url = url.replace("postgresql://", "postgresql+psycopg://")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    command.upgrade(alembic_config(sa_url), "head")

    work = OUT / "work"
    work.mkdir(exist_ok=True)
    cert, key = make_certificate(work)
    bundle = work / "ca-bundle.pem"
    ca = Path(os.environ.get("SSL_CERT_FILE") or "/root/.ccr/ca-bundle.crt")
    bundle.write_bytes(ca.read_bytes() + b"\n" + cert.read_bytes())
    api_key = "pk_live_" + secrets.token_urlsafe(24)
    env = {
        **os.environ,
        "DATABASE_URL": sa_url,
        "KAFKA_BOOTSTRAP_SERVERS": KAFKA,
        "DATA_DIR": str(work / "data"),
        "SECRET_KEY": __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode(),
        "PUBLIC_BASE_URL": f"http://127.0.0.1:{API_PORT}",
        "PAREEKSHA_API_KEY": api_key,
        "PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS": "1",
        "SSL_CERT_FILE": str(bundle),
        "REQUESTS_CA_BUNDLE": str(bundle),
        "NO_PROXY": os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost",
        "no_proxy": os.environ.get("NO_PROXY", "") + ",127.0.0.1,localhost",
        "COST_DEEPSEEK_PER_1K_INPUT_TOKENS": "0.00132",
        "COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS": "0.00396",
    }
    subprocess.run([sys.executable, "-m", "pareeksha.seed"], env=env, check=True, capture_output=True)

    server = start_receiver(cert, key)
    procs = [
        start("uvicorn", env, logs, "pareeksha.api.main:app", "--port", str(API_PORT)),
        *[start(f"pareeksha.workers.{w}", env, logs) for w in WORKERS],
    ]
    result: dict[str, Any] = {}
    try:
        api = httpx.Client(base_url=f"http://127.0.0.1:{API_PORT}", timeout=30)
        for _ in range(60):
            try:
                if api.get("/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        else:
            raise SystemExit("API did not come up")
        time.sleep(20)  # let the consumer groups join before the first event
        stamp("stack up (api + outbox_relay + auditor + evaluator + integrations)")
        headers = {"Authorization": f"Bearer {api_key}"}

        agents = api.get("/api/v1/agents", headers=headers).json()["items"]
        agent_name = next(a["name"] for a in agents if a["name"] == "EMI Reminder Bot")
        created = api.post(
            "/api/v1/integrations",
            headers=headers,
            json={
                "connector": "webhook",
                "name": "int03-crm-bridge",
                "config": {"url": f"https://127.0.0.1:{RECEIVER_PORT}/note"},
                "secrets": {"signing_secret": SINK_SECRET},
            },
        )
        assert created.status_code == 201, created.text
        integration = created.json()
        result["integration"] = {
            k: integration[k] for k in ("id", "connector", "direction", "inbound_url", "enabled")
        }
        log(f"integration {integration['id']} direction={integration['direction']}")
        test = api.post(f"/api/v1/integrations/{integration['id']}/test", headers=headers)
        result["integration_test"] = test.json()
        log(f"integration test (sink ping to the local HTTPS receiver): {test.json()}")

        body = {
            "external_id": "exotel-CA-int03",
            "recording_url": f"https://127.0.0.1:{RECEIVER_PORT}/recordings/CA-int03.wav",
            "agent_name": agent_name,
            "language": LANGUAGE,
            "metadata": {"phone": "+910000000000", "crm_contact_id": "int03-contact"},
        }
        raw = json.dumps(body).encode()
        path = f"/api/v1/webhooks/inbound/{integration['id']}"
        ctype = {"Content-Type": "application/json"}

        # negative checks first (they must not create anything)
        bad = api.post(path, content=raw, headers={**sign_headers("wrong-wrong-wrong-wrong", raw), **ctype})
        stale = api.post(path, content=raw, headers={**sign_headers(SINK_SECRET, raw, timestamp=int(time.time()) - 3600), **ctype})
        unsafe_raw = json.dumps({**body, "external_id": "x-unsafe", "recording_url": "https://169.254.169.254/x.wav"}).encode()
        # dev switch is ON for this stack (loopback receiver), so use a non-https URL for the unsafe case
        unsafe_raw = json.dumps({**body, "external_id": "x-unsafe", "recording_url": "http://example.com/x.wav"}).encode()
        unsafe = api.post(path, content=unsafe_raw, headers={**sign_headers(SINK_SECRET, unsafe_raw), **ctype})
        result["negative"] = {
            "bad_signature": [bad.status_code, bad.json()["error"]["code"]],
            "stale_timestamp": [stale.status_code, stale.json()["error"]["code"]],
            "non_https_url": [unsafe.status_code, unsafe.json()["error"]["code"]],
        }
        log(f"negative checks: {result['negative']}")
        assert (bad.status_code, stale.status_code, unsafe.status_code) == (401, 408, 422)

        t0 = stamp("POST /webhooks/inbound (signed)")
        resp = api.post(path, content=raw, headers={**sign_headers(SINK_SECRET, raw), **ctype})
        assert resp.status_code == 202, resp.text
        call_id = resp.json()["call_id"]
        stamp("webhook accepted", status=resp.status_code, response=resp.json())
        replay = api.post(path, content=raw, headers={**sign_headers(SINK_SECRET, raw), **ctype})
        result["replay"] = {"status": replay.status_code, "body": replay.json()}
        log(f"replayed delivery: {replay.status_code} {replay.json()}")
        assert replay.json() == {"call_id": call_id, "duplicate": True}

        deadline = t0 + LIMIT_S + 120
        while time.time() < deadline:
            with State.lock:
                good = [n for n in State.notes if n["signature_ok"]]
            if good:
                break
            time.sleep(1)
        else:
            raise SystemExit("no sink delivery arrived")
        t_note = good[0]["received_at"]
        result["seconds_webhook_to_note"] = round(t_note - t0, 1)
        result["within_3_minutes"] = (t_note - t0) <= LIMIT_S
        result["sink_delivery"] = good[0]["body"]
        result["recording_fetches"] = State.recording_fetches
        log(f"webhook -> sink delivery: {result['seconds_webhook_to_note']} s (limit {LIMIT_S} s)")

        # timeline from the database
        with psycopg.connect(url, row_factory=dict_row) as pg:
            def rows(sql: str, *a: Any) -> list[dict[str, Any]]:
                return pg.execute(sql, a).fetchall()  # type: ignore[arg-type]

            call = rows("SELECT * FROM calls WHERE id = %s", call_id)[0]
            turns = rows("SELECT idx, speaker, start_ms, end_ms, text FROM turns WHERE call_id = %s ORDER BY idx", call_id)
            ev = rows("SELECT e.overall_score, e.passed, e.needs_human_review, e.failure_types, e.created_at, rv.version FROM evaluations e JOIN rubric_versions rv ON rv.id = e.rubric_version_id WHERE call_id = %s", call_id)
            outbox = rows("SELECT topic, created_at FROM outbox_events WHERE envelope->'payload'->>'call_id' = %s ORDER BY created_at", call_id)
            deliveries = rows("SELECT direction, status, http_status, attempts, created_at, updated_at FROM integration_deliveries WHERE integration_id = %s ORDER BY created_at", integration["id"])
            refs = rows("SELECT external_id FROM external_refs WHERE call_id = %s", call_id)
            usage = rows("SELECT provider, operation, units, unit_type, est_cost FROM api_usage ORDER BY id")
        result.update(
            call={k: call[k] for k in ("source", "status", "language", "speaker_map", "duration_ms", "recording_original", "metadata")},
            turns=turns, evaluation=ev, outbox_timeline=outbox, deliveries=deliveries, external_refs=refs, db_usage=usage,
        )
        for t in turns:
            log(f"  turn {t['idx']} {t['speaker']:6} {t['start_ms']:>6}-{t['end_ms']:<6} {t['text']}")
        log(f"evaluation: {ev}")
        extra = httpx.get(f"http://127.0.0.1:{API_PORT}/health").json()
        result["health"] = extra
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        server.shutdown()
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    result["timeline"] = events
    (OUT / "e2e_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log("wrote e2e_result.json")
    assert result["within_3_minutes"]


main()
