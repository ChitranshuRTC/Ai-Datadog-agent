"""Typed configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings for the service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="aiops-platform")
    app_version: str = Field(default="1.0.0")
    app_environment: str = Field(default="production")
    app_debug: bool = Field(default=False)
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = Field(default="INFO")
    datadog_webhook_token: SecretStr | None = Field(default=None)
    datadog_webhook_hmac_secret: SecretStr | None = Field(default=None)
    slack_bot_token: SecretStr | None = Field(default=None)
    slack_incident_channel: str | None = Field(default=None)
    slack_api_base_url: AnyHttpUrl = Field(default="https://slack.com/api/")
    integration_max_retries: int = Field(default=3, ge=1, le=10)
    integration_retry_base_delay_seconds: float = Field(default=0.5, gt=0, le=30)
    github_token: SecretStr | None = Field(default=None)
    github_repository: str | None = Field(default=None)
    github_base_branch: str = Field(default="main")
    kubernetes_in_cluster: bool = Field(default=False)
    remediation_wait_seconds: int = Field(default=30, ge=0, le=600)
    auto_remediation_enabled: bool = Field(default=False)
    cors_allow_origins: str = Field(default="*")

    @property
    def cors_origins(self) -> list[str]:
        """Return configured CORS origins as a normalized list."""
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached, validated settings instance."""
    return Settings()
