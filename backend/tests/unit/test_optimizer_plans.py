"""Plan parsing per engine and candidate selection (no database)."""

from __future__ import annotations

from nexus.agent.catalog import ColumnInfo, SchemaCatalog, TableInfo
from nexus.sql.optimizer import (
    IndexSuggestion,
    _candidates,
    _mysql_steps,
    _pg_steps,
    _sqlite_steps,
    column_usage,
    index_ddl,
)


def _table(name: str, *cols: str) -> TableInfo:
    return TableInfo(
        name, "", tuple(ColumnInfo(c, "integer", True, "") for c in cols), (cols[0],), ()
    )


CATALOG = SchemaCatalog(
    "shop",
    {
        "orders": _table("orders", "order_id", "customer_id", "status", "created_at"),
        "customers": _table("customers", "customer_id", "city"),
    },
)

PG_PLAN = [
    {
        "Plan": {
            "Node Type": "Hash Join",
            "Total Cost": 500.0,
            "Plan Rows": 10,
            "Hash Cond": "(o.customer_id = c.customer_id)",
            "Plans": [
                {"Node Type": "Seq Scan", "Relation Name": "orders", "Total Cost": 400.0, "Plan Rows": 900, "Filter": "(status = 'paid')"},
                {"Node Type": "Hash", "Total Cost": 5.0, "Plans": [{"Node Type": "Index Scan", "Relation Name": "customers", "Index Cond": "(city = 'Quito')"}]},
            ],
        }
    }
]  # fmt: skip

MYSQL_PLAN = {
    "query_block": {
        "cost_info": {"query_cost": "1234.50"},
        "nested_loop": [
            {"table": {"table_name": "o", "access_type": "ALL", "rows_examined_per_scan": 12000, "attached_condition": "(o.status = 'paid')", "cost_info": {"prefix_cost": "1200.0"}}},
            {"table": {"table_name": "c", "access_type": "eq_ref", "rows_examined_per_scan": 1, "cost_info": {"prefix_cost": "1234.5"}}},
        ],
    }
}  # fmt: skip


def test_postgres_plan_is_flattened_with_costs_and_scans() -> None:
    steps, total, scanned = _pg_steps(PG_PLAN)
    assert total == 500.0 and scanned == ["orders"]
    assert [(s.depth, s.operation, s.table) for s in steps] == [
        (0, "Hash Join", None), (1, "Seq Scan", "orders"), (1, "Hash", None), (2, "Index Scan", "customers"),
    ]  # fmt: skip
    assert steps[1].detail == "(status = 'paid')"
    assert _pg_steps(None) == ([], None, [])


def test_mysql_plan_resolves_aliases_and_full_scans() -> None:
    steps, total, scanned = _mysql_steps(MYSQL_PLAN, {"o": "orders", "c": "customers"})
    assert total == 1234.5 and scanned == ["orders"]
    assert steps[0].operation == "ALL access" and steps[0].rows == 12000
    assert steps[1].table == "customers"


def test_sqlite_plan_tree() -> None:
    rows = [
        [2, 0, 0, "SCAN o"],
        [5, 0, 0, "SEARCH c USING INTEGER PRIMARY KEY (rowid=?)"],
        [9, 0, 0, "USE TEMP B-TREE FOR GROUP BY"],
        [11, 2, 0, "SCAN TABLE orders USING COVERING INDEX idx"],
    ]
    steps, total, scanned = _sqlite_steps(rows, {"o": "orders", "c": "customers"})
    assert total is None and scanned == ["orders"]
    assert [(s.depth, s.operation, s.table) for s in steps] == [
        (0, "SCAN", "orders"), (0, "SEARCH", "customers"), (0, "USE", None), (1, "SCAN", "orders"),
    ]  # fmt: skip


def test_usage_and_candidates_skip_indexed_and_small_tables() -> None:
    sql = (
        "SELECT c.city, COUNT(*) FROM shop.orders o JOIN shop.customers c ON c.customer_id = o.customer_id "
        "WHERE o.status = 'paid' AND o.created_at BETWEEN '2026-01-01' AND '2026-02-01' AND city IN ('Quito') "
        "GROUP BY c.city"
    )
    usage = column_usage(sql, "mysql", CATALOG)
    assert usage.filters == {"orders": {"status", "created_at"}, "customers": {"city"}}
    assert usage.joins == {"customers": {"customer_id"}, "orders": {"customer_id"}}
    candidates = _candidates(
        ["orders", "customers"],
        usage,
        indexes={("orders", "customer_id"), ("orders", "order_id")},
        rows={"orders": 12_000, "customers": 50},
        catalog=CATALOG,
    )
    assert candidates == [("orders", "created_at", "filter"), ("orders", "status", "filter")]


def test_ddl_per_engine_and_improvement() -> None:
    assert (
        index_ddl("postgresql", "retail", "ventas", ("canal",))
        == 'CREATE INDEX ON "retail"."ventas" ("canal")'
    )
    assert index_ddl("mysql", "shop", "orders", ("status",)) == (
        "CREATE INDEX `orders_status_idx` ON `shop`.`orders` (`status`)"
    )
    assert (
        index_ddl("sqlite", "main", "t", ("a", "b")) == 'CREATE INDEX "t_a_b_idx" ON "t" ("a", "b")'
    )
    assert IndexSuggestion("t", ("a",), "", "filter", 200.0, 50.0).improvement == 0.75
    assert IndexSuggestion("t", ("a",), "", "filter").improvement is None
