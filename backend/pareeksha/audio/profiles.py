"""The 8 shipped line/noise profiles (docs/08-evaluation-rubric.md §7)."""

from __future__ import annotations

from dataclasses import dataclass

from pareeksha.audio.noise import CATEGORIES

_CODECS = ("none", "alaw", "mulaw")
_RATES = (8000, 16000)


@dataclass(frozen=True)
class LineProfile:
    """FR-NP-1 fields. `background=None` means no background noise (snr_db then unused)."""

    name: str
    sample_rate: int = 16000
    codec: str = "none"
    pstn_bandpass: bool = False
    background: str | None = None
    snr_db: float | None = None
    packet_loss_pct: float = 0.0
    clipping: bool = False

    def __post_init__(self) -> None:
        if self.sample_rate not in _RATES:
            raise ValueError(f"sample_rate must be one of {_RATES}")
        if self.codec not in _CODECS:
            raise ValueError(f"codec must be one of {_CODECS}")
        if self.background is not None:
            if self.background not in CATEGORIES:
                raise ValueError(f"background must be one of {CATEGORIES}")
            if self.snr_db is None:
                raise ValueError("snr_db is required when background is set")
        if not 0.0 <= self.packet_loss_pct <= 100.0:
            raise ValueError("packet_loss_pct must be in [0, 100]")

    @property
    def is_identity(self) -> bool:
        return (
            self.sample_rate == 16000
            and self.codec == "none"
            and not self.pstn_bandpass
            and self.background is None
            and self.packet_loss_pct == 0.0
            and not self.clipping
        )


def _pstn(
    name: str,
    background: str | None = None,
    snr: float | None = None,
    loss: float = 0.0,
    clip: bool = False,
):
    return LineProfile(
        name=name,
        sample_rate=8000,
        codec="alaw",
        pstn_bandpass=True,
        background=background,
        snr_db=snr,
        packet_loss_pct=loss,
        clipping=clip,
    )


BUILTIN_PROFILES: dict[str, LineProfile] = {
    p.name: p
    for p in (
        LineProfile(name="clean_16k"),
        _pstn("pstn_8k_alaw"),
        _pstn("pstn_office_babble_15db", "office_babble", 15),
        _pstn("pstn_street_10db", "street_traffic", 10),
        _pstn("pstn_market_5db", "market_crowd", 5),
        _pstn("mobile_bus_5db", "bus_interior", 5, loss=2),
        _pstn("mobile_weak_signal", "street_traffic", 10, loss=5, clip=True),
        _pstn("auto_rickshaw_0db", "auto_rickshaw", 0, loss=1),
    )
}


def get_profile(name: str) -> LineProfile:
    try:
        return BUILTIN_PROFILES[name]
    except KeyError:
        raise KeyError(
            f"unknown noise profile {name!r}; known: {sorted(BUILTIN_PROFILES)}"
        ) from None
