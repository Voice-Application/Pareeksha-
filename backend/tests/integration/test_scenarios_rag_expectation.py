"""scenarios.rag_expectation round-trips through POST / GET / PATCH /scenarios."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.conftest import Tenant
from tests.integration.test_scenarios_api import SCENARIO


async def test_rag_expectation_round_trips_and_can_be_cleared(
    api: AsyncClient, tenant: Tenant
) -> None:
    expectation = {
        "source_document_id": str(uuid.uuid4()),
        "source_span": [10, 42],
        "reference_answer": "30 days",
        "answerable": True,
    }
    response = await api.post(
        "/api/v1/scenarios", json={**SCENARIO, "rag_expectation": expectation}, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["rag_expectation"] == expectation
    got = await api.get(f"/api/v1/scenarios/{created['id']}", headers=tenant.admin)
    assert got.json()["rag_expectation"] == expectation
    patched = await api.patch(
        f"/api/v1/scenarios/{created['id']}", json={"rag_expectation": None}, headers=tenant.admin
    )
    assert patched.status_code == 200 and patched.json()["rag_expectation"] is None
