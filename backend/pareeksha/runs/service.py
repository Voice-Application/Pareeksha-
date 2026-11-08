"""The API side of runs (docs/06-api-spec.md section 3): create, estimate, read, cancel.

``create_run`` writes the run row and its ``run.requested`` outbox row through the request's
session, so both commit in one transaction (FR-RN-1); the planner worker creates the items.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.crud import (
    ACTIVE_VERSION_KEY,
    active_version,
    decode_cursor,
    encode_cursor,
    paginate,
)
from pareeksha.api.deps import PageParams
from pareeksha.api.errors import ApiError
from pareeksha.db.models import (
    Agents,
    ApiUsage,
    Calls,
    Evaluations,
    KbDocuments,
    KbIndexes,
    KnowledgeBases,
    NoiseProfiles,
    Personas,
    PriceOverrides,
    PromptVersions,
    RunItems,
    Scenarios,
    TestRuns,
)
from pareeksha.events.outbox import enqueue_session
from pareeksha.events.schemas import ProgressEvent, RunRequested, make_envelope
from pareeksha.rag.guard import (
    LocalOnlyError,
    require_local_agent,
    require_local_embedding,
    require_local_reranker,
    require_platform_llm_allowed,
)
from pareeksha.rag.local_models import UnsupportedModelError, require_supported_models
from pareeksha.runs.estimate import (
    AgentModelLoad,
    ScenarioShape,
    estimate_run,
    is_over_budget,
    remaining_budget,
)
from pareeksha.runs.matrix import MAX_RUN_ITEMS, item_count, unique_in_order
from pareeksha.schemas.agents import AgentOut
from pareeksha.schemas.common import Page
from pareeksha.schemas.rag import RagConfig, index_key
from pareeksha.schemas.runs import (
    RunCreate,
    RunCreated,
    RunEstimate,
    RunEstimateOut,
    RunItemOut,
    RunOut,
    RunProgress,
    RunSummary,
)

PRODUCER = "api"
#: ``test_runs.status`` values after which a run can no longer be cancelled.
FINISHED_RUN_STATUSES = ("completed", "partial", "cancelled", "failed")

_IN_PROGRESS_ITEM_STATUSES = ("connecting", "in_progress", "completed", "evaluating")
_ERROR_ITEM_STATUSES = ("error", "judge_error", "skipped_budget")


# --------------------------------------------------------------------------------------------
# Validation and estimate
# --------------------------------------------------------------------------------------------


async def _require_all(
    session: AsyncSession, model: Any, ids: list[uuid.UUID], project_id: uuid.UUID, what: str
) -> dict[uuid.UUID, Any]:
    rows = (
        await session.scalars(
            select(model).where(model.id.in_(ids), model.project_id == project_id)
        )
    ).all()
    found = {row.id: row for row in rows}
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise ApiError(404, "not_found", f"{what} not found", {"ids": missing})
    return found


class Prepared:
    """A validated run request with its estimate (nothing written yet).

    ``version`` is the prompt version the run executes (None for other adapters): the agent's
    active one unless the caller pinned another.
    """

    def __init__(
        self,
        body: RunCreate,
        agent: Agents,
        scenario_ids: list[uuid.UUID],
        persona_ids: list[uuid.UUID],
        noise_profile_ids: list[uuid.UUID],
        estimate: RunEstimate,
        remaining: float | None,
        version: PromptVersions | None = None,
    ) -> None:
        """Keep the validated pieces; ``item_count`` is derived from the de-duplicated ids."""
        self.body = body
        self.agent = agent
        self.version = version
        self.scenario_ids = scenario_ids
        self.persona_ids = persona_ids
        self.noise_profile_ids = noise_profile_ids
        self.estimate = estimate
        self.remaining = remaining
        self.item_count = item_count(
            len(scenario_ids), len(persona_ids), len(noise_profile_ids), body.repeats
        )

    @property
    def over_budget(self) -> bool:
        return is_over_budget(self.estimate.est_cost, self.remaining)

    @property
    def dry_run(self) -> bool:
        return self.body.kind == "dry_run" or self.body.config.dry_run


async def _spent(session: AsyncSession, project_id: uuid.UUID) -> float:
    total = await session.scalar(
        select(func.coalesce(func.sum(ApiUsage.est_cost), 0)).where(
            ApiUsage.project_id == project_id
        )
    )
    return float(total or 0)


async def require_active_version(session: AsyncSession, agent: Agents) -> None:
    """422 for a prompt agent without an active version (nothing to run); other adapters pass."""
    if agent.adapter == "prompt" and await active_version(session, agent) is None:
        raise ApiError(
            422, "prompt_agent_has_no_version", "Create a prompt version before running this agent"
        )


async def resolve_version(
    session: AsyncSession, agent: Agents, number: int | None = None
) -> PromptVersions | None:
    """The prompt version a run of ``agent`` executes: version ``number``, else the active one.

    None for adapters other than ``prompt``. Raises 422 ``prompt_agent_has_no_version`` when no
    number is given and nothing is active, 404 ``not_found`` (``{"version": n}``) when the agent
    has no version ``number``. Never changes which version is active.
    """
    if agent.adapter != "prompt":
        return None
    if number is None:
        await require_active_version(session, agent)
        return await active_version(session, agent)
    version = await session.scalar(
        select(PromptVersions).where(
            PromptVersions.agent_id == agent.id,
            PromptVersions.project_id == agent.project_id,
            PromptVersions.version == number,
        )
    )
    if version is None:
        raise ApiError(404, "not_found", "Prompt version not found", {"version": number})
    return version


async def agent_model_load(
    session: AsyncSession,
    project_id: uuid.UUID,
    version: PromptVersions | None,
    rag: RagConfig | None,
) -> AgentModelLoad | None:
    """What each reply of a prompt agent sends its own model, for the estimate (None otherwise).

    The RAG context is the run's override, else the version's config: ``top_k`` chunks of the
    chunk size for retrieval, the knowledge base's live characters for full context, nothing
    when off. The price is the project's ``llm`` price for the version's provider and model.
    """
    if version is None:
        return None
    raw = rag.model_dump(mode="json") if rag is not None else (version.rag_config or None)
    context = 0
    if raw:
        cfg = RagConfig.model_validate(raw)
        if cfg.mode == "retrieval":
            context = cfg.top_k * cfg.chunking.size
        elif cfg.mode == "full_context":
            context = int(
                await session.scalar(
                    select(func.coalesce(func.sum(KbDocuments.char_count), 0)).where(
                        KbDocuments.kb_id == cfg.kb_id,
                        KbDocuments.project_id == project_id,
                        KbDocuments.deleted_at.is_(None),
                    )
                )
                or 0
            )
            context = min(context, cfg.context_char_limit)  # larger: the run is refused
    tools = list(version.tools or [])
    price = await session.scalar(
        select(PriceOverrides).where(
            PriceOverrides.project_id == project_id,
            PriceOverrides.kind == "llm",
            PriceOverrides.provider == version.provider,
            PriceOverrides.model == version.model,
        )
    )
    return AgentModelLoad(
        prompt_chars=len(version.system_prompt) + (len(json.dumps(tools)) if tools else 0),
        context_chars=context,
        has_tools=bool(tools),
        input_per_m=None if price is None else float(price.input_per_m_inr),
        output_per_m=(
            None
            if price is None or price.output_per_m_inr is None
            else float(price.output_per_m_inr)
        ),
    )


async def prepare(
    session: AsyncSession,
    project_id: uuid.UUID,
    body: RunCreate,
    *,
    prompt_version: int | None = None,
) -> Prepared:
    """404 for unknown/foreign ids (and an archived agent), 400 for an oversized matrix.

    ``prompt_version`` pins a prompt agent's run to that version number instead of the active
    one (see :func:`resolve_version`); ``Prepared.version`` carries the result.
    """
    agent = (
        await session.scalars(
            select(Agents).where(Agents.id == body.agent_id, Agents.project_id == project_id)
        )
    ).one_or_none()
    if agent is None:
        raise ApiError(404, "not_found", "Agent not found", {"id": str(body.agent_id)})
    version = await resolve_version(session, agent, prompt_version)
    if agent.archived:
        raise ApiError(409, "conflict", "Agent is archived", {"id": str(body.agent_id)})

    scenario_ids = unique_in_order(body.scenario_ids)
    persona_ids = unique_in_order(body.persona_ids)
    noise_ids = unique_in_order(body.noise_profile_ids)
    count = item_count(len(scenario_ids), len(persona_ids), len(noise_ids), body.repeats)
    if count > MAX_RUN_ITEMS:
        raise ApiError(
            400,
            "validation_error",
            f"This run would make {count} calls; the limit is {MAX_RUN_ITEMS}",
            {"item_count": count, "max_items": MAX_RUN_ITEMS},
        )
    scenarios = await _require_all(session, Scenarios, scenario_ids, project_id, "Scenario")
    await _require_all(session, Personas, persona_ids, project_id, "Persona")
    await _require_all(session, NoiseProfiles, noise_ids, project_id, "Noise profile")

    dry_run = body.kind == "dry_run" or body.config.dry_run
    estimate = estimate_run(
        [ScenarioShape(max_turns=scenarios[i].max_turns) for i in scenario_ids],
        cells_per_scenario=len(persona_ids) * len(noise_ids) * body.repeats,
        max_call_seconds=agent.max_call_seconds,
        text_only=dry_run,
        agent=await agent_model_load(session, project_id, version, body.config.rag),
    )
    remaining = remaining_budget(await _spent(session, project_id))
    return Prepared(
        body, agent, scenario_ids, persona_ids, noise_ids, estimate, remaining, version=version
    )


async def estimate(session: AsyncSession, project_id: uuid.UUID, body: RunCreate) -> RunEstimateOut:
    prepared = await prepare(session, project_id, body)
    return RunEstimateOut(
        item_count=prepared.item_count,
        estimate=prepared.estimate,
        remaining_budget=prepared.remaining,
        over_budget=prepared.over_budget,
    )


# --------------------------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------------------------


async def _pin_rag(
    session: AsyncSession, project_id: uuid.UUID, prepared: Prepared
) -> dict[str, Any]:
    """Effective RAG config (run override, else the run's version's): guards and index pin.

    The version is ``prepared.version``, the one the run executes (pinned or active), so the
    local-only check sees that version's provider and base URL. Returns the extra
    ``test_runs.config`` keys (``rag_index_id`` or ``rag_full_context_chars``).
    """
    agent = prepared.agent
    if agent.adapter != "prompt":
        return {}
    version = prepared.version
    raw = prepared.body.config.rag or (version.rag_config if version else None)
    if not raw or version is None:
        return {}
    cfg = RagConfig.model_validate(raw)
    kb = await session.scalar(
        select(KnowledgeBases).where(
            KnowledgeBases.id == cfg.kb_id, KnowledgeBases.project_id == project_id
        )
    )
    if kb is None:
        if cfg.mode == "off":
            return {}
        raise ApiError(404, "not_found", "Knowledge base not found", {"id": str(cfg.kb_id)})
    try:
        # first, in every mode (also off): the transcript reaches the hosted caller and judge
        require_platform_llm_allowed(kb.local_only)
    except LocalOnlyError as exc:
        raise ApiError(409, "local_only", str(exc)) from exc
    if cfg.mode == "off":
        return {}
    try:
        require_supported_models(cfg)
    except UnsupportedModelError as exc:
        raise ApiError(422, "unsupported_model", str(exc)) from exc
    try:
        require_local_agent(kb.local_only, version.provider, version.base_url)
        if cfg.mode == "retrieval":
            require_local_embedding(kb.local_only, cfg.embedding)
            if cfg.method == "hybrid_rerank":
                require_local_reranker(kb.local_only, cfg.reranker_provider)
    except LocalOnlyError as exc:
        raise ApiError(409, "local_only", str(exc)) from exc
    if cfg.mode == "full_context":
        chars = int(
            await session.scalar(
                select(func.coalesce(func.sum(KbDocuments.char_count), 0)).where(
                    KbDocuments.kb_id == kb.id,
                    KbDocuments.project_id == project_id,
                    KbDocuments.deleted_at.is_(None),
                )
            )
            or 0
        )
        if chars > cfg.context_char_limit:
            raise ApiError(
                409,
                "full_context_too_large",
                "The knowledge base is larger than the context limit",
                {"chars": chars, "context_char_limit": cfg.context_char_limit},
            )
        return {"rag_full_context_chars": chars}
    index_id = await session.scalar(
        select(KbIndexes.id)
        .where(
            KbIndexes.kb_id == kb.id,
            KbIndexes.project_id == project_id,
            KbIndexes.index_key == index_key(cfg),
            KbIndexes.status == "ready",
        )
        .order_by(KbIndexes.version.desc())
        .limit(1)
    )
    if index_id is None:
        raise ApiError(
            409,
            "rag_index_missing",
            "Build an index with this chunking and embedding model first",
            {
                "kb_id": str(kb.id),
                "chunking": cfg.chunking.model_dump(mode="json"),
                "embedding": cfg.embedding.model_dump(mode="json"),
            },
        )
    return {"rag_index_id": str(index_id)}


async def create_run(
    session: AsyncSession,
    project_id: uuid.UUID,
    body: RunCreate,
    *,
    prompt_version: int | None = None,
) -> RunCreated:
    """Insert the run and its ``run.requested`` outbox row; both commit with the request.

    A prompt agent's run executes ``prompt_version`` (default: the active version): its id is
    written to ``agent_snapshot.adapter_config.active_version_id``, which the simulator's
    ``read_spec``, the evaluator and compare read instead of the agent's live config.
    """
    prepared = await prepare(session, project_id, body, prompt_version=prompt_version)
    rag_pins = await _pin_rag(session, project_id, prepared)
    if prepared.over_budget and not body.confirm_over_budget:
        raise ApiError(
            402,
            "budget_exceeded",
            "The estimated cost is above the remaining budget",
            {
                "estimate": prepared.estimate.model_dump(),
                "remaining_budget": prepared.remaining,
                "item_count": prepared.item_count,
                "hint": "send confirm_over_budget=true to run anyway",
            },
        )
    snapshot = AgentOut.model_validate(prepared.agent, from_attributes=True).model_dump(
        mode="json", exclude={"has_adapter_secrets"}
    )
    if prepared.version is not None:  # the version this run executes, whatever is active later
        snapshot["adapter_config"] = {
            **(snapshot.get("adapter_config") or {}),
            ACTIVE_VERSION_KEY: str(prepared.version.id),
        }
    run = TestRuns(
        id=uuid.uuid4(),
        project_id=project_id,
        agent_id=body.agent_id,
        name=body.name,
        kind=body.kind,
        status="queued",
        config={
            **body.config.model_dump(mode="json", exclude_none=True),
            "scenario_ids": [str(i) for i in prepared.scenario_ids],
            "persona_ids": [str(i) for i in prepared.persona_ids],
            "noise_profile_ids": [str(i) for i in prepared.noise_profile_ids],
            "repeats": body.repeats,
            "item_count": prepared.item_count,
            **rag_pins,
        },
        agent_snapshot=snapshot,
        estimated_cost=Decimal(str(prepared.estimate.est_cost)),
    )
    session.add(run)
    await session.flush()  # the outbox row is added to the same session (and transaction)
    payload = RunRequested(
        run_id=run.id,
        agent_id=body.agent_id,
        kind=body.kind,
        scenario_ids=prepared.scenario_ids,
        persona_ids=prepared.persona_ids,
        noise_profile_ids=prepared.noise_profile_ids,
        repeats=body.repeats,
        seed=body.config.seed,
    )
    enqueue_session(session, make_envelope(payload, producer=PRODUCER, correlation_id=str(run.id)))
    await session.flush()
    return RunCreated(
        id=run.id,
        status="queued",
        item_count=prepared.item_count,
        estimate=prepared.estimate,
    )


# --------------------------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------------------------


async def _progress(
    session: AsyncSession, runs: Sequence[TestRuns]
) -> dict[uuid.UUID, RunProgress]:
    """Item counts per run. Before the planner has created the items every item counts as queued."""
    ids = [r.id for r in runs]
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(dict)
    if ids:
        rows = await session.execute(
            select(RunItems.run_id, RunItems.status, func.count())
            .where(RunItems.run_id.in_(ids))
            .group_by(RunItems.run_id, RunItems.status)
        )
        for run_id, status, n in rows.all():
            counts[run_id][status] = n
    out: dict[uuid.UUID, RunProgress] = {}
    for run in runs:
        by_status = counts[run.id]
        planned = sum(by_status.values())
        expected = int(cast("dict[str, Any]", run.config).get("item_count", 0))
        total = max(planned, expected)
        out[run.id] = RunProgress(
            total=total,
            queued=by_status.get("queued", 0) + (total - planned),
            in_progress=sum(by_status.get(s, 0) for s in _IN_PROGRESS_ITEM_STATUSES),
            evaluated=by_status.get("evaluated", 0),
            error=sum(by_status.get(s, 0) for s in _ERROR_ITEM_STATUSES),
        )
    return out


def _run_out(run: TestRuns, progress: RunProgress) -> RunOut:
    return RunOut(
        id=run.id,
        agent_id=run.agent_id,
        name=run.name,
        kind=cast("Any", run.kind),
        status=cast("Any", run.status),
        progress=progress,
        summary=RunSummary.model_validate(run.summary or {}),
        estimated_cost=None if run.estimated_cost is None else float(run.estimated_cost),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _get_run(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> TestRuns:
    run = (
        await session.scalars(
            select(TestRuns).where(TestRuns.id == run_id, TestRuns.project_id == project_id)
        )
    ).one_or_none()
    if run is None:
        raise ApiError(404, "not_found", "Run not found", {"id": str(run_id)})
    return run


async def get_run(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> RunOut:
    run = await _get_run(session, project_id, run_id)
    return _run_out(run, (await _progress(session, [run]))[run.id])


async def list_runs(
    session: AsyncSession,
    project_id: uuid.UUID,
    page: PageParams,
    *,
    agent_id: uuid.UUID | None,
    status: str | None,
    kind: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> Page[RunOut]:
    conditions: list[Any] = [TestRuns.project_id == project_id]
    if agent_id is not None:
        conditions.append(TestRuns.agent_id == agent_id)
    if status is not None:
        conditions.append(TestRuns.status == status)
    if kind is not None:
        conditions.append(TestRuns.kind == kind)
    if created_from is not None:
        conditions.append(TestRuns.created_at >= created_from)
    if created_to is not None:
        conditions.append(TestRuns.created_at <= created_to)
    runs, next_cursor = await paginate(session, TestRuns, conditions, page)
    progress = await _progress(session, runs)
    return Page(items=[_run_out(r, progress[r.id]) for r in runs], next_cursor=next_cursor)


async def list_items(
    session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID, page: PageParams
) -> Page[RunItemOut]:
    """Matrix rows, oldest first (``created_at, id``), with the call and its latest evaluation."""
    await _get_run(session, project_id, run_id)
    stmt = (
        select(RunItems, Scenarios.title, Personas.name, NoiseProfiles.name, Calls.id)
        .join(Scenarios, Scenarios.id == RunItems.scenario_id)
        .join(Personas, Personas.id == RunItems.persona_id)
        .join(NoiseProfiles, NoiseProfiles.id == RunItems.noise_profile_id)
        .outerjoin(Calls, Calls.run_item_id == RunItems.id)
        .where(RunItems.run_id == run_id)
    )
    if page.cursor:
        created_at, row_id = decode_cursor(page.cursor)
        stmt = stmt.where(
            (RunItems.created_at > created_at)
            | ((RunItems.created_at == created_at) & (RunItems.id > row_id))
        )
    stmt = stmt.order_by(RunItems.created_at, RunItems.id).limit(page.limit + 1)
    rows = (await session.execute(stmt)).all()
    next_cursor = None
    if len(rows) > page.limit:
        rows = rows[: page.limit]
        last = rows[-1][0]
        next_cursor = encode_cursor(last.created_at, last.id)

    call_ids = [call_id for *_, call_id in rows if call_id is not None]
    latest: dict[uuid.UUID, Evaluations] = {}
    if call_ids:
        evaluations = await session.scalars(
            select(Evaluations)
            .where(Evaluations.call_id.in_(call_ids))
            .order_by(Evaluations.created_at)  # later rows overwrite earlier ones below
        )
        latest = {e.call_id: e for e in evaluations}
    items: list[RunItemOut] = []
    for item, scenario, persona, profile, call_id in rows:
        evaluation = latest.get(call_id) if call_id is not None else None
        items.append(
            RunItemOut(
                id=item.id,
                scenario=scenario,
                persona=persona,
                noise_profile=profile,
                status=cast("Any", item.status),
                call_id=call_id,
                overall_score=(
                    None
                    if evaluation is None or evaluation.overall_score is None
                    else float(evaluation.overall_score)
                ),
                passed=None if evaluation is None else evaluation.passed,
                critical_failure=None if evaluation is None else evaluation.critical_failure,
            )
        )
    return Page(items=items, next_cursor=next_cursor)


async def all_items(
    session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID
) -> list[RunItemOut]:
    """Every matrix row of a run (at most ``MAX_RUN_ITEMS``), for the SSE snapshot and report."""
    items: list[RunItemOut] = []
    cursor: str | None = None
    while True:
        page = await list_items(session, project_id, run_id, PageParams(limit=200, cursor=cursor))
        items.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return items


# --------------------------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------------------------


async def cancel_run(session: AsyncSession, project_id: uuid.UUID, run_id: uuid.UUID) -> RunOut:
    """Cancel a queued or running run: 409 if it already finished.

    Items still ``queued`` become ``cancelled`` (a simulator that later receives their
    ``call.requested`` sees that and skips it). Calls already in flight finish and are evaluated.
    One ``item.status`` progress event per cancelled item and one ``run.completed`` progress
    event go to the outbox in the same transaction, so SSE clients see the cancellation.
    """
    run = (
        await session.scalars(
            select(TestRuns)
            .where(TestRuns.id == run_id, TestRuns.project_id == project_id)
            .with_for_update()
        )
    ).one_or_none()
    if run is None:
        raise ApiError(404, "not_found", "Run not found", {"id": str(run_id)})
    if run.status in FINISHED_RUN_STATUSES:
        raise ApiError(409, "conflict", f"Run is already {run.status}", {"status": run.status})
    cancelled_ids = (
        await session.scalars(
            update(RunItems)
            .where(RunItems.run_id == run_id, RunItems.status == "queued")
            .values(status="cancelled")
            .returning(RunItems.id)
        )
    ).all()
    run.status = "cancelled"
    run.finished_at = datetime.now(UTC)
    correlation = str(run_id)
    for item_id in cancelled_ids:
        enqueue_session(
            session,
            make_envelope(
                ProgressEvent(
                    kind="item.status", run_id=run_id, run_item_id=item_id, status="cancelled"
                ),
                producer=PRODUCER,
                correlation_id=correlation,
            ),
        )
    enqueue_session(
        session,
        make_envelope(
            ProgressEvent(kind="run.completed", run_id=run_id),
            producer=PRODUCER,
            correlation_id=correlation,
        ),
    )
    await session.flush()
    await session.refresh(run)
    return _run_out(run, (await _progress(session, [run]))[run.id])
