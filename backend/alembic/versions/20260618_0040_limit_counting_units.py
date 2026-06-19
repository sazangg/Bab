"""Add explicit limit counting units.

Revision ID: 20260618_0040
Revises: 20260618_0039
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0040"
down_revision: str | None = "20260618_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if _has_table("usage_records") and not _has_column("usage_records", "limit_counting_unit"):
        with op.batch_alter_table("usage_records") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "limit_counting_unit",
                    sa.String(length=50),
                    nullable=False,
                    server_default="logical_request",
                )
            )
    if _has_table("limit_policy_reservations") and not _has_column(
        "limit_policy_reservations", "counting_unit"
    ):
        with op.batch_alter_table("limit_policy_reservations") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "counting_unit",
                    sa.String(length=50),
                    nullable=False,
                    server_default="logical_request",
                )
            )


def downgrade() -> None:
    if _has_table("limit_policy_reservations") and _has_column(
        "limit_policy_reservations", "counting_unit"
    ):
        with op.batch_alter_table("limit_policy_reservations") as batch_op:
            batch_op.drop_column("counting_unit")
    if _has_table("usage_records") and _has_column("usage_records", "limit_counting_unit"):
        with op.batch_alter_table("usage_records") as batch_op:
            batch_op.drop_column("limit_counting_unit")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name)
    )
