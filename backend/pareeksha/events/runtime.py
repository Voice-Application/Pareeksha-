"""Small helpers shared by the Kafka workers: DB connection, headers, logging, signals."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import signal
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

import psycopg

from pareeksha.events.settings import EventSettings

#: Extra header (not in the frozen topics.py list): the consumer group that produced a retry /
#: DLQ copy. When a retried message returns to its topic only that group processes it; other
#: groups subscribed to the same topic skip it (they already handled the original).
HEADER_CONSUMER_GROUP = "x-consumer-group"

_LOG_FIELDS = ("group", "event_id", "correlation_id", "topic", "partition", "offset", "attempt")


class JsonFormatter(logging.Formatter):
    """One JSON object per line (TRD section 15: event_id, correlation_id, consumer group)."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for name in _LOG_FIELDS:
            if hasattr(record, name):
                out[name] = getattr(record, name)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("aiokafka").setLevel(logging.WARNING)


def encode_headers(headers: Mapping[str, str]) -> list[tuple[str, bytes]]:
    return [(k, v.encode("utf-8")) for k, v in headers.items()]


def decode_headers(headers: Iterable[tuple[str, bytes]] | None) -> dict[str, str]:
    return {k: v.decode("utf-8", errors="replace") for k, v in (headers or ())}


def utc_iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class Database:
    """One autocommit psycopg connection that reconnects after it breaks.

    A consumer handles one message at a time, so a pool would buy nothing. The transaction is
    opened explicitly by the caller with ``async with conn.transaction()``.
    """

    def __init__(self, settings: EventSettings) -> None:
        self._dsn = settings.database_url
        self._conn: psycopg.AsyncConnection[Any] | None = None

    async def connection(self) -> psycopg.AsyncConnection[Any]:
        if self._conn is None or self._conn.closed or self._conn.broken:
            await self.close()
            self._conn = await psycopg.AsyncConnection.connect(
                self._dsn, autocommit=True, connect_timeout=5
            )
        return self._conn

    async def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            with contextlib.suppress(psycopg.Error):
                await self._conn.close()
        self._conn = None


def install_stop_signals(stop: asyncio.Event) -> None:
    """SIGTERM / SIGINT set ``stop``: workers finish the current message, commit, and leave."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
