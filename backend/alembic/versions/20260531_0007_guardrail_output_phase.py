"""Add guardrail rule and event phase.

Revision ID: 20260531_0007
Revises: 20260531_0006
Create Date: 2026-05-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260531_0007"
down_revision: str | None = "20260531_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _add_column_if_missing(
        "guardrail_rules",
        "phase",
        sa.Column("phase", sa.String(length=50), nullable=False, server_default="both"),
    )
    _add_column_if_missing(
        "guardrail_events",
        "phase",
        sa.Column("phase", sa.String(length=50), nullable=False, server_default="request"),
    )


def downgrade() -> None:
    _drop_column_if_present("guardrail_events", "phase")
    _drop_column_if_present("guardrail_rules", "phase")


def _add_column_if_missing(table_name: str, column_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns(table_name)}
    if column_name in columns:
        return
    op.add_column(table_name, column)
    op.create_index(f"ix_{table_name}_{column_name}", table_name, [column_name], unique=False)


def _drop_column_if_present(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns(table_name)}
    if column_name not in columns:
        return
    op.drop_index(f"ix_{table_name}_{column_name}", table_name=table_name)
    op.drop_column(table_name, column_name)
