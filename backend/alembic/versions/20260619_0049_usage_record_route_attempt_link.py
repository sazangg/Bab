"""Link usage records to gateway route attempts.

Revision ID: 20260619_0049
Revises: 20260618_0048
Create Date: 2026-06-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "20260619_0049"
down_revision: str | None = "20260618_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("usage_records", "route_attempt_id"):
        with op.batch_alter_table("usage_records") as batch_op:
            batch_op.add_column(sa.Column("route_attempt_id", sa.Uuid(), nullable=True))
            batch_op.create_foreign_key(
                "fk_usage_records_route_attempt_id_gateway_route_attempts",
                "gateway_route_attempts",
                ["route_attempt_id"],
                ["id"],
                ondelete="RESTRICT",
            )
    if not _has_index("usage_records", "ix_usage_records_route_attempt_id"):
        op.create_index("ix_usage_records_route_attempt_id", "usage_records", ["route_attempt_id"])


def downgrade() -> None:
    if _has_index("usage_records", "ix_usage_records_route_attempt_id"):
        op.drop_index("ix_usage_records_route_attempt_id", table_name="usage_records")
    if _has_column("usage_records", "route_attempt_id"):
        with op.batch_alter_table("usage_records") as batch_op:
            if _has_foreign_key(
                "usage_records",
                "fk_usage_records_route_attempt_id_gateway_route_attempts",
            ):
                batch_op.drop_constraint(
                    "fk_usage_records_route_attempt_id_gateway_route_attempts",
                    type_="foreignkey",
                )
            batch_op.drop_column("route_attempt_id")


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name for column in inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name for index in inspect(op.get_bind()).get_indexes(table_name)
    )


def _has_foreign_key(table_name: str, constraint_name: str) -> bool:
    return any(
        foreign_key["name"] == constraint_name
        for foreign_key in inspect(op.get_bind()).get_foreign_keys(table_name)
    )
