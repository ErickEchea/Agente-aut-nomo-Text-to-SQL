"""benchmark runs

Revision ID: d29f69672965
Revises: adc942f4f943
Create Date: 2026-11-22 10:05:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d29f69672965"
down_revision: Union[str, Sequence[str], None] = "adc942f4f943"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "benchmark_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("config_name", sa.String(length=80), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subset", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dataset_version", sa.String(length=20), nullable=False),
        sa.Column("git_sha", sa.String(length=40), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_benchmark_runs_config_started",
        "benchmark_runs",
        ["config_name", "started_at"],
        unique=False,
    )
    op.create_table(
        "benchmark_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("item_id", sa.String(length=10), nullable=False),
        sa.Column("difficulty", sa.String(length=20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_id", name="uq_benchmark_result_item"),
    )
    op.create_index(
        op.f("ix_benchmark_results_run_id"), "benchmark_results", ["run_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_benchmark_results_run_id"), table_name="benchmark_results")
    op.drop_table("benchmark_results")
    op.drop_index("ix_benchmark_runs_config_started", table_name="benchmark_runs")
    op.drop_table("benchmark_runs")
