"""Seeding and probes for the evaluator / finalizer integration tests (real Postgres schema).

``create_database`` applies ``docs/schema.sql`` (the whole documented schema, as the Alembic
migration does) to a throwaway database on the integration-test server.
"""

from __future__ import annotations

import contextlib
import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.evaluation.rubric import RUBRIC_VERSION
from tests.fixtures import synthetic_calls as sc
from tests.integration.support import SCHEMA_SQL, TEST_DB_URL


def server_url() -> str:
    return TEST_DB_URL.rpartition("/")[0]


@contextlib.contextmanager
def create_database() -> Iterator[str]:
    """A fresh database with the full schema; dropped afterwards. Yields its libpq URL."""
    name = f"eval03b_{secrets.token_hex(4)}"
    with psycopg.connect(f"{server_url()}/postgres", autocommit=True) as admin:
        admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    url = f"{server_url()}/{name}"
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
        yield url
    finally:
        with psycopg.connect(f"{server_url()}/postgres", autocommit=True) as admin:
            admin.execute(
                psycopg.sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )


@dataclass(frozen=True)
class SeededCall:
    call_id: uuid.UUID
    run_id: uuid.UUID
    run_item_id: uuid.UUID
    agent_id: uuid.UUID


def _scalar(conn: psycopg.Connection[Any], sql: str, params: tuple[Any, ...]) -> Any:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def seed_rubric(conn: psycopg.Connection[Any]) -> None:
    conn.execute(
        "INSERT INTO rubric_versions (version, dimensions, pass_threshold, prompt_hash, is_active) "
        "VALUES (%s, %s, 80, 'sha256:test', true) ON CONFLICT DO NOTHING",
        (RUBRIC_VERSION, Jsonb([])),
    )


def seed_run(url: str, n_calls: int, *, kind: str = "matrix") -> list[SeededCall]:
    """A running ``test_run`` with ``n_calls`` run items, each with a finished simulated call
    (the synthetic EMI-reminder conversation, glass-box tool trace included)."""
    clean = sc.clean_call()
    out: list[SeededCall] = []
    with psycopg.connect(url, autocommit=True) as conn:
        seed_rubric(conn)
        project = _scalar(conn, "INSERT INTO projects (name) VALUES ('p') RETURNING id", ())
        agent = _scalar(
            conn,
            """
            INSERT INTO agents (project_id, name, description, endpoint_url, languages, glass_box,
                                mandatory_disclosures, forbidden_phrases)
            VALUES (%s, 'emi-bot', %s, 'ws://agent.invalid', '{hi-IN,en-IN}', true, %s, %s)
            RETURNING id
            """,
            (
                project,
                sc.AGENT.description,
                Jsonb([{"id": "recorded", "text": "This call is recorded", "within_turns": 1}]),
                Jsonb([{"id": "threat", "text": "we will send recovery agents"}]),
            ),
        )
        scenario = _scalar(
            conn,
            """
            INSERT INTO scenarios (project_id, agent_id, title, caller_goal, fixtures,
                                   success_criteria, expected_tool_calls)
            VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                project,
                agent,
                sc.SCENARIO.title,
                sc.SCENARIO.caller_goal,
                Jsonb(sc.SCENARIO.fixtures),
                sc.SCENARIO.success_criteria,
                Jsonb(sc.SCENARIO.expected_tool_calls),
            ),
        )
        persona = _scalar(
            conn,
            "INSERT INTO personas (project_id, name, language, code_mix_style, voice_id) "
            "VALUES (%s, 'Rohit', 'hi-IN', 'heavy', 'Shubham') RETURNING id",
            (project,),
        )
        noise = _scalar(
            conn,
            "INSERT INTO noise_profiles (project_id, name) VALUES (%s, 'clean') RETURNING id",
            (project,),
        )
        run = _scalar(
            conn,
            "INSERT INTO test_runs (project_id, agent_id, kind, status, started_at) "
            "VALUES (%s, %s, %s, 'running', now()) RETURNING id",
            (project, agent, kind),
        )
        for seed in range(n_calls):
            item = _scalar(
                conn,
                "INSERT INTO run_items (run_id, scenario_id, persona_id, noise_profile_id, seed, "
                "status) VALUES (%s, %s, %s, %s, %s, 'completed') RETURNING id",
                (run, scenario, persona, noise, seed),
            )
            call = _scalar(
                conn,
                "INSERT INTO calls (project_id, agent_id, run_item_id, source, language, status, "
                "end_reason, duration_ms, ended_at) "
                "VALUES (%s, %s, %s, 'simulation', 'hi-IN', 'completed', 'goal_achieved', 20000, "
                "now()) RETURNING id",
                (project, agent, item),
            )
            for t in clean.turns:
                conn.execute(
                    "INSERT INTO turns (call_id, idx, speaker, text, text_masked, start_ms, "
                    "end_ms, language_detected) VALUES (%s, %s, %s, %s, %s, %s, %s, 'hi-IN')",
                    (call, t.idx, t.speaker, t.text, t.text_masked, t.start_ms, t.end_ms),
                )
            conn.execute(
                "INSERT INTO tool_calls (call_id, turn_idx, seq, name, arguments, at_ms) "
                "VALUES (%s, 4, 0, 'record_ptp', %s, 9000)",
                (call, Jsonb({"amount": 4200, "date": "Friday"})),
            )
            out.append(SeededCall(call, run, item, agent))
    return out


def count(url: str, sql: str, *params: Any) -> int:
    with psycopg.connect(url, autocommit=True) as conn:
        return int(_scalar(conn, sql, tuple(params)))


def evaluation_count(url: str, call_id: uuid.UUID) -> int:
    return count(url, "SELECT count(*) FROM evaluations WHERE call_id = %s", call_id)


def processed_count(url: str, group: str, event_id: uuid.UUID) -> int:
    return count(
        url,
        "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
        group,
        event_id,
    )
