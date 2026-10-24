"""API-02 left no stub behind and every route it owns is a real handler."""

from __future__ import annotations

from pathlib import Path

from pareeksha.api.main import ROUTERS

PACKAGE = Path(__file__).resolve().parents[2] / "pareeksha"


def test_no_stub_api02_marker_remains_in_the_source() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if "STUB(API-02)" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_crud_resources_expose_the_documented_routes() -> None:
    routes = {
        (method, route.path)  # type: ignore[attr-defined]
        for router in ROUTERS
        for route in router.routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    expected = {
        ("POST", "/agents"),
        ("GET", "/agents"),
        ("GET", "/agents/{agent_id}"),
        ("PATCH", "/agents/{agent_id}"),
        ("POST", "/agents/{agent_id}/archive"),
        ("POST", "/scenarios"),
        ("POST", "/scenarios:bulk"),
        ("DELETE", "/scenarios/{scenario_id}"),
        ("POST", "/personas/{persona_id}/preview"),
        ("POST", "/noise-profiles/{noise_profile_id}/preview"),
        ("DELETE", "/integrations/{integration_id}"),
        ("POST", "/api-keys"),
        ("GET", "/api-keys"),
        ("DELETE", "/api-keys/{api_key_id}"),
    }
    assert expected <= routes
