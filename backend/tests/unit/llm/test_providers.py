"""DeepSeek and Gemini providers against httpx.MockTransport (no network)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    LLMPermanentError,
    LLMProviderName,
    LLMPurpose,
    LLMRetryableError,
)
from pareeksha.llm.deepseek import DeepSeekProvider
from pareeksha.llm.gemini import GeminiProvider

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def req(**kw: object) -> JSONCompletionRequest:
    base: dict[str, object] = {
        "purpose": LLMPurpose.JUDGE,
        "model": "m-1",
        "messages": [ChatMessage(role="user", content="hello")],
        "json_schema": SCHEMA,
    }
    base.update(kw)
    return JSONCompletionRequest(**base)  # type: ignore[arg-type]


async def no_sleep(_: float) -> None:
    return None


def deepseek(handler: Callable[[httpx.Request], httpx.Response]) -> DeepSeekProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DeepSeekProvider("k", http_client=client, sleep=no_sleep)


def gemini(handler: Callable[[httpx.Request], httpx.Response]) -> GeminiProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GeminiProvider("gk", http_client=client, sleep=no_sleep)


def ds_ok(text: str = '{"x": 1}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "m-1",
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "prompt_cache_hit_tokens": 3},
        },
    )


async def test_deepseek_request_shape_and_usage() -> None:
    seen: dict[str, object] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["auth"] = r.headers["authorization"]
        seen["url"] = str(r.url)
        seen["body"] = json.loads(r.content)
        return ds_ok()

    p = deepseek(handler)
    res = await p.complete_json(req(max_output_tokens=50))
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["auth"] == "Bearer k"
    assert seen["url"] == "https://api.deepseek.com/chat/completions"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 50
    assert body["messages"][0]["role"] == "system"
    assert "json" in body["messages"][0]["content"].lower()
    assert '"x"' in body["messages"][0]["content"]  # schema embedded in the prompt
    assert res.provider is LLMProviderName.DEEPSEEK
    assert (res.usage.input_tokens, res.usage.output_tokens, res.usage.cached_input_tokens) == (
        10,
        4,
        3,
    )
    await p.aclose()


async def test_deepseek_thinking_omits_temperature_and_adds_json_word() -> None:
    bodies: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return ds_ok()

    await deepseek(handler).complete_json(req(thinking=True, json_schema=None))
    assert bodies[0]["thinking"] == {"type": "enabled"}
    assert "temperature" not in bodies[0]
    assert "json" in bodies[0]["messages"][0]["content"].lower()  # type: ignore[index]


async def test_deepseek_retries_then_succeeds() -> None:
    codes = iter([500, 429, None])

    def handler(_: httpx.Request) -> httpx.Response:
        code = next(codes)
        return httpx.Response(code, text="boom", headers={"retry-after": "1"}) if code else ds_ok()

    res = await deepseek(handler).complete_json(req())
    assert res.text == '{"x": 1}'


async def test_deepseek_empty_content_is_retryable_and_gives_up_after_3_retries() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return ds_ok("")

    with pytest.raises(LLMRetryableError, match="empty"):
        await deepseek(handler).complete_json(req())
    assert calls == 4  # first attempt + 3 retries


async def test_deepseek_timeout_is_retryable() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=r)

    with pytest.raises(LLMRetryableError, match="ReadTimeout"):
        await deepseek(handler).complete_json(req())


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_deepseek_4xx_is_permanent_and_not_retried(status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="nope")

    with pytest.raises(LLMPermanentError):
        await deepseek(handler).complete_json(req())
    assert calls == 1


async def test_deepseek_unreadable_and_filtered_responses() -> None:
    with pytest.raises(LLMRetryableError, match="unreadable"):
        await deepseek(lambda _: httpx.Response(200, json={"oops": 1})).complete_json(req())
    filtered = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "x"}, "finish_reason": "content_filter"}]},
    )
    with pytest.raises(LLMPermanentError, match="content"):
        await deepseek(lambda _: filtered).complete_json(req())


def gem_ok(text: str = '{"x": 2}') -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "modelVersion": "gem-1",
            "candidates": [
                {
                    "content": {"parts": [{"text": "hidden", "thought": True}, {"text": text}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 20,
                "candidatesTokenCount": 5,
                "thoughtsTokenCount": 2,
                "cachedContentTokenCount": 8,
            },
        },
    )


async def test_gemini_request_shape_and_usage() -> None:
    seen: dict[str, object] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["url"] = str(r.url)
        seen["key"] = r.headers["x-goog-api-key"]
        seen["body"] = json.loads(r.content)
        return gem_ok()

    messages = [
        ChatMessage(role="system", content="be strict"),
        ChatMessage(role="user", content="q"),
        ChatMessage(role="assistant", content="a"),
        ChatMessage(role="user", content="q2"),
    ]
    res = await gemini(handler).complete_json(req(messages=messages, max_output_tokens=99))
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["url"].endswith("/models/m-1:generateContent")  # type: ignore[attr-defined]
    assert seen["key"] == "gk"
    assert body["systemInstruction"] == {"parts": [{"text": "be strict"}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    cfg = body["generationConfig"]
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseJsonSchema"] == SCHEMA
    assert cfg["maxOutputTokens"] == 99
    assert cfg["thinkingConfig"] == {"thinkingBudget": 0}
    assert res.text == '{"x": 2}'  # thought part excluded
    assert res.usage.input_tokens == 20
    assert res.usage.output_tokens == 7  # candidates + thoughts
    assert res.usage.cached_input_tokens == 8
    assert res.model == "gem-1"


async def test_gemini_system_only_and_thinking_on() -> None:
    bodies: list[dict[str, object]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return gem_ok()

    msgs = [ChatMessage(role="system", content="only system")]
    await gemini(handler).complete_json(req(messages=msgs, thinking=True, json_schema=None))
    assert "systemInstruction" not in bodies[0]
    assert bodies[0]["contents"][0]["parts"][0]["text"] == "only system"  # type: ignore[index]
    cfg = bodies[0]["generationConfig"]
    assert "thinkingConfig" not in cfg  # type: ignore[operator]
    assert "responseJsonSchema" not in cfg  # type: ignore[operator]


async def test_gemini_errors() -> None:
    blocked = httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
    with pytest.raises(LLMPermanentError, match="SAFETY"):
        await gemini(lambda _: blocked).complete_json(req())
    finish = httpx.Response(
        200, json={"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    )
    with pytest.raises(LLMPermanentError, match="finishReason"):
        await gemini(lambda _: finish).complete_json(req())
    with pytest.raises(LLMRetryableError, match="no candidates"):
        await gemini(lambda _: httpx.Response(200, json={})).complete_json(req())
    empty = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": " "}]}}]})
    with pytest.raises(LLMRetryableError, match="empty"):
        await gemini(lambda _: empty).complete_json(req())
    with pytest.raises(LLMRetryableError, match="non-JSON"):
        await gemini(lambda _: httpx.Response(200, text="<html>")).complete_json(req())
    with pytest.raises(LLMPermanentError):
        await gemini(lambda _: httpx.Response(403, text="bad key")).complete_json(req())
    with pytest.raises(LLMRetryableError):
        await gemini(lambda _: httpx.Response(503, text="down")).complete_json(req())

    def boom(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=r)

    with pytest.raises(LLMRetryableError, match="ConnectError"):
        await gemini(boom).complete_json(req())


async def test_owned_client_is_closed_and_injected_client_is_not() -> None:
    p = DeepSeekProvider("k")
    await p.aclose()
    await p.aclose()  # idempotent
    injected = httpx.AsyncClient()
    g = GeminiProvider("k", http_client=injected)
    await g.aclose()
    assert not injected.is_closed
    await injected.aclose()
    await GeminiProvider("k").aclose()
