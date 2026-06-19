"""Add dimension facts to limit policy reservations.

Revision ID: 20260618_0038
Revises: 20260618_0037
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0038"
down_revision: str | None = "20260618_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_table("limit_policy_reservations"):
        return
    with op.batch_alter_table("limit_policy_reservations") as batch_op:
        if not _has_column("limit_policy_reservations", "counter_key"):
            batch_op.add_column(sa.Column("counter_key", sa.String(length=500), nullable=True))
        if not _has_column("limit_policy_reservations", "dimension_snapshot"):
            batch_op.add_column(
                sa.Column(
                    "dimension_snapshot",
                    sa.JSON(),
                    nullable=False,
                    server_default="{}",
                )
            )
    if not _has_index("limit_policy_reservations", "ix_limit_policy_reservations_counter_key"):
        op.create_index(
            "ix_limit_policy_reservations_counter_key",
            "limit_policy_reservations",
            ["counter_key"],
        )


def downgrade() -> None:
    if not _has_table("limit_policy_reservations"):
        return
    if _has_index("limit_policy_reservations", "ix_limit_policy_reservations_counter_key"):
        op.drop_index(
            "ix_limit_policy_reservations_counter_key",
            table_name="limit_policy_reservations",
        )
    with op.batch_alter_table("limit_policy_reservations") as batch_op:
        if _has_column("limit_policy_reservations", "dimension_snapshot"):
            batch_op.drop_column("dimension_snapshot")
        if _has_column("limit_policy_reservations", "counter_key"):
            batch_op.drop_column("counter_key")


def _has_table(table_name: str) -> bool:
    return inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )
