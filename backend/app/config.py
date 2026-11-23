"""Application configuration, loaded from environment variables / .env.

All settings are prefixed ``WARDENIX_`` except the standard ``POSTGRES_*`` and
``DATABASE_URL`` variables, so they compose cleanly with Docker Compose.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.enums import Decision


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WARDENIX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database (standard POSTGRES_* / DATABASE_URL names, no WARDENIX_ prefix) ---
    postgres_user: str = Field("wardenix", validation_alias=AliasChoices("POSTGRES_USER"))
    postgres_password: str = Field("wardenix", validation_alias=AliasChoices("POSTGRES_PASSWORD"))
    postgres_db: str = Field("wardenix", validation_alias=AliasChoices("POSTGRES_DB"))
    postgres_host: str = Field("db", validation_alias=AliasChoices("POSTGRES_HOST"))
    postgres_port: int = Field(5432, validation_alias=AliasChoices("POSTGRES_PORT"))
    # Explicit override wins over the composed POSTGRES_* URL when provided.
    database_url: str | None = Field(None, validation_alias=AliasChoices("DATABASE_URL"))

    # --- Security (WARDENIX_ prefix) ---
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    bootstrap_admin_email: str | None = "admin@wardenix.local"
    bootstrap_admin_password: str | None = "changeme-admin"

    # --- Gateway behaviour ---
    default_action: Decision = Decision.DENY
    approval_ttl_seconds: int = 900
    approval_longpoll_seconds: int = 2
    upstream_timeout_seconds: int = 30
    agent_concurrency: int = 8
    max_args_bytes: int = 262_144
    # Circuit breaker: open after N consecutive upstream failures, cool down for S seconds.
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown_seconds: int = 30

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    # --- SSRF guard (outbound HTTP upstreams) ---
    # Comma-separated host or host:port allowlist; empty = no allowlist filter.
    ssrf_allowlist: str = ""
    # Allow loopback/private upstream targets (dev default True; set False in prod).
    ssrf_allow_private: bool = True

    # --- Logging ---
    log_level: str = "INFO"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ssrf_allowlist_list(self) -> list[str]:
        return [h.strip() for h in self.ssrf_allowlist.split(",") if h.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
