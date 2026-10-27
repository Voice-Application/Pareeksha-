"""Shared by the evaluator and finalizer workers."""

from __future__ import annotations

from collections.abc import Sequence

from pareeksha.events.consumer import Outgoing
from pareeksha.events.schemas import AnyEnvelope


def to_outgoing(envelopes: Sequence[AnyEnvelope]) -> list[Outgoing]:
    """Framework outputs carrying the ids and correlation the handlers already computed."""
    return [
        Outgoing(e.payload, correlation_id=e.correlation_id, event_id=e.event_id) for e in envelopes
    ]
