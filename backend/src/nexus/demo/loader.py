"""Load a generated :class:`Dataset` into PostgreSQL with ``COPY``, idempotently."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
import structlog
from psycopg import sql

from nexus.demo import DATASET_VERSION
from nexus.demo.generator import Dataset

logger = structlog.get_logger("nexus.demo.loader")

SCHEMA = "retail"
META_SCHEMA = "retail_meta"

_META_DDL = f"""
CREATE SCHEMA IF NOT EXISTS {META_SCHEMA};
CREATE TABLE IF NOT EXISTS {META_SCHEMA}.dataset (
    id          integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version     text NOT NULL,
    seed        bigint NOT NULL,
    scale       double precision NOT NULL,
    checksum    text NOT NULL,
    row_counts  jsonb NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True, slots=True)
class LoadResult:
    loaded: bool
    checksum: str
    row_counts: dict[str, int]
    seconds: float


def current_checksum(conn: psycopg.Connection) -> str | None:
    row = conn.execute(
        sql.SQL("SELECT checksum FROM {}.dataset WHERE version = %s").format(
            sql.Identifier(META_SCHEMA)
        ),
        (DATASET_VERSION,),
    ).fetchone()
    return None if row is None else str(row[0])


def load_dataset(
    dataset: Dataset, conninfo: str, sql_dir: Path, *, force: bool = False
) -> LoadResult:
    """Replace the retail data with ``dataset`` unless that version and checksum are loaded."""
    started = time.perf_counter()
    checksum = dataset.checksum()
    counts = dataset.row_counts()
    schema_sql = (sql_dir / "schema.sql").read_text(encoding="utf-8")
    constraints_sql = (sql_dir / "constraints.sql").read_text(encoding="utf-8")

    with psycopg.connect(conninfo) as conn:
        conn.execute(_META_DDL)
        if not force and current_checksum(conn) == checksum:
            conn.commit()
            logger.info("seed.skipped", reason="already loaded", checksum=checksum)
            return LoadResult(False, checksum, counts, time.perf_counter() - started)

        conn.execute(schema_sql)
        with conn.cursor() as cur:
            for table in dataset.tables:
                statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
                    sql.Identifier(SCHEMA),
                    sql.Identifier(table.name),
                    sql.SQL(", ").join(sql.Identifier(c) for c in table.column_names),
                )
                with cur.copy(statement) as copy:
                    for row in table.iter_rows():
                        copy.write_row(row)
                logger.info("seed.table_loaded", table=table.name, rows=len(table))
        conn.execute(constraints_sql)
        conn.execute(
            sql.SQL(
                "INSERT INTO {}.dataset "
                "(id, version, seed, scale, checksum, row_counts, loaded_at) "
                "VALUES (1, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version, seed = EXCLUDED.seed, "
                "scale = EXCLUDED.scale, checksum = EXCLUDED.checksum, "
                "row_counts = EXCLUDED.row_counts, loaded_at = now()"
            ).format(sql.Identifier(META_SCHEMA)),
            (
                DATASET_VERSION,
                dataset.config.seed,
                dataset.config.scale,
                checksum,
                json.dumps(counts),
            ),
        )
        conn.commit()

    seconds = time.perf_counter() - started
    logger.info("seed.loaded", checksum=checksum, rows=counts, seconds=round(seconds, 1))
    return LoadResult(True, checksum, counts, seconds)
