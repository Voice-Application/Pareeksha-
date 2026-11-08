"""RAG matrix: a group of ordinary runs (one per config/baseline) and the report over them.

Creation pre-validates every entry before any run is written, and the whole thing runs in the
request's single transaction, so a missing index on entry 3 leaves nothing behind.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.errors import ApiError
from pareeksha.db.models import (
    Calls,
    KbIndexes,
    PriceOverrides,
    PromptVersions,
    RagMatrices,
    RagMetrics,
    Retrievals,
    RunItems,
    TestRuns,
    Turns,
)
from pareeksha.rag.report import CallData, EntryModels, Prices, Summary, finish, summarize
from pareeksha.runs import service
from pareeksha.runs.estimate import is_over_budget
from pareeksha.schemas.rag import RagConfig, rag_label
from pareeksha.schemas.rag_report import RagMatrixCreate, RagMatrixOut, RagReport
from pareeksha.schemas.runs import RunConfig, RunCreate


def _entries(body: RagMatrixCreate) -> list[tuple[str, str, RagConfig]]:
    kb_id = body.configs[0].kb_id
    out: list[tuple[str, str, RagConfig]] = []
    if body.baselines.no_rag:
        out.append(("No RAG", "no_rag", RagConfig(mode="off", kb_id=kb_id)))
    if body.baselines.full_context:
        fc = RagConfig(
            mode="full_context", kb_id=kb_id, context_char_limit=body.configs[0].context_char_limit
        )
        out.append(("Full context", "full_context", fc))
    out += [(rag_label(c), "rag", c) for c in body.configs]
    used: set[str] = set()
    unique: list[tuple[str, str, RagConfig]] = []
    for label, kind, cfg in out:  # entries are keyed by label: "x", "x (2)", "x (3)"
        n, candidate = 1, label
        while candidate in used:
            n += 1
            candidate = f"{label} ({n})"
        used.add(candidate)
        unique.append((candidate, kind, cfg))
    return unique


async def create_matrix(
    session: AsyncSession, project_id: uuid.UUID, body: RagMatrixCreate
) -> RagMatrixOut:
    """Validate every entry, then create one run per entry plus the ``rag_matrices`` row.

    All runs execute ``body.prompt_version`` (default: the agent's active version; 404 if the
    agent has no such version) and the row's ``prompt_version_id`` names it. 409
    ``rag_index_missing`` lists every entry without a ready index; 402 if the summed estimate
    is over budget and not confirmed.
    """
    reqs = [
        (
            label,
            kind,
            cfg,
            RunCreate(
                agent_id=body.agent_id,
                name=f"RAG · {label}",
                scenario_ids=body.scenario_ids,
                persona_ids=body.persona_ids,
                noise_profile_ids=body.noise_profile_ids,
                repeats=body.repeats,
                config=RunConfig(rag=cfg),
                confirm_over_budget=True,  # the SUM is checked below
            ),
        )
        for label, kind, cfg in _entries(body)
    ]
    # Phase 1: validate everything, write nothing.
    # The matrix tests body.prompt_version (default: the active one); every run is pinned to it
    # and nothing changes which version is active.
    prepared = await service.prepare(
        session, project_id, reqs[0][3], prompt_version=body.prompt_version
    )
    if prepared.agent.adapter != "prompt":
        raise ApiError(422, "validation_error", "RAG matrices need a prompt agent")
    version = prepared.version
    assert version is not None  # resolve_version raised (422 / 404) otherwise
    missing: list[dict[str, Any]] = []
    na: dict[str, str] = {}
    costs: dict[str, float] = {}
    for label, _kind, _cfg, req in reqs:
        p = await service.prepare(session, project_id, req, prompt_version=version.version)
        costs[label] = p.estimate.est_cost
        try:
            # also refuses a local-only KB (409 local_only) for every entry, baselines included
            await service._pin_rag(session, project_id, p)
        except ApiError as exc:
            if exc.code == "rag_index_missing":
                missing.append(
                    {
                        "label": label,
                        **{k: v for k, v in (exc.details or {}).items() if k != "kb_id"},
                    }
                )
            elif exc.code == "full_context_too_large":
                d = exc.details or {}
                na[label] = (
                    f"n/a: KB is {d.get('chars')} chars, limit {d.get('context_char_limit')}"
                )
            else:
                raise
    if missing:
        raise ApiError(
            409,
            "rag_index_missing",
            "Build the missing indexes first",
            {"missing": missing},
        )
    n_runs = len(reqs) - len(na)
    total = sum(c for label, c in costs.items() if label not in na)  # an n/a entry never runs
    if n_runs and is_over_budget(total, prepared.remaining) and not body.confirm_over_budget:
        raise ApiError(
            402,
            "budget_exceeded",
            "The estimated cost of all runs is above the remaining budget",
            {
                "estimate": {"est_cost": total},
                "remaining_budget": prepared.remaining,
                "hint": "send confirm_over_budget=true to run anyway",
            },
        )
    # Phase 2: create.
    entries: list[dict[str, Any]] = []
    for label, kind, cfg, req in reqs:
        run_id = (
            None
            if label in na
            else (
                await service.create_run(session, project_id, req, prompt_version=version.version)
            ).id
        )
        entries.append(
            {
                "label": label,
                "kind": kind,
                "run_id": None if run_id is None else str(run_id),
                "status_note": na.get(label),
                "rag": cfg.model_dump(mode="json"),
            }
        )
    row = RagMatrices(
        project_id=project_id,
        agent_id=body.agent_id,
        prompt_version_id=version.id,
        kb_id=body.configs[0].kb_id,
        request=body.model_dump(mode="json"),
        entries=entries,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return matrix_out(row)


def matrix_out(row: RagMatrices) -> RagMatrixOut:
    return RagMatrixOut.model_validate(
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "kb_id": row.kb_id,
            "entries": row.entries,
            "created_at": row.created_at,
        }
    )


# --- report: DB loading -----------------------------------------------------------------------


async def load_prices(session: AsyncSession, project_id: uuid.UUID) -> Prices:
    rows = (
        await session.scalars(select(PriceOverrides).where(PriceOverrides.project_id == project_id))
    ).all()
    return {
        (r.kind, r.provider, r.model): (Decimal(r.input_per_m_inr), r.output_per_m_inr)
        for r in rows
    }


async def _load_calls(
    session: AsyncSession, project_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CallData]]:
    """Completed calls of each run with their metrics, retrievals, events and agent turn times."""
    rows = (
        await session.execute(
            select(Calls.id, RunItems.run_id, Calls.event_log)
            .join(RunItems, RunItems.id == Calls.run_item_id)
            .where(
                RunItems.run_id.in_(run_ids),
                Calls.project_id == project_id,
                Calls.status == "completed",
            )
        )
    ).all()
    call_ids = [r[0] for r in rows]
    metrics = {
        m.call_id: m
        for m in (
            await session.scalars(select(RagMetrics).where(RagMetrics.call_id.in_(call_ids)))
        ).all()
    }
    rets: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for r in (
        await session.scalars(select(Retrievals).where(Retrievals.call_id.in_(call_ids)))
    ).all():
        rets[r.call_id].append({"timings": r.timings, "usage": r.usage})
    turns: dict[uuid.UUID, list[int]] = defaultdict(list)
    for call_id, start, end in (
        await session.execute(
            select(Turns.call_id, Turns.start_ms, Turns.end_ms).where(
                Turns.call_id.in_(call_ids), Turns.speaker == "agent"
            )
        )
    ).all():
        turns[call_id].append(end - start)
    out: dict[uuid.UUID, list[CallData]] = defaultdict(list)
    for call_id, run_id, events in rows:
        m = metrics.get(call_id)
        out[run_id].append(
            CallData(
                metrics=dict(m.metrics) if m else {},
                skipped=list(m.skipped) if m else [],
                retrievals=rets[call_id],
                events=list(cast("list[Any]", events or [])),
                agent_turn_ms=turns[call_id],
            )
        )
    return out


async def build_report(
    session: AsyncSession, project_id: uuid.UUID, matrix: RagMatrices, monthly: int
) -> RagReport:
    entries: list[dict[str, Any]] = list(matrix.entries)
    run_ids = [uuid.UUID(e["run_id"]) for e in entries if e.get("run_id")]
    runs = {
        r.id: r
        for r in (
            await session.scalars(
                select(TestRuns).where(TestRuns.id.in_(run_ids), TestRuns.project_id == project_id)
            )
        ).all()
    }
    calls = await _load_calls(session, project_id, run_ids) if run_ids else {}
    prices = await load_prices(session, project_id)
    version = await session.get(PromptVersions, matrix.prompt_version_id)
    llm = (version.provider, version.model) if version else None
    index_ids = [
        uuid.UUID(str(cast("dict[str, Any]", r.config)["rag_index_id"]))
        for r in runs.values()
        if cast("dict[str, Any]", r.config).get("rag_index_id")
    ]
    stats = {
        i.id: i.stats
        for i in (
            await session.scalars(
                select(KbIndexes).where(
                    KbIndexes.id.in_(index_ids), KbIndexes.project_id == project_id
                )
            )
        ).all()
    }
    summaries: list[Summary] = []
    for e in entries:
        rag = e.get("rag") or {}
        run = runs.get(uuid.UUID(e["run_id"])) if e.get("run_id") else None
        models = EntryModels(llm=llm)
        index_tokens = 0
        if e["kind"] == "rag":
            emb = rag.get("embedding") or {}
            models.embedding = (emb.get("provider", "local"), emb.get("model", ""))
            if rag.get("method") == "hybrid_rerank":
                models.rerank = (
                    rag.get("reranker_provider", "local"),
                    rag.get("reranker_model", ""),
                )
            pinned = cast("dict[str, Any]", run.config).get("rag_index_id") if run else None
            if pinned:
                st = stats.get(uuid.UUID(str(pinned))) or {}
                index_tokens = int(st.get("input_tokens") or 0)
        s = summarize(
            e["label"],
            e["kind"],
            calls.get(run.id, []) if run else [],
            run_id=run.id if run else None,
            run_status=run.status if run else None,
            prices=prices,
            models=models,
            index_tokens=index_tokens,
        )
        s.row["status_note"] = e.get("status_note")
        summaries.append(s)
    rows, rec = finish(summaries, monthly)
    return RagReport.model_validate(
        {
            "matrix_id": matrix.id,
            "monthly_conversations": monthly,
            "rows": rows,
            "recommendation": rec,
        }
    )
