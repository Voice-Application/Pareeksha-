"""LLM provider selection and settings, read from the environment (see .env.example).

``LLM_PROVIDER=deepseek|gemini`` (default ``deepseek``). Each provider has its own key, models and
cost rates. Model IDs are pinned in the environment, never hard-coded in call sites.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pareeksha.llm.base import LLMProviderName, LLMPurpose, LLMUsage

DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
#: Current IDs from https://api-docs.deepseek.com/quick_start/pricing (checked 2026-10-23).
DEEPSEEK_DEFAULT_JUDGE_MODEL = "deepseek-v4-pro"
DEEPSEEK_DEFAULT_CALLER_MODEL = "deepseek-flash"


class LLMConfigError(ValueError):
    """The selected provider is not configured."""


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, case_sensitive=False
    )

    llm_provider: LLMProviderName = LLMProviderName.DEEPSEEK

    deepseek_api_key: str | None = Field(default=None, repr=False)
    deepseek_base_url: str = DEEPSEEK_DEFAULT_BASE_URL
    deepseek_judge_model: str = DEEPSEEK_DEFAULT_JUDGE_MODEL
    deepseek_caller_model: str = DEEPSEEK_DEFAULT_CALLER_MODEL
    cost_deepseek_per_1k_input_tokens: float | None = Field(default=None, ge=0)
    cost_deepseek_per_1k_output_tokens: float | None = Field(default=None, ge=0)

    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_judge_model: str | None = None
    gemini_caller_model: str | None = None
    cost_gemini_per_1k_input_tokens: float | None = Field(default=None, ge=0)
    cost_gemini_per_1k_output_tokens: float | None = Field(default=None, ge=0)

    judge_temperature: float = Field(default=0.0, ge=0, le=2)
    caller_temperature: float = Field(default=0.7, ge=0, le=2)

    @property
    def api_key(self) -> str:
        """API key of the active provider; raises ``LLMConfigError`` if missing."""
        key = (
            self.deepseek_api_key
            if self.llm_provider is LLMProviderName.DEEPSEEK
            else self.gemini_api_key
        )
        if not key:
            raise LLMConfigError(
                f"LLM_PROVIDER={self.llm_provider.value} but its API key is not set in .env"
            )
        return key

    @property
    def judge_model(self) -> str:
        return self._model(
            self.deepseek_judge_model
            if self.llm_provider is LLMProviderName.DEEPSEEK
            else self.gemini_judge_model,
            "JUDGE",
        )

    @property
    def caller_model(self) -> str:
        return self._model(
            self.deepseek_caller_model
            if self.llm_provider is LLMProviderName.DEEPSEEK
            else self.gemini_caller_model,
            "CALLER",
        )

    def model_for(self, purpose: LLMPurpose) -> str:
        """Judge model for deterministic tasks, caller model for generative ones."""
        if purpose in (LLMPurpose.CALLER, LLMPurpose.SCENARIO_GEN):
            return self.caller_model
        return self.judge_model

    def temperature_for(self, purpose: LLMPurpose) -> float:
        """TRD section 4: judge-like tasks 0, caller 0.7, scenario generation 0.8."""
        if purpose is LLMPurpose.CALLER:
            return self.caller_temperature
        if purpose is LLMPurpose.SCENARIO_GEN:
            return 0.8
        return self.judge_temperature

    def estimate_cost(self, usage: LLMUsage) -> float | None:
        """Cost of ``usage`` in the units of the COST_* rates; ``None`` if rates are not set."""
        if self.llm_provider is LLMProviderName.DEEPSEEK:
            rate_in = self.cost_deepseek_per_1k_input_tokens
            rate_out = self.cost_deepseek_per_1k_output_tokens
        else:
            rate_in = self.cost_gemini_per_1k_input_tokens
            rate_out = self.cost_gemini_per_1k_output_tokens
        if rate_in is None or rate_out is None:
            return None
        return usage.input_tokens / 1000 * rate_in + usage.output_tokens / 1000 * rate_out

    def _model(self, value: str | None, which: str) -> str:
        if not value:
            raise LLMConfigError(
                f"{self.llm_provider.value.upper()}_{which}_MODEL is not set; pin an exact model ID"
            )
        return value
