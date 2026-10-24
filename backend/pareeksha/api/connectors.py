"""Which connector an integration row refers to, and in which direction it works.

Connectors register in the ``pareeksha.connectors`` entry-point group (docs/10 section 1.1); the
connector framework's registry (INT-01) is the single source of truth.
"""

from __future__ import annotations

from pareeksha.integrations.base import ConnectorDirection
from pareeksha.integrations.registry import UnknownConnectorError, get_registry


def connector_direction(name: str) -> ConnectorDirection | None:
    """The direction of connector ``name``, or ``None`` when no such connector exists."""
    try:
        return get_registry().get(name).direction
    except UnknownConnectorError:
        return None
