import pytest

from pareeksha.agent_llm.url_guard import check_base_url


def test_public_https_passes() -> None:
    check_base_url("https://8.8.8.8/v1", allow_private=False)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/",
        "http://127.0.0.1:8080",
        "http://10.0.0.5",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com",
    ],
)
def test_blocked(url: str) -> None:
    with pytest.raises(ValueError):
        check_base_url(url, allow_private=False)


def test_loopback_allowed_when_private_allowed() -> None:
    check_base_url("http://127.0.0.1:11434/v1", allow_private=True)


def test_scheme_still_checked_when_private_allowed() -> None:
    with pytest.raises(ValueError):
        check_base_url("file:///etc/passwd", allow_private=True)
