"""Application settings loaded from the environment.

Design notes
------------
* All settings are read from environment variables prefixed with ``T2SQL_``
  (see ``.env.example``). Pydantic Settings performs type coercion and
  validation; invalid configuration fails fast at startup with an actionable
  error rather than surfacing deep in a request.
* The object is immutable (``frozen``) so that no request handler can mutate
  global configuration at runtime.
* Secrets are never stored inline. ``llm_api_key_env`` names *another*
  environment variable that holds the provider key; the key is resolved lazily
  and never logged (see :mod:`text_to_sql.common.redaction`).
* :func:`get_settings` is process-wide cached; tests build fresh ``Settings``
  instances directly (with overrides) and inject them, so nothing depends on
  hidden global state.
"""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment. Controls a handful of safety defaults."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


LLMProviderName = Literal["fake", "openai", "gemini"]
SQLDialectName = Literal["sqlite", "postgres"]

# Google Gemini speaks the OpenAI chat-completions protocol at this endpoint, so
# it reuses the same adapter rather than needing a bespoke client.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class Settings(BaseSettings):
    """Central, validated configuration object.

    Every field maps to a ``T2SQL_<UPPER_FIELD>`` environment variable.
    """

    model_config = SettingsConfigDict(
        env_prefix="T2SQL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    log_json: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # --- Database ------------------------------------------------------------
    database_url: str = "sqlite:///./data/text_to_sql.db"
    readonly_database_url: str | None = None
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- SQL dialect & safety limits ----------------------------------------
    sql_dialect: SQLDialectName = "sqlite"
    max_rows: int = Field(default=1000, ge=1, le=1_000_000)
    statement_timeout_ms: int = Field(default=5000, ge=100, le=600_000)
    max_joins: int = Field(default=6, ge=0, le=64)
    max_subquery_depth: int = Field(default=4, ge=1, le=32)
    max_selected_columns: int = Field(default=60, ge=1, le=1000)
    cost_rows_high_threshold: float = Field(default=1_000_000, gt=0)
    cost_rows_medium_threshold: float = Field(default=100_000, gt=0)

    # --- LLM provider --------------------------------------------------------
    llm_provider: LLMProviderName = "fake"
    llm_model: str = "deterministic-fake"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key_env: str = "OPENAI_API_KEY"
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # --- Pipeline behaviour --------------------------------------------------
    max_repair_attempts: int = Field(default=2, ge=0, le=10)
    schema_cache_ttl_seconds: float = Field(default=300.0, ge=0)
    enable_result_cache: bool = False
    retrieval_top_k: int = Field(default=12, ge=1, le=200)
    disclose_model_metadata: bool = True

    # --- Observability -------------------------------------------------------
    metrics_enabled: bool = True
    tracing_enabled: bool = True

    # --- Authorization / multi-tenancy --------------------------------------
    allowed_schemas: tuple[str, ...] = ()
    tenant_column: str = "organization_id"

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return upper

    @field_validator("allowed_schemas", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a comma-separated string from the environment."""
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @model_validator(mode="after")
    def _check_cost_thresholds(self) -> Settings:
        if self.cost_rows_medium_threshold >= self.cost_rows_high_threshold:
            raise ValueError(
                "cost_rows_medium_threshold must be < cost_rows_high_threshold "
                f"(got medium={self.cost_rows_medium_threshold}, "
                f"high={self.cost_rows_high_threshold})"
            )
        return self

    # ------------------------------------------------------------------ #
    # Derived / convenience accessors
    # ------------------------------------------------------------------ #
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def effective_readonly_url(self) -> str:
        """URL used by the read-only executor (falls back to the main URL)."""
        return self.readonly_database_url or self.database_url

    @property
    def effective_llm_base_url(self) -> str:
        """Base URL for the configured provider.

        When ``llm_provider='gemini'`` and the operator has not overridden
        ``llm_base_url``, default to Google's OpenAI-compatibility endpoint so the
        provider works with no extra configuration.
        """
        if self.llm_provider == "gemini" and self.llm_base_url == _OPENAI_DEFAULT_BASE_URL:
            return GEMINI_BASE_URL
        return self.llm_base_url

    def resolve_llm_api_key(self) -> str | None:
        """Resolve the provider API key from the environment variable it names.

        Returns ``None`` when unset. The value is intentionally not stored on the
        settings object so it cannot be accidentally serialized or logged.
        """
        return os.environ.get(self.llm_api_key_env) or None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance.

    Used by the FastAPI application factory and CLI entry points. Tests should
    construct ``Settings(...)`` directly to avoid caching across cases.
    """
    return Settings()
