"""``pareeksha.yaml`` (config-as-code, docs/10 section 3.3) and the CLI profile file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from pareeksha_sdk.errors import ConfigError

AGENT_FIELDS = {
    "name",
    "description",
    "adapter",
    "adapter_config",
    "endpoint_url",
    "languages",
    "glass_box",
    "mandatory_disclosures",
    "forbidden_phrases",
    "expected_tools",
    "bias_list",
    "max_call_seconds",
}
SCENARIO_FIELDS = {
    "title",
    "caller_goal",
    "fixtures",
    "reveal_rules",
    "success_criteria",
    "must_say",
    "must_not_say",
    "expected_tool_calls",
    "caller_speaks_first",
    "max_turns",
    "tags",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioSelector(_Strict):
    tags: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)


class Suite(_Strict):
    scenarios: ScenarioSelector = Field(default_factory=ScenarioSelector)
    personas: list[str] = Field(default_factory=list)
    noise_profiles: list[str] = Field(default_factory=list)
    fail_under: float | None = Field(default=None, ge=0, le=100)
    repeats: int = Field(default=1, ge=1, le=20)
    max_concurrency: int | None = Field(default=None, ge=1, le=20)


class ProjectConfig(_Strict):
    version: int
    agent: dict[str, Any]
    scenarios: list[dict[str, Any]] = Field(default_factory=list)
    personas: list[dict[str, Any]] = Field(default_factory=list)
    noise_profiles: list[dict[str, Any]] = Field(default_factory=list)
    suites: dict[str, Suite] = Field(default_factory=dict)

    @field_validator("version")
    @classmethod
    def _version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("only version: 1 is supported")
        return value

    @field_validator("agent")
    @classmethod
    def _agent(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_keys("agent", value, AGENT_FIELDS, required=("name",))
        return value

    @field_validator("scenarios")
    @classmethod
    def _scenarios(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in value:
            _check_keys("scenario", item, SCENARIO_FIELDS, required=("title",))
        _unique("scenario", [s["title"] for s in value])
        return value

    @field_validator("personas", "noise_profiles")
    @classmethod
    def _named(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in value:
            _check_keys("entry", item, None, required=("name",))
        _unique("name", [s["name"] for s in value])
        return value


def _check_keys(
    what: str, value: dict[str, Any], allowed: set[str] | None, required: tuple[str, ...]
) -> None:
    for key in required:
        if not value.get(key):
            raise ValueError(f"{what}: '{key}' is required")
    if allowed is not None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"{what}: unknown field(s) {unknown}")


def _unique(what: str, names: list[str]) -> None:
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"duplicate {what}(s): {dupes}")


def _resolve_file_refs(value: Any, base_dir: Path) -> Any:
    """``file://relative/path`` strings are replaced with the file's text."""
    if isinstance(value, str) and value.startswith("file://"):
        path = (base_dir / value.removeprefix("file://")).resolve()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"cannot read {value}: {exc}") from exc
    if isinstance(value, dict):
        return {k: _resolve_file_refs(v, base_dir) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_file_refs(v, base_dir) for v in value]
    return value


def load_config(path: Path) -> ProjectConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    try:
        return ProjectConfig.model_validate(_resolve_file_refs(raw, path.parent))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"{path}: {problems}") from exc


# --- CLI profile (~/.config/pareeksha/config.toml) --------------------------------------------


def profile_path() -> Path:
    override = os.environ.get("PAREEKSHA_CONFIG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "pareeksha" / "config.toml"


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def save_profile(url: str, key: str, path: Path | None = None) -> Path:
    target = path or profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"url = {_toml_str(url)}\nkey = {_toml_str(key)}\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def load_profile(path: Path | None = None) -> tuple[str, str]:
    """Credentials: ``PAREEKSHA_URL`` / ``PAREEKSHA_KEY`` win over the saved profile."""
    url = os.environ.get("PAREEKSHA_URL")
    key = os.environ.get("PAREEKSHA_KEY")
    if not (url and key):
        target = path or profile_path()
        try:
            data = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        url = url or data.get("url")
        key = key or data.get("key")
    if not url or not key:
        raise ConfigError("not logged in: run `pareeksha login --url ... --key ...`")
    return url, key
