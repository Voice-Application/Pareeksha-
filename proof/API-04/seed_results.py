"""Run inside the backend image: write the results of a run's calls as the simulator/evaluator would.

    python seed_results.py <run_id> <score:pass> [<score:pass> ...]

For every run item (in creation order) it inserts a completed call with a transcript, tool call,
metrics, deterministic checks and an evaluation (rows shaped as in docs/schema.sql, the same
columns EVAL-03b's pg_stores write), marks the item `evaluated` and finalises the run row. A
score of `-` leaves that item queued. The `recording_*` paths are written under DATA_DIR by
`capture.sh` (a real WAV per track). Nothing here is read back by the API except through the
database, which is the point: the API answers are checked against these rows.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.events.settings import libpq_url


def main(run_id: uuid.UUID, scores: list[str]) -> None:
    with psycopg.connect(libpq_url(os.environ["DATABASE_URL"]), autocommit=False) as conn:
        project_id, agent_id = conn.execute(
            "SELECT project_id, agent_id FROM test_runs WHERE id = %s", (run_id,)
        ).fetchone()  # type: ignore[misc]
        rubric_id = conn.execute(
            "SELECT id FROM rubric_versions ORDER BY is_active DESC, created_at LIMIT 1"
        ).fetchone()[0]  # type: ignore[index]
        items = conn.execute(
            "SELECT id FROM run_items WHERE run_id = %s ORDER BY created_at, id", (run_id,)
        ).fetchall()
        assert len(items) == len(scores), f"{len(items)} items, {len(scores)} scores given"
        evaluated: list[tuple[float, bool]] = []
        for n, ((item_id,), spec) in enumerate(zip(items, scores, strict=True)):
            if spec == "-":
                continue
            raw_score, raw_pass = spec.split(":")
            score, passed = float(raw_score), raw_pass == "pass"
            critical = score < 50
            call_id = conn.execute(
                """INSERT INTO calls (project_id, agent_id, run_item_id, source, language, status,
                       end_reason, duration_ms, recording_mixed, recording_caller, recording_agent)
                   VALUES (%s,%s,%s,'simulation','kn-IN','completed','goal_achieved',84200,
                           'proof/api04/mixed.wav','proof/api04/caller.wav','proof/api04/agent.wav')
                   RETURNING id""",
                (project_id, agent_id, item_id),
            ).fetchone()[0]  # type: ignore[index]
            conn.execute(
                """INSERT INTO turns (call_id, idx, speaker, text, text_masked, ground_truth_text,
                       agent_heard_text, language_detected, start_ms, end_ms, stt_confidence,
                       is_barge_in) VALUES
                   (%(c)s,0,'agent','Namaskara, nanu Shakti Finance inda','Namaskara',NULL,NULL,
                    'kn-IN',820,5400,0.95,false),
                   (%(c)s,1,'caller','Sir naanu already pay maadidini','Sir naanu already pay',
                    'Sir, naanu already pay maadidini, naal-ku saavira','naalvattu saavira',
                    'kn-IN',6100,9300,0.88,true)""",
                {"c": call_id},
            )
            conn.execute(
                """INSERT INTO tool_calls (call_id, turn_idx, seq, name, arguments, result, at_ms)
                   VALUES (%s,1,0,'record_promise_to_pay',%s,%s,11200)""",
                (call_id, Jsonb({"amount": 40000}), Jsonb({"ok": True})),
            )
            conn.execute(
                """INSERT INTO call_metrics (call_id, first_greeting_ms, response_latency_p50_ms,
                       response_latency_p95_ms, barge_in_attempts, barge_in_honoured,
                       silence_gaps_over_2s, turn_count, caller_asr_wer)
                   VALUES (%s,820,1040,2210,2,0,1,2,0.18)""",
                (call_id,),
            )
            conn.execute(
                """INSERT INTO deterministic_checks (call_id, check_type, check_key, passed,
                       evidence_turns, detail) VALUES
                   (%s,'disclosure_present','recording',%s,'{0,2}','No recording disclosure'),
                   (%s,'no_loop','loop',true,'{}','')""",
                (call_id, passed, call_id),
            )
            conn.execute(
                """INSERT INTO evaluations (call_id, rubric_version_id, judge_model, prompt_hash,
                       dimensions, overall_score, passed, critical_failure, needs_human_review,
                       review_reasons, failure_types, summary, confidence)
                   VALUES (%s,%s,'deepseek-v4-pro','sha256:seeded',%s,%s,%s,%s,%s,%s,%s,%s,'high')""",
                (
                    call_id,
                    rubric_id,
                    Jsonb({"task_completion": {"score": 1, "evidence_turns": [1], "reason": "x"}}),
                    score,
                    passed,
                    critical,
                    critical,
                    ["critical_failure"] if critical else [],
                    [] if passed else ["wrong_fact"],
                    "Seeded evaluation.",
                ),
            )
            conn.execute("UPDATE run_items SET status = 'evaluated' WHERE id = %s", (item_id,))
            evaluated.append((score, passed))
        if evaluated:
            summary = {
                "pass_rate": round(sum(p for _, p in evaluated) / len(evaluated), 4),
                "critical_failures": sum(s < 50 for s, _ in evaluated),
                "needs_review": sum(s < 50 for s, _ in evaluated),
                "score_mean": round(sum(s for s, _ in evaluated) / len(evaluated), 2),
                "latency_p50_ms": 1040,
                "latency_p95_ms": 2210,
                "top_failure_types": [["wrong_fact", sum(not p for _, p in evaluated)]],
                "score_distribution": [
                    sum(min(int(s // 10), 9) == b for s, _ in evaluated) for b in range(10)
                ],
            }
            conn.execute(
                "UPDATE test_runs SET status = 'completed', summary = %s, finished_at = now() "
                "WHERE id = %s AND status NOT IN ('cancelled')",
                (Jsonb(summary), run_id),
            )
        conn.commit()
    print(json.dumps({"run_id": str(run_id), "evaluated": len(evaluated)}))


if __name__ == "__main__":
    main(uuid.UUID(sys.argv[1]), sys.argv[2:])
