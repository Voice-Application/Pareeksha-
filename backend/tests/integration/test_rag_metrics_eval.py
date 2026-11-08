"""The evaluator path writes ``rag_metrics`` (retrieval + judged metrics); a re-delivery upserts."""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.evaluation.handlers import handle_call_completed
from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from pareeksha.events.schemas import CallCompleted, make_envelope
from pareeksha.events.settings import libpq_url
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.eval_support import SeededCall, seed_run
from tests.unit.evaluation.fakes import ScriptedProvider, client_for, judge_json

DOC_TEXT = "Refunds are processed within 7 business days. Late fees are Rs 100."
SPAN = (0, 46)


def seed_rag(url: str, call: SeededCall, *, local_only: bool = False) -> None:
    with psycopg.connect(libpq_url(url), autocommit=True) as conn:

        def one(sql: str, *params: Any) -> Any:
            row = conn.execute(sql, params).fetchone()
            assert row is not None
            return row[0]

        project = one("SELECT project_id FROM agents WHERE id = %s", call.agent_id)
        kb = one(
            "INSERT INTO knowledge_bases (project_id, name, local_only) VALUES (%s, 'kb', %s) "
            "RETURNING id",
            project,
            local_only,
        )
        doc = one(
            "INSERT INTO kb_documents (kb_id, project_id, filename, mime, sha256, text, "
            "char_count, blob_key) VALUES (%s, %s, 'faq.txt', 'text/plain', 'x', %s, %s, 'k') "
            "RETURNING id",
            kb,
            project,
            DOC_TEXT,
            len(DOC_TEXT),
        )
        index = one(
            "INSERT INTO kb_indexes (kb_id, project_id, version, index_key, chunking, embedding, "
            "status) VALUES (%s, %s, 1, 'k', '{}', '{}', 'ready') RETURNING id",
            kb,
            project,
        )
        chunk = one(
            "INSERT INTO kb_chunks (index_id, document_id, ordinal, text, start_char, end_char, "
            "parent_start, parent_end, text_sha) VALUES (%s, %s, 0, %s, %s, %s, %s, %s, 's') "
            "RETURNING id",
            index,
            doc,
            DOC_TEXT[: SPAN[1]],
            SPAN[0],
            SPAN[1],
            SPAN[0],
            SPAN[1],
        )
        cfg = {"mode": "retrieval", "kb_id": str(kb)}
        conn.execute(
            "UPDATE test_runs SET config = %s WHERE id = %s",
            (Jsonb({"rag": cfg}), call.run_id),
        )
        conn.execute(
            "UPDATE scenarios SET rag_expectation = %s WHERE id = "
            "(SELECT scenario_id FROM run_items WHERE id = %s)",
            (
                Jsonb(
                    {
                        "source_document_id": str(doc),
                        "source_span": list(SPAN),
                        "reference_answer": "7 business days",
                        "answerable": True,
                    }
                ),
                call.run_item_id,
            ),
        )
        result = {
            "chunk_id": str(chunk),
            "document_id": str(doc),
            "start_char": SPAN[0],
            "end_char": SPAN[1],
            "score": 1.0,
            "rank": 1,
            "method": "bm25",
        }
        conn.execute(
            "INSERT INTO retrievals (call_id, turn_idx, rag_config, index_id, query, results) "
            "VALUES (%s, 1, %s, %s, 'refund?', %s)",
            (call.call_id, Jsonb(cfg), index, Jsonb([result])),
        )


def rag_json() -> str:
    return json.dumps(
        {
            "claims": [
                {"text": "refunds take 7 days", "supported": True, "evidence": 0},
                {"text": "no late fee", "supported": False, "evidence": None},
            ],
            "answer_correct": True,
            "refused": False,
        }
    )


async def deliver(url: str, call: SeededCall, replies: list[str | Exception]) -> ScriptedProvider:
    provider = ScriptedProvider(replies)
    env = make_envelope(
        CallCompleted(
            call_id=call.call_id,
            source="simulation",
            agent_id=call.agent_id,
            run_id=call.run_id,
            run_item_id=call.run_item_id,
            end_reason="goal_achieved",
        ),
        producer="test",
        correlation_id=str(call.run_id),
    )
    async with transaction(url) as ctx:
        await handle_call_completed(cast(Any, env), PgEvaluatorStore(ctx.tx), client_for(provider))
    return provider


async def rag_rows(url: str, call_id: uuid.UUID) -> list[dict[str, Any]]:
    return await fetch_rows(
        url, "SELECT metrics, skipped FROM rag_metrics WHERE call_id = %s", call_id
    )


async def test_evaluator_writes_rag_metrics_and_upserts(database_url: str) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    seed_rag(database_url, call)
    provider = await deliver(database_url, call, [judge_json(evidence=[2]), rag_json()])
    assert len(provider.requests) == 2
    assert (
        "Refunds are processed within 7 business days" in provider.requests[1].messages[0].content
    )
    rows = await rag_rows(database_url, call.call_id)
    assert len(rows) == 1
    m = rows[0]["metrics"]
    assert m["mode"] == "retrieval" and m["hit_at_k"] is True and m["reciprocal_rank"] == 1.0
    assert m["context_precision"] == 1.0 and m["faithfulness"] == 0.5
    assert m["hallucinated"] is True and m["answer_correct"] is True
    assert m["refusal_correct"] is True and rows[0]["skipped"] == []

    # re-delivery: upsert, no duplicate; a judge failure is skipped, not fatal
    await deliver(database_url, call, [judge_json(evidence=[2])] + [RuntimeError("boom")] * 5)
    rows = await rag_rows(database_url, call.call_id)
    assert len(rows) == 1
    assert rows[0]["metrics"]["hit_at_k"] is True and "faithfulness" not in rows[0]["metrics"]
    assert {s["reason"] for s in rows[0]["skipped"]} == {"judge_error"}


async def test_local_only_kb_makes_no_rag_llm_call(database_url: str) -> None:
    call = seed_run(libpq_url(database_url), 1)[0]
    seed_rag(database_url, call, local_only=True)
    provider = await deliver(database_url, call, [judge_json(evidence=[2])])
    # not even the rubric judge: the transcript carries the KB's text to the hosted LLM
    assert provider.requests == []
    ev = await fetch_rows(
        database_url,
        "SELECT status, needs_human_review, review_reasons FROM evaluations WHERE call_id = %s",
        call.call_id,
    )
    assert len(ev) == 1 and ev[0]["needs_human_review"] is True
    assert ev[0]["status"] == "judge_error" and "local_only" in ev[0]["review_reasons"]
    rows = await rag_rows(database_url, call.call_id)
    assert rows[0]["metrics"]["hit_at_k"] is True
    assert {s["reason"] for s in rows[0]["skipped"]} == {"local_only"}
