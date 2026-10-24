"""DATABASE_URL handling of the session layer (no database needed)."""

from __future__ import annotations

import pytest

from pareeksha.db.session import database_url, get_session_factory, make_engine


def test_url_is_normalised_to_psycopg3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/d")
    assert database_url() == "postgresql+psycopg://u:p@h/d"
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/d")
    assert database_url() == "postgresql+psycopg://u:p@h/d"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/d")
    assert database_url() == "postgresql+psycopg://u:p@h/d"


def test_missing_url_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_factory_dependency_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert callable(get_session_factory())  # no engine, no env needed until a session is made


def test_make_engine_does_not_connect() -> None:
    engine = make_engine("postgresql+psycopg://u:p@127.0.0.1:1/d")
    assert engine.url.host == "127.0.0.1"
