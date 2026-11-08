"""GET /calls/{id} carries the call's retrievals (one per agent turn), project-scoped."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from pareeksha.db.models import Retrievals
from pareeksha.schemas.rag import RagConfig, rag_label
from tests.conftest import Tenant
from tests.integration.api04_support import Factory, new_rubric, seed_full_call
from tests.integration.runs_support import API

KB_ID = uuid.uuid4()
CFG = {"kb_id": str(KB_ID), "method": "bm25", "top_k": 2}


def result(rank: int) -> dict[str, object]:
    return {
        "rank": rank,
        "chunk_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "filename": "faq.txt",
        "start_char": 0,
        "end_char": 24,
        "score": 1.5 / rank,
        "text": "Refunds take seven days.",
    }


async def add_retrievals(factory: Factory, call_id: uuid.UUID) -> None:
    async with factory() as session, session.begin():
        session.add_all(
            [
                Retrievals(
                    call_id=call_id,
                    turn_idx=3,
                    rag_config=CFG,
                    query="second question",
                    queries=["second question"],
                    results=[],
                    context_chars=0,
                    timings={"total_ms": 3},
                    usage={},
                ),
                Retrievals(
                    call_id=call_id,
                    turn_idx=1,
                    rag_config=CFG,
                    query="how long do refunds take",
                    queries=["how long do refunds take", "refund time"],
                    results=[result(1), result(2)],
                    context_chars=120,
                    timings={"embed_ms": 4, "search_ms": 1, "total_ms": 5},
                    usage={"embed_tokens": 6},
                ),
            ]
        )


async def test_call_detail_lists_retrievals_in_turn_order(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(session_factory, tenant, None, rubric)
    await add_retrievals(session_factory, seeded.call_id)
    body = (await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)).json()
    first, second = body["retrievals"]
    assert (first["turn_idx"], second["turn_idx"]) == (1, 3)
    assert first["query"] == "how long do refunds take"
    assert first["queries"] == ["how long do refunds take", "refund time"]
    assert first["context_chars"] == 120
    assert first["timings"] == {"embed_ms": 4, "search_ms": 1, "total_ms": 5}
    assert first["rag_label"] == rag_label(RagConfig.model_validate(CFG))
    assert [r["rank"] for r in first["results"]] == [1, 2]
    assert first["results"][0]["filename"] == "faq.txt"
    assert first["results"][0]["text"] == "Refunds take seven days."
    assert first["results"][1]["score"] == 0.75
    assert second["results"] == []


async def test_call_without_rag_has_no_retrievals(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(session_factory, tenant, None, rubric)
    body = (await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)).json()
    assert body["retrievals"] == []


async def test_retrievals_are_project_scoped(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(session_factory, tenant, None, rubric)
    await add_retrievals(session_factory, seeded.call_id)
    mine = await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)
    assert len(mine.json()["retrievals"]) == 2
    theirs = await api.get(f"{API}/calls/{seeded.call_id}", headers=other_tenant.read)
    assert theirs.status_code == 404 and "retrievals" not in theirs.json()


async def test_an_old_config_shape_falls_back_to_its_label(
    api: AsyncClient, tenant: Tenant, session_factory: Factory
) -> None:
    rubric = await new_rubric(session_factory)
    seeded = await seed_full_call(session_factory, tenant, None, rubric)
    async with session_factory() as session, session.begin():
        session.add(
            Retrievals(
                call_id=seeded.call_id,
                turn_idx=1,
                rag_config={"label": "legacy", "method": "no-longer-valid"},
                query="q",
                results=[],
            )
        )
    body = (await api.get(f"{API}/calls/{seeded.call_id}", headers=tenant.read)).json()
    assert body["retrievals"][0]["rag_label"] == "legacy"
