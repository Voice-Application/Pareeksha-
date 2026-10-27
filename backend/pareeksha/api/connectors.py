"""Which connector an integration row refers to, and in which direction it works.

Connectors register in the ``pareeksha.connectors`` entry-point group (docs/10 section 1.1; the
built-ins ``webhook`` and ``hubspot`` are declared in ``pyproject.toml``). The connector framework's
registry is the single source of truth.
"""

from __future__ import annotations

from pareeksha.integrations.base import ConnectorDirection
from pareeksha.integrations.registry import get_registry


def installed_directions() -> dict[str, ConnectorDirection]:
    """Connector name -> direction for every registered (entry-point) connector."""
    registry = get_registry()
    return {name: registry.get(name).direction for name in registry.names()}


def connector_direction(name: str) -> ConnectorDirection | None:
    """The direction of connector ``name``, or ``None`` when no such connector exists."""
    return installed_directions().get(name)
