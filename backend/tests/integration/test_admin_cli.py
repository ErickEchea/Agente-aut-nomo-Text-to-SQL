"""``nexus-admin create-user`` against a real app database (used by `make e2e` provisioning)."""

from __future__ import annotations

import io

import pytest

from nexus.admin_cli import main
from nexus.config import DatabaseSettings
from nexus.db.migrate import upgrade

pytestmark = pytest.mark.integration


@pytest.fixture
def app_env(app_db: DatabaseSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    upgrade(app_db.sqlalchemy_url().render_as_string(hide_password=False))
    for key, value in {
        "HOST": app_db.host,
        "PORT": str(app_db.port),
        "NAME": app_db.name,
        "USER": app_db.user,
        "PASSWORD": app_db.password.get_secret_value(),
    }.items():
        monkeypatch.setenv(f"NEXUS_APP_DB__{key}", value)


def _create(monkeypatch: pytest.MonkeyPatch, *extra: str) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO("cli-password-123\n"))
    args = ["create-user", "--email", "Cli@Nexus.Test", "--name", "CLI", "--role", "viewer"]
    return main([*args, "--password-stdin", *extra])


@pytest.mark.usefixtures("app_env")
def test_create_user_is_idempotent_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _create(monkeypatch) == 0
    assert "created viewer cli@nexus.test" in capsys.readouterr().out
    assert _create(monkeypatch) == 1  # a duplicate is an error by default
    assert _create(monkeypatch, "--if-missing") == 0  # provisioning scripts may re-run
    assert "already exists" in capsys.readouterr().err
