"""Per-project LLM settings: the ``llm_settings`` row overlaid on the environment's ``LLMSettings``.

``effective_llm_settings`` is the one resolver (API and workers). Providers: ``deepseek``,
``gemini`` and ``openai_compatible`` (the DeepSeek provider class pointed at a user base URL; its
usage is recorded as ``deepseek`` because ``api_usage.provider`` has a fixed set of values).

Security rule: an ``openai_compatible`` project never falls back to the environment's DeepSeek key,
so that key cannot be sent to a user-chosen URL.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pareeksha.integrations.crypto import SecretBox, SecretDecryptError
from pareeksha.llm.base import LLMProvider, LLMProviderName
from pareeksha.llm.client import LLMClient, UsageSink
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.factory import build_provider

OPENAI_COMPATIBLE = "openai_compatible"
PROVIDERS = ("deepseek", "gemini", OPENAI_COMPATIBLE)

_COLUMNS = (
    "provider, base_url, judge_model, caller_model, designer_model, api_key_encrypted, "
    "api_key_last4, updated_at"
)


@dataclass(frozen=True)
class ProjectLLMRow:
    provider: str
    base_url: str | None
    judge_model: str | None
    caller_model: str | None
    designer_model: str | None
    api_key_encrypted: str | None
    api_key_last4: str | None
    updated_at: datetime


def decrypt_key(token: str | None) -> str | None:
    """The stored API key, or ``None`` when the row keeps none (the environment's key is used)."""
    if not token:
        return None
    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise LLMConfigError("SECRET_KEY is not configured; cannot read the project's API key")
    try:
        return SecretBox(secret).decrypt(token).get("api_key")
    except SecretDecryptError as exc:
        raise LLMConfigError(str(exc)) from exc


async def load_row(source: Any, project_id: uuid.UUID) -> ProjectLLMRow | None:
    """The project's row from an ``AsyncSession`` (API) or a psycopg connection (workers)."""
    if hasattr(source, "get"):  # SQLAlchemy AsyncSession
        from pareeksha.db.models import ProjectLlmSettings

        orm = await source.get(ProjectLlmSettings, project_id)
        if orm is None:
            return None
        return ProjectLLMRow(
            orm.provider,
            orm.base_url,
            orm.judge_model,
            orm.caller_model,
            orm.designer_model,
            orm.api_key_encrypted,
            orm.api_key_last4,
            orm.updated_at,
        )
    cur = await source.execute(
        f"SELECT {_COLUMNS} FROM llm_settings WHERE project_id = %s", (project_id,)
    )
    found = await cur.fetchone()
    return None if found is None else ProjectLLMRow(*found)


def apply_row(env: LLMSettings, row: ProjectLLMRow | None) -> LLMSettings:
    """``env`` with the project's row laid over it; ``env`` itself when there is no row."""
    if row is None:
        return env
    key = decrypt_key(row.api_key_encrypted)
    models = {"judge": row.judge_model, "caller": row.caller_model, "designer": row.designer_model}
    if row.provider == "gemini":
        update: dict[str, Any] = {"llm_provider": LLMProviderName.GEMINI}
        if key:
            update["gemini_api_key"] = key
        update.update({f"gemini_{k}_model": v for k, v in models.items() if v})
    else:
        update = {"llm_provider": LLMProviderName.DEEPSEEK}
        if row.provider == OPENAI_COMPATIBLE:
            update.update(
                deepseek_base_url=row.base_url,
                deepseek_guard_base_url=True,
                deepseek_api_key=key,  # None on purpose: no fallback to the env DeepSeek key
                deepseek_designer_model=row.designer_model,
                cost_deepseek_per_1k_input_tokens=None,  # the env rates are DeepSeek's, not theirs
                cost_deepseek_per_1k_output_tokens=None,
            )
            update.update(
                {f"deepseek_{k}_model": v for k, v in models.items() if v and k != "designer"}
            )
        else:
            if key:
                update["deepseek_api_key"] = key
            update.update({f"deepseek_{k}_model": v for k, v in models.items() if v})
    return env.model_copy(update=update)


async def effective_llm_settings(source: Any, project_id: uuid.UUID) -> LLMSettings:
    """Environment settings overlaid with the project's ``llm_settings`` row (if any)."""
    return apply_row(LLMSettings(), await load_row(source, project_id))


def fingerprint(settings: LLMSettings, row: ProjectLLMRow) -> str:
    """Changes whenever the row (``updated_at``) or anything it resolves to changes."""
    blob = f"{row.updated_at.isoformat()}\x00{settings.model_dump_json()}"
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class ResolvedLLM:
    fingerprint: str
    provider: LLMProvider
    settings: LLMSettings

    def client(self, usage_sink: UsageSink | None = None) -> LLMClient:
        """A client over the shared provider; closing is the cache's job, not the caller's."""
        return LLMClient(self.provider, self.settings, usage_sink=usage_sink)


class ProjectLLMClients:
    """Providers cached by ``(project_id, settings fingerprint)`` for the workers.

    A settings change (new ``updated_at``) gives a new fingerprint, so the next message builds a
    fresh provider without a restart. Replaced providers are kept until ``aclose`` because a call
    may still be using them (ponytail: one small object per settings change).
    A project without a row returns ``None``: the caller keeps its process-wide environment client.
    """

    def __init__(self) -> None:
        self._current: dict[uuid.UUID, ResolvedLLM] = {}
        self._retired: list[LLMProvider] = []

    async def resolve(self, source: Any, project_id: uuid.UUID) -> ResolvedLLM | None:
        row = await load_row(source, project_id)
        if row is None:
            self._retire(project_id)
            return None
        settings = apply_row(LLMSettings(), row)
        fp = fingerprint(settings, row)
        held = self._current.get(project_id)
        if held is None or held.fingerprint != fp:
            self._retire(project_id)
            held = ResolvedLLM(fp, build_provider(settings), settings)  # LLMConfigError: no key
            self._current[project_id] = held
        return held

    def _retire(self, project_id: uuid.UUID) -> None:
        old = self._current.pop(project_id, None)
        if old is not None:
            self._retired.append(old.provider)

    async def aclose(self) -> None:
        providers = [r.provider for r in self._current.values()] + self._retired
        self._current.clear()
        self._retired.clear()
        for provider in providers:
            await provider.aclose()
