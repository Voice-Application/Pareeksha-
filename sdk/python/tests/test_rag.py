from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from pareeksha_sdk import Pareeksha
from pareeksha_sdk.cli import app, report_table
from tests.fake_platform import API_KEY, REPORT, State

runner = CliRunner()


def _cli(*args: str, input: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=input)


@pytest.fixture
def kb_env(logged_in: str, tmp_path: Path) -> Path:
    """An agent with a tagged scenario, a persona and a noise profile, plus a KB called ``Docs``."""
    with Pareeksha(logged_in, API_KEY) as pk:
        agent = pk.agents.create({"name": "Bot", "adapter": "prompt"})
        pk.scenarios.create({"title": "Q1", "agent_id": str(agent.id), "tags": ["rag"]})
        pk.personas.create({"name": "Manju"})
        pk.noise_profiles.create({"name": "quiet"})
        pk.kb.create("Docs")
    cfg = tmp_path / "configs.json"
    cfg.write_text(json.dumps([{"method": "hybrid", "label": "hybrid"}]), encoding="utf-8")
    return cfg


def test_create_upload_and_dedupe(logged_in: str, state: State, tmp_path: Path) -> None:
    doc = tmp_path / "faq.txt"
    doc.write_text("refunds take 5 days", encoding="utf-8")
    assert _cli("kb", "create", "Docs", "--local-only").exit_code == 0
    assert state.kb_bodies[0] == {"name": "Docs", "local_only": True, "description": ""}
    first = _cli("kb", "upload", str(doc), "--kb", "Docs")
    assert first.exit_code == 0 and "uploaded: faq.txt" in first.output
    again = _cli("kb", "upload", str(doc), "--kb", "Docs")
    assert "already there" in again.output and len(state.docs) == 1


