"""
core/config.py
──────────────────────────────────────────────────────────────────────────────
Centralised application settings loaded from environment variables / .env file.

All settings are typed and validated by Pydantic-settings at startup.
Use `get_settings()` everywhere — it is cached so the .env is read once.
──────────────────────────────────────────────────────────────────────────────
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Application ────────────────────────────────────────────────────────
    app_name: str = "Metis Intelligence Backend"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"

    # ── Database ───────────────────────────────────────────────────────────
    database_url: str = Field(..., alias="DATABASE_URL")

    # ── OpenAI / LLM ──────────────────────────────────────────────────────
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")

    # Optional base URL for OpenAI-compatible proxy endpoints.
    # Set OPENAI_BASE_URL to route requests through a custom gateway
    # (e.g. https://www.genspark.ai/api/llm_proxy/v1).
    # Defaults to None which uses the official OpenAI endpoint.
    openai_base_url: str | None = Field(default=None, alias="OPENAI_BASE_URL")

    # Which OpenAI chat model to use.
    # Override with LLM_MODEL=gpt-5-mini in .env for a more capable model.
    llm_model: str = Field(default="gpt-5-mini", alias="LLM_MODEL")

    # When True the service skips the OpenAI call and returns the rich mock
    # report. Useful for local dev / CI when no API key is available.
    llm_mock_mode: bool = Field(default=False, alias="LLM_MOCK_MODE")

    # ── LLM provider / model-tier / cost controls ──────────────────────────
    # LLM_PROVIDER   : Which provider to route calls to.
    #                  "openai" is the only implemented provider.
    #                  Add "anthropic" or "gemini" by extending PROVIDER_CONFIGS
    #                  and call_llm() in services/llm_service.py.
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")

    # LLM_MODEL_TIER : Controls which model is selected from the provider's
    #                  model_tiers registry.
    #                  "cheap"   → gpt-5-nano  (low cost, fastest)
    #                  "default" → gpt-5-mini  (recommended)
    #                  "premium" → gpt-5       (highest quality)
    llm_model_tier: str = Field(default="default", alias="LLM_MODEL_TIER")

    # LLM_MAX_TOKENS : Hard cap on completion tokens per request.
    #                  Measured output for the 5-insight / 4-5-recommendation
    #                  report schema is consistently 400-580 tokens.
    #                  650 provides a ~15% safety buffer while cutting the
    #                  previous over-reservation of 1500 (~3x actual usage) by
    #                  ~57%.  Raise to 900+ only if you add more output fields.
    llm_max_tokens: int = Field(default=650, alias="LLM_MAX_TOKENS")

    # LLM_TEMPERATURE: Sampling temperature (0.0 = deterministic, 1.0 = creative).
    #                  0.4 balances consistency with natural-sounding text.
    llm_temperature: float = Field(default=0.4, alias="LLM_TEMPERATURE")

    # ── CORS ──────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], alias="CORS_ORIGINS"
    )

    # ── Logging ───────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("log_level", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        return v.upper()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
