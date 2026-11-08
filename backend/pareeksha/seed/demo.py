"""First-run demo data, so a fresh install has something to look at.

* ``data/demo_prompt.yaml``: a tool-calling prompt agent with v1 and a regressed v2, and one
  finished text run per version (so ``/runs/compare`` shows the regression);
* ``data/demo_rag.yaml``: a bilingual knowledge base (``data/demo_kb/``), a RAG prompt agent,
  ground-truth questions and a finished RAG matrix (three retrieval configs plus the no-RAG and
  full-context baselines), so the RAG report is populated.

Every result (transcripts, tool calls, checks, scores, retrievals, RAG metrics, token usage) is
PRECOMPUTED here: nothing calls an LLM, an embedding model or a hosted API. Evaluations carry
``judge_model = DEMO_JUDGE_MODEL`` so they are never mistaken for real judgements.

The knowledge base gets one ``pending`` index plus its ``kb.index.requested`` outbox event: the
indexer worker builds it with the local embedding model, the same as an index a user asks for.
The precomputed retrievals use the same chunker, so their offsets match what the indexer stores.

Each demo block is created whole, once: only when none of its root rows (agent, knowledge base)
exist. Afterwards the seed never touches it, so a user's edits survive a re-seed.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.outbox import enqueue_event
from pareeksha.api.routers.prompt_versions import _activate
from pareeksha.db.models import (
    Agents,
    Calls,
    DeterministicChecks,
    Evaluations,
    KbDocuments,
    KbIndexes,
    KnowledgeBases,
    NoiseProfiles,
    Personas,
    PriceOverrides,
    Projects,
    PromptVersions,
    RagMatrices,
    RagMetrics,
    Retrievals,
    RubricVersions,
    RunItems,
    Scenarios,
    TestRuns,
    ToolCalls,
    Turns,
)
from pareeksha.evaluation.checks import check_no_unexpected_tool, check_tool_calls
from pareeksha.events.schemas import KbIndexRequested, make_envelope
from pareeksha.rag.chunking import Chunk, chunk_document
from pareeksha.rag.matrix import _entries
from pareeksha.rag.metrics import retrieval_metrics
from pareeksha.rag.questions import locate_quote, question_scenario
from pareeksha.rag.retriever import format_context
from pareeksha.schemas.agents import AgentCreate, AgentOut
from pareeksha.schemas.prompts import PromptVersionCreate, content_hash
from pareeksha.schemas.rag import (
    ChunkingConfig,
    EmbeddingConfig,
    RagConfig,
    RagExpectation,
    index_key_for,
)
from pareeksha.schemas.rag_report import RagMatrixCreate
from pareeksha.schemas.runs import RunConfig
from pareeksha.schemas.scenarios import ScenarioCreate

if TYPE_CHECKING:  # runner imports this module
    from pareeksha.seed.runner import SeedResult

DATA_DIR = Path(__file__).parent / "data"
KB_DIR = DATA_DIR / "demo_kb"
DEMO_JUDGE_MODEL = "demo-seed (precomputed)"
#: Gates of rubric-2026-11-v3: any of these failure types fails the call whatever the score.
GATE_FAILURES = frozenset({"missing_disclosure", "intent_miss"})
_NS = uuid.UUID("6f1d3c2e-8a51-4c8e-9a5b-2f0d5e7c9b11")  # stable ids for precomputed chunks


def _load(name: str) -> Any:
    """Parse ``data/<name>``."""
    return yaml.safe_load((DATA_DIR / name).read_text(encoding="utf-8"))


def _jitter(key: str, lo: int, hi: int) -> int:
    """A stable pseudo-random int in ``[lo, hi]`` (same key, same value on every seed run)."""
    h = int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)
    return lo + h % (hi - lo + 1)


def _tokens(text: str) -> int:
    """Rough token count: ~4 Latin characters per token, ~2 for Devanagari and other scripts."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return max(1, ascii_chars // 4 + (len(text) - ascii_chars) // 2)


# --- scoring ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rubric:
    """The rubric version the demo evaluations are scored against."""

    id: uuid.UUID
    prompt_hash: str
    threshold: float
    #: (key, weight) in rubric order
    dims: tuple[tuple[str, int], ...]


async def _rubric(session: AsyncSession, version: str) -> Rubric:
    """The seeded rubric row for ``version``; keys, weights and threshold come from the shipped
    definition (``data/<version>.yaml``), because the seed never rewrites an existing row."""
    row = (
        await session.scalars(select(RubricVersions).where(RubricVersions.version == version))
    ).one()
    spec = _load(f"{version}.yaml")
    dims = tuple((d["key"], int(d["weight"])) for d in spec["dimensions"])
    return Rubric(row.id, row.prompt_hash, float(spec["pass_threshold"]), dims)


@dataclass
class Score:
    """One precomputed judgement: dimension scores (0-4, rubric order) and the verdict inputs."""

    dims: list[int]
    summary: str
    failure_types: list[str] = field(default_factory=list)
    critical: bool = False

    def overall(self, rubric: Rubric) -> float:
        """Weighted score out of 100, as the evaluator computes it."""
        return round(sum(w * s / 4 for (_, w), s in zip(rubric.dims, self.dims, strict=True)), 2)

    def passed(self, rubric: Rubric) -> bool:
        """At or above the threshold, no critical failure and no gate failure type."""
        return (
            self.overall(rubric) >= rubric.threshold
            and not self.critical
            and not GATE_FAILURES & set(self.failure_types)
        )


def _evaluation(call_id: uuid.UUID, rubric: Rubric, score: Score) -> Evaluations:
    """An ``evaluations`` row for ``score``, marked as precomputed (judge model and summary)."""
    return Evaluations(
        call_id=call_id,
        rubric_version_id=rubric.id,
        status="ok",
        judge_model=DEMO_JUDGE_MODEL,
        prompt_hash=rubric.prompt_hash,
        dimensions={
            key: {"score": s, "evidence_turns": [], "reason": ""}
            for (key, _), s in zip(rubric.dims, score.dims, strict=True)
        },
        overall_score=Decimal(str(score.overall(rubric))),
        passed=score.passed(rubric),
        critical_failure=score.critical,
        failure_types=score.failure_types,
        summary=f"{score.summary} (Demo data: precomputed, not judged.)",
        confidence="high",
    )


# --- calls --------------------------------------------------------------------------------------


@dataclass
class CallPlan:
    """Everything one precomputed call needs; :func:`_add_call` turns it into rows."""

    key: str  # jitter seed, unique per call
    run_id: uuid.UUID
    scenario_id: uuid.UUID
    persona_id: uuid.UUID
    profile_id: uuid.UUID
    language: str
    started_at: datetime
    #: ``{"speaker", "text", "tools": [{"name", "args"}]}``; tools only on agent turns
    turns: list[dict[str, Any]]
    tool_results: dict[str, dict[str, Any]]
    system_prompt: str
    model: str
    score: Score
    expected_tool_calls: list[dict[str, Any]] | None = None
    #: per agent turn: extra prompt characters (retrieved or full context)
    context_chars: int = 0
    retrieval: dict[str, Any] | None = None  # a ``retrievals`` row for the first agent turn
    rag_metrics: tuple[dict[str, Any], list[dict[str, str]]] | None = None
    caller_speaks_first: bool = True


async def _add_call(
    session: AsyncSession, project_id: uuid.UUID, agent_id: uuid.UUID, rubric: Rubric, p: CallPlan
) -> None:
    """Write the run item and its evaluated call: turns, tool calls, event log, deterministic
    checks (computed by the real check functions), retrieval, RAG metrics and evaluation.

    Timings follow the text runner: caller turns take no time, an agent turn spans its retrieval,
    tool rounds and reply; each LLM round logs an ``agent_llm_usage`` event.
    """
    item = RunItems(
        id=uuid.uuid4(),
        run_id=p.run_id,
        scenario_id=p.scenario_id,
        persona_id=p.persona_id,
        noise_profile_id=p.profile_id,
        seed=1,
        status="evaluated",
        attempts=1,
    )
    session.add(item)
    call_id = uuid.uuid4()
    events: list[dict[str, Any]] = []
    turns: list[Turns] = []
    tools: list[ToolCalls] = []
    actual: list[dict[str, Any]] = []
    history = len(p.system_prompt) + p.context_chars
    t = 0

    def log(type_: str, **data: Any) -> None:
        events.append({"t_ms": t, "type": type_, "data": data})

    def usage(prompt_chars: int, reply: str, latency: int) -> None:
        """Log one agent LLM round; tool schemas add ~40 prompt tokens each."""
        log(
            "agent_llm_usage",
            input_tokens=prompt_chars // 4 + 40 * len(p.tool_results),
            output_tokens=_tokens(reply) + 8,
            latency_ms=latency,
            model=p.model,
        )

    if not p.caller_speaks_first:
        log("caller_first_text_mode")
    log("call_start", language=p.language, text_mode=True)
    for idx, spec in enumerate(p.turns):
        text = str(spec["text"])
        if spec["speaker"] == "caller":
            t += _jitter(f"{p.key}:{idx}:caller", 300, 900)
            turns.append(_turn(call_id, idx, "caller", text, t, t))
            history += len(text)
            continue
        start = t
        if p.retrieval is not None and idx == p.retrieval["turn_idx"]:
            total = int(p.retrieval["timings"].get("total_ms", 0))
            t += total
            log("retrieval", total_ms=total, n_results=len(p.retrieval["results"]))
        for n, call in enumerate(spec.get("tools") or []):
            latency = _jitter(f"{p.key}:{idx}:tool{n}", 500, 1100)
            t += latency
            usage(history, "", latency)
            result = p.tool_results.get(call["name"], {})
            tools.append(
                ToolCalls(
                    call_id=call_id,
                    seq=len(tools),
                    name=call["name"],
                    arguments=call["args"],
                    at_ms=t,
                    turn_idx=idx,
                    result=result,
                )
            )
            actual.append({"name": call["name"], "args": call["args"], "turn_idx": idx})
            history += 120
        latency = _jitter(f"{p.key}:{idx}:reply", 700, 1500) + p.context_chars // 20
        t += latency
        usage(history, text, latency)
        turns.append(_turn(call_id, idx, "agent", text, start, t))
        history += len(text)
    log("call_end", reason="goal_achieved", error=None)
    session.add(
        Calls(
            id=call_id,
            project_id=project_id,
            source="simulation",
            status="completed",
            agent_id=agent_id,
            run_item_id=item.id,
            language=p.language,
            end_reason="goal_achieved",
            duration_ms=t,
            started_at=p.started_at,
            ended_at=p.started_at + timedelta(milliseconds=t),
            metadata_={
                "run_id": str(p.run_id),
                "scenario_id": str(p.scenario_id),
                "persona_id": str(p.persona_id),
                "noise_profile_id": str(p.profile_id),
                "seed": 1,
                "glass_box": True,
                "demo": True,
            },
            event_log=events,
        )
    )
    await session.flush()  # the call before its children (FKs are not deferred)
    session.add_all([*turns, *tools])
    if p.expected_tool_calls:
        for r in [
            *check_tool_calls(p.expected_tool_calls, actual),
            *check_no_unexpected_tool(p.expected_tool_calls, actual),
        ]:
            session.add(
                DeterministicChecks(
                    call_id=call_id,
                    check_type=r.check_type,
                    check_key=r.check_key,
                    passed=r.passed,
                    must_pass=r.must_pass,
                    evidence_turns=list(r.evidence_turns),
                    detail=r.detail,
                )
            )
    if p.retrieval is not None:
        session.add(Retrievals(call_id=call_id, **p.retrieval))
    if p.rag_metrics is not None:
        metrics, skipped = p.rag_metrics
        session.add(RagMetrics(call_id=call_id, metrics=metrics, skipped=skipped))
    session.add(_evaluation(call_id, rubric, p.score))


def _turn(call_id: uuid.UUID, idx: int, speaker: str, text: str, start: int, end: int) -> Turns:
    """A text-mode turn (no PII in the demo text, so the masked text is the text)."""
    return Turns(
        call_id=call_id,
        idx=idx,
        speaker=speaker,
        text_=text,
        text_masked=text,
        start_ms=start,
        end_ms=end,
        ground_truth_text=text,
    )


