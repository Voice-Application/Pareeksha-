"""The web BFF's admin route table must match the backend's admin-scoped operations.

The BFF forwards every browser request with the server's admin API key and refuses members only
the routes listed in ``web/lib/admin-routes.json``. A new ``AdminKey`` route missing from that table
would be open to every signed-in member, so the two are compared both ways.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pareeksha.api.main import app

TABLE = Path(__file__).resolve().parents[3] / "web" / "lib" / "admin-routes.json"
PREFIX = "/api/v1"
METHODS = {"get", "post", "put", "patch", "delete"}


def _shape(path: str) -> str:
    """Parameter names do not matter: ``/a/{id}`` and ``/a/{x}`` are the same route."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _admin_operations() -> set[tuple[str, str]]:
    ops: set[tuple[str, str]] = set()
    for path, item in app.openapi()["paths"].items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            scopes = {s for req in op.get("security") or [] for v in req.values() for s in v}
            if "admin" in scopes:
                assert path.startswith(PREFIX), f"admin route outside {PREFIX}: {method} {path}"
                ops.add((method.upper(), _shape(path.removeprefix(PREFIX))))
    return ops


def _web_table() -> set[tuple[str, str]]:
    routes = json.loads(TABLE.read_text())["routes"]
    return {(method, _shape(path)) for method, path in routes}


def test_openapi_has_admin_operations() -> None:
    assert ("POST", "/api-keys") in _admin_operations()


def test_every_admin_route_is_in_web_table() -> None:
    missing = _admin_operations() - _web_table()
    assert not missing, f"add these to web/lib/admin-routes.json: {sorted(missing)}"


def test_web_table_has_no_stale_routes() -> None:
    stale = _web_table() - _admin_operations()
    assert not stale, f"not admin-scoped, remove from web/lib/admin-routes.json: {sorted(stale)}"
