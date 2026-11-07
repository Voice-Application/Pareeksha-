"""Per-project LLM settings (docs/06-api-spec.md section 13).

The row overrides the environment for this project's judge, caller, scenario generation, role
detection and designer calls. The API key is write-only: stored encrypted (Fernet, ``SECRET_KEY``),
shown only as ``api_key_set`` and its last four characters.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Response
from pydantic import BaseModel

from pareeksha.api.auth import AdminKey, ReadKey
from pareeksha.api.crud import flush
from pareeksha.api.deps import AUTH_ERRORS, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.llm_deps import LlmBuilder
from pareeksha.api.routers.integrations import _secret_box
from pareeksha.db.models import ProjectLlmSettings
from pareeksha.integrations.ssrf import SSRFError, dev_allow_private, resolve_public
from pareeksha.llm._http import public_error
from pareeksha.llm.base import ChatMessage, LLMError, LLMPurpose
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.llm.project_settings import (
    OPENAI_COMPATIBLE,
    ProjectLLMRow,
    apply_row,
    load_row,
)
from pareeksha.schemas.settings import LLMSettingsOut, LLMSettingsUpdate, LLMTestResult

router = APIRouter(tags=["settings"], responses=AUTH_ERRORS)


def _env_key(env: LLMSettings, provider: str) -> str | None:
    return env.gemini_api_key if provider == "gemini" else env.deepseek_api_key


def _env_models(env: LLMSettings, provider: str) -> tuple[str | None, str | None, str | None]:
    if provider == "gemini":
        return env.gemini_judge_model, env.gemini_caller_model, env.gemini_designer_model
    if provider == "deepseek":
        return env.deepseek_judge_model, env.deepseek_caller_model, env.deepseek_designer_model
    return None, None, None


def _out(env: LLMSettings, row: ProjectLLMRow | None) -> LLMSettingsOut:
    """What the API shows; never the key. Models fall back to the environment's values."""
    provider = row.provider if row else env.llm_provider.value
    env_judge, env_caller, env_designer = _env_models(env, provider)
    judge = (row.judge_model if row else None) or env_judge
    caller = (row.caller_model if row else None) or env_caller
    designer = (row.designer_model if row else None) or env_designer or judge
    if row is not None and provider == OPENAI_COMPATIBLE:
        base_url = row.base_url
    elif provider == "deepseek":
        base_url = env.deepseek_base_url
    else:
        base_url = None
    stored = row is not None and row.api_key_encrypted is not None
    fallback = provider != OPENAI_COMPATIBLE and bool(_env_key(env, provider))
    return LLMSettingsOut(
        provider=provider,  # type: ignore[arg-type]
        base_url=base_url,
        judge_model=judge,
        caller_model=caller,
        designer_model=designer,
        api_key_set=stored or fallback,
        api_key_last4=row.api_key_last4 if row else None,
        source="project" if row else "environment",
    )


@router.get("/settings/llm", summary="The project's effective LLM settings (never the key)")
async def get_llm_settings(key: ReadKey, session: Db) -> LLMSettingsOut:
    return _out(LLMSettings(), await load_row(session, key.project_id))


async def _check_base_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ApiError(
            422,
            "unsafe_url",
            "base_url must not contain a query string, fragment or credentials",
            {"field": "base_url"},
        )
    try:
        await resolve_public(url, allow_private=dev_allow_private())
    except SSRFError as exc:
        raise ApiError(
            422, "unsafe_url", f"base_url is not allowed: {exc}", {"field": "base_url"}
        ) from exc


