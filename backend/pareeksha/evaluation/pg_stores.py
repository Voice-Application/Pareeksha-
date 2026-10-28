"""Postgres implementations of ``EvaluatorStore`` / ``FinalizerStore`` (plus the read ports).

Every store wraps the transaction-bound connection the consumer framework passes as ``ctx.tx``:
the evaluation rows, the ``run_items`` status change and the framework's ``processed_events`` row
commit (or roll back) together. That is what makes a redelivered ``call.completed`` produce
exactly one ``evaluations`` row.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.audit.roles import role_review_reasons
from pareeksha.evaluation.evaluator import CallSnapshot, EvaluationRecord
from pareeksha.evaluation.handlers import (
    TERMINAL_ITEM_STATUSES,
    FinishedRun,
    RunItemOutcome,
    RunState,
)
from pareeksha.evaluation.judge import AgentInfo
from pareeksha.evaluation.metrics import CallMetrics
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.evaluation.types import (
    Disclosure,
    ForbiddenPhrase,
    ToolCall,
    Turn,
    as_turn,
)
from pareeksha.events.schemas import (
    EvaluationCompleted,
    RunCompletedSummary,
    RunFinalStatus,
    RunKind,
)
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

Conn = psycopg.AsyncConnection[Any]

#: Run-item states an evaluation result may overwrite. ``cancelled`` / ``error`` /
#: ``skipped_budget`` are final and stay as they are.
_EVALUABLE_ITEM_STATUSES = (
    "queued",
    "connecting",
    "in_progress",
    "completed",
    "evaluating",
    "evaluated",
    "judge_error",
)


class RubricNotFoundError(RuntimeError):
    """``rubric_versions`` has no row for the evaluator's rubric (the seed was not applied)."""


def expected_amounts_from_fixtures(fixtures: Mapping[str, Any]) -> dict[str, Any]:
    """Scenario fixtures that are money amounts (``*_amount`` keys with a numeric value)."""
    return {
        k: v
        for k, v in fixtures.items()
        if k.lower().endswith("amount") and isinstance(v, (int, float)) and not isinstance(v, bool)
    }


