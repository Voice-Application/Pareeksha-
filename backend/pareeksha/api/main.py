# STUB(TL-01): placeholder API exposing only GET /health (DB + Kafka metadata check, per TRD).
# BE-API replaces this module in API-01/API-02 and must keep /health semantics.
import asyncio
import os

import psycopg
from aiokafka import AIOKafkaClient
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="Pareeksha API (INFRA-01 placeholder)")


def _db_ok() -> bool:
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, connect_timeout=3) as conn:
        return conn.execute("select 1").fetchone() == (1,)


async def _kafka_ok() -> bool:
    client = AIOKafkaClient(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"])
    await client.bootstrap()
    try:
        await client.force_metadata_update()
        return len(client.cluster.brokers()) > 0
    finally:
        await client.close()


@app.get("/health")
async def health():
    out = {}
    try:
        out["db"] = "ok" if await asyncio.to_thread(_db_ok) else "down"
    except Exception as e:  # report, do not crash
        out["db"] = f"down: {type(e).__name__}"
    try:
        out["kafka"] = "ok" if await _kafka_ok() else "down"
    except Exception as e:
        out["kafka"] = f"down: {type(e).__name__}"
    return JSONResponse(out, status_code=200 if set(out.values()) == {"ok"} else 503)
