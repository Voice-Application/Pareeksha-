"""INT-01b acceptance demo: real Kafka, real Postgres, real HTTPS receiver, real worker process.

    cd backend && python -I -c "import runpy,sys; sys.path[:0]=['.']; runpy.run_path('../proof/INT-01b/demo.py', run_name='__main__')"

(or ``PYTHONPATH=. python ../proof/INT-01b/demo.py``). Needs KAFKA (INFRA_TEST_KAFKA_BOOTSTRAP,
default localhost:9094) and a Postgres server (TEST_DATABASE_URL, same default as the test-suite).
Every number printed below is read back from Postgres or from the receiver, nothing is asserted
from memory.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import threading
import uuid
from pathlib import Path

import psycopg
from alembic import command
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from pareeksha.integrations.crypto import SecretBox
from tests.conftest import alembic_config
from tests.integration.support import prime_group, wait_for
from tests.integration.test_integrations_worker import (
    GROUP,
    SIGNING_SECRET,
    EVAL_TOPIC,
    Worker,
    delivery_rows,
    evaluation_event,
    lag_is_zero,
    publish,
    seed_evaluation,
)
from tests.integration.webhook_receiver import ReceiverServer


def banner(text: str) -> None:
    print(f"\n=== {text}", flush=True)


def table(url: str, integration: str) -> None:
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        cur = conn.execute(
            "SELECT left(event_id::text, 8) AS event, direction, status, attempts, http_status, "
            "request_summary->>'event_type' AS event_type "
            "FROM integration_deliveries WHERE integration_id = %s ORDER BY created_at",
            (uuid.UUID(integration),),
        )
        rows = cur.fetchall()
        print("  SELECT event, direction, status, attempts, http_status, event_type FROM integration_deliveries ...")
        for r in rows:
            print("   ", r)
        print(f"  -> {len(rows)} row(s)")


def receiver_summary(server: ReceiverServer) -> None:
    ids = server.state.requests
    print(
        f"  receiver: {len(ids)} POST(s), unique event ids = {len(server.state.unique_event_ids)}, "
        f"signatures valid = {all(r.signature_ok for r in ids)}"
    )


async def main() -> None:
    key = Fernet.generate_key().decode()
    os.environ["SECRET_KEY"] = key
    os.environ["PUBLIC_BASE_URL"] = "https://pareeksha.example.com"
    base = make_url(
        os.environ.get("TEST_DATABASE_URL")
        or "postgresql+psycopg://pareeksha:pareeksha@localhost:5432/pareeksha"
    )
    name = f"pareeksha_demo_{secrets.token_hex(4)}"
    admin = base.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = base.set(database=name).render_as_string(hide_password=False)
    command.upgrade(alembic_config(url), "head")
    print(f"database {name} migrated with Alembic")

    cert_dir = Path(tempfile.mkdtemp())
    server = ReceiverServer(cert_dir, SIGNING_SECRET).start()
    print(f"receiver listening on {server.url} (self-signed TLS, verifies HMAC, dedupes on event id)")
    os.environ["SSL_CERT_FILE"] = str(server.cert)

    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as c:
        project = c.execute("INSERT INTO projects (name) VALUES ('demo') RETURNING id").fetchone()
        assert project is not None
        token = SecretBox(key).encrypt({"signing_secret": SIGNING_SECRET}).encode()
        row = c.execute(
            "INSERT INTO integrations (project_id, connector, name, direction, config, "
            "secrets_encrypted, event_filter) VALUES (%s, 'webhook', 'demo receiver', 'sink', %s, %s, %s) "
            "RETURNING id",
            (
                project[0],
                psycopg.types.json.Jsonb({"url": server.url}),
                token,
                psycopg.types.json.Jsonb({"events": ["evaluation.completed"]}),
            ),
        ).fetchone()
        assert row is not None
        integration = str(row[0])
    print(f"integration {integration} (connector webhook, secret stored Fernet-encrypted)")

    await prime_group(GROUP, [EVAL_TOPIC])

    # ---------------------------------------------------------------------------------------
    banner("A. one evaluation.completed event -> one signed POST + one delivery-log row")
    ids = seed_evaluation(url, project[0])
    first = evaluation_event(ids)
    worker = await Worker.spawn(url, server)
    await publish(first)
    await wait_for(
        lambda: asyncio.sleep(0, result=bool(delivery_rows(url, integration))), timeout=60, what="row"
    )
    await wait_for(lag_is_zero, what="offset committed")
    table(url, integration)
    receiver_summary(server)
    body = json.loads(server.state.requests[0].body)
    print(f"  payload: type={body['type']} score={body['data']['overall_score']} "
          f"passed={body['data']['passed']} link={body['data']['link']}")

    banner("B. the SAME event delivered to Kafka three more times -> still one delivery")
    await publish(first, first, first)
    await wait_for(lag_is_zero, what="duplicates consumed")
    await asyncio.sleep(1.5)
    table(url, integration)
    receiver_summary(server)
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        print("  processed_events rows for this event:", conn.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
            (GROUP, first.event_id),
        ).fetchone())
    await worker.stop()

    # ---------------------------------------------------------------------------------------
    banner("C. kill -9 the worker while its HTTP request is in flight, restart it")
    ids2 = seed_evaluation(url, project[0], passed=False, score=31.0)
    second = evaluation_event(ids2, score=31.0)
    before = len(server.state.requests)
    server.state.hold = threading.Event()
    server.state.arrived.clear()
    victim = await Worker.spawn(url, server)
    await publish(second)
    await wait_for(
        lambda: asyncio.sleep(0, result=server.state.arrived.is_set()), timeout=60, what="request"
    )
    print("  receiver has the request, holding the response; row before the crash:")
    table(url, integration)
    await victim.kill()
    print("  worker killed with SIGKILL; Kafka offset committed? ->", await lag_is_zero())
    server.state.hold.set()
    survivor = await Worker.spawn(url, server)

    async def done() -> bool:
        rows = [r for r in delivery_rows(url, integration) if r["event_id"] == second.event_id]
        return bool(rows) and rows[0]["status"] == "succeeded"

    await wait_for(done, timeout=60, what="redelivery after crash")
    await wait_for(lag_is_zero, what="offset committed")
    await survivor.stop()
    print("  after restart:")
    table(url, integration)
    new = server.state.requests[before:]
    print(f"  receiver saw {len(new)} POST(s) for the crashed event, "
          f"{len({r.event_id for r in new})} unique event id (receiver dedupes on X-Pareeksha-Event-Id)")
    receiver_summary(server)

    server.stop()
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


if __name__ == "__main__":
    asyncio.run(main())
