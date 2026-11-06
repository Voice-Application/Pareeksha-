import json
from typing import Any

import httpx
import pytest

from pareeksha.agent_llm import AgentLLMError, AgentMessage, ToolCallReq, ToolSpec
from pareeksha.agent_llm.factory import build_chat_provider

KEY = "sk-test-secret"
TOOLS = [
    ToolSpec("get_order", "look up", {"type": "object", "properties": {"id": {"type": "string"}}})
]
MSGS = [AgentMessage("system", "be nice"), AgentMessage("user", "hi")]
TOOL_TURN = [
    *MSGS,
    AgentMessage("assistant", "", (ToolCallReq("c1", "get_order", {"id": "7"}, '{"id": "7"}'),)),
    AgentMessage("tool", '{"ok": true}', tool_call_id="c1", name="get_order"),
]

OPENAI_TEXT = {
    "choices": [{"message": {"content": "hello"}}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 2},
}
OPENAI_CALL = {
    "choices": [
        {
            "message": {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "get_order", "arguments": '{"id": "7"}'},
                    }
                ],
            }
        }
    ]
}
ANTHROPIC_TEXT = {
    "content": [{"type": "text", "text": "hello"}],
    "usage": {"input_tokens": 3, "output_tokens": 2},
}
ANTHROPIC_CALL = {
    "content": [{"type": "tool_use", "id": "c1", "name": "get_order", "input": {"id": "7"}}]
}
GEMINI_TEXT = {
    "candidates": [{"content": {"parts": [{"text": "hello"}]}}],
    "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2},
}
GEMINI_CALL = {
    "candidates": [
        {"content": {"parts": [{"functionCall": {"name": "get_order", "args": {"id": "7"}}}]}}
    ]
}

FAMILIES: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {
    "openai": (OPENAI_TEXT, OPENAI_CALL),
    "anthropic": (ANTHROPIC_TEXT, ANTHROPIC_CALL),
    "gemini": (GEMINI_TEXT, GEMINI_CALL),
}


def _provider(name: str, handler: Any) -> Any:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return build_chat_provider(name, api_key=KEY, http=http)  # type: ignore[arg-type]


def _json_handler(payload: dict[str, Any], seen: list[httpx.Request]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=payload)

    return handler


async def _chat(p: Any, msgs: list[AgentMessage] = MSGS, tools: list[ToolSpec] = TOOLS) -> Any:
    return await p.chat(msgs, tools, model="m", temperature=0.1)


@pytest.mark.parametrize("family", FAMILIES)
async def test_parses_text_reply(family: str) -> None:
    p = _provider(family, _json_handler(FAMILIES[family][0], []))
    r = await _chat(p)
    assert (r.text, r.tool_calls, r.input_tokens, r.output_tokens) == ("hello", (), 3, 2)


@pytest.mark.parametrize("family", FAMILIES)
async def test_parses_tool_call(family: str) -> None:
    p = _provider(family, _json_handler(FAMILIES[family][1], []))
    r = await _chat(p)
    (c,) = r.tool_calls
    assert (c.name, c.arguments) == ("get_order", {"id": "7"})
    assert c.id


async def test_openai_sends_tools_and_system() -> None:
    seen: list[httpx.Request] = []
    await _chat(_provider("openai", _json_handler(OPENAI_TEXT, seen)), TOOL_TURN)
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert body["messages"][0] == {"role": "system", "content": "be nice"}
    assert body["tools"][0]["function"]["name"] == "get_order"
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == '{"id": "7"}'
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'}


async def test_anthropic_sends_tools_and_system() -> None:
    seen: list[httpx.Request] = []
    await _chat(_provider("anthropic", _json_handler(ANTHROPIC_TEXT, seen)), TOOL_TURN)
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == KEY
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert body["system"] == "be nice"
    assert body["tools"][0]["input_schema"]["type"] == "object"
    assert body["messages"][1]["content"][0]["type"] == "tool_use"
    assert body["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "c1",
        "content": '{"ok": true}',
    }


async def test_gemini_sends_tools_and_system() -> None:
    seen: list[httpx.Request] = []
    await _chat(_provider("gemini", _json_handler(GEMINI_TEXT, seen)), TOOL_TURN)
    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent"
    )
    assert req.headers["x-goog-api-key"] == KEY
    assert KEY not in str(req.url)
    assert body["systemInstruction"]["parts"][0]["text"] == "be nice"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "get_order"
    assert body["contents"][1]["parts"][0]["functionCall"]["name"] == "get_order"
    assert body["contents"][2]["parts"][0]["functionResponse"] == {
        "name": "get_order",
        "response": {"ok": True},
    }


async def test_invalid_tool_arguments_kept_raw() -> None:
    payload = json.loads(json.dumps(OPENAI_CALL))
    payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{bad"
    r = await _chat(_provider("openai", _json_handler(payload, [])))
    assert r.tool_calls[0].arguments == {"_raw": "{bad"}
    assert r.tool_calls[0].raw_arguments == "{bad"


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(("status", "retryable"), [(401, False), (429, True), (503, True)])
async def test_http_errors_raise_agent_llm_error(family: str, status: int, retryable: bool) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": f"bad key {KEY}"}})

    with pytest.raises(AgentLLMError) as ei:
        await _chat(_provider(family, handler))
    assert ei.value.status == status
    assert ei.value.retryable is retryable
    assert KEY not in str(ei.value)


async def test_timeout_is_retryable_and_key_free() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(AgentLLMError) as ei:
        await _chat(_provider("openai", handler))
    assert ei.value.retryable
    assert KEY not in str(ei.value)


def test_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ValueError):
        build_chat_provider("openai_compatible", api_key=None)


async def test_defaults_and_custom_base_url() -> None:
    seen: list[httpx.Request] = []
    h = _json_handler(OPENAI_TEXT, seen)
    http = httpx.AsyncClient(transport=httpx.MockTransport(h))
    for name, url in [
        ("deepseek", "https://api.deepseek.com/chat/completions"),
        ("groq", "https://api.groq.com/openai/v1/chat/completions"),
        ("mistral", "https://api.mistral.ai/v1/chat/completions"),
        ("ollama", "http://localhost:11434/v1/chat/completions"),
    ]:
        await _chat(build_chat_provider(name, api_key=None, http=http))  # type: ignore[arg-type]
        assert str(seen[-1].url) == url
    p = build_chat_provider("openai_compatible", api_key=None, base_url="http://x/v1/", http=http)
    await _chat(p)
    assert str(seen[-1].url) == "http://x/v1/chat/completions"
