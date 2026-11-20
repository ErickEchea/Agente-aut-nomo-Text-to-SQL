"""``nexus-seed-demo``: generate the retail demo dataset and load it into the demo database.

Connection settings come from the environment (``NEXUS_SEED_DB__HOST``, ``__PORT``, ``__NAME``,
``__USER``, ``__PASSWORD``) and must be the **owner** role, never the agent's read-only role.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.config import DatabaseSettings
from nexus.demo.generator import DEFAULT_SCALE, DEFAULT_SEED, GeneratorConfig, generate
from nexus.demo.loader import load_dataset
from nexus.observability.logging import configure_logging


class SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )

    seed_db: DatabaseSettings
    demo_seed: int = DEFAULT_SEED
    demo_scale: float = DEFAULT_SCALE
    demo_sql_dir: Path = Path("/app/data/retail")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus-seed-demo", description=__doc__)
    parser.add_argument("--seed", type=int, help="RNG seed (default: NEXUS_DEMO_SEED or 20241101)")
    parser.add_argument("--scale", type=float, help="data volume multiplier (default 1.0)")
    parser.add_argument(
        "--sql-dir", type=Path, help="directory with schema.sql and constraints.sql"
    )
    parser.add_argument(
        "--force", action="store_true", help="reload even if the same data is present"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="generate only; print row counts and checksum as JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("INFO", json=True)

    if args.dry_run:
        config = GeneratorConfig(
            seed=args.seed if args.seed is not None else DEFAULT_SEED,
            scale=args.scale if args.scale is not None else DEFAULT_SCALE,
        )
        dataset = generate(config)
        payload = {"checksum": dataset.checksum(), "row_counts": dataset.row_counts()}
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0

    settings = SeedSettings()  # seed_db comes from the environment
    config = GeneratorConfig(
        seed=args.seed if args.seed is not None else settings.demo_seed,
        scale=args.scale if args.scale is not None else settings.demo_scale,
    )
    result = load_dataset(
        generate(config),
        settings.seed_db.libpq_conninfo(),
        args.sql_dir or settings.demo_sql_dir,
        force=args.force,
    )
    sys.stdout.write(
        json.dumps(
            {"loaded": result.loaded, "checksum": result.checksum, "rows": result.row_counts}
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
