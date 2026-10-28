"""EVAL-04b: an audit with uncertain role detection is stored with ``needs_human_review``."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.audit.pipeline import AuditDeps, Auditor
from pareeksha.events.consumer import PermanentError
from pareeksha.events.schemas import make_envelope
from pareeksha.speech.base import SpeechSelection
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant
from tests.integration.audit_support import (
    FakeSTT,
    audit_envelope,
    create_agent,
    make_auditor,
    role_reply,
    transaction,
    upload,
)
from tests.integration.test_agent_role_swap import KEEP, SWAPPED, evaluation_rows, judged
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json

pytestmark = pytest.mark.usefixtures("rubric")

GOOD_JUDGE = judge_json((4, 4, 4, 4, 4, 4, 4), evidence=[0])


async def audit_and_judge(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    role: str,
) -> dict[str, Any]:
    call_id = (await upload(api, tenant, await create_agent(api, tenant))).json()["call_id"]
    auditor, _, _ = make_auditor(blobs, llm_replies=[role])
    async with transaction(database_url) as ctx:
        (out,) = await auditor.handle(await audit_envelope(database_url, call_id), ctx)
    env = make_envelope(out.payload, producer="auditor", correlation_id=call_id)
    await judged(env, database_url, ScriptedProvider([GOOD_JUDGE]))
    (row,) = await evaluation_rows(database_url, call_id)
    return row


async def test_confident_agreeing_roles_need_no_review(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    row = await audit_and_judge(api, tenant, blobs, database_url, role_reply(KEEP))
    assert row["needs_human_review"] is False and row["review_reasons"] == []


async def test_low_confidence_roles_route_the_audit_to_a_human(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    row = await audit_and_judge(api, tenant, blobs, database_url, role_reply(KEEP, "low"))
    assert row["needs_human_review"] is True
    assert row["review_reasons"] == ["role_detection_low_confidence"]


async def test_heuristic_and_llm_disagreement_routes_the_audit_to_a_human(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    row = await audit_and_judge(api, tenant, blobs, database_url, role_reply(SWAPPED))
    assert row["needs_human_review"] is True
    assert "role_detection_disagreement" in row["review_reasons"]


# ------------------------------------------------------------------ per-agent speech override


class RecordingFactory:
    """``stt_factory`` that records the ``selection`` it was asked for."""

    def __init__(self, stt: FakeSTT) -> None:
        self.stt = stt
        self.selections: list[SpeechSelection | None] = []

    def __call__(self, **kwargs: Any) -> FakeSTT:
        self.selections.append(kwargs.get("selection"))
        return self.stt


async def run_audit(
    api: AsyncClient,
    tenant: Tenant,
    blobs: LocalBlobStore,
    database_url: str,
    factory: RecordingFactory,
    adapter_config: dict[str, object],
) -> None:
    agent_id = await create_agent(api, tenant)
    if adapter_config:
        import psycopg
        from psycopg.types.json import Jsonb

        from pareeksha.events.settings import libpq_url

        async with await psycopg.AsyncConnection.connect(
            libpq_url(database_url), autocommit=True
        ) as conn:
            await conn.execute(
                "UPDATE agents SET adapter_config = %s WHERE id = %s",
                (Jsonb(adapter_config), agent_id),
            )
    call_id = (await upload(api, tenant, agent_id)).json()["call_id"]
    auditor, _, _ = make_auditor(blobs)
    auditor = Auditor(
        AuditDeps(blobs=blobs, stt_factory=factory, llm=None, fetch=auditor.deps.fetch)
    )
    async with transaction(database_url) as ctx:
        await auditor.handle(await audit_envelope(database_url, call_id), ctx)


async def test_agent_speech_override_reaches_the_stt_provider_choice(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    factory = RecordingFactory(FakeSTT())
    await run_audit(api, tenant, blobs, database_url, factory, {"speech": {"stt": "gnani"}})
    (selection,) = factory.selections
    assert selection is not None and selection.stt is not None and selection.stt.value == "gnani"


async def test_agent_without_override_uses_the_environment_default(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    factory = RecordingFactory(FakeSTT())
    await run_audit(api, tenant, blobs, database_url, factory, {})
    assert factory.selections == [None]


async def test_invalid_stored_override_is_a_dead_letter(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, database_url: str
) -> None:
    factory = RecordingFactory(FakeSTT())
    with pytest.raises(PermanentError, match=r"adapter_config\.speech"):
        await run_audit(api, tenant, blobs, database_url, factory, {"speech": {"stt": "nope"}})
    assert factory.selections == []
