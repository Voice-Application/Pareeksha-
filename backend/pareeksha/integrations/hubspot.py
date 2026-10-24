"""HubSpot connector, sink side (docs/10 section 2.2): one call-audit note on the matching contact.

Flow: contact id from ``metadata.crm_contact_id`` or a CRM v3 contact search by phone/email, then
``POST /crm/v3/objects/notes`` associated to the contact (HUBSPOT_DEFINED type 202: note-contact).
No match is ``skipped``, not an error. Idempotency: the framework claims the delivery row before
``handle`` (delivery.py), so a redelivered event returns the stored note id without calling HubSpot;
the event id is also written into the note footer so a note can be traced back to its event.

API docs: https://developers.hubspot.com/docs/api-reference/crm-notes-v3/guide
Scopes: crm.objects.contacts.read and crm.objects.contacts.write (notes attach to contacts).
"""

from __future__ import annotations

import re
from datetime import UTC
from typing import Any, ClassVar, Literal

import httpx
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel, Field

from pareeksha.events.schemas import AnyEnvelope
from pareeksha.integrations.base import (
    Connector,
    ConnectorDirection,
    ConnectorError,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    DeliveryOutcome,
    EvaluationSummary,
    TestResult,
)

HUBSPOT_API = "https://api.hubapi.com"
NOTE_TO_CONTACT = 202  # HUBSPOT_DEFINED association type id, note -> contact

DEFAULT_NOTE_TEMPLATE = (
    "Pareeksha call audit - {{ verdict }} ({{ score }}/100){% if critical %} CRITICAL{% endif %}\n"
    "Agent: {{ agent }} - {{ language }} - {{ duration }}\n"
    "Issues: {{ issues }}\n"
    "Summary: {{ summary }}\n"
    "Details: {{ link }}"
)

_env = SandboxedEnvironment(autoescape=False)


class HubSpotConfig(BaseModel):
    match_by: Literal["phone", "email", "contact_id"] = "phone"
    only_failed: bool = False
    note_template: str = DEFAULT_NOTE_TEMPLATE
    public_base_url: str | None = None
    timeout_s: float = Field(default=10.0, gt=0, le=60)


class HubSpotSecrets(BaseModel):
    private_app_token: str = Field(min_length=8)


