"""Evaluator store: fail-closed local-only, version-level RAG config, failed retrievals."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from pareeksha.events.settings import libpq_url
from tests.integration.audit_support import transaction
from tests.integration.eval_support import SeededCall, seed_run
from tests.integration.test_rag_metrics_eval import (
    DOC_TEXT,
    SPAN,
    deliver,
    rag_json,
    rag_rows,
    seed_rag,
)
from tests.unit.evaluation.fakes import judge_json


def sql(url: str, query: str, *params: Any) -> Any:
    with psycopg.connect(libpq_url(url), autocommit=True) as conn:
        cur = conn.execute(query, params)
        row = cur.fetchone() if cur.description else None
        return None if row is None else row[0]


async def inputs_and_snapshot(url: str, call: SeededCall) -> tuple[Any, Any]:
    async with transaction(url) as ctx:
        store = PgEvaluatorStore(ctx.tx)
        return await store.load_rag_inputs(call.call_id), await store.load_snapshot(call.call_id)


async def test_unknown_kb_counts_as_local_only(database_url: str) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    cfg = {"mode": "retrieval", "kb_id": str(uuid.uuid4())}  # no such knowledge base
    sql(
        database_url,
        "UPDATE test_runs SET config = %s WHERE id = %s",
        Jsonb({"rag": cfg}),
        call.run_id,
    )
    inp, snap = await inputs_and_snapshot(database_url, call)
    assert inp.local_only is True and snap.local_only is True


async def test_a_call_without_rag_is_not_local_only(database_url: str) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    inp, snap = await inputs_and_snapshot(database_url, call)
    assert inp is None and snap.local_only is False


async def test_snapshot_knows_a_local_only_kb(database_url: str) -> None:
    for flag in (True, False):
        call = seed_run(libpq_url(database_url), 1)[0]
        seed_rag(database_url, call, local_only=flag)
        _, snap = await inputs_and_snapshot(database_url, call)
        assert snap.local_only is flag


def seed_version_rag(url: str, call: SeededCall, *, local_only: bool = False) -> None:
    """RAG config on the pinned prompt version only: no run override, no retrievals rows."""
    project = sql(url, "SELECT project_id FROM agents WHERE id = %s", call.agent_id)
    kb = sql(
        url,
        "INSERT INTO knowledge_bases (project_id, name, local_only) VALUES (%s, 'kb', %s) "
        "RETURNING id",
        project,
        local_only,
    )
    doc = sql(
        url,
        "INSERT INTO kb_documents (kb_id, project_id, filename, mime, sha256, text, char_count, "
        "blob_key) VALUES (%s, %s, 'faq.txt', 'text/plain', 'x', %s, %s, 'k') RETURNING id",
        kb,
        project,
        DOC_TEXT,
        len(DOC_TEXT),
    )
    version = sql(
        url,
        "INSERT INTO prompt_versions (project_id, agent_id, version, system_prompt, provider, "
        "model, temperature, rag_config, content_hash) "
        "VALUES (%s, %s, 1, 'p', 'openai', 'm', 0.2, %s, 'h') RETURNING id",
        project,
        call.agent_id,
        Jsonb({"mode": "retrieval", "kb_id": str(kb)}),
    )
    sql(
        url,
        "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
        Jsonb({"adapter_config": {"active_version_id": str(version)}}),
        call.run_id,
    )
    sql(
        url,
        "UPDATE scenarios SET rag_expectation = %s WHERE id = "
        "(SELECT scenario_id FROM run_items WHERE id = %s)",
        Jsonb(
            {
                "source_document_id": str(doc),
                "source_span": list(SPAN),
                "reference_answer": "7 business days",
                "answerable": True,
            }
        ),
        call.run_item_id,
    )


async def test_version_level_config_with_every_retrieval_failed_is_a_miss(
    database_url: str,
) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    seed_version_rag(database_url, call)
    failed = {"t_ms": 5, "type": "retrieval_failed", "data": {"error": "x", "turn_idx": 1}}
    sql(
        database_url,
        "UPDATE calls SET event_log = %s WHERE id = %s",
        Jsonb([failed]),
        call.call_id,
    )
    inp, snap = await inputs_and_snapshot(database_url, call)
    assert inp is not None and inp.mode == "retrieval" and inp.failed_turns == [1]
    assert snap.local_only is False

    await deliver(database_url, call, [judge_json(evidence=[2]), rag_json()])
    (row,) = await rag_rows(database_url, call.call_id)
    assert row["metrics"]["hit_at_k"] is False and row["metrics"]["reciprocal_rank"] == 0.0


async def test_version_level_local_only_kb_is_found(database_url: str) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    seed_version_rag(database_url, call, local_only=True)
    inp, snap = await inputs_and_snapshot(database_url, call)
    assert inp.local_only is True and snap.local_only is True
    provider = await deliver(database_url, call, [judge_json(evidence=[2])])
    assert provider.requests == []  # neither judge saw the transcript
