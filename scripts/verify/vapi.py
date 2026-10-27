#!/usr/bin/env python3
"""Tiny stdlib client for the verify scripts: runs, polling, SQL through compose.

Env: PAREEKSHA_API_URL (default http://localhost:${API_HOST_PORT:-8000}/api/v1), PAREEKSHA_API_KEY
(or read from .env), COMPOSE (default "docker compose").
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FINAL = {"completed", "partial", "failed", "cancelled"}


def dotenv() -> dict[str, str]:
    out: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                out[k.strip()] = v.split("#")[0].strip()
    return out


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name) or dotenv().get(name, default)


def api_url() -> str:
    port = setting("API_HOST_PORT", "8000")
    return os.environ.get("PAREEKSHA_API_URL") or f"http://localhost:{port}/api/v1"


def request(method: str, path: str, body: Any = None, *, timeout: int = 60) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        api_url() + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {setting('PAREEKSHA_API_KEY')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (operator-set URL)
            text = r.read().decode()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()[:300]}") from exc
    return json.loads(text) if text else None


def items(path: str, **params: Any) -> list[dict[str, Any]]:
    query = "&".join(f"{k}={v}" for k, v in {"limit": 200, **params}.items())
    return request("GET", f"{path}?{query}")["items"]


def compose(*args: str) -> list[str]:
    return [*shlex.split(os.environ.get("COMPOSE", "docker compose")), *args]


def sql(query: str) -> str:
    """Run one query in the compose Postgres, unaligned and tuple-only."""
    out = subprocess.run(
        compose("exec", "-T", "postgres", "psql", "-U", "pareeksha", "-d", "pareeksha", "-At", "-c", query),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def pick(rows: list[dict[str, Any]], key: str, wanted: list[str]) -> list[str]:
    found = {r[key]: r["id"] for r in rows}
    missing = [w for w in wanted if w not in found]
    if missing:
        raise SystemExit(f"not found by {key}: {missing}")
    return [found[w] for w in wanted]


def run_and_wait(
    agent: str,
    scenarios: list[str],
    personas: list[str],
    profiles: list[str],
    *,
    repeats: int = 1,
    concurrency: int = 3,
    name: str,
    poll_s: int = 10,
    timeout_s: int = 3600,
) -> dict[str, Any]:
    """Create a run through POST /runs, wait for it, return {run_id, wall_s, run, items}."""
    ag = next(a for a in items("/agents") if a["name"] == agent)
    body = {
        "agent_id": ag["id"],
        "name": name,
        "scenario_ids": pick(items("/scenarios"), "title", scenarios),
        "persona_ids": pick(items("/personas"), "name", personas),
        "noise_profile_ids": pick(items("/noise-profiles"), "name", profiles),
        "repeats": repeats,
        "config": {"max_concurrency": concurrency},
    }
    t0 = time.time()
    run_id = request("POST", "/runs", body)["id"]
    while True:
        run = request("GET", f"/runs/{run_id}")
        if run["status"] in FINAL:
            break
        if time.time() - t0 > timeout_s:
            raise SystemExit(f"run {run_id} still {run['status']} after {timeout_s}s")
        time.sleep(poll_s)
    return {
        "run_id": run_id,
        "wall_s": round(time.time() - t0, 1),
        "run": run,
        "items": items(f"/runs/{run_id}/items"),
    }


def call(call_id: str) -> dict[str, Any]:
    return request("GET", f"/calls/{call_id}")


if __name__ == "__main__":
    # `vapi.py demo` is what `make demo` runs after the stack is healthy and seeded.
    if sys.argv[1:] == ["demo"]:
        scen = [s["title"] for s in items("/scenarios")][:5]
        pers = [p["name"] for p in items("/personas")][:2]
        prof = [n["name"] for n in items("/noise-profiles")][:1]
        res = run_and_wait("EMI Reminder Bot", scen, pers, prof, repeats=1, concurrency=3, name="demo-10-call")
        done = [i for i in res["items"] if i["status"] == "evaluated"]
        print(json.dumps({"run_id": res["run_id"], "wall_s": res["wall_s"], "evaluated": len(done),
                          "of": len(res["items"]), "summary": res["run"].get("summary")}, indent=1))
        sys.exit(0 if done else 1)
    raise SystemExit(__doc__)
