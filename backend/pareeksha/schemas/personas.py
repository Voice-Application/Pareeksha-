"""Personas and noise profiles (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pareeksha.schemas.common import RequestModel

CodeMixStyle = Literal["none", "light", "heavy"]
Emotion = Literal["neutral", "frustrated", "angry", "confused", "anxious", "polite", "rushed"]
SilenceHabit = Literal["normal", "long_pauses", "goes_silent"]
Codec = Literal["none", "mulaw", "alaw"]


class PersonaCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(min_length=2, examples=["kn-IN"])
    code_mix_style: CodeMixStyle = "none"
    dialect_label: str = ""
    tts_model: str = "timbre-v3.0"
    voice_id: str = Field(min_length=1, examples=["Prakash"])
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    emotion: Emotion = "neutral"
    patience_turns: int = Field(default=8, ge=1, le=60)
    interruption_level: int = Field(default=0, ge=0, le=3)
    silence_habit: SilenceHabit = "normal"
    behaviour_notes: str = ""


class PersonaUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    language: str | None = Field(default=None, min_length=2)
    code_mix_style: CodeMixStyle | None = None
    dialect_label: str | None = None
    tts_model: str | None = None
    voice_id: str | None = Field(default=None, min_length=1)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    emotion: Emotion | None = None
    patience_turns: int | None = Field(default=None, ge=1, le=60)
    interruption_level: int | None = Field(default=None, ge=0, le=3)
    silence_habit: SilenceHabit | None = None
    behaviour_notes: str | None = None


class PersonaOut(PersonaCreate):
    id: UUID
    is_seed: bool = False
    created_at: datetime


class NoiseProfileCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["pstn_market_5db"])
    sample_rate: Literal[8000, 16000] = 16000
    codec: Codec = "none"
    pstn_bandpass: bool = False
    background_category: str | None = Field(default=None, examples=["market_crowd"])
    snr_db: float | None = Field(default=None, ge=-10, le=60)
    packet_loss_pct: float = Field(default=0.0, ge=0, le=20)
    clipping: bool = False
    description: str = ""

    @model_validator(mode="after")
    def _snr_required_with_background(self) -> NoiseProfileCreate:
        if self.background_category is not None and self.snr_db is None:
            raise ValueError("snr_db is required when background_category is set")
        return self


class NoiseProfileUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    sample_rate: Literal[8000, 16000] | None = None
    codec: Codec | None = None
    pstn_bandpass: bool | None = None
    background_category: str | None = None
    snr_db: float | None = Field(default=None, ge=-10, le=60)
    packet_loss_pct: float | None = Field(default=None, ge=0, le=20)
    clipping: bool | None = None
    description: str | None = None


class NoiseProfileOut(NoiseProfileCreate):
    id: UUID
    created_at: datetime
