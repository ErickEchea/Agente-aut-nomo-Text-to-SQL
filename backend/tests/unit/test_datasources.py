"""Multi-DB units: credential cipher, dialect profiles, error classes, SQLite path confinement."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from nexus.agent import prompts
from nexus.datasources.cipher import CredentialCipher, CredentialError
from nexus.datasources.dialects import MYSQL, POSTGRESQL, SQLITE, classify_error, profile_for
from nexus.datasources.registry import SourceError, resolve_sqlite

OLD = "old-secret-key-" + "a" * 24
NEW = "new-secret-key-" + "b" * 24


def test_cipher_round_trip_and_rotation() -> None:
    old = CredentialCipher(OLD)
    token = old.encrypt("p@ss wörd")
    assert token != "p@ss wörd" and old.decrypt(token) == "p@ss wörd"
    both = CredentialCipher(f"{NEW},{OLD}")
    assert both.decrypt(token) == "p@ss wörd"  # old rows still readable during rotation
    rotated = both.rotate(token)
    assert CredentialCipher(NEW).decrypt(rotated) == "p@ss wörd"
    with pytest.raises(CredentialError):
        CredentialCipher(NEW).decrypt(token)  # the old key was dropped
    with pytest.raises(CredentialError):
        CredentialCipher(NEW).rotate(token)


def test_cipher_accepts_fernet_keys_and_rejects_weak_ones() -> None:
    key = Fernet.generate_key().decode()
    assert CredentialCipher(key).decrypt(CredentialCipher(key).encrypt("x")) == "x"
    with pytest.raises(CredentialError):
        CredentialCipher("short")
    with pytest.raises(CredentialError):
        CredentialCipher(" , ")


def test_profiles_and_date_literals() -> None:
    day = dt.date(2026, 7, 1)
    assert POSTGRESQL.date_literal(day) == "DATE '2026-07-01'"
    assert MYSQL.date_literal(day) == "DATE '2026-07-01'"
    assert SQLITE.date_literal(day) == "'2026-07-01'"
    assert profile_for("mysql") is MYSQL
    with pytest.raises(ValueError, match="unsupported"):
        profile_for("oracle")


def test_sql_rules_name_the_engine_schema_and_tips() -> None:
    rules = prompts.sql_rules(SQLITE, "main")
    assert "experto en SQLite" in rules and "(main.<tabla>)" in rules
    assert "strftime" in rules and "8. " in rules
    assert "PostgreSQL" in prompts.SQL_RULES and "(retail.<tabla>)" in prompts.SQL_RULES
    block = prompts.time_block(None, SQLITE)
    assert "Ninguno" in block


def test_postgresql_rules_stay_identical_to_the_validated_prompt() -> None:
    # The PostgreSQL rules are the ones validated end to end with the real model (Phase 4). Small
    # wording changes alter greedy decoding, so a change here must be re-validated with
    # `make e2e-agent` (and, from Phase 6, the benchmark) before updating this hash.
    rules = prompts.sql_rules(POSTGRESQL, "retail")
    assert rules == prompts.SQL_RULES
    digest = hashlib.sha256(rules.encode()).hexdigest()
    assert digest == "43122d4beb0fe3ba03e26ad185045e6cddc36adb4f583f4677cb9d4cbbc04aa9"


@pytest.mark.parametrize(
    ("kind", "sqlstate", "errno", "message", "expected"),
    [
        ("postgresql", "42703", None, "column does not exist", ("42703", True, False)),
        ("postgresql", "57014", None, "canceling statement", ("57014", False, True)),
        ("postgresql", "42501", None, "permission denied", ("42501", False, False)),
        ("mysql", None, 1054, "Unknown column", ("MY1054", True, False)),
        ("mysql", None, 3024, "maximum statement execution time", ("MY3024", False, True)),
        ("mysql", None, 1792, "READ ONLY transaction", ("MY1792", False, False)),
        ("sqlite", None, None, "no such column: x", ("SQLITE_ERROR", True, False)),
        ("sqlite", None, None, "interrupted", ("SQLITE_INTERRUPT", False, True)),
        (
            "sqlite",
            None,
            None,
            "attempt to write a readonly database",
            ("SQLITE_READONLY", False, False),
        ),
        ("sqlite", None, None, "disk I/O error", ("SQLITE_ERROR", False, False)),
    ],
)
def test_error_classification(
    kind: str,
    sqlstate: str | None,
    errno: int | None,
    message: str,
    expected: tuple[str, bool, bool],
) -> None:
    result = classify_error(kind, sqlstate=sqlstate, errno=errno, message=message)  # type: ignore[arg-type]
    assert (result.code, result.repairable, result.timeout) == expected


def test_sqlite_files_stay_inside_the_allowed_directory(tmp_path: Path) -> None:
    base = tmp_path / "data"
    (base / "nested").mkdir(parents=True)
    (base / "ok.sqlite").write_bytes(b"")
    (base / "nested" / "deep.db").write_bytes(b"")
    (tmp_path / "secret.sqlite").write_bytes(b"")
    assert resolve_sqlite(base, "ok.sqlite") == (base / "ok.sqlite").resolve()
    assert resolve_sqlite(base, "nested/deep.db").name == "deep.db"
    for bad in ("../secret.sqlite", "missing.sqlite", str(tmp_path / "secret.sqlite")):
        with pytest.raises(SourceError):
            resolve_sqlite(base, bad)