def _summary(rubric: Rubric, plans: list[CallPlan]) -> dict[str, Any]:
    """``test_runs.summary`` as the finalizer would leave it for these calls."""
    scores = [p.score.overall(rubric) for p in plans]
    passed = sum(1 for p in plans if p.score.passed(rubric))
    failures: dict[str, int] = {}
    for p in plans:
        for f in p.score.failure_types:
            failures[f] = failures.get(f, 0) + 1
    buckets = [0] * 10
    for s in scores:
        buckets[min(int(s // 10), 9)] += 1
    n = len(plans)
    return {
        "item_count": n,
        "evaluated_count": n,
        "error_count": 0,
        "pass_rate": passed / n if n else None,
        "critical_failures": sum(1 for p in plans if p.score.critical),
        "needs_review": 0,
        "score_mean": round(sum(scores) / n, 2) if n else None,
        "suite_passed": None,
        "score_distribution": buckets,
        "top_failure_types": sorted(failures.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
    }


def _snapshot(agent: Agents, version: PromptVersions) -> dict[str, Any]:
    """The run's ``agent_snapshot``, pinned to ``version`` (what compare reads)."""
    snap = AgentOut.model_validate(agent, from_attributes=True).model_dump(
        mode="json", exclude={"has_adapter_secrets"}
    )
    snap["adapter_config"] = {**snap["adapter_config"], "active_version_id": str(version.id)}
    return snap


@dataclass(frozen=True)
class Grid:
    """The project, rubric, personas and noise profile a demo run is crossed over."""

    project_id: uuid.UUID
    rubric: Rubric
    personas: dict[str, uuid.UUID]
    profile_id: uuid.UUID


async def _grid(
    session: AsyncSession, project: Projects, rubric: Rubric, personas: list[str], profile: str
) -> Grid:
    """Look up the seeded personas (by name, in the given order) and noise profile."""
    found = {
        name: pid
        for name, pid in (
            await session.execute(
                select(Personas.name, Personas.id).where(
                    Personas.project_id == project.id, Personas.name.in_(personas)
                )
            )
        ).all()
    }
    missing = [p for p in personas if p not in found]
    if missing:
        raise ValueError(f"demo personas missing from the seed: {missing}")
    found = {p: found[p] for p in personas}
    profile_id = (
        await session.scalars(
            select(NoiseProfiles.id).where(
                NoiseProfiles.project_id == project.id, NoiseProfiles.name == profile
            )
        )
    ).one()
    return Grid(project.id, rubric, found, profile_id)


async def _prompt_agent(
    session: AsyncSession, project_id: uuid.UUID, spec: dict[str, Any]
) -> Agents:
    """A prompt agent as ``POST /agents`` stores it (endpoint ``prompt://<id>``)."""
    body = AgentCreate.model_validate({**spec, "adapter": "prompt"})
    agent_id = uuid.uuid4()
    row = Agents(
        id=agent_id,
        project_id=project_id,
        **{**body.model_dump(mode="json"), "endpoint_url": f"prompt://{agent_id}"},
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)  # server defaults (created_at, ...) for the run snapshots
    return row


async def _version(
    session: AsyncSession, agent: Agents, number: int, raw: dict[str, Any]
) -> PromptVersions:
    """Store version ``number`` and make it active, as ``POST .../prompt-versions`` does."""
    body = PromptVersionCreate.model_validate(raw)
    row = PromptVersions(
        id=uuid.uuid4(),
        project_id=agent.project_id,
        agent_id=agent.id,
        version=number,
        content_hash=content_hash(body),
        **body.model_dump(mode="json"),
    )
    session.add(row)
    await session.flush()
    _activate(agent, row)
    return row


async def _run(
    session: AsyncSession,
    grid: Grid,
    agent: Agents,
    version: PromptVersions,
    *,
    name: str,
    started_at: datetime,
    scenario_ids: list[uuid.UUID],
    config: dict[str, Any],
) -> TestRuns:
    """A completed run pinned to ``version``; its calls are added by :func:`_finish`."""
    run = TestRuns(
        id=uuid.uuid4(),
        project_id=grid.project_id,
        agent_id=agent.id,
        name=name,
        kind="matrix",
        status="completed",
        config={
            **config,
            "scenario_ids": [str(s) for s in scenario_ids],
            "persona_ids": [str(p) for p in grid.personas.values()],
            "noise_profile_ids": [str(grid.profile_id)],
            "repeats": 1,
            "item_count": len(scenario_ids) * len(grid.personas),
        },
        agent_snapshot=_snapshot(agent, version),
        rubric_version_id=grid.rubric.id,
        created_at=started_at - timedelta(minutes=1),
        started_at=started_at,
    )
    session.add(run)
    await session.flush()
    return run


async def _finish(
    session: AsyncSession, grid: Grid, agent: Agents, run: TestRuns, plans: list[CallPlan]
) -> None:
    """Add the run's calls, then its summary and finish time."""
    for plan in plans:
        await _add_call(session, grid.project_id, agent.id, grid.rubric, plan)
    run.summary = _summary(grid.rubric, plans)
    assert run.started_at is not None
    run.finished_at = run.started_at + timedelta(minutes=3)


async def _exists(session: AsyncSession, model: Any, project_id: uuid.UUID, name: str) -> bool:
    """Whether the project has a ``model`` row with this name (archived rows included)."""
    return (
        await session.scalar(
            select(model.id).where(model.project_id == project_id, model.name == name).limit(1)
        )
    ) is not None


# --- prompt agent: v1 vs v2 ---------------------------------------------------------------------


async def seed_prompt_demo(
    session: AsyncSession, project: Projects, rubric_version: str, out: SeedResult
) -> None:
    """The EMI helpdesk prompt agent, v1 and v2, a scenario set and one finished run each."""
    data = _load("demo_prompt.yaml")
    if await _exists(session, Agents, project.id, data["agent"]["name"]):
        out.count("demo_agents", False)
        return
    rubric = await _rubric(session, rubric_version)
    grid = await _grid(session, project, rubric, data["personas"], data["noise_profile"])
    agent = await _prompt_agent(session, project.id, data["agent"])
    out.count("demo_agents", True)
    tools = data["tools"]
    tool_results = {t["name"]: t["mock"]["result"] for t in tools}
    versions: dict[int, PromptVersions] = {}
    for n, raw in enumerate(data["versions"], start=1):
        versions[n] = await _version(session, agent, n, {**raw, "tools": tools})
        out.count("prompt_versions", True)

    scenarios: list[tuple[uuid.UUID, dict[str, Any]]] = []
    for raw in data["scenarios"]:
        spec = {k: v for k, v in raw.items() if k != "transcripts"}
        body = ScenarioCreate.model_validate(
            {**spec, "agent_id": agent.id, "caller_speaks_first": True, "max_turns": 6}
        )
        row = Scenarios(
            project_id=project.id,
            source="manual",
            **body.model_dump(exclude={"rag_expectation"}),
        )
        session.add(row)
        await session.flush()
        scenarios.append((row.id, raw))
        out.count("demo_scenarios", True)

    now = datetime.now(UTC)
    for spec in data["runs"]:
        version = versions[spec["version"]]
        started = now - timedelta(days=spec["days_ago"])
        run = await _run(
            session,
            grid,
            agent,
            version,
            name=spec["name"],
            started_at=started,
            scenario_ids=[s for s, _ in scenarios],
            config=RunConfig().model_dump(mode="json", exclude_none=True),
        )
        plans: list[CallPlan] = []
        for s_idx, (scenario_id, raw) in enumerate(scenarios):
            script = raw["transcripts"][spec["version"]]
            for p_idx, (persona, persona_id) in enumerate(grid.personas.items()):
                dims = list(script["dims"])
                if p_idx and dims[3] == 4:
                    dims[3] = 3  # the Hindi persona got Hinglish replies
                plans.append(
                    CallPlan(
                        key=f"{spec['name']}:{s_idx}:{persona}",
                        run_id=run.id,
                        scenario_id=scenario_id,
                        persona_id=persona_id,
                        profile_id=grid.profile_id,
                        language="hi-IN" if p_idx else "en-IN",
                        started_at=started + timedelta(seconds=20 * len(plans)),
                        turns=script["turns"],
                        tool_results=tool_results,
                        system_prompt=version.system_prompt,
                        model=version.model,
                        score=Score(
                            dims,
                            script["summary"],
                            list(script.get("failure_types", [])),
                            bool(script.get("critical", False)),
                        ),
                        expected_tool_calls=raw["expected_tool_calls"],
                    )
                )
        await _finish(session, grid, agent, run, plans)
        out.count("demo_runs", True)


# --- RAG: knowledge base, questions, matrix -----------------------------------------------------


@dataclass(frozen=True)
class DocChunk:
    """A chunk as the indexer will cut it, with a stable id for the precomputed results."""

    id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    chunk: Chunk


def _doc_text(name: str) -> str:
    """A demo document with LF line endings (offsets must not depend on the checkout)."""
    return (KB_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _results(
    q_key: str,
    method: str,
    rank: int | None,
    top_k: int,
    chunks: list[DocChunk],
    exp: RagExpectation,
) -> list[dict[str, Any]]:
    """Retrieval results that put the chunk holding the answer at ``rank`` (None = absent)."""

    def holds(c: DocChunk) -> bool:
        """Whether ``c`` overlaps the expected source span (what ``hit_at_k`` tests)."""
        span = exp.source_span
        return (
            span is not None
            and c.document_id == exp.source_document_id
            and c.chunk.start < span[1]
            and span[0] < c.chunk.end
        )

    target = next((c for c in chunks if holds(c)), None)
    others = sorted(
        (c for c in chunks if not holds(c)),
        key=lambda c: hashlib.sha256(f"{q_key}:{method}:{c.id}".encode()).hexdigest(),
    )
    picked = others[: top_k - (1 if rank and target else 0)]
    if rank and target is not None:
        picked.insert(min(rank, len(picked) + 1) - 1, target)
    out = []
    for r, c in enumerate(picked, start=1):
        score = {"bm25": 9.0 - 1.4 * r, "hybrid": 2 / (60 + r), "hybrid_rerank": 0.98 - 0.21 * r}
        out.append(
            {
                "rank": r,
                "chunk_id": str(c.id),
                "document_id": str(c.document_id),
                "filename": c.filename,
                "start_char": c.chunk.start,
                "end_char": c.chunk.end,
                "score": round(score[method], 4),
                "text": c.chunk.text,
            }
        )
    return out


def _timings(key: str, method: str) -> dict[str, int]:
    """Plausible per-stage retrieval latencies (ms) for a local model on a small KB."""
    t = {"rewrite_ms": 0, "search_ms": _jitter(f"{key}:search", 1, 4)}
    if method != "bm25":
        t["embed_ms"] = _jitter(f"{key}:embed", 24, 58)
    if method == "hybrid_rerank":
        t["rerank_ms"] = _jitter(f"{key}:rerank", 110, 260)
    t["total_ms"] = sum(t.values())
    return t


_DIMS = {  # rubric order: task, policy, facts, language, flow, empathy, escalation
    "correct": ([4, 4, 4, 4, 4, 3, 4], [], False, "Answered correctly from the documents."),
    "partial": (
        [3, 4, 2, 4, 4, 3, 4],
        ["hallucination"],
        False,
        "Right answer plus a claim the documents do not support.",
    ),
    "hallucinated": (
        [1, 4, 0, 4, 4, 3, 4],
        ["hallucination", "wrong_fact"],
        True,
        "Stated a fact that is not in the documents.",
    ),
    "refused": (
        [1, 4, 4, 4, 4, 3, 4],
        ["intent_miss"],
        False,
        "Said it had no information although the documents answer the question.",
    ),
    "refused_ok": ([4, 4, 4, 4, 4, 3, 4], [], False, "Correctly said it had no information."),
}


def _generation_metrics(
    mode: str, outcome: str, exp: RagExpectation, has_evidence: bool
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """What ``rag.metrics.compute_rag_metrics`` stores for this judged outcome."""
    metrics: dict[str, Any] = {}
    skipped: list[dict[str, str]] = []
    refused = outcome == "refused"
    if has_evidence:
        total, supported = {"correct": (2, 2), "partial": (3, 2), "hallucinated": (2, 1)}.get(
            outcome, (0, 0)
        )
        metrics.update(
            claims_total=total, claims_supported=supported, hallucinated=supported < total
        )
        if mode in ("retrieval", "full_context"):
            metrics["faithfulness"] = supported / total if total else 1.0
    else:
        skipped += [{"metric": "hallucinated", "reason": "no_evidence"}]
        if mode in ("retrieval", "full_context"):
            skipped += [{"metric": "faithfulness", "reason": "no_evidence"}]
    metrics["refusal_correct"] = refused != exp.answerable
    if exp.reference_answer:
        metrics["answer_correct"] = outcome in ("correct", "partial")
    else:
        skipped.append({"metric": "answer_correct", "reason": "no_ground_truth"})
    return metrics, skipped


async def seed_rag_demo(
    session: AsyncSession, project: Projects, rubric_version: str, out: SeedResult
) -> None:
    """The FAQ knowledge base, its RAG agent, ground-truth questions and a finished matrix."""
    data = _load("demo_rag.yaml")
    kb_spec, agent_spec = data["knowledge_base"], data["agent"]
    kb_found = await _exists(session, KnowledgeBases, project.id, kb_spec["name"])
    agent_found = await _exists(session, Agents, project.id, agent_spec["name"])
    if kb_found or agent_found:
        if kb_found:
            out.count("knowledge_bases", False)
        if agent_found:
            out.count("demo_agents", False)
        return
    rubric = await _rubric(session, rubric_version)
    grid = await _grid(session, project, rubric, [data["persona"]], data["noise_profile"])
    persona_id = next(iter(grid.personas.values()))

    # knowledge base, documents and a pending index for the indexer worker
    kb = KnowledgeBases(
        id=uuid.uuid4(),
        project_id=project.id,
        name=kb_spec["name"],
        description=" ".join(kb_spec["description"].split()),
    )
    session.add(kb)
    await session.flush()
    out.count("knowledge_bases", True)
    docs: dict[str, KbDocuments] = {}
    for name in kb_spec["documents"]:
        text = _doc_text(name)
        digest = hashlib.sha256(text.encode()).hexdigest()
        docs[name] = KbDocuments(
            id=uuid.uuid4(),
            kb_id=kb.id,
            project_id=project.id,
            filename=name,
            mime="text/markdown",
            sha256=digest,
            text=text,
            char_count=len(text),
            blob_key=f"kb/{kb.id}/{digest}",
        )
        session.add(docs[name])
        out.count("kb_documents", True)
    await session.flush()
    chunking, embedding = ChunkingConfig(), EmbeddingConfig()
    index = KbIndexes(
        id=uuid.uuid4(),
        kb_id=kb.id,
        project_id=project.id,
        version=1,
        index_key=index_key_for(chunking, embedding),
        chunking=chunking.model_dump(mode="json"),
        embedding=embedding.model_dump(mode="json"),
        status="pending",
        document_ids=[str(d.id) for d in docs.values()],
    )
    session.add(index)
    await session.flush()
    enqueue_event(
        session,
        make_envelope(
            KbIndexRequested(index_id=index.id, kb_id=kb.id),
            producer="seed",
            correlation_id=str(index.id),
        ),
    )
    out.count("kb_indexes", True)
    chunks = [
        DocChunk(uuid.uuid5(_NS, f"{name}:{i}"), doc.id, name, c)
        for name, doc in docs.items()
        for i, c in enumerate(chunk_document(doc.text, chunking))
    ]

    # the matrix's configs, and the agent whose version uses the first one
    configs = {
        c["key"]: RagConfig(kb_id=kb.id, method=c["method"], top_k=c["top_k"])
        for c in data["configs"]
    }
    agent = await _prompt_agent(
        session, project.id, {k: v for k, v in agent_spec.items() if k != "version"}
    )
    out.count("demo_agents", True)
    first = next(iter(configs.values()))
    version = await _version(
        session, agent, 1, {**agent_spec["version"], "rag_config": first.model_dump(mode="json")}
    )
    out.count("prompt_versions", True)

    # ground-truth questions
    questions: list[tuple[uuid.UUID, dict[str, Any], RagExpectation]] = []
    for q in data["questions"]:
        if q.get("answerable", True):
            doc = docs[q["doc"]]
            span = locate_quote(doc.text, q["quote"])
            if span is None:
                raise ValueError(f"demo quote not found in {q['doc']}: {q['quote']!r}")
            exp = RagExpectation(
                source_document_id=doc.id,
                source_span=span,
                reference_answer=q["reference_answer"],
            )
        else:
            exp = RagExpectation(answerable=False)
        body = question_scenario(agent.id, q["question"], exp.reference_answer, exp)
        row = Scenarios(
            project_id=project.id,
            source="generated",
            **{
                **body.model_dump(exclude={"rag_expectation"}),
                "rag_expectation": exp.model_dump(mode="json"),
            },
        )
        session.add(row)
        await session.flush()
        questions.append((row.id, q, exp))
        out.count("demo_scenarios", True)

    # one finished run per matrix entry
    request = RagMatrixCreate(
        agent_id=agent.id,
        configs=list(configs.values()),
        scenario_ids=[s for s, _, _ in questions],
        persona_ids=[persona_id],
        noise_profile_ids=[grid.profile_id],
        confirm_over_budget=True,
    )
    key_of = {c.method: k for k, c in configs.items()}
    full_chars = sum(d.char_count for d in docs.values())
    started = datetime.now(UTC) - timedelta(hours=3)
    entries: list[dict[str, Any]] = []
    for e_idx, (label, kind, cfg) in enumerate(_entries(request)):
        pins: dict[str, Any] = {}
        if kind == "rag":
            pins = {"rag_index_id": str(index.id)}
        elif kind == "full_context":
            pins = {"rag_full_context_chars": full_chars}
        run_started = started + timedelta(minutes=10 * e_idx)
        run = await _run(
            session,
            grid,
            agent,
            version,
            name=f"RAG · {label}",
            started_at=run_started,
            scenario_ids=[s for s, _, _ in questions],
            config={**RunConfig(rag=cfg).model_dump(mode="json", exclude_none=True), **pins},
        )
        plans = [
            _rag_plan(
                q_idx,
                q,
                exp,
                scenario_id,
                kind=kind,
                key=key_of.get(cfg.method, kind) if kind == "rag" else kind,
                cfg=cfg,
                run=run,
                index_id=index.id,
                chunks=chunks,
                full_chars=full_chars,
                grid=grid,
                persona_id=persona_id,
                version=version,
                refusal=data["refusal"],
                started_at=run_started + timedelta(seconds=12 * q_idx),
                label=label,
            )
            for q_idx, (scenario_id, q, exp) in enumerate(questions)
        ]
        await _finish(session, grid, agent, run, plans)
        out.count("demo_runs", True)
        entries.append(
            {
                "label": label,
                "kind": kind,
                "run_id": str(run.id),
                "status_note": None,
                "rag": cfg.model_dump(mode="json"),
            }
        )
    session.add(
        RagMatrices(
            project_id=project.id,
            agent_id=agent.id,
            prompt_version_id=version.id,
            kb_id=kb.id,
            request=request.model_dump(mode="json"),
            entries=entries,
            created_at=started - timedelta(minutes=1),
        )
    )
    out.count("rag_matrices", True)
    await _seed_price(session, project.id, data["price"], out)


def _rag_plan(
    q_idx: int,
    q: dict[str, Any],
    exp: RagExpectation,
    scenario_id: uuid.UUID,
    *,
    kind: str,
    key: str,
    cfg: RagConfig,
    run: TestRuns,
    index_id: uuid.UUID,
    chunks: list[DocChunk],
    full_chars: int,
    grid: Grid,
    persona_id: uuid.UUID,
    version: PromptVersions,
    refusal: dict[str, str],
    started_at: datetime,
    label: str,
) -> CallPlan:
    """One question asked in one matrix entry, with the outcome ``demo_rag.yaml`` gives it."""
    outcome = q["outcomes"][key]
    reply = {
        "correct": q.get("answer", ""),
        "partial": f"{q.get('answer', '')} {q.get('extra', '')}".strip(),
        "hallucinated": q["wrong"],
        "refused": refusal[q["lang"]],
    }[outcome]
    call_key = f"{run.name}:{q_idx}"
    mode = {"no_rag": "off", "full_context": "full_context"}.get(kind, "retrieval")
    retrieval: dict[str, Any] | None = None
    metrics: dict[str, Any] = {"mode": mode}
    skipped: list[dict[str, str]] = []
    context_chars = 0
    if kind == "rag":
        rank = (q.get("ranks") or {}).get(key)
        results = _results(call_key, cfg.method, rank, cfg.top_k, chunks, exp)
        context_chars = len(format_context([(r["filename"], r["text"]) for r in results]))
        retrieval = {
            "turn_idx": 1,
            "rag_config": cfg.model_dump(mode="json"),
            "index_id": index_id,
            "query": q["question"],
            "queries": [q["question"]],
            "results": results,
            "context_chars": context_chars,
            "timings": _timings(call_key, cfg.method),
            "usage": {"embed_tokens": _tokens(q["question"]) + 2} if cfg.method != "bm25" else {},
        }
        got = retrieval_metrics(results, exp)
        if got is None:
            skipped += [
                {"metric": m, "reason": "no_ground_truth"}
                for m in ("hit_at_k", "reciprocal_rank", "context_precision")
            ]
        else:
            metrics.update(got)
    elif kind == "full_context":
        context_chars = full_chars
        retrieval = {
            "turn_idx": 1,
            "rag_config": cfg.model_dump(mode="json"),
            "index_id": None,
            "query": q["question"],
            "queries": [q["question"]],
            "results": [],
            "context_chars": full_chars,
            "timings": {"total_ms": 0},
            "usage": {},
        }
    # the judge sees the retrieved context (or the KB) plus the expected source text
    has_evidence = kind != "no_rag" or exp.answerable
    gen, gen_skipped = _generation_metrics(mode, outcome, exp, has_evidence)
    metrics.update(gen)
    skipped += gen_skipped
    dims, failures, critical, summary = _DIMS[
        "refused_ok" if outcome == "refused" and not exp.answerable else outcome
    ]
    if outcome == "hallucinated" and not exp.answerable:
        dims = [0, *dims[1:]]
    return CallPlan(
        key=call_key,
        run_id=run.id,
        scenario_id=scenario_id,
        persona_id=persona_id,
        profile_id=grid.profile_id,
        language="hi-IN" if q["lang"] == "hi" else "en-IN",
        started_at=started_at,
        turns=[
            {"speaker": "caller", "text": q["question"]},
            {"speaker": "agent", "text": reply},
        ],
        tool_results={},
        system_prompt=version.system_prompt,
        model=version.model,
        score=Score(list(dims), f"{summary} [{label}]", list(failures), critical),
        context_chars=context_chars,
        retrieval=retrieval,
        rag_metrics=(metrics, skipped),
        caller_speaks_first=False,
    )


async def _seed_price(
    session: AsyncSession, project_id: uuid.UUID, spec: dict[str, Any], out: SeedResult
) -> None:
    """The demo model's price, so the report shows ₹; an existing price is left alone."""
    found = await session.scalar(
        select(PriceOverrides.id).where(
            PriceOverrides.project_id == project_id,
            PriceOverrides.kind == spec["kind"],
            PriceOverrides.provider == spec["provider"],
            PriceOverrides.model == spec["model"],
        )
    )
    if found is None:
        session.add(
            PriceOverrides(
                project_id=project_id,
                kind=spec["kind"],
                provider=spec["provider"],
                model=spec["model"],
                input_per_m_inr=Decimal(str(spec["input_per_m_inr"])),
                output_per_m_inr=Decimal(str(spec["output_per_m_inr"])),
            )
        )
    out.count("price_overrides", found is None)


async def seed_demo(
    session: AsyncSession, project: Projects, rubric_version: str, out: SeedResult
) -> None:
    """Both demo blocks (needs the personas, noise profiles and rubric seeded first)."""
    await seed_prompt_demo(session, project, rubric_version, out)
    await seed_rag_demo(session, project, rubric_version, out)
