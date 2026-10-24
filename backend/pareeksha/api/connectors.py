"""Which connector an integration row refers to, and in which direction it works.

Connectors register in the ``pareeksha.connectors`` entry-point group (docs/10 section 1.1). The
two connectors the product ships are listed as well, so an integration can be created before its
package is installed in the API image; the connector framework (INT-01) is what runs them.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import cast

from pareeksha.integrations.base import CONNECTOR_ENTRY_POINT_GROUP, ConnectorDirection

#: Connectors shipped with Pareeksha (docs/10-integrations-and-dx.md sections 2.1 and 2.2).
SHIPPED_DIRECTIONS: dict[str, ConnectorDirection] = {"webhook": "sink", "hubspot": "sink"}


def installed_directions() -> dict[str, ConnectorDirection]:
    """Connector name -> direction for the shipped and entry-point connectors."""
    found = dict(SHIPPED_DIRECTIONS)
    for ep in entry_points(group=CONNECTOR_ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            found[str(cls.name)] = cast(ConnectorDirection, cls.direction)
        except Exception:  # a broken plugin must not break integration CRUD
            continue
    return found


def connector_direction(name: str) -> ConnectorDirection | None:
    """The direction of connector ``name``, or ``None`` when no such connector exists."""
    return installed_directions().get(name)