@router.put(
    "/settings/llm",
    responses=errors(422),
    summary="Set the project's LLM provider, models and key (admin)",
)
async def put_llm_settings(body: LLMSettingsUpdate, key: AdminKey, session: Db) -> LLMSettingsOut:
    env = LLMSettings()
    existing = await session.get(ProjectLlmSettings, key.project_id)
    provider = body.provider

    if provider == OPENAI_COMPATIBLE:
        if not body.base_url:
            raise ApiError(422, "validation_error", "base_url is required for openai_compatible")
        if not (body.judge_model and body.caller_model):
            raise ApiError(
                422,
                "validation_error",
                "judge_model and caller_model are required for openai_compatible",
            )
        await _check_base_url(body.base_url)
        base_url: str | None = body.base_url
    else:
        base_url = None  # deepseek / gemini use the provider's own endpoint

    encrypted: str | None = None
    last4: str | None = None
    if body.api_key:
        encrypted = _secret_box().encrypt({"api_key": body.api_key})
        # the tail of a short key would be most of the key: show it only for long keys
        last4 = body.api_key[-4:] if len(body.api_key) >= 12 else None
    elif existing is not None and existing.provider == provider:
        encrypted, last4 = existing.api_key_encrypted, existing.api_key_last4  # keep
    if encrypted is None and (provider == OPENAI_COMPATIBLE or not _env_key(env, provider)):
        raise ApiError(
            422,
            "validation_error",
            f"No API key for {provider}: send api_key (the key of another provider is not reused)"
            + ("" if provider == OPENAI_COMPATIBLE else " or set it in the server environment"),
            {"field": "api_key"},
        )
    if provider == "gemini":
        env_judge, env_caller, _ = _env_models(env, provider)
        if not ((body.judge_model or env_judge) and (body.caller_model or env_caller)):
            raise ApiError(
                422,
                "validation_error",
                "gemini needs judge_model and caller_model (none is set in the server environment)",
            )

    values: dict[str, Any] = {
        "provider": provider,
        "base_url": base_url,
        "judge_model": body.judge_model,
        "caller_model": body.caller_model,
        "designer_model": body.designer_model,
        "api_key_encrypted": encrypted,
        "api_key_last4": last4,
        "updated_at": datetime.now(UTC),
    }
    if existing is None:
        existing = ProjectLlmSettings(project_id=key.project_id, **values)
        session.add(existing)
    else:
        for field, value in values.items():
            setattr(existing, field, value)
    await flush(session, "Could not save the LLM settings", refresh=existing)
    return _out(env, await load_row(session, key.project_id))


@router.delete(
    "/settings/llm",
    status_code=204,
    summary="Remove the project's LLM settings; the environment's apply again (admin)",
)
async def delete_llm_settings(key: AdminKey, session: Db) -> Response:
    row = await session.get(ProjectLlmSettings, key.project_id)
    if row is not None:
        await session.delete(row)
        await flush(session, "Could not remove the LLM settings")
    return Response(status_code=204)


class _Ping(BaseModel):
    ok: bool


def _short(exc: BaseException, secret: str | None) -> str:
    text = " ".join(str(exc).split())[:240] or type(exc).__name__
    return text.replace(secret, "***") if secret else text


@router.post(
    "/settings/llm/test",
    summary="One tiny call with the effective settings (admin); errors come back as ok=false",
)
async def test_llm_settings(key: AdminKey, session: Db, build: LlmBuilder) -> LLMTestResult:
    row = await load_row(session, key.project_id)
    provider: Any = row.provider if row else LLMSettings().llm_provider.value
    secret: str | None = None
    model: str | None = None
    try:
        settings = apply_row(LLMSettings(), row)
        secret = settings.api_key
        model = settings.judge_model
        client = build(settings, None)
    except LLMConfigError as exc:
        return LLMTestResult(
            ok=False, provider=provider, model=model, latency_ms=None, error=_short(exc, secret)
        )
    try:
        # judge purpose: deterministic, a model every provider setup has
        result = await client.generate_json(
            purpose=LLMPurpose.JUDGE,
            messages=[ChatMessage(role="user", content='Reply with the json object {"ok": true}.')],
            schema=_Ping,
            max_output_tokens=20,
            timeout_s=20.0,
            repair_attempts=1,
        )
    except LLMError as exc:  # never the provider's body: status code only
        return LLMTestResult(
            ok=False,
            provider=provider,
            model=model,
            latency_ms=None,
            error=public_error(exc, secret),
        )
    except LLMConfigError as exc:
        return LLMTestResult(
            ok=False, provider=provider, model=model, latency_ms=None, error=_short(exc, secret)
        )
    except Exception as exc:  # a provider failure must never become a 500 here
        return LLMTestResult(
            ok=False,
            provider=provider,
            model=model,
            latency_ms=None,
            error=f"unexpected error: {type(exc).__name__}",
        )
    finally:
        await client.aclose()
    return LLMTestResult(
        ok=True, provider=provider, model=model, latency_ms=result.latency_ms, error=None
    )