class HubSpotConnector(Connector):
    name: ClassVar[str] = "hubspot"
    direction: ClassVar[ConnectorDirection] = "sink"
    config_schema: ClassVar[type[BaseModel]] = HubSpotConfig
    secrets_schema: ClassVar[type[BaseModel]] = HubSpotSecrets
    subscribes_to: ClassVar[list[str]] = ["evaluation.completed"]

    def __init__(
        self, *, transport: httpx.AsyncBaseTransport | None = None, base_url: str = HUBSPOT_API
    ) -> None:
        self._transport = transport
        self._base = base_url

    async def _call(
        self,
        cfg: HubSpotConfig,
        sec: HubSpotSecrets,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Authorization": f"Bearer {sec.private_app_token}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=cfg.timeout_s, follow_redirects=False
            ) as client:
                response = await client.request(
                    method, self._base + path, headers=headers, json=json_body
                )
        except httpx.TimeoutException as exc:
            raise ConnectorRetryableError(f"HubSpot timeout: {exc!r}") from exc
        except httpx.TransportError as exc:
            raise ConnectorRetryableError(f"HubSpot transport error: {exc!r}") from exc
        status = response.status_code
        if status == 401:
            raise ConnectorPermanentError(
                "HubSpot rejected the private app token (401): token is invalid or revoked"
            )
        if status == 403:
            raise ConnectorPermanentError(
                "HubSpot denied access (403): the private app needs the "
                "crm.objects.contacts.read and crm.objects.contacts.write scopes"
            )
        if status == 429 or status >= 500:
            retry_after = response.headers.get("retry-after", "")
            raise ConnectorRetryableError(
                f"HubSpot HTTP {status}",
                retry_after_s=float(retry_after) if retry_after.isdigit() else None,
            )
        if status >= 400:
            raise ConnectorPermanentError(f"HubSpot HTTP {status}: {response.text[:200]}")
        return response

    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        cfg, sec = _typed(config, secrets)
        try:
            await self._call(cfg, sec, "GET", "/crm/v3/objects/contacts?limit=1")
        except ConnectorError as exc:
            return TestResult(ok=False, detail=str(exc))
        return TestResult(ok=True, detail="HubSpot token accepted")

    async def handle(
        self, event: AnyEnvelope, config: BaseModel, secrets: BaseModel, ctx: DeliveryCtx
    ) -> DeliveryOutcome:
        cfg, sec = _typed(config, secrets)
        summary = ctx.summary
        if event.type.value != "evaluation.completed" or summary is None:
            return DeliveryOutcome(status="skipped", detail="no evaluation summary for event")
        if cfg.only_failed and summary.passed is not False:
            return DeliveryOutcome(status="skipped", detail="only_failed and call did not fail")
        contact_id = await self._find_contact(cfg, sec, summary)
        if contact_id is None:
            return DeliveryOutcome(status="skipped", detail="no matching contact")
        body = render_note(cfg, summary, ctx, str(event.event_id))
        response = await self._call(
            cfg,
            sec,
            "POST",
            "/crm/v3/objects/notes",
            {
                "properties": {
                    "hs_timestamp": event.occurred_at.astimezone(UTC).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                    "hs_note_body": body,
                },
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": NOTE_TO_CONTACT,
                            }
                        ],
                    }
                ],
            },
        )
        note_id = response.json().get("id")
        if not note_id:
            raise ConnectorPermanentError("HubSpot created a note but returned no id")
        return DeliveryOutcome(
            status="succeeded",
            http_status=response.status_code,
            external_id=str(note_id),
            response_excerpt=f"note {note_id} on contact {contact_id}",
        )

    async def _find_contact(
        self, cfg: HubSpotConfig, sec: HubSpotSecrets, summary: EvaluationSummary
    ) -> str | None:
        meta = summary.metadata
        direct = meta.get("crm_contact_id", "").strip()
        if direct:
            return direct
        if cfg.match_by == "contact_id":
            return None
        if cfg.match_by == "email":
            email = meta.get("email", "").strip().lower()
            groups = [_group("email", email)] if email else []
        else:
            phone = meta.get("phone", "").strip()
            groups = [
                _group(prop, variant)
                for variant in _phone_variants(phone)
                for prop in ("phone", "mobilephone")
            ]
        if not groups:
            return None
        response = await self._call(
            cfg,
            sec,
            "POST",
            "/crm/v3/objects/contacts/search",
            {
                "filterGroups": groups,
                "properties": ["email", "phone", "mobilephone"],
                "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
                "limit": 1,
            },
        )
        results = response.json().get("results") or []
        return str(results[0]["id"]) if results else None


def _group(prop: str, value: str) -> dict[str, Any]:
    return {"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}


def _phone_variants(phone: str) -> list[str]:
    """Stored formats vary; try the value as given and its +digits form."""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return []
    variants = [phone.strip()]
    plus = "+" + digits
    if plus not in variants:
        variants.append(plus)
    return variants


def render_note(cfg: HubSpotConfig, s: EvaluationSummary, ctx: DeliveryCtx, event_id: str) -> str:
    base = (cfg.public_base_url or ctx.public_base_url or "").rstrip("/")
    link = s.link if s.link.startswith("http") or not base else base + s.link
    seconds = (s.duration_ms or 0) // 1000
    values = {
        "verdict": {True: "PASS", False: "FAIL", None: "UNSCORED"}[s.passed],
        "score": "n/a" if s.overall_score is None else f"{s.overall_score:g}",
        "critical": s.critical_failure,
        "agent": s.agent_name or "unknown agent",
        "language": s.language or "unknown language",
        "duration": f"{seconds // 60}m {seconds % 60}s",
        "issues": ", ".join(s.failure_types) or "none",
        "summary": s.summary,
        "link": link,
    }
    try:
        text = _env.from_string(cfg.note_template).render(**values)
    except TemplateError as exc:
        raise ConnectorPermanentError(f"note_template is invalid: {exc}") from exc
    return f"{text}\n[pareeksha event {event_id}]"


def _typed(config: BaseModel, secrets: BaseModel) -> tuple[HubSpotConfig, HubSpotSecrets]:
    if not isinstance(config, HubSpotConfig) or not isinstance(secrets, HubSpotSecrets):
        raise ConnectorPermanentError("hubspot connector got config/secrets of the wrong type")
    return config, secrets
