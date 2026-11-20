"""Mode 1 of the attack suite: the AST validator alone rejects every attack."""

from __future__ import annotations

import pytest
import sqlglot

from nexus.sql.validator import SQLValidationError, ValidationPolicy, validate_sql
from tests.security.suite import BENIGN, RETAIL_TABLES, SQL_ATTACKS, Benign, SqlAttack

POLICY = ValidationPolicy(allowed_tables=RETAIL_TABLES, max_rows=1000)


def test_suite_meets_minimum_size() -> None:
    assert len(SQL_ATTACKS) >= 40
    assert len({a.id for a in SQL_ATTACKS}) == len(SQL_ATTACKS)


@pytest.mark.parametrize("attack", SQL_ATTACKS, ids=lambda a: a.id)
def test_attack_is_rejected_with_expected_code(attack: SqlAttack) -> None:
    with pytest.raises(SQLValidationError) as exc_info:
        validate_sql(attack.sql, POLICY)
    assert exc_info.value.code.value == attack.code, exc_info.value.detail


@pytest.mark.parametrize("case", BENIGN, ids=lambda c: c.id)
def test_benign_query_passes_sanitized(case: Benign) -> None:
    result = validate_sql(case.sql, POLICY)
    assert result.limit_applied == case.limit
    assert "/*" not in result.sql
    assert "--" not in result.sql
    # The regenerated SQL is itself a single valid statement.
    assert len(sqlglot.parse(result.sql, dialect="postgres")) == 1


def test_too_long_sql_is_rejected() -> None:
    sql = "SELECT " + " + ".join(["1"] * 8000)
    with pytest.raises(SQLValidationError) as exc_info:
        validate_sql(sql, POLICY)
    assert exc_info.value.code.value == "too_long"


def test_limit_is_added_and_existing_small_limit_kept() -> None:
    added = validate_sql("SELECT nombre FROM productos", POLICY)
    assert added.limit_was_added
    assert added.sql.endswith("LIMIT 1000")
    kept = validate_sql("SELECT nombre FROM productos LIMIT 5", POLICY)
    assert not kept.limit_was_added
    assert kept.limit_applied == 5


def test_non_literal_limit_is_replaced() -> None:
    result = validate_sql("SELECT nombre FROM productos LIMIT (SELECT 10)", POLICY)
    assert result.limit_applied == 1000
    assert result.sql.endswith("LIMIT 1000")


def test_tables_used_are_reported_without_ctes() -> None:
    result = validate_sql(
        "WITH t AS (SELECT * FROM ventas) SELECT * FROM t JOIN sucursales USING (sucursal_id)",
        POLICY,
    )
    assert result.tables == ("sucursales", "ventas")


def test_extra_allowed_functions_extend_the_allowlist() -> None:
    sql = "SELECT custom_metric(1)"
    with pytest.raises(SQLValidationError):
        validate_sql(sql, POLICY)
    policy = ValidationPolicy(
        allowed_tables=RETAIL_TABLES, extra_allowed_functions=frozenset({"custom_metric"})
    )
    assert validate_sql(sql, policy).sql.startswith("SELECT CUSTOM_METRIC(1)")


def test_denylist_wins_over_extra_allowlist() -> None:
    policy = ValidationPolicy(
        allowed_tables=RETAIL_TABLES, extra_allowed_functions=frozenset({"pg_sleep"})
    )
    with pytest.raises(SQLValidationError) as exc_info:
        validate_sql("SELECT pg_sleep(1)", policy)
    assert exc_info.value.code.value == "forbidden_function"
