"""POST /knowledge-bases/{id}/indexes checks an embedding endpoint typed in the app before the
build is queued: the operator's OLLAMA_BASE_URL is accepted, other private URLs are 422."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import Tenant
from tests.integration.test_knowledge_bases_api import KB, _kb, _upload

pytestmark = pytest.mark.usefixtures("blobs")
OLLAMA = "http://ollama:11434/v1"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", OLLAMA)
    monkeypatch.delenv("AGENT_LLM_ALLOW_PRIVATE_URLS", raising=False)


async def _index(api: AsyncClient, tenant: Tenant, embedding: dict[str, Any]) -> Any:
    kb = await _kb(api, tenant)
    up = await _upload(api, tenant, kb["id"], "faq.txt", b"Late fee is 2 percent.")
    assert up.status_code == 201, up.text
    return await api.post(
        f"{KB}/{kb['id']}/indexes", json={"embedding": embedding}, headers=tenant.admin
    )


async def test_the_configured_ollama_endpoint_is_accepted(api: AsyncClient, tenant: Tenant) -> None:
    """No endpoint (the default) and the configured one both queue a build (202)."""
    for base_url in (None, OLLAMA):
        r = await _index(
            api,
            tenant,
            {"provider": "ollama", "model": "qwen3-embedding:0.6b", "base_url": base_url},
        )
        assert r.status_code == 202, r.text
        assert r.json()["embedding"]["base_url"] == base_url


@pytest.mark.parametrize(
    "base_url",
    ["http://10.0.0.5:8080/v1", "http://ollama:9999/v1", "ftp://embeddings.example.com/v1"],
)
async def test_other_private_or_plain_http_endpoints_are_refused(
    api: AsyncClient, tenant: Tenant, base_url: str
) -> None:
    r = await _index(
        api, tenant, {"provider": "openai_compatible", "model": "m", "base_url": base_url}
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "base_url_not_allowed"
