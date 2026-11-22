"""Application configuration — the single source of settings, loaded from environment variables.

Nested settings use ``__`` as delimiter, e.g. ``NEXUS_APP_DB__HOST``.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
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
    # Reasoning toggle for models that think by default (qwen3, gemma4); None = model default.
    think: bool | None = None
    # Extra models the per-node routing uses (AgentSettings.models); they must be pulled too.
    extra_models: str = ""

    @field_validator("think", mode="before")
    @classmethod
    def _empty_means_default(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def required_models(self) -> tuple[str, ...]:
        extra = tuple(m.strip() for m in self.extra_models.split(",") if m.strip())
        return tuple(dict.fromkeys((self.llm_model, *extra, self.embedding_model)))


class NodeModelSettings(BaseModel):
    """Per-node model routing (ADR-0003); empty = the default model (``ollama.llm_model``)."""

    understand: str | None = None
    plan: str | None = None
    generate: str | None = None
    repair: str | None = None
    visualize: str | None = None
    explain: str | None = None

    def routing(self) -> dict[str, str | None]:
        """Keyword arguments for ``nexus.agent.state.NodeModels`` (blank = the default model)."""
        return {name: (value or None) for name, value in self.model_dump().items()}


class SecuritySettings(BaseModel):
    jwt_secret: SecretStr
    access_token_ttl_s: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_s: int = Field(default=7 * 86400, ge=3600)
    cookie_secure: bool = False  # set true behind HTTPS
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    @field_validator("jwt_secret")
    @classmethod
    def _strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("jwt_secret must be at least 32 characters")
        return value


class AgentSettings(BaseModel):
    # The demo data ends 2026-10-31; a fixed as_of keeps "último trimestre" stable (ADR-0008).
    as_of: date | None = None
    schema_name: str = "retail"
    max_repairs: int = Field(default=3, ge=0, le=5)
    statement_timeout_ms: int = Field(default=15_000, ge=500, le=120_000)
    max_rows: int = Field(default=1000, ge=1, le=10_000)
    pii_columns: str = "clientes.cedula,clientes.email,clientes.telefono,empleados.cedula"
    glossary_path: Path = Path("/app/data/glossary.yaml")
    llm_timeout_s: float = Field(default=180.0, gt=0)
    connection_key: str = "retail-demo"
    retrieval_max_tables: int = Field(default=4, ge=1, le=20)
    models: NodeModelSettings = Field(default_factory=NodeModelSettings)

    @field_validator("as_of", mode="before")
    @classmethod
    def _empty_means_today(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def pii_column_list(self) -> list[str]:
        return [c.strip() for c in self.pii_columns.split(",") if c.strip()]


class ConnectionSettings(BaseModel):
    """User-registered data sources (ADR-0012, ADR-0013)."""

    # Comma-separated Fernet keys (or 32+ char secrets); the first encrypts. Unset disables
    # registering connections (the built-in demo source still works).
    credentials_keys: SecretStr | None = None
    # SQLite files may only be opened from this directory (read-only, no path traversal).
    sqlite_dir: Path = Path("/data/sqlite")
    pool_size: int = Field(default=3, ge=1, le=20)
    connect_timeout_s: float = Field(default=5.0, gt=0)


class RateLimitSettings(BaseModel):
    login_per_minute: int = Field(default=5, ge=1)
    runs_per_minute: int = Field(default=20, ge=1)
    default_per_minute: int = Field(default=120, ge=1)


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
    security: SecuritySettings
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    connections: ConnectionSettings = Field(default_factory=ConnectionSettings)

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
