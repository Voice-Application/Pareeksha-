"""Live smoke test for the hosted chat, embedding and reranker providers.

For each provider whose key is set in the environment, run one small real call through the
production provider classes (``build_chat_provider``, ``build_embedder``, ``build_reranker``), so
every request goes through ``pareeksha.agent_llm.base.post_json`` (https only, public address
pinned, no redirects, 10 MiB cap):

* chat: one turn with one tool the model must call; PASS needs a call to that tool.
* embed: two short documents; PASS needs two equal-length, finite, non-identical vectors.
* rerank: one query and three documents; PASS needs three finite scores with the relevant
  document on top.

Keys are read ONLY from environment variables, never from arguments, files or ``.env``:

    OPENAI_API_KEY                chat openai, embed openai
    ANTHROPIC_API_KEY             chat anthropic
    GEMINI_API_KEY                chat gemini, embed gemini
    DEEPSEEK_API_KEY              chat deepseek
    GROQ_API_KEY                  chat groq
    MISTRAL_API_KEY               chat mistral, embed mistral
    COHERE_API_KEY                embed cohere, rerank cohere
    VOYAGE_API_KEY                embed voyage, rerank voyage
    JINA_API_KEY                  embed jina, rerank jina
    AZURE_OPENAI_API_KEY          embed azure_openai, with
      AZURE_OPENAI_ENDPOINT         https://<resource>.openai.azure.com
      AZURE_OPENAI_EMBEDDING_DEPLOYMENT   the embedding deployment name
    AWS_BEARER_TOKEN_BEDROCK      embed bedrock (a Bedrock API key, sent as a bearer token;
                                  SigV4 access keys are not supported), with
      AWS_REGION                    default us-east-1 (falls back to AWS_DEFAULT_REGION)
    OLLAMA_BASE_URL               embed ollama (keyless; e.g. http://localhost:11434/v1, the
                                  same server Pareeksha trusts; default model qwen3-embedding:0.6b)

Models default to a small current model per provider and are overridden with
``SMOKE_<PROVIDER>_MODEL`` (chat), ``SMOKE_<PROVIDER>_EMBED_MODEL`` (embed) and
``SMOKE_<PROVIDER>_RERANK_MODEL`` (rerank), e.g. ``SMOKE_OPENAI_MODEL=gpt-4.1``.

Output is one line per check, ``PASS|FAIL|SKIP <kind> <provider> <model> <ms> <detail>``. Every
detail has each key value replaced by ``***``. Exit status is 1 if any check failed, else 0.

    PYTHONPATH=backend python scripts/smoke_providers.py [--only openai,cohere]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from pareeksha.agent_llm.base import AgentLLMError, AgentMessage, ToolSpec  # noqa: E402
from pareeksha.agent_llm.factory import build_chat_provider  # noqa: E402
from pareeksha.rag.embeddings import build_embedder  # noqa: E402
from pareeksha.rag.rerank import build_reranker  # noqa: E402
from pareeksha.schemas.rag import EmbeddingConfig  # noqa: E402

Kind = Literal["chat", "embed", "rerank"]
OLLAMA_ENV = "OLLAMA_BASE_URL"

KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY",
    "voyage": "VOYAGE_API_KEY",
    "jina": "JINA_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "bedrock": "AWS_BEARER_TOKEN_BEDROCK",
}

CHAT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-haiku-4-5",
    "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-flash",
    "groq": "openai/gpt-oss-20b",
    "mistral": "mistral-small-latest",
}
EMBED_MODELS = {
    "gemini": "gemini-embedding-001",
    "openai": "text-embedding-3-small",
    "azure_openai": "",  # the deployment name (AZURE_OPENAI_EMBEDDING_DEPLOYMENT)
    "cohere": "embed-v4.0",
    "voyage": "voyage-3.5-lite",
    "jina": "jina-embeddings-v3",
    "mistral": "mistral-embed",
    "bedrock": "amazon.titan-embed-text-v2:0",
    "ollama": "qwen3-embedding:0.6b",
}
RERANK_MODELS = {
    "cohere": "rerank-v3.5",
    "jina": "jina-reranker-v3",
    "voyage": "rerank-2.5-lite",
}
PROVIDERS = sorted(set(CHAT_MODELS) | set(EMBED_MODELS) | set(RERANK_MODELS))

WEATHER_TOOL = ToolSpec(
    name="get_weather",
    description="Current weather for a city.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name"}},
        "required": ["city"],
    },
)
CHAT_MESSAGES = [
    AgentMessage("system", "You are a test harness. Answer every question by calling a tool."),
    AgentMessage("user", "What is the weather in Paris right now? Use the get_weather tool."),
]
EMBED_TEXTS = ["The cat sat on the mat.", "Interest rates rose by a quarter point in March."]
RERANK_QUERY = "How do I reset my password?"
RERANK_DOCS = [
    "The cafeteria opens at 8 am on weekdays.",
    "To reset your password, open Settings, choose Security and click Reset password.",
    "Quarterly revenue grew by four percent.",
]
RERANK_EXPECTED_TOP = 1


class SmokeFailure(Exception):
    """A provider answered, but the answer does not meet the check's expectation."""


