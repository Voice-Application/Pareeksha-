"""GET / PUT / DELETE /settings/llm and the test endpoint (DB-free: fake session, scripted LLM)."""

from __future__ import annotations

import os

import pytest

from pareeksha.db.models import ProjectLlmSettings
from pareeksha.integrations.crypto import SecretBox
from pareeksha.llm.base import LLMPermanentError
from tests.unit.api_fakes import PROJECT_ID, Harness

KEY = "sk-live-abcdef123456"
OK = {"ok": True}


def test_without_a_row_the_environment_is_shown(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = harness.call("GET", "/settings/llm", "read").json()
    assert body["source"] == "environment"
    assert body["provider"] == "deepseek"  # the default
    assert body["base_url"] == "https://api.deepseek.com"
    assert body["judge_model"] and body["designer_model"] == body["judge_model"]
    assert body["api_key_set"] is False and body["api_key_last4"] is None
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key-9999")
    shown = harness.call("GET", "/settings/llm", "read")
    assert shown.json()["api_key_set"] is True
    assert "env-key-9999" not in shown.text


def test_put_stores_encrypted_key_and_never_returns_it(harness: Harness) -> None:
    put = harness.call(
        "PUT",
        "/settings/llm",
        json={"provider": "deepseek", "judge_model": "my-judge", "api_key": KEY},
    )
    assert put.status_code == 200
    body = put.json()
    assert body["source"] == "project" and body["judge_model"] == "my-judge"
    assert body["api_key_set"] is True and body["api_key_last4"] == "3456"
    row = harness.session.rows[(ProjectLlmSettings, PROJECT_ID)]
    assert KEY not in (row.api_key_encrypted or "")
    assert SecretBox(os.environ["SECRET_KEY"]).decrypt(row.api_key_encrypted) == {"api_key": KEY}
    again = harness.call("GET", "/settings/llm", "read")
    assert again.json() == body
    assert KEY not in put.text + again.text


def test_omitting_the_key_keeps_it_and_an_empty_key_is_refused(harness: Harness) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    kept = harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "caller_model": "c"})
    assert kept.json()["api_key_last4"] == "3456" and kept.json()["caller_model"] == "c"
    empty = harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": ""})
    assert empty.status_code == 400


def test_switching_provider_needs_a_key_unless_the_environment_has_one(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    refused = harness.call(
        "PUT",
        "/settings/llm",
        json={"provider": "gemini", "judge_model": "g", "caller_model": "g"},
    )
    assert refused.status_code == 422 and "API key" in refused.json()["error"]["message"]
    # the stored deepseek key was not reused for gemini
    assert harness.session.rows[(ProjectLlmSettings, PROJECT_ID)].provider == "deepseek"
    monkeypatch.setenv("GEMINI_API_KEY", "env-gem")
    ok = harness.call(
        "PUT",
        "/settings/llm",
        json={"provider": "gemini", "judge_model": "g", "caller_model": "g"},
    )
    assert ok.status_code == 200
    assert ok.json()["provider"] == "gemini" and ok.json()["api_key_last4"] is None
    assert ok.json()["api_key_set"] is True  # via the environment key


def test_gemini_needs_models(harness: Harness) -> None:
    resp = harness.call("PUT", "/settings/llm", json={"provider": "gemini", "api_key": KEY})
    assert resp.status_code == 422 and "judge_model" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",  # not https
        "https://10.0.0.5/v1",  # private
        "https://127.0.0.1:8443/v1",  # loopback
        "https://169.254.169.254/latest",  # link-local metadata
        "https://user:pw@8.8.8.8/v1",  # credentials in the URL
        "https://8.8.8.8/v1?x=",  # a query string would take over the path
        "https://8.8.8.8/v1#frag",
    ],
)
def test_openai_compatible_rejects_unsafe_urls(harness: Harness, url: str) -> None:
    resp = harness.call(
        "PUT",
        "/settings/llm",
        json={
            "provider": "openai_compatible",
            "base_url": url,
            "judge_model": "j",
            "caller_model": "c",
            "api_key": KEY,
        },
    )
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "unsafe_url"
    assert (ProjectLlmSettings, PROJECT_ID) not in harness.session.rows


