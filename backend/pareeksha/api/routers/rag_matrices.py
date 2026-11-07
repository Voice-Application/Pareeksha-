"""RAG matrices, their report, and per-project pricing (plans/2026-11-07-rag-lab.md, Task 9)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.db.models import KbIndexes, PriceOverrides, PromptVersions, RagMatrices
from pareeksha.rag.matrix import build_report, create_matrix, matrix_out
from pareeksha.schemas.common import Page
from pareeksha.schemas.rag_report import (
    PriceIn,
    PriceOut,
    PricingOut,
    RagMatrixCreate,
    RagMatrixOut,
    RagReport,
    UnpricedModel,
)

router = APIRouter(tags=["rag-lab"], responses=AUTH_ERRORS)


@router.post(
    "/rag-matrices",
    status_code=201,
    responses=errors(402, 404, 409, 422),
    summary="Create a RAG matrix (one run per config and baseline)",
)
async def post_rag_matrix(body: RagMatrixCreate, key: WriteKey, session: Db) -> RagMatrixOut:
    return await create_matrix(session, key.project_id, body)


@router.get("/rag-matrices", summary="List RAG matrices")
async def list_rag_matrices(
    key: ReadKey, session: Db, page: Pagination, agent_id: UUID | None = None
) -> Page[RagMatrixOut]:
    conds = [RagMatrices.project_id == key.project_id]
    if agent_id:
        conds.append(RagMatrices.agent_id == agent_id)
    rows, nxt = await paginate(session, RagMatrices, conds, page)
    return Page[RagMatrixOut](items=[matrix_out(r) for r in rows], next_cursor=nxt)


@router.get("/rag-matrices/{id}", responses=errors(404), summary="Get a RAG matrix")
async def get_rag_matrix(id: UUID, key: ReadKey, session: Db) -> RagMatrixOut:
    return matrix_out(await get_or_404(session, RagMatrices, id, key.project_id, "RAG matrix"))


@router.get(
    "/rag-matrices/{id}/report",
    responses=errors(404),
    summary="Retrieval quality, hallucination, latency, cost, savings and a recommendation",
)
async def get_rag_report(
    id: UUID,
    key: ReadKey,
    session: Db,
    monthly_conversations: Annotated[int, Query(ge=1, le=1_000_000_000)] = 10_000,
) -> RagReport:
    matrix = await get_or_404(session, RagMatrices, id, key.project_id, "RAG matrix")
    return await build_report(session, key.project_id, matrix, monthly_conversations)


# --- pricing ----------------------------------------------------------------------------------


def _price_out(r: PriceOverrides) -> PriceOut:
    return PriceOut(
        kind=r.kind,  # type: ignore[arg-type]
        provider=r.provider,
        model=r.model,
        input_per_m_inr=float(r.input_per_m_inr),
        output_per_m_inr=None if r.output_per_m_inr is None else float(r.output_per_m_inr),
        updated_at=r.updated_at,
    )


async def _pricing(session: Db, project_id: UUID) -> PricingOut:
    priced = (
        await session.scalars(
            select(PriceOverrides)
            .where(PriceOverrides.project_id == project_id)
            .order_by(PriceOverrides.kind, PriceOverrides.provider, PriceOverrides.model)
        )
    ).all()
    have = {(r.kind, r.provider, r.model) for r in priced}
    seen: set[tuple[str, str, str]] = set()
    for p, m in (
        await session.execute(
            select(PromptVersions.provider, PromptVersions.model)
            .where(PromptVersions.project_id == project_id)
            .distinct()
        )
    ).all():
        seen.add(("llm", p, m))
    for emb in (
        await session.scalars(select(KbIndexes.embedding).where(KbIndexes.project_id == project_id))
    ).all():
        seen.add(("embedding", str(emb.get("provider")), str(emb.get("model"))))
    for entries in (
        await session.scalars(
            select(RagMatrices.entries).where(RagMatrices.project_id == project_id)
        )
    ).all():
        for e in entries:
            rag = e.get("rag") or {}
            if rag.get("method") == "hybrid_rerank":
                seen.add(
                    ("rerank", str(rag.get("reranker_provider")), str(rag.get("reranker_model")))
                )
    unpriced = [
        UnpricedModel(kind=k, provider=p, model=m)  # type: ignore[arg-type]
        for k, p, m in sorted(seen - have)
        if k == "llm" or p != "local"  # local embedding/reranker always cost 0
    ]
    return PricingOut(prices=[_price_out(r) for r in priced], unpriced=unpriced)


@router.get("/pricing", summary="Prices entered for this project, and models still unpriced")
async def get_pricing(key: ReadKey, session: Db) -> PricingOut:
    return await _pricing(session, key.project_id)


@router.put(
    "/pricing",
    responses=errors(400),
    summary="Upsert prices (₹ per 1M tokens); local models are always 0",
)
async def put_pricing(body: list[PriceIn], key: WriteKey, session: Db) -> PricingOut:
    for p in body:
        stmt = insert(PriceOverrides).values(
            project_id=key.project_id,
            kind=p.kind,
            provider=p.provider,
            model=p.model,
            input_per_m_inr=p.input_per_m_inr,
            output_per_m_inr=p.output_per_m_inr,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                constraint="price_overrides_project_kind_key",
                set_={
                    "input_per_m_inr": stmt.excluded.input_per_m_inr,
                    "output_per_m_inr": stmt.excluded.output_per_m_inr,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
        )
    await session.flush()
    return await _pricing(session, key.project_id)
