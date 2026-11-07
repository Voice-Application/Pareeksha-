from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from pareeksha.adapters.base import AgentTarget
from pareeksha.schemas.prompts import PromptVersionCreate, content_hash


def _body(**over: Any) -> PromptVersionCreate:
    data: dict[str, Any] = {"system_prompt": "be nice", "provider": "openai", "model": "gpt-x"}
    return PromptVersionCreate(**{**data, **over})


def _tool(name: str = "refund", parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """A minimal tool dict; ``parameters`` defaults to an object schema."""
    return {"name": name, "parameters": parameters or {"type": "object"}}


def test_tool_names_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        _body(tools=[_tool(), _tool()])


def test_tool_parameters_must_be_object_schema() -> None:
    with pytest.raises(ValidationError):
        _body(tools=[_tool(parameters={"type": "string"})])


def test_content_hash_ignores_note() -> None:
    """The content hash ignores the note but changes with the settings."""
    assert content_hash(_body(note="a")) == content_hash(_body(note="b"))
    assert content_hash(_body()) != content_hash(_body(temperature=0.9))


def test_prompt_is_valid_adapter() -> None:
    """``prompt`` is an accepted ``AgentTarget`` adapter, with an empty endpoint."""
    target = AgentTarget(agent_id=uuid.uuid4(), adapter="prompt", endpoint_url="")
    assert target.adapter == "prompt"