def test_keys_come_from_env_and_are_never_printed(
    logged_in: str, state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMB_KEY", "sk-emb-secret")
    monkeypatch.setenv("RR_KEY", "sk-rr-secret")
    result = _cli(
        "kb", "create", "Docs", "--embedding-key-env", "EMB_KEY", "--reranker-key-env", "RR_KEY"
    )
    assert result.exit_code == 0
    assert state.kb_bodies[0]["secrets"] == {
        "embedding_api_key": "sk-emb-secret",
        "reranker_api_key": "sk-rr-secret",
    }
    assert "secret" not in result.output
    missing = _cli("kb", "create", "Other", "--embedding-key-env", "NOT_SET_VAR")
    assert missing.exit_code == 2
    assert "NOT_SET_VAR" in missing.output


def test_plain_key_argument_is_rejected(logged_in: str) -> None:
    assert _cli("kb", "create", "Docs", "--embedding-api-key", "sk-nope").exit_code != 0


def test_set_keys_uses_hidden_prompts(logged_in: str, state: State) -> None:
    _cli("kb", "create", "Docs")
    result = _cli("kb", "set-keys", "--kb", "Docs", input="sk-emb-2\n\n")
    assert result.exit_code == 0
    assert state.kb_bodies[-1] == {"secrets": {"embedding_api_key": "sk-emb-2"}}
    assert "sk-emb-2" not in result.output


def test_index_wait_ready_and_reuse(logged_in: str, state: State) -> None:
    _cli("kb", "create", "Docs")
    ready = _cli("kb", "index", "--kb", "Docs", "--size", "400", "--wait", "--poll", "0.01")
    assert ready.exit_code == 0
    assert "index v1 ready: 12 chunks" in ready.output
    assert state.index_bodies[0] == {
        "chunking": {"strategy": "recursive", "size": 400, "overlap": 100},
        "embedding": {"provider": "local", "model": "intfloat/multilingual-e5-large"},
    }
    state.index_reuse = True
    reused = _cli("kb", "index", "--kb", "Docs", "--wait")
    assert "using existing index v1" in reused.output


def test_index_wait_failed_exits_1(logged_in: str, state: State) -> None:
    _cli("kb", "create", "Docs")
    state.index_final = "failed"
    result = _cli("kb", "index", "--kb", "Docs", "--wait", "--poll", "0.01")
    assert result.exit_code == 1
    assert "embedding endpoint down" in result.output


def test_questions_import(logged_in: str, tmp_path: Path) -> None:
    with Pareeksha(logged_in, API_KEY) as pk:
        pk.agents.create({"name": "Bot", "adapter": "prompt"})
    _cli("kb", "create", "Docs")
    csv = tmp_path / "q.csv"
    csv.write_text("question,expected_answer\nq,a\n", encoding="utf-8")
    result = _cli("kb", "questions", "import", str(csv), "--kb", "Docs", "--agent", "Bot")
    assert result.exit_code == 0
    assert "imported 2 question(s)" in result.output
    assert "row 3: quote_not_found" in result.output


def test_rag_run_creates_matrix_and_waits(kb_env: Path, state: State) -> None:
    result = _cli(
        "rag", "run", "--agent", "Bot", "--kb", "Docs", "--config", str(kb_env), "--wait",
        "--poll", "0.01",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "matrix m-1" in result.output
    body = state.matrix_bodies[0]
    kb_id = next(iter(state.kbs))
    assert body["configs"] == [{"kb_id": kb_id, "method": "hybrid", "label": "hybrid"}]
    assert body["baselines"] == {"no_rag": True, "full_context": True}
    assert len(body["scenario_ids"]) == 1 and len(body["persona_ids"]) == 1


def test_rag_run_no_baselines_and_tag_filter(kb_env: Path, state: State) -> None:
    result = _cli(
        "rag", "run", "--agent", "Bot", "--kb", "Docs", "--config", str(kb_env),
        "--no-baselines", "--tags", "other",
    )  # fmt: skip
    assert result.exit_code == 2  # no scenario carries the "other" tag
    ok = _cli(
        "rag", "run", "--agent", "Bot", "--kb", "Docs", "--config", str(kb_env), "--no-baselines"
    )
    assert ok.exit_code == 0
    assert state.matrix_bodies[0]["baselines"] == {"no_rag": False, "full_context": False}


def test_rag_run_missing_index_exits_2(kb_env: Path, state: State) -> None:
    state.missing_indexes = [{"label": "hybrid", "chunking": {"size": 800}}]
    result = _cli("rag", "run", "--agent", "Bot", "--kb", "Docs", "--config", str(kb_env))
    assert result.exit_code == 2
    assert "missing indexes" in result.output
    assert '"label": "hybrid"' in result.output


def test_rag_report_table_and_json(logged_in: str) -> None:
    table = _cli("rag", "report", "m-1")
    out: str = table.output
    assert table.exit_code == 0
    header, hybrid, no_rag = out.splitlines()[:3]
    for col in ("hit-rate (CI)", "MRR", "faithfulness", "hallucination (CI)", "retr p50/p95 ms"):
        assert col in header
    assert "0.90 [0.75-0.97]" in hybrid and "42/120" in hybrid and "82.5%" in hybrid
    assert no_rag.split()[0] == "no_rag" and "-" in no_rag
    assert out.splitlines()[-1] == (
        "Recommendation: none - not enough ground-truth questions (2 < 10)"
    )
    raw = _cli("rag", "report", "m-1", "--monthly", "500", "--json")
    assert json.loads(raw.output)["monthly_conversations"] == 500


def test_report_table_columns_align() -> None:
    lines = report_table(REPORT).splitlines()
    assert lines[1].index("0.90") == lines[0].index("hit-rate (CI)")


def test_pricing_roundtrip(logged_in: str, state: State) -> None:
    listing = _cli("rag", "pricing")
    assert "UNPRICED llm  p/m" in listing.output
    result = _cli(
        "rag", "set-price", "--kind", "llm", "--provider", "p", "--model", "m",
        "--input-per-m", "10", "--output-per-m", "30",
    )  # fmt: skip
    assert result.exit_code == 0
    assert state.prices == [
        {
            "kind": "llm",
            "provider": "p",
            "model": "m",
            "input_per_m_inr": 10.0,
            "output_per_m_inr": 30.0,
        }
    ]