@dataclass(frozen=True, slots=True)
class Result:
    status: Literal["PASS", "FAIL", "SKIP"]
    kind: Kind
    provider: str
    model: str
    ms: int
    detail: str


def _secrets() -> list[str]:
    """Every key value set in the environment, longest first, for redaction."""
    values = {os.environ.get(name, "") for name in KEY_ENVS.values()}
    return sorted((v for v in values if v), key=len, reverse=True)


def redact(text: str) -> str:
    """``text`` on one line with every configured key value replaced by ``***``."""
    for secret in _secrets():
        text = text.replace(secret, "***")
    return " ".join(text.split())


def _model(kind: Kind, provider: str, default: str) -> str:
    """The model for a check: ``SMOKE_<PROVIDER>[_EMBED|_RERANK]_MODEL`` or ``default``."""
    suffix = {"chat": "", "embed": "_EMBED", "rerank": "_RERANK"}[kind]
    return os.environ.get(f"SMOKE_{provider.upper()}{suffix}_MODEL") or default


def _key(provider: str) -> str:
    """The provider's key from the environment, or "" when unset (Ollama needs none)."""
    return os.environ.get(KEY_ENVS[provider], "").strip() if provider in KEY_ENVS else ""


def _missing(provider: str) -> str | None:
    """Why `provider` is skipped (the env var it needs), or None when it can run."""
    if provider == "ollama":
        return None if os.environ.get(OLLAMA_ENV, "").strip() else f"{OLLAMA_ENV} not set"
    return None if _key(provider) else f"{KEY_ENVS[provider]} not set"


async def check_chat(provider: str, model: str, key: str) -> str:
    """One chat turn with ``get_weather``; the reply must call that tool."""
    chat = build_chat_provider(provider, api_key=key)  # type: ignore[arg-type]
    reply = await chat.chat(CHAT_MESSAGES, [WEATHER_TOOL], model=model, temperature=0.0)
    calls = [c for c in reply.tool_calls if c.name == WEATHER_TOOL.name]
    if not calls:
        names = [c.name for c in reply.tool_calls]
        raise SmokeFailure(f"no {WEATHER_TOOL.name} call (calls={names}, text={reply.text[:80]!r})")
    args = json.dumps(calls[0].arguments, sort_keys=True)
    return f"tool={calls[0].name} args={args} tokens={reply.input_tokens}/{reply.output_tokens}"


def _embedding_config(provider: str, model: str) -> EmbeddingConfig:
    """The ``EmbeddingConfig`` for ``provider``; Azure and Bedrock get their base URL from env."""
    base_url: str | None = None
    if provider == "azure_openai":
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        if not endpoint or not model:
            raise SmokeFailure(
                "AZURE_OPENAI_API_KEY is set but AZURE_OPENAI_ENDPOINT or "
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not"
            )
        base_url = f"{endpoint}/openai/deployments/{model}"
    elif provider == "bedrock":
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        base_url = f"https://bedrock-runtime.{region.strip()}.amazonaws.com"
    return EmbeddingConfig(provider=provider, model=model, base_url=base_url)  # type: ignore[arg-type]


