from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.fake_platform import API_KEY, State, serve


@pytest.fixture
def state() -> State:
    return State()


@pytest.fixture
def base_url(state: State) -> Iterator[str]:
    with serve(state) as url:
        yield url


@pytest.fixture
def logged_in(base_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the CLI profile at a temp file holding the fake server's credentials."""
    from pareeksha_sdk.config import save_profile

    profile = tmp_path / "config.toml"
    save_profile(base_url, API_KEY, profile)
    monkeypatch.setenv("PAREEKSHA_CONFIG", str(profile))
    monkeypatch.delenv("PAREEKSHA_URL", raising=False)
    monkeypatch.delenv("PAREEKSHA_KEY", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return base_url
