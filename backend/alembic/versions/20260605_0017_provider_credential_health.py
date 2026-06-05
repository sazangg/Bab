"""Add provider credential health timestamps and failure details.

Revision ID: 20260605_0017
Revises: 20260602_0016
Create Date: 2026-06-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260605_0017"
down_revision: str | Sequence[str] | None = "20260602_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    columns = _columns("provider_credentials")
    with op.batch_alter_table("provider_credentials") as batch:
        if "last_validation_at" not in columns:
            batch.add_column(sa.Column("last_validation_at", sa.DateTime(timezone=True)))
        if "last_failure_at" not in columns:
            batch.add_column(sa.Column("last_failure_at", sa.DateTime(timezone=True)))
        if "failure_reason" not in columns:
            batch.add_column(sa.Column("failure_reason", sa.String(length=100)))
        if "failure_message" not in columns:
            batch.add_column(sa.Column("failure_message", sa.String(length=1000)))


def downgrade() -> None:
    columns = _columns("provider_credentials")
    with op.batch_alter_table("provider_credentials") as batch:
        for column in (
            "failure_message",
            "failure_reason",
            "last_failure_at",
            "last_validation_at",
        ):
            if column in columns:
                batch.drop_column(column)