async def check_embed(provider: str, model: str, key: str) -> str:
    """Embed two short documents; expect two equal-length, finite, distinct vectors."""
    embedder = build_embedder(_embedding_config(provider, model), api_key=key)
    res = await embedder.embed(EMBED_TEXTS, kind="document")
    if len(res.vectors) != len(EMBED_TEXTS):
        raise SmokeFailure(f"expected {len(EMBED_TEXTS)} vectors, got {len(res.vectors)}")
    dims = {len(v) for v in res.vectors}
    if len(dims) != 1 or 0 in dims:
        raise SmokeFailure(f"vector lengths differ or are empty: {sorted(dims)}")
    if not all(isinstance(x, float | int) and math.isfinite(x) for v in res.vectors for x in v):
        raise SmokeFailure("vectors contain non-finite or non-numeric values")
    if res.vectors[0] == res.vectors[1]:
        raise SmokeFailure("the two different texts got identical vectors")
    return f"vectors={len(res.vectors)} dims={dims.pop()} tokens={res.input_tokens}"


async def check_rerank(provider: str, model: str, key: str) -> str:
    """Rerank three documents; expect three finite scores with the relevant one on top."""
    reranker = build_reranker(provider, model, api_key=key)
    scores, _ = await reranker.rerank(RERANK_QUERY, RERANK_DOCS)
    if len(scores) != len(RERANK_DOCS) or not all(math.isfinite(s) for s in scores):
        raise SmokeFailure(f"expected {len(RERANK_DOCS)} finite scores, got {scores}")
    top = max(range(len(scores)), key=scores.__getitem__)
    shown = "[" + ",".join(f"{s:.3f}" for s in scores) + "]"
    if top != RERANK_EXPECTED_TOP:
        raise SmokeFailure(f"doc {top} ranked first, expected {RERANK_EXPECTED_TOP}: {shown}")
    return f"scores={shown} top={top}"


Runner = Callable[[str, str, str], Awaitable[str]]


async def run_one(
    kind: Kind, provider: str, default_model: str, runner: Runner, show_provider_errors: bool
) -> Result:
    """Run one check, turning a missing key into SKIP and any exception into a redacted FAIL."""
    if provider == "azure_openai":  # the model is the deployment name
        default_model = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "").strip()
    model = _model(kind, provider, default_model)
    key = _key(provider)
    missing = _missing(provider)
    if missing:
        return Result("SKIP", kind, provider, model or "-", 0, missing)
    start = time.monotonic()
    try:
        detail = await runner(provider, model, key)
        status: Literal["PASS", "FAIL"] = "PASS"
    except AgentLLMError as exc:
        status, detail = "FAIL", f"AgentLLMError: {exc}"
        if show_provider_errors and exc.provider_message:
            detail += f" | provider: {exc.provider_message}"
    except Exception as exc:  # report every failure as a line, never a traceback
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    ms = int((time.monotonic() - start) * 1000)
    return Result(status, kind, provider, model or "-", ms, redact(detail))


def plan(only: set[str] | None) -> list[tuple[Kind, str, str, Runner]]:
    """Every (kind, provider, default model, runner) check, filtered by ``--only``."""
    checks: list[tuple[Kind, str, str, Runner]] = []
    checks += [("chat", p, m, check_chat) for p, m in CHAT_MODELS.items()]
    checks += [("embed", p, m, check_embed) for p, m in EMBED_MODELS.items()]
    checks += [("rerank", p, m, check_rerank) for p, m in RERANK_MODELS.items()]
    return [c for c in checks if only is None or c[1] in only]


def parse_only(value: str) -> set[str]:
    """``--only`` as a set of provider names; unknown names are an argparse error."""
    names = {v.strip() for v in value.split(",") if v.strip()}
    unknown = names - set(PROVIDERS)
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"unknown provider(s) {sorted(unknown)}; choose from {', '.join(PROVIDERS)}"
        )
    return names


async def main(only: set[str] | None, show_provider_errors: bool) -> int:
    """Run the planned checks one at a time, print a line each, and return the exit status."""
    failed = False
    for kind, provider, default_model, runner in plan(only):
        r = await run_one(kind, provider, default_model, runner, show_provider_errors)
        print(f"{r.status} {r.kind} {r.provider} {r.model} {r.ms} {r.detail}", flush=True)
        failed = failed or r.status == "FAIL"
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    """The command-line parser; ``--help`` prints the module docstring (the env var list)."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--only",
        type=parse_only,
        default=None,
        metavar="P1,P2",
        help=f"comma-separated providers to check ({', '.join(PROVIDERS)})",
    )
    ap.add_argument(
        "--show-provider-errors",
        action="store_true",
        help="append the provider's own error text (key-redacted, 200 chars) to FAIL lines",
    )
    return ap


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(asyncio.run(main(args.only, args.show_provider_errors)))
