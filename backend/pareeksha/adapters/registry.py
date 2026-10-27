"""Adapter lookup by ``agents.adapter``. Only the adapters that ship are listed."""

from __future__ import annotations

from pareeksha.adapters.audio_v1 import AudioV1Adapter
from pareeksha.adapters.base import Adapter, AdapterError, AdapterName
from pareeksha.adapters.pipecat_adapter import PipecatAdapter


class AdapterUnavailableError(AdapterError):
    """The agent uses an adapter this build does not include (livekit/vapi: not built)."""


_ADAPTERS: dict[AdapterName, type[Adapter]] = {
    "audio_v1": AudioV1Adapter,
    "pipecat": PipecatAdapter,
}


def available_adapters() -> list[AdapterName]:
    return sorted(_ADAPTERS)


def get_adapter(name: AdapterName) -> Adapter:
    try:
        return _ADAPTERS[name]()
    except KeyError:
        raise AdapterUnavailableError(
            f"adapter {name!r} is not available in this build (available: {available_adapters()})"
        ) from None
