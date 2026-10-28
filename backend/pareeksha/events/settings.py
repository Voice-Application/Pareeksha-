"""Connection settings shared by every Kafka/Postgres worker (read from the environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass


def libpq_url(url: str) -> str:
    """``postgresql+psycopg://...`` (SQLAlchemy style, as in .env) -> ``postgresql://...``."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(frozen=True, slots=True)
class EventSettings:
    """Where Kafka and Postgres are (``KAFKA_BOOTSTRAP_SERVERS``, ``DATABASE_URL``)."""

    bootstrap_servers: str
    database_url: str

    @classmethod
    def from_env(cls) -> EventSettings:
        return cls(
            bootstrap_servers=os.environ["KAFKA_BOOTSTRAP_SERVERS"],
            database_url=libpq_url(os.environ["DATABASE_URL"]),
        )


def kafka_bootstrap() -> str:
    """``KAFKA_BOOTSTRAP_SERVERS`` for API routes that read Kafka (FastAPI dependency)."""
    return os.environ["KAFKA_BOOTSTRAP_SERVERS"]
