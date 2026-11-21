"""``nexus-admin``: user management from the command line (e.g. demo analyst/viewer accounts)."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from collections.abc import Sequence

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.config import DatabaseSettings
from nexus.db.engines import create_engine
from nexus.db.models import Role, User
from nexus.security.accounts import create_user, normalize_email


class _AppDbOnly(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )
    app_db: DatabaseSettings


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
    args = parser.parse_args(argv)
    password = (
        sys.stdin.readline().rstrip("\n") if args.password_stdin else getpass.getpass("Password: ")
    )
    return asyncio.run(
        _create(args.email, args.name, Role(args.role), password, if_missing=args.if_missing)
    )


if __name__ == "__main__":
    raise SystemExit(main())
