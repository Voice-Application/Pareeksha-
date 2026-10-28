"""Async SQLAlchemy engine and session helpers (psycopg 3 driver).

``DATABASE_URL`` (``postgresql+psycopg://...``) is read lazily, so importing the API never needs a
database. Routes get a transactional session with ``Depends(get_session)``: it commits when the
request succeeds and rolls back when it raises.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def database_url() -> str:
    """``DATABASE_URL`` normalised to the psycopg 3 SQLAlchemy dialect."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(url or database_url(), pool_pre_ping=True, **kwargs)


@lru_cache(maxsize=1)
def _default_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(make_engine(), expire_on_commit=False)


def _new_default_session() -> AsyncSession:
    return _default_sessionmaker()()


#: A callable returning a new ``AsyncSession`` (an ``async_sessionmaker`` or a test double).
SessionFactory = Callable[[], AsyncSession]


def get_session_factory() -> SessionFactory:
    """FastAPI dependency; no connection is made until a session is used. Override in tests."""
    return _new_default_session


async def get_session(
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
