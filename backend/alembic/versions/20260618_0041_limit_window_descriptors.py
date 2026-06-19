"""Add limit window descriptors to usage counters.

Revision ID: 20260618_0041
Revises: 20260618_0040
Create Date: 2026-06-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260618_0041"
down_revision: str | None = "20260618_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if _has_table("usage_records") and not _has_column("usage_records", "limit_window_descriptor"):
        with op.batch_alter_table("usage_records") as batch_op:
            batch_op.add_column(
                sa.Column("limit_window_descriptor", sa.String(length=150), nullable=True)
            )
        _create_index(
            "ix_usage_records_limit_window_descriptor",
            "usage_records",
            ["limit_window_descriptor"],
        )
    if _has_table("limit_policy_reservations") and not _has_column(
        "limit_policy_reservations", "window_descriptor"
    ):
        with op.batch_alter_table("limit_policy_reservations") as batch_op:
            batch_op.add_column(
                sa.Column("window_descriptor", sa.String(length=150), nullable=True)
            )
        _create_index(
            "ix_limit_policy_reservations_window_descriptor",
            "limit_policy_reservations",
            ["window_descriptor"],
        )


def downgrade() -> None:
    if _has_table("limit_policy_reservations"):
        if _has_index(
            "limit_policy_reservations",
            "ix_limit_policy_reservations_window_descriptor",
        ):
            op.drop_index(
                "ix_limit_policy_reservations_window_descriptor",
                table_name="limit_policy_reservations",
            )
        if _has_column("limit_policy_reservations", "window_descriptor"):
            with op.batch_alter_table("limit_policy_reservations") as batch_op:
                batch_op.drop_column("window_descriptor")
    if _has_table("usage_records"):
        if _has_index("usage_records", "ix_usage_records_limit_window_descriptor"):
            op.drop_index(
                "ix_usage_records_limit_window_descriptor",
                table_name="usage_records",
            )
        if _has_column("usage_records", "limit_window_descriptor"):
            with op.batch_alter_table("usage_records") as batch_op:
                batch_op.drop_column("limit_window_descriptor")


def _create_index(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


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
