"""OpenAI chat-completions wire format (OpenAI, DeepSeek, Groq, Mistral, Ollama, compatible)."""

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
    parse_args,
    post_json,
)


def _text(content: Any) -> str:
    """Message content as text. Some servers (Mistral reasoning models) send a list of chunks
    (``thinking`` + ``text``) instead of a string; only the ``text`` chunks are the reply."""
    if content is None or isinstance(content, str):
        return content or ""
    if isinstance(content, list):
        return "".join(c["text"] for c in content if c.get("type") == "text")
    raise TypeError("message content is not a string or a list of chunks")


def _wire(m: AgentMessage) -> dict[str, Any]:
    """One message in Chat Completions format; assistant tool calls keep their raw argument text."""
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    out: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.tool_calls:
        out["content"] = m.content or None
        out["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.name,
                    "arguments": c.raw_arguments or json.dumps(c.arguments),
                },
            }
            for c in m.tool_calls
        ]
    return out


class OpenAICompatProvider:
    def __init__(self, base_url: str, api_key: str | None, http: httpx.AsyncClient | None = None):
        self._url = base_url.rstrip("/") + "/chat/completions"
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
        """Send one Chat Completions request and parse the reply's text, tool calls and token usage.

        A 400 that names ``temperature`` (reasoning models) is retried once without it; an
        unexpected response shape raises ``AgentLLMError``.
        """
        body: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [_wire(m) for m in messages],
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}

        async def send() -> tuple[dict[str, Any], int]:
            return await post_json(
                self._http, self._url, headers, body, timeout_s=timeout_s, api_key=self._key
            )

        try:
            data, latency = await send()
        except AgentLLMError as exc:
            # Reasoning models (o-series, gpt-5) accept only the default temperature: retry without.
            if exc.status != 400 or "temperature" not in exc.provider_message.lower():
                raise
            del body["temperature"]
            data, latency = await send()
        try:
            msg = data["choices"][0]["message"]
            calls = tuple(
                ToolCallReq(
                    id=str(c.get("id") or f"call_{i}"),
                    name=c["function"]["name"],
                    arguments=parse_args(c["function"].get("arguments") or ""),
                    raw_arguments=c["function"].get("arguments") or "",
                )
                for i, c in enumerate(msg.get("tool_calls") or [])
            )
            text = _text(msg.get("content"))
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise AgentLLMError("provider returned an unexpected response shape") from exc
        usage = data.get("usage") or {}
        return ChatReply(
            text=text,
            tool_calls=calls,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency,
        )
