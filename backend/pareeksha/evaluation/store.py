"""Postgres implementation of the evaluator's storage port (``handlers.EvaluatorStore``).

It runs on the consumer framework's transaction (``ctx.tx``), so the evaluation rows commit
together with the ``processed_events`` row. Uploaded and imported calls (EVAL-04) and simulated
calls share it: the only differences are where the scenario/persona/tool trace come from (a
simulation has them, an upload does not) and which language the language check expects.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.evaluation.evaluator import CallSnapshot, EvaluationRecord
from pareeksha.evaluation.judge import AgentInfo
from pareeksha.evaluation.types import Disclosure, ForbiddenPhrase, ToolCall, Turn
from pareeksha.events.consumer import PermanentError
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

_SCENARIO_COLS = ", ".join(f"s.{name}" for name in ScenarioCreate.model_fields)
_PERSONA_COLS = ", ".join(f"p.{name}" for name in PersonaCreate.model_fields)


def _language_tags(language: str | None) -> list[str]:
    return [t.strip() for t in (language or "").split(",") if t.strip()]


def _llm_provider(model: str) -> str:
    """``api_usage.provider`` for a judge model id (the table only accepts known vendors)."""
    lowered = model.lower()
    return (
        "deepseek"
        if lowered.startswith("deepseek")
        else "gemini"
        if "gemini" in lowered
        else "other"
    )


class PgEvaluatorStore:
    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        self._conn = conn

    async def load_snapshot(self, call_id: uuid.UUID) -> CallSnapshot | None:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT c.id, c.source, c.language, c.agent_id, c.run_item_id, ri.run_id, "
                "ri.scenario_id, ri.persona_id, "
                "a.name AS agent_name, a.description AS agent_description, a.glass_box, "
                "a.mandatory_disclosures, a.forbidden_phrases, a.languages AS agent_languages "
                "FROM calls c LEFT JOIN agents a ON a.id = c.agent_id "
                "LEFT JOIN run_items ri ON ri.id = c.run_item_id WHERE c.id = %s",
                (call_id,),
            )
            call = await cur.fetchone()
            if call is None:
                return None
            await cur.execute(
                "SELECT idx, speaker, start_ms, end_ms, text, text_masked, ground_truth_text, "
                "agent_heard_text, language_detected, is_barge_in FROM turns "
                "WHERE call_id = %s ORDER BY idx",
                (call_id,),
            )
            turns = [Turn(**row) for row in await cur.fetchall()]

            scenario: ScenarioCreate | None = None
            if call["scenario_id"] is not None:
                await cur.execute(
                    f"SELECT {_SCENARIO_COLS} FROM scenarios s WHERE s.id = %s",
                    (call["scenario_id"],),
                )
                row = await cur.fetchone()
                scenario = None if row is None else ScenarioCreate.model_validate(row)
            persona: PersonaCreate | None = None
            if call["persona_id"] is not None:
                await cur.execute(
                    f"SELECT {_PERSONA_COLS} FROM personas p WHERE p.id = %s", (call["persona_id"],)
                )
                row = await cur.fetchone()
                persona = None if row is None else PersonaCreate.model_validate(row)
            tool_calls: list[ToolCall] | None = None
            if call["glass_box"] and call["source"] == "simulation":  # uploads: trace unknown
                await cur.execute(
                    "SELECT name, arguments, turn_idx FROM tool_calls WHERE call_id = %s "
                    "ORDER BY seq",
                    (call_id,),
                )
                tool_calls = [
                    ToolCall(r["name"], dict(r["arguments"] or {}), r["turn_idx"])
                    for r in await cur.fetchall()
                ]

        agent = AgentInfo(
            name=call["agent_name"] or "voice agent",
            description=call["agent_description"] or "",
            mandatory_disclosures=tuple(
                Disclosure.from_dict(d) for d in call["mandatory_disclosures"] or []
            ),
            forbidden_phrases=tuple(
                ForbiddenPhrase.from_dict(d) for d in call["forbidden_phrases"] or []
            ),
        )
        if persona is not None:  # simulation: the persona's language, the agent's languages allowed
            expected_language: str | None = persona.language
            allowed = list(call["agent_languages"] or [])
        else:  # upload / import: the languages the uploader named
            tags = _language_tags(call["language"])
            expected_language = tags[0] if tags else None
            allowed = tags
        amounts = (
            {k: v for k, v in scenario.fixtures.items() if "amount" in k.lower()}
            if scenario
            else None
        )
        return CallSnapshot(
            call_id=call_id,
            agent=agent,
            turns=turns,
            language=call["language"] or "unknown",
            scenario=scenario,
            persona=persona,
            tool_calls=tool_calls,
            expected_language=expected_language,
            allowed_languages=allowed,
            expected_tool_calls=scenario.expected_tool_calls if scenario else None,
            expected_amounts=amounts or None,
            agent_id=call["agent_id"],
            run_id=call["run_id"],
            run_item_id=call["run_item_id"],
        )

    async def save_evaluation(self, record: EvaluationRecord) -> None:
        conn = self._conn
        cur = await conn.execute(
            "SELECT id FROM rubric_versions WHERE version = %s", (record.rubric_version,)
        )
        rubric = await cur.fetchone()
        if rubric is None:
            raise PermanentError(
                f"rubric version {record.rubric_version} is not in rubric_versions (run the seed)"
            )
        await conn.execute(
            "INSERT INTO evaluations (id, call_id, rubric_version_id, status, judge_model, "
            "temperature, prompt_hash, dimensions, overall_score, passed, critical_failure, "
            "needs_human_review, review_reasons, failure_types, summary, confidence, "
            "raw_response, input_tokens, output_tokens, latency_ms) "
            f"VALUES ({', '.join(['%s'] * 20)}) "
            "ON CONFLICT (call_id, rubric_version_id) DO UPDATE SET status = EXCLUDED.status, "
            "judge_model = EXCLUDED.judge_model, temperature = EXCLUDED.temperature, "
            "prompt_hash = EXCLUDED.prompt_hash, dimensions = EXCLUDED.dimensions, "
            "overall_score = EXCLUDED.overall_score, passed = EXCLUDED.passed, "
            "critical_failure = EXCLUDED.critical_failure, "
            "needs_human_review = EXCLUDED.needs_human_review, "
            "review_reasons = EXCLUDED.review_reasons, failure_types = EXCLUDED.failure_types, "
            "summary = EXCLUDED.summary, confidence = EXCLUDED.confidence, "
            "raw_response = EXCLUDED.raw_response, input_tokens = EXCLUDED.input_tokens, "
            "output_tokens = EXCLUDED.output_tokens, latency_ms = EXCLUDED.latency_ms, "
            "created_at = now()",
            (
                record.id,
                record.call_id,
                rubric[0],
                record.status,
                record.judge_model,
                record.temperature,
                record.prompt_hash,
                Jsonb(record.dimensions),
                record.overall_score,
                record.passed,
                record.critical_failure,
                record.needs_human_review,
                record.review_reasons,
                record.failure_types,
                record.summary,
                record.confidence,
                None if record.raw_response is None else Jsonb(record.raw_response),
                record.input_tokens,
                record.output_tokens,
                record.latency_ms,
            ),
        )
        await conn.execute("DELETE FROM deterministic_checks WHERE call_id = %s", (record.call_id,))
        for c in record.checks:
            await conn.execute(
                "INSERT INTO deterministic_checks (call_id, check_type, check_key, must_pass, "
                "passed, evidence_turns, detail) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (call_id, check_type, check_key) DO UPDATE SET "
                "must_pass = EXCLUDED.must_pass, passed = EXCLUDED.passed, "
                "evidence_turns = EXCLUDED.evidence_turns, detail = EXCLUDED.detail",
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
        await self._save_metrics(record)
        if record.input_tokens is not None and record.output_tokens is not None:
            await conn.execute(
                "INSERT INTO api_usage (provider, operation, units, unit_type, est_cost, call_id) "
                "VALUES (%s, 'llm_judge', %s, 'tokens', %s, %s)",
                (
                    _llm_provider(record.judge_model),
                    record.input_tokens + record.output_tokens,
                    record.est_cost,
                    record.call_id,
                ),
            )
        item_status = "evaluated" if record.status == "ok" else "judge_error"
        await conn.execute(
            "UPDATE run_items SET status = %s "
            "WHERE id = (SELECT run_item_id FROM calls WHERE id = %s)",
            (item_status, record.call_id),
        )

    async def _save_metrics(self, record: EvaluationRecord) -> None:
        m = record.metrics
        cur = await self._conn.execute(
            "SELECT c.source, (SELECT count(*) FROM turns t WHERE t.call_id = c.id) "
            "FROM calls c WHERE c.id = %s",
            (record.call_id,),
        )
        source, turn_count = await cur.fetchone() or ("simulation", 0)

        def whole(value: float | None) -> int | None:
            return None if value is None else round(value)

        await self._conn.execute(
            "INSERT INTO call_metrics (call_id, first_greeting_ms, response_latency_p50_ms, "
            "response_latency_p95_ms, barge_in_attempts, barge_in_honoured, "
            "agent_stop_time_p50_ms, "
            "silence_gaps_over_2s, turn_count, agent_talk_ratio, repeated_utterances, "
            "caller_asr_wer, latency_is_approximate, extra) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (call_id) DO UPDATE SET first_greeting_ms = EXCLUDED.first_greeting_ms, "
            "response_latency_p50_ms = EXCLUDED.response_latency_p50_ms, "
            "response_latency_p95_ms = EXCLUDED.response_latency_p95_ms, "
            "barge_in_attempts = EXCLUDED.barge_in_attempts, "
            "barge_in_honoured = EXCLUDED.barge_in_honoured, "
            "agent_stop_time_p50_ms = EXCLUDED.agent_stop_time_p50_ms, "
            "silence_gaps_over_2s = EXCLUDED.silence_gaps_over_2s, "
            "turn_count = EXCLUDED.turn_count, agent_talk_ratio = EXCLUDED.agent_talk_ratio, "
            "repeated_utterances = EXCLUDED.repeated_utterances, "
            "caller_asr_wer = EXCLUDED.caller_asr_wer, "
            "latency_is_approximate = EXCLUDED.latency_is_approximate, "
            "extra = EXCLUDED.extra, computed_at = now()",
            (
                record.call_id,
                m.first_greeting_latency_ms,
                whole(m.response_latency_p50_ms),
                whole(m.response_latency_p95_ms),
                m.barge_in_attempts,
                m.barge_in_honoured,
                whole(m.agent_stop_time_p50_ms),
                m.silence_gaps_over_2s,
                turn_count,
                None if m.agent_talk_ratio is None else round(m.agent_talk_ratio, 3),
                m.repeated_utterances,
                None if m.caller_wer is None else round(m.caller_wer, 4),
                source != "simulation",  # uploads/imports: timings come from STT segments
                Jsonb(m.extra or {}),
            ),
        )
