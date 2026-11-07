"""RAG ground-truth questions: CSV import, refusal for local-only KBs, generator branch (Task 8)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.events.consumer import Ctx
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.workers.generator import handle_generate_requested
from tests.conftest import Tenant
from tests.integration.domain import API, build_world, outbox_for

# Uploads write blobs: always use the temp-dir store, never the repo's ./data/runtime.
pytestmark = pytest.mark.usefixtures("blobs")

KB = f"{API}/knowledge-bases"
QUOTE = "Refunds are issued within 7 days."
DOC = QUOTE + " " + "filler words " * 300


class ScriptedRagLLM(LLMProvider):
    """Two answerable questions (one real quote, one invented) and one unanswerable."""

    name = LLMProviderName.DEEPSEEK

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.prompts.append(request.messages[0].content)
        questions = [
            {
                "passage": 1,
                "question": "Refund window?",
                "reference_answer": "7 days",
                "quote": QUOTE,
                "answerable": True,
            },
            {
                "passage": 2,
                "question": "Invented?",
                "reference_answer": "x",
                "quote": "This sentence is not in the document.",
                "answerable": True,
            },
            {
                "passage": None,
                "question": "Ship to Nepal?",
                "reference_answer": "",
                "quote": "",
                "answerable": False,
            },
        ]
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=json.dumps({"questions": questions}),
            usage=LLMUsage(input_tokens=10, output_tokens=10),
            latency_ms=1,
        )

    async def aclose(self) -> None:
        return None


async def _kb_with_doc(api: AsyncClient, tenant: Tenant, **body: Any) -> dict[str, Any]:
    body.setdefault("name", f"kb-{uuid.uuid4().hex[:8]}")
    kb: dict[str, Any] = (await api.post(KB, json=body, headers=tenant.admin)).json()
    up = await api.post(
        f"{KB}/{kb['id']}/documents",
        files={"file": ("Policy.txt", DOC.encode())},
        headers=tenant.admin,
    )
    assert up.status_code == 201, up.text
    kb["doc_id"] = up.json()["id"]
    return kb


async def test_import_csv_creates_scenarios_and_reports_unmatched(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    world = await build_world(api, tenant)
    kb = await _kb_with_doc(api, tenant)
    csv_text = (
        "﻿question,expected_answer,source_document,source_quote\n"
        "Refund window?,7 days,policy.TXT,refunds are  issued within 7 days.\n"
        "Other?,x,missing.txt,whatever\n"
        "Wrong quote?,x,Policy.txt,this is not there\n"
        ",x,Policy.txt,y\n"
        "Ship to Nepal?,Not covered,,\n"
    )
    url = f"{KB}/{kb['id']}/questions:import"
    r = await api.post(
        url,
        data={"agent_id": str(world.agent_id)},
        files={"file": ("q.csv", csv_text.encode("utf-8"))},
        headers=tenant.admin,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "created": 2,
        "unmatched": [
            {"row": 2, "reason": "document_not_found"},
            {"row": 3, "reason": "quote_not_found"},
            {"row": 4, "reason": "empty_question"},
        ],
    }
    items = (await api.get(f"{API}/scenarios", params={"tag": "rag"}, headers=tenant.read)).json()[
        "items"
    ]
    by_title = {s["title"]: s for s in items}
    exp = by_title["Refund window?"]["rag_expectation"]
    assert exp["source_document_id"] == kb["doc_id"] and exp["answerable"] is True
    a, b = exp["source_span"]
    assert DOC[a:b].lower() == "refunds are issued within 7 days."
    assert by_title["Ship to Nepal?"]["rag_expectation"]["answerable"] is False
    assert by_title["Ship to Nepal?"]["tags"] == ["rag", "unanswerable"]
    other = await build_world(api, other_tenant)
    nope = await api.post(
        url,
        data={"agent_id": str(other.agent_id)},
        files={"file": ("q.csv", csv_text.encode())},
        headers=tenant.admin,
    )
    assert nope.status_code == 404
    bad = await api.post(
        url,
        data={"agent_id": str(world.agent_id)},
        files={"file": ("q.csv", b"question\nx\n")},
        headers=tenant.admin,
    )
    assert bad.status_code == 422


async def test_generate_refused_for_local_only(api: AsyncClient, tenant: Tenant) -> None:
    world = await build_world(api, tenant)
    kb = await _kb_with_doc(api, tenant, local_only=True)
    r = await api.post(
        f"{KB}/{kb['id']}/questions:generate",
        json={"agent_id": str(world.agent_id), "count": 3},
        headers=tenant.admin,
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "local_only"


async def test_generator_rag_kind_drops_unmatched(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    kb = await _kb_with_doc(api, tenant)
    accepted = await api.post(
        f"{KB}/{kb['id']}/questions:generate",
        json={"agent_id": str(world.agent_id), "count": 3, "unanswerable_share": 0.34},
        headers=tenant.admin,
    )
    assert accepted.status_code == 202, accepted.text
    draft_id = accepted.json()["draft_id"]
    env = (await outbox_for(session_factory, "draft_id", draft_id))[0]
    provider = ScriptedRagLLM()

    def make(sink: Any) -> LLMClient:
        settings = LLMSettings(deepseek_api_key="k", deepseek_caller_model="pinned")
        return LLMClient(provider, settings, usage_sink=sink)

    ctx = Ctx(tx=pg, group="generator", topic=env.topic.value, partition=0, offset=0, attempt=1)
    async with pg.transaction():
        await handle_generate_requested(env, ctx, make)  # type: ignore[arg-type]
    draft = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert draft["status"] == "ready", draft
    assert draft["request"]["unmatched"] == 1
    assert [d["title"] for d in draft["drafts"]] == ["Refund window?", "Ship to Nepal?"]
    first = draft["drafts"][0]
    assert first["caller_goal"] == "Ask the agent: Refund window?"
    assert first["success_criteria"] == "7 days" and first["max_turns"] == 4
    a, b = first["rag_expectation"]["source_span"]
    assert DOC[a:b] == QUOTE and first["agent_id"] == str(world.agent_id)
    assert "json" in provider.prompts[0].lower()
    bulk = await api.post(
        f"{API}/scenarios:bulk", json={"scenarios": draft["drafts"]}, headers=tenant.admin
    )
    assert bulk.status_code == 201, bulk.text
    assert bulk.json()["items"][0]["rag_expectation"]["source_span"] == [a, b]
