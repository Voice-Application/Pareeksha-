"""Write an event to the transactional outbox through the request's SQLAlchemy session.

The domain rows and the event commit (or roll back) together; the outbox relay publishes the row
to Kafka later (TRD section 10.4). The raw-psycopg twin for workers is ``pareeksha.events.outbox``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.db.models import OutboxEvents
from pareeksha.events.schemas import AnyEnvelope


def enqueue_event(session: AsyncSession, envelope: AnyEnvelope) -> None:
    """Add the envelope to the session; it is inserted with the surrounding transaction."""
    session.add(
        OutboxEvents(
            id=envelope.event_id,
            topic=envelope.topic.value,
            key=envelope.partition_key(),
            envelope=envelope.model_dump(mode="json"),
            created_at=datetime.now(UTC),  # call order = relay order for events of one key
        )
    )
