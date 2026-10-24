"""Connector registry: discovery through the ``pareeksha.connectors`` entry-point group (FR-IN-1).

Built-ins register the same way as third-party packages (see ``pyproject.toml``). A class that
violates the contract is refused and listed in ``rejected`` instead of breaking start-up.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from pareeksha.integrations.base import (
    CONNECTOR_ENTRY_POINT_GROUP,
    Connector,
    validate_connector_class,
)
from pareeksha.schemas.integrations import ConnectorInfo

log = logging.getLogger(__name__)


class UnknownConnectorError(KeyError):
    """No installed connector has this name."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, type[Connector]] = {}
        #: entry-point name -> reasons it was refused
        self.rejected: dict[str, list[str]] = {}

    @classmethod
    def from_entry_points(cls, eps: Iterable[EntryPoint] | None = None) -> ConnectorRegistry:
        registry = cls()
        selected = entry_points(group=CONNECTOR_ENTRY_POINT_GROUP) if eps is None else eps
        for ep in selected:
            try:
                loaded: Any = ep.load()
            except Exception as exc:  # a broken plugin must not stop the platform
                registry.rejected[ep.name] = [f"import failed: {exc!r}"]
                log.warning("connector %s failed to import: %r", ep.name, exc)
                continue
            registry.register(loaded, source=ep.name)
        return registry

    def register(self, connector_cls: Any, *, source: str | None = None) -> bool:
        problems = validate_connector_class(connector_cls)
        label: str = source or str(getattr(connector_cls, "__name__", repr(connector_cls)))
        if not problems and connector_cls.name in self._connectors:
            problems = [f"duplicate connector name {connector_cls.name!r}"]
        if problems:
            self.rejected[label] = problems
            log.warning("connector %s refused: %s", label, "; ".join(problems))
            return False
        self._connectors[connector_cls.name] = connector_cls
        return True

    def get(self, name: str) -> type[Connector]:
        try:
            return self._connectors[name]
        except KeyError:
            raise UnknownConnectorError(name) from None

    def names(self) -> list[str]:
        return sorted(self._connectors)

    def info(self) -> list[ConnectorInfo]:
        """``GET /integrations/connectors``: connectors with JSON Schemas for the web forms."""
        return [
            ConnectorInfo(
                name=c.name,
                direction=c.direction,
                subscribes_to=list(c.subscribes_to),
                config_schema=c.config_schema.model_json_schema(),
                secrets_schema=c.secrets_schema.model_json_schema(),
            )
            for c in (self._connectors[n] for n in self.names())
        ]


_registry: ConnectorRegistry | None = None


def get_registry() -> ConnectorRegistry:
    """Process-wide registry, built from the installed entry points on first use."""
    global _registry
    if _registry is None:
        _registry = ConnectorRegistry.from_entry_points()
    return _registry
