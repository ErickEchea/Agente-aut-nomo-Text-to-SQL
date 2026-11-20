"""Application configuration — the single source of settings, loaded from environment variables.

Nested settings use ``__`` as delimiter, e.g. ``NEXUS_APP_DB__HOST``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL


class DatabaseSettings(BaseModel):
    """Connection parameters for a PostgreSQL database."""

    host: str
    port: int = Field(default=5432, ge=1, le=65535)
    name: str
    user: str
    password: SecretStr
    pool_size: int = Field(default=5, ge=1, le=50)
    connect_timeout_s: float = Field(default=5.0, gt=0)

    def sqlalchemy_url(self, driver: str = "postgresql+asyncpg") -> URL:
        """Build a URL without string interpolation so special characters in passwords are safe."""
        return URL.create(
            drivername=driver,
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )

    def libpq_conninfo(self) -> str:
        """Key/value conninfo for psycopg; values are quoted per libpq rules."""

        def quote(value: str) -> str:
            escaped = value.replace("\\", "\\\\").replace("'", "\\'")
            return f"'{escaped}'"

        parts = {
            "host": self.host,
            "port": str(self.port),
            "dbname": self.name,
            "user": self.user,
            "password": self.password.get_secret_value(),
            "connect_timeout": str(max(1, int(self.connect_timeout_s))),
        }
        return " ".join(f"{key}={quote(value)}" for key, value in parts.items())


class OllamaSettings(BaseModel):
    """Ollama endpoint and the models the stack requires."""

    base_url: HttpUrl = HttpUrl("http://ollama:11434")
    llm_model: str = "qwen2.5-coder:7b"
    embedding_model: str = "qwen3-embedding:0.6b"
    request_timeout_s: float = Field(default=5.0, gt=0)

    @property
    def required_models(self) -> tuple[str, ...]:
        return (self.llm_model, self.embedding_model)


class Settings(BaseSettings):
    """Top-level settings. Missing required values fail fast at startup."""

    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    app_db: DatabaseSettings
    demo_db: DatabaseSettings
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string (the natural .env format)."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("wildcard CORS origin is not allowed; list explicit origins")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings (cached). Tests construct ``Settings`` directly instead."""
    return Settings()  # required fields come from the environment
