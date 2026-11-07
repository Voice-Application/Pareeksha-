"""DB-free fakes for route tests: auth by header, an in-memory session, a scripted LLM provider."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import Header
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient

from pareeksha.api.auth import Principal, authenticate, has_scope
from pareeksha.api.errors import ApiError
from pareeksha.api.llm_deps import get_client_builder
from pareeksha.api.main import app
from pareeksha.api.ratelimit import DESIGNER_CHAT_LIMIT
from pareeksha.db.models import NoiseProfiles, Personas, ProjectLlmSettings
from pareeksha.db.session import get_session, get_session_factory
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient

KEY_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PROJECT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
LLM_ENV = (
    "LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_JUDGE_MODEL",
    "DEEPSEEK_CALLER_MODEL",
    "DEEPSEEK_DESIGNER_MODEL",
    "GEMINI_API_KEY",
    "GEMINI_JUDGE_MODEL",
    "GEMINI_CALLER_MODEL",
    "GEMINI_DESIGNER_MODEL",
    "PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS",
    "BUDGET_CREDITS",
)


def clean_llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """No LLM variables and no ``.env`` file (settings read ``.env`` from the cwd)."""
    monkeypatch.chdir(tmp_path)
    for name in LLM_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())


class FakeSession:
    """The few AsyncSession methods the settings / designer routes use."""

    def __init__(self) -> None:
        self.rows: dict[tuple[type, Any], Any] = {}
        self.added: list[Any] = []
        self.library: dict[type, list[Any]] = {Personas: [], NoiseProfiles: []}
        self.spent = 0.0
        self.committed = False

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def scalar(self, stmt: Any) -> float:
        return self.spent  # the project's recorded api_usage cost

    async def get(self, model: type, pk: Any) -> Any:
        return self.rows.get((model, pk))

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, ProjectLlmSettings):
            self.rows[(ProjectLlmSettings, obj.project_id)] = obj

    async def delete(self, obj: Any) -> None:
        self.rows.pop((type(obj), obj.project_id), None)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        return None

    async def scalars(self, stmt: Any) -> Iterator[Any]:
        return iter(self.library[stmt.column_descriptions[0]["entity"]])


class ScriptedProvider(LLMProvider):
    """Returns the queued texts (or raises the queued exception) and records the requests."""

    name = LLMProviderName.DEEPSEEK

    def __init__(self, *outputs: str | BaseException) -> None:
        self.outputs = list(outputs)
        self.requests: list[JSONCompletionRequest] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.requests.append(request)
        out = self.outputs.pop(0)
        if isinstance(out, BaseException):
            raise out
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=out,
            usage=LLMUsage(input_tokens=100, output_tokens=10),
            latency_ms=7,
        )

    async def aclose(self) -> None:
        return None


def persona_row(name: str = "Asha", language: str = "hi-IN") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        language=language,
        dialect_label="",
        code_mix_style="light",
        emotion="neutral",
        behaviour_notes="",
    )


def noise_row(name: str = "clean") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        description="",
        codec="none",
        background_category=None,
        snr_db=None,
    )


class Harness:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.provider = ScriptedProvider()
        self.usage_session = FakeSession()  # the sink's own session / transaction
        self.client = TestClient(app)

    def call(self, method: str, path: str, scopes: str = "admin", **kw: Any) -> Any:
        headers = {"x-test-scopes": scopes}
        return self.client.request(method, f"/api/v1{path}", headers=headers, **kw)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[Harness]:
    clean_llm_env(monkeypatch, tmp_path)
    session = FakeSession()
    h = Harness(session)

    async def fake_auth(
        security_scopes: SecurityScopes, x_test_scopes: str = Header(default="")
    ) -> Principal:
        granted = frozenset(x_test_scopes.split(","))
        if not has_scope(granted, security_scopes.scopes):
            raise ApiError(403, "forbidden", "API key lacks the required scope")
        return Principal(key_id=KEY_ID, project_id=PROJECT_ID, scopes=granted)

    async def fake_session() -> Any:
        yield session

    DESIGNER_CHAT_LIMIT._state.clear()
    app.dependency_overrides[get_session_factory] = lambda: lambda: h.usage_session
    app.dependency_overrides[authenticate] = fake_auth
    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_client_builder] = lambda: (
        lambda settings, sink: LLMClient(h.provider, settings, usage_sink=sink)
    )
    yield h
    for dep in (authenticate, get_session, get_session_factory, get_client_builder):
        app.dependency_overrides.pop(dep, None)


def turn_json(**fields: Any) -> str:
    """An assistant answer; fields override the question-turn defaults."""
    body: dict[str, Any] = {"reply": "ok", "questions": [], "draft": None, "ready": False}
    body.update(fields)
    return json.dumps(body)