def test_openai_compatible_requires_url_models_and_key(harness: Harness) -> None:
    base = {"provider": "openai_compatible", "base_url": "https://8.8.8.8/v1", "api_key": KEY}
    assert (
        harness.call("PUT", "/settings/llm", json={**base, "judge_model": "j"}).status_code == 422
    )
    no_url = {k: v for k, v in base.items() if k != "base_url"}
    resp = harness.call(
        "PUT", "/settings/llm", json={**no_url, "judge_model": "j", "caller_model": "c"}
    )
    assert resp.status_code == 422
    no_key = {k: v for k, v in base.items() if k != "api_key"}
    resp = harness.call(
        "PUT", "/settings/llm", json={**no_key, "judge_model": "j", "caller_model": "c"}
    )
    assert resp.status_code == 422 and "API key" in resp.json()["error"]["message"]


def test_openai_compatible_saved_with_a_public_host(harness: Harness) -> None:
    resp = harness.call(
        "PUT",
        "/settings/llm",
        json={
            "provider": "openai_compatible",
            "base_url": "https://8.8.8.8/v1",
            "judge_model": "j",
            "caller_model": "c",
            "api_key": KEY,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["base_url"] == "https://8.8.8.8/v1"
    assert resp.json()["designer_model"] == "j"


def test_dev_switch_allows_a_private_host(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS", "1")
    resp = harness.call(
        "PUT",
        "/settings/llm",
        json={
            "provider": "openai_compatible",
            "base_url": "https://127.0.0.1:8443/v1",
            "judge_model": "j",
            "caller_model": "c",
            "api_key": KEY,
        },
    )
    assert resp.status_code == 200


def test_delete_reverts_to_the_environment(harness: Harness) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    assert harness.call("DELETE", "/settings/llm").status_code == 204
    shown = harness.call("GET", "/settings/llm", "read").json()
    assert shown["source"] == "environment" and shown["api_key_set"] is False
    assert harness.call("DELETE", "/settings/llm").status_code == 204  # idempotent


def test_test_endpoint_succeeds(harness: Harness) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    harness.provider.outputs.append('{"ok": true}')
    body = harness.call("POST", "/settings/llm/test").json()
    assert body["ok"] is True and body["provider"] == "deepseek"
    assert body["latency_ms"] == 7 and body["error"] is None and body["model"]


def test_test_endpoint_reports_provider_errors_without_the_key(harness: Harness) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    harness.provider.outputs.append(LLMPermanentError(f"deepseek HTTP 401: invalid key {KEY}"))
    resp = harness.call("POST", "/settings/llm/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["latency_ms"] is None
    assert KEY not in resp.text and body["error"] == "The LLM provider returned HTTP 401"


def test_test_endpoint_unexpected_errors_are_not_500s(harness: Harness) -> None:
    harness.call("PUT", "/settings/llm", json={"provider": "deepseek", "api_key": KEY})
    harness.provider.outputs.append(RuntimeError(f"boom {KEY}"))
    resp = harness.call("POST", "/settings/llm/test")
    assert resp.status_code == 200 and resp.json()["ok"] is False and KEY not in resp.text


def test_test_endpoint_without_any_key(harness: Harness) -> None:
    body = harness.call("POST", "/settings/llm/test").json()
    assert body["ok"] is False and body["error"]


def test_scopes(harness: Harness) -> None:
    put = {"provider": "deepseek", "api_key": KEY}
    assert harness.call("GET", "/settings/llm", "read").status_code == 200
    for scope in ("read", "runs:write", "audits:write"):
        assert harness.call("PUT", "/settings/llm", scope, json=put).status_code == 403
        assert harness.call("DELETE", "/settings/llm", scope).status_code == 403
        assert harness.call("POST", "/settings/llm/test", scope).status_code == 403
    assert harness.call("PUT", "/settings/llm", "admin", json=put).status_code == 200


@pytest.mark.parametrize(("key", "last4"), [("abcd", None), ("short-key-1", None), (KEY, "3456")])
def test_last4_is_shown_only_for_long_keys(harness: Harness, key: str, last4: str | None) -> None:
    put = {"provider": "deepseek", "api_key": key}
    body = harness.call("PUT", "/settings/llm", json=put).json()
    assert body["api_key_last4"] == last4 and body["api_key_set"] is True
    assert harness.call("GET", "/settings/llm", "read").json()["api_key_last4"] == last4
