"""Prompt versions: client methods and `pareeksha prompt ...` against the fake platform."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pareeksha_sdk import Pareeksha
from pareeksha_sdk.cli import app
from tests.fake_platform import API_KEY, State

runner = CliRunner()
AGENT = {"name": "Bot", "adapter": "prompt"}


def test_client_create_list_activate(base_url: str, state: State) -> None:
    """The client creates, dedupes, lists and activates prompt versions."""
    with Pareeksha(base_url, API_KEY) as pk:
        agent_id = str(pk.agents.create(AGENT).id)
        first = pk.create_prompt_version(
            agent_id, system_prompt="be kind", provider="openai", model="m", temperature=0.2
        )
        assert first["version"] == 1 and first["unchanged"] is False
        assert state.prompt_bodies[0] == {
            "system_prompt": "be kind",
            "provider": "openai",
            "model": "m",
            "temperature": 0.2,
        }
        again = pk.create_prompt_version(
            agent_id, system_prompt="be kind", provider="openai", model="m"
        )
        assert again["version"] == 1 and again["unchanged"] is True
        pk.create_prompt_version(agent_id, system_prompt="v2", provider="openai", model="m")
        assert [v["version"] for v in pk.list_prompt_versions(agent_id)] == [2, 1]
        assert pk.activate_prompt_version(agent_id, 1)["version"] == 1
        assert state.prompt_activations == [(agent_id, 1)]


def test_client_config_only_change_creates_version(base_url: str, state: State) -> None:
    """A model change alone makes a new version; a note change alone does not."""
    with Pareeksha(base_url, API_KEY) as pk:
        agent_id = str(pk.agents.create(AGENT).id)
        pk.create_prompt_version(agent_id, system_prompt="same", provider="openai", model="m1")
        changed = pk.create_prompt_version(
            agent_id, system_prompt="same", provider="openai", model="m2"
        )
        assert changed["version"] == 2 and changed["unchanged"] is False
        again = pk.create_prompt_version(
            agent_id, system_prompt="same", provider="openai", model="m2", note="only a note"
        )
        assert again["version"] == 2 and again["unchanged"] is True


@pytest.fixture
def push_args(logged_in: str, tmp_path: Path) -> list[str]:
    with Pareeksha(logged_in, API_KEY) as pk:
        pk.agents.create(AGENT)
    prompt = tmp_path / "p.md"
    prompt.write_text("hello", encoding="utf-8")
    return [
        "prompt",
        "push",
        "--agent",
        "Bot",
        "--file",
        str(prompt),
        "--provider",
        "openai",
        "--model",
        "m",
    ]


def test_cli_push_and_unchanged(push_args: list[str]) -> None:
    """``prompt push`` creates v1 then reports it unchanged; ``versions`` and ``activate`` work."""
    result = runner.invoke(app, push_args)
    assert result.exit_code == 0 and "created v1" in result.output
    result = runner.invoke(app, push_args)
    assert result.exit_code == 0 and "unchanged (still v1)" in result.output
    result = runner.invoke(app, ["prompt", "versions", "--agent", "Bot"])
    assert "v1  openai/m" in result.output
    assert runner.invoke(app, ["prompt", "activate", "--agent", "Bot", "1"]).exit_code == 0


def test_cli_push_tools_file(push_args: list[str], tmp_path: Path, state: State) -> None:
    """``--tools`` sends the file's JSON; invalid JSON exits 2 without sending anything."""
    tools = tmp_path / "t.json"
    tools.write_text(json.dumps([{"name": "x"}]), encoding="utf-8")
    assert runner.invoke(app, [*push_args, "--tools", str(tools)]).exit_code == 0
    assert state.prompt_bodies[0]["tools"] == [{"name": "x"}]
    tools.write_text("{not json", encoding="utf-8")
    result = runner.invoke(app, [*push_args, "--tools", str(tools)])
    assert result.exit_code == 2 and "invalid JSON" in result.output
    assert len(state.prompt_bodies) == 1


def test_set_key_never_echoes(
    push_args: list[str], state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``prompt set-key`` stores the key from the environment or a prompt and never prints it."""
    monkeypatch.setenv("PAREEKSHA_AGENT_API_KEY", "sk-secret-1")
    result = runner.invoke(app, ["prompt", "set-key", "--agent", "Bot"])
    assert result.exit_code == 0 and "sk-secret-1" not in result.output
    assert next(iter(state.agents.values()))["adapter_secrets"] == {"api_key": "sk-secret-1"}
    monkeypatch.delenv("PAREEKSHA_AGENT_API_KEY")
    result = runner.invoke(app, ["prompt", "set-key", "--agent", "Bot"], input="sk-secret-2\n")
    assert result.exit_code == 0 and "sk-secret-2" not in result.output
    assert next(iter(state.agents.values()))["adapter_secrets"] == {"api_key": "sk-secret-2"}
