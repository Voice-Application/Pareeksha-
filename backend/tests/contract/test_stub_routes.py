"""Behaviour of the declared-but-unimplemented routes and the shared error envelope."""

from __future__ import annotations

import inspect
import re
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pareeksha.api.errors import ApiError
from pareeksha.api.main import ROUTERS, app
from pareeksha.api.stubs import not_implemented

client = TestClient(app)
AUTH = {"Authorization": "Bearer pk_live_test"}
ID = str(uuid.uuid4())
API = "/api/v1"
TASK = re.compile(r"# STUB\(([A-Z]+-\d{2})\)")

# Route paths here are relative to the /api/v1 prefix the routers are mounted under.
ROUTES = [r for router in ROUTERS for r in router.routes if isinstance(r, APIRoute)]

SAMPLE_BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/agents"): {
        "name": "EMI Reminder Bot",
        "adapter": "audio_v1",
        "endpoint_url": "ws://mock-agent:8765/ws",
        "languages": ["kn-IN"],
        "glass_box": True,
        "mandatory_disclosures": [{"id": "recording", "text": "recorded", "within_turns": 2}],
    },
    ("PATCH", "/agents/{agent_id}"): {"glass_box": False},
    ("POST", "/scenarios"): {"title": "t", "caller_goal": "g", "success_criteria": "s"},
    ("POST", "/scenarios:bulk"): {
        "scenarios": [{"title": "t", "caller_goal": "g", "success_criteria": "s"}]
    },
    ("PATCH", "/scenarios/{scenario_id}"): {"title": "x"},
    ("POST", "/agents/{agent_id}/scenarios:generate"): {"count": 10, "mix": {"happy_path": 3}},
    ("POST", "/personas"): {"name": "Manju", "language": "kn-IN", "voice_id": "Prakash"},
    ("PATCH", "/personas/{persona_id}"): {"speed": 1.2},
    ("POST", "/noise-profiles"): {
        "name": "pstn_market_5db",
        "sample_rate": 8000,
        "codec": "alaw",
        "background_category": "market_crowd",
        "snr_db": 5,
    },
    ("PATCH", "/noise-profiles/{noise_profile_id}"): {"snr_db": 10},
    ("POST", "/runs"): {
        "agent_id": ID,
        "scenario_ids": [ID],
        "persona_ids": [ID],
        "noise_profile_ids": [ID],
    },
    ("POST", "/runs:regression"): {"agent_id": ID},
    ("POST", "/runs:estimate"): {
        "agent_id": ID,
        "scenario_ids": [ID],
        "persona_ids": [ID],
        "noise_profile_ids": [ID],
    },
    ("PATCH", "/regression-tests/{regression_test_id}"): {"status": "retired"},
    ("POST", "/calls/{call_id}/review"): {"reviewer": "preetham", "passed": False},
    ("POST", "/calls/{call_id}/promote"): {"failure_type": "asr_misrecognition"},
    ("POST", "/calls/{call_id}/speaker-map"): {"spk_0": "caller", "spk_1": "agent"},
    ("POST", "/dialect-datasets"): {"name": "Kannada dialects v1"},
    ("POST", "/dialect-datasets/{dataset_id}/evaluate"): {
        "noise_profile_ids": [ID],
        "engines": ["gnani-prisma"],
    },
    ("POST", "/integrations"): {"connector": "hubspot", "name": "HubSpot"},
    ("PATCH", "/integrations/{integration_id}"): {"enabled": False},
    ("POST", "/api-keys"): {"name": "github-actions", "scopes": ["read", "runs:write"]},
}
SAMPLE_FILES: dict[tuple[str, str], dict[str, Any]] = {
    ("POST", "/audits"): {
        "files": {"file": ("call.wav", b"RIFF....", "audio/wav")},
        "data": {"agent_id": ID, "language": "kn-IN"},
    },
    ("POST", "/dialect-datasets/{dataset_id}/samples"): {
        "files": {
            "manifest": ("manifest.csv", b"file,reference_text\n", "text/csv"),
            "clips": ("clips.zip", b"PK", "application/zip"),
        },
    },
}
QUERY: dict[tuple[str, str], dict[str, str]] = {
    ("GET", "/runs/compare"): {"base": ID, "head": ID},
}
NO_AUTH_501 = {("POST", "/webhooks/inbound/{integration_id}")}


def _method(route: APIRoute) -> str:
    return sorted((route.methods or set()) - {"HEAD", "OPTIONS"})[0]


def _concrete(path: str) -> str:
    path = re.sub(r"\{track\}", "mixed", path)
    return re.sub(r"\{[^}]+\}", ID, path)


