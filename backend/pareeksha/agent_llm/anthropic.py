"""Anthropic Messages API with native tool use (``tool_use`` / ``tool_result`` blocks)."""

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

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
MAX_TOKENS = 4096


def _wire(messages: Sequence[AgentMessage]) -> tuple[str, list[dict[str, Any]]]:
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    out: list[dict[str, Any]] = []
    prev_tool = False
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            # Consecutive tool results must share one user turn.
            if prev_tool:
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            prev_tool = True
            continue
        prev_tool = False
        if m.role == "assistant":
            blocks: list[dict[str, Any]] = (
                [{"type": "text", "text": m.content}] if m.content else []
            )
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
                for c in m.tool_calls
            ]
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": "user", "content": m.content})
    return system, out


class AnthropicProvider:
    def __init__(
        self, base_url: str | None, api_key: str | None, http: httpx.AsyncClient | None = None
    ):
        self._url = (base_url or DEFAULT_BASE_URL).rstrip("/") + "/messages"
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
        system, wire = _wire(messages)
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "temperature": min(temperature, 1.0),
            "messages": wire,
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        headers = {"anthropic-version": "2023-06-01"}
        if self._key:
            headers["x-api-key"] = self._key
        data, latency = await post_json(
            self._http, self._url, headers, body, timeout_s=timeout_s, api_key=self._key
        )
        try:
            blocks = data["content"]
            text = "".join(b["text"] for b in blocks if b.get("type") == "text")
            calls = tuple(
                ToolCallReq(
                    id=str(b["id"]),
                    name=b["name"],
                    arguments=b.get("input") or {},
                    raw_arguments=json.dumps(b.get("input") or {}),
                )
                for b in blocks
                if b.get("type") == "tool_use"
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise AgentLLMError("provider returned an unexpected response shape") from exc
        usage = data.get("usage") or {}
        return ChatReply(
            text=text,
            tool_calls=calls,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            latency_ms=latency,
        )