class PgEvaluatorStore:
    """``EvaluatorStore`` + ``EvaluationReader`` over one open transaction."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def _rows(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def load_snapshot(self, call_id: uuid.UUID) -> CallSnapshot | None:
        calls = await self._rows(
            """
            SELECT c.id, c.agent_id, c.run_item_id, c.language, c.source, c.event_log,
                   ri.run_id, ri.scenario_id, ri.persona_id,
                   a.name AS agent_name, a.description AS agent_description,
                   a.languages AS agent_languages, a.glass_box,
                   a.mandatory_disclosures, a.forbidden_phrases
              FROM calls c
              LEFT JOIN run_items ri ON ri.id = c.run_item_id
              LEFT JOIN agents a ON a.id = c.agent_id
             WHERE c.id = %s
            """,
            (call_id,),
        )
        if not calls:
            return None
        call = calls[0]

        turn_rows = await self._rows(
            """
            SELECT idx, speaker, start_ms, end_ms, text, text_masked, ground_truth_text,
                   agent_heard_text, language_detected, is_barge_in
              FROM turns WHERE call_id = %s ORDER BY idx
            """,
            (call_id,),
        )
        turns: list[Turn] = [as_turn(r) for r in turn_rows]

        scenario: ScenarioCreate | None = None
        if call["scenario_id"] is not None:
            rows = await self._rows(
                """
                SELECT agent_id, title, caller_goal, fixtures, reveal_rules, success_criteria,
                       must_say, must_not_say, expected_tool_calls, caller_speaks_first,
                       max_turns, tags
                  FROM scenarios WHERE id = %s
                """,
                (call["scenario_id"],),
            )
            if rows:
                scenario = ScenarioCreate.model_validate(rows[0])

        persona: PersonaCreate | None = None
        if call["persona_id"] is not None:
            rows = await self._rows(
                """
                SELECT name, language, code_mix_style, dialect_label, tts_model, voice_id,
                       speed::float AS speed, emotion, patience_turns, interruption_level,
                       silence_habit, behaviour_notes
                  FROM personas WHERE id = %s
                """,
                (call["persona_id"],),
            )
            if rows:
                persona = PersonaCreate.model_validate(rows[0])

        glass_box = bool(call["glass_box"])
        tool_calls: list[ToolCall] | None = None
        # uploads / imports: the tool trace is unknown (None), not "no tools called"
        if glass_box and call["source"] == "simulation":
            tc_rows = await self._rows(
                "SELECT name, arguments, turn_idx FROM tool_calls WHERE call_id = %s ORDER BY seq",
                (call_id,),
            )
            tool_calls = [
                ToolCall(name=r["name"], args=dict(r["arguments"] or {}), turn_idx=r["turn_idx"])
                for r in tc_rows
            ]

        language = call["language"] or (persona.language if persona else None) or "unknown"
        if persona is None and call["source"] != "simulation":
            # upload / import: the languages the uploader named ("hi,en"); the first is expected
            tags = [t.strip() for t in language.split(",") if t.strip()]
            expected_language: str | None = tags[0] if tags else None
            allowed = list(dict.fromkeys(tags))
        else:
            expected_language = None if language == "unknown" else language
            # A simulated caller speaks one language; the agent answering in another language it
            # merely supports (Kannada caller, English reply) is the failure this check exists for.
            allowed = [language]
        agent = AgentInfo(
            name=call["agent_name"] or "unknown agent",
            description=call["agent_description"] or "",
            mandatory_disclosures=[
                Disclosure.from_dict(d) for d in (call["mandatory_disclosures"] or [])
            ],
            forbidden_phrases=[
                ForbiddenPhrase.from_dict(d) for d in (call["forbidden_phrases"] or [])
            ],
        )
        expected_tools = (
            list(scenario.expected_tool_calls)
            if scenario and scenario.expected_tool_calls
            else None
        )
        amounts = expected_amounts_from_fixtures(scenario.fixtures) if scenario else {}
        return CallSnapshot(
            call_id=call_id,
            agent=agent,
            turns=turns,
            language=language,
            scenario=scenario,
            persona=persona,
            tool_calls=tool_calls,
            expected_language=expected_language,
            allowed_languages=allowed,
            expected_tool_calls=expected_tools,
            expected_amounts=amounts or None,
            agent_id=call["agent_id"],
            run_id=call["run_id"],
            run_item_id=call["run_item_id"],
            review_reasons=role_review_reasons(call["event_log"]),
        )

    async def _rubric_id(self, version: str) -> uuid.UUID:
        rows = await self._rows("SELECT id FROM rubric_versions WHERE version = %s", (version,))
        if not rows:
            raise RubricNotFoundError(
                f"rubric_versions has no row for {version!r}; run `python -m pareeksha.seed`"
            )
        return cast(uuid.UUID, rows[0]["id"])

    async def save_evaluation(self, record: EvaluationRecord) -> None:
        rubric_id = await self._rubric_id(record.rubric_version)
        await self._conn.execute(
            """
            INSERT INTO evaluations (
                id, call_id, rubric_version_id, status, judge_model, temperature, prompt_hash,
                dimensions, overall_score, passed, critical_failure, needs_human_review,
                review_reasons, failure_types, summary, confidence, raw_response,
                input_tokens, output_tokens, latency_ms)
            VALUES (%(id)s, %(call_id)s, %(rubric)s, %(status)s, %(model)s, %(temp)s, %(hash)s,
                    %(dims)s, %(score)s, %(passed)s, %(critical)s, %(review)s,
                    %(reasons)s, %(ftypes)s, %(summary)s, %(confidence)s, %(raw)s,
                    %(tin)s, %(tout)s, %(latency)s)
            ON CONFLICT (call_id, rubric_version_id) DO UPDATE SET
                status = EXCLUDED.status, judge_model = EXCLUDED.judge_model,
                temperature = EXCLUDED.temperature, prompt_hash = EXCLUDED.prompt_hash,
                dimensions = EXCLUDED.dimensions, overall_score = EXCLUDED.overall_score,
                passed = EXCLUDED.passed, critical_failure = EXCLUDED.critical_failure,
                needs_human_review = EXCLUDED.needs_human_review,
                review_reasons = EXCLUDED.review_reasons, failure_types = EXCLUDED.failure_types,
                summary = EXCLUDED.summary, confidence = EXCLUDED.confidence,
                raw_response = EXCLUDED.raw_response, input_tokens = EXCLUDED.input_tokens,
                output_tokens = EXCLUDED.output_tokens, latency_ms = EXCLUDED.latency_ms
            """,
            {
                "id": record.id,
                "call_id": record.call_id,
                "rubric": rubric_id,
                "status": record.status,
                "model": record.judge_model,
                "temp": record.temperature,
                "hash": record.prompt_hash,
                "dims": Jsonb(record.dimensions),
                "score": record.overall_score,
                "passed": record.passed,
                "critical": record.critical_failure,
                "review": record.needs_human_review,
                "reasons": record.review_reasons,
                "ftypes": record.failure_types,
                "summary": record.summary,
                "confidence": record.confidence,
                "raw": None if record.raw_response is None else Jsonb(record.raw_response),
                "tin": record.input_tokens,
                "tout": record.output_tokens,
                "latency": record.latency_ms,
            },
        )

        await self._conn.execute(
            "DELETE FROM deterministic_checks WHERE call_id = %s", (record.call_id,)
        )
        for c in record.checks:
            await self._conn.execute(
                """
                INSERT INTO deterministic_checks
                    (call_id, check_type, check_key, must_pass, passed, evidence_turns, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (call_id, check_type, check_key) DO UPDATE SET
                    must_pass = EXCLUDED.must_pass, passed = EXCLUDED.passed,
                    evidence_turns = EXCLUDED.evidence_turns, detail = EXCLUDED.detail
                """,
                (
                    record.call_id,
                    c.check_type,
                    c.check_key,
                    c.must_pass,
                    c.passed,
                    list(c.evidence_turns),
                    c.detail,
                ),
            )

        await self._save_metrics(record.call_id, record.metrics)

        await self._conn.execute(
            """
            UPDATE run_items SET status = %s
             WHERE id = (SELECT run_item_id FROM calls WHERE id = %s)
               AND status = ANY(%s)
            """,
            (
                "evaluated" if record.status == "ok" else "judge_error",
                record.call_id,
                list(_EVALUABLE_ITEM_STATUSES),
            ),
        )

    async def _save_metrics(self, call_id: uuid.UUID, m: CallMetrics) -> None:
        def ms(v: float | None) -> int | None:
            return None if v is None else round(v)

        await self._conn.execute(
            """
            INSERT INTO call_metrics (
                call_id, first_greeting_ms, response_latency_p50_ms, response_latency_p95_ms,
                barge_in_attempts, barge_in_honoured, agent_stop_time_p50_ms,
                silence_gaps_over_2s, turn_count, agent_talk_ratio, repeated_utterances,
                caller_asr_wer, latency_is_approximate, extra)
            SELECT c.id, %(greet)s, %(p50)s, %(p95)s, %(att)s, %(hon)s, %(stop)s, %(gaps)s,
                   (SELECT count(*) FROM turns t WHERE t.call_id = c.id), %(talk)s, %(rep)s,
                   %(wer)s, c.source <> 'simulation', %(extra)s
              FROM calls c WHERE c.id = %(call_id)s
            ON CONFLICT (call_id) DO UPDATE SET
                first_greeting_ms = EXCLUDED.first_greeting_ms,
                response_latency_p50_ms = EXCLUDED.response_latency_p50_ms,
                response_latency_p95_ms = EXCLUDED.response_latency_p95_ms,
                barge_in_attempts = EXCLUDED.barge_in_attempts,
                barge_in_honoured = EXCLUDED.barge_in_honoured,
                agent_stop_time_p50_ms = EXCLUDED.agent_stop_time_p50_ms,
                silence_gaps_over_2s = EXCLUDED.silence_gaps_over_2s,
                turn_count = EXCLUDED.turn_count, agent_talk_ratio = EXCLUDED.agent_talk_ratio,
                repeated_utterances = EXCLUDED.repeated_utterances,
                caller_asr_wer = EXCLUDED.caller_asr_wer,
                latency_is_approximate = EXCLUDED.latency_is_approximate,
                extra = EXCLUDED.extra, computed_at = now()
            """,
            {
                "call_id": call_id,
                "greet": ms(m.first_greeting_latency_ms),
                "p50": ms(m.response_latency_p50_ms),
                "p95": ms(m.response_latency_p95_ms),
                "att": m.barge_in_attempts,
                "hon": m.barge_in_honoured,
                "stop": ms(m.agent_stop_time_p50_ms),
                "gaps": m.silence_gaps_over_2s,
                "talk": m.agent_talk_ratio,
                "rep": m.repeated_utterances,
                "wer": m.caller_wer,
                "extra": Jsonb(m.to_dict()),
            },
        )

    async def load_completed(self, call_id: uuid.UUID) -> EvaluationCompleted | None:
        rows = await self._rows(
            """
            SELECT e.id, e.status, e.overall_score::float AS overall_score, e.passed,
                   e.critical_failure, e.needs_human_review, e.failure_types,
                   c.agent_id, c.run_item_id, ri.run_id
              FROM evaluations e
              JOIN rubric_versions rv ON rv.id = e.rubric_version_id
              JOIN calls c ON c.id = e.call_id
              LEFT JOIN run_items ri ON ri.id = c.run_item_id
             WHERE e.call_id = %s AND rv.version = %s
            """,
            (call_id, RUBRIC_VERSION),
        )
        if not rows:
            return None
        r = rows[0]
        return EvaluationCompleted(
            call_id=call_id,
            evaluation_id=r["id"],
            status=r["status"],
            agent_id=r["agent_id"],
            run_id=r["run_id"],
            run_item_id=r["run_item_id"],
            overall_score=r["overall_score"],
            passed=r["passed"],
            critical_failure=r["critical_failure"],
            needs_human_review=r["needs_human_review"],
            failure_types=list(r["failure_types"]),
        )


class PgFinalizerStore:
    """``FinalizerStore`` + ``RunReader`` over one open transaction."""

    def __init__(self, conn: Conn) -> None:
        self._conn = conn

    async def _rows(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def load_run_state(self, run_id: uuid.UUID) -> RunState | None:
        runs = await self._rows(
            "SELECT id, agent_id, kind, status FROM test_runs WHERE id = %s", (run_id,)
        )
        if not runs:
            return None
        run = runs[0]
        items = await self._rows(
            """
            SELECT ri.status, ev.overall_score::float AS overall_score, ev.passed,
                   COALESCE(ev.critical_failure, false) AS critical_failure,
                   COALESCE(ev.needs_human_review, false) AS needs_human_review,
                   COALESCE(rt.status = 'blocking', true) AS blocking
              FROM run_items ri
              LEFT JOIN regression_tests rt ON rt.id = ri.regression_test_id
              LEFT JOIN calls c ON c.run_item_id = ri.id
              LEFT JOIN LATERAL (
                    SELECT e.overall_score, e.passed, e.critical_failure, e.needs_human_review
                      FROM evaluations e WHERE e.call_id = c.id
                     ORDER BY e.created_at DESC LIMIT 1) ev ON true
             WHERE ri.run_id = %s
             ORDER BY ri.id
            """,
            (run_id,),
        )
        return RunState(
            run_id=run_id,
            agent_id=run["agent_id"],
            kind=cast(RunKind, run["kind"]),
            status=run["status"],
            items=[
                RunItemOutcome(
                    status=i["status"],
                    overall_score=i["overall_score"],
                    passed=i["passed"],
                    critical_failure=i["critical_failure"],
                    needs_human_review=i["needs_human_review"],
                    blocking=i["blocking"],
                )
                for i in items
            ],
        )

    async def claim_run_completion(
        self, run_id: uuid.UUID, status: RunFinalStatus, summary: RunCompletedSummary
    ) -> bool:
        """Atomic: only the first caller finds ``finished_at`` unset and gets a row back.

        A run the API cancelled keeps ``status = 'cancelled'`` (the finalizer never overwrites it);
        only ``summary`` and ``finished_at`` are filled in.
        """
        cur = await self._conn.execute(
            """
            UPDATE test_runs
               SET status = CASE WHEN status = 'cancelled' THEN status ELSE %s END,
                   summary = %s, finished_at = now()
             WHERE id = %s AND finished_at IS NULL
               AND status IN ('queued', 'running', 'cancelled')
            RETURNING id
            """,
            (status, Jsonb(summary.model_dump(mode="json")), run_id),
        )
        return await cur.fetchone() is not None

    async def load_finished_run(self, run_id: uuid.UUID) -> FinishedRun | None:
        rows = await self._rows(
            """
            SELECT agent_id, kind, status, summary FROM test_runs
             WHERE id = %s AND finished_at IS NOT NULL
               AND status IN ('completed', 'partial', 'cancelled', 'failed')
            """,
            (run_id,),
        )
        if not rows:
            return None
        r = rows[0]
        return FinishedRun(
            agent_id=r["agent_id"],
            kind=cast(RunKind, r["kind"]),
            status=cast(RunFinalStatus, r["status"]),
            summary=RunCompletedSummary.model_validate(r["summary"]),
        )


async def mark_evaluating(conn: Conn, call_id: uuid.UUID) -> None:
    """``run_items``: ``completed`` -> ``evaluating`` (only that transition; autocommit connection,
    so the state is visible while the judge runs)."""
    await conn.execute(
        "UPDATE run_items SET status = 'evaluating' "
        "WHERE id = (SELECT run_item_id FROM calls WHERE id = %s) AND status = 'completed'",
        (call_id,),
    )


async def find_completable_runs(conn: Conn) -> list[uuid.UUID]:
    """Unfinished runs whose items are all terminal (their ``run.completed`` is overdue)."""
    cur = await conn.execute(
        """
        SELECT tr.id FROM test_runs tr
         WHERE tr.finished_at IS NULL AND tr.status IN ('queued', 'running', 'cancelled')
           AND EXISTS (SELECT 1 FROM run_items ri WHERE ri.run_id = tr.id)
           AND NOT EXISTS (SELECT 1 FROM run_items ri WHERE ri.run_id = tr.id
                              AND ri.status <> ALL(%s))
         ORDER BY tr.created_at
        """,
        (sorted(TERMINAL_ITEM_STATUSES),),
    )
    return [r[0] for r in await cur.fetchall()]