def _call(route: APIRoute, *, headers: dict[str, str]) -> Any:
    key = (_method(route), route.path)
    kwargs: dict[str, Any] = {"headers": dict(headers)}
    if key in SAMPLE_BODIES:
        kwargs["json"] = SAMPLE_BODIES[key]
    if key in SAMPLE_FILES:
        kwargs.update(SAMPLE_FILES[key])
    if key in QUERY:
        kwargs["params"] = QUERY[key]
    if key in NO_AUTH_501:
        kwargs["json"] = {
            "external_id": "exotel-CA123",
            "recording_url": "https://x.example/a.mp3",
            "language": "kn-IN",
        }
        kwargs["headers"].update({"X-Pareeksha-Timestamp": "1", "X-Pareeksha-Signature": "v1=00"})
    return client.request(_method(route), _concrete(API + route.path), **kwargs)


def _stub_owner(route: APIRoute) -> str | None:
    match = TASK.search(inspect.getsource(route.endpoint))
    return match.group(1) if match else None


IMPLEMENTED = {("GET", "/health"), ("GET", "/events/schemas")}


def _stub_routes() -> list[APIRoute]:
    return [r for r in ROUTES if (_method(r), r.path) not in IMPLEMENTED]


def test_every_declared_route_is_in_openapi() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    in_openapi = sum(len(item) for item in paths.values())
    assert len(ROUTES) == in_openapi  # the unprefixed /health alias is hidden from the schema


@pytest.mark.parametrize("route", _stub_routes(), ids=lambda r: f"{_method(r)} {r.path}")
def test_stub_route_returns_501_with_owner(route: APIRoute) -> None:
    owner = _stub_owner(route)
    assert owner is not None, "handler is missing its # STUB(<TASK-ID>) marker"
    assert owner != "TL-01"
    key = (_method(route), route.path)
    response = _call(route, headers={} if key in NO_AUTH_501 else AUTH)
    assert response.status_code == 501, response.text
    error = response.json()["error"]
    assert error["code"] == "not_implemented"
    assert error["details"] == {"owner": owner}


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: f"{_method(r)} {r.path}")
def test_no_stub_marker_names_the_contract_task(route: APIRoute) -> None:
    owner = _stub_owner(route)
    assert owner != "TL-01"
    if (_method(route), route.path) in IMPLEMENTED:
        assert owner is None


def test_stub_owner_ids_exist_on_the_task_board() -> None:
    board = (
        __import__("pathlib").Path(__file__).resolve().parents[3] / "docs" / "AGENTS.md"
    ).read_text(encoding="utf-8")
    owners = {_stub_owner(r) for r in _stub_routes()}
    assert owners, "no stubs found"
    for owner in owners:
        assert owner is not None
        assert f"**{owner}**" in board, f"{owner} is not a task in AGENTS.md section 7"


@pytest.mark.parametrize(
    "route",
    [r for r in _stub_routes() if (_method(r), r.path) not in NO_AUTH_501],
    ids=lambda r: f"{_method(r)} {r.path}",
)
def test_authenticated_routes_reject_missing_key(route: APIRoute) -> None:
    response = _call(route, headers={})
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


def test_validation_error_is_400_in_the_standard_envelope() -> None:
    response = client.post(f"{API}/agents", json={"name": ""}, headers=AUTH)
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["errors"]


def test_unknown_fields_are_rejected() -> None:
    response = client.post(
        f"{API}/api-keys", json={"name": "k", "scopes": ["read"], "bogus": 1}, headers=AUTH
    )
    assert response.status_code == 400


def test_invalid_scope_is_rejected() -> None:
    response = client.post(f"{API}/api-keys", json={"name": "k", "scopes": ["root"]}, headers=AUTH)
    assert response.status_code == 400


def test_unknown_route_uses_error_envelope() -> None:
    response = client.get(f"{API}/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_runs_compare_is_not_shadowed_by_run_id() -> None:
    response = client.get(f"{API}/runs/compare", params={"base": ID, "head": ID}, headers=AUTH)
    assert response.status_code == 501
    assert response.json()["error"]["details"]["owner"] == "API-04"


def test_bad_enum_for_audio_track_is_400() -> None:
    response = client.get(f"{API}/calls/{ID}/audio/bogus", headers=AUTH)
    assert response.status_code == 400


def test_not_implemented_helper_validates_owner() -> None:
    with pytest.raises(ApiError) as caught:
        not_implemented("API-02")
    assert caught.value.status_code == 501
    for bad in ("TL-01", "api-02", "oops", ""):
        with pytest.raises(ValueError):
            not_implemented(bad)


def test_health_reports_down_dependencies_with_503() -> None:
    response = client.get(f"{API}/health")  # no auth, no DB or Kafka configured in tests
    assert response.status_code == 503
    body = response.json()
    assert set(body) == {"db", "kafka"}
    assert body["db"].startswith("down") and body["kafka"].startswith("down")
    assert client.get("/health").status_code == 503  # root alias used by Compose


def test_events_schemas_endpoint() -> None:
    assert client.get(f"{API}/events/schemas").status_code == 401
    response = client.get(f"{API}/events/schemas", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 9
    assert "evaluation.completed" in body["events"]
