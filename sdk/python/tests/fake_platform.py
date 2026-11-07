"""A small in-memory Pareeksha API that speaks the documented wire format (docs/06-api-spec.md).

The real backend routes are still stubs (API-02/03/04), so SDK and CLI tests run against this
server over real HTTP (uvicorn on a free port), not against mocked ``httpx`` internals.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse

API_KEY = "pk_live_test"


class State:
    def __init__(self) -> None:
        self.agents: dict[str, dict[str, Any]] = {}
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.personas: dict[str, dict[str, Any]] = {}
        self.noise_profiles: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.dlq: dict[str, dict[str, Any]] = {}
        self.writes = 0
        self.polls_until_done = 1
        self.pass_rate: float | None = 0.9
        self.suite_passed = True
        self.final_status = "completed"
        self.kafka = "ok"
        self.audit_uploads: list[dict[str, Any]] = []
        self.page_size = 200
        self.prompt_versions: dict[str, list[dict[str, Any]]] = {}
        self.prompt_bodies: list[dict[str, Any]] = []
        self.active_prompt_version: dict[str, int] = {}
        self.prompt_activations: list[tuple[str, int]] = []
        self.designer_requests: list[dict[str, Any]] = []
        self.designer_commits: list[dict[str, Any]] = []
        self.llm_settings: dict[str, Any] = {
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "judge_model": "j",
            "caller_model": "c",
            "designer_model": "j",
            "api_key_set": False,
            "api_key_last4": None,
            "source": "environment",
        }


def build_app(state: State) -> FastAPI:
    """An in-memory FastAPI stand-in for the platform API, reading and recording ``state``."""
    app = FastAPI()

    def auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {API_KEY}":
            raise HTTPException(401, "unauthorized")

    @app.exception_handler(HTTPException)
    async def handle(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "unauthorized" if exc.status_code == 401 else "error",
                    "message": str(exc.detail),
                    "details": {},
                }
            },
            status_code=exc.status_code,
        )

    api = "/api/v1"

    @app.get(api + "/health")
    def health() -> dict[str, str]:
        return {"db": "ok", "kafka": state.kafka}

    @app.get(api + "/metrics/summary", dependencies=[Depends(auth)])
    def metrics() -> dict[str, Any]:
        return {
            "consumer_lag": {},
            "outbox_backlog": 0,
            "dlq_open": len(state.dlq),
            "credits_used": 0.0,
        }

    def page(items: list[dict[str, Any]], limit: int, cursor: str | None) -> dict[str, Any]:
        start = int(cursor or 0)
        size = min(limit, state.page_size)
        chunk = items[start : start + size]
        more = start + size < len(items)
        return {"items": chunk, "next_cursor": str(start + size) if more else None}

    def store_routes(path: str, table: dict[str, dict[str, Any]], name_key: str) -> None:
        @app.get(api + path, dependencies=[Depends(auth)], name=f"list{path}")
        def list_(
            limit: int = 50,
            cursor: str | None = None,
            agent_id: str | None = None,
            tag: str | None = None,
        ) -> dict[str, Any]:
            rows = list(table.values())
            if agent_id:
                rows = [r for r in rows if r.get("agent_id") == agent_id]
            if tag:
                rows = [r for r in rows if tag in r.get("tags", [])]
            return page(rows, limit, cursor)

        @app.post(api + path, status_code=201, dependencies=[Depends(auth)], name=f"create{path}")
        async def create(request: Request) -> dict[str, Any]:
            body = await request.json()
            if any(r[name_key] == body[name_key] for r in table.values()):
                raise HTTPException(409, "duplicate name")
            row = {"id": str(uuid.uuid4()), "archived": False, **body}
            table[row["id"]] = row
            state.writes += 1
            return row

        @app.patch(api + path + "/{item_id}", dependencies=[Depends(auth)], name=f"patch{path}")
        async def patch(item_id: str, request: Request) -> dict[str, Any]:
            if item_id not in table:
                raise HTTPException(404, "not found")
            table[item_id].update(await request.json())
            state.writes += 1
            return table[item_id]

        @app.get(api + path + "/{item_id}", dependencies=[Depends(auth)], name=f"get{path}")
        def get(item_id: str) -> dict[str, Any]:
            if item_id not in table:
                raise HTTPException(404, "not found")
            return table[item_id]

    store_routes("/agents", state.agents, "name")
    store_routes("/scenarios", state.scenarios, "title")
    store_routes("/personas", state.personas, "name")
    store_routes("/noise-profiles", state.noise_profiles, "name")

    def new_run(kind: str, count: int) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        state.runs[run_id] = {"id": run_id, "kind": kind, "polls": 0, "count": count}
        return {"id": run_id, "status": "queued", "item_count": count, "estimate": {}}

    @app.post(api + "/runs", status_code=201, dependencies=[Depends(auth)])
    async def create_run(request: Request) -> dict[str, Any]:
        body = await request.json()
        count = (
            len(body["scenario_ids"]) * len(body["persona_ids"]) * len(body["noise_profile_ids"])
        )
        state.writes += 1
        return new_run(body["kind"], count)

    @app.post(api + "/runs:regression", status_code=201, dependencies=[Depends(auth)])
    async def create_regression(request: Request) -> dict[str, Any]:
        await request.json()
        state.writes += 1
        return new_run("regression", 2)

    @app.get(api + "/runs/{run_id}", dependencies=[Depends(auth)])
    def get_run(run_id: str) -> dict[str, Any]:
        run = state.runs.get(run_id)
        if run is None:
            raise HTTPException(404, "not found")
        run["polls"] += 1
        done = run["polls"] > state.polls_until_done
        total = run["count"]
        return {
            "id": run_id,
            "kind": run["kind"],
            "status": state.final_status if done else "running",
            "progress": {"total": total, "evaluated": total if done else 0, "error": 0},
            "summary": {
                "pass_rate": state.pass_rate if done else None,
                "critical_failures": 0 if state.suite_passed else 1,
                "score_mean": 80.0,
                "top_failure_types": [["asr_misrecognition", 2]] if not state.suite_passed else [],
                "suite_passed": state.suite_passed if run["kind"] == "regression" else None,
            },
        }

    @app.get(api + "/runs/{run_id}/items", dependencies=[Depends(auth)])
    def run_items(run_id: str) -> dict[str, Any]:
        failing = (state.pass_rate is not None and state.pass_rate < 0.5) or not state.suite_passed
        row = {
            "id": str(uuid.uuid4()),
            "scenario": "Already paid",
            "persona": "Manju",
            "noise_profile": "pstn_market_5db",
            "status": "evaluated",
            "overall_score": 40 if failing else 90,
            "passed": not failing,
            "critical_failure": failing,
        }
        return {"items": [row], "next_cursor": None}

    @app.post(api + "/audits", status_code=202, dependencies=[Depends(auth)])
    async def audit(
        file: UploadFile = File(...),  # noqa: B008
        agent_id: str = Form(...),
        language: str = Form(...),
        stereo_channels_are_speakers: bool = Form(False),
    ) -> dict[str, str]:
        call_id = str(uuid.uuid4())
        state.audit_uploads.append(
            {
                "name": file.filename,
                "bytes": len(await file.read()),
                "agent_id": agent_id,
                "language": language,
            }
        )
        state.calls[call_id] = {"id": call_id, "polls": 0}
        return {"call_id": call_id}

    @app.get(api + "/calls/{call_id}", dependencies=[Depends(auth)])
    def get_call(call_id: str) -> dict[str, Any]:
        call = state.calls[call_id]
        call["polls"] += 1
        done = call["polls"] > 1
        return {
            "id": call_id,
            "status": "completed" if done else "transcribing",
            "evaluation": {"overall_score": 72.5} if done else None,
        }

    @app.put(api + "/calls/{call_id}/tool-calls", status_code=202, dependencies=[Depends(auth)])
    def report_tool_calls(call_id: str, body: dict[str, Any]) -> dict[str, Any]:
        state.calls[call_id]["tool_calls"] = body["tool_calls"]
        return {"call_id": call_id}

    @app.post(api + "/designer/chat", dependencies=[Depends(auth)])
    def designer_chat(body: dict[str, Any]) -> dict[str, Any]:
        state.designer_requests.append(body)
        if body.get("draft") is None:
            question = {"id": "endpoint_url", "text": "Where does the bot listen?", "options": []}
            return {"reply": "One question", "questions": [question], "draft": None, "ready": False}
        return {"reply": "Done", "questions": [], "draft": body["draft"], "ready": True}

    @app.post(api + "/designer/commit", status_code=201, dependencies=[Depends(auth)])
    def designer_commit(body: dict[str, Any]) -> dict[str, Any]:
        state.designer_commits.append(body["draft"])
        return {
            "agent_id": str(uuid.uuid4()),
            "scenario_ids": [],
            "persona_ids": [],
            "noise_profile_ids": [],
            "calls": 0,
            "run_wizard_path": "/runs/new?step=review",
        }

    @app.get(api + "/settings/llm", dependencies=[Depends(auth)])
    def get_llm_settings() -> dict[str, Any]:
        return state.llm_settings

    @app.put(api + "/settings/llm", dependencies=[Depends(auth)])
    def put_llm_settings(body: dict[str, Any]) -> dict[str, Any]:
        key = body.pop("api_key", None)
        state.llm_settings = {
            "provider": body["provider"],
            "base_url": body.get("base_url"),
            "judge_model": body.get("judge_model"),
            "caller_model": body.get("caller_model"),
            "designer_model": body.get("designer_model"),
            "api_key_set": key is not None,
            "api_key_last4": key[-4:] if key else None,
            "source": "project",
        }
        return state.llm_settings

    @app.post(api + "/settings/llm/test", dependencies=[Depends(auth)])
    def test_llm_settings() -> dict[str, Any]:
        provider = state.llm_settings["provider"]
        return {"ok": True, "provider": provider, "model": "m", "latency_ms": 12, "error": None}

    @app.get(api + "/dlq", dependencies=[Depends(auth)])
    def dlq(status: str = "open", limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        rows = [d for d in state.dlq.values() if d["status"] == status]
        return page(rows, limit, cursor)

    @app.post(api + "/dlq/{dead_letter_id}/replay", status_code=202, dependencies=[Depends(auth)])
    def replay(dead_letter_id: str) -> dict[str, str]:
        state.dlq[dead_letter_id]["status"] = "replayed"
        return {"status": "replayed"}

    @app.post(api + "/dlq/{dead_letter_id}/discard", dependencies=[Depends(auth)])
    def discard(dead_letter_id: str) -> dict[str, str]:
        state.dlq[dead_letter_id]["status"] = "discarded"
        return {"status": "discarded"}

    @app.post(api + "/agents/{agent_id}/prompt-versions", dependencies=[Depends(auth)])
    async def create_pv(agent_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Create a prompt version, or return the active one when only the note differs."""
        body = await request.json()
        state.prompt_bodies.append(body)
        rows = state.prompt_versions.setdefault(agent_id, [])
        # Like the server's content_hash: every field but the note, with defaults filled in,
        # compared against the active version.
        active = state.active_prompt_version.get(agent_id)
        current = next((r for r in rows if r["version"] == active), None)
        if current is not None and _pv_config(current) == _pv_config(body):
            return current
        row = {**body, "version": len(rows) + 1}
        rows.insert(0, row)
        state.active_prompt_version[agent_id] = row["version"]
        response.status_code = 201
        return row

    @app.get(api + "/agents/{agent_id}/prompt-versions", dependencies=[Depends(auth)])
    def list_pv(agent_id: str) -> list[dict[str, Any]]:
        return state.prompt_versions.get(agent_id, [])

    @app.post(
        api + "/agents/{agent_id}/prompt-versions/{version}/activate",
        dependencies=[Depends(auth)],
    )
    def activate_pv(agent_id: str, version: int) -> dict[str, Any]:
        state.prompt_activations.append((agent_id, version))
        state.active_prompt_version[agent_id] = version
        return {"version": version, "active": True}

    return app


_PV_DEFAULTS: dict[str, Any] = {
    "base_url": None,
    "temperature": 0.2,
    "tools": [],
    "max_tool_rounds": 5,
}


def _pv_config(fields: dict[str, Any]) -> dict[str, Any]:
    """The fields that make a prompt version distinct (the server hashes all but ``note``)."""
    return {**_PV_DEFAULTS, **{k: v for k, v in fields.items() if k not in ("note", "version")}}


def add_dead_letter(state: State) -> str:
    dl_id = str(uuid.uuid4())
    state.dlq[dl_id] = {
        "id": dl_id,
        "event_id": str(uuid.uuid4()),
        "original_topic": "pareeksha.calls.completed",
        "consumer_group": "evaluator",
        "error": "judge timeout",
        "attempts": 3,
        "status": "open",
    }
    return dl_id


@contextmanager
def serve(state: State) -> Iterator[str]:
    """Run the fake API on a free local port; yield its base URL."""
    config = uvicorn.Config(build_app(state), host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        raise RuntimeError("fake platform did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
