"""Gemini ``generateContent`` REST with function calling; the key goes in a header, not the URL."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx

from pareeksha.agent_llm.base import (
    AgentLLMError,
    AgentMessage,
    ChatReply,
    ToolCallReq,
    ToolSpec,
    post_json,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _response_obj(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except ValueError:
        return {"result": content}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def _tool_call(i: int, part: dict[str, Any]) -> ToolCallReq:
    fc = part["functionCall"]
    args = fc.get("args") or {}
    data: dict[str, Any] = {}
    if part.get("thoughtSignature"):
        data["thought_signature"] = part["thoughtSignature"]
    if fc.get("id"):  # Gemini 3 assigns ids; the functionResponse must echo them
        data["function_call_id"] = fc["id"]
    return ToolCallReq(
        id=str(fc.get("id") or f"call_{i}"),
        name=fc["name"],
        arguments=args,
        raw_arguments=json.dumps(args),
        provider_data=data,
    )


def _wire(messages: Sequence[AgentMessage]) -> tuple[str, list[dict[str, Any]]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    out: list[dict[str, Any]] = []
    prev_tool = False
    model_ids: set[str] = set()  # call ids the model itself assigned (echoed on the response)
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            resp: dict[str, Any] = {"name": m.name, "response": _response_obj(m.content)}
            if m.tool_call_id in model_ids:
                resp["id"] = m.tool_call_id
            part = {"functionResponse": resp}
            # Consecutive tool results share one user turn.
            if prev_tool:
                out[-1]["parts"].append(part)
            else:
                out.append({"role": "user", "parts": [part]})
            prev_tool = True
            continue
        prev_tool = False
        if m.role == "assistant":
            parts: list[dict[str, Any]] = [{"text": m.content}] if m.content else []
            for c in m.tool_calls:
                call: dict[str, Any] = {"name": c.name, "args": c.arguments}
                if c.provider_data.get("function_call_id"):
                    call["id"] = c.provider_data["function_call_id"]
                    model_ids.add(c.id)
                call_part: dict[str, Any] = {"functionCall": call}
                if sig := c.provider_data.get("thought_signature"):
                    call_part["thoughtSignature"] = sig
                parts.append(call_part)
            out.append({"role": "model", "parts": parts})
        else:
            out.append({"role": "user", "parts": [{"text": m.content}]})
    return system, out


class GeminiProvider:
    def __init__(
        self, base_url: str | None, api_key: str | None, http: httpx.AsyncClient | None = None
    ):
        self._base = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._key = api_key
        self._http = http

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply:
        system, contents = _wire(messages)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            # full JSON Schema; `parameters` is an OpenAPI subset that 400s on
                            # keywords like additionalProperties or $schema
                            "parametersJsonSchema": t.parameters,
                        }
                        for t in tools
                    ]
                }
            ]
        headers = {"x-goog-api-key": self._key} if self._key else {}
        data, latency = await post_json(
            self._http,
            f"{self._base}/models/{model}:generateContent",
            headers,
            body,
            timeout_s=timeout_s,
            api_key=self._key,
        )
        try:
            parts = data["candidates"][0]["content"].get("parts") or []
            text = "".join(p["text"] for p in parts if "text" in p)
            calls = tuple(
                _tool_call(i, p) for i, p in enumerate(p for p in parts if "functionCall" in p)
            )
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AgentLLMError("provider returned an unexpected response shape") from exc
        usage = data.get("usageMetadata") or {}
        return ChatReply(
            text=text,
            tool_calls=calls,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            latency_ms=latency,
        )
