"""POST /runs:estimate and RAG matrices count the prompt agent's own model (its price, its
RAG context), real app and Postgres."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from pareeksha.runs.estimate import AGENT_HISTORY_TOKENS_PER_EXCHANGE, AGENT_TOKENS_OUT
from tests.conftest import Tenant
from tests.integration.runs_support import API
from tests.integration.test_rag_matrix_api import Setup, env, setup  # noqa: F401

PROMPT = "Answer using:\n{{context}}"  # the version setup() creates: openai / m, max_turns 2


def _run_body(s: Setup, **config: Any) -> dict[str, Any]:
    return {
        "agent_id": s.agent_id,
        "scenario_ids": [s.scenario_id],
        "persona_ids": [s.persona_id],
        "noise_profile_ids": [s.noise_id],
        "config": config,
    }


async def _estimate(api: AsyncClient, tenant: Tenant, body: dict[str, Any]) -> dict[str, Any]:
    r = await api.post(f"{API}/runs:estimate", json=body, headers=tenant.read)
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()["estimate"]
    return out


async def _price(api: AsyncClient, tenant: Tenant, inp: float, out: float) -> None:
    r = await api.put(
        f"{API}/pricing",
        json=[{"kind": "llm", "provider": "openai", "model": "m",
               "input_per_m_inr": inp, "output_per_m_inr": out}],
        headers=tenant.admin,
    )  # fmt: skip
    assert r.status_code == 200, r.text


def _tokens(context_chars: int, turns: int = 2) -> tuple[int, int]:
    per_round = (len(PROMPT) + context_chars) / 4 + turns * AGENT_HISTORY_TOKENS_PER_EXCHANGE / 2
    return round(turns * per_round), turns * AGENT_TOKENS_OUT


async def test_estimate_prices_the_model_under_test(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url)
    before = await _estimate(api, tenant, _run_body(s))
    tin, tout = _tokens(0)
    assert before["agent_llm_calls"] == 2 and before["agent_llm_tokens"] == tin + tout
    assert before["agent_llm_unpriced"] is True

    await _price(api, tenant, 1000.0, 4000.0)
    after = await _estimate(api, tenant, _run_body(s))
    assert after["agent_llm_unpriced"] is False
    added = round(tin * 1000 / 1e6 + tout * 4000 / 1e6, 2)
    assert round(after["est_cost"] - before["est_cost"], 2) == added


async def test_rag_context_is_part_of_the_estimate(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url, chars=8000)
    retrieval = await _estimate(api, tenant, _run_body(s, rag=s.cfg(top_k=3)))
    full = await _estimate(
        api, tenant, _run_body(s, rag={"mode": "full_context", "kb_id": s.kb_id})
    )
    off = await _estimate(api, tenant, _run_body(s, rag={"mode": "off", "kb_id": s.kb_id}))
    assert retrieval["agent_llm_tokens"] == sum(_tokens(3 * 800))  # top_k x chunk size
    assert full["agent_llm_tokens"] == sum(_tokens(8000))  # the KB's characters
    assert off["agent_llm_tokens"] == sum(_tokens(0))


async def test_other_adapters_report_no_agent_model(api: AsyncClient, tenant: Tenant) -> None:
    from tests.integration.runs_support import make_fixture

    fx = await make_fixture(api, tenant, 1, 1, 1)  # an audio_v1 agent
    est = await _estimate(api, tenant, fx.body())
    assert (est["agent_llm_calls"], est["agent_llm_tokens"], est["agent_llm_unpriced"]) == (
        0,
        0,
        False,
    )
