"""``nexus-admin``: user management and credential-key rotation from the command line."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.config import ConnectionSettings, DatabaseSettings
from nexus.datasources.cipher import CredentialCipher
from nexus.db.engines import create_engine
from nexus.db.models import DataConnection, Role, User
from nexus.security.accounts import create_user, normalize_email


class _AppDbOnly(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )
    app_db: DatabaseSettings


class _KeysOnly(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )
    app_db: DatabaseSettings
    connections: ConnectionSettings = ConnectionSettings()


async def _rotate() -> int:
    """Re-encrypt every stored connection secret with the newest (first) key (ADR-0012)."""
    settings = _KeysOnly()
    keys = settings.connections.credentials_keys
    if keys is None:
        sys.stderr.write("NEXUS_CONNECTIONS__CREDENTIALS_KEYS is not set\n")
        return 1
    cipher = CredentialCipher(keys.get_secret_value())
    engine = create_engine(settings.app_db, application_name="nexus-admin")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    rotated = 0
    try:
        async with sessions() as session, session.begin():
            for row in await session.scalars(select(DataConnection)):
                if row.secret:
                    row.secret = cipher.rotate(row.secret)
                    rotated += 1
    finally:
        await engine.dispose()
    sys.stdout.write(f"re-encrypted {rotated} connection secret(s) with the newest key\n")
    return 0


async def _create(
    email: str, name: str, role: Role, password: str, *, if_missing: bool = False
) -> int:
    engine = create_engine(_AppDbOnly().app_db, application_name="nexus-admin")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            exists = await session.scalar(
                select(User.id).where(User.email == normalize_email(email))
            )
            if exists is not None:
                sys.stderr.write(f"user {email} already exists\n")
                return 0 if if_missing else 1
            await create_user(session, email=email, password=password, display_name=name, role=role)
    finally:
        await engine.dispose()
    sys.stdout.write(f"created {role.value} {normalize_email(email)}\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexus-admin")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create a user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], required=True)
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from stdin (no echo, no argv)",
    )
    create.add_argument(
        "--if-missing",
        action="store_true",
        help="succeed without changes when the user already exists (idempotent provisioning)",
    )
    sub.add_parser("rotate-keys", help="re-encrypt connection secrets with the newest key")
    args = parser.parse_args(argv)
    if args.command == "rotate-keys":
        return asyncio.run(_rotate())
    password = (
        sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    )
    return asyncio.run(
        _create(args.email, args.name, Role(args.role), password, if_missing=args.if_missing)
    )


if __name__ == "__main__":
    raise SystemExit(main())
