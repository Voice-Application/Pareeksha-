"""Liveness check of the two hard dependencies, Postgres and Kafka (TRD section 15).

Carried over unchanged in behaviour from the INFRA-01 placeholder: Docker Compose's api
healthcheck calls ``GET /health`` (root, hidden from OpenAPI) and expects 200 only when both are
reachable. The documented route is ``GET /api/v1/health``. The drivers are imported lazily so the
module (and the API's OpenAPI document) loads without them.
"""

from __future__ import annotations

import asyncio
import os

from pareeksha.schemas.system import HealthOut


def _db_ok() -> bool:
    import psycopg

    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, connect_timeout=3) as conn:
        return conn.execute("select 1").fetchone() == (1,)


async def _kafka_ok() -> bool:
    from aiokafka import AIOKafkaClient

    client = AIOKafkaClient(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"])
    await client.bootstrap()
    try:
        await client.force_metadata_update()
        return len(client.cluster.brokers()) > 0
    finally:
        await client.close()


async def check_health() -> HealthOut:
    """Each field is ``"ok"`` or ``"down: <ExceptionName>"``; never raises."""
    try:
        db = "ok" if await asyncio.to_thread(_db_ok) else "down"
    except Exception as exc:  # report, do not crash
        db = f"down: {type(exc).__name__}"
    try:
        kafka = "ok" if await _kafka_ok() else "down"
    except Exception as exc:
        kafka = f"down: {type(exc).__name__}"
    return HealthOut(db=db, kafka=kafka)
