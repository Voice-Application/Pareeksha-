"""GET /openapi.json must contain every route of docs/06-api-spec.md."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pareeksha.api.main import app

SPEC = Path(__file__).resolve().parents[3] / "docs" / "06-api-spec.md"
PREFIX = "/api/v1"

# Hand-enumerated from docs/06-api-spec.md (the doc parser below cross-checks it).
# "Standard GET (list/one), PATCH, DELETE exist for all three resources" is expanded in full.
EXPECTED: set[tuple[str, str]] = {
    # 1 agents
    ("POST", "/agents"),
    ("GET", "/agents"),
    ("GET", "/agents/{id}"),
    ("PATCH", "/agents/{id}"),
    ("POST", "/agents/{id}/archive"),
    ("POST", "/agents/{id}/test-connection"),
    # 2 scenarios, personas, noise profiles
    ("POST", "/scenarios"),
    ("GET", "/scenarios"),
    ("GET", "/scenarios/{id}"),
    ("PATCH", "/scenarios/{id}"),
    ("DELETE", "/scenarios/{id}"),
    ("POST", "/scenarios:bulk"),
    ("POST", "/agents/{id}/scenarios:generate"),
    ("GET", "/scenario-drafts/{id}"),
    ("POST", "/personas"),
    ("GET", "/personas"),
    ("GET", "/personas/{id}"),
    ("PATCH", "/personas/{id}"),
    ("DELETE", "/personas/{id}"),
    ("POST", "/personas/{id}/preview"),
    ("POST", "/noise-profiles"),
    ("GET", "/noise-profiles"),
    ("GET", "/noise-profiles/{id}"),
    ("PATCH", "/noise-profiles/{id}"),
    ("DELETE", "/noise-profiles/{id}"),
    ("POST", "/noise-profiles/{id}/preview"),
    # 3 runs
    ("POST", "/runs"),
    ("GET", "/runs/{id}/events"),
    ("POST", "/runs:regression"),
    ("GET", "/runs"),
    ("GET", "/runs/{id}"),
    ("GET", "/runs/{id}/items"),
    ("POST", "/runs/{id}/cancel"),
    ("GET", "/runs/compare"),
    ("GET", "/runs/{id}/report"),
    # 4 calls, evaluations, audits
    ("GET", "/calls/{id}"),
    ("GET", "/calls/{id}/audio/{track}"),
    ("POST", "/calls/{id}/reevaluate"),
    ("POST", "/calls/{id}/review"),
    ("POST", "/calls/{id}/promote"),
    ("POST", "/calls/{id}/speaker-map"),
    ("POST", "/audits"),
    # 5 dialect
    ("POST", "/dialect-datasets"),
    ("POST", "/dialect-datasets/{id}/samples"),
    ("POST", "/dialect-datasets/{id}/evaluate"),
    ("GET", "/dialect-reports/{id}"),
    ("GET", "/dialect-reports/{id}/html"),
    # 6 calibration, system
    ("GET", "/calibration"),
    ("GET", "/usage"),
    ("GET", "/health"),
    ("GET", "/metrics/summary"),
    # 8 integrations and webhooks
    ("GET", "/integrations/connectors"),
    ("POST", "/integrations"),
    ("GET", "/integrations"),
    ("GET", "/integrations/{id}"),
    ("PATCH", "/integrations/{id}"),
    ("DELETE", "/integrations/{id}"),
    ("POST", "/integrations/{id}/test"),
    ("GET", "/integrations/{id}/deliveries"),
    ("POST", "/integrations/{id}/deliveries/{id}/redeliver"),
    ("POST", "/webhooks/inbound/{id}"),
    # 9 dead letters
    ("GET", "/dlq"),
    ("POST", "/dlq/{id}/replay"),
    ("POST", "/dlq/{id}/discard"),
    # 10 API keys
    ("POST", "/api-keys"),
    ("GET", "/api-keys"),
    ("DELETE", "/api-keys/{id}"),
    # 11 event contract
    ("GET", "/events/schemas"),
}

# Added by TL-01 for the API data gaps in docs/design/pages/00-shared.md section 11
# (docs/06-api-spec.md section 12). Each is backed by an FR in docs/02-requirements.md.
ADDITIONS: set[tuple[str, str]] = {
    ("POST", "/runs:estimate"),  # FR-RN-2
    ("GET", "/calls"),  # FR-AU-*, FR-EV-7, FR-EV-8 (Audits, review queue, Calibration)
    ("GET", "/regression-tests"),  # FR-RG-1, FR-RG-2
    ("PATCH", "/regression-tests/{id}"),  # FR-RG-1
    ("GET", "/dialect-datasets"),  # FR-DI-1
    ("GET", "/dialect-reports"),  # FR-DI-4
    ("GET", "/dialect-reports/{id}/clips"),  # FR-DB-4 drill-down to worst clips
}


def _normalise(path: str) -> str:
    """Path parameter names are irrelevant to the contract."""
    return re.sub(r"\{[^}]+\}", "{id}", path)


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    response = TestClient(app).get("/openapi.json")
    assert response.status_code == 200
    document: dict[str, Any] = response.json()
    return document


def _documented(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, item in openapi["paths"].items():
        assert path.startswith(PREFIX), path
        for method in item:
            found.add((method.upper(), _normalise(path[len(PREFIX) :])))
    return found


def test_openapi_document_shape(openapi: dict[str, Any]) -> None:
    assert openapi["openapi"].startswith("3.")
    assert openapi["info"]["title"] == "Pareeksha API"
    assert "ApiKey" in openapi["components"]["securitySchemes"]


def test_every_spec_route_is_in_openapi(openapi: dict[str, Any]) -> None:
    missing = {(m, _normalise(p)) for m, p in EXPECTED} - _documented(openapi)
    assert not missing, f"routes missing from /openapi.json: {sorted(missing)}"


def test_openapi_has_no_undeclared_routes(openapi: dict[str, Any]) -> None:
    extra = _documented(openapi) - {(m, _normalise(p)) for m, p in EXPECTED | ADDITIONS}
    assert not extra, f"routes in /openapi.json but not in the reviewed list: {sorted(extra)}"


def test_additions_are_served(openapi: dict[str, Any]) -> None:
    missing = {(m, _normalise(p)) for m, p in ADDITIONS} - _documented(openapi)
    assert not missing, sorted(missing)


def test_routes_parsed_from_the_spec_document_are_covered(openapi: dict[str, Any]) -> None:
    """Every `METHOD /path` mentioned in docs/06-api-spec.md is served."""
    documented = _documented(openapi)
    mentioned: set[tuple[str, str]] = set()
    pattern = re.compile(r"\b(GET|POST|PATCH|DELETE)\s+(/[A-Za-z0-9_\-/{}:.]+)")
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("**Auth:**") or "the web app's" in line:
            continue
        for method, path in pattern.findall(line):
            path = path.rstrip(".")
            if path.startswith(("/api/v1", "/openapi", "/docs")):
                continue
            mentioned.add((method, _normalise(path)))
    assert len(mentioned) >= 50, "spec parser found suspiciously few routes"
    missing = mentioned - documented
    assert not missing, f"spec mentions routes that are not served: {sorted(missing)}"


def test_operation_ids_are_unique_and_named(openapi: dict[str, Any]) -> None:
    ids = [op["operationId"] for item in openapi["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))
    assert "create_run" in ids and "create_agent" in ids


def test_status_codes_follow_the_spec(openapi: dict[str, Any]) -> None:
    def codes(method: str, path: str) -> set[str]:
        return set(openapi["paths"][PREFIX + path][method.lower()]["responses"])

    assert "201" in codes("POST", "/agents")
    assert "201" in codes("POST", "/runs") and "402" in codes("POST", "/runs")
    assert "201" in codes("POST", "/runs:regression")
    assert "202" in codes("POST", "/runs/{run_id}/cancel")
    assert "202" in codes("POST", "/audits")
    assert "202" in codes("POST", "/agents/{agent_id}/scenarios:generate")
    assert "202" in codes("POST", "/calls/{call_id}/reevaluate")
    assert "201" in codes("POST", "/calls/{call_id}/promote")
    assert "202" in codes("POST", "/dialect-datasets/{dataset_id}/evaluate")
    assert "202" in codes("POST", "/dlq/{dead_letter_id}/replay")
    assert "200" in codes("POST", "/dlq/{dead_letter_id}/discard")
    assert "201" in codes("POST", "/api-keys")
    assert {"202", "401", "408", "422"} <= codes("POST", "/webhooks/inbound/{integration_id}")
    assert "204" in codes("DELETE", "/api-keys/{api_key_id}")


def test_validation_errors_are_400_not_422(openapi: dict[str, Any]) -> None:
    assert "HTTPValidationError" not in openapi["components"]["schemas"]
    op = openapi["paths"][PREFIX + "/agents"]["post"]["responses"]
    assert "400" in op and "422" not in op
    ref = op["400"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorResponse")


def test_security_requirements(openapi: dict[str, Any]) -> None:
    paths = openapi["paths"]
    assert paths[PREFIX + "/runs"]["post"]["security"] == [{"ApiKey": ["runs:write"]}]
    assert paths[PREFIX + "/runs"]["get"]["security"] == [{"ApiKey": ["read"]}]
    assert paths[PREFIX + "/audits"]["post"]["security"] == [{"ApiKey": ["audits:write"]}]
    assert paths[PREFIX + "/api-keys"]["post"]["security"] == [{"ApiKey": ["admin"]}]
    assert "security" not in paths[PREFIX + "/health"]["get"]
    assert "security" not in paths[PREFIX + "/webhooks/inbound/{integration_id}"]["post"]


def test_sse_and_binary_media_types(openapi: dict[str, Any]) -> None:
    paths = openapi["paths"]
    sse = paths[PREFIX + "/runs/{run_id}/events"]["get"]["responses"]["200"]["content"]
    assert "text/event-stream" in sse
    wav = paths[PREFIX + "/calls/{call_id}/audio/{track}"]["get"]["responses"]["200"]["content"]
    assert "audio/wav" in wav
    assert (
        "text/html" in paths[PREFIX + "/runs/{run_id}/report"]["get"]["responses"]["200"]["content"]
    )
    for name in ("SseSnapshot", "SseItemStatus", "SseCallEvaluated", "SseRunCompleted"):
        assert name in openapi["components"]["schemas"]


def test_multipart_endpoints(openapi: dict[str, Any]) -> None:
    audit = openapi["paths"][PREFIX + "/audits"]["post"]["requestBody"]["content"]
    assert "multipart/form-data" in audit
    samples = openapi["paths"][PREFIX + "/dialect-datasets/{dataset_id}/samples"]["post"]
    assert "multipart/form-data" in samples["requestBody"]["content"]


def test_list_endpoints_paginate(openapi: dict[str, Any]) -> None:
    op = openapi["paths"][PREFIX + "/agents"]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert params["limit"]["schema"]["maximum"] == 200
    assert params["limit"]["schema"]["default"] == 50
    assert "cursor" in params
    response_schema = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    page = openapi["components"]["schemas"][response_schema.rsplit("/", 1)[1]]
    assert set(page["properties"]) == {"items", "next_cursor"}


def test_docs_endpoints_exist() -> None:
    client = TestClient(app)
    assert client.get("/docs").status_code == 200
