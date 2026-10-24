"""Which connector an integration row refers to, and in which direction it works.

Connectors register in the ``pareeksha.connectors`` entry-point group (docs/10 section 1.1); the
connector framework's registry (INT-01) is the source of truth. Connectors the product ships but
whose package is not registered yet (HubSpot) are listed as well, so an integration can be created
before its package is installed in the API image.
"""

from __future__ import annotations

from pareeksha.integrations.base import ConnectorDirection
from pareeksha.integrations.registry import get_registry

#: Connectors shipped with Pareeksha (docs/10-integrations-and-dx.md sections 2.1 and 2.2).
SHIPPED_DIRECTIONS: dict[str, ConnectorDirection] = {"webhook": "sink", "hubspot": "sink"}


def installed_directions() -> dict[str, ConnectorDirection]:
    """Connector name -> direction for the shipped and registry (entry-point) connectors."""
    registry = get_registry()
    found = dict(SHIPPED_DIRECTIONS)
    for name in registry.names():
        found[name] = registry.get(name).direction
    return found


def connector_direction(name: str) -> ConnectorDirection | None:
    """The direction of connector ``name``, or ``None`` when no such connector exists."""
    return installed_directions().get(name)
