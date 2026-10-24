"""Interface tests for integrations/base.py (Connector ABC and its validation helper)."""

from __future__ import annotations

import uuid
from typing import ClassVar

import pytest
from pydantic import BaseModel, ValidationError

from pareeksha.events.schemas import AnyEnvelope, CallCompleted, make_envelope
from pareeksha.integrations.base import (
    CONNECTOR_ENTRY_POINT_GROUP,
    AuditRequest,
    Connector,
    ConnectorDirection,
    ConnectorDirectionError,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    DeliveryOutcome,
    EvaluationSummary,
    InboundRequest,
    TestResult,
    validate_connector_class,
)


class DemoConfig(BaseModel):
    only_failed: bool = False


class DemoSecrets(BaseModel):
    token: str


class DemoSink(Connector):
    name: ClassVar[str] = "demosink"
    direction: ClassVar[ConnectorDirection] = "sink"
    config_schema: ClassVar[type[BaseModel]] = DemoConfig
    secrets_schema: ClassVar[type[BaseModel]] = DemoSecrets
    subscribes_to: ClassVar[list[str]] = ["evaluation.completed"]

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        return TestResult(ok=True, detail="authenticated")

    async def handle(
        self, event: AnyEnvelope, config: BaseModel, secrets: BaseModel, ctx: DeliveryCtx
    ) -> DeliveryOutcome:
        return DeliveryOutcome(status="succeeded", http_status=201, external_id="note-1")


class DemoSource(Connector):
    name: ClassVar[str] = "demosource"
    direction: ClassVar[ConnectorDirection] = "source"
    config_schema: ClassVar[type[BaseModel]] = DemoConfig
    secrets_schema: ClassVar[type[BaseModel]] = DemoSecrets
    subscribes_to: ClassVar[list[str]] = []

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        return TestResult(ok=True)

    async def ingest(
        self, request: InboundRequest, config: BaseModel, secrets: BaseModel
    ) -> list[AuditRequest]:
        return [
            AuditRequest(
                recording_url="https://x.example/a.mp3", language="kn-IN", external_id="e1"
            )
        ]


def _summary() -> EvaluationSummary:
    return EvaluationSummary(
        call_id=uuid.uuid4(),
        source="import",
        overall_score=40.0,
        passed=False,
        link="https://pareeksha.example.com/calls/1",
        metadata={"phone": "+91XXXXXXXX00"},
    )


def test_entry_point_group_name() -> None:
    assert CONNECTOR_ENTRY_POINT_GROUP == "pareeksha.connectors"


def test_connector_is_abstract() -> None:
    with pytest.raises(TypeError):
        Connector()  # type: ignore[abstract]

    class NoTest(Connector):
        name: ClassVar[str] = "x"

    with pytest.raises(TypeError, match="test"):
        NoTest()  # type: ignore[abstract]


def test_valid_connectors_pass_validation() -> None:
    assert validate_connector_class(DemoSink) == []
    assert validate_connector_class(DemoSource) == []


def test_validation_reports_each_violation() -> None:
    class Both(DemoSink):
        name: ClassVar[str] = "both"
        direction: ClassVar[ConnectorDirection] = "both"

    assert validate_connector_class(Both) == ["source connectors must override ingest()"]

    class BadName(DemoSink):
        name: ClassVar[str] = "Has Space"

    assert any("name" in p for p in validate_connector_class(BadName))

    class BadDirection(DemoSink):
        direction = "sideways"  # type: ignore[assignment]

    assert any("direction" in p for p in validate_connector_class(BadDirection))

    class BadSchema(DemoSink):
        config_schema = dict  # type: ignore[assignment]

    assert any("config_schema" in p for p in validate_connector_class(BadSchema))

    class SilentSink(DemoSink):
        subscribes_to: ClassVar[list[str]] = []

    assert any("subscribe" in p for p in validate_connector_class(SilentSink))

    class NoHandle(Connector):
        name: ClassVar[str] = "nohandle"
        direction: ClassVar[ConnectorDirection] = "sink"
        config_schema: ClassVar[type[BaseModel]] = DemoConfig
        secrets_schema: ClassVar[type[BaseModel]] = DemoSecrets
        subscribes_to: ClassVar[list[str]] = ["run.completed"]

        async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
            return TestResult(ok=True)

    assert validate_connector_class(NoHandle) == ["sink connectors must override handle()"]
    assert validate_connector_class(object)  # not a Connector at all
    assert validate_connector_class(Connector)  # abstract


async def test_sink_handle_and_default_source_behaviour() -> None:
    sink = DemoSink()
    payload = CallCompleted(call_id=uuid.uuid4(), source="upload")
    event = make_envelope(payload, producer="integrations@h", correlation_id="c")
    ctx = DeliveryCtx(
        integration_id=uuid.uuid4(), delivery_id=uuid.uuid4(), attempt=1, summary=_summary()
    )
    outcome = await sink.handle(event, DemoConfig(), DemoSecrets(token="t"), ctx)
    assert outcome.status == "succeeded" and outcome.external_id == "note-1"
    assert (await sink.test(DemoConfig(), DemoSecrets(token="t"))).ok

    request = InboundRequest(headers={}, body=b"{}", integration_id="i")
    with pytest.raises(ConnectorDirectionError):
        await sink.ingest(request, DemoConfig(), DemoSecrets(token="t"))


async def test_source_ingest_and_default_sink_behaviour() -> None:
    source = DemoSource()
    request = InboundRequest(headers={"x": "y"}, body=b"{}", integration_id="i")
    audits = await source.ingest(request, DemoConfig(), DemoSecrets(token="t"))
    assert audits[0].external_id == "e1" and audits[0].metadata == {}

    payload = CallCompleted(call_id=uuid.uuid4(), source="upload")
    event = make_envelope(payload, producer="p", correlation_id="c")
    ctx = DeliveryCtx(integration_id=uuid.uuid4(), delivery_id=uuid.uuid4(), attempt=1)
    with pytest.raises(ConnectorDirectionError):
        await source.handle(event, DemoConfig(), DemoSecrets(token="t"), ctx)


def test_error_hierarchy() -> None:
    assert issubclass(ConnectorDirectionError, ConnectorPermanentError)
    err = ConnectorRetryableError("429", retry_after_s=12)
    assert err.retry_after_s == 12 and not isinstance(err, ConnectorPermanentError)


def test_models_validate() -> None:
    with pytest.raises(ValidationError):
        AuditRequest(recording_url="u", external_id="e")  # type: ignore[call-arg]  # language missing
    with pytest.raises(ValidationError):
        EvaluationSummary(
            call_id=uuid.uuid4(),
            source="import",
            link="l",
            overall_score=120,
        )
    with pytest.raises(ValidationError):
        DeliveryOutcome(status="exploded")  # type: ignore[arg-type]
    summary = _summary()
    assert "transcript" not in summary.model_dump()  # data minimisation: no transcript field
