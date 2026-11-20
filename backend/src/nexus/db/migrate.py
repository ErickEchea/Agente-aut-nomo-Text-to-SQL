"""``nexus-migrate``: apply Alembic migrations to the app DB (compose `migrate` job)."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.config import DatabaseSettings

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class _AppDbOnly(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )
    app_db: DatabaseSettings


def app_db_url_from_env() -> str:
    return _AppDbOnly().app_db.sqlalchemy_url().render_as_string(hide_password=False)


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url:
        # ConfigParser interpolation: escape % in URL-encoded passwords.
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


def main() -> int:
    upgrade(revision=sys.argv[1] if len(sys.argv) > 1 else "head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
