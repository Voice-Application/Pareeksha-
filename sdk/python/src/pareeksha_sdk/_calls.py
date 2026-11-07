"""Request builders shared by the sync and async clients (docs/06-api-spec.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter

from pareeksha_sdk.models import (
    Agent,
    Call,
    CallRef,
    DeadLetter,
    Health,
    Named,
    Run,
    RunCreated,
    RunItem,
)


@dataclass
class Call_:
    """One HTTP request plus how to turn the JSON answer into a value."""

    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    data: dict[str, str] | None = None
    file: Path | None = None
    #: marks list endpoints: the client follows ``next_cursor`` and returns all items
    paged: bool = False
    #: PATCH/PUT/GET/DELETE are safe to retry on any 5xx; POST only on gateway errors
    idempotent: bool = True
    #: add ``unchanged`` to the dict answer: True when the server said 200, not 201
    flag_unchanged: bool = False


_NAMED_LIST = TypeAdapter(list[Named])
_AGENT_LIST = TypeAdapter(list[Agent])
_ITEM_LIST = TypeAdapter(list[RunItem])
_DLQ_LIST = TypeAdapter(list[DeadLetter])


def _clean(**params: Any) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


def health() -> Call_:
    return Call_("GET", "/health")


def metrics_summary() -> Call_:
    return Call_("GET", "/metrics/summary")


def agents_list(include_archived: bool = False) -> Call_:
    return Call_("GET", "/agents", _clean(include_archived=include_archived or None), paged=True)


def agent_get(agent_id: UUID | str) -> Call_:
    return Call_("GET", f"/agents/{agent_id}")


def agent_create(body: dict[str, Any]) -> Call_:
    return Call_("POST", "/agents", json=body, idempotent=False)


def agent_update(agent_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_("PATCH", f"/agents/{agent_id}", json=body)


def prompt_version_create(agent_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_(
        "POST",
        f"/agents/{agent_id}/prompt-versions",
        json=body,
        idempotent=False,
        flag_unchanged=True,
    )


def prompt_versions_list(agent_id: UUID | str) -> Call_:
    return Call_("GET", f"/agents/{agent_id}/prompt-versions")


def prompt_version_activate(agent_id: UUID | str, version: int) -> Call_:
    return Call_("POST", f"/agents/{agent_id}/prompt-versions/{version}/activate", idempotent=False)


def kb_create(body: dict[str, Any]) -> Call_:
    return Call_("POST", "/knowledge-bases", json=body, idempotent=False)


def kb_list() -> Call_:
    return Call_("GET", "/knowledge-bases", paged=True)


def kb_update(kb_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_("PATCH", f"/knowledge-bases/{kb_id}", json=body)


def kb_document_upload(kb_id: UUID | str, file: Path) -> Call_:
    return Call_(
        "POST",
        f"/knowledge-bases/{kb_id}/documents",
        file=file,
        idempotent=False,
        flag_unchanged=True,
    )


def kb_documents_list(kb_id: UUID | str) -> Call_:
    return Call_("GET", f"/knowledge-bases/{kb_id}/documents", paged=True)


def kb_document_delete(kb_id: UUID | str, doc_id: UUID | str) -> Call_:
    return Call_("DELETE", f"/knowledge-bases/{kb_id}/documents/{doc_id}")


def kb_index_create(kb_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_(
        "POST",
        f"/knowledge-bases/{kb_id}/indexes",
        json=body,
        idempotent=False,
        flag_unchanged=True,
    )


def kb_indexes_list(kb_id: UUID | str) -> Call_:
    return Call_("GET", f"/knowledge-bases/{kb_id}/indexes", paged=True)


def kb_index_get(kb_id: UUID | str, index_id: UUID | str) -> Call_:
    return Call_("GET", f"/knowledge-bases/{kb_id}/indexes/{index_id}")


def kb_questions_generate(kb_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_(
        "POST", f"/knowledge-bases/{kb_id}/questions:generate", json=body, idempotent=False
    )


def kb_questions_import(kb_id: UUID | str, agent_id: UUID | str, file: Path) -> Call_:
    return Call_(
        "POST",
        f"/knowledge-bases/{kb_id}/questions:import",
        data={"agent_id": str(agent_id)},
        file=file,
        idempotent=False,
    )


def rag_matrix_create(body: dict[str, Any]) -> Call_:
    return Call_("POST", "/rag-matrices", json=body, idempotent=False)


def rag_matrix_get(matrix_id: UUID | str) -> Call_:
    return Call_("GET", f"/rag-matrices/{matrix_id}")


def rag_report(matrix_id: UUID | str, monthly_conversations: int) -> Call_:
    return Call_(
        "GET", f"/rag-matrices/{matrix_id}/report", {"monthly_conversations": monthly_conversations}
    )


def pricing_get() -> Call_:
    return Call_("GET", "/pricing")


def pricing_put(prices: list[dict[str, Any]]) -> Call_:
    return Call_("PUT", "/pricing", json=prices)


def library_list(kind: str, **filters: Any) -> Call_:
    return Call_("GET", f"/{kind}", _clean(**filters), paged=True)


def library_create(kind: str, body: dict[str, Any]) -> Call_:
    return Call_("POST", f"/{kind}", json=body, idempotent=False)


def library_update(kind: str, item_id: UUID | str, body: dict[str, Any]) -> Call_:
    return Call_("PATCH", f"/{kind}/{item_id}", json=body)


def run_create(body: dict[str, Any]) -> Call_:
    return Call_("POST", "/runs", json=body, idempotent=False)


def regression_run_create(body: dict[str, Any]) -> Call_:
    return Call_("POST", "/runs:regression", json=body, idempotent=False)


def run_get(run_id: UUID | str) -> Call_:
    return Call_("GET", f"/runs/{run_id}")


def run_items(run_id: UUID | str) -> Call_:
    return Call_("GET", f"/runs/{run_id}/items", paged=True)


def run_cancel(run_id: UUID | str) -> Call_:
    return Call_("POST", f"/runs/{run_id}/cancel", idempotent=False)


def audit_create(
    file: Path,
    agent_id: UUID | str,
    language: str,
    stereo_channels_are_speakers: bool = False,
) -> Call_:
    return Call_(
        "POST",
        "/audits",
        data={
            "agent_id": str(agent_id),
            "language": language,
            "stereo_channels_are_speakers": str(stereo_channels_are_speakers).lower(),
        },
        file=file,
        idempotent=False,
    )


def call_get(call_id: UUID | str) -> Call_:
    return Call_("GET", f"/calls/{call_id}")


def dlq_list(status: str | None = "open") -> Call_:
    return Call_("GET", "/dlq", _clean(status=status), paged=True)


def dlq_replay(dead_letter_id: UUID | str) -> Call_:
    return Call_("POST", f"/dlq/{dead_letter_id}/replay", idempotent=False)


def dlq_discard(dead_letter_id: UUID | str) -> Call_:
    return Call_("POST", f"/dlq/{dead_letter_id}/discard", idempotent=False)


# --- parsers ---------------------------------------------------------------------------------


def parse_agent(raw: Any) -> Agent:
    return Agent.model_validate(raw)


def parse_agents(raw: Any) -> list[Agent]:
    return _AGENT_LIST.validate_python(raw)


def parse_named(raw: Any) -> Named:
    return Named.model_validate(raw)


def parse_named_list(raw: Any) -> list[Named]:
    return _NAMED_LIST.validate_python(raw)


def parse_run(raw: Any) -> Run:
    return Run.model_validate(raw)


def parse_run_created(raw: Any) -> RunCreated:
    return RunCreated.model_validate(raw)


def parse_items(raw: Any) -> list[RunItem]:
    return _ITEM_LIST.validate_python(raw)


def parse_call(raw: Any) -> Call:
    return Call.model_validate(raw)


def parse_call_ref(raw: Any) -> CallRef:
    return CallRef.model_validate(raw)


def parse_dlq(raw: Any) -> list[DeadLetter]:
    return _DLQ_LIST.validate_python(raw)


def parse_health(raw: Any) -> Health:
    return Health.model_validate(raw)
