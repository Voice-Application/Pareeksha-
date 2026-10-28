import pytest

from pareeksha.workers import integrations


def test_worker_fails_fast_without_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(SystemExit, match="SECRET_KEY is not set"):
        integrations._secret_box()
