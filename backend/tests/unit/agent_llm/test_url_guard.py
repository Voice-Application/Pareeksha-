import pytest

from pareeksha.agent_llm.url_guard import check_base_url, is_operator_ollama


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


def test_https_to_loopback_is_non_public() -> None:
    with pytest.raises(ValueError, match="non-public address"):
        check_base_url("https://127.0.0.1:8080", allow_private=False)


@pytest.mark.parametrize("userinfo", ["user:pass", "user", "", ":pass", ":"])
def test_operator_url_rejects_userinfo(monkeypatch: pytest.MonkeyPatch, userinfo: str) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://127.0.0.1/v1")
    url = f"https://{userinfo}@127.0.0.1/v1"
    assert not is_operator_ollama(url)
    with pytest.raises(ValueError, match="credentials"):
        check_base_url(url, allow_private=True)
    monkeypatch.setenv("OLLAMA_BASE_URL", url)
    assert not is_operator_ollama("https://127.0.0.1/v1")
    assert not is_operator_ollama(url)


@pytest.mark.parametrize(("scheme", "port"), [("http", 80), ("https", 443)])
@pytest.mark.parametrize("explicit_config", [True, False])
def test_operator_default_ports(
    monkeypatch: pytest.MonkeyPatch, scheme: str, port: int, explicit_config: bool
) -> None:
    implicit = f"{scheme}://ollama/v1"
    explicit = f"{scheme}://ollama:{port}/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", explicit if explicit_config else implicit)
    url = implicit if explicit_config else explicit
    assert is_operator_ollama(url)
    assert is_operator_ollama(url + "/embeddings")
    check_base_url(url, allow_private=False)
    for other in (
        f"{scheme}://ollama:{port + 1}/v1",
        f"{scheme}://other/v1",
        url.replace(scheme, "https" if scheme == "http" else "http", 1),
        url + "x",
        url + "/../api",
        url + "?x=1",
        url + "#fragment",
    ):
        assert not is_operator_ollama(other)
